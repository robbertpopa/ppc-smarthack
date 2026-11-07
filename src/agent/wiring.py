from src.agent.guard import stub_guard
from src.agent.log import open_log
from src.agent.service import AgentService
from src.agent.sources import make_source
from src.common.config import Settings
from src.common.contract import StationConfig
from src.common.mock_data import load_mock


def build_service(settings: Settings) -> AgentService:
    if settings.source == "model":
        from src.agent.model_wiring import load_station, make_model_source
        from src.grid.agent_guard import make_grid_guard
        from src.ml.abstention import threshold

        station = load_station(settings)
        source = make_model_source(settings, station)
        return AgentService(
            station=station,
            log=open_log(settings.log_uri),
            guard=make_grid_guard(station, source),
            source=source,
            thresholds=threshold,
        )
    return AgentService(
        station=load_mock("station", StationConfig),
        log=open_log(settings.log_uri),
        guard=stub_guard,
        source=make_source(settings),
    )
