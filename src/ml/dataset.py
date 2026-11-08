"""Prepared train / test / demo datasets: all 300 houses, Ausgrid plus hourly weather.

Split by Sydney local date, never shuffled, chronological:
train 2010-07-01 to 2013-02-28 (32 months), test 2013-03-01 to 2013-04-30,
demo 2013-05-01 to 2013-06-30. Run: ``python -m src.ml.dataset``.
"""

import json
from pathlib import Path

import pandas as pd

from src.ml import ausgrid
from src.ml.data import raw_dir
from src.ml.split import local_date

TRAIN_START = pd.Timestamp("2010-07-01")
TEST_START = pd.Timestamp("2013-03-01")
DEMO_START = pd.Timestamp("2013-05-01")
DEMO_END = pd.Timestamp("2013-06-30")
WEATHER_COLUMNS = [
    "ALLSKY_SFC_SW_DWN",
    "ALLSKY_SFC_SW_DIFF",
    "ALLSKY_SFC_SW_DNI",
    "CLRSKY_SFC_SW_DWN",
    "ALLSKY_KT",
    "CLOUD_AMT",
    "SZA",
    "T2M",
    "RH2M",
    "WS10M",
    "WD10M",
    "PS",
    "PRECTOTCORR",
]


def out_dir() -> Path:
    return raw_dir().parent / "prepared" / "dataset"


def load_weather(folder: Path) -> pd.DataFrame:
    frames = [
        pd.read_csv(p, parse_dates=["time_utc"])
        for p in sorted(folder.glob("weather_hourly_*.csv"))
    ]
    w = pd.concat(frames, ignore_index=True)
    w["postcode"] = w["postcode"].astype(str)
    w[WEATHER_COLUMNS] = w[WEATHER_COLUMNS].astype("float32")
    w["hour"] = w.pop("time_utc").dt.tz_localize("UTC")
    return w.drop_duplicates(["postcode", "hour"])


def split_by_date(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    date = local_date(df["interval_start"])
    return {
        "train": df[(date >= TRAIN_START) & (date < TEST_START)],
        "test": df[(date >= TEST_START) & (date < DEMO_START)],
        "demo": df[(date >= DEMO_START) & (date <= DEMO_END)],
    }


def build() -> dict:
    profiles = ausgrid.build_profiles(raw_dir() / "ausgrid_full", include_held_out=True)
    weather = load_weather(raw_dir() / "weather")
    profiles["hour"] = profiles["interval_start"].dt.floor("h")
    table = profiles.merge(weather, on=["postcode", "hour"], how="left").drop(columns="hour")
    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "houses": int(table["house_id"].nunique()),
        "postcodes": int(table["postcode"].nunique()),
    }
    for name, part in split_by_date(table).items():
        part.to_parquet(out / f"{name}.parquet", index=False)
        manifest[name] = {
            "rows": len(part),
            "first": str(part["interval_start"].min()),
            "last": str(part["interval_start"].max()),
            "weather_missing": int(part["T2M"].isna().sum()),
        }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
