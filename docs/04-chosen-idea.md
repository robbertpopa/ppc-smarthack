# Chosen idea: dynamic export limits for prosumers

## The problem in short
A prosumer can have 25 kW of panels, but the grid connection approval (ATR, "aviz tehnic de racordare") only allows them to send, for example, 9 kW into the grid. The limit is **fixed**, set by the operator through a connection study, based on grid capacity. When many prosumers on the same transformer station inject at once, voltage rises, inverters trip (above 253 V) and the transformer can be overloaded.

## The path of the current and where the limit appears
Panels (DC) → inverter (DC to AC; optional battery) → house (consumes first) → **meter (delimitation point)** → service connection → low-voltage (LV) line → transformer station (MV/LV) → medium-voltage (MV) line → substation.
- The 9 kW limit is measured at the meter and programmed into the inverter, but the number comes from the grid.
- The physical bottleneck can be at: the service connection (maximum current), the LV line (heating and voltage rise), the transformer station (capacity; one cited procedure limits LV injection to 30% of transformer power).
- Energy losses: inverter, battery, cable heating (largest in relative terms on LV), transformer. Separately there is curtailed production (limitation, tripping on overvoltage).
- 25 kW does not mean 25 kW per day: kW is power, kWh is energy.

## The idea
An **agent** that computes, in near real time, **how much each house may inject right now**, instead of a fixed limit. Assumption (to verify): the fixed limit is sized for the worst case, so the rest of the time it leaves energy unused.

### How it works
1. **Perception:** aggregate net load at the station (from meters), time of day, sun position, last safe limits, yesterday's values at the same hour.
2. **Model (trained by us):** predicts, one hour ahead, **the highest export limit that will be safe** (as a percentage of kWp), using quantile regression. We apply the cautious quantile (5%): errors do not cost the same, a limit that is too high causes violations, one that is too low wastes energy.
3. **Decision:** the limit per house. When the uncertainty interval is large, the agent **falls back to the fixed limit** and the case goes to a human.
4. **Action:** a limit command to the inverters, or an alert/order for the operator.
5. **Explanations:** the main factors behind each decision (e.g. "net load dropped sharply, so the margin is small").
6. **Ground truth (labels):** a pandapower power flow on a simulated grid computes, for every moment, the highest limit that respects voltage (≤1.05 or 1.10 pu) and the transformer (≤100%).

### Why a model and not just physics
Physics can only be computed when you know the load and the sun at that moment. The operator needs the limit **in advance**. The model learns to predict the outcome of the physics from what is known now.

## Results from the exploration prototype (simulation)
All figures come from simulation on SimBench grids (German), with real consumption and generation from Ausgrid (Sydney, 2010–2013), rescaled. The code is local and uncommitted (see README).

### The cost of a fixed limit (Ausgrid, no grid)
A fixed limit of 36% of kWp clips **20.6% of the exportable surplus** (9.3% of production); for homes with large generation relative to consumption, 25–30% of surplus.

### Grid sweep (how much safe export exists)
No fixed limit is right everywhere: safe and wasteful in grids with room, unsafe in dense grids. The safe limit varies between ~0.08 and 1.00 of kWp, depending on penetration, panel size, consumption and sun.

### Time series and model (one separate test year: 1 July 2012 – 30 June 2013)
Export vs fixed limit = 100:
| | A: transformer binds | B: voltage binds | B + reactive power |
|---|---|---|---|
| Model (5% quantile) | 131 | 105 | 128 |
| Model + fallback to fixed limit | 127 | 101 | 119 |
| Safe maximum (oracle) | 134 | 110 | 132 |
| Intervals over the limit, model + fallback | 1.9% | 1.7% | 2.0% |
| Intervals flagged for a human | 6.4% | 42.5% | 16.7% |

- The model clearly beats "last known limit" and "same hour yesterday" (e.g. 4.2% vs 20–23% violations in scenario B).
- **The gain depends on what binds:** large where the fixed limit is conservative relative to the real margin, small where the grid is tight all the time.
- Reactive-power control (inverters absorb reactive power as a function of voltage) reduces the oracle's curtailed production from 20.9% to 6.5% of production.

### City of 50,078 houses (507 neighbourhoods, ~20,000 with panels), one day
| Rule | Energy sent to grid | Energy lost | Neighbourhood-hours with problems |
|---|---|---|---|
| No limit | 1,325 MWh | 0 | 1,466 |
| Fixed limit 36% | 775 MWh | 550 MWh | 296 |
| "Smart" limit | 1,140 MWh | 185 MWh | 0 |

The "smart" limit here is the safe limit computed by physics for each neighbourhood, not the model itself. Even the fixed limit is not fully safe: at 13:00 it still has problems in 38 neighbourhoods.

## Limits and risks of the results (to state honestly in the presentation)
- **It is simulation**: German test grids, Australian data, not PPC's network.
- **Optimistic observability**: the model sees the "uncensored" net load; in a real system, curtailed production is not visible.
- Assumes the operator can compute the safe limit from the past (grid model + per-house data).
- **Ideal inverters**: reactive-power control assumes all inverters respond; in Romania this is not guaranteed, and prosumers dispute operator access to settings.
- On validation, violations were lower than on test (1.8% vs 3.5% without fallback): calibration did not hold perfectly. Validation covers only 3 months.
- The 100% transformer limit is conservative; a thermal model would tolerate short overloads.
- Uniform limit per house; **fairness** (who gets how much) is not tested. Balanced three-phase grids, no batteries.
- The 1.05 pu limit comes from a press summary; the exact rule at the connection point is not verified.
- We do not know whether ANRE rules and contracts allow variable limits per prosumer.

## The "3-in-1" variant: prosumers + consumers + transformers
The transformer station is the natural unit: below it are consumers and prosumers, and the transformer sees the sum. The agent would have three levers, in order of cost:
1. export limit for prosumers (cost: lost solar energy);
2. invitations to shift consumption for consumers (cost: incentive);
3. flagging the station for maintenance/reinforcement, ordered by risk.
Plus a thermal model of the transformer (with a physical baseline) for the loading limit. For 24 hours, the realistic core: net-load forecast + thermal model + export limits; the invitations would be a simple rule.

## Fit with the scoring grid
| Criterion | How we cover it |
|---|---|
| Idea and relevance (25) | Real problem in Romania, figures, Australian precedent, gap in PPC's AI portfolio |
| ML quality (25) | Quantile model on time-separated data, multiple baselines, error analysis, comparison with physics |
| Robustness (10) | Missing data, noise, uncertainty, fallback to the fixed limit |
| The agent (25) | Data → prediction → decision under constraints → action |
| Explainability (10) | Factors per decision, pessimistic scenarios |
| Demo and repository (5) | Interactive grid map, reproducible README |
