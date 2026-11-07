# Data notes: Ausgrid "Solar home electricity data"

Only dataset used by the ML pipeline. Raw files live in `DATA_DIR/raw/ausgrid/` and are never committed.

```
python -m src.ml.data download                 # fetch the zip, verify, extract
python -m src.ml.data download --from <dir|zip>  # offline: use a local copy
python -m src.ml.data download --include-held-out  # final evaluation only, see below
```

## Held-out test year
`Solar home 2012-2013.csv` (July 2012 to June 2013) is the **test set** and is kept sealed until the final evaluation (rule 2 in `docs/tasks/p2/README.md`). `download` and `--from` skip it by default, so `DATA_DIR/raw/ausgrid/` and `profiles.parquet` contain 2010-11 and 2011-12 only. `--include-held-out` brings it back; use it only for the final evaluation run.

Full disclosure: before this rule existed, the file was opened to check its format and its daylight-saving pattern, and the first `profiles` run included it. No model existed at that point and nothing was tuned on it. Its content is not described in this file beyond the layout the parser needs.

## Sources
| What | URL |
|---|---|
| Copy we download | https://pierreh.eu/downloads/Ausgrid_solar_home_data.zip (page: https://pierreh.eu/ausgrid-solar-data/) |
| Original (withdrawn) | https://www.ausgrid.com.au/Industry/Our-Research/Data-to-share/Solar-home-electricity-data |
| Archive of the original page | http://web.archive.org/web/20240721012112/https://www.ausgrid.com.au/Industry/Our-Research/Data-to-share/Solar-home-electricity-data |
| Metadata record | https://data.gov.au/data/en/dataset/nsw-solar-home-electricty-data |

Attribution: Ausgrid, "Solar home electricity data" (2014); archive copy by Pierre Haessig (May 2026).

