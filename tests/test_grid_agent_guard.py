import tempfile
import unittest
from datetime import datetime, timezone
from importlib.util import find_spec
from pathlib import Path

if find_spec("pandapower") is None:
    raise unittest.SkipTest("grid tests require the optional simulation dependencies")

from src.agent.log import ActionLog  # noqa: E402
from src.agent.service import AgentService  # noqa: E402
from src.agent.sources import MockSource  # noqa: E402
from src.common.contract import Band, StationConfig  # noqa: E402
from src.common.mock_data import load_mock  # noqa: E402
from src.grid.agent_guard import make_grid_guard, readings_from_forecast  # noqa: E402

NOON = datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)


class NoForecast(MockSource):
    def forecast(self, pt_id, interval_start):
        found = super().forecast(pt_id, interval_start)
        return found.model_copy(update={"pv_kw": None})


class HeavyImport(MockSource):
    """Low PV and a very high load at the p90: the import side is the dangerous one."""

    def forecast(self, pt_id, interval_start):
        found = super().forecast(pt_id, interval_start)
        return found.model_copy(
            update={
                "pv_kw": Band(p10=0.0, p50=10.0, p90=70.0),
                "load_kw": Band(p10=12.0, p50=100.0, p90=900.0),
            }
        )


class AgentGuardTests(unittest.TestCase):
    def service(self, source, **grid_config):
        station = load_mock("station", StationConfig)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        guard = make_grid_guard(station, source, grid_config)
        return AgentService(station, ActionLog(Path(tmp.name) / "log.jsonl"), guard, source)

    def test_good_plan_passes_with_numbers(self):
        plan = self.service(MockSource()).propose(NOON)
        self.assertTrue(plan.guard.passed, plan.guard.violations)
        self.assertIsNotNone(plan.guard.v_max_pu)
        self.assertEqual(plan.status, "proposed")

    def test_overloaded_transformer_blocks_the_plan(self):
        plan = self.service(MockSource(), transformer_kva=20).propose(NOON)
        self.assertFalse(plan.guard.passed)
        self.assertEqual(plan.status, "rejected")
        self.assertTrue(any("Transformer" in v for v in plan.guard.violations))

    def test_missing_forecast_is_unverifiable_not_passed(self):
        plan = self.service(NoForecast()).propose(NOON)
        self.assertFalse(plan.guard.passed)
        self.assertIn("cannot be verified", plan.guard.violations[0])

    def test_import_side_overload_blocks_even_when_export_is_fine(self):
        plan = self.service(HeavyImport()).propose(NOON)
        self.assertFalse(plan.guard.passed)
        self.assertEqual(plan.status, "rejected")
        self.assertTrue(plan.guard.violations)

    def test_readings_use_opposite_ends_of_the_band_for_each_case(self):
        station = load_mock("station", StationConfig)
        forecast = HeavyImport().forecast(station.pt_id, NOON)
        export = readings_from_forecast(station, forecast, "t", "export")["houses"]
        imports = readings_from_forecast(station, forecast, "t", "import")["houses"]
        self.assertAlmostEqual(sum(h["pv_kw"] for h in export), 70.0)
        self.assertAlmostEqual(sum(h["load_kw"] for h in export), 12.0)
        self.assertAlmostEqual(sum(h["pv_kw"] for h in imports), 0.0)
        self.assertAlmostEqual(sum(h["load_kw"] for h in imports), 900.0)
        with self.assertRaises(ValueError):
            readings_from_forecast(station, forecast, "t", "sideways")


if __name__ == "__main__":
    unittest.main()
