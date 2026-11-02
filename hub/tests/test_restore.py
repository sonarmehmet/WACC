import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wacc_hub.restore import RestoreError, backup_databases, restore  # noqa: E402
from wacc_hub.service import Hub  # noqa: E402


def make_backend_db(path, marker):
    conn = sqlite3.connect(str(path))
    conn.executescript("CREATE TABLE jobs(id INTEGER); CREATE TABLE approvals(id INTEGER); "
                       "CREATE TABLE marker(v TEXT);")
    conn.execute("INSERT INTO marker VALUES (?)", (marker,))
    conn.commit()
    conn.close()


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.data = self.base / "data"
        self.data.mkdir()
        self.backups = self.base / "backups"
        self.hub = Hub(str(self.data / "hub.db"))
        self.backend_db = self.data / "backend.db"
        make_backend_db(self.backend_db, "original")
        self.targets = {"hub": Path(self.hub.db_path), "backend": self.backend_db}

    def tearDown(self):
        self.tmp.cleanup()

    def stopped(self, port):
        return False

    def test_backup_then_change_then_restore_returns_old_data(self):
        made = backup_databases(self.targets, self.backups, "20261102_120000")
        self.assertEqual(set(made), {"hub", "backend"})
        self.hub.create_task("claude1", "after backup", "d", owner="claude2")
        conn = sqlite3.connect(str(self.backend_db))
        conn.execute("UPDATE marker SET v='changed'")
        conn.commit()
        conn.close()
        self.hub.close() if hasattr(self.hub, "close") else None

        res = restore("hub_20261102_120000.db", self.backups, self.targets, self.data, self.stopped)
        restore("backend_20261102_120000.db", self.backups, self.targets, self.data, self.stopped)
        self.assertTrue(res["previous_kept_as"].startswith("pre-restore-"))
        self.assertTrue((self.data / res["previous_kept_as"]).exists())
        self.assertEqual(Hub(str(self.targets["hub"])).list_tasks(owner="claude2"), [])
        self.assertEqual(sqlite3.connect(str(self.backend_db)).execute("SELECT v FROM marker").fetchone()[0], "original")
        # the replaced database is kept, with the post-backup data still in it
        kept = sqlite3.connect(str(self.data / res["previous_kept_as"]))
        self.assertEqual(kept.execute("SELECT count(*) FROM tasks WHERE title='after backup'").fetchone()[0], 1)
        kept.close()

    def test_refuses_while_service_is_running(self):
        backup_databases(self.targets, self.backups, "20261102_120000")
        with self.assertRaises(RestoreError) as ctx:
            restore("hub_20261102_120000.db", self.backups, self.targets, self.data, lambda port: True)
        self.assertIn("çalışıyor", str(ctx.exception))

    def test_only_plain_backup_names_are_accepted(self):
        backup_databases(self.targets, self.backups, "20261102_120000")
        for bad in ("../data/hub.db", "..\\data\\hub.db", "C:\\x\\hub_20261102_120000.db", "hub.db", "", "other_20261102_120000.db",
                    "hub_20261102_120000.db.bak"):
            with self.assertRaises(RestoreError, msg=bad):
                restore(bad, self.backups, self.targets, self.data, self.stopped)

    def test_missing_corrupt_and_wrong_kind_backups_are_rejected_and_nothing_changes(self):
        self.backups.mkdir()
        with self.assertRaises(RestoreError):
            restore("hub_20261102_120000.db", self.backups, self.targets, self.data, self.stopped)
        (self.backups / "hub_20261102_120001.db").write_bytes(b"this is not a database" * 50)
        with self.assertRaises(RestoreError):
            restore("hub_20261102_120001.db", self.backups, self.targets, self.data, self.stopped)
        make_backend_db(self.backups / "hub_20261102_120002.db", "wrong kind")  # backend schema named as hub
        with self.assertRaises(RestoreError) as ctx:
            restore("hub_20261102_120002.db", self.backups, self.targets, self.data, self.stopped)
        self.assertIn("tablolar", str(ctx.exception))
        self.assertEqual(list(self.data.glob("pre-restore-*")), [])
        self.assertEqual(sqlite3.connect(str(self.backend_db)).execute("SELECT v FROM marker").fetchone()[0], "original")

    def test_restore_when_target_is_missing_just_restores(self):
        backup_databases(self.targets, self.backups, "20261102_120000")
        self.backend_db.unlink()
        res = restore("backend_20261102_120000.db", self.backups, self.targets, self.data, self.stopped,
                      now=datetime(2026, 11, 2, 12, 0, 0))
        self.assertIsNone(res["previous_kept_as"])
        self.assertTrue(self.backend_db.exists())


if __name__ == "__main__":
    unittest.main()
