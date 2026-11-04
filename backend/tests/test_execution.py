import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wacc_backend.engine import TaskEngine  # noqa: E402
from wacc_backend.execution.approvals import Approvals, mask  # noqa: E402
from wacc_backend.execution.executor import ExecutionKilled, FakeExecutor, RealExecutor, safe_env  # noqa: E402
from wacc_backend.execution.policy import (  # noqa: E402
    ALLOW, APPROVAL, DELETE, DENY, FINANCIAL, INSTALL, NETWORK, PERSONAL_FILES, PUBLISH, READ, RUN_ALLOWLIST,
    SECRET_EXPORT, SYSTEM_CHANGE, WRITE_PROJECT, classify)
from wacc_backend.execution.service import EmergencyStop, ExecutionService  # noqa: E402
from wacc_backend.storage import Storage, StorageError  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.root = base / "proj"
        (self.root / "data").mkdir(parents=True)
        (self.root / "backend" / "wacc_backend" / "execution").mkdir(parents=True)
        (self.root / "docs").mkdir()
        (self.root / ".git").mkdir()
        (self.root / "notes.txt").write_text("hello", encoding="utf-8")
        (self.root / "data" / "tokens.json").write_text("{}", encoding="utf-8")
        (self.root / ".env").write_text("K=V", encoding="utf-8")
        self.outside = base / "outside"
        self.outside.mkdir()
        (self.outside / "secret.txt").write_text("private", encoding="utf-8")
        self.storage = Storage(base / "b.db")
        self.engine = TaskEngine(self.storage)
        self.approvals = Approvals(self.storage)
        self.hubdata = base / "hubdata"
        self.stop = EmergencyStop(self.hubdata, self.engine, self.approvals)

    def tearDown(self):
        self.tmp.cleanup()

    def service(self, executor=None, roots=None):
        self.fake = executor or FakeExecutor()
        return ExecutionService(self.storage, roots or [self.root], self.fake, self.stop, self.approvals)

    def c(self, action, by="claude2"):
        return classify(action, [self.root], requested_by=by)

    def run_(self, argv, **kw):
        return self.c({"type": "run", "argv": argv, **kw}, by=kw.pop("by", "claude2") if False else "claude2")

    def code(self, fn, *a, **kw):
        with self.assertRaises(StorageError) as cm:
            fn(*a, **kw)
        return cm.exception.code


