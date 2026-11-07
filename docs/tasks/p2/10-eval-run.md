# P2-10 · `eval/run-table`

| | |
|---|---|
| Gate | G3 ("evaluation table reproducible with one command") |
| Target | T+9:00–10:30 (03:00–04:30) |
| Depends on | [08](08-abstention.md); real labels for scenarios A, B, B-VAR from P3 |
| Unblocks | [11](11-robustness.md), [13](13-error-analysis.md), P3's comparison panel and slides, P1's cloud run |
| Size budget | ~280 changed lines |
| Cut | never |
| Covers | Mandatory separate test set and baseline; Demo and repository (reproducibility); every number on the slides |

## Context
The jury reruns our results from the README, and every number in the presentation must come from this script ([../../01-theme-and-criteria.md](../../01-theme-and-criteria.md)). The table content is fixed in [../../08-parallel-plan.md](../../08-parallel-plan.md), "Shared evaluation". P1 runs the same command in the cloud and the outputs must match.

## Goal
`python -m src.eval.run` trains (deterministically) or loads the models, evaluates on the test period, and writes the table as CSV, Markdown and JSON.

## Files
- `src/eval/run.py`
- `src/eval/table.py` (formatting)
- `tests/eval/test_run.py`

## Steps
1. CLI: `python -m src.eval.run [--scenario all|A|B|B-VAR] [--run-id local] [--use-artifacts] [--allow-mock]`.
   - Default: retrain from labels with fixed seeds (one command reproduces everything). `--use-artifacts` loads the saved models and checks their `metadata.json` data hash matches the labels; mismatch is an error.
   - Refuses mock labels (`labels.is_mock`) unless `--allow-mock`; then every output is stamped `MOCK – NOT A RESULT` in the title and in `summary.json`.
2. For each scenario, on **test** daylight intervals:
   - Rows: `Fixed limit`, `Last known`, `Same hour yesterday`, `Model (q05)`, `Model + fallback`, `Safe maximum (oracle)`.
   - Columns: export index (fixed = 100), violation rate, abstention rate (model + fallback only), flagged cases per day (mean / max).
   - Calibration on test: coverage per quantile, next to validation coverage from metadata (the drift is reported).
   - Risk-coverage curve on test (CSV).
3. Footer: test period, number of daylight intervals, label `source_ref`, git sha, labels SHA-256, `VIOLATION_TARGET`, the threshold per station, and the accounting note from 05.
4. Outputs under `ARTIFACT_URI/eval/<run-id>/`: `table.csv`, `table.md`, `summary.json`, `risk_coverage_<pt_id>.csv`, `calibration.csv`. No timestamps or absolute paths inside the files, so two runs are byte-identical.
5. `summary.json` for P3's comparison panel. Agree the shape with P3 first; proposal:
   ```json
   {"run_id": "local", "git_sha": "…", "mock": false,
    "scenarios": {"PT-A": {"rows": {"fixed": {"export_index": 100.0, "violation_rate": 0.0, "abstain_rate": null}, "model_fallback": {…}}}}}
   ```
6. Ask P1 for `make eval` → `python -m src.eval.run`.

## Acceptance
- Two runs produce byte-identical `table.csv` and `summary.json` (test compares hashes, on mock labels with `--allow-mock`).
- Without `--allow-mock`, mock labels raise a clear error.
- `Fixed limit` export index is exactly 100; `oracle` violation rate is 0.
- The test period is the only data used for the reported rows (assert on the timestamps passed to the metrics).
- Runtime on real labels printed (target: a few minutes on a laptop).

## Definition of done
- One command, deterministic, all rows and columns of the shared evaluation (robustness rows come in 11).
- P1 confirms the cloud run matches the local `table.csv` hash (G3 check).

## Pitfalls
- Never choose anything on test here: thresholds come from metadata (validation).
- Keep formatting (decimals) fixed so diffs are meaningful.

## Hand-off
"P2-10 merged: `python -m src.eval.run` writes `eval/<run-id>/table.md|csv|summary.json`. Headline, scenario A: model+fallback <x> vs fixed 100, violations <y>%, flagged <z>%."
