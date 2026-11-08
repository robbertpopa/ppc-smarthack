# Dynamic buy-back pricing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pay prosumers a buy-back price linked to the hourly wholesale price (plus a grid bonus), show it per house in the agent API and the operator screen, and measure what a battery adds.

**Architecture:** A new `src/pricing/` package holds the pure parts (price loader, tariff rule, revenue, battery dispatch). The evaluation (`src/eval/`) reads it to produce a revenue block per scenario. The agent (`src/agent/`) attaches a `HousePrice` per house to each plan, and the screen (`src/ui/`) shows it. The safe-cap model is never touched.

**Tech Stack:** Python 3.12, pandas, numpy, pydantic, FastAPI, pytest, ruff; plain JS in `src/ui/static/index.html`.

Spec: [docs/superpowers/specs/2026-11-08-dynamic-buyback-pricing-design.md](../specs/2026-11-08-dynamic-buyback-pricing-design.md).

---

## Rules for every task (team rules, from [docs/11-commit-plan.md](../../11-commit-plan.md))

- **Commits:** conventional (`feat(pricing): …`, `test(…)`, `docs: …`), imperative, English. **No trailers** (no `Co-Authored-By`, no "Generated with"): this overrides tool defaults. One logical change per commit, tests in the same commit. Every commit passes `make test lint smoke`.
- **Never commit** `data/`, `.env`, tokens, parquet files. `EUENERGY_TOKEN` lives in the gitignored `.env`; export it with `set -a; . ./.env; set +a`.
- **Push, open a PR, merge: ask the user first.** Each "yes" covers one action. Commit locally on the phase branch.
- **Branches:** one per phase, cut from an up-to-date `main`: `pricing/core`, `pricing/api`, `pricing/battery`, `pricing/ui`. PR under about 300 changed lines where possible; if a phase is larger, say so in the PR.
- **Ownership:** phase 2 edits `src/common/` and `src/agent/` (P1). Phase 1 and 3 edit `src/eval/` (P2/P6 are also changing it: `git switch main && git pull` and rebase before opening the PR). Name the owner in the PR description.
- **README rule:** a step that changes how the project runs updates `README.md` in the same PR (each phase ends with that task).
- Run Python as `.venv/bin/python -m …`; the Makefile does the same.

## File structure

| File | Responsibility | Phase |
|---|---|---|
| `src/pricing/__init__.py` | package marker | 1 |
| `src/pricing/config.py` | `PricingConfig`: share, fee, bonus | 1 |
| `src/pricing/tariff.py` | pure buy-back rule, scalar and series | 1 |
| `src/pricing/prices.py` | fetch, save, load, profile, align PZU prices; CLI `fetch` | 1 |
| `src/pricing/revenue.py` | revenue under flat / dynamic / dynamic+bonus | 1 |
| `src/eval/pricing_eval.py` | evaluation block, markdown, chart | 1, 3 |
| `src/eval/run.py` | `--pricing` flag, wires the block into the summary | 1 |
| `src/smoke.py` | add `pricing` to the import check | 1 |
| `src/common/contract.py` | `HousePrice`, `Plan.prices` | 2 |
| `src/pricing/source.py` | `PriceSource`: wholesale price at a time, day curve, mock curve | 2 |
| `src/agent/planner.py` | `house_prices`, `make_plan(..., wholesale_eur_mwh)` | 2 |
| `src/agent/service.py`, `wiring.py`, `src/grid/demo_api.py` | pass the price source in; `price_view` | 2 |
| `src/agent/api.py` | `GET /prices` | 2 |
| `src/pricing/battery.py` | pure battery dispatch for one house | 3 |
| `src/ui/app.py`, `src/ui/static/index.html` | allow `prices`; "Prices" tab | 2, 4 |
| `tests/pricing/…`, `tests/eval/test_pricing_eval.py`, `tests/test_*prices*.py` | tests | all |

---

# Phase 1: pricing core (branch `pricing/core`)

### Task 1: Config and tariff rule

**Files:**
- Create: `src/pricing/__init__.py` (empty), `src/pricing/config.py`, `src/pricing/tariff.py`
- Test: `tests/pricing/test_tariff.py`

- [ ] **Step 1: Create the branch and the failing test**

```bash
git switch main && git pull && git switch -c pricing/core
mkdir -p tests/pricing src/pricing && touch src/pricing/__init__.py
```

`tests/pricing/test_tariff.py`:

```python
import numpy as np
import pandas as pd
import pytest

from src.pricing.config import PricingConfig
from src.pricing.tariff import buyback_price, buyback_price_series


def test_tariff_rules():
    cfg = PricingConfig(share=0.85, fee_eur_kwh=0.0, bonus_pct=0.10)
    assert buyback_price(100.0, False, cfg) == pytest.approx(0.085)
    assert buyback_price(100.0, True, cfg) == pytest.approx(0.0935)
    assert buyback_price(0.0, True, cfg) == 0.0
    assert buyback_price(-50.0, True, cfg) == 0.0
    assert buyback_price(100.0, False, PricingConfig(fee_eur_kwh=0.2)) == 0.0


def test_bad_inputs_are_refused():
    with pytest.raises(ValueError):
        buyback_price(float("nan"), True)
    with pytest.raises(ValueError):
        PricingConfig(share=1.5)
    with pytest.raises(ValueError):
        PricingConfig(bonus_pct=-0.1)


def test_series_matches_scalar():
    wholesale = pd.Series([100.0, -5.0, np.nan, 200.0])
    headroom = pd.Series([True, True, True, False])
    out = buyback_price_series(wholesale, headroom)
    assert out.iloc[0] == pytest.approx(buyback_price(100.0, True))
    assert out.iloc[1] == 0.0 and np.isnan(out.iloc[2])
    assert out.iloc[3] == pytest.approx(buyback_price(200.0, False))
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
    share: float = 0.85
    fee_eur_kwh: float = 0.0
    bonus_pct: float = 0.10

    def __post_init__(self):
        if not 0 <= self.share <= 1:
            raise ValueError("share must be between 0 and 1")
        if self.fee_eur_kwh < 0 or self.bonus_pct < 0:
            raise ValueError("fee and bonus must not be negative")
```

`src/pricing/tariff.py`:

```python
import math

import pandas as pd

from src.pricing.config import PricingConfig

DEFAULT = PricingConfig()


def buyback_price(
    wholesale_eur_mwh: float, headroom: bool, cfg: PricingConfig = DEFAULT
) -> float:
    """Buy-back price in EUR/kWh for one hour."""
    if not math.isfinite(wholesale_eur_mwh):
        raise ValueError("the wholesale price must be a finite number")
    base = max(0.0, cfg.share * wholesale_eur_mwh / 1000.0 - cfg.fee_eur_kwh)
    return base * (1 + cfg.bonus_pct) if headroom else base


def buyback_price_series(
    wholesale_eur_mwh: pd.Series, headroom: pd.Series, cfg: PricingConfig = DEFAULT
) -> pd.Series:
    """Same rule over a series; a missing wholesale price stays missing."""
    base = (cfg.share * wholesale_eur_mwh / 1000.0 - cfg.fee_eur_kwh).clip(lower=0.0)
    return base.where(~headroom.astype(bool), base * (1 + cfg.bonus_pct))
```

- [ ] **Step 4: Run it to see it pass**

Run: `.venv/bin/python -m pytest tests/pricing/test_tariff.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m ruff check src tests
git add src/pricing tests/pricing
git commit -m "feat(pricing): add the buy-back price rule"
```

---

### Task 2: Fetch, save and load the PZU prices

**Files:**
- Create: `src/pricing/prices.py`
- Test: `tests/pricing/test_prices.py`

The API: `GET https://euenergy.live/api/v1/prices?zone=RO&from=YYYY-MM-DD&to=YYYY-MM-DD` with `Authorization: Bearer <token>`. It returns `{"zone": "RO", "unit": "EUR/MWh", "hours": [{"ts": "2025-06-01T00:00:00.000Z", "price": 79.58, "currency": "EUR"}, …]}`. Hours can be missing (seen on 2024-01-01), so never assume 24 rows a day. Whether `to` is inclusive is not known: the code requests `[first of month, first of next month]`, drops duplicates and cuts to the year.

- [ ] **Step 1: Write the failing tests**

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


def fake_year(year):
    idx = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", tz="UTC", inclusive="left")
    return pd.Series(np.arange(len(idx), dtype=float) % 100, index=idx)


def test_parse_drops_duplicates_and_checks_unit():
    series = prices.parse_response(payload("2024-01-01", [(0, 1.0), (1, 2.0), (1, 3.0), (5, 4.0)]))
    assert list(series) == [1.0, 3.0, 4.0] and str(series.index.tz) == "UTC"
    with pytest.raises(ValueError):
        prices.parse_response(payload("2024-01-01", [], unit="RON/MWh"))
    with pytest.raises(ValueError):
        prices.parse_response({})


