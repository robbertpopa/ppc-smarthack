from datetime import datetime, timedelta, timezone

import pytest

from src.agent.guard import stub_guard
from src.agent.log import ActionLog
from src.agent.model_source import ModelSource
from src.agent.service import AgentService
from src.common.contract import Forecast, GridState, StationConfig
from src.common.mock_data import load_mock

NOON = datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)
DECISION = NOON - timedelta(minutes=60)


def good_forecast(**changes):
    base = load_mock("forecast", Forecast)
    return base.model_copy(
        update={"interval_start": NOON, "available_at": DECISION, **changes}
    )


def source(predict=lambda features: good_forecast(), grid=None, seen=None):
    seen = seen if seen is not None else {}

    def station_state(pt_id, t):
        seen["state_at"] = t
        return {"pt_id": pt_id}

    def build_features(state, t):
        seen["features_at"] = t
        return {"state": state, "t": t}

    grid = grid or (lambda pt_id, t: load_mock("grid_state", GridState))
    return ModelSource(predict, build_features, station_state, grid)


def test_features_are_built_at_the_decision_time_not_the_interval():
    seen = {}
    forecast = source(seen=seen).forecast("PT-A", NOON)
    assert forecast is not None
    assert seen["state_at"] == DECISION and seen["features_at"] == DECISION


def test_the_decision_time_is_the_same_instant_in_any_timezone():
    seen = {}
    plus_two = datetime.fromisoformat("2025-06-21T12:00:00+02:00")
    source(seen=seen).forecast("PT-A", plus_two)
    assert seen["features_at"] == DECISION


def test_a_dict_from_the_model_is_validated_into_a_forecast():
    forecast = source(lambda f: good_forecast().model_dump(mode="json")).forecast("PT-A", NOON)
    assert isinstance(forecast, Forecast)


@pytest.mark.parametrize(
    "predict",
    [
        lambda f: (_ for _ in ()).throw(RuntimeError("model file missing")),
        lambda f: {"pt_id": "PT-A"},
        lambda f: good_forecast(pt_id="PT-B"),
        lambda f: good_forecast(interval_start=NOON + timedelta(minutes=30)),
        lambda f: good_forecast(available_at=NOON),
    ],
)
def test_a_bad_forecast_becomes_no_forecast(predict):
    assert source(predict).forecast("PT-A", NOON) is None


def test_a_failure_in_the_data_before_the_model_becomes_no_forecast():
    def broken_state(pt_id, t):
        raise OSError("no data for this interval")

    model = ModelSource(
        lambda f: good_forecast(), lambda s, t: {}, broken_state, lambda pt_id, t: None
    )
    assert model.forecast("PT-A", NOON) is None


def test_a_missing_or_failed_grid_state_is_not_converged():
    assert source(grid=lambda pt_id, t: None).grid_state("PT-A", NOON).converged is False

    def boom(pt_id, t):
        raise RuntimeError("power flow crashed")

    assert source(grid=boom).grid_state("PT-A", NOON).converged is False
    assert source().grid_state("PT-A", NOON).converged is True


def service(model, tmp_path):
    return AgentService(
        load_mock("station", StationConfig),
        ActionLog(tmp_path / "actions.jsonl"),
        stub_guard,
        model,
        clock=lambda: NOON,
    )


def test_a_broken_model_makes_the_agent_abstain_instead_of_failing(tmp_path):
    def boom(features):
        raise RuntimeError("model file missing")

    plan = service(source(boom), tmp_path).propose(NOON)
    assert plan.abstain and plan.source == "fallback_static"
    assert "no forecast available" in plan.reasons


def test_a_failed_power_flow_makes_the_agent_abstain(tmp_path):
    plan = service(source(grid=lambda pt_id, t: None), tmp_path).propose(NOON)
    assert plan.abstain and "grid state did not converge" in plan.reasons


def test_a_working_model_gives_a_plan_from_its_cautious_quantile(tmp_path):
    plan = service(source(), tmp_path).propose(NOON)
    assert not plan.abstain and plan.source == "model"
    assert plan.safe_cap_share_used == good_forecast().safe_cap_share.q05
