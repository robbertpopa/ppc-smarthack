import math
from dataclasses import dataclass

import numpy as np

try:
    import pandapower as pp
    from pandapower.auxiliary import LoadflowNotConverged
except ModuleNotFoundError as exc:
    if exc.name != "pandapower":
        raise
    pp = None

    class LoadflowNotConverged(Exception):
        pass


NEIGHBORHOODS = 3
HOUSES_PER_NEIGHBORHOOD = 70
HOUSES_PER_NODE = 10
STATION_HOUSES = NEIGHBORHOODS * HOUSES_PER_NEIGHBORHOOD
NODES_PER_NEIGHBORHOOD = HOUSES_PER_NEIGHBORHOOD // HOUSES_PER_NODE

_UNCONVERGED = {
    "converged": False,
    "v_max_pu": None,
    "v_min_pu": None,
    "v_max_node": None,
    "line_loading_max_pct": None,
    "trafo_loading_pct": None,
    "exported_kwh": None,
    "curtailed_kwh": None,
}


@dataclass
class Grid:
    net: object
    houses: dict
    pt_id: str
    voltage_limit_pu: float
    interval_hours: float
    min_voltage_pu: float


def _settings(config, houses, topology):
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
    defaults = {
        "transformer_kva": 400,
        "voltage_limit_pu": 1.05,
        "min_voltage_pu": 0.90,
        "interval_hours": 0.5,
    }
    if topology == "simbench":
        del defaults["transformer_kva"]
    settings = {name: float(config.get(name, default)) for name, default in defaults.items()}
    for name, value in settings.items():
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite")
    if settings["min_voltage_pu"] >= settings["voltage_limit_pu"]:
        raise ValueError("minimum voltage must be below maximum voltage")
    return settings


def _register(net, mapping, house, bus):
    mapping[house["house_id"]] = {
        "bus": bus,
        "load": pp.create_load(net, bus, p_mw=0, q_mvar=0),
        "pv": pp.create_sgen(net, bus, p_mw=0, q_mvar=0),
        "kwp": float(house["kwp"]),
        "contract_cap_kw": house.get("contract_cap_kw"),
    }


def _make_grid(net, mapping, config, settings, default_pt):
    return Grid(
        net,
        mapping,
        config.get("pt_id", default_pt),
        settings["voltage_limit_pu"],
        settings["interval_hours"],
        settings["min_voltage_pu"],
    )


def build_grid(config):
    if pp is None:
        raise ImportError('Install the project simulation extra: pip install -e ".[sim]"')
    houses = config["houses"]
    topology = config.get("topology", "synthetic")
    if topology not in ("synthetic", "simbench"):
        raise ValueError("unknown topology")
    settings = _settings(config, houses, topology)
    if topology == "simbench":
        return _build_simbench(config, houses, settings)
    per_area = int(config.get("houses_per_neighborhood", HOUSES_PER_NEIGHBORHOOD))
    per_node = int(config.get("houses_per_node", HOUSES_PER_NODE))
    if per_area < 1 or per_node < 1:
        raise ValueError("house counts must be positive")
    net = pp.create_empty_network(sn_mva=1)
    mv = pp.create_bus(net, vn_kv=20, name="MV source")
    lv = pp.create_bus(net, vn_kv=0.4, name="Transformer LV")
    pp.create_ext_grid(net, mv, vm_pu=1.0)
    pp.create_transformer_from_parameters(
        net,
        mv,
        lv,
        sn_mva=settings["transformer_kva"] / 1000,
        vn_hv_kv=20,
        vn_lv_kv=0.4,
        vk_percent=4,
        vkr_percent=1,
        pfe_kw=0,
        i0_percent=0,
    )
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
        _register(net, mapping, house, previous)
    return _make_grid(net, mapping, config, settings, "PT-A")


def _build_simbench(config, houses, settings):
    import simbench

    net = simbench.get_simbench_net(config.get("simbench_code", "1-LV-rural3--0-sw"))
    buses = list(dict.fromkeys(int(x) for x in net.load.bus))
    if not buses or len(net.trafo) != 1:
        raise ValueError("benchmark must have load buses and one transformer")
    net.load.drop(net.load.index, inplace=True)
    net.sgen.drop(net.sgen.index, inplace=True)
    mapping = {}
    for i, house in enumerate(houses):
        _register(net, mapping, house, buses[i % len(buses)])
    return _make_grid(net, mapping, config, settings, "PT-simbench")


