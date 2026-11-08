"""Write power-flow labels in the schema the ML side reads (``src/ml/labels.py``).

``generate`` writes ``labels.parquet`` (by default ``DATA_DIR/labels/<scenario>/``) and
``station_houses.parquet`` next to it:

* ``labels.parquet``: one row per daylight half hour, validated with
  ``src.ml.labels.validate`` before it is written;
* ``station_houses.parquet``: the houses of the station with their Ausgrid id in the
  ``AG-0001`` form of ``profiles.parquet``, so evaluation can compute exported energy.

Runs append: a second run into the same folder (another Ausgrid file or day range)
reuses the station's houses and grid settings, adds its intervals and replaces the
ones it computes again, so the file never holds a duplicate interval.
"""

import argparse
import multiprocessing
import os
from pathlib import Path

import numpy as np
import pandas as pd

from src.ml import labels as labels_io
from src.ml.model_io import git_sha
from src.ml.split import TEST_START

from .ausgrid import day_profiles, half_hour_columns, house_readings, read_period, select_households
from .twin import binding_limit, build_grid, null_share_reason, safe_share

STEP = pd.Timedelta(minutes=30)
HOUSES_FILE = "station_houses.parquet"

# Grid settings per scenario (step 00 of docs/tasks/p6-ml-v2.md). Only A is agreed. A is the
# "transformer binds" scenario of docs/04-chosen-idea.md: 400 kVA with PV x4. Measured on three
# summer days (2011-12-19 to 21, 84 daylight intervals each setting), 400 kVA with PV x1 or x2
# gives safe_share = 1 in every interval (nothing binds, a constant target); PV x4 gives 74%
# ones and the transformer binding in 26%. In none of the probed settings did voltage or a line
# bind. TODO(P3 with P2): agree B (a setting where voltage binds, which needs a weaker feeder)
# and B-VAR (B plus reactive-power control, which the twin does not model yet).
SCENARIO_GRID = {
    "A": {"transformer_kva": 400.0, "pv_scale": 4.0},
    "B": None,
    "B-VAR": None,
}

_GRID = None


def scenario_grid(scenario, transformer_kva=None, pv_scale=None):
    """``(transformer_kva, pv_scale)`` of a scenario; explicit values override the mapping."""
    labels_io.pt_id(scenario)  # raises on an unknown scenario
    if scenario == "B-VAR":
        raise ValueError("scenario B-VAR needs reactive-power control, not in the twin yet (TODO)")
    agreed = SCENARIO_GRID[scenario] or {}
    kva = transformer_kva if transformer_kva is not None else agreed.get("transformer_kva")
    scale = pv_scale if pv_scale is not None else agreed.get("pv_scale")
    if kva is None or scale is None:
        raise ValueError(
            f"scenario {scenario} has no agreed grid settings yet (TODO with P3): "
            "pass --transformer-kva and --pv-scale"
        )
    return float(kva), float(scale)


def _init_worker(config):
    """Each process builds its own grid: a pandapower network is not shared across processes."""
    global _GRID
    _GRID = build_grid(config)


def _share(job):
    """Return everything the label row needs, so the parent needs no side list to pair them."""
    share = safe_share(_GRID, job)
    houses = job["houses"]
    row = (
        job["interval_start"],
        share,
        binding_limit(_GRID, job, share),
        sum(h["load_kw"] for h in houses),
        sum(h["pv_kw"] for h in houses),
    )
    return row, None if share is not None else null_share_reason(_GRID, job)


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


def customer_number(house_id: str) -> int:
    """``AG-0003`` -> 3."""
    return int(str(house_id).removeprefix("AG-"))


