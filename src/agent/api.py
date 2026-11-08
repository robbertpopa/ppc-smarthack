import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel

from src.agent.service import AgentService, ServiceError
from src.agent.sources import floor_to_half_hour
from src.agent.wiring import build_service
from src.common.config import Settings

STATUS = {"not_found": 404, "conflict": 409, "kill_switch_active": 409}


class ProposeRequest(BaseModel):
    interval_start: AwareDatetime | None = None
    actor: str = "agent"


class DecisionRequest(BaseModel):
    actor: str


class KillRequest(BaseModel):
    on: bool
    actor: str


def create_app(settings: Settings | None = None, service: AgentService | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if service is None:
        service = build_service(settings)
    app = FastAPI(title="PPC dynamic export limits: agent API", version="0.1.0")

    def require_token(x_demo_token: str | None = Header(default=None)) -> None:
        expected = settings.demo_token
        if not expected:
            if settings.app_env == "cloud":
                raise HTTPException(status_code=503, detail="writes disabled: no demo token")
            return
        if x_demo_token is None or not hmac.compare_digest(
            x_demo_token.encode(), expected.encode()
        ):
            raise HTTPException(status_code=403, detail="demo token required")

    @app.exception_handler(ServiceError)
    def service_error(_, exc: ServiceError):
        return JSONResponse(
            {"error": exc.code, "message": exc.message}, status_code=STATUS.get(exc.code, 400)
        )

    @app.get("/health")
    def health():
        return {"status": "ok", "app_env": settings.app_env, "source": settings.source}

    @app.get("/station")
    def station():
        return service.station

    @app.get("/forecast")
    def forecast(interval_start: AwareDatetime | None = Query(default=None)):
        when = interval_start or floor_to_half_hour()
        found = service.source.forecast(service.station.pt_id, when)
        if found is None:
            raise HTTPException(status_code=404, detail="no forecast")
        return found

    @app.get("/grid_state")
    def grid_state(interval_start: AwareDatetime | None = Query(default=None)):
        when = interval_start or floor_to_half_hour()
        found = service.source.grid_state(service.station.pt_id, when)
        if found is None:
            raise HTTPException(status_code=404, detail="no grid state")
        return found

    @app.get("/prices")
    def prices(interval_start: AwareDatetime | None = Query(default=None)):
        return service.price_view(interval_start or floor_to_half_hour())

    @app.post("/plan/propose", dependencies=[Depends(require_token)])
    def propose(body: ProposeRequest | None = None):
        body = body or ProposeRequest()
        return service.propose(body.interval_start or floor_to_half_hour(), body.actor)

    @app.get("/plans")
    def plans(status: str | None = None):
        return service.plans(status)

    @app.get("/plan/{plan_id}")
    def plan(plan_id: str):
        return service.get(plan_id)

    @app.post("/plan/{plan_id}/approve", dependencies=[Depends(require_token)])
    def approve(plan_id: str, body: DecisionRequest):
        return service.approve(plan_id, body.actor)

    @app.post("/plan/{plan_id}/reject", dependencies=[Depends(require_token)])
    def reject(plan_id: str, body: DecisionRequest):
        return service.reject(plan_id, body.actor)

    @app.post("/plan/{plan_id}/execute", dependencies=[Depends(require_token)])
    def execute(plan_id: str, body: DecisionRequest):
        return service.execute(plan_id, body.actor)

    @app.get("/queue")
    def queue():
        return service.queue()

    @app.post("/kill_switch", dependencies=[Depends(require_token)])
    def kill_switch(body: KillRequest):
        return service.kill_switch(body.on, body.actor)

    @app.get("/kill_switch")
    def kill_switch_state():
        return {"on": service.kill_active}

    @app.get("/log")
    def log(limit: int = Query(default=100, ge=1, le=1000)):
        return service.log.read(limit)

    return app


app = create_app()
