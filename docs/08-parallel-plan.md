# Parallel plan: three people, one agent

How we build the project in parallel during the 24 hours. Per-person instructions are in [tasks/](tasks/). The shared interfaces are in [09-contract.md](09-contract.md). The cloud design is in [10-cloud.md](10-cloud.md). The idea itself is in [04-chosen-idea.md](04-chosen-idea.md).

Clock times assume **T+0 = Saturday 18:00** and the end at **Sunday 12:00**. Shift them if we start later; the gates stay the same in relative hours.

## Architecture: one agent, four stages

```
Perceive            Estimate                 Decide                  Act
data + features --> ML models (P2)       --> planner (P1)        --> guard (P3)
(P2)                PV, load, safe cap       limits, abstain,        executor + log (P1)
                    quantiles                human queue             explanation (P1)
                          ^                       ^
                          |                       |
          labels, batteries, power flow (P3), transformer thermal (P1): the grid twin, deterministic
```

- **Not five agents.** One agent with four stages. The theme asks for perceive → estimate → decide → act, with every decision traceable to a model prediction.
- **The grid twin is not ML.** It is pandapower plus battery and transformer-thermal models. It produces the training labels and also acts as the guard that checks every plan before it is executed.
- **The LLM is optional** and only writes explanations from numbers. It never decides.

## Roles
Names are assigned by the team. Each role has its own instruction file.

| Person | Role | Owns | Instructions |
|---|---|---|---|
| **P1: ____** | Platform, cloud and agent core | `src/common/`, `src/agent/`, `infra/`, `Makefile`, `src/grid/thermal.py`; reviews everyone | [tasks/p1-platform-agent.md](tasks/p1-platform-agent.md) |
| **P2: ____** | ML and evaluation | `src/ml/`, `src/eval/` | [tasks/p2-ml.md](tasks/p2-ml.md) |
| **P3: ____** | Grid twin, then interface and presentation | `src/grid/` (except `thermal.py`), `src/ui/`, `README.md`, `pitch/` | [tasks/p3-grid-ui.md](tasks/p3-grid-ui.md) |

Why this split:
- **P2** takes the ML: its pitfalls (leakage from the future, calibration, abstention threshold) need judgement.
- **P3** starts with the grid twin, which has a clear recipe and tests, and moves to the interface once the physics is done. P1 reviews P3's work in the first five hours.
- **P1** holds the infrastructure, the integration and the agent logic, which are small in code but touch everything.

Everyone works in their own folder. A change to `src/common/` (the contract) is announced to the group first. **Cloud:** everything also runs in the cloud (demo, batch jobs, artifacts, audit log); P1 owns it. The cloud is a deployment, not a dependency: `make smoke` and `make eval` must work locally with no account.

## Timeline and gates
| Phase | Clock | P1: platform, cloud, agent | P2: ML | P3: grid → UI | Gate at the end |
|---|---|---|---|---|---|
| **0** T+0–1 | 18:00–19:00 | Scaffold, `.gitignore`, contract, mocks, Docker, Terraform for Azure, CI | Download data, check formats, list features | Install pandapower/SimBench, pick the grid | **G0:** contract and mocks merged, everyone can run `make smoke` |
| **1** T+1–5 | 19:00–23:00 | Docker, CI, mock-based app deployed, API and planner on mocks, review of P3 | Baselines, first quantile model (on mocks until labels arrive) | `power_flow`, `safe_share`, first labels by T+3 | **G1:** end-to-end demo on real labels, however ugly |
| **2** T+5–9 | 23:00–03:00 | Label job in the cloud, auto-deploy, guard integration, abstain queue, approvals, action log | Abstention rule, PV and load forecasts | `guard`, batteries (SoC), tests | **G2:** agent acts, guard blocks bad plans |
| **3** T+9–13 | 03:00–07:00 | Training and evaluation in the cloud, kill switch, transformer thermal model | `eval/run.py`, robustness (missing, noise, censored), explanations | Operator screen, comparison panel | **G3:** evaluation table reproducible with one command |
| **4** T+13–17 | 07:00–11:00 | Freeze, HTTPS, health check, runbook, backup video | Error analysis, final numbers | README, slides, demo script, UI polish | **G4:** feature freeze at T+13, code freeze at T+17 |
| **5** T+17–18 | 11:00–12:00 | Rehearse | Rehearse | Rehearse | Ready to present |

