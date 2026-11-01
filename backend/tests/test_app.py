import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fastapi.testclient import TestClient
    HAVE_API = True
except Exception:
    HAVE_API = False

from wacc_backend.config import load_settings  # noqa: E402


@unittest.skipUnless(HAVE_API, "fastapi/httpx not installed")
class AppTests(unittest.TestCase):
    def setUp(self):
        from wacc_backend.app import create_app
        self.tmp = tempfile.TemporaryDirectory()
        s = load_settings({"WACC_DATA_DIR": self.tmp.name})
        self.client = TestClient(create_app(s, token="secret"))
        self.h = {"X-WACC-Token": "secret"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_health_public_rest_protected(self):
        self.assertEqual(self.client.get("/health").json()["schema_version"], 2)
        self.assertEqual(self.client.get("/projects").status_code, 401)
        self.assertEqual(self.client.get("/projects", headers={"X-WACC-Token": "nope"}).status_code, 401)

    def test_project_flow(self):
        r = self.client.post("/projects", headers=self.h, json={"name": "WACC"})
        self.assertEqual(r.status_code, 201)
        pid = r.json()["id"]
        self.assertEqual(self.client.post("/projects", headers=self.h, json={"name": "WACC"}).status_code, 409)
        self.assertEqual(self.client.patch(f"/projects/{pid}", headers=self.h, json={"status": "PAUSED"}).json()["status"], "PAUSED")
        self.assertEqual(self.client.patch(f"/projects/{pid}", headers=self.h, json={"status": "X"}).status_code, 400)
        self.assertEqual(self.client.post(f"/projects/{pid}/archive", headers=self.h).json()["status"], "ARCHIVED")
        self.assertEqual(self.client.get("/projects", headers=self.h).json(), [])
        self.assertEqual(self.client.get("/projects/999", headers=self.h).status_code, 404)

    def test_engine_and_agents_over_api(self):
        h = self.h
        self.assertEqual(self.client.get("/jobs").status_code, 401)
        j = self.client.post("/jobs", headers=h, json={"kind": "k", "title": "t", "priority": 1}).json()
        self.assertEqual(j["status"], "QUEUED")
        self.assertEqual(self.client.post("/jobs", headers=h, json={"kind": "", "title": "t"}).status_code, 400)
        job = self.client.post("/jobs/claim", headers=h, json={"worker": "w"}).json()["job"]
        self.assertEqual(job["id"], j["id"])
        self.assertEqual(self.client.post(f"/jobs/{j['id']}/complete", headers=h, json={"worker": "x"}).status_code, 403)
        done = self.client.post(f"/jobs/{j['id']}/complete", headers=h, json={"worker": "w", "result": {"ok": 1}})
        self.assertEqual(done.json()["status"], "SUCCEEDED")
        self.assertEqual(self.client.get("/jobs/summary", headers=h).json()["counts"]["SUCCEEDED"], 1)
        self.assertEqual(self.client.get("/jobs/999", headers=h).status_code, 404)
        self.assertTrue(self.client.post("/engine/pause", headers=h).json()["paused"])
        self.client.post("/jobs", headers=h, json={"kind": "k", "title": "t2"})
        self.assertIsNone(self.client.post("/jobs/claim", headers=h, json={"worker": "w"}).json()["job"])
        self.client.post("/engine/resume", headers=h)
        r = self.client.post("/agents", headers=h, json={"name": "claude2", "role": "backend", "capabilities": ["api"]})
        self.assertEqual(r.status_code, 201)
        hb = self.client.post("/agents/claude2/heartbeat", headers=h, json={"status": "BUSY"})
        self.assertEqual(hb.json()["status"], "BUSY")
        self.assertEqual(self.client.post("/agents/ghost/heartbeat", headers=h, json={}).status_code, 404)
        self.assertEqual(len(self.client.get("/agents", headers=h).json()), 1)


if __name__ == "__main__":
    unittest.main()