def test_fetch_year_and_round_trip(tmp_path):
    full = fake_year(2025)

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
    full = fake_year(2025)
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
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/python -m pytest tests/pricing/test_prices.py -q`
Expected: FAIL, `cannot import name 'prices'`.

- [ ] **Step 3: Implement** `src/pricing/prices.py`:

```python
"""Hourly Romanian day-ahead (PZU) prices: fetch, store, load, and align to the Ausgrid year."""

import argparse
import json
import os
import urllib.request
from collections.abc import Callable
from pathlib import Path

import pandas as pd

BASE_URL = "https://euenergy.live/api/v1/prices"
ZONE = "RO"
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
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
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

- [ ] **Step 4: Run to see them pass**

Run: `.venv/bin/python -m pytest tests/pricing/test_prices.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m ruff check src tests
git add src/pricing/prices.py tests/pricing/test_prices.py
git commit -m "feat(pricing): fetch and load hourly Romanian day-ahead prices"
```

---

### Task 3: Profile, season alignment and flat tariff

**Files:**
- Modify: `src/pricing/prices.py` (add three functions before `main`)
- Test: `tests/pricing/test_prices.py` (append)

Why the season shift: Ausgrid is Sydney. Sydney July is winter, Bucharest July is summer. Pairing equal calendar months would pair a winter sun with a summer price shape. The code pairs **Sydney month m with Bucharest month m+6**, and local clock hour with local clock hour. The pitch states this.

- [ ] **Step 1: Append the failing tests** to `tests/pricing/test_prices.py`:

```python
def test_profile_covers_every_month_and_hour():
    table = prices.profile(fake_year(2025))
    assert table.shape == (288,) and list(table.index.names) == ["month", "hour"]
    with pytest.raises(ValueError):
        prices.profile(fake_year(2025)[:2000])


def test_align_pairs_opposite_seasons_and_local_hours():
    table = prices.profile(fake_year(2025))
    winter = pd.Timestamp("2012-07-01 12:00", tz="Australia/Sydney")
    summer = pd.Timestamp("2013-01-15 12:30", tz="Australia/Sydney")
    when = pd.DatetimeIndex([winter, summer]).tz_convert("UTC")
    out = prices.align(when, table)
    assert out.iloc[0] == table.loc[(1, 12)]  # Sydney July -> Bucharest January
    assert out.iloc[1] == table.loc[(7, 12)]  # Sydney January -> Bucharest July
    assert list(out.index) == list(when)


def test_flat_tariff_is_the_yearly_mean_in_eur_per_kwh():
    assert prices.flat_tariff(pd.Series([100.0, 200.0])) == pytest.approx(0.15)
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/python -m pytest tests/pricing/test_prices.py -q`
Expected: 3 FAIL, `module 'src.pricing.prices' has no attribute 'profile'`.

- [ ] **Step 3: Implement.** Insert in `src/pricing/prices.py` just above `def main`:

```python
def profile(series: pd.Series) -> pd.Series:
    """Mean price for every (month, hour of day) in Bucharest time."""
    local = series.index.tz_convert(BUCHAREST)
    table = series.groupby([local.month, local.hour]).mean()
    table.index = table.index.set_names(["month", "hour"])
    if len(table.dropna()) != 12 * 24:
        raise ValueError("the price year must cover every month and every hour of the day")
    return table


def align(
    intervals: pd.DatetimeIndex,
    table: pd.Series,
    tz: str = SYDNEY,
    month_shift: int = SEASON_SHIFT_MONTHS,
) -> pd.Series:
    """Wholesale price (EUR/MWh) for each interval, by local clock hour and matching season."""
    local = intervals.tz_convert(tz)
    month = (local.month - 1 + month_shift) % 12 + 1
    keys = pd.MultiIndex.from_arrays([month, local.hour])
    return pd.Series(table.reindex(keys).to_numpy(), index=intervals, name="wholesale_eur_mwh")


def flat_tariff(series: pd.Series) -> float:
    """The flat baseline: the yearly average price, in EUR/kWh."""
    return float(series.mean()) / 1000.0
```

- [ ] **Step 4: Run to see them pass**

Run: `.venv/bin/python -m pytest tests/pricing/test_prices.py -q`
Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m ruff check src tests
git add src/pricing/prices.py tests/pricing/test_prices.py
git commit -m "feat(pricing): align prices to the Ausgrid year by season and local hour"
```

---

### Task 4: Revenue

**Files:**
- Create: `src/pricing/revenue.py`
- Test: `tests/pricing/test_revenue.py`

- [ ] **Step 1: Failing test** `tests/pricing/test_revenue.py`:

```python
import numpy as np
import pandas as pd
import pytest

from src.pricing.revenue import revenue


def test_revenue_by_hand():
    idx = pd.date_range("2025-01-01", periods=3, freq="30min", tz="UTC")
    kwh = pd.Series([1.0, 2.0, 4.0], index=idx)
    wholesale = pd.Series([100.0, 200.0, np.nan], index=idx)
    room = pd.Series([True, False, True], index=idx)
    out = revenue(kwh, wholesale, room, flat_eur_kwh=0.1)
    assert out["exported_kwh"] == 3.0 and out["n_without_price"] == 1
    assert out["flat_eur"] == pytest.approx(0.3)
    assert out["dynamic_eur"] == pytest.approx(1 * 0.085 + 2 * 0.17)
    assert out["dynamic_bonus_eur"] == pytest.approx(1 * 0.0935 + 2 * 0.17)
    assert out["avg_dynamic_eur_kwh"] == pytest.approx(out["dynamic_eur"] / 3.0)


def test_no_export_gives_no_average():
    idx = pd.DatetimeIndex([], tz="UTC")
    empty = pd.Series([], index=idx, dtype=float)
    out = revenue(empty, empty, empty.astype(bool), 0.1)
    assert out["exported_kwh"] == 0.0 and out["avg_dynamic_eur_kwh"] is None


def test_missing_headroom_is_an_error():
    idx = pd.date_range("2025-01-01", periods=2, freq="30min", tz="UTC")
    kwh = pd.Series([1.0, 1.0], index=idx)
    wholesale = pd.Series([50.0, 50.0], index=idx)
    with pytest.raises(ValueError):
        revenue(kwh, wholesale, pd.Series([True], index=idx[:1]), 0.1)
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/pricing/test_revenue.py -q`
Expected: FAIL, `No module named 'src.pricing.revenue'`.

- [ ] **Step 3: Implement** `src/pricing/revenue.py`:

```python
import pandas as pd

from src.pricing.config import PricingConfig
from src.pricing.tariff import DEFAULT, buyback_price_series


def revenue(
    exported_kwh: pd.Series,
    wholesale_eur_mwh: pd.Series,
    headroom: pd.Series,
    flat_eur_kwh: float,
    cfg: PricingConfig = DEFAULT,
) -> dict:
    """What a prosumer earns for the exported energy under three prices.

    Intervals without a wholesale price earn nothing and are counted in ``n_without_price``.
    """
    index = exported_kwh.index
    wholesale = wholesale_eur_mwh.reindex(index)
    room = headroom.reindex(index)
    if room.isna().any():
        raise ValueError("headroom is missing for some intervals")
    ok = wholesale.notna()
    kwh = exported_kwh[ok]
    base = buyback_price_series(wholesale[ok], pd.Series(False, index=kwh.index), cfg)
    bonus = buyback_price_series(wholesale[ok], room[ok].astype(bool), cfg)
    total = float(kwh.sum())
    dynamic = float((kwh * base).sum())
    with_bonus = float((kwh * bonus).sum())
    return {
        "exported_kwh": total,
        "n_without_price": int((~ok).sum()),
        "flat_eur": total * flat_eur_kwh,
        "dynamic_eur": dynamic,
        "dynamic_bonus_eur": with_bonus,
        "avg_flat_eur_kwh": flat_eur_kwh,
        "avg_dynamic_eur_kwh": dynamic / total if total > 0 else None,
        "avg_dynamic_bonus_eur_kwh": with_bonus / total if total > 0 else None,
    }
```

- [ ] **Step 4: Run to see it pass**

Run: `.venv/bin/python -m pytest tests/pricing -q`
Expected: all pass (14 tests).

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m ruff check src tests
git add src/pricing/revenue.py tests/pricing/test_revenue.py
git commit -m "feat(pricing): compute prosumer revenue under flat and dynamic prices"
```

---

### Task 5: The evaluation block

**Files:**
- Create: `src/eval/pricing_eval.py`
- Test: `tests/eval/test_pricing_eval.py`

`compute(ctx, result, table, flat_eur_kwh)` uses what `src/eval/run.py` already builds: `ctx["surplus"]` (interval × house kW, or `None`), `ctx["kwp"]`, and `result["scored"]["fallback"]` (the share actually applied, indexed by interval) and `result["scored"]["abstain"]`. It returns a JSON-safe dict, or `None` when there is no surplus table.

**Do not assert that dynamic revenue beats the flat tariff.** Exports happen in the cheapest hours, so a share of the spot price can pay less than the yearly average. The block reports the number and the sensitivity grid; it makes no claim.

