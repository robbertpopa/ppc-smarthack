import pytest

from src.agent.planner import make_plan
from src.common.contract import Forecast, GridState, StationConfig
from src.common.mock_data import load_mock


@pytest.fixture
def station():
    return load_mock("station", StationConfig)


@pytest.fixture
def forecast():
    return load_mock("forecast", Forecast)


@pytest.fixture
def grid_state():
    return load_mock("grid_state", GridState)


def with_share(forecast, **q):
    data = forecast.model_dump(mode="json")
    data["safe_cap_share"].update(q)
    data["spread"] = round(data["safe_cap_share"]["q90"] - data["safe_cap_share"]["q05"], 3)
    return Forecast.model_validate(data)


def test_confident_forecast_uses_cautious_quantile(station, forecast, grid_state):
    plan = make_plan(forecast, grid_state, station)
    assert plan.source == "model" and not plan.abstain
    assert plan.safe_cap_share_used == forecast.safe_cap_share.q05
    limits = {x.house_id: x.export_limit_kw for x in plan.limits}
    assert limits["H01"] == pytest.approx(0.52 * 5.0)
    assert plan.status == "proposed"


def test_contract_cap_is_a_ceiling(station, forecast, grid_state):
    plan = make_plan(forecast, grid_state, station)
    limits = {x.house_id: x.export_limit_kw for x in plan.limits}
    assert limits["H06"] == 9.0


def test_wide_spread_abstains_and_falls_back(station, forecast, grid_state):
    wide = with_share(forecast, q05=0.2, q10=0.25, q20=0.3, q50=0.4, q90=0.7)
    plan = make_plan(wide, grid_state, station)
    assert plan.abstain and plan.source == "fallback_static"
    assert plan.safe_cap_share_used == station.static_share
    assert any("above threshold" in r for r in plan.reasons)
    limits = {x.house_id: x.export_limit_kw for x in plan.limits}
    assert limits["H02"] == pytest.approx(0.36 * 8.0)


def test_missing_forecast_abstains(station, grid_state):
    when = grid_state.interval_start
    plan = make_plan(None, grid_state, station, interval_start=when)
    assert plan.abstain and plan.confidence == 0.0
    assert plan.safe_cap_share_used == station.static_share
    assert plan.reasons == ["no forecast available"]


def test_missing_forecast_needs_an_interval(station):
    with pytest.raises(ValueError):
        make_plan(None, None, station)


def test_non_converged_grid_abstains(station, forecast, grid_state):
    broken = grid_state.model_copy(update={"converged": False})
    plan = make_plan(forecast, broken, station)
    assert plan.abstain and "grid state did not converge" in plan.reasons


def test_forecast_from_the_future_abstains(station, forecast, grid_state):
    late = forecast.model_copy(update={"available_at": forecast.interval_start.replace(hour=11)})
    plan = make_plan(late, grid_state, station)
    assert plan.abstain


def test_confidence_is_half_at_the_threshold(station, forecast):
    edge = with_share(forecast, q05=0.40, q10=0.45, q20=0.5, q50=0.6, q90=0.70)
    plan = make_plan(edge, None, station)
    assert not plan.abstain and plan.confidence == pytest.approx(0.5)


def test_forecast_for_another_station_is_refused(station, forecast):
    other = forecast.model_copy(update={"pt_id": "PT-Z"})
    with pytest.raises(ValueError):
        make_plan(other, None, station)
