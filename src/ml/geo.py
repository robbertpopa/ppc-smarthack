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

import os
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
    try:
        with open(path, encoding="utf-8-sig") as handle:
            first = handle.readline()
        skip = 0 if first.lstrip().startswith("Customer") else 1
        # keep "n/a" and "NA" as text (pandas would turn them into empty cells); only a truly
        # empty cell is missing
        frame = pd.read_csv(
            path,
            skiprows=skip,
            dtype=str,
            encoding="utf-8-sig",
            keep_default_na=False,
            na_values=[""],
        )
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as error:
        raise ValueError(f"{path.name}: cannot be read as a CSV file ({error})") from error
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}, found {list(frame.columns)}")
    return frame


def _numbers(frame: pd.DataFrame, name: str, columns: list[str], problems: list[str]) -> None:
    """Turn the columns into numbers in place; report every cell that is not one.

    A text such as ``n/a`` or ``1,5`` becomes NaN here and is named in the problems, so it
    never reaches a comparison as a string.
    """
    for column in columns:
        converted = pd.to_numeric(frame[column], errors="coerce")
        bad = converted.isna() & frame[column].notna() & (frame[column].str.strip() != "")
        if bad.any():
            shown = ", ".join(repr(v) for v in frame.loc[bad, column].head(3))
            problems.append(
                f"{name}: {int(bad.sum())} values in {column} are not numbers ({shown})"
            )
        frame[column] = converted


def _basic_problems(frame: pd.DataFrame, name: str, numeric: list[str]) -> list[str]:
    """Convert the numeric columns and return every problem found in the common columns."""
    problems: list[str] = []
    _numbers(frame, name, numeric, problems)
    if frame["Customer"].isna().any() or frame["Customer"].duplicated().any():
        problems.append(f"{name}: Customer must be unique and not empty")
    elif ((frame["Customer"] % 1 != 0) | (frame["Customer"] < 0)).any():
        problems.append(f"{name}: Customer must be a whole number")
    if frame[["Generator Capacity", "Postcode"]].isna().any().any():
        problems.append(f"{name}: Generator Capacity and Postcode must not be empty")
    elif (frame["Generator Capacity"] <= 0).any():
        problems.append(f"{name}: Generator Capacity must be positive")
    bad = ~frame["Postcode"].fillna("").str.strip().str.fullmatch(r"\d{4}")
    if bad.any():
        problems.append(f"{name}: {int(bad.sum())} postcodes are not four digits")
    return problems


def read_official(path) -> pd.DataFrame:
    """Ausgrid's own list of customers, capacities and postcodes."""
    name = Path(path).name
    frame = _read(path, OFFICIAL_COLUMNS)[OFFICIAL_COLUMNS].copy()
    problems = _basic_problems(frame, name, ["Customer", "Generator Capacity"])
    if problems:
        raise ValueError("official postcode file invalid: " + "; ".join(problems))
    frame["Postcode"] = frame["Postcode"].str.strip()
    return frame


def read_geo(path) -> pd.DataFrame:
    """The geo file as one row per house, validated.

    Columns: ``house_id``, ``postcode`` (text), ``kwp``, ``lat``, ``lon``, ``localities``.
    Raises ``ValueError`` listing every problem found, including text where a number belongs.
    """
    name = Path(path).name
    raw = _read(path, GEO_COLUMNS)[GEO_COLUMNS].copy()
    problems = _basic_problems(raw, name, ["Customer", "Generator Capacity", "lat", "lon"])
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
            "postcode": raw["Postcode"].str.strip(),
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
    """Same houses, same capacities, same postcodes as ``profiles.parquet``. Raise if not.

    Checked in both directions: a house of the profiles without a location, and a located
    house that is not in the profiles, are both reported.
    """
    seen = profiles.drop_duplicates("house_id").set_index("house_id")
    got = geo.set_index("house_id")
    problems = []
    no_location = seen.index.difference(got.index)
    not_in_profiles = got.index.difference(seen.index)
    if len(no_location):
        problems.append(
            f"{len(no_location)} houses of the profiles have no location ({list(no_location[:5])})"
        )
    if len(not_in_profiles):
        problems.append(
            f"{len(not_in_profiles)} located houses are not in the profiles "
            f"({list(not_in_profiles[:5])})"
        )
    both = got.index.intersection(seen.index)
    wrong_kwp = (got.loc[both, "kwp"] - seen.loc[both, "kwp"]).abs() > TOLERANCE
    wrong_post = got.loc[both, "postcode"] != seen.loc[both, "postcode"].astype(str)
    if wrong_kwp.any() or wrong_post.any():
        bad = both[wrong_kwp.to_numpy() | wrong_post.to_numpy()]
        problems.append(f"capacity or postcode differs from the profiles for {list(bad[:5])}")
    if problems:
        raise ValueError("geo file disagrees with profiles.parquet: " + "; ".join(problems))


def _store(source: Path, dest: Path) -> tuple[Path, Path] | None:
    """Copy ``source`` to a temporary name next to ``dest``; ``None`` if it already is ``dest``."""
    if dest.exists() and source.resolve() == dest.resolve():
        return None  # re-checking the stored file: nothing to copy
    temporary = dest.with_name(f".{dest.name}.tmp")
    shutil.copyfile(source, temporary)
    return temporary, dest


def ingest(source, official=None, profiles: pd.DataFrame | None = None) -> dict:
    """Validate the geo file, check it, and only then store it (and the official list).

    Every check runs before anything is written: the file itself, the agreement with the
    official list when given, and the agreement with the profiles when given. A file that
    fails any of them stores nothing. The files are written under temporary names and
    renamed at the end, so a failure while copying never leaves a new geo file next to an old
    official one. ``source`` may already be the stored file (to re-check it).
    """
    source = Path(source)
    geo = read_geo(source)
    if official is not None:
        check_against_official(geo, read_official(official))
    if profiles is not None:
        check_against_profiles(geo, profiles)
    target = reference_dir()
    target.mkdir(parents=True, exist_ok=True)
    pending = []
    try:
        for src, name in (
            (source, GEO_FILE),
            (Path(official) if official else None, OFFICIAL_FILE),
        ):
            if src is not None and (moved := _store(src, target / name)):
                pending.append(moved)
        for temporary, dest in pending:
            os.replace(temporary, dest)
    finally:
        for temporary, _ in pending:
            temporary.unlink(missing_ok=True)
    return {
        "houses": len(geo),
        "postcodes": int(geo["postcode"].nunique()),
        "checked_against_official": official is not None,
        "checked_against_profiles": profiles is not None,
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
