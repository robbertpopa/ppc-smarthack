import numpy as np
import pandas as pd

from src.ml.split import daylight, split
from src.ml.sun import solar_elevation


def frame(*local_times):
    """One row per Sydney wall-clock time, stored in UTC like the real files."""
    local = pd.DatetimeIndex(local_times).tz_localize("Australia/Sydney")
    return pd.DataFrame({"interval_start": local.tz_convert("UTC"), "v": range(len(local))})


def test_boundaries_follow_sydney_dates_not_utc_dates():
    df = frame(
        "2012-03-31 23:30",  # still 2012-03-31 in Sydney (12:30 UTC), train
        "2012-04-01 00:00",  # first val interval (13:00 UTC on 03-31)
        "2012-06-30 23:30",  # last val
        "2012-07-01 00:00",  # first test
        "2013-06-30 23:30",  # last test
        "2013-07-01 00:00",  # after the test year: in no set
    )
    parts = split(df)
    assert list(parts["train"]["v"]) == [0]
    assert list(parts["val"]["v"]) == [1, 2]
    assert list(parts["test"]["v"]) == [3, 4]


def test_sets_do_not_overlap_and_keep_order():
    index = pd.date_range("2010-07-01", "2013-07-02", freq="6h", tz="UTC")
    df = pd.DataFrame({"interval_start": index})
    parts = split(df)
    seen = [set(p.index) for p in parts.values()]
    assert not (seen[0] & seen[1]) and not (seen[0] & seen[2]) and not (seen[1] & seen[2])
    for p in parts.values():
        assert p["interval_start"].is_monotonic_increasing
    assert parts["train"]["interval_start"].max() < parts["val"]["interval_start"].min()
    assert parts["val"]["interval_start"].max() < parts["test"]["interval_start"].min()


def test_split_works_on_daylight_saving_change_days():
    # Sydney clocks go back on 2012-04-01 03:00: the day has 50 half hours
    index = pd.date_range("2012-03-31 13:00", periods=50, freq="30min", tz="UTC")
    parts = split(pd.DataFrame({"interval_start": index}))
    assert len(parts["train"]) == 0 and len(parts["val"]) == 50


def test_daylight_mask_follows_the_sun():
    df = frame("2012-06-21 03:00", "2012-06-21 12:00", "2012-12-21 06:00", "2012-12-21 21:00")
    assert list(daylight(df)) == [False, True, True, False]


def test_solar_noon_elevation_in_sydney():
    for start, expected in (("2012-12-20 18:00", 79.6), ("2012-06-20 18:00", 32.7)):
        day = pd.date_range(start, periods=24 * 12, freq="5min", tz="UTC")
        assert abs(solar_elevation(day).max() - expected) < 1.0


def test_solar_elevation_scalar_and_naive_input():
    assert isinstance(solar_elevation(pd.Timestamp("2012-12-21 02:00", tz="UTC")), float)
    try:
        solar_elevation(pd.DatetimeIndex(["2012-12-21 02:00"]))
    except ValueError as err:
        assert "timezone" in str(err)
    else:
        raise AssertionError("naive timestamps must be rejected")
    assert np.isfinite(solar_elevation(pd.DatetimeIndex(["2012-12-21 02:00"], tz="UTC"))).all()
