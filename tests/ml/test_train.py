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
    first, _ = model_io.load(train.MODEL_VERSION, "PT-A")
    train.train("A", grid=FAST)
    second, _ = model_io.load(train.MODEL_VERSION, "PT-A")
    rows = train.training_rows(labels.load("A"))
    X = rows[train.features.FEATURES]
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
    assert meta["features"] == train.features.FEATURES
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
