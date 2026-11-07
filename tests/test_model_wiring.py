import importlib
from datetime import datetime, timezone

import pytest

from src.agent.wiring import build_service
from src.common.config import Settings
from src.ml import forecast_pv_load, labels, train

predict_module = importlib.import_module("src.ml.predict")
FAST = [{"max_iter": 40, "learning_rate": 0.1, "max_leaf_nodes": 15, "min_samples_leaf": 40}]


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("wiring")
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_DIR", str(root / "data"))
    mp.setenv("ARTIFACT_URI", str(root / "artifacts"))
    labels.main(["mock", "--scenario", "A"])
    train.train("A", grid=FAST)
    forecast_pv_load.train("A", horizons=(60,), params=FAST[0])
    forecast_pv_load.clear_cache()
    predict_module.clear_cache()
    yield root
    mp.undo()


def test_model_source_runs_the_real_model_and_guard(env):
    service = build_service(Settings(source="model", scenario="A", log_uri=str(env / "a.jsonl")))
    moment = datetime(2012, 5, 10, 1, 0, tzinfo=timezone.utc)
    plan = service.propose(moment)
    assert plan.pt_id == "PT-A"
    assert plan.guard is not None and plan.guard.v_max_pu is not None
    assert "grid state did not converge" not in plan.reasons


def test_the_plan_carries_the_hotspot_and_grounded_factors(env):
    service = build_service(Settings(source="model", scenario="A", log_uri=str(env / "b.jsonl")))
    moment = datetime(2012, 5, 10, 1, 0, tzinfo=timezone.utc)
    state = service.source.grid_state("PT-A", moment)
    assert state.converged and 20 < state.trafo_hotspot_c < 200


def test_hotspot_rises_with_load():
    from src.agent.model_wiring import hotspot_c

    assert hotspot_c([0.2] * 10) < hotspot_c([0.2] * 5 + [1.4] * 5)
    assert hotspot_c([]) is None
