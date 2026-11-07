# P2-09 · `ml/pv-load-forecast`

| | |
|---|---|
| Gate | G2 |
| Target | T+7:00–9:00 (01:00–03:00) |
| Depends on | [07](07-predict.md); horizons agreed with P3 (batteries) |
| Unblocks | P3's battery logic (state of charge planning) |
| Size budget | ~250 changed lines |
| Cut | **first** if behind (the core does not need it) |
| Covers | ML quality (a second model, also against a baseline) |

## Context
Batteries need to know how much sun and load are coming over the next hours. The contract already has `pv_kw` and `load_kw` (p10/p50/p90, station totals) on `forecast`, and `horizon_min` for longer horizons ([../../09-contract.md](../../09-contract.md)). Same code as 06, different targets.

## Goal
Quantile forecasts of station PV and load for several horizons, each compared with a "same time yesterday" baseline, exposed through `predict(features, horizon_min)`.

## Files
- `src/ml/forecast_pv_load.py` (targets, training, report)
- `src/ml/features.py` (only: a `horizon_min` parameter for the target time; default 60 keeps 04's behaviour unchanged)
- `src/ml/predict.py` (only: fill `pv_kw` and `load_kw`)
- `tests/ml/test_pv_load.py`

## Steps
1. Horizons: default `(60, 180, 360)` minutes; confirm with P3. One model per target, quantile and horizon (`HistGradientBoostingRegressor`, quantiles 0.10, 0.50, 0.90, same settings and seed rules as 06).
2. Targets: station `pv_kw` and `load_kw` at `T = t + horizon`. Features: the 04 set computed for that `T` (sun elevation and calendar at `T`; lags at `t`).
3. Baseline: value at `T − 24 h`. Report pinball loss and p10–p90 coverage on validation for model and baseline. If the model does not beat the baseline at a horizon, say so and still ship the better of the two for that horizon (state it in metadata).
4. Save under `ARTIFACT_URI/models/pv-load-qgb-v1/<pt_id>/` with `metadata.json` (same fields as 06).
5. `predict(features, horizon_min=60)` fills `pv_kw` and `load_kw`. For `horizon_min != 60`, `safe_cap_share` and `spread` are `null` (the safe-cap model is one hour ahead only); the planner must not read them.

## Acceptance
- Rearranged quantiles are ordered; PV is 0 when the sun is below the horizon at `T` (enforce: set p10/p50/p90 to 0 there).
- `predict(…, horizon_min=180)` returns a valid contract object with `safe_cap_share = null`.
- Validation table with model vs baseline per horizon posted in the group.

## Definition of done
- P3 reads the forecasts for batteries; the comparison with the baseline is recorded.

## Pitfalls
- Changing `features.py` must not change any value for `horizon_min=60` (04's tests must still pass unchanged).

## Hand-off
"P2-09 merged: PV and load p10/p50/p90 for 60/180/360 min via `predict(features, horizon_min=…)`. Model vs baseline (pinball): <…>."
