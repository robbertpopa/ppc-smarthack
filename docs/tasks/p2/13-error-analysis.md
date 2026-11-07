# P2-13 · `eval/error-analysis`

| | |
|---|---|
| Gate | G4 (feature freeze at T+13 does not stop analysis; code freeze at T+17 does) |
| Target | T+13:00–16:00 (07:00–10:00) |
| Depends on | [10](10-eval-run.md), [11](11-robustness.md) |
| Unblocks | P3's README section and slides; P2's answers to the jury's ML questions |
| Size budget | ~250 changed lines |
| Cut | never (shrink to two breakdowns if late) |
| Covers | ML quality (25): "where the model fails, on what cases, and what we tried to fix it" |

## Context
The brief asks explicitly for an error analysis: where the model is wrong, on which cases, and what was tried to correct it. Candidates from [../p2-ml.md](../p2-ml.md): sunrise and sunset, cloudy days, weekends. Every number on a slide comes from a script.

## Goal
`python -m src.eval.run --error-analysis` writes breakdown tables, 2–3 plots and a Markdown summary that P3 copies into the README and the slides.

## Files
- `src/eval/error_analysis.py`
- `src/eval/plots.py`
- `src/eval/run.py` (only: the `--error-analysis` flag)
- `tests/eval/test_error_analysis.py`

## Steps
1. Residual on test: `r = safe_share − q05` (negative = violation, large positive = wasted export).
2. Breakdowns (violation rate, abstention rate, mean `r`, export index per bin):
   - hour of day (Sydney), with sunrise/sunset bins (sun elevation 0–10°) marked;
   - day type: clear vs cloudy (daily PV / clear-sky expectation < 0.5 = cloudy);
   - weekday vs weekend;
   - season (Sydney months);
   - binding constraint (`binding` column from labels: voltage, line, trafo).
3. Plots (matplotlib, PNG, fixed style): violation rate by hour; predicted band (q05–q90) vs realised `safe_share` for one clear and one cloudy test day; risk-coverage curve (from 10).
4. "What we tried": one short table with the attempts and their effect on validation (for example: extra lags, a cloud-ratio feature, a different quantile for the limit). Run each attempt through the same code, no hand numbers. Only add an attempt to the model if it improves validation, never test.
5. `error_analysis.md` in `ARTIFACT_URI/eval/<run-id>/`: the breakdown tables, the plots (relative links), three sentences of findings, and the honest limits (simulation, German grid with Australian profiles, calibration drift, censored observability).
6. `slides_numbers.md`: the 6–8 numbers the slides use, each with the file and row it comes from. Hand it to P3.
7. Small PNGs for the README go to `docs/img/` only if P3 asks (P3 owns the README).

## Acceptance
- Breakdown counts add up to the total number of test daylight intervals.
- Rerun is byte-identical for the tables (plots may differ in metadata; set a fixed `metadata` in `savefig`).
- Every number in `slides_numbers.md` is found verbatim in a generated table (a test greps for them).

## Definition of done
- P3 has `error_analysis.md` and `slides_numbers.md`; P2 can answer "where does it fail and why" with a table.

## Pitfalls
- Do not cherry-pick the clear/cloudy example days by how good they look: choose them by a rule (median clear day, median cloudy day of the test period) and say the rule.

## Hand-off
"P2-13 merged: error analysis in `eval/<run-id>/error_analysis.md`, slide numbers in `slides_numbers.md` (with sources). Main failure: <…>."
