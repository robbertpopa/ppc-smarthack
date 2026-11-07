"""The agent API with the grid guard instead of the stub guard.

Run: python -m uvicorn src.grid.demo_api:app --port 8000
Set TRANSFORMER_KVA (for example 20) to demonstrate the guard blocking an overloaded plan.
Set STATION_FILE (written by ``python -m src.ui.geo_build``) to control the three-neighbourhood
station of the map instead of the 8-house mock station.
The shared `src.agent.api:app` still uses the stub guard until P1 switches it.
"""

import os

from src.agent.api import create_app
from src.agent.log import open_log
from src.agent.service import AgentService
from src.agent.sources import make_source
from src.common.config import Settings
from src.grid.agent_guard import make_grid_guard
from src.grid.demo_station import load_station

settings = Settings.from_env()
_station, _station_grid = load_station()
_source = make_source(settings)
_grid_config = {
    **_station_grid,
    **(
        {"transformer_kva": float(os.environ["TRANSFORMER_KVA"])}
        if os.environ.get("TRANSFORMER_KVA")
        else {}
    ),
}
app = create_app(
    settings,
    AgentService(
        station=_station,
        log=open_log(settings.log_uri),
        guard=make_grid_guard(_station, _source, _grid_config),
        source=_source,
    ),
)
