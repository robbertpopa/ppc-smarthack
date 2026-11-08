"""Wiring for SOURCE=model: real model, real labels history, real guard.

Heavy imports (ml, grid) stay inside the functions so the mock path loads none of them.
"""

import logging
from datetime import datetime, timezone
from functools import lru_cache

from src.agent.model_source import ModelSource
from src.common.config import Settings
from src.common.contract import GridState, House, StationConfig
from src.common.mock_data import load_mock

logger = logging.getLogger(__name__)

UNCAPPED_KW = 1e6
TRANSFORMER_KVA = 400.0  # the labels are generated for this transformer
AMBIENT_C = 20.0  # assumed constant: no measured temperature in the data
HISTORY_STEPS = 48  # 24 hours of half hours warm up the thermal state
STEP_MIN = 30.0


def hotspot_c(ratios: list[float], ambient_c: float = AMBIENT_C) -> float | None:
    """Hot-spot temperature after a run of load ratios, starting from steady state.

    Uses the IEC 60076-7 model in ``src.grid.thermal`` with assumed parameters.
    """
    from src.grid import thermal

    if not ratios:
        return None
    state = thermal.steady_state(ratios[0], ambient_c)
    for ratio in ratios[1:]:
        state = thermal.step(state, ratio, ambient_c, STEP_MIN)
    return state.hotspot_c


# ``night`` is not checked live: at night there is no PV, so no export limit can bind, and
# abstaining would send every night interval to the crew and use up its daily budget.
LIVE_SKIPPED_FLAGS = frozenset({"night"})


def live_input_flags(features: dict) -> list[str]:
    """The training input checks (``abstention.quality_flags``) that force a live abstention."""
    from src.ml.abstention import quality_flags

    return [f for f in quality_flags(features) if f not in LIVE_SKIPPED_FLAGS]


def load_station(settings: Settings) -> StationConfig:
    """Houses of the scenario's station; other settings keep the mock defaults."""
    from src.ml import labels as labels_io

    houses = labels_io.load_station_houses(settings.scenario)
    base = load_mock("station", StationConfig)
    return base.model_copy(
        update={
            "pt_id": labels_io.pt_id(settings.scenario),
            "houses": [
                House(house_id=str(r.house_id), kwp=float(r.kwp)) for r in houses.itertuples()
            ],
        }
    )


def make_model_source(settings: Settings, station: StationConfig) -> ModelSource:
    from src.grid.twin import build_grid, power_flow
    from src.ml import features
    from src.ml import labels as labels_io
    from src.ml.explain import explain
    from src.ml.predict import predict

    @lru_cache(maxsize=1)
    def history():
        return labels_io.load(settings.scenario)

    houses = [h.model_dump(exclude_none=True) for h in station.houses]
    config = {"pt_id": station.pt_id, "houses": houses}
    grid = build_grid(config)
    total_kwp = sum(h.kwp for h in station.houses)

    def station_state(pt_id: str, t: datetime):
        frame = history()
        return frame[frame["pt_id"] == pt_id]

    def grid_state_for(pt_id: str, interval_start: datetime):
        """Power flow on the last reading known one hour before the interval, uncapped."""
        decision = interval_start.astimezone(timezone.utc)
        frame = history()
        seen = frame[(frame["pt_id"] == pt_id) & (frame["available_at"] <= decision)]
        if seen.empty:
            return None
        last = seen.iloc[-1]
        recent = seen.tail(HISTORY_STEPS)
        injections = {
            "interval_start": interval_start.isoformat(),
            "houses": [
                {
                    "house_id": h.house_id,
                    "load_kw": float(last["load_kw"]) / len(station.houses),
                    "pv_kw": float(last["pv_kw"]) * h.kwp / total_kwp,
                    "export_limit_kw": UNCAPPED_KW,
                }
                for h in station.houses
            ],
        }
        state = power_flow(grid, injections)
        state.pop("interval_start", None)
        if state.get("converged") and state.get("trafo_loading_pct") is not None:
            ratios = [
                abs(float(r.load_kw) - float(r.pv_kw)) / TRANSFORMER_KVA
                for r in recent.iloc[:-1].itertuples()
            ] + [state["trafo_loading_pct"] / 100]
            state["trafo_hotspot_c"] = hotspot_c(ratios)
        return GridState(interval_start=interval_start, **state)

    return ModelSource(
        predict,
        features.build,
        station_state,
        grid_state_for,
        explain=explain,
        input_flags=live_input_flags,
    )
