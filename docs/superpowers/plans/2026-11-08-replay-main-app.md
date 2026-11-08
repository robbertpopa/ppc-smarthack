# Replay Main App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Project rule for this repo:** do not commit, push or run any Azure action unless the user asks. Where a step would normally commit, run the checkpoint command instead (tests plus `ruff check`), and stop there.

**Goal:** Make a replay of the demo period (2013-05-01 to 2013-06-30) the main page of the app: the 210 station houses on the existing map, by day and half hour, with two views, Before (fixed 36% limit) and After (our dynamic limit).

**Architecture:** An offline build (`src/ui/replay_build.py`) turns the power-flow truth for the demo period and the trained `safe-cap-qgb-v2-dataset` model into one JSON per day plus an index and a GeoJSON, under `ARTIFACT_URI/replay/`. The UI server serves those files read-only and serves a new `replay.html` at `/`; the old operator screen moves to `/operator`. The page plays the replay with the existing `map.js` module.

**Tech Stack:** Python 3.12, pandas, FastAPI (existing `src/ui/app.py`), plain HTML/JS with the existing `window.StationMap` module, pytest, ruff.

Spec: `docs/superpowers/specs/2026-11-08-replay-main-app-design.md`.

## Facts the tasks rely on (checked 2026-11-08)

* Labels for scenario A live in `data/labels/A/` (station `PT-A`, 210 houses, `pv_scale` 4, 400 kVA). Demo labels do not exist yet.
* All 61 demo days have complete rows for the 210 houses, so one `src.grid.labels` call covers them. `src.grid.labels.check_window` allows it only with `--final-eval` (sealed from 2013-03-01).
* Model: `model_io.load("safe-cap-qgb-v2-dataset", "PT-A")` returns `(models, meta)`. `meta` has `features`, `abstention{tau, reachable}`, `offset{gamma, alpha, c_start}`.
* Surplus per house and interval: `surplus_kw(load_profiles(houses, path), houses)` with `path` `data/prepared/dataset/{test,demo}.parquet`; columns are the simulated ids (`H01`...), `kwp` from `houses.set_index("house_id")["kwp"]` already includes the PV scale.
* The map module (`src/ui/static/map/map.js`) takes `StationMap.mount(el, {geo, select})` and `update(view)`; house `status` is `ok | review | blocked | none` (green, amber, red, grey). GeoJSON features: `neighbourhood` (Polygon), `feeder` (LineString), `house` (Point with `house_id`, `neighbourhood`, `node`).
* The twin assigns house `i` to feeder `i // 70` (3 feeders), 5 houses per node.
* `src.eval.metrics` exports `EPS` and `FIXED_SHARE` (0.36). A violation is `applied_share > safe_share + EPS`.
* `src/eval/score_dataset.py` already contains the model-limit logic inline; Task 1 extracts it so the replay and the test scorer share one copy.
* Online offset: replay it continuously from 2013-03-01 (the test start) with `c_start`, so by 2013-05-01 it has learned from March and April labels as they became known. The model itself is not retrained.

## File structure

| File | Responsibility |
|---|---|
| `src/eval/score_dataset.py` (modify) | Add `model_limits(models, meta, rows)`; `score()` calls it. |
| `src/ui/replay_build.py` (create) | `policy_block`, `day_payload`, `build_geo`, `build`, CLI. Pure functions first, IO last. |
| `src/ui/app.py` (modify) | Routes `/`, `/operator`, `/replay/index`, `/replay/geo`, `/replay/day/<date>`. |
| `src/ui/static/replay.html` (create) | The page. |
| `tests/eval/test_score_dataset.py` (create) | `model_limits`. |
| `tests/test_ui_replay_build.py` (create) | `policy_block`, `day_payload`, `build_geo`. |
| `tests/test_ui_replay_routes.py` (create) | The new routes. |
| `tests/test_ui_app.py` (modify) | `/` assertions move to `/operator`. |

---

### Task 1: Extract `model_limits` from the test scorer

**Files:**
- Modify: `src/eval/score_dataset.py`
- Create: `tests/eval/test_score_dataset.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/eval/test_score_dataset.py
import numpy as np
import pandas as pd

from src.eval.metrics import FIXED_SHARE
from src.eval.score_dataset import model_limits
from src.ml import features, train
from src.ml import labels as labels_io


class Constant:
    def __init__(self, value):
        self.value = value

    def predict(self, X):
        return np.full(len(X), self.value)


def rows():
    return train.training_rows(labels_io.make_mock(None, "A")).iloc[2000:2200]


def meta(tau):
    return {
        "features": features.FEATURES,
        "abstention": {"tau": tau, "reachable": True},
        "offset": {"gamma": 0.01, "alpha": 0.02, "c_start": 0.0},
    }


def models():
    return {q: Constant(v) for q, v in zip(train.QUANTILES, (0.2, 0.25, 0.3, 0.5, 0.9))}


def test_a_wide_spread_abstains_and_falls_back_to_the_fixed_limit():
    frame, pred = model_limits(models(), meta(tau=0.5), rows())  # spread 0.7 > 0.5
    assert frame["abstain"].all()
    assert (frame["fallback"] == FIXED_SHARE).all()
    assert pred.shape == (len(frame), 5)


def test_without_abstention_the_fallback_is_the_offset_limit():
    frame, _ = model_limits(models(), meta(tau=0.9), rows())  # spread 0.7 <= 0.9
    kept = ~frame["abstain"]
    assert kept.any()
    assert (frame.loc[kept, "fallback"] == frame.loc[kept, "limit"]).all()
    assert frame.index.is_monotonic_increasing
    assert isinstance(frame.index, pd.DatetimeIndex)
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/pytest tests/eval/test_score_dataset.py -q`
Expected: FAIL with `ImportError: cannot import name 'model_limits'`.

