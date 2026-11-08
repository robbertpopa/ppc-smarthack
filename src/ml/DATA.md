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

## Where the houses are (postcode and coordinates)
Two small files describe the location of the 300 houses. They live in `DATA_DIR/reference/` and are never committed. They are added once with:

```
python -m src.ml.data geo --from <ausgrid_postcodes_geo.csv> --postcodes <"Solar home 2010-2011 post codes.csv">
```

| File | Origin | Columns |
|---|---|---|
| `ausgrid_postcodes_geo.csv` | made by the team from the postcodes | `Customer, Generator Capacity, Postcode, lat, lon, localities` |
| `Solar home 2010-2011 post codes.csv` | Ausgrid's own file (not in the zip we download; one title line, then the header) | `Customer, Generator Capacity, Postcode` |

What was checked on 2026-11-07 (and is checked again by the command and by `geo.check_against_*`):
- 300 customers, numbered 1 to 300, unique in both files. `Customer` is the number in the half-hourly files, so customer 1 is `AG-0001`.
- The geo file is a superset of Ausgrid's list: same customers, same generator capacity and postcode for every house.
- Both agree with `profiles.parquet` for all 300 houses (`kwp` and `postcode`).
- The coordinates are **per postcode**: 100 postcodes, 100 distinct coordinates, none missing, all inside New South Wales (latitude -34.11 to -32.63, longitude 150.98 to 152.31). So the precision is a suburb centre, about a kilometre, **not the position of a house**. Do not present it as one.

