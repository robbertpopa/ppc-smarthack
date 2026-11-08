"""Operator screen server.

Serves the static page and forwards calls to the agent API, so the browser talks
to one origin (no CORS) and the API address stays in the environment (`API_URL`).
Also serves the evaluation summary written by `python -m src.eval.run`; the run
folder comes from `EVAL_RUN_ID` (default `local`).
"""

import http.client
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.common.config import Settings

STATIC = Path(__file__).parent / "static"
MOCK_INSIGHT = Path(__file__).parent / "mocks" / "ai_insight.json"
# One name or id: letters, digits, "_" and "-", optionally joined by single dots. No "." or "..".
NAME = r"[\w\-]+(?:\.[\w\-]+)*"
READ = re.compile(
    rf"(health|station|forecast|grid_state|prices|plans|plan/{NAME}|queue|log|kill_switch)"
)
WRITE = re.compile(rf"(plan/propose|plan/{NAME}/(approve|reject|execute)|kill_switch)")
RUN_ID = re.compile(NAME)
FORWARD_HEADERS = ("content-type", "x-demo-token")


def is_allowed(method: str, path: str) -> bool:
    """Whether the screen may forward this call. The whole path must match."""
    pattern = READ if method == "GET" else WRITE if method == "POST" else None
    return pattern is not None and pattern.fullmatch(path) is not None


class RevalidatedFiles(StaticFiles):
    """Static files the browser must revalidate: the map module changes while it is built."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(settings: Settings | None = None, run_id: str | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    run_id = run_id or os.environ.get("EVAL_RUN_ID", "local")
    api = settings.api_url.rstrip("/")
    app = FastAPI(title="PPC operator screen", docs_url=None, redoc_url=None)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/simulation")
    def simulation():
        return FileResponse(STATIC / "simulation.html")

    @app.get("/static/theme.css")
    def theme():
        return FileResponse(STATIC / "theme.css", media_type="text/css")

    @app.get("/eval/summary")
    def eval_summary():
        if not RUN_ID.fullmatch(run_id):
            raise HTTPException(status_code=400, detail="invalid run id")
        path = Path(settings.artifact_uri) / "eval" / run_id / "summary.json"
        if not path.is_file():
            return JSONResponse({"available": False}, status_code=404)
        try:
            return {"available": True, "summary": json.loads(path.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            raise HTTPException(status_code=502, detail="summary.json is unreadable") from None

    @app.get("/geo/station")
    def geo_station():
        """Geometry for the map slot (P4): GeoJSON at <ARTIFACT_URI>/geo/station.geojson."""
        path = Path(settings.artifact_uri) / "geo" / "station.geojson"
        if not path.is_file():
            return JSONResponse({"available": False}, status_code=404)
        try:
            return {"available": True, "geojson": json.loads(path.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            raise HTTPException(status_code=502, detail="station.geojson is unreadable") from None

    @app.get("/ai/insight")
    def ai_insight(plan_id: str | None = None):
        """What the model says about a plan: drivers and a step trace.

        Reads <ARTIFACT_URI>/ai/<plan_id>.json when it exists. Until the model side writes
        those files it returns the packaged mock, marked `mock: true` so the screen labels it.
        """
        if plan_id is not None and not RUN_ID.fullmatch(plan_id):
            raise HTTPException(status_code=400, detail="invalid plan id")
        real = Path(settings.artifact_uri) / "ai" / f"{plan_id}.json" if plan_id else None
        try:
            if real is not None and real.is_file():
                return {"mock": False, "insight": json.loads(real.read_text(encoding="utf-8"))}
            return {"mock": True, "insight": json.loads(MOCK_INSIGHT.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            raise HTTPException(status_code=502, detail="AI insight file is unreadable") from None

    # The map module (P4) lives in static/map/ and is optional: the screen works without it.
    app.mount("/static/map", RevalidatedFiles(directory=STATIC / "map"), name="map")

    @app.api_route("/api/{path:path}", methods=["GET", "POST"])
    async def proxy(path: str, request: Request):
        if not is_allowed(request.method, path):
            raise HTTPException(status_code=404, detail="not an agent endpoint")
        body = await request.body() if request.method == "POST" else None
        headers = {k: v for k, v in request.headers.items() if k in FORWARD_HEADERS}
        query = request.url.query
        target = f"{api}/{path}" + (f"?{query}" if query else "")
        # urllib blocks, so run it in the threadpool: a slow API must not stall the other routes.
        return await run_in_threadpool(forward, target, request.method, body, headers)

    return app


def forward(url: str, method: str, body: bytes | None, headers: dict) -> Response:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status, payload, ctype = resp.status, resp.read(), resp.headers.get_content_type()
    except urllib.error.HTTPError as exc:
        status, payload, ctype = exc.code, exc.read(), exc.headers.get_content_type()
    except (OSError, http.client.HTTPException):
        # URLError, timeouts, resets and dropped connections (RemoteDisconnected) all land here.
        return JSONResponse(
            {"error": "api_unreachable", "message": "The agent API did not answer."},
            status_code=502,
        )
    return Response(payload, status_code=status, media_type=ctype)


app = create_app()
