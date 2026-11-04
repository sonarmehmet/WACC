"""Regression tests for bypasses found by attacking the policy (security review, 2026-11-04).

Each case was exploitable through actions that ran automatically (no approval)."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wacc_backend.execution.policy import ALLOW, APPROVAL, DENY, classify  # noqa: E402


@unittest.skipUnless(shutil.which("git"), "git not installed")
class PolicyAttackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        for d in ("data", "hub", "scripts", "web", "backend/wacc_backend/execution"):
            (self.root / d).mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return classify({"type": "run", "argv": ["git", *args], "cwd": str(self.root)}, [self.root], requested_by="claude2")

    def write(self, path):
        return classify({"type": "write_file", "path": path, "content": "x"}, [self.root]).verdict

    def test_git_cannot_stage_or_read_ignored_secrets_without_approval(self):
        for args in (["add", "-f", "data"], ["add", "-fA"], ["add", "-Af", "data"], ["add", "--force", "."],
                     ["add", "--forc", "data"], ["add", "--fo", "."]):
            self.assertEqual(self.git(*args).verdict, APPROVAL, args)
        for args in (["show", "HEAD:data/tokens.json"], ["show", ":0:data/tokens.json"],
                     ["show", ":(top)data/tokens.json"], ["show", "HEAD:./data/tokens.json"],
                     ["show", "HEAD:data/../data/ai_accounts.json"]):
            self.assertEqual(self.git(*args).verdict, DENY, args)

    def test_git_cannot_write_files_or_read_outside(self):
        outside = str(self.root.parent / "elsewhere.bat")
        for args in (["log", "-1", "--output=" + outside], ["log", "-1", "--output=hub/x.py"], ["log", "--out=hub/x.py"],
                     ["diff", "--output=backend/wacc_backend/execution/policy.py"], ["show", "--textconv", "HEAD"]):
            self.assertEqual(self.git(*args).verdict, DENY, args)
        self.assertEqual(self.git("diff", "--no-index", "a", "b").verdict, APPROVAL)

    def test_git_destructive_or_networked_variants_need_approval(self):
        for args in (["switch", "-f", "main"], ["switch", "--discard-changes", "main"], ["branch", "-f", "main", "HEAD~9"],
                     ["switch", "-fc", "x"], ["fetch", "https://evil.example/x"], ["fetch", "file:///home/u/other"]):
            self.assertEqual(self.git(*args).verdict, APPROVAL, args)
        self.assertIn(self.git("fetch", "../other-repo").verdict, (APPROVAL, DENY))

    def test_normal_git_use_stays_automatic(self):
        for args in (["status"], ["log", "-1", "--oneline"], ["diff", "--stat"], ["diff", "--cached"],
                     ["add", "hub/wacc_hub/db.py"], ["add", "."], ["commit", "-m", "fix: a/b thing"], ["fetch", "origin"],
                     ["show", "HEAD:hub/wacc_hub/db.py"], ["log", "--follow", "-p", "--", "README.md"]):
            self.assertEqual(self.git(*args).verdict, ALLOW, args)

    def test_compileall_and_analyzers_run_project_code(self):
        for argv in (["python", "-m", "compileall"], ["flutter", "analyze"], ["dart", "analyze"]):
            d = classify({"type": "run", "argv": argv, "cwd": str(self.root)}, [self.root])
            self.assertEqual(d.verdict, APPROVAL, argv)

    def test_files_that_change_what_runs_next_need_approval(self):
        for path in ("start_wacc.bat", "scripts/run_backend.bat", "x/y.cmd", "fastapi.py", "json.py", "web/json.py",
                     "hub/http.py", "backend/wacc_backend/security.py", "backend/wacc_backend/app.py",
                     "hub/requirements.txt", "backend/requirements.txt", "mobile/pubspec.yaml", ".github/workflows/tests.yml",
                     "conftest.py", "sitecustomize.py", "hub/wacc_hub/auth.py", "web/serve.py", "x/evil.pth", ".gitattributes"):
            self.assertEqual(self.write(path), APPROVAL, path)
        for path in ("hub/wacc_hub/db.py", "web/public/app.js", "mobile/lib/main.dart", "docs/NOTES.md", "backend/tests/test_x.py"):
            self.assertEqual(self.write(path), ALLOW, path)

    def test_real_git_cannot_leak_secrets_through_automatic_commands(self):
        run = lambda *a: subprocess.run(["git", *a], cwd=self.root, capture_output=True, text=True)  # noqa: E731
        run("init", "-q")
        (self.root / ".gitignore").write_text("data/*\n")
        (self.root / "data" / "tokens.json").write_text("SECRET-TOKEN")
        # what an agent could chain if every step were automatic: only steps the policy ALLOWs are executed
        for args in (["add", "-f", "data"], ["add", "-fA"], ["add", "--forc", "data"]):
            if self.git(*args).verdict == ALLOW:
                run(*args)
        staged = run("diff", "--cached").stdout if self.git("diff", "--cached").verdict == ALLOW else ""
        self.assertNotIn("SECRET-TOKEN", staged)


if __name__ == "__main__":
    unittest.main()
