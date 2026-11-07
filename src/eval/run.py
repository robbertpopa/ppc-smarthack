"""One command for the whole evaluation table.

    python -m src.eval.run [--scenario all|A|B|B-VAR] [--run-id local]
                           [--use-artifacts] [--allow-mock]

Trains (deterministically, fixed seeds) or loads the models, then scores every policy on
the **test period only**: 2012-07-01 to 2013-06-30, daylight intervals with a known safe
share. Nothing is chosen here: thresholds come from the model metadata (validation).
Outputs go to ``ARTIFACT_URI/eval/<run-id>/`` and contain no timestamps or absolute
paths, so two runs of the same code on the same data are byte-identical.

The test year needs the held-out Ausgrid file in the profiles: run
``python -m src.ml.data download --include-held-out`` and then ``... profiles`` once,
for the final evaluation only.
"""

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src.eval import table
from src.eval.metrics import FIXED_SHARE, evaluate, surplus_kw
from src.ml import abstention, baselines, calibration, features, model_io, train
from src.ml import labels as labels_io
from src.ml.config import SYDNEY, artifact_uri, profiles_path, violation_target
from src.ml.split import split

MOCK_TITLE = "MOCK – NOT A RESULT"
TITLE = "Evaluation on the test period"
KEYS = ("fixed", "last_known", "same_hour_yesterday", "model_q05", "model_fallback", "oracle")


class MockLabelsError(RuntimeError):
    pass


def eval_dir(run_id: str) -> Path:
    return Path(artifact_uri()) / "eval" / run_id


def _load_models(scenario: str, labels: pd.DataFrame, use_artifacts: bool, grid):
    pt_id = labels["pt_id"].iloc[0]
    if use_artifacts:
        models, meta = model_io.load(train.MODEL_VERSION, pt_id)
        expected = model_io.file_sha256(labels_io.labels_path(scenario) / "labels.parquet")
        if meta["labels_sha256"] != expected:
            raise ValueError(
                f"the saved model for {pt_id} was trained on other labels "
                f"({meta['labels_sha256'][:12]} vs {expected[:12]}); "
                "retrain or drop --use-artifacts"
            )
    else:
        train.train(scenario, grid=grid)
        models, meta = model_io.load(train.MODEL_VERSION, pt_id)
    return models, meta


def _prepare(scenario: str, allow_mock: bool, use_artifacts: bool, grid) -> dict:
    labels = labels_io.load(scenario)
    mock = labels_io.is_mock(labels)
    if mock and not allow_mock:
        raise MockLabelsError(
            f"scenario {scenario} has mock labels; pass --allow-mock to run on them "
            "(the outputs are then stamped MOCK – NOT A RESULT)"
        )
    test_labels = split(labels)["test"]
    if test_labels.empty:
        raise ValueError(
            f"scenario {scenario}: the labels have no rows in the test period "
            "(2012-07-01 to 2013-06-30)"
        )
    houses = labels_io.load_station_houses(scenario)
    surplus = kwp = profiles = None
    if profiles_path().exists():
        profiles = pd.read_parquet(profiles_path())
        surplus = surplus_kw(profiles, houses)
        kwp = houses.set_index("house_id")["kwp"]
        if not surplus.index.intersection(pd.DatetimeIndex(test_labels["interval_start"])).size:
            raise ValueError(
                "profiles.parquet does not cover the test period; for the final evaluation run "
                "`python -m src.ml.data download --include-held-out` and then `... profiles`"
            )
    models, meta = _load_models(scenario, labels, use_artifacts, grid)
    return {
        "scenario": scenario, "labels": labels, "test_labels": test_labels, "houses": houses,
        "profiles": profiles, "surplus": surplus, "kwp": kwp, "models": models, "meta": meta,
        "mock": mock,
    }  # fmt: skip


def _round(value):
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(value) else round(float(value), 6)
    if isinstance(value, np.integer):
        return int(value)
    return value


def tau_of(meta: dict) -> float:
    info = meta["abstention"]
    return float(info["tau"]) if info["reachable"] else -math.inf


