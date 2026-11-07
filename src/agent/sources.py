import math
from datetime import datetime, timedelta, timezone
from typing import Protocol

from src.common.config import Settings
from src.common.contract import AwareDatetime, Forecast, GridState, SafeCapShare
from src.common.mock_data import load_mock


class Source(Protocol):
    def forecast(self, pt_id: str, interval_start: AwareDatetime) -> Forecast | None: ...

    def grid_state(self, pt_id: str, interval_start: AwareDatetime) -> GridState | None: ...


class MockSource:
    def __init__(self) -> None:
        self._forecast = load_mock("forecast", Forecast)
        self._grid_state = load_mock("grid_state", GridState)

    def forecast(self, pt_id: str, interval_start: AwareDatetime) -> Forecast | None:
        hour = interval_start.hour + interval_start.minute / 60
        sun = max(0.0, math.sin(math.pi * (hour - 4) / 12)) if 4 <= hour <= 16 else 0.0
        q50 = 0.90 - 0.50 * sun
        q05 = max(0.05, q50 - (0.05 + 0.30 * (1 - sun)))
        q90 = min(1.0, q50 + 0.10)
        q10 = q05 + (q50 - q05) * 0.2
        q20 = q05 + (q50 - q05) * 0.5
        share = SafeCapShare(
            q05=round(q05, 3),
            q10=round(q10, 3),
            q20=round(q20, 3),
            q50=round(q50, 3),
            q90=round(q90, 3),
        )
        return self._forecast.model_copy(
            update={
                "pt_id": pt_id,
                "interval_start": interval_start,
                "available_at": interval_start - timedelta(hours=1),
                "safe_cap_share": share,
                "spread": round(share.q90 - share.q05, 3),
            }
        )

    def grid_state(self, pt_id: str, interval_start: AwareDatetime) -> GridState | None:
        return self._grid_state.model_copy(
            update={"pt_id": pt_id, "interval_start": interval_start}
        )


def make_source(settings: Settings) -> Source:
    if settings.source == "mock":
        return MockSource()
    if settings.source == "model":
        raise NotImplementedError(
            "SOURCE=model needs ml.predict, ml.features.build and grid.power_flow, "
            "which are not merged yet"
        )
    raise NotImplementedError(f"unknown source {settings.source!r}")


def floor_to_half_hour(moment: datetime | None = None) -> datetime:
    moment = moment or datetime.now(timezone.utc)
    return moment.replace(minute=0 if moment.minute < 30 else 30, second=0, microsecond=0)
