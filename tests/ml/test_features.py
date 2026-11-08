import numpy as np
import pandas as pd
import pytest

from src.ml import features, labels
from src.ml.sun import clearsky_ghi

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


V1 = features.FEATURES[:14]


@pytest.fixture(scope="module")
def weather(station):
    """Hourly weather over the station's period: sunlight at a varying share of clear sky."""
    hours = pd.date_range(
        station["interval_start"].min().floor("h") - pd.Timedelta(hours=6),
        station["interval_start"].max().ceil("h"),
        freq="h",
        tz="UTC",
    )
    sky = clearsky_ghi(hours + pd.Timedelta(minutes=30))
    share = 0.3 + 0.6 * (np.arange(len(hours)) % 7) / 6
    return pd.DataFrame(
        {
            "time": hours,
            "ghi_wm2": sky * share,
            "t2m_c": 15 + (np.arange(len(hours)) % 24) / 2,
            "available_at": hours + pd.Timedelta(hours=1),
        }
    )


@pytest.fixture(scope="module")
def frame_w(station, weather):
    return features.build_frame(station, weather=weather)


def test_nineteen_features_and_weather_ones_are_nan_without_weather(frame):
    assert len(features.FEATURES) == 19 and len(V1) == 14
    for name in features.WEATHER_FEATURES:
        assert frame[name].isna().all(), name
    assert frame["clearsky_T"].notna().all() and frame["net_over_clearsky"].notna().any()


def test_weather_leaves_the_v1_features_unchanged(frame, frame_w):
    assert same(frame[V1], frame_w[V1])
    assert same(frame["clearsky_T"], frame_w["clearsky_T"])


def test_weather_features_use_the_newest_finished_hour(station, weather):
    t = pd.Timestamp("2011-03-05 02:30", tz="UTC")  # 13:30 in Sydney
    got = features.build(station, t, weather=weather)
    w = weather.set_index("time")
    newest = pd.Timestamp("2011-03-05 01:00", tz="UTC")  # hour 01:00-02:00, known at 02:00
    half = pd.Timedelta(minutes=30)
    assert got["t2m_now"] == pytest.approx(w.loc[newest, "t2m_c"])
    assert got["kt_now"] == pytest.approx(w.loc[newest, "ghi_wm2"] / clearsky_ghi(newest + half))
    lag = newest - pd.Timedelta(hours=1)
    assert got["kt_lag_1"] == pytest.approx(w.loc[lag, "ghi_wm2"] / clearsky_ghi(lag + half))
    sky_now = clearsky_ghi(t - STEP + STEP / 2)
    assert got["net_over_clearsky"] == pytest.approx(got["net_now"] / (sky_now / 1000))


def test_weather_from_after_the_decision_changes_nothing(station, weather, frame_w):
    rng = np.random.default_rng(2)
    for t in frame_w["decision_time"].sample(20, random_state=2):
        broken = weather.copy()
        future = broken["available_at"] > t
        broken.loc[future, ["ghi_wm2", "t2m_c"]] = rng.uniform(500, 900, (future.sum(), 2))
        expected = features.build(station, t, weather=weather)
        got = features.build(station, t, weather=broken)
        assert same([got[k] for k in features.FEATURES], [expected[k] for k in features.FEATURES])
        row = features.build_frame(station, weather=broken).set_index("decision_time").loc[t]
        assert same(row[features.FEATURES], [expected[k] for k in features.FEATURES])


def test_build_equals_build_frame_with_weather(station, weather, frame_w):
    for t in frame_w["decision_time"].sample(100, random_state=3):
        one = features.build(station, t, weather=weather)
        row = frame_w.set_index("decision_time").loc[t]
        assert same([one[k] for k in features.FEATURES], row[features.FEATURES])


def test_night_gives_zero_clear_sky_and_no_ratios(station, weather):
    t = pd.Timestamp("2011-03-05 13:00", tz="UTC")  # target 14:00 UTC: 01:00 in Sydney
    got = features.build(station, t, weather=weather)
    assert got["clearsky_T"] == 0.0
    assert np.isnan(got["kt_now"]) and np.isnan(got["kt_lag_1"])
    assert np.isnan(got["net_over_clearsky"])
    assert not np.isnan(got["t2m_now"])  # temperature is known at night too


def test_haurwitz_matches_hand_computed_values(monkeypatch):
    from src.ml import sun

    stamp = pd.Timestamp("2011-03-05 02:00", tz="UTC")
    for elevation, expected in ((90.0, 1098 * np.exp(-0.057)), (30.0, 549 * np.exp(-0.114))):
        monkeypatch.setattr(sun, "solar_elevation", lambda ts, lat, lon, e=elevation: e)
        assert sun.clearsky_ghi(stamp) == pytest.approx(expected)  # 1037.2 and 489.9 W/m^2
    monkeypatch.setattr(sun, "solar_elevation", lambda ts, lat, lon: np.array([-5.0, 0.0]))
    assert list(sun.clearsky_ghi(pd.DatetimeIndex([stamp, stamp]))) == [0.0, 0.0]


def test_usable_drops_columns_with_no_value(frame):
    assert features.usable(frame) == [
        f for f in features.FEATURES if f not in features.WEATHER_FEATURES
    ]
    with pytest.raises(ValueError, match="retrain"):
        features.check_known(["net_now", "cloud_ratio"], "model x")
