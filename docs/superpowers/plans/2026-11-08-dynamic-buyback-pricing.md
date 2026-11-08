# Prosumer aggregator price Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let PPC offer battery owners an opt-in price for injected energy (hourly day-ahead price minus a fee, plus a monthly solar adder), measure what prosumers and PPC gain, show the price per house in the agent API and the operator screen, and value the imbalance savings of the PV/load forecast.

**Architecture:** A new `src/pricing/` package holds the pure parts (prices, tariff, solar adder, settlement, battery dispatch, imbalance). The evaluation (`src/eval/`) reads it to produce a `pricing` block per scenario. The agent (`src/agent/`) attaches a `HousePrice` per house to each plan, and the screen (`src/ui/`) shows it. The safe-cap model is never touched. Grid data never enters the price (unbundling).

**Tech Stack:** Python 3.12, pandas, numpy, pydantic, FastAPI, pytest, ruff; plain JS in `src/ui/static/index.html`.

Spec: [docs/superpowers/specs/2026-11-08-dynamic-buyback-pricing-design.md](../specs/2026-11-08-dynamic-buyback-pricing-design.md). Background and the simulated year: [docs/14-prosumers-and-pricing.md](../../14-prosumers-and-pricing.md).

**Every code block below was run before it was written here:** the four phases were built in a scratch worktree, `make test lint smoke` passed (439 tests), and the screen was loaded in a browser with the demo API.

---

## Rules for every task (team rules, from [docs/11-commit-plan.md](../../11-commit-plan.md))

- **Commits:** conventional (`feat(pricing): …`, `test(…)`, `docs: …`), imperative, English. **No trailers** (no `Co-Authored-By`, no "Generated with"): this overrides tool defaults. One logical change per commit, tests in the same commit. Every commit passes `make test lint smoke`.
- **Never commit** `data/`, `.env`, tokens, parquet files, `local-notes/`. `EUENERGY_TOKEN` lives in the gitignored `.env`; export it with `set -a; . ./.env; set +a`.
- **Push, open a PR, merge: ask the user first.** Each "yes" covers one action. Commit locally on the phase branch.
- **Branches:** one per phase, cut from an up-to-date `main`: `pricing/core`, `pricing/imbalance`, `pricing/api`, `pricing/ui`. Phase 2 and 3 need phase 1 merged; phase 4 needs phase 3. The docs branch `docs/dynamic-buyback-pricing-design` holds this plan; merge it first or copy the docs.
- **Ownership:** phase 3 edits `src/common/` and `src/agent/` (P1). Phases 1 and 2 edit `src/eval/` (P2/P6 are also changing it): `git switch main && git pull` and rebase before opening the PR. Name the owner in the PR description.
- **README rule:** a step that changes how the project runs updates `README.md` in the same PR (each phase ends with that task).
- Run Python as `.venv/bin/python -m …`; the Makefile does the same. Line length is 100 (ruff).
- **Do not claim the result in advance.** Whatever the real-data run shows, report it, including if the prosumer gains little or PPC's margin stays negative.

## What the numbers mean (read before changing a default)

- `fee_eur_mwh = 30`, `floor_eur_mwh = 0`, `bonus_share = 0.5` are placeholders. The sensitivity table (fee 0–50) shows how the split moves.
- The **solar adder** is the month's average price minus its solar-weighted price, floored at 0, from a standard solar shape (Bucharest latitude). A prosumer whose real profile differs from that shape is not exactly neutral.
- The Ausgrid data is Sydney. Prices are matched by season (Sydney month + 6) and local clock hour.
- Imbalance spreads (30/60/120 EUR/MWh) are scenario values, not market data. The saving assumes PPC can correct its position on the intraday market about an hour ahead.
- `docs/14` has a stylised one-household simulation (+19% prosumer at fee 30, +29% with the imbalance bonus). The evaluation here runs on the repository's station and will give different numbers. Use the evaluation's numbers on slides.

## File structure

| File | Responsibility | Phase |
|---|---|---|
| `src/pricing/config.py` | `PricingConfig`: fee, floor, bonus share | 1 |
| `src/pricing/tariff.py` | hourly price rule, scalar and series | 1 |
| `src/pricing/prices.py` | fetch, save, load, profile, align PZU prices; CLI `fetch` | 1 |
| `src/pricing/solar.py` | solar weights, monthly adder | 1 |
| `src/pricing/settlement.py` | what a group is paid, PPC's margin | 1 |
| `src/pricing/battery.py` | pure battery dispatch for one house | 1 |
| `src/eval/pricing_eval.py` | the `pricing` block, markdown, chart | 1, 2 |
| `src/eval/run.py`, `src/smoke.py`, `README.md` | `--pricing` flag, smoke check, docs | 1, 2 |
| `src/pricing/imbalance.py` | imbalance volume, cost, saving, bonus split | 2 |
| `src/eval/imbalance_eval.py` | net-export forecasts and the savings | 2 |
| `src/common/contract.py`, `docs/09-contract.md` | `HousePrice`, `Plan.prices` | 3 |
| `src/pricing/source.py` | wholesale price and adder at a time; mock curve | 3 |
| `src/agent/planner.py`, `service.py`, `wiring.py`, `api.py`, `src/grid/demo_api.py` | prices in plans, `GET /prices` | 3 |
| `src/ui/app.py`, `src/ui/static/index.html` | allow `prices`; "Prices" tab | 3, 4 |

---

# Phase 1: prices, tariff, solar adder, battery, evaluation (branch `pricing/core`)

### Task 1: Config and the hourly price rule

**Files:** create `src/pricing/__init__.py` (empty), `src/pricing/config.py`, `src/pricing/tariff.py`; test `tests/pricing/test_tariff.py`.

- [ ] **Step 1: Branch and failing test**

```bash
git switch main && git pull && git switch -c pricing/core
mkdir -p src/pricing tests/pricing && touch src/pricing/__init__.py
```

`tests/pricing/test_tariff.py`:

```python
import numpy as np
import pandas as pd
import pytest

from src.pricing.config import PricingConfig
from src.pricing.tariff import hourly_price, hourly_price_series


def test_hourly_price_is_wholesale_minus_fee_with_a_floor():
    cfg = PricingConfig(fee_eur_mwh=30.0, floor_eur_mwh=0.0)
    assert hourly_price(100.0, cfg) == 70.0
    assert hourly_price(20.0, cfg) == 0.0  # fee would push it below zero: floor applies
    assert hourly_price(-50.0, cfg) == 0.0
    assert hourly_price(20.0, PricingConfig(fee_eur_mwh=30.0, floor_eur_mwh=5.0)) == 5.0


def test_bad_inputs_are_refused():
    with pytest.raises(ValueError):
        hourly_price(float("nan"))
    for bad in ({"fee_eur_mwh": -1}, {"floor_eur_mwh": -1}, {"bonus_share": 1.5}):
        with pytest.raises(ValueError):
            PricingConfig(**bad)


def test_series_matches_scalar_and_keeps_gaps():
    wholesale = pd.Series([100.0, -5.0, np.nan, 20.0])
    out = hourly_price_series(wholesale)
    assert out.iloc[0] == hourly_price(100.0) and out.iloc[1] == 0.0
    assert np.isnan(out.iloc[2]) and out.iloc[3] == 0.0
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/python -m pytest tests/pricing/test_tariff.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.pricing.config'`.

- [ ] **Step 3: Implement**

`src/pricing/config.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class PricingConfig:
    """Placeholders: none of these values is claimed as correct (see the spec)."""

    fee_eur_mwh: float = 30.0
    floor_eur_mwh: float = 0.0
    bonus_share: float = 0.5

    def __post_init__(self):
        if self.fee_eur_mwh < 0 or self.floor_eur_mwh < 0:
            raise ValueError("fee and floor must not be negative")
        if not 0 <= self.bonus_share <= 1:
            raise ValueError("bonus_share must be between 0 and 1")
```

`src/pricing/tariff.py`:

```python
import math

import pandas as pd

from src.pricing.config import PricingConfig

DEFAULT = PricingConfig()


def hourly_price(wholesale_eur_mwh: float, cfg: PricingConfig = DEFAULT) -> float:
    """What PPC pays for one MWh in an hour: day-ahead price minus the fee, not below the floor."""
    if not math.isfinite(wholesale_eur_mwh):
        raise ValueError("the wholesale price must be a finite number")
    return max(cfg.floor_eur_mwh, wholesale_eur_mwh - cfg.fee_eur_mwh)


def hourly_price_series(wholesale_eur_mwh: pd.Series, cfg: PricingConfig = DEFAULT) -> pd.Series:
    """Same rule over a series; a missing price stays missing."""
    return (wholesale_eur_mwh - cfg.fee_eur_mwh).clip(lower=cfg.floor_eur_mwh)
```

- [ ] **Step 4: Run it to see it pass**

Run: `.venv/bin/python -m pytest tests/pricing/test_tariff.py -q && .venv/bin/python -m ruff check src tests`
Expected: `3 passed`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/pricing tests/pricing
git commit -m "feat(pricing): add the hourly price rule"
```

---

### Task 2: Fetch, load and align the PZU prices

**Files:** create `src/pricing/prices.py`; test `tests/pricing/test_prices.py`.

The API: `GET https://euenergy.live/api/v1/prices?zone=RO&from=YYYY-MM-DD&to=YYYY-MM-DD` with `Authorization: Bearer <token>` returns `{"unit": "EUR/MWh", "hours": [{"ts": "2025-06-01T00:00:00.000Z", "price": 79.58, "currency": "EUR"}, …]}`. Hours can be missing, so never assume 24 rows a day. **Python's default client name is refused by the API's firewall (HTTP 403, while `curl` works): `http_get` sends a `User-Agent`.** Whether `to` is inclusive is unknown, so the code requests `[first of month, first of next month]`, drops duplicates and cuts to the year.

- [ ] **Step 1: Failing test**

`tests/pricing/test_prices.py`:

```python
import numpy as np
import pandas as pd
import pytest

from src.pricing import prices


def payload(day, rows, unit="EUR/MWh"):
    return {
        "unit": unit,
        "hours": [
            {"ts": f"{day}T{h:02d}:00:00.000Z", "price": p, "currency": "EUR"} for h, p in rows
        ],
    }


def fake_year(year=2025):
    idx = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", tz="UTC", inclusive="left")
    return pd.Series(np.arange(len(idx), dtype=float) % 100, index=idx)


def test_parse_drops_duplicates_and_checks_unit():
    series = prices.parse_response(payload("2024-01-01", [(0, 1.0), (1, 2.0), (1, 3.0), (5, 4.0)]))
    assert list(series) == [1.0, 3.0, 4.0] and str(series.index.tz) == "UTC"
    with pytest.raises(ValueError):
        prices.parse_response(payload("2024-01-01", [], unit="RON/MWh"))
    with pytest.raises(ValueError):
        prices.parse_response({})


def test_http_get_sends_a_token_and_a_user_agent(monkeypatch):
    seen = {}

    class Reply:
        def read(self):
            return b'{"hours": []}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        seen["request"] = request
        return Reply()

    monkeypatch.setattr(prices.urllib.request, "urlopen", fake_urlopen)
    assert prices.http_get("https://example.test/p", "tok") == {"hours": []}
    assert seen["request"].get_header("Authorization") == "Bearer tok"
    assert seen["request"].get_header("User-agent") == prices.USER_AGENT


def test_fetch_year_and_round_trip(tmp_path):
    full = fake_year()

    def get(url, token):
        assert token == "t" and "zone=RO" in url
        lo = pd.Timestamp(url.split("from=")[1].split("&")[0], tz="UTC")
        hi = pd.Timestamp(url.split("to=")[1], tz="UTC")
        part = full[(full.index >= lo) & (full.index <= hi)]
        rows = [{"ts": t.isoformat(), "price": float(p)} for t, p in part.items()]
        return {"unit": "EUR/MWh", "hours": rows}

    got = prices.fetch_year(2025, "t", get)
    assert len(got) == len(full) and got.index.is_unique
    path = tmp_path / "pzu" / "ro.parquet"
    prices.save(got, path)
    loaded = prices.load(path)
    assert len(loaded) == len(full) and loaded.isna().sum() == 0


def test_load_fills_short_gaps_only(tmp_path):
    full = fake_year()
    holes = full.drop(full.index[10:12]).drop(full.index[100:106])
    path = tmp_path / "ro.parquet"
    prices.save(holes, path)
    loaded = prices.load(path)
    assert loaded.iloc[10:12].notna().all()
    assert loaded.iloc[100:103].notna().all() and loaded.iloc[103:106].isna().all()


def test_missing_file_says_how_to_fetch(tmp_path):
    with pytest.raises(FileNotFoundError, match="prices fetch"):
        prices.load(tmp_path / "none.parquet")


def test_cli_needs_the_token(monkeypatch):
    monkeypatch.delenv("EUENERGY_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="EUENERGY_TOKEN"):
        prices.main(["fetch", "--year", "2025"])


def test_profile_covers_every_month_and_hour():
    table = prices.profile(fake_year())
    assert table.shape == (288,) and list(table.index.names) == ["month", "hour"]
    with pytest.raises(ValueError):
        prices.profile(fake_year()[:2000])


def test_align_pairs_opposite_seasons_and_local_hours():
    table = prices.profile(fake_year())
    winter = pd.Timestamp("2012-07-01 12:00", tz="Australia/Sydney")
    summer = pd.Timestamp("2013-01-15 12:30", tz="Australia/Sydney")
    when = pd.DatetimeIndex([winter, summer]).tz_convert("UTC")
    out = prices.align(when, table)
    assert out.iloc[0] == table.loc[(1, 12)]  # Sydney July -> Bucharest January
    assert out.iloc[1] == table.loc[(7, 12)]  # Sydney January -> Bucharest July
    assert list(out.index) == list(when)


def test_monthly_average_and_its_alignment():
    table = prices.profile(fake_year())
    monthly = prices.monthly_average(table)
    assert monthly.shape == (12,) and monthly.loc[3] == pytest.approx(table.loc[3].mean())
    when = pd.DatetimeIndex([pd.Timestamp("2012-07-01 12:00", tz="Australia/Sydney")])
    aligned = prices.align_monthly(when.tz_convert("UTC"), monthly)
    assert aligned.iloc[0] == monthly.loc[1]
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/python -m pytest tests/pricing/test_prices.py -q`
Expected: FAIL, `cannot import name 'prices'`.

