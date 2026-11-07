import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
from threading import RLock

from src.agent.guard import Guard
from src.agent.log import ActionLog
from src.agent.planner import make_plan
from src.agent.sources import Source
from src.common.contract import ActionEvent, AwareDatetime, EventType, Plan, StationConfig


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
    ):
        self.station = station
        self.log = log
        self.guard = guard
        self.source = source
        self.clock = clock
        self._plans: dict[str, Plan] = {}
        self._reviews: list[datetime] = []
        self._kill = False
        self._lock = RLock()

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

    def _set_status(self, plan: Plan, status: str) -> Plan:
        plan = plan.model_copy(update={"status": status})
        self._plans[plan.plan_id] = plan
        return plan

    def propose(self, interval_start: AwareDatetime, actor: str = "agent") -> Plan:
        with self._lock:
            pt_id = self.station.pt_id
            forecast = self.source.forecast(pt_id, interval_start)
            grid_state = self.source.grid_state(pt_id, interval_start)
            plan = make_plan(forecast, grid_state, self.station, interval_start)
            existing = self._plans.get(plan.plan_id)
            if existing is not None and existing.status != "rejected":
                return existing
            plan = plan.model_copy(update={"guard": self.guard(plan, grid_state)})
            if not plan.guard.passed:
                plan = self._set_status(plan, "rejected")
                self._emit(plan, "guard_blocked", actor, {"violations": plan.guard.violations})
                return plan
            self._plans[plan.plan_id] = plan
            self._emit(plan, "plan_proposed", actor, {"source": plan.source})
            if plan.abstain:
                self._emit(plan, "abstained", actor, {"reasons": plan.reasons})
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
                self._reviews.append(self.clock())
                detail.update(self._review_counts())
            plan = self._set_status(plan, "approved" if approve else "rejected")
            self._emit(plan, "plan_approved" if approve else "plan_rejected", actor, detail)
            return plan

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
            plan = self._set_status(plan, "executed")
            detail = {"source": plan.source, "houses": len(plan.limits)}
            self._emit(plan, "plan_executed", actor, detail)
            return plan

    def kill_switch(self, on: bool, actor: str) -> dict:
        with self._lock:
            cancelled = []
            if on:
                for plan in list(self._plans.values()):
                    if plan.status in ("proposed", "approved"):
                        self._set_status(plan, "rejected")
                        cancelled.append(plan.plan_id)
            self._kill = on
            self._emit(
                None,
                "kill_switch",
                actor,
                {"on": on, "cancelled": cancelled, "fallback_share": self.station.static_share},
            )
            return {"on": on, "cancelled": cancelled}

    def _review_counts(self) -> dict:
        today = self.clock().date()
        reviewed = sum(1 for t in self._reviews if t.date() == today)
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
