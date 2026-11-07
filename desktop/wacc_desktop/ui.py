"""Tkinter window: dark "control room" look. Left: clock + live meters. Centre: animated core with the
emergency stop. Right: agents, tasks, approvals, audit, AI accounts. Refreshes every 5 seconds.

The three tokens are not on the main screen: the installed app fills them in itself, they only live in
the Ayarlar dialog for people who run from source."""

import math
import random
import sys
import time
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from .client import ApiError, WaccClient, describe_agent, describe_approval, describe_provider

REFRESH_MS = 5000
FRAME_MS = 50

BG = "#060c0e"
PANEL = "#0a1417"
FIELD = "#0d1c20"
EDGE = "#12372f"
TEXT = "#d3efe6"
DIM = "#5f8a7d"
GREEN = "#2ee6a6"
AMBER = "#e8a23a"
RED = "#ff4d5e"

STATE_COLOR = {"idle": GREEN, "pending": AMBER, "stopped": RED, "offline": "#6c7f87"}
STATE_TEXT = {"idle": "BEKLEMEDE", "pending": "ONAYINI BEKLİYOR", "stopped": "ACİL DURDURMA AKTİF",
              "offline": "BAĞLANTI YOK"}
DAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
MONTHS = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık")


def mix(a: str, b: str, t: float) -> str:
    """Blend colour a towards colour b (t=0 -> a, t=1 -> b). Colours are '#rrggbb'."""
    t = max(0.0, min(1.0, t))
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x * (1 - t) + y * t) for x, y in zip(ca, cb))


