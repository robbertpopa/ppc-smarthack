"""Check proposed plans using the twin. Battery sign: positive means charging."""

import math

from .battery import step
from .twin import power_flow


def guard(grid, plan, injections):
    violations = []
    if plan.get("pt_id", grid.pt_id) != grid.pt_id:
        return {"passed": False, "violations": ["Plan station does not match grid"]}
    if plan.get("interval_start", injections.get("interval_start")) != injections.get(
        "interval_start"
    ):
        return {"passed": False, "violations": ["Plan interval does not match readings"]}
    try:
        limits = {x["house_id"]: x for x in plan["limits"]}
        readings = {x["house_id"]: x for x in injections["houses"]}
    except (KeyError, TypeError):
        return {"passed": False, "violations": ["Missing or invalid plan or readings"]}
    if len(limits) != len(plan["limits"]) or limits.keys() != grid.houses.keys():
        return {"passed": False, "violations": ["Plan must cover each house exactly once"]}
    if len(readings) != len(injections["houses"]) or readings.keys() != grid.houses.keys():
        return {"passed": False, "violations": ["Readings must cover each house exactly once"]}
    updated = []
    for hid, source in readings.items():
        item = limits[hid]
        try:
            power = float(item.get("battery_kw", 0))
            load = float(source["load_kw"])
            pv = float(source["pv_kw"])
            limit = float(item["export_limit_kw"])
            if (
                not all(math.isfinite(x) for x in (power, load, pv, limit))
                or min(load, pv, limit) < 0
            ):
                raise ValueError("non-finite or negative values")
        except (KeyError, TypeError, ValueError) as exc:
            violations.append(f"{hid}: invalid power input ({exc})")
            continue
        net_load = load + power
        cap = grid.houses[hid].get("contract_cap_kw")
        if cap is not None and limit > float(cap):
            violations.append(f"{hid}: limit exceeds contract cap")
        if max(-net_load, 0) > limit:
            violations.append(f"{hid}: battery discharge alone exceeds export limit")
        if power and "battery_soc_kwh" not in source:
            violations.append(f"{hid}: battery state missing")
        elif "battery_soc_kwh" in source:
            try:
                step(float(source["battery_soc_kwh"]), power, grid.interval_hours)
            except (ValueError, TypeError) as exc:
                violations.append(f"{hid}: {exc}")
        # Express negative net demand as extra generation so both remain nonnegative.
        updated.append(
            {
                **source,
                "load_kw": max(net_load, 0),
                "pv_kw": pv + max(-net_load, 0),
                "export_limit_kw": limit,
            }
        )
    if violations:
        return {"passed": False, "violations": violations}
    try:
        state = power_flow(grid, {**injections, "houses": updated}, include_internal=True)
    except (ValueError, KeyError, TypeError) as exc:
        return {"passed": False, "violations": [f"Invalid input: {exc}"]}
    if not state["converged"]:
        violations.append("Power flow did not converge")
    else:
        if state["v_min_pu"] < grid.min_voltage_pu:
            violations.append("Voltage below configured minimum")
        if state["v_max_pu"] > grid.voltage_limit_pu:
            violations.append("Voltage exceeds configured limit")
        if state["line_loading_max_pct"] > 100:
            violations.append("Line loading exceeds 100%")
        if state["trafo_loading_pct"] > 100:
            violations.append("Transformer loading exceeds 100%")
    return {
        "passed": not violations,
        "violations": violations,
        "v_max_pu": state["v_max_pu"],
        "trafo_loading_pct": state["trafo_loading_pct"],
    }
