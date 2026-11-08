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
        input_flags: Callable[[Any], list[str]] | None = None,
    ):
        self.explain = explain
        self.input_flags = input_flags
        self.predict = predict
        self.build_features = build_features
        self.station_state = station_state
        self.grid_state_for = grid_state_for
        self.horizon_min = horizon_min

    def _features(self, pt_id: str, interval_start: AwareDatetime):
        """The features the model sees for this interval, built at the decision time."""
        decision = interval_start.astimezone(timezone.utc) - timedelta(minutes=self.horizon_min)
        return self.build_features(self.station_state(pt_id, decision), decision)

    def input_checks(self, pt_id: str, interval_start: AwareDatetime) -> list[str]:
        """Input check flags for the features ``forecast`` uses; any flag forces abstention.

        Empty only when no checks are wired. If the checks cannot run (the features cannot
        be built, or the checker itself fails) the result is ``["input_check_failed"]``:
        a broken check must stop the model's limit, not let it through silently.
        """
        if self.input_flags is None:
            return []
        try:
            return list(self.input_flags(self._features(pt_id, interval_start)))
        except Exception as exc:
            logger.warning("input checks failed for %s at %s: %r", pt_id, interval_start, exc)
            return ["input_check_failed"]

    def forecast(self, pt_id: str, interval_start: AwareDatetime) -> Forecast | None:
        decision = interval_start.astimezone(timezone.utc) - timedelta(minutes=self.horizon_min)
        try:
            features = self._features(pt_id, interval_start)
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
        try:
            return self.explain(self._features(pt_id, interval_start))
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
