"""C1, C2, S4: write the real power-flow labels in the schema ``src/ml/labels.py`` reads.

``src/grid/labels.py`` appends dicts with ``safe_cap_share`` and a string time, and keeps
the per-house readings only in memory. This adapter takes those dicts plus the per-house
readings of the same intervals and returns a frame that passes ``labels_io.validate``,
and the matching ``station_houses`` table (house ids in the ``AG-0001`` form of
``profiles.parquet``).
"""

import pandas as pd

from src.ml import labels as labels_io

STEP = pd.Timedelta(minutes=30)


def ausgrid_id(customer) -> str:
    """Grid code uses the raw customer number ("3"); profiles use "AG-0003"."""
    text = str(customer)
    return text if text.startswith("AG-") else f"AG-{int(text):04d}"


def to_ml_labels(
    records: list[dict],
    readings: pd.DataFrame,
    kwp_by_house: dict,
    pt_id: str,
    source_ref: str,
) -> pd.DataFrame:
    """Labels in the ML schema.

    ``records``: the dicts ``src/grid/labels.py`` builds (``interval_start`` ISO string,
    ``safe_cap_share`` float or None, optional ``binding``). ``readings``: one row per
    interval and house with ``interval_start``, ``house_id``, ``load_kw``, ``pv_kw``: the
    inputs of that power flow. A ``None`` share means the power flow did not converge.
    """
    rec = pd.DataFrame(records)
    start = pd.to_datetime(rec["interval_start"], utc=True)
    share = pd.to_numeric(rec["safe_cap_share"], errors="coerce").astype("float64")
    converged = share.notna()
    if "binding" in rec:
        binding = rec["binding"].astype(object)
    else:  # safe_share() does not say which limit binds: only "none" is known for sure
        binding = pd.Series(None, index=rec.index, dtype=object)
        binding[converged & (share >= 1.0)] = "none"
    binding = pd.Series(
        [b if c else None for b, c in zip(binding, converged, strict=True)], dtype=object
    )

    r = readings.assign(interval_start=pd.to_datetime(readings["interval_start"], utc=True))
    totals = r.groupby("interval_start")[["load_kw", "pv_kw"]].sum(min_count=1)
    load = totals["load_kw"].reindex(start).to_numpy()
    pv = totals["pv_kw"].reindex(start).to_numpy()

    out = pd.DataFrame(
        {
            "pt_id": pt_id,
            "interval_start": start.to_numpy(),
            "safe_share": share.to_numpy(),
            "converged": converged.to_numpy(dtype=bool),
            "binding": binding.to_numpy(dtype=object),
            "load_kw": load,
            "pv_kw": pv,
            "net_kw": load - pv,
            "kwp_total": float(sum(kwp_by_house.values())),
            "n_houses": pd.Series(len(kwp_by_house), index=rec.index, dtype="int64"),
            "provenance": "simulated",
            "source_ref": source_ref,
        }
    )
    out["interval_start"] = pd.to_datetime(out["interval_start"], utc=True)
    out["available_at"] = out["interval_start"] + STEP
    out = out[list(labels_io.COLUMNS)].sort_values("interval_start").reset_index(drop=True)
    labels_io.validate(out)
    return out


def station_houses(pt_id: str, kwp_by_house: dict, load_scale=1.0, pv_scale=1.0) -> pd.DataFrame:
    """The ``station_houses.parquet`` the ML side needs for export numbers."""
    ids = list(kwp_by_house)
    return pd.DataFrame(
        {
            "pt_id": pt_id,
            "house_id": [f"H{i + 1:02d}" for i in range(len(ids))],
            "source_house_id": [ausgrid_id(c) for c in ids],
            "kwp": [float(kwp_by_house[c]) for c in ids],
            "load_scale": float(load_scale),
            "pv_scale": float(pv_scale),
        }
    )[list(labels_io.HOUSE_COLUMNS)]
