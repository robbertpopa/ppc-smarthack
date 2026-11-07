"""Ground-truth labels (the safe export share per station and half hour).

P3 writes the real file from power flows; until it exists we train on a mock file with
the same schema, so the whole code path is ready. Layout under ``DATA_DIR``:

    labels/<scenario>/labels.parquet         one row per station and half hour
    labels/<scenario>/station_houses.parquet which houses make up the station

Schema of ``labels.parquet`` (times are UTC, power is kW):

    pt_id, interval_start, safe_share (0..1, null if not converged), converged,
    binding (voltage | line | trafo | none, nullable), load_kw, pv_kw, net_kw,
    kwp_total, n_houses, available_at (= interval_start + 30 min), provenance,
    source_ref ("grid/labels.py@<sha>", "mock" for mock files)

Run ``python -m src.ml.labels mock --scenario A`` to write a mock file.
"""

import argparse
import zlib

import numpy as np
import pandas as pd

from .config import data_dir
from .split import SYDNEY
from .sun import solar_elevation

SCENARIOS = ("A", "B", "B-VAR")
BINDING = ("voltage", "line", "trafo", "none")
STEP = pd.Timedelta(minutes=30)
MOCK_REF = "mock"
MOCK_HOUSES = 30
COLUMNS = (
    "pt_id", "interval_start", "safe_share", "converged", "binding", "load_kw", "pv_kw",
    "net_kw", "kwp_total", "n_houses", "available_at", "provenance", "source_ref",
)  # fmt: skip
HOUSE_COLUMNS = ("pt_id", "house_id", "source_house_id", "kwp", "load_scale", "pv_scale")


def pt_id(scenario: str) -> str:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}, expected one of {SCENARIOS}")
    return f"PT-{scenario}"


def _is_utc(series: pd.Series) -> bool:
    tz = getattr(series.dt, "tz", None)
    if tz is None:
        return False
    return all(
        pd.Timestamp(d, tz=tz).utcoffset() == pd.Timedelta(0) for d in ("2020-01-01", "2020-07-01")
    )


def validate(df: pd.DataFrame) -> None:
    """Raise ``ValueError`` listing every problem found; return nothing if the file is fine."""
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"labels invalid: missing columns {missing}")

    problems: list[str] = []
    for col in ("interval_start", "available_at"):
        if not pd.api.types.is_datetime64_any_dtype(df[col]) or not _is_utc(df[col]):
            problems.append(f"{col} must be a UTC timezone-aware timestamp")
    if not pd.api.types.is_bool_dtype(df["converged"]):
        problems.append("converged must be bool")
    if not pd.api.types.is_float_dtype(df["safe_share"]):
        problems.append("safe_share must be float")
    if not pd.api.types.is_integer_dtype(df["n_houses"]):
        problems.append("n_houses must be an integer")
    if df["pt_id"].isna().any():
        problems.append("pt_id has nulls")
    if problems:  # the checks below need the right types
        raise ValueError("labels invalid: " + "; ".join(problems))

    dup = df.duplicated(["pt_id", "interval_start"]).sum()
    if dup:
        problems.append(f"{dup} duplicate (pt_id, interval_start) rows")
    share = df["safe_share"]
    outside = ((share < 0) | (share > 1)).sum()
    if outside:
        problems.append(f"{outside} safe_share values outside [0, 1]")
    unconverged = (~df["converged"]) & share.notna()
    if unconverged.any():
        problems.append(f"{unconverged.sum()} rows have a safe_share but converged is false")
    bad_binding = df["binding"].notna() & ~df["binding"].isin(BINDING)
    if bad_binding.any():
        problems.append(f"{bad_binding.sum()} rows have an unknown binding (allowed: {BINDING})")
    if (df["available_at"] != df["interval_start"] + STEP).any():
        problems.append("available_at must be interval_start + 30 min")
    both = df["load_kw"].notna() & df["pv_kw"].notna()
    if both.any() and not np.allclose(
        df.loc[both, "net_kw"], df.loc[both, "load_kw"] - df.loc[both, "pv_kw"], atol=1e-6
    ):
        problems.append("net_kw must equal load_kw - pv_kw")
    if problems:
        raise ValueError("labels invalid: " + "; ".join(problems))


def is_mock(df: pd.DataFrame) -> bool:
    """True if any row comes from a mock file; evaluation refuses these by default."""
    return bool((df["source_ref"] == MOCK_REF).any())


def labels_path(scenario: str):
    pt_id(scenario)
    return data_dir() / "labels" / scenario


def load(scenario: str) -> pd.DataFrame:
    """Read, validate and sort the labels of one scenario from ``DATA_DIR``."""
    path = labels_path(scenario) / "labels.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found; P3 writes it, or run `python -m src.ml.labels mock`"
        )
    df = pd.read_parquet(path)
    validate(df)
    return df.sort_values(["pt_id", "interval_start"]).reset_index(drop=True)


def load_station_houses(scenario: str) -> pd.DataFrame:
    path = labels_path(scenario) / "station_houses.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    houses = pd.read_parquet(path)
    missing = [c for c in HOUSE_COLUMNS if c not in houses.columns]
    if missing:
        raise ValueError(f"station_houses invalid: missing columns {missing}")
    return houses


