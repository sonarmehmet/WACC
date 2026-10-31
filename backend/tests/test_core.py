import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wacc_backend.config import load_settings  # noqa: E402
from wacc_backend.security import get_or_create_token, token_matches  # noqa: E402
from wacc_backend.storage import Storage, StorageError  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_defaults_are_local_only(self):
        s = load_settings({"WACC_DATA_DIR": "/tmp/x"})
        self.assertEqual((s.host, s.port), ("127.0.0.1", 8800))
        self.assertEqual(s.db_path, Path("/tmp/x/backend.db"))

    def test_overrides_and_validation(self):
        s = load_settings({"WACC_BACKEND_PORT": "9000", "WACC_BACKEND_HOST": "0.0.0.0", "WACC_BACKEND_DB": "/tmp/a.db"})
        self.assertEqual((s.host, s.port, s.db_path), ("0.0.0.0", 9000, Path("/tmp/a.db")))
        for bad in ("abc", "0", "70000"):
            with self.assertRaises(ValueError):
                load_settings({"WACC_BACKEND_PORT": bad})


class SecurityTests(unittest.TestCase):
    def test_token_created_once_and_reused(self):
        with tempfile.TemporaryDirectory() as d:
            s = load_settings({"WACC_DATA_DIR": d})
            t1 = get_or_create_token(s)
            self.assertGreaterEqual(len(t1), 32)
            self.assertEqual(get_or_create_token(s), t1)

    def test_env_override_wins(self):
        with tempfile.TemporaryDirectory() as d:
            s = load_settings({"WACC_DATA_DIR": d, "WACC_BACKEND_TOKEN": "fixed"})
            self.assertEqual(get_or_create_token(s), "fixed")
            self.assertFalse(s.token_file.exists())

    def test_token_matches(self):
        self.assertTrue(token_matches("abc", "abc"))
        self.assertFalse(token_matches("abc", "abd"))
        self.assertFalse(token_matches("abc", ""))
        self.assertFalse(token_matches("", ""))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(Path(self.tmp.name) / "b.db")

    def tearDown(self):
        self.tmp.cleanup()

    def code(self, fn, *a, **kw):
        with self.assertRaises(StorageError) as cm:
            fn(*a, **kw)
        return cm.exception.code

    def test_migration_is_idempotent_and_wal(self):
        self.assertEqual(self.db.schema_version(), 1)
        self.assertEqual(Storage(self.db.db_path).schema_version(), 1)
        conn = sqlite3.connect(self.db.db_path)
        self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        conn.close()

    def test_project_crud(self):
        p = self.db.create_project("  WACC  ", "main")
        self.assertEqual((p["name"], p["status"]), ("WACC", "ACTIVE"))
        self.assertEqual(self.code(self.db.create_project, "WACC"), "DUPLICATE")
        self.assertEqual(self.code(self.db.create_project, "   "), "BAD_NAME")
        self.assertEqual(self.db.update_project(p["id"], description="new")["description"], "new")
        self.assertEqual(self.code(self.db.update_project, p["id"], status="WEIRD"), "BAD_STATUS")
        self.assertEqual(self.code(self.db.update_project, 999, name="x"), "NOT_FOUND")

    def test_archive_hides_but_never_deletes(self):
        p = self.db.create_project("A")
        self.db.create_project("B")
        self.assertEqual(self.db.archive_project(p["id"])["status"], "ARCHIVED")
        self.assertEqual([x["name"] for x in self.db.list_projects()], ["B"])
        self.assertEqual(len(self.db.list_projects(include_archived=True)), 2)
        self.assertIsNotNone(self.db.get_project(p["id"]))

    def test_rename_collision(self):
        a = self.db.create_project("A")
        self.db.create_project("B")
        self.assertEqual(self.code(self.db.update_project, a["id"], name="B"), "DUPLICATE")


if __name__ == "__main__":
    unittest.main()
