import numpy as np
import pandas as pd
import pytest

from src.ml import features, labels

STEP = pd.Timedelta(minutes=30)


@pytest.fixture(scope="module")
def station():
    mock = labels.make_mock(None, "A")
    start = pd.Timestamp("2011-03-01", tz="UTC")
    return mock[
        (mock["interval_start"] >= start) & (mock["interval_start"] < start + pd.Timedelta(days=40))
    ].reset_index(drop=True)


@pytest.fixture(scope="module")
def frame(station):
    return features.build_frame(station)


def same(a, b):
    return np.array_equal(np.asarray(a, dtype=float), np.asarray(b, dtype=float), equal_nan=True)


def tiny(values, shares=None, start="2012-01-02 00:00"):
    """A station with kwp_total 2 and the given net_kw per half hour."""
    n = len(values)
    index = pd.date_range(start, periods=n, freq="30min", tz="UTC")
    return pd.DataFrame(
        {
            "pt_id": "PT-A",
            "interval_start": index,
            "safe_share": shares if shares is not None else [0.5] * n,
            "net_kw": values,
            "kwp_total": 2.0,
            "available_at": index + STEP,
        }
    )


def test_features_match_a_hand_computed_case():
    df = tiny([2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0], shares=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
    row = features.build_frame(df).set_index("target_start").loc[df["interval_start"].iloc[6]]
    # target T is the 7th interval; decision t = T - 60 min; the last interval ends at t
    assert row["decision_time"] == df["interval_start"].iloc[4]
    assert row["net_now"] == 4.0  # the interval starting at T - 90 min is index 3: 8 / 2
    assert (row["net_lag_1"], row["net_lag_2"], row["net_lag_3"]) == (3.0, 2.0, 1.0)
    assert row["share_last"] == 0.4
    assert np.isnan(row["net_same_T_yesterday"]) and np.isnan(row["share_same_T_yesterday"])
    assert row["safe_share"] == 0.7


def test_same_time_yesterday_is_relative_to_the_target():
    index = pd.date_range("2012-01-01 00:00", periods=48 * 2, freq="30min", tz="UTC")
    df = tiny(np.arange(len(index)) * 2.0, shares=np.linspace(0, 1, len(index)), start=index[0])
    row = features.build_frame(df).set_index("target_start").loc[index[60]]
    assert row["net_same_T_yesterday"] == 12.0  # net_kw of index 12 is 24, divided by kwp 2
    assert row["share_same_T_yesterday"] == pytest.approx(12 / (len(index) - 1))


def test_calendar_features_use_sydney_local_time():
    # 2011-12-31 19:00 UTC is Sunday 2012-01-01 06:00 in Sydney (UTC+11)
    df = tiny([1.0] * 4, start="2011-12-31 18:00")
    row = (
        features.build_frame(df)
        .set_index("target_start")
        .loc[pd.Timestamp("2011-12-31 19:00", tz="UTC")]
    )
    assert row["is_weekend"] == 1.0
    assert row["hour_sin"] == pytest.approx(1.0) and row["hour_cos"] == pytest.approx(
        0.0, abs=1e-12
    )
    assert row["doy_sin"] == pytest.approx(np.sin(2 * np.pi / 365.25))


def test_future_perturbation_changes_nothing(station, frame):
    rng = np.random.default_rng(1)
    usable = frame.dropna(subset=["net_now", "share_last", "net_same_T_yesterday"])
    for t in usable["decision_time"].sample(20, random_state=1):
        broken = station.copy()
        future = broken["available_at"] > t
        broken.loc[future, ["net_kw", "safe_share"]] = rng.uniform(100, 200, (future.sum(), 2))
        expected = features.build(station, t)
        got = features.build(broken, t)
        assert same([got[k] for k in features.FEATURES], [expected[k] for k in features.FEATURES])
        row = features.build_frame(broken).set_index("decision_time").loc[t]
        assert same(row[features.FEATURES], list(expected[k] for k in features.FEATURES))


def test_build_equals_build_frame_for_200_random_times(station, frame):
    for t in frame["decision_time"].sample(200, random_state=0):
        one = features.build(station, t)
        row = frame.set_index("decision_time").loc[t]
        assert same([one[k] for k in features.FEATURES], row[features.FEATURES])
        assert one["target_start"] == row["target_start"] and one["pt_id"] == "PT-A"


def test_a_missing_interval_gives_nan_and_shifts_nothing(station, frame):
    gone = station[station["interval_start"].dt.hour == 2]["interval_start"].iloc[5]  # midday
    gap = features.build_frame(station[station["interval_start"] != gone])
    assert len(gap) == len(frame)
    both = frame.merge(gap, on="target_start", suffixes=("_full", "_gap"))
    for name in features.FEATURES:
        full, hole = both[f"{name}_full"], both[f"{name}_gap"]
        assert ((full == hole) | (full.isna() & hole.isna()) | hole.isna()).all(), name
    hit = both.set_index("target_start")
    assert not np.isnan(hit.loc[gone + 3 * STEP, "net_now_full"])
    assert np.isnan(hit.loc[gone + 3 * STEP, "net_now_gap"])
    assert not np.isnan(hit.loc[gone + 4 * STEP, "net_lag_1_full"])
    assert np.isnan(hit.loc[gone + 4 * STEP, "net_lag_1_gap"])
    assert not hit["net_now_gap"].eq(0).any()


def test_build_rejects_naive_time_and_several_stations(station):
    with pytest.raises(ValueError, match="timezone"):
        features.build(station, pd.Timestamp("2011-03-05 02:00"))
    with pytest.raises(ValueError, match="half-hour grid"):
        features.build(station, pd.Timestamp("2011-03-05 02:07", tz="UTC"))
    with pytest.raises(ValueError, match="half-hour grid"):
        features.build(station, pd.Timestamp("2011-03-05 02:00", tz="UTC"), horizon_min=45)
    two = pd.concat([station, station.assign(pt_id="PT-B")], ignore_index=True)
    with pytest.raises(ValueError, match="exactly one station"):
        features.build(two, pd.Timestamp("2011-03-05 02:00", tz="UTC"))


def test_features_are_the_single_source_of_column_order(frame):
    assert list(frame.columns) == [*features.KEYS, *features.FEATURES, "safe_share"]


def test_build_accepts_a_plain_datetime(station, frame):
    t = frame["decision_time"].iloc[500]
    plain, stamped = features.build(station, t.to_pydatetime()), features.build(station, t)
    assert same([plain[k] for k in features.FEATURES], [stamped[k] for k in features.FEATURES])
