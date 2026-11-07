# PPC Smarthack XI 2026

Team preparation for the PPC challenge at Smarthack XI: **"24h to Power PPC: AI in energy, from data to action"**.

## Project status
Hackathon prototype in progress. The repository contains documentation and a local grid-twin prototype; integration with the agent and ML is pending.

## Local P3 prototype

Use Python 3.12 as required by the project. Install the project simulation and development dependencies with `python -m pip install -e ".[sim,dev]"`, then `python -m pip install -r requirements-grid.txt` for the additional local comparison and Parquet tools. Run `python -m pytest` for the project tests and `python -m src.grid.compare_station` to compare pandapower and OpenDSS voltages on the synthetic station.

To generate a provisional one-day label file, use:

```sh
python -m src.grid.labels --source "PATH_TO/Solar home 2012-2013.csv" --output labels.parquet --days 1
```

The input data must be obtained separately; do not commit it. Add `--pv-scale 4` for a synthetic stress scenario, not measured generation. The label schema and battery sign convention still require agreement with P2 and P1. The local prototype UI in `src/ui/index.html` reads `simulare-case-detalii.csv` from the local simulation; it is not connected to the agent API. See `src/grid/ASSUMPTIONS.md` for limitations. The initial one-day labels are not sufficient for model training.

The default twin uses a synthetic three-feeder station. `build_grid({'topology': 'simbench', 'houses': [...]})` provides a separate SimBench benchmark, with households allocated to existing load buses. The benchmark transformer's phase shift requires DC initialization; this is regression tested. Use `python -m src.grid.compare_recorded PATH_TO/simulare-case-detalii.csv` to compare voltage against OpenDSS at five recorded profile intervals on the synthetic feeder. Use `python -m src.grid.audit_labels --source PATH_TO_AUSGRID_CSV --labels PATH_TO_LABELS` to audit sampled boundaries; null labels must not be treated as zero.

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
| [docs/tasks/](docs/tasks/) | Instructions per person: [P1 (platform, cloud, agent)](docs/tasks/p1-platform-agent.md), [P2 (ML)](docs/tasks/p2-ml.md) with [per-branch briefs](docs/tasks/p2/README.md), [P3 (grid, UI)](docs/tasks/p3-grid-ui.md) |

## Conventions
- Branch: `main`.
- Conventional commit messages: `docs: ...`, `feat: ...`, `fix: ...`, `chore: ...`.
- Everything in the repository is written in English.
- Exploration data and code stay local (ignored via `.gitignore`) until the hackathon starts.
