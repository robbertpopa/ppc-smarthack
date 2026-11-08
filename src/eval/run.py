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

from src.eval import imbalance_eval, pricing_eval, table
from src.eval.metrics import FIXED_SHARE, evaluate, fairness, load_profiles, skill_score, surplus_kw
from src.ml import abstention, baselines, calibration, features, model_io, online_calibration, train
from src.ml import labels as labels_io
from src.ml.config import SYDNEY, artifact_uri, profiles_path, violation_target
from src.ml.split import TEST_START, daylight, split
from src.pricing import prices as price_data

MOCK_TITLE = "MOCK – NOT A RESULT"
TITLE = "Evaluation on the test period"
LOOK_BACK = pd.Timedelta(days=2)
KEYS = ("fixed", "last_known", "same_hour_yesterday", "model_q05", "model_fallback", "oracle")


class MockLabelsError(RuntimeError):
    pass


def _require_report_extra() -> None:
    """The error analysis draws plots; matplotlib lives in the optional ``report`` extra."""
    try:
        import matplotlib  # noqa: F401
    except ImportError as error:
        raise SystemExit(
            "--error-analysis needs matplotlib: install it with `pip install '.[report]'` "
            "(it is kept out of the serving image on purpose)"
        ) from error


def _has_report_extra() -> bool:
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return False
    return True


def eval_dir(run_id: str) -> Path:
    return Path(artifact_uri()) / "eval" / run_id


def _load_models(scenario: str, labels: pd.DataFrame, run_id: str, use_artifacts: bool, grid):
    """Models for the evaluation.

    By default they are trained fresh into this run's own folder
    (``eval/<run-id>/models/<pt_id>``), so an evaluation never overwrites the models the
    API serves from ``ARTIFACT_URI/models``. ``--use-artifacts`` scores the deployed ones.
    """
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
        own = eval_dir(run_id) / "models"
        train.train(scenario, grid=grid, out_root=own)
        models, meta = model_io.load_dir(own / pt_id)
    return models, meta


def _load_v2(scenario: str, labels: pd.DataFrame, run_id: str, use_artifacts: bool, grid):
    """Models of ``safe-cap-qgb-v2`` next to v1 (same rules), or None if there are none."""
    pt_id = labels["pt_id"].iloc[0]
    version = train.MODEL_VERSION_V2
    if use_artifacts:
        try:
            models, meta = model_io.load(version, pt_id)
        except FileNotFoundError:
            return None
    else:
        own = eval_dir(run_id) / "models_v2"
        train.train(scenario, grid=grid, out_root=own, version=version)
        models, meta = model_io.load_dir(own / pt_id)
    weather = train._optional_weather(scenario) if meta.get("weather", {}).get("used") else None
    return {"models": models, "meta": meta, "weather": weather}


def _surplus(test_labels, houses, mock: bool, allow_mock: bool):
    """Surplus per house for the export numbers, or fail: it is the main metric.

    Only a mock run that was explicitly allowed may go without profiles (export is then
    NaN everywhere). Otherwise the profiles must cover every scored test interval.
    """
    if not profiles_path().exists():
        if mock and allow_mock:
            return None, None, None
        raise FileNotFoundError(
            f"{profiles_path()} not found: without per-house profiles there are no export "
            "numbers. Run `python -m src.ml.data download` and `... profiles` (and for the "
            "final evaluation `download --include-held-out` first)"
        )
    profiles = load_profiles(houses)
    surplus = surplus_kw(profiles, houses)
    kwp = houses.set_index("house_id")["kwp"]
    scored = test_labels.loc[
        daylight(test_labels) & test_labels["safe_share"].notna(), "interval_start"
    ]
    missing = pd.DatetimeIndex(scored).difference(surplus.index)
    if len(missing):
        raise ValueError(
            f"profiles.parquet does not cover {len(missing)} of {len(scored)} scored test "
            "intervals; for the final evaluation run "
            "`python -m src.ml.data download --include-held-out` and then `... profiles`"
        )
    return profiles, surplus, kwp


