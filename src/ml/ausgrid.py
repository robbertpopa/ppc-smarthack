"""Parse and clean the Ausgrid half-hourly CSVs into one tidy, UTC-indexed table.

Conventions (evidence in DATA.md):
* Each CSV row is one house, one category (GC/CL/GG) and one day; 48 columns.
* A column is labelled by the time its half hour *ends*: ``0:30`` is 00:00-00:30
  and ``0:00`` is the last interval of the day (23:30-24:00).
* Values are kWh per half hour; ``kW = kWh * 2``.
* Timestamps are Sydney wall-clock time **with daylight saving**. In a fixed
  48-column day that has two consequences, handled in ``_utc_map``:
  - spring forward: the 02:00-03:00 hour does not exist, the file holds zeros;
  - fall back: the repeated 02:00-03:00 hour is summed into one, so it cannot be
    split into its two UTC intervals.
* ``available_at = interval_start + 30 min`` for measured values (not stored).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from src.ml.config import SYDNEY as TZ
from src.ml.data import half_hourly_csvs, inspect_csv

MAX_GG_PER_KWP = 1.2
CATEGORIES = ("GC", "CL", "GG")
DATE_FORMATS = ("%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%d/%m/%y", "%d%b%Y")
KEY = ["house_id", "category", "interval_start"]
OUTPUT_COLUMNS = [
    "house_id",
    "interval_start",
    "gc_kw",
    "cl_kw",
    "gg_kw",
    "kwp",
    "postcode",
    "quality",
]

RULE_TEXT = {
    "values_read": "half-hour readings read from the CSV files",
    "duplicate_readings_dropped": "duplicate (house, category, interval) readings dropped",
    "dst_nonexistent_hour_dropped": "filler for the non-existent hour (spring forward), dropped",
    "dst_repeated_hour_nulled": "merged repeated hour (fall back), set to null",
    "negative_to_null": "negative readings set to null",
    "gg_above_limit_to_null": f"gross generation above {MAX_GG_PER_KWP} x kWp set to null",
    "duplicate_rows_across_files": "duplicate (house, interval) rows across files dropped",
}


def _parse_dates(values: pd.Series) -> pd.Series:
    """Parse a date column whose format differs between files (detected, not assumed)."""
    unique = pd.Series(values.unique())
    for fmt in DATE_FORMATS:
        parsed = pd.to_datetime(unique, format=fmt, errors="coerce")
        if parsed.notna().all():
            return values.map(dict(zip(unique, parsed)))
    raise ValueError(f"unrecognised date format, e.g. {values.iloc[0]!r}")


def _interval_start_minute(label: str) -> int:
    """'0:30' -> 0 (the half hour ends at 0:30); '0:00' -> 1410 (ends at midnight)."""
    hours, minutes = label.split(":")
    end = int(hours) * 60 + int(minutes) or 1440
    return end - 30


def _repeat(values: pd.Series, times: int) -> pd.Categorical:
    cat = pd.Categorical(values)
    return pd.Categorical.from_codes(np.repeat(cat.codes, times), cat.categories)


def parse_file(path: Path) -> pd.DataFrame:
    """One Ausgrid file in long format, in the file's own local clock.

    Columns: house_id, category, interval_start (naive Sydney wall clock),
    kwh, kwp, postcode, quality ("NA" or null). Nothing is cleaned here.
    """
    info = inspect_csv(path, header_only=True)
    if not info.half_hourly:
        raise ValueError(f"{path.name}: not a half-hourly Ausgrid file")
    # keep_default_na=False: the quality flag "NA" must not become a missing value
    raw = pd.read_csv(
        path, skiprows=info.header_index, dtype=str, keep_default_na=False, encoding="utf-8-sig"
    )
    time_cols = [c for c in raw.columns if ":" in c]
    starts = np.array([_interval_start_minute(c) for c in time_cols])
    if sorted(starts) != list(range(0, 1440, 30)):
        raise ValueError(f"{path.name}: expected 48 half-hour columns, got {time_cols}")
    if not set(raw["Consumption Category"]) <= set(CATEGORIES):
        raise ValueError(f"{path.name}: unknown consumption categories")

    n = len(raw)
    kwh = raw[time_cols].apply(pd.to_numeric).to_numpy(dtype="float64")  # "" -> NaN, junk raises
    days = _parse_dates(raw["date"]).to_numpy("datetime64[ns]")
    offsets = (starts * 60).astype("timedelta64[s]").astype("timedelta64[ns]")
    ids = raw["Customer"].map(lambda c: f"AG-{int(c):04d}")
    quality = (
        raw["Row Quality"].replace("", None)
        if "Row Quality" in raw.columns
        else pd.Series([None] * n)
    )
    return pd.DataFrame(
        {
            "house_id": _repeat(ids, 48),
            "category": _repeat(raw["Consumption Category"], 48),
            "interval_start": np.repeat(days, 48) + np.tile(offsets, n),
            "kwh": kwh.ravel(),
            "kwp": np.repeat(pd.to_numeric(raw["Generator Capacity"]).to_numpy(), 48),
            "postcode": _repeat(raw["Postcode"], 48),
            "quality": _repeat(quality.astype(object), 48),
        }
    )


def _utc_map(local: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    """Map naive Sydney timestamps to UTC.

    Returns (map with columns interval_start, utc, blank; non-existent timestamps).
    A repeated (ambiguous) timestamp gets two UTC rows, both ``blank`` because the
    file holds only the sum of the two readings.
    """
    plain = local.tz_localize(TZ, ambiguous="NaT", nonexistent="NaT")
    bad = plain.isna()
    parts = [
        pd.DataFrame(
            {"interval_start": local[~bad], "utc": plain[~bad].tz_convert("UTC"), "blank": False}
        )
    ]
    problem = local[bad]
    gone = problem.tz_localize(TZ, ambiguous=np.ones(len(problem), bool), nonexistent="NaT").isna()
    repeated = problem[~gone]
    for first_pass in (True, False):
        utc = repeated.tz_localize(TZ, ambiguous=np.full(len(repeated), first_pass)).tz_convert(
            "UTC"
        )
        parts.append(pd.DataFrame({"interval_start": repeated, "utc": utc, "blank": True}))
    return pd.concat(parts, ignore_index=True), problem[gone]


def _profiles_from_long(long: pd.DataFrame, rules: Counter) -> pd.DataFrame:
    """One file: dedupe, pivot categories to columns, move to UTC, kWh to kW, clean."""
    cats, cols = list(CATEGORIES), ["gc_kw", "cl_kw", "gg_kw"]
    rules["values_read"] += int(long["kwh"].notna().sum())
    dup = long.duplicated(KEY)
    rules["duplicate_readings_dropped"] += int(dup.sum())
    rules["gg_kwh_removed"] += float(long.loc[dup & (long["category"] == "GG"), "kwh"].sum())
    long = long[~dup]

    static = long.drop_duplicates("house_id")[["house_id", "kwp", "postcode"]]
    long = long.assign(na=(long["quality"] == "NA").astype("float32"))
    wide = long.set_index(["house_id", "interval_start", "category"])[["kwh", "na"]].unstack(
        "category"
    )
    na = wide["na"].max(axis=1).gt(0)  # any category of the day flagged non-actual
    wide = wide["kwh"].reindex(columns=cats)
    wide["na"] = na
    wide = wide.reset_index()
    wide.columns.name = None

    tzmap, nonexistent = _utc_map(pd.DatetimeIndex(wide["interval_start"].unique()))
    for rule, hit in (
        ("dst_nonexistent_hour_dropped", wide["interval_start"].isin(nonexistent)),
        (
            "dst_repeated_hour_nulled",
            wide["interval_start"].isin(tzmap.loc[tzmap["blank"], "interval_start"]),
        ),
    ):
        rules[rule] += int(wide.loc[hit, cats].notna().sum().sum())
        rules["gg_kwh_removed"] += float(wide.loc[hit, "GG"].sum())
    wide = wide.merge(
        tzmap, on="interval_start", how="inner"
    )  # inner: the non-existent hour disappears
    wide.loc[wide["blank"], cats] = np.nan
    wide["interval_start"] = wide["utc"]
    wide["quality"] = pd.Series(np.where(wide["na"], "NA", None), dtype="object", index=wide.index)
    wide = wide.drop(columns=["utc", "blank", "na"]).merge(static, on="house_id", how="left")

    wide = wide.rename(columns=dict(zip(cats, cols)))
    wide[cols] = wide[cols] * 2  # kWh per half hour -> mean kW
    negative = wide[cols] < 0
    rules["negative_to_null"] += int(negative.sum().sum())
    rules["gg_kwh_removed"] += float(wide.loc[negative["gg_kw"], "gg_kw"].sum()) / 2
    wide[cols] = wide[cols].mask(negative)
    over = wide["gg_kw"] > MAX_GG_PER_KWP * wide["kwp"]
    rules["gg_above_limit_to_null"] += int(over.sum())
    rules["gg_kwh_removed"] += float(wide.loc[over, "gg_kw"].sum()) / 2
    wide.loc[over, "gg_kw"] = np.nan
    return wide[OUTPUT_COLUMNS]


def build_profiles(raw_dir: Path, include_held_out: bool = False) -> pd.DataFrame:
    """All half-hourly files under ``raw_dir`` as one cleaned table, UTC.

    One row per house and half hour; kW, not kWh. ``interval_start`` is the start
    of the interval and ``available_at`` is ``interval_start + 30 min``. The cleaning
    counts are in ``result.attrs["rules"]``. Whole missing days stay missing.
    """
    rules: Counter = Counter()
    files = half_hourly_csvs(raw_dir, include_held_out)
    parts = [_profiles_from_long(parse_file(p), rules) for p in files]
    if not parts:
        raise FileNotFoundError(f"no half-hourly Ausgrid CSV under {raw_dir}")
    out = pd.concat(parts, ignore_index=True)
    dup = out.duplicated(["house_id", "interval_start"])
    rules["duplicate_rows_across_files"] += int(dup.sum())
    out = out[~dup].sort_values(["house_id", "interval_start"], ignore_index=True)
    for col in ("house_id", "postcode"):
        out[col] = out[col].astype(str)
    out.attrs["rules"] = dict(rules)
    return out


def summarize(profiles: pd.DataFrame) -> str:
    """Data-quality summary: coverage, nulls per column, every cleaning rule with its count."""
    rules = profiles.attrs.get("rules", {})
    local = profiles["interval_start"].dt.tz_convert(TZ)
    per_day = profiles.groupby([profiles["house_id"], local.dt.date], observed=True).size()
    day_lengths = {int(k): int(v) for k, v in per_day.value_counts().sort_index().items()}
    lines = [
        f"houses: {profiles['house_id'].nunique()}",
        f"rows: {len(profiles):,}",
        f"range (Sydney): {local.min():%Y-%m-%d %H:%M} .. {local.max():%Y-%m-%d %H:%M}",
        f"intervals per house-day: {day_lengths}",
        "nulls per column:",
    ]
    lines += [f"  {c}: {n:,} ({n / len(profiles):.1%})" for c, n in profiles.isna().sum().items()]
    lines.append("cleaning rules (counts are half-hour readings):")
    lines += [
        f"  {k}: {rules.get(k, 0):,.0f}  {text}" for k, text in RULE_TEXT.items() if k in rules
    ]
    return "\n".join(lines)


def generation_check(raw_dir: Path, profiles: pd.DataFrame) -> list[dict]:
    """Per file: gross generation summed straight from the raw CSV vs the profiles.

    ``raw`` must equal ``profile + removed`` (what the cleaning rules took out); ``removed``
    is global, so compare the totals.
    """
    rows = []
    for path in half_hourly_csvs(raw_dir):
        long = parse_file(path)
        gg = long["category"] == "GG"
        total = float(long.loc[gg, "kwh"].sum())
        days = long.loc[gg, "interval_start"].dt.normalize()
        start = days.min().tz_localize(TZ)
        end = (days.max() + pd.Timedelta(days=1)).tz_localize(TZ)
        window = (profiles["interval_start"] >= start) & (profiles["interval_start"] < end)
        rows.append(
            {
                "file": path.name,
                "raw_gg_kwh": total,
                "profile_gg_kwh": profiles.loc[window, "gg_kw"].sum() / 2,
            }
        )
    return rows
