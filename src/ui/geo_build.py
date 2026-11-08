"""Build the neighbourhood map data (P4) from a table of customers with coordinates.

    python -m src.ui.geo_build --customers data/p4/customers.csv --out artifacts

The table has one row per customer: Customer, Generator Capacity (kWp), Postcode, lat, lon,
localities. The coordinates are postcode centroids, not addresses. The script

1. picks three neighbourhoods: three groups of nearby postcodes, as close together as possible,
   each with enough customers (``--houses-per-neighbourhood``, ``--radius-km``);
2. takes the first N customers of each group, in customer order, and gives every house a
   deterministic offset around its postcode centroid so that houses do not sit on top of each other;
3. writes ``<out>/geo/station.geojson`` (served by the screen at ``/geo/station``) and
   ``<out>/station/demo_station.json`` (the station for ``STATION_FILE``, see ``demo_station.py``).

The three neighbourhoods are the three feeders of the twin: ``houses_per_neighborhood`` is N and
house order in the station file is neighbourhood by neighbourhood, so house ``i`` belongs to
feeder ``i // N`` exactly as ``src.grid.twin.build_grid`` assigns it. Positions never enter the
physics: line lengths in the twin are assumed values, not distances on the map.
"""

import argparse
import csv
import itertools
import json
import math
import zlib
from pathlib import Path

from src.common.contract import House, StationConfig
from src.common.mock_data import load_mock

GOLDEN_ANGLE = 2.399963229728653
EARTH_M_PER_DEG = 111_320.0
PAD_M = 350.0  # padding of the neighbourhood outline around its houses


def read_customers(path: str | Path) -> list[dict]:
    """Rows of the customer table. Raises ValueError on a missing column or a bad value."""
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = {"Customer", "Generator Capacity", "Postcode", "lat", "lon"} - set(
            reader.fieldnames or []
        )
        if missing:
            raise ValueError(f"missing columns: {sorted(missing)}")
        rows = []
        for raw in reader:
            row = {
                "customer": str(int(raw["Customer"])),
                "kwp": float(raw["Generator Capacity"]),
                "postcode": str(raw["Postcode"]).strip(),
                "lat": float(raw["lat"]),
                "lon": float(raw["lon"]),
                "locality": (raw.get("localities") or "").split(",")[0].strip(),
            }
            if not (row["kwp"] > 0 and math.isfinite(row["lat"]) and math.isfinite(row["lon"])):
                raise ValueError(f"customer {row['customer']}: kWp and coordinates must be valid")
            rows.append(row)
    if not rows:
        raise ValueError("no customers")
    return rows


def _km(a: dict, b: dict) -> float:
    dlat = (a["lat"] - b["lat"]) * 111.0
    dlon = (a["lon"] - b["lon"]) * 111.0 * math.cos(math.radians((a["lat"] + b["lat"]) / 2))
    return math.hypot(dlat, dlon)


def _postcodes(rows: list[dict]) -> list[dict]:
    """One entry per postcode: its centroid, its customers and a name from its first locality."""
    by_code: dict[str, dict] = {}
    for row in rows:
        entry = by_code.setdefault(
            row["postcode"],
            {
                "postcode": row["postcode"],
                "lat": row["lat"],
                "lon": row["lon"],
                "rows": [],
                "locality": row["locality"],
            },
        )
        entry["rows"].append(row)
    return sorted(by_code.values(), key=lambda p: p["postcode"])


def choose_neighbourhoods(
    rows: list[dict], per_hood: int = 15, radius_km: float = 4.0, count: int = 3
) -> list[list[dict]]:
    """Three groups of postcodes, each with at least ``per_hood`` customers, closest together.

    A group is a seed postcode plus every still unused postcode within ``radius_km`` of it.
    Seeds are tried in all combinations, and the combination whose seeds are closest to each
    other wins (ties go to the first found, in postcode order), so the result is deterministic.
    """
    codes = _postcodes(rows)
    seeds = [p for p in codes if len(p["rows"]) >= 4]
    best = None
    for combo in itertools.combinations(seeds, count):
        spread = max(_km(a, b) for a, b in itertools.combinations(combo, 2))
        if best is not None and spread >= best[0]:
            continue
        used: set[str] = set()
        groups = []
        for seed in combo:
            members = [p for p in codes if p["postcode"] not in used and _km(seed, p) <= radius_km]
            used |= {p["postcode"] for p in members}
            groups.append(members)
        if all(sum(len(p["rows"]) for p in g) >= per_hood for g in groups):
            best = (spread, groups)
    if best is None:
        raise ValueError(
            f"no {count} neighbourhoods with {per_hood} customers within {radius_km} km: "
            "lower --houses-per-neighbourhood or raise --radius-km"
        )
    # West to east, so the order of neighbourhoods and of feeders is stable.
    return sorted(best[1], key=lambda g: min(p["lon"] for p in g))


def _offset(lat: float, lon: float, rank: int, phase: float) -> tuple[float, float]:
    """A deterministic spiral around the centroid: rank 0 is close, later ranks move outwards."""
    radius = 120.0 + 130.0 * math.sqrt(rank)
    angle = phase + rank * GOLDEN_ANGLE
    dlat = radius * math.cos(angle) / EARTH_M_PER_DEG
    dlon = radius * math.sin(angle) / (EARTH_M_PER_DEG * math.cos(math.radians(lat)))
    return round(lat + dlat, 6), round(lon + dlon, 6)