### Sources
| File | Source | Status |
|---|---|---|
| `ausgrid_postcodes_geo.csv`: `lat`, `lon`, `localities` | `australian_postcodes.csv` from the GitHub repository [matthewproctor/australianpostcodes](https://github.com/matthewproctor/australianpostcodes), downloaded from https://raw.githubusercontent.com/matthewproctor/australianpostcodes/master/australian_postcodes.csv (the repository describes itself as "a community sourced comprehensive database of Australian Post Codes with geolocation data") | Recorded 2026-11-07, from the team member who built the file |
| `ausgrid_postcodes_geo.csv`: `Customer`, `Generator Capacity`, `Postcode` | Ausgrid's solar home data, as in the half-hourly files (see Sources above) | Same as the main dataset |
| `Solar home 2010-2011 post codes.csv` | Ausgrid's own file, published with the solar home data. It is **not** in the zip we download | SHA-256 `c27b7836f72bbac1ff466de96662c383afaedf76684ad8761c37c4e13a0f672b`. **Source not recorded: TODO for whoever downloaded it.** Write the page or link it came from, the date and the licence, here and in the README |

**Licence of the coordinates: none declared.** GitHub reports no licence for the repository, and its README says the postcodes originate in Australia Post's database, which it describes as "technically not meant to be republished". So:
- We do **not** commit or redistribute the geo file; it stays in `DATA_DIR/reference/`, which is outside git.
- The README and the slides must name the source and say that the coordinates are community-sourced from Australia Post data with no licence stated.
- If the coordinates are shown on a public screen (the map), consider replacing them with postal-area centres from the Australian Bureau of Statistics, which publishes its boundary files under Creative Commons Attribution (to be verified before use).

**Still not recorded:** how one coordinate and three suburb names were chosen per postcode out of the many rows the source holds for it (the geo file has exactly one coordinate per postcode and at most three names). Whoever built the geo file should add the rule here.

Where it fits (`src/ml/geo.py` loads and validates it; nothing uses it yet):
1. **Station composition.** Today a station is 30 houses picked at random (mock) or in file order (P3's twin). Houses in one postcode area share the same weather, which is what a real low-voltage station sees. Choosing a station from one area makes the clouds hit all of its houses together, which is the case the model has to handle.
2. **Map for the operator screen** (P3): a point per postcode, sized by installed power.
3. **Regional feature or check**: whether the error depends on the coast, Sydney or Newcastle.

## Weather and solar radiation: NASA POWER (hourly, 2010–2013)
Hourly weather for the 100 postcodes of the houses, from the NASA POWER hourly point API. The model reads it through `src.ml.weather.load()` (below); no feature uses it yet (P6 step 02).

```
python -m src.ml.weather fetch    # one request per postcode and year, cached, safe to rerun
python -m src.ml.weather build [--csv]   # joins them into DATA_DIR/weather_hourly.parquet (+ .sha256)
```

| | |
|---|---|
| Source | NASA POWER (Prediction Of Worldwide Energy Resources), https://power.larc.nasa.gov/ ; API https://power.larc.nasa.gov/api/temporal/hourly/point (hourly API v2.10.4; underlying sources MERRA-2, SYN1DEG, POWER) |
| Licence | CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), as stated in https://power.larc.nasa.gov/llms.txt. Attribution is required, so the source goes in the project README and the slides. How NASA asks to be cited: https://power.larc.nasa.gov/docs/referencing/ (**not read yet: copy the exact citation here**) |
| Retrieved | 2026-11-07, no key needed |
| Raw files | `DATA_DIR/raw/nasa_power/hourly/<postcode>_<year>.json`, exactly as the API sent them. Never committed |
| Request | `community=re`, `time-standard=utc`, 13 parameters, coordinates = the postcode coordinate of `src.ml.geo` |
| Parameters | `ALLSKY_SFC_SW_DWN` (global horizontal, Wh/m²), `ALLSKY_SFC_SW_DIFF`, `ALLSKY_SFC_SW_DNI`, `CLRSKY_SFC_SW_DWN` (clear-sky), `ALLSKY_KT`, `CLOUD_AMT` (%), `SZA` (°), `T2M` (°C), `RH2M` (%), `WS10M` (m/s), `WD10M` (°), `PS` (kPa), `PRECTOTCORR` (mm/h) |

`weather_hourly.parquet`: one row per postcode and UTC hour (`time_utc`, `postcode`, then the parameters). NASA's fill value −999 becomes null. `build` writes its SHA-256 to `weather_hourly.parquet.sha256`; the file built on 2026-11-07 has `844a2f883b24220fb219c8b560fc70157b6121350c7030b15ca574f60d3495b8` (pyarrow 26.0.1). The API refuses a JSON answer longer than about two years, hence one request per year (400 requests, none failed).

What was checked on 2026-11-07:
- 100 postcodes × 35,064 hours (2010-01-01 00:00 to 2013-12-31 23:00 UTC), 3,506,400 rows; every request returned every parameter for every hour.
- Only `ALLSKY_KT` has nulls (49.1%): NASA gives none at night. All other parameters are complete.
- Plausible ranges: `T2M` −1.9 to 43.4 °C, `RH2M` 9 to 100 %, `PS` 96 to 103.5 kPa; all-sky irradiance never exceeds 1.2 × clear-sky + 10 Wh/m².

Limits to keep in mind:
- **Resolution is coarse.** POWER's cells are about 0.5° × 0.625° (meteorology) and 1° (clouds and radiation), so the 100 postcodes carry only **6 distinct radiation/cloud series and 7 temperature series**. Postcodes in the same cell have identical weather. The weather is regional, not per suburb; do not present it as measured at the house.
- **Satellite and reanalysis estimates, not station measurements.**
- **Timestamp: `HH` is the start of the hour, and the value is the mean over the hour** (checked 2026-11-08). In postcode 2008, over the daylight hours of 2010-07 → 2012-06, POWER's `SZA` differs from the zenith computed by `src.ml.sun` by 0.24° on average at `HH + 30 min`, against 4.6° at `HH` and 4.3° at `HH + 60 min`. So a value is known only when its hour ends: `load()` sets `available_at = time + 1 h`.
- **2012-13 is the held-out test year.** The weather for it is downloaded (the file covers 2010–2013) but it is an input, not a label; keep it out of anything tuned before the final evaluation.

### What the model reads: `load(house_ids=None)`
`src.ml.weather.load()` returns one row per UTC hour with `time` (start of the hour), `ghi_wm2` (`ALLSKY_SFC_SW_DWN`, the mean W/m² over the hour), `t2m_c` (`T2M`, °C) and `available_at = time + 1 h`.
- **Station series.** `house_ids` (`AG-0001` form) are the station's houses. Their postcodes' series are averaged, each weighted by its number of houses; a missing value is skipped, and an hour missing everywhere stays NaN, never 0. `None` uses all 300 houses. On 2026-11-08 the 210-house station of the label generator differed from the all-house series by at most 13 W/m² and 0.06 °C, because the grid is coarse.
- **Leakage rule.** A feature for decision time `t` may only use rows with `available_at <= t`.
- **History only.** POWER is a reanalysis published days later. Here it stands in for a live weather feed; in a deployment a live source (for example Open-Meteo or ANM, a team decision in P6) would replace it, with the same `available_at` rule.
- **Not the Sydney point of the P6 brief.** Step 01 of `docs/tasks/p6-ml-v2.md` asked for one Sydney point in `raw/nasa_power/sydney.parquet`. The per-postcode download was already there and covers the houses' own cells, so `load()` builds the station series from it instead of a second download.
