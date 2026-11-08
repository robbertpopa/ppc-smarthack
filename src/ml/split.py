"""The fixed time splits and the daylight mask.

**v1:** train until 2012-03-31, validation 2012-04-01 to 2012-06-30, test 2012-07-01 to
2013-06-30 (``split``).

**v2:** fit on 2010-07-01 → 2012-06-30; choose the settings on four expanding quarterly
folds over 2011-07-01 → 2012-06-30 (``folds``), so the choice sees every season and not
three autumn months; the test year is unchanged and sealed.

The dates are **Sydney local dates**: splitting on UTC dates would move every boundary by
10 or 11 hours. Never shuffle, never split at random.
"""

import numpy as np
import pandas as pd

from src.ml.config import SYDNEY
from src.ml.sun import solar_elevation

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


FIT_END = pd.Timestamp("2012-06-30")
FOLD_STARTS = tuple(
    pd.Timestamp(d) for d in ("2011-07-01", "2011-10-01", "2012-01-01", "2012-04-01")
)
FOLD_NAMES = ("2011 Jul-Sep", "2011 Oct-Dec", "2012 Jan-Mar", "2012 Apr-Jun")


def folds(df: pd.DataFrame) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Four expanding quarterly folds over 2011-07-01 → 2012-06-30 (model v2).

    Returns ``(fit, valid)`` pairs, one per quarter in ``FOLD_NAMES``. ``valid`` is the
    quarter; ``fit`` is every row of an earlier Sydney date, so a quarter is predicted by
    models that never saw it or anything after it. The four quarters together are one year
    of out-of-sample predictions with every season. The test year is in no fold.
    ``split`` stays as it is for v1.
    """
    date = local_date(df["interval_start"])
    ends = (*FOLD_STARTS[1:], FIT_END + pd.Timedelta(days=1))
    return [
        (df[date < start], df[(date >= start) & (date < end)])
        for start, end in zip(FOLD_STARTS, ends, strict=True)
    ]


def fit_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Everything up to ``FIT_END``: what v2 is finally refitted on."""
    return df[local_date(df["interval_start"]) <= FIT_END]


def oos(df: pd.DataFrame) -> pd.DataFrame:
    """The rows of the four validation quarters, in time order."""
    return pd.concat([valid for _, valid in folds(df)])


def daylight(df: pd.DataFrame) -> np.ndarray:
    """Boolean mask: the sun is above the horizon at the middle of the interval."""
    middle = df["interval_start"] + pd.Timedelta(minutes=15)
    return solar_elevation(middle) > 0