- [ ] **Step 3: Implement**

`src/pricing/prices.py`:

```python
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
```

- [ ] **Step 4: Run it to see it pass**

Run: `.venv/bin/python -m pytest tests/pricing -q && .venv/bin/python -m ruff check src tests`
Expected: all pass, clean.

- [ ] **Step 5: Commit**

```bash
git add src/pricing/prices.py tests/pricing/test_prices.py
git commit -m "feat(pricing): fetch, load and align hourly Romanian day-ahead prices"
```

---

### Task 3: The solar adder

**Files:** create `src/pricing/solar.py`; test `tests/pricing/test_solar.py`.

Prosumers inject at midday, when prices are lowest, but are paid the monthly average. The gap is today's regulated overpayment. The adder publishes it as a per-MWh amount that is the same for everyone, so it does not dull a single prosumer's incentive to shift energy to the evening.

- [ ] **Step 1: Failing test**

`tests/pricing/test_solar.py`:

```python
import numpy as np
import pandas as pd
import pytest

from src.pricing import prices, solar


def table_from(hourly_by_month):
    index = pd.MultiIndex.from_product([range(1, 13), range(24)], names=["month", "hour"])
    return pd.Series([hourly_by_month(m, h) for m, h in index], index=index, dtype=float)


def test_weights_sum_to_one_and_peak_at_midday():
    for month in (1, 6, 12):
        w = solar.solar_weights(month)
        assert w.sum() == pytest.approx(1.0) and (w >= 0).all()
        assert 12 <= int(np.argmax(w)) <= 14
        assert w[:4].sum() == 0 and w[-3:].sum() == 0  # night
    assert solar.solar_weights(6).nonzero()[0].size > solar.solar_weights(12).nonzero()[0].size


def test_flat_prices_give_no_adder():
    adder = solar.monthly_adder(table_from(lambda m, h: 100.0))
    assert adder.shape == (12,) and np.allclose(adder, 0.0)


def test_cheap_midday_gives_a_positive_adder_and_dear_midday_none():
    duck = table_from(lambda m, h: 30.0 if 10 <= h < 16 else 150.0)
    assert (solar.monthly_adder(duck) > 30).all()
    inverted = table_from(lambda m, h: 200.0 if 10 <= h < 16 else 100.0)
    assert (solar.monthly_adder(inverted) == 0.0).all()  # floored at zero


def test_adder_on_the_price_year_helper():
    idx = pd.date_range("2025-01-01", "2026-01-01", freq="h", tz="UTC", inclusive="left")
    series = pd.Series(100.0, index=idx)
    assert (solar.monthly_adder(prices.profile(series)) == 0).all()
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/python -m pytest tests/pricing/test_solar.py -q`
Expected: FAIL, `cannot import name 'solar'`.

- [ ] **Step 3: Implement**

`src/pricing/solar.py`:

```python
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
```

- [ ] **Step 4: Run it to see it pass**

Run: `.venv/bin/python -m pytest tests/pricing -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/pricing/solar.py tests/pricing/test_solar.py
git commit -m "feat(pricing): compute the monthly solar adder"
```

---

### Task 4: Settlement

**Files:** create `src/pricing/settlement.py`; test `tests/pricing/test_settlement.py`.

- [ ] **Step 1: Failing test**

`tests/pricing/test_settlement.py`:

```python
import numpy as np
import pandas as pd
import pytest

from src.pricing.config import PricingConfig
from src.pricing.settlement import settle


def test_settlement_by_hand():
    idx = pd.date_range("2025-01-01", periods=3, freq="30min", tz="UTC")
    kwh = pd.Series([1000.0, 2000.0, 4000.0], index=idx)
    wholesale = pd.Series([100.0, 200.0, np.nan], index=idx)
    monthly = pd.Series(150.0, index=idx)
    adder = pd.Series(40.0, index=idx)
    out = settle(kwh, wholesale, monthly, adder, PricingConfig(fee_eur_mwh=30.0))
    assert out["exported_kwh"] == 3000.0 and out["n_without_price"] == 1
    assert out["regulated_eur"] == pytest.approx(3 * 150.0)
    assert out["hourly_eur"] == pytest.approx(1 * 70.0 + 2 * 170.0)
    assert out["adder_eur"] == pytest.approx(3 * 40.0)
    assert out["paid_eur"] == pytest.approx(out["hourly_eur"] + out["adder_eur"])
    assert out["value_eur"] == pytest.approx(1 * 100.0 + 2 * 200.0)
    assert out["ppc_margin_regulated_eur"] == pytest.approx(500.0 - 450.0)
    assert out["ppc_margin_paid_eur"] == pytest.approx(500.0 - out["paid_eur"])


def test_empty_series_settles_to_zero():
    idx = pd.DatetimeIndex([], tz="UTC")
    empty = pd.Series([], index=idx, dtype=float)
    out = settle(empty, empty, empty, empty)
    assert out["exported_kwh"] == 0.0 and out["paid_eur"] == 0.0
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/python -m pytest tests/pricing/test_settlement.py -q`
Expected: FAIL, `No module named 'src.pricing.settlement'`.

- [ ] **Step 3: Implement**

`src/pricing/settlement.py`:

```python
import pandas as pd

from src.pricing.config import PricingConfig
from src.pricing.tariff import DEFAULT, hourly_price_series


def settle(
    exported_kwh: pd.Series,
    wholesale_eur_mwh: pd.Series,
    monthly_avg_eur_mwh: pd.Series,
    adder_eur_mwh: pd.Series,
    cfg: PricingConfig = DEFAULT,
) -> dict:
    """What a prosumer is paid for the exported energy, and what PPC's side of it is worth.

    ``regulated_eur``: today, the monthly average on every kWh. ``hourly_eur``: the hourly
    price (day-ahead minus fee, not below the floor). ``paid_eur``: hourly plus the solar adder.
    ``value_eur``: the day-ahead value of the same energy, what PPC does not have to buy.
    Intervals without a price are dropped and counted. All inputs share one index.
    """
    index = exported_kwh.index
    wholesale = wholesale_eur_mwh.reindex(index)
    monthly = monthly_avg_eur_mwh.reindex(index)
    adder = adder_eur_mwh.reindex(index)
    ok = wholesale.notna() & monthly.notna() & adder.notna()
    kwh = exported_kwh[ok]
    regulated = float((kwh * monthly[ok]).sum()) / 1000
    hourly = float((kwh * hourly_price_series(wholesale[ok], cfg)).sum()) / 1000
    extra = float((kwh * adder[ok]).sum()) / 1000
    value = float((kwh * wholesale[ok]).sum()) / 1000
    return {
        "exported_kwh": float(kwh.sum()),
        "n_without_price": int((~ok).sum()),
        "regulated_eur": regulated,
        "hourly_eur": hourly,
        "adder_eur": extra,
        "paid_eur": hourly + extra,
        "value_eur": value,
        "ppc_margin_regulated_eur": value - regulated,
        "ppc_margin_paid_eur": value - hourly - extra,
    }
```

- [ ] **Step 4: Run it to see it pass**

Run: `.venv/bin/python -m pytest tests/pricing -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/pricing/settlement.py tests/pricing/test_settlement.py
git commit -m "feat(pricing): settle what a group is paid and PPC's margin"
```

---

### Task 5: Battery dispatch

**Files:** create `src/pricing/battery.py`; test `tests/pricing/test_battery.py`.

The battery stores from the cheapest solar hours (and everything the cap would waste) and sells in the best evening hours (18–22 local) if that pays after the round-trip loss. It stays idle where the agent fell back. Its defaults equal those of `src.grid.battery.step`; a test checks that.

- [ ] **Step 1: Failing test**

`tests/pricing/test_battery.py`:

```python
import inspect
import math

import numpy as np
import pandas as pd
import pytest

from src.grid.battery import step
from src.pricing.battery import BatteryParams, battery_houses, dispatch

FEE = 30.0


def frame(days=2, surplus_kw=6.0, cap_kw=4.0):
    idx = pd.date_range("2025-06-21 00:00", periods=48 * days, freq="30min", tz="Australia/Sydney")
    idx = idx.tz_convert("UTC")
    hour = idx.tz_convert("Australia/Sydney").hour
    surplus = pd.Series(np.where((hour >= 9) & (hour < 16), surplus_kw, 0.0), index=idx)
    price = pd.Series(np.where((hour >= 18) & (hour < 22), 200.0, 40.0), index=idx)
    cap = pd.Series(cap_kw, index=idx)
    active = pd.Series(True, index=idx)
    return price, surplus, cap, active


def plain(surplus, cap):
    return np.minimum(surplus, cap)


def test_defaults_match_the_grid_battery_model():
    defaults = {k: v.default for k, v in inspect.signature(step).parameters.items()}
    p = BatteryParams()
    assert (p.capacity_kwh, p.min_soc_kwh) == (defaults["capacity_kwh"], defaults["min_soc_kwh"])
    assert p.max_power_kw == defaults["max_power_kw"]
    assert p.roundtrip_efficiency == defaults["roundtrip_efficiency"]


def test_never_exceeds_cap_or_power_and_is_empty_each_night():
    price, surplus, cap, active = frame()
    out = dispatch(price, surplus, cap, active, FEE)
    assert (out["export_kw"] <= cap + 1e-9).all()
    assert out["battery_kw"].abs().max() <= 5.0 + 1e-9
    day = out.index.tz_convert("Australia/Sydney").date
    charged = out["battery_kw"].clip(lower=0).groupby(day).sum() * 0.5
    sold = (-out["battery_kw"]).clip(lower=0).groupby(day).sum() * 0.5
    assert (charged > 0).all()
    assert np.allclose(sold, 0.9 * charged)  # everything stored is sold, minus the loss
    assert (charged * math.sqrt(0.9) <= 9.0 + 1e-6).all()  # within the usable 9 kWh


def test_stores_at_midday_and_sells_in_the_evening():
    price, surplus, cap, active = frame()
    out = dispatch(price, surplus, cap, active, FEE)
    assert (out["battery_kw"][surplus > 0] > 0).any()
    evening = out[price > 100]
    assert (evening["battery_kw"] < 0).any() and (evening["export_kw"] > 0).any()


def test_earns_more_than_no_battery_and_keeps_energy_balance():
    price, surplus, cap, active = frame()
    out = dispatch(price, surplus, cap, active, FEE)
    base = plain(surplus, cap) * 0.5
    with_battery = out["export_kw"] * 0.5
    assert (with_battery * price).sum() > (base * price).sum()
    assert with_battery.sum() <= surplus.sum() * 0.5 + 1e-9


def test_stores_what_the_cap_would_waste_even_at_a_low_evening_price():
    price, surplus, cap, active = frame(days=1, surplus_kw=6.0, cap_kw=2.0)
    price[:] = 40.0
    price[(price.index.tz_convert("Australia/Sydney").hour >= 18)] = 80.0
    out = dispatch(price, surplus, cap, active, FEE)
    assert out["export_kw"].sum() * 0.5 > plain(surplus, cap).sum() * 0.5


def test_idle_when_the_agent_fell_back_and_when_nothing_pays():
    price, surplus, cap, active = frame()
    out = dispatch(price, surplus, cap, active & False, FEE)
    assert (out["battery_kw"] == 0).all()
    assert np.allclose(out["export_kw"], plain(surplus, cap))
    flat = price * 0 + 100.0
    idle = dispatch(flat, surplus, pd.Series(10.0, index=price.index), active, FEE)
    assert (idle["battery_kw"] == 0).all()  # round-trip loss makes shifting a loss


def test_inputs_must_share_an_index_and_houses_are_a_fixed_choice():
    price, surplus, cap, active = frame()
    with pytest.raises(ValueError):
        dispatch(price, surplus.iloc[1:], cap, active, FEE)
    assert battery_houses(["H03", "H01", "H02", "H04"]) == ["H01", "H02"]
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/python -m pytest tests/pricing/test_battery.py -q`
Expected: FAIL, `No module named 'src.pricing.battery'`.

