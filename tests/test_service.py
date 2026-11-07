from datetime import datetime, timezone

import pytest

from src.agent.guard import stub_guard
from src.agent.log import ActionLog, open_log
from src.agent.service import AgentService, ServiceError
from src.agent.sources import MockSource
from src.common.contract import GuardResult, StationConfig
from src.common.mock_data import load_mock

NOON = datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)
NIGHT = datetime(2025, 6, 21, 2, 0, tzinfo=timezone.utc)


def make_service(tmp_path, guard=stub_guard, station=None):
    station = station or load_mock("station", StationConfig)
    log = ActionLog(tmp_path / "actions.jsonl")
    return AgentService(station, log, guard, MockSource(), clock=lambda: NOON), log


def events(log):
    return [e.event for e in log.read()]


def test_confident_plan_goes_through_to_execution(tmp_path):
    service, log = make_service(tmp_path)
    plan = service.propose(NOON)
    assert not plan.abstain and plan.status == "proposed"
    assert service.approve(plan.plan_id, "op").status == "approved"
    assert service.execute(plan.plan_id, "op").status == "executed"
    assert events(log) == ["plan_proposed", "plan_approved", "plan_executed"]


def test_log_events_carry_the_plan_hash(tmp_path):
    service, log = make_service(tmp_path)
    plan = service.propose(NOON)
    first = log.read()[0]
    assert first.plan_id == plan.plan_id and len(first.plan_sha) == 16


def test_unsure_case_is_queued_and_logged(tmp_path):
    service, log = make_service(tmp_path)
    plan = service.propose(NIGHT)
    assert plan.abstain and plan.source == "fallback_static"
    assert events(log) == ["plan_proposed", "abstained"]
    assert [p.plan_id for p in service.queue()["pending"]] == [plan.plan_id]


def test_review_budget_is_counted(tmp_path):
    station = load_mock("station", StationConfig).model_copy(update={"review_budget": 1})
    service, log = make_service(tmp_path, station=station)
    first = service.propose(NIGHT)
    second = service.propose(NIGHT.replace(hour=3))
    service.approve(first.plan_id, "op")
    queue = service.queue()
    assert queue["reviewed_today"] == 1 and queue["remaining"] == 0
    service.reject(second.plan_id, "op")
    last = log.read()[-1]
    assert last.detail["over_budget"] is True


def test_guard_can_block_a_plan(tmp_path):
    def deny(plan, grid_state):
        return GuardResult(passed=False, violations=["v_max 1.12 pu above 1.10"])

    service, log = make_service(tmp_path, guard=deny)
    plan = service.propose(NOON)
    assert plan.status == "rejected" and plan.guard.violations
    assert events(log) == ["guard_blocked"]
    with pytest.raises(ServiceError) as err:
        service.approve(plan.plan_id, "op")
    assert err.value.code == "conflict"


def test_propose_is_idempotent_until_rejected(tmp_path):
    service, log = make_service(tmp_path)
    first = service.propose(NOON)
    assert service.propose(NOON) == first
    assert events(log) == ["plan_proposed"]
    service.reject(first.plan_id, "op")
    again = service.propose(NOON)
    assert again.status == "proposed"


def test_execute_requires_approval(tmp_path):
    service, _ = make_service(tmp_path)
    plan = service.propose(NOON)
    with pytest.raises(ServiceError) as err:
        service.execute(plan.plan_id, "op")
    assert err.value.code == "conflict"


def test_kill_switch_cancels_pending_and_blocks_execution(tmp_path):
    service, log = make_service(tmp_path)
    approved = service.propose(NOON)
    service.approve(approved.plan_id, "op")
    pending = service.propose(NIGHT)
    out = service.kill_switch(True, "op")
    assert set(out["cancelled"]) == {approved.plan_id, pending.plan_id}
    assert service.get(approved.plan_id).status == "rejected"
    with pytest.raises(ServiceError) as err:
        service.execute(approved.plan_id, "op")
    assert err.value.code in ("kill_switch_active", "conflict")
    last = log.read()[-1]
    assert last.event == "kill_switch" and last.detail["fallback_share"] == 0.36
    service.kill_switch(False, "op")
    assert not service.kill_active


def test_unknown_plan_is_not_found(tmp_path):
    service, _ = make_service(tmp_path)
    with pytest.raises(ServiceError) as err:
        service.get("PLAN-nope")
    assert err.value.code == "not_found"


def test_log_uri_must_be_local():
    with pytest.raises(NotImplementedError):
        open_log("s3://bucket/actions.jsonl")


def test_same_instant_in_another_timezone_is_the_same_plan(tmp_path):
    service, log = make_service(tmp_path)
    first = service.propose(NOON)
    plus_two = datetime.fromisoformat("2025-06-21T12:00:00+02:00")
    assert service.propose(plus_two).plan_id == first.plan_id
    assert events(log) == ["plan_proposed"]


def test_unaligned_times_land_in_the_half_hour_slot(tmp_path):
    service, log = make_service(tmp_path)
    first = service.propose(NOON.replace(minute=7))
    assert first.plan_id.endswith("2025-06-21-1000-PT-A")
    assert service.propose(NOON.replace(minute=8)) == first
    assert service.propose(NOON.replace(minute=31)).plan_id.endswith("1030-PT-A")
    assert events(log) == ["plan_proposed", "plan_proposed"]
