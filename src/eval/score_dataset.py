"""Score ``safe-cap-qgb-v2-dataset`` once on the test period of ``src.ml.dataset``.

    python -m src.eval.score_dataset --model-version safe-cap-qgb-v2-dataset

Test is 2013-03-01 to 2013-04-30 (Sydney dates). Same rule as ``eval.run.score_model``
for v2: ``q05`` minus the online offset replayed from the stored start value, abstain on a
wide spread or a failed input check, fixed limit when abstaining. Run it once per version.
"""

import argparse
import json
import math
import sys

import numpy as np
import pandas as pd

from src.eval.metrics import FIXED_SHARE, evaluate, load_profiles, skill_score, surplus_kw
from src.ml import abstention, baselines, dataset, features, model_io, online_calibration, train
from src.ml import labels as labels_io
from src.ml.config import SYDNEY
from src.ml.split import local_date


def model_limits(models, meta, rows):
    """q05, spread, abstention, the offset limit and the fallback limit for every row.

    The online offset is replayed in time order from ``meta["offset"]["c_start"]``: a label
    teaches it once its interval is over, and an abstained interval teaches nothing.
    Returns ``(frame indexed by target_start, raw quantile predictions)``.
    """
    pred = train.predict_quantiles(models, rows[meta["features"]])
    index = pd.DatetimeIndex(rows["target_start"])
    q05 = pd.Series(pred[:, 0], index=index)
    spread = pd.Series(pred[:, -1] - pred[:, 0], index=index)
    flagged = pd.Series(
        [bool(abstention.quality_flags(r)) for r in rows[features.FEATURES].to_dict("records")],
        index=index,
    )
    info = meta["abstention"]
    tau = float(info["tau"]) if info["reachable"] else -math.inf
    abstain = (spread > tau) | flagged
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
    frame = pd.DataFrame(
        {
            "q05": q05,
            "spread": spread,
            "abstain": abstain,
            "limit": limit,
            "fallback": limit.where(~abstain, FIXED_SHARE),
        }
    )
    return frame, pred


def score(scenario: str, version: str) -> dict:
    labels = labels_io.load(scenario)
    houses = labels_io.load_station_houses(scenario)
    models, meta = model_io.load(version, labels["pt_id"].iloc[0])
    use_weather = bool(meta.get("weather", {}).get("used"))
    if use_weather:
        raise SystemExit("this scorer is for the no-weather version")
    rows = train.training_rows(labels)
    date = local_date(rows["interval_start"])
    test_rows = rows[(date >= dataset.TEST_START) & (date < dataset.DEMO_START)]
    test_labels = labels[
        (local_date(labels["interval_start"]) >= dataset.TEST_START)
        & (local_date(labels["interval_start"]) < dataset.DEMO_START)
    ]
    if test_rows.empty:
        raise SystemExit("no labelled test rows")
    surplus = surplus_kw(load_profiles(houses, dataset.out_dir() / "test.parquet"), houses)
    kwp = houses.set_index("house_id")["kwp"]

    frame, pred = model_limits(models, meta, test_rows)
    q05 = frame["q05"]
    abstain, limit, fallback = frame["abstain"], frame["limit"], frame["fallback"]
    y = test_rows["safe_share"].to_numpy()
    persistence = test_rows["share_last"].to_numpy()
    results = {
        name: evaluate(baselines.apply(name, labels), test_labels, surplus, kwp)
        for name in baselines.NAMES
    }
    results["model_q05"] = evaluate(q05, test_labels, surplus, kwp)
    results["model_offset"] = evaluate(limit, test_labels, surplus, kwp)
    results["model_fallback"] = evaluate(fallback, test_labels, surplus, kwp, abstain=abstain)
    skill = skill_score(y, q05.to_numpy(), persistence)
    coverage = {str(q): float(np.mean(y <= pred[:, i])) for i, q in enumerate(train.QUANTILES)}
    days = sorted(local_date(test_rows["interval_start"]).dt.date.astype(str).unique())
    return {
        "model_version": version,
        "n_test_rows": len(test_rows),
        "test_days": [days[0], days[-1], len(days)],
        "abstain_rate": float(abstain.mean()),
        "coverage_test": coverage,
        "coverage_validation": meta["validation"]["coverage_val"],
        "skill_q05_vs_persistence": skill,
        "policies": {
            k: {m: v[m] for m in ("violation_rate", "export_index", "n_intervals")}
            for k, v in results.items()
        },
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.eval.score_dataset")
    parser.add_argument("--scenario", default="A")
    parser.add_argument("--model-version", default=train.MODEL_VERSION_V2_DATASET)
    args = parser.parse_args(argv)
    result = score(args.scenario, args.model_version)
    print(json.dumps(result, indent=2, default=float))
    print(f"timezone for dates: {SYDNEY}", file=sys.stderr)


if __name__ == "__main__":
    main()
