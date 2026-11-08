"""Wiring for SOURCE=model: real model, real labels history, real guard.

Heavy imports (ml, grid) stay inside the functions so the mock path loads none of them.
"""

import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from functools import lru_cache

from src.agent.model_source import ModelSource
from src.common.config import Settings
from src.common.contract import GridState, House, StationConfig
from src.common.mock_data import load_mock

logger = logging.getLogger(__name__)

UNCAPPED_KW = 1e6
TRANSFORMER_KVA = 400.0  # the labels are generated for this transformer
AMBIENT_C = 20.0  # assumed when no measured temperature is known at that time
HISTORY_STEPS = 48  # 24 hours of half hours warm up the thermal state
STEP_MIN = 30.0


def hotspot_c(ratios: list[float], ambient_c: float | Sequence[float] = AMBIENT_C) -> float | None:
    """Hot-spot temperature after a run of load ratios, starting from steady state.

    Uses the IEC 60076-7 model in ``src.grid.thermal`` with assumed parameters.
    ``ambient_c`` is one temperature for every step or one per step (``ambient_at``).
    """
    from src.grid import thermal

    if not ratios:
        return None
    ambient = (
        [float(ambient_c)] * len(ratios) if isinstance(ambient_c, (int, float)) else list(ambient_c)
    )
    if len(ambient) != len(ratios):
        raise ValueError(f"{len(ratios)} load ratios but {len(ambient)} ambient temperatures")
    state = thermal.steady_state(ratios[0], ambient[0])
    for ratio, temperature in zip(ratios[1:], ambient[1:], strict=True):
        state = thermal.step(state, ratio, temperature, STEP_MIN)
    return state.hotspot_c


def ambient_at(weather, times) -> list[float]:
    """Air temperature known at each time: the newest hour with ``available_at <= time``.

    ``weather`` is ``src.ml.weather.load``'s table or None. Where nothing is known yet (no
    weather, no hour that old, or a missing value) the answer is ``AMBIENT_C``, the assumed
    constant of the grid state before measured temperature was used.
    """
    import pandas as pd

    times = pd.DatetimeIndex(times)
    if weather is None or weather.empty:
        return [AMBIENT_C] * len(times)
    known = weather.dropna(subset=["t2m_c"]).sort_values("available_at")
    asked = pd.DataFrame({"at": times, "order": range(len(times))}).sort_values("at")
    joined = pd.merge_asof(
        asked, known[["available_at", "t2m_c"]], left_on="at", right_on="available_at"
    ).sort_values("order")
    return joined["t2m_c"].fillna(AMBIENT_C).astype(float).tolist()


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
    from src.ml.weather import load as load_weather

    @lru_cache(maxsize=1)
    def history():
        return labels_io.load(settings.scenario)

    @lru_cache(maxsize=1)
    def weather():
        """Measured temperature of the station's houses, or None (then 20 C is assumed)."""
        try:
            return load_weather([h.house_id for h in station.houses])
        except (OSError, ValueError, KeyError) as error:
            logger.info("no weather for the hot-spot, assuming %.0f C: %s", AMBIENT_C, error)
            return None

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
            # the temperature known when each reading was complete; for the interval itself,
            # the temperature known at its start
            times = [*recent.iloc[:-1]["available_at"], interval_start.astimezone(timezone.utc)]
            state["trafo_hotspot_c"] = hotspot_c(ratios, ambient_at(weather(), times))
        return GridState(interval_start=interval_start, **state)

    return ModelSource(
        predict,
        features.build,
        station_state,
        grid_state_for,
        explain=explain,
        input_flags=live_input_flags,
    )
