import pandas as pd
import pytest

from src.eval import imbalance_eval
from src.ml import features, forecast_pv_load, labels
from src.ml import predict as predict_module

SMALL = {"max_iter": 30, "learning_rate": 0.1, "max_leaf_nodes": 15, "min_samples_leaf": 40}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("imbalance")
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_DIR", str(root / "data"))
    mp.setenv("ARTIFACT_URI", str(root / "artifacts"))
    labels.main(["mock", "--scenario", "A"])
    predict_module.clear_cache()
    yield labels.load("A")
    mp.undo()
    predict_module.clear_cache()


def scored_like(table, rows=200):
    frame = features.build_frame(table).dropna(subset=features.FEATURES).iloc[1000 : 1000 + rows]
    return {"X": frame[features.FEATURES], "rows": frame[["pt_id", "target_start"]]}


def test_actual_and_baseline_exports(env):
    actual = imbalance_eval.actual_export_kw(env)
    assert (actual >= 0).all() and actual.index.is_unique
    baseline = imbalance_eval.baseline_export_kw(actual)
    probe = actual.index[100]
    assert baseline.loc[probe] == actual.loc[probe - pd.Timedelta(hours=24)]


def test_without_a_trained_model_the_result_is_none(env):
    ctx, result = {"labels": env}, {"scored": scored_like(env)}
    assert imbalance_eval.station_savings(ctx, result) is None


def test_with_a_trained_model_every_spread_has_a_saving(env):
    forecast_pv_load.train("A", horizons=(60,), params=SMALL)
    ctx, result = {"labels": env}, {"scored": scored_like(env)}
    out = imbalance_eval.station_savings(ctx, result)
    assert out["horizon_min"] == 60 and [s["spread_eur_mwh"] for s in out["by_spread"]] == [
        30.0,
        60.0,
        120.0,
    ]
    first = out["by_spread"][0]
    assert first["n_intervals"] > 0 and first["baseline_mwh"] > 0 and first["model_mwh"] >= 0
    ratios = [s["saving_eur"] / s["spread_eur_mwh"] for s in out["by_spread"]]
    assert ratios[0] == pytest.approx(ratios[1]) == pytest.approx(ratios[2])
