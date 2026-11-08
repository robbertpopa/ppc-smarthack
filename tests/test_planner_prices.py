from datetime import datetime, timezone

import pytest

from src.agent.planner import make_plan
from src.agent.sources import MockSource
from src.common.contract import StationConfig
from src.common.mock_data import load_mock
from src.pricing.config import PricingConfig

NOON = datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)


def plan_at(wholesale, adder=40.0, cfg=None):
    station = load_mock("station", StationConfig)
    source = MockSource()
    forecast = source.forecast(station.pt_id, NOON)
    grid = source.grid_state(station.pt_id, NOON)
    return make_plan(
        forecast, grid, station, NOON, wholesale_eur_mwh=wholesale, adder_eur_mwh=adder, pricing=cfg
    )


def test_no_wholesale_price_means_no_prices():
    assert plan_at(None).prices == []


def test_price_is_hourly_plus_adder_for_every_house():
    plan = plan_at(100.0, 40.0, PricingConfig(fee_eur_mwh=30.0))
    assert len(plan.prices) == 8 and {p.house_id for p in plan.prices} == {
        h.house_id for h in load_mock("station", StationConfig).houses
    }
    first = plan.prices[0]
    assert first.wholesale_eur_mwh == 100.0
    assert first.hourly_eur_kwh == pytest.approx(0.07)  # 100 - 30 EUR/MWh
    assert first.adder_eur_kwh == pytest.approx(0.04)
    assert first.total_eur_kwh == pytest.approx(0.11)
    assert not first.floor_applied and first.reason.startswith("hourly price")


def test_the_floor_applies_when_wholesale_minus_fee_is_below_it():
    plan = plan_at(20.0, 40.0, PricingConfig(fee_eur_mwh=30.0, floor_eur_mwh=5.0))
    first = plan.prices[0]
    assert first.floor_applied and first.hourly_eur_kwh == pytest.approx(0.005)
    assert first.total_eur_kwh == pytest.approx(0.045) and first.reason.startswith("floor")


def test_negative_wholesale_pays_the_floor_never_a_charge():
    plan = plan_at(-20.0, 0.0)
    assert all(p.hourly_eur_kwh == 0.0 and p.total_eur_kwh >= 0 for p in plan.prices)