def apply_theme(root):
    """Dark ttk theme (used by the dialogs) and dark dropdown lists."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD, bordercolor=EDGE,
                    lightcolor=EDGE, darkcolor=EDGE, troughcolor=BG, focuscolor=BG)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=GREEN)
    style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT, arrowcolor=GREEN)
    style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)])
    style.configure("TButton", background=PANEL, foreground=GREEN, padding=(12, 5))
    style.map("TButton", background=[("active", "#0f2a25")], foreground=[("active", GREEN)])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", EDGE)


class App(tk.Tk):
    def __init__(self, preset=None):
        """preset: {"hub", "backend", "user"} tokens when the launcher started the services itself
        (the installed app), so nothing has to be typed or pasted."""
        super().__init__()
        self.title("WACC")
        self.geometry("1240x760")
        self.minsize(1040, 660)
        self.configure(bg=BG)
        apply_theme(self)
        families = set(tkfont.families(self))
        self._mono = next((f for f in ("Consolas", "Cascadia Mono", "DejaVu Sans Mono", "Courier New") if f in families),
                          "TkFixedFont")
        self._set_icon()
        self.client = WaccClient()
        self._approvals = []
        self._agents = []
        self._providers = []
        self.state = "offline"
        self._t = 0.0
        self._hub_ok = self._backend_ok = False
        rnd = random.Random(7)
        # angle, radius (0..1), angular speed, size, phase
        self._particles = [[rnd.uniform(0, 6.283), math.sqrt(rnd.random()), rnd.uniform(-0.12, 0.12),
                            rnd.uniform(1.2, 3.2), rnd.uniform(0, 6.283)] for _ in range(70)]
        self._build()
        self._tick_clock()
        self.after(FRAME_MS, self._tick_orb)
        if preset:
            for key in ("hub", "backend", "user"):
                self.vars[key].set(preset.get(key, ""))
            self.after(100, self.connect)
        else:
            self.after(200, self.refresh)
            self.after(400, self.open_settings)

    def F(self, size, bold=False):
        return (self._mono, size, "bold") if bold else (self._mono, size)

    def _set_icon(self):
        candidates = [Path(__file__).resolve().parents[2] / "assets" / "icon-192.png"]
        bundle = getattr(sys, "_MEIPASS", None)  # inside the packaged exe
        if bundle:
            candidates.insert(0, Path(bundle) / "assets" / "icon-192.png")
        for icon in candidates:
            try:
                self._icon = tk.PhotoImage(file=str(icon))  # keep a reference or Tk drops it
                self.iconphoto(True, self._icon)
                return
            except (tk.TclError, OSError):
                continue  # a missing icon must never stop the panel

    # ------------------------------------------------------------------ widgets
    def _panel(self, parent, **pack):
        frame = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=EDGE, bd=0)
        frame.pack(**pack)
        return frame

    def _caption(self, parent, text, pady=(14, 4)):
        tk.Label(parent, text=text, bg=PANEL, fg=GREEN, font=self.F(9, True), anchor="w").pack(fill="x", padx=16, pady=pady)

    def _btn(self, parent, text, cmd, kind="normal"):
        fg = {"normal": GREEN, "danger": RED, "amber": AMBER}[kind]
        rest, hover = PANEL, mix(PANEL, fg, 0.16)
        b = tk.Button(parent, text=text, command=cmd, font=self.F(9, True), fg=fg, bg=rest, activeforeground=fg,
                      activebackground=hover, relief="flat", bd=0, padx=12, pady=6, cursor="hand2",
                      highlightthickness=1, highlightbackground=mix(fg, PANEL, 0.62), highlightcolor=fg)
        b.bind("<Enter>", lambda _e: b.configure(bg=hover))
        b.bind("<Leave>", lambda _e: b.configure(bg=rest))
        return b

    def _listbox(self, parent):
        box = tk.Listbox(parent, activestyle="none", bg=PANEL, fg=TEXT, selectbackground=EDGE, selectforeground=GREEN,
                         highlightthickness=0, bd=0, relief="flat", font=self.F(10))
        box.bind("<Double-Button-1>", lambda _e, b=box: self._detail(b))
        return box

    def _meter(self, parent, label):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", padx=16, pady=3)
        tk.Label(row, text=label, bg=PANEL, fg=DIM, font=self.F(8), width=8, anchor="w").pack(side="left")
        bar = tk.Canvas(row, height=8, bg=PANEL, highlightthickness=0)
        bar.pack(side="left", fill="x", expand=True, padx=6)
        value = tk.StringVar(value="--")
        tk.Label(row, textvariable=value, bg=PANEL, fg=TEXT, font=self.F(9, True), width=6, anchor="e").pack(side="left")
        return bar, value

    def _set_meter(self, meter, fraction, text, color=GREEN):
        bar, value = meter
        bar.delete("all")
        width = max(bar.winfo_width(), 60)
        bar.create_rectangle(0, 0, width, 8, fill=mix(PANEL, color, 0.12), outline="")
        if fraction > 0:
            bar.create_rectangle(0, 0, max(3, width * min(fraction, 1.0)), 8, fill=color, outline="")
        value.set(text)

    # ------------------------------------------------------------------ layout
    def _build(self):
        self.vars = {key: tk.StringVar() for key in ("hub", "backend", "user")}
        self.status = tk.StringVar(value="Hazır.")
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=14, pady=14)

        # ---- left: clock and meters
        left = self._panel(outer, side="left", fill="y")
        left.configure(width=270)
        left.pack_propagate(False)
        self._caption(left, "SAAT", pady=(16, 0))
        self.clock = tk.Label(left, text="--:--", bg=PANEL, fg=TEXT, font=self.F(34, True), anchor="w")
        self.clock.pack(fill="x", padx=16)
        self.date = tk.Label(left, text="", bg=PANEL, fg=DIM, font=self.F(9), anchor="w")
        self.date.pack(fill="x", padx=16)
        self._caption(left, "SİSTEM DURUMU", pady=(22, 6))
        self.m_agents = self._meter(left, "AJAN")
        self.m_tasks = self._meter(left, "GÖREV")
        self.m_approvals = self._meter(left, "ONAY")
        self._caption(left, "BAĞLANTI", pady=(22, 6))
        self.link_hub = tk.Label(left, text="● Hub", bg=PANEL, fg=DIM, font=self.F(10), anchor="w")
        self.link_hub.pack(fill="x", padx=16)
        self.link_backend = tk.Label(left, text="● Backend", bg=PANEL, fg=DIM, font=self.F(10), anchor="w")
        self.link_backend.pack(fill="x", padx=16)
        tk.Label(left, textvariable=self.status, bg=PANEL, fg=DIM, font=self.F(8), anchor="nw", justify="left",
                 wraplength=236).pack(fill="x", padx=16, pady=(14, 0))
        bottom = tk.Frame(left, bg=PANEL)
        bottom.pack(side="bottom", fill="x", padx=16, pady=16)
        self._btn(bottom, "AYARLAR", self.open_settings).pack(fill="x")

        # ---- right: lists
        right = self._panel(outer, side="right", fill="y")
        right.configure(width=450)
        right.pack_propagate(False)
        nav = tk.Frame(right, bg=PANEL)
        nav.pack(fill="x", padx=10, pady=(12, 6))
        self.body = tk.Frame(right, bg=PANEL)
        self.body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.pages, self.nav = {}, {}
        self.agents_box = self._page(nav, "agents", "AJANLAR", (
            ("Ajan ekle", self.add_agent, "normal"), ("Aç / Kapat", self.toggle_agent, "normal"), ("Sil", self.remove_agent, "danger")),
            "Claude, Gemini, ChatGPT ya da başka istediğin kadar hesap. Çift tıkla: tam satırı gör.")
        self.tasks_box = self._page(nav, "tasks", "GÖREVLER", (), "Hub'daki görevler.")
        self.approval_list = self._page(nav, "approvals", "ONAYLAR", (
            ("Onayla", lambda: self.decide(True), "normal"), ("Reddet", lambda: self.decide(False), "danger")),
            "Onaylamadan önce komutu dikkatle oku: onay yalnızca bu tek eylem içindir.")
        self.audit_box = self._page(nav, "audit", "DENETİM", (), "Son işlemler.")
        self.provider_list = self._page(nav, "ai", "YAPAY ZEKA", (
            ("Hesap ekle", self.add_account, "normal"), ("Aç / Kapat", self.toggle_provider, "normal"),
            ("Test et", self.test_provider, "amber"), ("Sil", self.remove_account, "danger")),
            "Değiştirmek için onay token'ı gerekir. API anahtarı kaydedilir ama bir daha gösterilmez.")
        self._show("approvals")

        # ---- centre: the core
        centre = tk.Frame(outer, bg=PANEL, highlightthickness=1, highlightbackground=EDGE)
        centre.pack(side="left", fill="both", expand=True, padx=14)
        head = tk.Frame(centre, bg=PANEL)
        head.pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(head, text="W . A . C . C", bg=PANEL, fg=GREEN, font=self.F(26, True)).pack(side="left")
        self.online = tk.Label(head, text="● OFFLINE", bg=PANEL, fg=DIM, font=self.F(9, True))
        self.online.pack(side="right")
        tk.Label(centre, text="Yapay zekâ geliştirme ekibi kontrol odası", bg=PANEL, fg=DIM, font=self.F(9)).pack()
        self.orb = tk.Canvas(centre, bg=PANEL, highlightthickness=0)
        self.orb.pack(fill="both", expand=True, padx=10, pady=6)
        self.state_label = tk.Label(centre, text=STATE_TEXT["offline"], bg=PANEL, fg=DIM, font=self.F(11, True))
        self.state_label.pack()
        controls = tk.Frame(centre, bg=PANEL)
        controls.pack(pady=(10, 18))
        self._btn(controls, "WEB PANEL", lambda: webbrowser.open("http://127.0.0.1:8780")).pack(side="left", padx=5)
        self._btn(controls, "DEVAM ETTİR", self.resume, "amber").pack(side="left", padx=5)
        self._btn(controls, "ACİL DURDUR", self.emergency_stop, "danger").pack(side="left", padx=5)

    def _page(self, nav, key, label, buttons, hint):
        frame = tk.Frame(self.body, bg=PANEL)
        actions = tk.Frame(frame, bg=PANEL)
        actions.pack(side="bottom", fill="x", pady=(8, 0))
        for text, cmd, kind in buttons:
            self._btn(actions, text, cmd, kind).pack(side="left", padx=(0, 6))
        tk.Label(frame, text=hint, bg=PANEL, fg=DIM, font=self.F(8), anchor="w", justify="left", wraplength=420).pack(
            side="bottom", fill="x", pady=(8, 0))
        box = self._listbox(frame)
        box.pack(fill="both", expand=True)
        self.pages[key] = frame
        button = tk.Button(nav, text=label, command=lambda: self._show(key), font=self.F(8, True), relief="flat", bd=0,
                           padx=6, pady=4, bg=PANEL, fg=DIM, activebackground=EDGE, activeforeground=GREEN, cursor="hand2")
        button.pack(side="left", padx=1)
        self.nav[key] = button
        return box

    def _show(self, key):
        for name, frame in self.pages.items():
            frame.pack_forget()
            self.nav[name].configure(fg=DIM, bg=PANEL)
        self.pages[key].pack(fill="both", expand=True)
        self.nav[key].configure(fg=GREEN, bg=EDGE)

    def _detail(self, box):
        sel = box.curselection()
        if sel:
            messagebox.showinfo("WACC", box.get(sel[0]))

    # --------------------------------------------------------------- animation
    def _tick_clock(self):
        now = time.localtime()
        self.clock.configure(text=time.strftime("%H:%M", now))
        self.date.configure(text=f"{now.tm_mday:02d}.{now.tm_mon:02d}.{now.tm_year}  {DAYS[now.tm_wday]}")
        self.after(1000, self._tick_clock)

    def _tick_orb(self):
        self._t += FRAME_MS / 1000.0
        width, height = self.orb.winfo_width(), self.orb.winfo_height()
        if width > 60 and height > 60:
            self._draw_orb(width, height)
        self.after(FRAME_MS, self._tick_orb)

    def _draw_orb(self, width, height):
        c, t = self.orb, self._t
        col = STATE_COLOR[self.state]
        speed = 2.4 if self.state == "stopped" else 1.0
        c.delete("fx")
        cx, cy = width / 2, height / 2
        radius = min(width, height) * 0.40
        for scale, fade in ((1.0, 0.72), (0.78, 0.84), (0.42, 0.9)):
            r = radius * scale
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=mix(col, PANEL, fade), tags="fx")
        for scale, start, rate, extent, thick in ((1.0, 0, 38, 62, 3), (0.78, 150, -55, 40, 2), (1.07, 260, 22, 24, 2)):
            r = radius * scale
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=(start + t * rate * speed) % 360, extent=extent,
                         style="arc", outline=col, width=thick, tags="fx")
        for ang, rad, spin, size, phase in self._particles:
            a = ang + t * spin * speed
            r = rad * radius * 0.94
            x, y = cx + r * math.cos(a), cy + r * math.sin(a)
            glow = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 1.6 + phase))
            s = size * (0.8 + 0.3 * glow)
            c.create_oval(x - s, y - s, x + s, y + s, fill=mix(PANEL, mix(col, "#ffffff", 0.55), glow), outline="", tags="fx")
        pulse = 11 + 3 * math.sin(t * 2.2 * speed)
        for k, fade in ((3.2, 0.9), (2.2, 0.78), (1.4, 0.55)):
            r = pulse * k
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=mix(col, PANEL, fade), outline="", tags="fx")
        c.create_oval(cx - pulse, cy - pulse, cx + pulse, cy + pulse, fill=col, outline="", tags="fx")

    def _set_state(self, state):
        self.state = state
        col = STATE_COLOR[state]
        self.state_label.configure(text=STATE_TEXT[state], fg=col)
        live = state != "offline"
        self.online.configure(text="● ONLINE" if live else "● OFFLINE", fg=GREEN if live else DIM)

    # --------------------------------------------------------------- settings
    def open_settings(self):
        if getattr(self, "_settings", None) is not None and self._settings.winfo_exists():
            self._settings.lift()
            return
        self._settings = SettingsDialog(self)

    # ----------------------------------------------------------------- actions
    def connect(self):
        self.client = WaccClient(self.vars["hub"].get().strip(), self.vars["backend"].get().strip(),
                                 self.vars["user"].get().strip())
        self.refresh(schedule=False)

    def _fill(self, box, lines):
        box.delete(0, "end")
        for line in lines:
            box.insert("end", line)

    def refresh(self, schedule=True):
        problems = []
        tasks = []
        self._hub_ok = self._backend_ok = False
        stopped = False
        try:
            self._agents = [a for a in self.client.agents() if a.get("agent_id") != "user"]
            tasks = self.client.tasks()
            self._fill(self.agents_box, [describe_agent(a) for a in self._agents])
            self._fill(self.tasks_box, [f"{t.get('id')}  [{t.get('status')}]  {t.get('owner') or '-'}  {t.get('title')}"
                                        for t in tasks])
            self._hub_ok = True
        except ApiError as exc:
            problems.append(f"Hub: {exc.message}")
        try:
            self._approvals = self.client.pending_approvals()
            self._providers = self.client.providers()
            self._fill(self.provider_list, [describe_provider(p) for p in self._providers])
            self._fill(self.approval_list, [describe_approval(a) for a in self._approvals])
            self._fill(self.audit_box, [f"{r.get('ts')}  {r.get('agent')}  {r.get('outcome')}  {r.get('summary')}"
                                        for r in self.client.audit(60)])
            stopped = bool(self.client.exec_status().get("emergency_stop"))
            self.title("WACC — ACİL DURDURMA AKTİF" if stopped else "WACC")
            self._backend_ok = True
        except ApiError as exc:
            problems.append(f"Backend: {exc.message}")
        self.status.set(" | ".join(problems) if problems else "Bağlı.")
        self._update_dashboard(tasks, stopped)
        if schedule:
            self.after(REFRESH_MS, self.refresh)

    def _update_dashboard(self, tasks, stopped):
        total = len(self._agents)
        active = sum(1 for a in self._agents if a.get("enabled", 1))
        self._set_meter(self.m_agents, active / total if total else 0, f"{active}/{total}")
        open_tasks = sum(1 for t in tasks if str(t.get("status")).lower() not in ("done", "completed", "cancelled", "canceled"))
        self._set_meter(self.m_tasks, open_tasks / len(tasks) if tasks else 0, f"{open_tasks}/{len(tasks)}")
        pending = len(self._approvals)
        self._set_meter(self.m_approvals, min(pending / 5, 1.0), str(pending), AMBER if pending else GREEN)
        for label, ok, name in ((self.link_hub, self._hub_ok, "Hub"), (self.link_backend, self._backend_ok, "Backend")):
            label.configure(text=f"● {name}", fg=GREEN if ok else RED)
        if not (self._hub_ok or self._backend_ok):
            state = "offline"
        elif stopped:
            state = "stopped"
        elif pending:
            state = "pending"
        else:
            state = "idle"
        self._set_state(state)
        self.nav["approvals"].configure(text=f"ONAYLAR ({pending})" if pending else "ONAYLAR")

    def decide(self, approve: bool):
        sel = self.approval_list.curselection()
        if not sel:
            return
        item = self._approvals[sel[0]]
        question = ("Bu eylemi ONAYLIYOR musun?\n\n" if approve else "Bu eylemi reddediyor musun?\n\n") + describe_approval(item)
        if not messagebox.askyesno("WACC", question):
            return
        try:
            (self.client.approve if approve else self.client.deny)(item["id"])
        except ApiError as exc:
            messagebox.showerror("WACC", exc.message)
        self.refresh(schedule=False)

    def _selected_agent(self):
        sel = self.agents_box.curselection()
        return self._agents[sel[0]] if sel else None

    def add_agent(self):
        dialog = AgentDialog(self, [p["name"] for p in self._providers])
        self.wait_window(dialog)
        if not dialog.result:
            return
        res = self._call(self.client.register_agent, **dialog.result)
        if res is None:
            return
        self.refresh(schedule=False)
        messagebox.showinfo(
            "WACC", f"Ajan eklendi: {res['agent']['agent_id']}\n\nBu ajanın Hub token'ı (yalnızca şimdi gösterilir, "
                    f"data\\tokens.json içinde de durur):\n\n{res['token']}\n\nToken'ı yalnızca o ajan oturumuna ver, başkasıyla paylaşma.")

    def toggle_agent(self):
        a = self._selected_agent()
        if a and self._call(self.client.set_agent_enabled, a["agent_id"], not a.get("enabled", 1)) is not None:
            self.refresh(schedule=False)

    def remove_agent(self):
        a = self._selected_agent()
        if not a:
            return
        if a.get("kind", "builtin") == "builtin":
            messagebox.showinfo("WACC", "Hazır ajanlar silinmez, yalnızca kapatılabilir (Aç / Kapat).")
            return
        if messagebox.askyesno("WACC", f"{a['agent_id']} silinsin mi? Token'ı iptal olur, açık görevleri boşa düşer, kilitleri kalkar."):
            if self._call(self.client.remove_agent, a["agent_id"]) is not None:
                self.refresh(schedule=False)

    def _selected_provider(self):
        sel = self.provider_list.curselection()
        return self._providers[sel[0]] if sel else None

    def _call(self, fn, *args):
        try:
            return fn(*args)
        except ApiError as exc:
            messagebox.showerror("WACC", exc.message)
        return None

    def add_account(self):
        dialog = AccountDialog(self)
        self.wait_window(dialog)
        if dialog.result and self._call(self.client.add_account, dialog.result) is not None:
            self.refresh(schedule=False)

    def toggle_provider(self):
        p = self._selected_provider()
        if p and self._call(self.client.set_provider_enabled, p["name"], not p.get("enabled", True)) is not None:
            self.refresh(schedule=False)

    def test_provider(self):
        p = self._selected_provider()
        if not p:
            return
        res = self._call(self.client.test_provider, p["name"])
        if res is None:
            return
        text = (f"Çalışıyor ({res.get('latency_ms')} ms): {res.get('reply')}" if res.get("ok")
                else f"BAŞARISIZ: {res.get('error')}")
        messagebox.showinfo("WACC", text)

    def remove_account(self):
        p = self._selected_provider()
        if not p:
            return
        if p.get("source") != "account":
            messagebox.showinfo("WACC", "Bu sağlayıcı ortam ayarından geliyor (data\\llm.env). Buradan silinmez, yalnızca kapatılabilir.")
            return
        if messagebox.askyesno("WACC", f"{p['name']} hesabı silinsin mi? Kayıtlı API anahtarı da silinir."):
            if self._call(self.client.remove_account, p["name"]) is not None:
                self.refresh(schedule=False)

    def emergency_stop(self):
        for fn in (self.client.hub_stop, self.client.exec_stop):
            try:
                fn()
            except ApiError as exc:
                messagebox.showerror("WACC", exc.message)
        self.refresh(schedule=False)

    def resume(self):
        if not messagebox.askyesno("WACC", "Acil durdurma kaldırılsın mı?"):
            return
        try:
            self.client.exec_resume()
        except ApiError as exc:
            messagebox.showerror("WACC", exc.message)
        self.refresh(schedule=False)


class SettingsDialog(tk.Toplevel):
    """The three access tokens. The installed app fills them in by itself; this is only for running from source."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Ayarlar")
        self.configure(bg=BG)
        self.transient(parent)
        self.resizable(False, False)
        explain = ("Bu üç anahtar, uygulamanın kendi servislerine (Hub, Backend) girmek için kullandığı şifrelerdir.\n"
                   "Kurulu uygulamada (WACC-Setup.exe) otomatik doldurulur: buraya hiçbir şey yazman gerekmez.\n"
                   "Yalnızca kaynak koddan elle çalıştırıyorsan, data klasöründeki token dosyalarından yapıştır.\n"
                   "Token'lar diske yazılmaz.")
        ttk.Label(self, text=explain, justify="left", wraplength=440).grid(row=0, column=0, columnspan=2, padx=14, pady=(14, 8), sticky="w")
        rows = (("Hub token (ajanlar ve görevler)", "hub"), ("Backend token (yapay zeka, komut çalıştırma)", "backend"),
                ("Onay token'ı (onay verebilen sen)", "user"))
        for i, (label, key) in enumerate(rows, start=1):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", padx=14, pady=4)
            ttk.Entry(self, textvariable=parent.vars[key], show="*", width=26).grid(row=i, column=1, padx=14, pady=4)
        buttons = ttk.Frame(self)
        buttons.grid(row=len(rows) + 1, column=0, columnspan=2, pady=12)
        ttk.Button(buttons, text="Bağlan", command=self._connect).pack(side="left", padx=6)
        ttk.Button(buttons, text="Kapat", command=self.destroy).pack(side="left")
        self._parent = parent

    def _connect(self):
        self._parent.connect()
        self.destroy()


