import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import tkinter
    tkinter.Tk().destroy()
    HAVE_TK = True
except Exception:  # no tkinter or no display
    HAVE_TK = False


@unittest.skipUnless(HAVE_TK, "tkinter/display not available")
class UiSmoke(unittest.TestCase):
    def test_window_builds_and_survives_unreachable_servers(self):
        from wacc_desktop.ui import App
        app = App()
        try:
            app.vars["user"].set("x")
            app.connect()  # servers are down: must show an error text, not crash
            self.assertTrue(app.status.get())
        finally:
            app.destroy()

    def test_dashboard_orb_and_pages_render(self):
        from wacc_desktop import ui
        app = ui.App()
        try:
            app.update()
            app._agents = [{"agent_id": "a", "enabled": 1}, {"agent_id": "b", "enabled": 0}]
            app._approvals = [{"id": "x"}]
            app._hub_ok = app._backend_ok = True
            for state in ("idle", "pending", "stopped", "offline"):
                app._set_state(state)
                app._draw_orb(640, 520)
            app._update_dashboard([{"status": "done"}, {"status": "open"}], False)
            self.assertEqual(app.state, "pending")  # one approval waiting
            self.assertIn("(1)", app.nav["approvals"].cget("text"))
            for key in app.pages:
                app._show(key)
            self.assertEqual(ui.mix("#000000", "#ffffff", 0.5), "#808080")
            app.open_settings()
            app.update()
            app._settings.destroy()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