- [ ] **Step 1: Failing tests** `tests/eval/test_pricing_eval.py`:

```python
import json

import numpy as np
import pandas as pd
import pytest

from src.eval import pricing_eval
from src.pricing import prices


def fake_year(year=2025):
    idx = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", tz="UTC", inclusive="left")
    return pd.Series(np.arange(len(idx), dtype=float) % 100 + 10.0, index=idx)


def make(days=3):
    idx = pd.date_range("2013-01-14", periods=48 * days, freq="30min", tz="UTC")
    hour = idx.tz_convert("Australia/Sydney").hour
    sun = np.where((hour >= 9) & (hour < 16), 8.0, 0.0)
    surplus = pd.DataFrame({"H1": sun, "H2": sun * 0.5}, index=idx)
    kwp = pd.Series({"H1": 10.0, "H2": 5.0})
    abstain = pd.Series(False, index=idx)
    abstain.iloc[:48] = True  # the first day falls back to the fixed limit
    share = pd.Series(0.5, index=idx).where(~abstain, 0.36)
    ctx = {"surplus": surplus, "kwp": kwp}
    result = {"scored": {"fallback": share, "abstain": abstain}}
    return ctx, result


@pytest.fixture(scope="module")
def table():
    return prices.profile(fake_year())


def test_block_numbers_and_shape(table):
    ctx, result = make()
    block = pricing_eval.compute(ctx, result, table, 0.1)
    # smart limit: min(8, 5) + min(4, 2.5) = 7.5 kW * 0.5 h * 14 sunny intervals * 2 days,
    # day one is on the fixed limit: (3.6 + 1.8) * 0.5 * 14
    assert block["model"]["exported_kwh"] == pytest.approx(5.4 * 0.5 * 14 + 7.5 * 0.5 * 14 * 2)
    assert block["fixed_limit"]["exported_kwh"] == pytest.approx(5.4 * 0.5 * 14 * 3)
    assert block["model"]["dynamic_bonus_eur"] > block["model"]["dynamic_eur"] > 0
    assert 0 < block["headroom_share"] < 1
    assert len(block["sensitivity"]) == 9
    assert [r["name"] for r in block["rows"]][0] == "Fixed limit, flat tariff"
    json.dumps(block, allow_nan=False)


def test_no_surplus_table_gives_none(table):
    ctx, result = make()
    assert pricing_eval.compute({**ctx, "surplus": None}, result, table, 0.1) is None


def test_markdown_is_written(tmp_path, table):
    ctx, result = make()
    block = pricing_eval.compute(ctx, result, table, 0.1)
    pricing_eval.write(tmp_path, "PT-A", block, "MOCK, NOT A RESULT")
    text = (tmp_path / "pricing_PT-A.md").read_text()
    assert text.startswith("# MOCK, NOT A RESULT") and "euenergy.live" in text
    assert "Smart limit, dynamic price + grid bonus" in text
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/eval/test_pricing_eval.py -q`
Expected: FAIL, `cannot import name 'pricing_eval'`.

- [ ] **Step 3: Implement** `src/eval/pricing_eval.py`:

```python
"""Revenue of the exported energy under a flat and a dynamic buy-back price."""

import math

import numpy as np
import pandas as pd

from src.eval.metrics import FIXED_SHARE, export_by_interval
from src.pricing import prices
from src.pricing.config import PricingConfig
from src.pricing.revenue import revenue

SHARES = (0.85, 0.95, 1.0)
BONUSES = (0.0, 0.10, 0.20)
TITLE = "Prosumer revenue: flat tariff versus dynamic buy-back price"
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


def _inputs(ctx: dict, result: dict, table: pd.Series) -> dict | None:
    surplus, kwp = ctx["surplus"], ctx["kwp"]
    if surplus is None:
        return None
    scored = result["scored"]
    index = scored["fallback"].index.intersection(surplus.index).sort_values()
    if len(index) == 0:
        return None
    share = scored["fallback"].loc[index]
    abstain = scored["abstain"].loc[index]
    fixed = pd.Series(FIXED_SHARE, index=index)
    return {
        "index": index,
        "share": share,
        "abstain": abstain,
        "wholesale": prices.align(index, table),
        "headroom": (~abstain) & (share >= FIXED_SHARE),
        "model_kwh": export_by_interval(share, surplus, kwp).reindex(index).fillna(0.0),
        "fixed_kwh": export_by_interval(fixed, surplus, kwp).reindex(index).fillna(0.0),
    }


def _row(name, kwh, eur, avg) -> dict:
    return {"name": name, "exported_kwh": kwh, "revenue_eur": eur, "avg_eur_kwh": avg}


def _rows(block: dict) -> list[dict]:
    fixed, model = block["fixed_limit"], block["model"]
    kwh, flat = model["exported_kwh"], model["avg_flat_eur_kwh"]
    dynamic, bonus = model["avg_dynamic_eur_kwh"], model["avg_dynamic_bonus_eur_kwh"]
    return [
        _row("Fixed limit, flat tariff", fixed["exported_kwh"], fixed["flat_eur"], flat),
        _row("Smart limit, flat tariff", kwh, model["flat_eur"], flat),
        _row("Smart limit, dynamic price", kwh, model["dynamic_eur"], dynamic),
        _row("Smart limit, dynamic price + grid bonus", kwh, model["dynamic_bonus_eur"], bonus),
    ]


def compute(
    ctx: dict,
    result: dict,
    table: pd.Series,
    flat_eur_kwh: float,
    cfg: PricingConfig = PricingConfig(),
) -> dict | None:
    """The revenue block of one scenario, or None when there is no surplus table."""
    data = _inputs(ctx, result, table)
    if data is None:
        return None
    index, wholesale, headroom = data["index"], data["wholesale"], data["headroom"]
    never = pd.Series(False, index=index)
    block = {
        "flat_eur_kwh": flat_eur_kwh,
        "n_intervals": len(index),
        "headroom_share": float(headroom.mean()),
        "fixed_limit": revenue(data["fixed_kwh"], wholesale, never, flat_eur_kwh, cfg),
        "model": revenue(data["model_kwh"], wholesale, headroom, flat_eur_kwh, cfg),
        "sensitivity": [
            {
                "share": s,
                "bonus_pct": b,
                "dynamic_bonus_eur": revenue(
                    data["model_kwh"],
                    wholesale,
                    headroom,
                    flat_eur_kwh,
                    PricingConfig(share=s, fee_eur_kwh=cfg.fee_eur_kwh, bonus_pct=b),
                )["dynamic_bonus_eur"],
            }
            for s in SHARES
            for b in BONUSES
        ],
    }
    block["rows"] = _rows(block)
    return _clean(block)


def _cell(value, digits):
    return "—" if value is None else f"{value:.{digits}f}"


def write(out, pt_id: str, block: dict, mock_title: str | None = None) -> None:
    """The markdown table next to the other evaluation outputs."""
    title = f"{mock_title} – {TITLE}" if mock_title else TITLE
    lines = [
        f"# {title}",
        "",
        f"Station {pt_id}. {SOURCE_NOTE}",
        "",
        "| Policy | Exported (kWh) | Revenue (EUR) | Average price (EUR/kWh) |",
        "|---|---:|---:|---:|",
    ]
    for r in block["rows"]:
        lines.append(
            f"| {r['name']} | {_cell(r['exported_kwh'], 1)} | {_cell(r['revenue_eur'], 2)} "
            f"| {_cell(r['avg_eur_kwh'], 4)} |"
        )
    lines += [
        "",
        "Sensitivity: smart limit, dynamic price + grid bonus, revenue in EUR.",
        "",
        "| Share of wholesale | Bonus | Revenue (EUR) |",
        "|---:|---:|---:|",
    ]
    for s in block["sensitivity"]:
        lines.append(
            f"| {s['share']:.2f} | {s['bonus_pct']:.2f} | {_cell(s['dynamic_bonus_eur'], 2)} |"
        )
    (out / f"pricing_{pt_id}.md").write_text("\n".join(lines) + "\n")
```

- [ ] **Step 4: Run to see it pass**

Run: `.venv/bin/python -m pytest tests/eval/test_pricing_eval.py -q && .venv/bin/python -m ruff check src tests`
Expected: `3 passed`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add src/eval/pricing_eval.py tests/eval/test_pricing_eval.py
git commit -m "feat(eval): add the prosumer revenue block"
```

---

### Task 6: Wire it into `python -m src.eval.run --pricing`

**Files:**
- Modify: `src/eval/run.py` (imports; `run()` signature and loop; `main()`)
- Test: `tests/eval/test_run.py` (append)

- [ ] **Step 1: Failing test.** Append to `tests/eval/test_run.py`:

```python
def test_pricing_flag_adds_the_revenue_block(env, first):
    from src.pricing import prices

    idx = pd.date_range("2025-01-01", "2026-01-01", freq="h", tz="UTC", inclusive="left")
    year = pd.Series(range(len(idx)), index=idx, dtype=float).mod(100) + 10
    prices.save(year, prices.prices_path())
    summary = eval_run.run(["A"], "priced", allow_mock=True, grid=FAST, pricing=True)
    scenario = next(iter(summary["scenarios"].values()))
    block = scenario["pricing"]
    assert block["model"]["exported_kwh"] > 0 and len(block["rows"]) >= 4
    assert list(eval_run.eval_dir("priced").glob("pricing_*.md"))
    plain = eval_run.run(["A"], "plain", allow_mock=True, grid=FAST)
    assert "pricing" not in next(iter(plain["scenarios"].values()))