def _inputs(grid, injections):
    records = injections["houses"]
    by_id = {item["house_id"]: item for item in records}
    if len(records) != len(by_id) or by_id.keys() != grid.houses.keys():
        raise ValueError("injections must contain every house exactly once")
    values = np.array(
        [
            [float(by_id[hid][key]) for key in ("load_kw", "pv_kw", "export_limit_kw")]
            for hid in grid.houses
        ]
    )
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("power values must be finite and nonnegative")
    return values.T


def solve(grid, injections):
    load, pv, limit = _inputs(grid, injections)
    actual = np.minimum(pv, load + limit)
    mappings = grid.houses.values()
    grid.net.load.loc[[m["load"] for m in mappings], "p_mw"] = load / 1000
    grid.net.sgen.loc[[m["pv"] for m in mappings], "p_mw"] = actual / 1000
    base = {
        "pt_id": grid.pt_id,
        "interval_start": injections["interval_start"],
        "provenance": "simulated",
        "trafo_hotspot_c": None,
        "batteries": [],
    }
    try:
        pp.runpp(grid.net, numba=False, init="dc", calculate_voltage_angles=True)
    except LoadflowNotConverged:
        return {**base, **_UNCONVERGED}
    voltages = grid.net.res_bus.vm_pu.loc[(grid.net.bus.vn_kv == 0.4) & grid.net.bus.in_service]
    line_loading = float(grid.net.res_line.loading_percent.max())
    transformer_loading = float(grid.net.res_trafo.loading_percent.max())
    if (
        voltages.empty
        or not all(math.isfinite(float(v)) for v in voltages)
        or not all(math.isfinite(v) for v in (line_loading, transformer_loading))
    ):
        return {**base, **_UNCONVERGED}
    node = voltages.idxmax()
    return {
        **base,
        "converged": True,
        "v_max_pu": float(voltages.loc[node]),
        "v_min_pu": float(voltages.min()),
        "v_max_node": str(grid.net.bus.at[node, "name"]),
        "line_loading_max_pct": line_loading,
        "trafo_loading_pct": transformer_loading,
        "exported_kwh": float(np.maximum(actual - load, 0).sum() * grid.interval_hours),
        "curtailed_kwh": float((pv - actual).sum() * grid.interval_hours),
    }


def power_flow(grid, injections):
    state = solve(grid, injections)
    state.pop("v_min_pu")
    return state


def limit_violations(grid, state):
    violations = []
    if state["v_min_pu"] < grid.min_voltage_pu:
        violations.append("Voltage below configured minimum")
    if state["v_max_pu"] > grid.voltage_limit_pu:
        violations.append("Voltage exceeds configured limit")
    if state["line_loading_max_pct"] > 100:
        violations.append("Line loading exceeds 100%")
    if state["trafo_loading_pct"] > 100:
        violations.append("Transformer loading exceeds 100%")
    return violations


def _allowed_limit(info, share):
    limit = info["kwp"] * share
    cap = info["contract_cap_kw"]
    return limit if cap is None else min(limit, float(cap))


def _share_is_safe(grid, injections, share):
    data = {
        **injections,
        "houses": [
            {**h, "export_limit_kw": _allowed_limit(grid.houses[h["house_id"]], share)}
            for h in injections["houses"]
        ],
    }
    state = solve(grid, data)
    if not state["converged"]:
        return None
    return not limit_violations(grid, state)


def safe_share(grid, injections, scan_steps=20, tolerance=0.001):
    if scan_steps < 1 or not 0 < tolerance < 1:
        raise ValueError("invalid search resolution")
    for index in range(scan_steps, -1, -1):
        verdict = _share_is_safe(grid, injections, index / scan_steps)
        if verdict is None:
            return None
        if verdict:
            break
    else:
        return None
    if index == scan_steps:
        return 1.0
    low = index / scan_steps
    high = (index + 1) / scan_steps
    while high - low > tolerance:
        mid = (low + high) / 2
        verdict = _share_is_safe(grid, injections, mid)
        if verdict is None:
            return None
        if verdict:
            low = mid
        else:
            high = mid
    return low
