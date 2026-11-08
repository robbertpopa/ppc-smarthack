"""Hourly Romanian day-ahead (PZU) prices: fetch, store, load, and align to the Ausgrid year."""

import argparse
import json
import os
import urllib.request
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

BASE_URL = "https://euenergy.live/api/v1/prices"
ZONE = "RO"
USER_AGENT = "ppc-smarthack/0.1"  # the API's firewall refuses Python's default client name
BUCHAREST = "Europe/Bucharest"
SYDNEY = "Australia/Sydney"
MAX_GAP_HOURS = 3
SEASON_SHIFT_MONTHS = 6  # Sydney July is winter, Bucharest January is winter


def prices_path(data_dir: str | None = None) -> Path:
    return Path(data_dir or os.environ.get("DATA_DIR", "./data")) / "pzu" / "ro.parquet"


def parse_response(payload: dict) -> pd.Series:
    """One API response to a UTC-indexed series in EUR/MWh."""
    rows = payload.get("hours")
    if not isinstance(rows, list):
        raise ValueError("the response has no 'hours' list")
    if payload.get("unit") != "EUR/MWh":
        raise ValueError(f"unexpected price unit {payload.get('unit')!r}")
    index = pd.DatetimeIndex(pd.to_datetime([r["ts"] for r in rows], utc=True))
    series = pd.Series([float(r["price"]) for r in rows], index=index, dtype=float)
    return series[~series.index.duplicated(keep="last")].sort_index()


def http_get(url: str, token: str, timeout: float = 30) -> dict:
    headers = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def month_ranges(year: int) -> list[tuple[str, str]]:
    """Month by month, as (first day, first day of the next month)."""
    edges = [f"{year}-{m:02d}-01" for m in range(1, 13)] + [f"{year + 1}-01-01"]
    return list(zip(edges[:-1], edges[1:], strict=True))


def fetch_year(year: int, token: str, get: Callable[[str, str], dict] = http_get) -> pd.Series:
    parts = []
    for start, end in month_ranges(year):
        parts.append(parse_response(get(f"{BASE_URL}?zone={ZONE}&from={start}&to={end}", token)))
    series = pd.concat(parts)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    lo = pd.Timestamp(f"{year}-01-01", tz="UTC")
    hi = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
    return series[(series.index >= lo) & (series.index < hi)]


def save(series: pd.Series, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ts": series.index, "price_eur_mwh": series.to_numpy()}).to_parquet(
        path, index=False
    )


def load(path: Path | None = None) -> pd.Series:
    """The saved year on a complete hourly grid. Gaps up to 3 h carry the last price."""
    path = path or prices_path()
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found: run `python -m src.pricing.prices fetch --year 2025`"
        )
    frame = pd.read_parquet(path)
    series = pd.Series(
        frame["price_eur_mwh"].to_numpy(), index=pd.DatetimeIndex(frame["ts"]).tz_convert("UTC")
    ).sort_index()
    grid = pd.date_range(series.index.min(), series.index.max(), freq="h")
    return series.reindex(grid).ffill(limit=MAX_GAP_HOURS)


def profile(series: pd.Series) -> pd.Series:
    """Mean price for every (month, hour of day) in Bucharest time."""
    local = series.index.tz_convert(BUCHAREST)
    table = series.groupby([local.month, local.hour]).mean()
    table.index = table.index.set_names(["month", "hour"])
    if len(table.dropna()) != 12 * 24:
        raise ValueError("the price year must cover every month and every hour of the day")
    return table


def monthly_average(table: pd.Series) -> pd.Series:
    """Mean price of each Bucharest month: the regulated price prosumers get today."""
    return table.groupby(level="month").mean()


def _season_keys(intervals: pd.DatetimeIndex, tz: str, month_shift: int):
    local = intervals.tz_convert(tz)
    return np.asarray((local.month - 1 + month_shift) % 12 + 1), np.asarray(local.hour)


def align(
    intervals: pd.DatetimeIndex,
    table: pd.Series,
    tz: str = SYDNEY,
    month_shift: int = SEASON_SHIFT_MONTHS,
) -> pd.Series:
    """Wholesale price (EUR/MWh) for each interval, by local clock hour and matching season."""
    month, hour = _season_keys(intervals, tz, month_shift)
    keys = pd.MultiIndex.from_arrays([month, hour])
    return pd.Series(table.reindex(keys).to_numpy(), index=intervals, name="wholesale_eur_mwh")


def align_monthly(
    intervals: pd.DatetimeIndex,
    by_month: pd.Series,
    tz: str = SYDNEY,
    month_shift: int = SEASON_SHIFT_MONTHS,
) -> pd.Series:
    """A per-month value (indexed 1..12) for each interval, by matching season."""
    month, _ = _season_keys(intervals, tz, month_shift)
    return pd.Series(by_month.reindex(month).to_numpy(), index=intervals)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.pricing.prices")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="download one year of hourly RO prices")
    fetch.add_argument("--year", type=int, required=True)
    args = parser.parse_args(argv)
    token = os.environ.get("EUENERGY_TOKEN")
    if not token:
        raise SystemExit("set EUENERGY_TOKEN (see README, section 10)")
    series = fetch_year(args.year, token)
    save(series, prices_path())
    print(f"saved {len(series)} hourly prices for {args.year} to {prices_path()}")


if __name__ == "__main__":
    main()
