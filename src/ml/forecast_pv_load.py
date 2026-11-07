"""Quantile forecasts of station PV and load for several hours ahead (for the batteries).

Same code as the safe-cap model, different targets: the station totals ``pv_kw`` and
``load_kw`` at ``T = t + horizon``, quantiles 0.10, 0.50 and 0.90, one model per target,
horizon and quantile. Features are the task 04 set computed for that ``T``. Targets are
divided by ``kwp_total`` while training and multiplied back when predicting.

Each model is compared with "same time yesterday" on the validation period (pinball loss
and p10-p90 coverage). The comparison is stored in ``metadata.json`` whether or not the
model wins.

Labels only cover daylight, so the load forecast exists for daylight target times only.
At night PV is exactly 0 and the load band is ``None``.
"""

import argparse

import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import mean_pinball_loss

from src.common.contract import Band
from src.ml import features, model_io
from src.ml import labels as labels_io
from src.ml.split import daylight, split
from src.ml.train import BASE_PARAMS, fit_quantile

MODEL_VERSION = "pv-load-qgb-v1"
HORIZONS = (60, 180, 360)
QUANTILES = (0.10, 0.50, 0.90)
TARGETS = ("pv_kw", "load_kw")
DAY = pd.Timedelta(hours=24)


def band(values: np.ndarray) -> Band:
    """Order the three quantiles and clip below at zero."""
    p10, p50, p90 = np.sort(np.clip(np.asarray(values, dtype=float), 0, None))
    return Band(p10=float(p10), p50=float(p50), p90=float(p90))


def _name(target: str, horizon: int, q: float) -> str:
    return f"{target.removesuffix('_kw')}_h{horizon}_q{round(q * 100):02d}"


