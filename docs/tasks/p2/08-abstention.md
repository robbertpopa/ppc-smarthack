# P2-08 · `ml/abstention`

| | |
|---|---|
| Gate | G2 |
| Target | T+5:00–7:00 (23:00–01:00) |
| Depends on | [07](07-predict.md); **real labels from P3** (the threshold is meaningless on mock labels) |
| Unblocks | [10](10-eval-run.md); P1's "not sure" queue |
| Size budget | ~250 changed lines |
| Cut | never |
| Covers | Agent (25): decision layer with a justified threshold and a real constraint; Robustness (10): "I am not sure" |

## Context
The PPC brief asks for thresholds chosen with a reason, real constraints (how many cases a crew can check per day) and the confidence level, and for an agent that says "I am not sure" and sends the case to a human. Our rule: if `spread = q90 − q05` is above a threshold, the planner abstains and applies the fixed 0.36 limit, and the case goes to the human queue.

In exploration the first version of the threshold search ran the wrong way and flagged 43.5% of intervals. The test below exists to stop that.

## Goal
A threshold per station chosen on validation by a documented rule, stored in the model metadata, with the risk-coverage curve and calibration as evidence, and a clear list of input-quality reasons for abstaining.

## Files
- `src/ml/abstention.py`
- `src/ml/calibration.py`
- `src/ml/train.py` (only: call the threshold search after training and write it to `metadata.json`)
- `tests/ml/test_abstention.py`

## Steps
1. **Threshold search (validation only):** candidates = the distinct spread quantiles 0%, 1%, …, 100% of validation spreads. For each threshold `τ`: abstain where `spread > τ`, apply 0.36 there and `q05` elsewhere; compute the violation rate with `src/eval/metrics.py`. Choose **the highest `τ` whose violation rate ≤ `VIOLATION_TARGET`** (fewest abstentions that still meet the target). Evaluate all candidates and take the maximum; do not rely on scanning order or monotonicity.
2. `VIOLATION_TARGET` from config, default `0.02` (proposed; the team confirms it). If no threshold meets it, return `τ = -inf` (always abstain), log it loudly, and report it; do not quietly relax the target.
3. **Crew budget check:** with `CREW_CASES_PER_DAY` (from P1's config; ask PPC for a real number), report the mean and maximum flagged cases per day on validation and whether the budget holds. Report, do not tune to it silently: if it does not hold, that is a finding for the presentation.
4. **Risk-coverage curve:** for every candidate `τ`, coverage (share not abstained) vs violation rate of the non-abstained intervals. Save as CSV under `ARTIFACT_URI/models/<version>/<pt_id>/risk_coverage.csv`.
5. **Calibration** (`calibration.py`): coverage per quantile on validation (and a function 10 will call on test). Exploration drifted from 1.3–1.8% violations on validation to 2.3–3.5% on test: report the drift, do not hide it.
6. **Input-quality reasons:** `quality_flags(features) -> list[str]`, for example `missing_net_now`, `missing_share_last`, `stale_input` (newest input older than 60 min), `out_of_range_net` (|net| > 2 × `kwp_total`), `night` (sun below horizon at `T`). Any of these means "not sure" whatever the spread.
   **Contract:** propose to P1 an optional `quality_flags: list[str]` on `forecast` (default empty). P1 decides and updates the contract and mock. If P1 declines, P1's planner calls `ml.quality_flags(features)` directly.
7. Helper for the planner: `threshold(pt_id) -> float` reads it from metadata. The planner must not hard-code a threshold.

## Interface
```python
def choose_threshold(spread, q05, labels, surplus, kwp, target: float) -> dict: ...  # {"tau", "violation_rate", "abstain_rate", "per_day_mean", "per_day_max"}
def risk_coverage(spread, q05, labels, surplus, kwp) -> pd.DataFrame: ...
def quality_flags(features: dict) -> list[str]: ...
def threshold(pt_id: str) -> float: ...
```

## Acceptance
- **Direction test:** on a synthetic case where violations fall as `τ` falls, the chosen `τ` is the largest feasible one, and its abstention rate is ≤ that of every other feasible `τ`.
- Target unreachable → always abstain, and the report says so.
- `quality_flags` flags each listed case on hand-made inputs and returns `[]` on a clean one.
- On real labels, post: `τ`, abstention rate, violation rate with fallback, flagged cases per day vs crew budget, for each scenario.

## Definition of done
- Threshold, target and the reason for the target are in `metadata.json` and in the PR description.
- P1's queue receives the abstained cases with reasons (spread above `τ`, or the input flags).

## Pitfalls
- Choosing `τ` on test, even once, invalidates the table.
- Scenario B (voltage binds) flagged 42.5% in exploration even with the correct search. That is an honest result about a tight grid, not a bug; say why in the presentation.

## Hand-off
"P2-08 merged: thresholds per station in metadata (target <x>%). Abstain rate A/B/B-VAR: <…>. Flagged per day vs crew budget: <…>. `quality_flags` available; contract decision from P1: <…>."
