# P2: ML and evaluation

**Owns:** `src/ml/`, `src/eval/`. Read first: [../08-parallel-plan.md](../08-parallel-plan.md), [../09-contract.md](../09-contract.md), [../04-chosen-idea.md](../04-chosen-idea.md), [../05-data-and-sources.md](../05-data-and-sources.md).

**Branch-sized briefs:** this role is split into one task file per branch in [p2/](p2/README.md) (order, dependencies, parallel lanes, acceptance tests).

## Goal
Train models that predict **the highest safe export limit one hour ahead**, with calibrated uncertainty, and prove with a separate test period that they beat simple baselines. Produce the evaluation table the jury will read.

## What you deliver
| By gate | Deliverable |
|---|---|
| G0 | Data download script (not data itself), notes on formats |
| G1 | Baselines and a first quantile model; `ml.predict` returns a valid `forecast` |
| G2 | Final safe-cap model with an abstention rule; PV and load forecasts (longer horizon) |
| G3 | `python -m src.eval.run` produces the whole evaluation table with one command |
| G4 | Error analysis and final numbers for the slides |

## Tasks

### Phase 0 (T+0–1)
- Write `src/ml/data.py` that **downloads** the data from the links in [05](../05-data-and-sources.md) into `data/` (git-ignored). Do not commit data.
- Ausgrid pitfalls: the 2010–2011 file has dates like `1-Jul-10` and no "Row Quality" column; 2012–2013 differs. Parse both formats. Fix 48 intervals per day.
- Build the arrays: gross generation (GG), consumption (GC), controlled load (CL), per-house panel capacity. Net load = consumption − generation.
- Agree with P3 on the label file format (see below).

### Phase 1 (T+1–5): first slice
- **Split in time, never random:** train until 2012-03-31, validation April–June 2012, test 2012-07-01 → 2013-06-30. Horizon: 2 half-hours (one hour).
- **Features** (only information available at decision time): station net load now and a few lags, same hour yesterday, hour of day, day of year, clear-sky proxy from sun position, last safe share.
- **Baselines** (all must be in the final table): fixed limit (0.36 share), last known safe share, same hour yesterday.
- **Model:** quantile gradient boosting (sklearn), quantiles 0.05, 0.10, 0.20, 0.50, 0.90. Use the cautious quantile (0.05) as the limit.
- Train on P3's labels. Until they arrive, train on the mock labels so the whole code path exists.

### Phase 2 (T+5–9)
- **Abstention rule:** `spread = q90 − q05`. Pick the threshold on the validation period, **searching thresholds in descending order and keeping the highest one that still meets the violation target** (the first version of this search went the wrong way and flagged 43.5% of intervals).
- Check calibration on validation and on test. In exploration the violation rate drifted between validation (1.3–1.8%) and test (2.3–3.5%): report it, do not hide it.
- PV forecast and load forecast (quantiles p10/p50/p90) for horizons of several hours; these feed the batteries. Same code, different targets.

### Phase 3 (T+9–13)
- `src/eval/run.py`: one command, deterministic (fixed seeds), prints the final table and saves it as CSV and Markdown.
- **Robustness:** drop 20% of readings (set to missing, never 0), add 30% noise, and censor production (when the limit curtails PV, the meter no longer shows the potential). Report degradation per case.
- **Explanations:** permutation importance (global) and local ablation (per decision: which feature moved the limit most).

### Phase 4 (T+13–17)
- Error analysis: where does the model fail (sunrise/sunset, cloud days, weekends)? Put 2–3 plots or tables in the README.
- Final numbers for the slides. Every number on a slide must come from the script.

## Cloud (your part is small, see [../10-cloud.md](../10-cloud.md))
- Read and write only through `DATA_DIR` and `ARTIFACT_URI` (a path or an `s3://` URI); no absolute paths.
- Write a `metadata.json` next to every model: git sha, data hash, training period, metrics.
- Keep training and `src/eval/run.py` deterministic (fixed seeds), so the cloud run matches the local one.
- The prediction must run inside our API container; no external model API.

## Interfaces
- **You consume:** P3's label file (`labels.parquet`: `pt_id`, `interval_start`, `safe_share`, plus the per-interval aggregates used as features), the contract.
- **You provide:** `ml.predict(features) -> forecast` and `eval/run.py` output to P1 and the pitch.

## Definition of done
- Time-separated test; baselines in the table; the same script reproduces the numbers.
- The model runs in our code (no external API).
- Abstention rate and violation rate reported together.
- Missing values stay missing; no leakage from the future (`available_at <= decision time` checked).

## Pitfalls
- Net load hides self-consumption; in a real deployment only net values are visible. Evaluate once with net-only inputs.
- The safe share can be non-monotone in rare cases; if P3 reports it, handle it (coarse scan before bisection).
- Calibration: do not tune on the test period.
- Time zones: Ausgrid is Sydney local time; do not mix with UTC silently.

## If you fall behind
Keep: baselines, one quantile model, the evaluation table. Cut first: PV/load forecasts, censored-data test, local explanations.
