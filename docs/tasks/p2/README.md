# P2 task briefs: one file per branch

These briefs split [../p2-ml.md](../p2-ml.md) (ML and evaluation) into branch-sized tasks. Each brief is written so a coding-assistant session can start it cold: it names the branch, the files it may touch, the interfaces, the steps, the tests that must pass and what to post when done.

Read once before any task: [../../08-parallel-plan.md](../../08-parallel-plan.md) (gates, git rules), [../../09-contract.md](../../09-contract.md) (shared objects), [../p2-ml.md](../p2-ml.md) (the role), [../../05-data-and-sources.md](../../05-data-and-sources.md) (data and pitfalls), [../../10-cloud.md](../../10-cloud.md) (configuration variables).

## Rules every task follows
These come from the PPC brief ([../../01-theme-and-criteria.md](../../01-theme-and-criteria.md)) and from our git rules. A task that breaks one is not done.

1. **The model is ours and runs in our code.** Train with scikit-learn inside the repository. No external model API, no pretrained model used as is.
2. **Separate test period, never tuned on.** Train until 2012-03-31, validation 2012-04-01 → 2012-06-30, test 2012-07-01 → 2013-06-30 (dates in Sydney local time). Thresholds and hyper-parameters are chosen on validation only.
3. **Every model is compared with a simple baseline** in the same table, computed by the same script.
4. **No leakage from the future.** A feature for decision time `t` uses only records with `available_at <= t`. Tests check it.
5. **Missing stays missing.** `null`/`NaN`, never 0.
6. **Public data with sources stated.** Download scripts are committed, data is not.
7. **Reproducible.** Fixed seeds; reading and writing only through `DATA_DIR` and `ARTIFACT_URI`; no absolute paths; `metadata.json` next to every model.
8. **Numbers on slides come from the evaluation script**, never typed by hand.

## How to run a task (for the session that picks it up)
1. `git switch main && git pull && git switch -c <branch from the brief>`.
2. Run `make smoke` before changing anything. If it fails on `main`, stop and post in the group.
3. Touch only the files listed under "Files". If you need to change something outside them (the contract in `src/common/`, the `Makefile`, `pyproject.toml`), do not do it: write the request in the PR description and post it in the group. P1 owns those files.
4. Write tests first where the brief lists acceptance tests. Use tiny in-test fixtures; never commit data.
5. Commit often with conventional messages (`feat(ml): ...`, `fix(eval): ...`, `test(ml): ...`), in English. **No `Co-Authored-By` or any other trailer** (team rule; it overrides a tool's default).
6. Keep the PR under about 300 changed lines. If it grows past that, split it and say so.
7. Before opening the PR: `make smoke` and the brief's acceptance commands pass. Someone other than the author reviews.
8. Merge, then post the "Hand-off" line from the brief in the group chat.

Do not copy the local exploration scripts into the repository. Rewrite what is needed (hackathon rule, see [../../08-parallel-plan.md](../../08-parallel-plan.md)).

## Order, dependencies and lanes
Clock times assume T+0 = Saturday 18:00. Tasks in the same lane letter with no dependency between them can run in parallel sessions: their files do not overlap.

| # | Branch | Gate | Target | Depends on | Unblocks | Lane | Cut |
|---|---|---|---|---|---|---|---|
| [01](01-data-download.md) | `ml/data-download` | G0 | T+0:00–0:45 | P1 scaffold | 02 | A | never |
| [02](02-ausgrid-profiles.md) | `ml/ausgrid-profiles` | G0→G1 | T+0:45–1:45 | 01 | **P3 labels**, 03 | A | never |
| [03](03-labels-io.md) | `ml/labels-io` | G1 | T+1:00–2:00 | P1 contract | 04, 05, 06 | B | never |
| [04](04-features.md) | `ml/features` | G1 | T+2:00–3:00 | 03 | 06, 07 | A | never |
| [05](05-baselines-metrics.md) | `ml/baselines-metrics` | G1 | T+2:00–3:00 | 03 | 06, 10 | B | never |
| [06](06-quantile-model.md) | `ml/quantile-model` | G1 | T+3:00–4:15 | 04, 05 | 07, 08 | A | never |
| [07](07-predict.md) | `ml/predict` | G1 | T+4:00–5:00 | 06 | **P1 planner on real model** | A | never |
| [08](08-abstention.md) | `ml/abstention` | G2 | T+5:00–7:00 | 07, P3 labels | 10, P1 queue | A | never |
| [09](09-pv-load-forecast.md) | `ml/pv-load-forecast` | G2 | T+7:00–9:00 | 07 | P3 batteries | B | 1st |
| [10](10-eval-run.md) | `eval/run-table` | G3 | T+9:00–10:30 | 08 | 11, 13, P3 panel | A | never |
| [11](11-robustness.md) | `eval/robustness` | G3 | T+10:30–12:00 | 10 | 13 | A | censored test 2nd |
| [12](12-explanations.md) | `ml/explanations` | G3 | T+10:30–13:00 | 07 | P1 explanation text | B | local part 3rd |
| [13](13-error-analysis.md) | `eval/error-analysis` | G4 | T+13:00–16:00 | 10, 11 | P3 README and slides | A | never |

**Critical path:** 02 (profiles) → P3 writes `labels.parquet` by T+3 → 06 → 07 → G1 end-to-end demo at T+5. If 02 slips, P3 has nothing to simulate on. Do 02 before anything else after 01.

**If there are no real labels at T+3:** keep going on the mock labels from 03 (the whole code path must exist), and tell P1 (the plan says P1 then takes over `safe_share`).

## Which rule or score each task covers
| PPC requirement or criterion (points) | Tasks |
|---|---|
| Model trained by the team, runs in our code | 06, 07 |
| Separate test set, compared with a baseline | 03 (split), 05, 10 |
| Data prepared by the team, sources stated, features with a reason (ML quality, 25) | 01, 02, 04 |
| Error analysis (ML quality, 25) | 13 |
| Decision layer: thresholds with a reason, real constraints, confidence (Agent, 25) | 08 |
| "I am not sure" sent to a human (Robustness, 10; Agent, 25) | 08 |
| Missing data, wrong inputs, noise, uncertainty (Robustness, 10) | 08, 11 |
| Explainability: feature importance, similar past cases (10) | 12 |
| Reproducible from the README with our evaluation script (Demo and repo, 5) | 10, 13 |

## Coordination points (agree before the task starts)
| Task | With | What |
|---|---|---|
| 02 | P3 | Profiles file format and units (posted at T+1:45 at the latest) |
| 03 | P3 | `labels.parquet` and `station_houses.parquet` schemas |
| 06 | P1 | Where `ARTIFACT_URI` I/O helpers live (`src/common/`), Makefile targets `data`, `train`, `eval` |
| 08 | P1 | Optional `quality_flags` field in `forecast` (contract change, P1 decides); the crew budget per day; how the planner reads the threshold |
| 09 | P3 | Horizons the battery logic needs |
| 10 | P3 | `summary.json` schema for the comparison panel |
| 12 | P1 | Shape of the per-decision explanation figures |

## Decisions the team still has to confirm
- **Violation target** for the abstention rule (proposed: 2% of daylight intervals on validation, the level exploration reached with fallback). Used in 08.
- **Crew budget** (cases a human can check per day). Used in 08 to report whether the flagged volume is realistic. Ask PPC in the first hour.
- **Time zone of the Ausgrid timestamps** (local with or without daylight saving). Checked in 02.
