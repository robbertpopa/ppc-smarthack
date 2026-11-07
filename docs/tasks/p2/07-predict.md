# P2-07 · `ml/predict`

| | |
|---|---|
| Gate | G1 (the end-to-end demo at T+5 needs it) |
| Target | T+4:00–5:00 (22:00–23:00) |
| Depends on | [06](06-quantile-model.md), P1's `forecast` dataclass in `src/common/` |
| Unblocks | P1's planner on the real model, [08](08-abstention.md), [09](09-pv-load-forecast.md), [12](12-explanations.md) |
| Size budget | ~150 changed lines |
| Cut | never |
| Covers | Mandatory "the model runs in our code"; Agent (every decision traceable to a prediction) |

## Context
P1's `agent.plan(forecast, grid_state, config)` consumes contract object 1, `forecast` ([../../09-contract.md](../../09-contract.md)). Until now P1 used the mock; this task replaces it with our model, inside the API container, with no external API.

## Goal
`ml.predict(features) -> forecast` returns a valid contract object from the trained model, fast enough for the API.

## Files
- `src/ml/predict.py`
- `src/ml/__init__.py` (export `predict`, `features`)
- `tests/ml/test_predict.py`

## Steps
1. Load the models lazily once per process (cache by `model_version` and `pt_id`). `MODEL_VERSION` from the environment, default `safe-cap-qgb-v1`.
2. Input: the dict from `features.build` (keys `FEATURES` + `pt_id`, `decision_time`, `target_start`). Build the row in `FEATURES` order; missing keys become NaN, never 0.
3. Predict the five quantiles, apply `rearrange` (06), fill the forecast:
   - `pt_id`, `interval_start = target_start`, `horizon_min = 60`
   - `safe_cap_share = {"q05": …, "q10": …, "q20": …, "q50": …, "q90": …}`, `spread = q90 − q05`
   - `pv_kw = null`, `load_kw = null` (filled by 09)
   - `available_at = decision_time`, `model_version`, `provenance = "forecast"`, `source_ref = "ml/train.py@<git sha from metadata>"`
4. Return P1's dataclass (or a dict that validates against it, whichever the contract code expects).
5. If no model file exists, raise a clear error naming the expected path. Do not silently return the mock: P1 decides when to use mocks.

## Interface
```python
def predict(features: dict, horizon_min: int = 60) -> Forecast: ...
```

## Acceptance
- Output validates against the contract code in `src/common/`; JSON round-trip equals the input object.
- Same input twice gives the same output.
- A features dict with half the values missing still returns a forecast (NaN-tolerant model); a dict missing `pt_id` raises.
- One call under 50 ms after the first (print the timing in the test output, do not assert on slow CI machines).
- `make smoke` passes with a model trained on mock labels (coordinate with P1 if smoke needs a tiny model fixture).

## Definition of done
- P1's planner runs on `ml.predict` instead of the mock: confirm together and quote it in the PR.

## Pitfalls
- `available_at` is the decision time, not the target time.
- Feature order: always from `FEATURES`, never from dict order.

## Hand-off
"P2-07 merged: `from src.ml import predict`; returns contract `forecast`. P1 can switch the planner off the mock. Model path: `ARTIFACT_URI/models/<MODEL_VERSION>/<pt_id>/`."
