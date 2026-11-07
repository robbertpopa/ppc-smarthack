# P2-01 · `ml/data-download`: done

Brief: [01-data-download.md](01-data-download.md). Branch: `ml/ausgrid-profiles` (task 01 is the first commit).

## What was built
| File | Purpose |
|---|---|
| `src/ml/config.py` | `data_dir()` and `artifact_uri()`, thin wrappers over P1's `src.common.config.Settings` (one source of truth, relative defaults `./data` and `./artifacts`) |
| `src/ml/data.py` | CLI `python -m src.ml.data download [--force] [--from DIR_OR_ZIP]` |
| `src/ml/DATA.md` | Sources, licence status, checksums, format notes |
| `tests/ml/test_data_download.py` | 11 tests, no network |

## How it works
- Downloads `https://pierreh.eu/downloads/Ausgrid_solar_home_data.zip` with the standard library, a generic `User-Agent` (`smarthack-ppc-team`), a 60 s timeout, streaming to a `.part` file and then a rename.
- Writes `DATA_DIR/raw/SHA256SUMS` (sha256sum format) for the zip and every extracted file. A second run downloads nothing if the zip matches. If only an extracted file is missing or edited, it is restored from the zip without the network.
- Extracts into `DATA_DIR/raw/ausgrid/`; rejects zip entries that would escape that folder.
- Finds half-hourly CSVs by **header** (`Customer,…,Consumption Category,…,0:30`), not by name, so the monthly files are skipped. The first line of each file is a title row; the header is line 2.
- Prints file names, sizes, data rows, the title line and the header line.
- `--from` (not in the brief): ingest a local zip or already extracted folder with no network, for a slow venue network.

## Findings recorded in `DATA.md`
- The copy's own README says the data was published by Ausgrid under **CC BY 3.0 Australia** (attribution required). Not verified against Ausgrid, whose page is withdrawn.
- Formats: 2010-11 has 53 columns and dates like `1-Jul-10`; 2011-12 and 2012-13 have 54 (adds `Row Quality`) and dates like `1/07/2011`, CRLF line endings and a trailing comma.
- 300 houses per file; controlled load for only 139 / 139 / 138 houses; 81 house-days missing in 2012-13; no duplicate rows.

## Acceptance
| Check | Result |
|---|---|
| `python -m pytest tests/ml/test_data_download.py` passes without network | Pass (11 tests) |
| Second run downloads nothing | Pass in the tests (faked downloader). Not run against the real server |
| No files under `data/` in `git status` | Pass (`data/` is ignored) |
| No data, absolute paths or secrets in the diff | Pass |

## Not done / open
- **The real HTTP path is untested**: the team already holds the zip, so no download was made. Only the faked downloader has run.
- **SHA-256 of the zip is not in `DATA.md`.** It needs `sha256sum` on the team's copy (the file was deliberately not opened).
- **Requests for P1:** a `make data` target (`python -m src.ml.data download`), and `pytest` in the dev dependencies (already there).
- **Held-out year:** `--from` copied the 2012-13 file, which the team keeps as the test set. See the open item in [02_ausgrid-profiles_done.md](02_ausgrid-profiles_done.md).

## Hand-off
"P2-01 done: `python -m src.ml.data download` fetches Ausgrid into `DATA_DIR/raw/ausgrid/`, notes in `src/ml/DATA.md`."
