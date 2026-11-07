"""``predict(features) -> forecast``: the trained model as a contract object.

Called by the agent (``ModelSource``) inside the API container; no external model API.
Models are loaded once per process and cached by ``(model_version, pt_id)``. The model
version comes from ``MODEL_VERSION`` (default ``safe-cap-qgb-v1``).
"""

import logging
import os

import pandas as pd

from src.common.contract import Forecast
from src.ml import features as feature_set
from src.ml import model_io

logger = logging.getLogger(__name__)
DEFAULT_MODEL_VERSION = "safe-cap-qgb-v1"
SAFE_CAP_HORIZON_MIN = 60
_cache: dict[str, tuple[dict, dict]] = {}


def model_version() -> str:
    return os.environ.get("MODEL_VERSION", DEFAULT_MODEL_VERSION)


def clear_cache() -> None:
    _cache.clear()


def _load(version: str, pt_id: str):
    key = str(model_io.model_dir(version, pt_id))
    if key not in _cache:
        models, meta = model_io.load(version, pt_id)
        if meta["features"] != feature_set.FEATURES:
            raise ValueError(
                f"model {version}/{pt_id} was trained on other features than the code now builds; "
                "retrain it"
            )
        _cache[key] = (models, meta)
    return _cache[key]


def _timestamp(features: dict, key: str) -> pd.Timestamp:
    if features.get(key) is None:
        raise ValueError(f"features must include {key}")
    stamp = pd.Timestamp(features[key])
    if stamp.tzinfo is None:
        raise ValueError(f"{key} must be timezone-aware")
    return stamp.tz_convert("UTC")


def _pv_load(features: dict) -> dict:
    """PV and load bands from the second model if it exists; the safe cap never needs it."""
    from src.ml import forecast_pv_load

    try:
        return forecast_pv_load.predict_pv_load(features, SAFE_CAP_HORIZON_MIN)
    except FileNotFoundError:
        return {}
    except ValueError as exc:  # a stale second model must not break the safe cap
        logger.warning("no PV and load forecast: %s", exc)
        return {}


def predict(features: dict, horizon_min: int = SAFE_CAP_HORIZON_MIN) -> Forecast:
    """Quantiles of the safe export share for one station and interval.

    ``features`` is the dict from ``ml.features.build``. Missing feature values become
    NaN (never 0); the model handles them. ``available_at`` is the decision time.
    """
    from src.ml.train import QUANTILES, predict_quantiles

    if horizon_min != SAFE_CAP_HORIZON_MIN:
        raise ValueError(f"only horizon_min={SAFE_CAP_HORIZON_MIN} is supported for the safe cap")
    pt_id = features.get("pt_id")
    if not pt_id:
        raise ValueError("features must include pt_id")
    target_start = _timestamp(features, "target_start")
    decision_time = _timestamp(features, "decision_time")

    models, meta = _load(model_version(), pt_id)
    pv_load = _pv_load(features)
    row = [features.get(name) for name in feature_set.FEATURES]  # always in FEATURES order
    X = pd.DataFrame([row], columns=feature_set.FEATURES, dtype=float)  # None becomes NaN
    q = predict_quantiles(models, X)[0]
    shares = {f"q{round(p * 100):02d}": float(v) for p, v in zip(QUANTILES, q, strict=True)}
    return Forecast(
        pt_id=pt_id,
        interval_start=target_start.to_pydatetime(),
        horizon_min=horizon_min,
        safe_cap_share=shares,
        spread=float(shares["q90"] - shares["q05"]),
        pv_kw=pv_load.get("pv_kw"),
        load_kw=pv_load.get("load_kw"),
        available_at=decision_time.to_pydatetime(),
        model_version=meta["model_version"],
        provenance="forecast",
        source_ref=f"ml/train.py@{meta['git_sha']}",
    )


__all__ = ["predict", "clear_cache", "model_version"]
