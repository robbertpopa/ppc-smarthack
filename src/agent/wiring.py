from src.agent.guard import stub_guard
from src.agent.log import open_log
from src.agent.service import AgentService
from src.agent.sources import make_source
from src.common.config import Settings
from src.common.contract import StationConfig
from src.common.mock_data import load_mock


def build_service(settings: Settings) -> AgentService:
    return AgentService(
        station=load_mock("station", StationConfig),
        log=open_log(settings.log_uri),
        guard=stub_guard,
        source=make_source(settings),
    )
