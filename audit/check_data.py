"""Audit check: quality of profiles.parquet and weather_hourly.parquet (read only).

    .venv/bin/python audit/check_data.py

Reads only dates, counts and summary statistics. It never reads the sealed 2012-13 Ausgrid
file; it only reports whether any row of the working data falls in the test year.
"""

import numpy as np
import pandas as pd

from src.ml.config import data_dir
from src.ml.split import TEST_START
from src.ml.sun import solar_elevation

SYD = "Australia/Sydney"
TEST_UTC = pd.Timestamp(TEST_START).tz_localize(SYD).tz_convert("UTC")


def profiles():
    p = pd.read_parquet(data_dir() / "profiles.parquet")
    print("== profiles.parquet")
    print("rows", len(p), "houses", p["house_id"].nunique())
    print("range UTC", p["interval_start"].min(), "->", p["interval_start"].max())
    print("rows in test year (must be 0):", int((p["interval_start"] >= TEST_UTC).sum()))
    print("duplicate (house, interval):", int(p.duplicated(["house_id", "interval_start"]).sum()))

    kwp = p.groupby("house_id")["kwp"].agg(["min", "max"])
    print("houses whose kwp changes inside the data:", int((kwp["min"] != kwp["max"]).sum()))
    print("houses with kwp == 0:", int((kwp["max"] == 0).sum()))

    elev = solar_elevation(p["interval_start"] + pd.Timedelta(minutes=15))
    night = elev < -6
    gg = p["gg_kw"]
    print("negative gg / gc:", int((gg < 0).sum()), int((p["gc_kw"] < 0).sum()))
    print(
        "gg > 0.05 kW while sun < -6 deg (night generation):",
        int((night & (gg > 0.05)).sum()),
        "houses:",
        p.loc[night & (gg > 0.05), "house_id"].nunique(),
    )
    ratio = gg / p["kwp"].replace(0, np.nan)
    print(
        "gg/kwp quantiles in daylight:",
        ratio[elev > 0].quantile([0.5, 0.99, 0.999]).round(3).to_dict(),
    )
    print("gg in (1.0, 1.2] x kwp kept as valid:", int(((ratio > 1.0) & (ratio <= 1.2)).sum()))

    # stuck generation meter: same non-zero value for >= 6 consecutive daylight intervals
    day = p.loc[elev > 10, ["house_id", "interval_start", "gg_kw"]].sort_values(
        ["house_id", "interval_start"]
    )
    same = (
        (day["gg_kw"].diff() == 0)
        & (day["house_id"] == day["house_id"].shift())
        & (day["gg_kw"] > 0)
    )
    run_id = (~same).cumsum()
    runs = same.groupby(run_id).sum()
    print("stuck runs (>= 5 repeats, gg > 0, sun > 10 deg):", int((runs >= 5).sum()))

    # dead PV: a house-day with zero generation while the sun is high
    p["date"] = p["interval_start"].dt.tz_convert(SYD).dt.date
    noon = p[elev > 30]
    dead = noon.groupby(["house_id", "date"])["gg_kw"].max()
    print(
        "house-days with gg == 0 all day though sun > 30 deg:",
        int((dead == 0).sum()),
        "houses:",
        dead[dead == 0].reset_index()["house_id"].nunique(),
    )

    # where is the centre of PV in local time? should be close to solar noon (~12:00 / 13:00 DST)
    local = p["interval_start"].dt.tz_convert(SYD)
    hours = local.dt.hour + local.dt.minute / 60 + 0.25
    w = gg.fillna(0)
    month = local.dt.month
    centre = (hours * w).groupby(month).sum() / w.groupby(month).sum()
    print("PV centre of mass by month (local, mid-interval):", centre.round(2).to_dict())


def weather():
    path = data_dir() / "weather_hourly.parquet"
    w = pd.read_parquet(
        path, columns=["time_utc", "postcode", "ALLSKY_SFC_SW_DWN", "CLRSKY_SFC_SW_DWN", "SZA"]
    )
    print("== weather_hourly.parquet")
    t = pd.to_datetime(w["time_utc"], utc=True)
    print("rows", len(w), "postcodes", w["postcode"].nunique(), "range", t.min(), "->", t.max())
    print("rows on/after the test start:", int((t >= TEST_UTC).sum()))
    print("duplicate (postcode, time):", int(w.duplicated(["postcode", "time_utc"]).sum()))
    print("fill values (-999):", int((w["ALLSKY_SFC_SW_DWN"] <= -900).sum()))

    # postcode 2008 is central Sydney, where src.ml.sun computes the sun position
    one = w[w["postcode"] == "2008"].copy()
    one["t"] = pd.to_datetime(one["time_utc"], utc=True)
    one = one[(one["t"] >= "2011-01-01") & (one["t"] < "2011-03-01")]
    day = one["SZA"].to_numpy() < 80
    for shift in (-60, -30, 0, 15, 30, 45, 60):
        elev = solar_elevation(one["t"] + pd.Timedelta(minutes=shift))
        err = np.abs(elev[day] - (90 - one["SZA"].to_numpy()[day])).mean()
        print(f"  daytime |our elevation(t{shift:+d} min) - (90 - SZA)| mean = {err:.2f} deg")


if __name__ == "__main__":
    profiles()
    weather()
