# PPC Romania in numbers

What we learned about PPC from the workshop presentation and public sources. Confidence is marked per group: **(deck)** = PPC presentation, **(press)** = articles, **(unverified)** = a search summary whose source we did not see.

## The four companies (deck)
| Company | Role | Figures from the deck |
|---|---|---|
| PPC Renewables Romania | Renewable generation | 1.6 GW+ installed, largest private producer |
| Rețele Electrice | Distribution (Muntenia, Banat, Dobrogea) | 136,000 km of lines, 293 substations, 26,000+ transformer stations |
| PPC Energy | Supply | ~3 million customers, ~80 stores |
| PPC Blue | E-mobility | 1,100+ charging points |

## Data and platform (deck)
- 2M+ smart metering points, 96 readings per day each (every 15 minutes), ~192 million rows per day.
- Internal platform (PPC Digital Solutions): collection → NiFi (streaming) and Airflow (batch) → S3 (bronze/silver) → Spark/PySpark on EMR → Redshift and Kafka feeds to suppliers.
- Stated effect: consumption data reaches suppliers in minutes, not days.
- "What's next: AI": anomaly detection on meter behaviour, predictive monitoring of faulty meters, AI-assisted dashboards.

## Existing AI portfolio (deck): avoid copying it
| # | Project | Stage |
|---|---|---|
| 01 | Smart Sentry (failure prediction for turbines/panels) | production |
| 02 | Energy Anomaly Detection (suspicious consumption/fraud) | production |
| 03 | LegalRoute (OCR + LLM for documents) | production |
| 04 | Inverter Smart Extractor (PDF → table) | production |
| 05 | Short Term Energy Demand Forecast (15 minutes, day ahead) | production |
| 06 | AI Claims Agent (voice agent for overdue bills) | development |
| 07 | ReClassAI (complaint reclassification) | production |
| 08 | Short Term Energy Production Forecast (wind) | development |
| 09 | AgentHub (AI agent platform) | development |

The list may not be exhaustive. Not in the deck: battery optimisation, customer flexibility, prosumers on the low-voltage grid, AI for PPC Blue, prioritisation of grid interventions.

## External figures (press; re-verify before using in the presentation)
**Generation (PPC Renewables)**
- 1,546 MW in 32 parks: wind 1,182 MW, solar 341 MW, hydro 22 MW ([PPC site](https://www.ppcenergy.ro/ppc-renewables/ppc-renewables-romania/)). 2026 press releases speak of 1.6 GW.
- Targets: 2 GW by end of 2026, 3.6 GW in 2028, 4.7 GW in 2030.
- Announced batteries (BESS): Corugea 40 MW / 80 MWh, Topolog 13.5 MW / 27 MWh, Târgușor 60 MW / 120 MWh, Fântânele-Vest ~45.7 MW / 91 MWh (≈160 MW / ≈320 MWh in total), plus Ciorani 27 MW in permitting. The site still showed 0 MW of installed battery capacity.

**Distribution (Rețele Electrice)**
- Investments of ~1.4 billion lei in 2025 (908 million own funds), ~1.3 billion planned for 2026.
- Smart meters: ~2 million at end of 2025; coverage on 31.12.2025: Dobrogea 66.85%, Muntenia 58.81%, Banat 56.45%; 2026 target: 67%.
- Service quality: unplanned SAIDI Muntenia 74.6 min in 2024 (vs 142.8 in 2019); national SAIDI rose in 2025 (236 min vs 229).
- **Network losses (technical) and energy theft: we found no figures.**

**Supply (PPC Energie)**
- Turnover 8.51 billion lei and **net loss of 143 million lei in 2025** (79 million in 2024). Competitors in 2025: Electrica profit 244 million lei, E.ON profit 286 million lei.
- **We did not find the reason for the loss.** We only know PPC was asking the state for delayed compensation for the price cap (805 million lei at end of 2024, plus 266 million financing costs). We cannot claim this is the cause.

**Mobility (PPC Blue)**
- 1,400+ points, 46+ MW (2026 press release; the deck is older). New partnerships (Cometex/Altex, 300+ points), a CEF project with 106 points on TEN-T routes. Usage data: not public.

**Group**
- Adjusted EBITDA 2 billion euro in 2025, reported net profit 359 million euro. In Romania, EBITDA in the first half of 2026: 276.9 million euro vs 195.2.

## The Romanian market now (press)
- Negative prices in 2026: eight hours on 5 April, a record nine hours on 26 April. Evening peak of 1,032 lei/MWh on 8 August.
- ~5,000 MW of photovoltaic and ~3,100 MW of wind installed nationally. Maximum daily spread 168 €/MWh in 2025. DNV estimates battery revenues of 120–180 €/kW/year.
- Prosumers: 332,684 (30 April 2026), 3,789 MW, 101,243 with batteries; 359,378 on 30 June 2026, 127,084 with batteries (unverified). Prosumer capacity exceeds the ~3,300 MW of dispatchable solar parks.

Details on prosumer problems: [06-motivation-and-problems.md](06-motivation-and-problems.md).
