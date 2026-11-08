# Prosumer aggregator price: design

**Status:** design v2, 2026-11-08. Replaces the first version (a "share of spot" buy-back with a grid bonus), which was rewritten after checking how PPC buys and sells today and what PPC's CEO asked for. Not implemented. The earlier plan ([../plans/2026-11-08-dynamic-buyback-pricing.md](../plans/2026-11-08-dynamic-buyback-pricing.md)) matches v1 and must be rewritten after this spec is approved.

## Goal

PPC offers an opt-in product in which it acts as the **single buyer** of a prosumer's injected energy, like Italy's GSE (Ritiro Dedicato), which PPC Romania's CEO has said Romania should copy. PPC pays the hourly day-ahead price (PZU) minus a published fee, with a floor, and **shares with the prosumer part of the imbalance cost it saves** by forecasting the aggregated export. PPC's profit comes from that saving, not from a haircut on the prosumer's price.

## Context (what we found, and how sure we are)

| Fact | Source | Confidence |
|---|---|---|
| PPC's prosumer product (MaxControl) prices consumption at 0.097 lei/kWh plus the monthly average of 15-minute PZU prices, with a price floor and cap. The fixed part covers supply and estimated imbalance. The injection price is "per the regulations". | PPC's own offer PDF | High |
| Law 160/2026: up to 200 kW, the supplier offsets drawn against injected energy within the billing period, at the active-energy price in the contract, until 2030. 200–400 kW: the supplier buys at the monthly weighted-average PZU price on request. | Law-firm summary (BPV Grigorescu); ANRE's page could not be opened | Medium |
| Whether the law is in force since 26 July 2026 or its application was postponed to 2027 | Two sources disagree | Unresolved |
| Prosumers up to 400 kW pay no imbalance, so suppliers do. AFEER estimates 200–372 lei/MWh per injected MWh (about 40–75 EUR/MWh). | AFEER (supplier association: an interested party) | Low, cross-check only |
| Balancing price reached 60,976 lei/MWh on 27 April 2026 | Press (Business Review) | Medium |
| PPC Romania's CEO: the state, through a state company, should pay prosumers, as GSE does in Italy | profit.ro interview | High |
| GSE pays the hourly zonal price, monthly (about two months later), with an optional guaranteed minimum of 4.75 €c/kWh for 2026 for small plants, and does the imbalance trading itself. The floor is public money. | Enpal, SurgePV | Medium |
| PPC owns the supplier (PPC Energie) and the grid operator (Rețele Electrice, formerly E-Distribuție) | PPC press release, Oct 2023 | High |
| Romanian balancing prices are **not** in the euenergy.live API (it has prices and load only) | probed | High |

## The scheme

**Price paid to the prosumer, per exported kWh, per hour:**

- `base = max(floor, PZU − fee)`, in EUR/kWh, never negative.
- `PZU` is the hourly day-ahead price. `fee` is a published aggregator fee for admin and residual risk. `floor` is a minimum price. Italy's floor is state-funded; here **PPC funds it**, so it is a cost in the profit view and the sensitivity table shows how large a floor PPC can afford.
- **Bonus (settled monthly, after the fact):** `bonus pool = bonus_share × imbalance cost saved`, shared out pro rata to each prosumer's exported kWh. Default `bonus_share = 0.5`.
- All of `fee`, `floor` and `bonus_share` are placeholders in config. No value is claimed as correct; the evaluation reports a sensitivity grid.

**Why the grid headroom is no longer in the price.** In v1 the bonus depended on the agent's safe export limit. That would pass grid data from the grid operator to the supplier, which unbundling rules may forbid. The price now depends only on public PZU data and PPC's own forecast. The safe export limit stays on the operator side.

## Imbalance savings (the profit source)

- **PPC's imbalance volume** per 30 minutes is `|actual − forecast|` of the aggregated prosumer export of the station, in MWh.
- **Two forecasts, on the same test year:** the **baseline** is "same time yesterday" (already in the repository); the **model** is the repository's PV/load forecast (`src/ml/forecast_pv_load.py`, 60-minute horizon) turned into a net-export forecast. A 60-minute horizon means PPC corrects its position on the intraday market about an hour ahead. **This is an assumption**: it needs intraday liquidity at roughly the PZU price.
- **Cost** = volume × imbalance spread (EUR/MWh). There is no balancing-price series in our data source, so v1 reports three spreads side by side: 30, 60 and 120 EUR/MWh, with AFEER's 40–75 EUR/MWh as a cross-check. A real series (ENTSO-E imbalance prices, needs a token) is an optional upgrade behind the same interface.
- **Saving** `S` = cost with baseline − cost with model.

## PPC profit view

Per scenario and spread, over the test year, against the status quo (buying at PZU and carrying baseline imbalance):

`PPC net = fee × exported kWh + (1 − bonus_share) × S − floor top-ups`

where a floor top-up is `kWh × max(0, floor − (PZU − fee))` in the hours where the floor applies. The view also lists the prosumer side: revenue under (a) a flat tariff at the yearly average PZU, (b) the scheme price, (c) the scheme price plus bonus, and (d) with battery response. **Nothing is asserted in advance**: prosumers export at midday, when PZU is lowest, so the scheme price can still pay less than a flat yearly average. The sensitivity grid (fee 0 / 10 / 20 EUR/MWh, floor 0 / 10 / 20 EUR/MWh, spread 30 / 60 / 120) shows what it takes for both sides to gain, and where PPC's net turns negative.

