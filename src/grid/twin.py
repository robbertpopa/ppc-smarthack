"""Balanced AC grid twin. All limits and synthetic topology are assumptions."""

import math
from dataclasses import dataclass

try:
    import pandapower as pp
    from pandapower.auxiliary import LoadflowNotConverged
except ModuleNotFoundError as exc:
    if exc.name != "pandapower":
        raise
    pp = None

    class LoadflowNotConverged(Exception):
        """Placeholder used only when the optional simulator is unavailable."""


@dataclass
class Grid:
    net: object
    houses: dict
    pt_id: str
    voltage_limit_pu: float
    interval_hours: float
    min_voltage_pu: float


def build_grid(config):
    """Build synthetic station or SimBench benchmark; houses are {house_id, kwp}."""
    if pp is None:
        raise ImportError('Install the project simulation extra: pip install -e ".[sim]"')
    houses = config["houses"]
    if not houses or len({h["house_id"] for h in houses}) != len(houses):
        raise ValueError("houses must be nonempty with unique identifiers")
    if any(not math.isfinite(float(h["kwp"])) or float(h["kwp"]) <= 0 for h in houses):
        raise ValueError("each house requires positive finite kwp")
    if any(
        h.get("contract_cap_kw") is not None
        and (not math.isfinite(float(h["contract_cap_kw"])) or float(h["contract_cap_kw"]) <= 0)
        for h in houses
    ):
        raise ValueError("contract caps must be positive and finite when provided")
    for name, value in (
        ("transformer_kva", config.get("transformer_kva", 400)),
        ("voltage_limit_pu", config.get("voltage_limit_pu", 1.05)),
        ("min_voltage_pu", config.get("min_voltage_pu", 0.90)),
        ("interval_hours", config.get("interval_hours", 0.5)),
    ):
        if not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError(f"{name} must be positive and finite")
    topology = config.get("topology", "synthetic")
    if topology == "simbench":
        return _build_simbench(config, houses)
    if topology != "synthetic":
        raise ValueError("unknown topology")
    net = pp.create_empty_network(sn_mva=1)
    mv = pp.create_bus(net, vn_kv=20, name="MV source")
    lv = pp.create_bus(net, vn_kv=0.4, name="Transformer LV")
    pp.create_ext_grid(net, mv, vm_pu=1.0)
    pp.create_transformer_from_parameters(
        net,
        mv,
        lv,
        sn_mva=config.get("transformer_kva", 400) / 1000,
        vn_hv_kv=20,
        vn_lv_kv=0.4,
        vk_percent=4,
        vkr_percent=1,
        pfe_kw=0,
        i0_percent=0,
    )
    per_area = int(config.get("houses_per_neighborhood", 70))
    per_node = int(config.get("houses_per_node", 10))
    if per_area < 1 or per_node < 1:
        raise ValueError("house counts must be positive")
    mapping = {}
    previous = lv
    for i, house in enumerate(houses):
        if i % per_area == 0:
            previous = lv
        if i % per_area % per_node == 0:
            node = pp.create_bus(
                net,
                vn_kv=0.4,
                name=f"area-{i // per_area + 1}-node-{(i % per_area) // per_node + 1}",
            )
            pp.create_line_from_parameters(
                net,
                previous,
                node,
                length_km=0.03,
                r_ohm_per_km=0.206,
                x_ohm_per_km=0.08,
                c_nf_per_km=0,
                max_i_ka=0.3,
            )
            previous = node
        load = pp.create_load(net, previous, p_mw=0, q_mvar=0)
        pv = pp.create_sgen(net, previous, p_mw=0, q_mvar=0)
        mapping[house["house_id"]] = {
            "bus": previous,
            "load": load,
            "pv": pv,
            "kwp": float(house["kwp"]),
            "contract_cap_kw": house.get("contract_cap_kw"),
        }
    if float(config.get("min_voltage_pu", 0.90)) >= float(config.get("voltage_limit_pu", 1.05)):
        raise ValueError("minimum voltage must be below maximum voltage")
    return Grid(
        net,
        mapping,
        config.get("pt_id", "PT-A"),
        float(config.get("voltage_limit_pu", 1.05)),
        float(config.get("interval_hours", 0.5)),
        float(config.get("min_voltage_pu", 0.90)),
    )


def _build_simbench(config, houses):
    """Replace benchmark loads and generators with homes at existing load buses.

    Allocation cycles deterministically across load buses. This benchmark is
    not a three-neighborhood model and its original transformer is preserved.
    """
    import simbench

    net = simbench.get_simbench_net(config.get("simbench_code", "1-LV-rural3--0-sw"))
    buses = list(dict.fromkeys(int(x) for x in net.load.bus))
    if not buses or len(net.trafo) != 1:
        raise ValueError("benchmark must have load buses and one transformer")
    net.load.drop(net.load.index, inplace=True)
    net.sgen.drop(net.sgen.index, inplace=True)
    mapping = {}
    for i, house in enumerate(houses):
        bus = buses[i % len(buses)]
        load = pp.create_load(net, bus, p_mw=0, q_mvar=0)
        pv = pp.create_sgen(net, bus, p_mw=0, q_mvar=0)
        mapping[house["house_id"]] = {
            "bus": bus,
            "load": load,
            "pv": pv,
            "kwp": float(house["kwp"]),
            "contract_cap_kw": house.get("contract_cap_kw"),
        }
    if float(config.get("min_voltage_pu", 0.90)) >= float(config.get("voltage_limit_pu", 1.05)):
        raise ValueError("minimum voltage must be below maximum voltage")
    return Grid(
        net,
        mapping,
        config.get("pt_id", "PT-simbench"),
        float(config.get("voltage_limit_pu", 1.05)),
        float(config.get("interval_hours", 0.5)),
        float(config.get("min_voltage_pu", 0.90)),
    )