class ClassifyTests(Base):
    def test_read_and_write_inside_project(self):
        d = self.c({"type": "read_file", "path": "notes.txt"})
        self.assertEqual((d.action_class, d.verdict), (READ, ALLOW))
        self.assertEqual(self.c({"type": "list_dir", "path": "."}).verdict, ALLOW)
        d = self.c({"type": "write_file", "path": "docs/a.md", "content": "x"})
        self.assertEqual((d.action_class, d.verdict), (WRITE_PROJECT, ALLOW))

    def test_paths_outside_project_are_personal_files(self):
        for path in ("../outside/secret.txt", str(self.outside / "secret.txt"), "/etc/passwd", "docs/../../outside/secret.txt"):
            d = self.c({"type": "read_file", "path": path})
            self.assertEqual((d.action_class, d.verdict), (PERSONAL_FILES, DENY), path)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported")
    def test_symlink_escape_is_blocked(self):
        try:
            os.symlink(self.outside, self.root / "link")
        except OSError:
            self.skipTest("cannot create symlink here")
        d = self.c({"type": "read_file", "path": "link/secret.txt"})
        self.assertEqual((d.action_class, d.verdict), (PERSONAL_FILES, DENY))
        self.assertEqual(self.c({"type": "write_file", "path": "link/new.txt", "content": "x"}).verdict, DENY)

    @unittest.skipUnless(os.name == "nt", "drive letters only exist on Windows")
    def test_other_drive_is_blocked(self):
        self.assertEqual(self.c({"type": "read_file", "path": "D:\\other\\file.txt"}).verdict, DENY)

    def test_bad_path_values(self):
        for path in ("", "  ", "a\x00b", "a\nb", None, 5):
            self.assertEqual(self.c({"type": "read_file", "path": path}).verdict, DENY, repr(path))

    def test_secret_files_and_data_dir_are_denied(self):
        for path in ("data/tokens.json", ".env", "data/hub.db", "keys/server.pem", "data/backend_token.txt"):
            d = self.c({"type": "read_file", "path": path})
            self.assertEqual((d.action_class, d.verdict), (SECRET_EXPORT, DENY), path)
        self.assertEqual(self.c({"type": "write_file", "path": ".env", "content": "x"}).verdict, DENY)

    def test_git_internals_are_protected(self):
        self.assertEqual(self.c({"type": "write_file", "path": ".git/config", "content": "x"}).verdict, DENY)

    def test_write_limits_and_protected_files(self):
        self.assertEqual(self.c({"type": "write_file", "path": "a.txt", "content": "x" * 2_000_001}).verdict, DENY)
        self.assertEqual(self.c({"type": "write_file", "path": "a.txt", "content": 5}).verdict, DENY)
        for path in ("backend/wacc_backend/execution/policy.py", "docs/EXECUTION_SECURITY.md", ".gitignore"):
            d = self.c({"type": "write_file", "path": path, "content": "x"})
            self.assertEqual((d.action_class, d.verdict), (SYSTEM_CHANGE, APPROVAL), path)

    def test_delete_always_needs_approval(self):
        d = self.c({"type": "delete_path", "path": "notes.txt"})
        self.assertEqual((d.action_class, d.verdict), (DELETE, APPROVAL))
        self.assertEqual(self.c({"type": "delete_path", "path": "../outside"}).verdict, DENY)

    def test_run_allowlist(self):
        for argv in (["git", "status"], ["git", "commit", "-m", "fix: a/b path"], ["git", "add", "."],
                     ["dart", "format", "."], ["adb", "devices"],
                     ["node", "--version"], ["python.exe", "--version"]):
            d = self.c({"type": "run", "argv": argv})
            self.assertEqual((d.action_class, d.verdict), (RUN_ALLOWLIST, ALLOW), argv)

    def test_running_project_code_needs_approval_unless_opted_in(self):
        for argv in (["python", "-m", "pytest", "backend"], ["python3", "-m", "unittest"], ["flutter", "test"],
                     ["flutter", "build", "apk", "--release"], ["dart", "test"],
                     ["python", "-m", "compileall", "backend"], ["flutter", "analyze"], ["dart", "analyze"]):
            d = self.c({"type": "run", "argv": argv})
            self.assertEqual(d.verdict, APPROVAL, argv)
            opted = classify({"type": "run", "argv": argv}, [self.root], auto_run_code=True)
            self.assertEqual((opted.action_class, opted.verdict), (RUN_ALLOWLIST, ALLOW), argv)

    def test_service_flag_controls_code_running_approval(self):
        argv = ["python", "-m", "pytest", "backend"]
        svc = self.service()
        self.assertEqual(svc.submit("claude2", {"type": "run", "argv": argv}).get("status"), "APPROVAL_REQUIRED")
        auto = ExecutionService(self.storage, [self.root], self.fake, self.stop, self.approvals, auto_run_code=True)
        self.assertNotEqual(auto.submit("claude2", {"type": "run", "argv": argv}).get("status"), "APPROVAL_REQUIRED")

    def test_run_install_needs_approval(self):
        for argv in (["pip", "install", "requests"], ["python", "-m", "pip", "install", "x"], ["flutter", "pub", "get"],
                     ["npm", "install"], ["dart", "pub", "add", "http"]):
            d = self.c({"type": "run", "argv": argv})
            self.assertEqual((d.action_class, d.verdict), (INSTALL, APPROVAL), argv)

    def test_git_publish_and_destructive_rules(self):
        d = self.c({"type": "run", "argv": ["git", "push", "origin", "task/x"]})
        self.assertEqual((d.action_class, d.verdict), (PUBLISH, APPROVAL))
        for argv in (["git", "push", "--force", "origin", "task/x"], ["git", "push", "-f"], ["git", "push", "origin", "+task/x"],
                     ["git", "push", "origin", "--delete", "task/x"]):
            self.assertEqual(self.c({"type": "run", "argv": argv}).verdict, DENY, argv)
        self.assertEqual(self.c({"type": "run", "argv": ["git", "push", "origin", "main"]}, by="claude2").verdict, DENY)
        self.assertEqual(self.c({"type": "run", "argv": ["git", "push", "origin", "HEAD:main"]}, by="claude3").verdict, DENY)
        self.assertEqual(self.c({"type": "run", "argv": ["git", "push", "origin", "main"]}, by="claude1").verdict, APPROVAL)
        for argv in (["git", "reset", "--hard"], ["git", "clean", "-fd"], ["git", "checkout", "--", "."],
                     ["git", "branch", "-D", "x"], ["git", "rebase", "main"]):
            d = self.c({"type": "run", "argv": argv})
            self.assertEqual((d.action_class, d.verdict), (DELETE, APPROVAL), argv)

    def test_git_option_injection(self):
        self.assertEqual(self.c({"type": "run", "argv": ["git", "-c", "core.sshCommand=evil", "fetch"]}).verdict, APPROVAL)
        self.assertEqual(self.c({"type": "run", "argv": ["git", "log", "--upload-pack=evil"]}).verdict, DENY)
        self.assertEqual(self.c({"type": "run", "argv": ["git", "commit", "--amend"]}).verdict, APPROVAL)
        self.assertEqual(self.c({"type": "run", "argv": ["git", "commit", "--no-verify", "-m", "x"]}).verdict, APPROVAL)

    def test_unknown_programs_and_paths_to_executables(self):
        d = self.c({"type": "run", "argv": ["evil"]})
        self.assertEqual((d.action_class, d.verdict), (SYSTEM_CHANGE, APPROVAL))
        for argv in (["./evil.exe"], ["C:\\Windows\\System32\\cmd.exe"], ["/bin/sh", "-c", "id"]):
            self.assertEqual(self.c({"type": "run", "argv": argv}).verdict, DENY, argv)
        self.assertEqual(self.c({"type": "run", "argv": ["python", "script.py"]}).verdict, APPROVAL)
        self.assertEqual(self.c({"type": "run", "argv": ["powershell", "-Command", "x"]}).verdict, APPROVAL)

    def test_run_argument_validation(self):
        for argv in ([], "git status", ["git", 5], ["git", ""], ["git", "a\nb"], ["git"] + ["x"] * 80, ["git", "a" * 2001]):
            self.assertEqual(self.c({"type": "run", "argv": argv}).verdict, DENY, repr(argv)[:40])

    def test_run_cwd_and_path_arguments_stay_inside(self):
        self.assertEqual(self.c({"type": "run", "argv": ["git", "status"], "cwd": str(self.outside)}).action_class, PERSONAL_FILES)
        self.assertEqual(self.c({"type": "run", "argv": ["python", "-m", "pytest", "/etc"]}).verdict, DENY)
        self.assertEqual(self.c({"type": "run", "argv": ["python", "-m", "pytest", "../outside"]}).verdict, DENY)
        d = self.c({"type": "run", "argv": ["git", "add", "data/tokens.json"]})
        self.assertEqual((d.action_class, d.verdict), (SECRET_EXPORT, DENY))
        self.assertEqual(self.c({"type": "run", "argv": ["git", "add", ".env"]}).verdict, DENY)

    def test_network_rules(self):
        for url in ("https://pypi.org/simple/x", "https://files.pythonhosted.org/a", "https://docs.github.com/x"):
            d = self.c({"type": "http_get", "url": url})
            self.assertEqual((d.action_class, d.verdict), (NETWORK, ALLOW), url)
        for url in ("https://evil.com/x", "https://pypi.org.evil.com/x"):
            self.assertEqual(self.c({"type": "http_get", "url": url}).verdict, APPROVAL, url)
        for url in ("http://pypi.org/x", "https://127.0.0.1/x", "https://192.168.1.1/", "https://localhost/", "https://[::1]/",
                    "https://user:pw@pypi.org/", "https://printer.local/", "ftp://pypi.org", "", None):
            self.assertEqual(self.c({"type": "http_get", "url": url}).verdict, DENY, url)

    def test_unsupported_and_malformed_actions_are_denied(self):
        for action in ({"type": "format_disk"}, {"type": "pay", "amount": 5}, {}, {"type": 5}, "rm -rf /", None, []):
            self.assertEqual(self.c(action).verdict, DENY, repr(action))

    def test_hash_is_stable_and_content_sensitive(self):
        a = self.c({"type": "write_file", "path": "a.txt", "content": "one"})
        b = self.c({"type": "write_file", "path": "a.txt", "content": "one"})
        c = self.c({"type": "write_file", "path": "a.txt", "content": "two"})
        d = self.c({"type": "write_file", "path": "b.txt", "content": "one"})
        self.assertEqual(a.action_hash, b.action_hash)
        self.assertEqual(len({a.action_hash, c.action_hash, d.action_hash}), 3)


