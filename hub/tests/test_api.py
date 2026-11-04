import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fastapi.testclient import TestClient
    HAVE_API = True
except Exception:  # fastapi/httpx not installed
    HAVE_API = False

from wacc_hub.service import Hub  # noqa: E402


@unittest.skipUnless(HAVE_API, "fastapi/httpx not installed")
class ApiTests(unittest.TestCase):
    def setUp(self):
        from wacc_hub.api import create_app
        self.tmp = tempfile.TemporaryDirectory()
        self.tokens = {a: f"tok-{a}" for a in ("claude1", "claude2", "claude3", "gemini", "user")}
        self.client = TestClient(create_app(Hub(os.path.join(self.tmp.name, "h.db")), self.tokens))

    def tearDown(self):
        self.tmp.cleanup()

    def h(self, agent):
        return {"X-WACC-Token": self.tokens[agent]}

    def test_health_is_public_but_rest_needs_token(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/inbox").status_code, 401)
        self.assertEqual(self.client.get("/inbox", headers={"X-WACC-Token": "bad"}).status_code, 401)

    def test_lock_rejects_nan_ttl_and_giant_paths_cleanly(self):
        for raw in ('{"path":"a.txt","ttl":NaN}', '{"path":"a.txt","ttl":1e999}', '{"path":"%s","ttl":60}' % ("a" * 5000)):
            r = self.client.post("/locks", headers={**self.h("claude2"), "Content-Type": "application/json"}, content=raw)
            self.assertIn(r.status_code, (400, 422), raw[:30])  # a clean refusal, never a 500

    def test_negative_limits_do_not_mean_unlimited(self):
        for i in range(3):
            self.client.post("/messages", headers=self.h("claude2"),
                             json={"receiver": "claude3", "message_type": "STATUS_UPDATE", "subject": "m%d" % i})
        for path in ("/inbox", "/sent", "/feed"):
            agent = "claude3" if path == "/inbox" else "claude2"
            r = self.client.get(path + "?limit=-1", headers=self.h(agent))
            self.assertEqual(r.status_code, 200)
            self.assertLessEqual(len(r.json()), 1, path)  # clamped to at least 1, not "no limit"

    def test_sender_comes_from_token(self):
        r = self.client.post("/messages", headers=self.h("claude2"),
                             json={"receiver": "claude3", "message_type": "STATUS_UPDATE", "subject": "hi"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sender"], "claude2")
        inbox = self.client.get("/inbox?unread=true", headers=self.h("claude3")).json()
        self.assertEqual(len(inbox), 1)

    def test_task_flow_and_errors(self):
        r = self.client.post("/tasks", headers=self.h("claude2"), json={"title": "x", "owner": "claude3"})
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/tasks", headers=self.h("claude1"), json={"title": "API", "owner": "claude2"})
        self.assertEqual(r.json()["task_id"], "T-0001")
        self.assertEqual(self.client.post("/tasks/T-0001/accept", headers=self.h("claude2")).status_code, 200)
        r = self.client.post("/tasks/T-0001/status", headers=self.h("claude2"), json={"status": "COMPLETED"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"]["code"], "COMMIT_REQUIRED")

    def test_lock_conflict_returns_409(self):
        self.client.post("/locks", headers=self.h("claude2"), json={"path": "backend/"})
        r = self.client.post("/locks", headers=self.h("claude3"), json={"path": "backend/x.py"})
        self.assertEqual(r.status_code, 409)

    def test_emergency_stop_over_api(self):
        self.assertEqual(self.client.post("/system/stop", headers=self.h("claude2"), json={}).status_code, 403)
        self.assertEqual(self.client.post("/system/stop", headers=self.h("user"), json={}).status_code, 200)
        r = self.client.post("/messages", headers=self.h("claude2"),
                             json={"receiver": "claude3", "message_type": "STATUS_UPDATE", "subject": "x"})
        self.assertEqual(r.status_code, 423)
        self.assertEqual(self.client.post("/system/resume", headers=self.h("user")).status_code, 200)

    def test_audit_restricted(self):
        self.assertEqual(self.client.get("/audit", headers=self.h("claude3")).status_code, 403)
        self.assertEqual(self.client.get("/audit", headers=self.h("claude1")).status_code, 200)


if __name__ == "__main__":
    unittest.main()
