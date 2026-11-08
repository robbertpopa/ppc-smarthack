"""Solar elevation from time alone (NOAA approximation, no extra dependency).

Used as a clear-sky proxy: it is known in advance for any future time, so it never
leaks anything from the future. Accuracy is within about half a degree, which is
enough for a daylight mask and a model feature.
"""

import numpy as np
import pandas as pd

SYDNEY_LAT = -33.87
SYDNEY_LON = 151.21


def solar_elevation(ts, lat: float = SYDNEY_LAT, lon: float = SYDNEY_LON):
    """Elevation of the sun above the horizon in degrees (no refraction).

    ``ts`` is a timestamp or a list-like of timestamps and must carry a time zone.
    A scalar gives a float, anything else a numpy array.
    """
    scalar = np.ndim(ts) == 0
    idx = pd.DatetimeIndex([ts] if scalar else ts)
    if idx.tz is None:
        raise ValueError("solar_elevation needs timezone-aware timestamps")
    idx = idx.tz_convert("UTC")

    day = idx.day_of_year.to_numpy()
    hour = idx.hour.to_numpy() + idx.minute.to_numpy() / 60 + idx.second.to_numpy() / 3600
    gamma = 2 * np.pi / 365 * (day - 1 + (hour - 12) / 24)
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * np.cos(gamma)
        - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2 * gamma)
        - 0.040849 * np.sin(2 * gamma)
    )
    decl = (
        0.006918
        - 0.399912 * np.cos(gamma)
        + 0.070257 * np.sin(gamma)
        - 0.006758 * np.cos(2 * gamma)
        + 0.000907 * np.sin(2 * gamma)
        - 0.002697 * np.cos(3 * gamma)
        + 0.00148 * np.sin(3 * gamma)
    )
    solar_minutes = hour * 60 + eqtime + 4 * lon
    hour_angle = np.radians(solar_minutes / 4 - 180)
    lat_r = np.radians(lat)
    cos_zenith = np.sin(lat_r) * np.sin(decl) + np.cos(lat_r) * np.cos(decl) * np.cos(hour_angle)
    elevation = 90 - np.degrees(np.arccos(np.clip(cos_zenith, -1, 1)))
    return float(elevation[0]) if scalar else elevation


def clearsky_ghi(ts, lat: float = SYDNEY_LAT, lon: float = SYDNEY_LON):
    """Clear-sky sunlight on a horizontal surface in W/m^2 (Haurwitz model), 0 at night.

    ``1098 * cos z * exp(-0.057 / cos z)`` with ``cos z = sin(elevation)``. Like
    ``solar_elevation`` it depends on time alone, so it never leaks the future. It is the
    sky's ceiling: measured sunlight divided by it gives how clear the sky is.
    """
    elevation = solar_elevation(ts, lat, lon)
    cos_z = np.sin(np.radians(np.asarray(elevation, dtype=float)))
    up = cos_z > 0
    safe = np.where(up, cos_z, 1.0)
    ghi = np.where(up, 1098.0 * safe * np.exp(-0.057 / safe), 0.0)
    return float(ghi) if np.ndim(ts) == 0 else ghi
