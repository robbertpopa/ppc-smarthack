import time

import numpy as np
import pandas as pd
import pytest

from src.ml import explain as explain_module
from src.ml import features, labels, train
from src.ml import predict as predict_module
from src.ml.explain import explain as explain_function

FAST = [{"max_iter": 40, "learning_rate": 0.1, "max_leaf_nodes": 15, "min_samples_leaf": 40}]


def toy_rows(n, start, rng):
    """Decisions where only net_now decides the safe share."""
    X = pd.DataFrame(rng.normal(size=(n, len(features.FEATURES))), columns=features.FEATURES)
    X["target_start"] = pd.date_range(start, periods=n, freq="30min", tz="UTC")
    X["safe_share"] = 0.5 + 0.2 * np.tanh(X["net_now"].to_numpy())
    return X


@pytest.fixture(scope="module")
def toy():
    rng = np.random.default_rng(0)
    rows = toy_rows(1500, "2011-01-01", rng)
    val = toy_rows(600, "2012-04-02", rng)
    models = {
        q: train.fit_quantile(rows[features.FEATURES], rows["safe_share"], q, FAST[0], 0)
        for q in train.QUANTILES
    }
    return models, explain_module.build_artifacts(models, rows, val)


def feats(**overrides):
    base = {name: 0.0 for name in features.FEATURES}
    base.update(
        pt_id="PT-A",
        target_start=pd.Timestamp("2012-05-10 02:00", tz="UTC"),
        decision_time=pd.Timestamp("2012-05-10 01:00", tz="UTC"),
    )
    base.update(overrides)
    return base


def test_the_only_useful_feature_ranks_first_globally(toy):
    importance = toy[1]["importance"]
    assert importance["feature"].iloc[0] == "net_now"
    assert importance["importance"].iloc[0] > 5 * importance["importance"].iloc[1]


def test_the_only_useful_feature_ranks_first_locally(toy):
    out = explain_module.explain_with(*toy, feats(net_now=2.5))
    assert out["figures"][0]["name"] == "net_now"
    assert out["figures"][0]["effect"] > 0  # a high net load raises the cautious limit in the toy


def test_missing_features_are_reported_and_not_ablated(toy):
    out = explain_module.explain_with(*toy, feats(net_now=None, net_lag_1=float("nan")))
    assert {"net_now", "net_lag_1"} <= set(out["missing"])
    assert all(f["name"] not in out["missing"] for f in out["figures"])


def test_output_is_numbers_and_iso_times_only(toy):
    out = explain_module.explain_with(*toy, feats(net_now=1.0))
    assert len(out["figures"]) == 3 and len(out["similar"]) == 5
    for figure in out["figures"]:
        assert isinstance(figure["name"], str)
        assert isinstance(figure["value"], float) and isinstance(figure["effect"], float)
    for case in out["similar"]:
        assert pd.Timestamp(case["interval_start"]).tz is not None
        assert isinstance(case["safe_share"], float) and isinstance(case["in_sample"], bool)
        assert case["in_sample"] == (case["q05"] is None)  # q05 only for validation cases


def test_it_is_deterministic(toy):
    one = explain_module.explain_with(*toy, feats(net_now=1.0))
    assert one == explain_module.explain_with(*toy, feats(net_now=1.0))


def test_similar_cases_come_from_the_past_and_not_the_test_period(toy):
    decision = pd.Timestamp("2012-04-05 00:00", tz="UTC")
    out = explain_module.explain_with(*toy, feats(decision_time=decision, net_now=0.3))
    assert out["similar"]
    for case in out["similar"]:
        known_at = pd.Timestamp(case["interval_start"]) + pd.Timedelta(minutes=30)
        assert known_at <= decision < pd.Timestamp("2012-06-30 14:00", tz="UTC")
    early = explain_module.explain_with(
        *toy, feats(decision_time=pd.Timestamp("2010-01-01", tz="UTC"))
    )
    assert early["similar"] == []


