import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import Response
from fastapi.testclient import TestClient

from src.common.config import Settings
from src.ui.app import create_app


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

    def test_info_reports_the_configured_api(self):
        self.assertEqual(
            self.client().get("/ui/info").json()["api_url"], "http://agent.example:9000"
        )

    def test_proxy_forwards_allowed_calls_with_the_token(self):
        client = self.client()
        with patch(
            "src.ui.app.forward", return_value=Response(b"{}", media_type="application/json")
        ) as f:
            self.assertEqual(
                client.get("/api/forecast?interval_start=2025-06-21T10:00:00Z").status_code, 200
            )
            self.assertEqual(
                f.call_args.args[0],
                "http://agent.example:9000/forecast?interval_start=2025-06-21T10:00:00Z",
            )
            client.post("/api/plan/propose", json={"actor": "x"}, headers={"x-demo-token": "t"})
            self.assertEqual(f.call_args.args[3]["x-demo-token"], "t")
            self.assertEqual(f.call_args.args[1], "POST")

    def test_proxy_refuses_other_paths_and_wrong_methods(self):
        client = self.client()
        with patch("src.ui.app.forward") as f:
            self.assertEqual(client.get("/api/openapi.json").status_code, 404)
            self.assertEqual(client.get("/api/plan/../../etc").status_code, 404)
            self.assertEqual(client.post("/api/forecast", json={}).status_code, 404)
            self.assertEqual(client.get("/api/plan/x/approve").status_code, 404)
            f.assert_not_called()

    def test_unreachable_api_is_reported(self):
        client = self.client()
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "api_unreachable")

    def test_summary_missing_gives_404_not_numbers(self):
        response = self.client().get("/eval/summary")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["available"])

    def test_summary_is_read_from_the_artifacts(self):
        client = self.client(run_id="local")
        folder = Path(self.tmp.name) / "eval" / "local"
        folder.mkdir(parents=True)
        (folder / "summary.json").write_text(
            json.dumps({"run_id": "local", "mock": True, "scenarios": {}})
        )
        body = client.get("/eval/summary").json()
        self.assertTrue(body["summary"]["mock"])

    def test_run_id_cannot_escape_the_folder(self):
        self.assertEqual(self.client(run_id="../x").get("/eval/summary").status_code, 400)


if __name__ == "__main__":
    unittest.main()
