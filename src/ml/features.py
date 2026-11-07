"""Features for the safe-cap model, built only from what is known at decision time.

The model decides at time ``t`` the limit for the interval starting at
``T = t + horizon`` (60 min by default). A value may be used only if its
``available_at <= t``. Measurements and labels of an interval are available at its
end, so the newest usable interval is the one that *ends* at ``t`` (it starts at
``t - 30 min``). All power values are divided by ``kwp_total`` so the model does not
depend on the size of one station.

| Feature                | Definition                                 | Reason                |
|------------------------|--------------------------------------------|-----------------------|
| net_now                | net_kw of the interval ending at t         | current state         |
| net_lag_1, _2, _3      | net_kw 30, 60, 90 min before that          | trend (clouds, load)  |
| net_same_T_yesterday   | net_kw at T - 24 h                         | daily pattern         |
| share_last             | safe_share of the interval ending at t     | persistence           |
| share_same_T_yesterday | safe_share at T - 24 h                     | daily pattern         |
| sun_elev_T             | solar elevation at the middle of T         | clear-sky proxy       |
| sun_elev_now           | solar elevation at the middle of last one  | with net_now: clouds  |
| hour_sin, hour_cos     | hour of T, Sydney local time               | daily cycle           |
| doy_sin, doy_cos       | day of year of T, Sydney local time        | season (south)        |
| is_weekend             | T is Saturday or Sunday, Sydney local time | load pattern          |

Only net values are used, never generation and consumption separately: in a real
deployment the meter shows the net value. A missing input interval gives NaN in the
features that need it (never 0) and does not shift other rows.
"""

import numpy as np
import pandas as pd

from src.ml.config import SYDNEY
from src.ml.sun import solar_elevation

STEP = pd.Timedelta(minutes=30)
DAY = pd.Timedelta(hours=24)
HORIZON_MIN = 60

FEATURES: list[str] = [
    "net_now",
    "net_lag_1",
    "net_lag_2",
    "net_lag_3",
    "net_same_T_yesterday",
    "share_last",
    "share_same_T_yesterday",
    "sun_elev_T",
    "sun_elev_now",
    "hour_sin",
    "hour_cos",
    "doy_sin",
    "doy_cos",
    "is_weekend",
]
KEYS = ["pt_id", "decision_time", "target_start"]


def _series(labels: pd.DataFrame):
    """Normalised net load and safe share indexed by interval start."""
    start = pd.DatetimeIndex(labels["interval_start"])
    net = pd.Series((labels["net_kw"] / labels["kwp_total"]).to_numpy(), index=start)
    share = pd.Series(labels["safe_share"].to_numpy(), index=start)
    return net, share


def _compute(labels: pd.DataFrame, target_start: pd.DatetimeIndex, horizon_min: int):
    """Features for every target start, from the rows of ``labels`` only."""
    net, share = _series(labels)
    horizon = pd.Timedelta(minutes=horizon_min)
    decision = target_start - horizon
    last = decision - STEP  # start of the interval that ends at the decision time

    def at(series, when):
        return series.reindex(when).to_numpy()

    local = target_start.tz_convert(SYDNEY)
    hour = local.hour + local.minute / 60
    doy = local.day_of_year
    out = pd.DataFrame(
        {
            "net_now": at(net, last),
            "net_lag_1": at(net, last - STEP),
            "net_lag_2": at(net, last - 2 * STEP),
            "net_lag_3": at(net, last - 3 * STEP),
            "net_same_T_yesterday": at(net, target_start - DAY),
            "share_last": at(share, last),
            "share_same_T_yesterday": at(share, target_start - DAY),
            "sun_elev_T": solar_elevation(target_start + STEP / 2),
            "sun_elev_now": solar_elevation(last + STEP / 2),
            "hour_sin": np.sin(2 * np.pi * hour / 24),
            "hour_cos": np.cos(2 * np.pi * hour / 24),
            "doy_sin": np.sin(2 * np.pi * doy / 365.25),
            "doy_cos": np.cos(2 * np.pi * doy / 365.25),
            "is_weekend": (local.day_of_week >= 5).astype(float),
        }
    )
    out.insert(0, "target_start", target_start)
    out.insert(0, "decision_time", decision)
    return out


def _one_station(labels: pd.DataFrame, horizon_min: int) -> pd.DataFrame:
    labels = labels.sort_values("interval_start")
    grid = pd.date_range(
        labels["interval_start"].min(), labels["interval_start"].max(), freq=STEP, tz="UTC"
    )
    frame = _compute(labels, grid, horizon_min)
    frame.insert(0, "pt_id", labels["pt_id"].iloc[0])
    target = pd.Series(
        labels["safe_share"].to_numpy(), index=pd.DatetimeIndex(labels["interval_start"])
    )
    frame["safe_share"] = target.reindex(grid).to_numpy()
    return frame


def build_frame(labels: pd.DataFrame, horizon_min: int = HORIZON_MIN) -> pd.DataFrame:
    """One row per target interval on a complete half-hour grid, for training.

    Columns: ``pt_id``, ``decision_time``, ``target_start``, ``FEATURES`` and the target
    ``safe_share`` at ``target_start`` (NaN where unknown). Gaps in ``labels`` stay NaN:
    the index is reindexed first, so nothing closes the gap.
    """
    frames = [_one_station(g, horizon_min) for _, g in labels.groupby("pt_id", sort=True)]
    return pd.concat(frames, ignore_index=True)


def build(station_state: pd.DataFrame, t: pd.Timestamp, horizon_min: int = HORIZON_MIN) -> dict:
    """Features for one decision at time ``t``; the single-point version of ``build_frame``.

    ``station_state`` holds the history of one station (the label columns). Rows whose
    ``available_at`` is after ``t`` are dropped first, so the future cannot leak in.
    """
    if t.tzinfo is None:
        raise ValueError("decision time t must be timezone-aware")
    t = t.tz_convert("UTC")
    known = station_state[station_state["available_at"] <= t]
    known = known[known["interval_start"] > t - pd.Timedelta(hours=26 + horizon_min / 60)]
    stations = station_state["pt_id"].unique()
    if len(stations) != 1:
        raise ValueError(f"station_state must hold exactly one station, got {list(stations)}")
    target_start = pd.DatetimeIndex([t + pd.Timedelta(minutes=horizon_min)])
    row = _compute(known, target_start, horizon_min).iloc[0]
    out = {
        "pt_id": stations[0],
        "decision_time": row["decision_time"],
        "target_start": row["target_start"],
    }
    out.update({name: float(row[name]) for name in FEATURES})
    return out