- [ ] **Step 3: Implement**

In `src/eval/score_dataset.py`, add above `score()`:

```python
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
```

Then make `score()` use it. Replace the block from `pred = train.predict_quantiles(...)` down to `fallback = limit.where(~abstain, FIXED_SHARE)` with:

```python
    frame, pred = model_limits(models, meta, test_rows)
    index = frame.index
    q05, spread = frame["q05"], frame["spread"]
    abstain, limit, fallback = frame["abstain"], frame["limit"], frame["fallback"]
```

and delete the now unused local `info`, `tau`, `flagged`, `offset`, `replayed` lines in `score()`.

- [ ] **Step 4: Run tests and lint**

Run: `.venv/bin/pytest tests/eval/test_score_dataset.py -q && .venv/bin/ruff check src/eval tests/eval`
Expected: `2 passed`, `All checks passed!`.

Do not call `score()` again on real data: the test period was scored once for each version. The refactor is covered by the unit tests only.

- [ ] **Step 5: Checkpoint**

Run: `.venv/bin/ruff format src/eval/score_dataset.py tests/eval/test_score_dataset.py` (only these two files, never `src` as a whole).

---

### Task 2: `policy_block` and `day_payload` (pure functions)

**Files:**
- Create: `src/ui/replay_build.py`
- Create: `tests/test_ui_replay_build.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ui_replay_build.py
import numpy as np
import pandas as pd

from src.ui.replay_build import day_payload, policy_block


def test_a_share_above_the_safe_share_marks_every_reading_house_red():
    block = policy_block(0.5, 0.4, np.array([1.0, 2.0, np.nan]), np.array([4.0, 4.0, 4.0]))
    assert block["violation"] is True
    assert block["status"] == "rrn"


def test_a_house_capped_below_its_surplus_is_amber_and_the_rest_green():
    surplus = np.array([3.0, 0.5])
    block = policy_block(0.36, 0.9, surplus, np.array([5.0, 5.0]))  # caps 1.8 and 1.8
    assert block["violation"] is False
    assert block["status"] == "ag"
    assert block["export_kw"] == [1.8, 0.5]
    assert block["export_total_kw"] == 2.3
    assert block["curtailed_total_kw"] == 1.2


def test_a_missing_reading_is_not_counted_as_export():
    block = policy_block(0.5, 0.9, np.array([np.nan, 2.0]), np.array([4.0, 4.0]))
    assert block["export_kw"] == [None, 2.0]
    assert block["export_total_kw"] == 2.0


def test_day_payload_groups_by_sydney_date_and_summarises_both_policies():
    times = pd.DatetimeIndex(
        ["2013-05-01T00:00Z", "2013-05-01T00:30Z", "2013-05-01T23:00Z"], name="interval_start"
    )  # the last one is 2013-05-02 09:00 in Sydney
    table = pd.DataFrame(
        {"safe": [0.9, 0.2, 0.9], "fallback": [0.6, 0.6, 0.6], "abstain": [False, False, True]},
        index=times,
    )
    surplus = pd.DataFrame({"H01": [2.0, 2.0, 2.0], "H02": [0.5, 0.5, 0.5]}, index=times)
    kwp = pd.Series({"H01": 5.0, "H02": 5.0})
    days = day_payload(table, surplus, kwp, fixed=0.36)
    assert sorted(days) == ["2013-05-01", "2013-05-02"]
    first = days["2013-05-01"]
    assert len(first["intervals"]) == 2
    assert first["intervals"][0]["after"]["status"] == "gg"
    assert first["intervals"][1]["after"]["violation"] is True
    assert first["intervals"][1]["before"]["violation"] is True  # 0.36 > 0.2
    assert first["summary"]["after"]["violations"] == 1
    # an abstained interval uses the fixed limit in both views
    assert days["2013-05-02"]["intervals"][0]["after"]["share"] == 0.36
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/pytest tests/test_ui_replay_build.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.ui.replay_build'`.

- [ ] **Step 3: Implement**

```python
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
            "summary": {"before": _summary(intervals, "before"), "after": _summary(intervals, "after")},
        }
    return out
```

