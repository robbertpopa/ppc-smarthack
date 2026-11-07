# P3: grid twin, then interface and presentation

**Owns:** `src/grid/` (except `thermal.py`, which P1 owns), `src/ui/`, `README.md`, `pitch/`. Read first: [../08-parallel-plan.md](../08-parallel-plan.md), [../09-contract.md](../09-contract.md), [../04-chosen-idea.md](../04-chosen-idea.md).

## Goal
Part 1 (hours 0–9): build a deterministic digital twin of one low-voltage station (pandapower on a SimBench grid) that produces the **ground-truth labels** for P2's model, simulates batteries, and acts as the **guard** that checks every plan before it is executed. It is not ML; it must be correct. P1 reviews your merges in this phase.

Part 2 (hours 9–18): build the operator screen, the README and the slides, using the numbers produced by the evaluation script.

## What you deliver
| By gate | Deliverable |
|---|---|
| G0 | pandapower and SimBench installed, grid chosen, `build_grid` returning a grid |
| G1 | `power_flow` and `safe_share` working; a first label file for P2 by T+3 (even 10 days) |
| G2 | `guard` and batteries (state of charge), with tests |
| G3 | Operator screen with the comparison panel |
| G4 | README that reproduces everything, slides, demo script |

## Tasks

### Phase 0 (T+0–1)
- Pin versions that worked in exploration: pandapower 3.5.6, simbench 1.6.3, numba 0.68.1 (Python 3.12).
- Pick the SimBench LV grid. In exploration: `1-LV-rural3--0-sw` (25 kWp per prosumer, 30% penetration, 400 kVA transformer) as the transformer-binding case, and a 1 MVA variant with limit 1.05 pu as the voltage-binding case.
- Agree the label file format with P2.

### Phase 1 (T+1–5): the physics core
- `build_grid(config)`: loads, PV sgens per prosumer, per-house kWp, penetration, seed.
- `power_flow(grid, injections) -> grid_state` (contract object 2). Inputs per house: load kW, PV kW, export limit.
- `safe_share(grid, injections)`: the highest share φ in [0, 1] of each house's kWp such that voltage ≤ limit (1.10 pu, or 1.05 pu in the voltage-binding scenario), lines ≤ 100% and transformer ≤ 100%. Use bisection with a **coarse scan first**, because feasibility is not always monotone (less PV can overload the transformer on import).
- Label generator: run it over the Ausgrid profiles that P2 provides, every daylight half-hour, write `labels.parquet`. Parallelise with `multiprocessing`; one power flow takes milliseconds.
- Sanity check against a direct power flow at φ and φ+ε on a random sample (exploration agreement: 250/250 and 248/250).
- **Tests P1 will ask for before merging** (they are also your acceptance criteria):
  1. A limit above the safe share produces a violation.
  2. A limit at the safe share does not.
  3. Non-convergence returns `converged: false`, never a fake number.
  4. Labels are identical with a fixed seed.

### Phase 2 (T+5–9)
- **Batteries:** `soc_next = soc + dt·(η·charge − discharge/η)` with η = √(roundtrip efficiency). Assumed parameters, to be declared: 10 kWh, 5 kW charge and discharge, roundtrip 0.9, SoC between 1 and 10 kWh. Test: SoC never leaves its bounds.
- **`guard(grid, plan, injections) -> {passed, violations}`:** its own power flow on the full station with the plan's limits. Checks voltage, line loading, transformer loading, battery SoC bounds, and that nobody exports above their limit. It must be able to **reject** a plan and say why; test it with a deliberately bad plan and a good one.
- Optional scenario: reactive-power droop (Volt/VAR, V1 = 1.02, V2 = 1.05 pu, cosφ 0.9). Declared assumption: all inverters respond. Cut first if short of time.
- Write `src/grid/ASSUMPTIONS.md`: balanced three-phase, no unbalance, German grid with Australian profiles, assumed battery parameters.

### Phase 3 (T+9–13): the operator screen
- Streamlit or a small web page against P1's API (mocks until it is ready); `API_URL` from the environment, nothing hard-coded to localhost.
- Screens: one station, time slider, limits per house, status colours (green, yellow, red), station state (voltage, transformer loading), the forecast band, the plan, the "not sure" queue with approve and reject buttons, the action log.
- **Comparison panel:** fixed limit versus ours (export, violations, flagged cases), numbers read from the evaluation output, not typed by hand.
- The screen must show clearly what is simulated.
- Optional, if time remains: a map of a real Bucharest neighbourhood with building outlines from OpenStreetMap (download once; send a `User-Agent` header to Overpass). The grid behind it is synthetic and the screen must say so.

### Phase 4 (T+13–17)
- **README:** how to run, how to reproduce the evaluation table (`python -m src.eval.run`), what was prepared before the hackathon, data sources, limitations, link to the docs.
- **Slides:** problem (numbers and sources from [06](../06-motivation-and-problems.md)), idea, how it works, results (copied from the evaluation output), what we do not know, next steps. Prepare short answers to likely jury questions with P1 and P2.
- Demo script with P1: three scenes (normal day, cloud passing, unsure case handled by a human).
- UI polish, then rehearse.

## Interfaces
- **You consume:** P2's per-house profiles (generation, consumption), P1's API, the contract.
- **You provide:** `labels.parquet` to P2, `power_flow` and `guard` to P1, the screen, README and slides to the team.

## Definition of done
- `make smoke` runs a power flow and a safe-share search in a few seconds.
- The four tests above pass, and the guard blocks a bad plan and passes a good one.
- Every assumed parameter is in `ASSUMPTIONS.md`.
- Everything on screen and on slides comes from the code or the evaluation script.

## Pitfalls
- Non-convergence: return `converged: false`, never a number.
- 1.05 pu at the connection point comes from a press summary; the exact rule is unverified. Make the limit a parameter and say so in the presentation.
- A 100% transformer limit is conservative; the thermal model (P1) is what makes it dynamic.
- Do not copy the local exploration scripts into the repository; rewrite them cleanly.
- If you are stuck for more than 20 minutes, post in the group. If there are no labels at T+3, P1 takes over `safe_share` and you move to batteries and the guard.

## If you fall behind
Keep: `power_flow`, `safe_share`, `guard`, one operator screen, README. Cut first: Volt/VAR, the map, polished styling, extra scenarios.