class AgentDialog(tk.Toplevel):
    """Add an agent account of any kind. 'Bağlı yapay zeka hesabı' is optional (an account from the Yapay Zeka tab)."""

    def __init__(self, parent, provider_names):
        super().__init__(parent)
        self.title("Ajan ekle")
        self.configure(bg=BG)
        self.result = None
        self.transient(parent)
        self.vars = {"name": tk.StringVar(), "kind": tk.StringVar(value="claude"), "role": tk.StringVar(),
                     "provider": tk.StringVar()}
        rows = (("Ad (küçük harf, örn. claude4, gpt1)", "name", None), ("Tür", "kind", ("claude", "gemini", "chatgpt", "other")),
                ("Rol (boşsa türe göre)", "role", None), ("Bağlı yapay zeka hesabı (isteğe bağlı)", "provider", [""] + list(provider_names)))
        for i, (label, key, values) in enumerate(rows):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=3)
            if values is not None:
                widget = ttk.Combobox(self, textvariable=self.vars[key], values=values, state="readonly", width=38)
            else:
                widget = ttk.Entry(self, textvariable=self.vars[key], width=40)
            widget.grid(row=i, column=1, padx=8, pady=3)
        buttons = ttk.Frame(self)
        buttons.grid(row=len(rows), column=0, columnspan=2, pady=8)
        ttk.Button(buttons, text="Ekle", command=self._ok).pack(side="left", padx=6)
        ttk.Button(buttons, text="Vazgeç", command=self.destroy).pack(side="left")
        self.grab_set()

    def _ok(self):
        self.result = {k: v.get().strip() for k, v in self.vars.items()}
        self.destroy()


