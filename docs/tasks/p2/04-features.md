# P2-04 · `ml/features`

| | |
|---|---|
| Gate | G1 |
| Target | T+2:00–3:00 (20:00–21:00); parallel with 05 |
| Depends on | [03](03-labels-io.md) |
| Unblocks | [06](06-quantile-model.md), [07](07-predict.md) |
| Size budget | ~250 changed lines |
| Cut | never |
| Covers | ML quality (features built with a clear reason); mandatory traceability (no leakage) |

## Context
The model decides at time `t` the limit for the interval starting at `t + 60 min` (horizon two half-hours). It may use only what is known at `t`. The contract function is `ml.features.build(station_state, t) -> features` ([../../09-contract.md](../../09-contract.md)).

## Goal
One feature builder used both for training (vectorised over history) and for live prediction (one point), with tests that prove it never looks into the future.

## Files
- `src/ml/features.py`
- `src/ml/sun.py` (if 03 did not already add the sun function)
- `tests/ml/test_features.py`

## Features (each with its reason; keep this table in the module docstring)
All power values are divided by `kwp_total` so the model is not tied to one station size.

| Name | Definition at decision time `t`, target `T = t + 60 min` | Reason |
|---|---|---|
| `net_now` | `net_kw` of the interval ending at `t` | Current state of the station |
| `net_lag_1`, `net_lag_2`, `net_lag_3` | `net_kw` 30, 60, 90 min before that | Trend (clouds arriving, load rising) |
| `net_same_T_yesterday` | `net_kw` at `T − 24 h` | Daily pattern |
| `share_last` | `safe_share` of the interval ending at `t` | Persistence; the "last known" baseline as input |
| `share_same_T_yesterday` | `safe_share` at `T − 24 h` | Daily pattern of the limit |
| `sun_elev_T` | Solar elevation at the middle of `T` | Clear-sky proxy; known in advance from time alone |
| `sun_elev_now` | Solar elevation at the middle of the interval ending at `t` | With `net_now`, shows how cloudy it is now |
| `hour_sin`, `hour_cos` | Hour of `T`, Sydney local | Daily cycle |
| `doy_sin`, `doy_cos` | Day of year of `T`, Sydney local | Season (southern hemisphere) |
| `is_weekend` | Of `T`, Sydney local | Load pattern |

Rule: a value is usable only if its `available_at <= t`. Measured values and labels of an interval are available at its end (`interval_start + 30 min`).

## Steps
1. `sun.py`: `solar_elevation(ts_utc, lat=-33.87, lon=151.21) -> degrees` (NOAA approximation, ~30 lines, no extra dependency unless `pvlib` is already pinned).
2. `build_frame(labels_one_station) -> pd.DataFrame`: vectorised, one row per decision time, columns = features + `decision_time`, `target_start`, target `safe_share` at `T`. Use shifts on a complete half-hour index (reindex first so gaps become NaN, never closing the gap).
3. `build(station_state, t) -> dict`: the single-point version for the API. It must produce exactly the same values as `build_frame` for the same `t` (it can call the same internal code on a slice ending at `t`).
4. `FEATURES: list[str]` as the single source of the column order. The model and the explainer use it.

## Interface
```python
FEATURES: list[str]
def build_frame(labels: pd.DataFrame) -> pd.DataFrame: ...
def build(station_state: pd.DataFrame, t: pd.Timestamp) -> dict: ...  # keys: FEATURES + pt_id, decision_time, target_start
```

## Acceptance (the leakage tests are the point of this task)
- **Future-perturbation test:** take a random `t`, change every value with `available_at > t` to garbage, rebuild: features at `t` are unchanged.
- **Batch = single point:** for 200 random `t`, `build` equals the row of `build_frame`.
- Sun: elevation at solar noon in Sydney ≈ 79.6° on 21 December and ≈ 32.7° on 21 June (±1°).
- A missing input interval gives NaN in the affected features, not 0, and does not shift other rows.

## Definition of done
- The feature table with reasons is in the docstring (it goes in the README later).
- Leakage tests pass.

## Pitfalls
- "Same hour yesterday" is relative to the target `T`, not to `t`.
- Do not use `gg_kw` or `gc_kw` separately: in a real deployment only net values are visible at the meter (11 checks this).
- Hour and day features from Sydney local time, storage in UTC.

## Hand-off
"P2-04 merged: `ml.features.build(station_state, t)` and `build_frame`, leakage tests pass. Feature list in `FEATURES`."
