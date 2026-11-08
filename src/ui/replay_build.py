# src/ui/replay_build.py
"""Build the replay of the demo period: the station, day by day, before and after our limit.

    python -m src.grid.labels --source "data/raw/ausgrid_full/Solar home 2012-2013.csv" \\
        --scenario A --start 2013-05-01 --days 61 --workers 10 --final-eval
    python -m src.ui.replay_build

Writes ``<ARTIFACT_URI>/replay/index.json``, ``replay/geo.geojson`` and ``replay/days/<date>.json``.
Before is the fixed limit, After is the model's limit (the fixed limit where the model abstains).
Red: the limit is above the safe share, so the station is over what the grid can carry; amber:
not red but the house is capped below what it could export; green: neither; grey: no reading.
"""

import argparse
import json
import math
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

from src.eval.metrics import EPS, FIXED_SHARE, load_profiles, surplus_kw
from src.eval.score_dataset import model_limits
from src.grid.labels import customer_number
from src.ml import dataset, model_io, train
from src.ml import labels as labels_io
from src.ml.config import artifact_uri
from src.ml.split import local_date
from src.ui import geo_build

HOURS = 0.5  # one interval


def policy_block(share, safe, surplus, kwp) -> dict:
    """One policy in one interval. ``surplus`` and ``kwp`` are arrays aligned to the houses."""
    cap = share * kwp
    exported = np.minimum(surplus, cap)
    curtailed = surplus - exported
    missing = np.isnan(surplus)
    violation = bool(share > safe + EPS)
    letters = np.where(missing, "n", np.where(violation, "r", np.where(curtailed > EPS, "a", "g")))
    return {
        "share": round(float(share), 4),
        "violation": violation,
        "status": "".join(letters),
        "export_kw": [None if m else round(float(e), 2) for e, m in zip(exported, missing)],
        "export_total_kw": round(float(np.nansum(exported)), 2),
        "curtailed_total_kw": round(float(np.nansum(curtailed)), 2),
    }


def _summary(intervals: list[dict], key: str) -> dict:
    blocks = [i[key] for i in intervals]
    return {
        "violations": sum(b["violation"] for b in blocks),
        "export_kwh": round(sum(b["export_total_kw"] for b in blocks) * HOURS, 2),
        "curtailed_kwh": round(sum(b["curtailed_total_kw"] for b in blocks) * HOURS, 2),
    }


def day_payload(table, surplus, kwp, fixed=FIXED_SHARE) -> dict[str, dict]:
    """One payload per Sydney date. ``table``: ``safe``, ``fallback``, ``abstain`` by interval.

    ``surplus`` has the same index and one column per house (in station order); ``kwp`` is
    indexed by the same columns. The model's share is its ``fallback`` (fixed where it abstains).
    """
    kwp_values = kwp.reindex(surplus.columns).to_numpy(dtype=float)
    dates = local_date(table.index.to_series()).dt.strftime("%Y-%m-%d")
    out: dict[str, dict] = {}
    for date, part in table.groupby(dates.to_numpy(), sort=True):
        intervals = []
        for start, row in part.iterrows():
            values = surplus.loc[start].to_numpy(dtype=float)
            intervals.append(
                {
                    "t": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "safe": round(float(row["safe"]), 4),
                    "fixed": round(float(fixed), 4),
                    "model": round(float(row["fallback"]), 4),
                    "abstained": bool(row["abstain"]),
                    "surplus_kw": [None if np.isnan(v) else round(float(v), 2) for v in values],
                    "before": policy_block(fixed, row["safe"], values, kwp_values),
                    "after": policy_block(row["fallback"], row["safe"], values, kwp_values),
                }
            )
        out[date] = {
            "date": date,
            "intervals": intervals,
            "summary": {
                "before": _summary(intervals, "before"),
                "after": _summary(intervals, "after"),
            },
        }
    return out


