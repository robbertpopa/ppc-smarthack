"""S1: one Ausgrid reader for both sides.

``src/grid/ausgrid.py`` reads the raw CSV again and skips every cleaning rule of
``src/ml/ausgrid.py`` (generation above 1.2 x kWp, the fall-back hour, ``Row Quality``).
So the labels' power flows and the ML export numbers see different readings.
``src.grid`` cannot be imported without pandapower, so ``grid_style_day`` mirrors
``src/grid/ausgrid.py:6-14,42-53`` line by line. ``day_from_profiles`` is the fix: the same
``(48, n_houses)`` arrays, read from the cleaned ``profiles.parquet``.
"""

import numpy as np
import pandas as pd

SYD = "Australia/Sydney"


def read_raw(path) -> pd.DataFrame:
    """As ``src/grid/ausgrid.py:7-9``."""
    frame = pd.read_csv(path, skiprows=1, low_memory=False)
    frame["date"] = pd.to_datetime(frame["date"], dayfirst=True)
    return frame


def grid_style_day(raw: pd.DataFrame, date, customers: list[int]):
    """``day_profiles`` of the grid code: kW arrays of shape (48, n), load = GC + CL."""
    day = raw[raw["date"] == pd.Timestamp(date)].set_index(["Customer", "Consumption Category"])
    hours = list(raw.columns[5:53])
    load = day.xs("GC", level=1).loc[customers, hours].astype(float)
    pv = day.xs("GG", level=1).loc[customers, hours].astype(float)
    if "CL" in day.index.get_level_values(1):
        rows = day.xs("CL", level=1)
        controlled = rows.reindex(customers)[hours].astype(float).fillna(0.0)
        load = load + controlled
    return 2 * load.to_numpy().T, 2 * pv.to_numpy().T


def day_from_profiles(profiles: pd.DataFrame, date, customers: list[int]):
    """The same arrays from ``profiles.parquet``; cleaned readings stay NaN (never 0)."""
    ids = [f"AG-{c:04d}" for c in customers]
    p = profiles[profiles["house_id"].isin(ids)].copy()
    local = p["interval_start"].dt.tz_convert(SYD)
    p = p[local.dt.tz_localize(None).dt.normalize() == pd.Timestamp(date)]
    p["load"] = p["gc_kw"] + p["cl_kw"].fillna(0)
    load = p.pivot(index="interval_start", columns="house_id", values="load")[ids]
    pv = p.pivot(index="interval_start", columns="house_id", values="gg_kw")[ids]
    if len(load) != 48:
        raise ValueError(f"{date}: {len(load)} intervals (a daylight-saving day), not 48")
    return load.to_numpy(), pv.to_numpy()


def differences(a: np.ndarray, b: np.ndarray, tol: float = 1e-9) -> int:
    """Cells that differ, a NaN on one side counting as a difference."""
    both_nan = np.isnan(a) & np.isnan(b)
    return int((~both_nan & ~np.isclose(a, b, atol=tol, equal_nan=False)).sum())
