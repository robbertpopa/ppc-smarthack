# PPC Smarthack XI 2026

Team preparation for the PPC challenge at Smarthack XI: **"24h to Power PPC: AI in energy, from data to action"**.

## Project status
Preparation phase. This repository contains **documentation only**. Code is written and committed during the 24 hours of the hackathon, as the rules require.

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

## Conventions
- Branch: `main`.
- Conventional commit messages: `docs: ...`, `feat: ...`, `fix: ...`, `chore: ...`.
- Everything in the repository is written in English.
- Exploration data and code stay local (ignored via `.gitignore`) until the hackathon starts.