```


- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/eval/test_run.py::test_pricing_flag_adds_the_revenue_block -q`
Expected: FAIL, `run() got an unexpected keyword argument 'pricing'`.

- [ ] **Step 3: Edit `src/eval/run.py`.**

1. Imports: change `from src.eval import table` to `from src.eval import pricing_eval, table` and add `from src.pricing import prices as price_data` after the `src.ml` imports (keep ruff's sort order).
2. `run()` signature: add `pricing=False,` after `grid=None,`.
3. After `all_rows, summary_scenarios, … = {}, {}, [], [], False` and `sections = []`, add:

```python
    price_inputs = None
    if pricing:
        series = price_data.load()
        price_inputs = (price_data.profile(series), price_data.flat_tariff(series))
```

4. In the loop, directly after the `if error_analysis:` block that appends to `sections`, add:

```python
        if price_inputs is not None:
            block = pricing_eval.compute(ctx, result, *price_inputs)
            if block is not None:
                extra = {**extra, "pricing": block}
                pricing_eval.write(out, pt_id, block, MOCK_TITLE if ctx["mock"] else None)
```

5. `main()`: add the argument and pass it:

```python
    parser.add_argument(
        "--pricing", action="store_true", help="also write the buy-back price revenue"
    )
```
and in the `run(...)` call add `pricing=args.pricing,` as the last argument.

- [ ] **Step 4: Run to see it pass**

Run: `.venv/bin/python -m pytest tests/eval -q`
Expected: all pass (existing tests unchanged, new one passes; this module trains small models, allow about a minute).

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m ruff check src tests
git add src/eval/run.py tests/eval/test_run.py
git commit -m "feat(eval): add --pricing to write the buy-back price revenue"
```

---

### Task 7: The summer-day chart

**Files:**
- Modify: `src/eval/pricing_eval.py` (add `day_chart`), `src/eval/run.py` (call it)
- Test: `tests/eval/test_pricing_eval.py` (append)

- [ ] **Step 1: Failing test.** Append:

```python
def test_summer_day_chart_is_written(tmp_path, table):
    pytest.importorskip("matplotlib")
    ctx, result = make()
    path = pricing_eval.day_chart(ctx, result, table, tmp_path, "PT-A")
    assert path.name == "pricing_day_PT-A.png" and path.stat().st_size > 1000


def test_chart_needs_a_summer_day(tmp_path, table):
    pytest.importorskip("matplotlib")
    ctx, result = make()
    shift = pd.Timedelta(days=120)  # mid-May to early June: Sydney autumn and winter
    surplus = ctx["surplus"]
    moved_ctx = {"surplus": surplus.set_axis(surplus.index + shift), "kwp": ctx["kwp"]}
    moved = {"scored": {k: v.set_axis(v.index + shift) for k, v in result["scored"].items()}}
    assert pricing_eval.day_chart(moved_ctx, moved, table, tmp_path, "PT-A") is None
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/eval/test_pricing_eval.py -q`
Expected: 2 FAIL, `has no attribute 'day_chart'`.

- [ ] **Step 3: Implement.** In `src/eval/pricing_eval.py` add `from src.pricing.tariff import buyback_price_series` to the imports and, above `_cell`:

```python
SUMMER_MONTHS = (12, 1, 2)  # Sydney summer, the sunniest part of the Ausgrid year


def day_chart(ctx, result, table, out, pt_id: str, cfg: PricingConfig = PricingConfig()):
    """PNG of the summer day with the most exported energy; None without such a day."""
    data = _inputs(ctx, result, table)
    if data is None:
        return None
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    local = data["index"].tz_convert(prices.SYDNEY)
    summer = np.isin(local.month, SUMMER_MONTHS)
    if not summer.any():
        return None
    dates = np.asarray(local.date)
    totals = data["model_kwh"][summer].groupby(dates[summer]).sum()
    day = totals.idxmax()
    pick = dates == day
    hours = local[pick].hour + local[pick].minute / 60
    wholesale = data["wholesale"][pick]
    price = buyback_price_series(wholesale, data["headroom"][pick], cfg)
    fig, ax = plt.subplots(figsize=(7.0, 3.6), dpi=100)
    ax.bar(hours, data["model_kwh"][pick], width=0.45, color="#9ecae1", label="Exported (kWh)")
    ax.set_xlabel(f"Hour of {day} (Sydney time)")
    ax.set_ylabel("Exported energy (kWh per half-hour)")
    ax2 = ax.twinx()
    ax2.plot(hours, wholesale / 10, color="#8c8c8c", label="Wholesale (ct/kWh)")
    ax2.plot(hours, price * 100, color="#d62728", label="Buy-back price (ct/kWh)")
    ax2.set_ylabel("Price (ct/kWh)")
    handles, labels = ax.get_legend_handles_labels()
    more, names = ax2.get_legend_handles_labels()
    ax.legend(handles + more, labels + names, loc="upper left", fontsize=8)
    ax.set_title(f"{pt_id}: wholesale price, buy-back price and exported energy")
    fig.tight_layout()
    path = out / f"pricing_day_{pt_id}.png"
    fig.savefig(path, metadata={"Software": None})
    plt.close(fig)
    return path
```

In `src/eval/run.py`, add this helper just above `def eval_dir`:

```python
def _has_report_extra() -> bool:
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return False
    return True
```

and, directly after the `pricing_eval.write(...)` line from Task 6 (same indentation), add:

```python
                if _has_report_extra():
                    pricing_eval.day_chart(ctx, result, price_inputs[0], out, pt_id)
```

- [ ] **Step 4: Run to see it pass**

Run: `.venv/bin/python -m pytest tests/eval -q && .venv/bin/python -m ruff check src tests`
Expected: all pass; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/eval tests/eval
git commit -m "feat(eval): draw the summer day with price and exported energy"
```

---

### Task 8: Smoke, README, run it on real data

**Files:** modify `src/smoke.py`, `README.md`.

- [ ] **Step 1: Smoke.** In `src/smoke.py` change `PACKAGES = ["common", "ml", "grid", "agent", "ui", "eval"]` to include `"pricing"`.

- [ ] **Step 2: README.** Insert a new section before `### Environment variables`:

```markdown
### 10. Prices and the buy-back price (optional)
The evaluation can also show what prosumers earn when the buy-back price follows the hourly wholesale price. It needs one year of Romanian day-ahead prices from [euenergy.live](https://euenergy.live) (CC-BY-4.0, free token). Put `EUENERGY_TOKEN=<your token>` in `.env` (the file is not committed), then:
```bash
set -a; . ./.env; set +a
python -m src.pricing.prices fetch --year 2025
python -m src.eval.run --pricing
```
The first command saves `data/pzu/ro.parquet`. The second adds a `pricing` block to `summary.json`, a `pricing_<station>.md` table and a `pricing_day_<station>.png` chart. Prices are matched to the Ausgrid year by season (Sydney July with Bucharest January) and local hour, so the result shows the shape of the effect, not a forecast in euros.
```

Add a row to the environment table: `| `EUENERGY_TOKEN` | unset | `python -m src.pricing.prices fetch` |`, and a row to the data table: `| [euenergy.live](https://euenergy.live) hourly Romanian day-ahead prices | buy-back price | CC BY 4.0, credit euenergy.live |`.

- [ ] **Step 3: Verify everything**

```bash
make test lint smoke
```
Expected: all tests pass, `All checks passed!`, `SMOKE OK`.

- [ ] **Step 4: Real run (needs the token and real labels; skip if labels are not on this machine and say so)**

```bash
set -a; . ./.env; set +a
.venv/bin/python -m src.pricing.prices fetch --year 2025
.venv/bin/python -m src.eval.run --run-id pricing-check --pricing
```
Expected: `saved 8760 hourly prices …` (a few rows fewer if the API has gaps), then `evaluation written to …`. Open `artifacts/eval/pricing-check/pricing_<station>.md`. **Report the numbers as they are**, including if dynamic revenue is below the flat tariff.

- [ ] **Step 5: Commit**

```bash
git add src/smoke.py README.md
git commit -m "docs: document the price fetch and the --pricing evaluation"
```

Then **ask the user** before pushing `pricing/core` and opening its PR.

---

# Phase 2: per-house price in the agent API (branch `pricing/api`)

Cut from `main` after phase 1 is merged (it needs `src/pricing/`), or from `pricing/core` if the user says to stack. Needs P1's sign-off: it changes `src/common/contract.py`, `src/agent/`, `docs/09-contract.md`.

### Task 9: `HousePrice` in the contract

**Files:** modify `src/common/contract.py`, `docs/09-contract.md`; test `tests/test_contract.py`.

- [ ] **Step 1: Branch and failing tests.** `git switch main && git pull && git switch -c pricing/api`, then append to `tests/test_contract.py` (add `HousePrice` to its import list):

```python
def test_house_price_refuses_a_negative_price():
    ok = {
        "house_id": "H01",
        "interval_start": "2025-06-21T10:00:00Z",
        "buyback_eur_kwh": 0.09,
        "wholesale_eur_mwh": 100.0,
        "bonus_applied": True,
        "reason": "bonus: the safe limit is at least the fixed limit",
    }
    assert HousePrice(**ok).buyback_eur_kwh == 0.09
    with pytest.raises(ValidationError):
        HousePrice(**{**ok, "buyback_eur_kwh": -0.01})
    with pytest.raises(ValidationError):
        HousePrice(**{**ok, "extra": 1})


def test_plan_without_prices_still_loads():
    assert load_mock("plan", Plan).prices == []
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/python -m pytest tests/test_contract.py -q`
Expected: FAIL on import of `HousePrice`.

- [ ] **Step 3: Implement.** In `src/common/contract.py`, after `class HouseLimit`:

```python
class HousePrice(Strict):
    house_id: str
    interval_start: AwareDatetime
    buyback_eur_kwh: float = Field(ge=0)
    wholesale_eur_mwh: float
    bonus_applied: bool
    reason: str
```

and in `class Plan`, add before `status`: `prices: list[HousePrice] = Field(default_factory=list)`. Old plans in the action log have no `prices` and still validate.

In `docs/09-contract.md`: read the section headings, add a `HousePrice` section after the plan section in the same style: the JSON example from the test, plus "`prices` in a plan is empty when no wholesale price was available; `buyback_eur_kwh` is never negative".

- [ ] **Step 4: Run to see them pass**

Run: `.venv/bin/python -m pytest tests/test_contract.py tests/test_planner.py tests/test_service.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/common/contract.py docs/09-contract.md tests/test_contract.py
git commit -m "feat(common): add HousePrice and Plan.prices to the contract"
```

---

### Task 10: `PriceSource`

**Files:**
- Create: `src/pricing/source.py`
- Test: `tests/test_pricing_source.py`

- [ ] **Step 1: Failing tests** `tests/test_pricing_source.py`:

```python
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.common.config import Settings
from src.pricing import prices
from src.pricing.source import MOCK_CURVE_EUR_MWH, PriceSource, mock_source, price_source_for


def year(y=2025):
    idx = pd.date_range(f"{y}-01-01", f"{y + 1}-01-01", freq="h", tz="UTC", inclusive="left")
    return pd.Series(np.arange(len(idx), dtype=float) % 100 + 10.0, index=idx)


def test_mock_source_follows_the_bucharest_clock():
    noon_bucharest = datetime(2025, 6, 21, 9, 0, tzinfo=timezone.utc)  # 12:00 in summer
    assert mock_source().wholesale(noon_bucharest) == MOCK_CURVE_EUR_MWH[12]
    assert mock_source().mock is True


def test_real_prices_win_over_the_profile_when_the_hour_is_known():
    series = year()
    source = PriceSource(prices.profile(series), series)
    when = datetime(2025, 6, 21, 10, 30, tzinfo=timezone.utc)
    assert source.wholesale(when) == series.loc["2025-06-21 10:00:00+00:00"]
    other_year = datetime(2012, 6, 21, 10, 30, tzinfo=timezone.utc)
    assert source.wholesale(other_year) is not None  # falls back to the (month, hour) profile
    assert source.mock is False


def test_day_curve_has_24_utc_hours():
    curve = mock_source().day_curve(datetime(2025, 6, 21, 13, 0, tzinfo=timezone.utc))
    assert len(curve) == 24 and curve[0]["ts"].startswith("2025-06-21T00:00:00")
    assert all(c["wholesale_eur_mwh"] is not None for c in curve)


def test_settings_pick_mock_or_data(tmp_path):
    assert price_source_for(Settings(source="mock", data_dir=str(tmp_path))).mock is True
    assert price_source_for(Settings(source="model", data_dir=str(tmp_path))).mock is True
    prices.save(year(), prices.prices_path(str(tmp_path)))
    assert price_source_for(Settings(source="model", data_dir=str(tmp_path))).mock is False
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/python -m pytest tests/test_pricing_source.py -q`
Expected: FAIL, `No module named 'src.pricing.source'`.

- [ ] **Step 3: Implement** `src/pricing/source.py`:

```python
"""Wholesale price at a time, for the agent and the screen."""

from datetime import datetime

import pandas as pd

from src.common.config import Settings
from src.pricing import prices

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

- [ ] **Step 4: Run to see them pass**

Run: `.venv/bin/python -m pytest tests/test_pricing_source.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m ruff check src tests
git add src/pricing/source.py tests/test_pricing_source.py
git commit -m "feat(pricing): add the wholesale price source with a mock curve"
```

---

### Task 11: Prices in the plan

**Files:** modify `src/agent/planner.py`, `src/agent/service.py`, `src/agent/wiring.py`, `src/grid/demo_api.py`; test `tests/test_planner_prices.py`, `tests/test_service_prices.py`.

Note from the mock data: at noon the mock forecast gives `safe_cap_share_used = 0.35`, below the station's `static_share` of 0.36, so there is **no headroom** in the default mock. Tests that need a bonus lower `static_share` with `station.model_copy(update={"static_share": 0.30})`.

- [ ] **Step 1: Failing tests** `tests/test_planner_prices.py`:

```python
from datetime import datetime, timezone

import pytest

from src.agent.planner import make_plan
from src.agent.sources import MockSource
from src.common.contract import StationConfig
from src.common.mock_data import load_mock

NOON = datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)
NIGHT = datetime(2025, 6, 21, 2, 0, tzinfo=timezone.utc)


