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
from src.common.contract import StationConfig  # noqa: E402
from src.common.mock_data import load_mock  # noqa: E402
from src.grid.agent_guard import make_grid_guard  # noqa: E402

NOON = datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)


class NoForecast(MockSource):
    def forecast(self, pt_id, interval_start):
        found = super().forecast(pt_id, interval_start)
        return found.model_copy(update={"pv_kw": None})


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


if __name__ == "__main__":
    unittest.main()
