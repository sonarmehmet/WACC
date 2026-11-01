"use strict";

/* WACC web panel (T-0005). Plain JS, no build step.
 * Every value that comes from the Hub is untrusted agent text: it is only ever added as a
 * text node (textContent / append), never as HTML. */

const AGENTS = ["claude1", "claude2", "claude3", "gemini", "user"];
const WORKERS = ["claude1", "claude2", "claude3", "gemini"];
const LEADERS = ["claude1", "user"];
const MESSAGE_TYPES = [
  "TASK_ASSIGNMENT", "TASK_ACCEPTED", "TASK_COMPLETED", "TASK_BLOCKED", "HELP_REQUEST",
  "HELP_RESPONSE", "CODE_READY", "REVIEW_REQUEST", "REVIEW_RESULT", "BUG_REPORT", "BUG_FIXED",
  "INTEGRATION_REQUEST", "INTEGRATION_RESULT", "TECHNICAL_DECISION", "HANDOFF",
  "STATUS_UPDATE", "SYSTEM_ALERT",
];
const PRIORITIES = ["LOW", "NORMAL", "HIGH", "CRITICAL"];
const TASK_STATUSES = ["BACKLOG", "ASSIGNED", "ACCEPTED", "IN_PROGRESS", "REVIEW", "BLOCKED", "COMPLETED", "CANCELLED"];
const STATUS_ORDER = ["BLOCKED", "REVIEW", "IN_PROGRESS", "ACCEPTED", "ASSIGNED", "BACKLOG", "COMPLETED", "CANCELLED"];
const STATUS_LABELS = {
  BLOCKED: "Engelli", REVIEW: "İncelemede", IN_PROGRESS: "Devam ediyor", ACCEPTED: "Kabul edildi",
  ASSIGNED: "Atandı", BACKLOG: "Bekleyen", COMPLETED: "Tamamlandı", CANCELLED: "İptal",
};
const REFRESH_MS = 5000;
const TOKEN_KEY = "wacc.token";

const state = {
  token: "",
  me: null,
  tab: "agents",
  conversation: null,
  data: { agents: [], feed: [], tasks: [], locks: [], emergency: false },
  busy: false,
  again: false,
  signatures: {},
};

const $ = (id) => document.getElementById(id);
const enc = encodeURIComponent;

/* ------------------------------------------------------------------ utilities */

// The user token is the only one that can approve things, so it is NOT kept across browser
// sessions unless "Hatırla" is ticked: by default it lives in sessionStorage (gone when the
// tab closes); with "Hatırla" it goes to localStorage. Storage can be blocked: the panel then
// still works for this page load.
function storageArea(persistent) {
  try { return persistent ? window.localStorage : window.sessionStorage; } catch (e) { return null; }
}

function loadToken() {
  for (const persistent of [true, false]) {
    const area = storageArea(persistent);
    let value = "";
    try { value = area ? area.getItem(TOKEN_KEY) || "" : ""; } catch (e) { value = ""; }
    if (value) return { token: value, remember: persistent };
  }
  return { token: "", remember: false };
}

function saveToken(token, remember) {
  for (const persistent of [true, false]) {
    const area = storageArea(persistent);
    if (!area) continue;
    try {
      if (token && persistent === remember) area.setItem(TOKEN_KEY, token);
      else area.removeItem(TOKEN_KEY);
    } catch (e) { /* ignore */ }
  }
}

function el(tag, props, ...kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    node.append(kid); // strings become text nodes, so nothing is parsed as HTML
  }
  return node;
}

function chip(text, tone) {
  return el("span", { class: "chip" + (tone ? " " + tone : ""), text: String(text) });
}

function select(options, value) {
  const node = el("select", {}, options.map((o) => el("option", { value: o, text: o })));
  if (value) node.value = value;
  return node;
}

function labeled(text, control) {
  return el("label", {}, text, control);
}

function parseTime(ts) {
  if (!ts) return null;
  const d = new Date(String(ts).replace(/(\.\d{3})\d+/, "$1"));
  return Number.isNaN(d.getTime()) ? null : d;
}

