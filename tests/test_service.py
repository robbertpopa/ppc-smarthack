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


def test_propose_is_idempotent(tmp_path):
    service, log = make_service(tmp_path)
    first = service.propose(NOON)
    assert service.propose(NOON) == first
    assert events(log) == ["plan_proposed"]


def test_human_rejection_is_not_overridden_by_propose(tmp_path):
    service, log = make_service(tmp_path)
    first = service.propose(NIGHT)
    rejected = service.reject(first.plan_id, "op")
    assert service.propose(NIGHT) == rejected
    assert rejected.status == "rejected" and service.queue()["pending"] == []
    assert events(log) == ["plan_proposed", "abstained", "plan_rejected"]


def test_guard_blocked_plan_is_proposed_again_when_the_guard_passes(tmp_path):
    verdicts = iter([False, True])

    def flaky(plan, grid_state):
        ok = next(verdicts)
        return GuardResult(passed=ok, violations=[] if ok else ["v_max 1.12 pu above 1.10"])

    service, log = make_service(tmp_path, guard=flaky)
    assert service.propose(NOON).status == "rejected"
    assert service.propose(NOON).status == "proposed"
    assert events(log) == ["guard_blocked", "plan_proposed"]


def test_kill_switch_writes_one_rejection_per_cancelled_plan(tmp_path):
    service, log = make_service(tmp_path)
    approved = service.propose(NOON)
    service.approve(approved.plan_id, "op")
    pending = service.propose(NIGHT)
    service.kill_switch(True, "op")
    rejections = [e for e in log.read() if e.event == "plan_rejected"]
    assert {e.plan_id for e in rejections} == {approved.plan_id, pending.plan_id}
    assert all(e.detail["reason"] == "kill_switch" for e in rejections)
    assert log.read()[-1].event == "kill_switch"


def test_kill_cancelled_plan_can_be_proposed_again(tmp_path):
    service, _ = make_service(tmp_path)
    plan = service.propose(NOON)
    service.kill_switch(True, "op")
    service.kill_switch(False, "op")
    assert service.propose(NOON).status == "proposed"
    assert plan.plan_id == service.propose(NOON).plan_id


class BrokenLog:
    def __init__(self, inner):
        self.inner = inner
        self.fail = False

    def append(self, event):
        if self.fail:
            raise OSError("disk full")
        self.inner.append(event)

    def read(self, limit=100):
        return self.inner.read(limit)

    def read_all(self):
        return self.inner.read_all()


def test_a_failed_log_write_leaves_the_state_unchanged(tmp_path):
    inner = ActionLog(tmp_path / "actions.jsonl")
    log = BrokenLog(inner)
    service = AgentService(
        load_mock("station", StationConfig), log, stub_guard, MockSource(), clock=lambda: NOON
    )
    plan = service.propose(NOON)
    service.approve(plan.plan_id, "op")
    log.fail = True
    with pytest.raises(OSError):
        service.execute(plan.plan_id, "op")
    assert service.get(plan.plan_id).status == "approved"
    with pytest.raises(OSError):
        service.kill_switch(True, "op")
    assert not service.kill_active and service.get(plan.plan_id).status == "approved"
    with pytest.raises(OSError):
        service.propose(NIGHT)
    assert [p.plan_id for p in service.plans()] == [plan.plan_id]
    log.fail = False
    assert service.execute(plan.plan_id, "op").status == "executed"


def restart(tmp_path):
    station = load_mock("station", StationConfig)
    log = ActionLog(tmp_path / "actions.jsonl")
    return AgentService(station, log, stub_guard, MockSource(), clock=lambda: NOON)


def test_plans_and_kill_switch_survive_a_restart(tmp_path):
    service, _ = make_service(tmp_path)
    executed = service.propose(NOON)
    service.approve(executed.plan_id, "op")
    service.execute(executed.plan_id, "op")
    pending = service.propose(NIGHT)
    service.kill_switch(True, "op")
    again = restart(tmp_path)
    assert again.kill_active
    assert again.get(executed.plan_id).status == "executed"
    assert again.get(pending.plan_id).status == "rejected"
    with pytest.raises(ServiceError):
        again.execute(executed.plan_id, "op")
    again.kill_switch(False, "op")
    assert not restart(tmp_path).kill_active


