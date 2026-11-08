import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path

from src.common.contract import StationConfig
from src.grid.demo_station import load_station
from src.ui import geo_build

# Three groups of nearby postcodes, 20 km apart, plus a postcode that belongs to none of them.
CENTRES = {"A": (-33.70, 151.00), "B": (-33.70, 151.25), "C": (-33.95, 151.12)}


def table():
    rows, customer = [], 0
    for name, (lat, lon) in CENTRES.items():
        for k, code in enumerate((f"{name}1", f"{name}2")):
            for _ in range(5):
                customer += 1
                rows.append(
                    {
                        "customer": str(customer),
                        "kwp": 1.0 + customer / 10,
                        "postcode": code,
                        "lat": lat + 0.01 * k,
                        "lon": lon + 0.01 * k,
                        "locality": f"{name}-town {k}",
                    }
                )
    rows.append(
        {
            "customer": "99",
            "kwp": 2.0,
            "postcode": "Z9",
            "lat": -33.3,
            "lon": 150.5,
            "locality": "Far away",
        }
    )
    return rows


def inside(point, ring):
    """Ray casting: is (lon, lat) inside the closed ring of [lon, lat] pairs?"""
    x, y, hit = point[0], point[1], False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


class ChooseTests(unittest.TestCase):
    def test_three_neighbourhoods_west_to_east(self):
        groups = geo_build.choose_neighbourhoods(table(), per_hood=8, radius_km=4)
        self.assertEqual(len(groups), 3)
        names = [{p["postcode"][0] for p in g} for g in groups]
        self.assertEqual(names, [{"A"}, {"C"}, {"B"}])  # by longitude: A 151.00, C 151.12, B 151.25

    def test_not_enough_customers_is_an_error(self):
        with self.assertRaises(ValueError):
            geo_build.choose_neighbourhoods(table(), per_hood=40, radius_km=4)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.geo, self.bundle = geo_build.build(table(), per_hood=8, per_node=4, radius_km=4)
        self.houses = [f for f in self.geo["features"] if f["properties"]["kind"] == "house"]

    def test_the_station_lists_neighbourhood_by_neighbourhood(self):
        ids = [h["house_id"] for h in self.bundle["station"]["houses"]]
        self.assertEqual(len(ids), 24)
        for hood in self.bundle["neighbourhoods"]:
            first = ids.index(hood["house_ids"][0])
            self.assertEqual(ids[first : first + 8], hood["house_ids"])
            self.assertEqual(first % 8, 0)  # house i is on feeder i // 8, as the twin assigns it

    def test_the_station_is_a_valid_station_config_with_the_twin_settings(self):
        station = StationConfig.model_validate(self.bundle["station"])
        self.assertEqual(len(station.houses), 24)
        self.assertEqual(
            self.bundle["grid_config"], {"houses_per_neighborhood": 8, "houses_per_node": 4}
        )
        self.assertEqual(station.static_share, 0.36)

    def test_every_house_has_its_own_position_near_its_postcode(self):
        positions = {tuple(f["geometry"]["coordinates"]) for f in self.houses}
        self.assertEqual(len(positions), len(self.houses))
        centre = {(r["postcode"]): (r["lat"], r["lon"]) for r in table()}
        for f in self.houses:
            lon, lat = f["geometry"]["coordinates"]
            clat, clon = centre[f["properties"]["postcode"]]
            metres = math.hypot(
                (lat - clat) * 111_320, (lon - clon) * 111_320 * math.cos(math.radians(clat))
            )
            self.assertLess(metres, 900)

    def test_each_outline_contains_its_houses(self):
        rings = {
            f["properties"]["id"]: f["geometry"]["coordinates"][0]
            for f in self.geo["features"]
            if f["properties"]["kind"] == "neighbourhood"
        }
        self.assertEqual(len(rings), 3)
        for f in self.houses:
            self.assertTrue(
                inside(f["geometry"]["coordinates"], rings[f["properties"]["neighbourhood"]])
            )

    def test_nodes_hold_the_houses_in_order(self):
        for hood in self.bundle["neighbourhoods"]:
            nodes = [
                f["properties"]["node"]
                for f in self.houses
                if f["properties"]["house_id"] in hood["house_ids"]
            ]
            by_id = {f["properties"]["house_id"]: f["properties"]["node"] for f in self.houses}
            self.assertEqual([by_id[i] for i in hood["house_ids"]], nodes)
            self.assertEqual(sorted(set(nodes)), [f"{hood['id']}-1", f"{hood['id']}-2"])

    def test_the_same_table_gives_the_same_output(self):
        again = geo_build.build(table(), per_hood=8, per_node=4, radius_km=4)
        self.assertEqual((self.geo, self.bundle), again)

    def test_the_geometry_says_it_is_assumed(self):
        self.assertEqual(self.geo["meta"]["provenance"], "assumed")

    def test_houses_per_neighbourhood_must_be_a_multiple_of_the_node_size(self):
        with self.assertRaises(ValueError):
            geo_build.build(table(), per_hood=8, per_node=3)


class FilesTests(unittest.TestCase):
    def test_read_write_and_load_station_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "customers.csv"
            lines = ["Customer,Generator Capacity,Postcode,lat,lon,localities"]
            lines += [
                ",".join(str(r[k]) for k in ("customer", "kwp", "postcode", "lat", "lon"))
                + f',"{r["locality"]}, x"'
                for r in table()
            ]
            csv_path.write_text("\n".join(lines), encoding="utf-8")
            rows = geo_build.read_customers(csv_path)
            self.assertEqual(len(rows), len(table()))
            self.assertEqual(rows[0]["locality"], "A-town 0")
            geo, bundle = geo_build.build(rows, per_hood=8, per_node=4)
            written = geo_build.write(Path(tmp) / "out", geo, bundle)
            self.assertTrue(all(p.is_file() for p in written))
            station, grid = load_station({"STATION_FILE": str(written[1])})
            self.assertEqual(len(station.houses), 24)
            self.assertEqual(grid["houses_per_neighborhood"], 8)
            self.assertEqual(
                json.loads(written[0].read_text(encoding="utf-8"))["type"], "FeatureCollection"
            )

    def test_a_table_with_a_missing_column_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text("Customer,lat,lon\n1,1,2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                geo_build.read_customers(path)


class DemoStationTests(unittest.TestCase):
    def test_without_a_file_it_is_the_mock_station(self):
        station, grid = load_station({})
        self.assertEqual(len(station.houses), 8)
        self.assertEqual(grid, {})

    def test_grid_config_must_be_an_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            geo, bundle = geo_build.build(table(), per_hood=8, per_node=4)
            bundle["grid_config"] = [1]
            path.write_text(json.dumps(bundle), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_station({"STATION_FILE": str(path)})


@unittest.skipUnless(importlib.util.find_spec("pandapower"), "needs the sim extra")
class TwinAgreementTests(unittest.TestCase):
    def test_the_twin_puts_each_neighbourhood_on_its_own_feeder(self):
        from src.grid.twin import build_grid

        _, bundle = geo_build.build(table(), per_hood=8, per_node=4)
        houses = bundle["station"]["houses"]
        grid = build_grid({"houses": houses, **bundle["grid_config"]})
        names = grid.net.bus.name
        for hood_index, hood in enumerate(bundle["neighbourhoods"], start=1):
            for house_id in hood["house_ids"]:
                bus = grid.houses[house_id]["bus"]
                self.assertTrue(
                    str(names.at[bus]).startswith(f"area-{hood_index}-"), (house_id, names.at[bus])
                )


if __name__ == "__main__":
    unittest.main()
