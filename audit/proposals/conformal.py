"""M4: per-group conformal shift of ``q05`` so its coverage holds at every hour.

Fit on a calibration slice (validation, never test): for each group (local hour, or a bin
of solar elevation), ``shift = quantile_{1-alpha}(q05 - y)``; apply ``q05 - shift``. A group
with fewer than ``min_n`` rows uses the shift of all rows.
"""

import numpy as np
import pandas as pd


def fit_shift(q05, y, groups, alpha: float = 0.05, min_n: int = 30) -> dict:
    q05, y, groups = np.asarray(q05, float), np.asarray(y, float), np.asarray(groups)
    gap = q05 - y
    shifts = {"__all__": float(np.quantile(gap, 1 - alpha))}
    for g in np.unique(groups):
        sel = groups == g
        if sel.sum() >= min_n:
            shifts[g.item() if hasattr(g, "item") else g] = float(np.quantile(gap[sel], 1 - alpha))
    return shifts


def apply_shift(q05, groups, shifts: dict) -> np.ndarray:
    q05, groups = np.asarray(q05, float), np.asarray(groups)
    s = np.array(
        [shifts.get(g.item() if hasattr(g, "item") else g, shifts["__all__"]) for g in groups]
    )
    return np.clip(q05 - s, 0.0, 1.0)


def coverage_by_group(q05, y, groups) -> pd.Series:
    """Share of rows where the truth is below ``q05`` (the violations), per group."""
    return pd.Series(np.asarray(y) < np.asarray(q05)).groupby(np.asarray(groups)).mean()