- [ ] **Step 4: Run tests and lint**

Run: `.venv/bin/pytest tests/test_ui_replay_build.py -q && .venv/bin/ruff check src/ui tests/test_ui_replay_build.py`
Expected: `4 passed`, `All checks passed!`. If `ruff` reports unused imports (`argparse`, `json`, ...), leave them: Task 4 uses them. Do not run `ruff --fix` yet.

---

### Task 3: `build_geo` for the 210 station houses

**Files:**
- Modify: `src/ui/replay_build.py`
- Modify: `tests/test_ui_replay_build.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ui_replay_build.py`:

```python
from src.ui.replay_build import build_geo


def customers():
    rows = []
    for n in range(1, 13):
        rows.append(
            {
                "customer": str(n),
                "kwp": 4.0,
                "postcode": "2076" if n % 2 else "2259",
                "lat": -33.7 if n % 2 else -33.2,
                "lon": 151.1 + n / 100,
                "locality": "Normanhurst" if n % 2 else "Alison",
            }
        )
    return rows


def test_houses_are_split_into_feeders_in_station_order():
    order = [str(n) for n in range(1, 13)]
    geo = build_geo(order, customers(), per_hood=6, per_node=3)
    kinds = [f["properties"]["kind"] for f in geo["features"]]
    assert kinds.count("neighbourhood") == 2
    assert kinds.count("feeder") == 2
    assert kinds.count("house") == 12
    houses = {
        f["properties"]["house_id"]: f["properties"]
        for f in geo["features"]
        if f["properties"]["kind"] == "house"
    }
    assert houses["1"]["neighbourhood"] == "N1" and houses["6"]["neighbourhood"] == "N1"
    assert houses["7"]["neighbourhood"] == "N2" and houses["12"]["neighbourhood"] == "N2"
    assert houses["1"]["node"] == "N1-1" and houses["4"]["node"] == "N1-2"
    assert geo["meta"]["provenance"] == "assumed"


def test_a_house_without_coordinates_is_an_error():
    import pytest

    with pytest.raises(ValueError, match="no coordinates"):
        build_geo(["1", "99"], customers(), per_hood=2, per_node=1)
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/pytest tests/test_ui_replay_build.py -q`
Expected: FAIL, `ImportError: cannot import name 'build_geo'`.

- [ ] **Step 3: Implement** (append to `src/ui/replay_build.py`)

```python
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
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/test_ui_replay_build.py -q`
Expected: `6 passed`.

---

### Task 4: `build()`, CLI, demo labels, first real build

**Files:**
- Modify: `src/ui/replay_build.py`

- [ ] **Step 1: Add `build()` and the CLI** (append)

```python
VERSION = train.MODEL_VERSION_V2_DATASET
NOTES = [
    "Simulated station: 400 kVA transformer, PV scaled x4, synthetic grid. Positions are postcode centres.",
    "The model was trained without weather, on labels with gaps in the train period.",
    "The twin has no inverter limit: the per-house cap (share x kWp) stands in for it.",
    "One offline run on data the model never saw; the model was not retrained on it. Scenario A only.",
]


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
        "days": [{"date": d, "intervals": len(p["intervals"]), **p["summary"]} for d, p in days.items()],
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
```

- [ ] **Step 2: Lint**

Run: `.venv/bin/ruff check src/ui tests/test_ui_replay_build.py && .venv/bin/ruff format src/ui/replay_build.py tests/test_ui_replay_build.py`
Expected: `All checks passed!`. Fix any real issue (long lines in `NOTES` may need wrapping); do not format other files.

- [ ] **Step 3: Generate the demo-period labels** (about a minute, 61 days, 10 workers)

Tell the user first; this is the first read of the demo period. Run in the background if it is slow.

Run:
```bash
cp data/labels/A/labels.parquet /tmp/labels_before_demo.parquet
.venv/bin/python -W ignore -m src.grid.labels --source "data/raw/ausgrid_full/Solar home 2012-2013.csv" --scenario A --start 2013-05-01 --days 61 --workers 10 --final-eval
```
Expected: `... labels computed (0 replaced earlier ones)`, and the null-share line. If it fails with "station customers lack complete rows", stop and report: the 61-day completeness check in the spec assumed all 210 houses are complete.

- [ ] **Step 4: Build the replay**

Run: `.venv/bin/python -W ignore -m src.ui.replay_build --out artifacts/replay`
Expected: a `totals` JSON for `before` and `after`, then `61 days written`. Look at the totals and report them as they are.

- [ ] **Step 5: Sanity-check the output**