def _prepare(
    scenario: str, run_id: str, allow_mock: bool, use_artifacts: bool, grid, v2: bool = True
) -> dict:
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
    profiles, surplus, kwp = _surplus(test_labels, houses, mock, allow_mock)
    models, meta = _load_models(scenario, labels, run_id, use_artifacts, grid)
    second = _load_v2(scenario, labels, run_id, use_artifacts, grid) if v2 else None
    return {
        "scenario": scenario, "labels": labels, "test_labels": test_labels, "houses": houses,
        "profiles": profiles, "surplus": surplus, "kwp": kwp, "models": models, "meta": meta,
        "mock": mock, "v2": second,
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


def score_model(
    ctx: dict, labels: pd.DataFrame, v2: bool = False, weather_missing: bool = False
) -> dict:
    """Run the clean models on test-period features built from ``labels``.

    ``labels`` is normally the clean label table; the robustness variants pass a copy
    whose inputs (``load_kw``, ``pv_kw``, ``net_kw``) were corrupted. The target
    ``safe_share`` is never touched, so the scored rows are the same.

    ``v2`` scores ``safe-cap-qgb-v2``: its weather features, and its limit is ``q05`` minus
    the online offset, replayed in time order from the start value in the metadata (a label
    teaches the offset only once it is known, and an abstained interval teaches nothing).
    ``weather_missing`` blanks the weather features of v2 (the weather feed is down).
    """
    model = ctx["v2"] if v2 else ctx
    meta = model["meta"]
    weather = None if (not v2 or weather_missing) else model["weather"]
    # features need at most 24 h of history, so the test period plus two days is enough
    start = pd.Timestamp(TEST_START).tz_localize(SYDNEY).tz_convert("UTC") - LOOK_BACK
    labels = labels[labels["interval_start"] >= start]
    rows = split(train.training_rows(labels, weather))["test"]
    X = rows[meta["features"]]
    pred = train.predict_quantiles(model["models"], X)
    index = pd.DatetimeIndex(rows["target_start"])
    q05 = pd.Series(pred[:, 0], index=index)
    spread = pd.Series(pred[:, -1] - pred[:, 0], index=index)
    flagged = pd.Series(
        [bool(abstention.quality_flags(r)) for r in rows[features.FEATURES].to_dict("records")],
        index=index,
    )
    abstain = (spread > tau_of(meta)) | flagged
    limit = q05
    if v2:
        offset = meta["offset"]
        replayed = online_calibration.replay(
            pd.DataFrame(
                {
                    "q05": q05,
                    "safe_share": rows["safe_share"].to_numpy(),
                    "decision_time": pd.DatetimeIndex(rows["decision_time"]),
                    "available_at": index + features.STEP,
                    "abstain": abstain.to_numpy(),
                },
                index=index,
            ),
            offset["gamma"],
            offset["alpha"],
            c0=offset["c_start"],
        )
        limit = replayed.limit
    return {
        "rows": rows, "X": X, "pred": pred, "index": index, "q05": q05, "spread": spread,
        "flagged": flagged, "abstain": abstain, "limit": limit,
        "fallback": limit.where(~abstain, FIXED_SHARE),
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
    persistence = rows["share_last"].to_numpy()
    for key, share in (("fixed", shares["fixed"]), ("model_fallback", fallback)):
        results[key]["jain"] = fairness(share, test, surplus, kwp)
    results["oracle"]["jain"] = fairness(shares["oracle"], test, surplus, kwp)
    for key in ("model_q05", "model_fallback"):
        results[key]["skill_q05"] = skill_score(y, q05.to_numpy(), persistence)
    second = _policies_v2(ctx, labels, persistence, y) if ctx.get("v2") else None
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
        "scored": scored, "v2": second,
    }  # fmt: skip


def _policies_v2(ctx: dict, labels: pd.DataFrame, persistence, y) -> dict:
    """Rows of ``safe-cap-qgb-v2`` on the same test intervals as v1."""
    test, surplus, kwp = ctx["test_labels"], ctx["surplus"], ctx["kwp"]
    scored = score_model(ctx, labels, v2=True)
    skill = skill_score(y, scored["q05"].to_numpy(), persistence)
    rows = {
        "model_v2_q05": evaluate(scored["limit"], test, surplus, kwp),
        "model_v2_fallback": evaluate(
            scored["fallback"], test, surplus, kwp, abstain=scored["abstain"]
        ),
    }
    for result in rows.values():
        result["skill_q05"] = skill
    rows["model_v2_fallback"]["jain"] = fairness(scored["fallback"], test, surplus, kwp)
    meta = ctx["v2"]["meta"]
    tau = tau_of(meta)
    return {"rows": rows, "scored": scored, "tau": None if math.isinf(tau) else tau}


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
    extra = (
        "delta_violation_rate",
        "delta_export_index",
        "delta_abstain_rate",
        "skill_q05",
        "jain",
    )
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
    pricing=False,
    v2=True,
) -> dict:
    """Evaluate every scenario and write the outputs. Returns the summary."""
    if error_analysis:
        _require_report_extra()
    started = time.perf_counter()
    out = eval_dir(run_id)
    out.mkdir(parents=True, exist_ok=True)
    all_rows, summary_scenarios, calibrations, footer, any_mock = {}, {}, [], [], False
    sections = []
    price_table = price_data.profile(price_data.load()) if pricing else None
    for scenario in scenarios:
        ctx = _prepare(scenario, run_id, allow_mock, use_artifacts, grid, v2)
        pt_id = ctx["labels"]["pt_id"].iloc[0]
        result = policies(ctx)
        rows, extra = result["rows"], {}
        if robustness:
            from src.eval import robustness as robust

            variants = robust.run_variants(ctx, result)
            rows = {**rows, **variants["rows"]}
            extra = {"robustness": {k: _clean_note(v) for k, v in variants["notes"].items()}}
        if result["v2"] is not None:
            second = result["v2"]
            rows = {**rows, **second["rows"]}
            if robustness and variants["rows"]:
                weak = robust.run_weather_missing(ctx, result)
                rows = {**rows, **weak["rows"]}
                extra["robustness"] = {**extra["robustness"], **_clean_note(weak["notes"])}
            meta2 = ctx["v2"]["meta"]
            extra["v2"] = {
                "model_version": meta2["model_version"],
                "threshold": _round(second["tau"]) if second["tau"] is not None else None,
                "offset": _clean_note(
                    {k: meta2["offset"][k] for k in ("gamma", "alpha", "c_start", "reachable")}
                ),
                "weather_used": bool(meta2["weather"]["used"]),
                "labels_sha256": meta2["labels_sha256"],
            }
        if error_analysis:
            from src.eval import error_analysis as analysis

            sections.append(analysis.analyse(ctx, result, rows, out, pt_id))
        if price_table is not None:
            savings = imbalance_eval.station_savings(ctx, result)
            block = pricing_eval.compute(ctx, result, price_table, imbalance=savings)
            if block is not None:
                extra = {**extra, "pricing": block}
                pricing_eval.write(out, pt_id, block, MOCK_TITLE if ctx["mock"] else None)
                if _has_report_extra():
                    pricing_eval.day_chart(ctx, result, price_table, out, pt_id)
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
        "--no-v2", dest="v2", action="store_false", help="score only safe-cap-qgb-v1"
    )
    parser.add_argument(
        "--error-analysis", action="store_true", help="also write the error analysis"
    )
    parser.add_argument(
        "--pricing", action="store_true", help="also write the prosumer price comparison"
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
            pricing=args.pricing,
            v2=args.v2,
        )
    except MockLabelsError as err:
        raise SystemExit(str(err)) from err


if __name__ == "__main__":
    main()
