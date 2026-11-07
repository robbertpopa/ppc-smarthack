# Why: motivation and real problems

Confidence level: **(official)** = ANRE, operators, authorities; **(press)** = articles; **(study)** = papers; **(interest)** = organisations with a commercial interest; **(unverified)**.

## Romania: figures
- Prosumers: **332,684 on 30 April 2026**, 3,789 MW, 101,243 with batteries (official/press). On 30 June 2026: 359,378 and 127,084 with batteries (unverified).
- Prosumer capacity exceeds the dispatchable solar parks (~3,300 MW) (press).

## Observed problems in Romania
- **Overvoltage at prosumers.** Example: Delgaz Grid, Botoșani, 253.40 V measured (above the inverter trip threshold) (press). Effect: inverters trip and production is lost.
- **ANRE draft order** on prosumers and power limitation (press; the text must be reviewed directly at the official source).
- **APCE:** the prosumer association asks for clear rules and transparency on limits (interest).
- **AFEER study** on prosumers: an association of suppliers that states AI-assisted drafting; **we treat its figures with caution** (interest).
- **George Buhnici** (prosumer and public voice): has 25 kW of panels and is allowed to send 9 kW; considers the limit an artificial bottleneck. Clarified: the limit is the approved evacuation power set in the ATR and comes from grid capacity, not from how much he produces (press).
- **Billing and ATR:** delays in approvals, compensation, disputes about settlement rules (press).

## Poland (closest precedent)
- **1,612,450 prosumers at the end of 2025** (official/press).
- A study in *Energies* (2025): **614 overvoltage incidents in 78 days** in one network, and a **2.6% annual loss** for one house (study).
- Operators started limiting and tripping inverters, with negative reactions from prosumers.

## Australia (most advanced solution)
- **Backstop** (emergency command) for panels and **flexible exports** (SA Power Networks, Energex): limits that vary with grid capacity, from 1.5 kW (static) to up to 10 kW (in good hours) (official/press).
- The solution is implemented by operators; **we found no** replication at hackathons.

## Source quality
| Source | Type | How we treat it |
|---|---|---|
| ANRE, operators, legal acts | official | Read the text, not the summary |
| Energy press (Profit, Economica, Energy-Report, etc.) | press | OK for figures with citation; verify against primary sources |
| AFEER | interest (suppliers) | Figures with caution; do not argue on them alone |
| APCE | interest (prosumers) | Useful for problems, not for aggregate figures |
| *Energies* 2025 study (Poland) | peer-reviewed study | Good for order of magnitude |
| Vendor figures (Autobidder etc.) | interest | Illustration only |
| Search summaries with no source seen | unverified | Not used in the presentation |

## What supports the idea and what does not
**Supports:** the problem is real and growing; fixed limits are conservative; there is operational precedent (Australia) and public data to simulate it.
**Does not prove:** that PPC/Rețele Electrice actually lose money from fixed limits; that the rules allow variable limits; that the model works on their network. These must be asked/verified (see [07](07-next-steps.md)).
