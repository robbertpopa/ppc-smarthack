"""S5: one definition of "the intervals we label and score".

Today there are two, and the stricter one silently wins:
- ML (``src/ml/split.py:37-40``): the sun is above the horizon at mid-interval.
- Grid labels (``src/grid/labels.py:37``): Sydney local hour in [6, 20) and station PV > 0.
``evaluate`` scores only intervals that have a label, so the evaluation domain is the
grid filter, not the one the ML docs describe. ``domain`` is the proposed single rule.
"""

import numpy as np
import pandas as pd

from src.ml.sun import solar_elevation

SYD = "Australia/Sydney"


def ml_domain(interval_start: pd.Series) -> np.ndarray:
    return solar_elevation(interval_start + pd.Timedelta(minutes=15)) > 0


def grid_domain(interval_start: pd.Series, pv_kw: pd.Series) -> np.ndarray:
    local = interval_start.dt.tz_convert(SYD)
    hour = (local.dt.hour + local.dt.minute / 60).to_numpy()
    return (hour >= 6) & (hour < 20) & (pv_kw.to_numpy() > 0)


def domain(interval_start: pd.Series, pv_kw: pd.Series) -> np.ndarray:
    """Label every interval where export is possible or the sun is up; one rule for both."""
    return ml_domain(interval_start) | (pv_kw.to_numpy() > 0)
