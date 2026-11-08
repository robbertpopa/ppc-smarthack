"""Wholesale price and solar adder at a time, for the agent and the screen."""

from datetime import datetime

import pandas as pd

from src.common.config import Settings
from src.pricing import prices, solar

# An illustrative day (Bucharest hours 0 to 23): low at midday, high in the evening.
MOCK_CURVE_EUR_MWH = (
    85, 80, 78, 76, 80, 95, 120, 130, 100, 60, 35, 20,
    15, 15, 25, 45, 80, 130, 165, 170, 150, 125, 105, 90,
)  # fmt: skip


class PriceSource:
    def __init__(self, table: pd.Series, series: pd.Series | None = None, mock: bool = False):
        self.table = table
        self.series = series
        self.mock = mock
        self.adders = solar.monthly_adder(table)

    def wholesale(self, when: datetime) -> float | None:
        """EUR/MWh for the hour of ``when``: the real price if known, else the profile."""
        hour = pd.Timestamp(when).tz_convert("UTC").floor("h")
        if self.series is not None and hour in self.series.index:
            value = self.series.loc[hour]
            if pd.notna(value):
                return float(value)
        local = hour.tz_convert(prices.BUCHAREST)
        value = self.table.get((local.month, local.hour))
        return None if value is None or pd.isna(value) else float(value)

    def adder(self, when: datetime) -> float:
        """The solar adder (EUR/MWh) of the Bucharest month of ``when``."""
        month = pd.Timestamp(when).tz_convert(prices.BUCHAREST).month
        return float(self.adders.loc[month])

    def day_curve(self, day: datetime) -> list[dict]:
        """The 24 UTC hours of the day of ``day``."""
        start = pd.Timestamp(day).tz_convert("UTC").floor("D")
        points = [start + pd.Timedelta(hours=h) for h in range(24)]
        return [{"ts": t.isoformat(), "wholesale_eur_mwh": self.wholesale(t)} for t in points]


def mock_source() -> PriceSource:
    index = pd.MultiIndex.from_product([range(1, 13), range(24)], names=["month", "hour"])
    table = pd.Series([float(MOCK_CURVE_EUR_MWH[h]) for _, h in index], index=index)
    return PriceSource(table, mock=True)


def price_source_for(settings: Settings) -> PriceSource:
    """Real prices when ``SOURCE`` is not ``mock`` and the file exists, else the mock curve."""
    path = prices.prices_path(settings.data_dir)
    if settings.source == "mock" or not path.exists():
        return mock_source()
    series = prices.load(path)
    return PriceSource(prices.profile(series), series)