class ServiceTests(Base):
    def test_allowed_action_runs_and_is_audited(self):
        svc = self.service()
        r = svc.submit("claude2", {"type": "read_file", "path": "notes.txt"})
        self.assertEqual((r["status"], r["class"]), ("OK", READ))
        self.assertEqual(len(self.fake.calls), 1)
        log = self.approvals.audit_log()
        self.assertEqual((log[0]["agent"], log[0]["outcome"]), ("claude2", "OK"))

    def test_executor_receives_write_content_but_hash_covers_it(self):
        svc = self.service()
        svc.submit("claude2", {"type": "write_file", "path": "docs/a.txt", "content": "payload-text"})
        self.assertEqual(self.fake.calls[0]["content"], "payload-text")
        # the stored approval keeps only the digest, never the file body
        aid = svc.submit("claude2", {"type": "write_file", "path": ".gitignore", "content": "payload-text"})["approval_id"]
        stored = self.approvals.get(aid)["action"]
        self.assertNotIn("content", stored)
        self.assertIn("sha256", stored)
        self.approvals.decide(aid, True, "user")
        self.assertEqual(self.code(svc.submit, "claude2", {"type": "write_file", "path": ".gitignore", "content": "other"}, aid),
                         "HASH_MISMATCH")  # different body, same path: approval does not carry over

    def test_denied_action_never_reaches_executor(self):
        svc = self.service()
        r = svc.submit("claude2", {"type": "read_file", "path": "data/tokens.json"})
        self.assertEqual(r["status"], "DENIED")
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.approvals.audit_log()[0]["outcome"], "DENIED")

    def test_bad_agent_name(self):
        svc = self.service()
        for bad in ("", "  ", "x" * 41):
            self.assertEqual(self.code(svc.submit, bad, {"type": "read_file", "path": "notes.txt"}), "BAD_AGENT")

    def test_approval_full_flow(self):
        svc = self.service()
        action = {"type": "delete_path", "path": "notes.txt"}
        r = svc.submit("claude2", action)
        self.assertEqual(r["status"], "APPROVAL_REQUIRED")
        aid = r["approval_id"]
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(svc.submit("claude2", action)["approval_id"], aid)  # identical pending request is reused
        self.assertEqual(self.code(svc.submit, "claude2", action, aid), "NOT_APPROVED")  # still pending
        for who in ("claude1", "claude2", "gemini", ""):
            self.assertEqual(self.code(self.approvals.decide, aid, True, who), "FORBIDDEN")
        self.assertEqual(self.approvals.decide(aid, True, "user")["status"], "APPROVED")
        self.assertEqual(self.code(svc.submit, "claude3", action, aid), "FORBIDDEN")  # other agent cannot use it
        ok = svc.submit("claude2", action, aid)
        self.assertEqual((ok["status"], ok["approval_id"]), ("OK", aid))
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.code(svc.submit, "claude2", action, aid), "NOT_APPROVED")  # single use
        self.assertEqual(self.approvals.get(aid)["status"], "EXECUTED")

    def test_changed_action_invalidates_approval(self):
        svc = self.service()
        aid = svc.submit("claude2", {"type": "delete_path", "path": "notes.txt"})["approval_id"]
        self.approvals.decide(aid, True, "user")
        other = {"type": "delete_path", "path": "docs"}
        self.assertEqual(self.code(svc.submit, "claude2", other, aid), "HASH_MISMATCH")
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.approvals.get(aid)["status"], "APPROVED")  # not burned by the failed attempt

    def test_denied_and_expired_approvals_cannot_run(self):
        svc = self.service()
        action = {"type": "delete_path", "path": "notes.txt"}
        a1 = svc.submit("claude2", action)["approval_id"]
        self.approvals.decide(a1, False, "user")
        self.assertEqual(self.code(svc.submit, "claude2", action, a1), "NOT_APPROVED")
        a2 = svc.submit("claude2", action)["approval_id"]
        self.assertNotEqual(a1, a2)
        conn = self.storage._connect()
        conn.execute("UPDATE approvals SET expires_at='2000-01-01T00:00:00.000000Z' WHERE id=?", (a2,))
        conn.close()
        self.assertEqual(self.code(self.approvals.decide, a2, True, "user"), "BAD_STATE")
        self.assertEqual(self.approvals.get(a2)["status"], "EXPIRED")
        self.assertEqual(self.code(svc.submit, "claude2", action, a2), "NOT_APPROVED")
        self.assertEqual(self.fake.calls, [])

    def test_approved_but_expired_before_use(self):
        svc = self.service()
        action = {"type": "delete_path", "path": "notes.txt"}
        aid = svc.submit("claude2", action)["approval_id"]
        self.approvals.decide(aid, True, "user")
        conn = self.storage._connect()
        conn.execute("UPDATE approvals SET expires_at='2000-01-01T00:00:00.000000Z' WHERE id=?", (aid,))
        conn.close()
        self.assertEqual(self.code(svc.submit, "claude2", action, aid), "NOT_APPROVED")

    def test_install_is_approved_once_per_exact_action(self):
        svc = self.service()
        action = {"type": "run", "argv": ["pip", "install", "requests==2.32.0"]}
        aid = svc.submit("claude2", action)["approval_id"]
        self.approvals.decide(aid, True, "user")
        self.assertEqual(svc.submit("claude2", action, aid)["status"], "OK")
        self.assertEqual(svc.submit("claude2", action)["status"], "OK")  # same package/version: no second prompt
        newer = {"type": "run", "argv": ["pip", "install", "requests==2.33.0"]}
        self.assertEqual(svc.submit("claude2", newer)["status"], "APPROVAL_REQUIRED")  # new version asks again
        self.assertEqual(len(self.fake.calls), 2)

    def test_publish_asks_every_time(self):
        svc = self.service()
        action = {"type": "run", "argv": ["git", "push", "origin", "task/x"]}
        for _ in range(2):
            aid = svc.submit("claude2", action)["approval_id"]
            self.approvals.decide(aid, True, "user")
            self.assertEqual(svc.submit("claude2", action, aid)["status"], "OK")
        self.assertEqual(svc.submit("claude2", action)["status"], "APPROVAL_REQUIRED")

    def test_executor_failure_is_reported_and_audited(self):
        svc = self.service(FakeExecutor(fail_with=RuntimeError("boom token=hunter2")))
        r = svc.submit("claude2", {"type": "read_file", "path": "notes.txt"})
        self.assertEqual(r["status"], "ERROR")
        self.assertNotIn("hunter2", r["error"])
        self.assertEqual(self.approvals.audit_log()[0]["outcome"], "ERROR")

    def test_results_are_masked(self):
        svc = self.service(FakeExecutor(results={"read_file": {"content": "api_key=hunter2 and sk-abcdefgh12345678"}}))
        out = svc.submit("claude2", {"type": "read_file", "path": "notes.txt"})["result"]["content"]
        self.assertNotIn("hunter2", out)
        self.assertNotIn("sk-abcdefgh", out)


