"""The monthly solar adder: today's regulated overpayment, published as a per-MWh amount.

Prosumers inject at midday, when prices are lowest, but are paid the monthly average. The
gap between that average and the generation-weighted price is the adder. It is computed from
public prices and a standard solar shape, so it is the same for everyone and does not depend
on what one prosumer does (which keeps the incentive to shift energy to the evening).
"""

import math
from datetime import date

import numpy as np
import pandas as pd

LATITUDE = 44.4  # Bucharest
LONGITUDE = 26.1
ZONE_MERIDIAN = 30.0  # EET


def solar_weights(month: int) -> np.ndarray:
    """Share of a mid-month day's generation in each local clock hour (24 values, sum 1)."""
    doy = date(2025, month, 15).timetuple().tm_yday
    decl = math.radians(23.44) * math.sin(2 * math.pi * (284 + doy) / 365)
    lat = math.radians(LATITUDE)
    length = 2 * math.degrees(math.acos(-math.tan(lat) * math.tan(decl))) / 15
    dst = 4 <= month <= 10
    noon = 12 + (ZONE_MERIDIAN - LONGITUDE) * 4 / 60 + (1 if dst else 0)
    weights = []
    for hour in range(24):
        x = (hour + 0.5 - (noon - length / 2)) / length
        weights.append(math.sin(math.pi * x) if 0 < x < 1 else 0.0)
    values = np.array(weights)
    return values / values.sum()


def monthly_adder(table: pd.Series) -> pd.Series:
    """EUR/MWh per Bucharest month: the month's average price minus its solar-weighted price.

    ``table`` is the (month, hour) price profile from ``prices.profile``. A month where the
    solar hours cost more than the average (January) would give a negative number; the adder
    is floored at 0 so that it never lowers the hourly price.
    """
    values = {}
    for month in range(1, 13):
        hourly = table.xs(month, level="month").reindex(range(24)).to_numpy(dtype=float)
        gap = float(np.mean(hourly) - np.dot(solar_weights(month), hourly))
        values[month] = max(0.0, gap)
    return pd.Series(values, name="adder_eur_mwh").rename_axis("month")