function fmtTime(ts) {
  const d = parseTime(ts);
  return d ? d.toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "medium" }) : "-";
}

function ago(ts) {
  const d = parseTime(ts);
  if (!d) return "hiç";
  const s = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
  if (s < 60) return s + " sn önce";
  if (s < 3600) return Math.round(s / 60) + " dk önce";
  if (s < 86400) return Math.round(s / 3600) + " sa önce";
  return Math.round(s / 86400) + " gün önce";
}

function newKey() {
  try { return crypto.randomUUID(); } catch (e) { return "k" + Date.now() + Math.random().toString(16).slice(2); }
}

let toastTimer = null;
function toast(text, isError) {
  const box = $("toast");
  box.textContent = text;
  box.className = "toast" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.add("hidden"), 4500);
}

/* ------------------------------------------------------------------------ API */

class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function api(path, options = {}) {
  const headers = { "X-WACC-Token": state.token };
  const init = { method: options.method || "GET", headers };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  let res;
  try {
    res = await fetch("/api" + path, init);
  } catch (e) {
    throw new ApiError(0, "NETWORK", "Panel sunucusuna ulaşılamıyor");
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* empty or non-JSON body */ }
  if (!res.ok) {
    const detail = data && data.detail;
    const message = (detail && detail.message) || (typeof detail === "string" ? detail : "") ||
      "İstek başarısız (" + res.status + ")";
    throw new ApiError(res.status, (detail && detail.code) || "HTTP_" + res.status, message);
  }
  return data;
}

async function act(fn, okText) {
  try {
    await fn();
    toast(okText);
    await refresh();
  } catch (e) {
    toast(e.message || "İşlem başarısız", true);
  }
}

/* ------------------------------------------------------------------ rendering */

// Re-render a region only when its data changed and the user is not typing inside it.
function renderRegion(key, box, data, build) {
  const sig = JSON.stringify(data);
  if (state.signatures[key] === sig) return;
  const active = document.activeElement;
  if (active && box.contains(active) && active.matches("input, select, textarea")) return;
  state.signatures[key] = sig;
  build();
}

function setConn(tone, text) {
  const badge = $("conn");
  badge.className = "badge " + tone;
  badge.textContent = text;
}

function renderStop() {
  const on = state.data.emergency;
  $("stopBadge").classList.toggle("hidden", !on);
  $("stopBtn").classList.toggle("hidden", on || !LEADERS.includes(state.me));
  $("resumeBtn").classList.toggle("hidden", !on || state.me !== "user");
}

function agentCard(a) {
  return el("article", { class: "card agent" },
    el("div", { class: "head" },
      el("span", { class: "dot" + (a.online ? " on" : ""), title: a.online ? "çevrimiçi" : "çevrimdışı" }),
      el("h3", { text: a.agent_id }),
      el("span", { class: "role", text: a.role })),
    el("div", { class: "meta", text: "Durum: " + a.status + (a.current_task ? " · " + a.current_task : "") }),
    el("div", { class: "stats" },
      chip("Okunmamış " + a.unread, a.unread ? "warn" : ""),
      chip("Yanıtlanacak " + a.pending_responses, a.pending_responses ? "warn" : ""),
      chip("Yanıt bekliyor " + a.awaiting_reply),
      chip("Aktif görev " + a.active_tasks),
      chip("Engelli " + a.blocked_tasks, a.blocked_tasks ? "bad" : "")),
    el("div", { class: "meta", text: "Son görülme: " + ago(a.last_seen) }),
    a.last_commit ? el("div", { class: "meta", text: "Son commit: " + String(a.last_commit).slice(0, 10) }) : null,
    a.last_sent ? el("div", { class: "meta", text: "Son mesaj → " + a.last_sent.receiver + ": " + a.last_sent.subject }) : null);
}