def plan_at(when, wholesale, static_share=None):
    station = load_mock("station", StationConfig)
    if static_share is not None:
        station = station.model_copy(update={"static_share": static_share})
    source = MockSource()
    forecast = source.forecast(station.pt_id, when)
    grid = source.grid_state(station.pt_id, when)
    return make_plan(forecast, grid, station, when, wholesale_eur_mwh=wholesale)


def test_no_wholesale_price_means_no_prices():
    assert plan_at(NOON, None).prices == []


def test_bonus_when_the_safe_limit_is_at_least_the_fixed_limit():
    plan = plan_at(NOON, 100.0, static_share=0.30)
    assert len(plan.prices) == 8
    assert all(p.bonus_applied and p.reason.startswith("bonus") for p in plan.prices)
    assert plan.prices[0].buyback_eur_kwh == pytest.approx(0.0935)
    assert plan.prices[0].wholesale_eur_mwh == 100.0


def test_no_bonus_below_the_fixed_limit():
    plan = plan_at(NOON, 100.0)  # mock noon: share 0.35 < fixed 0.36
    assert not any(p.bonus_applied for p in plan.prices)
    assert plan.prices[0].buyback_eur_kwh == pytest.approx(0.085)
    assert "below the fixed limit" in plan.prices[0].reason


def test_no_bonus_when_the_agent_fell_back():
    plan = plan_at(NIGHT, 100.0, static_share=0.30)
    assert plan.abstain and not any(p.bonus_applied for p in plan.prices)
    assert "fixed limit" in plan.prices[0].reason


def test_zero_or_negative_wholesale_pays_nothing():
    for w in (0.0, -20.0):
        plan = plan_at(NOON, w, static_share=0.30)
        assert all(p.buyback_eur_kwh == 0.0 and not p.bonus_applied for p in plan.prices)
        assert plan.prices[0].reason.startswith("no payment")
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
    assert len(plan.prices) == 8 and plan.prices[0].wholesale_eur_mwh == 15.0  # 13:00 Bucharest


def test_without_a_source_the_plan_has_no_prices(tmp_path):
    assert service(tmp_path, None).propose(NOON).prices == []


def test_price_view_has_curve_and_houses(tmp_path):
    svc = service(tmp_path, mock_source())
    assert svc.price_view(NOON)["houses"] == []  # nothing proposed yet
    svc.propose(NOON)
    view = svc.price_view(NOON)
    assert view["mock"] is True and len(view["curve"]) == 24 and len(view["houses"]) == 8
```

(`NOON` 10:00Z in June is 13:00 in Bucharest (EEST), so `MOCK_CURVE[13] = 15`.)

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/python -m pytest tests/test_planner_prices.py tests/test_service_prices.py -q`
Expected: FAIL, `unexpected keyword argument 'wholesale_eur_mwh'` / `'prices'`.

- [ ] **Step 3: Implement.**

