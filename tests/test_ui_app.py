import http.client
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import Response
from fastapi.testclient import TestClient

from src.common.config import Settings
from src.ui.app import create_app, forward, is_allowed

OK = Response(b"{}", media_type="application/json")


class AllowlistTests(unittest.TestCase):
    def test_prices_is_read_only(self):
        self.assertTrue(is_allowed("GET", "prices"))
        self.assertFalse(is_allowed("POST", "prices"))

    def test_agent_reads_and_writes_are_allowed(self):
        for path in (
            "health",
            "station",
            "forecast",
            "grid_state",
            "prices",
            "plans",
            "queue",
            "log",
            "kill_switch",
            "plan/PLAN-2025-06-21-1000-PT-A",
            "plan/v1.2",
        ):
            self.assertTrue(is_allowed("GET", path), path)
        for path in (
            "plan/propose",
            "plan/PLAN-2025-06-21-1000-PT-A/approve",
            "plan/x/reject",
            "plan/x/execute",
            "kill_switch",
        ):
            self.assertTrue(is_allowed("POST", path), path)

    def test_the_whole_path_must_match(self):
        for path in (
            "health\n",
            "health/",
            "health ",
            "/health",
            "plan/..",
            "plan/.",
            "plan/.hidden",
            "plan/a..b",
            "plan/%2e%2e",
            "plan/../../etc",
            "plan/x/approve",
            "plans/x",
            "",
        ):
            self.assertFalse(is_allowed("GET", path), repr(path))
        for path in ("plan/../approve", "plan/x/approve\n", "plan/x/delete", "health", "plan/x"):
            self.assertFalse(is_allowed("POST", path), repr(path))

    def test_other_methods_are_refused(self):
        for method in ("PUT", "DELETE", "PATCH", "HEAD"):
            self.assertFalse(is_allowed(method, "health"))
            self.assertFalse(is_allowed(method, "kill_switch"))


