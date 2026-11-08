# P6: ML v2, a calibrated safe-cap model trained on real labels

**Status:** proposal, written 2026-11-07 from a research session (three research rounds, then a review of `main` at `99fee37`). Updated 2026-11-08 against `main` at `76be12f`: steps 10–12 and S3 added (label schema, live input checks, thermal ambient, house locations), the merge order with PR #25, and the README rule. Step 03 changes rule 2 of [p2/README.md](p2/README.md) (the validation split): the team confirms that before 03 starts.

**Owns:** new `src/ml/weather.py`, `src/ml/online_calibration.py`; changes to `src/ml/features.py`, `src/ml/sun.py`, `src/ml/split.py`, `src/ml/train.py`, `src/ml/abstention.py`, `src/ml/predict.py`, `src/ml/explain.py`, `src/eval/run.py`, `src/eval/metrics.py`, `src/eval/robustness.py`, `src/eval/error_analysis.py`; tests under `tests/ml/` and `tests/eval/`. **Asks P1** for anything in `src/common/`, `src/agent/`, `Makefile`, `pyproject.toml` (steps 11 and 12 touch `src/agent/`). **Asks P3** for the label files and `src/grid/labels.py` (step 10).

## Contents
0. [How to use this file (people and AI sessions)](#0-how-to-use-this-file)
1. [Summary](#1-summary)
2. [The PPC theme and how P6 serves it](#2-the-ppc-theme-and-how-p6-serves-it)
3. [Where we are on main](#3-where-we-are-on-main)
4. [Principles: accurate, readable, production ready](#4-principles)
5. [The model in the end](#5-the-model-in-the-end)
6. [Data](#6-data)
7. [Implementation steps](#7-implementation-steps)
8. [Production readiness](#8-production-readiness)
9. [Skills and tools](#9-skills-and-tools)
10. [Research context](#10-research-context)
11. [Where each part comes from](#11-where-each-part-comes-from)
12. [Claims we rejected](#12-claims-we-rejected)
13. [Not now, and why](#13-not-now-and-why)
14. [Decisions for the team](#14-decisions-for-the-team)
15. [Hand-off](#15-hand-off)

---

## 0. How to use this file

**For an AI coding session (read this first).** This file is the context. Before writing code for a step:
1. Read sections 1–5 of this file, then the step in section 7, then the sections that step lists under "Context". Do not start from memory or from a summary.
2. Read the repository files the step names, on a fresh `main` (`git switch main && git pull`), then create the step's branch.
3. Read the team rules once: [p2/README.md](p2/README.md) (8 rules, how to run a task), [../01-theme-and-criteria.md](../01-theme-and-criteria.md) (the theme), [../11-commit-plan.md](../11-commit-plan.md) (commit rules), [../09-contract.md](../09-contract.md) (shared objects), [../10-cloud.md](../10-cloud.md) (`DATA_DIR`, `ARTIFACT_URI`).
4. Use the skills in section 9 at the moments listed there.
5. A fact marked **reported** in sections 10–11 was not re-checked: check it before it goes into code, a test or a slide. Facts in section 12 are wrong; never use them.
6. Hard rules: never read the sealed test year before step 08; never commit data; no `Co-Authored-By` or any other commit trailer; ask a person before any push, merge, force-push or Azure action; numbers on slides come only from the evaluation output.
7. **README rule:** a step that changes how the project runs (a command, option, environment variable, dependency, data step, port, output path or expected time) updates `README.md` in the same pull request. The reviewer checks it ([../../README.md](../../README.md), "Keeping this README current").
8. **Merge order:** start no step that edits `src/ml/train.py`, `abstention.py`, `predict.py`, `explain.py`, `forecast_pv_load.py`, `model_io.py` or `src/eval/` before PR #25 is merged (section 3).
9. When a step is done, post its hand-off line and tick it in section 15.

**For people.** Sections 1, 2, 5 and 14 are enough to decide. Section 7 is the work list; section 10 is the evidence.

**Status words used below.** *in repo*: already in our code or docs. *checked*: the source page was opened on 2026-11-07. *reported*: a research agent reported it, not re-opened. *team choice*: an engineering judgement made in the session, not taken from a source.

---

## 1. Summary
- v1 (`safe-cap-qgb-v1`) is on `main` and has only run on **mock labels**.
- The validation period is **April–June 2012** (Sydney autumn and early winter); the test is a **full year**. This is the likely cause of the violation drift seen in exploration (1.3–1.8% on validation, 2.3–3.5% on test).
- P6 adds `safe-cap-qgb-v2` next to v1 with four changes backed by evidence: **weather and clear-sky features**, **validation over all four seasons**, an **online offset** on the limit that learns from recent misses, and **tuning on the violation rate** instead of quantile coverage. Plus three things the jury asks for: **skill against a baseline**, **fairness between houses**, and an error analysis that shows **what we tried to correct**.
- No new dependency. v1 stays loadable; `MODEL_VERSION` switches between them.
- **Blocker found on 2026-11-08:** the power-flow label generator writes a different schema from the one training reads, so v1 and v2 can only train on mock labels until step 10 is done. And the live agent does not run the existing input checks, so it does not abstain when readings are missing (step 11).
- Effort (team choice estimate): about 17 hours of code over 13 steps, plus the label generation runtime (measured: about 7 s per day with 4 workers, section 3).

| Change | Theme criterion it serves | Evidence |
|---|---|---|
| Weather + clear-sky features | ML quality (25) | solar forecasting literature, NASA POWER (section 10) |
| Four quarterly validation folds | ML quality (25), Robustness (10) | our reading of `split.py`; KIT 2026 benchmark |
| Online offset tuned on violations | Agent decision layer (25), Robustness (10) | Gibbs and Candès 2021; Pinson et al. 2026 |
| Crew budget in the threshold choice | Agent decision layer (25) | the theme's own example |
| Skill score, Jain fairness | ML quality (25), Idea (25) | Yang et al.; Quessongo et al. 2026 |
| v1 → v2 in the error analysis | ML quality (25): "what you tried to correct" | the theme text |
| Explanations of the offset and weather | Explainability (10) | the theme text; our `explain.py` |
| Weather-missing robustness case | Robustness (10) | the theme text |
| Live input checks: missing readings → "not sure" | Robustness (10), Agent (25) | the theme text; measured gap (section 3) |
| Labels in the training schema | ML quality (25): "trained on our data" | measured gap (section 3) |

---

## 2. The PPC theme and how P6 serves it
Source: the PPC document "Smarthack XI 2026: tema PPC" (summary in [../01-theme-and-criteria.md](../01-theme-and-criteria.md)). The theme asks for an agent that **perceives** through data, **estimates** with ML models trained by the team, **decides** under real constraints and **acts**; every decision must be traceable to the prediction behind it.

### Mandatory requirements
| Requirement | How P6 keeps it |
|---|---|
| A model trained by the team, separate test set, simple baseline; training code in the repo; runs in our code, not an external API | scikit-learn models trained in `train.py`; sealed test year; baselines fixed 0.36, last known, same hour yesterday, oracle; no pretrained model, no API |
| An LLM alone is not enough | P6 uses no LLM; explanations are numbers turned into text by templates (`explain.py`) |
| The agent executes actions | per-house limit commands, the "not sure" queue, and (asked of P1) a calibration alert and a "stations to check" list |
| Public, synthetic or team data, sources stated | Ausgrid (public), NASA POWER (public), labels from our power flow (synthetic, method stated); every source in section 10 |
| Public repo, commits during the 24 hours | small conventional commits, one branch per step |

### "A complete project"
| Item in the theme | P6 contribution |
|---|---|
| Data prepared by the team, features with a clear reason | weather download with availability times; 5 new features, each with a reason in the docstring table (step 02) |
| Model trained and evaluated correctly; error analysis: where it fails and **what we tried to correct** | folds over all seasons (03); v1 vs v2 in the "what we tried" table (07) |
| Justified decision layer: thresholds with a reason, real constraints (**cases a crew can check per day**), confidence | offset and `τ` chosen on validation against `VIOLATION_TARGET`, with the crew budget `CREW_CASES_PER_DAY` checked and reported (04) |
| Concrete actions | limit per house; "not sure" queue; calibration alert; stations to check (09, with P1) |
| Difficult situations: missing data, rare cases, wrong inputs, uncertainty; "I am not sure" to a person | weather optional; input checks wired into the live agent (11); weather-missing robustness case (05); abstention unchanged |
| Explainability: feature importance, similar past cases | new feature names in `explain.py`; the offset shown as its own factor (06) |
| Reproducibility: README and the evaluation script | one command per stage; byte-identical evaluation; README updated (09) |

### Scoring (100 points)
| Criterion | Points | What P6 adds |
|---|---|---|
| Idea and relevance for PPC | 25 | Romanian and EU facts, fairness column, honest limits (section 10.6) |
| ML quality | 25 | better features, all-season validation, skill score, v1→v2 error analysis |
| Robustness | 10 | online offset against drift, weather-missing case, input checks kept |
| The agent | 25 | calibrated limits, crew-aware threshold, alert and priority list |
| Explainability | 10 | offset and weather in the explanation |
| Demo and repository | 5 | reproducible commands, small commits, this brief |

Deliverables (theme): a working project in a public GitHub repository with the presentation material, and a live demo followed by technical questions.

---

## 3. Where we are on main
State at `99fee37` (2026-11-07), all merged by P2:

| Module | What it does |
|---|---|
| `src/ml/data.py`, `ausgrid.py` | download Ausgrid, build `profiles.parquet`; the 2012–13 file is sealed unless `--include-held-out` |
| `src/ml/labels.py` | label schema, validation, mock labels; scenarios `A`, `B`, `B-VAR`, station ids `PT-A`, `PT-B`, `PT-B-VAR` |
| `src/ml/features.py` | 14 features, `available_at <= t`, NaN never 0, net values only |
| `src/ml/split.py` | train ≤ 2012-03-31, validation 2012-04-01 → 06-30, test 2012-07-01 → 2013-06-30 (Sydney dates) |
| `src/ml/train.py` | one `HistGradientBoostingRegressor(loss="quantile")` per quantile (0.05, 0.10, 0.20, 0.50, 0.90), 4 settings, pinball on validation, sort + clip, `metadata.json` |
| `src/ml/abstention.py` | `τ` on `q90 − q05`, highest `τ` meeting the violation target, input checks (`missing_net_now`, `stale_input`, `out_of_range_net`, `night`) |
| `src/ml/calibration.py` | quantile coverage, val/test drift report |
| `src/ml/predict.py` | contract `forecast`; `MODEL_VERSION` env (default `safe-cap-qgb-v1`) |
| `src/ml/forecast_pv_load.py` | PV and load p10/p50/p90 at 60/180/360 min (`pv-load-qgb-v1`) |
| `src/ml/explain.py` | permutation importance, local ablation (top 3 factors), 5 similar past cases |
| `src/eval/run.py`, `table.py`, `metrics.py` | one-command evaluation table on the test year, deterministic |
| `src/eval/robustness.py` | missing, noise and censored-production cases |
| `src/eval/error_analysis.py` | where the model fails (edges of the day, cloudy days, seasons) and a "what we tried" table on train/validation |
| `src/ml/config.py` | `VIOLATION_TARGET` (default 0.02), `CREW_CASES_PER_DAY` (default 20) |

Missing: **real labels** (`DATA_DIR/labels/` does not exist; only exploration files in `data/prepared/`). Local data folders also hold `data/ausgrid`, `data/simbench`, a GoiEner sample in `data/goiener` (not used) and empty `data/ukpn_*` folders.

Label generator today (`src/grid/labels.py`, P3): one Ausgrid CSV per run (`--source`, `--scenario`, `--output`, `--start`, `--days`, `--transformer-kva`, `--pv-scale`, `--workers`); daylight 06:00–20:00 Sydney with PV > 0; it builds the **synthetic three-feeder station** by default (SimBench is optional through `build_grid({"topology": "simbench", ...})`), names the station `PT-<scenario>` and writes `labels.parquet` in the schema of `src/ml/labels.py` plus `station_houses.parquet`, by default into `DATA_DIR/labels/<scenario>/`; later runs append and keep the same houses.

### Since then (main at `76be12f`, 2026-11-08)
| Change | What it means for P6 |
|---|---|
| `SOURCE=model` wiring (`src/agent/model_wiring.py`, `wiring.py`) | the agent uses `ml.predict`, the labels history, the grid guard and the model's abstention threshold; `SCENARIO` picks the station |
| Hot-spot temperature in the grid state (`model_wiring.hotspot_c`) | IEC 60076-7 over the last 24 h of readings with an **assumed constant 20 °C ambient** (`AMBIENT_C`): step 12 replaces it with measured temperature |
| `src.common.pipeline` | train, PV/load forecast and evaluation in one command |
| README rewritten as the local run guide | every run-affecting change updates it (README rule, section 0) |

### Open pull requests that touch P6
| PR | Files | Effect on P6 |
|---|---|---|
| #25 `fix/p2-review-comments` | `src/ml/train.py`, `abstention.py`, `predict.py`, `explain.py`, `forecast_pv_load.py`, `model_io.py`, `src/eval/*`, `pyproject.toml`, `Makefile`, CI | the same files as steps 02–07 and 11: **merge it before those steps start**, or every P6 branch conflicts. Caches keyed on `metadata.json` time, so a retrained model is picked up by a running API |
| #26 `ml/house-locations` | `src/ml/geo.py`, `src/ml/data.py`, `src/ml/DATA.md` | postcode, suburb, latitude and longitude per Ausgrid customer (`python -m src.ml.data geo --from <geo.csv>`, stored under `DATA_DIR/reference/`). Enables stretch S3 (weather and sun per location); also useful for the P4 map |

### Measured on 2026-11-08 (clean data folder)
- **Label schema mismatch.** One day of `src.grid.labels` (`--start 2012-01-15 --days 1 --workers 4`) wrote 28 labels in about 7 s with columns `pt_id, interval_start, safe_cap_share, provenance, n_houses, pv_scale, transformer_kva, source` and station id `PT-synthetic-400kVA`. `src.ml.labels.validate` rejects it: missing `safe_share`, `converged`, `binding`, `load_kw`, `pv_kw`, `net_kw`, `kwp_total`, `available_at`, `source_ref`; no `station_houses.parquet`. Step 10.
- **Label runtime.** About 7 s per day with 4 workers: two training years ≈ 730 days ≈ 85 minutes per scenario on 4 workers (estimate; days differ in length).
- **Live input checks not wired.** `abstention.quality_flags` (`missing_net_now`, `missing_share_last`, `stale_input`, `out_of_range_net`, `night`) is used only in training and evaluation. With `SOURCE=model` on a day without readings, `/forecast` returns q05 ≈ 0.74 with no flag and `/plan/propose` proposes limits. Step 11.
- **Training on mock labels** (scenario A): about 45 s; PV/load forecast about 40 s; tests 353 pass in about 2 minutes.

---

## 4. Principles
1. **Small steps.** One idea per branch, under about 300 changed lines, tests first.
2. **No new dependency.** No pvlib, MAPIE, PyTorch, LightGBM or forecasting framework. Each formula is a few lines and is written in the docstring.
3. **Every number has a name and a reason.** Thresholds, step sizes, targets and the periods they were chosen on go into `metadata.json`.
4. **Same style as v1.** Docstring tables, `available_at <= t`, NaN stays NaN, fixed seeds, paths only through `DATA_DIR` and `ARTIFACT_URI`, Sydney local dates for splits.
5. **Measure, do not assume.** A change is kept only if it helps on the validation folds; the report says so either way.
6. **v1 stays.** v2 is a new model version; `MODEL_VERSION` switches; rollback is the same variable.
7. **Honest limits.** Simulation, Australian data, a German or synthetic grid; say it on screen and in slides.

---

## 5. The model in the end
Every 30 minutes, for each transformer station, the agent asks: *what is the highest share of each house's kWp it may export in the half hour that starts one hour from now, without voltage, line or transformer violations?*

| Stage | What happens | Trained? | Where |
|---|---|---|---|
| Perceive | station net load from the meters, last known safe share, weather now (sunlight, temperature) | no | `features.build` |
| Estimate | five quantile models give q05, q10, q20, q50, q90 of the safe share | yes, offline | `train.py` |
| Calibrate | limit = clip(q05 − c, 0, 1); `c` learns from recent misses | `c` online | `online_calibration.py` |
| Decide | abstain if `q90 − q05 > τ` or an input check fails: fixed 0.36 and a person reviews | `τ` on validation | `abstention.py`, P1 planner |
| Check | power flow on the whole station with the plan, two worst cases | no (physics) | `src/grid/agent_guard.py` |
| Act | limit command per house, or fallback + review queue; alert when the rolling violation rate is above target | — | P1 agent |
| Explain | top factors (including the offset), similar past cases | — | `explain.py` |
| Learn | 30 minutes after an interval ends its safe share is known and updates `c` | — | `online_calibration.py` |

Other models in the agent: the PV and load forecast (60/180/360 min, same recipe, other targets) for batteries; the transformer thermal model ([../12-thermal-model.md](../12-thermal-model.md)), physics only, not trained.

Training, once and offline: raw data → labels by power flow → features → four quarterly folds (choose the setting) → calibration (`γ`, `τ`, start offset) → refit on both training years → test once on the sealed year → save.

---

## 6. Data
| Dataset | Role in P6 | Where | Licence | Status |
|---|---|---|---|---|
| Ausgrid Solar Home, 300 homes, 30 min, 2010-07 → 2012-06 | training and validation | `DATA_DIR/raw/ausgrid/`, `profiles.parquet` | CC BY 3.0 AU (stated in the copy's README; Ausgrid page withdrawn) | in repo ([../../src/ml/DATA.md](../../src/ml/DATA.md)) |
| Ausgrid 2012-07 → 2013-06 | **sealed** test | same, only with `--include-held-out` at step 08 | same | in repo |
| Labels A, B, B-VAR | target `safe_share` | `DATA_DIR/labels/<scenario>/labels.parquet` | ours (power flow) | P3 generates (step 08) |
| NASA POWER hourly, Sydney, 2010-07 → 2013-06 | weather features | `DATA_DIR/raw/nasa_power/` | public NASA data | hourly from 2001-01-01: checked |

Stretch (kept because they serve the theme; section 7, S1 and S2): FeederBW (real European feeders: ML quality, idea relevance), ENWL or CSIRO networks (robustness across grids).

Pitch only (idea and relevance): ANRE, German 60% rule, Kapacitet+, University of Queensland thesis, Aydin et al. (section 10.6).

Not in P6: Open-Meteo, Meteostat, PVGIS, CAMS, Swiss profiles, GoiEner, Low Carbon London, ETT, ENTSO-E, UK DNO portals (section 10; reasons in section 13).

**Limits to state.** One weather point for the whole Ausgrid area (Sydney coordinates in `src/ml/sun.py`); stretch S3 uses the house coordinates from PR #26 instead. NASA POWER is history: a live system needs a live source (Open-Meteo or the Romanian ANM); the model must still work without weather. Australian homes, Romanian story: say it.

---

## 7. Implementation steps
| # | Branch | Depends on | Size | Hours (estimate) | Cut |
|---|---|---|---|---|---|
| 00 | — (setup) | — | — | 0.5 | never |
| 10 | `grid/labels-ml-schema` (P3 with P2) | 00 | ~200 lines | 2 | never |
| 11 | `agent/live-input-checks` (P1 with P2) | PR #25 | ~100 | 1 | never |
| 01 | `ml/weather` | 00 | ~150 | 2 | never |
| 02 | `ml/features-v2` | 01, PR #25 | ~150 | 1.5 | never |
| 03 | `ml/time-folds` | team OK on rule 2, PR #25 | ~200 | 2 | never |
| 04 | `ml/online-offset` | 03 | ~200 | 2 | never |
| 05 | `eval/v2-columns` | 04 | ~200 | 2 | Jain 2nd |
| 06 | `ml/explain-v2` | 02, 04 | ~100 | 1 | 3rd |
| 07 | `eval/what-we-tried-v2` | 05 | ~100 | 1 | never |
| 12 | `agent/thermal-ambient` (P1) | 01 | ~60 | 0.5 | 2nd |
| 08 | run: labels, train, final evaluation | 02–07, 10, 11 | — | about 85 min of labels per scenario on 4 workers | never |
| 09 | `docs/p6-results` + P1 requests | 08 | ~100 | 1.5 | never |
| S1 | `eval/feederbw-check` | 08 | ~200 | 4 | 1st |
| S2 | second grid family for labels (P3) | 10 | — | 4–6 | 1st |
| S3 | `ml/weather-by-location` | 02, PR #26 | ~150 | 2 | 1st |

Rows are in working order; the numbers are stable ids (10–12 and S3 were added on 2026-11-08). Parallel: 10, 11, 01 and 03 touch different files and can run at the same time (10 in `src/grid/`, 11 in `src/agent/` and `predict.py`, 01 a new file, 03 `split.py` and `train.py`). 06 can start once 02 and 04 are merged. **PR #25 first:** 02–07 and 11 edit the files it changes.

### 00 · Setup and checks
**Context:** sections 3 and 6; [p2/README.md](p2/README.md) "How to run a task".
1. `git switch main && git pull`; install and check as in the README ("Run it locally", sections 2–3): `python -m pip install -e ".[dev,ml,sim,grid-tools]"`, then tests, lint and `python -m src.smoke`.
2. `python -m src.ml.data download` and `python -m src.ml.data profiles` (2010–12 only; the test file stays sealed).
3. Check that PR #25 is merged; if not, ask the team to merge it before 02–07 and 11 start.
4. With P3, agree the scenario mapping: which grid configuration (synthetic station or SimBench, transformer size, PV scale, reactive-power control for B-VAR) is `A`, `B`, `B-VAR`. Step 10 implements it.
5. Label time is already measured (section 3): about 7 s per day with 4 workers, about 85 minutes per scenario for two years. Run `--days 7 --workers 8` once on the target machine to confirm; if it is too long for a laptop, ask the team before using the Azure batch job.

### 10 · `grid/labels-ml-schema` (P3, with P2)
**Goal:** the power-flow labels load with `src.ml.labels.load(scenario)` and train the model; this is what turns mock numbers into results.
**Why (theme):** "a model trained … on data prepared by the team"; without it every number is from mock labels.
**Context:** section 3 ("Measured"), `src/ml/labels.py` (schema, `validate`, the mock writer as the reference), `src/grid/labels.py`, `src/grid/twin.py`, [p2/03-labels-io.md](p2/03-labels-io.md).
**Files:** `src/grid/labels.py` (P3), tests under `tests/` for the grid labels.
1. Add `--scenario {A,B,B-VAR}`: write `DATA_DIR/labels/<scenario>/labels.parquet` and `station_houses.parquet` in the ML schema (`pt_id` = `PT-<scenario>`, `safe_share`, `converged`, `binding`, `load_kw`, `pv_kw`, `net_kw`, `kwp_total`, `n_houses`, `available_at = interval_start + 30 min`, `provenance`, `source_ref = "grid/labels.py@<sha>"`, UTC times). Keep `--output` working as today.
2. `safe_share` is null where the power flow did not converge, never 0. `binding` from the twin if it reports it, otherwise null.
3. Several runs (one per Ausgrid file and day range) append to the same scenario folder without duplicates.
4. The scenario mapping from step 00; if it is not agreed yet, implement `A` with today's defaults and leave `B` and `B-VAR` as clearly marked TODOs.
5. README step 6 ("Labels"): replace the "does not yet match" note with the real command (README rule).
**Acceptance:** a tiny in-test fixture written by the new option passes `src.ml.labels.validate`; null stays null; one real day loads with `labels.load("A")` and `python -m src.ml.train --scenario A` runs on it.

### 11 · `agent/live-input-checks` (P1, with P2)
**Goal:** the live agent says "I am not sure" when its inputs are missing, stale or wrong, as training and evaluation already assume.
**Why (theme):** "difficult situations: missing data, wrong inputs … a good agent says 'I am not sure' and sends the case to a person"; Robustness (10), Agent (25).
**Context:** section 3 ("Measured"), `src/ml/abstention.py` (`quality_flags`), `src/agent/service.py` (`force_abstain` passed to `make_plan`), `src/agent/planner.py`, `src/agent/model_source.py`, [../09-contract.md](../09-contract.md).
**Files:** `src/agent/model_source.py` or `service.py` (P1), `src/ml/predict.py` if the flags travel with the forecast, tests.
1. When `SOURCE=model`, compute `abstention.quality_flags(features)` for each decision with the same features `predict` used.
2. Any flag forces abstention through the existing `force_abstain` path, with the flag names as the reasons (they appear in the plan, the queue and the log).
3. If P1 prefers the flags on the `forecast` object (the optional `quality_flags` field discussed in P2 task 08), it is a contract change: P1 decides.
4. Out-of-range days (no readings in the history) must give `missing_net_now` and `stale_input`, so the plan abstains instead of proposing limits.
**Acceptance:** a test with an empty history gives an abstained plan whose reasons include `missing_net_now`; a normal day inside the label period is unchanged.

### 12 · `agent/thermal-ambient` (P1)
**Goal:** the transformer hot-spot uses measured temperature instead of a constant 20 °C.
**Why (theme):** real constraints in the decision layer; honest physics.
**Context:** `src/agent/model_wiring.py` (`hotspot_c`, `AMBIENT_C`), [../12-thermal-model.md](../12-thermal-model.md), step 01.
**Files:** `src/agent/model_wiring.py`, its tests.
1. When `weather.load()` has a temperature with `available_at <=` the decision time, pass it as the ambient for each step; otherwise keep 20 °C and say "assumed" in the grid state, as today.
2. Same for the history steps used to warm up the thermal state.
**Acceptance:** a hot day gives a higher hot-spot than the 20 °C default; missing weather gives exactly today's numbers.

### 01 · `ml/weather`
**Goal:** hourly sunlight and temperature for Sydney, each with the time it becomes known.
**Why (theme):** data prepared by the team with a stated source; better features (ML quality).
**Context:** section 10.1 (weather sources), section 12 (leakage), [../05-data-and-sources.md](../05-data-and-sources.md).
**Files:** `src/ml/weather.py`, `tests/ml/test_weather.py`.
1. `python -m src.ml.weather download`: one call per year to the NASA POWER hourly point API (https://power.larc.nasa.gov/docs/services/api/temporal/hourly/), coordinates `SYDNEY_LAT`, `SYDNEY_LON` from `src/ml/sun.py`, 2010-07-01 → 2013-06-30, UTC time standard. Parameters: all-sky sunlight on the ground and 2 m temperature. The expected names are `ALLSKY_SFC_SW_DWN` and `T2M`: **check them in the API documentation before coding** (reported, not checked).
2. Send a `User-Agent` that names the project, no personal e-mail. Save `DATA_DIR/raw/nasa_power/sydney.parquet` and write its SHA-256 next to it.
3. `load() -> DataFrame` with `time` (UTC), `ghi_wm2`, `t2m_c`, `available_at`. **Conservative rule:** `available_at = time + 1 h` whatever end of the hour the API labels, so no value can be used early. Fill values (for example −999) become NaN.
4. Docstring: source URL, licence note, the availability rule, and that NASA POWER is for history only.
5. README: the download command in "Run it locally" (section 5, Data) and NASA POWER in "Data and sources" (README rule).
**Acceptance:** tests on a tiny in-test JSON: parsing, NaN for fill values, the `available_at` rule, UTC index; no network in tests.

### 02 · `ml/features-v2`
**Goal:** five new features, all known at decision time `t`; `FEATURES` grows from 14 to 19.
**Why (theme):** features "built with a clear reason" (complete project, item 1); ML quality.
**Context:** section 10.3 (clear-sky literature), section 10.5 (leakage repo), `src/ml/features.py` docstring.
**Files:** `src/ml/sun.py`, `src/ml/features.py`, `tests/ml/test_features.py`.

| Feature | Definition | Reason |
|---|---|---|
| `clearsky_T` | clear-sky sunlight at the middle of `T` by Haurwitz: `1098 · cos z · exp(−0.057 / cos z)` W/m², 0 when the sun is down, divided by 1000 | the sky's ceiling at the target time |
| `kt_now` | measured sunlight ÷ clear-sky sunlight for the newest hour with `available_at <= t`; NaN when clear-sky < 50 W/m² | how cloudy it is now |
| `kt_lag_1` | the same one hour earlier | clearing or clouding |
| `t2m_now` | temperature of the newest known hour | air-conditioning load, hot afternoons |
| `net_over_clearsky` | `net_now` ÷ (clear-sky sunlight of the newest interval / 1000); NaN when the sun is low | net load relative to what the sun could give |

1. `sun.py`: `clearsky_ghi(ts)` next to `solar_elevation` (Haurwitz; `cos z = sin(elevation)`), tested against two or three hand-computed values.
2. `features.build(station_state, t, horizon_min=60, weather=None)` and `build_frame(labels, horizon_min=60, weather=None)`: weather optional. Without weather the weather features are NaN, never 0; the model still predicts (HistGradientBoosting handles NaN).
3. Add the five rows to the docstring table and to `explain.LABELS`.
4. Not added: PV of neighbouring houses. It needs separate PV meters, which breaks the "net only" rule in the `features.py` docstring; `kt_now` carries the same cloud signal.
5. `forecast_pv_load.py` uses `FEATURES` too: its models must be retrained (its metadata check already refuses models trained on other features).
**Acceptance:** the 14 v1 features keep their values; a test that moves weather one hour into the future leaves the features at `t` unchanged (no leakage); NaN when weather is absent; Haurwitz is 0 at night.

### 03 · `ml/time-folds`
**Goal:** choose the model settings on a full year of out-of-sample predictions instead of three autumn months.
**Why (theme):** "evaluated correctly on a separate test set"; the drift is the main ML weakness to fix.
**Context:** section 1 (drift), section 10.3 (KIT benchmark), `src/ml/split.py`, `src/ml/train.py`.
**Files:** `src/ml/split.py`, `src/ml/train.py`, `tests/ml/test_split.py`, `tests/ml/test_train.py`.
1. **New rule 2 (needs team OK):** training data 2010-07-01 → 2012-06-30; four **expanding quarterly folds** over 2011-07-01 → 2012-06-30 (Jul–Sep, Oct–Dec, Jan–Mar, Apr–Jun): each quarter is predicted by models trained only on data before it. The test year 2012-07-01 → 2013-06-30 is unchanged and sealed. Sydney local dates, as today.
2. `split.folds(df) -> list[tuple[DataFrame, DataFrame]]`; the existing `split` stays for v1.
3. `train.py`, `MODEL_VERSION = "safe-cap-qgb-v2"`: for each of the 4 settings in `GRID`, fit the five quantile models per fold, collect the out-of-sample predictions of the four quarters, pick the setting with the lowest mean pinball loss. Then **refit on all of 2010-07 → 2012-06** with that setting. Keep `fit_quantile`, `rearrange`, `predict_quantiles`.
4. Report per quarter: pinball per quantile, q05 coverage, violation rate of q05. A season that is much worse is a finding for the error analysis, not something to hide.
5. Save the out-of-sample predictions (`oos_predictions.parquet` next to the model): steps 04, 06 and 07 use them.
6. Cost: 4 settings × 4 folds × 5 quantiles = 80 fits of about 20,000 rows (team choice estimate: minutes on a laptop).
**Acceptance:** no fold uses a row at or after its prediction quarter; same seed gives byte-identical metadata; v1 training (`safe-cap-qgb-v1`) still works.

### 04 · `ml/online-offset`
**Goal:** keep the violation rate at the target when the weather regime shifts, and choose the abstention threshold with the crew in mind.
**Why (theme):** "a justified decision layer: thresholds with a reason, real constraints (how many cases a crew can check per day), the model's confidence"; robustness to uncertainty.
**Context:** sections 10.3 (Gibbs and Candès; Pinson et al.), `src/ml/abstention.py`, `src/ml/config.py`.
**Files:** `src/ml/online_calibration.py`, `src/ml/train.py` (calls it), `src/ml/abstention.py` (uses the adjusted limit), tests.

```text
limit_t = clip(q05_t − c_t, 0, 1)
after each interval i whose label is known (available_at_i <= decision time)
and where the model limit was applied (not abstained):
    miss_i = 1 if limit_i > safe_share_i + 1e-6 else 0
    c ← clip(c + γ · (miss_i − α), −0.05, 0.30)
```

1. `α = VIOLATION_TARGET` (default 0.02). `c` rises after a miss and falls slowly while there are none. The bounds keep it readable: at most 5 points looser, 30 points stricter.
2. `Offset` class: `apply(q05)`, `update(limit, safe_share)`, `to_dict()`, `from_dict()`. No hidden state, no randomness.
3. On the out-of-sample year from 03, replay in time order for each `γ` in `(0.001, 0.003, 0.01, 0.03)`: violation rate and export index. Keep the `γ` with the highest export index whose violation rate is at most `α`; ties go to the smaller `γ`. If none meets `α`, keep the one closest and report it as not reachable (never relax `α` silently).
4. Then choose `τ` with the existing `abstention.choose_threshold`, using the offset limit. Keep the spread as `q90 − q05` (raw quantiles: it measures uncertainty).
5. **Crew budget:** report flagged cases per day (mean and maximum) against `CREW_CASES_PER_DAY`, as v1 does. If the budget does not hold at the chosen `τ`, do not change `α` in code: write it in the report with the `risk_coverage.csv` curve so the team decides (more crew, or a higher target).
6. `metadata.json`: `γ`, `τ`, the final `c` of the replay (start value for the test and live use), `α`, whether each was reachable, and the out-of-sample period they came from.
7. Where the live `c` is kept between agent calls is P1's choice (ask): a small JSON per station is enough.
**Acceptance:** all misses → `c` rises and the limit falls; no misses → `c` falls; the replay never uses a label before its `available_at`; `to_dict`/`from_dict` round-trip.

### 05 · `eval/v2-columns`
**Goal:** score v2 exactly like v1 and add the columns the jury will ask for.
**Why (theme):** "compared with a baseline"; reproducible results from our evaluation script; robustness.
**Context:** section 10.3 (skill scores, Jain), `src/eval/run.py`, `metrics.py`, `robustness.py`, `table.py`.
**Files:** `src/eval/run.py`, `src/eval/metrics.py`, `src/eval/robustness.py`, `src/eval/table.py`, tests.
1. `run.py`: score v1 and v2 side by side on the test year. For v2, replay the offset in time order from the start value in the metadata (no look-ahead, labels used only after `available_at`).
2. **Skill score:** `1 − pinball_0.05(model q05) / pinball_0.05(last known share)`. Positive is better than persistence.
3. **Jain's fairness index** in `metrics.py`: `J = (Σ x)² / (n · Σ x²)` over houses, `x` = share of a house's exportable energy it was allowed to export over the test year. 1 = every house kept the same share. Report it for fixed, model and oracle.
4. `robustness.py`: add **weather missing** (all weather features NaN) next to missing readings, noise and censored production. If the cost is large, the fix is a training option that blanks weather on a fixed 10% of rows (fixed seed); decide from the numbers.
5. `summary.json` keeps its schema for P3's comparison panel; new numbers go in new keys.
6. README section 9 ("Reproduce the results"): any new option or output file (README rule).
**Acceptance:** two runs give byte-identical outputs; Jain is 1 for equal shares and lower for unequal ones; v1 numbers unchanged by this branch.

### 06 · `ml/explain-v2`
**Goal:** the agent can say why a v2 limit is what it is, including the offset.
**Why (theme):** explainability (10): "feature importance or similar cases from history".
**Context:** `src/ml/explain.py` docstring; section 5.
**Files:** `src/ml/explain.py`, `tests/ml/test_explain.py` (or `tests/test_explain.py`).
1. Labels for the five new features (step 02 adds the names; here the wording is checked).
2. The offset as its own factor: "limit lowered by `c` because recent limits were too high" (or raised), with the number from the offset state.
3. Similar past cases keep using training and validation only, with outcomes known at decision time.
**Acceptance:** an explanation for a v2 prediction lists the offset when `c ≠ 0`; every number in the text is in the figures (existing rule).

### 07 · `eval/what-we-tried-v2`
**Goal:** the error analysis shows what we changed and whether it helped.
**Why (theme):** "error analysis: where the model fails, on what cases, and **what you tried to correct**".
**Context:** `src/eval/error_analysis.py` (its "what we tried" table uses training and validation only).
**Files:** `src/eval/error_analysis.py`, tests.
1. Add rows on the out-of-sample year from 03 (never the test year): v1 features + old split; + weather features; + folds; + offset. Columns: pinball q05, violation rate, export index, abstention rate.
2. Keep the existing failure tables (edges of the day, cloudy vs clear days, seasons) for v2 on the test year.
**Acceptance:** every number written to `slides_numbers.md` is found verbatim in a generated table (existing rule).

### 08 · Run: labels, training, final evaluation
**Why (theme):** the model trained by the team on our data; results from our script.
**Context:** sections 3, 6; step 00.
1. P3 generates labels for A, B, B-VAR over 2010-07 → 2012-06 with the step 10 option and the mapping agreed in 00, into `DATA_DIR/labels/<scenario>/` (about 85 minutes per scenario on 4 workers).
2. `python -m src.ml.weather download`, then `python -m src.ml.train --scenario all` (v2) and the PV/load forecast retrain.
3. Read the fold report: any change that does not help on the folds is turned off for v2, and the hand-off says so.
4. **Final evaluation, once:** P3 generates the test-year labels; `python -m src.ml.data download --include-held-out`, `python -m src.ml.data profiles`, then `python -m src.eval.run --scenario all --run-id final`.
5. Numbers for slides come only from `ARTIFACT_URI/eval/final/`.

### 09 · `docs/p6-results` and requests to P1
**Why (theme):** reproducibility, concrete actions, idea and relevance.
1. README: each step should already have updated it (README rule). Here, run every command in "Run it locally" once more on a clean `DATA_DIR`, set `MODEL_VERSION=safe-cap-qgb-v2` where v2 is the default to show, and fix anything that drifted.
2. [../05-data-and-sources.md](../05-data-and-sources.md): add NASA POWER (and FeederBW if S1 runs).
3. [../02-ppc-in-numbers.md](../02-ppc-in-numbers.md) still says "360,000+" prosumers: replace it with the ANRE figure (section 10.6), with its source.
4. **Ask P1** (agent): keep the offset state per station; log the rolling violation and abstention rates; raise an **alert** when the rolling violation rate is above `α`; optionally a "stations to check today" list ordered by offset and abstentions. These are actions in the theme's sense.
5. Pitch: the facts in section 10.6, marked with their sources.

### Stretch (cut first)
- **S1 · `eval/feederbw-check`.** FeederBW (KIT and Netze BW): 200 real German low-voltage feeders, 1-minute active/reactive power, **voltage** and currents, April 2023 → March 2025, hourly weather per feeder, metadata with installed PV, batteries, EV chargers, heat pumps; CC BY 4.0; Zenodo 17831177 (five zips of 1.7 GB; one is enough); loaders at github.com/KIT-IAI/FeederBW. Use: retrain the PV/load forecast on one batch and report it next to Ausgrid; check measured voltage against the 1.05 pu rule. External test only, never mixed into training. Serves: ML quality, idea relevance (European data).
- **S2 · second grid family (P3).** Labels on the ENWL / University of Manchester 25 real UK low-voltage networks (about 131 feeders, OpenDSS, released for research) or the CSIRO 23 representative Australian networks (OpenDSS, github.com/csiro-energy-systems/RepresentativeLVNetworks). Read the licence first. We already have `opendssdirect`. Serves: robustness across grids.
- **S3 · `ml/weather-by-location`.** After PR #26 is merged, each Ausgrid house has a postcode, latitude and longitude (`DATA_DIR/reference/`). Download NASA POWER for the station's houses' centroid (or a few points) instead of one Sydney point, and compute sun position and clear-sky sunlight at that centroid. Keep the step 01 availability rule and the step 02 feature names, so nothing else changes. Measure on the folds; keep it only if it helps. Serves: ML quality, and removes a stated limit (section 6). README: the new download option (README rule).

---

## 8. Production readiness
Definition of done for P6 (adapted from Breck et al., "The ML Test Score", reported):
- [ ] Every new feature has an `available_at` test; weather is optional at prediction time.
- [ ] `metadata.json`: git sha, labels and weather SHA-256, folds, chosen setting, `γ`, `τ`, start offset, `α`, crew budget result, scikit-learn version.
- [ ] v1 still loads; `MODEL_VERSION=safe-cap-qgb-v2` switches; rollback is the same variable.
- [ ] Property tests: quantiles ordered and in [0, 1]; limit in [0, 1]; PV forecast 0 at night.
- [ ] Evaluation deterministic; the test year read once (step 08).
- [ ] The agent logs the rolling violation and abstention rates and alerts above `α` (P1).
- [ ] Guard and kill switch unchanged: no limit is sent without the guard's pass.
- [ ] Models are loaded once at API start (existing `predict` cache); artifacts come only from our own `ARTIFACT_URI` (joblib is fine for our own files; use skops if models ever come from elsewhere).
- [ ] The live agent runs the input checks: missing, stale or out-of-range readings abstain (step 11).
- [ ] Labels used for training come from the power flow in the ML schema (step 10); mock labels are never reported as results.
- [ ] Every pull request that changes how the project runs updates `README.md` (README rule).
- [ ] `make smoke`, `python -m pytest`, `python -m ruff check src tests` pass on every branch.

---

## 9. Skills and tools
Claude Code skills available in this setup and when to use them:

| When | Skill or tool |
|---|---|
| Start of each step | `superpowers:writing-plans`: turn the step into a short plan |
| Writing code | `superpowers:test-driven-development`: acceptance tests first |
| A number looks wrong (drift, a bad fold, a leak) | `superpowers:systematic-debugging` before changing anything |
| Library questions (scikit-learn 1.9, pandas, pandapower, OpenDSS) | Context7 MCP for current documentation |
| Before saying "done" | `superpowers:verification-before-completion`: run the acceptance commands and paste the output |
| Before the PR | `/code-review`, then `/simplify` to keep the code short and readable |
| Plots for the error analysis and slides | `dataviz` |
| Slides | `pptx` (if the deck is PowerPoint) |

Found but not needed for P6 (section 10.7): third-party skill packs (K-Dense scientific skills), Hugging Face, Kaggle and Jupyter MCP servers. Third-party skills run code: review before installing. Optional later: project skills in `.claude/skills/` for "train and evaluate" and "leakage audit".

---

## 10. Research context
Everything found in the research session, so no one has to search again. Status words as in section 0.

### 10.1 Weather and sunlight
| Source | What | Coverage | Licence / access | Use | Status |
|---|---|---|---|---|---|
| NASA POWER | hourly sunlight, temperature | global, hourly from 2001-01-01 (covers Sydney 2010–13) | public API | **P6 weather** | checked |
| Open-Meteo historical weather (ERA5) | hourly reanalysis | global, from 1940 | free API | alternative to NASA POWER | checked |
| Open-Meteo historical forecast API | archived weather forecasts | most models from about 2022 | free API | leak-free forecasts for post-2022 data; **not** usable for 2010–13 | checked |
| Meteostat | station observations | global | **CC BY 4.0**, commercial use allowed | Bucharest temperature for the thermal model | checked |
| PVGIS (EU JRC) | hourly sunlight and PV yield per kWp | Europe incl. Bucharest, 2005–2023 | free | Romanian PV profiles | reported |
| Copernicus CAMS radiation | 15-min sunlight | Europe/Africa (not Sydney 2010–13) | free account | Bucharest high resolution | reported |
| NREL NSRDB | US-centred sunlight | mostly US | open | fallback | reported |
| Romanian ANM | weather observations | Romania | data.gov.ro | live source for a Romanian deployment | reported |
| Renewables.ninja, Sheffield Solar PV_Live, Open Climate Fix UK PV | simulated or UK PV | Europe / UK | open | not needed | reported |
| pvlib | clear-sky models, sun position | library, BSD-3 | — | not used: Haurwitz in 3 lines instead | reported |

### 10.2 Load, PV and grid data
| Dataset | Content | Licence / access | Use | Status |
|---|---|---|---|---|
| Ausgrid Solar Home | 300 homes, 30 min, PV and load, 2010–13; paper: Ratnam et al. 2017, DOI 10.1080/14786451.2015.1100196 | CC BY 3.0 AU (copy's README); copy by Pierre Haessig | **training** | in repo |
| SimBench | German LV/MV grids for pandapower | open | grid twin option | in repo |
| **FeederBW** (KIT, Netze BW) | 200 German LV feeders, 1-min P/Q/V/I, Apr 2023–Mar 2025, hourly weather, PV/battery/EV/heat-pump capacity | **CC BY 4.0**, Zenodo 17831177, ~8.5 GB in 5 zips | **S1** | checked |
| ENWL / U. Manchester LVNS | 25 real UK underground LV networks, ~131 feeders, OpenDSS, PV/EV/heat-pump profiles | released "to the research and engineering communities"; exact licence not read | **S2** | checked |
| CSIRO Representative LV Networks | 23 Australian LV networks (clustered from ~95,000), OpenDSS | LICENSE file present, terms not read | **S2** | checked |
| Swiss residential profiles (Zenodo 21398769) | 2,447 installations, 15 min, withdrawal and injection, 2023–24 | CC BY 4.0 | later | checked |
| GoiEner (Zenodo 7362094) | Spanish smart meters, hourly, 2014–22, no PV | page shows both CC BY 4.0 and CC BY-SA | later (sample already in `data/goiener`) | checked |
| ENTSO-E Transparency | Romania system load and solar, hourly, 2015+ | free, registration | context | reported |
| Transelectrica | Romanian load forecasts and archives | public | context | reported |
| Low Carbon London | 5,567 London homes, 30 min, 2011–14, no PV | open | later | reported |
| ETT (ETDataset) | Chinese transformers, load + oil temperature, 2016–18 (2 transformers in the small set) | licence not read | sanity check of the thermal model | checked |
| IEEE European LV test feeder | one 55-load benchmark network | IEEE | second grid | reported |
| NREL SMART-DS, PNNL taxonomy feeders, pylovo (TUM), DINGO | synthetic grids | open | only if S2 sources fail | reported |
| UK Power Networks, SSEN portals | LV feeder aggregates | login needed | later | reported |
| UNSW Solar Analytics / Energy Data Platform | household voltage, PV, 5 min | on request | best real-voltage source, not open | reported |
| Pecan Street, UK SERL | detailed homes | restricted (commercial licence / accredited researchers) | no | reported |
| Adobe | no public energy or weather dataset exists | — | no | checked (search) |

### 10.3 Papers
| Paper | Finding | Use in P6 | Status |
|---|---|---|---|
| Gibbs, Candès, "Adaptive Conformal Inference Under Distribution Shift", arXiv 2106.00170 | update the miss level online from observed misses | step 04 mechanism | checked |
| Stratigakos, Wen, Spyrou, Pinson, "Decision-calibrated prediction sets for robust power system operations", arXiv 2606.02081 (2026) | calibrating to the constraint-violation target lands within ~3 pp; coverage-based calibration overshoots by >11 pp | step 04: tune on violations | checked |
| Romano et al., Conformalized Quantile Regression, arXiv 1905.03222 | calibrates quantile models; assumes exchangeable data | not used (does not fix drift) | reported |
| Hertel, Pütz, Kolar, Schäfer, Mikut, Hagenmeyer (KIT), arXiv 2607.15705 (2026) | Transformers beat established load-forecasting methods by 6.6–10.7%; Chronos-2 zero-shot competitive on 2 of 3 datasets; long context, covariates and **continuous retraining** matter | supports step 03 | checked |
| Kaas, Treutlein, …, Hagenmeyer (KIT), arXiv 2607.01966 (2026) | on 200 FeederBW feeders Chronos-2 was best against six baselines (no numbers in the abstract) | reason for "not now" | checked |
| Quessongo, Gebbran, Unsihuay-Vila, arXiv 2608.23444 (2026) | fair DOEs with the Jain index close to 1; fairness costs curtailment | step 05 Jain | checked |
| Aydin, Holt, Almassalkhi, arXiv 2504.18905 (2025) | ≥50% more PV hosting capacity with ≤5% annual PV curtailed (IEEE-37 feeder) | pitch | checked |
| Mishra, Hota, Lankeshwara, Sharma, Tushar, Bajpai, arXiv 2607.25328 (2026) | flexible DOEs as ranges reduce curtailment on an Australian LV network | later idea; affiliation not shown | checked |
| Treutlein et al. (KIT), arXiv 2409.19713 (2024) | pseudo-measurements for 2,323 real LV feeders from metadata + weather; XGBoost/MLP beat linear | feeder metadata matters | reported |
| "On the importance of clear-sky model…", arXiv 2503.07647 | forecast the clear-sky index, not raw sunlight | step 02 | reported |
| Yang et al., meta-analysis of solar forecasting skill, arXiv 2208.10536 | report skill against a reference | step 05 | reported |
| Hierarchical reconciliation, arXiv 2411.01528 | small gains (median MAE −2.8% reported) | not now | reported |
| Scolari et al. (behind-the-meter PV disaggregation, IEEE TPWRS) | separate hidden PV from net load | idea for the net-only limit | reported |
| Ochoa et al., "Basics of Operating Envelopes"; Project EDGE final report (ARENA); SA Power Networks flexible exports | DOEs in real Australian networks | pitch | reported |
| Breck et al., "The ML Test Score" (Google) | production checklist | section 8 | reported |

### 10.4 Libraries and frameworks
| Library | Licence | Decision |
|---|---|---|
| scikit-learn `HistGradientBoostingRegressor` | BSD-3 | **keep** (in repo) |
| MAPIE v1 (`ConformalizedQuantileRegressor`, `TimeSeriesRegressor(method="aci")`, `adapt_conformal_inference`) | BSD-3 | reference only (checked) |
| conformal-tights (superlinear-ai) | MIT | not needed: calibrates coverage |
| quantile-forest (zillow) | Apache-2.0 | optional second model, not in P6 |
| crepes | BSD-3 | not needed |
| OpenSTEF (Alliander / LF Energy), v4 monorepo | MPL-2.0 | patterns only; too heavy |
| Nixtla mlforecast / statsforecast / neuralforecast, skforecast, Darts, sktime | Apache / BSD | not needed |
| Open Climate Fix Quartz solar forecast, PVNet | **MIT** | optional external PV baseline |
| alliander-opensource/transformer-thermal-model | MPL-2.0 | already our reference for `thermal.py` |
| pandera, Great Expectations, MLflow, Evidently, NannyML, DVC, skops, hypothesis | various | not in P6; hypothesis is a candidate for property tests (ask P1 for the dev extra) |
| skl2onnx | — | not needed; support for quantile HGB not confirmed |

### 10.5 GitHub projects
| Repo | Licence | What | Use |
|---|---|---|---|
| akamaxe/kapacitet-plus | MIT | Swedish LV neighbourhood twin. Static study 413 kW; day-ahead envelopes without forecast 588 kW; hourly study, no control 609 kW; perfect foresight 787 kW (1.9×), 2–3% curtailment, 3% anchored on German EnWG §11(2) | pitch: "the step from 609 to 787 kW is what a forecast would have to buy" (their words) |
| aaquila-ka/OperatingEnvelopes (UQ MEng thesis) | not asserted | wrong cable records: envelope 3.66 kW instead of 1.95 kW (+88%), 7 homes above 253 V | pitch and limits: why the guard stays; read only |
| Jouqio/climate-aware-pv-forecasting | not asserted | same-hour weather inflated skill 1.7–3.4× (10 sites) | evidence for the availability rule |
| fsossan/PV-Disaggregation (EPFL) | MIT | hidden PV from net load and sunlight (MATLAB) | idea only |
| ZhisenJiang/NB-based-DOE-allocation | none | bargaining-based DOE allocation | skip (no licence) |
| Future-Power-Networks/MAPDN | MIT | RL voltage control on pandapower | skip |
| KIT-IAI/FeederBW | not asserted | FeederBW loaders | S1 |
| pierre-haessig/ausgrid-solar-data | CC BY 4.0 | source of our Ausgrid copy | cite |

No open-source project predicts a one-hour-ahead safe export share with quantiles, abstention and a guard; the closest (Kapacitet+) uses perfect foresight or day-ahead limits without a forecast. P6 targets exactly that gap.

### 10.6 Romania, EU and pitch facts
| Fact | Source | Status |
|---|---|---|
| 385,791 prosumers, 4,281.86 MW installed, 151,040 with storage (31 Aug 2026); Ilfov 21,647 / 303.81 MW; Bucharest 8,307 / 134.94 MW; 476 MW in Jan 2022 | press reports of the ANRE file `anre.ro/wp-content/uploads/2026/10/Situatie-prosumatori_august_2026.pdf` | checked (press) |
| Earlier: 332,684 prosumers, 3,789 MW (30 Apr 2026) | same series | checked (press) |
| Law 160/2026 (in force 26 Jul 2026): monthly net compensation for prosumers ≤ 200 kW | press | reported |
| Germany, Solarspitzengesetz: new PV < 100 kW since 25 Feb 2025 without smart meter and control box may feed in only 60% of peak; EEG 2027 draft proposes 50% (not law) | German press and installer guides | checked |
| EN 50160: ±10% of 230 V (207–253 V) | standard summaries | reported |
| Kapacitet+, UQ thesis, Aydin et al. | sections 10.3, 10.5 | checked |

### 10.7 Skills, plugins and MCP servers found
| Item | Use | Status |
|---|---|---|
| github.com/anthropics/skills (official) | document and data skills | reported |
| K-Dense scientific-agent-skills | science/ML skill pack, third party | reported; review before installing |
| Hugging Face MCP, Kaggle MCP, Jupyter MCP | dataset search, notebooks | reported; not needed |
| Context7 MCP | current library docs | connected in this setup |

---

## 11. Where each part comes from
| Part of P6 | Source | Status |
|---|---|---|
| Quantile GBM, 4 settings, pinball, sort + clip, abstention `τ`, `α` = 2%, crew budget, baselines, robustness, explanations, error analysis | our P2 code and briefs | in repo |
| Labels by power flow, scenarios A / B / B-VAR | P3 code; [../04-chosen-idea.md](../04-chosen-idea.md) | in repo |
| Theme requirements and scoring | PPC theme document; [../01-theme-and-criteria.md](../01-theme-and-criteria.md) | in repo |
| NASA POWER weather | NASA POWER hourly API documentation | checked |
| Weather only up to `t`; conservative `available_at` | our `available_at` rule; Jouqio repo (leakage 1.7–3.4×) | in repo, checked |
| Clear-sky features | arXiv 2503.07647; Yang et al. arXiv 2208.10536 | reported |
| Haurwitz formula instead of pvlib | team choice (no new dependency); formula from the Haurwitz clear-sky model | team choice |
| Temperature, net ÷ clear-sky features | team choice | team choice |
| Dropping neighbour PV | net-only rule in `features.py` | in repo |
| Four quarterly folds | our reading of `split.py`; KIT arXiv 2607.15705 | checked |
| Online offset | Gibbs and Candès arXiv 2106.00170; MAPIE v1 | checked |
| Tune on violations | Pinson et al. arXiv 2606.02081 | checked |
| Skill score against "last known" | Yang et al. (reference forecasts); the choice of reference is ours | reported, team choice |
| Jain index on each house's exported share | Quessongo et al. arXiv 2608.23444; README's "no fairness analysis" | checked |
| No pretrained model | theme rule (trained by the team); KIT arXiv 2607.01966 | checked |
| Weather-missing robustness, 10% blanking option | theme ("missing data"); team choice | team choice |
| v1 → v2 "what we tried" | theme text; `error_analysis.py` | in repo |
| Production checklist | Breck et al.; our `docs/10-cloud.md` | reported, in repo |
| Hour estimates | team choice | team choice |
| Step 10 (label schema), step 11 (live input checks), label runtime | measured on 2026-11-08 by running `src.grid.labels`, `src.ml.labels.validate` and the `SOURCE=model` API | checked |
| Step 12 (thermal ambient) | `src/agent/model_wiring.py` (`AMBIENT_C = 20.0`, "assumed constant") | in repo |
| Merge order with PR #25; S3 house locations | PR #25 and #26 descriptions and file lists (GitHub) | checked |
| README rule | team decision, written in `README.md` | in repo |

---

## 12. Claims we rejected
Research agents reported these; checking showed them wrong or unsupported. Do not use them.

| Claim | What is true |
|---|---|
| Meteostat is non-commercial (CC BY-NC) | CC BY 4.0, commercial use allowed (checked) |
| CQR guarantees coverage even when the data distribution shifts | CQR assumes exchangeable data; drift needs an online method (ACI) |
| ONNX export supports quantile `HistGradientBoostingRegressor` | not confirmed on the skl2onnx page; not needed |
| Open Climate Fix Quartz is Apache-2.0 | MIT (GitHub API) |
| ETT has 39–69 transformer stations | the small set has 2 transformers; the large-set count is inconsistent on the page |
| Liander publishes measured voltage | its page shows maps, not measurements |
| arXiv 2607.25328 is from Politehnica Bucharest | the abstract page shows no affiliations; it uses an Australian network |
| Germany's EEG 2027 draft proposes a 70% cap | the draft proposes 50%; the current rule is 60% |
| Romania has 332,684 prosumers (as the latest figure) | superseded: 385,791 on 31 Aug 2026 |
| Chronos-2 MAE 3.84 kW, coverage 89.75% on FeederBW | not in the abstract; unverified |
| A skill score formula averaging climatology and persistence RMSE | wrong; skill = 1 − error / reference error |
| A "3–6 point" drop in violation rate from calibration | impossible from a 2.3–3.5% starting rate |
| "15–25%", "5–15%", "0.5–1.5 pp" gains; "2 weeks" efforts | no source; dropped |
| "QRF by Meinshausen and Athey in the GEFCom2014 top 5" | unsupported; dropped |
| Skill pack "250K users", "every community plugin security-scanned" | unsupported; dropped |
| Ausgrid data downloadable from data.nsw.gov.au | not confirmed (page refused access); we use the Haessig copy |
| UK Power Networks feeder data details (dates, licence) | the page needs a login; unverified |

---

## 13. Not now, and why
| Idea | Why not |
|---|---|
| Chronos-2 or other pretrained models | theme rule (model trained by us), adds PyTorch, hard to explain; strong results but not needed for the core |
| OpenSTEF, mlforecast, Darts, sktime | a framework for a 300-line model |
| MAPIE, conformal-tights as dependencies | they calibrate coverage; we calibrate violations in about 30 lines |
| LightGBM / XGBoost instead of scikit-learn | small expected gain, new dependency |
| Neural power-flow surrogates (GNN, PINN), RL voltage control, polyhedral conformal sets | pandapower labels are fast enough; out of scope for 24 h |
| Neighbour PV features | break the net-only rule |
| Hierarchical reconciliation | small reported gains |
| Flexible (range) envelopes, fairness-optimal allocation | research ideas for after the hackathon |
| Open-Meteo archived forecasts as features | only from about 2022, our labels are 2010–13 |

---

## 14. Decisions for the team
1. Change rule 2 to the four quarterly folds (step 03).
2. Confirm `α` = 2% (`VIOLATION_TARGET`) and the crew budget (`CREW_CASES_PER_DAY`, default 20).
3. The scenario mapping and station ids with P3 (step 00).
4. Where label generation runs: laptop or the Azure batch job (ask before any Azure run).
5. The live weather source for the deployment story: Open-Meteo or ANM.
6. Whether to run S1 (FeederBW), S2 (second grid family) and S3 (weather by location).
7. Merge PR #25 before steps 02–07 and 11; merge PR #26 if S3 or the P4 map will use the house locations.
8. Who owns steps 10 (P3, `src/grid/`) and 11–12 (P1, `src/agent/`).

---

## 15. Hand-off
Post one line per merged step, then the final line.

- [ ] 00 setup: "PR #25 merged; labels take <…> per week of data per scenario; mapping A/B/B-VAR agreed: <…>."
- [x] 10: "grid labels write the ML schema; one real day trains." (PR #31, in the P6 pull request)
- [x] 11: "the live agent abstains on missing, stale or out-of-range readings."
- [x] 12: "hot-spot uses measured temperature when known."
- [x] 01: "weather for Sydney 2010–13 downloaded, SHA-256 <…>."
- [x] 02: "19 features; no-leak test passes."
- [x] 03: "v2 trains on four quarterly folds; per-quarter q05 violation rates <…>." Code done; the rates come with the real labels (step 08), mock rates are not results.
- [x] 04: "offset γ = <…>, τ = <…>, flagged per day max <…> vs crew <…>." Code done; the numbers come with the real labels (step 08).
- [x] 05: "v1 and v2 side by side; skill and Jain columns; weather-missing case."
- [x] 06: "explanations show the offset and weather factors."
- [x] 07: "what-we-tried table v1 → v2 on the out-of-sample year."
- [ ] 08: "final evaluation in eval/final."
- [~] 09: "README and data docs updated; P1 requests posted."

Final: "P6 merged: safe-cap-qgb-v2 with weather features, quarterly folds and an online offset. Test year, scenarios A / B / B-VAR: violations <…>, export index <…>, skill vs last known <…>, Jain <…>; v1 next to it in eval/final."
