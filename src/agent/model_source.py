import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from src.common.contract import AwareDatetime, Forecast, GridState

logger = logging.getLogger(__name__)


class ModelSource:
    def __init__(
        self,
        predict: Callable[[Any], Any],
        build_features: Callable[[Any, datetime], Any],
        station_state: Callable[[str, datetime], Any],
        grid_state_for: Callable[[str, datetime], Any],
        horizon_min: int = 60,
        explain: Callable[[Any], Any] | None = None,
    ):
        self.explain = explain
        self.predict = predict
        self.build_features = build_features
        self.station_state = station_state
        self.grid_state_for = grid_state_for
        self.horizon_min = horizon_min

    def forecast(self, pt_id: str, interval_start: AwareDatetime) -> Forecast | None:
        decision = interval_start.astimezone(timezone.utc) - timedelta(minutes=self.horizon_min)
        try:
            features = self.build_features(self.station_state(pt_id, decision), decision)
            forecast = self.predict(features)
            if not isinstance(forecast, Forecast):
                forecast = Forecast.model_validate(forecast)
        except Exception as exc:
            logger.warning("no forecast for %s at %s: %r", pt_id, interval_start, exc)
            return None
        if forecast.pt_id != pt_id or forecast.interval_start != interval_start:
            logger.warning("forecast does not match %s at %s", pt_id, interval_start)
            return None
        if forecast.available_at > decision:
            logger.warning("forecast for %s at %s is after the decision", pt_id, interval_start)
            return None
        return forecast

    def factors(self, pt_id: str, interval_start: AwareDatetime) -> dict | None:
        """Top factors and similar cases for the forecast; None when unavailable."""
        if self.explain is None:
            return None
        decision = interval_start.astimezone(timezone.utc) - timedelta(minutes=self.horizon_min)
        try:
            return self.explain(self.build_features(self.station_state(pt_id, decision), decision))
        except Exception as exc:
            logger.warning("no explanation for %s at %s: %r", pt_id, interval_start, exc)
            return None

    def grid_state(self, pt_id: str, interval_start: AwareDatetime) -> GridState:
        state = None
        try:
            state = self.grid_state_for(pt_id, interval_start)
            if state is not None and not isinstance(state, GridState):
                state = GridState.model_validate(state)
        except Exception as exc:
            logger.warning("no grid state for %s at %s: %r", pt_id, interval_start, exc)
            state = None
        if state is None:
            return GridState(
                pt_id=pt_id, interval_start=interval_start, converged=False, provenance="simulated"
            )
        return state
