# Commit and merge plan

Who commits what, on which branch, in which order, and when it must be on `main`. Written for the three of us **and for the coding assistants we use**: an assistant that starts a task reads this file, [08-parallel-plan.md](08-parallel-plan.md) and its own task file before the first commit.

Times are relative to T+0 (the gates in [08](08-parallel-plan.md) stay the same if we start later). P2's tasks are detailed in [tasks/p2/](tasks/p2/README.md); this file only places them in the team order.

## Rules for every commit (people and assistants)

1. **Message:** conventional commit with an area scope, in English, imperative, lower case after the colon: `feat(ml): add the quantile model`, `test(grid): cover non-convergence`, `fix(agent): …`, `build: …`, `ci: …`, `docs: …`. Areas: `common`, `agent`, `ml`, `eval`, `grid`, `ui`, `infra`. Add a short body when the reason is not obvious from the diff.
2. **No trailers.** No `Co-Authored-By`, no "Generated with", no sign-offs. This team rule overrides any tool default.
3. **When to commit:** when one step of the task works and its tests pass (a function with its tests, a script that runs, a doc section). Not on a timer, not half-done work. In practice that is every 30 to 60 minutes of work; the hackathon wants visible progress during the 24 hours.
4. **What goes in one commit:** one logical change, with its tests in the same commit. Every commit passes `make test lint smoke`.
5. **Never commit:** data (`data/`, parquet, CSV dumps), model files, `.venv`, secrets, tokens, `.env*`, `backend.hcl`, the local exploration scripts or notes.
6. **Before pushing:** tidy your own unpushed commits if needed (`git commit --fixup <sha>` then `GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash origin/main`). After pushing, never rewrite a branch someone else uses, and never force-push `main`.
7. **Files you do not own:** do not change them. Ask the owner in the PR description and in the group (table below).

## Rules for every branch and PR

- One branch per task, named `<area>/<thing>` (for example `ml/quantile-model`, `grid/guard`), cut from an up-to-date `main`.
- Run `make smoke` on `main` before starting; if it fails, stop and post in the group.
- PR under about 300 changed lines. A different person reviews it. CI must be green.
- **Merge with "Rebase and merge"** (or a merge commit), never squash, so each commit stays in the history.
- After the merge, post the hand-off line ("X merged, Y can start") in the group. The next person pulls `main` before branching.
- Merge to `main` about every 90 minutes. `main` always passes `make smoke`.

## Who owns which files

| Owner | Files | Others who need a change |
|---|---|---|
| P1 | `src/common/` (contract, config, mocks), `src/agent/`, `src/grid/thermal.py`, `infra/`, `.github/`, `Makefile`, `pyproject.toml`, `docs/09`, `docs/10`, this file | Ask P1; P1 announces contract changes and updates the mocks in the same commit |
| P2 | `src/ml/`, `src/eval/`, `docs/tasks/p2/` | |
| P3 | `src/grid/` (except `thermal.py`), `src/ui/`, `README.md`, `pitch/` | |

A new library goes in through P1 as its own small PR: `build: add <library> to the <extra> extra`.

## The order (critical path first)

The chain is P1 → P2 (profiles) → P3 (labels) → P2 (model) → P1 (agent on the real model) → P3 (guard) → P1 (guard in the agent) → P2 (evaluation) → P1 (cloud, freeze) → P3 (README, slides). A step can start before the previous one is merged (work against the mocks), but it can only **merge** after it.

