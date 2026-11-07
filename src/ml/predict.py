"""``predict(features) -> forecast``: the trained model as a contract object.

Called by the agent (``ModelSource``) inside the API container; no external model API.
Models are loaded once per training and station (the cache notices a model retrained into
the same folder). The model version comes from ``MODEL_VERSION`` (default
``safe-cap-qgb-v1``).
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


def model_version() -> str:
    return os.environ.get("MODEL_VERSION", DEFAULT_MODEL_VERSION)


def clear_cache() -> None:
    """Forget every loaded model (this module's, the PV and load models, the explanations)."""
    model_io.clear_caches()


def _load(version: str, pt_id: str):
    def loader(folder):
        models, meta = model_io.load_dir(folder)
        if meta["features"] != feature_set.FEATURES:
            raise ValueError(
                f"model {version}/{pt_id} was trained on other features than the code now builds; "
                "retrain it"
            )
        return models, meta

    return model_io.cached("safe-cap", model_io.model_dir(version, pt_id), loader)


def _timestamp(features: dict, key: str) -> pd.Timestamp:
    if features.get(key) is None:
        raise ValueError(f"features must include {key}")
    stamp = pd.Timestamp(features[key])
    if stamp.tzinfo is None:
        raise ValueError(f"{key} must be timezone-aware")
    return stamp.tz_convert("UTC")


def _pv_load(features: dict) -> dict:
    """PV and load bands from the second model if it exists; the safe cap never needs it.

    No second model yet is normal and silent. Any other problem with it (an older folder,
    a missing file) is logged and must not stop the safe-cap forecast.
    """
    from src.ml import forecast_pv_load

    try:
        return forecast_pv_load.predict_pv_load(features, SAFE_CAP_HORIZON_MIN)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("no PV and load forecast: %r", exc)
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
    ahead = target_start - decision_time
    if ahead != pd.Timedelta(minutes=horizon_min):
        raise ValueError(
            f"the features look {ahead} ahead but horizon_min={horizon_min}: "
            "build them for the same horizon"
        )

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
