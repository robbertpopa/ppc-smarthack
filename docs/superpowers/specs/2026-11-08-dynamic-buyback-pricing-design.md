# Prosumer aggregator price: design

**Status:** design v3.1, 2026-11-08 (v3.1 adds PPC's MaxControl as a second "today", see "What PPC pays today"). Replaces v1 (a "share of spot" buy-back with a grid bonus) and v2 (a monthly "at least the regulated price" guarantee). v3 was built and tested in a scratch worktree (439 tests pass, screen checked in a browser) before the plan was written. Plan: [../plans/2026-11-08-dynamic-buyback-pricing.md](../plans/2026-11-08-dynamic-buyback-pricing.md). Background, numbers and the simulated year: [../../14-prosumers-and-pricing.md](../../14-prosumers-and-pricing.md).

## Goal

PPC offers an opt-in product to prosumers who have a battery and a smart meter. PPC acts as single buyer of their injected energy, like Italy's GSE (Ritiro Dedicato), which PPC Romania's CEO has said Romania should copy. The price follows the hourly day-ahead price (PZU), so shifting energy to the evening pays. A monthly solar adder keeps today's regulated money for the energy a prosumer cannot shift. PPC's gain comes from the value of shifted energy, a fee, and part of the imbalance cost it saves by forecasting the aggregated export. Other prosumers stay on the regulated terms, unchanged.

## Context (what we found, and how sure we are)

| Fact | Source | Confidence |
|---|---|---|
| PPC's prosumer product (MaxControl) prices consumption at 0.097 lei/kWh plus the monthly consumption-weighted average of 15-minute PZU prices, with a price floor and cap. The offer PDF says the injection price is "per the regulations". | PPC's own offer PDF | High |
| **MaxControl pays injected energy monthly at the 15-minute day-ahead price minus the grid injection tariff (TG, 0.00363 lei/kWh), zero when the price is negative.** Residential prosumers up to 200 kW with a smart meter. Launched July 2026, the offer was then valid to the end of that month. | Economica, 7 July 2026 (press); PPC's PDF is silent | Medium: confirm current terms with PPC |
| For older compensation contracts PPC's page says injected energy is offset kWh against kWh and any surplus unpaid after 24 months is paid at a tariff "lower than the consumption price"; its own statements conflict on which tariff applies | PPC's prosumer price page | Medium |
| Law 160/2026: up to 200 kW the supplier offsets drawn against injected energy within the billing period at the contract's active-energy price, until 2030. 200–400 kW: the supplier buys at the monthly weighted-average PZU price on request. | Law-firm summary (BPV Grigorescu); ANRE's page could not be opened | Medium |
| Whether the law applies since 26 July 2026 or from 2027 | Two sources disagree | Unresolved |
| Prosumers up to 400 kW pay no imbalance, so suppliers do. AFEER estimates 200–372 lei/MWh per injected MWh (about 38–72 EUR/MWh at about 5.2 lei/EUR). | AFEER (supplier association: an interested party) | Low, cross-check only |
| PPC Romania's CEO: a state company should pay prosumers, as GSE does in Italy | profit.ro interview | High |
| GSE pays the hourly zonal price, monthly, with an optional guaranteed minimum (4.75 €c/kWh for 2026), and does the imbalance trading. The floor is public money. | Enpal, SurgePV | Medium |
| PPC owns the supplier (PPC Energie) and the grid operator (Rețele Electrice) | PPC press release, Oct 2023 | High |
| Distributors have no legal access to prosumer batteries; prosumers oppose control | Press (see docs/14) | Medium |
| Romanian balancing prices are not in the euenergy.live API (prices and load only) | probed | High |
| The API refuses Python's default client name (HTTP 403) but accepts `curl` | probed | High |

## What PPC pays today (two kinds of customer), and where the saving is

| | Older compensation contract | PPC MaxControl |
|---|---|---|
| Injection is paid at | the contract's active-energy price (a monthly average for an indexed contract; a fixed price for a fixed contract) | 15-minute day-ahead price minus TG |
| PPC's margin on the energy | negative: it pays about the monthly average (or more) for midday energy that is worth less | about zero |
| PPC still bears | imbalance | imbalance |
| A battery helps the prosumer | not for price (paid the same at any hour) | yes: evening exports earn the evening price |

For one battery household (10 kWp, 10 kWh battery, 7.6 MWh exported a year, prices November 2025–October 2026, simulated, EUR per year):

| | Older contract | MaxControl | Proposed (fee 30, solar adder) |
|---|---:|---:|---:|
| Prosumer receives | 982 | 1,034 | 1,169 |
| PPC margin before imbalance | −343 | −2 | −136 |
| PPC against older contract | none | +341 | +207 |
| Prosumer against older contract | none | +5% | +19% |

Consequences:
1. **The cheapest saving for PPC is moving battery households from the older contract to MaxControl** (about +341 EUR a year each, the prosumer gains about 5%). It exists today. Households without a battery lose about a third on MaxControl, so they will not move.
2. **The solar adder is a way to share value to win older-contract customers, not a need of MaxControl customers.** On top of MaxControl it would cost PPC more, so it is never added to MaxControl.
3. **The imbalance PPC bears is uncertain by more than a factor of 10** (a distribution operator's study implies a few EUR/MWh; AFEER's 38–72 EUR/MWh is an interested party). The bonus is therefore the least certain part.
4. **What this project adds beyond MaxControl:** a forecast-based imbalance saving, the evening-price signal for batteries, and the evaluation of how to split the value.

## The scheme

**Who:** prosumers with a battery and a smart meter (SMI). About a third of residential prosumers, and growing. If the storage obligation of Law 255/2024 turns out to be in force (unverified), more.

**What PPC pays for each exported kWh (settled monthly, shown as separate invoice lines):**

1. **Hourly price:** `max(floor, PZU − fee)` for the interval (EUR/MWh). Never negative, so the prosumer is never charged in negative-price hours. `floor` defaults to 0.
2. **Solar adder:** for each month, the month's average PZU minus its solar-weighted PZU, from public prices and a standard solar shape (Bucharest latitude), floored at 0 and published after the month ends. The same for everyone and independent of what one prosumer does, so it does not dull the incentive to shift. It carries over today's regulated overpayment (about 50 EUR/MWh in March–August, near 0 in winter).
3. **Imbalance bonus:** `bonus_share` of the measured imbalance saving (below), shared pro rata to exported kWh of participants who share data. Default `bonus_share = 0.5`.

**What the prosumer pays PPC:** an aggregator fee per exported MWh (default 30 EUR/MWh, range 20–40), covering admin and PPC's remaining imbalance risk. Nothing else: no subscription, no penalty for staying out.

**What PPC does not do:** control inverters or batteries. It reads smart-meter data and, with consent, battery or inverter data, and publishes next-day prices as information. The prosumer's own system decides.

**Why not a "never below the regulated price" guarantee (v2).** In months where the guarantee binds, shifting energy earns the prosumer nothing extra. The simulation (docs/14, section 5b) gave a battery owner +2.4% and PPC about 94% of the value. The solar adder keeps the full evening incentive.

**Why grid headroom is not in the price (v1).** It would pass grid data from the grid operator to the supplier, which unbundling rules may forbid. The price depends only on public PZU data, meter data and PPC's own forecast. The safe export limit stays on the operator side.

All of `fee`, `floor` and `bonus_share` are placeholders in `src/pricing/config.py`. No value is claimed as correct; the evaluation reports a fee sensitivity table (0–50 EUR/MWh).

## What is measured (the evaluation block)

For the houses with a battery (the first 30% of the station's houses in sorted order, matching the 33% of residential prosumers with one), under the smart export limit, over the test year:

| Row | Prosumer is paid | PPC's margin is |
|---|---|---|
| Older contract today | monthly average PZU on the exported kWh | value of that energy (its PZU price) minus what it pays |
| MaxControl today, no battery response | 15-minute spot minus TG (0.7 EUR/MWh) | same formula |
| MaxControl today with battery response | the same, on the battery-shifted exports | same formula |
| Proposed hourly price only | hourly price (fee, floor) | same formula |
| Proposed hourly price + solar adder, no battery | hourly + adder | same formula |
| **Proposed**: hourly + adder + battery response | hourly + adder on the battery-shifted exports | same formula |

Each row reports the prosumer's revenue and its change against today in percent, PPC's margin in EUR and as a percent of the energy's value, and PPC's improvement against the older contract (the first row). The fee sensitivity also reports the prosumer's share of the value created. **Nothing is asserted in advance.** Prosumers export at midday, when PZU is lowest, so PPC pays today about 49 EUR/MWh (about 70 in sunny months) above that energy's value, and the adder keeps most of that. Only regulation can remove it.

## Imbalance savings (the profit source beyond shifting)

- PPC's imbalance volume per 30 minutes is `|actual − forecast|` of the station's net export `max(0, pv − load)`, before any limit.
- Two forecasts on the same test year: the **baseline** is "same time yesterday"; the **model** is the PV/load forecast (`src/ml/forecast_pv_load.py`, 60-minute horizon). A 60-minute horizon means PPC corrects its position on the intraday market about an hour ahead. **This is an assumption:** it needs intraday liquidity at roughly the PZU price.
- Cost = volume × imbalance spread. There is no balancing-price series in our data source, so three scenario spreads are reported side by side: 30, 60 and 120 EUR/MWh, with AFEER's 38–72 EUR/MWh as a cross-check. A real series (ENTSO-E imbalance prices, needs a token) is an optional upgrade behind the same interface.
- Saving = baseline cost − model cost. The battery houses' share of the station's exports gets the bonus (`bonus_share` of a positive saving); PPC keeps the rest. A negative saving is not shared.
- Without a trained PV/load model this part is skipped and the output says so.

## Data

- **Prices:** euenergy.live, `GET /api/v1/prices?zone=RO&from=&to=`, hourly, EUR/MWh, UTC, token in `EUENERGY_TOKEN` (gitignored `.env`), with a `User-Agent` header. CC-BY-4.0: credit euenergy.live. Fetch with `python -m src.pricing.prices fetch --year 2025` (a module, because `.gitignore` allows only listed folders). Saved to `data/pzu/ro.parquet`, month by month; gaps of up to 3 hours carry the last price, longer gaps stay missing and are counted.
- **Alignment:** the price year differs from the Ausgrid test year, and Ausgrid is Sydney (July is winter). Prices are averaged per (month, hour) in Bucharest time; each Sydney interval takes **month + 6 and the same local clock hour**. The result shows the shape of the effect, not a forecast in euros, and the pitch says so.
- **Imbalance spread:** scenario values, real series later.

## Phases

Four pull requests, in order. Each phase is testable and demoable by itself.

1. **Prices, tariff, solar adder, battery, evaluation** (`pricing/core`). The pure `src/pricing/` modules, the `pricing` block, markdown and chart behind `python -m src.eval.run --pricing`.
2. **Imbalance savings and bonus** (`pricing/imbalance`). Net-export forecasts, volume and cost, bonus, in the block. Reads `forecast_pv_load.py` (P6's area) without editing it.
3. **Per-house price in the agent API** (`pricing/api`). `HousePrice` in the contract (`wholesale_eur_mwh`, `hourly_eur_kwh`, `adder_eur_kwh`, `total_eur_kwh`, `floor_applied`, `reason`) carried in `Plan.prices`; a price source with an illustrative mock curve; `GET /prices` returns `interval_start`, `mock`, `curve` (24 UTC hours) and `houses` (the plan's prices, empty when no plan exists). The bonus is settled monthly and appears in the evaluation, not in the live price. The live agent has no per-house surplus, so live plans keep `battery_kw = 0`. `src/common/` and `src/agent/` belong to P1, who approves; `docs/09-contract.md` is updated in the same PR.
4. **Prices tab in the operator screen** (`pricing/ui`). The day curve with the selected hour marked, each house's price and reason, and the earnings and imbalance tables from the evaluation summary. Works with the mock curve, marked "Mock".

Using batteries to cancel PPC's imbalance in real time is a follow-up, not part of this work.

## Approval path (to settle with PPC; none of this is checked with them)

- **Law:** up to 200 kW the compensation is by quantity at the contract price until 2030, so this product fits prosumers who opt out of compensation, or the 200–400 kW tier, better. For 200–400 kW the regulated price is probably a legal minimum, so the adder matters. Needs a legal opinion; ANRE's updated methodology is pending.
- **Roles:** acting as single buyer and balancing party for others' energy may need a specific role or licence. Not verified.
- **Unbundling:** handled by design (no grid data in the price).
- **Internal sign-off:** commercial pricing, energy risk (intraday position management), billing IT (15-minute metering), legal. An opt-in pilot on smart-meter MaxControl customers with a battery is the natural first step.
- **Questions for PPC:** what is paid for injection today under MaxControl; their actual imbalance cost per injected MWh; whether intraday correction at about PZU cost is realistic; their real purchase mix; the fee they would accept.

## Tests

Pure and fast, no network.
- Price rule: floor, fee, never negative, missing prices stay missing.
- Prices: UTC to Bucharest, season alignment, gap fill, `User-Agent` and token header, missing file message, token required.
- Solar adder: weights, zero for flat prices, positive for cheap midday, floored at zero.
- Settlement: a hand-computed example.
- Battery: defaults equal the grid battery model; cap and power respected; each day empty; stores waste; idle on fallback and when nothing pays.
- Evaluation block: signs, fee monotonicity, JSON-safe, markdown, chart.
- Imbalance: volume, saving zero for equal forecasts, bonus split, a model trained on mock labels.
- Contract, planner, service, API, screen allowlist and tab.

## Risks and limits (stated in the pitch)

- The price year and the Ausgrid year differ; results show shape, not euros.
- The imbalance spread is a scenario value; the saving assumes intraday correction an hour ahead at about PZU cost.
- PZU is a proxy for PPC's purchase cost and for the value of the energy; the real mix is not public.
- A prosumer whose real generation shape differs from the standard shape is not exactly neutral against today.
- The price of the older contract is a modelled monthly average; fixed contracts may pay more (third-party guides report 0.72–0.86 lei/kWh). MaxControl's terms come from one press article.
- Simulation on Australian household data and one station, not PPC's customers.
- Battery wear is not counted, and shifted energy must be surplus (a home battery is often worth more covering the home's own evening load).
- `fee`, `floor` and `bonus_share` are free parameters.
- If euenergy.live changes or goes down, ENTSO-E (A44 for prices, A85 for imbalance, zone `10YRO-TEL------P`) is the fallback and needs its own token.

## Done means

- `make test lint smoke` passes on each phase's branch.
- Every number on a slide comes from the evaluation output.
- `README.md` is updated in each phase that changes how the project runs.
