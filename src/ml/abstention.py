"""When the model is not sure: the abstention threshold and the input checks.

Rule: ``spread = q90 - q05``. Where ``spread > tau`` the planner abstains, applies the
fixed 0.36 limit and the case goes to a person. Otherwise it applies ``q05``.

``tau`` is chosen on the **validation period only**: among all candidate thresholds,
the highest one whose violation rate is at most the target (so the fewest abstentions
that still meet the target). Every candidate is evaluated and the maximum taken; the
result does not depend on the scanning order or on monotonicity. (The first version of
this search ran the wrong way and flagged 43.5% of intervals.)

If no threshold meets the target, ``tau`` is ``-inf``: always abstain. That is reported,
never quietly relaxed.
"""

import json
import math

import numpy as np
import pandas as pd

from src.eval.metrics import EPS, FIXED_SHARE, evaluate
from src.ml import model_io

STALE_MINUTES = 60
NET_RANGE = 2.0  # |net| above 2 x kwp_total cannot be a real reading
NET_AGES_MIN = {"net_now": 0, "net_lag_1": 30, "net_lag_2": 60, "net_lag_3": 90}


def _policy(spread: pd.Series, q05: pd.Series, tau: float, flagged):
    abstain = spread > tau
    if flagged is not None:
        abstain = abstain | flagged.reindex(spread.index).fillna(False).astype(bool)
    applied = q05.where(~abstain, FIXED_SHARE)
    return applied, abstain


def _row(tau, applied, abstain, labels, surplus, kwp) -> dict:
    result = evaluate(applied, labels, surplus, kwp, abstain=abstain)
    return {
        "tau": tau,
        "violation_rate": result["violation_rate"],
        "abstain_rate": result["abstain_rate"],
        "per_day_mean": result["per_day_mean"],
        "per_day_max": result["per_day_max"],
        "export_index": result["export_index"],
        "n_intervals": result["n_intervals"],
    }


def candidates(spread: pd.Series) -> np.ndarray:
    """The distinct 0%, 1%, ..., 100% quantiles of the validation spreads."""
    return np.unique(np.quantile(spread.to_numpy(), np.linspace(0, 1, 101)))


