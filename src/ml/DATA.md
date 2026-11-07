# Data notes: Ausgrid "Solar home electricity data"

Only dataset used by the ML pipeline. Raw files live in `DATA_DIR/raw/ausgrid/` and are never committed.

```
python -m src.ml.data download                 # fetch the zip, verify, extract
python -m src.ml.data download --from <dir|zip>  # offline: use a local copy
```

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
- Three half-hourly files, one per financial year (July to June), 300 houses each. These are the only files we use.
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
| Data rows | 269,735 | 270,304 | 268,557 |
| Days covered | 365 | 366 (leap year) | 365 |

Common header: `Customer,Generator Capacity,Postcode,Consumption Category,date,0:30,1:00,…,23:30,0:00`.

- `Consumption Category`: `GC` general consumption, `CL` controlled load (off-peak hot water), `GG` gross generation. Values are **kWh per half hour**.
- Columns are labelled by the time the half-hour **ends**; `0:00` is the last interval of the day (Ausgrid notes, column 6).
- `Row Quality`: blank = actual meter values, `NA` = some values estimated or substituted. 2011-12: 100 `NA` rows; 2012-13: 431. The 2010-11 file has no such column.
- Customers are numbered 1–300 in every file. `Generator Capacity` (kWp) is constant per customer in each file.
- `CL` exists for only 139 / 139 / 138 houses, so missing is not 0.
- 2010-11 and 2011-12 have every house-day (300 × days). 2012-13 has 109,419 `GC` and `GG` rows against 109,500 expected, so **81 house-days are missing**.
- No duplicate (customer, category, date) rows and no empty value cells in any file.

## Time zone (found in task 02)
The 48 columns are **Sydney wall-clock time with daylight saving** (`Australia/Sydney`), as the Ausgrid notes say ("EST … and EDT during the summer period"). Evidence from the data:
- The centre of gravity of gross generation sits at about 11.9 h in winter and 13.0 h in summer, and it jumps by one hour exactly on the clock-change days (2010-10-03, 2011-04-03, 2011-10-02, 2012-04-01), not gradually.
- Spring forward (first Sunday of October, e.g. 2011-10-02): columns `2:30` and `3:00` (02:00–03:00, an hour that does not exist) hold exactly `0` for every house. They are filler, not readings.
- Fall back (first Sunday of April, e.g. 2012-04-01): the same two columns hold about **double** the usual value, because the repeated 02:00–03:00 hour is summed into one. It cannot be split into its two UTC intervals.
- 2012-13 behaves the same (2012-10-07: zeros; 2013-04-07: doubled).

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

Not stored: whole missing days (81 house-days in 2012-13) stay missing, no filling.

## Quality summary (all three files, run on 2026-11-07)
> **To redo:** this run included the 2012-13 file, which the team keeps as the held-out test year. The figures below must be regenerated on 2010-11 and 2011-12 only.

- 300 houses, 15,778,512 rows, 2010-07-01 00:00 to 2013-06-30 23:30 (Sydney time).
- Intervals per house-day: 326,919 days with 48; 900 with 46 (spring forward); 900 with 50 (fall back). Total house-days = 300 × 1,096 − 81.
- Nulls: `gc_kw` 3,600 and `gg_kw` 6,983 (the four fall-back intervals per house-day, plus the over-limit rule below); `cl_kw` 54.0% (houses without controlled load, not zero); `quality` 99.9%.

| Cleaning rule | Readings |
|---|---:|
| Readings read | 38,812,608 |
| Duplicate (house, category, interval) readings dropped | 0 |
| Spring-forward filler dropped (non-existent hour) | 4,432 |
| Fall-back merged hour set to null | 4,430 |
| Negative readings set to null | 0 |
| `gg_kw` above 1.2 × `kwp` set to null | 3,383 |
| Duplicate (house, interval) rows across files | 0 |

Gross generation, kWh, summed straight from the raw CSV versus the profiles; the raw total equals profiles plus what the rules removed:

| File | Raw CSV | Profiles |
|---|---:|---:|
| 2010-2011 | 635,572.9 | 634,985.6 |
| 2011-2012 | 624,954.0 | 624,236.8 |
| 2012-2013 | 654,300.1 | 653,391.2 |
| Total | 1,914,827.0 | 1,914,827.0 (profiles + removed) |

Remarks:
- **Over-limit generation comes from a few houses.** In 2010-11, 906 readings exceed 1.2 × kWp, and 6 houses account for them (customers 262, 215 and 299 for 858 of them). The peak is up to 1.48 × kWp. A recorded capacity that is too low is more likely than bad meter data. We apply the rule as planned; revisit if those houses matter.
- Ausgrid's notes say the date is `DDMMMYYYY` and that `Row Quality` is column 54; the files differ (see the table above), so parsing detects the date format from the values and the layout from the header.