class EmergencyStopTests(Base):
    def test_stop_blocks_everything_and_expires_approvals(self):
        svc = self.service()
        aid = svc.submit("claude2", {"type": "delete_path", "path": "notes.txt"})["approval_id"]
        self.approvals.decide(aid, True, "user")
        out = self.stop.trigger("test")
        self.assertEqual(out["approvals_expired"], 1)
        self.assertTrue((self.hubdata / "EMERGENCY_STOP").exists())
        self.assertEqual(self.code(svc.submit, "claude2", {"type": "read_file", "path": "notes.txt"}), "EMERGENCY_STOP")
        self.assertEqual(self.code(svc.submit, "claude2", {"type": "delete_path", "path": "notes.txt"}, aid), "EMERGENCY_STOP")
        self.assertEqual(self.approvals.get(aid)["status"], "EXPIRED")
        self.assertEqual(self.fake.calls, [])
        self.stop.clear()
        self.assertFalse(self.stop.active())
        self.assertEqual(svc.submit("claude2", {"type": "read_file", "path": "notes.txt"})["status"], "OK")

    def test_hub_stop_file_alone_stops_the_backend(self):
        svc = self.service()
        self.hubdata.mkdir(parents=True, exist_ok=True)
        (self.hubdata / "EMERGENCY_STOP").write_text("hub says stop", encoding="utf-8")
        self.assertEqual(self.code(svc.submit, "claude2", {"type": "read_file", "path": "notes.txt"}), "EMERGENCY_STOP")

    def test_engine_pause_also_stops(self):
        svc = self.service()
        self.engine.set_paused(True)
        self.assertEqual(self.code(svc.submit, "claude2", {"type": "read_file", "path": "notes.txt"}), "EMERGENCY_STOP")

    def test_stop_kills_a_running_action_within_two_seconds(self):
        svc = self.service(FakeExecutor(block_seconds=10))
        holder = {}
        t = threading.Thread(target=lambda: holder.update(r=svc.submit("claude2", {"type": "read_file", "path": "notes.txt"})))
        t.start()
        time.sleep(0.3)
        started = time.monotonic()
        self.stop.trigger("kill it")
        t.join(timeout=5)
        self.assertFalse(t.is_alive())
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(holder["r"]["status"], "KILLED")
        self.assertIn("KILLED", [r["outcome"] for r in self.approvals.audit_log()])  # order vs. the STOP row is a race


