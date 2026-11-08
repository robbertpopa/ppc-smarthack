import json

import numpy as np
import pandas as pd
import pytest

from src.ml import labels, model_io, train

FAST = [{"max_iter": 40, "learning_rate": 0.1, "max_leaf_nodes": 15, "min_samples_leaf": 40}]


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("ml")
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_DIR", str(root / "data"))
    mp.setenv("ARTIFACT_URI", str(root / "artifacts"))
    labels.main(["mock", "--scenario", "A"])
    yield root
    mp.undo()


@pytest.fixture(scope="module")
def report(env):
    return train.train("A", grid=FAST)


def test_rearrange_sorts_and_clips():
    out = train.rearrange(np.array([[0.5, 0.2, 1.4, 0.3, -0.2], [0.1, 0.2, 0.3, 0.4, 0.5]]))
    assert (np.diff(out, axis=1) >= 0).all()
    assert out.min() >= 0 and out.max() <= 1
    assert out.shape == (2, 5)


def test_same_seed_gives_identical_predictions(env, report):
    first, meta = model_io.load(train.MODEL_VERSION, "PT-A")
    train.train("A", grid=FAST)
    second, _ = model_io.load(train.MODEL_VERSION, "PT-A")
    rows = train.training_rows(labels.load("A"))
    X = rows[meta["features"]]
    assert np.array_equal(train.predict_quantiles(first, X), train.predict_quantiles(second, X))


def test_q05_beats_the_history_baselines_on_mock_labels(report):
    q05 = report["q05_policy"]["violation_rate"]
    base = report["baselines_val"]
    assert q05 < base["last_known"]["violation_rate"]
    assert q05 < base["same_hour_yesterday"]["violation_rate"]
    assert 0.0 < report["coverage_val"]["0.05"] < 0.2


def test_quantile_coverage_grows_with_the_quantile(report):
    cover = [report["coverage_val"][str(q)] for q in train.QUANTILES]
    assert cover == sorted(cover)


def test_metadata_has_every_field(env, report):
    _, meta = model_io.load(train.MODEL_VERSION, "PT-A")
    required = [
        "model_version", "pt_id", "git_sha", "labels_sha256", "train_period", "val_period",
        "features", "quantiles", "hyperparameters", "validation", "sklearn_version",
        "is_mock_labels",
    ]  # fmt: skip
    for key in required:
        assert key in meta, key
    assert meta["is_mock_labels"] is True
    # trained without weather: every feature but the three weather ones, in FEATURES order
    expected = [f for f in train.features.FEATURES if f not in train.features.WEATHER_FEATURES]
    assert meta["features"] == expected
    assert len(meta["labels_sha256"]) == 64
    json.dumps(meta)  # it is plain JSON


def test_test_period_is_never_read(env, report):
    _, meta = model_io.load(train.MODEL_VERSION, "PT-A")
    assert pd.Timestamp(meta["val_period"][1]) < pd.Timestamp("2012-06-30 14:00", tz="UTC")
    assert pd.Timestamp(meta["train_period"][1]) < pd.Timestamp("2012-03-31 13:00", tz="UTC")


def test_missing_model_names_the_expected_path(env):
    with pytest.raises(FileNotFoundError, match="no model at"):
        model_io.load("does-not-exist", "PT-A")


def test_unknown_labels_are_an_error(env):
    with pytest.raises(FileNotFoundError):
        train.train("B", grid=FAST)


def test_hyperparameter_search_has_at_most_four_settings():
    assert len(train.GRID) <= 4


V2 = train.MODEL_VERSION_V2
TWO = [FAST[0], {**FAST[0], "max_leaf_nodes": 7, "min_samples_leaf": 80}]


@pytest.fixture(scope="module")
def report_v2(env):
    return train.train("A", grid=TWO, version=V2)


def test_v1_is_still_the_default_version_and_loads(env, report):
    assert train.MODEL_VERSION == "safe-cap-qgb-v1"
    _, meta = model_io.load("safe-cap-qgb-v1", "PT-A")
    assert meta["model_version"] == "safe-cap-qgb-v1" and "folds" not in meta