function renderAgents() {
  const box = $("agents");
  const minute = Math.floor(Date.now() / 60000); // keeps "x dk önce" fresh
  renderRegion("agents", box, [state.data.agents, minute], () => {
    const list = state.data.agents;
    box.replaceChildren(...(list.length ? list.map(agentCard) : [el("p", { class: "empty", text: "Henüz ajan yok." })]));
  });
}

function messageCard(m) {
  const loud = m.priority === "HIGH" || m.priority === "CRITICAL";
  const cls = "card msg" + (m.sender === state.me ? " me" : "") + (m.message_type === "SYSTEM_ALERT" ? " alert" : "");
  const conv = String(m.conversation_id || "");
  return el("article", { class: cls },
    el("div", { class: "top-line" },
      el("span", { class: "who", text: m.sender + " → " + m.receiver }),
      chip(m.message_type),
      m.priority !== "NORMAL" ? chip(m.priority, loud ? "bad" : "") : null,
      m.response_required && m.status !== "ANSWERED" ? chip("yanıt gerekli", "warn") : null,
      chip(m.status),
      m.task_id ? chip(m.task_id) : null,
      el("span", { class: "meta", text: fmtTime(m.timestamp) }),
      conv ? el("span", {
        class: "meta tag", text: "#" + conv.slice(0, 8), title: "Bu konuşmayı filtrele",
        onclick: () => setConversation(conv),
      }) : null),
    el("div", { class: "subject", text: m.subject }),
    m.content ? el("div", { class: "body", text: m.content }) : null);
}

function renderFeed() {
  const box = $("feed");
  renderRegion("feed", box, [state.data.feed, state.me], () => {
    const newestFirst = state.data.feed.slice().reverse();
    box.replaceChildren(...(newestFirst.length ? newestFirst.map(messageCard)
      : [el("p", { class: "empty", text: "Henüz mesaj yok." })]));
  });
  const filtered = Boolean(state.conversation);
  $("clearFilter").classList.toggle("hidden", !filtered);
  $("filterInfo").textContent = filtered ? "Konuşma #" + state.conversation.slice(0, 8) + " gösteriliyor" : "Tüm konuşmalar";
  const hint = $("convHint");
  hint.classList.toggle("hidden", !filtered);
  hint.textContent = filtered ? "Mesaj #" + state.conversation.slice(0, 8) + " konuşmasına eklenecek." : "";
}

function taskActions(t) {
  const wrap = el("div", { class: "actions" });
  const path = "/tasks/" + enc(t.task_id);
  if (t.owner === state.me && t.status === "ASSIGNED") {
    wrap.append(el("button", {
      type: "button", class: "small", text: "Kabul et",
      onclick: () => act(() => api(path + "/accept", { method: "POST" }), t.task_id + " kabul edildi"),
    }));
  }
  const status = select(TASK_STATUSES, t.status);
  const commit = el("input", { type: "text", placeholder: "commit hash" });
  const note = el("input", { type: "text", placeholder: "not" });
  wrap.append(
    labeled("Durum", status), labeled("Commit", commit), labeled("Not", note),
    el("button", {
      type: "button", class: "small", text: "Durumu güncelle",
      onclick: () => act(() => api(path + "/status", {
        method: "POST",
        body: { status: status.value, commit: commit.value.trim() || null, note: note.value.trim() || null },
      }), t.task_id + " güncellendi"),
    }));
  if (LEADERS.includes(state.me)) {
    const owner = select(WORKERS, t.owner || "claude2");
    wrap.append(labeled("Sahip", owner), el("button", {
      type: "button", class: "small", text: "Ata",
      onclick: () => act(() => api(path + "/assign/" + enc(owner.value), { method: "POST" }),
        t.task_id + " → " + owner.value),
    }));
  }
  return wrap;
}

