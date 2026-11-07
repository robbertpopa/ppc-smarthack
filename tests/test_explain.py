import pytest

from src.agent.explain import grounded
from src.agent.planner import make_plan
from src.common.contract import Explanation, Figure, Forecast, GridState, StationConfig
from src.common.mock_data import load_mock


@pytest.fixture
def parts():
    return (
        load_mock("forecast", Forecast),
        load_mock("grid_state", GridState),
        load_mock("station", StationConfig),
    )


def test_model_explanation_is_grounded(parts):
    forecast, grid_state, station = parts
    plan = make_plan(forecast, grid_state, station)
    assert grounded(plan.explanation)


def test_abstain_explanations_are_grounded(parts):
    forecast, grid_state, station = parts
    assert grounded(make_plan(None, grid_state, station, grid_state.interval_start).explanation)
    broken = grid_state.model_copy(update={"converged": False})
    assert grounded(make_plan(forecast, broken, station).explanation)
    wide = forecast.model_dump(mode="json")
    wide["safe_cap_share"].update(q05=0.1, q10=0.2, q20=0.3, q50=0.4, q90=0.7)
    wide["spread"] = 0.6
    assert grounded(make_plan(Forecast.model_validate(wide), grid_state, station).explanation)


def test_text_with_an_unlisted_number_is_rejected():
    exp = Explanation(
        text="The limit is 52% and voltage 1.09.", figures=[Figure(name="a", value=52)]
    )
    assert not grounded(exp)
