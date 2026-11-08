"""Hourly weather and solar radiation for the postcodes of the houses, from NASA POWER.

    python -m src.ml.weather fetch [--start-year 2010] [--end-year 2013] [--workers 3]
    python -m src.ml.weather build

``fetch`` asks the NASA POWER hourly point API (https://power.larc.nasa.gov/api/temporal/hourly/point,
no key needed) for one year per postcode and keeps each answer as it came in
``DATA_DIR/raw/nasa_power/hourly/<postcode>_<year>.json``. A file that is already there is not
asked again, so an interrupted run can simply be started again. ``build`` joins the files into
``DATA_DIR/weather_hourly.parquet``: one row per postcode and hour, timestamps in UTC.

The API refuses a JSON answer longer than about two years, hence one request per year.
Coordinates are the per-postcode centres of ``src.ml.geo`` (about a kilometre of precision, which
is far finer than the data: POWER's cells are ~0.5 x 0.625 degrees for the meteorology and ~1 degree
for the clouds and radiation, so neighbouring postcodes often receive identical values).

``load(house_ids)`` gives the model's view: hourly sunlight (``ghi_wm2``) and temperature
(``t2m_c``) for the houses of a station, with the time each value becomes known.

* **Time.** ``time`` is the start of the hour in UTC. The value is the mean over that hour:
  POWER's solar zenith angle matches the sun at ``time + 30 min`` (0.24 degrees on average over
  2010-07 to 2012-06 daylight hours in postcode 2008; 4.6 degrees at ``time``, 4.3 at
  ``time + 60 min``).
* **Availability rule.** ``available_at = time + 1 h``: a value is used only once its hour is over,
  so a feature at decision time ``t`` may only use rows with ``available_at <= t``.
* **History only.** POWER is a reanalysis published days later, not a forecast or a live feed.
  It stands in for a live weather source in the simulation; it is never a source for the future.
* **Licence.** CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/); the source is named in
  the README and on the slides. Details and pitfalls: ``src/ml/DATA.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from src.ml import geo
from src.ml.config import data_dir

API_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
USER_AGENT = "smarthack-ppc-team"
TIMEOUT_S = 120
RETRIES = 5
COMMUNITY = "re"  # renewable energy: units suited to solar work
FILL_VALUE = -999.0  # what POWER writes where it has no value
# Every parameter of the hourly API that matters for rooftop solar and for the load. One request
# may carry at most 20.
PARAMETERS = (
    "ALLSKY_SFC_SW_DWN",  # global horizontal irradiance, Wh/m^2
    "ALLSKY_SFC_SW_DIFF",  # diffuse part
    "ALLSKY_SFC_SW_DNI",  # direct normal
    "CLRSKY_SFC_SW_DWN",  # same as the first, if the sky were clear
    "ALLSKY_KT",  # clearness index (null at night)
    "CLOUD_AMT",  # cloud amount, %
    "SZA",  # solar zenith angle, degrees
    "T2M",  # temperature at 2 m, C
    "RH2M",  # relative humidity, %
    "WS10M",  # wind speed at 10 m, m/s
    "WD10M",  # wind direction, degrees
    "PS",  # surface pressure, kPa
    "PRECTOTCORR",  # rain, mm/hour
)
OUTPUT_FILE = "weather_hourly.parquet"
# The two parameters the model uses, and their names in ``load()``.
MODEL_COLUMNS = {"ALLSKY_SFC_SW_DWN": "ghi_wm2", "T2M": "t2m_c"}
KNOWN_AFTER = pd.Timedelta(hours=1)  # a value is the mean of its hour: known when the hour ends


def raw_dir() -> Path:
    return data_dir() / "raw" / "nasa_power" / "hourly"


def raw_path(postcode: str, year: int) -> Path:
    return raw_dir() / f"{postcode}_{year}.json"


def weather_path() -> Path:
    return data_dir() / OUTPUT_FILE


def postcodes() -> pd.DataFrame:
    """One row per postcode: ``postcode``, ``lat``, ``lon``, ``houses``."""
    houses = geo.load()
    table = houses.groupby("postcode", as_index=False).agg(
        lat=("lat", "first"), lon=("lon", "first"), houses=("house_id", "count")
    )
    return table.sort_values("postcode", ignore_index=True)


def request_url(lat: float, lon: float, year: int) -> str:
    query = {
        "start": f"{year}0101",
        "end": f"{year}1231",
        "latitude": f"{lat:.5f}",
        "longitude": f"{lon:.5f}",
        "community": COMMUNITY,
        "parameters": ",".join(PARAMETERS),
        "format": "json",
        "time-standard": "utc",  # the same clock as profiles.parquet
    }
    return f"{API_URL}?{urllib.parse.urlencode(query, safe=',')}"


def fetch_year(lat: float, lon: float, year: int) -> bytes:
    """One year of hourly data for one point, as the API's JSON text."""
    request = urllib.request.Request(
        request_url(lat, lon, year), headers={"User-Agent": USER_AGENT}
    )
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:
                return resp.read()
        except urllib.error.HTTPError as error:
            # 4xx other than "too many requests" is our mistake: asking again changes nothing
            if error.code != 429 and error.code < 500:
                raise RuntimeError(f"NASA POWER refused {year} at {lat},{lon}: {error}") from error
            failure = error
        except (urllib.error.URLError, TimeoutError) as error:
            failure = error
        time.sleep(2**attempt)
    raise RuntimeError(f"NASA POWER failed {RETRIES} times for {year} at {lat},{lon}: {failure}")


