"""Write power-flow labels in the schema the ML side reads (``src/ml/labels.py``).

``generate`` writes two files into ``output`` (for training, ``DATA_DIR/labels/<scenario>``):

* ``labels.parquet``: one row per daylight half hour, validated with
  ``src.ml.labels.validate`` before it is written;
* ``station_houses.parquet``: the houses of the station with their Ausgrid id in the
  ``AG-0001`` form of ``profiles.parquet``, so evaluation can compute exported energy.
"""

import argparse
import multiprocessing
import os
from pathlib import Path

import numpy as np
import pandas as pd

from src.ml import labels as labels_io
from src.ml.model_io import git_sha

from .ausgrid import day_profiles, half_hour_columns, house_readings, read_period, select_households
from .twin import binding_limit, build_grid, safe_share

STEP = pd.Timedelta(minutes=30)
_GRID = None


def _init_worker(config):
    """Each process builds its own grid: a pandapower network is not shared across processes."""
    global _GRID
    _GRID = build_grid(config)


def _share(job):
    """Return everything the label row needs, so the parent needs no side list to pair them."""
    share = safe_share(_GRID, job)
    houses = job["houses"]
    return (
        job["interval_start"],
        share,
        binding_limit(_GRID, job, share),
        sum(h["load_kw"] for h in houses),
        sum(h["pv_kw"] for h in houses),
    )


def _jobs(frame, eligible, hours, pv_scale):
    """Yield one power-flow job per daylight interval, day after day, in time order.

    The generator is lazy: with a pool, the parent prepares the next day while the workers
    are still busy, and only a few days of readings are in memory at once.
    """
    for date, day in frame.groupby("date", sort=True):
        try:
            load, pv = day_profiles(day, eligible, hours)
        except ValueError as exc:
            raise ValueError(f"{exc} on {date}") from exc
        pv = pv * pv_scale
        for i in range(48):
            if not 6 <= i / 2 < 20 or pv[i].sum() <= 0:
                continue
            local = (date + pd.Timedelta(minutes=30 * i)).tz_localize("Australia/Sydney")
            utc = local.tz_convert("UTC").isoformat().replace("+00:00", "Z")
            yield {"interval_start": utc, "houses": house_readings(eligible, load[i], pv[i])}


def source_house_id(customer) -> str:
    """Ausgrid customer number as ``profiles.parquet`` writes it: 3 -> ``AG-0003``."""
    return f"AG-{int(customer):04d}"


def label_frame(rows, pt_id, kwp_total, n_houses, source_ref):
    """Rows ``(interval_start, share, binding, load_kw, pv_kw)`` as a validated label table.

    A ``None`` share (no convergence, or unsafe even without export) gets
    ``converged = False``, a null share and a null binding.
    """
    rows = list(rows)
    start = pd.Series(pd.to_datetime([r[0] for r in rows], utc=True))
    share = pd.Series([np.nan if r[1] is None else float(r[1]) for r in rows], dtype="float64")
    converged = share.notna()
    load = pd.Series([r[3] for r in rows], dtype="float64")
    pv = pd.Series([r[4] for r in rows], dtype="float64")
    frame = pd.DataFrame(
        {
            "pt_id": pd.Series(pt_id, index=share.index, dtype="object"),
            "interval_start": start,
            "safe_share": share,
            "converged": converged.astype(bool),
            "binding": pd.Series(
                [b if c else None for (_, _, b, _, _), c in zip(rows, converged, strict=True)],
                index=share.index,
                dtype="object",
            ),
            "load_kw": load,
            "pv_kw": pv,
            "net_kw": load - pv,
            "kwp_total": pd.Series(float(kwp_total), index=share.index, dtype="float64"),
            "n_houses": pd.Series(n_houses, index=share.index, dtype="int64"),
            "available_at": start + STEP,
            "provenance": pd.Series("simulated", index=share.index, dtype="object"),
            "source_ref": pd.Series(source_ref, index=share.index, dtype="object"),
        }
    )[list(labels_io.COLUMNS)]
    labels_io.validate(frame)
    return frame


def station_houses(pt_id, houses, eligible, pv_scale):
    """The ``station_houses.parquet`` table; ``kwp`` is the scaled capacity the grid uses."""
    return pd.DataFrame(
        {
            "pt_id": pt_id,
            "house_id": [h["house_id"] for h in houses],
            "source_house_id": [source_house_id(c) for c in eligible],
            "kwp": [h["kwp"] for h in houses],
            "load_scale": 1.0,
            "pv_scale": float(pv_scale),
        }
    )[list(labels_io.HOUSE_COLUMNS)]


def generate(
    source, output, start, days, transformer_kva=400, pv_scale=1.0, workers=1, scenario="A"
):
    """Write ``labels.parquet`` and ``station_houses.parquet`` into the ``output`` folder.

    Results are identical for any ``workers`` (order is kept). ``scenario`` names the
    station (``PT-A``, ``PT-B``, ``PT-B-VAR``) as the ML side and the agent expect it.
    """
    if days < 1:
        raise ValueError("days must be positive")
    if workers < 1:
        raise ValueError("workers must be positive")
    if not 0 < pv_scale < float("inf"):
        raise ValueError("pv_scale must be positive and finite")
    pt_id = labels_io.pt_id(scenario)
    frame, cl_customers = read_period(source, start, days)
    hours = half_hour_columns(frame)
    eligible, frame, capacity = select_households(frame, cl_customers, days)
    houses = [{"house_id": str(c), "kwp": float(capacity.loc[c]) * pv_scale} for c in eligible]
    config = {"houses": houses, "transformer_kva": transformer_kva, "pt_id": pt_id}
    # Build the grid here first: an invalid config raises now, in the parent, instead of
    # making the pool respawn failing workers forever.
    _init_worker(config)
    jobs = _jobs(frame, eligible, hours, pv_scale)
    rows = []
    pool = None
    try:
        if workers > 1:
            pool = multiprocessing.get_context("spawn").Pool(
                workers, initializer=_init_worker, initargs=(config,)
            )
            results = pool.imap(_share, jobs, chunksize=4)
        else:
            results = map(_share, jobs)
        for row in results:
            rows.append(row)
            if len(rows) % 100 == 0:
                print(f"{len(rows)} labels, up to {row[0]}", flush=True)
    finally:
        if pool:
            pool.terminate()
            pool.join()
    labels = label_frame(
        rows,
        pt_id=pt_id,
        kwp_total=sum(h["kwp"] for h in houses),
        n_houses=len(houses),
        source_ref=f"grid/labels.py@{git_sha()}",
    )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    labels.to_parquet(output / "labels.parquet", index=False)
    station_houses(pt_id, houses, eligible, pv_scale).to_parquet(
        output / "station_houses.parquet", index=False
    )
    print(f"{len(labels)} labels written to {output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument(
        "--output", required=True, help="folder for both files, e.g. DATA_DIR/labels/A"
    )
    parser.add_argument("--scenario", default="A", choices=labels_io.SCENARIOS)
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
        args.scenario,
    )
