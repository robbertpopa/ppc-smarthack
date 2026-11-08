# tests/test_ui_replay_routes.py
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from src.common.config import Settings
from src.ui.app import create_app


class ReplayRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = TestClient(create_app(Settings(artifact_uri=self.tmp.name)))

    def write(self, name, text):
        path = Path(self.tmp.name) / "replay" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_root_is_the_replay_page_and_operator_is_the_old_screen(self):
        root = self.client.get("/").text
        for needle in ('id="mapHost"', "window.StationMap", "/replay/index", "Before", "After"):
            self.assertIn(needle, root)
        self.assertIn("Station operator screen", self.client.get("/operator").text)

    def test_not_built_gives_404(self):
        for path in ("/replay/index", "/replay/geo", "/replay/audit", "/replay/day/2013-05-01"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404)
            self.assertFalse(response.json()["available"])

    def test_files_are_served_as_written(self):
        self.write("index.json", json.dumps({"pt_id": "PT-A"}))
        self.write("geo.geojson", json.dumps({"type": "FeatureCollection", "features": []}))
        self.write("days/2013-05-01.json", json.dumps({"date": "2013-05-01"}))
        self.assertEqual(self.client.get("/replay/index").json()["pt_id"], "PT-A")
        self.assertEqual(self.client.get("/replay/geo").json()["type"], "FeatureCollection")
        self.assertEqual(self.client.get("/replay/day/2013-05-01").json()["date"], "2013-05-01")

    def test_a_malformed_date_is_refused_and_cannot_escape(self):
        self.write("index.json", "{}")
        for bad in ("2013-5-1", "..", "2013-05-01.json", "2013-05-01%2F.."):
            self.assertIn(self.client.get(f"/replay/day/{bad}").status_code, (404, 422))

    def test_an_unreadable_file_is_a_502(self):
        self.write("index.json", "{not json")
        self.assertEqual(self.client.get("/replay/index").status_code, 502)
