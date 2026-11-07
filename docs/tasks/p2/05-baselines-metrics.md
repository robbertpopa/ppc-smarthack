# P2-05 · `ml/baselines-metrics`

| | |
|---|---|
| Gate | G1 |
| Target | T+2:00–3:00 (20:00–21:00); parallel with 04 |
| Depends on | [03](03-labels-io.md) |
| Unblocks | [06](06-quantile-model.md), [10](10-eval-run.md) |
| Size budget | ~250 changed lines |
| Cut | never |
| Covers | Mandatory "compared with a simple baseline"; ML quality |

## Context
The final table compares every policy on export (fixed limit = 100), violations and abstentions ([../../08-parallel-plan.md](../../08-parallel-plan.md), "Shared evaluation"). The metric code must be shared by training, abstention and evaluation so the numbers agree everywhere.

## Goal
The three baselines and the metric functions, tested on hand-computed cases.

## Files
- `src/ml/baselines.py`
- `src/eval/__init__.py`, `src/eval/metrics.py`
- `tests/ml/test_baselines.py`, `tests/eval/test_metrics.py`

## Baselines (share of kWp applied for target interval `T`, decision at `t = T − 60 min`)
| Name | Rule |
|---|---|
| `fixed` | 0.36 for every interval (the ATR-style fixed limit) |
| `last_known` | `safe_share` of the interval ending at `t`; if missing, 0.36 |
| `same_hour_yesterday` | `safe_share` at `T − 24 h`; if missing, 0.36 |
| `oracle` | `safe_share` at `T` (the safe maximum; upper bound, not a policy) |

## Metrics
For a policy that applies share `φ_T` to every house of a station on daylight intervals:
- **Exported energy:** `Σ_T Σ_h min(surplus_h,T, φ_T · kwp_h) · 0.5 h`, with `surplus = max(pv_scale·gg − load_scale·(gc + cl), 0)` built from `profiles.parquet` and `station_houses.parquet` (03). If P3 used a different scaling, follow theirs and say so.
- **Export index:** exported energy / exported energy under `fixed` × 100.
- **Violation rate:** share of daylight intervals with `φ_T > safe_share_T + 1e-6` (intervals with null `safe_share` are excluded and counted separately).
- **Abstention rate:** share of daylight intervals where the policy abstained (used from 08 on).
- **Per-day abstentions:** mean and max flagged cases per day (for the crew budget, 08).

Accounting note, also printed under the final table: export is counted at the applied limit even in a violation interval; the violation rate is reported next to it, so a policy cannot look good by exporting unsafely.

## Interface
```python
# src/ml/baselines.py
def apply(name: str, labels: pd.DataFrame) -> pd.Series: ...   # share per target interval
# src/eval/metrics.py
def surplus_kw(profiles, station_houses) -> pd.DataFrame: ...  # per house and interval
def exported_kwh(share: pd.Series, surplus: pd.DataFrame, kwp: pd.Series) -> float: ...
def evaluate(share, labels, surplus, kwp, abstain=None) -> dict: ...  # export_index, violation_rate, abstain_rate, ...
```

## Acceptance
- Hand-computed case with 2 houses and 3 intervals for `exported_kwh`, `violation_rate` and the index.
- `fixed` has index exactly 100; `oracle` has violation rate 0 on non-null intervals.
- On mock labels, print a first baseline table (posted to the group as the T+3 "baseline numbers").

## Definition of done
- One metrics module used by everybody; no other file recomputes export or violations.

## Pitfalls
- Evaluate on daylight intervals only; at night the export limit is meaningless and would dilute every rate.
- Missing `safe_share` is not "safe": exclude and count.

## Hand-off
"P2-05 merged: baselines (`fixed`, `last_known`, `same_hour_yesterday`, `oracle`) and `src/eval/metrics.py`. First baseline numbers on <mock|real> labels: <table>."
