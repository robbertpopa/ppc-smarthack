import argparse
from pathlib import Path

import pandas as pd

from .ausgrid import day_profiles, half_hour_columns, house_readings, read_period, select_households
from .twin import build_grid, limit_violations, solve


def audit(source, labels_dir, transformer_kva=400):
    """Re-solve sampled boundary labels of a ``generate`` output folder.

    ``transformer_kva`` must be the value the labels were generated with.
    """
    labels_dir = Path(labels_dir)
    labels = pd.read_parquet(labels_dir / "labels.parquet")
    houses = pd.read_parquet(labels_dir / "station_houses.parquet")
    if labels.empty or labels[["pt_id", "interval_start"]].duplicated().any():
        raise ValueError("Labels are empty or contain duplicate intervals")
    if houses.pv_scale.nunique() != 1:
        raise ValueError("Expected one consistent scenario")
    scale = float(houses.pv_scale.iloc[0])
    local = pd.to_datetime(labels.interval_start, utc=True).dt.tz_convert("Australia/Sydney")
    days_local = local.dt.tz_localize(None).dt.normalize()
    start, days = days_local.min(), (days_local.max() - days_local.min()).days + 1
    frame, cl_customers = read_period(source, start, days)
    hours = half_hour_columns(frame)
    eligible, frame, capacity = select_households(frame, cl_customers, days)
    grid = build_grid(
        {
            "houses": [
                {"house_id": str(c), "kwp": float(capacity.loc[c]) * scale} for c in eligible
            ],
            "transformer_kva": float(transformer_kva),
        }
    )
    boundary = labels[labels.safe_share.notna() & (labels.safe_share < 0.998)]
    if boundary.empty:
        raise ValueError("No finite boundary labels available to audit")
    samples = boundary.sample(n=min(12, len(boundary)), random_state=42)
    for row in samples.itertuples(index=False):
        t = pd.Timestamp(row.interval_start).tz_convert("Australia/Sydney")
        day = frame[frame.date == t.tz_localize(None).normalize()]
        load, pv = day_profiles(day, eligible, hours)
        slot = t.hour * 2 + t.minute // 30
        houses = house_readings(eligible, load[slot], pv[slot] * scale)
        for share, expected in (
            (row.safe_share, True),
            (min(1, row.safe_share + 0.002), False),
        ):
            reading = {
                "interval_start": row.interval_start,
                "houses": [
                    {**h, "export_limit_kw": share * grid.houses[h["house_id"]]["kwp"]}
                    for h in houses
                ],
            }
            state = solve(grid, reading)
            if not state["converged"]:
                raise AssertionError(f"{row.interval_start}: did not converge")
            if (not limit_violations(grid, state)) != expected:
                raise AssertionError(
                    f"{row.interval_start}: unexpected safety at {share:.4f}, state={state}"
                )
    print(
        f"{len(samples)} sampled boundaries passed at the label and failed 0.002 above; "
        f"{len(labels)} labels checked for duplicate times"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--labels", required=True, help="folder written by src.grid.labels")
    parser.add_argument("--transformer-kva", type=float, default=400)
    args = parser.parse_args()
    audit(args.source, args.labels, args.transformer_kva)