Run:
```bash
.venv/bin/python - <<'EOF'
import json, pathlib
r = pathlib.Path("artifacts/replay")
i = json.loads((r / "index.json").read_text())
d = json.loads((r / "days" / "2013-05-15.json").read_text())
iv = d["intervals"][len(d["intervals"]) // 2]
assert len(iv["before"]["status"]) == len(i["houses"]) == 210
print(len(i["days"]), "days;", sum(x["intervals"] for x in i["days"]), "intervals")
print("size of one day:", (r / "days" / "2013-05-15.json").stat().st_size // 1024, "KB")
print(iv["t"], "safe", iv["safe"], "model", iv["model"], iv["after"]["status"][:20])
EOF
```
Expected: 61 days, a day file well under 300 KB, and 210 characters per status string.

---

### Task 5: Routes: replay at `/`, operator at `/operator`

**Files:**
- Modify: `src/ui/app.py`
- Create: `tests/test_ui_replay_routes.py`
- Modify: `tests/test_ui_app.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ui_replay_routes.py
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from src.common.config import Settings
from src.ui.app import create_app


class ReplayRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = TestClient(create_app(Settings(artifact_uri=self.tmp.name)))

    def write(self, name, text):
        path = Path(self.tmp.name) / "replay" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_root_is_the_replay_page_and_operator_is_the_old_screen(self):
        root = self.client.get("/").text
        for needle in ('id="mapHost"', "window.StationMap", "/replay/index", "Before", "After"):
            self.assertIn(needle, root)
        self.assertIn("Station operator screen", self.client.get("/operator").text)

    def test_not_built_gives_404(self):
        for path in ("/replay/index", "/replay/geo", "/replay/day/2013-05-01"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404)
            self.assertFalse(response.json()["available"])

    def test_files_are_served_as_written(self):
        self.write("index.json", json.dumps({"pt_id": "PT-A"}))
        self.write("geo.geojson", json.dumps({"type": "FeatureCollection", "features": []}))
        self.write("days/2013-05-01.json", json.dumps({"date": "2013-05-01"}))
        self.assertEqual(self.client.get("/replay/index").json()["pt_id"], "PT-A")
        self.assertEqual(self.client.get("/replay/geo").json()["type"], "FeatureCollection")
        self.assertEqual(self.client.get("/replay/day/2013-05-01").json()["date"], "2013-05-01")

    def test_a_malformed_date_is_refused_and_cannot_escape(self):
        self.write("index.json", "{}")
        for bad in ("2013-5-1", "..", "2013-05-01.json", "../index"):
            self.assertIn(self.client.get(f"/replay/day/{bad}").status_code, (404, 422))

    def test_an_unreadable_file_is_a_502(self):
        self.write("index.json", "{not json")
        self.assertEqual(self.client.get("/replay/index").status_code, 502)
```

In `tests/test_ui_app.py`, change the three places that fetch the operator page from `"/"` to `"/operator"`:
`test_pages_are_served` (`client.get("/")` -> `client.get("/operator")`),
`test_the_page_has_the_map_slot_and_keeps_the_simulation_notice` (`.get("/")` -> `.get("/operator")`),
`test_screen_has_the_prices_tab_and_panel` (`.get("/")` -> `.get("/operator")`).

- [ ] **Step 2: Run to see failures**

Run: `.venv/bin/pytest tests/test_ui_replay_routes.py tests/test_ui_app.py -q`
Expected: the new tests FAIL (no `/operator`, no replay routes); the updated `test_ui_app` tests FAIL on `/operator` 404.

- [ ] **Step 3: Implement** in `src/ui/app.py`

Add near the other constants: `DAY_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")`.

Change the index route and add the new ones inside `create_app` (after the `/simulation` route):

```python
    @app.get("/")
    def index():
        return FileResponse(STATIC / "replay.html")

    @app.get("/operator")
    def operator():
        return FileResponse(STATIC / "index.html")

    replay_dir = Path(settings.artifact_uri) / "replay"

    def replay_file(path: Path):
        if not path.is_file():
            return JSONResponse({"available": False}, status_code=404)
        try:
            return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            raise HTTPException(status_code=502, detail=f"{path.name} is unreadable") from None

    @app.get("/replay/index")
    def replay_index():
        return replay_file(replay_dir / "index.json")

    @app.get("/replay/geo")
    def replay_geo():
        return replay_file(replay_dir / "geo.geojson")

    @app.get("/replay/day/{date}")
    def replay_day(date: str):
        if not DAY_DATE.fullmatch(date):
            raise HTTPException(status_code=422, detail="date must look like 2013-05-01")
        return replay_file(replay_dir / "days" / f"{date}.json")
```

(Delete the old `index()` route that returned `index.html`.)

- [ ] **Step 4: Create a minimal `src/ui/static/replay.html`** so the root test can pass now. Task 6 replaces it. Content for now:

```html
<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Replay</title></head>
<body><div id="mapHost"></div><p>Before After /replay/index window.StationMap</p></body></html>
```

- [ ] **Step 5: Run tests and lint**

Run: `.venv/bin/pytest tests/test_ui_replay_routes.py tests/test_ui_app.py -q && .venv/bin/ruff check src/ui tests`
Expected: all pass (the `.json` and `../index` cases return 404 or 422).