def test_the_nearest_case_is_the_identical_one(toy):
    art = toy[1]
    row = art["index"].iloc[100]
    query = {name: float(row[name]) for name in features.FEATURES}
    out = explain_module.explain_with(
        toy[0],
        art,
        feats(**query, decision_time=row["target_start"] + pd.Timedelta(days=1)),
    )
    assert out["similar"][0]["interval_start"] == row["target_start"].strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp("explain")
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_DIR", str(root / "data"))
    mp.setenv("ARTIFACT_URI", str(root / "artifacts"))
    labels.main(["mock", "--scenario", "A"])
    train.train("A", grid=FAST)
    predict_module.clear_cache()
    yield labels.load("A")
    mp.undo()


def test_training_saves_the_explanation_data_and_explain_runs_fast(trained, capsys):
    from src.ml import model_io
    from src.ml.predict import model_version

    decision = pd.Timestamp("2012-05-10 00:00", tz="UTC")
    feats_ = features.build(trained, decision)
    assert explain_function(feats_)["figures"]
    start = time.perf_counter()
    for _ in range(10):
        out = explain_function(feats_)
    per_call = (time.perf_counter() - start) / 10 * 1000
    with capsys.disabled():
        print(f"\nexplain: {per_call:.1f} ms per call")
    assert per_call < 200
    assert out["figures"][0]["name"] in features.FEATURES
    table = explain_module.global_importance("PT-A")
    _, meta = model_io.load(model_version(), "PT-A")  # no weather here: 16 of the 19 features
    assert list(table.columns) == ["feature", "importance", "std"]
    assert sorted(table["feature"]) == sorted(meta["features"])


def test_explain_requires_identity(trained):
    with pytest.raises(ValueError, match="pt_id"):
        explain_function({"target_start": 1})


def test_labels_cover_every_feature():
    assert set(explain_module.LABELS) == set(features.FEATURES)


def test_explanation_data_from_an_older_version_asks_for_a_retrain(tmp_path, toy):
    art = dict(toy[1])
    art["index"] = art["index"].drop(columns="in_sample")  # as written before in_sample existed
    explain_module.save_artifacts(art, tmp_path)
    with pytest.raises(ValueError, match="older version: retrain"):
        explain_module.load_artifacts(tmp_path)
    explain_module.save_artifacts(toy[1], tmp_path)  # current data loads fine
    assert "in_sample" in explain_module.load_artifacts(tmp_path)["index"].columns


def test_the_offset_is_reported_as_its_own_factor(toy):
    plain = explain_module.explain_with(*toy, feats(net_now=1.0))
    assert plain["offset"] is None  # v1, or an offset that rounds to zero points
    lowered = explain_module.explain_with(*toy, feats(net_now=1.0), offset_c=0.043)
    assert lowered["offset"] == {"c": 0.043, "points": 4, "lowers": True}
    raised = explain_module.explain_with(*toy, feats(net_now=1.0), offset_c=-0.02)
    assert raised["offset"]["lowers"] is False and raised["offset"]["points"] == 2
    assert explain_module.explain_with(*toy, feats(net_now=1.0), offset_c=0.001)["offset"] is None
    assert lowered["figures"] == plain["figures"] and lowered["q05"] == plain["q05"]


def test_v2_explanations_carry_the_live_offset_or_the_saved_start_value(trained, monkeypatch):
    from src.ml import model_io

    train.train("A", grid=FAST, version=train.MODEL_VERSION_V2)
    monkeypatch.setenv("MODEL_VERSION", train.MODEL_VERSION_V2)
    predict_module.clear_cache()
    feats_ = features.build(trained, pd.Timestamp("2012-05-10 00:00", tz="UTC"))
    saved = model_io.load_metadata(train.MODEL_VERSION_V2, "PT-A")["offset"]["c_start"]
    assert explain_function(feats_)["offset"] == explain_module.offset_factor(saved)
    live = explain_function({**feats_, "offset_c": 0.1})["offset"]
    assert live == {"c": 0.1, "points": 10, "lowers": True}
    assert "offset" in explain_function(feats_) and explain_function(feats_)["figures"]
