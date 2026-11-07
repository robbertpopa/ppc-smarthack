import unittest
from importlib.util import find_spec
from unittest.mock import patch

if find_spec("pandapower") is None:
    raise unittest.SkipTest("grid tests require the optional simulation dependencies")

from pandapower.auxiliary import LoadflowNotConverged  # noqa: E402

from src.common.contract import GridState, GuardResult  # noqa: E402
from src.grid import build_grid, guard, power_flow, safe_share  # noqa: E402
from src.grid.battery import step  # noqa: E402
from src.grid.twin import solve  # noqa: E402


class TwinTests(unittest.TestCase):
    def setUp(self):
        self.grid = build_grid({"houses": [{"house_id": "H1", "kwp": 100}], "transformer_kva": 40})
        self.injections = {
            "interval_start": "2025-01-01T00:00:00Z",
            "houses": [{"house_id": "H1", "load_kw": 1, "pv_kw": 100, "export_limit_kw": 0}],
        }

    def test_boundary(self):
        share = safe_share(self.grid, self.injections)
        self.assertIsNotNone(share)
        self.assertLess(share, 1)
        for offset, expected in ((0, True), (0.002, False)):
            data = {
                **self.injections,
                "houses": [
                    {**self.injections["houses"][0], "export_limit_kw": (share + offset) * 100}
                ],
            }
            state = solve(self.grid, data)
            safe = (
                state["v_min_pu"] >= 0.90
                and state["v_max_pu"] <= 1.05
                and state["line_loading_max_pct"] <= 100
                and state["trafo_loading_pct"] <= 100
            )
            self.assertEqual(safe, expected)

    def test_nonconvergence_is_explicit(self):
        with patch("src.grid.twin.pp.runpp", side_effect=LoadflowNotConverged):
            state = power_flow(self.grid, self.injections)
        self.assertFalse(state["converged"])
        self.assertIsNone(state["v_max_pu"])

    def test_safe_share_rejects_nonconvergence(self):
        with patch("src.grid.twin.pp.runpp", side_effect=LoadflowNotConverged):
            self.assertIsNone(safe_share(self.grid, self.injections))

    def test_safe_share_is_reproducible(self):
        self.assertEqual(
            safe_share(self.grid, self.injections), safe_share(self.grid, self.injections)
        )

    def test_missing_house_rejected(self):
        with self.assertRaises(ValueError):
            power_flow(self.grid, {**self.injections, "houses": []})

    def test_guard_accepts_safe_and_rejects_overload(self):
        good = {"limits": [{"house_id": "H1", "export_limit_kw": 5, "battery_kw": 0}]}
        bad = {"limits": [{"house_id": "H1", "export_limit_kw": 99, "battery_kw": 0}]}
        self.assertTrue(guard(self.grid, good, self.injections)["passed"])
        result = guard(self.grid, bad, self.injections)
        self.assertFalse(result["passed"])
        self.assertTrue(result["violations"])
        GuardResult.model_validate(result)

    def test_grid_state_matches_shared_contract(self):
        state = power_flow(self.grid, self.injections)
        GridState.model_validate(state)
        self.assertNotIn("v_min_pu", state)

    def test_guard_enforces_contract_cap(self):
        grid = build_grid({"houses": [{"house_id": "H1", "kwp": 100, "contract_cap_kw": 4}]})
        plan = {"limits": [{"house_id": "H1", "export_limit_kw": 5, "battery_kw": 0}]}
        result = guard(grid, plan, self.injections)
        self.assertFalse(result["passed"])
        self.assertTrue(any("contract cap" in message for message in result["violations"]))

    def test_safe_share_applies_contract_cap(self):
        grid = build_grid(
            {
                "houses": [{"house_id": "H1", "kwp": 100, "contract_cap_kw": 4}],
                "transformer_kva": 40,
            }
        )
        self.assertEqual(safe_share(grid, self.injections), 1.0)

    def test_battery_bounds(self):
        self.assertGreater(step(5, 5, 0.5), 5)
        with self.assertRaises(ValueError):
            step(9.9, 5, 0.5)
        with self.assertRaises(ValueError):
            step(1, -5, 0.5)

    def test_guard_rejects_invalid_idle_battery(self):
        plan = {"limits": [{"house_id": "H1", "export_limit_kw": 5, "battery_kw": 0}]}
        data = {
            **self.injections,
            "houses": [{**self.injections["houses"][0], "battery_soc_kwh": 11}],
        }
        self.assertFalse(guard(self.grid, plan, data)["passed"])

    def test_guard_rejects_low_voltage_even_when_solver_converges(self):
        plan = {"limits": [{"house_id": "H1", "export_limit_kw": 5, "battery_kw": 0}]}
        state = {
            "converged": True,
            "v_min_pu": 0.01,
            "v_max_pu": 0.02,
            "line_loading_max_pct": 0,
            "trafo_loading_pct": 1,
        }
        with patch("src.grid.guard.solve", return_value=state):
            result = guard(self.grid, plan, self.injections)
        self.assertFalse(result["passed"])
        self.assertIn("Voltage below configured minimum", result["violations"])

    def test_simbench_benchmark_runs(self):
        grid = build_grid({"topology": "simbench", "houses": [{"house_id": "H1", "kwp": 5}]})
        state = power_flow(grid, self.injections)
        self.assertTrue(state["converged"])
        self.assertEqual(len(grid.net.trafo), 1)
        self.assertEqual(len(grid.houses), 1)

    def test_simbench_phase_shift_no_load(self):
        grid = build_grid({"topology": "simbench", "houses": [{"house_id": "H1", "kwp": 5}]})
        data = {
            "interval_start": "2025-01-01T00:00:00Z",
            "houses": [{"house_id": "H1", "load_kw": 0, "pv_kw": 0, "export_limit_kw": 0}],
        }
        state = solve(grid, data)
        self.assertTrue(state["converged"])
        self.assertGreater(state["v_min_pu"], 0.98)
        self.assertLess(state["v_max_pu"], 1.10)
        self.assertLess(state["trafo_loading_pct"], 2)

    def test_simbench_210_homes(self):
        houses = [{"house_id": f"H{i}", "kwp": 5} for i in range(210)]
        grid = build_grid({"topology": "simbench", "houses": houses})
        data = {
            "interval_start": "2025-01-01T00:00:00Z",
            "houses": [
                {"house_id": h["house_id"], "load_kw": 1, "pv_kw": 2, "export_limit_kw": 5}
                for h in houses
            ],
        }
        state = solve(grid, data)
        self.assertTrue(state["converged"])
        self.assertGreater(state["v_min_pu"], 0.9)
        self.assertLess(state["v_max_pu"], 1.1)


if __name__ == "__main__":
    unittest.main()
