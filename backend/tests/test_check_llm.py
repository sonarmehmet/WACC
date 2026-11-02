import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        raw = json.dumps({"choices": [{"message": {"content": "OK"}}],
                          "usage": {"prompt_tokens": 5, "completion_tokens": 1}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class CheckLlmScript(unittest.TestCase):
    def run_script(self, env_extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith("WACC_")}
        env.update(env_extra)
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "check_llm.py")], env=env,
                              capture_output=True, text=True, timeout=60)

    def test_reports_pass_against_a_local_server(self):
        server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            out = self.run_script({"WACC_LOCAL_LLM_URL": f"http://127.0.0.1:{server.server_port}/v1",
                                   "WACC_LOCAL_LLM_MODEL": "tiny"})
        finally:
            server.shutdown()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("PASS local-llm", out.stdout)

    def test_reports_fail_when_server_is_down_and_hides_key(self):
        out = self.run_script({"WACC_LOCAL_LLM_URL": "http://127.0.0.1:1/v1"})
        self.assertEqual(out.returncode, 1)
        self.assertIn("FAIL local-llm", out.stdout)

    def test_nothing_configured_explains_what_to_do(self):
        out = self.run_script({})
        self.assertIn(out.returncode, (0, 2))
        if out.returncode == 2:
            self.assertIn("WACC_LOCAL_LLM_URL", out.stdout)


if __name__ == "__main__":
    unittest.main()
