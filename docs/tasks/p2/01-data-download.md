# P2-01 · `ml/data-download`

| | |
|---|---|
| Gate | G0 |
| Target | T+0:00–0:45 (18:00–18:45) |
| Depends on | P1 scaffold (folders, `pyproject.toml`). If it is not merged yet, start anyway; rebase when it lands |
| Unblocks | [02](02-ausgrid-profiles.md) |
| Size budget | ~150 changed lines |
| Cut | never |
| Covers | Mandatory rule "public data, sources stated"; ML quality (data prepared by the team) |

## Context
The primary dataset is Ausgrid "Solar home electricity data" (Sydney, 300 homes with panels, 30-minute readings, 2010–2013). The original page is withdrawn; we use the unofficial copy. Links and pitfalls: [../../05-data-and-sources.md](../../05-data-and-sources.md). Data is never committed.

## Goal
One command downloads the raw data into `DATA_DIR/raw/`, verifies it, and prints what it found. A short notes file documents the source, the licence status and the formats.

## Files
- `src/ml/__init__.py` (empty or a docstring only; 07 adds the public API)
- `src/ml/config.py`: reads `DATA_DIR` and `ARTIFACT_URI` from the environment with the local defaults from [../../10-cloud.md](../../10-cloud.md). If P1's scaffold already has a config module in `src/common/`, re-export it instead of duplicating.
- `src/ml/data.py`
- `src/ml/DATA.md`
- `tests/ml/test_data_download.py`

## Steps
1. `config.py`: `data_dir() -> Path` (default `./data`), `artifact_uri() -> str` (default `./artifacts`). Relative paths resolve against the current working directory, never an absolute path in code.
2. `data.py` with a CLI: `python -m src.ml.data download`.
   - Source URL: `https://pierreh.eu/downloads/Ausgrid_solar_home_data.zip`.
   - Download with the standard library, a generic `User-Agent` (for example `smarthack-ppc-team`), a timeout, and streaming to a temporary file, then rename. No personal data in headers.
   - Skip the download if the file exists and its SHA-256 matches `data/raw/SHA256SUMS`; `--force` re-downloads.
   - Unzip into `DATA_DIR/raw/ausgrid/`. Write `SHA256SUMS` for the zip and every extracted file.
   - Print: file names, sizes, row counts, the first header line of each CSV.
3. `DATA.md`: source URLs (copy, original, archive), "licence of the copy not verified", the SHA-256 of the zip as observed on first download, and the format notes you saw (header row, columns, date format per file). Keep it factual and short.
4. Ask P1 to add `make data` → `python -m src.ml.data download` (P1 owns the Makefile).

## Interface
```python
# src/ml/data.py
def download(force: bool = False) -> list[Path]: ...   # returns extracted CSV paths
```

## Acceptance
- `python -m pytest tests/ml/test_data_download.py` passes **without network**: test the checksum/skip logic with a small temporary file and a monkeypatched downloader.
- `python -m src.ml.data download` run twice: the second run downloads nothing.
- `git status` shows no files under `data/`.

## Definition of done
- Raw data is reproducible from one command; sources and licence status are written down.
- No data, no absolute paths, no secrets in the diff.

## Pitfalls
- The expected content is three CSVs, one per financial year (July to June). Verify on download; do not assume file names in later code, detect the format from the header (see 02).
- The first line of each CSV may be a title row, not the header. Note it in `DATA.md`.

## Out of scope
Parsing and cleaning (that is 02). GoiEner and SimBench downloads (SimBench is installed by P3 as a package).

## Hand-off
"P2-01 merged: `python -m src.ml.data download` fetches Ausgrid into `DATA_DIR/raw/ausgrid/`, notes in `src/ml/DATA.md`."
