"""What prosumers earn and what PPC's side of it is worth, under today's regulated price and
the proposed hourly price with a solar adder, for the houses that have a battery."""

import dataclasses
import math

import numpy as np
import pandas as pd

from src.eval.metrics import STEP_HOURS
from src.pricing import prices, solar
from src.pricing.battery import battery_houses, dispatch
from src.pricing.config import PricingConfig
from src.pricing.settlement import settle
from src.pricing.tariff import hourly_price_series

FEES = (0, 10, 20, 30, 40, 50)  # EUR/MWh, for the sensitivity table
SUMMER_MONTHS = (12, 1, 2)  # Sydney summer, the sunniest part of the Ausgrid year
TITLE = "Prosumer revenue and PPC margin: regulated price versus hourly price with solar adder"
SOURCE_NOTE = "Prices: hourly day-ahead (PZU), Romania, via euenergy.live (CC-BY-4.0)."


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value)
    value = float(value)
    return round(value, 6) if math.isfinite(value) else None


def _pct(new, old):
    return None if not old or old <= 0 else (new / old - 1) * 100


def _inputs(ctx: dict, result: dict, table: pd.Series) -> dict | None:
    """Prices and the smart limit's decisions on the scored intervals, or None."""
    surplus, kwp = ctx["surplus"], ctx["kwp"]
    if surplus is None:
        return None
    scored = result["scored"]
    index = scored["fallback"].index.intersection(surplus.index).sort_values()
    if len(index) == 0:
        return None
    adder = solar.monthly_adder(table)
    return {
        "index": index,
        "share": scored["fallback"].loc[index],
        "active": ~scored["abstain"].loc[index],
        "wholesale": prices.align(index, table),
        "monthly": prices.align_monthly(index, prices.monthly_average(table)),
        "adder": prices.align_monthly(index, adder),
        "adder_by_month": adder,
        "houses": battery_houses(kwp.index),
    }


def _group_exports(ctx: dict, data: dict, fee: float) -> tuple[pd.Series, pd.Series]:
    """kWh per interval of the battery houses: without and with battery response."""
    index, surplus, kwp = data["index"], ctx["surplus"], ctx["kwp"]
    plain = pd.Series(0.0, index=index)
    shifted = pd.Series(0.0, index=index)
    for house in data["houses"]:
        s = surplus.loc[index, house]
        cap = data["share"] * kwp[house]
        plain += np.minimum(s.fillna(0.0), cap) * STEP_HOURS
        out = dispatch(data["wholesale"], s, cap, data["active"], fee)
        shifted += out["export_kw"] * STEP_HOURS
    return plain, shifted


def _row(name, kwh, paid, value, today):
    margin = value - paid
    return {
        "name": name,
        "exported_kwh": kwh,
        "prosumer_eur": paid,
        "prosumer_vs_today_pct": _pct(paid, today["prosumer_eur"]) if today else 0.0,
        "ppc_margin_eur": margin,
        "ppc_margin_pct_of_value": margin / value * 100 if value > 0 else None,
        "ppc_improvement_eur": margin - today["ppc_margin_eur"] if today else 0.0,
    }


def compute(
    ctx: dict,
    result: dict,
    table: pd.Series,
    cfg: PricingConfig = PricingConfig(),
) -> dict | None:
    """The block of one scenario, or None when there is no surplus table."""
    data = _inputs(ctx, result, table)
    if data is None:
        return None
    wholesale, monthly, adder = data["wholesale"], data["monthly"], data["adder"]
    none = adder * 0.0
    plain, shifted = _group_exports(ctx, data, cfg.fee_eur_mwh)
    today = settle(plain, wholesale, monthly, none, cfg)
    hourly_only = settle(plain, wholesale, monthly, none, cfg)
    with_adder = settle(plain, wholesale, monthly, adder, cfg)
    proposed = settle(shifted, wholesale, monthly, adder, cfg)
    base = {
        "prosumer_eur": today["regulated_eur"],
        "ppc_margin_eur": today["ppc_margin_regulated_eur"],
    }
    rows = [
        _row(
            "Today: regulated monthly average",
            today["exported_kwh"],
            today["regulated_eur"],
            today["value_eur"],
            None,
        ),
        _row(
            "Hourly price only (no adder, no battery)",
            hourly_only["exported_kwh"],
            hourly_only["hourly_eur"],
            hourly_only["value_eur"],
            base,
        ),
        _row(
            "Hourly price + solar adder, no battery",
            with_adder["exported_kwh"],
            with_adder["paid_eur"],
            with_adder["value_eur"],
            base,
        ),
        _row(
            "Hourly price + solar adder + battery response (proposed)",
            proposed["exported_kwh"],
            proposed["paid_eur"],
            proposed["value_eur"],
            base,
        ),
    ]
    sensitivity = []
    for fee in FEES:
        fee_cfg = dataclasses.replace(cfg, fee_eur_mwh=float(fee))
        p_plain, p_shifted = _group_exports(ctx, data, fee_cfg.fee_eur_mwh)
        old = settle(p_plain, wholesale, monthly, none, fee_cfg)
        new = settle(p_shifted, wholesale, monthly, adder, fee_cfg)
        gain_prosumer = new["paid_eur"] - old["regulated_eur"]
        gain_ppc = new["ppc_margin_paid_eur"] - old["ppc_margin_regulated_eur"]
        created = gain_prosumer + gain_ppc
        sensitivity.append(
            {
                "fee_eur_mwh": fee,
                "prosumer_eur": new["paid_eur"],
                "prosumer_vs_today_pct": _pct(new["paid_eur"], old["regulated_eur"]),
                "ppc_margin_eur": new["ppc_margin_paid_eur"],
                "ppc_improvement_eur": gain_ppc,
                "value_created_eur": created,
                "prosumer_share_of_value_pct": (
                    gain_prosumer / created * 100 if created > 0 else None
                ),
            }
        )
    block = {
        "battery_houses": data["houses"],
        "n_intervals": len(data["index"]),
        "fee_eur_mwh": cfg.fee_eur_mwh,
        "floor_eur_mwh": cfg.floor_eur_mwh,
        "adder_eur_mwh_by_bucharest_month": data["adder_by_month"].to_dict(),
        "rows": rows,
        "sensitivity": sensitivity,
    }
    return _clean(block)


