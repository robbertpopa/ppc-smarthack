"""The fixed time split and the daylight mask.

Train until 2012-03-31, validation 2012-04-01 to 2012-06-30, test 2012-07-01 to
2013-06-30. The dates are **Sydney local dates**: splitting on UTC dates would move
every boundary by 10 or 11 hours. Never shuffle, never split at random.
"""

import numpy as np
import pandas as pd

from .sun import solar_elevation

SYDNEY = "Australia/Sydney"
VAL_START = pd.Timestamp("2012-04-01")
TEST_START = pd.Timestamp("2012-07-01")
TEST_END = pd.Timestamp("2013-06-30")


def local_date(interval_start: pd.Series) -> pd.Series:
    """Sydney calendar date (tz-naive midnight) of each interval start."""
    return interval_start.dt.tz_convert(SYDNEY).dt.tz_localize(None).dt.normalize()


def split(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return ``train``, ``val`` and ``test`` by the Sydney date of ``interval_start``.

    Rows after the end of the test year belong to no set. The sets never overlap.
    """
    date = local_date(df["interval_start"])
    return {
        "train": df[date < VAL_START],
        "val": df[(date >= VAL_START) & (date < TEST_START)],
        "test": df[(date >= TEST_START) & (date <= TEST_END)],
    }


def daylight(df: pd.DataFrame) -> np.ndarray:
    """Boolean mask: the sun is above the horizon at the middle of the interval."""
    middle = df["interval_start"] + pd.Timedelta(minutes=15)
    return solar_elevation(middle) > 0
