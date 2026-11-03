import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import scan_secrets  # noqa: E402


class ScanTests(unittest.TestCase):
    def test_patterns_detect_real_looking_secrets_and_ignore_normal_text(self):
        bad = ["key = 'sk-" + "a" * 30 + "'", "ghp_" + "b" * 36, "AKIA" + "A" * 16, "-----BEGIN RSA PRIVATE KEY-----",
               "token: \"abcdefghijklmnop1234\"", "me@gmail.com"]
        for line in bad:
            self.assertTrue(scan_secrets.scan_text("x.py", line), line)
        for line in ["token = read_token()", "X-WACC-Token header", "sk-short", "email: user@example.com", "password = ''"]:
            self.assertEqual(scan_secrets.scan_text("x.py", line), [], line)

    def test_sensitive_file_names(self):
        for name in ("data/tokens.json", ".env", "x/llm.env", "data/backend_tokens.json", "data/ai_accounts.json",
                     "a/server.pem", "backups/hub_1.db", "k.key"):
            self.assertTrue(scan_secrets.SENSITIVE_NAMES.search(name), name)
        for name in ("docs/tokens-guide.md", "web/serve.py", "hub/wacc_hub/auth.py", "assets/icon.svg"):
            self.assertFalse(scan_secrets.SENSITIVE_NAMES.search(name), name)

    def test_tree_scan_finds_a_planted_secret_in_a_temp_repo(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            run = lambda *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True)
            run("init", "-q")
            (repo / "ok.txt").write_text("nothing here", encoding="utf-8")
            (repo / "leak.py").write_text("API_KEY = 'sk-" + "z" * 30 + "'\n", encoding="utf-8")
            (repo / "tokens.json").write_text("{}", encoding="utf-8")
            run("add", "-A")
            labels = {(p, label) for p, _, label in scan_secrets.scan_tree(repo)}
            self.assertIn(("leak.py", "OpenAI-style key"), labels)
            self.assertIn(("tokens.json", "Sensitive file name is tracked"), labels)
            self.assertFalse([p for p, _ in labels if p == "ok.txt"])

    def test_this_repository_is_clean(self):
        self.assertEqual(scan_secrets.scan_tree(ROOT), [])


if __name__ == "__main__":
    unittest.main()