---

### Task 6: The replay page

**Files:**
- Modify (replace): `src/ui/static/replay.html`

- [ ] **Step 1: Write the page.** Full content:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PPC: the grid, before and after our limit</title>
<style>
:root{--bg:#fbfbf9;--ink:#17191c;--on-ink:#fff;--muted:#656a70;--line:#e6e6e1;--line2:#c9c9c2;--soft:#f1f1ed;--ok:#2f7d5b;--rev:#c98600;--revtext:#8a5300;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#111314;--ink:#ececea;--on-ink:#111314;--muted:#9aa0a6;--line:#262a2d;--line2:#3a3f43;--soft:#1b1e20;--ok:#4aa37e;--rev:#e0a93b;--revtext:#e0b45c;--bad:#e5645a}}
*{box-sizing:border-box}
body{font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:var(--bg);margin:0;padding:0 0 48px;line-height:1.5;font-variant-numeric:tabular-nums}
.wrap{max-width:1240px;margin:0 auto;padding:0 24px}
h1,h2,p{margin:0}
.muted{color:var(--muted)}.sub{color:var(--muted);font-size:.85rem}
button,input{font:inherit;color:inherit}
button{min-height:44px;padding:0 18px;border-radius:8px;border:1px solid var(--ink);background:var(--ink);color:var(--on-ink);font-weight:500;cursor:pointer}
button.line{background:transparent;color:var(--ink);border-color:var(--line2)}
button[aria-pressed="true"]{outline:3px solid var(--rev);outline-offset:1px}
button:focus-visible,input:focus-visible{outline:3px solid var(--rev);outline-offset:2px}
input[type=date],select{padding:8px 10px;border:1px solid var(--line2);border-radius:8px;background:var(--bg);min-height:44px;font:inherit}
header{border-bottom:1px solid var(--line)}
header .wrap{display:flex;flex-wrap:wrap;gap:8px 24px;align-items:baseline;justify-content:space-between;padding-top:16px;padding-bottom:16px}
.tag{color:var(--revtext);font-weight:500;font-size:.9rem}
.err{color:var(--bad);font-weight:500;padding-top:12px}.err:empty{display:none}
.bar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:18px 0}
.views{display:flex;gap:8px}
.grid{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(300px,1fr);gap:24px;align-items:start}
@media (max-width:900px){.grid{grid-template-columns:1fr}}
.mapbox{height:540px;border:1px solid var(--line2);border-radius:10px;position:relative;overflow:hidden}
.card{border:1px solid var(--line);border-radius:10px;padding:16px}
.state{display:flex;gap:10px;align-items:center;font-size:1.3rem;font-weight:500}
.dot{display:inline-block;width:12px;height:12px;border-radius:99px;background:var(--line2)}
.dot.ok{background:var(--ok)}.dot.bad{background:var(--bad)}
.meter{position:relative;height:14px;background:var(--soft);border-radius:8px;margin:14px 0 6px}
.meter i{position:absolute;top:-4px;width:3px;height:22px;background:var(--ink)}
.meter b{position:absolute;top:0;left:0;height:14px;border-radius:8px;background:var(--ok);opacity:.55}
table{border-collapse:collapse;width:100%;font-size:.92rem}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}th:first-child,td:first-child{text-align:left}
th{font-weight:500;color:var(--muted)}
td.bad{color:var(--bad);font-weight:500}td.good{color:var(--ok);font-weight:500}
svg{width:100%;display:block}
.strip{display:grid;grid-template-columns:repeat(61,1fr);gap:2px}
.strip button{min-height:22px;padding:0;border:0;border-radius:3px;background:var(--soft)}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:.85rem;color:var(--muted);margin-top:8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px}
section{margin-top:28px}
</style>
</head>
<body>
<header><div class="wrap">
  <div><b style="font-size:1.1rem">PPC · prosumer export limit</b> <span class="muted" id="station">Loading…</span></div>
  <span class="tag">Simulated data · replay of 2013-05-01 to 2013-06-30</span>