## Licence
The README inside the copy states that Ausgrid published the data under **Creative Commons Attribution 3.0 Australia** (https://creativecommons.org/licenses/by/3.0/au/). We did not verify this against Ausgrid, because the original page is withdrawn; the copy's own statement is all we have. Attribution is required, so it goes in the project README and the slides.

## Checksums (observed 2026-11-07, from a local copy of the extracted files)
The SHA-256 of the **zip** is not recorded yet: it is written to `raw/SHA256SUMS` by the first real `download`. Paste it here then.

| File | SHA-256 |
|---|---|
| `Solar home 2010-2011.csv` | `2fc1f615e22fbd8ec350cdb19f7465d3a038453fc2ffd19473ef1bd38fd28289` |
| `Solar home 2011-2012.csv` | `a7d6abd1369311a5566e00d249141fd8aec28e9faba0bc928788607d961fc8c8` |
| `Solar home 2012-2013.csv` | `e4be46b3c9991c65735a9545319a2f1c33be8e639c75a17a88e0323a8e5098be` |

## What the copy contains
- Three half-hourly files, one per financial year (July to June), 300 houses each. These are the only files we use; 2012-13 is held out (see above).
- A monthly dataset (2,657 solar and 4,064 non-solar homes, 2007–2014) and the Ausgrid notes PDF. Monthly data is not used: its header is `Customer ID,Netwk Bill Rate Type,Consumption Month,Sum,Unit of me`, so `half_hourly_csvs()` skips it.

## Format of the half-hourly files (as observed)
Each row is one house, one category and one day; the 48 half-hour values are columns.

| | 2010-2011 | 2011-2012 | 2012-2013 |
|---|---|---|---|
| Line 1 | title row (not data) | title row | title row |
| Line 2 | header | header | header |
| Columns | 53 | 54 (adds `Row Quality`) | 54 (adds `Row Quality`) |
| Date format | `1-Jul-10` | `1/07/2011` | `1/07/2012` |
| Line ending | `\n` | `\r\n`, trailing comma | `\r\n`, trailing comma |
| Data rows | 269,735 | 270,304 | held out |
| Days covered | 365 | 366 (leap year) | 365 |

Common header: `Customer,Generator Capacity,Postcode,Consumption Category,date,0:30,1:00,…,23:30,0:00`.

- `Consumption Category`: `GC` general consumption, `CL` controlled load (off-peak hot water), `GG` gross generation. Values are **kWh per half hour**.
- Columns are labelled by the time the half-hour **ends**; `0:00` is the last interval of the day (Ausgrid notes, column 6).
- `Row Quality`: blank = actual meter values, `NA` = some values estimated or substituted. 2011-12 has 100 `NA` rows. The 2010-11 file has no such column.
- Customers are numbered 1–300 in every file. `Generator Capacity` (kWp) is constant per customer in each file.
- `CL` exists for only 139 of the 300 houses in both years, so missing is not 0.
- 2010-11 and 2011-12 have every house-day (300 × days).
- No duplicate (customer, category, date) rows and no empty value cells in the two years used.

## Time zone (found in task 02)
The 48 columns are **Sydney wall-clock time with daylight saving** (`Australia/Sydney`), as the Ausgrid notes say ("EST … and EDT during the summer period"). Evidence from the data:
- The centre of gravity of gross generation sits at about 11.9 h in winter and 13.0 h in summer, and it jumps by one hour exactly on the clock-change days (2010-10-03, 2011-04-03, 2011-10-02, 2012-04-01), not gradually.
- Spring forward (first Sunday of October, e.g. 2011-10-02): columns `2:30` and `3:00` (02:00–03:00, an hour that does not exist) hold exactly `0` for every house. They are filler, not readings.
- Fall back (first Sunday of April, e.g. 2012-04-01): the same two columns hold about **double** the usual value, because the repeated 02:00–03:00 hour is summed into one. It cannot be split into its two UTC intervals.

How `profiles.parquet` handles it: every timestamp is converted to UTC with the tz database. The spring-forward filler is dropped (a 46-interval day). On fall-back days the four UTC intervals of the repeated hour are kept as rows with **null** values (a 50-interval day), because the true split is unknown. So the number of intervals per house-day is 48 on normal days, 46 and 50 on the two change days.

## `profiles.parquet` (task 02)
`python -m src.ml.data profiles` writes `DATA_DIR/profiles.parquet`: one row per house and half hour.

| Column | Type | Meaning |
|---|---|---|
| `house_id` | str | `AG-0001` … `AG-0300` |
| `interval_start` | timestamp, UTC | **start** of the half hour; `available_at = interval_start + 30 min` (implied, not stored) |
| `gc_kw` | float, nullable | general consumption, mean kW (`kWh × 2`) |
| `cl_kw` | float, nullable | controlled load, mean kW; null for houses without it |
| `gg_kw` | float, nullable | gross generation, mean kW |
| `kwp` | float | installed capacity from the file |
| `postcode` | str | as given |
| `quality` | str, nullable | `"NA"` if Ausgrid flagged any of that house's GC/CL/GG rows for the day as non-actual (some values estimated); null otherwise. The 2010-11 file has no flag, so its rows are null, which does not prove the values are actual |

Not stored: whole missing days stay missing, no filling (there are none in 2010-11 and 2011-12).

## Quality summary (2010-11 and 2011-12, run on 2026-11-07)
- 300 houses, 10,526,400 rows, 2010-07-01 00:00 to 2012-06-30 23:30 (Sydney time).
- Intervals per house-day: 218,100 days with 48; 600 with 46 (spring forward); 600 with 50 (fall back). Total house-days = 300 × 731, none missing.
- Nulls: `gc_kw` 2,400 and `gg_kw` 4,417 (the four fall-back intervals per house-day, plus the over-limit rule below); `cl_kw` 53.8% (houses without controlled load, not zero); `quality` 99.97%.

| Cleaning rule | Readings |
|---|---:|
| Readings read | 25,921,872 |
| Duplicate (house, category, interval) readings dropped | 0 |
| Spring-forward filler dropped (non-existent hour) | 2,956 |
| Fall-back merged hour set to null | 2,954 |
| Negative readings set to null | 0 |
| `gg_kw` above 1.2 × `kwp` set to null | 2,017 |
| Duplicate (house, interval) rows across files | 0 |

Gross generation, kWh, summed straight from the raw CSV versus the profiles; the raw total equals profiles plus what the rules removed:

| File | Raw CSV | Profiles |
|---|---:|---:|
| 2010-2011 | 635,572.9 | 634,985.6 |
| 2011-2012 | 624,954.0 | 624,236.8 |
| Total | 1,260,526.9 | 1,260,526.9 (profiles + removed) |

Remarks:
- **Over-limit generation comes from a few houses.** In 2010-11, 906 readings exceed 1.2 × kWp, and 6 houses account for them (customers 262, 215 and 299 for 858 of them). The peak is up to 1.48 × kWp. A recorded capacity that is too low is more likely than bad meter data. We apply the rule as planned; revisit if those houses matter.
- Ausgrid's notes say the date is `DDMMMYYYY` and that `Row Quality` is column 54; the files differ (see the table above), so parsing detects the date format from the values and the layout from the header.
