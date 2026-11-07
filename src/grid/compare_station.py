import math

import opendssdirect as dss

from .twin import (
    HOUSES_PER_NEIGHBORHOOD,
    HOUSES_PER_NODE,
    NEIGHBORHOODS,
    NODES_PER_NEIGHBORHOOD,
    STATION_HOUSES,
    build_grid,
    power_flow,
)


def compare(profiles):
    if len(profiles) != STATION_HOUSES:
        raise ValueError(f"exactly {STATION_HOUSES} household profiles required")
    houses = [{"house_id": str(i), "kwp": 5.0} for i in range(STATION_HOUSES)]
    grid = build_grid({"houses": houses})
    injections = {
        "interval_start": "2025-01-01T12:00:00Z",
        "houses": [
            {"house_id": str(i), "load_kw": load, "pv_kw": pv, "export_limit_kw": max(pv, 0)}
            for i, (load, pv) in enumerate(profiles)
        ],
    }
    state = power_flow(grid, injections)
    if not state["converged"]:
        raise RuntimeError("pandapower did not converge")
    command = dss.Text.Command
    command("clear")
    command("new circuit.station basekv=20 pu=1 phases=3 bus1=source")
    command("edit vsource.source r1=0.000001 x1=0.000001 r0=0.000001 x0=0.000001")
    command(
        "new transformer.t phases=3 windings=2 buses=[source lv] conns=[wye wye] "
        "kvs=[20 0.4] kvas=[400 400] %rs=[0.5 0.5] xhl=3.872983346 %noloadloss=0 %imag=0"
    )
    for area in range(NEIGHBORHOODS):
        previous = "lv"
        for seg in range(NODES_PER_NEIGHBORHOOD):
            node = f"a{area + 1}s{seg + 1}"
            command(
                f"new line.l{area + 1}_{seg + 1} bus1={previous} bus2={node} "
                "phases=3 length=0.03 units=km r1=0.206 x1=0.08 r0=0.206 "
                "x0=0.08 c1=0 c0=0 normamps=300"
            )
            first = area * HOUSES_PER_NEIGHBORHOOD + seg * HOUSES_PER_NODE
            group = profiles[first : first + HOUSES_PER_NODE]
            total_load = sum(p[0] for p in group)
            total_pv = sum(p[1] for p in group)
            command(
                f"new load.h{area + 1}_{seg + 1} bus1={node} phases=3 conn=wye "
                f"kv=0.4 kw={total_load} kvar=0 model=1 vminpu=0.5 vmaxpu=1.5"
            )
            if total_pv:
                command(
                    f"new generator.p{area + 1}_{seg + 1} bus1={node} phases=3 conn=wye "
                    f"kv=0.4 kw={total_pv} kvar=0 model=1 vminpu=0.5 vmaxpu=1.5"
                )
            previous = node
    command("set voltagebases=[20, 0.4]")
    command("calcvoltagebases")
    dss.Solution.Solve()
    if not dss.Solution.Converged():
        raise RuntimeError("OpenDSS did not converge")
    differences = []
    for area in range(NEIGHBORHOODS):
        for seg in range(NODES_PER_NEIGHBORHOOD):
            dss.Circuit.SetActiveBus(f"a{area + 1}s{seg + 1}")
            dss_v = dss.Bus.puVmagAngle()[0]
            name = f"area-{area + 1}-node-{seg + 1}"
            pp_bus = grid.net.bus.index[grid.net.bus.name == name][0]
            differences.append(abs(dss_v - grid.net.res_bus.vm_pu.loc[pp_bus]))
    return max(differences)


if __name__ == "__main__":
    for load, pv in [(1, 0), (1, 1), (0.5, 3)]:
        difference = compare([(load, pv)] * STATION_HOUSES)
        print(f"load={load} kW, PV={pv} kW per home: max voltage difference={difference:.7f} pu")
        if not math.isfinite(difference) or difference > 0.001:
            raise AssertionError("solvers differ by more than 0.001 pu")
