"""Train the safe-cap model: one quantile gradient-boosting model per quantile.

The model predicts the highest safe export share one hour ahead. The planner uses the
cautious quantile ``q05``; the spread ``q90 - q05`` drives "not sure" (abstention).

    python -m src.ml.train --scenario A       # or B, B-VAR, all

Only the training period is used for fitting. The validation period picks the
hyper-parameters (at most four settings) and is reported. **The test period is not read
here**; the evaluation script does that once.
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
from src.ml import abstention, baselines, calibration, features, model_io
from src.ml import labels as labels_io
from src.ml.config import crew_cases_per_day, violation_target
from src.ml.explain import build_artifacts, save_artifacts
from src.ml.split import daylight, split

QUANTILES: tuple[float, ...] = (0.05, 0.10, 0.20, 0.50, 0.90)
MODEL_VERSION = "safe-cap-qgb-v1"
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


def training_rows(labels: pd.DataFrame, weather: pd.DataFrame | None = None) -> pd.DataFrame:
    """Daylight rows with a known target, with ``interval_start`` set to the target time.

    ``weather`` (``src.ml.weather.load``) fills the weather features; without it they are NaN.
    """
    frame = features.build_frame(labels, weather=weather)
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


def train(
    scenario: str,
    seed: int = 0,
    grid: list[dict] | None = None,
    save: bool = True,
    out_root=None,
) -> dict:
    """Train, report on validation and save. Returns the validation report.

    Models go to ``ARTIFACT_URI/models/<version>/<pt_id>/`` unless ``out_root`` is given
    (then ``<out_root>/<pt_id>/``), so an evaluation run can keep its models apart from the
    ones the API serves.
    """
    grid = GRID if grid is None else grid
    labels = labels_io.load(scenario)
    stations = labels["pt_id"].unique()
    if len(stations) != 1:
        raise ValueError(f"scenario {scenario} must hold one station, found {list(stations)}")
    pt_id = stations[0]

    rows = training_rows(labels)
    parts = split(rows)
    train_rows, val_rows = parts["train"], parts["val"]
    if train_rows.empty or val_rows.empty:
        raise ValueError(
            f"need training and validation rows, got {len(train_rows)} and {len(val_rows)}"
        )
    columns = features.usable(train_rows)
    X_train, y_train = train_rows[columns], train_rows["safe_share"]
    X_val, y_val = val_rows[columns], val_rows["safe_share"].to_numpy()

    search = []
    for params in grid:
        models = {q: fit_quantile(X_train, y_train, q, params, seed) for q in QUANTILES}
        pred = predict_quantiles(models, X_val)
        pinball = {
            str(q): float(mean_pinball_loss(y_val, pred[:, i], alpha=q))
            for i, q in enumerate(QUANTILES)
        }
        search.append(
            {
                "params": params,
                "mean_pinball_val": float(np.mean(list(pinball.values()))),
                "models": models,
                "pred": pred,
                "pinball": pinball,
            }
        )
    best = min(search, key=lambda item: item["mean_pinball_val"])
    models, params, pred = best["models"], best["params"], best["pred"]

    surplus, kwp = _optional_surplus(scenario)
    val_labels = split(labels)["val"]
    q05 = pd.Series(pred[:, 0], index=pd.DatetimeIndex(val_rows["target_start"]))
    policy, base = _economics(labels, val_labels, q05, surplus, kwp)
    index = pd.DatetimeIndex(val_rows["target_start"])
    spread = pd.Series(pred[:, -1] - pred[:, 0], index=index)
    flagged = pd.Series(
        [bool(abstention.quality_flags(r)) for r in X_val.to_dict("records")], index=index
    )
    target = violation_target()
    sweep = abstention.sweep(spread, q05, val_labels, surplus, kwp, flagged)
    chosen = abstention.pick(sweep, target)
    curve = abstention.curve(sweep)
    holdout = abstention.holdout_check(spread, q05, val_labels, surplus, kwp, target, flagged)
    budget = crew_cases_per_day()
    report = {
        "pt_id": pt_id,
        "n_train": len(train_rows),
        "n_val": len(val_rows),
        "params": params,
        "pinball_val": best["pinball"],
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
            "train_period": [
                str(train_rows["target_start"].min()),
                str(train_rows["target_start"].max()),
            ],
            "val_period": [
                str(val_rows["target_start"].min()),
                str(val_rows["target_start"].max()),
            ],
            "features": columns,
            "quantiles": list(QUANTILES),
            "seed": seed,
            "hyperparameters": params,
            "hyperparameter_search": [
                {"params": s["params"], "mean_pinball_val": s["mean_pinball_val"]} for s in search
            ],
            "validation": report,
            "abstention": report["abstention"],
            "sklearn_version": sklearn.__version__,
        }
        out = Path(out_root) / pt_id if out_root else model_io.model_dir(MODEL_VERSION, pt_id)

        def write_extras(folder):  # swapped in together with the models they describe
            curve.to_csv(folder / "risk_coverage.csv", index=False)
            save_artifacts(build_artifacts(models, train_rows, val_rows, seed), folder)

        model_io.save(models, meta, out, extra=write_extras)
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.ml.train")
    parser.add_argument("--scenario", default="A", choices=(*labels_io.SCENARIOS, "all"))
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    names = list(labels_io.SCENARIOS) if args.scenario == "all" else [args.scenario]
    done = 0
    for name in names:
        if not (labels_io.labels_path(name) / "labels.parquet").exists():
            print(f"skip {name}: no labels file", file=sys.stderr)
            continue
        report = train(name, args.seed)
        done += 1
        print(
            f"{name} ({report['pt_id']}): trained on {report['n_train']} rows, "
            f"validated on {report['n_val']}"
        )
        print("  q05 coverage on validation:", round(report["coverage_val"]["0.05"], 4))
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
