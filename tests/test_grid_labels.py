import os
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest import mock

if find_spec("pandapower") is None or find_spec("pyarrow") is None:
    raise unittest.SkipTest("label tests require the simulation and grid-tools extras")

import pandas as pd  # noqa: E402

from src.grid.ausgrid import day_profiles, half_hour_columns, read_period, select_households  # noqa: E402
from src.grid.labels import generate  # noqa: E402
from src.ml import labels as labels_io  # noqa: E402

SLOTS = [f"{i // 2}:{30 * (i % 2):02d}" for i in range(48)]


def write_csv(path, customers=211, controlled=None):
    rows = []
    for customer in range(1, customers + 1):
        for date in ("01/01/2013", "02/01/2013"):
            categories = {"GC": 0.1, "GG": 0.0}
            if customer in (controlled or {}) and date in controlled[customer]:
                categories["CL"] = 0.2
            for category, value in categories.items():
                values = [
                    0.5 if category == "GG" and 16 <= i < 32 else value for i in range(len(SLOTS))
                ]
                rows.append([customer, 5.0, 2000, category, date, *values])
    frame = pd.DataFrame(
        rows,
        columns=["Customer", "Generator Capacity", "Postcode", "Consumption Category", "date"]
        + SLOTS,
    )
    path.write_text("Ausgrid test data\n" + frame.to_csv(index=False))


class LabelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "ausgrid.csv"

    def test_incomplete_controlled_load_customer_is_excluded(self):
        write_csv(self.source, controlled={5: {"02/01/2013"}})
        frame, cl_customers = read_period(self.source, "2013-01-01", 1)
        eligible, _, capacity = select_households(frame, cl_customers, 1)
        self.assertEqual(len(eligible), 210)
        self.assertNotIn(5, eligible)
        self.assertEqual(float(capacity.loc[eligible[0]]), 5.0)

    def test_fewer_than_station_size_is_rejected(self):
        write_csv(self.source, customers=100)
        frame, cl_customers = read_period(self.source, "2013-01-01", 1)
        with self.assertRaises(ValueError):
            select_households(frame, cl_customers, 1)

    def test_controlled_load_is_added_and_energy_converted_to_kw(self):
        write_csv(self.source, controlled={5: {"01/01/2013", "02/01/2013"}})
        frame, cl_customers = read_period(self.source, "2013-01-01", 1)
        eligible, frame, _ = select_households(frame, cl_customers, 1)
        load, pv = day_profiles(
            frame[frame.date == "2013-01-01"], eligible, half_hour_columns(frame)
        )
        self.assertEqual(load.shape, (48, 210))
        self.assertAlmostEqual(load[0, eligible.index(5)], 2 * (0.1 + 0.2))
        self.assertAlmostEqual(load[0, eligible.index(6)], 2 * 0.1)
        self.assertAlmostEqual(pv[20, 0], 1.0)
        self.assertEqual(pv[0, 0], 0.0)

    def test_generate_uses_daylight_window_and_utc_times(self):
        write_csv(self.source)
        output = Path(self.directory.name) / "A"
        generate(self.source, output, "2013-01-01", 1)
        labels = pd.read_parquet(output / "labels.parquet")
        self.assertEqual(len(labels), 16)
        self.assertEqual(labels.interval_start.iloc[0], pd.Timestamp("2012-12-31T21:00:00Z"))
        self.assertEqual(labels.interval_start.iloc[-1], pd.Timestamp("2013-01-01T04:30:00Z"))
        self.assertTrue((labels.safe_share == 1.0).all())
        self.assertTrue((labels.binding == "none").all())
        self.assertTrue((labels.provenance == "simulated").all())

    def test_output_is_what_the_ml_side_loads(self):
        write_csv(self.source, controlled={5: {"01/01/2013", "02/01/2013"}})
        data = Path(self.directory.name) / "data"
        generate(self.source, data / "labels" / "B", "2013-01-01", 1, scenario="B")
        with mock.patch.dict(os.environ, {"DATA_DIR": str(data)}):
            labels = labels_io.load("B")
            houses = labels_io.load_station_houses("B")
        self.assertEqual(list(labels.columns), list(labels_io.COLUMNS))
        self.assertTrue((labels.pt_id == "PT-B").all())
        self.assertTrue(labels.source_ref.str.startswith("grid/labels.py@").all())
        step = labels.available_at - labels.interval_start
        self.assertTrue((step == pd.Timedelta("30min")).all())
        self.assertEqual(int(labels.n_houses.iloc[0]), 210)
        self.assertAlmostEqual(float(labels.kwp_total.iloc[0]), 210 * 5.0)
        # 12:00 local: every house makes 1 kW; house 5 also has 0.4 kW of controlled load
        noon = labels.set_index("interval_start").loc[pd.Timestamp("2013-01-01T01:00:00Z")]
        self.assertAlmostEqual(noon.pv_kw, 210 * 1.0)
        self.assertAlmostEqual(noon.load_kw, 210 * 0.2 + 0.4)
        self.assertAlmostEqual(noon.net_kw, noon.load_kw - noon.pv_kw)
        self.assertEqual(list(houses.columns), list(labels_io.HOUSE_COLUMNS))
        self.assertEqual(houses.source_house_id.iloc[0], "AG-0001")
        self.assertEqual(len(houses), 210)

    def test_a_binding_limit_is_named_when_the_share_is_below_one(self):
        write_csv(self.source)
        output = Path(self.directory.name) / "A"
        generate(self.source, output, "2013-01-01", 1, transformer_kva=100)
        labels = pd.read_parquet(output / "labels.parquet")
        below = labels[labels.safe_share < 1]
        self.assertFalse(below.empty)
        self.assertTrue(below.binding.isin(["voltage", "line", "trafo"]).all())
        houses = pd.read_parquet(output / "station_houses.parquet")
        self.assertTrue((houses.pv_scale == 1.0).all())

    def test_pv_scale_is_kept_in_station_houses(self):
        write_csv(self.source)
        output = Path(self.directory.name) / "A"
        generate(self.source, output, "2013-01-01", 1, pv_scale=2.0)
        houses = pd.read_parquet(output / "station_houses.parquet")
        labels = pd.read_parquet(output / "labels.parquet")
        self.assertTrue((houses.pv_scale == 2.0).all())
        self.assertAlmostEqual(float(houses.kwp.iloc[0]), 10.0)
        self.assertAlmostEqual(float(labels.kwp_total.iloc[0]), 210 * 10.0)

    def test_unknown_scenario_is_rejected(self):
        write_csv(self.source)
        with self.assertRaises(ValueError):
            generate(self.source, Path(self.directory.name) / "Z", "2013-01-01", 1, scenario="Z")

    def test_labels_are_identical_with_one_or_two_workers(self):
        write_csv(self.source, controlled={5: {"01/01/2013"}})
        outputs = []
        for workers in (1, 2):
            output = Path(self.directory.name) / f"labels-{workers}"
            generate(self.source, output, "2013-01-01", 1, workers=workers)
            outputs.append(pd.read_parquet(output / "labels.parquet"))
        pd.testing.assert_frame_equal(outputs[0], outputs[1])

    def test_invalid_grid_fails_in_the_parent_with_workers(self):
        write_csv(self.source)
        output = Path(self.directory.name) / "x.parquet"
        for workers in (1, 2):
            with self.assertRaises(ValueError):
                generate(self.source, output, "2013-01-01", 1, transformer_kva=-1, workers=workers)
        self.assertFalse(output.exists())

    def test_workers_must_be_positive(self):
        write_csv(self.source)
        with self.assertRaises(ValueError):
            generate(
                self.source, Path(self.directory.name) / "x.parquet", "2013-01-01", 1, workers=0
            )


if __name__ == "__main__":
    unittest.main()