- [ ] **Step 3: Implement**

`src/pricing/battery.py`:

```python
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
```

- [ ] **Step 4: Run it to see it pass**

Run: `.venv/bin/python -m pytest tests/pricing -q && .venv/bin/python -m ruff check src tests`
Expected: `25 passed`, clean.

- [ ] **Step 5: Commit**

```bash
git add src/pricing/battery.py tests/pricing/test_battery.py
git commit -m "feat(pricing): add price-driven battery dispatch"
```

---

### Task 6: The evaluation block

**Files:** create `src/eval/pricing_eval.py`; test `tests/eval/test_pricing_eval.py`.

For the houses with a battery (the first 30% in sorted order) it settles four prices: today's regulated monthly average, the hourly price alone, hourly plus adder, and hourly plus adder with the battery responding. It also runs a fee sensitivity (0–50 EUR/MWh) and writes a markdown table and a summer-day chart. `compute` needs `ctx["surplus"]` and `ctx["kwp"]` from `src/eval/run.py` and `result["scored"]["fallback"]` and `["abstain"]`; it returns `None` without a surplus table.

- [ ] **Step 1: Failing test**

`tests/eval/test_pricing_eval.py`:

```python
import json

import numpy as np
import pandas as pd
import pytest

from src.eval import pricing_eval
from src.pricing import prices


def duck_year(year=2025):
    """A year of prices: cheap at midday, dear in the evening, so the adder and shifting pay."""
    idx = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", tz="UTC", inclusive="left")
    hour = idx.tz_convert("Europe/Bucharest").hour
    evening = np.where((hour >= 18) & (hour < 22), 220.0, 120.0)
    price = np.where((hour >= 10) & (hour < 16), 40.0, evening)
    return pd.Series(price, index=idx)


def make(days=4):
    idx = pd.date_range("2013-01-14", periods=48 * days, freq="30min", tz="UTC")
    hour = idx.tz_convert("Australia/Sydney").hour
    sun = np.where((hour >= 9) & (hour < 16), 8.0, 0.0)
    surplus = pd.DataFrame({"H1": sun, "H2": sun * 0.5, "H3": sun}, index=idx)
    kwp = pd.Series({"H1": 10.0, "H2": 5.0, "H3": 10.0})
    abstain = pd.Series(False, index=idx)
    abstain.iloc[:48] = True  # the first day falls back to the fixed limit
    share = pd.Series(0.5, index=idx).where(~abstain, 0.36)
    ctx = {"surplus": surplus, "kwp": kwp}
    result = {"scored": {"fallback": share, "abstain": abstain}}
    return ctx, result


@pytest.fixture(scope="module")
def table():
    return prices.profile(duck_year())


def test_block_shape_and_signs(table):
    ctx, result = make()
    block = pricing_eval.compute(ctx, result, table)
    assert block["battery_houses"] == ["H1"]  # ceil(0.3 * 3) = 1, first in sorted order
    names = [r["name"] for r in block["rows"]]
    assert names[0] == "Today: regulated monthly average" and "proposed" in names[-1]
    today, hourly, adder, proposed = block["rows"]
    assert today["prosumer_vs_today_pct"] == 0.0 and today["ppc_improvement_eur"] == 0.0
    assert today["ppc_margin_eur"] < 0  # PPC pays the monthly average for cheap midday energy
    assert hourly["prosumer_eur"] < today["prosumer_eur"]  # no adder: the prosumer loses
    assert adder["prosumer_eur"] > hourly["prosumer_eur"]
    assert proposed["prosumer_eur"] > adder["prosumer_eur"]  # the battery adds revenue
    assert proposed["ppc_improvement_eur"] > 0
    assert [s["fee_eur_mwh"] for s in block["sensitivity"]] == [0, 10, 20, 30, 40, 50]
    json.dumps(block, allow_nan=False)


def test_a_higher_fee_moves_value_from_prosumer_to_ppc(table):
    ctx, result = make()
    s = pricing_eval.compute(ctx, result, table)["sensitivity"]
    assert s[0]["prosumer_eur"] > s[-1]["prosumer_eur"]
    assert s[0]["ppc_improvement_eur"] < s[-1]["ppc_improvement_eur"]


def test_no_surplus_table_gives_none(table):
    ctx, result = make()
    assert pricing_eval.compute({**ctx, "surplus": None}, result, table) is None


def test_markdown_is_written(tmp_path, table):
    ctx, result = make()
    block = pricing_eval.compute(ctx, result, table)
    pricing_eval.write(tmp_path, "PT-A", block, "MOCK, NOT A RESULT")
    text = (tmp_path / "pricing_PT-A.md").read_text()
    assert text.startswith("# MOCK, NOT A RESULT") and "euenergy.live" in text
    assert "battery response (proposed)" in text and "Fee sensitivity" in text


def test_summer_day_chart_is_written(tmp_path, table):
    pytest.importorskip("matplotlib")
    ctx, result = make()
    path = pricing_eval.day_chart(ctx, result, table, tmp_path, "PT-A")
    assert path.name == "pricing_day_PT-A.png" and path.stat().st_size > 1000


def test_chart_needs_a_summer_day(tmp_path, table):
    pytest.importorskip("matplotlib")
    ctx, result = make()
    shift = pd.Timedelta(days=120)  # mid-May: Sydney autumn
    surplus = ctx["surplus"]
    moved_ctx = {"surplus": surplus.set_axis(surplus.index + shift), "kwp": ctx["kwp"]}
    moved = {"scored": {k: v.set_axis(v.index + shift) for k, v in result["scored"].items()}}
    assert pricing_eval.day_chart(moved_ctx, moved, table, tmp_path, "PT-A") is None
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/python -m pytest tests/eval/test_pricing_eval.py -q`
Expected: FAIL, `cannot import name 'pricing_eval'`.

- [ ] **Step 3: Implement**

`src/eval/pricing_eval.py`:

```python
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
```

- [ ] **Step 4: Run it to see it pass**

Run: `.venv/bin/python -m pytest tests/eval/test_pricing_eval.py -q && .venv/bin/python -m ruff check src tests`
Expected: `6 passed`, clean.

- [ ] **Step 5: Commit**

```bash
git add src/eval/pricing_eval.py tests/eval/test_pricing_eval.py
git commit -m "feat(eval): compare the regulated price with the hourly price and solar adder"
```

---

### Task 7: `python -m src.eval.run --pricing`, smoke, README

**Files:** modify `src/eval/run.py`, `src/smoke.py`, `README.md`; test `tests/eval/test_run.py`.

- [ ] **Step 1: Failing test.** Add to `tests/eval/test_run.py` (and `import numpy as np` next to its `import pandas as pd`):

Change to `tests/eval/test_run.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/tests/eval/test_run.py b/tests/eval/test_run.py
index 1d15d8e..6b627aa 100644
--- a/tests/eval/test_run.py
+++ b/tests/eval/test_run.py
@@ -1,6 +1,7 @@
 import hashlib
 import json
 
+import numpy as np
 import pandas as pd
 import pytest
 
@@ -267,3 +268,19 @@ def test_the_control_is_not_scored_again_when_the_rebuilt_totals_are_the_label_t
     calls.clear()
     out = robustness.run_variants(ctx, clean)
     assert len(calls) == 4 and out["notes"]["control_rescored"] is True
+
+
+def test_pricing_flag_adds_the_price_block(env, first):
+    from src.pricing import prices
+
+    idx = pd.date_range("2025-01-01", "2026-01-01", freq="h", tz="UTC", inclusive="left")
+    hour = idx.tz_convert("Europe/Bucharest").hour
+    midday = (hour >= 10) & (hour < 16)
+    year = pd.Series(np.where(midday, 40.0, 150.0), index=idx)
+    prices.save(year, prices.prices_path())
+    summary = eval_run.run(["A"], "priced", allow_mock=True, grid=FAST, pricing=True)
+    block = next(iter(summary["scenarios"].values()))["pricing"]
+    assert len(block["rows"]) == 4 and len(block["sensitivity"]) == 6
+    assert list(eval_run.eval_dir("priced").glob("pricing_*.md"))
+    plain = eval_run.run(["A"], "plain", allow_mock=True, grid=FAST)
+    assert "pricing" not in next(iter(plain["scenarios"].values()))
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/python -m pytest tests/eval/test_run.py::test_pricing_flag_adds_the_price_block -q`
Expected: FAIL, `run() got an unexpected keyword argument 'pricing'`.

- [ ] **Step 3: Implement.**

Change to `src/eval/run.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/src/eval/run.py b/src/eval/run.py
index 0601dff..3b5c031 100644
--- a/src/eval/run.py
+++ b/src/eval/run.py
@@ -23,12 +23,13 @@ from pathlib import Path
 import numpy as np
 import pandas as pd
 
-from src.eval import table
+from src.eval import pricing_eval, table
 from src.eval.metrics import FIXED_SHARE, evaluate, load_profiles, surplus_kw
 from src.ml import abstention, baselines, calibration, features, model_io, train
 from src.ml import labels as labels_io
 from src.ml.config import SYDNEY, artifact_uri, profiles_path, violation_target
 from src.ml.split import TEST_START, daylight, split
+from src.pricing import prices as price_data
 
 MOCK_TITLE = "MOCK – NOT A RESULT"
 TITLE = "Evaluation on the test period"
@@ -51,6 +52,14 @@ def _require_report_extra() -> None:
         ) from error
 
 
+def _has_report_extra() -> bool:
+    try:
+        import matplotlib  # noqa: F401
+    except ImportError:
+        return False
+    return True
+
+
 def eval_dir(run_id: str) -> Path:
     return Path(artifact_uri()) / "eval" / run_id
 
@@ -243,6 +252,7 @@ def run(
     robustness=True,
     error_analysis=False,
     grid=None,
+    pricing=False,
 ) -> dict:
     """Evaluate every scenario and write the outputs. Returns the summary."""
     if error_analysis:
@@ -252,6 +262,7 @@ def run(
     out.mkdir(parents=True, exist_ok=True)
     all_rows, summary_scenarios, calibrations, footer, any_mock = {}, {}, [], [], False
     sections = []
+    price_table = price_data.profile(price_data.load()) if pricing else None
     for scenario in scenarios:
         ctx = _prepare(scenario, run_id, allow_mock, use_artifacts, grid)
         pt_id = ctx["labels"]["pt_id"].iloc[0]
@@ -267,6 +278,13 @@ def run(
             from src.eval import error_analysis as analysis
 
             sections.append(analysis.analyse(ctx, result, rows, out, pt_id))
+        if price_table is not None:
+            block = pricing_eval.compute(ctx, result, price_table)
+            if block is not None:
+                extra = {**extra, "pricing": block}
+                pricing_eval.write(out, pt_id, block, MOCK_TITLE if ctx["mock"] else None)
+                if _has_report_extra():
+                    pricing_eval.day_chart(ctx, result, price_table, out, pt_id)
         any_mock |= ctx["mock"]
         all_rows[pt_id] = rows
         meta, test = ctx["meta"], ctx["test_labels"]
@@ -337,6 +355,9 @@ def main(argv: list[str] | None = None) -> None:
     parser.add_argument(
         "--error-analysis", action="store_true", help="also write the error analysis"
     )
+    parser.add_argument(
+        "--pricing", action="store_true", help="also write the prosumer price comparison"
+    )
     args = parser.parse_args(argv)
     names = list(labels_io.SCENARIOS) if args.scenario == "all" else [args.scenario]
     names = [n for n in names if (labels_io.labels_path(n) / "labels.parquet").exists()]
@@ -352,6 +373,7 @@ def main(argv: list[str] | None = None) -> None:
             args.allow_mock,
             args.robustness,
             args.error_analysis,
+            pricing=args.pricing,
         )
     except MockLabelsError as err:
         raise SystemExit(str(err)) from err
```

