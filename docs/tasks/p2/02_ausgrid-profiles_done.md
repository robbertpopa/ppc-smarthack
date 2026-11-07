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
Duplicate readings dropped; spring-forward filler dropped; fall-back merged hour set to null; negative readings set to null; `gg_kw > 1.2 × kwp` set to null; duplicate rows across files dropped. Counts for the run on the data available locally are in `DATA.md`. In 2010-11 the over-limit rule hit mostly 3 houses (262, 215, 299), which suggests an understated kWp rather than bad data.

## Acceptance
| Check | Result |
|---|---|
| Tests with in-test CSVs for both formats: `0:30` / `0:00` columns, kWh to kW, nulls, format detection | Pass (13 tests; 24 in `tests/ml` with task 01) |
| 300 houses, 48 intervals per house-day, no duplicate key | 300 houses, no duplicates. 48 intervals on normal days, **46 and 50 on the two change days** by design |
| Generation per year equals a direct sum over the raw CSV | Pass: raw total equals profiles plus what the rules removed, printed per file |
| One-house test file equals house 1 in the full file | Pass |
| Same result on pandas 2.2.3 and 3.1.1; `make smoke`, `make lint`, full test suite | Pass (80 tests in the project) |

## Not done / open
- **The 2012-13 file was included by mistake.** The team keeps that year as the test set. `--from` copied it, so the local `data/raw/ausgrid/` and `profiles.parquet` contain it, and the figures in `DATA.md` cover three years. Fix to do next: delete that file locally, restrict `--from` to the named years, rebuild, and update the `DATA.md` numbers. Nothing was sent to P3.
- **Request for P1:** add `pyarrow` to `pyproject.toml` (parquet needs it; `pandas` alone is not enough), and `make profiles`.
- **Message to P3 is not sent.** It should carry the schema above, kW (not kWh), interval start in UTC, and the 46 / 48 / 50 day lengths.

## Hand-off (once the held-out year is removed)
"P2-02 done: `DATA_DIR/profiles.parquet` (house_id, interval_start UTC, gc_kw, cl_kw, gg_kw, kwp, …), kW not kWh, timestamps are interval start. Time zone: Sydney local time with daylight saving; change days have 46 and 50 intervals. P3 can start labels."
