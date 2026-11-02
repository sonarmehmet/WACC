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


if __name__ == "__main__":
    unittest.main()
