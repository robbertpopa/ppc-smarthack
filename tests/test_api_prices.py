from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.agent.api import create_app
from src.agent.guard import stub_guard
from src.agent.log import ActionLog
from src.agent.service import AgentService
from src.agent.sources import MockSource
from src.common.config import Settings
from src.common.contract import StationConfig
from src.common.mock_data import load_mock
from src.pricing.source import mock_source

NOON = "2025-06-21T10:00:00Z"


def client(tmp_path, prices=None):
    service = AgentService(
        load_mock("station", StationConfig),
        ActionLog(tmp_path / "a.jsonl"),
        stub_guard,
        MockSource(),
        clock=lambda: datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc),
        prices=prices,
    )
    return TestClient(create_app(Settings(), service))


def test_prices_before_and_after_a_plan(tmp_path):
    c = client(tmp_path, mock_source())
    before = c.get("/prices", params={"interval_start": NOON}).json()
    assert before["mock"] is True and len(before["curve"]) == 24 and before["houses"] == []
    c.post("/plan/propose", json={"interval_start": NOON})
    after = c.get("/prices", params={"interval_start": NOON}).json()
    first = after["houses"][0]
    assert len(after["houses"]) == 8 and first["total_eur_kwh"] >= first["hourly_eur_kwh"]


def test_prices_without_a_source_is_empty_not_an_error(tmp_path):
    body = client(tmp_path).get("/prices", params={"interval_start": NOON}).json()
    assert body["curve"] == [] and body["houses"] == [] and body["mock"] is False
