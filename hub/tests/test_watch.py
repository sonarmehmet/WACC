import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wacc_hub.service import Hub  # noqa: E402
from wacc_hub.watch import WatchState, poll_once, watch  # noqa: E402


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hub = Hub(os.path.join(self.tmp.name, "hub.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, subject="hello", sender="claude1", to="claude2", **kw):
        return self.hub.send_message(sender, to, "STATUS_UPDATE", subject, "body", **kw)

    def test_existing_inbox_is_not_replayed_but_new_messages_are_announced_once(self):
        self.send("old")
        state = WatchState()
        self.assertEqual(poll_once(self.hub, "claude2", state), [])
        self.send("new one")
        lines = poll_once(self.hub, "claude2", state)
        self.assertEqual(len(lines), 1)
        self.assertIn("new one", lines[0])
        self.assertIn("claude1 -> claude2", lines[0])
        self.assertEqual(poll_once(self.hub, "claude2", state), [])

    def test_all_flag_announces_existing_messages(self):
        self.send("old")
        lines = poll_once(self.hub, "claude2", WatchState(), announce_existing=True)
        self.assertEqual(len(lines), 1)

    def test_long_multiline_subject_is_shortened_to_one_line(self):
        self.send("x" * 150 + "\nsecond line")
        state = WatchState()
        poll_once(self.hub, "claude2", state, announce_existing=True)
        self.send("y\n" * 90)
        line = poll_once(self.hub, "claude2", state)[0]
        self.assertNotIn("\n", line)
        self.assertLess(len(line), 300)

    def test_task_assignment_and_status_change_are_reported(self):
        state = WatchState()
        poll_once(self.hub, "claude2", state)
        self.hub.create_task("claude1", "Do the thing", "d", owner="claude2")
        first = poll_once(self.hub, "claude2", state)
        self.assertTrue(any("yeni görev" in line for line in first), first)
        task_id = self.hub.list_tasks(owner="claude2")[0]["task_id"]
        self.hub.accept_task("claude2", task_id)
        changed = poll_once(self.hub, "claude2", state)
        self.assertTrue(any(task_id in line and "->" in line for line in changed), changed)

    def test_emergency_stop_and_resume_are_reported(self):
        state = WatchState()
        poll_once(self.hub, "claude2", state)
        self.hub.emergency_stop("user", "test")
        self.assertIn("ACİL DURDURMA", poll_once(self.hub, "claude2", state)[0])
        self.assertEqual(poll_once(self.hub, "claude2", state), [])
        self.hub.resume("user")
        self.assertIn("kaldırıldı", poll_once(self.hub, "claude2", state)[0])

    def test_watch_is_read_only_and_loop_terminates(self):
        self.send("m1")
        out = []
        code = watch(self.hub, "claude2", interval=0.5, emit=out.append, sleep=lambda s: None, max_polls=3,
                     announce_existing=True)
        self.assertEqual(code, 0)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(self.hub.inbox("claude2", unread_only=True)), 1)  # still unread

    def test_keyboard_interrupt_exits_cleanly(self):
        out = []

        def boom(_):
            raise KeyboardInterrupt

        self.assertEqual(watch(self.hub, "claude2", emit=out.append, sleep=boom, max_polls=5), 0)
        self.assertEqual(out[-1], "watch durduruldu")


if __name__ == "__main__":
    unittest.main()