Sleep in shifts of about 2 hours, always at least two people awake.

**Hard rule:** at G1 the demo must run end to end. If it does not, everything else is cut until it does.

## Cloud track (P1), checked at the same gates
| Gate | Cloud milestone |
|---|---|
| G0 | Dockerfile, compose, Terraform for Azure and CI in the repo; budget alert |
| G1 | CI (lint, tests, smoke); the mock-based app deployed at a URL; datasets on the file share |
| G2 | Batch job runs label generation in the cloud; auto-deploy on merge to `main` |
| G3 | Training and the evaluation table run in the cloud and match the local run |
| G4 | Frozen deployed version, health check, backup video recorded on the cloud URL and locally |

## Dependencies (who waits for whom)
- **Nobody waits for anybody in phase 0–1**: everyone works against the mocks in the contract.
- P2 needs P3's labels from T+3. Until then P2 trains on the mock labels or on a first quick label file from P3 (even 10 days of data is enough to start).
- P1 needs P3's `guard` from phase 2. Before that, P1 uses a stub guard that always passes and logs a warning.
- P3's UI needs P1's API from phase 3. Before that, P3 builds against the mocks.
- **If there are no labels at T+3:** P1 takes over `safe_share` and P3 moves to batteries and the guard.

## Review rules
- P1 reviews every merge of P3 in phases 1–2 (the physics is on the critical path).
- A different person reviews each merge request than the one who wrote it; coding assistants also review each other's work where possible.
- Keep merge requests small (under about 300 changed lines) so review takes minutes.

## Sync points (5 minutes each, standing up)
T+1 (contract), T+3 (labels file ready, baseline numbers), T+5 (G1), T+9 (G2), T+13 (freeze), T+17 (code freeze). Between syncs, post in the group chat if blocked for more than 20 minutes.

## Git rules
- `main` always runs (`make smoke` passes).
- One branch per task, named `<area>/<thing>` (for example `ml/quantile-model`). Merge to `main` about every 90 minutes.
- Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`), no co-author trailers, English only.
- Commit continuously through the 24 hours (hackathon rule). Do not commit data, `.venv`, or large files.
- No secrets, keys or cloud credentials in the repository, ever. Use environment variables.
- Do not copy the local exploration scripts into the repository; rewrite what we need. State in the README what was explored beforehand (see [05](05-data-and-sources.md)).

## Shared evaluation (what the final table contains)
All numbers are computed by one script (`src/eval/run.py`) on a separate test period.
- Export versus the fixed limit (fixed = 100) for: model, model with fallback, and the safe maximum (oracle).
- Share of intervals over the safe limit.
- Share of intervals flagged "not sure" and the risk-coverage curve.
- Baselines: fixed limit, last known limit, same hour yesterday.
- Robustness: 20% missing readings, 30% noise, censored production.
- Scenarios: transformer binds, voltage binds, voltage binds with reactive-power control.

## What we cut first, if we fall behind
1. The Bucharest map and elaborate UI.
2. Reactive-power (Volt/VAR) scenario and cloud extras (infrastructure as code, scheduled jobs).
3. The censored-data test.
4. The thermal model (kept only if the core slice already works).
Everything up to G1 is never cut.

## Open questions to settle in phase 0
- Who takes P1, P2 and P3?
- Which dataset is the primary one if PPC provides real data? (Ask the mentors.)
- Is code prepared before the start allowed? (Ask the organisers; the answer decides how much of the exploration we may reuse.)
- Cloud: who owns the account, what is the budget, are credits provided, may any real data leave the premises or the EU? (See [10-cloud.md](10-cloud.md).)
- Who presents? Proposed: P3 writes the slides, P1 runs the demo, P2 answers the ML questions, all rehearse.
