"""Audit check: is training deterministic, and how far does the stored model drift from a retrain?

    .venv/bin/python -m audit.check_repro

Trains twice with one hyper-parameter setting and ``save=False`` (nothing is written).
"""

import json

from src.ml import train


def main() -> None:
    a = train.train("A", seed=0, grid=[train.BASE_PARAMS], save=False)
    b = train.train("A", seed=0, grid=[train.BASE_PARAMS], save=False)
    same = json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    print("two runs, same seed, identical report:", same)
    c = train.train("A", seed=1, grid=[train.BASE_PARAMS], save=False)
    print("seed 0 vs 1, q05 coverage:", a["coverage_val"]["0.05"], c["coverage_val"]["0.05"])
    ab = a["abstention"]
    print(
        "retrain now: tau",
        ab["tau"],
        "abstain",
        round(ab["abstain_rate"], 3),
        "violations",
        ab["violation_rate_with_fallback"],
        "holdout",
        ab["holdout"],
    )


if __name__ == "__main__":
    main()