</div></header>
<main class="wrap">
  <p class="err" id="err" role="alert"></p>
  <div class="bar">
    <div class="views" role="group" aria-label="View">
      <button id="vBefore" type="button" aria-pressed="true">Before: fixed limit</button>
      <button id="vAfter" type="button" aria-pressed="false" class="line">After: our dynamic limit</button>
    </div>
    <button id="prev" class="line" type="button" aria-label="Previous day">‹</button>
    <label class="sub" for="date">Day (Sydney)</label><input type="date" id="date">
    <button id="next" class="line" type="button" aria-label="Next day">›</button>
    <button id="play" type="button">Play</button>
    <label class="sub" for="speed">Speed</label>
    <select id="speed"><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select>
    <label class="sub" for="slider">Time</label><input type="range" id="slider" min="0" max="0" value="0" style="flex:1;min-width:180px">
    <b id="clock">—</b>
  </div>
  <div class="grid">
    <div>
      <div class="mapbox" id="mapBox"><div id="mapHost" style="position:absolute;inset:0"></div></div>
      <div class="legend">
        <span><i style="background:var(--ok)"></i>✓ within the safe limit</span>
        <span><i style="background:#ffd978"></i>! capped below what the house could sell</span>
        <span><i style="background:var(--bad)"></i>× limit above what the grid can carry</span>
        <span><i style="background:#e9eef1"></i>no reading</span>
      </div>
      <p class="sub" style="margin-top:8px">Illustrative layout: postcode centres with small offsets, not addresses. The grid behind the map is synthetic.</p>
    </div>
    <div>
      <div class="card" aria-live="polite">
        <div class="state"><i class="dot" id="dot"></i><span id="verdict">—</span></div>
        <p class="sub" id="verdictSub"></p>
        <div class="meter" aria-hidden="true"><b id="mLimit"></b><i id="mSafe"></i></div>
        <p class="sub">Bar: the limit in force. Black mark: the highest share the grid can safely take now.</p>
        <p style="margin-top:8px">Limit <b id="vLimit">—</b> of each house's kWp · safe <b id="vSafe">—</b></p>
        <p class="sub" id="abst"></p>
      </div>
      <div class="card" style="margin-top:16px">
        <h2 style="font-size:1rem;font-weight:500;margin-bottom:8px">This day, and all 61 days</h2>
        <table><thead><tr><th></th><th>Before</th><th>After</th></tr></thead>
          <tbody id="cmp"></tbody></table>
      </div>
    </div>
  </div>
  <section>
    <h2 style="font-size:1rem;font-weight:500;margin-bottom:6px">The day: safe share and the two limits</h2>
    <svg id="chart" viewBox="0 0 960 130" preserveAspectRatio="none" role="img" aria-label="Safe share and the fixed and dynamic limits over the day"></svg>
    <div class="legend"><span><i style="background:var(--ink)"></i>safe share (grid truth)</span><span><i style="background:var(--rev)"></i>fixed limit</span><span><i style="background:var(--ok)"></i>our limit</span></div>
  </section>
  <section>
    <h2 style="font-size:1rem;font-weight:500;margin-bottom:6px">The two months: share of daylight intervals over the safe limit</h2>
    <p class="sub">Top row Before, bottom row After. Darker red means more intervals over the limit. Click a day to open it.</p>
    <div class="strip" id="stripB" aria-label="Before, per day"></div>
    <div class="strip" id="stripA" style="margin-top:4px" aria-label="After, per day"></div>
  </section>
  <section><h2 style="font-size:1rem;font-weight:500;margin-bottom:6px">What this is and is not</h2><ul class="sub" id="notes" style="margin:0;padding-left:20px"></ul></section>
</main>
<script>
const $ = id => document.getElementById(id);
const S = {index: null, geo: null, cache: new Map(), date: null, day: null, i: 0, view: "before", timer: null};
const STATUS = {g: "ok", a: "review", r: "blocked", n: "none"};
const TIME = new Intl.DateTimeFormat("en-AU", {timeZone: "Australia/Sydney", hour: "2-digit", minute: "2-digit", hour12: false});
const fmt = (v, d = 1) => v == null ? "—" : Number(v).toFixed(d);
const pct = v => (100 * v).toFixed(0) + "%";
const kwh = v => Math.round(v).toLocaleString("en-US") + " kWh";

async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " answered " + r.status + (r.status === 404 ? ": run python -m src.ui.replay_build" : ""));
  return r.json();
}
async function loadDay(date) {
  if (!S.cache.has(date)) S.cache.set(date, await getJson("/replay/day/" + date));
  return S.cache.get(date);
}
const block = () => S.day.intervals[S.i][S.view];