Change to `src/smoke.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/src/smoke.py b/src/smoke.py
index 2e0be17..1e07081 100644
--- a/src/smoke.py
+++ b/src/smoke.py
@@ -9,7 +9,7 @@ from src.agent.sources import MockSource
 from src.common.contract import ActionEvent, Forecast, GridState, Plan, StationConfig
 from src.common.mock_data import load_mock
 
-PACKAGES = ["common", "ml", "grid", "agent", "ui", "eval"]
+PACKAGES = ["common", "ml", "grid", "agent", "ui", "eval", "pricing"]
 
 
 def main() -> None:
```

README: insert a new section before `### Environment variables`:

````markdown
### 10. Prices and the prosumer price comparison (optional)
The evaluation can compare what battery owners earn today (the regulated monthly average price) with an hourly price plus a monthly solar adder, and what that does to PPC's margin. It needs one year of Romanian day-ahead prices from [euenergy.live](https://euenergy.live) (CC-BY-4.0, free token). Put `EUENERGY_TOKEN=<your token>` in `.env` (the file is not committed), then:
```bash
set -a; . ./.env; set +a
python -m src.pricing.prices fetch --year 2025
python -m src.eval.run --pricing
```
The first command saves `data/pzu/ro.parquet`. The second adds a `pricing` block to `summary.json`, a `pricing_<station>.md` table and a `pricing_day_<station>.png` chart. Prices are matched to the Ausgrid year by season (Sydney July with Bucharest January) and local hour, so the result shows the shape of the effect, not a forecast in euros. Fee, floor and bonus share are placeholders in `src/pricing/config.py`.
````

Add a row to the environment table: ``| `EUENERGY_TOKEN` | unset | `python -m src.pricing.prices fetch` |`` and a row to the data table: `| [euenergy.live](https://euenergy.live) hourly Romanian day-ahead prices | price comparison | CC BY 4.0, credit euenergy.live |`.

- [ ] **Step 4: Verify everything**

```bash
make test lint smoke
```
Expected: all tests pass, `All checks passed!`, `SMOKE OK`.

- [ ] **Step 5: Commit**

```bash
git add src/eval/run.py src/smoke.py README.md tests/eval/test_run.py
git commit -m "feat(eval): add --pricing to compare prosumer prices"
```

---

### Task 8: Run it on real data and report it

Needs the token and real labels (skip and say so if labels are not on this machine).

- [ ] **Step 1: Run**

```bash
set -a; . ./.env; set +a
.venv/bin/python -m src.pricing.prices fetch --year 2025
.venv/bin/python -m src.eval.run --run-id pricing-check --pricing
```
Expected: `saved … hourly prices for 2025 …` (a few rows fewer than 8760 if the API has gaps), then `evaluation written to …`.

- [ ] **Step 2: Read `artifacts/eval/pricing-check/pricing_<station>.md` and report the numbers as they are:** prosumer change against today for each row, PPC margin and improvement, the fee table, and whether the prosumer share of the value created is near the 47/53 split the simulation in `docs/14` suggested. Say plainly if it differs.

- [ ] **Step 3: Ask the user** before pushing `pricing/core` and opening its PR.

---

# Phase 2: imbalance savings and the bonus (branch `pricing/imbalance`)