def label_frame(rows, pt_id, kwp_total, n_houses, source_ref):
    """Rows ``(interval_start, share, binding, load_kw, pv_kw)`` as a validated label table.

    A ``None`` share (no convergence, or unsafe even without export) gets
    ``converged = False``, a null share and a null binding: null, never 0.
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


def station_houses(pt_id, houses, eligible, pv_scale, transformer_kva):
    """The ``station_houses.parquet`` table; ``kwp`` is the scaled capacity the grid uses.

    ``transformer_kva`` is an extra column (the ML side ignores it) so that a later run
    and ``audit_labels`` use the same grid.
    """
    return pd.DataFrame(
        {
            "pt_id": pt_id,
            "house_id": [h["house_id"] for h in houses],
            "source_house_id": [source_house_id(c) for c in eligible],
            "kwp": [h["kwp"] for h in houses],
            "load_scale": 1.0,
            "pv_scale": float(pv_scale),
            "transformer_kva": float(transformer_kva),
        }
    )[[*labels_io.HOUSE_COLUMNS, "transformer_kva"]]


def _earlier_run(output, pt_id, transformer_kva, pv_scale):
    """Labels and houses already in the output folder, checked against this run."""
    houses_file = output.parent / HOUSES_FILE
    if not output.exists():
        if houses_file.exists():
            raise ValueError(f"{houses_file} exists without {output.name}; remove it first")
        return None, None
    if not houses_file.exists():
        raise ValueError(f"{output} exists without {HOUSES_FILE}; remove it or write elsewhere")
    labels = pd.read_parquet(output)
    labels_io.validate(labels)
    if labels_io.is_mock(labels):
        raise ValueError(f"{output} holds mock labels; remove them before writing real ones")
    houses = pd.read_parquet(houses_file)
    found = {
        "pt_id": set(labels["pt_id"]) | set(houses["pt_id"]),
        "pv_scale": set(houses["pv_scale"]),
        "transformer_kva": set(houses.get("transformer_kva", pd.Series([None]))),
    }
    wanted = {"pt_id": {pt_id}, "pv_scale": {pv_scale}, "transformer_kva": {transformer_kva}}
    for key, values in found.items():
        if values != wanted[key]:
            raise ValueError(
                f"{output} was written with {key} {sorted(map(str, values))}, "
                f"this run uses {sorted(map(str, wanted[key]))}; write to another folder"
            )
    return labels, houses


def _merge(old, new):
    """Old labels plus new ones; an interval computed again keeps the new row."""
    if old is None:
        return new, 0
    again = old["interval_start"].isin(new["interval_start"])
    merged = pd.concat([old[~again], new], ignore_index=True)
    merged = merged.sort_values(["pt_id", "interval_start"]).reset_index(drop=True)
    labels_io.validate(merged)
    return merged, int(again.sum())


def check_window(start, days, final_eval=False):
    """Refuse a run that reaches the sealed test year unless it is the final evaluation.

    ``start`` and ``days`` are Sydney local dates, as in the Ausgrid files. The test year
    starts at ``src.ml.split.TEST_START`` (2012-07-01).
    """
    if start is None:
        raise ValueError("start is required")
    end = pd.Timestamp(start) + pd.Timedelta(days=days)  # exclusive
    if end > TEST_START and not final_eval:
        raise ValueError(
            f"{pd.Timestamp(start).date()} + {days} days reaches the sealed test year "
            f"(from {TEST_START.date()}); pass final_eval (--final-eval) only for the "
            "final evaluation"
        )


def generate(
    source,
    output=None,
    start=None,
    days=1,
    transformer_kva=None,
    pv_scale=None,
    workers=1,
    scenario="A",
    final_eval=False,
):
    """Write or extend ``labels.parquet`` at ``output`` and ``station_houses.parquet`` next to it.

    ``output`` defaults to ``DATA_DIR/labels/<scenario>/labels.parquet``, where training
    reads it. ``scenario`` names the station (``PT-A``, ...) and picks its grid settings
    (``SCENARIO_GRID``); ``transformer_kva`` and ``pv_scale`` override them. Results are
    identical for any ``workers`` (order is kept).
    """
    if days < 1:
        raise ValueError("days must be positive")
    check_window(start, days, final_eval)
    if workers < 1:
        raise ValueError("workers must be positive")
    transformer_kva, pv_scale = scenario_grid(scenario, transformer_kva, pv_scale)
    if not 0 < pv_scale < float("inf"):
        raise ValueError("pv_scale must be positive and finite")
    pt_id = labels_io.pt_id(scenario)
    output = (
        Path(output) if output is not None else labels_io.labels_path(scenario) / ("labels.parquet")
    )
    old_labels, old_houses = _earlier_run(output, pt_id, transformer_kva, pv_scale)
    customers = (
        None if old_houses is None else [customer_number(h) for h in old_houses["source_house_id"]]
    )

    frame, cl_customers = read_period(source, start, days)
    hours = half_hour_columns(frame)
    eligible, frame, capacity = select_households(frame, cl_customers, days, customers)
    houses = [{"house_id": str(c), "kwp": float(capacity.loc[c]) * pv_scale} for c in eligible]
    if old_houses is not None and not np.allclose(
        [h["kwp"] for h in houses], old_houses["kwp"].to_numpy(dtype=float)
    ):
        raise ValueError(f"house capacities differ from the earlier run in {output.parent}")
    config = {"houses": houses, "transformer_kva": transformer_kva, "pt_id": pt_id}
    # Build the grid here first: an invalid config raises now, in the parent, instead of
    # making the pool respawn failing workers forever.
    _init_worker(config)
    jobs = _jobs(frame, eligible, hours, pv_scale)
    rows = []
    null_reasons = {"no_convergence": 0, "unsafe_without_export": 0}
    pool = None
    try:
        if workers > 1:
            pool = multiprocessing.get_context("spawn").Pool(
                workers, initializer=_init_worker, initargs=(config,)
            )
            results = pool.imap(_share, jobs, chunksize=4)
        else:
            results = map(_share, jobs)
        for row, reason in results:
            rows.append(row)
            if reason is not None:
                null_reasons[reason] += 1
            if len(rows) % 100 == 0:
                print(f"{len(rows)} labels, up to {row[0]}", flush=True)
    finally:
        if pool:
            pool.terminate()
            pool.join()
    new = label_frame(
        rows,
        pt_id=pt_id,
        kwp_total=sum(h["kwp"] for h in houses),
        n_houses=len(houses),
        source_ref=f"grid/labels.py@{git_sha()}",
    )
    labels, replaced = _merge(old_labels, new)
    output.parent.mkdir(parents=True, exist_ok=True)
    labels.to_parquet(output, index=False)
    station_houses(pt_id, houses, eligible, pv_scale, transformer_kva).to_parquet(
        output.parent / HOUSES_FILE, index=False
    )
    print(
        f"{len(new)} labels computed ({replaced} replaced earlier ones); "
        f"{len(labels)} labels in {output}",
        flush=True,
    )
    # both kinds are written as converged = False and training drops them: count them apart
    print(
        f"null shares: {null_reasons['no_convergence']} power flows did not converge, "
        f"{null_reasons['unsafe_without_export']} unsafe even without export",
        flush=True,
    )
    return null_reasons


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--scenario", default="A", choices=labels_io.SCENARIOS)
    parser.add_argument(
        "--output", help="labels file; default DATA_DIR/labels/<scenario>/labels.parquet"
    )
    parser.add_argument("--start", required=True, help="first Sydney date, e.g. 2011-07-01")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--transformer-kva", type=float, help="default: the scenario's (A: 400)")
    parser.add_argument("--pv-scale", type=float, help="default: the scenario's (A: 1)")
    parser.add_argument(
        "--workers", type=int, default=1, help=f"processes (this machine has {os.cpu_count()})"
    )
    parser.add_argument(
        "--final-eval",
        action="store_true",
        help="allow days from 2012-07-01 on (the sealed test year): final evaluation only",
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
        args.final_eval,
    )