`src/agent/planner.py`: import `HousePrice` in the contract import list, add `from src.pricing.config import PricingConfig` and `from src.pricing.tariff import buyback_price`. Add above `make_plan`:

```python
def house_prices(
    station: StationConfig,
    interval_start: AwareDatetime,
    share: float,
    abstain: bool,
    wholesale_eur_mwh: float,
    cfg: PricingConfig,
) -> list[HousePrice]:
    headroom = not abstain and share >= station.static_share
    price = buyback_price(wholesale_eur_mwh, headroom, cfg)
    if price == 0.0:
        reason = "no payment: the wholesale price is zero or negative"
    elif abstain:
        reason = "no bonus: the agent used the fixed limit"
    elif not headroom:
        reason = "no bonus: the safe limit is below the fixed limit"
    else:
        reason = "bonus: the safe limit is at least the fixed limit"
    return [
        HousePrice(
            house_id=house.house_id,
            interval_start=interval_start,
            buyback_eur_kwh=round(price, 6),
            wholesale_eur_mwh=wholesale_eur_mwh,
            bonus_applied=headroom and price > 0,
            reason=reason,
        )
        for house in station.houses
    ]
```

Change the `make_plan` signature to end with `force_abstain: str | None = None, wholesale_eur_mwh: float | None = None, pricing: PricingConfig | None = None,` and, just before `return Plan(`:

```python
    prices = (
        []
        if wholesale_eur_mwh is None
        else house_prices(
            station, interval_start, share, abstain, wholesale_eur_mwh, pricing or PricingConfig()
        )
    )
```
and add `prices=prices,` to the `Plan(...)` call (before `status="proposed"`).

`src/agent/service.py`: add `from src.pricing.source import PriceSource`; `from src.agent.planner import make_plan, plan_id_for`; add `prices: PriceSource | None = None,` as the last `__init__` parameter and `self.prices = prices`; in `propose`, replace the `make_plan(...)` call with:

```python
            wholesale = self.prices.wholesale(interval_start) if self.prices else None
            plan = make_plan(
                forecast,
                grid_state,
                station,
                interval_start,
                force_abstain=forced,
                wholesale_eur_mwh=wholesale,
            )
```
and add the method:

```python
    def price_view(self, when: AwareDatetime) -> dict:
        """Day curve of the wholesale price and, if a plan exists, each house's price."""
        when = floor_to_half_hour(when.astimezone(timezone.utc))
        with self._lock:
            plan = self._plans.get(plan_id_for(self.station.pt_id, when))
        return {
            "interval_start": when,
            "mock": bool(self.prices and self.prices.mock),
            "curve": self.prices.day_curve(when) if self.prices else [],
            "houses": plan.prices if plan else [],
        }
```

`src/agent/wiring.py`: `from src.pricing.source import price_source_for`; add `prices=price_source_for(settings),` to **both** `AgentService(...)` calls. `src/grid/demo_api.py`: add `from src.pricing.source import price_source_for` and, in the `AgentService(...)` call, `prices=price_source_for(settings),` after `source=_source,`.

- [ ] **Step 4: Run to see them pass**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (existing planner/service tests do not pass `prices`, so they are unchanged).

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m ruff check src tests
git add src tests
git commit -m "feat(agent): attach a buy-back price per house to each plan"
```

---

### Task 12: `GET /prices` and the screen's allowlist

**Files:** modify `src/agent/api.py`, `src/ui/app.py`; tests `tests/test_api_prices.py`, `tests/test_ui_app.py`.

- [ ] **Step 1: Failing tests.** `tests/test_api_prices.py`:

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
    assert len(after["houses"]) == 8 and after["houses"][0]["buyback_eur_kwh"] >= 0


def test_prices_without_a_source_is_empty_not_an_error(tmp_path):
    body = client(tmp_path).get("/prices", params={"interval_start": NOON}).json()
    assert body["curve"] == [] and body["houses"] == [] and body["mock"] is False
```

In `tests/test_ui_app.py`, add `"prices",` to the GET allowlist tuple in `test_agent_reads_and_writes_are_allowed`, and add:

```python
    def test_prices_is_read_only(self):
        self.assertFalse(is_allowed("POST", "prices"))
```
inside `AllowlistTests`.

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/python -m pytest tests/test_api_prices.py tests/test_ui_app.py -q`
Expected: FAIL (`404` on `/prices`; `prices` not allowed).

- [ ] **Step 3: Implement.** In `src/agent/api.py`, after the `/grid_state` route:

```python
    @app.get("/prices")
    def prices(interval_start: AwareDatetime | None = Query(default=None)):
        return service.price_view(interval_start or floor_to_half_hour())
```
In `src/ui/app.py`, change the `READ` regex (it must stay under 100 columns, so split it):

```python
READ = re.compile(
    rf"(health|station|forecast|grid_state|prices|plans|plan/{NAME}|queue|log|kill_switch)"
)
```

- [ ] **Step 4: Run to see them pass**

Run: `make test lint smoke`
Expected: all pass, `All checks passed!`, `SMOKE OK`.

- [ ] **Step 5: README and commit.** In `README.md` section 4 (demo), add one sentence after the "Open http://127.0.0.1:8001" line: "Each plan also carries a buy-back price per house; `GET /prices` shows the day's wholesale curve and those prices (the demo uses an illustrative curve, marked `mock`)." Then:

```bash
git add src README.md tests
git commit -m "feat(agent): add GET /prices and let the screen read it"
```

Ask the user before pushing `pricing/api` and opening its PR; name P1 as the owner to review.

---

# Phase 3: battery response (branch `pricing/battery`)

Cut from `main` after phase 1 is merged. Independent of phase 2.

**Limit to state in the PR:** the live agent has no per-house surplus, so live plans keep `battery_kw = 0`. Battery response is measured in the evaluation only; the screen shows the evaluation number.

### Task 13: The dispatch rule

**Files:**
- Create: `src/pricing/battery.py`
- Test: `tests/pricing/test_battery.py`

Rule: a price at or above the day's median is "high". Low price: store the surplus. High price: sell stored energy into the room under the cap, and store only what the cap would have wasted. Export never exceeds the cap. On fallback hours the battery stays idle. Uses `src.grid.battery.step` (positive power = charging; defaults 10 kWh, 1 kWh minimum, 5 kW, 90% round trip).

- [ ] **Step 1: Failing tests** `tests/pricing/test_battery.py`:

```python
import numpy as np
import pandas as pd
import pytest

from src.pricing.battery import battery_houses, dispatch


def frame(n=96):
    idx = pd.date_range("2025-06-21", periods=n, freq="30min", tz="UTC")
    hour = idx.hour + idx.minute / 60
    surplus = pd.Series(np.where((hour >= 8) & (hour < 16), 6.0, 0.0), index=idx)
    price = pd.Series(np.where((hour >= 17) & (hour < 21), 200.0, 40.0), index=idx)
    cap = pd.Series(4.0, index=idx)
    active = pd.Series(True, index=idx)
    day = pd.Series(idx.date, index=idx)
    return price, surplus, cap, active, day


def test_never_exceeds_cap_or_bounds():
    out = dispatch(*frame())
    assert (out["export_kw"] <= 4.0 + 1e-9).all()
    assert out["battery_kw"].abs().max() <= 5.0 + 1e-9
    assert out["soc_kwh"].between(1.0 - 1e-9, 10.0 + 1e-9).all()


def test_stores_at_low_price_and_sells_at_high_price():
    price, surplus, cap, active, day = frame()
    out = dispatch(price, surplus, cap, active, day)
    assert (out["battery_kw"][surplus > 0] > 0).any()
    evening = out[price > 100]
    assert (evening["battery_kw"] < 0).any() and (evening["export_kw"] > 0).any()


def test_earns_more_than_no_battery_and_conserves_energy():
    price, surplus, cap, active, day = frame()
    out = dispatch(price, surplus, cap, active, day)
    plain = np.minimum(surplus, cap) * 0.5
    with_battery = out["export_kw"] * 0.5
    assert (with_battery * price).sum() > (plain * price).sum()
    assert with_battery.sum() <= surplus.sum() * 0.5 + 1e-9


def test_idle_when_the_agent_fell_back():
    price, surplus, cap, active, day = frame()
    out = dispatch(price, surplus, cap, active & False, day)
    assert (out["battery_kw"] == 0).all()
    assert np.allclose(out["export_kw"], np.minimum(surplus, cap))


def test_inputs_must_share_an_index_and_houses_are_a_fixed_choice():
    price, surplus, cap, active, day = frame()
    with pytest.raises(ValueError):
        dispatch(price, surplus.iloc[1:], cap, active, day)
    assert battery_houses(["H03", "H01", "H02", "H04"]) == ["H01", "H02"]
```

- [ ] **Step 2: Run to see it fail**

Run: `git switch main && git pull && git switch -c pricing/battery && .venv/bin/python -m pytest tests/pricing/test_battery.py -q`
Expected: FAIL, `No module named 'src.pricing.battery'`.

- [ ] **Step 3: Implement** `src/pricing/battery.py`:

```python
"""Price-driven battery dispatch for one house. Pure: no grid, no I/O."""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.grid.battery import step