def score_model(ctx: dict, labels: pd.DataFrame) -> dict:
    """Run the clean models on test-period features built from ``labels``.

    ``labels`` is normally the clean label table; the robustness variants pass a copy
    whose inputs (``load_kw``, ``pv_kw``, ``net_kw``) were corrupted. The target
    ``safe_share`` is never touched, so the scored rows are the same.
    """
    rows = split(train.training_rows(labels))["test"]
    X = rows[features.FEATURES]
    pred = train.predict_quantiles(ctx["models"], X)
    index = pd.DatetimeIndex(rows["target_start"])
    q05 = pd.Series(pred[:, 0], index=index)
    spread = pd.Series(pred[:, -1] - pred[:, 0], index=index)
    flagged = pd.Series(
        [bool(abstention.quality_flags(r)) for r in X.to_dict("records")], index=index
    )
    abstain = (spread > tau_of(ctx["meta"])) | flagged
    return {
        "rows": rows, "X": X, "pred": pred, "index": index, "q05": q05, "spread": spread,
        "flagged": flagged, "abstain": abstain, "fallback": q05.where(~abstain, FIXED_SHARE),
    }  # fmt: skip


def policies(ctx: dict) -> dict:
    """Rows for one station on the test period, plus what the other steps need."""
    labels, test, meta = ctx["labels"], ctx["test_labels"], ctx["meta"]
    surplus, kwp = ctx["surplus"], ctx["kwp"]
    scored = score_model(ctx, labels)
    rows, pred = scored["rows"], scored["pred"]
    q05, spread, flagged = scored["q05"], scored["spread"], scored["flagged"]
    abstain, fallback = scored["abstain"], scored["fallback"]
    info = meta["abstention"]
    tau = tau_of(meta)

    shares = {name: baselines.apply(name, labels) for name in baselines.NAMES}
    results = {
        "fixed": evaluate(shares["fixed"], test, surplus, kwp),
        "last_known": evaluate(shares["last_known"], test, surplus, kwp),
        "same_hour_yesterday": evaluate(shares["same_hour_yesterday"], test, surplus, kwp),
        "model_q05": evaluate(q05, test, surplus, kwp),
        "model_fallback": evaluate(fallback, test, surplus, kwp, abstain=abstain),
        "oracle": evaluate(shares["oracle"], test, surplus, kwp),
    }
    y = rows["safe_share"].to_numpy()
    cal_test = calibration.quantile_coverage(y, pred, train.QUANTILES)
    cal_val = meta["validation"]["coverage_val"]
    cal = pd.DataFrame(
        {
            "quantile": [str(q) for q in train.QUANTILES],
            "coverage_validation": [cal_val[str(q)] for q in train.QUANTILES],
            "coverage_test": [cal_test[str(q)] for q in train.QUANTILES],
        }
    )
    drift = calibration.drift(
        float(info["violation_rate_with_fallback"]), results["model_fallback"]["violation_rate"]
    )
    curve = abstention.risk_coverage(spread, q05, test, surplus, kwp, flagged)
    return {
        "rows": results, "calibration": cal, "drift": drift, "risk_coverage": curve,
        "tau": None if not info["reachable"] else tau, "n_test": len(rows),
        "scored": scored,
    }  # fmt: skip


def _clean_note(value):
    if isinstance(value, dict):
        return {k: _clean_note(v) for k, v in value.items()}
    return _round(value)


def _clean(results: dict) -> dict:
    keep = (
        "export_index",
        "violation_rate",
        "abstain_rate",
        "per_day_mean",
        "per_day_max",
        "n_intervals",
    )
    extra = ("delta_violation_rate", "delta_export_index", "delta_abstain_rate")
    return {
        k: {m: _round(r[m]) for m in (*keep, *(e for e in extra if e in r))}
        for k, r in results.items()
    }


