# Romanian prosumers, what PPC pays today, and what to charge

Background for the pricing work ([spec](superpowers/specs/2026-11-08-dynamic-buyback-pricing-design.md)). Research as of 2026-11-08. Prosumer figures are ANRE data as quoted by the press, not ANRE's own publications. Items marked **UNVERIFIED** conflict across sources or were not opened in full. Prices in sections 3 and 4 are our own calculation from the euenergy.live API (pulled 2026-11-08), see "How we computed it".

## 1. Market size

| Date | Prosumers | Installed (MW) | With batteries |
|---|---:|---:|---:|
| 30 Apr 2026 | 332,684 | 3,789 | 101,243 |
| 30 Jun 2026 | 359,378 | 4,019 | 127,084 |

- 30 Apr 2026: households 299,523 prosumers (1,929 MW), companies 33,161 (1,860 MW). About 10,000 new prosumers a month.
- Battery share of residential prosumers rose from 23% to 33% in 2026; commercial and industrial from 7.5% to 10%.
- Prosumer battery capacity: about 850 MW (ANRE estimate), over 800 MW (APCE, the prosumer association), over 600 MW (ANRE's vice-president). Company BESS about 600 MW. Utility-scale BESS about 1.1 GW / 2 GWh. ANRE lacks exact figures because not all prosumers report new or upgraded batteries.

## 2. Rules: sell limit and compensation

- Prosumer status: installations up to 400 kW per consumption point.
- Up to 200 kW: quantity-based compensation (kWh against kWh in the billing period, at the contract's active-energy price). 200–400 kW: surplus settled financially at the **monthly weighted-average PZU price of the production month**. A supplier must buy at that price on request.
- After 2030 all prosumers sell on the 200–400 kW terms: wholesale price, no 1:1 compensation.
- Law 160/2026 is in force since 26 Jul 2026 and amended Law 123/2012. Its application depends on an updated ANRE methodology (not yet seen). One source says application was postponed to 2027: **UNVERIFIED**.
- **UNVERIFIED storage obligation:** ess-news and pv magazine describe Law 255/2024 as requiring new prosumers to install storage (at least 30% of PV capacity for 3–200 kW systems, 50% for 200–400 kW), and existing 3–400 kW prosumers to add storage by 31 Dec 2027 or be limited to 3 kW export. Adevărul reports the Senate committees removed it; Business24 and ProTV report it as something the government wants. Check the current law text before relying on it.
- Subsidy: RON 400M, up to 75% of eligible costs, capped at RON 15,000 incl. VAT, for existing prosumers. Minimum battery size cut from 12 kWh to 10 kWh.
- PPC's prosumer offer (MaxControl): consumption at 0.097 lei/kWh fixed (supply and estimated imbalance) plus the monthly consumption-weighted average of 15-minute PZU prices, with a billing cap of 0.999 lei/kWh and a floor of 0. The injection price is "per the regulations". Source: PPC's offer PDF.

## 3. What PPC pays externally (PZU proxy)

PPC's real purchase mix (forwards, own generation) is not public. PZU is the proxy. EUR/MWh, averages of hourly prices, local Bucharest time.

| Period | All hours (monthly avg) | Solar 10–15 | Evening 18–22 | Average − solar |
|---|---:|---:|---:|---:|
| Last 12 months (Nov 2025–Oct 2026) | 133 | 84 | 191 | 49 |
| Sunny months (Mar–Aug 2026) | 116 | 46 | 177 | 70 |
| October 2026 | 240 | 184 | 304 | 56 |

Month by month:

| Month | Avg | Solar | Evening | Avg − solar | Hours ≤ 0 |
|---|---:|---:|---:|---:|---:|
| 2025-11 | 121 | 107 | 171 | 14 | 0 |
| 2025-12 | 118 | 118 | 148 | 0 | 0 |
| 2026-01 | 149 | 163 | 205 | −14 | 0 |
| 2026-02 | 100 | 79 | 139 | 20 | 4 |
| 2026-03 | 105 | 36 | 171 | 70 | 27 |
| 2026-04 | 96 | 33 | 149 | 63 | 79 |
| 2026-05 | 110 | 35 | 164 | 75 | 49 |
| 2026-06 | 117 | 47 | 191 | 71 | 38 |
| 2026-07 | 117 | 47 | 168 | 70 | 32 |
| 2026-08 | 151 | 79 | 220 | 72 | 9 |
| 2026-09 | 177 | 82 | 265 | 95 | 13 |
| 2026-10 | 240 | 184 | 304 | 56 | 0 |

## 4. Today versus a PPC aggregator, per MWh injected at midday

12-month averages. "Today" is the regulated monthly-average price.

| | Today (regulated) | Aggregator, hourly price | Aggregator + battery |
|---|---:|---:|---:|
| Prosumer receives | about 133 | 74 (84 − 10 fee) | 163 per MWh stored (0.9 × (191 − 10)) |
| Worth to PPC (what it does not have to buy) | 84 | 84 | 172 |
| PPC margin before imbalance | **−49** | +10 | +9 |
| Imbalance cost, borne by PPC | about 38–72 (AFEER, interested party) | reduced by forecast (to measure) | same |
| Prosumer versus today | none | **−59 (−44%)** | **+30 (+22%)**, battery wear not counted |

Reading it:
- Today PPC pays about 49 EUR/MWh above what midday energy is worth (70 in sunny months) and bears the imbalance. This is the cost PPC's CEO wants the state to carry.
- Moving a prosumer to a pure hourly price **transfers** about 59 EUR/MWh from the prosumer to PPC. It creates no value.
- New value comes only from (a) imbalance savings, capped at about 38–72 EUR/MWh, and (b) a battery shifting energy from midday to evening, about 88 EUR/MWh stored.
- A prosumer without a battery cannot be made whole by a bonus: matching today's 133 needs about 118 EUR/MWh of savings at a 50% share, more than the whole estimated imbalance cost.

## 5. What to charge, and how (proposal v2)

Principle: **nobody is worse off than today; the value created is shared.** The operator cannot dispatch prosumer batteries (section 6), so every part is opt-in and runs on consent and prices.

An earlier version of this section used a monthly "at least the regulated price" guarantee. The simulation in section 5b showed it fails: in months where the guarantee binds, shifting energy earns the prosumer nothing extra, so a battery owner gained only +2.4% and PPC captured about 94% of the value. It is replaced by the solar adder below.

**Who it is for.** Prosumers with a battery and a smart meter (SMI), about a third of residential prosumers and growing. Others stay on the regulated terms, unchanged (0% change for them and for PPC). If the storage obligation turns out to be law, the addressable base grows.

**What PPC pays for injected energy (settled monthly, as separate invoice lines, as PPC's offers already do):**

1. **Hourly price.** Each exported kWh at `max(0, PZU − fee)` for its interval (15 minutes where the meter allows). The prosumer is never charged in negative-price hours.
2. **Solar adder.** A published per-kWh amount for each month, equal to that month's average PZU minus its generation-weighted PZU, computed from public data after the month ends. It is the same for everyone and does not depend on the prosumer's behaviour, so it does not dull the incentive to shift. It carries over today's regulated overpayment (about 50 EUR/MWh in March–August, about 0 in winter), so a prosumer who does not shift gets roughly today's money. Whether it is floored at 0 in winter months is a choice (January would be −14 EUR/MWh).
3. **Savings share (bonus).** A share (start at 50%) of the imbalance cost PPC measurably saved, for participants who share their data and a day-ahead export schedule.

**What the prosumer pays PPC.**

1. **Aggregator fee** per exported MWh, covering admin and PPC's remaining imbalance risk. Start at **30 EUR/MWh**: it splits the shifting value about evenly (section 5b). The range 20–40 is the negotiating room. A lower fee for prosumers who share data is possible. The evaluation (spec phase 2) will compute the break-even fee.
2. **Nothing else:** no subscription, no access fee, no penalty for not taking part.

**What PPC does not do.** It does not control inverters or batteries and does not change their software. It reads smart-meter data and, with consent, battery or inverter data, and publishes the next day's prices and a recommended export window as information. The prosumer's own system, or the prosumer, decides. This answers the concerns in section 6.

**What it does not fix.** PPC still pays the adder, so its margin stays negative before imbalance (about −20% of the energy's value instead of −54%). The structural overpayment on unshifted midday energy remains for everyone not in the product. Only regulation can remove it. The pitch should say so.

**Runway.** In 2030 quantity compensation ends and everyone sells at wholesale. Hourly settlement then becomes the default basis, and a product like this is ready.

## 5b. Simulated year, one battery prosumer

Stylised household: 10 kWp (13,000 kWh a year), 60% of generation exported (7,560 kWh), 10 kWh battery (9 kWh usable, 5 kW, 90% round trip) shifting exports from the cheapest solar hours to the best evening hours (18–22) each day. Prices: the 12 months in section 3. PPC's value of an exported kWh is the PZU price of its hour. Today's revenue is the regulated monthly-average price on the unshifted exports: **982 EUR a year**; PPC's margin before imbalance is **−343 EUR (−54% of the energy's value)**.

Value created by the battery shifting: about **393 EUR a year**.

| Design | Fee (EUR/MWh) | Prosumer revenue | Prosumer vs today | PPC margin before imbalance | PPC improvement (share of today's loss) | Split of the 393 (prosumer / PPC) |
|---|---:|---:|---:|---:|---:|---:|
| Guarantee (max of hourly and regulated), v1 | 10 | 1,006 | +2.4% | +27 | +370 (108%) | 6% / 94% |
| Hourly + solar adder | 0 | 1,363 | +38.8% | −331 | +12 (4%) | 97% / 3% |
| Hourly + solar adder | 10 | 1,296 | +32.0% | −264 | +79 (23%) | 80% / 20% |
| Hourly + solar adder | 20 | 1,232 | +25.4% | −199 | +144 (42%) | 63% / 37% |
| **Hourly + solar adder** | **30** | **1,169** | **+19.0%** | **−136** | **+207 (60%)** | **47% / 53%** |
| Hourly + solar adder | 40 | 1,107 | +12.7% | −74 | +269 (78%) | 32% / 68% |
| Hourly + solar adder | 50 | 1,046 | +6.5% | −14 | +329 (96%) | 16% / 84% |

On top, the imbalance savings (an assumption until the evaluation measures it). Using a baseline imbalance cost of 55 EUR/MWh (middle of AFEER's 38–72) and a forecast that removes 50% of it: about 199 EUR a year saved, shared 50/50:

- Prosumer: **+100 EUR, +10%** of today's revenue.
- PPC: **+100 EUR**, another 29% of today's loss.
- Range: with baseline 38–72 EUR/MWh and 30–70% removed, the prosumer's share is +4% to +19% of today's revenue.

**Result at fee 30 plus the middle imbalance case:**

| | Today | Proposed | Change |
|---|---:|---:|---:|
| Prosumer (battery owner) | 982 EUR | 1,269 EUR | **+29%** |
| PPC margin before imbalance | −343 EUR | −36 EUR | loss reduced by about **90%** |
| Prosumer without a battery | 982 EUR | 982 EUR | 0% (stays regulated) |

Limits of this simulation: a synthetic generation shape (Romanian latitude, assumed monthly shares) with identical smooth days, so it ignores the correlation between sunny days and low prices (which would make the gain larger); a flat 60% export share; a greedy daily battery rule; no battery wear; shifted energy must be surplus (a home battery is often worth more covering its own evening load); regulated price taken as the simple monthly mean, not volume-weighted; PZU as PPC's value. Percentages are relative to one household. The script is `local-notes/pricing_sim.py` (not committed).

## 6. Operators cannot access prosumer batteries today (design constraint)

- **Legal:** distributors have no right to access prosumer installations. ANRE's Alicus backed access with prosumer consent in 2023, which needs a law change. In Aug 2026 PM Bolojan asked for dispatching of prosumer generation and storage, saying new rules are still needed.
- **Technical:** distributors cannot see or change inverter settings, production profiles or battery data. Mihai Pește (Rețele Electrice, PPC group) says a 2024 initiative to share inverter data was blocked. His goal is data sharing, not direct operation (Nordics, UK, Australia as models).
- **Prosumer objections** (APCE, Dan Pârșan): "abusive control", fear that distributors dictate charge, discharge and production, no software and hardware for it yet, cybersecurity risk from forced inverter software changes (ANRE linked it to Chinese-made inverters), and "fix your own network first".
- **Pilots:** Electrica's virtual power plant and Delgaz Grid's REDFlex test flexibility, but neither is full dispatch. DEER plans about 300 transformer replacements and 270 remote monitoring units.
- Prosumer batteries already help the grid in practice: they fed it after Reactor 2 tripped (Digi24).

**Implication:** assume consent and incentives, never dispatch.

## 7. Open questions and checks

- **Law:** current text of the storage obligation; whether Law 160/2026 applies now or from 2027; whether a PPC financial product can coexist with quantity compensation up to 200 kW; whether PPC may act as single buyer and balancing party for others' energy. Needs a legal opinion and ANRE's pending methodology.
- **PPC data:** what it actually pays for injection today under MaxControl; its real imbalance cost per injected MWh; its real purchase mix; whether intraday correction one hour ahead at about PZU cost is realistic.
- **Unbundling:** keep grid data (Rețele Electrice) out of the supplier's price. The proposal uses only public PZU data, smart-meter data and consented customer data.
- **Not read yet:** the AFEER study ([afeer.ro/pdf/studiu-2026.pdf](https://www.afeer.ro/pdf/studiu-2026.pdf)) in full, and ANRE's own prosumer statistics (primary source).

## How we computed section 3 and 4

- Hourly day-ahead prices for Romania from the euenergy.live API (CC-BY-4.0), 12 months to 31 Oct 2026. Some hours are missing (a month has 672–744 rows instead of its full hours).
- "Solar" is 10:00–14:59 and "evening" 18:00–21:59, Bucharest time. These are simple averages, not weighted by actual generation, so a real prosumer's weighted price will differ.
- The fee of 10 EUR/MWh is a placeholder. Lei figures are converted at about 5.2 lei/EUR (assumed). AFEER's 200–372 lei/MWh is therefore about 38–72 EUR/MWh.
- Battery numbers assume 90% round trip, evening sale at the evening average, and ignore wear and the fact that the shifted energy must be surplus.

## Sources

- https://www.romania-insider.com/ro-10000-prosumers-one-month-jun-2026
- https://www.ess-news.com/2026/09/15/romania-finalizes-rules-for-national-battery-storage-subsidy-program/
- https://e-nergia.ro/romania-a-depasit-pragul-de-330-000-de-prosumatori-aproape-o-treime-au-deja-baterii-apar-10-000-de-noi-prosumatori-pe-luna-romania-avea-la-30-aprilie-2026-332-684-de-prosumatori-racordati-la-rete
- https://balkangreenenergynews.com/prosumers-in-romania-have-much-more-battery-power-than-energy-companies/
- https://www.economica.net/prosumatori-retea-date-control_809199.html
- https://www.profit.ro/povesti-cu-profit/energie/bolojan-cere-dispecerizarea-prosumatorilor-distribuitorii-solicita-de-mai-demult-sa-capete-acces-la-instalatiile-acestora-pentru-echilibrarea-sistemului-energetic-national-22632120
- https://www.ppcenergy.ro/prosumatori/legislatie/
- https://agerpres.ro/ots/compensarea-energiei-pentru-prosumatori-se-modifica-ce-urmeaza-pana-in-2030--660492
- https://adevarul.ro/economie/obligatia-prosumatorilor-de-a-si-instala-baterii-2388647.html
- https://www.digi24.ro/stiri/economie/energie/ce-rol-au-avut-prosumatorii-cu-baterii-de-stocare-in-alimentarea-retelei-nationale-joi-seara-dupa-oprirea-reactorului-2-3905735
- PPC MaxControl offer: https://www.ppcenergy.ro/wp-content/uploads/oferta-ppc-maxcontrol-rezidential.pdf
- BPV Grigorescu, legal framework: https://www.bpv-grigorescu.com/ro/noutati-si-publicatii/publicatii/modificari-ale-cadrului-legal-privind-prosumatorii
- profit.ro, PPC Romania CEO on Italy's model: https://www.profit.ro/povesti-cu-profit/energie/exclusiv-seful-ppc-romania-in-italia-statul-este-cel-care-ii-plateste-pe-prosumatori-pentru-energia-injectata-in-retele-nu-furnizorii-asa-ar-trebui-sa-fie-si-in-romania-22396703
- Italy GSE Ritiro Dedicato: https://www.enpal.com/it/fotovoltaico/ritiro-dedicato
- euenergy.live prices API (CC-BY-4.0): https://euenergy.live
