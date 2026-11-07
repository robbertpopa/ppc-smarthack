"""Explain a prediction with numbers only: top factors and similar past cases.

The agent turns these numbers into text with templates (and rejects any text with a number
that is not in the figures). Explanations describe **the model, not the physics**.

* Global: permutation importance of the ``q05`` model on the validation period, scored by
  pinball loss at 0.05, fixed seed, 10 repeats (``importance.csv`` next to the model).
  The lag features are correlated, so permutation importance splits credit between
  ``net_now`` and ``net_lag_*``; read them as a group.
* Local: for each present feature, replace it by its validation median for the same
  half hour of the day and recompute ``q05``; ``effect = q05(actual) - q05(reference)``.
  The three largest effects are returned. Missing features are listed, not ablated.
* Similar cases: the five nearest decisions from training and validation whose outcome was
  already known at the decision time (standardised features, Euclidean distance over the
  dimensions both have), with the realised ``safe_share``. The ``q05`` the model gave is
  shown for validation cases only: for training cases it would be an in-sample prediction,
  so ``q05`` is ``None`` and ``in_sample`` is true.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.ml import features as feature_set
from src.ml import model_io
from src.ml.config import SYDNEY

LABELS: dict[str, str] = {
    "net_now": "net load now (share of installed kWp)",
    "net_lag_1": "net load 30 min earlier (share of kWp)",
    "net_lag_2": "net load 60 min earlier (share of kWp)",
    "net_lag_3": "net load 90 min earlier (share of kWp)",
    "net_same_T_yesterday": "net load at the same time yesterday (share of kWp)",
    "share_last": "last known safe export share",
    "share_same_T_yesterday": "safe export share at the same time yesterday",
    "sun_elev_T": "sun height at the target time (degrees)",
    "sun_elev_now": "sun height now (degrees)",
    "hour_sin": "time of day (sine)",
    "hour_cos": "time of day (cosine)",
    "doy_sin": "season (sine)",
    "doy_cos": "season (cosine)",
    "is_weekend": "weekend",
}
TOP_FACTORS = 3
SIMILAR = 5
MIN_SHARED_DIMS = 3
REPEATS = 10
STEP = pd.Timedelta(minutes=30)


def _slot(target_start) -> pd.Series:
    local = pd.DatetimeIndex(target_start).tz_convert(SYDNEY)
    return pd.Series(local.hour * 2 + local.minute // 30)


def global_importance_of(model, X_val: pd.DataFrame, y_val, seed: int = 0) -> pd.DataFrame:
    """Permutation importance of one quantile model (loss increase, higher is more)."""
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import mean_pinball_loss

    def score(estimator, X, y):
        return -mean_pinball_loss(y, estimator.predict(X), alpha=0.05)

    result = permutation_importance(
        model, X_val, y_val, scoring=score, n_repeats=REPEATS, random_state=seed, n_jobs=1
    )
    table = pd.DataFrame(
        {
            "feature": list(X_val.columns),
            "importance": result.importances_mean,
            "std": result.importances_std,
        }
    )
    return table.sort_values(["importance", "feature"], ascending=[False, True]).reset_index(
        drop=True
    )


def build_artifacts(models: dict, train_rows: pd.DataFrame, val_rows: pd.DataFrame, seed: int = 0):
    """Everything ``explain`` needs besides the models; written next to them by ``save``."""
    from src.ml.train import predict_quantiles

    names = feature_set.FEATURES
    importance = global_importance_of(models[0.05], val_rows[names], val_rows["safe_share"], seed)
    slots = _slot(val_rows["target_start"]).to_numpy()
    reference = {
        int(slot): {f: _num(val_rows.loc[slots == slot, f].median()) for f in names}
        for slot in np.unique(slots)
    }
    overall = {f: _num(val_rows[f].median()) for f in names}
    past = pd.concat([train_rows, val_rows], ignore_index=True)
    index = past[[*names, "target_start", "safe_share"]].copy()
    index["q05"] = predict_quantiles(models, past[names])[:, 0]
    # The models were fitted on the training rows, so their q05 there is an in-sample
    # prediction, tighter than on new decisions. It is only shown for validation cases.
    index["in_sample"] = [True] * len(train_rows) + [False] * len(val_rows)
    return {"importance": importance, "reference": reference, "overall": overall, "index": index}


def _num(value):
    return None if pd.isna(value) else float(value)


def save_artifacts(art: dict, out) -> None:
    out = Path(out)
    art["importance"].to_csv(out / "importance.csv", index=False, float_format="%.8f")
    (out / "explain_reference.json").write_text(
        json.dumps({"reference": art["reference"], "overall": art["overall"]}, sort_keys=True)
    )
    art["index"].to_parquet(out / "explain_index.parquet", index=False)


def load_artifacts(out) -> dict:
    out = Path(out)
    if not (out / "explain_index.parquet").exists():
        raise FileNotFoundError(
            f"no explanation data in {out}: retrain with `python -m src.ml.train`"
        )
    ref = json.loads((out / "explain_reference.json").read_text())
    return {
        "importance": pd.read_csv(out / "importance.csv"),
        "reference": {int(k): v for k, v in ref["reference"].items()},
        "overall": ref["overall"],
        "index": pd.read_parquet(out / "explain_index.parquet"),
    }


def global_importance(pt_id: str, version: str | None = None) -> pd.DataFrame:
    """The saved permutation importance of a station's ``q05`` model."""
    from src.ml.predict import model_version

    path = model_io.model_dir(version or model_version(), pt_id) / "importance.csv"
    if not path.exists():
        raise FileNotFoundError(f"no importance table at {path}")
    return pd.read_csv(path)


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and np.isnan(value))