class UiAppTests(unittest.TestCase):
    def client(self, **kwargs):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        settings = Settings(artifact_uri=self.tmp.name, api_url="http://agent.example:9000/")
        return TestClient(create_app(settings, **kwargs))

    def test_pages_are_served(self):
        client = self.client()
        self.assertIn("Station operator screen", client.get("/").text)
        self.assertEqual(client.get("/simulation").status_code, 200)

    def test_proxy_forwards_the_query_to_the_configured_api(self):
        client = self.client()
        with patch("src.ui.app.forward", return_value=OK) as f:
            response = client.get("/api/forecast?interval_start=2025-06-21T10:00:00Z")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            f.call_args.args[0],
            "http://agent.example:9000/forecast?interval_start=2025-06-21T10:00:00Z",
        )

    def test_proxy_forwards_the_kill_switch_post_with_the_token(self):
        client = self.client()
        with patch("src.ui.app.forward", return_value=OK) as f:
            client.post(
                "/api/kill_switch", json={"on": True, "actor": "x"}, headers={"x-demo-token": "t"}
            )
        url, method, body, headers = f.call_args.args
        self.assertEqual(url, "http://agent.example:9000/kill_switch")
        self.assertEqual(method, "POST")
        self.assertEqual(json.loads(body), {"on": True, "actor": "x"})
        self.assertEqual(headers["x-demo-token"], "t")

    def test_proxy_forwards_only_content_type_and_the_demo_token(self):
        client = self.client()
        with patch("src.ui.app.forward", return_value=OK) as f:
            client.post(
                "/api/plan/propose",
                json={"actor": "x"},
                headers={
                    "x-demo-token": "t",
                    "authorization": "Bearer secret",
                    "cookie": "session=1",
                    "x-forwarded-for": "1.2.3.4",
                },
            )
        self.assertEqual(set(f.call_args.args[3]), {"content-type", "x-demo-token"})

    def test_the_proxy_route_refuses_what_the_allowlist_refuses(self):
        client = self.client()
        with patch("src.ui.app.forward") as f:
            # A raw newline cannot reach the route through this client; the matcher test
            # above covers "health\n". Encoded dots do reach it, decoded to "..".
            self.assertEqual(client.get("/api/plan/%2e%2e").status_code, 404)
            self.assertEqual(client.get("/api/plan/%2e%2e/approve").status_code, 404)
            self.assertEqual(client.get("/api/openapi.json").status_code, 404)
            self.assertEqual(client.post("/api/forecast", json={}).status_code, 404)
            self.assertEqual(client.get("/api/plan/x/approve").status_code, 404)
            self.assertEqual(client.put("/api/kill_switch", json={}).status_code, 405)
            f.assert_not_called()

    def test_unreachable_api_is_a_502(self):
        response = self.client().get("/api/health")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "api_unreachable")

    def test_a_dropped_connection_is_a_502_not_a_500(self):
        for error in (
            http.client.RemoteDisconnected("closed"),
            ConnectionResetError("reset"),
            http.client.IncompleteRead(b"x"),
            TimeoutError(),
        ):
            with patch("urllib.request.urlopen", side_effect=error):
                response = forward("http://agent.example/health", "GET", None, {})
            self.assertEqual(response.status_code, 502, repr(error))

    def test_summary_missing_gives_404_not_numbers(self):
        response = self.client().get("/eval/summary")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["available"])

    def write_summary(self, run_id):
        folder = Path(self.tmp.name) / "eval" / run_id
        folder.mkdir(parents=True)
        (folder / "summary.json").write_text(
            json.dumps({"run_id": run_id, "mock": True, "scenarios": {}})
        )

    def test_summary_is_read_from_the_artifacts(self):
        client = self.client()
        self.write_summary("local")
        self.assertTrue(client.get("/eval/summary").json()["summary"]["mock"])

    def test_run_id_comes_from_the_environment(self):
        with patch.dict(os.environ, {"EVAL_RUN_ID": "run-2.1"}):
            client = self.client()
        self.write_summary("run-2.1")
        self.assertEqual(client.get("/eval/summary").json()["summary"]["run_id"], "run-2.1")

    def test_geo_missing_gives_404(self):
        response = self.client().get("/geo/station")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["available"])

    def write_geo(self, text):
        folder = Path(self.tmp.name) / "geo"
        folder.mkdir(parents=True)
        (folder / "station.geojson").write_text(text, encoding="utf-8")

    def test_geo_is_read_from_the_artifacts(self):
        client = self.client()
        self.write_geo('{"type": "FeatureCollection", "features": []}')
        body = client.get("/geo/station").json()
        self.assertTrue(body["available"])
        self.assertEqual(body["geojson"]["type"], "FeatureCollection")

    def test_unreadable_geo_is_a_502(self):
        client = self.client()
        self.write_geo("{not json")
        self.assertEqual(client.get("/geo/station").status_code, 502)

    def test_map_module_is_optional_and_its_folder_is_served(self):
        client = self.client()
        self.assertEqual(client.get("/static/map/map.js").status_code, 404)
        self.assertEqual(client.get("/static/map/README.md").status_code, 200)
        self.assertEqual(client.get("/static/map/../index.html").status_code, 404)

    def test_the_page_has_the_map_slot_and_keeps_the_simulation_notice(self):
        page = self.client().get("/").text
        needles = ('id="mapHost"', "window.StationMap", "/static/map/map.js", "Simulated data")
        for needle in needles:
            self.assertIn(needle, page)

    def test_ai_insight_is_a_labelled_mock_until_a_real_file_exists(self):
        client = self.client()
        body = client.get("/ai/insight?plan_id=PLAN-1").json()
        self.assertTrue(body["mock"])
        self.assertTrue(body["insight"]["drivers"])
        folder = Path(self.tmp.name) / "ai"
        folder.mkdir()
        (folder / "PLAN-1.json").write_text('{"drivers": []}', encoding="utf-8")
        real = client.get("/ai/insight?plan_id=PLAN-1").json()
        self.assertFalse(real["mock"])
        self.assertEqual(real["insight"], {"drivers": []})
        self.assertTrue(client.get("/ai/insight?plan_id=PLAN-2").json()["mock"])

    def test_ai_insight_plan_id_cannot_escape_the_folder(self):
        client = self.client()
        for bad in ("..", "../x", ".hidden", "a/b"):
            self.assertEqual(client.get("/ai/insight", params={"plan_id": bad}).status_code, 400)

    def test_run_id_cannot_escape_the_eval_folder(self):
        for bad in ("..", "../x", ".", ".hidden", "a/b", "x\n"):
            self.assertEqual(self.client(run_id=bad).get("/eval/summary").status_code, 400, bad)


if __name__ == "__main__":
    unittest.main()
