import logging
import math
from collections.abc import Callable

from src.common.contract import GridState, GuardResult, Plan

log = logging.getLogger(__name__)

Guard = Callable[[Plan, GridState | None], GuardResult]


def stub_guard(plan: Plan, grid_state: GridState | None) -> GuardResult:
    log.warning("stub guard in use: voltage and transformer limits are not checked")
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
