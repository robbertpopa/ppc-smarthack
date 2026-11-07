from src.agent.explain import build_explanation
from src.common.contract import (
    AwareDatetime,
    Forecast,
    GridState,
    HouseLimit,
    Plan,
    StationConfig,
)


def plan_id_for(pt_id: str, interval_start: AwareDatetime) -> str:
    return f"PLAN-{interval_start:%Y-%m-%d-%H%M}-{pt_id}"


def make_plan(
    forecast: Forecast | None,
    grid_state: GridState | None,
    station: StationConfig,
    interval_start: AwareDatetime | None = None,
) -> Plan:
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
        explanation=build_explanation(
            source=source,
            share=share,
            static_share=station.static_share,
            spread=spread,
            threshold=station.spread_threshold,
            grid_state=grid_state,
            reason=reason_for_text,
        ),
        status="proposed",
    )
