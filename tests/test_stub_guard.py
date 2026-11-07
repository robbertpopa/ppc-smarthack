import src.agent.guard as guard_module
from src.agent.planner import make_plan
from src.common.contract import Forecast, GridState, StationConfig
from src.common.mock_data import load_mock

MESSAGE = "stub guard in use: voltage and transformer limits are not checked"


def test_the_stub_guard_warns_once_not_on_every_plan(caplog, monkeypatch):
    plan = make_plan(
        load_mock("forecast", Forecast),
        load_mock("grid_state", GridState),
        load_mock("station", StationConfig),
    )
    monkeypatch.setattr(guard_module, "_warned", False)
    with caplog.at_level("WARNING", logger="src.agent.guard"):
        guard_module.stub_guard(plan, None)
        guard_module.stub_guard(plan, None)
    assert [r.message for r in caplog.records].count(MESSAGE) == 1
