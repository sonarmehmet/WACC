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
const BACKEND_TOKEN_KEY = "wacc.backend_token";

const state = {
  token: "",
  backendToken: "",
  me: null,
  tab: "agents",
  conversation: null,
  data: { agents: [], feed: [], tasks: [], locks: [], emergency: false, backend: null },
  busy: false,
  again: false,
  backendBusy: false,
  backendAgain: false,
  backendGen: 0,
  approvalToken: "", // memory only: never written to any storage
  approvalTimer: null,
  approvalBusy: false,
  approvalAgain: false,
  approvalGen: 0,
  pendingCount: 0,
  aiBusy: false,
  aiAgain: false,
  aiGen: 0,
  aiTests: {}, // provider name -> last test result (no secrets)
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

function loadToken(key) {
  for (const persistent of [true, false]) {
    const area = storageArea(persistent);
    let value = "";
    try { value = area ? area.getItem(key) || "" : ""; } catch (e) { value = ""; }
    if (value) return { token: value, remember: persistent };
  }
  return { token: "", remember: false };
}

function saveToken(key, token, remember) {
  for (const persistent of [true, false]) {
    const area = storageArea(persistent);
    if (!area) continue;
    try {
      if (token && persistent === remember) area.setItem(key, token);
      else area.removeItem(key);
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

// Hub: /api/<path> with the hub token. Backend: /backend/<path>, read-only, own token.
function api(path, options = {}) {
  return request("/api", state.token, path, options);
}

function backendGet(path) {
  return request("/backend", state.backendToken, path, {});
}

async function request(prefix, token, path, options) {
  const headers = { "X-WACC-Token": token };
  const init = { method: options.method || "GET", headers };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  let res;
  try {
    res = await fetch(prefix + path, init);
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

/* -------------------------------------------------------------------- backend */

function clip(value, max) {
  const s = value == null ? "" : String(value);
  return s.length > max ? s.slice(0, max) + "…" : s;
}

function dataTable(headers, rows) {
  return el("table", {},
    el("thead", {}, el("tr", {}, headers.map((h) => el("th", { text: h })))),
    el("tbody", {}, rows.map((cells) => el("tr", {}, cells.map((c) => el("td", {}, c))))));
}

function section(title, ...content) {
  return el("section", { class: "group" }, el("h2", { text: title }), ...content);
}

function emptyNote(text) {
  return el("p", { class: "empty", text });
}

function setBackendConn(tone, text) {
  const badge = $("backendConn");
  badge.className = "badge " + tone;
  badge.textContent = text;
}

function agentStatusChip(status) {
  const tone = status === "BUSY" ? "warn" : (status === "DISABLED" ? "bad" : "");
  return chip(status, tone);
}

function jobStatusChip(status) {
  return chip(status, status === "FAILED" ? "bad" : (status === "RUNNING" ? "warn" : ""));
}

function renderBackend() {
  const box = $("backend");
  const b = state.data.backend;
  renderRegion("backend", box, [b, Math.floor(Date.now() / 60000)], () => {
    if (!b) { box.replaceChildren(); return; }
    const parts = [];
    const meta = "Sürüm " + b.health.version + " · veritabanı şema " + b.health.schema_version;
    if (b.locked) {
      parts.push(section("Durum", el("div", { class: "card meta", text: meta + " · ayrıntılar için token gerekli" })));
      box.replaceChildren(...parts);
      return;
    }

    const counts = b.summary.counts || {};
    parts.push(section("İş kuyruğu",
      el("div", { class: "card" },
        el("div", { class: "meta", text: meta }),
        el("div", { class: "stats" },
          b.summary.paused ? chip("DURAKLATILDI", "bad") : chip("çalışıyor"),
          Object.keys(counts).map((s) => chip(s + " " + counts[s], s === "FAILED" && counts[s] ? "bad" : "")))),
      b.jobs.length
        ? dataTable(["#", "Tür", "Başlık", "Durum", "Öncelik", "Deneme", "Üstlenen", "Güncelleme", "Hata"],
          b.jobs.map((j) => [String(j.id), j.kind, clip(j.title, 60), jobStatusChip(j.status),
            String(j.priority), j.attempts + "/" + j.max_attempts, j.claimed_by || "-",
            fmtTime(j.updated_at), clip(j.error, 80) || "-"]))
        : emptyNote("Kuyrukta iş yok.")));

    parts.push(section("Ajan kaydı",
      b.agents.length
        ? dataTable(["Ad", "Rol", "Durum", "Çevrimiçi", "Yetenekler", "İş", "Son görülme"],
          b.agents.map((a) => [a.name, a.role, agentStatusChip(a.status), a.online ? "evet" : "hayır",
            (a.capabilities || []).join(", ") || "-", a.current_job == null ? "-" : String(a.current_job),
            ago(a.last_seen)]))
        : emptyNote("Kayıtlı ajan yok.")));

    parts.push(section("Projeler",
      b.projects.length
        ? dataTable(["#", "Ad", "Durum", "Açıklama"],
          b.projects.map((p) => [String(p.id), p.name, p.status, clip(p.description, 80) || "-"]))
        : emptyNote("Henüz proje yok.")));

    const usage = b.usage || {};
    const usd = (v) => "$" + Number(v || 0).toFixed(4);
    parts.push(section("AI sağlayıcıları",
      el("div", { class: "card" },
        el("div", { class: "stats" },
          chip("Gün " + (usage.day || "-")),
          chip("Harcanan " + usd(usage.spent_usd) + " / bütçe " + usd(usage.budget_usd),
            Number(usage.spent_usd) >= Number(usage.budget_usd) && Number(usage.budget_usd) > 0 ? "bad" : ""))),
      b.providers.length
        ? dataTable(["Ad", "Tür", "Model", "1K giriş", "1K çıkış"],
          b.providers.map((p) => [p.name, p.kind, p.model || "-", usd(p.price_in_per_1k), usd(p.price_out_per_1k)]))
        : emptyNote("Etkin sağlayıcı yok (WACC_ENABLE_MOCK, WACC_LOCAL_LLM_URL…)."),
      (usage.providers || []).length
        ? dataTable(["Sağlayıcı", "Çağrı", "Başarılı", "Giriş token", "Çıkış token", "Maliyet"],
          usage.providers.map((u) => [u.provider, String(u.calls || 0), String(u.ok_calls || 0),
            String(u.tin || 0), String(u.tout || 0), usd(u.cost)]))
        : null));

    box.replaceChildren(...parts);
  });
}

// A token change bumps backendGen; a poll that was already in flight with the old token
// then drops its result instead of showing stale data, and a refresh asked for while one is
// running is repeated afterwards instead of being lost.
async function refreshBackend() {
  if (state.backendBusy) { state.backendAgain = true; return; }
  state.backendBusy = true;
  const gen = state.backendGen;
  try {
    let health;
    try {
      health = await backendGet("/health");
    } catch (e) {
      if (gen !== state.backendGen) return;
      state.data.backend = null;
      setBackendConn("bad", e.code === "BACKEND_UNREACHABLE" ? "Backend'e ulaşılamıyor" : e.message);
      renderBackend();
      return;
    }
    if (gen !== state.backendGen) return;
    if (!state.backendToken) {
      state.data.backend = { health, locked: true };
      setBackendConn("warn", "Token gerekli");
      renderBackend();
      return;
    }
    try {
      const [summary, agents, jobs, projects, providers, usage] = await Promise.all([
        backendGet("/jobs/summary"), backendGet("/agents"), backendGet("/jobs?limit=50"),
        backendGet("/projects"), backendGet("/ai/providers"), backendGet("/ai/usage"),
      ]);
      if (gen !== state.backendGen) return;
      state.data.backend = { health, summary, agents, jobs, projects, providers, usage };
      setBackendConn("ok", "Bağlı");
    } catch (e) {
      if (gen !== state.backendGen) return;
      state.data.backend = { health, locked: true };
      setBackendConn(e.status === 401 ? "warn" : "bad", e.status === 401 ? "Token geçersiz" : e.message);
    }
    renderBackend();
  } finally {
    state.backendBusy = false;
    if (state.backendAgain || gen !== state.backendGen) {
      state.backendAgain = false;
      refreshBackend();
    }
  }
}

function backendTokenChanged() {
  state.backendGen += 1;
  state.signatures.backend = null;
  // the Backend token is also what the Onaylar tab uses to list requests before an approval
  // token is entered
  state.approvalGen += 1;
  state.signatures.approvals = null;
  refreshApprovals();
  state.aiGen += 1;
  state.signatures.ai = null;
  if (state.tab === "ai") refreshAi();
}

/* ------------------------------------------------------------------ approvals */

// Approving needs the user's own token (shown in the Backend window). It is kept ONLY in this
// variable: never in localStorage/sessionStorage, cleared from the input after it is taken,
// dropped after 5 idle minutes and on "Unut". Until it is entered the tab is read-only and
// uses the Backend token, if any, just to list requests.
const APPROVAL_IDLE_MS = 5 * 60 * 1000;
const RISKY_CLASSES = ["DELETE", "SYSTEM_CHANGE", "PUBLISH", "PERSONAL_FILES", "FINANCIAL", "SECRET_EXPORT"];

function approvalCall(token, path, options) {
  return request("/backend", token, path, options || {});
}

function viewToken() {
  return state.approvalToken || state.backendToken;
}

function setApprovalToken(token) {
  clearTimeout(state.approvalTimer);
  state.approvalToken = token;
  state.approvalGen += 1;
  state.signatures.approvals = null;
  if (token) {
    state.approvalTimer = setTimeout(() => {
      setApprovalToken("");
      toast("Onay token'ı hareketsizlikten dolayı silindi");
      refreshApprovals();
    }, APPROVAL_IDLE_MS);
  }
  renderApprovalToken();
  state.aiGen += 1;
  state.signatures.ai = null;
  if (state.tab === "ai") refreshAi();
}

function touchApprovalToken() {
  if (state.approvalToken) setApprovalToken(state.approvalToken);
}

function renderApprovalToken() {
  const holding = Boolean(state.approvalToken);
  $("approvalTokenState").textContent = holding
    ? "Onay token'ı bellekte (5 dk hareketsizlikte silinir)"
    : "Onay token'ı yok: yalnızca görüntüleme";
  $("approvalTokenState").className = "badge " + (holding ? "ok" : "warn");
  $("forgetApprovalToken").disabled = !holding;
  // the Yapay Zeka tab shows the same in-memory token
  $("aiTokenState").textContent = $("approvalTokenState").textContent;
  $("aiTokenState").className = $("approvalTokenState").className;
  $("forgetAiToken").disabled = !holding;
  $("aiAddBtn").disabled = !holding;
}

function setApprovalConn(tone, text) {
  const badge = $("approvalConn");
  badge.className = "badge " + tone;
  badge.textContent = text;
}

function updatePendingBadge() {
  const n = state.pendingCount;
  const tabButton = $("approvalsTab");
  tabButton.textContent = n ? "Onaylar (" + n + ")" : "Onaylar";
  tabButton.classList.toggle("alert", n > 0);
  document.title = (n ? "(" + n + ") " : "") + "WACC Panel";
}

function actionSummary(action) {
  let text;
  try { text = JSON.stringify(action); } catch (e) { text = String(action); }
  return clip(text, 300);
}

function remaining(ts) {
  const d = parseTime(ts);
  if (!d) return "-";
  const s = Math.round((d.getTime() - Date.now()) / 1000);
  if (s <= 0) return "süresi doldu";
  return Math.floor(s / 60) + " dk " + String(s % 60).padStart(2, "0") + " sn kaldı";
}

async function decide(item, verb) {
  if (!state.approvalToken) { toast("Önce onay token'ını gir", true); return; }
  if (verb === "approve") {
    const ok = window.confirm("Bu eylemi ONAYLIYOR musun?\n\nSınıf: " + item.action_class +
      "\nİsteyen: " + item.requested_by + "\n\n" + actionSummary(item.action));
    if (!ok) return;
  }
  try {
    await approvalCall(state.approvalToken, "/exec/approvals/" + enc(String(item.id)) + "/" + verb,
      { method: "POST" });
    touchApprovalToken();
    toast("#" + item.id + (verb === "approve" ? " onaylandı" : " reddedildi"));
  } catch (e) {
    toast(e.message || "İşlem başarısız", true);
  }
  refreshApprovals();
}

async function execControl(verb) {
  const token = verb === "resume" ? state.approvalToken : viewToken();
  if (!token) { toast(verb === "resume" ? "Devam ettirmek için onay token'ı gerekir" : "Token gerekli", true); return; }
  if (verb === "stop" && !window.confirm("Yürütme backend'i (ve Hub'ın paylaşılan durdurma bayrağı) durdurulsun mu?")) return;
  try {
    await approvalCall(token, "/exec/" + verb, {
      method: "POST", body: verb === "stop" ? { reason: "web panel: manual stop" } : undefined,
    });
    if (verb === "resume") touchApprovalToken();
    toast(verb === "stop" ? "Yürütme durduruldu" : "Yürütme devam ettirildi");
  } catch (e) {
    toast(e.message || "İşlem başarısız", true);
  }
  refreshApprovals();
}

function pendingCard(item) {
  const risky = RISKY_CLASSES.includes(item.action_class);
  let raw;
  try { raw = JSON.stringify(item.action, null, 2); } catch (e) { raw = String(item.action); }
  const canDecide = Boolean(state.approvalToken);
  return el("article", { class: "card pending" },
    el("div", { class: "head" },
      el("strong", { text: "#" + item.id }),
      chip(item.action_class, risky ? "bad" : "warn"),
      el("span", { text: "isteyen: " + item.requested_by }),
      el("span", { class: "meta", text: remaining(item.expires_at) })),
    el("div", { class: "meta", text: "Ham eylem (backend'in doğruladığı biçim; neyin çalışacağı budur):" }),
    el("pre", { class: "raw", text: clip(raw, 4000) }),
    el("div", { class: "meta", text: "Eylem özeti SHA-256: " + String(item.action_hash || "").slice(0, 16) + "… (onay yalnızca bu eyleme bağlıdır)" }),
    el("div", { class: "meta", text: "Backend risk özeti: " + clip(item.risk_summary, 300) }),
    el("div", { class: "meta", text: "Ajanın kendi açıklaması güvenilir değildir; karar için yalnızca yukarıdaki ham eyleme bak." }),
    el("div", { class: "actions" },
      el("button", {
        type: "button", text: "Onayla", disabled: !canDecide,
        title: canDecide ? "" : "Önce onay token'ını gir",
        onclick: () => decide(item, "approve"),
      }),
      el("button", {
        type: "button", class: "ghost", text: "Reddet", disabled: !canDecide,
        title: canDecide ? "" : "Önce onay token'ını gir",
        onclick: () => decide(item, "deny"),
      })));
}

function renderApprovals() {
  const box = $("approvals");
  const a = state.data.approvals;
  renderRegion("approvals", box, [a, Boolean(state.approvalToken), Math.floor(Date.now() / 15000)], () => {
    if (!a) { box.replaceChildren(); return; }
    const parts = [];
    parts.push(section("Yürütme",
      el("div", { class: "card" },
        el("div", { class: "stats" },
          a.status.emergency_stop ? chip("DURDURULDU", "bad") : chip("açık"),
          chip("izinli kök: " + (a.status.roots || []).join(", "))),
        el("div", { class: "actions" },
          a.status.emergency_stop ? null : el("button", {
            type: "button", class: "danger", text: "Yürütmeyi durdur", onclick: () => execControl("stop"),
          }),
          a.status.emergency_stop ? el("button", {
            type: "button", text: "Devam ettir", disabled: !state.approvalToken,
            title: state.approvalToken ? "" : "Yalnızca kullanıcı tokenı devam ettirebilir",
            onclick: () => execControl("resume"),
          }) : null))));
    parts.push(section("Bekleyen onaylar (" + a.pending.length + ")",
      a.pending.length ? a.pending.map(pendingCard) : emptyNote("Bekleyen onay yok.")));
    const done = a.history.filter((i) => i.status !== "PENDING");
    parts.push(section("Son kararlar",
      done.length
        ? dataTable(["#", "İsteyen", "Sınıf", "Durum", "Karar veren", "Zaman", "Eylem"],
          done.slice(0, 20).map((i) => [String(i.id), i.requested_by, i.action_class, chip(i.status,
            i.status === "DENIED" ? "bad" : (i.status === "EXECUTED" ? "" : "warn")),
            i.decided_by || "-", fmtTime(i.decided_at || i.created_at), actionSummary(i.action)]))
        : emptyNote("Henüz karar yok.")));
    parts.push(section("Denetim kaydı",
      a.audit.length
        ? dataTable(["Zaman", "Ajan", "Sınıf", "Sonuç", "Özet", "ms"],
          a.audit.slice(0, 30).map((r) => [fmtTime(r.ts), r.agent, r.action_class, r.outcome,
            clip(r.summary, 100), String(r.duration_ms || 0)]))
        : emptyNote("Denetim kaydı boş.")));
    box.replaceChildren(...parts);
  });
}

// Light poll of the pending count always (when some token exists); the full view only while
// the Onaylar tab is open. Same stale-result guard as refreshBackend.
async function refreshApprovals() {
  if (state.approvalBusy) { state.approvalAgain = true; return; }
  state.approvalBusy = true;
  const gen = state.approvalGen;
  try {
    const token = viewToken();
    if (!token) {
      state.data.approvals = null;
      state.pendingCount = 0;
      updatePendingBadge();
      setApprovalConn("warn", "Token gerekli");
      renderApprovals();
      return;
    }
    const full = state.tab === "approvals";
    try {
      const pending = await approvalCall(token, "/exec/approvals?status=PENDING&limit=50");
      if (gen !== state.approvalGen) return;
      state.pendingCount = pending.length;
      updatePendingBadge();
      if (full) {
        const [status, history, audit] = await Promise.all([
          approvalCall(token, "/exec/status"),
          approvalCall(token, "/exec/approvals?limit=30"),
          approvalCall(token, "/exec/audit?limit=50"),
        ]);
        if (gen !== state.approvalGen) return;
        state.data.approvals = { status, pending, history, audit };
      }
      setApprovalConn("ok", "Bağlı");
    } catch (e) {
      if (gen !== state.approvalGen) return;
      state.data.approvals = null;
      state.pendingCount = 0;
      updatePendingBadge();
      setApprovalConn(e.status === 401 ? "warn" : "bad",
        e.status === 401 ? "Token geçersiz" : (e.code === "BACKEND_UNREACHABLE" ? "Backend'e ulaşılamıyor" : e.message));
    }
    renderApprovals();
  } finally {
    state.approvalBusy = false;
    if (state.approvalAgain || gen !== state.approvalGen) {
      state.approvalAgain = false;
      refreshApprovals();
    }
  }
}

/* ----------------------------------------------------------------- AI accounts */

// Providers are listed with whatever token is available; every change (add, remove, switch,
// test) needs the user's token, which is the same memory-only token as for approvals. The API
// key of a new account is read from the form, the field is emptied BEFORE the request is sent,
// and it is never kept, shown or stored; the Backend never returns it either.
const AI_NAME_RE = /^[a-z0-9][a-z0-9_-]{1,30}$/;

function setAiConn(tone, text) {
  const badge = $("aiConn");
  badge.className = "badge " + tone;
  badge.textContent = text;
}

function usdText(value) {
  return "$" + Number(value || 0).toFixed(4);
}

function aiTestCell(name) {
  const t = state.aiTests[name];
  if (!t) return "-";
  if (t.pending) return chip("test ediliyor…", "warn");
  return t.ok
    ? chip("OK · " + t.latency + " ms" + (t.reply ? " · yanıt: " + t.reply : ""))
    : chip("hata: " + clip(t.error, 120) + (t.latency ? " · " + t.latency + " ms" : ""), "bad");
}

function aiHeaderChips(usage) {
  const spent = Number(usage.spent_usd || 0);
  const budget = Number(usage.budget_usd || 0);
  return el("div", { class: "card" },
    el("div", { class: "stats" },
      chip("Gün " + (usage.day || "-")),
      chip("Harcanan " + usdText(spent) + " / bütçe " + usdText(budget), budget > 0 && spent >= budget ? "bad" : "")),
    el("div", { class: "meta", text: "Bütçeyi bu panel değiştirmez; yalnızca görüntülenir." }));
}

function providerActions(p) {
  const canChange = Boolean(state.approvalToken);
  const hint = canChange ? "" : "Önce kullanıcı tokenını gir";
  const buttons = [
    el("button", {
      type: "button", class: "small", text: p.enabled ? "Kapat" : "Aç", disabled: !canChange, title: hint,
      onclick: () => aiToggle(p),
    }),
    el("button", {
      type: "button", class: "small ghost", text: "Test", disabled: !canChange, title: hint,
      onclick: () => aiTest(p),
    }),
  ];
  // providers that come from the environment (data/llm.env) can only be switched, not removed
  if (p.source === "account") {
    buttons.push(el("button", {
      type: "button", class: "small danger", text: "Sil", disabled: !canChange, title: hint,
      onclick: () => aiRemove(p),
    }));
  }
  return el("div", { class: "actions" }, buttons);
}

function renderAi() {
  const box = $("ai");
  const a = state.data.ai;
  renderRegion("ai", box, [a, Boolean(state.approvalToken), state.aiTests], () => {
    if (!a) { box.replaceChildren(); return; }
    const parts = [section("Kullanım", aiHeaderChips(a.usage || {}))];
    parts.push(section("Sağlayıcılar (" + a.providers.length + ")",
      a.providers.length
        ? dataTable(["Ad", "Tür", "Model", "Kaynak", "Durum", "1K giriş", "1K çıkış", "Son test", "İşlemler"],
          a.providers.map((p) => [p.name, p.kind, p.model || "-",
            p.source === "account" ? "hesap" : "ortam (llm.env)",
            p.enabled ? chip("açık") : chip("kapalı", "warn"),
            usdText(p.price_in_per_1k), usdText(p.price_out_per_1k), aiTestCell(p.name), providerActions(p)]))
        : emptyNote("Etkin sağlayıcı yok. Aşağıdan hesap ekle ya da data/llm.env ile yerel model ayarla.")));
    box.replaceChildren(...parts);
  });
}

async function refreshAi() {
  if (state.aiBusy) { state.aiAgain = true; return; }
  state.aiBusy = true;
  const gen = state.aiGen;
  try {
    const token = viewToken();
    if (!token) {
      state.data.ai = null;
      setAiConn("warn", "Token gerekli");
      renderAi();
      return;
    }
    try {
      const [providers, usage] = await Promise.all([
        approvalCall(token, "/ai/providers"), approvalCall(token, "/ai/usage"),
      ]);
      if (gen !== state.aiGen) return;
      state.data.ai = { providers, usage };
      setAiConn("ok", "Bağlı");
    } catch (e) {
      if (gen !== state.aiGen) return;
      state.data.ai = null;
      setAiConn(e.status === 401 ? "warn" : "bad",
        e.status === 401 ? "Token geçersiz" : (e.code === "BACKEND_UNREACHABLE" ? "Backend'e ulaşılamıyor" : e.message));
    }
    renderAi();
  } finally {
    state.aiBusy = false;
    if (state.aiAgain || gen !== state.aiGen) {
      state.aiAgain = false;
      refreshAi();
    }
  }
}

async function aiChange(path, options, okText) {
  if (!state.approvalToken) { toast("Önce kullanıcı tokenını gir", true); return false; }
  try {
    await approvalCall(state.approvalToken, path, options);
    touchApprovalToken();
    toast(okText);
    return true;
  } catch (e) {
    toast(e.message || "İşlem başarısız", true);
    return false;
  } finally {
    refreshAi();
  }
}

function aiToggle(p) {
  return aiChange("/ai/providers/" + enc(p.name) + "/enabled",
    { method: "POST", body: { enabled: !p.enabled } }, p.name + (p.enabled ? " kapatıldı" : " açıldı"));
}

function aiRemove(p) {
  if (!window.confirm("'" + p.name + "' hesabı silinsin mi? Kayıtlı API anahtarı da silinir.")) return Promise.resolve(false);
  delete state.aiTests[p.name];
  return aiChange("/ai/accounts/" + enc(p.name), { method: "DELETE" }, p.name + " silindi");
}

async function aiTest(p) {
  if (!state.approvalToken) { toast("Önce kullanıcı tokenını gir", true); return; }
  if (p.kind === "cloud" && !window.confirm("'" + p.name +
    "' bulut sağlayıcıya küçük bir gerçek istek gönderilecek (günlük bütçeye sayılır). Devam?")) return;
  state.aiTests[p.name] = { pending: true };
  renderAi();
  try {
    const r = await approvalCall(state.approvalToken, "/ai/providers/" + enc(p.name) + "/test", { method: "POST" });
    touchApprovalToken();
    state.aiTests[p.name] = r.ok
      ? { ok: true, latency: r.latency_ms, reply: clip(r.reply, 40) }
      : { ok: false, latency: r.latency_ms, error: r.error || "bilinmeyen hata" };
  } catch (e) {
    state.aiTests[p.name] = { ok: false, error: e.message || "test başarısız" };
  }
  state.signatures.ai = null;
  renderAi();
  refreshAi();
}

async function aiAdd(ev) {
  ev.preventDefault();
  if (!state.approvalToken) { toast("Önce kullanıcı tokenını gir", true); return; }
  const name = $("aiName").value.trim().toLowerCase();
  const kind = $("aiKind").value;
  const apiKey = $("aiKey").value;
  if (!AI_NAME_RE.test(name)) { toast("Ad 2-31 karakter olmalı: a-z, 0-9, - veya _", true); return; }
  if (kind === "cloud" && !apiKey) { toast("Bulut hesabı için API anahtarı gerekli", true); return; }
  const body = {
    name, kind, base_url: $("aiUrl").value.trim(), model: $("aiModel").value.trim(),
    enabled: $("aiEnabled").checked,
  };
  if (apiKey) body.api_key = apiKey;
  for (const [field, id] of [["price_in_per_1k", "aiPriceIn"], ["price_out_per_1k", "aiPriceOut"]]) {
    const raw = $(id).value.trim();
    if (raw !== "") body[field] = Number(raw);
  }
  $("aiKey").value = ""; // the secret leaves the form before anything is sent, success or not
  const button = $("aiAddBtn");
  button.disabled = true; // no double submit
  const ok = await aiChange("/ai/accounts", { method: "POST", body }, name + " eklendi");
  button.disabled = !state.approvalToken;
  if (ok) {
    $("aiAddForm").reset();
    $("aiEnabled").checked = true;
  }
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
  if (name === "backend") refreshBackend();
  if (name === "approvals") refreshApprovals();
  if (name === "ai") refreshAi();
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

  const saved = loadToken(TOKEN_KEY);
  const savedBackend = loadToken(BACKEND_TOKEN_KEY);
  state.token = saved.token;
  state.backendToken = savedBackend.token;
  $("token").value = saved.token;
  $("backendToken").value = savedBackend.token;
  // off unless the user chose to keep a token
  $("remember").checked = saved.token ? saved.remember : savedBackend.remember;

  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));

  $("tokenForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    state.token = $("token").value.trim();
    saveToken(TOKEN_KEY, state.token, $("remember").checked);
    state.signatures = {};
    refresh();
  });
  // Changing the checkbox moves already-saved tokens between the two stores right away.
  $("remember").addEventListener("change", () => {
    const remember = $("remember").checked;
    if (state.token) saveToken(TOKEN_KEY, state.token, remember);
    if (state.backendToken) saveToken(BACKEND_TOKEN_KEY, state.backendToken, remember);
  });
  $("backendTokenForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    state.backendToken = $("backendToken").value.trim();
    saveToken(BACKEND_TOKEN_KEY, state.backendToken, $("remember").checked);
    backendTokenChanged();
    refreshBackend();
  });
  $("forgetBackendToken").addEventListener("click", () => {
    state.backendToken = "";
    $("backendToken").value = "";
    saveToken(BACKEND_TOKEN_KEY, "", false);
    backendTokenChanged();
    refreshBackend();
  });
  $("approvalTokenForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const value = $("approvalToken").value.trim();
    $("approvalToken").value = ""; // do not leave the secret sitting in the DOM
    setApprovalToken(value);
    refreshApprovals();
  });
  $("forgetApprovalToken").addEventListener("click", () => {
    $("approvalToken").value = "";
    setApprovalToken("");
    refreshApprovals();
  });
  // The Yapay Zeka tab has its own input for the same in-memory user token.
  $("aiTokenForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const value = $("aiToken").value.trim();
    $("aiToken").value = ""; // do not leave the secret sitting in the DOM
    setApprovalToken(value);
    refreshApprovals();
  });
  $("forgetAiToken").addEventListener("click", () => {
    $("aiToken").value = "";
    setApprovalToken("");
    refreshApprovals();
  });
  $("aiAddForm").addEventListener("submit", aiAdd);
  // Top-right "Unut" clears every token held by this panel.
  $("forgetToken").addEventListener("click", () => {
    state.token = "";
    state.backendToken = "";
    $("approvalToken").value = "";
    $("aiToken").value = "";
    $("aiKey").value = "";
    state.aiTests = {};
    setApprovalToken("");
    state.me = null;
    state.signatures = {};
    $("token").value = "";
    $("backendToken").value = "";
    $("remember").checked = false;
    saveToken(TOKEN_KEY, "", false);
    saveToken(BACKEND_TOKEN_KEY, "", false);
    state.data.backend = null;
    backendTokenChanged();
    refresh();
    if (state.tab === "backend") refreshBackend();
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

  renderApprovalToken();
  setTab("agents");
  refresh();
  refreshApprovals();
  setInterval(() => {
    if (document.hidden) return;
    refresh();
    if (state.tab === "backend") refreshBackend(); // backend data is only polled while it is visible
    refreshApprovals(); // cheap pending count always; the full view only on the Onaylar tab
    if (state.tab === "ai") refreshAi();
  }, REFRESH_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
}

init();