def day_chart(ctx, result, table, out, pt_id: str, cfg: PricingConfig = PricingConfig()):
    """PNG of the summer day with the most exported energy; None without such a day."""
    data = _inputs(ctx, result, table)
    if data is None:
        return None
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plain, shifted = _group_exports(ctx, data, cfg.fee_eur_mwh)
    local = data["index"].tz_convert(prices.SYDNEY)
    summer = np.isin(local.month, SUMMER_MONTHS)
    if not summer.any():
        return None
    dates = np.asarray(local.date)
    day = plain[summer].groupby(dates[summer]).sum().idxmax()
    pick = dates == day
    hours = local[pick].hour + local[pick].minute / 60
    wholesale = data["wholesale"][pick]
    paid = hourly_price_series(wholesale, cfg) + data["adder"][pick]
    fig, ax = plt.subplots(figsize=(7.0, 3.6), dpi=100)
    ax.bar(hours - 0.11, plain[pick], width=0.22, color="#9ecae1", label="Export, no battery (kWh)")
    ax.bar(hours + 0.11, shifted[pick], width=0.22, color="#3182bd", label="Export, battery (kWh)")
    ax.set_xlabel(f"Hour of {day} (Sydney time)")
    ax.set_ylabel("Exported energy (kWh per half-hour)")
    ax2 = ax.twinx()
    ax2.plot(hours, wholesale / 10, color="#8c8c8c", label="Wholesale (ct/kWh)")
    ax2.plot(hours, paid / 10, color="#d62728", label="Paid: hourly + adder (ct/kWh)")
    ax2.set_ylabel("Price (ct/kWh)")
    handles, labels = ax.get_legend_handles_labels()
    more, names = ax2.get_legend_handles_labels()
    ax.legend(handles + more, labels + names, loc="upper left", fontsize=7)
    ax.set_title(f"{pt_id}: battery houses on the sunniest summer day")
    fig.tight_layout()
    path = out / f"pricing_day_{pt_id}.png"
    fig.savefig(path, metadata={"Software": None})
    plt.close(fig)
    return path


def _cell(value, digits, signed=False):
    if value is None:
        return "—"
    return f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"


def write(out, pt_id: str, block: dict, mock_title: str | None = None) -> None:
    """The markdown tables next to the other evaluation outputs."""
    title = f"{mock_title} – {TITLE}" if mock_title else TITLE
    houses = ", ".join(block["battery_houses"])
    lines = [
        f"# {title}",
        "",
        f"Station {pt_id}; houses with a battery: {houses}. Fee {block['fee_eur_mwh']:.0f} "
        f"EUR/MWh. {SOURCE_NOTE}",
        "",
        "| Policy | Exported (kWh) | Prosumer (EUR) | vs today (%) | PPC margin (EUR) "
        "| PPC margin (% of value) | PPC improvement (EUR) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in block["rows"]:
        lines.append(
            f"| {r['name']} | {_cell(r['exported_kwh'], 1)} | {_cell(r['prosumer_eur'], 2)} "
            f"| {_cell(r['prosumer_vs_today_pct'], 1, True)} | {_cell(r['ppc_margin_eur'], 2)} "
            f"| {_cell(r['ppc_margin_pct_of_value'], 1)} "
            f"| {_cell(r['ppc_improvement_eur'], 2, True)} |"
        )
    lines += [
        "",
        "Fee sensitivity (hourly price + solar adder + battery response).",
        "",
        "| Fee (EUR/MWh) | Prosumer (EUR) | vs today (%) | PPC margin (EUR) "
        "| PPC improvement (EUR) | Prosumer share of value created (%) |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for s in block["sensitivity"]:
        lines.append(
            f"| {s['fee_eur_mwh']} | {_cell(s['prosumer_eur'], 2)} "
            f"| {_cell(s['prosumer_vs_today_pct'], 1, True)} | {_cell(s['ppc_margin_eur'], 2)} "
            f"| {_cell(s['ppc_improvement_eur'], 2, True)} "
            f"| {_cell(s['prosumer_share_of_value_pct'], 0)} |"
        )
    (out / f"pricing_{pt_id}.md").write_text("\n".join(lines) + "\n")
