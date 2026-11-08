"""Price-driven battery dispatch for one house. Pure: no grid, no I/O.

Each local day starts and ends empty. The battery stores energy from the cheapest solar
hours (and everything the export cap would waste) and sells it in the best evening hours,
as long as that pays more than exporting at once after the round-trip loss. Export never
exceeds the cap, and the battery stays idle in intervals where the agent fell back.
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

STEP_HOURS = 0.5
SELL_HOURS = range(18, 22)  # local clock hours in which stored energy is sold
SHARE_WITH_BATTERY = 0.30  # 101,243 of 332,684 prosumers (docs/06-motivation-and-problems.md)
SYDNEY = "Australia/Sydney"


@dataclass(frozen=True)
class BatteryParams:
    """Same numbers as the defaults of ``src.grid.battery.step``."""

    capacity_kwh: float = 10.0
    min_soc_kwh: float = 1.0
    max_power_kw: float = 5.0
    roundtrip_efficiency: float = 0.9

    @property
    def usable_kwh(self) -> float:
        return self.capacity_kwh - self.min_soc_kwh


def battery_houses(house_ids, fraction: float = SHARE_WITH_BATTERY) -> list[str]:
    """The first houses in sorted order: a fixed, repeatable choice."""
    ids = sorted(house_ids)
    return ids[: math.ceil(fraction * len(ids))]


def dispatch(
    price_eur_mwh: pd.Series,
    surplus_kw: pd.Series,
    cap_kw: pd.Series,
    active: pd.Series,
    fee_eur_mwh: float,
    params: BatteryParams = BatteryParams(),
    tz: str = SYDNEY,
) -> pd.DataFrame:
    """Battery power and grid export of one house, per half-hour.

    All inputs share one sorted half-hour index. ``surplus_kw`` is what the panels give beyond
    the house's own use, ``cap_kw`` the export limit in force, ``active`` False where the agent
    fell back. Output ``battery_kw`` is positive when charging (like ``src.grid.battery``),
    ``export_kw`` is what reaches the grid.
    """
    index = price_eur_mwh.index
    for other in (surplus_kw, cap_kw, active):
        if not other.index.equals(index):
            raise ValueError("all inputs must share one index")
    local = index.tz_convert(tz)
    days, hours = np.asarray(local.date), np.asarray(local.hour)
    price = price_eur_mwh.to_numpy(dtype=float)
    surplus = surplus_kw.fillna(0.0).clip(lower=0.0).to_numpy(dtype=float) * STEP_HOURS
    cap = cap_kw.to_numpy(dtype=float) * STEP_HOURS
    on = active.to_numpy(dtype=bool) & np.isfinite(price)
    plain = np.minimum(surplus, cap)
    sells_hour = np.isin(hours, list(SELL_HOURS))
    p = params
    eff = math.sqrt(p.roundtrip_efficiency)
    per_step = p.max_power_kw * STEP_HOURS
    charge = np.zeros(len(index))
    discharge = np.zeros(len(index))
    for day in np.unique(days):
        idx = np.flatnonzero(days == day)
        sells = sorted((i for i in idx if on[i] and sells_hour[i]), key=lambda i: -price[i])
        room = {i: min(per_step, max(cap[i] - plain[i], 0.0)) for i in sells}
        units = []
        for i in idx:
            if on[i] and not sells_hour[i] and surplus[i] > 0:
                units.append((0.0, i, max(surplus[i] - cap[i], 0.0)))  # would be wasted anyway
                units.append((max(0.0, price[i] - fee_eur_mwh), i, min(surplus[i], cap[i])))
        units.sort(key=lambda u: u[0])
        budget = p.usable_kwh / eff
        for opportunity, i, available in units:
            for s in sells:
                limit = per_step - charge[i]
                if budget <= 1e-9 or available <= 1e-9 or limit <= 1e-9:
                    break
                if room[s] <= 1e-9:
                    continue
                if p.roundtrip_efficiency * max(0.0, price[s] - fee_eur_mwh) <= opportunity:
                    break  # sells are sorted by price, so no later one pays more
                q = min(available, budget, room[s] / p.roundtrip_efficiency, limit)
                charge[i] += q
                available -= q
                budget -= q
                room[s] -= q * p.roundtrip_efficiency
                discharge[s] += q * p.roundtrip_efficiency
    export = np.minimum(surplus - charge, cap) + discharge
    return pd.DataFrame(
        {"battery_kw": (charge - discharge) / STEP_HOURS, "export_kw": export / STEP_HOURS},
        index=index,
    )