def build_geo(order: list[str], customers: list[dict], per_hood=70, per_node=5) -> dict:
    """GeoJSON for the map: the houses of the station, in station order, in feeders of ``per_hood``.

    ``order`` lists customer numbers (``"109"``). House ``i`` is on feeder ``i // per_hood``, as
    ``src.grid.twin.build_grid`` assigns it. Positions are postcode centroids with the same
    deterministic offsets as ``geo_build``; they never enter the physics.
    """
    by_customer = {r["customer"]: r for r in customers}
    missing = [c for c in order if c not in by_customer]
    if missing:
        raise ValueError(f"no coordinates for customers {missing[:5]}")
    rank_in_code: dict[str, int] = {}
    placed = []
    for i, customer in enumerate(order):
        row = by_customer[customer]
        rank = rank_in_code.get(row["postcode"], 0)
        rank_in_code[row["postcode"]] = rank + 1
        phase = (zlib.crc32(row["postcode"].encode()) % 360) * math.pi / 180
        lat, lon = geo_build._offset(row["lat"], row["lon"], rank, phase)
        hood = f"N{i // per_hood + 1}"
        node = f"{hood}-{(i % per_hood) // per_node + 1}"
        placed.append({**row, "lat": lat, "lon": lon, "group": hood, "node": node})
    features = []
    for hood in sorted({h["group"] for h in placed}):
        members = [h for h in placed if h["group"] == hood]
        code_counts = pd.Series([h["postcode"] for h in members]).value_counts()
        biggest = code_counts.index[0]
        name = next(h["locality"] for h in members if h["postcode"] == biggest) or hood
        nodes: dict[str, list[dict]] = {}
        for h in members:
            nodes.setdefault(h["node"], []).append(h)
        path = [
            [
                round(sum(h["lon"] for h in chunk) / len(chunk), 6),
                round(sum(h["lat"] for h in chunk) / len(chunk), 6),
            ]
            for chunk in nodes.values()
        ]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [geo_build._outline(members)]},
                "properties": {
                    "kind": "neighbourhood",
                    "id": hood,
                    "name": name,
                    "houses": len(members),
                    "kwp": round(sum(h["kwp"] for h in members), 2),
                },
            }
        )
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": path},
                "properties": {"kind": "feeder", "neighbourhood": hood},
            }
        )
        for h in members:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [h["lon"], h["lat"]]},
                    "properties": {
                        "kind": "house",
                        "house_id": h["customer"],
                        "neighbourhood": hood,
                        "node": h["node"],
                        "kwp": h["kwp"],
                        "postcode": h["postcode"],
                        "locality": h["locality"],
                    },
                }
            )
    return {
        "type": "FeatureCollection",
        "meta": {
            "provenance": "assumed",
            "note": "Postcode centroids with deterministic offsets. Not real addresses; "
            "the grid behind the map is synthetic.",
            "houses_per_neighbourhood": per_hood,
            "houses_per_node": per_node,
        },
        "features": features,
    }


VERSION = train.MODEL_VERSION_V2_DATASET
CAUSES = {
    "trafo": "Transformer limit binds: the station cannot take more export than the safe share.",
    "voltage": "Voltage limit binds: a node would leave its voltage band above the safe share.",
    "line": "Line limit binds: a feeder would be overloaded above the safe share.",
    "fixed_too_high": "The fixed limit (36% of each house's kWp) is above the safe share.",
    "model_too_high": "The model's limit is above the safe share: the forecast was too optimistic.",
    "abstained": "The model was not sure (wide spread or failed input check), so the fixed limit "
    "was used, and it is above the safe share.",
    "no_safe_limit": "No safe limit exists in this interval: the power flow did not converge, or "
    "the grid is unsafe even with no export.",
}
NOTES = [
    "Simulated station: 400 kVA transformer, PV scaled x4, synthetic grid. "
    "Positions are postcode centres.",
    "The model was trained without weather, on labels with gaps in the train period.",
    "The twin has no inverter limit: the per-house cap (share x kWp) stands in for it.",
    "One offline run on data the model never saw; the model was not retrained on it. "
    "Scenario A only.",
]


