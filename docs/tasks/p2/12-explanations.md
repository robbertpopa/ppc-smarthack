# P2-12 · `ml/explanations`

| | |
|---|---|
| Gate | G3 |
| Target | T+10:30–13:00 (04:30–07:00); parallel with 11 |
| Depends on | [07](07-predict.md); shape of the explanation figures agreed with P1 |
| Unblocks | P1's explanation text (templates) and P3's operator screen |
| Size budget | ~250 changed lines |
| Cut | the local part third (global importance stays) |
| Covers | Explainability (10): why a decision was made, by feature importance or similar past cases |

## Context
The brief gives two examples of explainability: feature importance and similar cases from history. P1 turns numbers into text with templates; an LLM, if used at all, may only rephrase, and P1 rejects any text with a number that is not in the figures ([../p1-platform-agent.md](../p1-platform-agent.md)). So this task produces numbers only.

## Goal
Global importance per station, and for each decision the top factors that moved the limit and the most similar past cases.

## Files
- `src/ml/explain.py`
- `src/ml/__init__.py` (export `explain`)
- `tests/ml/test_explain.py`

## Steps
1. **Global:** `sklearn.inspection.permutation_importance` on validation for the `q05` model, scored by pinball loss at 0.05, fixed seed, 10 repeats. Save `importance.csv` next to the model; P3 can show it, 13 uses it.
2. **Local (per decision):** for each feature, replace its value by a reference (its validation median for the same hour of day) and recompute `q05`; `effect = q05(actual) − q05(reference)`. Return the top 3 by `|effect|`. Missing features are reported as `missing`, not ablated.
3. **Similar past cases:** the 5 nearest training+validation decisions (standardised features, Euclidean, excluding NaN dimensions) with their date, their `q05` and the realised `safe_share`. Shows the operator "the last times it looked like this, the safe limit turned out to be …".
4. Output shape, agreed with P1 (it maps onto `plan.explanation.figures`):
   ```json
   {"figures": [{"name": "net_now", "value": -0.42, "effect": -0.08},
                {"name": "spread", "value": 0.12}],
    "similar": [{"interval_start": "2012-05-03T02:00:00Z", "q05": 0.33, "safe_share": 0.37}]}
   ```
   Feature names map to readable labels in one dictionary (for example `net_now` → "net load now (share of kWp)") that P1's templates import.
5. Performance: one `explain` call under 200 ms (5 × `FEATURES` predictions plus one nearest-neighbour query on a prebuilt index).

## Interface
```python
def global_importance(pt_id: str) -> pd.DataFrame: ...
def explain(features: dict) -> dict: ...   # {"figures": [...], "similar": [...]}
LABELS: dict[str, str]
```

## Acceptance
- On a toy model where only one feature matters, that feature is ranked first globally and locally.
- `explain` is deterministic; every number in its output is a float or ISO time, nothing pre-formatted as text.
- Similar cases never come from the test period or from after the decision time.

## Definition of done
- P1's plan carries real figures for every decision; the operator screen can show "why".

## Pitfalls
- Permutation importance on correlated lags splits credit between them; say so next to the chart, or group the lag features.
- Explanations explain the model, not the physics. Keep that wording on screen.

## Hand-off
"P2-12 merged: `ml.explain(features)` → top-3 factors with effect on q05 + 5 similar past cases. Global importance in `importance.csv`."
