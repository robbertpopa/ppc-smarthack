import math

import opendssdirect as dss
import pandapower as pp


def compare(load_kw, pv_kw):
    net = pp.create_empty_network(sn_mva=1)
    source = pp.create_bus(net, vn_kv=0.4)
    house = pp.create_bus(net, vn_kv=0.4)
    pp.create_ext_grid(net, source, vm_pu=1.0)
    pp.create_line_from_parameters(
        net,
        source,
        house,
        length_km=0.1,
        r_ohm_per_km=0.4,
        x_ohm_per_km=0.08,
        c_nf_per_km=0,
        max_i_ka=0.2,
    )
    pp.create_load(net, house, p_mw=load_kw / 1000, q_mvar=0)
    pp.create_sgen(net, house, p_mw=pv_kw / 1000, q_mvar=0)
    pp.runpp(net, numba=False)

    dss.Text.Command("clear")
    dss.Text.Command("new circuit.test basekv=0.4 pu=1 phases=3 bus1=source")
    dss.Text.Command("edit vsource.source r1=0.000001 x1=0.000001 r0=0.000001 x0=0.000001")
    dss.Text.Command(
        "new line.feeder bus1=source bus2=house phases=3 length=0.1 units=km "
        "r1=0.4 x1=0.08 r0=0.4 x0=0.08 c1=0 c0=0"
    )
    dss.Text.Command(
        f"new load.house bus1=house phases=3 conn=wye kv=0.4 kw={load_kw} kvar=0 model=1"
    )
    if pv_kw:
        dss.Text.Command(
            f"new generator.pv bus1=house phases=3 conn=wye kv=0.4 kw={pv_kw} kvar=0 model=1"
        )
    dss.Text.Command("set voltagebases=[0.4]")
    dss.Text.Command("calcvoltagebases")
    dss.Solution.Solve()
    if not dss.Solution.Converged():
        raise RuntimeError("OpenDSS power flow did not converge")
    dss.Circuit.SetActiveBus("house")
    voltage = dss.Bus.puVmagAngle()[0]
    return float(net.res_bus.vm_pu.loc[house]), voltage


def main():
    for load, pv in [(10, 0), (10, 10), (10, 30)]:
        pp_v, dss_v = compare(load, pv)
        difference = abs(pp_v - dss_v)
        print(
            f"load={load} kW PV={pv} kW: pandapower={pp_v:.6f} pu, "
            f"OpenDSS={dss_v:.6f} pu, difference={difference:.6f} pu"
        )
        if not math.isfinite(difference) or difference > 0.001:
            raise AssertionError("Solvers differ by more than 0.001 pu")


if __name__ == "__main__":
    main()
