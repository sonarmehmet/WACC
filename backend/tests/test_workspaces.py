import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wacc_backend.engine import TaskEngine  # noqa: E402
from wacc_backend.execution.approvals import Approvals  # noqa: E402
from wacc_backend.execution.executor import FakeExecutor, RealExecutor  # noqa: E402
from wacc_backend.execution.service import EmergencyStop, ExecutionService  # noqa: E402
from wacc_backend.storage import Storage, StorageError  # noqa: E402
from wacc_backend.workspaces import WorkspaceStore, slugify  # noqa: E402

try:
    from fastapi.testclient import TestClient
    HAVE_API = True
except Exception:  # pragma: no cover
    HAVE_API = False


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.data = self.base / "data"
        self.data.mkdir()
        self.store = WorkspaceStore(self.data / "workspaces.json", self.base / "workspace", forbidden=[self.data])

    def tearDown(self):
        self.tmp.cleanup()

    def code(self, fn, *a, **kw):
        with self.assertRaises(StorageError) as cm:
            fn(*a, **kw)
        return cm.exception.code


class StoreTests(Base):
    def test_slug_and_default_folder_is_created(self):
        self.assertEqual(slugify("Rüzgâr Türbini Sitesi!"), "ruzgar-turbini-sitesi")
        w = self.store.add("Rüzgar Türbini Sitesi")
        self.assertEqual(w["name"], "ruzgar-turbini-sitesi")
        self.assertTrue(Path(w["folder"]).is_dir())
        self.assertEqual(Path(w["folder"]).parent, self.base / "workspace")
        self.assertEqual(self.code(self.store.add, "Rüzgar türbini sitesi"), "DUPLICATE")
        self.assertEqual(self.code(self.store.add, "!"), "BAD_NAME")

    def test_own_folder_anywhere_but_not_where_wacc_lives_or_the_system(self):
        mine = self.base / "Belgeler" / "proje"
        w = self.store.add("Benim", str(mine))
        self.assertTrue(mine.is_dir() and w["exists"])
        self.assertEqual(self.code(self.store.add, "Ikinci", str(mine)), "DUPLICATE")  # same folder twice
        self.assertEqual(self.code(self.store.add, "Rel", "relative/dir"), "BAD_FOLDER")
        self.assertEqual(self.code(self.store.add, "Root", str(Path(mine.anchor))), "BAD_FOLDER")
        self.assertEqual(self.code(self.store.add, "Veri", str(self.data / "x")), "BAD_FOLDER")
        self.assertEqual(self.code(self.store.add, "Ust", str(self.base)), "BAD_FOLDER")  # contains WACC's data
        self.assertEqual(self.code(self.store.add, "Ssh", str(self.base / ".ssh")), "BAD_FOLDER")
        self.assertEqual(self.code(self.store.add, "Home", str(Path.home())), "BAD_FOLDER")

    def test_agents_assign_unassign_and_persist(self):
        self.store.add("Site")
        self.store.assign("site", "claude1")
        self.store.assign("site", "claude1")  # idempotent
        self.assertEqual(self.store.get("site")["agents"], ["claude1"])
        again = WorkspaceStore(self.data / "workspaces.json", self.base / "workspace", forbidden=[self.data])
        self.assertEqual(again.projects_of("claude1"), ["site"])
        self.assertEqual(self.code(self.store.assign, "site", "Bad Name"), "BAD_AGENT")
        self.assertEqual(self.code(self.store.assign, "yok", "claude1"), "NOT_FOUND")
        self.store.unassign("site", "claude1")
        self.assertIsNone(self.store.folders_for("claude1"))

    def test_remove_keeps_folder_and_files(self):
        w = self.store.add("Site")
        keep = Path(w["folder"]) / "index.html"
        keep.write_text("<h1>x</h1>", encoding="utf-8")
        self.assertTrue(self.store.remove("site"))
        self.assertFalse(self.store.remove("site"))
        self.assertTrue(keep.exists())

    def test_broken_file_is_ignored_not_fatal(self):
        (self.data / "workspaces.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.store.list(), [])


class ScopeTests(Base):
    def setUp(self):
        super().setUp()
        self.storage = Storage(self.base / "b.db")
        approvals = Approvals(self.storage)
        stop = EmergencyStop(self.base / "hub", TaskEngine(self.storage), approvals)
        self.default = self.base / "default"
        self.default.mkdir()
        self.a = Path(self.store.add("Alfa")["folder"])
        self.b = Path(self.store.add("Beta")["folder"])
        self.store.assign("alfa", "claude1")
        self.store.assign("beta", "claude2")
        self.svc = ExecutionService(self.storage, [self.default], RealExecutor([self.default], extra_roots=self.store.folders),
                                    stop, approvals, scope=self.store.folders_for)

    def write(self, agent, path):
        return self.svc.submit(agent, {"type": "write_file", "path": str(path), "content": "hi"})

    def test_agent_works_in_its_project_and_nowhere_else(self):
        self.assertEqual(self.write("claude1", self.a / "a.txt")["status"], "OK")
        self.assertTrue((self.a / "a.txt").exists())
        self.assertEqual(self.write("claude1", self.b / "b.txt")["status"], "DENIED")      # another project
        self.assertEqual(self.write("claude1", self.default / "d.txt")["status"], "DENIED")  # default folder
        self.assertEqual(self.write("claude2", self.a / "x.txt")["status"], "DENIED")
        self.assertEqual(self.write("claude2", self.b / "b.txt")["status"], "OK")

    def test_agent_without_project_keeps_the_default_folder(self):
        self.assertEqual(self.write("claude3", self.default / "d.txt")["status"], "OK")
        self.assertEqual(self.write("claude3", self.a / "x.txt")["status"], "DENIED")

    def test_two_projects_means_both_folders(self):
        self.store.assign("beta", "claude1")
        self.assertEqual(self.write("claude1", self.b / "b.txt")["status"], "OK")

    def test_delete_inside_project_needs_approval_and_moves_to_trash(self):
        (self.a / "old.txt").write_text("x", encoding="utf-8")
        res = self.svc.submit("claude1", {"type": "delete_path", "path": str(self.a / "old.txt")})
        self.assertEqual(res["status"], "APPROVAL_REQUIRED")
        self.assertTrue((self.a / "old.txt").exists())

    def test_outside_every_project_is_personal_files(self):
        res = self.write("claude1", self.base / "Belgeler" / "x.txt")
        self.assertEqual((res["status"], res["class"]), ("DENIED", "PERSONAL_FILES"))


@unittest.skipUnless(HAVE_API, "fastapi/httpx not installed")
class ApiTests(Base):
    def setUp(self):
        super().setUp()
        from wacc_backend.app import create_app
        from wacc_backend.config import load_settings
        self.fake = FakeExecutor()
        settings = load_settings({"WACC_DATA_DIR": str(self.data)})
        self.client = TestClient(create_app(settings, token="secret", providers=[], executor=self.fake, user_token="human",
                                            agent_tokens={"claude2": "tok-c2"}))
        self.u, self.c2 = {"X-WACC-Token": "human"}, {"X-WACC-Token": "tok-c2"}

    def test_only_the_user_changes_projects_agents_can_read(self):
        mine = str(self.base / "Belgeler" / "site")
        self.assertEqual(self.client.post("/workspaces", json={"title": "Site", "folder": mine}, headers=self.c2).status_code, 403)
        r = self.client.post("/workspaces", json={"title": "Site", "folder": mine}, headers=self.u)
        self.assertEqual(r.status_code, 201)
        self.assertTrue(Path(mine).is_dir())
        self.assertEqual(self.client.post("/workspaces/site/agents", json={"agent": "claude2"}, headers=self.c2).status_code, 403)
        self.assertEqual(self.client.post("/workspaces/site/agents", json={"agent": "claude2"}, headers=self.u).json()["agents"], ["claude2"])
        self.assertEqual(self.client.get("/workspaces", headers=self.c2).json()[0]["name"], "site")
        bad = self.client.post("/workspaces", json={"title": "Kotu", "folder": str(self.data / "z")}, headers=self.u)
        self.assertEqual((bad.status_code, bad.json()["detail"]["code"]), (400, "BAD_FOLDER"))
        self.assertEqual(self.client.delete("/workspaces/site/agents/claude2", headers=self.u).json()["agents"], [])
        self.assertEqual(self.client.delete("/workspaces/site", headers=self.u).json(), {"removed": True})
        self.assertTrue(Path(mine).is_dir())


if __name__ == "__main__":
    unittest.main()