def test_review_budget_and_human_rejections_survive_a_restart(tmp_path):
    service, _ = make_service(tmp_path)
    plan = service.propose(NIGHT)
    service.reject(plan.plan_id, "op")
    again = restart(tmp_path)
    assert again.queue()["reviewed_today"] == 1
    assert again.propose(NIGHT).status == "rejected"
    approved = service.propose(NOON)
    service.approve(approved.plan_id, "op")
    assert restart(tmp_path).get(approved.plan_id).status == "approved"


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


def service_with_threshold(tmp_path, threshold):
    station = load_mock("station", StationConfig)
    return AgentService(
        station,
        ActionLog(tmp_path / "actions.jsonl"),
        stub_guard,
        MockSource(),
        clock=lambda: NOON,
        thresholds=lambda pt_id: threshold,
    )


def test_a_stricter_model_threshold_makes_the_agent_abstain(tmp_path):
    assert not make_service(tmp_path)[0].propose(NOON).abstain
    other = tmp_path / "strict"
    other.mkdir()
    plan = service_with_threshold(other, 0.01).propose(NOON)
    assert plan.abstain and plan.source == "fallback_static"
    assert any("threshold 0.01" in r for r in plan.reasons)


def test_a_looser_model_threshold_lets_a_wide_forecast_through(tmp_path):
    assert make_service(tmp_path)[0].propose(NIGHT).abstain
    other = tmp_path / "loose"
    other.mkdir()
    plan = service_with_threshold(other, 1.0).propose(NIGHT)
    assert not plan.abstain and plan.source == "model"


@pytest.mark.parametrize("bad", [float("-inf"), float("nan"), 0.0, -0.2])
def test_an_unusable_threshold_means_always_abstain(tmp_path, bad):
    plan = service_with_threshold(tmp_path, bad).propose(NOON)
    assert plan.abstain and plan.source == "fallback_static" and plan.confidence == 0.0


def test_no_threshold_from_the_model_keeps_the_station_value(tmp_path):
    service = AgentService(
        load_mock("station", StationConfig),
        ActionLog(tmp_path / "actions.jsonl"),
        stub_guard,
        MockSource(),
        clock=lambda: NOON,
        thresholds=lambda pt_id: None,
    )
    assert not service.propose(NOON).abstain and service.propose(NIGHT).abstain


def test_a_threshold_lookup_that_raises_makes_the_agent_abstain(tmp_path):
    def broken(pt_id):
        raise RuntimeError("metadata file missing")

    service = AgentService(
        load_mock("station", StationConfig),
        ActionLog(tmp_path / "actions.jsonl"),
        stub_guard,
        MockSource(),
        clock=lambda: NOON,
        thresholds=broken,
    )
    plan = service.propose(NOON)
    assert plan.abstain and plan.source == "fallback_static" and plan.confidence == 0.0
    assert "abstention threshold lookup failed" in plan.reasons


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), 0, "high", [0.3]])
def test_every_unusable_threshold_abstains_even_with_zero_spread(tmp_path, bad):
    from src.common.contract import Forecast

    class Flat(MockSource):
        def forecast(self, pt_id, interval_start):
            flat = {"q05": 0.5, "q10": 0.5, "q20": 0.5, "q50": 0.5, "q90": 0.5}
            base = super().forecast(pt_id, interval_start).model_dump()
            base.update(safe_cap_share=flat, spread=0.0)
            return Forecast.model_validate(base)

    service = AgentService(
        load_mock("station", StationConfig),
        ActionLog(tmp_path / "actions.jsonl"),
        stub_guard,
        Flat(),
        clock=lambda: NOON,
        thresholds=lambda pt_id: bad,
    )
    plan = service.propose(NOON)
    assert plan.abstain and plan.source == "fallback_static"
    assert "no usable abstention threshold" in plan.reasons