def _mock_inputs(profiles: pd.DataFrame | None, rng: np.random.Generator):
    """Station totals per half hour and the house table, from real profiles or a sine."""
    if profiles is not None:
        kwp = profiles.groupby("house_id")["kwp"].first()
        ids = rng.choice(np.sort(kwp[kwp > 0].index.to_numpy()), MOCK_HOUSES, replace=False)
        sub = profiles[profiles["house_id"].isin(ids)].copy()
        sub["load"] = sub["gc_kw"] + sub["cl_kw"].fillna(0)  # no controlled load is not missing
        grouped = sub.groupby("interval_start")
        # a total is only valid when every house reported
        station = pd.DataFrame(
            {
                "load_kw": grouped["load"].sum(min_count=MOCK_HOUSES),
                "pv_kw": grouped["gg_kw"].sum(min_count=MOCK_HOUSES),
            }
        )
        return station, sorted(ids), kwp.loc[sorted(ids)].to_numpy()

    index = pd.date_range(
        "2010-06-30 14:00", "2012-06-30 13:30", freq="30min", tz="UTC", name="interval_start"
    )
    kwp = np.full(MOCK_HOUSES, 2.0)
    sun = np.clip(np.sin(np.radians(solar_elevation(index + pd.Timedelta(minutes=15)))), 0, None)
    day = index.tz_convert(SYDNEY).normalize()
    cloud = pd.Series(rng.uniform(0.3, 1.0, day.nunique()), index=day.unique())
    hour = index.tz_convert(SYDNEY).hour + index.tz_convert(SYDNEY).minute / 60
    total = kwp.sum()
    station = pd.DataFrame(
        {
            "load_kw": total * (0.12 + 0.08 * np.cos(np.radians(15 * (hour - 19)))),
            "pv_kw": total
            * 0.75
            * sun**1.2
            * cloud.loc[day].to_numpy()
            * rng.uniform(0.9, 1.0, len(index)),
        },
        index=index,
    )
    return station, [f"SIM-{i + 1:04d}" for i in range(MOCK_HOUSES)], kwp


def make_mock_with_houses(profiles: pd.DataFrame | None, scenario: str, seed: int = 0):
    """Deterministic fake labels and their ``station_houses`` table.

    Plausible but meaningless: ``clip(0.9 - 0.6 pv/kwp + 0.3 load/kwp + noise, 0.05, 1)``
    on daylight half hours of a station of 30 random houses. Rows where the totals are
    missing get ``converged = False`` and a null share, as a failed power flow would.
    """
    name = pt_id(scenario)
    rng = np.random.default_rng([seed, zlib.crc32(scenario.encode())])
    station, source_ids, kwp = _mock_inputs(profiles, rng)
    kwp_total = float(kwp.sum())

    station = station.sort_index()
    station = station[solar_elevation(station.index + pd.Timedelta(minutes=15)) > 0]
    noise = rng.normal(0, 0.03, len(station))
    raw = 0.9 - 0.6 * station["pv_kw"] / kwp_total + 0.3 * station["load_kw"] / kwp_total + noise
    share = raw.clip(0.05, 1.0).astype("float64")
    converged = share.notna().to_numpy()
    start = station.index.to_series().reset_index(drop=True)
    labels = pd.DataFrame(
        {
            "pt_id": name,
            "interval_start": start,
            "safe_share": share.to_numpy(),
            "converged": converged,
            "binding": np.where(
                converged, np.where(share.to_numpy() < 1.0, "voltage", "none"), None
            ),
            "load_kw": station["load_kw"].to_numpy(),
            "pv_kw": station["pv_kw"].to_numpy(),
            "net_kw": (station["load_kw"] - station["pv_kw"]).to_numpy(),
            "kwp_total": kwp_total,
            "n_houses": MOCK_HOUSES,
            "available_at": start + STEP,
            "provenance": "simulated",
            "source_ref": MOCK_REF,
        }
    )
    labels["binding"] = labels["binding"].astype("object")
    houses = pd.DataFrame(
        {
            "pt_id": name,
            "house_id": [f"H{i + 1:02d}" for i in range(MOCK_HOUSES)],
            "source_house_id": source_ids,
            "kwp": kwp,
            "load_scale": 1.0,
            "pv_scale": 1.0,
        }
    )
    return labels, houses


def make_mock(profiles: pd.DataFrame | None, scenario: str, seed: int = 0) -> pd.DataFrame:
    return make_mock_with_houses(profiles, scenario, seed)[0]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.ml.labels")
    sub = parser.add_subparsers(dest="command", required=True)
    mock = sub.add_parser("mock", help="write mock labels with the real schema")
    mock.add_argument("--scenario", default="A", choices=SCENARIOS)
    mock.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    profiles_path = data_dir() / "profiles.parquet"
    profiles = pd.read_parquet(profiles_path) if profiles_path.exists() else None
    labels, houses = make_mock_with_houses(profiles, args.scenario, args.seed)
    validate(labels)
    out = labels_path(args.scenario)
    out.mkdir(parents=True, exist_ok=True)
    labels.to_parquet(out / "labels.parquet", index=False)
    houses.to_parquet(out / "station_houses.parquet", index=False)
    source = (
        "profiles.parquet" if profiles is not None else "a synthetic sine (no profiles.parquet)"
    )
    print(f"wrote {len(labels)} MOCK labels from {source} to {out} (source_ref = {MOCK_REF})")


if __name__ == "__main__":
    main()