class AccountDialog(tk.Toplevel):
    """Add an AI account. The API key field is masked and the key is only sent to the backend."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Yapay zeka hesabı ekle")
        self.configure(bg=BG)
        self.result = None
        self.transient(parent)
        self.vars = {k: tk.StringVar(value=v) for k, v in
                     (("name", ""), ("kind", "cloud"), ("base_url", "https://"), ("model", ""), ("api_key", ""))}
        rows = (("Ad (küçük harf, örn. openrouter)", "name"), ("Tür (local / cloud)", "kind"),
                ("Adres (OpenAI uyumlu /v1; yerel: http://127.0.0.1:11434/v1)", "base_url"),
                ("Model adı", "model"), ("API anahtarı (yerel için boş)", "api_key"))
        for i, (label, key) in enumerate(rows):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=3)
            if key == "kind":
                widget = ttk.Combobox(self, textvariable=self.vars[key], values=("local", "cloud"), state="readonly", width=38)
            else:
                widget = ttk.Entry(self, textvariable=self.vars[key], width=40, show="*" if key == "api_key" else "")
            widget.grid(row=i, column=1, padx=8, pady=3)
        buttons = ttk.Frame(self)
        buttons.grid(row=len(rows), column=0, columnspan=2, pady=8)
        ttk.Button(buttons, text="Ekle", command=self._ok).pack(side="left", padx=6)
        ttk.Button(buttons, text="Vazgeç", command=self.destroy).pack(side="left")
        self.grab_set()

    def _ok(self):
        spec = {k: v.get().strip() for k, v in self.vars.items()}
        if not spec["api_key"]:
            spec.pop("api_key")
        self.result = spec
        self.destroy()


def main():
    App().mainloop()
