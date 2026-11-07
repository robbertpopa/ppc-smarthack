import pytest

from src.agent.guard import make_grid_guard
from src.agent.planner import make_plan
from src.common.contract import Forecast, GridState, StationConfig
from src.common.mock_data import load_mock


@pytest.fixture
def plan():
    return make_plan(
        load_mock("forecast", Forecast),
        load_mock("grid_state", GridState),
        load_mock("station", StationConfig),
    )


def adapt(grid_guard, injections=lambda plan: {"H01": 1.0}):
    return make_grid_guard(grid_guard, grid="grid", injections_for=injections)


def test_the_grid_guard_gets_the_grid_the_plan_and_the_injections(plan):
    seen = {}

    def grid_guard(grid, got_plan, injections):
        seen.update(grid=grid, plan=got_plan, injections=injections)
        return {"passed": True, "violations": []}

    result = adapt(grid_guard)(plan, None)
    assert result.passed and result.violations == []
    assert seen == {
        "grid": "grid",
        "plan": plan.model_dump(mode="json"),
        "injections": {"H01": 1.0},
    }
    assert isinstance(seen["plan"], dict) and seen["plan"]["interval_start"].endswith("Z")


def test_a_guard_written_for_plain_dicts_works(plan):
    def dict_guard(grid, got_plan, injections):
        ids = {x["house_id"] for x in got_plan["limits"]}
        houses = {h.house_id for h in load_mock("station", StationConfig).houses}
        ok = got_plan.get("pt_id") == "PT-A" and ids == houses
        return {"passed": ok, "violations": [] if ok else ["wrong plan shape"]}

    assert adapt(dict_guard)(plan, None).passed


def test_violations_block_the_plan_and_are_reported(plan):
    result = adapt(lambda *a: {"passed": False, "violations": ["v_max 1.12 pu above 1.10"]})(
        plan, None
    )
    assert not result.passed and result.violations == ["v_max 1.12 pu above 1.10"]


def test_figures_are_passed_on_when_the_guard_gives_them(plan):
    result = adapt(
        lambda *a: {"passed": True, "violations": [], "v_max_pu": 1.041, "trafo_loading_pct": 86.0}
    )(plan, None)
    assert result.v_max_pu == 1.041 and result.trafo_loading_pct == 86.0


def test_missing_figures_stay_empty_not_borrowed_from_another_state(plan):
    grid_state = load_mock("grid_state", GridState)
    result = adapt(lambda *a: {"passed": True, "violations": []})(plan, grid_state)
    assert result.v_max_pu is None and result.trafo_loading_pct is None


def test_an_object_result_works_like_a_dict(plan):
    class Verdict:
        passed = True
        violations = ()
        v_max_pu = 1.02

    result = adapt(lambda *a: Verdict())(plan, None)
    assert result.passed and result.v_max_pu == 1.02


def test_a_guard_that_raises_blocks_the_plan(plan):
    def boom(*args):
        raise RuntimeError("power flow did not converge")

    result = adapt(boom)(plan, None)
    assert not result.passed and "RuntimeError" in result.violations[0]


def test_failing_to_build_the_injections_blocks_the_plan(plan):
    def no_profile(_plan):
        raise KeyError("no profile for this interval")

    result = adapt(lambda *a: {"passed": True}, injections=no_profile)(plan, None)
    assert not result.passed and "KeyError" in result.violations[0]


@pytest.mark.parametrize("answer", [None, {}, {"violations": []}, {"passed": "yes"}, {"passed": 1}])
def test_an_answer_without_a_real_passed_flag_blocks_the_plan(plan, answer):
    result = adapt(lambda *a: answer)(plan, None)
    assert not result.passed and result.violations == ["guard returned no passed flag"]


def test_passed_with_violations_is_treated_as_blocked(plan):
    result = adapt(lambda *a: {"passed": True, "violations": ["line 3 at 104%"]})(plan, None)
    assert not result.passed and "line 3 at 104%" in result.violations[0]


def test_the_adapter_plugs_into_the_service(tmp_path):
    from datetime import datetime, timezone

    from src.agent.log import ActionLog
    from src.agent.service import AgentService
    from src.agent.sources import MockSource

    noon = datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)
    guard = adapt(lambda *a: {"passed": False, "violations": ["trafo 104%"]})
    log = ActionLog(tmp_path / "actions.jsonl")
    service = AgentService(load_mock("station", StationConfig), log, guard, MockSource())
    plan = service.propose(noon)
    assert plan.status == "rejected" and plan.guard.violations == ["trafo 104%"]
    assert [e.event for e in log.read()] == ["guard_blocked"]
