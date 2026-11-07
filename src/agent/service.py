import hashlib
import logging
import math
from collections.abc import Callable
from datetime import datetime, timezone
from threading import RLock

from src.agent.guard import Guard
from src.agent.log import ActionLog
from src.agent.planner import make_plan
from src.agent.sources import Source, floor_to_half_hour
from src.common.contract import ActionEvent, AwareDatetime, EventType, Plan, StationConfig

logger = logging.getLogger(__name__)

DECISION_STATUS = {
    "plan_approved": "approved",
    "plan_rejected": "rejected",
    "plan_executed": "executed",
}


class ServiceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentService:
    def __init__(
        self,
        station: StationConfig,
        log: ActionLog,
        guard: Guard,
        source: Source,
        clock: Callable[[], datetime] = _utcnow,
        thresholds: Callable[[str], float | None] | None = None,
    ):
        self.station = station
        self.log = log
        self.guard = guard
        self.source = source
        self.clock = clock
        self.thresholds = thresholds
        self._plans: dict[str, Plan] = {}
        self._retryable: set[str] = set()
        self._reviews: list[datetime] = []
        self._kill = False
        self._lock = RLock()
        self._restore()

    def _restore(self) -> None:
        for event in self.log.read_all():
            detail = event.detail
            if event.event in ("plan_proposed", "guard_blocked") and "plan" in detail:
                plan = Plan.model_validate(detail["plan"])
                self._plans[plan.plan_id] = plan
                if event.event == "guard_blocked":
                    self._retryable.add(plan.plan_id)
                else:
                    self._retryable.discard(plan.plan_id)
            elif event.event in DECISION_STATUS and event.plan_id in self._plans:
                plan = self._plans[event.plan_id]
                self._plans[event.plan_id] = plan.model_copy(
                    update={"status": DECISION_STATUS[event.event]}
                )
                if detail.get("reason") == "kill_switch":
                    self._retryable.add(event.plan_id)
                if detail.get("abstain") and event.event != "plan_executed":
                    self._reviews.append(event.ts)
            elif event.event == "kill_switch":
                self._kill = bool(detail.get("on"))

    def _threshold_station(self) -> tuple[StationConfig, str | None]:
        if self.thresholds is None:
            return self.station, None
        pt_id = self.station.pt_id
        try:
            threshold = self.thresholds(pt_id)
        except Exception as exc:
            logger.warning("threshold lookup failed for %s: %r", pt_id, exc)
            return self.station, "abstention threshold lookup failed"
        if threshold is None:
            return self.station, None
        try:
            value = float(threshold)
        except (TypeError, ValueError):
            value = math.nan
        if not math.isfinite(value) or value <= 0:
            logger.warning("unusable threshold for %s: always abstaining", pt_id)
            return self.station, "no usable abstention threshold"
        return self.station.model_copy(update={"spread_threshold": value}), None

    def _emit(self, plan: Plan | None, event: EventType, actor: str, detail: dict) -> None:
        sha = hashlib.sha256(plan.model_dump_json().encode()).hexdigest()[:16] if plan else None
        self.log.append(
            ActionEvent(
                ts=self.clock(),
                plan_id=plan.plan_id if plan else None,
                event=event,
                actor=actor,
                detail=detail,
                plan_sha=sha,
            )
        )

    def _get(self, plan_id: str) -> Plan:
        plan = self._plans.get(plan_id)
        if plan is None:
            raise ServiceError("not_found", f"unknown plan {plan_id}")
        return plan

    def _transition(
        self, plan: Plan, status: str, event: EventType, actor: str, detail: dict
    ) -> Plan:
        moved = plan.model_copy(update={"status": status})
        self._emit(moved, event, actor, detail)
        self._plans[moved.plan_id] = moved
        return moved

    def propose(self, interval_start: AwareDatetime, actor: str = "agent") -> Plan:
        with self._lock:
            interval_start = floor_to_half_hour(interval_start.astimezone(timezone.utc))
            pt_id = self.station.pt_id
            forecast = self.source.forecast(pt_id, interval_start)
            grid_state = self.source.grid_state(pt_id, interval_start)
            station, forced = self._threshold_station()
            plan = make_plan(forecast, grid_state, station, interval_start, force_abstain=forced)
            existing = self._plans.get(plan.plan_id)
            if existing is not None and not (
                existing.status == "rejected" and plan.plan_id in self._retryable
            ):
                return existing
            plan = plan.model_copy(update={"guard": self.guard(plan, grid_state)})
            if not plan.guard.passed:
                plan = plan.model_copy(update={"status": "rejected"})
                detail = {"violations": plan.guard.violations, "plan": plan.model_dump(mode="json")}
                self._emit(plan, "guard_blocked", actor, detail)
                self._plans[plan.plan_id] = plan
                self._retryable.add(plan.plan_id)
                return plan
            detail = {"source": plan.source, "plan": plan.model_dump(mode="json")}
            self._emit(plan, "plan_proposed", actor, detail)
            if plan.abstain:
                self._emit(plan, "abstained", actor, {"reasons": plan.reasons})
            self._plans[plan.plan_id] = plan
            self._retryable.discard(plan.plan_id)
            return plan

    def _decide(self, plan_id: str, actor: str, approve: bool) -> Plan:
        with self._lock:
            plan = self._get(plan_id)
            if plan.status != "proposed":
                raise ServiceError("conflict", f"plan is {plan.status}, not proposed")
            if approve and (plan.guard is None or not plan.guard.passed):
                raise ServiceError("conflict", "plan did not pass the guard")
            detail: dict = {"abstain": plan.abstain}
            if plan.abstain:
                detail.update(self._review_counts(extra=1))
            moved = self._transition(
                plan,
                "approved" if approve else "rejected",
                "plan_approved" if approve else "plan_rejected",
                actor,
                detail,
            )
            if plan.abstain:
                self._reviews.append(self.clock())
            return moved

    def approve(self, plan_id: str, actor: str) -> Plan:
        return self._decide(plan_id, actor, True)

    def reject(self, plan_id: str, actor: str) -> Plan:
        return self._decide(plan_id, actor, False)

    def execute(self, plan_id: str, actor: str) -> Plan:
        with self._lock:
            plan = self._get(plan_id)
            if self._kill:
                raise ServiceError("kill_switch_active", "kill switch is active")
            if plan.status != "approved":
                raise ServiceError("conflict", f"plan is {plan.status}, not approved")
            detail = {"source": plan.source, "houses": len(plan.limits)}
            return self._transition(plan, "executed", "plan_executed", actor, detail)

    def kill_switch(self, on: bool, actor: str) -> dict:
        with self._lock:
            cancelled = []
            if on:
                for plan in list(self._plans.values()):
                    if plan.status in ("proposed", "approved"):
                        self._transition(
                            plan, "rejected", "plan_rejected", actor, {"reason": "kill_switch"}
                        )
                        self._retryable.add(plan.plan_id)
                        cancelled.append(plan.plan_id)
            self._emit(
                None,
                "kill_switch",
                actor,
                {"on": on, "cancelled": cancelled, "fallback_share": self.station.static_share},
            )
            self._kill = on
            return {"on": on, "cancelled": cancelled}

    def _review_counts(self, extra: int = 0) -> dict:
        today = self.clock().date()
        reviewed = extra + sum(1 for t in self._reviews if t.date() == today)
        budget = self.station.review_budget
        return {
            "reviewed_today": reviewed,
            "review_budget": budget,
            "over_budget": reviewed > budget,
        }

    def queue(self) -> dict:
        with self._lock:
            pending = [p for p in self._plans.values() if p.abstain and p.status == "proposed"]
            counts = self._review_counts()
            counts["remaining"] = max(0, counts["review_budget"] - counts["reviewed_today"])
            return {"pending": sorted(pending, key=lambda p: p.interval_start), **counts}

    def plans(self, status: str | None = None) -> list[Plan]:
        with self._lock:
            found = [p for p in self._plans.values() if status in (None, p.status)]
            return sorted(found, key=lambda p: p.interval_start)

    def get(self, plan_id: str) -> Plan:
        with self._lock:
            return self._get(plan_id)

    @property
    def kill_active(self) -> bool:
        return self._kill
