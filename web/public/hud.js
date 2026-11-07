"use strict";

/* WACC control-room HUD: clock, left-panel meters, link lights and the animated radar.
 * Read-only view of the panel's own `state` (declared in app.js); it never talks to the network
 * and never touches tokens. Loaded before app.js, so `state` is only read lazily at run time. */

(function () {
  const byId = (id) => document.getElementById(id);

  const MODES = {
    boot:    { color: "#2b6058", label: "BAĞLANIYOR",          fast: false },
    idle:    { color: "#37e6b3", label: "BEKLEMEDE",           fast: false },
    pending: { color: "#ff9f3a", label: "ONAYINI BEKLİYOR",    fast: true },
    stopped: { color: "#ff4d4d", label: "ACİL DURDURMA AKTİF", fast: true },
    auth:    { color: "#3aa0ff", label: "TOKEN GEREKLİ",       fast: false },
    offline: { color: "#56666a", label: "BAĞLANTI YOK",        fast: false },
  };

  function appState() { return typeof state === "undefined" ? null : state; }

  function currentMode() {
    const s = appState();
    const conn = byId("conn");
    if (!s || !conn) return "boot";
    if (conn.classList.contains("bad")) return "offline";
    if (s.data.emergency) return "stopped";
    if (conn.classList.contains("warn")) return "auth";
    if (s.pendingCount > 0) return "pending";
    return conn.classList.contains("ok") ? "idle" : "boot";
  }

  /* ---------------------------------------------------------------- clock */
  function tickClock() {
    const now = new Date();
    byId("clock").textContent = String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0");
    byId("date-line").textContent = now.toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit", year: "numeric", weekday: "long" });
  }

  /* --------------------------------------------------------------- meters */
  function setBar(key, fraction, text, tone) {
    const fill = byId("bar-" + key);
    byId("pct-" + key).textContent = text;
    fill.style.width = Math.round(Math.max(0, Math.min(1, fraction)) * 100) + "%";
    fill.classList.remove("warn", "danger");
    if (tone) fill.classList.add(tone);
  }

  function setDot(id, tone) {
    byId(id).className = "link-dot" + (tone ? " " + tone : "");
  }

  function toneOf(badgeId) {
    const badge = byId(badgeId);
    if (!badge) return "";
    for (const tone of ["ok", "warn", "bad"]) if (badge.classList.contains(tone)) return tone;
    return "";
  }

  function updateHud() {
    tickClock();
    const s = appState();
    if (!s) return;
    const agents = s.data.agents || [];
    const online = agents.filter((a) => a.online).length;
    setBar("agents", agents.length ? online / agents.length : 0, online + "/" + agents.length);
    const tasks = s.data.tasks || [];
    const done = tasks.filter((t) => t.status === "COMPLETED" || t.status === "CANCELLED").length;
    setBar("tasks", tasks.length ? done / tasks.length : 0, done + "/" + tasks.length);
    const locks = (s.data.locks || []).length;
    setBar("locks", locks / 10, String(locks), locks >= 8 ? "warn" : "");
    const pending = s.pendingCount || 0;
    setBar("approvals", pending / 5, String(pending), pending >= 3 ? "danger" : pending ? "warn" : "");
    setDot("dot-hub", toneOf("conn"));
    setDot("dot-backend", toneOf("backendConn") || toneOf("approvalConn"));
    setDot("dot-approval", s.approvalToken ? "ok" : "warn");

    const mode = currentMode();
    const spec = MODES[mode];
    const label = byId("state-label");
    label.textContent = spec.label;
    const root = document.documentElement;
    root.style.setProperty("--state-color", spec.color);
    root.style.setProperty("--state-glow", spec.color + "66");
    const caption = byId("caption");
    const text = {
      pending: pending + " onay bekliyor: Onaylar sekmesine bak",
      stopped: "Tüm ajanlar durduruldu",
      auth: "Ayarlar'dan token gir",
      offline: "Hub'a ulaşılamıyor",
    }[mode] || "";
    caption.textContent = text;
    caption.classList.toggle("visible", Boolean(text));
    byId("hud-note").textContent = s.me ? "Giriş: " + s.me : "";
  }

  /* ---------------------------------------------------------------- radar */
  const canvas = byId("radar-canvas");
  const ctx = canvas.getContext("2d");
  let stars = [];
  let arc1 = 0;
  let arc2 = 180;

  function resizeCanvas() {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(rect.width * dpr));
    canvas.height = Math.max(1, Math.round(rect.height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    stars = [];
  }

  function initStars(rMax) {
    stars = [];
    for (let i = 0; i < 110; i++) {
      stars.push({
        angle: Math.random() * Math.PI * 2,
        radius: 10 + Math.random() * Math.max(10, rMax - 10),
        size: 0.8 + Math.random() * 1.8,
        phase: Math.random() * Math.PI * 2,
        drift: (Math.random() - 0.5) * 0.0006,
      });
    }
  }

  const rad = (d) => (d * Math.PI) / 180;

  function drawRadar(t) {
    const rect = canvas.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;
    if (w < 10 || h < 10) { requestAnimationFrame(drawRadar); return; }
    const dpr = window.devicePixelRatio || 1;
    if (Math.abs(canvas.width - w * dpr) > 2 || Math.abs(canvas.height - h * dpr) > 2) resizeCanvas();

    const spec = MODES[currentMode()];
    const color = spec.color;
    ctx.clearRect(0, 0, w, h);
    const cx = w / 2;
    const cy = h / 2;
    const rOuter = Math.max(30, Math.min(w, h) / 2 - 14);
    const rInner = rOuter * 0.72;
    if (stars.length === 0) initStars(rInner - 6);
    const sec = t / 1000;

    ctx.strokeStyle = "rgba(55,230,179,0.10)";
    ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(cx, cy, rOuter, 0, Math.PI * 2); ctx.stroke();
    ctx.strokeStyle = "rgba(55,230,179,0.06)";
    ctx.beginPath(); ctx.arc(cx, cy, rInner, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.arc(cx, cy, rInner * 0.45, 0, Math.PI * 2); ctx.stroke();

    for (const s of stars) {
      s.angle += s.drift * (spec.fast ? 3 : 1);
      const sx = cx + s.radius * Math.cos(s.angle);
      const sy = cy + s.radius * Math.sin(s.angle);
      const twinkle = 0.5 + 0.5 * Math.sin(sec * 2 + s.phase);
      const size = s.size * (0.6 + twinkle * 0.7);
      ctx.beginPath();
      ctx.arc(sx, sy, size, 0, Math.PI * 2);
      ctx.fillStyle = twinkle > 0.7 ? "rgba(210,225,255,0.95)" : "rgba(140,165,195,0.55)";
      ctx.shadowBlur = twinkle > 0.75 ? 6 : 0;
      ctx.shadowColor = "#bcd6ff";
      ctx.fill();
    }
    ctx.shadowBlur = 0;

    const speed = spec.fast ? 1.8 : 0.7;
    arc1 = (arc1 + speed) % 360;
    arc2 = (arc2 - speed * 0.7 + 360) % 360;

    ctx.lineWidth = 3;
    ctx.strokeStyle = color;
    ctx.shadowBlur = 10;
    ctx.shadowColor = color;
    ctx.beginPath(); ctx.arc(cx, cy, rOuter, rad(arc1), rad(arc1 + 55)); ctx.stroke();

    ctx.lineWidth = 2;
    ctx.strokeStyle = "#1f6e5a";
    ctx.shadowColor = "#1f6e5a";
    ctx.shadowBlur = 6;
    ctx.beginPath(); ctx.arc(cx, cy, rInner * 0.9, rad(arc2), rad(arc2 + 40)); ctx.stroke();
    ctx.shadowBlur = 0;

    const pulse = 0.5 + 0.5 * Math.sin(sec * (spec.fast ? 4 : 2));
    const coreR = 9 + pulse * 7;
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR * 2.2);
    grad.addColorStop(0, color);
    grad.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = grad;
    ctx.beginPath(); ctx.arc(cx, cy, coreR * 2.2, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(cx, cy, coreR, 0, Math.PI * 2); ctx.fill();

    requestAnimationFrame(drawRadar);
  }

  /* ------------------------------------------------------- settings dialog */
  function setModal(open) {
    byId("settings-modal").classList.toggle("hidden", !open);
    if (open) byId("token").focus();
  }

  window.addEventListener("load", () => {
    resizeCanvas();
    requestAnimationFrame(drawRadar);
    updateHud();
    setInterval(updateHud, 1000);
  });
  window.addEventListener("resize", resizeCanvas);
  byId("settingsBtn").addEventListener("click", () => setModal(true));
  byId("settingsClose").addEventListener("click", () => setModal(false));
  byId("settings-modal").addEventListener("click", (ev) => { if (ev.target === ev.currentTarget) setModal(false); });
  byId("tokenForm").addEventListener("submit", () => setModal(false));
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") setModal(false); });
  window.WACCHud = { update: updateHud, closeSettings: () => setModal(false), openSettings: () => setModal(true) };
})();
