# ML pipeline audit: open findings

A critical audit of the data, labels, training and evaluation of the safe-cap model. It was first written on 2026-11-07 against `16f8d30`. It was re-checked on 2026-11-08 against `main` at `eabaf20`, and the status table was updated after the P6 pull requests were merged (`main` at `550da39`). Only what is still open is described in full; what has been fixed since is in the table at the end.

Every finding names the code it rests on as `file:line` on `eabaf20`. **Confirmed** means it was measured or reproduced. **Suspected** means it was read in the code but not measured.

The scripts and tested fix prototypes behind the numbers are on the branch [`audit/prototypes`](https://github.com/robbertpopa/ppc-smarthack/tree/audit/prototypes) (`audit/check_*.py`, `audit/proposals/`, `audit/tests/`). They are kept out of `main` on purpose: they are not wired into `src/`, and CI does not run them.

## Verdict

The code is careful about time: features use only what is known at decision time (0 differences between `build` and `build_frame`, 0 look-ahead in a perturbation test), the test year is sealed, and the evaluation is reproducible. **No model number is a result yet.** The models are trained on mock labels, and the real labels are not usable for training until the team chooses the grid scenarios (C1).

## Critical

**C1: No model has been trained on real labels, and scenario A gives constant labels.** Confirmed.
- `src/ml/labels.py:190`: the mock target is a made-up formula (`0.9 − 0.6 pv/kWp + 0.3 load/kWp + noise`), not a power flow. Every model metric so far (coverage, export index, beats yesterday) measures how well gradient boosting learns that formula.
- The real generator writes the training schema with #31. At its default settings (400 kVA, PV ×1, 210 houses, 365 kWp) every one of 84 real labels on 2011-01-10 → 12 is `safe_share = 1`, with `binding = none`. At PV ×4, 32 % bind on the transformer and the lowest share is 0.29. A model trained on an all-ones target learns a constant, so violation and abstention rates become trivial.
- Fix: run `--days 7` at a few transformer sizes and PV scales, choose settings where a limit binds in a meaningful share of daylight intervals, and write them into `SCENARIO_GRID` and `docs/04-chosen-idea.md` (P6 step 00). Then generate two years and retrain (step 08).

## Major

**M2: The violation rate is diluted by intervals with no constraint, and it ignores how large a violation is.** Confirmed on mock labels.
- `src/eval/metrics.py:108-115`: the denominator is every scored daylight interval, including those with `safe_share = 1`, where q05 cannot violate anything. A violation is binary: 0.001 above the limit counts as much as 0.3.
- On mock labels, 21 % of intervals have `safe_share = 1`; the violation rate is 6.7 % overall and 8.6 % where the limit matters. This gets worse as real labels approach all ones (C1).
- Fix: also report `violation_rate | safe_share < 1`, the energy exported above the safe limit (kWh), and the 95th percentile of the excess, by season and hour.

**M3: Daylight-only labels make the model abstain every morning.** Confirmed.
- `src/grid/labels.py:37` keeps 06:00–20:00 local with PV > 0, and the mock keeps sun above the horizon (`src/ml/labels.py:188`). The features take `net_*` from the label file (`src/ml/features.py:85`), so the first hour after sunrise never has `net_now`.
- 12.3 % of rows with a target have no `net_now`, and 14.4 % abstain on the input checks alone (`src/ml/abstention.py:156`). This also shows live, now that #37 runs the checks in the agent. The trees learn "NaN means morning", while a real meter reports net at night too.
- Fix: build `net_*` from `profiles.parquet` over all 48 intervals, so that only `share_last` can be missing. On the first quarter of 2011 the prototype brings missing `net_now` from 11.6 % to 0.1 %, and input-check abstention from 11.6 % to 3.9 %.

**M4: The model is most confident where it is most often wrong, at the edges of the day.** Confirmed on mock labels, suspected on real ones.
- `src/ml/abstention.py`: abstention uses only the spread `q90 − q05`. At 06:00 and 17:00 local, q05 violates in 11.5 % and 10.7 % of cases with a spread of 0.02–0.05, below any threshold. q90 covers 72 % instead of 90 %. To reach 2 % violations the model abstains in 77 % of validation intervals.
- Fix: P6 step 04 (online offset), or conformal calibration of q05 per hour or sun-height bin, and report coverage per hour.

**M1: The validation period is one season.** Confirmed.
- `src/ml/split.py:14-15`: hyperparameters and the abstention threshold are chosen on April–June 2012 only, and the test is a full year.
- Fix: P6 step 03 (quarterly folds) is merged through #38 and #40; it needs real labels to show its effect.

**S1: Two Ausgrid readers clean the data differently.** Confirmed.
- `src/grid/ausgrid.py:6` reads the raw CSV with no cleaning. `src/ml/ausgrid.py:27` caps generation at 1.2 × kWp and keeps the `Row Quality` flag. In 2011-12, 1,111 readings that `profiles.parquet` nulls out (for example 2.37 kW on a 1.92 kWp house) still go into the power flow, so labels and exported-energy numbers come from different data.
- The grid code also names houses `3` where the ML code uses `AG-0003` (#31 maps them).
- Fix: have the label generator read `profiles.parquet`, as a separate PR.

**S2: `src.ml` and `src.eval` import each other.** Confirmed.
- `src/ml/train.py:23`, `src/ml/abstention.py:22` and `src/ml/baselines.py:21` import `src.eval.metrics`, and `src/eval/error_analysis.py:23` imports `src.ml`. `src/ml/predict.py:88` imports `src.ml.train`, so serving a forecast loads the training code.
- Fix: move the metric functions into `src/ml/metrics.py`, and the quantile helpers out of `train.py`.

## Minor

**m1: The PV and load forecast is compared with a baseline that cannot win.** Confirmed.
- `src/ml/forecast_pv_load.py:92`: "same time yesterday" gives one value for every quantile, a band of zero width, so its pinball loss on q10 and q90 is penalised by construction. `beats_yesterday: true` everywhere says little.
- Fix: a probabilistic baseline, such as empirical quantiles of yesterday's residuals at the same hour.

**m2: Some broken readings are not filtered.** Confirmed.
- These count as valid: 2,614 house-days with no PV while the sun is above 30°, 97 stuck series, 172 night-time generation readings, and 5,207 readings between 1.0 and 1.2 × kWp.
- The kWp comes from the connection application (Ausgrid notes, column 3), so PV above kWp can be a wrong kWp rather than a broken meter.
- Fix: mark those days and series as missing, and count each rule in `src/ml/DATA.md`.

**m3: Test-year weather sits next to the working data.** Confirmed.
- `src/ml/weather.py:296`: `fetch` defaults to `--end-year 2013`, so weather for July 2012 → 2013 is downloaded with the rest. `weather.load` applies `available_at`, so features cannot use it early, but exploratory work can touch it.
- Fix: default `--end-year 2012` and keep the test year behind the same flag as the Ausgrid file.

**m4: `share_last` needs a power flow every 30 minutes in production.** Suspected.
- `src/ml/features.py:85`: the feature is the label of the interval that just ended. Live, this needs meters on every house and a calibrated twin; the docstring says "only net values are used".
- Fix: document it, and test robustness to a noisy or missing `share_last`.

**m5: Dependencies are not pinned.** Confirmed.
- `pyproject.toml:11-12`: `numpy>=2.0` and `pandas>=2.2` have no upper bound and there is no lock file. Pandas changes can move time and DST handling.
- `src/ml/train.py:53`: `random_state` does not change the models (seed 0 and seed 1 give the same predictions), yet the metadata suggests it does.
- Fix: a lock file used in CI and Docker; drop the seed or make it matter.

**m6: The demo script picks a night interval.** Confirmed.
- `pitch/demo-script.md:19`: 10:00 UTC is 20:00–21:00 in Sydney. With the real model there is no PV then, and the "small spread, the model decides" story works only on the mock forecast.
- Fix: use 02:00 UTC (12:00–13:00 local), or show the station's local time.

**m7: After retraining, the agent serves the old plan for an interval it already planned.** Confirmed.
- `src/agent/service.py:169`: a plan id is the interval and the station, and an existing plan is returned as is. The action log keeps the plans across restarts. After a retrain, the same interval still shows the old model's limit until `LOG_URI` is cleared.
- Fix: put the model version in the plan id or in the reuse check, or say so in the runbook.

**m8: The plan's "uncertainty threshold" on the operator screen is not the model's.** Confirmed.
- The screen shows the station default (30 %), while the agent applies the model's threshold from `metadata.json` (12 % on the current mock model).
- Fix: show the threshold the plan used.

**C4 (downgraded): model metadata has no schema version.** Confirmed.
- On `main`, `src/ml/train.py:210` writes the top-level `abstention` key that `src/ml/abstention.py:197` reads. A model saved by an older commit (`a3d8176`) lacks it, and then the agent abstains on every interval with "abstention threshold lookup failed".
- Retraining fixes it. A `schema_version` in `metadata.json`, checked on load, would name the cause instead.

## Fixed since the first audit

| Finding | Status |
|---|---|
| C2: the grid label schema was rejected by `src.ml.labels.validate` | merged, #31 |
| C3: the label generator defaulted to `--start 2013-01-01` | merged, #31 (start required, test year needs `--final-eval`) |
| M6: houses changed with the run window | merged, #31 (later runs keep the station's houses) |
| S4: no test between the grid writer and the ML reader | merged, #31 (`labels_io.load` on the generator output) |
| M5: no weather in the model | merged: weather loader (#36), weather features (#39), transformer ambient from weather (#40). Training does not pass weather to the features yet |
| Live agent ignored the input checks | merged, #37 and #41 (a broken check fails closed) |
| M1: one-season validation | code merged, #38 and #40 (quarterly folds) |
| M4: overconfident at the edges of the day | partly: online offset merged in #40 (P6 step 04); not measured on real labels |
| S3: Sydney hardcoded in `src/ml/sun.py:11` and `src/ml/config.py:12` | accepted: the data and the station are in Sydney; it matters only for a station elsewhere |
| S5: two definitions of a daylight interval | negligible: 56 intervals, 0.001 % of PV energy (customer 1: 0.1 of 4,866 kWh outside 06–20) |

## What works

- Ausgrid parsing matches the dataset notes. For 2010-11 the published means are consumption 6,980 kWh, generation 2,119 kWh and 1,253 kWh/kWp; `profiles.parquet` gives 6,978, 2,117 and 1,251. For 2011-12 it is within 0.2 %. DST days and the `0:00` column are handled correctly.
- Features use no future data: `build` equals `build_frame`, and a perturbation test with future values changes nothing.
- The sealed test year is excluded from download by default, and the split uses Sydney local dates.
- NASA POWER hour labels are the start of the hour: the solar zenith matches `src.ml.sun` at `HH + 30 min` (0.24°).
