"""The one place where export and violations are computed.

Training, the abstention rule and the evaluation table all call these functions, so the
numbers agree everywhere. A policy applies a share of each house's installed kWp.

Accounting note (also printed under the final table): export is counted at the applied
limit even in an interval where the limit was unsafe. The violation rate is reported
next to it, so a policy cannot look good by exporting unsafely.
"""

import numpy as np
import pandas as pd

from src.ml.config import SYDNEY
from src.ml.split import daylight

FIXED_SHARE = 0.36  # the fixed limit every policy is compared with
EPS = 1e-6
STEP_HOURS = 0.5


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


def exported_kwh(share: pd.Series, surplus: pd.DataFrame, kwp: pd.Series) -> float:
    """``sum over T and houses of min(surplus, share_T * kwp_h) * 0.5 h``.

    ``share`` is indexed by interval start. Intervals with a missing surplus or share add
    nothing; every policy is scored on the same intervals, so the comparison stays fair.
    """
    intervals = share.index.intersection(surplus.index)
    cap = (
        share.loc[intervals].to_numpy()[:, None] * kwp.reindex(surplus.columns).to_numpy()[None, :]
    )
    exported = np.minimum(surplus.loc[intervals].to_numpy(), cap)
    return float(np.nansum(exported)) * STEP_HOURS


def evaluate(
    share: pd.Series,
    labels: pd.DataFrame,
    surplus: pd.DataFrame,
    kwp: pd.Series,
    abstain: pd.Series | None = None,
) -> dict:
    """Score a policy of one station on its daylight intervals with a known safe share.

    ``share`` is the share actually applied (fallback already substituted where the policy
    abstained), indexed by ``interval_start``. ``abstain`` is a boolean series with the same
    index, used only for the abstention numbers. Intervals with a null ``safe_share`` are
    left out and counted in ``n_null_label``.
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

    exported = exported_kwh(applied, surplus, kwp)
    reference = exported_kwh(pd.Series(FIXED_SHARE, index=scored), surplus, kwp)
    violations = int((applied > safe + EPS).sum())
    result = {
        "n_intervals": len(scored),
        "n_null_label": int((day & ~known).sum()),
        "exported_kwh": exported,
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