def check_answer(body: bytes, year: int) -> None:
    """Raise unless the answer holds every parameter for every hour of the year."""
    parameter = json.loads(body)["properties"]["parameter"]
    hours = int((pd.Timestamp(f"{year + 1}-01-01") - pd.Timestamp(f"{year}-01-01")).days * 24)
    missing = [p for p in PARAMETERS if p not in parameter]
    short = [p for p in PARAMETERS if p in parameter and len(parameter[p]) != hours]
    if missing or short:
        raise ValueError(f"{year}: missing parameters {missing}, wrong length {short}")


def download_one(job: tuple[str, float, float, int]) -> tuple[str, int, str]:
    postcode, lat, lon, year = job
    path = raw_path(postcode, year)
    if path.exists():
        return postcode, year, "cached"
    body = fetch_year(lat, lon, year)
    check_answer(body, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(body)
    tmp.replace(path)  # a half-written file never looks like a finished one
    return postcode, year, "downloaded"


def fetch(start_year: int, end_year: int, workers: int) -> int:
    table = postcodes()
    jobs = [
        (row.postcode, row.lat, row.lon, year)
        for row in table.itertuples()
        for year in range(start_year, end_year + 1)
    ]
    print(f"{len(table)} postcodes x {end_year - start_year + 1} years = {len(jobs)} requests")
    done = failed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [(job, pool.submit(download_one, job)) for job in jobs]
        for job, future in futures:
            try:
                future.result()
            except Exception as error:  # keep going: the rest is cached for the next run
                failed += 1
                print(f"FAILED {job[0]} {job[3]}: {error}", file=sys.stderr)
            done += 1
            if done % 25 == 0 or done == len(jobs):
                print(f"{done}/{len(jobs)} done, {failed} failed", flush=True)
    return 1 if failed else 0


def read_raw(path: Path) -> pd.DataFrame:
    """One cached answer as a table indexed by UTC hour, one column per parameter."""
    parameter = json.loads(path.read_text())["properties"]["parameter"]
    frame = pd.DataFrame({name: parameter[name] for name in PARAMETERS})
    frame.index = pd.to_datetime(frame.index, format="%Y%m%d%H", utc=True)
    return frame.astype("float32").mask(frame == FILL_VALUE, np.nan)


def build(start_year: int, end_year: int, csv: bool = False) -> pd.DataFrame:
    """Join the cached answers into one table and write it. Raise if any is missing.

    With ``csv`` the same table is also written as ``weather_hourly.csv`` (for spreadsheets).
    """
    table = postcodes()
    years = range(start_year, end_year + 1)
    missing = [f"{p}_{y}" for p in table["postcode"] for y in years if not raw_path(p, y).exists()]
    if missing:
        raise FileNotFoundError(
            f"{len(missing)} answers are not downloaded yet (first: {missing[:3]}): run `fetch`"
        )
    parts = []
    for row in table.itertuples():
        frame = pd.concat([read_raw(raw_path(row.postcode, y)) for y in years]).sort_index()
        frame.index.name = "time_utc"
        frame.insert(0, "postcode", row.postcode)
        parts.append(frame.reset_index())
    out = pd.concat(parts, ignore_index=True)
    out["postcode"] = out["postcode"].astype("category")
    out.to_parquet(weather_path(), index=False)
    sha_path(weather_path()).write_text(f"{file_sha256(weather_path())}  {OUTPUT_FILE}\n")
    if csv:
        out.to_csv(weather_path().with_suffix(".csv"), index=False, date_format="%Y-%m-%d %H:%M")
    return out


def sha_path(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load(house_ids: list[str] | None = None) -> pd.DataFrame:
    """Hourly sunlight and temperature for a station, with the time each value is known.

    Columns: ``time`` (UTC, start of the hour), ``ghi_wm2`` (mean W/m^2 over the hour),
    ``t2m_c`` (mean C), ``available_at`` (``time + 1 h``). One row per hour, sorted.

    ``house_ids`` (``AG-0001`` form) are the station's houses: the series of their postcodes are
    averaged, each postcode weighted by its number of houses, skipping missing values. ``None``
    uses every house. An hour where no postcode has a value stays NaN, never 0.
    """
    path = weather_path()
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found: run `python -m src.ml.weather fetch` then `build`"
        )
    houses = geo.load()
    if house_ids is not None:
        wanted = set(house_ids)
        unknown = sorted(wanted - set(houses["house_id"]))
        if unknown:
            raise ValueError(f"houses without a postcode in the geo table: {unknown[:5]}")
        houses = houses[houses["house_id"].isin(wanted)]
    weights = houses["postcode"].astype(str).value_counts()
    frame = pd.read_parquet(
        path,
        columns=["postcode", "time_utc", *MODEL_COLUMNS],
        filters=[("postcode", "in", list(weights.index))],
    )
    frame["postcode"] = frame["postcode"].astype(str)
    missing = sorted(set(weights.index) - set(frame["postcode"]))
    if missing:
        raise ValueError(f"no weather for postcodes {missing[:5]}: run `fetch` and `build` again")
    w = frame["postcode"].map(weights).astype("float64")
    columns = {}
    for source, name in MODEL_COLUMNS.items():
        value = frame[source].astype("float64")
        present = value.notna()
        num = (value.fillna(0) * w).groupby(frame["time_utc"]).sum()
        den = w.where(present, 0.0).groupby(frame["time_utc"]).sum()
        columns[name] = (num / den).where(den > 0)
    out = pd.DataFrame(columns).rename_axis("time").reset_index()
    out["time"] = pd.to_datetime(out["time"], utc=True)
    out["available_at"] = out["time"] + KNOWN_AFTER
    return out.sort_values("time", ignore_index=True)


def load_prepared(house_ids: list[str] | None = None) -> pd.DataFrame:
    """Same table as ``load``, from the hourly weather of the prepared dataset.

    Uses ``DATA_DIR/raw/weather/weather_hourly_*.csv`` and the postcode of each house in
    ``DATA_DIR/prepared/dataset/train.parquet`` (``src.ml.dataset``), so no geo table or
    ``weather_hourly.parquet`` is needed.
    """
    from src.ml import dataset  # imported here: dataset imports modules that import this one

    houses = pd.read_parquet(dataset.out_dir() / "train.parquet", columns=["house_id", "postcode"])
    houses = houses.drop_duplicates("house_id")
    if house_ids is not None:
        wanted = set(house_ids)
        unknown = sorted(wanted - set(houses["house_id"]))
        if unknown:
            raise ValueError(f"houses without a postcode in the dataset: {unknown[:5]}")
        houses = houses[houses["house_id"].isin(wanted)]
    weights = houses["postcode"].astype(str).value_counts()
    frame = dataset.load_weather(dataset.raw_dir() / "weather")
    frame = frame[frame["postcode"].isin(weights.index)]
    missing = sorted(set(weights.index) - set(frame["postcode"]))
    if missing:
        raise ValueError(f"no weather for postcodes {missing[:5]}")
    w = frame["postcode"].map(weights).astype("float64")
    columns = {}
    for source, name in MODEL_COLUMNS.items():
        value = frame[source].astype("float64")
        num = (value.fillna(0) * w).groupby(frame["hour"]).sum()
        den = w.where(value.notna(), 0.0).groupby(frame["hour"]).sum()
        columns[name] = (num / den).where(den > 0)
    out = pd.DataFrame(columns).rename_axis("time").reset_index()
    out["time"] = pd.to_datetime(out["time"], utc=True)
    out["available_at"] = out["time"] + KNOWN_AFTER
    return out.sort_values("time", ignore_index=True)


def describe(out: pd.DataFrame) -> None:
    hours = out.groupby("postcode", observed=True).size()
    print(
        f"{weather_path()}: {len(out):,} rows, {out['postcode'].nunique()} postcodes, "
        f"{hours.min()}-{hours.max()} hours each, "
        f"{out['time_utc'].min()} to {out['time_utc'].max()}"
    )
    print(f"SHA-256 {sha_path(weather_path()).read_text().split()[0]}")
    print("share of missing values per parameter:")
    print((out[list(PARAMETERS)].isna().mean() * 100).round(2).to_string())
    values = out.drop_duplicates("postcode")
    cells = out.pivot(index="time_utc", columns="postcode", values="T2M").T.drop_duplicates()
    print(f"postcodes with a distinct 2010-2013 temperature series: {len(cells)} of {len(values)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.ml.weather")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("fetch", "download the hourly answers"), ("build", "join them to parquet")):
        command = sub.add_parser(name, help=text)
        command.add_argument("--start-year", type=int, default=2010)
        command.add_argument("--end-year", type=int, default=2013)
        if name == "fetch":
            command.add_argument("--workers", type=int, default=3)
        else:
            command.add_argument("--csv", action="store_true", help="also write a CSV file")
    args = parser.parse_args(argv)
    if args.command == "fetch":
        return fetch(args.start_year, args.end_year, args.workers)
    describe(build(args.start_year, args.end_year, csv=args.csv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
