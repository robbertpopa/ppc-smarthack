# Slides outline

One slide per heading. Each number states its source and confidence level (see [docs/06](../docs/06-motivation-and-problems.md)). Result numbers are **copied from the evaluation output** (`eval/<run-id>/table.md` and `summary.json`), never typed from memory. Anything marked FILL waits for that output.

## 1. The problem
- Romania had 332,684 prosumers on 30 April 2026 (official/press); more panels than the dispatchable solar parks.
- Overvoltage at prosumers: 253.40 V measured in Botoșani, above the inverter trip level (press). Inverters trip and production is lost.
- A fixed limit is set once in the connection approval (for example 9 kW for a 25 kW installation). It comes from grid capacity, not from the sun or the consumption of the day.
- Poland: 614 overvoltage incidents in 78 days in one network, 2.6% annual loss for one house (peer-reviewed study, order of magnitude).

## 2. The idea
An agent that works out how much each house may export **right now**, one hour ahead, and falls back to the fixed limit when it is unsure. Australia already does flexible exports (SA Power Networks, Energex, from 1.5 kW static to up to 10 kW), run by the operators; we found no replication at hackathons.

## 3. How it works
Data, forecast (quantile model, cautious 5% quantile), decision with abstention, guard, action, log. Draw it as one line:
`forecast -> plan -> guard (own power flow) -> human if unsure -> execute -> action log`.
Why a model and not only physics: physics needs the load and sun of that moment, the operator needs the limit in advance.

## 4. The safety layer
- The guard re-computes the whole station with the plan's limits and rejects on voltage, line or transformer overload, battery bounds, or a limit above the contract cap.
- No forecast, no verification, no pass.
- Kill switch, append-only action log, review budget for the crew.
- It is a simulation check, not a certified protection system.

## 5. Live demo
Three scenes from [demo-script.md](demo-script.md): normal day, uncertainty rises, a person decides. Bonus: the guard blocks a plan.

## 6. Results (FILL from the evaluation output)
Table for each scenario: export index (fixed = 100), violation rate, share sent to a human, flagged cases per day, for fixed limit, last known, same hour yesterday, model (q05), model + fallback and the safe maximum. Also the risk-coverage curve and the calibration drift between validation and test. State the test period and the label source. If `summary.json` has `mock: true`, this slide must not be shown.

## 7. What we do not know
- It is a simulation: synthetic or German grid, Australian profiles, not PPC's network.
- Curtailed production is invisible in a real system; our model sees the uncensored load.
- Reactive-power control assumes every inverter responds.
- The 1.05 pu limit comes from a press summary; the exact connection-point rule is unverified.
- We do not know whether ANRE rules and contracts allow variable limits per prosumer.
- Balanced three-phase only, no fairness analysis between houses, 100% transformer limit is conservative.

## 8. Next steps
Ask the operator for real station and meter data; verify the rules with ANRE; thermal model of the transformer; per-house fairness rule; connect to a real inverter gateway in a pilot; extend to consumers and transformers (the "3-in-1" variant in [docs/04](../docs/04-chosen-idea.md)).
