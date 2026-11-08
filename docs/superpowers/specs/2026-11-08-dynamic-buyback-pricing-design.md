# Dynamic buy-back price for prosumers: design

**Status:** design, written 2026-11-08, awaiting team review. Not implemented.

## Goal

PPC buys prosumers' surplus energy. Today the buy-back price is flat. This feature ties the price to PPC's real wholesale cost (the hourly day-ahead price, PZU) and adds a bonus when the grid has room to take the energy, so prosumers earn more and the price also steers export toward hours that help the grid.

## Scope

Four phases, each its own pull request, built in this order:

1. **Pricing core:** price loader, tariff rule, revenue, evaluation table and chart.
2. **Per-house price in the agent API:** new contract object and endpoint.
3. **Battery response:** price-driven battery dispatch for houses with a battery.
4. **Live price in the UI:** price panel in `src/ui/`.

Out of scope: changing the safe-cap model, a real settlement or billing system, the legal question of variable buy-back prices (see Risks).

## Price rule

Inputs per house and hour: wholesale price `w` (EUR/MWh), the agent's decision for that hour (cap, fallback flag, human-flag).

- **Base:** `base = max(0, share × w − fee)`, in EUR/kWh. Defaults `share = 0.85`, `fee = 0`, both in config.
- **Grid bonus:** when the safe limit leaves headroom (cap ≥ the fixed limit) and the agent did not fall back or flag a human, `price = base × (1 + bonus_pct)`. Otherwise `price = base`. Default `bonus_pct = 0.10`.
- Negative or zero `w` pays 0. The prosumer is never charged. The bonus is never negative.
- **Baseline for comparison:** flat tariff = the yearly average PZU price, paid for every exported kWh.

## Data

- **Source:** euenergy.live API, `GET /api/v1/prices?zone=RO&from=YYYY-MM-DD&to=YYYY-MM-DD`, hourly, EUR/MWh, UTC timestamps, token in the environment variable `EUENERGY_TOKEN` (kept in the gitignored `.env`, never committed). Data is CC-BY-4.0: credit euenergy.live in the README and slides.
- **Fetch script** saves one year to `data/pzu/` (gitignored), requesting month by month. A saved sample response is used by tests, so CI never needs the token.
- **Gaps:** hours can be missing. The loader fills short gaps by carrying the last value and flags longer ones. It never assumes 24 rows per day.
- **Alignment:** the price year differs from the Ausgrid test year (1 Jul 2012 – 30 Jun 2013). Prices are converted from UTC to Europe/Bucharest and matched by **month and hour of day**. This shows the shape of the gain, not a forecast in euros, and the pitch states it.

## Phase 1: pricing core

New package `src/pricing/`:
- `prices.py`: load and align PZU prices. Depends only on `data/pzu/`.
- `tariff.py`: pure `buyback_price(wholesale, headroom, fallback) -> EUR/kWh`. No I/O.
- `revenue.py`: from the agent's per-hour decisions and exported kWh, returns prosumer revenue under the flat tariff, the dynamic base, and dynamic + bonus.
- `scripts/fetch_pzu.py`: the fetch script.
- Evaluation: a revenue table for scenarios A, B and B+reactive power, PPC's average purchase cost per kWh under each tariff, one summer-day chart (PZU curve, buy-back price, exported energy), and a small sensitivity table for `bonus_pct`. Hooks into `src/eval/run.py` after PR #25 is merged.

Data flow: `agent decision` + `PZU price` → `tariff` → `revenue` → `eval table / chart`.

## Phase 2: per-house price in the agent API

- New contract object `HousePrice` in `src/common/contract.py`: `house_id`, `interval_start`, `buyback_eur_kwh`, `bonus_applied`, `reason`. Strict, like the other contract objects.
- A plan carries its `HousePrice` list next to its `HouseLimit` list. The price is computed from the same decision as the limit, so the two cannot disagree.
- New endpoint `GET /prices` in `src/agent/api.py` (read-only, same auth rules as the other GETs).
- Mocks in `src/common/mocks` updated in the same commit as the contract change.
- **Owner:** `src/common/` and `src/agent/` belong to P1. P1 approves and announces the contract change ([docs/09-contract.md](../../09-contract.md) is updated in the same PR).

## Phase 3: battery response

- Uses the existing twin (`src/grid/battery.py`, `GridState.batteries`, `HouseLimit.battery_kw`). No new battery model.
- Rule: for houses with a battery, charge at hours where the price is below the daily median, discharge into the hours above it. Never exceed the safe export limit, the battery's power, or its SoC bounds. When the agent falls back or flags a human, the battery follows the plain fixed-limit behaviour.
- Revenue is reported with and without battery response, so the prosumer gain is no longer a minimum.
- Dispatch is a pure function over `(prices, soc, limits)` so it is testable without the grid.

## Phase 4: live price in the UI

- A price panel in `src/ui/`: current and next-day price curve, each house's buy-back price and bonus (from `GET /prices`), and, after phase 3, the battery schedule.
- Uses the existing mocks pattern in `src/ui/mocks`, so the UI works without the live agent.
- Tomorrow's prices are published around 13:00 CET. Before then, the panel shows today's curve and says so.

## Tests

Pure and fast, no network.
- `tariff`: zero and negative wholesale pays 0; the bonus is never negative; no bonus on fallback or human-flagged hours.
- `prices`: UTC to Bucharest conversion, month/hour alignment, gap fill and flag.
- `revenue`: a small hand-computed example.
- Fetch script: tested against a saved sample response.
- Contract: `HousePrice` rejects invalid values, as the other contract tests do. API test for `/prices`.
- Battery dispatch: SoC and power bounds, no export above the safe limit, fallback behaviour.
- UI: renders from mocks.

## Risks and limits (to state in the pitch)

- The price year and the Ausgrid year differ; results show shape, not euros.
- PZU is a proxy for PPC's purchase cost. Real cost also includes imbalance, network and supplier fees.
- A variable buy-back price may need ANRE approval, as variable export limits may. Not checked.
- Prosumers other than battery owners do not react to the price, so the gain from phase 1 is a minimum and phase 3 adds only the battery part.
- `bonus_pct`, `share` and `fee` are free parameters. We report a sensitivity table instead of presenting one value as correct.
- The euenergy.live API is a third party. If it changes or goes down, the fallback is ENTSO-E (document type A44, Romania zone `10YRO-TEL------P`), which needs its own token.

## Done means

- `make test lint smoke` passes on each phase's branch.
- Every number on a slide comes from the evaluation output.
- `README.md` is updated in each phase that changes how the project runs (new command, environment variable, data step).