function taskCard(t) {
  const canAct = state.me && (t.owner === state.me || LEADERS.includes(state.me));
  const deps = t.dependencies || [];
  const files = t.affected_files || [];
  const meta = [
    t.branch && "dal: " + t.branch,
    t.commit_hash && "commit: " + String(t.commit_hash).slice(0, 10),
    deps.length && "bağımlı: " + deps.join(", "),
    files.length && "dosyalar: " + files.join(", "),
  ].filter(Boolean).join(" · ");
  const loud = t.priority === "HIGH" || t.priority === "CRITICAL";
  return el("article", { class: "card task" },
    el("div", { class: "head" },
      el("strong", { text: t.task_id }),
      el("span", { text: t.title }),
      t.priority !== "NORMAL" ? chip(t.priority, loud ? "bad" : "") : null,
      chip(t.owner ? "→ " + t.owner : "sahipsiz")),
    meta ? el("div", { class: "meta", text: meta }) : null,
    t.note ? el("div", { class: "meta", text: "Not: " + t.note }) : null,
    el("details", {},
      el("summary", { text: "Ayrıntı ve işlemler" }),
      t.description ? el("div", { class: "body", text: t.description }) : null,
      t.acceptance ? el("div", { class: "meta", text: "Kabul: " + t.acceptance }) : null,
      t.test_criteria ? el("div", { class: "meta", text: "Test: " + t.test_criteria }) : null,
      canAct ? taskActions(t) : null));
}

function renderTasks() {
  const box = $("tasks");
  renderRegion("tasks", box, [state.data.tasks, state.me], () => {
    const tasks = state.data.tasks;
    if (!tasks.length) {
      box.replaceChildren(el("p", { class: "empty", text: "Henüz görev yok." }));
      return;
    }
    const groups = STATUS_ORDER
      .map((s) => [s, tasks.filter((t) => t.status === s)])
      .filter(([, list]) => list.length);
    box.replaceChildren(...groups.map(([s, list]) => el("section", { class: "group" },
      el("h2", {}, STATUS_LABELS[s] || s, chip(list.length)),
      list.map(taskCard))));
  });
  const isLeader = LEADERS.includes(state.me);
  $("taskHint").classList.toggle("hidden", isLeader || !state.me);
  $("taskSubmit").disabled = !isLeader;
}

function renderLocks() {
  const box = $("locks");
  renderRegion("locks", box, [state.data.locks, Math.floor(Date.now() / 60000)], () => {
    const locks = state.data.locks;
    if (!locks.length) {
      box.replaceChildren(el("p", { class: "empty", text: "Aktif kilit yok." }));
      return;
    }
    const head = el("tr", {}, ["Yol", "Sahip", "Görev", "Bitiş", "Durum"].map((h) => el("th", { text: h })));
    const rows = locks.map((l) => el("tr", {},
      el("td", { text: l.path }), el("td", { text: l.owner }), el("td", { text: l.task_id || "-" }),
      el("td", { text: fmtTime(l.expires_at) }),
      el("td", {}, l.expired ? chip("süresi doldu", "bad") : chip("aktif"))));
    box.replaceChildren(el("table", {}, el("thead", {}, head), el("tbody", {}, rows)));
  });
}

function renderAll() {
  renderStop();
  renderAgents();
  renderFeed();
  renderTasks();
  renderLocks();
}

/* -------------------------------------------------------------------- refresh */

async function refresh() {
  if (state.busy) { state.again = true; return; }
  state.busy = true;
  try {
    let health;
    try {
      health = await api("/health");
    } catch (e) {
      setConn("bad", e.code === "HUB_UNREACHABLE" ? "Hub'a ulaşılamıyor" : e.message);
      return;
    }
    state.data.emergency = Boolean(health.emergency_stop);
    if (!state.token) {
      state.me = null;
      setConn("warn", "Token gerekli");
      renderStop();
      return;
    }
    try {
      state.me = (await api("/whoami")).agent;
    } catch (e) {
      state.me = null;
      setConn(e.status === 401 ? "warn" : "bad", e.status === 401 ? "Token geçersiz" : e.message);
      renderStop();
      return;
    }
    setConn("ok", "Bağlı: " + state.me);
    const feedPath = "/feed?limit=200" + (state.conversation ? "&conversation_id=" + enc(state.conversation) : "");
    const [agents, feed, tasks, locks] = await Promise.all([
      api("/agents"), api(feedPath), api("/tasks"), api("/locks"),
    ]);
    Object.assign(state.data, { agents, feed, tasks, locks });
    renderAll();
  } catch (e) {
    setConn("bad", e.message || "Bağlantı hatası");
  } finally {
    state.busy = false;
    if (state.again) { state.again = false; refresh(); }
  }
}

