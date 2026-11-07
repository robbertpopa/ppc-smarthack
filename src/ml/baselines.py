"""Baselines every model is compared with.

Each returns the share of installed kWp applied for the target interval ``T`` when the
decision is taken at ``t = T - 60 min``. ``oracle`` is the safe maximum itself: an upper
bound, not a policy.

| Name                | Rule                                                   |
|---------------------|--------------------------------------------------------|
| fixed               | 0.36 for every interval                                |
| last_known          | safe_share of the interval ending at t, else 0.36      |
| same_hour_yesterday | safe_share at T - 24 h, else 0.36                      |
| oracle              | safe_share at T                                        |

Run ``python -m src.ml.baselines --scenario A`` for a first table on the validation period.
"""

import argparse

import pandas as pd

from src.eval.metrics import FIXED_SHARE, evaluate, surplus_kw
from src.ml import labels as labels_io
from src.ml.config import profiles_path
from src.ml.split import split

NAMES = ("fixed", "last_known", "same_hour_yesterday", "oracle")
HORIZON = pd.Timedelta(minutes=60)
LAST_INTERVAL = HORIZON + pd.Timedelta(minutes=30)  # start of the interval ending at t
DAY = pd.Timedelta(hours=24)


def apply(name: str, labels: pd.DataFrame) -> pd.Series:
    """Share applied to each row of ``labels`` (indexed by ``interval_start``) by a baseline."""
    if name not in NAMES:
        raise ValueError(f"unknown baseline {name!r}, expected one of {NAMES}")
    start = pd.DatetimeIndex(labels["interval_start"])
    known = pd.Series(labels["safe_share"].to_numpy(), index=start)
    if name == "fixed":
        values = pd.Series(FIXED_SHARE, index=start)
    elif name == "last_known":
        values = known.reindex(start - LAST_INTERVAL).set_axis(start).fillna(FIXED_SHARE)
    elif name == "same_hour_yesterday":
        values = known.reindex(start - DAY).set_axis(start).fillna(FIXED_SHARE)
    else:
        values = known
    return values.rename_axis("interval_start")


def table(labels, surplus, kwp, part=None, names=NAMES) -> pd.DataFrame:
    """One row per baseline with the metrics of ``evaluate``.

    Baselines are computed on the full ``labels`` (they need yesterday and the last
    interval) and scored on ``part``, for example the validation rows.
    """
    part = labels if part is None else part
    rows = {name: evaluate(apply(name, labels), part, surplus, kwp) for name in names}
    return pd.DataFrame(rows).T[["export_index", "violation_rate", "n_intervals", "n_null_label"]]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.ml.baselines")
    parser.add_argument("--scenario", default="A", choices=labels_io.SCENARIOS)
    parser.add_argument("--split", default="val", choices=("train", "val"))
    args = parser.parse_args(argv)

    labels = labels_io.load(args.scenario)
    houses = labels_io.load_station_houses(args.scenario)
    surplus = surplus_kw(pd.read_parquet(profiles_path()), houses)
    kwp = houses.set_index("house_id")["kwp"]
    part = split(labels)[args.split]
    note = "MOCK labels, not a result" if labels_io.is_mock(labels) else "real labels"
    print(f"baselines on {args.split} ({note}), fixed limit = 100")
    print(table(labels, surplus, kwp, part).round(4).to_string())


if __name__ == "__main__":
    main()