def audit_events(days, binding, surplus, kwp, unsafe_times=()) -> dict:
    """Every interval where a policy broke the safe limit, or no safe limit existed, with causes.

    ``binding`` (voltage, line, trafo or none) comes from the power-flow labels. ``excess_kw`` is
    the export of a policy above what the safe share would have allowed. Counts are per cause.
    """
    kv = kwp.reindex(surplus.columns).to_numpy(dtype=float)
    events, counts = [], {key: 0 for key in CAUSES}
    for date, day in days.items():
        for iv in day["intervals"]:
            if not (iv["before"]["violation"] or iv["after"]["violation"]):
                continue
            start = pd.Timestamp(iv["t"])
            row = surplus.loc[start].to_numpy(dtype=float)
            safe_kw = float(np.nansum(np.minimum(row, iv["safe"] * kv)))
            bind = binding.get(start)
            bind = bind if isinstance(bind, str) and bind in ("trafo", "voltage", "line") else None
            causes = [bind] if bind else []
            if iv["before"]["violation"]:
                causes.append("fixed_too_high")
            if iv["after"]["violation"]:
                causes.append("abstained" if iv["abstained"] else "model_too_high")
            events.append(
                {
                    "t": iv["t"],
                    "date": date,
                    "safe": iv["safe"],
                    "binding": bind,
                    "abstained": iv["abstained"],
                    "causes": causes,
                    **{
                        key: {
                            "violation": iv[key]["violation"],
                            "share": iv[key]["share"],
                            "excess_kw": round(max(0.0, iv[key]["export_total_kw"] - safe_kw), 2),
                        }
                        for key in ("before", "after")
                    },
                }
            )
            for cause in causes:
                counts[cause] += 1
    for start in unsafe_times:
        t = pd.Timestamp(start)
        events.append(
            {
                "t": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "date": str(local_date(pd.Series([t])).dt.strftime("%Y-%m-%d").iloc[0]),
                "safe": None,
                "binding": None,
                "abstained": False,
                "causes": ["no_safe_limit"],
                "before": None,
                "after": None,
            }
        )
        counts["no_safe_limit"] += 1
    events.sort(key=lambda e: e["t"])
    return {"causes": CAUSES, "counts": counts, "events": events}


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def build(scenario="A", version=VERSION, out=None, customers_csv="data/p4/customers.csv") -> dict:
    out = Path(out) if out else Path(artifact_uri()) / "replay"
    labels = labels_io.load(scenario)
    houses = labels_io.load_station_houses(scenario)
    pt_id = labels["pt_id"].iloc[0]
    models, meta = model_io.load(version, pt_id)
    if meta.get("weather", {}).get("used"):
        raise SystemExit("the replay is built for the no-weather version")

    dates = local_date(labels["interval_start"])
    if not (dates >= dataset.DEMO_START).any():
        raise SystemExit("no demo-period labels: run src.grid.labels with --final-eval first")
    rows = train.training_rows(labels)
    row_dates = local_date(rows["interval_start"])
    # replay the offset from the test start so it has learned from March and April, then keep demo
    window = rows[(row_dates >= dataset.TEST_START) & (row_dates <= dataset.DEMO_END)]
    frame, _ = model_limits(models, meta, window)
    frame["safe"] = window["safe_share"].to_numpy()
    demo_dates = local_date(frame.index.to_series())
    frame = frame[(demo_dates >= dataset.DEMO_START) & (demo_dates <= dataset.DEMO_END)]

    parts = [
        surplus_kw(load_profiles(houses, dataset.out_dir() / f"{name}.parquet"), houses)
        for name in ("demo",)
    ]
    surplus = pd.concat(parts).sort_index()
    surplus = surplus.reindex(frame.index)[list(houses["house_id"])]
    kwp = houses.set_index("house_id")["kwp"]

    order = [str(customer_number(s)) for s in houses["source_house_id"]]
    geo = build_geo(order, geo_build.read_customers(customers_csv))
    group = {
        f["properties"]["house_id"]: f["properties"]["neighbourhood"]
        for f in geo["features"]
        if f["properties"]["kind"] == "house"
    }
    days = day_payload(frame[["safe", "fallback", "abstain"]], surplus, kwp)
    for date, payload in days.items():
        _write(out / "days" / f"{date}.json", payload)
    _write(out / "geo.geojson", geo)
    binding = labels.drop_duplicates("interval_start").set_index("interval_start")["binding"]
    unsafe = labels[
        ~labels["converged"] & (local_date(labels["interval_start"]) >= dataset.DEMO_START)
    ]
    _write(
        out / "audit.json",
        audit_events(days, binding, surplus, kwp, unsafe["interval_start"]),
    )

    def total(key, field):
        return round(sum(d["summary"][key][field] for d in days.values()), 2)

    index = {
        "pt_id": pt_id,
        "scenario": scenario,
        "model_version": version,
        "fixed_share": FIXED_SHARE,
        "git_sha": model_io.git_sha(),
        "labels_sha256": model_io.file_sha256(labels_io.labels_path(scenario) / "labels.parquet"),
        "houses": [
            {"id": c, "kwp": round(float(k), 2), "group": group[c]}
            for c, k in zip(order, kwp.reindex(houses["house_id"]))
        ],
        "days": [
            {"date": d, "intervals": len(p["intervals"]), **p["summary"]} for d, p in days.items()
        ],
        "totals": {
            key: {
                "violations": int(total(key, "violations")),
                "export_kwh": total(key, "export_kwh"),
                "curtailed_kwh": total(key, "curtailed_kwh"),
            }
            for key in ("before", "after")
        },
        "notes": NOTES,
    }
    _write(out / "index.json", index)
    return index


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.ui.replay_build")
    parser.add_argument("--scenario", default="A")
    parser.add_argument("--model-version", default=VERSION)
    parser.add_argument("--out", help="default: <ARTIFACT_URI>/replay")
    parser.add_argument("--customers", default="data/p4/customers.csv")
    args = parser.parse_args(argv)
    index = build(args.scenario, args.model_version, args.out, args.customers)
    print(json.dumps(index["totals"], indent=2))
    print(f"{len(index['days'])} days written")


if __name__ == "__main__":
    main()
