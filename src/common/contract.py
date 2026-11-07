from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Provenance = Literal["measured", "simulated", "forecast", "assumed"]
PlanSource = Literal["model", "fallback_static"]
PlanStatus = Literal["proposed", "approved", "rejected", "executed"]
EventType = Literal[
    "plan_proposed",
    "guard_blocked",
    "plan_approved",
    "plan_rejected",
    "plan_executed",
    "abstained",
    "kill_switch",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SafeCapShare(Strict):
    q05: float = Field(ge=0, le=1)
    q10: float = Field(ge=0, le=1)
    q20: float = Field(ge=0, le=1)
    q50: float = Field(ge=0, le=1)
    q90: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> "SafeCapShare":
        if not self.q05 <= self.q10 <= self.q20 <= self.q50 <= self.q90:
            raise ValueError("quantiles must not cross: q05 <= q10 <= q20 <= q50 <= q90")
        return self


class Band(Strict):
    p10: float = Field(ge=0)
    p50: float = Field(ge=0)
    p90: float = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> "Band":
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("band must not cross: p10 <= p50 <= p90")
        return self


class Forecast(Strict):
    pt_id: str
    interval_start: AwareDatetime
    horizon_min: int = Field(gt=0)
    safe_cap_share: SafeCapShare
    spread: float = Field(ge=0, le=1)
    pv_kw: Band | None = None
    load_kw: Band | None = None
    available_at: AwareDatetime
    model_version: str
    provenance: Provenance
    source_ref: str

    @model_validator(mode="after")
    def _spread_matches(self) -> "Forecast":
        expected = self.safe_cap_share.q90 - self.safe_cap_share.q05
        if abs(self.spread - expected) > 1e-3:
            raise ValueError("spread must equal safe_cap_share.q90 - safe_cap_share.q05")
        return self


class BatteryState(Strict):
    house_id: str
    soc_kwh: float = Field(ge=0)
    power_kw: float


class GridState(Strict):
    pt_id: str
    interval_start: AwareDatetime
    converged: bool
    v_max_pu: float | None = None
    v_max_node: str | None = None
    line_loading_max_pct: float | None = None
    trafo_loading_pct: float | None = None
    trafo_hotspot_c: float | None = None
    batteries: list[BatteryState] = Field(default_factory=list)
    exported_kwh: float | None = None
    curtailed_kwh: float | None = None
    provenance: Provenance


class HouseLimit(Strict):
    house_id: str
    export_limit_kw: float = Field(ge=0)
    battery_kw: float = 0.0


class GuardResult(Strict):
    passed: bool
    v_max_pu: float | None = None
    trafo_loading_pct: float | None = None
    violations: list[str] = Field(default_factory=list)


class Figure(Strict):
    name: str
    value: float


class Explanation(Strict):
    text: str
    figures: list[Figure]


class Plan(Strict):
    plan_id: str
    pt_id: str
    interval_start: AwareDatetime
    limits: list[HouseLimit]
    safe_cap_share_used: float = Field(ge=0, le=1)
    source: PlanSource
    abstain: bool
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]
    guard: GuardResult | None = None
    explanation: Explanation | None = None
    status: PlanStatus


class ActionEvent(Strict):
    ts: AwareDatetime
    plan_id: str | None = None
    event: EventType
    actor: str
    detail: dict = Field(default_factory=dict)
    plan_sha: str | None = None


class House(Strict):
    house_id: str
    kwp: float = Field(gt=0)
    contract_cap_kw: float | None = Field(default=None, gt=0)


class StationConfig(Strict):
    pt_id: str
    houses: list[House] = Field(min_length=1)
    static_share: float = Field(default=0.36, ge=0, le=1)
    spread_threshold: float = Field(default=0.30, gt=0, le=1)
    review_budget: int = Field(default=20, ge=0)
