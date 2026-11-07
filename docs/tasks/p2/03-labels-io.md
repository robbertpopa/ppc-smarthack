# P2-03 · `ml/labels-io`

| | |
|---|---|
| Gate | G1 |
| Target | T+1:00–2:00 (19:00–20:00); can run in parallel with 02 |
| Depends on | P1's contract in `src/common/` (G0) |
| Unblocks | [04](04-features.md), [05](05-baselines-metrics.md), [06](06-quantile-model.md) |
| Size budget | ~200 changed lines |
| Cut | never |
| Covers | Separate test set (mandatory); ML quality |

## Context
P3 writes the ground truth (`safe_share` per station and interval) from power flows. Until it exists, P2 trains on mock labels so the whole code path is ready. The time split is fixed in [../p2-ml.md](../p2-ml.md).

## Goal
An agreed, validated label schema; a deterministic mock label file with the same schema; one function that returns the train / validation / test split.

## Files
- `src/ml/labels.py`
- `src/ml/split.py`
- `tests/ml/test_labels.py`, `tests/ml/test_split.py`

## Schemas to agree with P3 (post them, get a "yes", then code)
`DATA_DIR/labels/<scenario>/labels.parquet`, one row per station and half-hour:

| Column | Type | Meaning |
|---|---|---|
| `pt_id` | str | Station id, one per scenario (`PT-A`, `PT-B`, `PT-B-VAR`) |
| `interval_start` | timestamp UTC | |
| `safe_share` | float in [0, 1], nullable | Highest safe export share of kWp; null if the power flow did not converge |
| `converged` | bool | |
| `binding` | str, nullable | `voltage`, `line`, `trafo` or `none` (which limit decided the share) |
| `load_kw`, `pv_kw`, `net_kw` | float, nullable | Station totals of the injections used (`net_kw = load_kw − pv_kw`) |
| `kwp_total`, `n_houses` | float, int | |
| `available_at` | timestamp UTC | `interval_start + 30 min` |
| `provenance` | str | `simulated` |
| `source_ref` | str | `grid/labels.py@<git sha>`; mock files use `mock` |

`DATA_DIR/labels/<scenario>/station_houses.parquet`: `pt_id`, `house_id` (simulated house), `source_house_id` (Ausgrid id), `kwp`, `load_scale`, `pv_scale`. Evaluation needs it to compute exported energy per house (see 05).

## Steps
1. `labels.py`: `validate(df)` checks columns, types, UTC, uniqueness of (`pt_id`, `interval_start`), `safe_share` in [0, 1] or null, `safe_share` null when `converged` is false. Raise with a clear message listing every problem.
2. `load(scenario) -> pd.DataFrame` reads from `DATA_DIR`, validates, returns sorted.
3. `make_mock(profiles, scenario, seed=0)`: a deterministic fake `safe_share` from the real profiles if `profiles.parquet` exists (station of 30 random houses), otherwise from a synthetic daily sine. Something plausible, for example `clip(0.9 − 0.6·pv/kwp_total + 0.3·load/kwp_total + noise, 0.05, 1)`. `source_ref = "mock"`. CLI: `python -m src.ml.labels mock --scenario A`.
4. `is_mock(df) -> bool`. Evaluation (10) refuses mock labels unless told otherwise, so a mock number can never reach a slide.
5. `split.py`: `split(df) -> dict[str, pd.DataFrame]` with keys `train`, `val`, `test` using Sydney local dates: train ≤ 2012-03-31, val 2012-04-01 → 2012-06-30, test 2012-07-01 → 2013-06-30. Also `daylight(df)` mask: solar elevation > 0 at the interval midpoint (reuse 04's sun function if merged; otherwise put the function here and let 04 import it).

## Interface
```python
def validate(df: pd.DataFrame) -> None: ...
def load(scenario: str) -> pd.DataFrame: ...
def make_mock(profiles: pd.DataFrame | None, scenario: str, seed: int = 0) -> pd.DataFrame: ...
def is_mock(df: pd.DataFrame) -> bool: ...
def split(df: pd.DataFrame) -> dict[str, pd.DataFrame]: ...
```

## Acceptance
- Mock output passes `validate`; two runs with the same seed are identical (`df.equals`).
- `validate` rejects: a duplicate row, a share of 1.2, a naive timestamp, a non-converged row with a number.
- Split: no overlap between sets; boundaries tested on a row at 2012-03-31 23:30 and 2012-04-01 00:00 Sydney time.

## Definition of done
- P3 confirmed the schema in the group chat (quote it in the PR).
- Every later task can call `load` and `split` without knowing whether labels are mock or real.

## Pitfalls
- Splitting by date in UTC shifts the boundary by 10–11 hours. Use Sydney dates.
- Never shuffle. Never random split.

## Hand-off
"P2-03 merged: label schema agreed with P3, mock labels via `python -m src.ml.labels mock`, `split()` gives the fixed time split."
