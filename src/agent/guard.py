import logging
import math
from collections.abc import Callable, Mapping
from typing import Any

from src.common.contract import GridState, GuardResult, Plan

log = logging.getLogger(__name__)

Guard = Callable[[Plan, GridState | None], GuardResult]


_warned = False


def stub_guard(plan: Plan, grid_state: GridState | None) -> GuardResult:
    global _warned
    if not _warned:
        log.warning("stub guard in use: voltage and transformer limits are not checked")
        _warned = True
    violations = [
        f"{limit.house_id}: export limit {limit.export_limit_kw} kW is not a finite number"
        for limit in plan.limits
        if not math.isfinite(limit.export_limit_kw)
    ]
    return GuardResult(
        passed=not violations,
        v_max_pu=grid_state.v_max_pu if grid_state else None,
        trafo_loading_pct=grid_state.trafo_loading_pct if grid_state else None,
        violations=violations,
    )


def _field(result: Any, name: str) -> Any:
    if isinstance(result, Mapping):
        return result.get(name)
    return getattr(result, name, None)


def _blocked(reason: str) -> GuardResult:
    log.warning("guard blocked a plan: %s", reason)
    return GuardResult(passed=False, violations=[reason])


def make_grid_guard(
    grid_guard: Callable[[Any, Plan, Any], Any],
    grid: Any,
    injections_for: Callable[[Plan], Any],
) -> Guard:
    def guard(plan: Plan, grid_state: GridState | None) -> GuardResult:
        try:
            result = grid_guard(grid, plan, injections_for(plan))
        except Exception as exc:
            return _blocked(f"guard failed: {type(exc).__name__}: {exc}")
        passed = _field(result, "passed")
        if not isinstance(passed, bool):
            return _blocked("guard returned no passed flag")
        violations = [str(v) for v in (_field(result, "violations") or [])]
        if passed and violations:
            return _blocked("guard passed the plan but listed violations: " + "; ".join(violations))
        return GuardResult(
            passed=passed,
            v_max_pu=_field(result, "v_max_pu"),
            trafo_loading_pct=_field(result, "trafo_loading_pct"),
            violations=violations,
        )

    return guard