/* ---------------------------------------------------------------- interaction */

function setTab(name) {
  state.tab = name;
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("hidden", s.id !== "tab-" + name));
}

function setConversation(id) {
  state.conversation = id || null;
  state.signatures.feed = null;
  setTab("feed");
  refresh();
}

function fill(selectNode, options, value) {
  selectNode.replaceChildren(...options.map((o) => {
    const label = typeof o === "string" ? { value: o, text: o } : o;
    return el("option", { value: label.value, text: label.text });
  }));
  if (value !== undefined) selectNode.value = value;
}

function init() {
  fill($("msgReceiver"), [...AGENTS, "ALL"], "claude1");
  fill($("msgType"), MESSAGE_TYPES, "STATUS_UPDATE");
  fill($("msgPriority"), PRIORITIES, "NORMAL");
  fill($("taskOwner"), [{ value: "", text: "Sahipsiz (BACKLOG)" }, ...WORKERS.map((w) => ({ value: w, text: w }))], "");
  fill($("taskPriority"), PRIORITIES, "NORMAL");

  const saved = loadToken();
  state.token = saved.token;
  $("token").value = saved.token;
  $("remember").checked = saved.remember; // off unless the user chose to keep the token

  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));

  $("tokenForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    state.token = $("token").value.trim();
    saveToken(state.token, $("remember").checked);
    state.signatures = {};
    refresh();
  });
  // Changing the checkbox moves an already-saved token between the two stores right away.
  $("remember").addEventListener("change", () => {
    if (state.token) saveToken(state.token, $("remember").checked);
  });
  $("forgetToken").addEventListener("click", () => {
    state.token = "";
    state.me = null;
    state.signatures = {};
    $("token").value = "";
    $("remember").checked = false;
    saveToken("", false);
    refresh();
  });

  $("clearFilter").addEventListener("click", () => setConversation(null));

  $("msgForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const body = {
      receiver: $("msgReceiver").value,
      message_type: $("msgType").value,
      priority: $("msgPriority").value,
      subject: $("msgSubject").value.trim(),
      content: $("msgContent").value,
      response_required: $("msgResponse").checked,
      idempotency_key: newKey(),
    };
    if (state.conversation) body.conversation_id = state.conversation;
    act(async () => {
      await api("/messages", { method: "POST", body });
      $("msgSubject").value = "";
      $("msgContent").value = "";
      $("msgResponse").checked = false;
    }, "Mesaj gönderildi");
  });

  $("taskForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const button = $("taskSubmit");
    const body = {
      title: $("taskTitle").value.trim(),
      description: $("taskDescription").value,
      owner: $("taskOwner").value || null,
      priority: $("taskPriority").value,
      affected_files: $("taskFiles").value.split(",").map((s) => s.trim()).filter(Boolean),
      acceptance: $("taskAcceptance").value.trim(),
      test_criteria: $("taskTests").value.trim(),
    };
    button.disabled = true; // the task API has no idempotency key: block double submits
    act(async () => {
      try {
        await api("/tasks", { method: "POST", body });
        $("taskForm").reset();
      } finally {
        button.disabled = !LEADERS.includes(state.me);
      }
    }, "Görev oluşturuldu");
  });

  $("stopBtn").addEventListener("click", () => {
    if (!window.confirm("Tüm ajanlar için ACİL DURDURMA açılsın mı?")) return;
    act(() => api("/system/stop", { method: "POST", body: { reason: "web panel: manual stop" } }), "Acil durdurma açıldı");
  });
  $("resumeBtn").addEventListener("click", () => {
    act(() => api("/system/resume", { method: "POST" }), "Çalışma devam ettirildi");
  });

  setTab("agents");
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, REFRESH_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
}

init();
