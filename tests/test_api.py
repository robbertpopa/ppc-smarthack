from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.agent.api import create_app
from src.agent.guard import stub_guard
from src.agent.log import ActionLog
from src.agent.service import AgentService
from src.agent.sources import MockSource
from src.common.config import Settings
from src.common.contract import StationConfig
from src.common.mock_data import load_mock

NOON = "2025-06-21T10:00:00Z"
NIGHT = "2025-06-21T02:00:00Z"


def client(tmp_path, token=None, app_env="local"):
    service = AgentService(
        load_mock("station", StationConfig),
        ActionLog(tmp_path / "actions.jsonl"),
        stub_guard,
        MockSource(),
        clock=lambda: datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc),
    )
    settings = Settings(demo_token=token, app_env=app_env)
    return TestClient(create_app(settings, service))


def test_health(tmp_path):
    body = client(tmp_path).get("/health").json()
    assert body["status"] == "ok" and body["source"] == "mock"


def test_forecast_and_grid_state_come_from_the_mock_source(tmp_path):
    c = client(tmp_path)
    noon = c.get("/forecast", params={"interval_start": NOON}).json()
    night = c.get("/forecast", params={"interval_start": NIGHT}).json()
    assert noon["spread"] < 0.30 < night["spread"]
    assert c.get("/grid_state", params={"interval_start": NOON}).json()["converged"] is True


def test_full_flow_over_http(tmp_path):
    c = client(tmp_path)
    plan = c.post("/plan/propose", json={"interval_start": NOON}).json()
    pid = plan["plan_id"]
    assert plan["status"] == "proposed" and plan["abstain"] is False
    assert c.post(f"/plan/{pid}/approve", json={"actor": "op"}).json()["status"] == "approved"
    assert c.post(f"/plan/{pid}/execute", json={"actor": "op"}).json()["status"] == "executed"
    kinds = [e["event"] for e in c.get("/log").json()]
    assert kinds == ["plan_proposed", "plan_approved", "plan_executed"]
    assert c.get("/plans", params={"status": "executed"}).json()[0]["plan_id"] == pid


def test_unsure_case_shows_up_in_the_queue(tmp_path):
    c = client(tmp_path)
    c.post("/plan/propose", json={"interval_start": NIGHT})
    queue = c.get("/queue").json()
    assert len(queue["pending"]) == 1 and queue["remaining"] == 20


def test_errors_map_to_http_codes(tmp_path):
    c = client(tmp_path)
    assert c.get("/plan/PLAN-nope").status_code == 404
    plan = c.post("/plan/propose", json={"interval_start": NOON}).json()
    assert c.post(f"/plan/{plan['plan_id']}/execute", json={"actor": "op"}).status_code == 409


def test_kill_switch_over_http(tmp_path):
    c = client(tmp_path)
    pid = c.post("/plan/propose", json={"interval_start": NOON}).json()["plan_id"]
    c.post(f"/plan/{pid}/approve", json={"actor": "op"})
    out = c.post("/kill_switch", json={"on": True, "actor": "op"}).json()
    assert out["cancelled"] == [pid]
    assert c.get("/kill_switch").json() == {"on": True}
    assert c.post(f"/plan/{pid}/execute", json={"actor": "op"}).status_code == 409


@pytest.mark.parametrize(
    "path,body",
    [
        ("/plan/propose", {"interval_start": NOON}),
        ("/kill_switch", {"on": True, "actor": "op"}),
    ],
)
def test_writes_need_the_demo_token_when_set(tmp_path, path, body):
    c = client(tmp_path, token="secret")
    assert c.post(path, json=body).status_code == 403
    assert c.post(path, json=body, headers={"X-Demo-Token": "secret"}).status_code == 200
    assert c.get("/health").status_code == 200


def test_wrong_token_is_refused(tmp_path):
    c = client(tmp_path, token="secret")
    body = {"interval_start": NOON}
    assert c.post("/plan/propose", json=body, headers={"X-Demo-Token": "other"}).status_code == 403


def test_cloud_without_a_token_refuses_all_writes(tmp_path):
    c = client(tmp_path, app_env="cloud")
    assert c.post("/plan/propose", json={"interval_start": NOON}).status_code == 503
    assert c.post("/kill_switch", json={"on": True, "actor": "op"}).status_code == 503
    assert c.get("/health").status_code == 200


def test_local_without_a_token_allows_writes(tmp_path):
    c = client(tmp_path)
    assert c.post("/plan/propose", json={"interval_start": NOON}).status_code == 200