def explain_with(models: dict, art: dict, feats: dict) -> dict:
    """Top factors and similar cases for one decision (pure: no disk, no clock)."""
    names = feature_set.FEATURES
    target = pd.Timestamp(feats["target_start"]).tz_convert("UTC")
    decision = pd.Timestamp(feats["decision_time"]).tz_convert("UTC")
    values = {f: (None if _is_missing(feats.get(f)) else float(feats[f])) for f in names}
    present = [f for f in names if values[f] is not None]
    missing = [f for f in names if values[f] is None]

    row = pd.DataFrame([[np.nan if values[f] is None else values[f] for f in names]], columns=names)
    slot = int(_slot([target]).iloc[0])
    ref = art["reference"].get(slot, art["overall"])

    # one batch: the actual row, then one row per present feature set to its reference
    batch = pd.concat([row] * (1 + len(present)), ignore_index=True)
    for i, f in enumerate(present, start=1):
        fallback = art["overall"].get(f)
        reference_value = ref.get(f, fallback)
        batch.loc[i, f] = np.nan if reference_value is None else reference_value
    q05 = models[0.05].predict(batch)
    actual = float(q05[0])
    effects = {f: actual - float(q05[i]) for i, f in enumerate(present, start=1)}
    top = sorted(effects, key=lambda f: (-abs(effects[f]), f))[:TOP_FACTORS]
    figures = [{"name": f, "value": values[f], "effect": effects[f]} for f in top]

    return {
        "figures": figures,
        "missing": missing,
        "q05": actual,
        "similar": _similar(art, values, decision),
    }


def _similar(art: dict, values: dict, decision: pd.Timestamp) -> list[dict]:
    names = feature_set.FEATURES
    index = art["index"]
    # only cases whose outcome was known at the decision time (never from the future)
    known = index["target_start"] + STEP <= decision
    pool = index[known]
    if pool.empty:
        return []
    matrix = pool[names].to_numpy(dtype=float)
    mean, std = (
        np.nanmean(index[names].to_numpy(dtype=float), axis=0),
        np.nanstd(index[names].to_numpy(dtype=float), axis=0),
    )
    std = np.where(std > 0, std, 1.0)
    query = np.array([np.nan if values[f] is None else values[f] for f in names])
    z_pool, z_query = (matrix - mean) / std, (query - mean) / std
    diff = z_pool - z_query
    shared = ~np.isnan(diff)
    n_shared = shared.sum(axis=1)
    squared = np.where(shared, diff**2, 0.0).sum(axis=1)
    distance = np.where(
        n_shared >= MIN_SHARED_DIMS, np.sqrt(squared / np.maximum(n_shared, 1)), np.inf
    )
    order = np.lexsort((pool["target_start"].to_numpy(), distance))[:SIMILAR]
    cases = []
    for i in order:
        if not np.isfinite(distance[i]):
            continue
        r = pool.iloc[i]
        cases.append(
            {
                "interval_start": r["target_start"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "q05": None if r["in_sample"] else float(r["q05"]),
                "in_sample": bool(r["in_sample"]),
                "safe_share": float(r["safe_share"]),
            }
        )
    return cases


def explain(feats: dict) -> dict:
    """``{"figures": [...], "similar": [...], "missing": [...], "q05": float}``."""
    from src.ml.predict import _load, model_version

    pt_id = feats.get("pt_id")
    if not pt_id:
        raise ValueError("features must include pt_id")
    for key in ("target_start", "decision_time"):
        if feats.get(key) is None:
            raise ValueError(f"features must include {key}")
    version = model_version()
    models, _ = _load(version, pt_id)
    folder = model_io.model_dir(version, pt_id)
    return explain_with(models, model_io.cached("explain", folder, load_artifacts), feats)
