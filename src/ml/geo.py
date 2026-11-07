"""Where the 300 Ausgrid houses are: postcode, suburb names and a coordinate.

Two small files describe the houses:

* ``ausgrid_postcodes_geo.csv`` (team-made): ``Customer, Generator Capacity, Postcode,
  lat, lon, localities``. The coordinate is **per postcode** (a suburb-level centre, about
  a kilometre of precision), not the position of a house. 100 postcodes cover the 300 houses.
* ``Solar home 2010-2011 post codes.csv`` (Ausgrid's own, ``Customer, Generator Capacity,
  Postcode`` after a title line): the official postcode of each house. The geo file must
  agree with it, so it is used to check the geo file when both are given.

Both are stored in ``DATA_DIR/reference/`` and are never committed. ``Customer`` is the
same number as in the half-hourly files, so ``AG-0001`` is customer 1.

    python -m src.ml.data geo --from <geo.csv> [--postcodes <official.csv>]
"""

import shutil
from pathlib import Path

import pandas as pd

from src.ml.config import data_dir

GEO_FILE = "ausgrid_postcodes_geo.csv"
OFFICIAL_FILE = "Solar home 2010-2011 post codes.csv"
GEO_COLUMNS = ["Customer", "Generator Capacity", "Postcode", "lat", "lon", "localities"]
OFFICIAL_COLUMNS = ["Customer", "Generator Capacity", "Postcode"]
# New South Wales, with some margin: anything outside is a typo, not a house
LAT_RANGE = (-37.6, -28.0)
LON_RANGE = (140.9, 153.7)
TOLERANCE = 1e-9


def reference_dir() -> Path:
    return data_dir() / "reference"


def house_id(customer: int) -> str:
    """The id used in ``profiles.parquet``: customer 1 is ``AG-0001``."""
    return f"AG-{int(customer):04d}"


def _read(path, columns: list[str]) -> pd.DataFrame:
    """Read a CSV that may start with a title line (``2010-2011 ,,``) before the header."""
    path = Path(path)
    with open(path, encoding="utf-8-sig") as handle:
        first = handle.readline()
    skip = 0 if first.lstrip().startswith("Customer") else 1
    frame = pd.read_csv(path, skiprows=skip, dtype={"Postcode": str}, encoding="utf-8-sig")
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}, found {list(frame.columns)}")
    return frame


def read_official(path) -> pd.DataFrame:
    """Ausgrid's own list of customers, capacities and postcodes."""
    frame = _read(path, OFFICIAL_COLUMNS)[OFFICIAL_COLUMNS]
    problems = _basic_problems(frame, Path(path).name)
    if problems:
        raise ValueError("; ".join(problems))
    return frame


def _basic_problems(frame: pd.DataFrame, name: str) -> list[str]:
    problems = []
    if frame["Customer"].isna().any() or frame["Customer"].duplicated().any():
        problems.append(f"{name}: Customer must be unique and not empty")
    if frame[["Generator Capacity", "Postcode"]].isna().any().any():
        problems.append(f"{name}: Generator Capacity and Postcode must not be empty")
    elif (frame["Generator Capacity"] <= 0).any():
        problems.append(f"{name}: Generator Capacity must be positive")
    bad = ~frame["Postcode"].astype(str).str.fullmatch(r"\d{4}")
    if bad.any():
        problems.append(f"{name}: {int(bad.sum())} postcodes are not four digits")
    return problems