def sweep(spread, q05, labels, surplus, kwp, flagged=None) -> pd.DataFrame:
    """Score every candidate ``tau`` once, plus ``-inf`` (always abstain).

    One row per ``tau`` with the numbers at that threshold: violation rate with the
    fallback, abstention rate, flagged cases per day, export index, ``coverage`` (share
    not sent to a person) and ``risk`` (violation rate of ``q05`` among those).
    ``choose_threshold`` and ``risk_coverage`` are views of this table.
    """
    safe = labels.set_index("interval_start")["safe_share"].reindex(spread.index)
    unsafe = q05 > safe + EPS
    reference, rows = None, []
    for tau in [-math.inf, *candidates(spread)]:
        applied, abstain = _policy(spread, q05, tau, flagged)
        result = evaluate(applied, labels, surplus, kwp, abstain=abstain, reference_kwh=reference)
        reference = result["reference_kwh"]
        kept = ~abstain
        rows.append(
            {
                "tau": float(tau),
                "violation_rate": result["violation_rate"],
                "abstain_rate": result["abstain_rate"],
                "per_day_mean": result["per_day_mean"],
                "per_day_max": result["per_day_max"],
                "export_index": result["export_index"],
                "n_intervals": result["n_intervals"],
                "coverage": float(kept.mean()),
                "risk": float(unsafe[kept].mean()) if kept.any() else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def pick(rows: pd.DataFrame, target: float) -> dict:
    """The row with the highest finite ``tau`` that meets ``target`` (else ``-inf``)."""
    finite = rows[np.isfinite(rows["tau"])]
    feasible = finite[finite["violation_rate"] <= target]
    if feasible.empty:
        chosen = rows[rows["tau"] == -math.inf].iloc[0]
        return {**chosen.to_dict(), "reachable": False, "target": target}
    chosen = feasible.loc[feasible["tau"].idxmax()]
    return {**chosen.to_dict(), "reachable": True, "target": target}


def choose_threshold(spread, q05, labels, surplus, kwp, target: float, flagged=None) -> dict:
    """Highest ``tau`` whose violation rate on ``labels`` is at most ``target``.

    ``spread`` and ``q05`` are indexed by interval start; ``labels`` are the validation
    rows. ``flagged`` marks intervals that abstain whatever the spread (input checks).
    Returns ``tau`` (``-inf`` if unreachable), ``reachable`` and the numbers at ``tau``.
    """
    return pick(sweep(spread, q05, labels, surplus, kwp, flagged), target)


def curve(rows: pd.DataFrame) -> pd.DataFrame:
    """Risk-coverage table from a ``sweep`` (the always-abstain row is left out)."""
    kept = rows[np.isfinite(rows["tau"])]
    return kept[["tau", "coverage", "risk", "violation_rate", "export_index"]].reset_index(
        drop=True
    )


def risk_coverage(spread, q05, labels, surplus, kwp, flagged=None) -> pd.DataFrame:
    """For every candidate ``tau``: coverage against the risk of what is not flagged."""
    return curve(sweep(spread, q05, labels, surplus, kwp, flagged))


def holdout_check(spread, q05, labels, surplus, kwp, target: float, flagged=None) -> dict:
    """Choose ``tau`` on the first half of the validation period, score it on the second.

    The final threshold is chosen on all of validation, so its reported violation rate sits
    at the target by construction. This shows how the same rule behaves on data it did not
    choose from; a large gap means the target will likely be exceeded in use.
    """
    cut = spread.index.sort_values()[len(spread) // 2]
    first = spread.index < cut
    in_first = labels["interval_start"] < cut

    def part(mask):
        return None if flagged is None else flagged[mask]

    chosen = pick(
        sweep(spread[first], q05[first], labels[in_first], surplus, kwp, part(first)), target
    )
    if not chosen["reachable"] or first.all() or not (~first).any():
        return {"tau_first_half": None, "violation_rate_second_half": None}
    applied, abstain = _policy(spread[~first], q05[~first], chosen["tau"], part(~first))
    second = evaluate(applied, labels[~in_first], surplus, kwp, abstain=abstain)
    return {
        "tau_first_half": chosen["tau"],
        "violation_rate_first_half": chosen["violation_rate"],
        "violation_rate_second_half": second["violation_rate"],
        "abstain_rate_second_half": second["abstain_rate"],
        "gap_to_target": second["violation_rate"] - target,
    }


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def quality_flags(features: dict) -> list[str]:
    """Reasons not to trust a prediction whatever its spread. Empty list means clean.

    ``missing_net_now`` / ``missing_share_last``: the newest readings are absent.
    ``stale_input``: the newest net reading is older than 60 minutes.
    ``out_of_range_net``: |net| above 2 x installed power (a broken meter).
    ``night``: the sun is below the horizon at the target time.
    """
    flags = []
    if _missing(features.get("net_now")):
        flags.append("missing_net_now")
    if _missing(features.get("share_last")):
        flags.append("missing_share_last")
    ages = [age for name, age in NET_AGES_MIN.items() if not _missing(features.get(name))]
    if not ages or min(ages) > STALE_MINUTES:
        flags.append("stale_input")
    nets = [features.get(n) for n in NET_AGES_MIN if not _missing(features.get(n))]
    if any(abs(v) > NET_RANGE for v in nets):
        flags.append("out_of_range_net")
    sun = features.get("sun_elev_T")
    if not _missing(sun) and sun <= 0:
        flags.append("night")
    return flags


def threshold(pt_id: str, version: str | None = None) -> float:
    """The spread threshold of a station, read from the model metadata.

    ``-inf`` means no threshold met the violation target: always abstain. The planner must
    not hard-code a threshold. The metadata is read once per training and cached, so this
    is cheap on the decision path and a retrained model is still noticed.
    """
    from src.ml.predict import model_version

    def loader(folder):
        return json.loads((folder / "metadata.json").read_text())

    folder = model_io.model_dir(version or model_version(), pt_id)
    if model_io.stamp(folder) is None:
        raise FileNotFoundError(f"no model at {folder} (expected {folder / 'metadata.json'})")
    meta = model_io.cached("metadata", folder, loader)
    info = meta.get("abstention")
    if not info:
        raise ValueError(f"model {pt_id} has no abstention threshold in its metadata")
    return -math.inf if not info["reachable"] else float(info["tau"])
