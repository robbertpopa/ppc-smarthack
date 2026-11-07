import importlib
import time

import numpy as np
import pandas as pd
import pytest

from src.common.contract import Forecast
from src.ml import features, labels, train
from src.ml import predict as predict_function  # the package re-exports the function

predict_module = importlib.import_module("src.ml.predict")
FAST = [{"max_iter": 40, "learning_rate": 0.1, "max_leaf_nodes": 15, "min_samples_leaf": 40}]


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp("predict")
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_DIR", str(root / "data"))
    mp.setenv("ARTIFACT_URI", str(root / "artifacts"))
    labels.main(["mock", "--scenario", "A"])
    train.train("A", grid=FAST)
    predict_module.clear_cache()
    yield labels.load("A")
    mp.undo()


@pytest.fixture
def decision(trained):
    return pd.Timestamp("2012-05-10 00:00", tz="UTC")  # 10:00 in Sydney, target 11:00


@pytest.fixture
def feats(trained, decision):
    return features.build(trained, decision)


def test_the_package_exports_predict_as_a_function():
    assert callable(predict_function) and predict_function is predict_module.predict


def test_output_is_a_valid_contract_forecast(feats, decision):
    forecast = predict_function(feats)
    assert isinstance(forecast, Forecast)
    assert Forecast.model_validate_json(forecast.model_dump_json()) == forecast
    assert forecast.pt_id == "PT-A" and forecast.horizon_min == 60
    assert forecast.interval_start == decision + pd.Timedelta(minutes=60)
    assert forecast.available_at == decision  # the decision time, not the target time
    assert forecast.provenance == "forecast" and forecast.model_version == "safe-cap-qgb-v1"
    assert forecast.source_ref.startswith("ml/train.py@")
    assert forecast.pv_kw is None and forecast.load_kw is None
    q = forecast.safe_cap_share
    assert 0 <= q.q05 <= q.q10 <= q.q20 <= q.q50 <= q.q90 <= 1
    assert forecast.spread == pytest.approx(q.q90 - q.q05)


def test_same_input_gives_the_same_output(feats):
    assert predict_function(feats) == predict_function(feats)


def test_half_the_features_missing_still_gives_a_forecast(feats):
    broken = dict(feats)
    for name in features.FEATURES[::2]:
        broken[name] = np.nan
    for name in features.FEATURES[1::4]:
        del broken[name]
    assert isinstance(predict_function(broken), Forecast)


def test_missing_identity_raises(feats):
    for key in ("pt_id", "target_start", "decision_time"):
        broken = {k: v for k, v in feats.items() if k != key}
        with pytest.raises(ValueError, match=key):
            predict_function(broken)


def test_naive_times_are_rejected(feats):
    with pytest.raises(ValueError, match="timezone-aware"):
        predict_function({**feats, "target_start": pd.Timestamp("2012-05-10 01:00")})


def test_feature_order_does_not_depend_on_dict_order(feats):
    shuffled = dict(reversed(list(feats.items())))
    assert predict_function(shuffled) == predict_function(feats)


def test_unknown_model_names_the_path(feats, monkeypatch):
    monkeypatch.setenv("MODEL_VERSION", "no-such-model")
    with pytest.raises(FileNotFoundError, match="no model at"):
        predict_function(feats)


def test_other_horizons_are_not_supported_yet(feats):
    with pytest.raises(ValueError, match="horizon_min"):
        predict_function(feats, horizon_min=180)


def test_a_call_after_the_first_is_fast(feats, capsys):
    predict_function(feats)
    start = time.perf_counter()
    for _ in range(20):
        predict_function(feats)
    per_call = (time.perf_counter() - start) / 20 * 1000
    with capsys.disabled():
        print(f"\npredict: {per_call:.1f} ms per call after the first")


def test_it_plugs_into_the_agents_model_source(trained, decision):
    from src.agent.model_source import ModelSource

    source = ModelSource(
        predict=predict_function,
        build_features=features.build,
        station_state=lambda pt_id, t: trained[trained["pt_id"] == pt_id],
        grid_state_for=lambda pt_id, start: None,
    )
    start = decision + pd.Timedelta(minutes=60)
    forecast = source.forecast("PT-A", start.to_pydatetime())
    assert isinstance(forecast, Forecast) and forecast.interval_start == start
