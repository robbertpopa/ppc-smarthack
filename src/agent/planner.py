from collections.abc import Sequence
from datetime import timezone

from src.agent.explain import build_explanation, ensure_grounded
from src.common.contract import (
    AwareDatetime,
    Forecast,
    GridState,
    HouseLimit,
    Plan,
    StationConfig,
)

# Live input checks (``src.ml.abstention.quality_flags``) as the operator reads them. The flag
# name itself goes in ``reasons``; this sentence goes in the explanation (no digits: every
# number in the text must be one of the figures).
INPUT_CHECK_TEXT = {
    "missing_net_now": "The newest net reading is missing",
    "missing_share_last": "The last known safe share is missing",
    "stale_input": "The newest reading is too old",
    "out_of_range_net": "A net reading is out of range",
}


def plan_id_for(pt_id: str, interval_start: AwareDatetime) -> str:
    return f"PLAN-{interval_start.astimezone(timezone.utc):%Y-%m-%d-%H%M}-{pt_id}"


def make_plan(
    forecast: Forecast | None,
    grid_state: GridState | None,
    station: StationConfig,
    interval_start: AwareDatetime | None = None,
    force_abstain: str | Sequence[str] | None = None,
) -> Plan:
    """The plan for one interval. ``force_abstain`` (one reason or several) always abstains."""
    if forecast is None and interval_start is None:
        raise ValueError("interval_start is required when there is no forecast")
    if forecast is not None:
        if forecast.pt_id != station.pt_id:
            raise ValueError("forecast belongs to another station")
        interval_start = forecast.interval_start

    reasons: list[str] = []
    reason_for_text: str | None = None
    spread = forecast.spread if forecast is not None else None

    if forecast is None:
        reasons.append("no forecast available")
        reason_for_text = "No forecast is available"
    else:
        if forecast.available_at > forecast.interval_start:
            reasons.append("forecast was not available before the interval started")
            reason_for_text = "The forecast was not available in time"
        if spread > station.spread_threshold:
            reasons.append(
                f"spread {spread:.2f} above threshold {station.spread_threshold:.2f}"
            )
    if grid_state is not None and not grid_state.converged:
        reasons.append("grid state did not converge")
        reason_for_text = reason_for_text or "The grid state could not be computed"

    forced = [force_abstain] if isinstance(force_abstain, str) else list(force_abstain or ())
    bad_input = bool(forced) and forced[0] in INPUT_CHECK_TEXT
    if forced:
        reasons.extend(forced)
        first = forced[0]
        reason_for_text = reason_for_text or INPUT_CHECK_TEXT.get(first, first.capitalize())

    abstain = bool(reasons)
    if abstain:
        share, source, confidence = station.static_share, "fallback_static", 0.0
        if forecast is not None and reason_for_text is None:
            confidence = max(0.0, 1.0 - spread / (2 * station.spread_threshold))
    else:
        share = min(max(forecast.safe_cap_share.q05, 0.0), 1.0)
        source = "model"
        confidence = min(1.0, max(0.0, 1.0 - spread / (2 * station.spread_threshold)))
        reasons.append(f"spread {spread:.2f} below threshold {station.spread_threshold:.2f}")

    limits = []
    for house in station.houses:
        limit = share * house.kwp
        if house.contract_cap_kw is not None:
            limit = min(limit, house.contract_cap_kw)
        limits.append(HouseLimit(house_id=house.house_id, export_limit_kw=round(limit, 3)))

    return Plan(
        plan_id=plan_id_for(station.pt_id, interval_start),
        pt_id=station.pt_id,
        interval_start=interval_start,
        limits=limits,
        safe_cap_share_used=share,
        source=source,
        abstain=abstain,
        confidence=round(confidence, 3),
        reasons=reasons,
        explanation=ensure_grounded(
            build_explanation(
                source=source,
                share=share,
                static_share=station.static_share,
                # bad input explains the case better than the spread computed from it
                spread=None if bad_input else spread,
                threshold=station.spread_threshold,
                grid_state=grid_state,
                reason=reason_for_text,
            )
        ),
        status="proposed",
    )
