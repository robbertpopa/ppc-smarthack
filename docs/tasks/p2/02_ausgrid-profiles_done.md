# P2-02 · `ml/ausgrid-profiles`: done

Brief: [02-ausgrid-profiles.md](02-ausgrid-profiles.md). Branch: `ml/ausgrid-profiles` (task 02 is the second commit). Depends on [01](01_data-download_done.md).

## What was built
| File | Purpose |
|---|---|
| `src/ml/ausgrid.py` | `parse_file(path)` (one file, long format, local clock) and `build_profiles(raw_dir)` (all files, cleaned, UTC), plus `summarize` and `generation_check` |
| `src/ml/data.py` | adds `python -m src.ml.data profiles` (writes `DATA_DIR/profiles.parquet`, prints the quality summary) |
| `src/ml/DATA.md` | time-zone finding, output schema, quality summary |
| `tests/ml/test_ausgrid.py` | 13 tests on tiny in-test CSVs, both formats |

## Output: `DATA_DIR/profiles.parquet`
One row per house and half hour: `house_id` (`AG-0001`), `interval_start` (UTC, tz-aware, **start** of the half hour), `gc_kw`, `cl_kw`, `gg_kw` (mean kW, nullable), `kwp`, `postcode`, `quality` (`"NA"` when Ausgrid flagged the day as non-actual, else null). `available_at = interval_start + 30 min` by convention, not stored.

## Conventions and the time-zone decision
- Columns are labelled by the time the half hour **ends**; `0:00` is the last interval of the day (tested).
- kWh per half hour to kW: `× 2` (tested).
- **Time zone: Sydney wall-clock time with daylight saving.** Evidence: generation peaks about 11.9 h in winter and 13.0 h in summer, switching exactly on the change days; the Ausgrid notes say EST/EDT.
  - Spring forward: columns `2:30` and `3:00` are exactly 0 for every house (the hour does not exist). Dropped, so the day has 46 intervals.
  - Fall back: the same columns hold about double the usual value (the repeated hour is summed). Kept as four UTC rows with null values, so the day has 50 intervals.
- Missing stays missing: whole missing days have no rows; houses without controlled load have null `cl_kw`, not 0.

## Cleaning rules (every rule counted in `result.attrs["rules"]` and printed)
Duplicate readings dropped; spring-forward filler dropped; fall-back merged hour set to null; negative readings set to null; `gg_kw > 1.2 × kwp` set to null; duplicate rows across files dropped. Counts for the run on 2010-11 and 2011-12 are in `DATA.md`. In 2010-11 the over-limit rule hit mostly 3 houses (262, 215, 299), which suggests an understated kWp rather than bad data.

## Acceptance
| Check | Result |
|---|---|
| Tests with in-test CSVs for both formats: `0:30` / `0:00` columns, kWh to kW, nulls, format detection | Pass (13 tests; 29 in `tests/ml` with task 01) |
| 300 houses, 48 intervals per house-day, no duplicate key | 300 houses, 10,526,400 rows, no duplicates. 48 intervals on normal days (218,100), **46 and 50 on the two change days** (600 each) by design |
| Generation per year equals a direct sum over the raw CSV | Pass: raw total equals profiles plus what the rules removed, printed per file |
| One-house test file equals house 1 in the full file | Pass |
| Same result on pandas 2.2.3 and 3.1.1; `make smoke`, `make lint`, full test suite | Pass (85 passed, 2 skipped in the project; the skipped ones are P3's grid tests, which need the `grid-tools` extra) |

## Held-out test year (fixed on this branch)
The 2012-13 file is the team's test set. The first version of this task included it by mistake (`--from` copied it, and the first `profiles` run used it). Now `download` and `--from` skip it unless `--include-held-out` is given, tests cover that, and `profiles.parquet` was rebuilt from 2010-11 and 2011-12 only (ends 2012-06-30). The file had been opened for format and daylight-saving checks before the fix; nothing was tuned on it (stated in `DATA.md`).

## Not done / open
- **Request for P1:** add `pyarrow` to the base or `ml` dependencies in `pyproject.toml` (P3 put it only in the `grid-tools` extra); parquet writing needs it. Also a `make profiles` target.
- **Message to P3 is not sent.** It should carry the schema above, kW (not kWh), interval start in UTC, and the 46 / 48 / 50 day lengths. P3's `src/grid/ausgrid.py` reads the raw CSV directly, takes the 48 columns as they are (no daylight-saving handling) and treats a missing controlled load as 0; switching to `profiles.parquet` would fix both.

## Hand-off
"P2-02 done: `DATA_DIR/profiles.parquet` (house_id, interval_start UTC, gc_kw, cl_kw, gg_kw, kwp, …), kW not kWh, timestamps are interval start, 2010-07 to 2012-06 (2012-13 is the held-out test year). Time zone: Sydney local time with daylight saving; change days have 46 and 50 intervals. P3 can start labels."
