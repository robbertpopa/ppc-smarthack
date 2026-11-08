"""Imbalance savings of the PV/load forecast against "same time yesterday".

The quantity is the station's net export, ``max(0, pv - load)``, before any export limit. The
model forecast is the repository's PV/load model at a 60-minute horizon: PPC corrects its
position on the intraday market about an hour ahead (an assumption). Without a trained
PV/load model the result is None and the caller says so.
"""

import pandas as pd

from src.ml import forecast_pv_load
from src.pricing import imbalance

HORIZON_MIN = 60
DAY = pd.Timedelta(hours=24)


def actual_export_kw(labels: pd.DataFrame) -> pd.Series:
    """Net export of the station per interval, from the label table."""
    index = pd.DatetimeIndex(labels["interval_start"])
    net = pd.Series(labels["pv_kw"].to_numpy() - labels["load_kw"].to_numpy(), index=index)
    return net.clip(lower=0.0)


def baseline_export_kw(actual: pd.Series) -> pd.Series:
    """The same interval one day earlier."""
    return actual.reindex(actual.index - DAY).set_axis(actual.index)


def model_export_kw(X: pd.DataFrame, pt_id: str, index: pd.DatetimeIndex) -> pd.Series:
    """The PV/load model's median net export for each row of features ``X``."""
    values = []
    for record in X.to_dict("records"):
        out = forecast_pv_load.predict_pv_load({**record, "pt_id": pt_id}, HORIZON_MIN)
        load = out["load_kw"].p50 if out["load_kw"] is not None else 0.0
        values.append(max(0.0, out["pv_kw"].p50 - load))
    return pd.Series(values, index=index)


def station_savings(ctx: dict, result: dict) -> dict | None:
    """Savings of the model forecast for each spread scenario, or None without models."""
    scored = result["scored"]
    labels = ctx["labels"]
    pt_id = labels["pt_id"].iloc[0]
    index = pd.DatetimeIndex(scored["rows"]["target_start"])
    try:
        model = model_export_kw(scored["X"], pt_id, index)
    except FileNotFoundError:
        return None
    actual = actual_export_kw(labels)
    baseline = baseline_export_kw(actual)
    return {
        "horizon_min": HORIZON_MIN,
        "baseline": "same time yesterday",
        "by_spread": [
            imbalance.saving(actual, baseline, model, spread)
            for spread in imbalance.SPREADS_EUR_MWH
        ],
    }
