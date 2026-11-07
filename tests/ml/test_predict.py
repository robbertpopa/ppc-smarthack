import os
import time

import numpy as np
import pandas as pd
import pytest

from src.common.contract import Forecast
from src.ml import features, labels, model_io, train
from src.ml import predict as predict_module
from src.ml.predict import predict as predict_function

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


def test_the_module_is_not_hidden_by_the_function():
    assert hasattr(predict_module, "predict") and callable(predict_function)
    assert predict_module.predict is predict_function
    assert hasattr(predict_module, "clear_cache")  # still a module: it has module attributes


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
    assert per_call < 50


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


def test_features_for_another_horizon_are_refused(trained, decision):
    long = features.build(trained, decision, horizon_min=180)
    with pytest.raises(ValueError, match="horizon_min=60"):
        predict_function(long)


def test_a_retrained_model_is_picked_up_without_a_restart(trained, feats, monkeypatch):
    predict_module.clear_cache()
    loads = []
    real = model_io.load_dir
    monkeypatch.setattr(model_io, "load_dir", lambda path: loads.append(path) or real(path))
    predict_function(feats)
    predict_function(feats)
    assert len(loads) == 1  # cached
    meta = model_io.model_dir("safe-cap-qgb-v1", "PT-A") / "metadata.json"
    stat = meta.stat()
    os.utime(meta, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))  # as if retrained
    predict_function(feats)
    assert len(loads) == 2


def test_a_missing_model_is_remembered_and_found_when_it_appears(tmp_path, monkeypatch, feats):
    monkeypatch.setenv("ARTIFACT_URI", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        predict_function(feats)
    with pytest.raises(FileNotFoundError):  # second call answers from the cache
        predict_function(feats)
