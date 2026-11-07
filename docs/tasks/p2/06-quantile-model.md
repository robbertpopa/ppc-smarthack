# P2-06 · `ml/quantile-model`

| | |
|---|---|
| Gate | G1 |
| Target | T+3:00–4:15 (21:00–22:15) |
| Depends on | [04](04-features.md), [05](05-baselines-metrics.md); real labels from P3 if they exist, mock labels otherwise |
| Unblocks | [07](07-predict.md), [08](08-abstention.md) |
| Size budget | ~250 changed lines |
| Cut | never |
| Covers | Mandatory "model trained by the team, training code in the repository"; ML quality |

## Context
The model predicts the safe export share one hour ahead as quantiles. The planner uses the cautious quantile `q05`; the spread `q90 − q05` drives "not sure" (08). Errors are asymmetric: a limit too high causes violations, one too low wastes energy, hence a low quantile and not the mean.

## Goal
`python -m src.ml.train --scenario A` trains one quantile model per quantile on the training period, reports validation metrics, and saves the models with `metadata.json` under `ARTIFACT_URI/models/<version>/<pt_id>/`.

## Files
- `src/ml/train.py`
- `src/ml/model_io.py` (save, load, metadata)
- `tests/ml/test_train.py`

## Steps
1. Model: `sklearn.ensemble.HistGradientBoostingRegressor(loss="quantile", quantile=q)` for `q` in `QUANTILES = (0.05, 0.10, 0.20, 0.50, 0.90)`. It handles NaN natively, so missing inputs stay missing (rule 5). Fixed `random_state=0`, `early_stopping=False` (no hidden random split), modest defaults (for example `max_iter=300`, `learning_rate=0.05`, `max_leaf_nodes=31`, `min_samples_leaf=40`).
2. Data: `labels.load(scenario)` → `features.build_frame` → `split` → daylight rows with a non-null target. Train on `train`; report on `val`. **Do not touch `test` in this task.**
3. A small hyper-parameter check (at most 4 settings) chosen by mean pinball loss on validation. Write the grid and the result to `metadata.json`.
4. **Quantile crossing:** at prediction time sort the five values per row (monotone rearrangement) and clip to [0, 1]. Put this in one helper used by train, predict and eval.
5. Validation report (printed and stored in metadata): pinball loss per quantile, coverage per quantile (share of `safe_share < q`; `q05` should be near 5%), violation rate and export index of `q05` used as the limit, next to the three baselines from 05.
6. `model_io.save(models, meta, path)`: joblib for models; `metadata.json` with `model_version` (`safe-cap-qgb-v1`), `pt_id`, git sha (`git rev-parse HEAD`, or `unknown`), SHA-256 of the labels file, training and validation periods, `FEATURES`, `QUANTILES`, hyper-parameters, validation metrics, scikit-learn version, `is_mock_labels`.
7. Paths through `ARTIFACT_URI`. If it is an `s3://` URI, use P1's storage helper from `src/common/`; do not write your own S3 code (ask P1 if the helper does not exist yet; local paths must work regardless).
8. Ask P1 for `make train` → `python -m src.ml.train --scenario all`.

## Interface
```python
QUANTILES: tuple[float, ...]
def train(scenario: str, seed: int = 0) -> dict: ...                 # returns validation report
def rearrange(q: np.ndarray) -> np.ndarray: ...                        # sort + clip, shape (n, 5)
# model_io
def save(models: dict[float, object], meta: dict, out: str) -> None: ...
def load(model_version: str, pt_id: str) -> tuple[dict[float, object], dict]: ...
```

## Acceptance
- Two runs with the same seed produce identical predictions on validation (`np.array_equal`).
- `rearrange` output is non-decreasing per row and within [0, 1].
- On mock labels, `q05` beats `last_known` and `same_hour_yesterday` on validation violation rate (sanity check that the pipeline works; real numbers come with real labels).
- `metadata.json` contains every field listed in step 6.

## Definition of done
- Model trained by our code, saved with metadata, validation numbers posted in the group next to the baselines.
- Nothing in this task reads the test period.

## Pitfalls
- Do not tune on test. Do not report test numbers from here; 10 does that.
- `GradientBoostingRegressor` (the older class) does not accept NaN; that is why we use the histogram one.
- With mock labels, write `is_mock_labels: true` in metadata so nobody mistakes the numbers.

## Hand-off
"P2-06 merged: `python -m src.ml.train --scenario A` → `ARTIFACT_URI/models/safe-cap-qgb-v1/PT-A/`. Validation: q05 coverage <x>%, violations <y>% vs last-known <z>%."
