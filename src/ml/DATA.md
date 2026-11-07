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

## Not yet decided (task 02)
- **Time zone.** The Ausgrid notes say the 48 columns are "Eastern Standard Time (EST) and Eastern Daylight Savings Time (EDT) during the summer period", which suggests local Sydney time. A file with a fixed 48 columns on clock-change days does not fit that. Task 02 checks the change days and records the result here.
- The notes describe the date as `DDMMMYYYY` and the quality column as column 54; the files differ (see the table above), so parse by header.
