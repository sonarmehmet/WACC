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
        self.assertEqual(self.client.get("/health").json()["schema_version"], 1)
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


if __name__ == "__main__":
    unittest.main()