class AuditTests(Base):
    def test_secrets_are_masked_in_audit(self):
        self.approvals.audit("claude2", READ, "read x token=hunter2", "ERROR", "failed with sk-abcdefgh12345678 and Bearer abc.def.ghi")
        row = self.approvals.audit_log()[0]
        blob = " ".join(str(v) for v in row.values())
        for secret in ("hunter2", "sk-abcdefgh", "abc.def.ghi"):
            self.assertNotIn(secret, blob)
        self.assertIn("[masked]", blob)
        self.assertNotIn("password123", mask("password: password123"))

    def test_audit_is_append_only(self):
        self.approvals.audit("claude2", READ, "x", "OK")
        conn = self.storage._connect()
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("UPDATE exec_audit SET outcome='HACKED'")
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM exec_audit")
        conn.close()
        self.assertEqual(self.approvals.audit_log()[0]["outcome"], "OK")


class RealExecutorTests(Base):
    def real_service(self):
        return ExecutionService(self.storage, [self.root], RealExecutor([self.root], timeout=5), self.stop, self.approvals)

    def test_write_read_list_roundtrip_is_atomic(self):
        svc = self.real_service()
        self.assertEqual(svc.submit("claude2", {"type": "write_file", "path": "docs/new/a.txt", "content": "héllo\nworld"})["status"], "OK")
        self.assertEqual((self.root / "docs/new/a.txt").read_text(encoding="utf-8"), "héllo\nworld")
        self.assertEqual([p.name for p in (self.root / "docs/new").iterdir()], ["a.txt"])  # no temp file left behind
        r = svc.submit("claude2", {"type": "read_file", "path": "docs/new/a.txt"})
        self.assertEqual(r["result"]["content"], "héllo\nworld")
        self.assertIn("a.txt", svc.submit("claude2", {"type": "list_dir", "path": "docs/new"})["result"]["entries"])

    def test_delete_moves_to_trash_and_never_erases(self):
        svc = self.real_service()
        action = {"type": "delete_path", "path": "notes.txt"}
        aid = svc.submit("claude2", action)["approval_id"]
        self.approvals.decide(aid, True, "user")
        r = svc.submit("claude2", action, aid)
        self.assertEqual(r["status"], "OK")
        self.assertFalse((self.root / "notes.txt").exists())
        moved = self.root / r["result"]["moved_to"]
        self.assertTrue(moved.exists())
        self.assertEqual(moved.read_text(encoding="utf-8"), "hello")
        self.assertEqual(moved.parent.name, "_to_delete")

    def test_project_root_cannot_be_deleted(self):
        svc = self.real_service()
        action = {"type": "delete_path", "path": "."}
        aid = svc.submit("claude2", action)["approval_id"]
        self.approvals.decide(aid, True, "user")
        r = svc.submit("claude2", action, aid)
        self.assertEqual(r["status"], "ERROR")
        self.assertTrue(self.root.exists())

    def test_process_runs_without_shell_and_returns_output(self):
        ex = RealExecutor([self.root], timeout=10)
        out = ex.run({"type": "run", "argv": [sys.executable, "-c", "print('hi')"], "cwd": str(self.root)}, lambda: False)
        self.assertEqual((out["exit_code"], out["output"].strip()), (0, "hi"))
        out = ex.run({"type": "run", "argv": [sys.executable, "-c", "import sys; sys.exit(3)"], "cwd": str(self.root)}, lambda: False)
        self.assertEqual(out["exit_code"], 3)
        meta = ex.run({"type": "run", "argv": [sys.executable, "-c", "print('a;b && c')"], "cwd": str(self.root)}, lambda: False)
        self.assertEqual(meta["output"].strip(), "a;b && c")  # metacharacters are plain data, no shell

    def test_environment_is_scrubbed(self):
        os.environ["WACC_CLOUD_LLM_KEY"] = "super-secret"
        try:
            self.assertNotIn("WACC_CLOUD_LLM_KEY", safe_env())
            ex = RealExecutor([self.root], timeout=10)
            code = "import os; print(os.environ.get('WACC_CLOUD_LLM_KEY'))"
            out = ex.run({"type": "run", "argv": [sys.executable, "-c", code], "cwd": str(self.root)}, lambda: False)
            self.assertEqual(out["output"].strip(), "None")
        finally:
            del os.environ["WACC_CLOUD_LLM_KEY"]

    def test_timeout_kills_the_process(self):
        ex = RealExecutor([self.root], timeout=1)
        started = time.monotonic()
        with self.assertRaises(ExecutionKilled) as cm:
            ex.run({"type": "run", "argv": [sys.executable, "-c", "import time; time.sleep(60)"], "cwd": str(self.root)}, lambda: False)
        self.assertIn("timeout", str(cm.exception))
        self.assertLess(time.monotonic() - started, 6)

    def test_emergency_stop_kills_a_real_process_tree(self):
        ex = RealExecutor([self.root], timeout=60)
        flag = {"stop": False}
        marker = self.root / "child_alive.txt"
        (self.root / "child.py").write_text(
            "import pathlib, sys, time\n"
            "for i in range(600):\n"
            "    time.sleep(0.1)\n"
            "    pathlib.Path(sys.argv[1]).write_text(str(i))\n", encoding="utf-8")
        (self.root / "parent.py").write_text(
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, 'child.py', sys.argv[1]])\n"
            "time.sleep(60)\n", encoding="utf-8")
        threading.Timer(1.0, lambda: flag.update(stop=True)).start()
        started = time.monotonic()
        with self.assertRaises(ExecutionKilled):
            ex.run({"type": "run", "argv": [sys.executable, "parent.py", str(marker)], "cwd": str(self.root)}, lambda: flag["stop"])
        self.assertLess(time.monotonic() - started, 5)
        time.sleep(0.5)
        seen = marker.read_text() if marker.exists() else None
        self.assertIsNotNone(seen, "the child never started, so this test proved nothing")
        time.sleep(0.8)
        self.assertEqual(marker.read_text(), seen)  # the grandchild stopped writing: the whole tree was killed

if __name__ == "__main__":
    unittest.main()
