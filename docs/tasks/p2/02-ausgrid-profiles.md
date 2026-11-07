# P2-02 · `ml/ausgrid-profiles`

| | |
|---|---|
| Gate | G0 → G1 |
| Target | T+0:45–1:45 (18:45–19:45). **P3 needs this file to generate labels by T+3** |
| Depends on | [01](01-data-download.md) |
| Unblocks | P3's label generator, [03](03-labels-io.md), [11](11-robustness.md) |
| Size budget | ~250 changed lines |
| Cut | never |
| Covers | ML quality (data cleaned and combined by the team) |

## Context
P3 runs power flows over per-house consumption and generation profiles. Those profiles come from this task. Format pitfalls are listed in [../p2-ml.md](../p2-ml.md) and [../../05-data-and-sources.md](../../05-data-and-sources.md).

## Goal
A clean, tidy, UTC-indexed per-house profiles file that P3 and every later P2 task read, plus a data-quality summary.

## Files
- `src/ml/ausgrid.py` (parsing and cleaning)
- `src/ml/data.py` (add the `profiles` subcommand only)
- `src/ml/DATA.md` (append the quality summary and the time-zone finding)
- `tests/ml/test_ausgrid.py`

## Output: `DATA_DIR/profiles.parquet`
One row per house and half-hour.

| Column | Type | Meaning |
|---|---|---|
| `house_id` | str | Ausgrid customer id, prefixed (`AG-0001`) |
| `interval_start` | timestamp, UTC, tz-aware | Start of the half-hour |
| `gc_kw` | float, nullable | General consumption, mean power over the interval |
| `cl_kw` | float, nullable | Controlled load (off-peak hot water); null if the house has none |
| `gg_kw` | float, nullable | Gross generation |
| `kwp` | float | Installed panel capacity ("Generator Capacity") |
| `postcode` | str | As given |
| `quality` | str, nullable | Row quality flag where the file has one |

Plus `available_at = interval_start + 30 min` is implied by convention for measured values (document it; do not store it if size matters).

## Steps
1. **Detect the format from the header**, not the file name. Known differences: the 2010–2011 file uses dates like `1-Jul-10` and has no "Row Quality" column; 2012–2013 differs. Parse both, plus whatever 2011–2012 uses.
2. Wide to long: each row is one house, one category (`GC`, `CL`, `GG`) and one day with 48 half-hour columns. Pivot categories to columns.
3. **Interval convention:** the half-hour columns are labelled by the time the interval *ends* (`0:30` … `0:00`); convert to `interval_start`. The `0:00` column is the last interval of the day. Write a test for it.
4. **Units:** readings are kWh per half-hour. `kW = kWh × 2`. Test it.
5. **Time zone:** check whether timestamps follow daylight saving (look at the days of the clock change: a DST-aware file would have 46 or 50 intervals; a fixed 48 means standard time or shifted data). Record the finding in `DATA.md` and convert to UTC accordingly (`Australia/Sydney` or fixed UTC+10). Never mix local and UTC silently.
6. **Cleaning, every rule counted and reported:** duplicate rows dropped; negative readings set to null; physically impossible generation (`gg_kw > 1.2 × kwp`) set to null; whole days missing stay missing (no filling here). Keep the counts.
7. `python -m src.ml.data profiles` writes `profiles.parquet` and prints the quality summary: houses, date range, rows, nulls per column, rules applied with counts.
8. Post the schema to P3 as soon as step 4 works, even before cleaning is done.

## Interface
```python
# src/ml/ausgrid.py
def parse_file(path: Path) -> pd.DataFrame: ...       # long format, one file
def build_profiles(raw_dir: Path) -> pd.DataFrame: ... # all files, cleaned, UTC
```

## Acceptance
- `pytest tests/ml/test_ausgrid.py` with small in-test CSV strings for **both** formats: correct `interval_start` for the `0:30` and `0:00` columns, kWh→kW, nulls stay null, format detection picks the right parser.
- On the real data: 300 houses (or the number found, explained), 48 intervals per house-day, no duplicate (`house_id`, `interval_start`).
- Total generation per year matches a direct sum over the raw CSV to within rounding (print both).

## Definition of done
- P3 has the file and the schema; the time-zone decision is written down.
- Every cleaning rule is listed with how many values it touched.

## Pitfalls
- Southern hemisphere: summer is December. Day-of-year features later must use Sydney dates.
- Controlled load is not present for every house; missing is not 0.
- Do not drop the 2010–2011 year because it is awkward: it is part of the training period.

## Out of scope
Scaling to SimBench houses (P3 owns it), labels, features.

## Hand-off
"P2-02 merged: `DATA_DIR/profiles.parquet` (house_id, interval_start UTC, gc_kw, cl_kw, gg_kw, kwp, …), kW not kWh, timestamps are interval start. Time zone: <finding>. P3 can start labels."