def read_geo(path) -> pd.DataFrame:
    """The geo file as one row per house, validated.

    Columns: ``house_id``, ``postcode`` (text), ``kwp``, ``lat``, ``lon``, ``localities``.
    Raises ``ValueError`` listing every problem found.
    """
    name = Path(path).name
    raw = _read(path, GEO_COLUMNS)[GEO_COLUMNS]
    problems = _basic_problems(raw, name)
    if raw[["lat", "lon"]].isna().any().any():
        problems.append(f"{name}: lat and lon must not be empty")
    else:
        outside = ~raw["lat"].between(*LAT_RANGE) | ~raw["lon"].between(*LON_RANGE)
        if outside.any():
            problems.append(f"{name}: {int(outside.sum())} coordinates are outside New South Wales")
        spread = raw.groupby("Postcode")[["lat", "lon"]].nunique().max(axis=1)
        if (spread > 1).any():
            problems.append(
                f"{name}: postcodes with more than one coordinate: {list(spread[spread > 1].index)}"
            )
    if problems:
        raise ValueError("geo file invalid: " + "; ".join(problems))
    out = pd.DataFrame(
        {
            "house_id": raw["Customer"].map(house_id),
            "postcode": raw["Postcode"].astype(str),
            "kwp": raw["Generator Capacity"].astype(float),
            "lat": raw["lat"].astype(float),
            "lon": raw["lon"].astype(float),
            "localities": raw["localities"].fillna("").astype(str),
        }
    )
    return out.sort_values("house_id", ignore_index=True)


def check_against_official(geo: pd.DataFrame, official: pd.DataFrame) -> None:
    """The geo file must describe the same customers as Ausgrid's list. Raise if not."""
    ref = official.assign(house_id=official["Customer"].map(house_id)).set_index("house_id")
    got = geo.set_index("house_id")
    problems = []
    only_geo, only_ref = got.index.difference(ref.index), ref.index.difference(got.index)
    if len(only_geo) or len(only_ref):
        problems.append(
            f"customers only in the geo file: {list(only_geo[:5])}; only in the official file: "
            f"{list(only_ref[:5])}"
        )
    both = got.index.intersection(ref.index)
    wrong_kwp = (got.loc[both, "kwp"] - ref.loc[both, "Generator Capacity"]).abs() > TOLERANCE
    wrong_post = got.loc[both, "postcode"] != ref.loc[both, "Postcode"].astype(str)
    if wrong_kwp.any():
        problems.append(f"generator capacity differs for {list(both[wrong_kwp][:5])}")
    if wrong_post.any():
        problems.append(f"postcode differs for {list(both[wrong_post][:5])}")
    if problems:
        raise ValueError(
            "geo file disagrees with the official postcode list: " + "; ".join(problems)
        )


def check_against_profiles(geo: pd.DataFrame, profiles: pd.DataFrame) -> None:
    """The houses, capacities and postcodes must match ``profiles.parquet``. Raise if not."""
    seen = profiles.drop_duplicates("house_id").set_index("house_id")
    got = geo.set_index("house_id")
    both = got.index.intersection(seen.index)
    problems = []
    if len(both) != len(seen):
        problems.append(f"{len(seen) - len(both)} houses of the profiles have no location")
    wrong_kwp = (got.loc[both, "kwp"] - seen.loc[both, "kwp"]).abs() > TOLERANCE
    wrong_post = got.loc[both, "postcode"] != seen.loc[both, "postcode"].astype(str)
    if wrong_kwp.any() or wrong_post.any():
        bad = both[wrong_kwp.to_numpy() | wrong_post.to_numpy()]
        problems.append(f"capacity or postcode differs from the profiles for {list(bad[:5])}")
    if problems:
        raise ValueError("geo file disagrees with profiles.parquet: " + "; ".join(problems))


def ingest(source, official=None) -> dict:
    """Validate the geo file (and check it against the official list) and store both."""
    geo = read_geo(source)
    if official is not None:
        check_against_official(geo, read_official(official))
    target = reference_dir()
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target / GEO_FILE)
    if official is not None:
        shutil.copyfile(official, target / OFFICIAL_FILE)
    return {
        "houses": len(geo),
        "postcodes": int(geo["postcode"].nunique()),
        "checked_against_official": official is not None,
        "folder": str(target),
    }


def load() -> pd.DataFrame:
    """The stored geo table, one row per house, or an error that says how to add it."""
    path = reference_dir() / GEO_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found: add it with `python -m src.ml.data geo --from <geo.csv>`"
        )
    return read_geo(path)
