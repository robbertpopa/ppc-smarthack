"""Adapter that lets the agent use the grid guard.

The agent calls ``guard(plan, grid_state) -> GuardResult``. The grid guard needs
per-house readings, so this module builds them from the forecast and runs the
guard's own power flow. It never invents readings: with no PV or load forecast
the plan is rejected as unverifiable.
"""

import logging
import math
from collections.abc import Callable

from src.common.contract import Forecast, GridState, GuardResult, Plan, StationConfig

from .guard import guard as grid_guard
from .twin import build_grid

log = logging.getLogger(__name__)

Guard = Callable[[Plan, GridState | None], GuardResult]


def readings_from_forecast(
    station: StationConfig, forecast: Forecast, interval_start: str, case: str = "export"
) -> dict:
    """Worst-case readings for one side of the check.

    ``export``: PV p90 split by kWp and load p10 split evenly. It stresses overvoltage and
    export overload. ``import``: PV p10 and load p90. It stresses undervoltage and import
    overload. Splitting a station total across houses is an assumption: the real per-house
    split is unknown until smart-meter data is connected.
    """
    if case not in ("export", "import"):
        raise ValueError("case must be 'export' or 'import'")
    total_kwp = sum(h.kwp for h in station.houses)
    pv_total = forecast.pv_kw.p90 if case == "export" else forecast.pv_kw.p10
    load_total = forecast.load_kw.p10 if case == "export" else forecast.load_kw.p90
    load_each = load_total / len(station.houses)
    return {
        "interval_start": interval_start,
        "houses": [
            {
                "house_id": h.house_id,
                "load_kw": load_each,
                "pv_kw": pv_total * h.kwp / total_kwp,
            }
            for h in station.houses
        ],
    }


def _merge(results: list[dict]) -> dict:
    """The plan passes only if it passes both cases; report the worst numbers of the two."""
    violations = list(dict.fromkeys(v for r in results for v in r["violations"]))

    def worst(name):
        values = [r[name] for r in results if r.get(name) is not None and math.isfinite(r[name])]
        return max(values) if values else None

    return {
        "passed": all(r["passed"] for r in results),
        "violations": violations,
        "v_max_pu": worst("v_max_pu"),
        "trafo_loading_pct": worst("trafo_loading_pct"),
    }


def make_grid_guard(station: StationConfig, source, grid_config: dict | None = None) -> Guard:
    """Build a guard for one station. ``source`` provides ``forecast(pt_id, interval_start)``."""
    config = {
        "pt_id": station.pt_id,
        "houses": [h.model_dump(exclude_none=True) for h in station.houses],
        **(grid_config or {}),
    }
    grid = build_grid(config)

    def check(plan: Plan, grid_state: GridState | None) -> GuardResult:
        forecast = source.forecast(plan.pt_id, plan.interval_start)
        if forecast is None or forecast.pv_kw is None or forecast.load_kw is None:
            return GuardResult(
                passed=False, violations=["no PV and load forecast: the plan cannot be verified"]
            )
        payload = plan.model_dump(mode="json")
        result = _merge(
            [
                grid_guard(
                    grid,
                    payload,
                    readings_from_forecast(station, forecast, payload["interval_start"], case),
                )
                for case in ("export", "import")
            ]
        )
        log.info("grid guard: passed=%s violations=%s", result["passed"], result["violations"])
        return GuardResult(
            passed=result["passed"],
            v_max_pu=result.get("v_max_pu"),
            trafo_loading_pct=result.get("trafo_loading_pct"),
            violations=result["violations"],
        )

    return check
