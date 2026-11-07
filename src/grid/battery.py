"""Battery step: positive power charges, negative power discharges, in kW."""

import math


def step(
    soc_kwh,
    power_kw,
    hours,
    *,
    capacity_kwh=10.0,
    min_soc_kwh=1.0,
    max_power_kw=5.0,
    roundtrip_efficiency=0.9,
):
    values = (
        soc_kwh,
        power_kw,
        hours,
        capacity_kwh,
        min_soc_kwh,
        max_power_kw,
        roundtrip_efficiency,
    )
    if not all(math.isfinite(float(x)) for x in values):
        raise ValueError("battery parameters must be finite")
    if (
        hours <= 0
        or capacity_kwh <= 0
        or not 0 <= min_soc_kwh <= capacity_kwh
        or max_power_kw < 0
        or not 0 < roundtrip_efficiency <= 1
    ):
        raise ValueError("invalid battery parameters")
    if not min_soc_kwh <= soc_kwh <= capacity_kwh or abs(power_kw) > max_power_kw:
        raise ValueError("battery state or power outside bounds")
    efficiency = math.sqrt(roundtrip_efficiency)
    next_soc = soc_kwh + hours * (efficiency * max(power_kw, 0) - max(-power_kw, 0) / efficiency)
    if not min_soc_kwh - 1e-9 <= next_soc <= capacity_kwh + 1e-9:
        raise ValueError("battery action would exceed state-of-charge bounds")
    return min(capacity_kwh, max(min_soc_kwh, next_soc))
