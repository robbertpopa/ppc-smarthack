"""S3: the station's place and time zone as data, not as constants in the code.

Sydney is fixed in ``src/ml/sun.py:11-12`` (coordinates), ``src/ml/config.py:12`` (time
zone used by features, split and metrics) and as a literal in four more files. A station
in Romania would get the sun of Sydney. ``time_features`` is the drop-in for the time and
sun columns of ``src/ml/features._compute`` with the station's own ``StationGeo``.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.ml.sun import solar_elevation

STEP = pd.Timedelta(minutes=30)


@dataclass(frozen=True)
class StationGeo:
    lat: float
    lon: float
    tz: str


SYDNEY = StationGeo(-33.87, 151.21, "Australia/Sydney")


def from_postcodes(source_house_ids, postcode_of: dict, geo: pd.DataFrame, tz: str) -> StationGeo:
    """Centroid of the houses' postcodes (``data/reference/ausgrid_postcodes_geo.csv``)."""
    by_pc = geo.drop_duplicates("Postcode").set_index("Postcode")
    codes = [int(postcode_of[h]) for h in source_house_ids]
    return StationGeo(
        float(by_pc.loc[codes, "lat"].mean()), float(by_pc.loc[codes, "lon"].mean()), tz
    )


def time_features(
    target_start: pd.DatetimeIndex, horizon_min: int, geo: StationGeo
) -> pd.DataFrame:
    last = target_start - pd.Timedelta(minutes=horizon_min) - STEP
    local = target_start.tz_convert(geo.tz)
    hour = local.hour + local.minute / 60
    doy = local.day_of_year
    return pd.DataFrame(
        {
            "sun_elev_T": solar_elevation(target_start + STEP / 2, lat=geo.lat, lon=geo.lon),
            "sun_elev_now": solar_elevation(last + STEP / 2, lat=geo.lat, lon=geo.lon),
            "hour_sin": np.sin(2 * np.pi * hour / 24),
            "hour_cos": np.cos(2 * np.pi * hour / 24),
            "doy_sin": np.sin(2 * np.pi * doy / 365.25),
            "doy_cos": np.cos(2 * np.pi * doy / 365.25),
            "is_weekend": (local.day_of_week >= 5).astype(float),
        }
    )


def sunrise_utc(day: str, geo: StationGeo) -> pd.Timestamp:
    """First minute of the local day with the sun above the horizon."""
    start = pd.Timestamp(day).tz_localize(geo.tz).tz_convert("UTC")
    minutes = pd.date_range(start, periods=24 * 60, freq="1min")
    up = solar_elevation(minutes, lat=geo.lat, lon=geo.lon) > 0
    return minutes[int(np.argmax(up))]