## Data

- **Prices:** euenergy.live, `GET /api/v1/prices?zone=RO&from=&to=`, hourly, EUR/MWh, UTC. Token in `EUENERGY_TOKEN` (gitignored `.env`). CC-BY-4.0: credit euenergy.live. Fetch with `python -m src.pricing.prices fetch --year 2025` (a module, because `.gitignore` allows only listed folders). Saved to `data/pzu/ro.parquet`. Month by month; missing hours: gaps of up to 3 hours carry the last price, longer gaps stay missing and are counted.
- **Alignment:** the price year differs from the Ausgrid test year, and Ausgrid is Sydney (July is winter). Prices are averaged per (month, hour) in Bucharest time; each Sydney interval takes the **month + 6 and the same local clock hour**. The result shows the shape of the effect, not a forecast in euros, and the pitch says so.
- **Imbalance spread:** scenario values (above), real series later.

## Phases

Five pull requests, in order. Each phase is testable and demoable by itself.

1. **Pricing core.** PZU loader and alignment, price rule (`fee`, `floor`), prosumer revenue under flat / scheme price / with floor, PPC fee income and floor top-ups. Evaluation block and chart behind `python -m src.eval.run --pricing`.
2. **Imbalance savings and bonus.** Net-export forecast adapter, imbalance volume and cost under baseline and model, bonus pool, PPC net, sensitivity grid. Touches the area P6 is changing (`src/ml/forecast_pv_load.py`, `src/eval/`): rebase before the PR.
3. **Per-house price in the agent API.** New contract object `HousePrice` (`house_id`, `interval_start`, `buyback_eur_kwh`, `wholesale_eur_mwh`, `floor_applied`, `reason`), carried in `Plan.prices`; `GET /prices` returns the day's wholesale curve and the plan's prices. The price is the hourly base only; the bonus is settled monthly and appears in the evaluation and statement, not in the live price. `src/common/` and `src/agent/` belong to P1, who approves. Update `docs/09-contract.md` and the mocks in the same PR.
4. **Battery response.** Price-driven dispatch for houses with a battery (a price at or above the day's median is "high"; low price: store; high price: sell into the room under the cap and store only what the cap would waste; idle on fallback hours). Reuses `src/grid/battery.py`. Batteries are assumed on the first 30% of houses (101,243 of 332,684 Romanian prosumers have one, [docs/06](../../06-motivation-and-problems.md)). The live agent has no per-house surplus, so live plans keep `battery_kw = 0`; battery response is measured in the evaluation. Using batteries to cancel PPC's imbalance in real time is a follow-up, not v1: it needs a 15-minute control loop assumption.
5. **Prices tab in the operator screen.** Day curve with the selected hour marked, each house's price and reason (from `GET /prices`), and tables from the evaluation summary: what prosumers earn and the PPC profit view. Works with the illustrative mock curve when no price data exists, marked "Mock".

## Approval path (to settle with PPC; none of this is checked with them)

- **Law:** up to 200 kW the compensation is by quantity at the contract price until 2030, so this product may fit prosumers who opt out of compensation, or the 200–400 kW tier, better. Needs a legal opinion, and ANRE's updated methodology is pending.
- **Roles:** acting as a single buyer and balancing party for others' injected energy may need a specific role or licence. Not verified.
- **Unbundling:** handled by design (no grid data in the price). The operator-side limit and the supplier-side price stay separate.
- **Internal sign-off:** commercial pricing, energy risk (intraday position management), billing IT (15-minute metering), legal. An opt-in pilot on smart-meter customers is the natural first step.
- **Questions for PPC:** what is paid for injection today under MaxControl; their actual imbalance cost per injected MWh; whether intraday correction at about PZU cost is realistic; the cost PPC would accept for a floor.

## Tests

Pure and fast, no network.
- Price rule: floor applies; never negative; negative PZU pays the floor or zero as configured; fee deducted.
- Prices: UTC to Bucharest conversion, season alignment, gap fill and flag.
- Revenue and PPC net: small hand-computed examples (including floor top-ups and a bonus pool).
- Imbalance: volume and cost on a tiny series; saving is zero when the forecasts are equal.
- Fetch: saved sample response, no token in CI.
- Contract: `HousePrice` rejects invalid values; API test for `/prices`.
- Battery: bounds, no export above the cap, idle on fallback hours.
- UI: renders from mocks.

## Risks and limits (stated in the pitch)

- The price year and the Ausgrid year differ; results show shape, not euros.
- The imbalance spread is a scenario value, not market data. The headline is a range, not one number.
- The saving depends on intraday correction one hour ahead being possible at about PZU cost.
- PZU is a proxy for PPC's purchase cost. The real cost also includes network and supplier fees.
- Simulation on Australian household data, not PPC's network or customers.
- `fee`, `floor` and `bonus_share` are free parameters.
- If euenergy.live changes or goes down, ENTSO-E (document type A44 for prices, A85 for imbalance, zone `10YRO-TEL------P`) is the fallback and needs its own token.

## Done means

- `make test lint smoke` passes on each phase's branch.
- Every number on a slide comes from the evaluation output.
- `README.md` is updated in each phase that changes how the project runs.