def test_v2_reports_each_quarter(env, report_v2):
    _, meta = model_io.load(V2, "PT-A")
    assert meta["model_version"] == V2
    names = [fold["name"] for fold in meta["folds"]]
    assert names == list(train.FOLD_NAMES) and len(names) == 4
    for fold in meta["folds"]:
        assert fold["n_train"] > 0 and fold["n_val"] > 0
        assert set(fold["pinball"]) == {str(q) for q in train.QUANTILES}
        assert 0.0 <= fold["q05_coverage"] <= 1.0
        assert 0.0 <= fold["q05_violation_rate"] <= 1.0
    sizes = [fold["n_train"] for fold in meta["folds"]]
    assert sizes == sorted(sizes)  # each quarter has more history than the last


def test_v2_picks_the_setting_with_the_lowest_mean_pinball(env, report_v2):
    _, meta = model_io.load(V2, "PT-A")
    search = meta["hyperparameter_search"]
    assert len(search) == len(TWO)
    best = min(search, key=lambda item: item["mean_pinball_oos"])
    assert meta["hyperparameters"] == best["params"]


def test_v2_refits_on_the_whole_fit_period_and_never_reads_the_test_year(env, report_v2):
    _, meta = model_io.load(V2, "PT-A")
    assert pd.Timestamp(meta["train_period"][1]) < pd.Timestamp("2012-06-30 14:00", tz="UTC")
    assert pd.Timestamp(meta["val_period"][0]) >= pd.Timestamp("2011-06-30 14:00", tz="UTC")
    assert pd.Timestamp(meta["val_period"][1]) < pd.Timestamp("2012-06-30 14:00", tz="UTC")
    # the final models saw the last quarter too: more rows than the largest fold's history
    assert meta["validation"]["n_train"] > meta["folds"][-1]["n_train"]


def test_v2_saves_the_out_of_sample_predictions(env, report_v2):
    path = model_io.model_dir(V2, "PT-A") / "oos_predictions.parquet"
    oos = pd.read_parquet(path)
    assert {"target_start", "fold", "safe_share", "q05", "q10", "q20", "q50", "q90"} <= set(
        oos.columns
    )
    assert sorted(oos["fold"].unique()) == [0, 1, 2, 3]
    assert (oos[["q05", "q10", "q20", "q50", "q90"]].diff(axis=1).dropna(axis=1) >= 0).all().all()
    assert oos["target_start"].max() < pd.Timestamp("2012-06-30 14:00", tz="UTC")
    assert len(oos) == report_v2["n_val"]


def test_v2_same_seed_gives_byte_identical_metadata(env, report_v2):
    path = model_io.model_dir(V2, "PT-A") / "metadata.json"
    first = path.read_bytes()
    train.train("A", grid=TWO, version=V2)
    assert path.read_bytes() == first


def test_v2_leaves_the_v1_model_alone(env, report, report_v2):
    assert model_io.model_dir(V2, "PT-A") != model_io.model_dir(train.MODEL_VERSION, "PT-A")
    assert (model_io.model_dir(train.MODEL_VERSION, "PT-A") / "metadata.json").exists()


def test_unknown_version_is_an_error(env):
    with pytest.raises(ValueError, match="unknown model version"):
        train.train("A", grid=FAST, version="safe-cap-qgb-v9")


def test_v2_chooses_the_offset_step_on_the_out_of_sample_year(env, report_v2):
    from src.ml import online_calibration as oc

    _, meta = model_io.load(V2, "PT-A")
    offset = meta["offset"]
    assert offset["gamma"] in oc.GAMMAS
    assert offset["alpha"] == 0.02 and offset["reachable"] in (True, False)
    assert oc.C_MIN <= offset["c_start"] <= oc.C_MAX
    assert [row["gamma"] for row in offset["table"]] == list(oc.GAMMAS)
    assert offset["period"] == meta["val_period"]
    json.dumps(meta)
    assert "offset" not in model_io.load("safe-cap-qgb-v1", "PT-A")[1]


def test_v2_threshold_is_chosen_on_the_offset_limit(env, report_v2):
    # the report's limit economics are those of the offset limit, next to the raw q05
    assert report_v2["offset"]["gamma"] > 0
    assert (
        report_v2["abstention"]["violation_rate_with_fallback"]
        <= (report_v2["abstention"]["violation_target"] + 1e-9)
        or not report_v2["abstention"]["reachable"]
    )