def power_flow(grid, injections, *, include_internal=False):
    """Run one interval: injections contains interval_start and houses list.

    Each house has house_id, load_kw, pv_kw and export_limit_kw. Missing data
    is rejected. Limits apply to net export; self-consumed PV remains available.
    """
    records = injections["houses"]
    by_id = {item["house_id"]: item for item in records}
    if len(records) != len(by_id) or by_id.keys() != grid.houses.keys():
        raise ValueError("injections must contain every house exactly once")
    exported = curtailed = 0.0
    for hid, mapping in grid.houses.items():
        record = by_id[hid]
        load, pv, limit = (float(record[k]) for k in ("load_kw", "pv_kw", "export_limit_kw"))
        if not all(math.isfinite(v) and v >= 0 for v in (load, pv, limit)):
            raise ValueError("power values must be finite and nonnegative")
        actual = min(pv, load + limit)
        grid.net.load.at[mapping["load"], "p_mw"] = load / 1000
        grid.net.sgen.at[mapping["pv"], "p_mw"] = actual / 1000
        exported += max(actual - load, 0) * grid.interval_hours
        curtailed += (pv - actual) * grid.interval_hours
    base = {
        "pt_id": grid.pt_id,
        "interval_start": injections["interval_start"],
        "provenance": "simulated",
        "trafo_hotspot_c": None,
        "batteries": [],
    }

    def external(result):
        if not include_internal:
            result.pop("v_min_pu", None)
        return result

    try:
        # SimBench transformers can have a large phase shift (150 degrees).
        # DC initialization accounts for that shift, unlike a flat start.
        pp.runpp(grid.net, numba=False, init="dc", calculate_voltage_angles=True)
    except LoadflowNotConverged:
        return external(
            {
                **base,
                "converged": False,
                "v_max_pu": None,
                "v_min_pu": None,
                "v_max_node": None,
                "line_loading_max_pct": None,
                "trafo_loading_pct": None,
                "exported_kwh": None,
                "curtailed_kwh": None,
            }
        )
    voltages = grid.net.res_bus.vm_pu.loc[(grid.net.bus.vn_kv == 0.4) & grid.net.bus.in_service]
    line_loading = float(grid.net.res_line.loading_percent.max())
    transformer_loading = float(grid.net.res_trafo.loading_percent.max())
    if (
        voltages.empty
        or not all(math.isfinite(float(v)) for v in voltages)
        or not all(math.isfinite(v) for v in (line_loading, transformer_loading))
    ):
        return external(
            {
                **base,
                "converged": False,
                "v_max_pu": None,
                "v_min_pu": None,
                "v_max_node": None,
                "line_loading_max_pct": None,
                "trafo_loading_pct": None,
                "exported_kwh": None,
                "curtailed_kwh": None,
            }
        )
    node = voltages.idxmax()
    return external(
        {
            **base,
            "converged": True,
            "v_max_pu": float(voltages.loc[node]),
            "v_min_pu": float(voltages.min()),
            "v_max_node": str(grid.net.bus.at[node, "name"]),
            "line_loading_max_pct": line_loading,
            "trafo_loading_pct": transformer_loading,
            "exported_kwh": exported,
            "curtailed_kwh": curtailed,
        }
    )


def safe_share(grid, injections, scan_steps=20, tolerance=0.001):
    """Find highest observed feasible share; None means no safe point found.

    Coarse scanning allows import overload at low shares; narrow feasible
    islands between scan points can still be missed, so this is approximate.
    """
    if scan_steps < 1 or not 0 < tolerance < 1:
        raise ValueError("invalid search resolution")
    convergence_failed = False

    def safe(share):
        nonlocal convergence_failed

        def allowed(house):
            info = grid.houses[house["house_id"]]
            limit = info["kwp"] * share
            return (
                min(limit, float(info["contract_cap_kw"]))
                if info["contract_cap_kw"] is not None
                else limit
            )

        data = {
            **injections,
            "houses": [{**h, "export_limit_kw": allowed(h)} for h in injections["houses"]],
        }
        state = power_flow(grid, data, include_internal=True)
        if not state["converged"]:
            convergence_failed = True
            return False
        return (
            state["converged"]
            and state["v_min_pu"] >= grid.min_voltage_pu
            and state["v_max_pu"] <= grid.voltage_limit_pu
            and state["line_loading_max_pct"] <= 100
            and state["trafo_loading_pct"] <= 100
        )

    points = [i / scan_steps for i in range(scan_steps + 1)]
    feasible = [x for x in points if safe(x)]
    if convergence_failed:
        return None
    if not feasible:
        return None
    low = max(feasible)
    if low == 1:
        return 1.0
    high = min(1.0, low + 1 / scan_steps)
    while high - low > tolerance:
        mid = (low + high) / 2
        if safe(mid):
            low = mid
        else:
            high = mid
        if convergence_failed:
            return None
    return low
