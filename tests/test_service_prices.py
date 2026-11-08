from datetime import datetime, timezone

from src.agent.guard import stub_guard
from src.agent.log import ActionLog
from src.agent.service import AgentService
from src.agent.sources import MockSource
from src.common.contract import StationConfig
from src.common.mock_data import load_mock
from src.pricing.source import mock_source

NOON = datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)


def service(tmp_path, prices):
    return AgentService(
        load_mock("station", StationConfig),
        ActionLog(tmp_path / "a.jsonl"),
        stub_guard,
        MockSource(),
        prices=prices,
    )


def test_propose_attaches_prices_from_the_source(tmp_path):
    plan = service(tmp_path, mock_source()).propose(NOON)
    first = plan.prices[0]
    assert len(plan.prices) == 8 and first.wholesale_eur_mwh == 15.0  # 13:00 Bucharest
    assert first.adder_eur_kwh > 0 and first.hourly_eur_kwh == 0.0  # 15 EUR/MWh < 30 fee


def test_without_a_source_the_plan_has_no_prices(tmp_path):
    assert service(tmp_path, None).propose(NOON).prices == []


def test_price_view_has_curve_and_houses(tmp_path):
    svc = service(tmp_path, mock_source())
    assert svc.price_view(NOON)["houses"] == []  # nothing proposed yet
    svc.propose(NOON)
    view = svc.price_view(NOON)
    assert view["mock"] is True and len(view["curve"]) == 24 and len(view["houses"]) == 8