STEP_HOURS = 0.5
SHARE_WITH_BATTERY = 0.30  # 101,243 of 332,684 prosumers (docs/06-motivation-and-problems.md)


@dataclass(frozen=True)
class BatteryParams:
    capacity_kwh: float = 10.0
    min_soc_kwh: float = 1.0
    max_power_kw: float = 5.0
    roundtrip_efficiency: float = 0.9


def battery_houses(house_ids, fraction: float = SHARE_WITH_BATTERY) -> list[str]:
    """The first houses in sorted order: a fixed, repeatable choice."""
    ids = sorted(house_ids)
    return ids[: math.ceil(fraction * len(ids))]


def dispatch(
    price: pd.Series,
    surplus_kw: pd.Series,
    cap_kw: pd.Series,
    active: pd.Series,
    day: pd.Series,
    params: BatteryParams = BatteryParams(),
) -> pd.DataFrame:
    """Battery power and grid export of one house, per half-hour.

    All inputs share one sorted index. ``price`` is any price (higher is better to sell at),
    ``surplus_kw`` what the panels give beyond the house's own use, ``cap_kw`` the export
    limit in force, ``active`` False where the agent fell back (the battery stays idle) and
    ``day`` a label per interval: a price at or above the day's median counts as high.

    Low price: store the surplus. High price: sell the stored energy into the room under the
    cap, and store only what the cap would have wasted. Export never exceeds ``cap_kw``.
    Output ``battery_kw`` is positive when charging, like ``src.grid.battery``.
    """
    index = price.index
    for other in (surplus_kw, cap_kw, active, day):
        if not other.index.equals(index):
            raise ValueError("all inputs must share one index")
    high = (price >= price.groupby(day).transform("median")).to_numpy()
    surplus = surplus_kw.fillna(0.0).clip(lower=0.0).to_numpy()
    cap = cap_kw.to_numpy(dtype=float)
    on = active.to_numpy(dtype=bool)
    p = params
    eff = math.sqrt(p.roundtrip_efficiency)
    soc = p.min_soc_kwh
    out = np.zeros((len(index), 3))
    for i in range(len(index)):
        charge = discharge = 0.0
        if on[i]:
            room_up = max((p.capacity_kwh - soc) / (eff * STEP_HOURS), 0.0)
            room_down = max((soc - p.min_soc_kwh) * eff / STEP_HOURS, 0.0)
            if high[i]:
                wasted = max(surplus[i] - cap[i], 0.0)
                charge = min(p.max_power_kw, wasted, room_up)
                free = max(cap[i] - surplus[i], 0.0)
                discharge = min(p.max_power_kw, free, room_down)
            else:
                charge = min(p.max_power_kw, surplus[i], room_up)
        power = charge - discharge
        exported = min(surplus[i] - charge, cap[i]) + discharge
        out[i] = (power, exported, soc)
        soc = step(
            soc,
            power,
            STEP_HOURS,
            capacity_kwh=p.capacity_kwh,
            min_soc_kwh=p.min_soc_kwh,
            max_power_kw=p.max_power_kw,
            roundtrip_efficiency=p.roundtrip_efficiency,
        )
    return pd.DataFrame(out, index=index, columns=["battery_kw", "export_kw", "soc_kwh"])
```

- [ ] **Step 4: Run to see it pass**

Run: `.venv/bin/python -m pytest tests/pricing/test_battery.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m ruff check src tests
git add src/pricing/battery.py tests/pricing/test_battery.py
git commit -m "feat(pricing): add price-driven battery dispatch"
```

---

### Task 14: Battery in the evaluation block

**Files:** modify `src/eval/pricing_eval.py`; test `tests/eval/test_pricing_eval.py`.

The battery houses are the first 30% of houses in sorted order (`battery_houses`). Their extra export is `(export with battery − export without) × 0.5 h` per interval (negative while charging, positive while selling). It is added to the smart-limit export and paid at the dynamic price + bonus.

- [ ] **Step 1: Failing test.** Append:

```python
def test_battery_row_is_added_and_keeps_energy_balance(table):
    ctx, result = make()
    block = pricing_eval.compute(ctx, result, table, 0.1)
    battery = block["battery"]
    assert battery["houses"] == ["H1"]  # ceil(0.3 * 2) = 1, first in sorted order
    assert block["rows"][-1]["name"].startswith("Smart limit, dynamic price + grid bonus + bat")
    # the cap binds here, so the battery also sells energy the cap would have wasted
    assert block["model"]["exported_kwh"] < battery["exported_kwh"]
    assert battery["exported_kwh"] <= ctx["surplus"].to_numpy().sum() * 0.5
    assert battery["gain_eur"] > 0
    assert battery["gain_eur"] == pytest.approx(
        battery["dynamic_bonus_eur"] - block["model"]["dynamic_bonus_eur"], abs=1e-5
    )
    json.dumps(block, allow_nan=False)
```

The battery sells what the export cap would have wasted, so it can raise exported energy as well as shift it to better hours. When the cap does not bind, losses make total export slightly lower and the gain comes only from price.

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/eval/test_pricing_eval.py -q`
Expected: FAIL, `KeyError: 'battery'`.

- [ ] **Step 3: Implement.** In `src/eval/pricing_eval.py` add imports `from src.pricing.battery import STEP_HOURS, battery_houses, dispatch`, then above `compute`:

```python
def _battery_extra_kwh(ctx: dict, data: dict, houses: list[str]) -> pd.Series:
    """Export gained (or stored) by the battery houses, per interval, in kWh."""
    index, surplus, kwp = data["index"], ctx["surplus"], ctx["kwp"]
    day = pd.Series(index.tz_convert(prices.SYDNEY).date, index=index)
    active = ~data["abstain"]
    extra = pd.Series(0.0, index=index)
    for house in houses:
        s = surplus.loc[index, house]
        cap = data["share"] * kwp[house]
        out = dispatch(data["wholesale"], s, cap, active, day)
        plain = np.minimum(s.fillna(0.0), cap) * STEP_HOURS
        extra += out["export_kw"] * STEP_HOURS - plain
    return extra
```

In `compute`, after `block = {...}` and before `block["rows"] = _rows(block)`:

```python
    houses = battery_houses(ctx["kwp"].index)
    with_battery = revenue(
        data["model_kwh"] + _battery_extra_kwh(ctx, data, houses),
        wholesale,
        headroom,
        flat_eur_kwh,
        cfg,
    )
    block["battery"] = {
        "houses": houses,
        "exported_kwh": with_battery["exported_kwh"],
        "dynamic_bonus_eur": with_battery["dynamic_bonus_eur"],
        "avg_dynamic_bonus_eur_kwh": with_battery["avg_dynamic_bonus_eur_kwh"],
        "gain_eur": with_battery["dynamic_bonus_eur"] - block["model"]["dynamic_bonus_eur"],
    }
```

and in `_rows`, turn `return [ … ]` into a `rows = [ … ]` list and finish with:

```python
    battery = block.get("battery")
    if battery:
        count = len(battery["houses"])
        name = f"Smart limit, dynamic price + grid bonus + battery ({count} houses)"
        avg = battery["avg_dynamic_bonus_eur_kwh"]
        rows.append(_row(name, battery["exported_kwh"], battery["dynamic_bonus_eur"], avg))
    return rows
```

- [ ] **Step 4: Run to see it pass**

Run: `make test lint smoke`
Expected: all pass (the run test from Task 6 still passes: its block now also has `battery`).

- [ ] **Step 5: README and commit.** In README section 10, add after the paragraph on outputs: "A battery row shows what the first 30% of houses (the share of Romanian prosumers with a battery) would earn if they stored midday surplus and sold it at higher-priced hours, under the same export limit. The live agent does not control batteries; this is measured in the evaluation only." Then:

```bash
git add src README.md tests
git commit -m "feat(eval): add the battery response to the revenue block"
```

Ask the user before pushing `pricing/battery` and opening its PR.

---

# Phase 4: live price in the screen (branch `pricing/ui`)

Cut from `main` after phases 1 and 2 are merged (phase 3 adds a table row but is not required).

### Task 15: The "Prices" tab

**Files:** modify `src/ui/static/index.html`; test `tests/test_ui_app.py`.

- [ ] **Step 1: Failing test.** In `tests/test_ui_app.py` add (the file uses `unittest`; follow its existing app-creation pattern, for example `TestClient(create_app(Settings()))`):

```python
class PricesTabTests(unittest.TestCase):
    def test_screen_has_the_prices_tab_and_panel(self):
        html = TestClient(create_app(Settings())).get("/").text
        for needle in ('id="tab-prices"', 'id="p-prices"', 'id="priceChart"', 'id="rev"'):
            self.assertIn(needle, html)
        self.assertIn('const TABS = ["houses", "queue", "decision", "log", "compare", "prices"]', html)
```