function mapView() {
  const iv = S.day.intervals[S.i], b = iv[S.view];
  return {
    pt_id: S.index.pt_id, interval_start: iv.t, selected: null, kill_switch: false, groups: S.groups,
    houses: S.index.houses.map((h, k) => ({
      id: h.id, group: h.group, kwp: h.kwp, contract_cap_kw: null,
      limit_kw: Math.round(b.share * h.kwp * 100) / 100, share: b.share,
      status: STATUS[b.status[k]], capped: b.status[k] === "a"
    }))
  };
}
function row(label, before, after, worse) {
  const cls = worse ? ["bad", "good"] : ["", ""];
  return `<tr><td>${label}</td><td class="${cls[0]}">${before}</td><td class="${cls[1]}">${after}</td></tr>`;
}
function renderStats() {
  const iv = S.day.intervals[S.i], b = block();
  $("clock").textContent = TIME.format(new Date(iv.t)) + " · " + S.date;
  $("dot").className = "dot " + (b.violation ? "bad" : "ok");
  $("verdict").textContent = b.violation ? "Over what the grid can carry" : "Within the safe limit";
  $("verdictSub").textContent = b.violation
    ? "The limit is above the safe share: the transformer would be overloaded in this interval."
    : "The limit stays below the safe share: the transformer is not overloaded.";
  $("vLimit").textContent = pct(b.share); $("vSafe").textContent = pct(iv.safe);
  $("mLimit").style.width = pct(Math.min(1, b.share)); $("mLimit").style.background = b.violation ? "var(--bad)" : "var(--ok)";
  $("mSafe").style.left = pct(Math.min(1, iv.safe));
  $("abst").textContent = S.view === "after" && iv.abstained ? "The model was not sure here: the fixed limit is used." : "";
  const d = S.day.summary, t = S.index.totals;
  $("cmp").innerHTML =
    row("Intervals over the safe limit, this day", d.before.violations, d.after.violations, d.before.violations > d.after.violations) +
    row("Exported, this day", kwh(d.before.export_kwh), kwh(d.after.export_kwh), d.after.export_kwh > d.before.export_kwh) +
    row("Not sold (capped), this day", kwh(d.before.curtailed_kwh), kwh(d.after.curtailed_kwh), d.before.curtailed_kwh > d.after.curtailed_kwh) +
    row("Intervals over the safe limit, 61 days", t.before.violations, t.after.violations, t.before.violations > t.after.violations) +
    row("Exported, 61 days", kwh(t.before.export_kwh), kwh(t.after.export_kwh), t.after.export_kwh > t.before.export_kwh) +
    row("Not sold (capped), 61 days", kwh(t.before.curtailed_kwh), kwh(t.after.curtailed_kwh), t.before.curtailed_kwh > t.after.curtailed_kwh);
}
function renderChart() {
  const n = S.day.intervals.length, x = k => 20 + 920 * (n < 2 ? 0 : k / (n - 1)), y = v => 120 - 110 * Math.min(1, Math.max(0, v));
  const line = (key, color, dash) => `<polyline fill="none" stroke="${color}" stroke-width="2" ${dash ? 'stroke-dasharray="6 4"' : ""} points="${S.day.intervals.map((iv, k) => x(k) + "," + y(iv[key])).join(" ")}"/>`;
  $("chart").innerHTML = '<rect x="0" y="0" width="960" height="130" fill="none"/>' +
    line("fixed", "var(--rev)", true) + line("safe", "var(--ink)") + line("model", "var(--ok)") +
    `<line x1="${x(S.i)}" x2="${x(S.i)}" y1="0" y2="130" stroke="var(--muted)" stroke-width="1.5"/>`;
}
function render() {
  if (!S.day) return;
  renderStats(); renderChart();
  const m = window.StationMap;
  if (m && S.mounted) m.update(mapView());
}
async function openDay(date, last) {
  S.date = date; S.day = await loadDay(date);
  $("date").value = date; S.i = last ? S.day.intervals.length - 1 : 0;
  $("slider").max = S.day.intervals.length - 1; $("slider").value = S.i;
  render();
}
function shift(days) {
  const dates = S.index.days.map(d => d.date), k = dates.indexOf(S.date) + days;
  if (k >= 0 && k < dates.length) return openDay(dates[k], days < 0);
  stop();
}
function stop() { clearInterval(S.timer); S.timer = null; $("play").textContent = "Play"; }
function play() {
  if (S.timer) return stop();
  $("play").textContent = "Pause";
  S.timer = setInterval(async () => {
    if (S.i < S.day.intervals.length - 1) { S.i++; $("slider").value = S.i; render(); }
    else await shift(1);
  }, 700 / Number($("speed").value));
}
function setView(v) {
  S.view = v; $("vBefore").setAttribute("aria-pressed", v === "before"); $("vAfter").setAttribute("aria-pressed", v === "after");
  $("vBefore").classList.toggle("line", v !== "before"); $("vAfter").classList.toggle("line", v !== "after"); render();
}
function strips() {
  for (const [id, key] of [["stripB", "before"], ["stripA", "after"]]) {
    $(id).replaceChildren(...S.index.days.map(d => {
      const b = document.createElement("button"), share = d[key].violations / Math.max(1, d.intervals);
      b.type = "button"; b.title = `${d.date}: ${d[key].violations} of ${d.intervals} intervals over the safe limit, ${Math.round(d[key].export_kwh)} kWh exported`;
      b.setAttribute("aria-label", b.title);
      b.style.background = share === 0 ? "var(--soft)" : `color-mix(in srgb, var(--bad) ${Math.round(25 + 75 * share)}%, transparent)`;
      b.onclick = () => { stop(); openDay(d.date); };
      return b;
    }));
  }
}
async function boot() {
  try {
    S.index = await getJson("/replay/index"); S.geo = await getJson("/replay/geo");
    S.groups = S.geo.features.filter(f => f.properties.kind === "neighbourhood").map(f => ({id: f.properties.id, name: f.properties.name}));
    $("station").textContent = `${S.index.pt_id} · ${S.index.houses.length} houses · model ${S.index.model_version}`;
    $("notes").replaceChildren(...S.index.notes.map(t => { const li = document.createElement("li"); li.textContent = t; return li; }));
    const dates = S.index.days.map(d => d.date);
    $("date").min = dates[0]; $("date").max = dates[dates.length - 1];
    strips();
    await new Promise((ok, no) => { const s = document.createElement("script"); s.src = "/static/map/map.js"; s.onload = ok; s.onerror = () => no(new Error("map module not found")); document.head.append(s); });
    window.StationMap.mount($("mapHost"), {geo: S.geo, select: () => {}}); S.mounted = true;
    await openDay(dates[0]);
    if (window.StationMap.onShow) window.StationMap.onShow();
  } catch (e) { $("err").textContent = e.message; }
}
$("vBefore").onclick = () => setView("before"); $("vAfter").onclick = () => setView("after");
$("prev").onclick = () => { stop(); shift(-1); }; $("next").onclick = () => { stop(); shift(1); };
$("play").onclick = play;
$("speed").onchange = () => { if (S.timer) { stop(); play(); } };
$("date").onchange = e => { stop(); if (S.index.days.some(d => d.date === e.target.value)) openDay(e.target.value); };
$("slider").oninput = e => { S.i = Number(e.target.value); render(); };
$("chart").onclick = e => { const r = e.currentTarget.getBoundingClientRect(); const n = S.day.intervals.length; S.i = Math.max(0, Math.min(n - 1, Math.round(((e.clientX - r.left) / r.width * 960 - 20) / 920 * (n - 1)))); $("slider").value = S.i; render(); };
boot();
</script>
</body>
</html>
```

(`row()` colours the Before cell red and the After cell green when the third flag is true, that is when After is the better number.)

- [ ] **Step 2: Run the route tests**

Run: `.venv/bin/pytest tests/test_ui_replay_routes.py -q`
Expected: pass (the page contains `mapHost`, `window.StationMap`, `/replay/index`, `Before`, `After`).

- [ ] **Step 3: Serve and look at it**

Run (background):
```bash
ARTIFACT_URI=artifacts API_URL=http://127.0.0.1:8000 .venv/bin/python -m uvicorn src.ui.app:app --port 8001
```
Open `http://127.0.0.1:8001/` with the preview tools. Check, in order:
1. The map shows 210 houses in three neighbourhoods; zoom in to see house marks.
2. Pick 2013-05-15 and a midday interval. Switch Before and After: colours and the state line change; the table shows both policies.
3. Press Play: the clock advances, the cursor moves on the chart; at the end of the day it goes to the next day.
4. Click a cell in the 61-day strips: that day opens.
5. The browser console has no errors (`read_console_messages`).
Take screenshots of Before and After for the same interval and tell the user what they show, including if After is not better in some intervals.

