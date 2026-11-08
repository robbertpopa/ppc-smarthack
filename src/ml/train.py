"""Train the safe-cap model: one quantile gradient-boosting model per quantile.

The model predicts the highest safe export share one hour ahead. The planner uses the
cautious quantile ``q05``; the spread ``q90 - q05`` drives "not sure" (abstention).

    python -m src.ml.train --scenario A       # or B, B-VAR, all

    python -m src.ml.train --scenario A --model-version safe-cap-qgb-v2

v1 (default): the training period fits, the validation period (2012-04 to 2012-06) picks
the hyper-parameters (at most four settings) and is reported. v2: the settings are chosen
on four expanding quarterly folds over 2011-07 to 2012-06 (every season), then the models
are refitted on 2010-07 to 2012-06; the out-of-sample predictions are saved next to them
(``oos_predictions.parquet``). **The test period is not read here**; the evaluation script
does that once.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_pinball_loss

from src.eval.metrics import evaluate, load_profiles, surplus_kw
from src.ml import abstention, baselines, calibration, features, model_io, online_calibration
from src.ml import labels as labels_io
from src.ml.config import crew_cases_per_day, violation_target
from src.ml.explain import build_artifacts, save_artifacts
from src.ml.split import FOLD_NAMES, daylight, fit_rows, folds, oos, split

QUANTILES: tuple[float, ...] = (0.05, 0.10, 0.20, 0.50, 0.90)
MODEL_VERSION_V1 = "safe-cap-qgb-v1"
MODEL_VERSION_V2 = "safe-cap-qgb-v2"
VERSIONS = (MODEL_VERSION_V1, MODEL_VERSION_V2)
MODEL_VERSION = MODEL_VERSION_V1  # what train(), the evaluation and the API use unless told
BASE_PARAMS = {"max_iter": 300, "learning_rate": 0.05, "max_leaf_nodes": 31, "min_samples_leaf": 40}
GRID: list[dict] = [
    BASE_PARAMS,
    {**BASE_PARAMS, "max_leaf_nodes": 15, "min_samples_leaf": 80},
    {**BASE_PARAMS, "max_iter": 150, "learning_rate": 0.1},
    {**BASE_PARAMS, "max_leaf_nodes": 63, "min_samples_leaf": 20},
]


def rearrange(q: np.ndarray) -> np.ndarray:
    """Sort the quantiles of each row (no crossing) and clip to [0, 1]. Shape (n, 5)."""
    return np.clip(np.sort(np.asarray(q, dtype=float), axis=1), 0.0, 1.0)


def fit_quantile(
    X, y, quantile: float, params: dict, seed: int = 0
) -> HistGradientBoostingRegressor:
    """``HistGradientBoostingRegressor`` takes NaN natively, so missing stays missing."""
    model = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=quantile,
        random_state=seed,
        early_stopping=False,  # no hidden random validation split
        **params,
    )
    return model.fit(X, y)


def predict_quantiles(models: dict[float, object], X) -> np.ndarray:
    """Rearranged predictions in ``QUANTILES`` order, shape (n, 5)."""
    raw = np.column_stack([models[q].predict(X) for q in QUANTILES])
    return rearrange(raw)


def training_rows(labels: pd.DataFrame) -> pd.DataFrame:
    """Daylight rows with a known target, with ``interval_start`` set to the target time."""
    frame = features.build_frame(labels)
    frame["interval_start"] = frame["target_start"]
    keep = daylight(frame) & frame["safe_share"].notna().to_numpy()
    return frame[keep].reset_index(drop=True)


def _economics(labels, part, share, surplus, kwp):
    """Violation rate and export index of a policy on a slice, plus the baselines."""
    policy = evaluate(share, part, surplus, kwp)
    return policy, baselines.table(labels, surplus, kwp, part)


def _optional_surplus(scenario: str):
    try:
        houses = labels_io.load_station_houses(scenario)
        profiles = load_profiles(houses)
    except (FileNotFoundError, OSError) as error:
        print(f"warning: {scenario}: export numbers skipped ({error})", file=sys.stderr)
        return None, None
    surplus = surplus_kw(profiles, houses)
    return (surplus, houses.set_index("house_id")["kwp"]) if len(surplus) else (None, None)


def _pinball(y, pred) -> dict[str, float]:
    return {
        str(q): float(mean_pinball_loss(y, pred[:, i], alpha=q)) for i, q in enumerate(QUANTILES)
    }


def _search(pairs, grid, seed, keep_models=False) -> list[dict]:
    """Fit every setting on every ``(fit, valid)`` pair and score the pooled predictions.

    v1 has one pair (train, validation); v2 has the four quarterly folds. The score of a
    setting is the mean pinball loss over the five quantiles of **all** out-of-sample rows.
    """
    y = np.concatenate([valid["safe_share"].to_numpy() for _, valid in pairs])
    results = []
    for params in grid:
        preds, fitted = [], []
        for fit, valid in pairs:
            models = {
                q: fit_quantile(fit[features.FEATURES], fit["safe_share"], q, params, seed)
                for q in QUANTILES
            }
            preds.append(predict_quantiles(models, valid[features.FEATURES]))
            fitted.append(models if keep_models else None)
        pred = np.vstack(preds)
        pinball = _pinball(y, pred)
        results.append(
            {
                "params": params,
                "mean_pinball": float(np.mean(list(pinball.values()))),
                "pinball": pinball,
                "pred": pred,
                "fold_pred": preds,
                "models": fitted,
            }
        )
    return results


def _fold_report(name, fit, valid, valid_labels, pred, surplus, kwp) -> dict:
    """One quarter: pinball per quantile, q05 coverage and the violation rate of q05."""
    y = valid["safe_share"].to_numpy()
    q05 = pd.Series(pred[:, 0], index=pd.DatetimeIndex(valid["target_start"]))
    policy = evaluate(q05, valid_labels, surplus, kwp)
    return {
        "name": name,
        "valid_period": [str(valid["target_start"].min()), str(valid["target_start"].max())],
        "n_train": len(fit),
        "n_val": len(valid),
        "pinball": _pinball(y, pred),
        "q05_coverage": float(calibration.quantile_coverage(y, pred, QUANTILES)["0.05"]),
        "q05_violation_rate": policy["violation_rate"],
    }


def _oos_frame(val_rows, pred) -> pd.DataFrame:
    """What ``online_calibration.replay`` needs: q05, the outcome and when each is known."""
    index = pd.DatetimeIndex(val_rows["target_start"])
    return pd.DataFrame(
        {
            "q05": pred[:, 0],
            "safe_share": val_rows["safe_share"].to_numpy(),
            "decision_time": pd.DatetimeIndex(val_rows["decision_time"]),
            "available_at": index + features.STEP,  # a label is known when its interval ends
        },
        index=index,
    )


def _choose_offset(val_rows, val_labels, pred, surplus, kwp) -> tuple[dict, np.ndarray]:
    """Step size ``gamma`` of the online offset, replayed on the out-of-sample year.

    Returns the record for ``metadata.json`` and the offset limits of every interval. The
    final ``c`` of the replay is the start value for the test year and live use.
    """
    alpha = violation_target()
    frame = _oos_frame(val_rows, pred)
    chosen = online_calibration.choose_gamma(frame, val_labels, surplus, kwp, alpha)
    run = online_calibration.replay(frame, chosen["gamma"], alpha)
    record = {
        "gamma": chosen["gamma"],
        "alpha": alpha,
        "c_start": run.c_final,
        "c_bounds": [online_calibration.C_MIN, online_calibration.C_MAX],
        "reachable": bool(chosen["reachable"]),
        "violation_rate": chosen["violation_rate"],
        "export_index": chosen["export_index"],
        "period": [str(val_rows["target_start"].min()), str(val_rows["target_start"].max())],
        "table": chosen["table"].to_dict(orient="records"),
        "reason": (
            "gamma with the highest export index whose violation rate on the out-of-sample "
            "year is at most alpha; if none, the lowest violation rate (reachable is false)"
        ),
    }
    return record, run.limit.to_numpy()


def _decision_layer(
    labels, val_labels, val_rows, pred, surplus, kwp, limit=None
) -> tuple[dict, pd.DataFrame]:
    """The limit, the baselines and the abstention threshold on one out-of-sample set.

    The limit is ``q05`` unless ``limit`` (the offset limit of v2) is given. The spread
    ``q90 - q05`` stays on the raw quantiles: it measures the model's uncertainty.
    """
    y_val = val_rows["safe_share"].to_numpy()
    index = pd.DatetimeIndex(val_rows["target_start"])
    q05 = pd.Series(pred[:, 0] if limit is None else limit, index=index)
    policy, base = _economics(labels, val_labels, q05, surplus, kwp)
    spread = pd.Series(pred[:, -1] - pred[:, 0], index=index)
    X_val = val_rows[features.FEATURES]
    flagged = pd.Series(
        [bool(abstention.quality_flags(r)) for r in X_val.to_dict("records")], index=index
    )
    target = violation_target()
    sweep = abstention.sweep(spread, q05, val_labels, surplus, kwp, flagged)
    chosen = abstention.pick(sweep, target)
    holdout = abstention.holdout_check(spread, q05, val_labels, surplus, kwp, target, flagged)
    budget = crew_cases_per_day()
    report = {
        "coverage_val": calibration.quantile_coverage(y_val, pred, QUANTILES),
        "q05_policy": {k: policy[k] for k in ("violation_rate", "export_index", "n_intervals")},
        "baselines_val": base.to_dict(orient="index"),
        "abstention": {
            "tau": chosen["tau"] if chosen["reachable"] else None,
            "reachable": chosen["reachable"],
            "violation_target": target,
            "target_reason": (
                "share of daylight validation intervals allowed to exceed the safe limit; "
                "2% is the level the exploration reached with a fallback (team to confirm)"
            ),
            "violation_rate_with_fallback": chosen["violation_rate"],
            "abstain_rate": chosen["abstain_rate"],
            "flagged_per_day_mean": chosen["per_day_mean"],
            "flagged_per_day_max": chosen["per_day_max"],
            "crew_cases_per_day": budget,
            "crew_budget_holds": bool(chosen["per_day_max"] <= budget),
            "share_flagged_by_input_checks": float(flagged.mean()),
            "holdout": holdout,
        },
    }
    return report, abstention.curve(sweep)


def train(
    scenario: str,
    seed: int = 0,
    grid: list[dict] | None = None,
    save: bool = True,
    out_root=None,
    version: str = MODEL_VERSION,
) -> dict:
    """Train, report on out-of-sample data and save. Returns the report.

    ``safe-cap-qgb-v1`` (default): fit on the training period, choose the setting and the
    abstention threshold on the validation period. ``safe-cap-qgb-v2``: choose the setting
    on four expanding quarterly folds (``split.folds``), refit on all of 2010-07 → 2012-06,
    and take the abstention threshold from the four out-of-sample quarters. The test year
    is read by neither.

    Models go to ``ARTIFACT_URI/models/<version>/<pt_id>/`` unless ``out_root`` is given
    (then ``<out_root>/<pt_id>/``), so an evaluation run can keep its models apart from the
    ones the API serves.
    """
    if version not in VERSIONS:
        raise ValueError(f"unknown model version {version!r}, expected one of {VERSIONS}")
    folded = version == MODEL_VERSION_V2
    grid = GRID if grid is None else grid
    labels = labels_io.load(scenario)
    stations = labels["pt_id"].unique()
    if len(stations) != 1:
        raise ValueError(f"scenario {scenario} must hold one station, found {list(stations)}")
    pt_id = stations[0]

    rows = training_rows(labels)
    if folded:
        pairs = folds(rows)
        label_pairs = folds(labels)
        fit_set, val_rows, val_labels = fit_rows(rows), oos(rows), oos(labels)
    else:
        parts = split(rows)
        pairs = [(parts["train"], parts["val"])]
        fit_set, val_rows, val_labels = parts["train"], parts["val"], split(labels)["val"]
    if fit_set.empty or val_rows.empty or any(v.empty for _, v in pairs):
        raise ValueError(
            f"need training and validation rows, got {len(fit_set)} and {len(val_rows)}"
        )

    search = _search(pairs, grid, seed, keep_models=not folded)
    best = min(search, key=lambda item: item["mean_pinball"])
    params, pred = best["params"], best["pred"]
    if folded:  # the models that go live saw the whole fit period, the last quarter too
        X_fit, y_fit = fit_set[features.FEATURES], fit_set["safe_share"]
        models = {q: fit_quantile(X_fit, y_fit, q, params, seed) for q in QUANTILES}
    else:
        models = best["models"][0]

    surplus, kwp = _optional_surplus(scenario)
    offset, limit = (
        _choose_offset(val_rows, val_labels, pred, surplus, kwp) if folded else (None, None)
    )
    decision, curve = _decision_layer(labels, val_labels, val_rows, pred, surplus, kwp, limit)
    report = {
        "pt_id": pt_id,
        "n_train": len(fit_set),
        "n_val": len(val_rows),
        "params": params,
        "pinball_val": best["pinball"],
        **decision,
    }
    if folded:
        report["offset"] = offset
        report["folds"] = [
            _fold_report(name, fit, valid, vlabels, fold_pred, surplus, kwp)
            for name, (fit, valid), (_, vlabels), fold_pred in zip(
                FOLD_NAMES, pairs, label_pairs, best["fold_pred"], strict=True
            )
        ]

    if save:
        score_key = "mean_pinball_oos" if folded else "mean_pinball_val"
        meta = {
            "model_version": version,
            "pt_id": pt_id,
            "scenario": scenario,
            "git_sha": model_io.git_sha(),
            "labels_sha256": model_io.file_sha256(
                labels_io.labels_path(scenario) / "labels.parquet"
            ),
            "is_mock_labels": labels_io.is_mock(labels),
            "train_period": [
                str(fit_set["target_start"].min()),
                str(fit_set["target_start"].max()),
            ],
            "val_period": [
                str(val_rows["target_start"].min()),
                str(val_rows["target_start"].max()),
            ],
            "features": features.FEATURES,
            "quantiles": list(QUANTILES),
            "seed": seed,
            "hyperparameters": params,
            "hyperparameter_search": [
                {"params": s["params"], score_key: s["mean_pinball"]} for s in search
            ],
            "validation": report,
            "abstention": report["abstention"],
            "sklearn_version": sklearn.__version__,
        }
        if folded:
            meta["folds"] = report["folds"]
            meta["offset"] = offset
            meta["fold_note"] = (
                "val_period is the four out-of-sample quarters; the final models are refitted "
                "on train_period"
            )
        out = Path(out_root) / pt_id if out_root else model_io.model_dir(version, pt_id)

        def write_extras(folder):  # swapped in together with the models they describe
            curve.to_csv(folder / "risk_coverage.csv", index=False)
            if folded:
                _oos_table(val_rows, pred, pairs, best["fold_pred"]).to_parquet(
                    folder / "oos_predictions.parquet", index=False
                )
                art = build_artifacts(models, pairs[0][0], val_rows, seed, val_q05=pred[:, 0])
            else:
                art = build_artifacts(models, fit_set, val_rows, seed)
            save_artifacts(art, folder)

        model_io.save(models, meta, out, extra=write_extras)
    return report


def _oos_table(val_rows, pred, pairs, fold_pred) -> pd.DataFrame:
    """The out-of-sample predictions of the four quarters, for the steps that replay them."""
    table = pd.DataFrame(
        {
            "target_start": val_rows["target_start"].to_numpy(),
            "fold": np.repeat(np.arange(len(pairs)), [len(p) for p in fold_pred]),
            "safe_share": val_rows["safe_share"].to_numpy(),
        }
    )
    for i, q in enumerate(QUANTILES):
        table[model_io.quantile_name(q)] = pred[:, i]
    return table


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.ml.train")
    parser.add_argument("--scenario", default="A", choices=(*labels_io.SCENARIOS, "all"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--model-version",
        default=MODEL_VERSION,
        choices=VERSIONS,
        help="v2 chooses the settings on four quarterly folds over 2011-07 to 2012-06",
    )
    args = parser.parse_args(argv)
    names = list(labels_io.SCENARIOS) if args.scenario == "all" else [args.scenario]
    done = 0
    for name in names:
        if not (labels_io.labels_path(name) / "labels.parquet").exists():
            print(f"skip {name}: no labels file", file=sys.stderr)
            continue
        report = train(name, args.seed, version=args.model_version)
        done += 1
        print(
            f"{name} ({report['pt_id']}): trained on {report['n_train']} rows, "
            f"validated on {report['n_val']}"
        )
        print("  q05 coverage on validation:", round(report["coverage_val"]["0.05"], 4))
        for fold in report.get("folds", []):
            print(
                f"  {fold['name']}: q05 coverage {fold['q05_coverage']:.4f}, "
                f"q05 violations {fold['q05_violation_rate']:.4f}, pinball q05 "
                f"{fold['pinball']['0.05']:.4f} ({fold['n_val']} rows)"
            )
        info = report["abstention"]
        print(
            f"  abstention: tau={info['tau']}, abstain {info['abstain_rate']:.3f}, "
            f"violations {info['violation_rate_with_fallback']:.4f} "
            f"(target {info['violation_target']}), flagged per day max "
            f"{info['flagged_per_day_max']:.0f} vs crew {info['crew_cases_per_day']}"
        )
        print("  q05 as the limit:", {k: round(v, 4) for k, v in report["q05_policy"].items()})
        for name_, row in report["baselines_val"].items():
            rate, export = row["violation_rate"], row["export_index"]
            print(f"  baseline {name_}: violation {rate:.4f}, export {export:.1f}")
    if not done:
        raise SystemExit(
            "no labels found: run `python -m src.ml.labels mock` or ask P3 for the real file"
        )


if __name__ == "__main__":
    main()