Cut from `main` after phase 1 is merged. It reads `src/ml/forecast_pv_load.py` (P6's area): do not edit that file, call `predict_pv_load`. Train the PV/load model first for real runs: `python -m src.ml.forecast_pv_load --scenario A`. Without it the imbalance block is `None` and the screen says so.

### Task 9: Imbalance volume, cost and saving

**Files:** create `src/pricing/imbalance.py`; test `tests/pricing/test_imbalance.py`.

- [ ] **Step 1: Branch and failing test**

```bash
git switch main && git pull && git switch -c pricing/imbalance
```

`tests/pricing/test_imbalance.py`:

```python
import pandas as pd
import pytest

from src.pricing import imbalance


def series(values):
    idx = pd.date_range("2025-06-21", periods=len(values), freq="30min", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


def test_volume_is_the_absolute_gap_in_mwh():
    actual, forecast = series([1000, 2000, 3000]), series([1500, 2000, 2000])
    # |500| + 0 + |1000| = 1500 kW * 0.5 h = 750 kWh = 0.75 MWh
    assert imbalance.volume_mwh(actual, forecast) == pytest.approx(0.75)


def test_saving_is_zero_for_equal_forecasts_and_positive_for_a_better_one():
    actual = series([1000, 2000, 3000, 2000])
    baseline = series([2000, 1000, 3000, 3000])
    same = imbalance.saving(actual, baseline, baseline, 60.0)
    assert same["saving_eur"] == 0.0
    better = imbalance.saving(actual, baseline, actual, 60.0)
    assert better["model_mwh"] == 0.0
    assert better["baseline_mwh"] == pytest.approx((1000 + 1000 + 0 + 1000) * 0.5 / 1000)
    assert better["saving_eur"] == pytest.approx(better["baseline_cost_eur"])
    assert better["baseline_cost_eur"] == pytest.approx(better["baseline_mwh"] * 60.0)


def test_only_common_intervals_count():
    actual = series([1000, 1000, 1000])
    baseline = series([0, 0, 0])
    model = series([0, 0, 0]).iloc[1:]
    out = imbalance.saving(actual, baseline, model, 10.0)
    assert out["n_intervals"] == 2


def test_the_bonus_is_a_share_of_a_positive_saving_only():
    assert imbalance.split_saving(100.0, 0.5) == (50.0, 50.0)
    assert imbalance.split_saving(-40.0, 0.5) == (0.0, -40.0)
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/python -m pytest tests/pricing/test_imbalance.py -q`
Expected: FAIL, `cannot import name 'imbalance'`.

- [ ] **Step 3: Implement**

`src/pricing/imbalance.py`:

```python
"""Imbalance volume, cost and saving. Pure: series in, numbers out.

PPC's imbalance is the gap between the export it expected and what arrived. A better forecast
shrinks the gap. The cost of a gap is an imbalance spread (EUR/MWh) that is not in our data
source, so callers pass scenario values (``SPREADS_EUR_MWH``) or a real series later.
"""

import pandas as pd

STEP_HOURS = 0.5
SPREADS_EUR_MWH = (30.0, 60.0, 120.0)  # scenario values; AFEER's 38-72 EUR/MWh is a cross-check


def volume_mwh(actual_kw: pd.Series, forecast_kw: pd.Series) -> float:
    """Sum of |actual - forecast| over the intervals both have, in MWh."""
    both = pd.concat([actual_kw, forecast_kw], axis=1, join="inner").dropna()
    return float((both.iloc[:, 0] - both.iloc[:, 1]).abs().sum() * STEP_HOURS / 1000)


def saving(
    actual_kw: pd.Series,
    baseline_kw: pd.Series,
    model_kw: pd.Series,
    spread_eur_mwh: float,
) -> dict:
    """Imbalance cost with the baseline forecast, with the model forecast, and the difference.

    Only intervals where all three series have a value are compared, so both forecasts are
    scored on the same intervals.
    """
    frame = pd.concat([actual_kw, baseline_kw, model_kw], axis=1, join="inner").dropna()
    actual, baseline, model = (frame.iloc[:, i] for i in range(3))
    base_mwh = volume_mwh(actual, baseline)
    model_mwh = volume_mwh(actual, model)
    return {
        "spread_eur_mwh": spread_eur_mwh,
        "n_intervals": len(frame),
        "baseline_mwh": base_mwh,
        "model_mwh": model_mwh,
        "baseline_cost_eur": base_mwh * spread_eur_mwh,
        "model_cost_eur": model_mwh * spread_eur_mwh,
        "saving_eur": (base_mwh - model_mwh) * spread_eur_mwh,
    }


def split_saving(saving_eur: float, bonus_share: float) -> tuple[float, float]:
    """(prosumer bonus, what PPC keeps). A negative saving is not shared: PPC bears it."""
    bonus = max(0.0, saving_eur) * bonus_share
    return bonus, saving_eur - bonus
```

- [ ] **Step 4: Run it to see it pass**

Run: `.venv/bin/python -m pytest tests/pricing -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/pricing/imbalance.py tests/pricing/test_imbalance.py
git commit -m "feat(pricing): value imbalance volume and savings"
```

---

### Task 10: Forecasts for the imbalance savings

**Files:** create `src/eval/imbalance_eval.py`; test `tests/eval/test_imbalance_eval.py`.

The quantity is the station's net export `max(0, pv - load)` before any limit. Baseline: the same interval one day earlier. Model: the PV/load model at a 60-minute horizon. The integration test trains a small PV/load model on mock labels (about 10 seconds).

- [ ] **Step 1: Failing test**

`tests/eval/test_imbalance_eval.py`:

```python
import pandas as pd
import pytest

from src.eval import imbalance_eval
from src.ml import features, forecast_pv_load, labels
from src.ml import predict as predict_module

SMALL = {"max_iter": 30, "learning_rate": 0.1, "max_leaf_nodes": 15, "min_samples_leaf": 40}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("imbalance")
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_DIR", str(root / "data"))
    mp.setenv("ARTIFACT_URI", str(root / "artifacts"))
    labels.main(["mock", "--scenario", "A"])
    predict_module.clear_cache()
    yield labels.load("A")
    mp.undo()
    predict_module.clear_cache()


def scored_like(table, rows=200):
    frame = features.build_frame(table).dropna(subset=features.FEATURES).iloc[1000 : 1000 + rows]
    return {"X": frame[features.FEATURES], "rows": frame[["pt_id", "target_start"]]}


def test_actual_and_baseline_exports(env):
    actual = imbalance_eval.actual_export_kw(env)
    assert (actual >= 0).all() and actual.index.is_unique
    baseline = imbalance_eval.baseline_export_kw(actual)
    probe = actual.index[100]
    assert baseline.loc[probe] == actual.loc[probe - pd.Timedelta(hours=24)]


def test_without_a_trained_model_the_result_is_none(env):
    ctx, result = {"labels": env}, {"scored": scored_like(env)}
    assert imbalance_eval.station_savings(ctx, result) is None


def test_with_a_trained_model_every_spread_has_a_saving(env):
    forecast_pv_load.train("A", horizons=(60,), params=SMALL)
    ctx, result = {"labels": env}, {"scored": scored_like(env)}
    out = imbalance_eval.station_savings(ctx, result)
    assert out["horizon_min"] == 60 and [s["spread_eur_mwh"] for s in out["by_spread"]] == [
        30.0,
        60.0,
        120.0,
    ]
    first = out["by_spread"][0]
    assert first["n_intervals"] > 0 and first["baseline_mwh"] > 0 and first["model_mwh"] >= 0
    ratios = [s["saving_eur"] / s["spread_eur_mwh"] for s in out["by_spread"]]
    assert ratios[0] == pytest.approx(ratios[1]) == pytest.approx(ratios[2])
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/python -m pytest tests/eval/test_imbalance_eval.py -q`
Expected: FAIL, `cannot import name 'imbalance_eval'`.

- [ ] **Step 3: Implement**

`src/eval/imbalance_eval.py`:

```python
"""Imbalance savings of the PV/load forecast against "same time yesterday".

The quantity is the station's net export, ``max(0, pv - load)``, before any export limit. The
model forecast is the repository's PV/load model at a 60-minute horizon: PPC corrects its
position on the intraday market about an hour ahead (an assumption). Without a trained
PV/load model the result is None and the caller says so.
"""

import pandas as pd

from src.ml import forecast_pv_load
from src.pricing import imbalance

HORIZON_MIN = 60
DAY = pd.Timedelta(hours=24)


def actual_export_kw(labels: pd.DataFrame) -> pd.Series:
    """Net export of the station per interval, from the label table."""
    index = pd.DatetimeIndex(labels["interval_start"])
    net = pd.Series(labels["pv_kw"].to_numpy() - labels["load_kw"].to_numpy(), index=index)
    return net.clip(lower=0.0)


def baseline_export_kw(actual: pd.Series) -> pd.Series:
    """The same interval one day earlier."""
    return actual.reindex(actual.index - DAY).set_axis(actual.index)


def model_export_kw(X: pd.DataFrame, pt_id: str, index: pd.DatetimeIndex) -> pd.Series:
    """The PV/load model's median net export for each row of features ``X``."""
    values = []
    for record in X.to_dict("records"):
        out = forecast_pv_load.predict_pv_load({**record, "pt_id": pt_id}, HORIZON_MIN)
        load = out["load_kw"].p50 if out["load_kw"] is not None else 0.0
        values.append(max(0.0, out["pv_kw"].p50 - load))
    return pd.Series(values, index=index)


def station_savings(ctx: dict, result: dict) -> dict | None:
    """Savings of the model forecast for each spread scenario, or None without models."""
    scored = result["scored"]
    labels = ctx["labels"]
    pt_id = labels["pt_id"].iloc[0]
    index = pd.DatetimeIndex(scored["rows"]["target_start"])
    try:
        model = model_export_kw(scored["X"], pt_id, index)
    except FileNotFoundError:
        return None
    actual = actual_export_kw(labels)
    baseline = baseline_export_kw(actual)
    return {
        "horizon_min": HORIZON_MIN,
        "baseline": "same time yesterday",
        "by_spread": [
            imbalance.saving(actual, baseline, model, spread)
            for spread in imbalance.SPREADS_EUR_MWH
        ],
    }
```

- [ ] **Step 4: Run it to see it pass**

Run: `.venv/bin/python -m pytest tests/eval/test_imbalance_eval.py -q && .venv/bin/python -m ruff check src tests`
Expected: `3 passed`, clean.

- [ ] **Step 5: Commit**

```bash
git add src/eval/imbalance_eval.py tests/eval/test_imbalance_eval.py
git commit -m "feat(eval): score the PV/load forecast against yesterday as imbalance"
```

---

### Task 11: Add the savings to the block, the flag and the README

**Files:** modify `src/eval/pricing_eval.py`, `src/eval/run.py`, `README.md`; test `tests/eval/test_pricing_eval.py`.

The bonus is `bonus_share` of the saving of the battery houses' share of the station's exports. A negative saving is not shared: PPC bears it.

- [ ] **Step 1: Failing tests.**

Change to `tests/eval/test_pricing_eval.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/tests/eval/test_pricing_eval.py b/tests/eval/test_pricing_eval.py
index ff04348..5be399a 100644
--- a/tests/eval/test_pricing_eval.py
+++ b/tests/eval/test_pricing_eval.py
@@ -89,3 +89,49 @@ def test_chart_needs_a_summer_day(tmp_path, table):
     moved_ctx = {"surplus": surplus.set_axis(surplus.index + shift), "kwp": ctx["kwp"]}
     moved = {"scored": {k: v.set_axis(v.index + shift) for k, v in result["scored"].items()}}
     assert pricing_eval.day_chart(moved_ctx, moved, table, tmp_path, "PT-A") is None
+
+
+def fake_savings(saving_eur=100.0):
+    item = {
+        "spread_eur_mwh": 60.0,
+        "n_intervals": 10,
+        "baseline_mwh": 3.0,
+        "model_mwh": 1.0,
+        "baseline_cost_eur": 180.0,
+        "model_cost_eur": 60.0,
+        "saving_eur": saving_eur,
+    }
+    return {"horizon_min": 60, "baseline": "same time yesterday", "by_spread": [item]}
+
+
+def test_imbalance_savings_are_shared_by_the_bonus_share(table):
+    ctx, result = make()
+    without = pricing_eval.compute(ctx, result, table)
+    assert without["imbalance"] is None
+    block = pricing_eval.compute(ctx, result, table, imbalance=fake_savings(100.0))
+    item = block["imbalance"]["scenarios"][0]
+    assert 0 < item["group_share"] < 1  # one of three houses has a battery
+    assert item["group_saving_eur"] == pytest.approx(100.0 * item["group_share"], abs=1e-4)
+    assert item["prosumer_bonus_eur"] == pytest.approx(item["group_saving_eur"] / 2, abs=1e-4)
+    proposed = block["rows"][-1]
+    assert item["prosumer_total_eur"] == pytest.approx(
+        proposed["prosumer_eur"] + item["prosumer_bonus_eur"], abs=1e-4
+    )
+    assert item["ppc_improvement_total_eur"] == pytest.approx(
+        proposed["ppc_improvement_eur"] + item["ppc_keeps_eur"], abs=1e-4
+    )
+    json.dumps(block, allow_nan=False)
+
+
+def test_a_negative_saving_is_not_shared(table):
+    ctx, result = make()
+    block = pricing_eval.compute(ctx, result, table, imbalance=fake_savings(-50.0))
+    item = block["imbalance"]["scenarios"][0]
+    assert item["prosumer_bonus_eur"] == 0.0 and item["ppc_keeps_eur"] < 0
+
+
+def test_markdown_lists_the_imbalance_scenarios(tmp_path, table):
+    ctx, result = make()
+    block = pricing_eval.compute(ctx, result, table, imbalance=fake_savings())
+    pricing_eval.write(tmp_path, "PT-A", block)
+    assert "Imbalance savings" in (tmp_path / "pricing_PT-A.md").read_text()
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/python -m pytest tests/eval/test_pricing_eval.py -q`
Expected: FAIL, `compute() got an unexpected keyword argument 'imbalance'`.

- [ ] **Step 3: Implement.**

Change to `src/eval/pricing_eval.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/src/eval/pricing_eval.py b/src/eval/pricing_eval.py
index 43d67c2..458e73d 100644
--- a/src/eval/pricing_eval.py
+++ b/src/eval/pricing_eval.py
@@ -8,6 +8,7 @@ import numpy as np
 import pandas as pd
 
 from src.eval.metrics import STEP_HOURS
+from src.pricing import imbalance as imbalance_model
 from src.pricing import prices, solar
 from src.pricing.battery import battery_houses, dispatch
 from src.pricing.config import PricingConfig
@@ -73,6 +74,50 @@ def _group_exports(ctx: dict, data: dict, fee: float) -> tuple[pd.Series, pd.Ser
     return plain, shifted
 
 
+def _group_share(ctx: dict, data: dict, plain_group: pd.Series) -> float:
+    """The battery houses' share of the station's smart-limit exports."""
+    index, surplus, kwp = data["index"], ctx["surplus"], ctx["kwp"]
+    columns = surplus.columns
+    caps = data["share"].to_numpy()[:, None] * kwp.reindex(columns).to_numpy()[None, :]
+    everyone = np.minimum(surplus.loc[index].fillna(0.0).to_numpy(), caps).sum() * STEP_HOURS
+    return float(plain_group.sum() / everyone) if everyone > 0 else 0.0
+
+
+def _imbalance_block(imbalance, group_share, cfg, today_paid, proposed, base) -> dict | None:
+    """What the imbalance savings add on top, for each spread scenario."""
+    if imbalance is None:
+        return None
+    scenarios = []
+    for item in imbalance["by_spread"]:
+        group_saving = item["saving_eur"] * group_share
+        bonus, kept = imbalance_model.split_saving(group_saving, cfg.bonus_share)
+        scenarios.append(
+            {
+                "spread_eur_mwh": item["spread_eur_mwh"],
+                "station_baseline_mwh": item["baseline_mwh"],
+                "station_model_mwh": item["model_mwh"],
+                "station_saving_eur": item["saving_eur"],
+                "group_share": group_share,
+                "group_saving_eur": group_saving,
+                "prosumer_bonus_eur": bonus,
+                "ppc_keeps_eur": kept,
+                "prosumer_total_eur": proposed["paid_eur"] + bonus,
+                "prosumer_total_vs_today_pct": _pct(proposed["paid_eur"] + bonus, today_paid),
+                "ppc_improvement_total_eur": (
+                    proposed["ppc_margin_paid_eur"]
+                    - base["ppc_margin_eur"]
+                    + kept
+                ),
+            }
+        )
+    return {
+        "horizon_min": imbalance["horizon_min"],
+        "baseline": imbalance["baseline"],
+        "bonus_share": cfg.bonus_share,
+        "scenarios": scenarios,
+    }
+
+
 def _row(name, kwh, paid, value, today):
     margin = value - paid
     return {
@@ -91,8 +136,12 @@ def compute(
     result: dict,
     table: pd.Series,
     cfg: PricingConfig = PricingConfig(),
+    imbalance: dict | None = None,
 ) -> dict | None:
-    """The block of one scenario, or None when there is no surplus table."""
+    """The block of one scenario, or None when there is no surplus table.
+
+    ``imbalance`` is the result of ``imbalance_eval.station_savings`` (or None).
+    """
     data = _inputs(ctx, result, table)
     if data is None:
         return None
@@ -167,6 +216,9 @@ def compute(
         "adder_eur_mwh_by_bucharest_month": data["adder_by_month"].to_dict(),
         "rows": rows,
         "sensitivity": sensitivity,
+        "imbalance": _imbalance_block(
+            imbalance, _group_share(ctx, data, plain), cfg, today["regulated_eur"], proposed, base
+        ),
     }
     return _clean(block)
 
@@ -254,4 +306,23 @@ def write(out, pt_id: str, block: dict, mock_title: str | None = None) -> None:
             f"| {_cell(s['ppc_improvement_eur'], 2, True)} "
             f"| {_cell(s['prosumer_share_of_value_pct'], 0)} |"
         )
+    extra = block.get("imbalance")
+    if extra:
+        lines += [
+            "",
+            f"Imbalance savings ({extra['baseline']} versus the PV/load model at "
+            f"{extra['horizon_min']} min; spread values are scenarios, not market data). "
+            f"Bonus share {extra['bonus_share']:.0%}.",
+            "",
+            "| Spread (EUR/MWh) | Saved, battery houses (EUR) | Prosumer bonus (EUR) "
+            "| Prosumer total vs today (%) | PPC improvement incl. savings (EUR) |",
+            "|---:|---:|---:|---:|---:|",
+        ]
+        for item in extra["scenarios"]:
+            lines.append(
+                f"| {item['spread_eur_mwh']:.0f} | {_cell(item['group_saving_eur'], 2)} "
+                f"| {_cell(item['prosumer_bonus_eur'], 2)} "
+                f"| {_cell(item['prosumer_total_vs_today_pct'], 1, True)} "
+                f"| {_cell(item['ppc_improvement_total_eur'], 2, True)} |"
+            )
     (out / f"pricing_{pt_id}.md").write_text("\n".join(lines) + "\n")
```

Change to `src/eval/run.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/src/eval/run.py b/src/eval/run.py
index 3b5c031..b34fd81 100644
--- a/src/eval/run.py
+++ b/src/eval/run.py
@@ -23,7 +23,7 @@ from pathlib import Path
 import numpy as np
 import pandas as pd
 
-from src.eval import pricing_eval, table
+from src.eval import imbalance_eval, pricing_eval, table
 from src.eval.metrics import FIXED_SHARE, evaluate, load_profiles, surplus_kw
 from src.ml import abstention, baselines, calibration, features, model_io, train
 from src.ml import labels as labels_io
@@ -279,7 +279,8 @@ def run(
 
             sections.append(analysis.analyse(ctx, result, rows, out, pt_id))
         if price_table is not None:
-            block = pricing_eval.compute(ctx, result, price_table)
+            savings = imbalance_eval.station_savings(ctx, result)
+            block = pricing_eval.compute(ctx, result, price_table, imbalance=savings)
             if block is not None:
                 extra = {**extra, "pricing": block}
                 pricing_eval.write(out, pt_id, block, MOCK_TITLE if ctx["mock"] else None)
```

README: in section 10 add: "If the PV/load forecast is trained (`python -m src.ml.forecast_pv_load --scenario A`), the table also shows the imbalance savings of that forecast against 'same time yesterday' for three imbalance spreads (30, 60 and 120 EUR/MWh, scenario values, not market data) and the bonus prosumers would get. Without the trained model that part is skipped."

- [ ] **Step 4: Verify**

Run: `make test lint smoke`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/eval README.md tests/eval
git commit -m "feat(eval): add the imbalance savings and the bonus to the price block"
```

Ask the user before pushing `pricing/imbalance`.

---

# Phase 3: per-house price in the agent API (branch `pricing/api`)

Cut from `main` after phase 1 is merged. Needs P1's sign-off: it changes `src/common/contract.py`, `src/agent/`, `docs/09-contract.md`. The price shown per house is the product's price (hourly price plus adder); who is eligible (battery and smart meter) is a contract matter, not shown here.

### Task 12: `HousePrice` in the contract

**Files:** modify `src/common/contract.py`, `docs/09-contract.md`; test `tests/test_contract.py`.

- [ ] **Step 1: Branch and failing tests** (add `HousePrice` to the test file's import list):

```bash
git switch main && git pull && git switch -c pricing/api
```

Change to `tests/test_contract.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/tests/test_contract.py b/tests/test_contract.py
index 1d92eaf..d1ab331 100644
--- a/tests/test_contract.py
+++ b/tests/test_contract.py
@@ -6,6 +6,7 @@ from src.common.contract import (
     ActionEvent,
     Forecast,
     GridState,
+    HousePrice,
     Plan,
     SafeCapShare,
     StationConfig,
@@ -60,3 +61,27 @@ def test_settings_defaults_and_env():
     s = Settings.from_env(env)
     assert (s.app_env, s.demo_token, s.log_uri) == ("cloud", "t", "/tmp/x.jsonl")
     assert Settings.from_env({"DEMO_TOKEN": ""}).demo_token is None
+
+
+def test_house_price_checks_its_total_and_refuses_negatives():
+    ok = {
+        "house_id": "H01",
+        "interval_start": "2025-06-21T10:00:00Z",
+        "wholesale_eur_mwh": 100.0,
+        "hourly_eur_kwh": 0.07,
+        "adder_eur_kwh": 0.04,
+        "total_eur_kwh": 0.11,
+        "floor_applied": False,
+        "reason": "hourly price: wholesale minus the fee, plus the solar adder",
+    }
+    assert HousePrice(**ok).total_eur_kwh == 0.11
+    with pytest.raises(ValidationError):
+        HousePrice(**{**ok, "total_eur_kwh": 0.5})
+    with pytest.raises(ValidationError):
+        HousePrice(**{**ok, "hourly_eur_kwh": -0.01, "total_eur_kwh": 0.03})
+    with pytest.raises(ValidationError):
+        HousePrice(**{**ok, "extra": 1})
+
+
+def test_plan_without_prices_still_loads():
+    assert load_mock("plan", Plan).prices == []
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/python -m pytest tests/test_contract.py -q`
Expected: FAIL on import of `HousePrice`.

- [ ] **Step 3: Implement.**

Change to `src/common/contract.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/src/common/contract.py b/src/common/contract.py
index b41c85a..6c47c32 100644
--- a/src/common/contract.py
+++ b/src/common/contract.py
@@ -94,6 +94,23 @@ class HouseLimit(Strict):
     battery_kw: float = 0.0
 
 
+class HousePrice(Strict):
+    house_id: str
+    interval_start: AwareDatetime
+    wholesale_eur_mwh: float
+    hourly_eur_kwh: float = Field(ge=0)
+    adder_eur_kwh: float = Field(ge=0)
+    total_eur_kwh: float = Field(ge=0)
+    floor_applied: bool
+    reason: str
+
+    @model_validator(mode="after")
+    def _total_matches(self) -> "HousePrice":
+        if abs(self.total_eur_kwh - (self.hourly_eur_kwh + self.adder_eur_kwh)) > 1e-6:
+            raise ValueError("total_eur_kwh must equal hourly_eur_kwh + adder_eur_kwh")
+        return self
+
+
 class GuardResult(Strict):
     passed: bool
     v_max_pu: float | None = None
@@ -123,6 +140,7 @@ class Plan(Strict):
     reasons: list[str]
     guard: GuardResult | None = None
     explanation: Explanation | None = None
+    prices: list[HousePrice] = Field(default_factory=list)
     status: PlanStatus
```

In `docs/09-contract.md` read the section headings and add a `HousePrice` section after the plan section, in the same style: the JSON example from the test, plus "`prices` in a plan is empty when no wholesale price was available; `total_eur_kwh` is `hourly_eur_kwh + adder_eur_kwh`; no price is ever negative".

- [ ] **Step 4: Run to see them pass**

Run: `.venv/bin/python -m pytest tests/test_contract.py tests/test_planner.py tests/test_service.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/common/contract.py docs/09-contract.md tests/test_contract.py
git commit -m "feat(common): add HousePrice and Plan.prices to the contract"
```

---

### Task 13: The price source

**Files:** create `src/pricing/source.py`; test `tests/test_pricing_source.py`.

Real prices when `SOURCE` is not `mock` and `data/pzu/ro.parquet` exists, otherwise an illustrative duck-curve marked `mock`. A partial year is refused.

- [ ] **Step 1: Failing test**

`tests/test_pricing_source.py`:

```python
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from src.common.config import Settings
from src.pricing import prices
from src.pricing.source import MOCK_CURVE_EUR_MWH, PriceSource, mock_source, price_source_for


def year(y=2025):
    idx = pd.date_range(f"{y}-01-01", f"{y + 1}-01-01", freq="h", tz="UTC", inclusive="left")
    hour = idx.tz_convert("Europe/Bucharest").hour
    price = np.where((hour >= 10) & (hour < 16), 40.0, 140.0)
    return pd.Series(price, index=idx)


def test_mock_source_follows_the_bucharest_clock():
    noon_bucharest = datetime(2025, 6, 21, 9, 0, tzinfo=timezone.utc)  # 12:00 in summer
    assert mock_source().wholesale(noon_bucharest) == MOCK_CURVE_EUR_MWH[12]
    assert mock_source().mock is True


def test_real_prices_win_over_the_profile_when_the_hour_is_known():
    series = year()
    series.loc["2025-06-21 10:00:00+00:00"] = 77.0
    source = PriceSource(prices.profile(series), series)
    assert source.wholesale(datetime(2025, 6, 21, 10, 30, tzinfo=timezone.utc)) == 77.0
    other_year = datetime(2012, 6, 21, 10, 30, tzinfo=timezone.utc)
    assert source.wholesale(other_year) is not None  # falls back to the (month, hour) profile
    assert source.mock is False


def test_the_adder_is_positive_when_midday_is_cheap():
    source = PriceSource(prices.profile(year()))
    assert source.adder(datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)) > 30
    assert mock_source().adder(datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)) > 0


