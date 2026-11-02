"""Tkinter window: agents, tasks, approvals and the emergency stop. Refreshes every 5 seconds."""

import tkinter as tk
from tkinter import messagebox, ttk

from .client import ApiError, WaccClient, describe_approval

REFRESH_MS = 5000


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WACC")
        self.geometry("980x600")
        self.client = WaccClient()
        self._approvals = []
        self._build()
        self.after(200, self.refresh)

    # ------------------------------------------------------------------ layout
    def _build(self):
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        self.vars = {}
        for label, key in (("Hub token", "hub"), ("Backend token", "backend"), ("Onay token'ı", "user")):
            ttk.Label(top, text=label).pack(side="left", padx=(0, 2))
            var = tk.StringVar()
            self.vars[key] = var
            ttk.Entry(top, textvariable=var, show="*", width=18).pack(side="left", padx=(0, 8))
        ttk.Button(top, text="Bağlan", command=self.connect).pack(side="left")
        ttk.Button(top, text="ACİL DURDUR", command=self.emergency_stop).pack(side="right")
        ttk.Button(top, text="Devam ettir", command=self.resume).pack(side="right", padx=6)

        self.status = tk.StringVar(value="Token'ları girip Bağlan'a bas. (Token'lar diske yazılmaz.)")
        ttk.Label(self, textvariable=self.status, padding=(6, 0)).pack(fill="x")

        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=6, pady=6)
        self.agents_box = self._tab(tabs, "Ajanlar")
        self.tasks_box = self._tab(tabs, "Görevler")
        self.audit_box = self._tab(tabs, "Denetim")

        approvals = ttk.Frame(tabs)
        tabs.add(approvals, text="Onaylar")
        self.approval_list = tk.Listbox(approvals, activestyle="none")
        self.approval_list.pack(fill="both", expand=True, padx=4, pady=4)
        buttons = ttk.Frame(approvals)
        buttons.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(buttons, text="Onayla", command=lambda: self.decide(True)).pack(side="left")
        ttk.Button(buttons, text="Reddet", command=lambda: self.decide(False)).pack(side="left", padx=6)
        ttk.Label(buttons, text="Onaylamadan önce komutu dikkatle oku: onay yalnızca bu tek eylem içindir.").pack(side="left", padx=8)

    def _tab(self, tabs, title):
        frame = ttk.Frame(tabs)
        tabs.add(frame, text=title)
        box = tk.Listbox(frame, activestyle="none")
        box.pack(fill="both", expand=True, padx=4, pady=4)
        return box

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
        try:
            self._fill(self.agents_box, [f"{a.get('id') or a.get('name')}  {a.get('status', '')}  {a.get('current_task') or ''}"
                                         for a in self.client.agents()])
            self._fill(self.tasks_box, [f"{t.get('id')}  [{t.get('status')}]  {t.get('owner') or '-'}  {t.get('title')}"
                                        for t in self.client.tasks()])
        except ApiError as exc:
            problems.append(f"Hub: {exc.message}")
        try:
            self._approvals = self.client.pending_approvals()
            self._fill(self.approval_list, [describe_approval(a) for a in self._approvals])
            self._fill(self.audit_box, [f"{r.get('ts')}  {r.get('agent')}  {r.get('outcome')}  {r.get('summary')}"
                                        for r in self.client.audit(60)])
            stopped = self.client.exec_status().get("emergency_stop")
            self.title("WACC — ACİL DURDURMA AKTİF" if stopped else "WACC")
        except ApiError as exc:
            problems.append(f"Backend: {exc.message}")
        self.status.set(" | ".join(problems) if problems else "Bağlı.")
        if schedule:
            self.after(REFRESH_MS, self.refresh)

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


def main():
    App().mainloop()
