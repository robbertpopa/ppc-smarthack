# Likely jury questions

Draft answers for P3. Agree the ones about the model and the cloud with P2 and P1 before the demo.

**Is this PPC's real network?**
No. The station is synthetic (three feeders, 400 kVA by default) or a German SimBench benchmark, and the household profiles are Australian (Ausgrid). Every assumed parameter is listed in `src/grid/ASSUMPTIONS.md`.

**Why trust the labels?**
They come from a deterministic power flow (pandapower). We compared voltages with OpenDSS on the synthetic station at several operating points, and tests check that a limit above the safe share violates and a limit at it does not. A power flow that does not converge returns "not converged", never a number. Limits are the scenario parameters, not verified regulation.

**What does the guard add if the model is already cautious?**
It is independent of the model. It runs its own power flow with the plan's limits, so a model error cannot reach an inverter without being checked. With no PV and load forecast it refuses to pass the plan.

**What happens if the model is wrong or unsure?**
When the uncertainty is above the threshold the agent applies the fixed limit and queues the case for a person. The crew has a daily review budget, and the screen shows when it is exceeded.

**Could this control real inverters?**
Not in this prototype. It produces limits and a log. A real deployment needs an inverter gateway, operator access to settings and security review.

**Are variable limits allowed in Romania?**
We do not know. The fixed limit is the approved evacuation power in the connection approval. That is the first question for the operator and ANRE.

**What if the real grid is not balanced or inverters do not follow the limit?**
The twin is balanced three-phase with ideal inverters, and the guard does not check phase imbalance. Both are listed as limitations.

**Where do the numbers on the slides come from?**
From the evaluation output (`src.eval.run`), copied unchanged. The operator screen reads the same `summary.json` and shows nothing if it is missing.

**What would you do next with more time?**
Real station and meter data, a thermal model of the transformer, a fairness rule between houses, and a pilot behind an inverter gateway.
