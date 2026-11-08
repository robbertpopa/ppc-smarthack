import numpy as np
import pandas as pd

from src.ml.split import FOLD_NAMES, daylight, folds, oos, split
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


def test_solar_elevation_accepts_datetime_and_numpy_scalars():
    from datetime import datetime, timezone

    stamp = pd.Timestamp("2012-12-21 02:00", tz="UTC")
    expected = solar_elevation(stamp)
    assert solar_elevation(datetime(2012, 12, 21, 2, tzinfo=timezone.utc)) == expected


def _six_hourly():
    index = pd.date_range("2010-07-01", "2013-07-02", freq="6h", tz="UTC")
    return pd.DataFrame({"interval_start": index})


def test_four_expanding_quarterly_folds_over_the_validation_year():
    df = _six_hourly()
    pairs = folds(df)
    assert len(pairs) == 4 == len(FOLD_NAMES)
    starts = []
    for fit, valid in pairs:
        local = valid["interval_start"].dt.tz_convert("Australia/Sydney")
        starts.append((local.min().date().isoformat(), local.max().date().isoformat()))
        # a quarter is predicted only by rows that end before it starts
        assert fit["interval_start"].max() < valid["interval_start"].min()
        assert fit["interval_start"].is_monotonic_increasing
    assert starts == [
        ("2011-07-01", "2011-09-30"),
        ("2011-10-01", "2011-12-31"),
        ("2012-01-01", "2012-03-31"),
        ("2012-04-01", "2012-06-30"),
    ]
    sizes = [len(fit) for fit, _ in pairs]
    assert sizes == sorted(sizes) and len(set(sizes)) == 4  # expanding


def test_folds_never_touch_the_test_year():
    df = _six_hourly()
    last_fit_day = pd.Timestamp("2012-06-30 14:00", tz="UTC")  # end of 2012-06-30 in Sydney
    for fit, valid in folds(df):
        assert fit["interval_start"].max() < last_fit_day
        assert valid["interval_start"].max() < last_fit_day
    assert split(df)["test"]["interval_start"].min() > last_fit_day


def test_fold_boundaries_follow_sydney_dates_not_utc_dates():
    df = frame(
        "2011-06-30 23:30",  # before the first quarter: only ever training
        "2011-07-01 00:00",  # first interval of the first quarter (14:00 UTC on 06-30)
        "2011-09-30 23:30",  # last of the first quarter
        "2011-10-01 00:00",  # first of the second quarter
        "2012-06-30 23:30",  # last of the last quarter
        "2012-07-01 00:00",  # test year: in no fold
    )
    pairs = folds(df)
    assert list(pairs[0][0]["v"]) == [0] and list(pairs[0][1]["v"]) == [1, 2]
    assert list(pairs[1][0]["v"]) == [0, 1, 2] and list(pairs[1][1]["v"]) == [3]
    assert list(pairs[3][1]["v"]) == [4]
    assert all(5 not in set(f["v"]) | set(v["v"]) for f, v in pairs)


def test_oos_is_the_union_of_the_validation_quarters():
    df = _six_hourly()
    union = pd.concat([valid for _, valid in folds(df)])
    assert list(oos(df).index) == list(union.index)
