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
        from wacc_backend.orchestrator import MockProvider
        from wacc_backend.execution.executor import FakeExecutor
        self.fake = FakeExecutor()
        self.client = TestClient(create_app(s, token="secret", providers=[MockProvider()], executor=self.fake,
                                            user_token="human",
                                            agent_tokens={"claude2": "tok-c2", "claude3": "tok-c3"}))
        self.u = {"X-WACC-Token": "human"}
        self.h = {"X-WACC-Token": "secret"}  # legacy shared token (read-only for actions)
        self.c2 = {"X-WACC-Token": "tok-c2"}
        self.c3 = {"X-WACC-Token": "tok-c3"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_health_public_rest_protected(self):
        self.assertEqual(self.client.get("/health").json()["schema_version"], 4)
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
        hb = self.client.post("/agents/claude2/heartbeat", headers=self.c2, json={"status": "BUSY"})
        self.assertEqual(hb.json()["status"], "BUSY")
        self.assertEqual(self.client.post("/agents/ghost/heartbeat", headers=self.u, json={}).status_code, 404)
        self.assertEqual(len(self.client.get("/agents", headers=h).json()), 1)

    def test_ai_and_memory_over_api(self):
        h = self.h
        self.assertEqual(self.client.post("/ai/complete", json={"prompt": "hi"}).status_code, 401)
        r = self.client.post("/ai/complete", headers=h, json={"prompt": "hello"})
        self.assertEqual(r.json()["provider"], "mock")
        self.assertEqual(self.client.post("/ai/complete", headers=h, json={"prompt": " "}).status_code, 400)
        self.assertEqual(self.client.get("/ai/providers", headers=h).json()[0]["name"], "mock")
        self.assertEqual(self.client.get("/ai/usage", headers=h).json()["providers"][0]["calls"], 1)
        self.assertEqual(self.client.post("/ai/budget", headers=h, json={"usd": 2}).json()["budget_usd"], 2)
        self.assertEqual(self.client.post("/ai/budget", headers=h, json={"usd": -1}).status_code, 400)
        m = self.client.post("/memory", headers=h, json={"content": "hub uses sqlite", "tags": ["hub"]})
        self.assertEqual(m.status_code, 201)
        mid = m.json()["id"]
        self.assertEqual(self.client.get("/memory/search?q=sqlite", headers=h).json()[0]["id"], mid)
        self.assertEqual(self.client.get(f"/memory/{mid}", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/memory/999", headers=h).status_code, 404)
        bad = self.client.post("/memory", headers=h, json={"content": "ghp_" + "a" * 24})
        self.assertEqual(bad.status_code, 400)
        self.assertTrue(self.client.post(f"/memory/{mid}/archive", headers=h).json()["archived"])

    def test_execution_roles_and_flow(self):
        h, u = self.c2, self.u
        self.assertEqual(self.client.post("/exec", json={"agent": "a", "action": {}}).status_code, 401)
        r = self.client.post("/exec", headers=h, json={"agent": "claude2", "action": {"type": "write_file", "path": "x.txt", "content": "hi"}})
        self.assertEqual(r.json()["status"], "OK")  # root defaults to the repo folder
        d = self.client.post("/exec", headers=h, json={"agent": "claude2", "action": {"type": "read_file", "path": "data/tokens.json"}})
        self.assertEqual(d.json()["status"], "DENIED")
        req = {"agent": "claude2", "action": {"type": "delete_path", "path": "x.txt"}}
        aid = self.client.post("/exec", headers=h, json=req).json()["approval_id"]
        self.assertEqual(self.client.post(f"/exec/approvals/{aid}/approve", headers=h).status_code, 403)  # agent token cannot approve
        self.assertEqual(self.client.post(f"/exec/approvals/{aid}/approve").status_code, 401)
        self.assertEqual(self.client.post(f"/exec/approvals/{aid}/approve", headers=u).json()["status"], "APPROVED")
        done = self.client.post("/exec", headers=h, json={**req, "approval_id": aid})
        self.assertEqual(done.json()["status"], "OK")
        self.assertEqual(self.client.post("/exec", headers=h, json={**req, "approval_id": aid}).status_code, 403)
        self.assertEqual(self.client.get("/exec/audit", headers=h).json()[0]["agent"], "claude2")
        self.assertEqual(self.client.get("/exec/approvals/999", headers=h).status_code, 404)

    def test_execution_stop_and_resume(self):
        h, u = self.h, self.u
        self.assertTrue(self.client.post("/exec/stop", headers=h, json={"reason": "test"}).json()["emergency_stop"])
        blocked = self.client.post("/exec", headers=h, json={"agent": "claude2", "action": {"type": "read_file", "path": "README.md"}})
        self.assertEqual(blocked.status_code, 423)
        self.assertEqual(self.client.post("/exec/resume", headers=h).status_code, 403)  # only the user lifts it
        self.assertFalse(self.client.post("/exec/resume", headers=u).json()["emergency_stop"])
        self.assertFalse(self.client.get("/exec/status", headers=h).json()["emergency_stop"])


    def test_actions_are_attributed_by_token_not_by_request_body(self):
        read = {"type": "read_file", "path": "README.md"}
        # an agent cannot submit under another agent's name
        r = self.client.post("/exec", headers=self.c3, json={"agent": "claude2", "action": read})
        self.assertEqual(r.status_code, 403)
        self.assertIn("claude3", r.json()["detail"]["message"])
        # under its own name it works
        self.assertEqual(self.client.post("/exec", headers=self.c3, json={"agent": "claude3", "action": read}).status_code, 200)
        # the legacy shared token cannot submit actions at all
        self.assertEqual(self.client.post("/exec", headers=self.h, json={"agent": "claude2", "action": read}).status_code, 403)
        # the human may submit for testing
        self.assertEqual(self.client.post("/exec", headers=self.u, json={"agent": "claude2", "action": read}).status_code, 200)
        audit = self.client.get("/exec/audit", headers=self.u).json()
        self.assertIn("claude3", {row["agent"] for row in audit})

    def test_approval_requested_by_one_agent_cannot_be_used_by_another(self):
        req = {"agent": "claude2", "action": {"type": "delete_path", "path": "x.txt"}}
        aid = self.client.post("/exec", headers=self.c2, json=req).json()["approval_id"]
        self.client.post(f"/exec/approvals/{aid}/approve", headers=self.u)
        stolen = self.client.post("/exec", headers=self.c3, json={**req, "agent": "claude3", "approval_id": aid})
        self.assertEqual(stolen.status_code, 403)

    def test_agents_cannot_heartbeat_for_others_or_toggle_agents(self):
        self.client.post("/agents", headers=self.u, json={"name": "claude2", "role": "backend", "capabilities": []})
        self.client.post("/agents", headers=self.u, json={"name": "claude3", "role": "mobile", "capabilities": []})
        self.assertEqual(self.client.post("/agents/claude2/heartbeat", headers=self.c3, json={}).status_code, 403)
        self.assertEqual(self.client.post("/agents/claude2/heartbeat", headers=self.h, json={}).status_code, 403)
        self.assertEqual(self.client.post("/agents/claude2/enabled", headers=self.c3, json={"enabled": False}).status_code, 403)
        self.assertEqual(self.client.post("/agents/claude2/enabled", headers=self.u, json={"enabled": False}).status_code, 200)

    def test_per_agent_tokens_are_read_valid_everywhere(self):
        self.assertEqual(self.client.get("/projects", headers=self.c2).status_code, 200)
        self.assertEqual(self.client.get("/projects", headers={"X-WACC-Token": "tok-c2 "}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
