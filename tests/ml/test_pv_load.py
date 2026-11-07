import pandas as pd
import pytest

from src.common.contract import Forecast
from src.ml import features, forecast_pv_load, labels, train
from src.ml import predict as predict_module
from src.ml.predict import predict as predict_function

SMALL = {"max_iter": 30, "learning_rate": 0.1, "max_leaf_nodes": 15, "min_samples_leaf": 40}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("pvload")
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_DIR", str(root / "data"))
    mp.setenv("ARTIFACT_URI", str(root / "artifacts"))
    labels.main(["mock", "--scenario", "A"])
    predict_module.clear_cache()
    yield labels.load("A")
    mp.undo()


@pytest.fixture(scope="module")
def report(env):
    return forecast_pv_load.train("A", horizons=(60, 180), params=SMALL)


def at(state, hours_utc=2, horizon=60):
    t = pd.Timestamp("2012-05-10", tz="UTC") + pd.Timedelta(hours=hours_utc)
    return features.build(state, t, horizon_min=horizon)


def test_report_compares_every_target_and_horizon_with_yesterday(report):
    assert set(report) == {"pv_kw_h60", "pv_kw_h180", "load_kw_h60", "load_kw_h180"}
    for row in report.values():
        assert row["pinball_model"] >= 0 and row["pinball_yesterday"] >= 0
        assert isinstance(row["beats_yesterday"], bool)
        assert 0 <= row["coverage_p10_p90_model"] <= 1
        assert "coverage_p10_p90_yesterday" not in row  # a single value has no band


def test_bands_are_ordered_and_scaled_to_the_station(env, report):
    out = forecast_pv_load.predict_pv_load(at(env, 1, 60), 60)
    for band in out.values():
        assert 0 <= band.p10 <= band.p50 <= band.p90
    kwp_total = float(env["kwp_total"].iloc[0])
    assert out["pv_kw"].p90 <= 1.5 * kwp_total  # kW of the station, not a share


def test_pv_is_zero_when_the_sun_is_down(env, report):
    feats = {**at(env, 1, 60), "sun_elev_T": -5.0}
    out = forecast_pv_load.predict_pv_load(feats, 60)
    assert (out["pv_kw"].p10, out["pv_kw"].p50, out["pv_kw"].p90) == (0.0, 0.0, 0.0)
    assert out["load_kw"] is None


def test_longer_horizon_uses_its_own_model(env, report):
    short = forecast_pv_load.predict_pv_load(at(env, 1, 60), 60)
    long = forecast_pv_load.predict_pv_load(at(env, 1, 180), 180)
    assert short["pv_kw"] != long["pv_kw"]


def test_unknown_horizon_is_rejected(env, report):
    with pytest.raises(ValueError, match="horizon_min must be one of"):
        forecast_pv_load.predict_pv_load(at(env, 1, 60), 360)


def test_safe_cap_forecast_carries_pv_and_load_once_the_models_exist(env, report):
    train.train("A", grid=[SMALL])
    predict_module.clear_cache()
    forecast = predict_function(at(env, 1, 60))
    assert isinstance(forecast, Forecast)
    assert forecast.pv_kw is not None and forecast.load_kw is not None
    assert Forecast.model_validate_json(forecast.model_dump_json()) == forecast


def test_feature_values_do_not_change_for_the_default_horizon(env):
    t = pd.Timestamp("2012-05-10 02:00", tz="UTC")
    default, explicit = features.build(env, t), features.build(env, t, horizon_min=60)
    assert default == explicit or all(
        (default[k] == explicit[k]) or (default[k] != default[k] and explicit[k] != explicit[k])
        for k in default
    )


def test_an_incomplete_model_folder_does_not_break_the_safe_cap(env, report, monkeypatch):
    from src.ml import model_io

    train.train("A", grid=[SMALL])
    predict_module.clear_cache()
    folder = model_io.model_dir(forecast_pv_load.MODEL_VERSION, "PT-A")
    (folder / "pv_h60_q10.joblib").rename(folder / "gone.joblib")
    try:
        with pytest.raises(ValueError, match="incomplete"):
            forecast_pv_load.predict_pv_load(at(env, 1, 60), 60)
        forecast = predict_function(at(env, 1, 60))  # logs, but still answers
        assert isinstance(forecast, Forecast) and forecast.pv_kw is None
    finally:
        (folder / "gone.joblib").rename(folder / "pv_h60_q10.joblib")
        predict_module.clear_cache()


def test_a_broken_pv_load_folder_is_logged_once_not_on_every_call(env, report, caplog):
    import logging

    from src.ml import model_io

    train.train("A", grid=[SMALL])
    predict_module.clear_cache()
    folder = model_io.model_dir(forecast_pv_load.MODEL_VERSION, "PT-A")
    (folder / "pv_h60_q10.joblib").rename(folder / "gone.joblib")
    try:
        with caplog.at_level(logging.WARNING, logger="src.ml.predict"):
            for _ in range(5):
                assert predict_function(at(env, 1, 60)).pv_kw is None
        warnings_logged = [r for r in caplog.records if "PV and load" in r.getMessage()]
        assert len(warnings_logged) == 1
    finally:
        (folder / "gone.joblib").rename(folder / "pv_h60_q10.joblib")
        predict_module.clear_cache()


def test_an_unexpected_bug_there_is_logged_with_its_traceback_and_still_answers(
    env, report, caplog, monkeypatch
):
    import logging

    train.train("A", grid=[SMALL])
    predict_module.clear_cache()

    def boom(feats, horizon):
        raise KeyError("kwp_total")  # e.g. an older folder without a field

    monkeypatch.setattr(forecast_pv_load, "predict_pv_load", boom)
    with caplog.at_level(logging.WARNING, logger="src.ml.predict"):
        forecast = predict_function(at(env, 1, 60))
    assert isinstance(forecast, Forecast) and forecast.pv_kw is None
    record = next(r for r in caplog.records if "PV and load" in r.getMessage())
    assert record.exc_info is not None  # a bug is not reduced to a one-line warning
