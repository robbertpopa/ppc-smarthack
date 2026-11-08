"""The one place where export and violations are computed.

Training, the abstention rule and the evaluation table all call these functions, so the
numbers agree everywhere. A policy applies a share of each house's installed kWp.

Accounting note (also printed under the final table): export is counted at the applied
limit even in an interval where the limit was unsafe. The violation rate is reported
next to it, so a policy cannot look good by exporting unsafely.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import mean_pinball_loss

from src.common.contract import StationConfig
from src.ml.config import SYDNEY, profiles_path
from src.ml.split import daylight

FIXED_SHARE = StationConfig.model_fields["static_share"].default  # the fixed limit to beat
EPS = 1e-6
STEP_HOURS = 0.5


def load_profiles(station_houses: pd.DataFrame, path=None) -> pd.DataFrame:
    """Read only the columns and source houses that ``surplus_kw`` needs.

    ``path`` defaults to ``profiles.parquet``; the dataset version passes the train file of
    ``src.ml.dataset``, which has the same columns and cleaning.
    """
    return pd.read_parquet(
        profiles_path() if path is None else path,
        columns=["interval_start", "house_id", "gc_kw", "cl_kw", "gg_kw"],
        filters=[("house_id", "in", station_houses["source_house_id"].unique().tolist())],
    )


def surplus_kw(profiles: pd.DataFrame, station_houses: pd.DataFrame) -> pd.DataFrame:
    """Power a house would export without a limit, per interval and simulated house.

    ``max(pv_scale * gg - load_scale * (gc + cl), 0)`` from the Ausgrid profiles, using the
    scales of ``station_houses``. A house without controlled load has ``cl = 0``; a missing
    generation or consumption reading stays NaN.
    """
    mapping = station_houses[["house_id", "source_house_id", "load_scale", "pv_scale"]]
    data = mapping.merge(
        profiles, left_on="source_house_id", right_on="house_id", suffixes=("", "_src")
    )
    load = data["load_scale"] * (data["gc_kw"] + data["cl_kw"].fillna(0))
    data["surplus"] = (data["pv_scale"] * data["gg_kw"] - load).clip(lower=0)
    wide = data.pivot(index="interval_start", columns="house_id", values="surplus")
    return wide.sort_index()


def export_by_interval(share: pd.Series, surplus: pd.DataFrame, kwp: pd.Series) -> pd.Series:
    """Exported energy (kWh) of a policy in each interval.

    ``sum over houses of min(surplus, share_T * kwp_h) * 0.5 h``. ``share`` is indexed by
    interval start. Intervals with a missing surplus or share add nothing; every policy is
    scored on the same intervals, so the comparison stays fair.
    """
    intervals = share.index.intersection(surplus.index)
    kwp = kwp.reindex(surplus.columns)
    if kwp.isna().any():
        raise ValueError(f"kwp is missing for houses {list(kwp.index[kwp.isna()])}")
    cap = share.loc[intervals].to_numpy()[:, None] * kwp.to_numpy()[None, :]
    exported = np.nansum(np.minimum(surplus.loc[intervals].to_numpy(), cap), axis=1)
    return pd.Series(exported * STEP_HOURS, index=intervals)


def exported_kwh(share: pd.Series, surplus: pd.DataFrame, kwp: pd.Series) -> float:
    """Total of ``export_by_interval`` (one body, one place for the checks)."""
    return float(export_by_interval(share, surplus, kwp).sum())


def evaluate(
    share: pd.Series,
    labels: pd.DataFrame,
    surplus: pd.DataFrame | None,
    kwp: pd.Series | None,
    abstain: pd.Series | None = None,
    reference_kwh: float | None = None,
) -> dict:
    """Score a policy of one station on its daylight intervals with a known safe share.

    ``share`` is the share actually applied (fallback already substituted where the policy
    abstained), indexed by ``interval_start``. ``abstain`` is a boolean series with the same
    index, used only for the abstention numbers. Intervals with a null ``safe_share`` are
    left out and counted in ``n_null_label``. Without ``surplus`` the export numbers are NaN
    and only the violation and abstention numbers are filled. ``reference_kwh`` is the
    export of the fixed limit on the same intervals; pass it back from an earlier call on the
    same rows to avoid recomputing it.
    """
    lab = labels.set_index("interval_start")
    if not lab.index.is_unique:
        raise ValueError("evaluate expects one station: interval_start must be unique")
    day = daylight(labels)
    known = lab["safe_share"].notna().to_numpy()
    scored = lab.index[day & known]
    applied = share.reindex(scored)
    if applied.isna().any():
        raise ValueError(
            f"the policy has no share for {int(applied.isna().sum())} scored intervals"
        )
    safe = lab.loc[scored, "safe_share"]

    if surplus is None:
        exported = reference = float("nan")
    else:
        exported = exported_kwh(applied, surplus, kwp)
        reference = reference_kwh
        if reference is None:
            reference = exported_kwh(pd.Series(FIXED_SHARE, index=scored), surplus, kwp)
    violations = int((applied > safe + EPS).sum())
    result = {
        "n_intervals": len(scored),
        "n_null_label": int((day & ~known).sum()),
        "exported_kwh": exported,
        "reference_kwh": reference,
        "export_index": 100 * exported / reference if reference > 0 else float("nan"),
        "violation_rate": violations / len(scored) if len(scored) else float("nan"),
        "n_violations": violations,
        "abstain_rate": float("nan"),
        "per_day_mean": float("nan"),
        "per_day_max": float("nan"),
    }
    if abstain is not None:
        flagged = abstain.reindex(scored).fillna(False).astype(bool)
        per_day = flagged.groupby(scored.tz_convert(SYDNEY).date).sum()
        result["abstain_rate"] = float(flagged.mean()) if len(scored) else float("nan")
        result["per_day_mean"] = float(per_day.mean()) if len(per_day) else float("nan")
        result["per_day_max"] = float(per_day.max()) if len(per_day) else float("nan")
    return result


def skill_score(y, q05, reference, alpha: float = 0.05) -> float:
    """``1 - pinball(q05) / pinball(reference)`` at level ``alpha``; positive beats the reference.

    ``reference`` is the last known safe share (persistence). Intervals where any of the
    three is missing are left out of both losses, so the two are scored on the same rows.
    """
    y, q05, reference = (np.asarray(v, dtype=float) for v in (y, q05, reference))
    keep = np.isfinite(y) & np.isfinite(q05) & np.isfinite(reference)
    if not keep.any():
        return float("nan")
    base = mean_pinball_loss(y[keep], reference[keep], alpha=alpha)
    if base <= 0:
        return float("nan")
    return float(1 - mean_pinball_loss(y[keep], q05[keep], alpha=alpha) / base)


def jain_index(x) -> float:
    """Jain's fairness index ``(sum x)^2 / (n * sum x^2)``: 1 when all equal, 1/n at worst."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0 or (x**2).sum() == 0:
        return float("nan")
    return float(x.sum() ** 2 / (len(x) * (x**2).sum()))


def fairness(share: pd.Series, labels: pd.DataFrame, surplus, kwp) -> float:
    """Jain index over houses of the part of their exportable energy a policy let through.

    For each house, ``sum min(surplus, share * kwp) / sum surplus`` over the scored daylight
    intervals; houses that never had a surplus are left out. 1 means every house was allowed
    the same share of what it could export. NaN without per-house surplus.
    """
    if surplus is None:
        return float("nan")
    lab = labels.set_index("interval_start")
    scored = lab.index[daylight(labels) & lab["safe_share"].notna().to_numpy()]
    scored = scored.intersection(surplus.index)
    applied = share.reindex(scored).to_numpy()[:, None]
    have = surplus.loc[scored]
    cap = applied * kwp.reindex(have.columns).to_numpy()[None, :]
    allowed = np.nansum(np.minimum(have.to_numpy(), cap), axis=0)
    available = np.nansum(have.to_numpy(), axis=0)
    some = available > 0
    return jain_index(allowed[some] / available[some])
