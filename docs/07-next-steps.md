# Next steps

## Working rules for now
- **Only documentation in the repository.** The exploration code stays local and uncommitted; code commits start when the hackathon starts (the "commits during the 24 hours" rule).
- Conventional commit messages (`docs:`, `feat:`, `fix:`, `chore:`), directly on `main`, no other attribution.
- Everything in the repository is written in English.

## Before the hackathon (no code)
1. **Ask the organisers:** is code/a prototype made beforehand allowed? How much preparation (research, downloaded data, explorations) is accepted? If not, we start from scratch in 24h and use the exploration only as a plan.
2. **Verify the uncertain assumptions:**
   - ANRE rules on variable evacuation limits and who may set them;
   - whether inverters in Romania accept operator commands/limitation and reactive power (Volt/VAR);
   - the exact voltage rule at the connection point (1.05 pu comes from a press summary);
   - what the ATR says about approved power and conditions for revision.
3. **Prepare the materials:** a 3-minute story for the jury, the "path of the current" diagram, slides with sourced figures, the list of limitations (see [04](04-chosen-idea.md)).
4. **Prepare a fallback plan:** pick an alternative idea we can start if PPC has no data or interest in LV grids.
5. Assign roles: data/simulation, model, agent and decision, demo and presentation.

## In the first hour (questions for PPC)
- Do we have **ATR/approved-power data** for prosumers, or at least aggregated per station?
- Is there a **meter → transformer station → feeder** mapping and voltage data at the meter?
- What **transformer data** exists (rated power, loading, temperature, age)?
- What is known about **curtailed production** (limitations, inverter disconnections)?
- What is the **current process** for setting limits and who decides?
- What **actions** can a real operator take (command to inverter, order to a crew, alert)?
- How many **cases can a crew check per day** (the constraint for the decision layer)?

## Indicative plan for the 24 hours
| Interval | What we do |
|---|---|
| 0–2h | Final choice, questions to PPC, repository setup, pipeline skeleton |
| 2–6h | Data: profiles (Ausgrid or PPC data), grid, power flow, labels |
| 6–12h | Model: baselines, quantile, time validation, error analysis |
| 12–17h | Agent: decision, fallback to fixed limit, "I am not sure", actions, explanations |
| 17–21h | Robustness (missing data, noise), reproducibility, README |
| 21–24h | Demo (interactive map), presentation, rehearsal, clean-up |

Regular commits throughout.

## Risks
| Risk | Response |
|---|---|
| PPC has no LV data | Public and synthetic data with sources; say openly what is simulated |
| The result depends on the chosen grid | Present two or three scenarios and the condition under which the gain disappears |
| The model does not beat simple physics on real data | Present it as "forecast + safety" with error analysis; compare against baselines |
| The jury asks about legality | Prepare the answer: the ATR limit stays as a ceiling; the agent only uses it dynamically and safely; verified with ANRE |
| Too much to do in 24h | Minimal core: forecast + limit + fallback + explanations; the rest is optional |

## To improve after the core (if time allows)
- Per-grid training and transfer between grids.
- Realistic observability (load censored by limits).
- Thermal model of the transformer (dynamic loading limits).
- Fairness between prosumers (who gets how much) and batteries.
- Evaluation over a full year with more months of validation.

## Pre-presentation checklist
- [ ] Sources for every figure
- [ ] The evaluation script reproduces the figures on the slides
- [ ] The model runs in our code, no external API
- [ ] The agent executes actions, not just displays
- [ ] The "I am not sure" case is visible in the demo
- [ ] Limitations are stated openly
- [ ] Public repository, commits throughout the 24h