def test_day_curve_has_24_utc_hours():
    curve = mock_source().day_curve(datetime(2025, 6, 21, 13, 0, tzinfo=timezone.utc))
    assert len(curve) == 24 and curve[0]["ts"].startswith("2025-06-21T00:00:00")
    assert all(c["wholesale_eur_mwh"] is not None for c in curve)


def test_settings_pick_mock_or_data(tmp_path):
    assert price_source_for(Settings(source="mock", data_dir=str(tmp_path))).mock is True
    assert price_source_for(Settings(source="model", data_dir=str(tmp_path))).mock is True
    prices.save(year(), prices.prices_path(str(tmp_path)))
    assert price_source_for(Settings(source="model", data_dir=str(tmp_path))).mock is False


def test_a_partial_year_is_refused(tmp_path):
    prices.save(year()[:2000], prices.prices_path(str(tmp_path)))
    with pytest.raises(ValueError):
        price_source_for(Settings(source="model", data_dir=str(tmp_path)))
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/python -m pytest tests/test_pricing_source.py -q`
Expected: FAIL, `No module named 'src.pricing.source'`.

- [ ] **Step 3: Implement**

`src/pricing/source.py`:

```python
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
```

- [ ] **Step 4: Run it to see it pass**

Run: `.venv/bin/python -m pytest tests/test_pricing_source.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/pricing/source.py tests/test_pricing_source.py
git commit -m "feat(pricing): add the wholesale price source with a mock curve"
```

---

### Task 14: Prices in the plan

**Files:** modify `src/agent/planner.py`, `src/agent/service.py`, `src/agent/wiring.py`, `src/grid/demo_api.py`; tests `tests/test_planner_prices.py`, `tests/test_service_prices.py`.

- [ ] **Step 1: Failing tests**

`tests/test_planner_prices.py`:

```python
from datetime import datetime, timezone

import pytest

from src.agent.planner import make_plan
from src.agent.sources import MockSource
from src.common.contract import StationConfig
from src.common.mock_data import load_mock
from src.pricing.config import PricingConfig

NOON = datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)


def plan_at(wholesale, adder=40.0, cfg=None):
    station = load_mock("station", StationConfig)
    source = MockSource()
    forecast = source.forecast(station.pt_id, NOON)
    grid = source.grid_state(station.pt_id, NOON)
    return make_plan(
        forecast, grid, station, NOON, wholesale_eur_mwh=wholesale, adder_eur_mwh=adder, pricing=cfg
    )


def test_no_wholesale_price_means_no_prices():
    assert plan_at(None).prices == []


def test_price_is_hourly_plus_adder_for_every_house():
    plan = plan_at(100.0, 40.0, PricingConfig(fee_eur_mwh=30.0))
    assert len(plan.prices) == 8 and {p.house_id for p in plan.prices} == {
        h.house_id for h in load_mock("station", StationConfig).houses
    }
    first = plan.prices[0]
    assert first.wholesale_eur_mwh == 100.0
    assert first.hourly_eur_kwh == pytest.approx(0.07)  # 100 - 30 EUR/MWh
    assert first.adder_eur_kwh == pytest.approx(0.04)
    assert first.total_eur_kwh == pytest.approx(0.11)
    assert not first.floor_applied and first.reason.startswith("hourly price")


def test_the_floor_applies_when_wholesale_minus_fee_is_below_it():
    plan = plan_at(20.0, 40.0, PricingConfig(fee_eur_mwh=30.0, floor_eur_mwh=5.0))
    first = plan.prices[0]
    assert first.floor_applied and first.hourly_eur_kwh == pytest.approx(0.005)
    assert first.total_eur_kwh == pytest.approx(0.045) and first.reason.startswith("floor")


def test_negative_wholesale_pays_the_floor_never_a_charge():
    plan = plan_at(-20.0, 0.0)
    assert all(p.hourly_eur_kwh == 0.0 and p.total_eur_kwh >= 0 for p in plan.prices)
```

`tests/test_service_prices.py`:

```python
from datetime import datetime, timezone

from src.agent.guard import stub_guard
from src.agent.log import ActionLog
from src.agent.service import AgentService
from src.agent.sources import MockSource
from src.common.contract import StationConfig
from src.common.mock_data import load_mock
from src.pricing.source import mock_source

NOON = datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)


def service(tmp_path, prices):
    return AgentService(
        load_mock("station", StationConfig),
        ActionLog(tmp_path / "a.jsonl"),
        stub_guard,
        MockSource(),
        prices=prices,
    )


def test_propose_attaches_prices_from_the_source(tmp_path):
    plan = service(tmp_path, mock_source()).propose(NOON)
    first = plan.prices[0]
    assert len(plan.prices) == 8 and first.wholesale_eur_mwh == 15.0  # 13:00 Bucharest
    assert first.adder_eur_kwh > 0 and first.hourly_eur_kwh == 0.0  # 15 EUR/MWh < 30 fee


def test_without_a_source_the_plan_has_no_prices(tmp_path):
    assert service(tmp_path, None).propose(NOON).prices == []


def test_price_view_has_curve_and_houses(tmp_path):
    svc = service(tmp_path, mock_source())
    assert svc.price_view(NOON)["houses"] == []  # nothing proposed yet
    svc.propose(NOON)
    view = svc.price_view(NOON)
    assert view["mock"] is True and len(view["curve"]) == 24 and len(view["houses"]) == 8
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/python -m pytest tests/test_planner_prices.py tests/test_service_prices.py -q`
Expected: FAIL, `unexpected keyword argument 'wholesale_eur_mwh'` / `'prices'`.

- [ ] **Step 3: Implement.**

Change to `src/agent/planner.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/src/agent/planner.py b/src/agent/planner.py
index e469a81..fedadab 100644
--- a/src/agent/planner.py
+++ b/src/agent/planner.py
@@ -6,21 +6,57 @@ from src.common.contract import (
     Forecast,
     GridState,
     HouseLimit,
+    HousePrice,
     Plan,
     StationConfig,
 )
+from src.pricing.config import PricingConfig
+from src.pricing.tariff import hourly_price
 
 
 def plan_id_for(pt_id: str, interval_start: AwareDatetime) -> str:
     return f"PLAN-{interval_start.astimezone(timezone.utc):%Y-%m-%d-%H%M}-{pt_id}"
 
 
+def house_prices(
+    station: StationConfig,
+    interval_start: AwareDatetime,
+    wholesale_eur_mwh: float,
+    adder_eur_mwh: float,
+    cfg: PricingConfig,
+) -> list[HousePrice]:
+    """The product's price for each house: hourly price plus the published solar adder."""
+    hourly = hourly_price(wholesale_eur_mwh, cfg)
+    floor_applied = wholesale_eur_mwh - cfg.fee_eur_mwh < cfg.floor_eur_mwh
+    reason = (
+        "floor applies: the wholesale price minus the fee is below the floor"
+        if floor_applied
+        else "hourly price: wholesale minus the fee, plus the solar adder"
+    )
+    return [
+        HousePrice(
+            house_id=house.house_id,
+            interval_start=interval_start,
+            wholesale_eur_mwh=wholesale_eur_mwh,
+            hourly_eur_kwh=round(hourly / 1000, 6),
+            adder_eur_kwh=round(adder_eur_mwh / 1000, 6),
+            total_eur_kwh=round(hourly / 1000, 6) + round(adder_eur_mwh / 1000, 6),
+            floor_applied=floor_applied,
+            reason=reason,
+        )
+        for house in station.houses
+    ]
+
+
 def make_plan(
     forecast: Forecast | None,
     grid_state: GridState | None,
     station: StationConfig,
     interval_start: AwareDatetime | None = None,
     force_abstain: str | None = None,
+    wholesale_eur_mwh: float | None = None,
+    adder_eur_mwh: float = 0.0,
+    pricing: PricingConfig | None = None,
 ) -> Plan:
     if forecast is None and interval_start is None:
         raise ValueError("interval_start is required when there is no forecast")
