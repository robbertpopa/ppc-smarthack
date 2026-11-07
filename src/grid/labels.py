import argparse
import multiprocessing
import os

import pandas as pd

from .ausgrid import day_profiles, half_hour_columns, house_readings, read_period, select_households
from .twin import build_grid, safe_share

_GRID = None


def _init_worker(config):
    """Each process builds its own grid: a pandapower network is not shared across processes."""
    global _GRID
    _GRID = build_grid(config)


def _share(injections):
    return safe_share(_GRID, injections)


def generate(source, output, start, days, transformer_kva=400, pv_scale=1.0, workers=1):
    """Write the label file. Results are identical for any ``workers`` (order is kept)."""
    if days < 1:
        raise ValueError("days must be positive")
    if workers < 1:
        raise ValueError("workers must be positive")
    if not 0 < pv_scale < float("inf"):
        raise ValueError("pv_scale must be positive and finite")
    frame, cl_customers = read_period(source, start, days)
    hours = half_hour_columns(frame)
    eligible, frame, capacity = select_households(frame, cl_customers, days)
    houses = [{"house_id": str(c), "kwp": float(capacity.loc[c]) * pv_scale} for c in eligible]
    config = {
        "houses": houses,
        "transformer_kva": transformer_kva,
        "pt_id": f"PT-synthetic-{transformer_kva:g}kVA",
    }
    pt_id = config["pt_id"]
    labels = []
    pool = None
    if workers > 1:
        pool = multiprocessing.get_context("spawn").Pool(
            workers, initializer=_init_worker, initargs=(config,)
        )
    else:
        _init_worker(config)
    try:
        for date, day in frame.groupby("date", sort=True):
            try:
                load, pv = day_profiles(day, eligible, hours)
            except ValueError as exc:
                raise ValueError(f"{exc} on {date}") from exc
            pv = pv * pv_scale
            times, jobs = [], []
            for i in range(48):
                if not 6 <= i / 2 < 20 or pv[i].sum() <= 0:
                    continue
                local = (date + pd.Timedelta(minutes=30 * i)).tz_localize("Australia/Sydney")
                utc = local.tz_convert("UTC").isoformat().replace("+00:00", "Z")
                times.append(utc)
                jobs.append(
                    {"interval_start": utc, "houses": house_readings(eligible, load[i], pv[i])}
                )
            shares = pool.map(_share, jobs) if pool else [_share(job) for job in jobs]
            for utc, share in zip(times, shares, strict=True):
                labels.append(
                    {
                        "pt_id": pt_id,
                        "interval_start": utc,
                        "safe_cap_share": share,
                        "provenance": "simulated",
                        "n_houses": len(houses),
                        "pv_scale": pv_scale,
                        "transformer_kva": transformer_kva,
                        "source": f"Ausgrid 2012-2013; synthetic radial {transformer_kva:g} kVA",
                    }
                )
            print(f"{date.date()}: {len(labels)} labels", flush=True)
    finally:
        if pool:
            pool.terminate()
            pool.join()
    pd.DataFrame(labels).to_parquet(output, index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start", default="2013-01-01")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--transformer-kva", type=float, default=400)
    parser.add_argument("--pv-scale", type=float, default=1)
    parser.add_argument(
        "--workers", type=int, default=1, help=f"processes (this machine has {os.cpu_count()})"
    )
    args = parser.parse_args()
    generate(
        args.source,
        args.output,
        args.start,
        args.days,
        args.transformer_kva,
        args.pv_scale,
        args.workers,
    )