def run(
    scenarios,
    run_id="local",
    use_artifacts=False,
    allow_mock=False,
    robustness=True,
    error_analysis=False,
    grid=None,
) -> dict:
    """Evaluate every scenario and write the outputs. Returns the summary."""
    started = time.perf_counter()
    out = eval_dir(run_id)
    out.mkdir(parents=True, exist_ok=True)
    all_rows, summary_scenarios, calibrations, footer, any_mock = {}, {}, [], [], False
    sections = []
    for scenario in scenarios:
        ctx = _prepare(scenario, allow_mock, use_artifacts, grid)
        pt_id = ctx["labels"]["pt_id"].iloc[0]
        result = policies(ctx)
        rows, extra = result["rows"], {}
        if robustness:
            from src.eval import robustness as robust

            variants = robust.run_variants(ctx, result)
            rows = {**rows, **variants["rows"]}
            extra = {"robustness": {k: _clean_note(v) for k, v in variants["notes"].items()}}
        if error_analysis:
            from src.eval import error_analysis as analysis

            sections.append(analysis.analyse(ctx, result, rows, out, pt_id))
        any_mock |= ctx["mock"]
        all_rows[pt_id] = rows
        meta, test = ctx["meta"], ctx["test_labels"]
        cal = result["calibration"].assign(station=pt_id)
        calibrations.append(cal)
        result["risk_coverage"].to_csv(
            out / f"risk_coverage_{pt_id}.csv",
            index=False,
            float_format="%.6f",
            lineterminator="\n",
        )
        threshold = result["tau"]
        first_day = test["interval_start"].min().tz_convert(SYDNEY).strftime("%Y-%m-%d")
        last_day = test["interval_start"].max().tz_convert(SYDNEY).strftime("%Y-%m-%d")
        tau_text = "always abstain" if threshold is None else f"{threshold:.4f}"
        footer.append(
            f"{pt_id}: test {first_day} to {last_day}, {result['n_test']} daylight intervals; "
            f"labels `{test['source_ref'].iloc[0]}`, SHA-256 `{meta['labels_sha256'][:16]}`; "
            f"threshold on spread {tau_text}; violation drift validation "
            f"{result['drift']['validation']:.4f} to test {result['drift']['test']:.4f}"
        )
        summary_scenarios[pt_id] = {
            "rows": _clean(rows),
            "threshold": _round(threshold) if threshold is not None else None,
            "calibration_drift": {k: _round(v) for k, v in result["drift"].items()},
            "labels_sha256": meta["labels_sha256"],
            "source_ref": test["source_ref"].iloc[0],
            **extra,
        }
    git = model_io.git_sha()
    footer += [
        f"git `{git}`; violation target {violation_target()}; fixed limit {FIXED_SHARE}",
        table.ACCOUNTING_NOTE,
    ]
    title = f"{MOCK_TITLE} – {TITLE}" if any_mock else TITLE
    frame = table.to_frame(all_rows)
    (out / "table.csv").write_text(table.to_csv(frame))
    (out / "table.md").write_text(table.to_markdown(frame, title, footer))
    pd.concat(calibrations).to_csv(
        out / "calibration.csv", index=False, float_format="%.6f", lineterminator="\n"
    )
    summary = {
        "run_id": run_id,
        "git_sha": git,
        "mock": bool(any_mock),
        "scenarios": summary_scenarios,
    }
    if any_mock:
        summary["title"] = MOCK_TITLE
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    if error_analysis:
        analysis.write(sections, out, any_mock)
    print(f"evaluation written to {out} in {time.perf_counter() - started:.1f} s")
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.eval.run")
    parser.add_argument("--scenario", default="all", choices=(*labels_io.SCENARIOS, "all"))
    parser.add_argument("--run-id", default="local")
    parser.add_argument("--use-artifacts", action="store_true", help="load saved models")
    parser.add_argument(
        "--allow-mock", action="store_true", help="run on mock labels (not a result)"
    )
    parser.add_argument("--no-robustness", dest="robustness", action="store_false")
    parser.add_argument(
        "--error-analysis", action="store_true", help="also write the error analysis"
    )
    args = parser.parse_args(argv)
    names = list(labels_io.SCENARIOS) if args.scenario == "all" else [args.scenario]
    names = [n for n in names if (labels_io.labels_path(n) / "labels.parquet").exists()]
    if not names:
        raise SystemExit(
            "no labels found: ask P3 for the real file, or use `python -m src.ml.labels mock`"
        )
    try:
        run(
            names,
            args.run_id,
            args.use_artifacts,
            args.allow_mock,
            args.robustness,
            args.error_analysis,
        )
    except MockLabelsError as err:
        raise SystemExit(str(err)) from err


if __name__ == "__main__":
    main()
