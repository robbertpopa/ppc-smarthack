# PPC Smarthack XI 2026

Team preparation for the PPC challenge at Smarthack XI: **"24h to Power PPC: AI in energy, from data to action"**.

## Project status
Hackathon prototype. Working today: the agent API with a review queue, kill switch and action log (P1); the grid twin, the guard and the operator screen (P3), all running on **mock forecasts**. Not yet connected: the trained model (P2), the evaluation table, and the shared `src.agent.api` still uses the stub guard (the grid guard is wired in `src.grid.demo_api`).

Everything shown is simulated. The grid is synthetic (or a German SimBench benchmark), the profiles are Australian (Ausgrid), and nothing controls real inverters.

## Run it

Python 3.12. Install with `python -m pip install -e ".[sim,grid-tools,dev]"`.

| What | Command |
|---|---|
| Tests, lint, smoke | `python -m pytest`, `python -m ruff check src tests`, `python -m src.smoke` |
| Agent API with the grid guard | `python -m uvicorn src.grid.demo_api:app --port 8000` |
| Operator screen | `API_URL=http://127.0.0.1:8000 python -m uvicorn src.ui.app:app --port 8001`, then open http://127.0.0.1:8001 |
| Evaluation table | `python -m src.eval.run` (P2's script: **not in the repository yet**) |

On Windows PowerShell set variables first: `$env:API_URL = "http://127.0.0.1:8000"`.

Environment: `API_URL` is the agent API the screen calls, `ARTIFACT_URI` and `EVAL_RUN_ID` (default `local`) tell the screen where to read `eval/<run id>/summary.json`, `LOG_URI` is the action log, and `DEMO_TOKEN` is required by the API for writes when set (type it in the screen's token field; it is not stored). See [docs/10-cloud.md](docs/10-cloud.md).

### The operator screen
Pick a day and a half-hour slot. The screen shows the station state (voltage, transformer and line load), the forecast band for the safe export share against the fixed limit, the plan with the limit per house (green: model limit and guard passed, yellow: fixed fallback or contract cap, red: blocked by the guard), the "not sure" queue with approve and reject, the kill switch and the action log. The comparison panel (fixed limit versus ours) reads `summary.json` from the evaluation output; with no file it shows no numbers. A `mock: true` summary is labelled "MOCK, NOT A RESULT". The older CSV viewer for the 210-house simulation is at `/simulation`.

### Grid twin and labels
`python -m src.grid.compare_station` compares pandapower and OpenDSS voltages on the synthetic station. To generate a provisional label file:

```sh
python -m src.grid.labels --source "PATH_TO/Solar home 2012-2013.csv" --output labels.parquet --days 1 --workers 4
```

The input data must be obtained separately; do not commit it. `--workers` runs power flows in parallel and gives the same file as one worker. Add `--pv-scale 4` for a synthetic stress scenario, not measured generation. The label schema and battery sign convention still require agreement with P2 and P1, and one day of labels is not enough for model training. `python -m src.grid.audit_labels --source PATH_TO_AUSGRID_CSV --labels PATH_TO_LABELS` audits sampled boundaries; null labels must not be treated as zero. `python -m src.grid.compare_recorded PATH_TO/simulare-case-detalii.csv` compares voltage against OpenDSS at five recorded intervals.

The default twin is a synthetic three-feeder station. `build_grid({'topology': 'simbench', 'houses': [...]})` gives a separate SimBench benchmark (its 150-degree transformer phase shift needs DC initialization; this is regression tested). Limitations and every assumed parameter are in [src/grid/ASSUMPTIONS.md](src/grid/ASSUMPTIONS.md).

### What the guard checks
`src.grid.agent_guard.make_grid_guard` runs its own power flow on the whole station with the plan's limits and rejects the plan on voltage, line or transformer overload, battery bounds or a limit above the contract cap. It runs two worst-case cases built from the forecast, export (PV p90, load p10) and import (PV p10, load p90), split across houses by an assumed rule, and the plan must pass both. With no PV and load forecast it rejects the plan as unverifiable instead of passing it. It is a simulation check, not a certified protection system.

### Limitations
Balanced three-phase grid, active power only, ideal inverters, a 1.05 pu limit taken from a press summary (the exact rule is unverified), a conservative 100% transformer limit, and no fairness analysis between houses. Figures from the exploration phase are not reproduced by this repository yet; use only what `src.eval.run` produces once it exists.

## Chosen direction
**Dynamic export limits for prosumers, at the MV/LV transformer-station level.** An agent computes how much each house may export right now, instead of using the fixed limit from the grid connection approval. A team-trained ML model (quantile regression) predicts the highest safe limit one hour ahead; when it is unsure, the agent falls back to the fixed limit and sends the case to a human.

Why: the problem is real in Romania (overvoltage, 360,000+ prosumers), the solution exists in Australia, and it does not appear in PPC's AI portfolio. Extended variant: "3-in-1" (prosumers + consumers + transformers).

The figures from our exploration come from simulation (German SimBench grids, Australian Ausgrid data), not from PPC's network.

## Documentation
| File | Content |
|---|---|
| [docs/01-theme-and-criteria.md](docs/01-theme-and-criteria.md) | Theme, mandatory requirements, scoring |
| [docs/02-ppc-in-numbers.md](docs/02-ppc-in-numbers.md) | What we know about PPC, with confidence levels |
| [docs/04-chosen-idea.md](docs/04-chosen-idea.md) | Concept, architecture, simulation results, limits |
| [docs/05-data-and-sources.md](docs/05-data-and-sources.md) | Datasets, validation, pitfalls |
| [docs/06-motivation-and-problems.md](docs/06-motivation-and-problems.md) | Real problems: Romania, Poland, Australia |
| [docs/07-next-steps.md](docs/07-next-steps.md) | Steps before and during the hackathon, risks |
| [docs/08-parallel-plan.md](docs/08-parallel-plan.md) | Parallel plan for three people, gates, git rules |
| [docs/09-contract.md](docs/09-contract.md) | Shared interfaces and mock examples |
| [docs/10-cloud.md](docs/10-cloud.md) | Docker, Terraform and Azure: services, CI/CD, runbook, cost and security |
| [docs/11-commit-plan.md](docs/11-commit-plan.md) | Commit and merge plan: who commits what, on which branch, in which order |
| [docs/tasks/](docs/tasks/) | Instructions per person: [P1 (platform, cloud, agent)](docs/tasks/p1-platform-agent.md), [P2 (ML)](docs/tasks/p2-ml.md) with [per-branch briefs](docs/tasks/p2/README.md), [P3 (grid, UI)](docs/tasks/p3-grid-ui.md), [P4 (neighbourhood map)](docs/tasks/p4-map.md) |

## Conventions
- Branch: `main`.
- Conventional commit messages: `docs: ...`, `feat: ...`, `fix: ...`, `chore: ...`.
- Everything in the repository is written in English.
- Exploration data and code stay local (ignored via `.gitignore`) until the hackathon starts.