def _rows(labels: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Feature rows for one horizon with normalised targets and the yesterday baseline."""
    frame = features.build_frame(labels, horizon)
    start = pd.DatetimeIndex(labels["interval_start"])
    kwp = pd.Series(labels["kwp_total"].to_numpy(), index=start)
    for target in TARGETS:
        norm = pd.Series((labels[target] / labels["kwp_total"]).to_numpy(), index=start)
        frame[target] = norm.reindex(pd.DatetimeIndex(frame["target_start"])).to_numpy()
        yesterday = norm.reindex(pd.DatetimeIndex(frame["target_start"]) - DAY)
        frame[f"{target}_yesterday"] = yesterday.to_numpy()
    frame["kwp_total"] = kwp.reindex(pd.DatetimeIndex(frame["target_start"])).to_numpy()
    frame["interval_start"] = frame["target_start"]
    return frame[daylight(frame)].reset_index(drop=True)


def _pinball(y, pred_by_q) -> float:
    return float(np.mean([mean_pinball_loss(y, pred_by_q[q], alpha=q) for q in QUANTILES]))


def train(scenario: str, seed: int = 0, horizons=HORIZONS, params=None, save: bool = True) -> dict:
    """Train all models, compare with yesterday on validation, save with metadata."""
    params = BASE_PARAMS if params is None else params
    labels = labels_io.load(scenario)
    stations = labels["pt_id"].unique()
    if len(stations) != 1:
        raise ValueError(f"scenario {scenario} must hold one station, found {list(stations)}")
    pt_id = stations[0]
    models, report = {}, {}
    for horizon in horizons:
        parts = split(_rows(labels, horizon))
        for target in TARGETS:
            fit = parts["train"].dropna(subset=[target])
            val = parts["val"].dropna(subset=[target, f"{target}_yesterday"])
            if fit.empty or val.empty:
                raise ValueError(f"{target} h{horizon}: no training or validation rows")
            pred = {}
            for q in QUANTILES:
                model = fit_quantile(fit[features.FEATURES], fit[target], q, params, seed)
                models[_name(target, horizon, q)] = model
                pred[q] = model.predict(val[features.FEATURES])
            y = val[target].to_numpy()
            # the bands that are served are sorted, so the loss is scored on the sorted bands
            ordered = np.clip(
                np.sort(np.column_stack([pred[q] for q in QUANTILES]), axis=1), 0, None
            )
            served = {q: ordered[:, i] for i, q in enumerate(QUANTILES)}
            base = {q: val[f"{target}_yesterday"].to_numpy() for q in QUANTILES}
            model_loss, base_loss = _pinball(y, served), _pinball(y, base)
            report[f"{target}_h{horizon}"] = {
                "pinball_model": model_loss,
                "pinball_yesterday": base_loss,
                "beats_yesterday": model_loss < base_loss,
                "coverage_p10_p90_model": float(
                    np.mean((y >= ordered[:, 0]) & (y <= ordered[:, 2]))
                ),
                "n_val": len(val),
            }
    if save:
        meta = {
            "model_version": MODEL_VERSION,
            "pt_id": pt_id,
            "scenario": scenario,
            "git_sha": model_io.git_sha(),
            "labels_sha256": model_io.file_sha256(
                labels_io.labels_path(scenario) / "labels.parquet"
            ),
            "is_mock_labels": labels_io.is_mock(labels),
            "horizons": list(horizons),
            "quantiles": list(QUANTILES),
            "targets": list(TARGETS),
            "features": features.FEATURES,
            "kwp_total": float(labels["kwp_total"].iloc[-1]),
            "seed": seed,
            "hyperparameters": params,
            "validation": report,
            "sklearn_version": sklearn.__version__,
        }
        model_io.save(models, meta, model_io.model_dir(MODEL_VERSION, pt_id))
    return report


def _load(pt_id: str):
    def loader(folder):
        import joblib

        meta = model_io.load_metadata(MODEL_VERSION, pt_id)
        if meta["features"] != features.FEATURES:
            raise ValueError(f"{MODEL_VERSION}/{pt_id} was trained on other features; retrain it")
        names = [
            _name(t, h, q)
            for t in meta["targets"]
            for h in meta["horizons"]
            for q in meta["quantiles"]
        ]
        try:
            return {n: joblib.load(folder / f"{n}.joblib") for n in names}, meta
        except FileNotFoundError as error:  # not "no model yet": the folder is incomplete
            raise ValueError(f"{MODEL_VERSION}/{pt_id} is incomplete: {error}") from error

    return model_io.cached("pv-load", model_io.model_dir(MODEL_VERSION, pt_id), loader)


def predict_pv_load(feats: dict, horizon_min: int = 60) -> dict[str, Band | None]:
    """``{"pv_kw": Band, "load_kw": Band | None}`` for the target time in ``feats``.

    ``feats`` comes from ``features.build(state, t, horizon_min)``. PV is exactly 0 when
    the sun is below the horizon at the target time; the load band is then ``None``.
    """
    pt_id = feats.get("pt_id")
    if not pt_id:
        raise ValueError("features must include pt_id")
    models, meta = _load(pt_id)
    if horizon_min not in meta["horizons"]:
        raise ValueError(f"horizon_min must be one of {meta['horizons']}, got {horizon_min}")
    X = pd.DataFrame(
        [[feats.get(n) for n in features.FEATURES]], columns=features.FEATURES, dtype=float
    )
    kwp = meta["kwp_total"]
    out = {}
    for target in TARGETS:
        raw = [models[_name(target, horizon_min, q)].predict(X)[0] * kwp for q in meta["quantiles"]]
        out[target] = band(raw)
    sun = feats.get("sun_elev_T")
    if sun is not None and not np.isnan(sun) and sun <= 0:
        out["pv_kw"] = Band(p10=0.0, p50=0.0, p90=0.0)
        out["load_kw"] = None
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.ml.forecast_pv_load")
    parser.add_argument("--scenario", default="A", choices=labels_io.SCENARIOS)
    args = parser.parse_args(argv)
    report = train(args.scenario)
    print(f"{'target/horizon':<14} {'pinball model':>14} {'yesterday':>10} {'beats':>6}")
    for key, row in report.items():
        print(
            f"{key:<14} {row['pinball_model']:>14.4f} {row['pinball_yesterday']:>10.4f} "
            f"{str(row['beats_yesterday']):>6}"
        )


if __name__ == "__main__":
    main()
