import json
import os
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

from wacc_hub.service import Hub, HubError  # noqa: E402


class AgentAccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.hub = Hub(str(self.dir / "hub.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def code(self, fn, *a, **kw):
        with self.assertRaises(HubError) as cm:
            fn(*a, **kw)
        return cm.exception.code

    def registry(self):
        return json.loads((self.dir / "agents.json").read_text(encoding="utf-8"))

    def test_user_adds_any_kind_of_account_and_registry_is_published(self):
        row = self.hub.register_agent("user", "gpt1", "chatgpt", "", "my-openai")
        self.assertEqual((row["kind"], row["provider"], row["enabled"], row["removed"]), ("chatgpt", "my-openai", 1, 0))
        self.hub.register_agent("user", "claude4", "claude")
        names = {a["name"]: a for a in self.registry()}
        self.assertEqual(names["gpt1"]["provider"], "my-openai")
        self.assertIn("claude4", names)
        self.assertIn("claude1", names)  # built-ins are listed too
        self.assertNotIn("user", names)
        self.assertNotIn("token", json.dumps(self.registry()).lower())  # the registry is non-secret

    def test_only_the_user_manages_accounts(self):
        for fn, args in ((self.hub.register_agent, ("claude2", "x1", "claude")),
                         (self.hub.set_agent_enabled, ("claude2", "claude3", False)),
                         (self.hub.remove_agent, ("claude2", "claude3"))):
            self.assertEqual(self.code(fn, *args), "FORBIDDEN")

    def test_name_kind_and_provider_validation(self):
        for name in ("User", "user", "all", "claude1", "gemini", "x", "1abc", "a b", "a" * 21, "hub", ""):
            self.assertEqual(self.code(self.hub.register_agent, "user", name, "claude"), "BAD_NAME", name)
        self.assertEqual(self.code(self.hub.register_agent, "user", "okname", "grok"), "BAD_KIND")
        self.assertEqual(self.code(self.hub.register_agent, "user", "okname", "other", "", "Bad Provider!"), "BAD_PROVIDER")
        self.hub.register_agent("user", "okname", "other")
        self.assertEqual(self.code(self.hub.register_agent, "user", "okname", "other"), "DUPLICATE")

    def test_new_agent_can_talk_and_receives_broadcasts_until_switched_off(self):
        self.hub.register_agent("user", "gpt1", "chatgpt")
        count = lambda: self.hub.query_one("SELECT count(*) n FROM messages WHERE receiver='gpt1'")["n"]
        self.hub.send_message("claude1", "gpt1", "STATUS_UPDATE", "hello gpt")
        self.assertEqual(count(), 1)
        self.hub.send_message("claude1", "ALL", "STATUS_UPDATE", "broadcast 1")
        self.assertEqual(count(), 2)
        self.hub.send_message("gpt1", "claude1", "STATUS_UPDATE", "reply")  # it can send too
        self.hub.set_agent_enabled("user", "gpt1", False)
        self.hub.send_message("claude1", "ALL", "STATUS_UPDATE", "broadcast 2")
        self.assertEqual(count(), 2)  # switched-off agents are skipped
        self.assertEqual(self.code(self.hub.inbox, "gpt1"), "AGENT_DISABLED")
        self.assertEqual(self.code(self.hub.send_message, "gpt1", "claude1", "STATUS_UPDATE", "x"), "AGENT_DISABLED")
        self.assertEqual(self.code(self.hub.send_message, "claude1", "gpt1", "STATUS_UPDATE", "x"), "AGENT_DISABLED")
        self.assertFalse(self.hub.agent_enabled("gpt1"))
        self.hub.set_agent_enabled("user", "gpt1", True)
        self.assertTrue(self.hub.agent_enabled("gpt1"))

    def test_built_in_agents_can_be_switched_off_but_not_removed(self):
        self.hub.set_agent_enabled("user", "gemini", False)
        self.assertFalse([a for a in self.registry() if a["name"] == "gemini"][0]["enabled"])
        self.assertEqual(self.code(self.hub.remove_agent, "user", "gemini"), "NOT_REMOVABLE")
        self.assertEqual(self.code(self.hub.set_agent_enabled, "user", "user", False), "BAD_NAME")
        self.assertEqual(self.code(self.hub.send_message, "claude1", "gemini", "STATUS_UPDATE", "x"), "AGENT_DISABLED")

    def test_removing_releases_tasks_and_locks_and_keeps_history(self):
        self.hub.register_agent("user", "gpt1", "chatgpt")
        self.hub.send_message("gpt1", "claude1", "STATUS_UPDATE", "kept in history")
        task = self.hub.create_task("claude1", "Work", "d", owner="gpt1")
        self.hub.accept_task("gpt1", task["task_id"])
        self.hub.acquire_lock("gpt1", "web/", task["task_id"])
        self.assertEqual(self.hub.remove_agent("user", "gpt1"), {"removed": True, "name": "gpt1"})
        t = self.hub.list_tasks(owner=None, status="BACKLOG")
        self.assertIn(task["task_id"], [x["task_id"] for x in t])
        self.assertEqual(self.hub.list_locks(), [])
        self.assertNotIn("gpt1", [a["agent_id"] for a in self.hub.overview()])
        self.assertNotIn("gpt1", [a["name"] for a in self.registry()])
        self.assertEqual(self.code(self.hub.send_message, "claude1", "gpt1", "STATUS_UPDATE", "x"), "UNKNOWN_AGENT")
        self.assertTrue([m for m in self.hub.feed(50) if m["subject"] == "kept in history"])
        self.assertEqual(self.code(self.hub.remove_agent, "user", "gpt1"), "UNKNOWN_AGENT")

    def test_removed_name_can_be_added_again_fresh(self):
        self.hub.register_agent("user", "gpt1", "chatgpt", "Old role", "old-acc")
        self.hub.remove_agent("user", "gpt1")
        row = self.hub.register_agent("user", "gpt1", "claude", "New role")
        self.assertEqual((row["kind"], row["role"], row["provider"], row["enabled"], row["removed"]), ("claude", "New role", None, 1, 0))

    def test_old_database_without_new_columns_is_upgraded(self):
        import sqlite3
        old = self.dir / "old.db"
        conn = sqlite3.connect(str(old))
        conn.executescript("CREATE TABLE agents (agent_id TEXT PRIMARY KEY, role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OFFLINE', "
                           "current_task TEXT, last_seen TEXT, last_commit TEXT, last_message_at TEXT);"
                           "INSERT INTO agents(agent_id, role) VALUES ('claude1','TEAM_LEADER');")
        conn.commit()
        conn.close()
        hub = Hub(str(old))
        row = hub.query_one("SELECT * FROM agents WHERE agent_id='claude1'")
        self.assertEqual((row["enabled"], row["removed"], row["kind"]), (1, 0, "builtin"))
        hub.register_agent("user", "gpt1", "chatgpt")


@unittest.skipUnless(HAVE_API, "fastapi/httpx not installed")
class AgentAccountApiTests(unittest.TestCase):
    def setUp(self):
        from wacc_hub.api import create_app
        self.tmp = tempfile.TemporaryDirectory()
        self.token_file = Path(self.tmp.name) / "tokens.json"
        self.tokens = {a: f"tok-{a}" for a in ("claude1", "claude2", "claude3", "gemini", "user")}
        self.client = TestClient(create_app(Hub(os.path.join(self.tmp.name, "h.db")), self.tokens, token_path=self.token_file))
        self.u = {"X-WACC-Token": "tok-user"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_returns_a_working_token_once_and_persists_it(self):
        r = self.client.post("/agents", headers=self.u, json={"name": "gpt1", "kind": "chatgpt", "provider": "my-openai"})
        self.assertEqual(r.status_code, 201)
        token = r.json()["token"]
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(self.client.get("/whoami", headers={"X-WACC-Token": token}).json(), {"agent": "gpt1"})
        self.assertEqual(json.loads(self.token_file.read_text(encoding="utf-8"))["gpt1"], token)
        listing = self.client.get("/agents", headers=self.u).json()
        self.assertEqual([a["kind"] for a in listing if a["agent_id"] == "gpt1"], ["chatgpt"])
        self.assertNotIn(token, json.dumps(listing))

    def test_agents_cannot_manage_accounts(self):
        a = {"X-WACC-Token": "tok-claude2"}
        self.assertEqual(self.client.post("/agents", headers=a, json={"name": "evil", "kind": "claude"}).status_code, 403)
        self.assertEqual(self.client.post("/agents/gemini/enabled", headers=a, json={"enabled": False}).status_code, 403)
        self.assertEqual(self.client.delete("/agents/claude3", headers=a).status_code, 403)
        self.assertEqual(self.client.post("/agents", json={"name": "evil", "kind": "claude"}).status_code, 401)

    def test_switch_off_blocks_the_token_at_once_and_remove_revokes_it(self):
        token = self.client.post("/agents", headers=self.u, json={"name": "gpt1", "kind": "chatgpt"}).json()["token"]
        h = {"X-WACC-Token": token}
        self.assertEqual(self.client.get("/inbox", headers=h).status_code, 200)
        self.client.post("/agents/gpt1/enabled", headers=self.u, json={"enabled": False})
        off = self.client.get("/inbox", headers=h)
        self.assertEqual((off.status_code, off.json()["detail"]["code"]), (403, "AGENT_DISABLED"))
        self.client.post("/agents/gpt1/enabled", headers=self.u, json={"enabled": True})
        self.assertEqual(self.client.get("/inbox", headers=h).status_code, 200)
        self.assertEqual(self.client.delete("/agents/gpt1", headers=self.u).json()["removed"], True)
        self.assertEqual(self.client.get("/inbox", headers=h).status_code, 401)
        self.assertNotIn("gpt1", json.loads(self.token_file.read_text(encoding="utf-8")))

    def test_duplicates_builtins_and_bad_input(self):
        self.assertEqual(self.client.post("/agents", headers=self.u, json={"name": "claude1", "kind": "claude"}).status_code, 400)
        self.client.post("/agents", headers=self.u, json={"name": "gpt1", "kind": "chatgpt"})
        self.assertEqual(self.client.post("/agents", headers=self.u, json={"name": "gpt1", "kind": "chatgpt"}).status_code, 409)
        self.assertEqual(self.client.delete("/agents/gemini", headers=self.u).status_code, 409)
        self.assertEqual(self.client.post("/agents", headers=self.u, json={"name": "okname", "kind": "nope"}).status_code, 400)
        self.assertEqual(self.client.delete("/agents/ghost", headers=self.u).status_code, 404)


if __name__ == "__main__":
    unittest.main()