def _hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Convex hull (monotone chain) of (lon, lat) points."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _outline(houses: list[dict]) -> list[list[float]]:
    """Hull of every house padded by PAD_M, as a closed GeoJSON ring."""
    ring = []
    for h in houses:
        for k in range(12):
            a = 2 * math.pi * k / 12
            ring.append(
                (
                    h["lon"]
                    + PAD_M * math.sin(a) / (EARTH_M_PER_DEG * math.cos(math.radians(h["lat"]))),
                    h["lat"] + PAD_M * math.cos(a) / EARTH_M_PER_DEG,
                )
            )
    hull = _hull(ring)
    hull.append(hull[0])
    return [[round(x, 6), round(y, 6)] for x, y in hull]


def build(
    rows: list[dict], per_hood: int = 15, per_node: int = 5, radius_km: float = 4.0
) -> tuple[dict, dict]:
    """Return (geojson, demo_station bundle). Pure: nothing is written."""
    if per_hood % per_node:
        raise ValueError("houses per neighbourhood must be a multiple of houses per node")
    groups = choose_neighbourhoods(rows, per_hood, radius_km)
    features, hoods, houses_out = [], [], []
    for index, members in enumerate(groups, start=1):
        hood_id = f"N{index}"
        # The first N customers of the group, in customer order; then west to east and by id,
        # so the five houses of a node share a postcode and the feeder runs across the area.
        chosen = sorted((r for p in members for r in p["rows"]), key=lambda r: int(r["customer"]))[
            :per_hood
        ]
        biggest = max(members, key=lambda p: (len(p["rows"]), p["postcode"]))
        chosen.sort(key=lambda r: (r["lon"], int(r["customer"])))
        placed, rank_in_code = [], {}
        for row in chosen:
            rank = rank_in_code.get(row["postcode"], 0)
            rank_in_code[row["postcode"]] = rank + 1
            phase = (zlib.crc32(row["postcode"].encode()) % 360) * math.pi / 180
            lat, lon = _offset(row["lat"], row["lon"], rank, phase)
            placed.append({**row, "lat": lat, "lon": lon, "group": hood_id})
        nodes = []
        for n in range(per_hood // per_node):
            chunk = placed[n * per_node : (n + 1) * per_node]
            for h in chunk:
                h["node"] = f"{hood_id}-{n + 1}"
            nodes.append(
                (
                    round(sum(h["lon"] for h in chunk) / len(chunk), 6),
                    round(sum(h["lat"] for h in chunk) / len(chunk), 6),
                )
            )
        name = biggest["locality"] or f"Neighbourhood {index}"
        kwp = round(sum(h["kwp"] for h in placed), 2)
        hoods.append({"id": hood_id, "name": name, "house_ids": [h["customer"] for h in placed]})
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [_outline(placed)]},
                "properties": {
                    "kind": "neighbourhood",
                    "id": hood_id,
                    "name": name,
                    "houses": len(placed),
                    "kwp": kwp,
                },
            }
        )
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [list(n) for n in nodes]},
                "properties": {"kind": "feeder", "neighbourhood": hood_id},
            }
        )
        for h in placed:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [h["lon"], h["lat"]]},
                    "properties": {
                        "kind": "house",
                        "house_id": h["customer"],
                        "neighbourhood": hood_id,
                        "node": h["node"],
                        "kwp": h["kwp"],
                        "postcode": h["postcode"],
                        "locality": h["locality"],
                    },
                }
            )
            houses_out.append({"house_id": h["customer"], "kwp": h["kwp"]})
    geojson = {
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
    base = load_mock("station", StationConfig)
    station = base.model_copy(update={"houses": [House(**h) for h in houses_out]})
    bundle = {
        "station": json.loads(station.model_dump_json(exclude_none=True)),
        "grid_config": {"houses_per_neighborhood": per_hood, "houses_per_node": per_node},
        "neighbourhoods": hoods,
    }
    return geojson, bundle


def write(out: str | Path, geojson: dict, bundle: dict) -> list[Path]:
    out = Path(out)
    paths = [out / "geo" / "station.geojson", out / "station" / "demo_station.json"]
    for path, payload in zip(paths, (geojson, bundle)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return paths


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--customers", required=True, help="CSV with the customer table")
    parser.add_argument("--out", default="artifacts", help="artifact folder (ARTIFACT_URI)")
    parser.add_argument("--houses-per-neighbourhood", type=int, default=15)
    parser.add_argument("--houses-per-node", type=int, default=5)
    parser.add_argument("--radius-km", type=float, default=4.0)
    args = parser.parse_args(argv)
    geojson, bundle = build(
        read_customers(args.customers),
        args.houses_per_neighbourhood,
        args.houses_per_node,
        args.radius_km,
    )
    for path in write(args.out, geojson, bundle):
        print("wrote", path)
    for hood in bundle["neighbourhoods"]:
        print(f"  {hood['id']} {hood['name']}: {len(hood['house_ids'])} houses")
    print(
        "Run the demo with:\n"
        f"  STATION_FILE={Path(args.out) / 'station' / 'demo_station.json'} "
        f"ARTIFACT_URI={args.out} python -m uvicorn src.grid.demo_api:app --port 8000"
    )


if __name__ == "__main__":
    main()
