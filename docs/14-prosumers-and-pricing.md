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

## 5. What to charge, and how (proposal)

Principle: **nobody is worse off than today; the gain goes to those who create the value.** The operator cannot dispatch prosumer batteries (section 6), so every part is opt-in and based on consent and prices.

**Who it is for.** Prosumers with a battery and a smart meter (SMI), about a third of residential prosumers and growing. Others stay on the regulated terms, unchanged. If the storage obligation turns out to be law, the addressable base grows.

**What PPC pays for injected energy (settled monthly, shown as separate lines on the invoice, as PPC's offers already do):**

1. **Hourly price.** Each exported kWh at the PZU price of its interval (15 minutes where the meter allows) minus the fee below, never below the floor.
2. **No-regret guarantee.** At month end the prosumer receives at least `exported kWh × monthly weighted-average PZU`, the regulated price. For 200–400 kW this is probably a legal minimum anyway. If the hourly total is higher, the prosumer gets the hourly total.
3. **Savings share (bonus).** A share (start at 50%) of the imbalance cost PPC measurably saved, paid pro rata to exported kWh of participants who share their data.
4. **Floor** (minimum hourly price): start at 0, so the prosumer is never charged in negative-price hours. A positive floor is a PPC cost and only goes in if the savings fund it.

**What the prosumer pays PPC.**

1. **Aggregator fee** per exported MWh, covering admin and PPC's remaining imbalance risk. Two published levels: **lower if the prosumer shares data and a day-ahead export schedule, higher if not**, because PPC's imbalance is larger without it. The level is not guessed: the evaluation (spec phase 2) computes the break-even fee, and the sensitivity grid covers 10–40 EUR/MWh.
2. **Nothing else:** no subscription, no access fee, no penalty for not taking part. A charge for deviating from a committed schedule (the imbalance spread times the deviation) is a later option.

**What PPC does not do.** It does not control inverters or batteries and does not change their software. It reads smart-meter data and, with consent, battery or inverter data, and it publishes the next day's prices and a recommended export window as information. The prosumer's own system, or the prosumer, decides. This answers the concerns in section 6.

**Why this works for PPC.**
- Per MWh, PPC pays the regulated price in the worst case (so no new loss) and the market value in the best case.
- On shifted energy it earns the fee: about +9 EUR/MWh in the table.
- Its real gain is the imbalance saving and the evening energy it does not have to buy.

**What it does not fix.** The structural overpayment of about 49 EUR/MWh on unshifted midday injection (70 in sunny months) stays, because those prosumers keep the regulated price. Only regulation or batteries can change that. The pitch should say so.

**Illustration for one battery (upper bound).** A 10 kWh battery with 9 kWh of usable range shifting 9 kWh a day earns about 79 EUR/MWh more than hourly export, roughly 0.7 EUR per day, about 180–260 EUR a year. Real value is lower: a household battery is usually worth more covering the home's own evening load, and the shifted export is only the surplus.

**Runway.** In 2030 quantity compensation ends and everyone sells at wholesale. Hourly settlement then becomes the default basis, and a product like this is ready.

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
