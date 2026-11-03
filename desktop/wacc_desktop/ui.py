"""Tkinter window: agents, tasks, approvals and the emergency stop. Refreshes every 5 seconds."""

from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from .client import ApiError, WaccClient, describe_approval, describe_provider

REFRESH_MS = 5000


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WACC")
        self.geometry("980x600")
        self._set_icon()
        self.client = WaccClient()
        self._approvals = []
        self._build()
        self.after(200, self.refresh)

    def _set_icon(self):
        icon = Path(__file__).resolve().parents[2] / "assets" / "icon-192.png"
        try:
            self._icon = tk.PhotoImage(file=str(icon))  # keep a reference or Tk drops it
            self.iconphoto(True, self._icon)
        except (tk.TclError, OSError):
            pass  # a missing icon must never stop the panel

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

        ai = ttk.Frame(tabs)
        tabs.add(ai, text="Yapay Zeka")
        self.provider_list = tk.Listbox(ai, activestyle="none")
        self.provider_list.pack(fill="both", expand=True, padx=4, pady=4)
        row = ttk.Frame(ai)
        row.pack(fill="x", padx=4, pady=(0, 4))
        for label, cmd in (("Hesap ekle", self.add_account), ("Aç / Kapat", self.toggle_provider),
                           ("Test et", self.test_provider), ("Sil", self.remove_account)):
            ttk.Button(row, text=label, command=cmd).pack(side="left", padx=(0, 6))
        ttk.Label(row, text="Değiştirmek için onay token'ı gerekir. API anahtarı kaydedilir ama bir daha gösterilmez.").pack(side="left", padx=6)
        self._providers = []

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
            self._providers = self.client.providers()
            self._fill(self.provider_list, [describe_provider(p) for p in self._providers])
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


class AccountDialog(tk.Toplevel):
    """Add an AI account. The API key field is masked and the key is only sent to the backend."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Yapay zeka hesabı ekle")
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