- [ ] **Step 2: Run to see it fail**

Run: `git switch main && git pull && git switch -c pricing/ui && .venv/bin/python -m pytest tests/test_ui_app.py -q`
Expected: FAIL, `'id="tab-prices"' not found`.

- [ ] **Step 3: Implement in `src/ui/static/index.html`.**

1. After the `tab-compare` button add:
```html
    <button class="tab" role="tab" id="tab-prices" aria-controls="p-prices" aria-selected="false" tabindex="-1" type="button">Prices</button>
```
2. After the `p-compare` section add:
```html
  <section class="panel" id="p-prices" role="tabpanel" aria-labelledby="tab-prices" hidden>
    <h2 class="h">Buy-back price <span class="tag" id="priceTag" hidden>Mock</span></h2>
    <p class="sub" id="priceNote">Loading prices…</p>
    <svg id="priceChart" viewBox="0 0 960 120" preserveAspectRatio="none" role="img" aria-label="Wholesale price over the day"></svg>
    <div class="scroll"><table id="priceTable" hidden><thead><tr><th>House</th><th>Buy-back</th><th>Wholesale</th><th>Why</th></tr></thead><tbody></tbody></table></div>
    <h2 class="h" style="margin-top:18px">What prosumers earn</h2>
    <p class="sub" id="revNote">Loading evaluation output…</p>
    <div class="scroll"><table id="rev" hidden><thead></thead><tbody></tbody></table></div>
  </section>
```
3. Change `const TABS = ["houses", "queue", "decision", "log", "compare"];` to include `"prices"` as the last item.
4. In `state`, add `prices: null`.
5. Add the script block before `/* ---------- map slot`:

```js
/* ---------- prices ---------- */
const SVGNS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs) {
  const n = document.createElementNS(SVGNS, tag);
  Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
  return n;
}

function drawPriceChart(d) {
  const box = $("priceChart"); box.replaceChildren();
  const pts = d.curve.map((c, i) => [i, c.wholesale_eur_mwh]).filter(p => p[1] != null);
  if (!pts.length) return;
  const lo = Math.min(0, ...pts.map(p => p[1])), hi = Math.max(1, ...pts.map(p => p[1]));
  const x = i => (i / 23) * 940 + 10, y = v => 105 - ((v - lo) / (hi - lo)) * 95;
  box.append(svgEl("line", {x1: 10, x2: 950, y1: y(0), y2: y(0), stroke: "currentColor", "stroke-opacity": ".25"}));
  box.append(svgEl("polyline", {points: pts.map(p => x(p[0]) + "," + y(p[1])).join(" "), fill: "none", stroke: "currentColor", "stroke-width": "2", "vector-effect": "non-scaling-stroke"}));
  const hour = new Date(d.interval_start).getUTCHours();
  box.append(svgEl("line", {x1: x(hour), x2: x(hour), y1: 0, y2: 115, stroke: "var(--rev)", "stroke-width": "2", "vector-effect": "non-scaling-stroke"}));
}

function renderPrices() {
  const d = state.prices; if (!d) return;
  $("priceTag").hidden = !d.mock;
  const at = d.interval_start.slice(0, 10) + " " + d.interval_start.slice(11, 16) + " UTC";
  const hourKey = d.interval_start.slice(0, 13);
  const now = d.curve.find(c => c.ts.slice(0, 13) === hourKey);
  const note = $("priceNote");
  if (!d.curve.length) { note.textContent = "This agent has no price source."; $("priceChart").replaceChildren(); $("priceTable").hidden = true; return; }
  note.textContent = "Wholesale (day-ahead) price at " + at + ": " + (now && now.wholesale_eur_mwh != null ? num(now.wholesale_eur_mwh, 0) + " EUR/MWh. " : "not available. ") +
    (d.mock ? "Illustrative curve, not market data. " : "") + (d.houses.length ? "" : "Propose a plan to see each house's price.");
  drawPriceChart(d);
  const body = $("priceTable").tBodies[0]; body.replaceChildren();
  d.houses.forEach(h => {
    const r = el("tr");
    r.append(el("td", h.house_id), el("td", num(h.buyback_eur_kwh * 100, 2, " ct/kWh")), el("td", num(h.wholesale_eur_mwh, 0, " EUR/MWh")), el("td", h.reason));
    body.append(r);
  });
  $("priceTable").hidden = !body.children.length;
}

async function loadPrices(t, my) {
  let data;
  try { data = await api("prices?interval_start=" + encodeURIComponent(t)); }
  catch (e) { if (my === gen) $("priceNote").textContent = "Prices are not available: " + e.message; return; }
  if (my !== gen) return;
  state.prices = data; renderPrices();
}

async function loadPricingEval() {
  const note = $("revNote"), table = $("rev");
  table.hidden = true;
  let res;
  try { res = await fetch("/eval/summary"); } catch (_) { note.textContent = "The screen server did not answer."; return; }
  if (!res.ok) { note.className = "empty"; note.textContent = "No evaluation output yet. Run python -m src.eval.run --pricing, then reload."; return; }
  const s = (await res.json()).summary, scenarios = s.scenarios || {};
  const head = table.tHead, body = table.tBodies[0]; head.replaceChildren(); body.replaceChildren();
  const hr = el("tr"); ["Station · policy", "Exported (kWh)", "Revenue (EUR)", "Average (ct/kWh)"].forEach(c => hr.append(el("th", c))); head.append(hr);
  Object.keys(scenarios).forEach(k => {
    const block = scenarios[k].pricing; if (!block) return;
    block.rows.forEach(row => {
      const r = el("tr");
      r.append(el("td", k + " · " + row.name), el("td", num(row.exported_kwh, 0)), el("td", num(row.revenue_eur, 2)), el("td", row.avg_eur_kwh == null ? "—" : num(row.avg_eur_kwh * 100, 2)));
      body.append(r);
    });
  });
  table.hidden = !body.children.length;
  note.className = "sub";
  note.textContent = body.children.length
    ? (s.mock ? "MOCK, NOT A RESULT. " : "") + "Run " + s.run_id + ". Numbers come from the evaluation output; prices are matched to the Ausgrid year by season and hour. Prices: euenergy.live (CC-BY-4.0)."
    : "This evaluation run has no price block. Run python -m src.eval.run --pricing.";
}
```
6. In `refresh()`, add `loadPrices` to the array: `[loadKill, loadForecast, loadGrid, loadQueue, loadLog, loadPrices].map(f => f(t, my))`.
7. In the init block at the bottom, add `loadPricingEval();` after `loadComparison();`.

- [ ] **Step 4: Run to see it pass, then look at it in a browser**

Run: `make test lint smoke`
Expected: all pass.

Then verify by eye (use the browser tool, not guesswork):

```bash
python -m uvicorn src.grid.demo_api:app --port 8000
```
```bash
API_URL=http://127.0.0.1:8000 python -m uvicorn src.ui.app:app --port 8001
```
Open http://127.0.0.1:8001/#prices. Check: the "Mock" tag shows, the curve draws with a marker at the selected hour, the note says "Illustrative curve". Press "Propose plan", return to Prices: eight house rows appear with a buy-back price and a reason. Change the day with the arrows: the curve and marker update. Check the browser console for errors. If an evaluation run with `--pricing` exists (`EVAL_RUN_ID=<id>`), the revenue table fills; otherwise the "No evaluation output" message shows. Report what you saw; if anything is off, say so.

- [ ] **Step 5: README and commit.** In README section 4 add: "The **Prices** tab shows the day's wholesale curve, each house's buy-back price for the selected half-hour, and, after `python -m src.eval.run --pricing`, what prosumers earn under each price (start the screen with `EVAL_RUN_ID=<run id>` to pick the run)." Then:

```bash
git add src/ui tests README.md
git commit -m "feat(ui): add the Prices tab"
```

Ask the user before pushing `pricing/ui` and opening its PR.

---

## Self-review against the spec

- **Price rule, data, alignment (spec "Price rule", "Data"):** Tasks 1–3. Season alignment replaces the spec's "same calendar month" (see the note under Task 3 and the spec edit).
- **Phase 1 outputs (revenue table, chart, sensitivity):** Tasks 5–7. PPC's average purchase cost per kWh is the `avg_*_eur_kwh` columns.
- **Phase 2 (contract, plan, endpoint, mocks, P1 sign-off):** Tasks 9–12. The mock contract JSON needs no change because `prices` defaults to an empty list.
- **Phase 3 (battery, fallback idle, with/without revenue):** Tasks 13–14. Live `battery_kw` stays 0 (stated).
- **Phase 4 (UI panel, mocks, day-ahead timing):** Task 15. Tomorrow's prices before 13:00 CET are not special-cased: the curve shows whatever the source has, and the mock/profile fills gaps.
- **Tests, README, no trailers, no push without a yes:** in every phase.
- **Honesty:** Task 5 and Task 8 forbid asserting that dynamic beats flat and require reporting the real numbers.