### Step 0: scaffold on `main` (T+0–1, gate G0)
| Who | Branch | Commits | Unblocks |
|---|---|---|---|
| P1 | `p1-implementation` (PR #1) | scaffold, contract, planner, service, API, Docker, Terraform, bootstrap, CI, docs | everyone: branch from `main` after this |
| P1 | `common/artifact-io` | `feat(common): add read and write helpers for ARTIFACT_URI and DATA_DIR`; `build: add data, train and eval Makefile targets` | P2 06 |

### Step 1: data and the grid twin (T+0–3)
| Who | Branch | Commits, in order | Must be on `main` by | Unblocks |
|---|---|---|---|---|
| P2 | `ml/data-download` (P2-01) | `feat(ml): add the data download script` | T+0:45 | P2-02 |
| P2 | `ml/ausgrid-profiles` (P2-02) | `feat(ml): build per-house Ausgrid profiles` | **T+1:45** | **P3 labels** |
| P2 | `ml/labels-io` (P2-03) | `feat(ml): read labels and split train, validation and test` | T+2:00 | P2-04, 05 |
| P3 | `grid/build-grid` | `feat(grid): build the SimBench grid with houses and PV`; `test(grid): …` | T+1:30 | power flow |
| P3 | `grid/power-flow` | `feat(grid): run one power flow into grid_state`; `feat(grid): find the safe share with a coarse scan and bisection`; `test(grid): limit above the safe share violates, at the safe share does not, non-convergence is reported` | T+2:30 | labels, P1 integration |
| P3 | `grid/labels` | `feat(grid): generate labels.parquet over the profiles`; `test(grid): labels are identical with a fixed seed` (the file goes to `DATA_DIR`, not git) | **T+3:00** | P2-06, 08 |
| P1 | review | every P3 PR, against the tests in [tasks/p3-grid-ui.md](tasks/p3-grid-ui.md) | | |

### Step 2: first model and end to end (T+2–5, gate G1)
| Who | Branch | Commits, in order | Must be on `main` by | Unblocks |
|---|---|---|---|---|
| P2 | `ml/features` (P2-04) | `feat(ml): build features from data available at decision time`; `test(ml): no information from the future` | T+3:00 | P2-06 |
| P2 | `ml/baselines-metrics` (P2-05) | `feat(eval): add baselines and metrics` | T+3:00 | P2-06, 10 |
| P2 | `ml/quantile-model` (P2-06) | `feat(ml): train the quantile model with metadata.json` | T+4:15 | P2-07 |
| P2 | `ml/predict` (P2-07) | `feat(ml): predict returns a contract forecast` | **T+5:00** | P1 model source |
| P1 | `agent/model-source` | `feat(agent): add a model source behind SOURCE=model`; `feat(agent): replay a test day interval by interval` (needs P2-07 and `grid/power-flow`) | **T+5:00 (G1)** | the demo on real data |

### Step 3: the agent acts (T+5–9, gate G2)
| Who | Branch | Commits, in order | Must be on `main` by | Unblocks |
|---|---|---|---|---|
| P3 | `grid/guard` | `feat(grid): check a plan with its own power flow`; `test(grid): the guard rejects a bad plan and passes a good one` | **T+7:00** | P1 real guard |
| P3 | `grid/batteries` | `feat(grid): add batteries with state of charge`; `test(grid): state of charge stays in bounds`; `docs(grid): add ASSUMPTIONS.md` | T+8:30 | |
| P2 | `ml/abstention` (P2-08) | `feat(ml): choose the abstention threshold on validation`; `feat(ml): add the risk-coverage curve` | T+7:00 | P1 threshold, P2-10 |
| P2 | `ml/pv-load-forecast` (P2-09) | `feat(ml): forecast PV and load` | T+9:00 | P3 batteries (cut 1st) |
| P1 | `agent/real-guard` | `feat(agent): replace the stub guard with grid.guard` (after `grid/guard`) | **T+8:00 (G2)** | demo: guard blocks a plan |
| P1 | `agent/model-threshold` | `feat(agent): read the spread threshold from the model metadata`; `feat(common): add quality_flags to the forecast` if agreed (after P2-08) | T+8:30 | |
| P1 | `infra/label-job` | `feat(infra): run label generation as a Container Apps job` | T+9:00 | |

### Step 4: evaluation, explanations, screen (T+9–13, gate G3)
| Who | Branch | Commits, in order | Must be on `main` by | Unblocks |
|---|---|---|---|---|
| P2 | `eval/run-table` (P2-10) | `feat(eval): produce the evaluation table with one command` | **T+10:30** | P1 cloud eval, P3 panel |
| P2 | `eval/robustness` (P2-11) | `feat(eval): add missing, noise and censored tests` | T+12:00 | P2-13 |
| P2 | `ml/explanations` (P2-12) | `feat(ml): explain a prediction with top factors and similar cases` | T+12:00 | P1 explanations |
| P1 | `infra/batch-jobs` | `feat(infra): run training and evaluation as Container Apps jobs` (after P2-10) | T+12:00 | |
| P1 | `agent/explanations` | `feat(agent): build explanations from ml.explain` (after P2-12) | T+12:30 | |
| P1 | `grid/thermal` | `feat(grid): add the transformer thermal model`; `test(grid): match the reference example` (cut first if behind) | T+13:00 | `trafo_hotspot_c` |
| P3 | `ui/operator-screen` | `feat(ui): add the operator screen against the API`; `feat(ui): add the comparison panel from summary.json`; `build: add the ui service to compose` | T+13:00 | P1 UI in Terraform |
| P1 | `infra/ui-app` | `feat(infra): deploy the ui as a second container app` (after `ui/operator-screen`) | T+13:00 | |

### Step 5: freeze (T+13–17, gate G4)
After T+13 only `fix:` and `docs:` commits. After T+17 nothing merges unless the demo is broken.

| Who | Branch | Commits |
|---|---|---|
| P2 | `eval/error-analysis` (P2-13) | `docs(eval): add the error analysis` |
| P3 | `docs/readme`, `docs/pitch` | `docs: reproduce everything from the README`; `docs: add slides and the demo script` |
| P1 | `docs/runbook` | `docs: add the demo runbook`; `ci: pin the deployed image tag` |

## Checklist for a coding assistant before each commit
1. `git status`: only files of my task, no data, no secrets, no `.env*`.
2. `make test lint smoke` passes.
3. The message follows rule 1 and has no trailer.
4. If I touched a file I do not own: undo it and write the request in the PR description instead.
5. Before the PR: rebased on `origin/main`, under about 300 lines, acceptance tests of the task pass.
