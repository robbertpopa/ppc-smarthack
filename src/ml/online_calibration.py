"""The online offset: keep the violation rate at its target when the weather regime shifts.

The quantile models are fixed after training. The sky is not: a run of unusual days makes
``q05`` too high again and again. The offset ``c`` learns from those misses and lowers the
limit (or raises it again when there are none), in the manner of adaptive conformal
inference (Gibbs and Candes 2021) but tuned on the **violation rate** of the limit rather
than on quantile coverage (Pinson et al. 2026).

    limit_t = clip(q05_t - c_t, 0, 1)
    after each interval i whose label is known (available_at_i <= decision time)
    and where the model limit was applied (not abstained):
        miss_i = 1 if limit_i > safe_share_i + 1e-6 else 0
        c <- clip(c + gamma * (miss_i - alpha), C_MIN, C_MAX)

| Name    | Value                  | Reason                                                |
|---------|------------------------|-------------------------------------------------------|
| alpha   | ``VIOLATION_TARGET``   | the share of limits that may be too high              |
| gamma   | one of ``GAMMAS``      | step size: larger reacts faster but is noisier        |
| C_MAX   | 0.30                   | at most 30 points stricter than ``q05``               |
| C_MIN   | -0.05                  | at most 5 points looser: the model is never trusted   |
|         |                        | beyond its own ``q05`` by much                        |

``c`` rises by ``gamma * (1 - alpha)`` after a miss and falls by ``gamma * alpha`` after
each safe interval, so with a miss rate equal to ``alpha`` it stays where it is.

There is no hidden state and no randomness: ``Offset`` is three numbers and ``replay`` is a
pure function of its inputs. Intervals that abstained (fixed limit, a person decides) do not
update ``c``: the model limit was not applied, so it was not tested.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.eval.metrics import EPS, FIXED_SHARE, evaluate

GAMMAS = (0.001, 0.003, 0.01, 0.03)
C_MIN = -0.05
C_MAX = 0.30


@dataclass
class Offset:
    """The state of one station: the step size, the target and the current offset ``c``."""

    gamma: float
    alpha: float
    c: float = 0.0

    def apply(self, q05: float) -> float:
        """The limit to send: ``q05`` lowered by ``c``, kept inside [0, 1]."""
        return float(np.clip(q05 - self.c, 0.0, 1.0))

    def update(self, limit: float, safe_share: float) -> bool:
        """Learn from one finished interval; returns whether the limit was a miss.

        An unknown ``safe_share`` (the power flow did not converge) is not a miss and
        changes nothing: it is never read as 0.
        """
        if safe_share is None or np.isnan(safe_share):
            return False
        miss = bool(limit > safe_share + EPS)
        self.c = float(np.clip(self.c + self.gamma * (miss - self.alpha), C_MIN, C_MAX))
        return miss

    def to_dict(self) -> dict:
        return {"gamma": self.gamma, "alpha": self.alpha, "c": self.c}

    @classmethod
    def from_dict(cls, data: dict) -> "Offset":
        return cls(gamma=float(data["gamma"]), alpha=float(data["alpha"]), c=float(data["c"]))


@dataclass
class Replay:
    """``limit``: the offset limit per interval (before any abstention); ``c_before``: the
    offset used for it; ``c_final``: the offset after the last label."""

    limit: pd.Series
    c_before: pd.Series
    c_final: float


def replay(
    frame: pd.DataFrame, gamma: float, alpha: float, c0: float = 0.0, abstain: bool = True
) -> Replay:
    """Run the offset in time order over a table of predictions with known outcomes.

    ``frame`` is indexed by interval start and holds ``q05``, ``safe_share``,
    ``decision_time`` and ``available_at`` (the time the label is known), plus an optional
    boolean ``abstain``. Intervals are decided in order of ``decision_time``; before each
    decision the offset learns from every earlier interval whose ``available_at`` is not
    after that decision time, so no label is used before it exists. The order of the rows
    in ``frame`` does not matter.

    With ``abstain=False`` the ``abstain`` column is ignored and every interval teaches the
    offset (used when the threshold is not chosen yet).
    """
    if (frame["available_at"] <= frame["decision_time"]).any():
        raise ValueError("available_at must be after decision_time for every interval")
    order = np.argsort(frame["decision_time"].to_numpy(), kind="stable")
    by_known = np.argsort(frame["available_at"].to_numpy(), kind="stable")
    q05 = frame["q05"].to_numpy(dtype=float)
    safe = frame["safe_share"].to_numpy(dtype=float)
    decided = frame["decision_time"].to_numpy()
    known = frame["available_at"].to_numpy()
    skip = (
        frame["abstain"].to_numpy(dtype=bool)
        if abstain and "abstain" in frame
        else np.zeros(len(frame), dtype=bool)
    )

    offset = Offset(gamma, alpha, c0)
    limit = np.full(len(frame), np.nan)
    c_used = np.full(len(frame), np.nan)
    learned = 0
    for i in order:
        while learned < len(by_known) and known[by_known[learned]] <= decided[i]:
            j = by_known[learned]
            learned += 1
            # a label can only be learned from once its own decision was made
            if not np.isnan(limit[j]) and not skip[j]:
                offset.update(limit[j], safe[j])
        c_used[i] = offset.c
        limit[i] = offset.apply(q05[i])
    # labels that arrived after the last decision still count towards the final offset
    while learned < len(by_known):
        j = by_known[learned]
        learned += 1
        if not skip[j]:
            offset.update(limit[j], safe[j])
    return Replay(
        pd.Series(limit, index=frame.index, name="limit"),
        pd.Series(c_used, index=frame.index, name="c_before"),
        offset.c,
    )


def choose_gamma(
    frame: pd.DataFrame,
    labels: pd.DataFrame,
    surplus: pd.DataFrame | None,
    kwp: pd.Series | None,
    alpha: float,
    gammas: tuple[float, ...] = GAMMAS,
    c0: float = 0.0,
) -> dict:
    """Replay every ``gamma`` on the out-of-sample year and keep the best one.

    Best means the highest export index among the values whose violation rate is at most
    ``alpha``; ties go to the smaller ``gamma``. If none meets ``alpha`` the one with the
    lowest violation rate is kept (ties: smaller ``gamma``) and ``reachable`` is False:
    ``alpha`` is never relaxed here. Intervals marked ``abstain`` in ``frame`` get the fixed
    limit and do not teach the offset; ``labels`` (``interval_start``, ``safe_share``) and
    ``surplus``/``kwp`` are what ``src.eval.metrics.evaluate`` expects.

    Returns the chosen row (``gamma``, ``violation_rate``, ``export_index``, ``c_final``,
    ``reachable``, ``alpha``) and ``table`` with one row per ``gamma``.
    """
    rows, reference = [], None
    has_abstain = "abstain" in frame
    for gamma in gammas:
        run = replay(frame, gamma, alpha, c0)
        applied = run.limit
        flagged = frame["abstain"] if has_abstain else None
        if has_abstain:
            applied = applied.where(~frame["abstain"].astype(bool), FIXED_SHARE)
        result = evaluate(applied, labels, surplus, kwp, abstain=flagged, reference_kwh=reference)
        reference = result["reference_kwh"]
        rows.append(
            {
                "gamma": float(gamma),
                "violation_rate": result["violation_rate"],
                "export_index": result["export_index"],
                "n_intervals": result["n_intervals"],
                "c_final": run.c_final,
            }
        )
    table = pd.DataFrame(rows)
    feasible = table[table["violation_rate"] <= alpha]
    if feasible.empty:
        lowest = table["violation_rate"].min()
        best = table[table["violation_rate"] == lowest].sort_values("gamma").iloc[0]
    else:
        top = feasible["export_index"].max()
        best = feasible[feasible["export_index"] == top].sort_values("gamma").iloc[0]
    return {**best.to_dict(), "reachable": not feasible.empty, "alpha": alpha, "table": table}
