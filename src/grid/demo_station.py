"""The station the demo API controls: the mock station, or the one built for the map.

``STATION_FILE`` points at the JSON written by ``python -m src.ui.geo_build``. It has the station
(the contract's ``station_config``) and the twin settings that group its houses into feeders.
"""

import json
import os
from collections.abc import Mapping
from pathlib import Path

from src.common.contract import StationConfig
from src.common.mock_data import load_mock


def load_station(env: Mapping[str, str] | None = None) -> tuple[StationConfig, dict]:
    """Return (station, grid settings). Without STATION_FILE it is the mock station and {}."""
    env = os.environ if env is None else env
    path = env.get("STATION_FILE")
    if not path:
        return load_mock("station", StationConfig), {}
    bundle = json.loads(Path(path).read_text(encoding="utf-8"))
    grid = bundle.get("grid_config", {})
    if not isinstance(grid, dict):
        raise ValueError("grid_config in STATION_FILE must be an object")
    return StationConfig.model_validate(bundle["station"]), grid