- [ ] **Step 4: Fix anything the check shows**, then re-run Task 5 tests.

---

### Task 7: Docs and the full run

**Files:**
- Modify: `src/ui/static/map/README.md` (one line)
- Modify: `README.md` (run section)

- [ ] **Step 1: Document**

In `src/ui/static/map/README.md`, add under "Run the three-neighbourhood demo": "The replay page (`/`) mounts this module with the 210 station houses from `/replay/geo` and sets each house's `status` from the replayed policy."

In `README.md`, add to the local run guide: the two commands from the top of `src/ui/replay_build.py` (labels with `--final-eval`, then `python -m src.ui.replay_build`), the UI start command with `ARTIFACT_URI=artifacts`, and that `/` is the replay and `/operator` the old screen.

- [ ] **Step 2: Full checks**

Run: `.venv/bin/ruff check . && .venv/bin/pytest tests/ml tests/eval tests/test_ui_app.py tests/test_ui_replay_build.py tests/test_ui_replay_routes.py tests/test_grid_labels.py -q -W ignore`
Expected: ruff clean; all tests pass. One timing test in `tests/ml/test_predict.py` can fail under load; rerun it alone before treating it as a failure.

- [ ] **Step 3: Report to the user**

Give the Before and After totals from `index.json` as they are (violations, exported kWh, capped kWh over the 61 days), say these are the first and only read of the demo period for this model version, and list what was not verified (inverter limits are not modelled; March has no labels so the offset learned only from April).

---

## Self-review against the spec

* Main page, old screen kept at `/operator`: Task 5.
* Precomputed replay with a play clock: Tasks 4 and 6 (Play, speed, scrubber).
* Existing map module, 210 houses: Tasks 3 and 6.
* Two views Before and After: Task 6 (`setView`).
* Red, amber, green, grey rules and the violation test from `evaluate`: Task 2.
* Day chart, 61-day strips, honest notes: Task 6.
* Model logic shared with the test scorer, no second copy: Task 1.
* Demo labels with `--final-eval`: Task 4.
* Spec item "gauge against 400 kVA" is replaced by the limit-versus-safe-share meter, because the build stores shares, not transformer load. Update the spec line when this plan is accepted.