@@ -70,6 +106,13 @@ def make_plan(
             limit = min(limit, house.contract_cap_kw)
         limits.append(HouseLimit(house_id=house.house_id, export_limit_kw=round(limit, 3)))
 
+    prices = (
+        []
+        if wholesale_eur_mwh is None
+        else house_prices(
+            station, interval_start, wholesale_eur_mwh, adder_eur_mwh, pricing or PricingConfig()
+        )
+    )
     return Plan(
         plan_id=plan_id_for(station.pt_id, interval_start),
         pt_id=station.pt_id,
@@ -91,5 +134,6 @@ def make_plan(
                 reason=reason_for_text,
             )
         ),
+        prices=prices,
         status="proposed",
     )
```

Change to `src/agent/service.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/src/agent/service.py b/src/agent/service.py
index c941b07..86cdb8e 100644
--- a/src/agent/service.py
+++ b/src/agent/service.py
@@ -8,9 +8,10 @@ from threading import RLock
 from src.agent.explain import add_factors, ensure_grounded
 from src.agent.guard import Guard
 from src.agent.log import ActionLog
-from src.agent.planner import make_plan
+from src.agent.planner import make_plan, plan_id_for
 from src.agent.sources import Source, floor_to_half_hour
 from src.common.contract import ActionEvent, AwareDatetime, EventType, Plan, StationConfig
+from src.pricing.source import PriceSource
 
 logger = logging.getLogger(__name__)
 
@@ -41,6 +42,7 @@ class AgentService:
         source: Source,
         clock: Callable[[], datetime] = _utcnow,
         thresholds: Callable[[str], float | None] | None = None,
+        prices: PriceSource | None = None,
     ):
         self.station = station
         self.log = log
@@ -48,6 +50,7 @@ class AgentService:
         self.source = source
         self.clock = clock
         self.thresholds = thresholds
+        self.prices = prices
         self._plans: dict[str, Plan] = {}
         self._retryable: set[str] = set()
         self._reviews: list[datetime] = []
@@ -133,6 +136,18 @@ class AgentService:
         explanation = add_factors(plan.explanation, factors_of(pt_id, interval_start), LABELS)
         return plan.model_copy(update={"explanation": ensure_grounded(explanation)})
 
+    def price_view(self, when: AwareDatetime) -> dict:
+        """Day curve of the wholesale price and, if a plan exists, each house's price."""
+        when = floor_to_half_hour(when.astimezone(timezone.utc))
+        with self._lock:
+            plan = self._plans.get(plan_id_for(self.station.pt_id, when))
+        return {
+            "interval_start": when,
+            "mock": bool(self.prices and self.prices.mock),
+            "curve": self.prices.day_curve(when) if self.prices else [],
+            "houses": plan.prices if plan else [],
+        }
+
     def propose(self, interval_start: AwareDatetime, actor: str = "agent") -> Plan:
         with self._lock:
             interval_start = floor_to_half_hour(interval_start.astimezone(timezone.utc))
@@ -140,7 +155,16 @@ class AgentService:
             forecast = self.source.forecast(pt_id, interval_start)
             grid_state = self.source.grid_state(pt_id, interval_start)
             station, forced = self._threshold_station()
-            plan = make_plan(forecast, grid_state, station, interval_start, force_abstain=forced)
+            wholesale = self.prices.wholesale(interval_start) if self.prices else None
+            plan = make_plan(
+                forecast,
+                grid_state,
+                station,
+                interval_start,
+                force_abstain=forced,
+                wholesale_eur_mwh=wholesale,
+                adder_eur_mwh=self.prices.adder(interval_start) if self.prices else 0.0,
+            )
             plan = self._with_factors(plan, pt_id, interval_start)
             existing = self._plans.get(plan.plan_id)
             if existing is not None and not (
```

Change to `src/agent/wiring.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/src/agent/wiring.py b/src/agent/wiring.py
index 48b688d..cb8e905 100644
--- a/src/agent/wiring.py
+++ b/src/agent/wiring.py
@@ -5,6 +5,7 @@ from src.agent.sources import make_source
 from src.common.config import Settings
 from src.common.contract import StationConfig
 from src.common.mock_data import load_mock
+from src.pricing.source import price_source_for
 
 
 def build_service(settings: Settings) -> AgentService:
@@ -21,10 +22,12 @@ def build_service(settings: Settings) -> AgentService:
             guard=make_grid_guard(station, source),
             source=source,
             thresholds=threshold,
+            prices=price_source_for(settings),
         )
     return AgentService(
         station=load_mock("station", StationConfig),
         log=open_log(settings.log_uri),
         guard=stub_guard,
         source=make_source(settings),
+        prices=price_source_for(settings),
     )
```

Change to `src/grid/demo_api.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/src/grid/demo_api.py b/src/grid/demo_api.py
index 14cd88f..a1472c7 100644
--- a/src/grid/demo_api.py
+++ b/src/grid/demo_api.py
@@ -15,6 +15,7 @@ from src.common.config import Settings
 from src.common.contract import StationConfig
 from src.common.mock_data import load_mock
 from src.grid.agent_guard import make_grid_guard
+from src.pricing.source import price_source_for
 
 settings = Settings.from_env()
 _station = load_mock("station", StationConfig)
@@ -31,5 +32,6 @@ app = create_app(
         log=open_log(settings.log_uri),
         guard=make_grid_guard(_station, _source, _grid_config),
         source=_source,
+        prices=price_source_for(settings),
     ),
 )
```

- [ ] **Step 4: Run to see them pass**

Run: `.venv/bin/python -m pytest -q --ignore=tests/eval --ignore=tests/ml`
Expected: all pass (existing planner and service tests do not pass `prices`).

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "feat(agent): attach the product price per house to each plan"
```

---

### Task 15: `GET /prices` and the screen's allowlist

**Files:** modify `src/agent/api.py`, `src/ui/app.py`, `README.md`; tests `tests/test_api_prices.py`, `tests/test_ui_app.py`.

- [ ] **Step 1: Failing tests**

`tests/test_api_prices.py`:

```python
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.agent.api import create_app
from src.agent.guard import stub_guard
from src.agent.log import ActionLog
from src.agent.service import AgentService
from src.agent.sources import MockSource
from src.common.config import Settings
from src.common.contract import StationConfig
from src.common.mock_data import load_mock
from src.pricing.source import mock_source

NOON = "2025-06-21T10:00:00Z"


def client(tmp_path, prices=None):
    service = AgentService(
        load_mock("station", StationConfig),
        ActionLog(tmp_path / "a.jsonl"),
        stub_guard,
        MockSource(),
        clock=lambda: datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc),
        prices=prices,
    )
    return TestClient(create_app(Settings(), service))


def test_prices_before_and_after_a_plan(tmp_path):
    c = client(tmp_path, mock_source())
    before = c.get("/prices", params={"interval_start": NOON}).json()
    assert before["mock"] is True and len(before["curve"]) == 24 and before["houses"] == []
    c.post("/plan/propose", json={"interval_start": NOON})
    after = c.get("/prices", params={"interval_start": NOON}).json()
    first = after["houses"][0]
    assert len(after["houses"]) == 8 and first["total_eur_kwh"] >= first["hourly_eur_kwh"]


def test_prices_without_a_source_is_empty_not_an_error(tmp_path):
    body = client(tmp_path).get("/prices", params={"interval_start": NOON}).json()
    assert body["curve"] == [] and body["houses"] == [] and body["mock"] is False
```

Change to `tests/test_ui_app.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/tests/test_ui_app.py b/tests/test_ui_app.py
index 6c422e9..137d257 100644
--- a/tests/test_ui_app.py
+++ b/tests/test_ui_app.py
@@ -16,12 +16,17 @@ OK = Response(b"{}", media_type="application/json")
 
 
 class AllowlistTests(unittest.TestCase):
+    def test_prices_is_read_only(self):
+        self.assertTrue(is_allowed("GET", "prices"))
+        self.assertFalse(is_allowed("POST", "prices"))
+
     def test_agent_reads_and_writes_are_allowed(self):
         for path in (
             "health",
             "station",
             "forecast",
             "grid_state",
+            "prices",
             "plans",
             "queue",
             "log",
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/python -m pytest tests/test_api_prices.py tests/test_ui_app.py -q`
Expected: FAIL (`404` on `/prices`; `prices` not allowed).

- [ ] **Step 3: Implement.**

Change to `src/agent/api.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/src/agent/api.py b/src/agent/api.py
index 23f1395..d36610d 100644
--- a/src/agent/api.py
+++ b/src/agent/api.py
@@ -73,6 +73,10 @@ def create_app(settings: Settings | None = None, service: AgentService | None =
             raise HTTPException(status_code=404, detail="no grid state")
         return found
 
+    @app.get("/prices")
+    def prices(interval_start: AwareDatetime | None = Query(default=None)):
+        return service.price_view(interval_start or floor_to_half_hour())
+
     @app.post("/plan/propose", dependencies=[Depends(require_token)])
     def propose(body: ProposeRequest | None = None):
         body = body or ProposeRequest()
```

Change to `src/ui/app.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/src/ui/app.py b/src/ui/app.py
index 50f28d3..84235ff 100644
--- a/src/ui/app.py
+++ b/src/ui/app.py
@@ -25,7 +25,9 @@ STATIC = Path(__file__).parent / "static"
 MOCK_INSIGHT = Path(__file__).parent / "mocks" / "ai_insight.json"
 # One name or id: letters, digits, "_" and "-", optionally joined by single dots. No "." or "..".
 NAME = r"[\w\-]+(?:\.[\w\-]+)*"
-READ = re.compile(rf"(health|station|forecast|grid_state|plans|plan/{NAME}|queue|log|kill_switch)")
+READ = re.compile(
+    rf"(health|station|forecast|grid_state|prices|plans|plan/{NAME}|queue|log|kill_switch)"
+)
 WRITE = re.compile(rf"(plan/propose|plan/{NAME}/(approve|reject|execute)|kill_switch)")
 RUN_ID = re.compile(NAME)
 FORWARD_HEADERS = ("content-type", "x-demo-token")
```

- [ ] **Step 4: Run to see them pass**

Run: `make test lint smoke`
Expected: all pass, `SMOKE OK`.

- [ ] **Step 5: README and commit.** In `README.md` section 4 (demo) add after the "Open http://127.0.0.1:8001" line: "Each plan also carries the product's price per house (hourly price plus a monthly solar adder); `GET /prices` returns the day's wholesale curve and those prices. The demo uses an illustrative curve, marked `mock`."

```bash
git add src README.md tests
git commit -m "feat(agent): add GET /prices and let the screen read it"
```

Ask the user before pushing `pricing/api`; name P1 as the owner to review.

---

# Phase 4: the Prices tab (branch `pricing/ui`)

