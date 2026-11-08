import importlib
import tempfile
from pathlib import Path

from src.agent.guard import stub_guard
from src.agent.log import ActionLog
from src.agent.service import AgentService
from src.agent.sources import MockSource
from src.common.contract import ActionEvent, Forecast, GridState, Plan, StationConfig
from src.common.mock_data import load_mock

PACKAGES = ["common", "ml", "grid", "agent", "ui", "eval", "pricing"]


def main() -> None:
    for name in PACKAGES:
        importlib.import_module(f"src.{name}")
    for name, model in [
        ("forecast", Forecast),
        ("grid_state", GridState),
        ("station", StationConfig),
        ("action_event", ActionEvent),
    ]:
        load_mock(name, model)
    station = load_mock("station", StationConfig)
    forecast = load_mock("forecast", Forecast)
    with tempfile.TemporaryDirectory() as tmp:
        log = ActionLog(Path(tmp) / "actions.jsonl")
        service = AgentService(station, log, stub_guard, MockSource())
        plan = service.propose(forecast.interval_start)
        assert isinstance(plan, Plan) and not plan.abstain, plan
        service.approve(plan.plan_id, "smoke")
        service.execute(plan.plan_id, "smoke")
        events = [e.event for e in log.read()]
        assert events == ["plan_proposed", "plan_approved", "plan_executed"], events
    print("SMOKE OK")


if __name__ == "__main__":
    main()
