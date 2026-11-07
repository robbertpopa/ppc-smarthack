"""Operator screen server.

Serves the static page and forwards calls to the agent API, so the browser talks
to one origin (no CORS) and the API address stays in the environment (`API_URL`).
Also serves the evaluation summary written by `python -m src.eval.run`.
"""

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from src.common.config import Settings

STATIC = Path(__file__).parent / "static"
READ = re.compile(
    r"^(health|station|forecast|grid_state|plans|plan/[\w.\-]+|queue|log|kill_switch)$"
)
WRITE = re.compile(r"^(plan/propose|plan/[\w.\-]+/(approve|reject|execute)|kill_switch)$")
FORWARD_HEADERS = ("content-type", "x-demo-token")
RUN_ID = re.compile(r"^[\w.\-]+$")


def create_app(settings: Settings | None = None, run_id: str = "local") -> FastAPI:
    settings = settings or Settings.from_env()
    api = settings.api_url.rstrip("/")
    app = FastAPI(title="PPC operator screen", docs_url=None, redoc_url=None)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/simulation")
    def simulation():
        return FileResponse(STATIC / "simulation.html")

    @app.get("/ui/info")
    def info():
        return {"api_url": api, "app_env": settings.app_env}

    @app.get("/eval/summary")
    def eval_summary():
        if not RUN_ID.match(run_id):
            raise HTTPException(status_code=400, detail="invalid run id")
        path = Path(settings.artifact_uri) / "eval" / run_id / "summary.json"
        if not path.is_file():
            return JSONResponse({"available": False}, status_code=404)
        try:
            return {"available": True, "summary": json.loads(path.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            raise HTTPException(status_code=502, detail="summary.json is unreadable") from None

    @app.api_route("/api/{path:path}", methods=["GET", "POST"])
    async def proxy(path: str, request: Request):
        allowed = READ if request.method == "GET" else WRITE
        if not allowed.match(path):
            raise HTTPException(status_code=404, detail="not an agent endpoint")
        body = await request.body() if request.method == "POST" else None
        headers = {k: v for k, v in request.headers.items() if k in FORWARD_HEADERS}
        query = request.url.query
        target = f"{api}/{path}" + (f"?{query}" if query else "")
        return forward(target, request.method, body, headers)

    return app


def forward(url: str, method: str, body: bytes | None, headers: dict) -> Response:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status, payload, ctype = resp.status, resp.read(), resp.headers.get_content_type()
    except urllib.error.HTTPError as exc:
        status, payload, ctype = exc.code, exc.read(), exc.headers.get_content_type()
    except (urllib.error.URLError, TimeoutError):
        return JSONResponse(
            {"error": "api_unreachable", "message": "The agent API did not answer."},
            status_code=502,
        )
    return Response(payload, status_code=status, media_type=ctype)


app = create_app()