Cut from `main` after phases 1 and 3 are merged (phase 2's table fills in only after it).

### Task 16: The tab

**Files:** modify `src/ui/static/index.html`; test `tests/test_ui_app.py`.

The tab shows the day's wholesale curve with the selected hour marked, each house's price and reason (from `GET /prices`), the earnings table from the evaluation summary (`pricing.rows`) and the imbalance table (`pricing.imbalance.scenarios`). It works with the mock curve and says "Mock".

- [ ] **Step 1: Branch and failing test**

```bash
git switch main && git pull && git switch -c pricing/ui
```

Change to `tests/test_ui_app.py` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/tests/test_ui_app.py b/tests/test_ui_app.py
index 137d257..2fb0528 100644
--- a/tests/test_ui_app.py
+++ b/tests/test_ui_app.py
@@ -230,3 +230,11 @@ class UiAppTests(unittest.TestCase):
 
 if __name__ == "__main__":
     unittest.main()
+
+
+class PricesTabTests(unittest.TestCase):
+    def test_screen_has_the_prices_tab_and_panel(self):
+        html = TestClient(create_app(Settings())).get("/").text
+        for needle in ('id="tab-prices"', 'id="p-prices"', 'id="priceChart"', 'id="rev"'):
+            self.assertIn(needle, html)
+        self.assertIn('"compare", "prices"]', html)
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_ui_app.py -q`
Expected: FAIL, `'id="tab-prices"' not found`.

- [ ] **Step 3: Implement.**

Change to `src/ui/static/index.html` (apply by hand or save as a patch and run `git apply`):

```diff
diff --git a/src/ui/static/index.html b/src/ui/static/index.html
index 397025c..de07b97 100644
--- a/src/ui/static/index.html
+++ b/src/ui/static/index.html
@@ -181,6 +181,7 @@ a{color:var(--ink)}
     <button class="tab" role="tab" id="tab-decision" aria-controls="p-decision" aria-selected="false" tabindex="-1" type="button">Decision</button>
     <button class="tab" role="tab" id="tab-log" aria-controls="p-log" aria-selected="false" tabindex="-1" type="button">Log</button>
     <button class="tab" role="tab" id="tab-compare" aria-controls="p-compare" aria-selected="false" tabindex="-1" type="button">Comparison</button>
+    <button class="tab" role="tab" id="tab-prices" aria-controls="p-prices" aria-selected="false" tabindex="-1" type="button">Prices</button>
   </nav>
 
   <section class="panel" id="p-houses" role="tabpanel" aria-labelledby="tab-houses">
@@ -234,13 +235,25 @@ a{color:var(--ink)}
     <div class="scroll"><table id="cmp" hidden><thead></thead><tbody></tbody></table></div>
   </section>
 
+  <section class="panel" id="p-prices" role="tabpanel" aria-labelledby="tab-prices" hidden>
+    <h2 class="h">Price for injected energy <span class="tag" id="priceTag" hidden>Mock</span></h2>
+    <p class="sub" id="priceNote">Loading prices…</p>
+    <svg id="priceChart" viewBox="0 0 960 120" preserveAspectRatio="none" role="img" aria-label="Wholesale price over the day"></svg>
+    <div class="scroll"><table id="priceTable" hidden><thead><tr><th>House</th><th>Hourly price</th><th>Solar adder</th><th>Total</th><th>Why</th></tr></thead><tbody></tbody></table></div>
+    <h2 class="h" style="margin-top:18px">What prosumers with a battery earn, and PPC's margin</h2>
+    <p class="sub" id="revNote">Loading evaluation output…</p>
+    <div class="scroll"><table id="rev" hidden><thead></thead><tbody></tbody></table></div>
+    <h2 class="h" style="margin-top:18px">Imbalance savings on top <span class="sub" style="text-transform:none;letter-spacing:0;font-weight:400">(spreads are scenarios)</span></h2>
+    <div class="scroll"><table id="imb" hidden><thead></thead><tbody></tbody></table></div>
+  </section>
+
   <footer>Simulated data. The grid is a model, not PPC's network, and nothing here controls real inverters. · <a href="/simulation">210-house simulation viewer</a></footer>
 </div>
 
 <script>
 "use strict";
 const $ = id => document.getElementById(id);
-const state = {station: null, plan: null, plans: [], fc: null, kill: false, busy: false, selected: null, geo: null, insight: null, insightFor: null,
+const state = {prices: null, station: null, plan: null, plans: [], fc: null, kill: false, busy: false, selected: null, geo: null, insight: null, insightFor: null,
   allowed: {approve: false, reject: false, execute: false}};
 let gen = 0; // generation of the latest refresh: results of older ones are dropped
 const pct = v => v == null ? "—" : (v * 100).toFixed(0) + "%";
@@ -280,7 +293,7 @@ function intervalStart() {
 const slotOf = iso => Number(iso.slice(11, 13)) * 2 + (iso.slice(14, 16) === "30" ? 1 : 0);
 
 /* ---------- tabs ---------- */
-const TABS = ["houses", "queue", "decision", "log", "compare"];
+const TABS = ["houses", "queue", "decision", "log", "compare", "prices"];
 function showTab(name, focus) {
   if (!TABS.includes(name)) name = "houses";
   TABS.forEach(t => {
@@ -694,6 +707,78 @@ async function loadComparison() {
   if (!body.children.length) note.textContent += " The summary has no rows.";
 }
 
+/* ---------- prices ---------- */
+const SVGNS = "http://www.w3.org/2000/svg";
+function svgEl(tag, attrs) {
+  const n = document.createElementNS(SVGNS, tag);
+  Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
+  return n;
+}
+const signed = (v, d = 1, unit = "") => v == null ? "—" : (v >= 0 ? "+" : "") + Number(v).toFixed(d) + unit;
+const ctKwh = v => v == null ? "—" : (v * 100).toFixed(2) + " ct/kWh";
+
+function fillTable(table, headers, rows) {
+  const head = table.tHead, body = table.tBodies[0]; head.replaceChildren(); body.replaceChildren();
+  const hr = el("tr"); headers.forEach(h => hr.append(el("th", h))); head.append(hr);
+  rows.forEach(cells => { const r = el("tr"); cells.forEach(c => r.append(el("td", c))); body.append(r); });
+  table.hidden = !rows.length;
+}
+
+function drawPriceChart(d) {
+  const box = $("priceChart"); box.replaceChildren();
+  const pts = d.curve.map((c, i) => [i, c.wholesale_eur_mwh]).filter(p => p[1] != null);
+  if (!pts.length) return;
+  const lo = Math.min(0, ...pts.map(p => p[1])), hi = Math.max(1, ...pts.map(p => p[1]));
+  const x = i => (i / 23) * 940 + 10, y = v => 105 - ((v - lo) / (hi - lo)) * 95;
+  box.append(svgEl("line", {x1: 10, x2: 950, y1: y(0), y2: y(0), stroke: "currentColor", "stroke-opacity": ".25"}));
+  box.append(svgEl("polyline", {points: pts.map(p => x(p[0]) + "," + y(p[1])).join(" "), fill: "none", stroke: "currentColor", "stroke-width": "2", "vector-effect": "non-scaling-stroke"}));
+  const hour = new Date(d.interval_start).getUTCHours();
+  box.append(svgEl("line", {x1: x(hour), x2: x(hour), y1: 0, y2: 115, stroke: "var(--rev)", "stroke-width": "2", "vector-effect": "non-scaling-stroke"}));
+}
+
+function renderPrices() {
+  const d = state.prices; if (!d) return;
+  $("priceTag").hidden = !d.mock;
+  const note = $("priceNote");
+  if (!d.curve.length) { note.textContent = "This agent has no price source."; $("priceChart").replaceChildren(); $("priceTable").hidden = true; return; }
+  const at = d.interval_start.slice(0, 10) + " " + d.interval_start.slice(11, 16) + " UTC";
+  const now = d.curve.find(c => c.ts.slice(0, 13) === d.interval_start.slice(0, 13));
+  note.textContent = "Wholesale (day-ahead) price at " + at + ": " + (now && now.wholesale_eur_mwh != null ? num(now.wholesale_eur_mwh, 0) + " EUR/MWh. " : "not available. ") +
+    (d.mock ? "Illustrative curve, not market data. " : "") + (d.houses.length ? "" : "Propose a plan to see each house's price.");
+  drawPriceChart(d);
+  fillTable($("priceTable"), ["House", "Hourly price", "Solar adder", "Total", "Why"],
+    d.houses.map(h => [h.house_id, ctKwh(h.hourly_eur_kwh), ctKwh(h.adder_eur_kwh), ctKwh(h.total_eur_kwh), h.reason]));
+}
+
+async function loadPrices(t, my) {
+  let data;
+  try { data = await api("prices?interval_start=" + encodeURIComponent(t)); }
+  catch (e) { if (my === gen) $("priceNote").textContent = "Prices are not available: " + e.message; return; }
+  if (my !== gen) return;
+  state.prices = data; renderPrices();
+}
+
+async function loadPricingEval() {
+  const note = $("revNote");
+  $("rev").hidden = true; $("imb").hidden = true;
+  let res;
+  try { res = await fetch("/eval/summary"); } catch (_) { note.textContent = "The screen server did not answer."; return; }
+  if (!res.ok) { note.className = "empty"; note.textContent = "No evaluation output yet. Run python -m src.eval.run --pricing, then reload."; return; }
+  const s = (await res.json()).summary, scenarios = s.scenarios || {};
+  const rows = [], imb = [];
+  Object.keys(scenarios).forEach(k => {
+    const block = scenarios[k].pricing; if (!block) return;
+    block.rows.forEach(r => rows.push([k + " · " + r.name, num(r.prosumer_eur, 0), signed(r.prosumer_vs_today_pct, 1, "%"), num(r.ppc_margin_eur, 0), signed(r.ppc_improvement_eur, 0)]));
+    ((block.imbalance || {}).scenarios || []).forEach(i => imb.push([k + " · " + num(i.spread_eur_mwh, 0) + " EUR/MWh", num(i.group_saving_eur, 0), num(i.prosumer_bonus_eur, 0), signed(i.prosumer_total_vs_today_pct, 1, "%"), signed(i.ppc_improvement_total_eur, 0)]));
+  });
+  fillTable($("rev"), ["Station · policy", "Prosumer (EUR)", "vs today", "PPC margin (EUR)", "PPC improvement (EUR)"], rows);
+  fillTable($("imb"), ["Station · spread", "Saved (EUR)", "Prosumer bonus (EUR)", "Prosumer total vs today", "PPC improvement incl. savings (EUR)"], imb);
+  note.className = "sub";
+  note.textContent = rows.length
+    ? (s.mock ? "MOCK, NOT A RESULT. " : "") + "Run " + s.run_id + ". Numbers come from the evaluation output; prices are matched to the Ausgrid year by season and hour, so this shows the shape of the effect, not a forecast in euros. Prices: euenergy.live (CC-BY-4.0)."
+    : "This evaluation run has no price block. Run python -m src.eval.run --pricing.";
+}
+
 /* ---------- map slot (filled by P4) ----------
    Contract: src/ui/static/map/README.md. A map module registers window.StationMap with
    mount(el, host), update(view) and optionally onShow() and destroy(). The screen never
@@ -736,7 +821,7 @@ async function refresh() {
   renderStrip();
   try {
     if (!state.station) await loadStation();
-    await Promise.all([loadKill, loadForecast, loadGrid, loadQueue, loadLog].map(f => f(t, my)));
+    await Promise.all([loadKill, loadForecast, loadGrid, loadQueue, loadLog, loadPrices].map(f => f(t, my)));
     await loadPlan(t, my);
     if (my === gen) loadDay();
   } catch (e) {
@@ -790,6 +875,7 @@ $("date").value = new Date().toISOString().slice(0, 10);
 showTab(location.hash.slice(1));
 renderStrip();
 loadComparison();
+loadPricingEval();
 loadMapModule();
 refresh();
 </script>
```

- [ ] **Step 4: Run it to see it pass, then look at it in a browser**

Run: `make test lint smoke`
Expected: all pass.

Then check by eye with the browser tool, using free ports (another process may hold 8000/8010):

```bash
python -m uvicorn src.grid.demo_api:app --port 8020
```
```bash
API_URL=http://127.0.0.1:8020 python -m uvicorn src.ui.app:app --port 8021
```
Open http://127.0.0.1:8021/#prices. Expected: the "Mock" tag, a curve with a marker at the selected hour, a note saying "Illustrative curve", and the message "No evaluation output yet" (or the tables, if you start the screen with `EVAL_RUN_ID=<run with --pricing>` and `ARTIFACT_URI` pointing at it). Press "Propose plan", return to Prices: eight house rows appear with hourly price, adder, total and a reason (with the mock curve the midday wholesale price is below the fee, so the reason reads "floor applies"). Change the day with the arrows: the curve and marker update. Two 404s in the console for the optional map files are expected. Report what you saw; if anything is off, say so. Stop both servers when done.

- [ ] **Step 5: README and commit.** In `README.md` section 4 add: "The **Prices** tab shows the day's wholesale curve, each house's price for the selected half-hour, and, after `python -m src.eval.run --pricing`, what battery owners earn and PPC's margin under each price (start the screen with `EVAL_RUN_ID=<run id>` to pick the run)."

```bash
git add src/ui tests README.md
git commit -m "feat(ui): add the Prices tab"
```

Ask the user before pushing `pricing/ui`.

---

## Self-review against the spec

- **Scheme (hourly price, floor, fee, adder, bonus share):** Tasks 1, 3, 6, 11. The bonus is paid from imbalance savings only (Task 11).
- **Profit view and sensitivity:** `rows` and `sensitivity` in Task 6; imbalance scenarios in Task 11. Percentages are in the block (`prosumer_vs_today_pct`, `ppc_margin_pct_of_value`).
- **Baseline is the regulated monthly average:** `settle(...)["regulated_eur"]`, row 1 of the table.
- **Battery core, consent-based, no control:** Task 5; the agent API shows prices only (Task 14).
- **No grid data in the price (unbundling):** `house_prices` takes no grid input.
- **Data, season alignment, User-Agent, gaps:** Task 2.
- **API, contract, mocks, P1 sign-off:** Tasks 12–15. The mock plan JSON needs no change (`prices` defaults to empty).
- **UI and README, no trailers, no push without a yes:** Tasks 7, 15, 16 and the rules.
- **Limits stated:** "What the numbers mean" above and the spec's risks.
