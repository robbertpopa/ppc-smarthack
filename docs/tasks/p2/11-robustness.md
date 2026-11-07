# P2-11 · `eval/robustness`

| | |
|---|---|
| Gate | G3 |
| Target | T+10:30–12:00 (04:30–06:00); parallel with 12 |
| Depends on | [10](10-eval-run.md) |
| Unblocks | [13](13-error-analysis.md) |
| Size budget | ~250 changed lines |
| Cut | the censored-data case second (after 09) |
| Covers | Robustness (10): missing data, wrong inputs, noise, uncertainty |

## Context
The jury scores how the agent handles missing data, rare cases, wrong inputs and uncertainty. Exploration tested 20% missing and 30% noise with small degradation; censored production (when the limit curtails PV, the meter no longer shows the potential) was not tested properly. Net-only inputs are the realistic case ([../p2-ml.md](../p2-ml.md), pitfalls).

## Goal
Robustness rows in the evaluation table: how export, violations and abstentions change when inputs degrade, with the model trained on clean data (as deployed).

## Files
- `src/eval/robustness.py`
- `src/eval/run.py` (only: `--robustness` flag, on by default, adds the rows)
- `tests/eval/test_robustness.py`

## Variants (corrupt the **inputs only**, never the labels; fixed seed per variant)
| Variant | What changes |
|---|---|
| `missing_20` | 20% of house readings set to NaN at random. Station aggregates are rebuilt from the remaining houses scaled by `n_houses / n_available`; if fewer than half the houses report, the aggregate is NaN |
| `noise_30` | Each house reading multiplied by `N(1, 0.3)`, clipped at 0 |
| `censored` | Observed generation is what the fixed limit let through: observed export = `min(surplus, 0.36 · kwp)`, so the meter under-reports PV on sunny hours; aggregates rebuilt from that |
| `net_only` | Check that no feature uses gross generation or consumption separately (an assertion on `FEATURES` plus a run); documents that the model is deployable with meter data only |

For `missing_20`, also report how many extra intervals `quality_flags` (08) sent to a human. The story is "worse inputs → the agent says 'not sure' more often instead of exporting unsafely".

## Steps
1. `corrupt(profiles, variant, seed) -> profiles` on per-house readings, then rebuild station aggregates with the same code path as P3's label aggregates (agree the function with P3, or reimplement the sum and test it equals P3's aggregates on clean data).
2. Rebuild features from the corrupted aggregates, predict with the clean models, evaluate with `metrics.evaluate` against the clean labels.
3. Table rows: `Model + fallback (clean)`, then one row per variant, with the change versus clean in parentheses.
4. Optional, if time: retrain on corrupted training data and compare (shows whether training on noisy data helps).

## Acceptance
- Rebuilt aggregates on clean data equal the label file aggregates (to 1e-9).
- Corruption is deterministic per seed and touches only inputs (assert labels unchanged).
- `missing_20`: no NaN becomes 0 anywhere in the pipeline (assert on the feature frame).
- Rows appear in `table.md`, `table.csv` and `summary.json`; 10's determinism test still passes.

## Definition of done
- Degradation per variant in the table, with the abstention increase reported.

## Pitfalls
- Censoring changes what the model sees on exactly the hours that matter (sunny middays). If the effect is large, that is an honest limitation for the slides (see [../../04-chosen-idea.md](../../04-chosen-idea.md), "Optimistic observability").

## Hand-off
"P2-11 merged: robustness rows in the table. Model + fallback violations clean <a>%, missing <b>%, noise <c>%, censored <d>%; abstentions rise from <x>% to <y>% with missing data."
