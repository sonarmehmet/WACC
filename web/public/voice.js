"use strict";

/* Voice and typed commands for the control room. Speech comes from the browser's own speech
 * recognition (Edge/Chrome); this file never sends audio anywhere itself and never holds a token.
 *
 * Safety rule: what is heard is untrusted (a TV, a video call, someone else in the room). So voice may
 * only navigate, read out the status, FILL IN forms (the person still presses the button) and trigger the
 * emergency stop (which only makes things safer). Approving, denying and resuming are click-only. */

(function () {
  const $ = (id) => document.getElementById(id);
  const logBox = $("voiceLog");
  const synth = window.speechSynthesis;
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null;
  let wantLive = false; // "sürekli dinle"
  let single = false;
  let speaking = false;

  function line(cls, text) {
    const div = document.createElement("div");
    div.className = cls;
    div.textContent = (cls === "me" ? "Sen: " : "WACC: ") + text;
    logBox.appendChild(div);
    while (logBox.children.length > 6) logBox.firstChild.remove();
    logBox.scrollTop = logBox.scrollHeight;
  }

  function say(text, speak) {
    line("bot", text);
    if (speak === false || !synth) return;
    try {
      if (rec) rec.abort(); // do not hear ourselves
      synth.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "tr-TR";
      speaking = true;
      u.onend = u.onerror = () => { speaking = false; if (wantLive) startRec(true); };
      synth.speak(u);
    } catch (e) { speaking = false; }
  }

  function agentNames() { return (state.data.agents || []).map((a) => a.agent_id); }

  function statusText() {
    const agents = state.data.agents || [];
    const online = agents.filter((a) => a.online).length;
    const tasks = state.data.tasks || [];
    const open = tasks.filter((t) => t.status !== "COMPLETED" && t.status !== "CANCELLED").length;
    const parts = [online + " ajan çevrimiçi, toplam " + agents.length, open + " açık görev", (state.pendingCount || 0) + " onay bekliyor"];
    if (state.data.emergency) parts.unshift("acil durdurma açık");
    return parts.join(", ") + ".";
  }

  function run(text, needWake) {
    const cmd = WACCParse.parseCommand(text, { agents: agentNames(), needWake: Boolean(needWake) });
    if (cmd.intent === "ignore") return;
    line("me", text);
    switch (cmd.intent) {
      case "listening": say("Dinliyorum.", false); break;
      case "tab": setTab(cmd.tab); say(cmd.label + " açıldı.", false); break;
      case "status": say(statusText()); break;
      case "settings": window.WACCHud.openSettings(); say("Ayarlar açıldı.", false); break;
      case "stop":
        if (!LEADERS.includes(state.me)) { say("Acil durdurmayı yalnızca claude1 ya da user başlatabilir."); break; }
        act(() => api("/system/stop", { method: "POST", body: { reason: "voice/typed command" } }), "Acil durdurma açıldı")
          .then(() => say("Acil durdurma açıldı."));
        break;
      case "resume":
        say("Devam ettirmek için DEVAM ETTİR düğmesine kendin bas. Sesle kaldırmıyorum: ortam sesi yanlış komut verebilir.");
        break;
      case "approve":
      case "deny":
        setTab("approvals");
        say("Onay ve ret yalnızca tıklayarak verilir. Onaylar sekmesini açtım.");
        break;
      case "task":
        setTab("tasks");
        if (cmd.title) $("taskTitle").value = cmd.title;
        $("taskTitle").focus();
        say(cmd.title ? "Görev formunu doldurdum. Oluştur'a bas." : "Görev formunu açtım, başlığı yaz.");
        break;
      case "message":
        setTab("feed");
        $("msgReceiver").value = cmd.to;
        $("msgSubject").value = cmd.text.slice(0, 60);
        $("msgContent").value = cmd.text;
        say(cmd.to + " için mesajı hazırladım. Gönder'e bas.");
        break;
      case "addai":
        setTab("agents");
        if (cmd.provider) { $("ezProvider").value = cmd.provider; $("ezProvider").dispatchEvent(new Event("change")); }
        $("ezKey").focus();
        say("Sağlayıcıyı seçtim. API anahtarını kutuya yapıştırıp Ekle'ye bas.");
        break;
      case "help":
        say("Şunları söyleyebilirsin: durum; ajanlar, görevler, onaylar, kilitler, yapay zeka; görev ekle ve başlık; claude1'e söyle ve mesaj; grok ekle; acil durdur; ayarlar.");
        break;
      default:
        say("Anlamadım. 'yardım' yaz ya da de.");
    }
  }

  /* ----------------------------------------------------------- microphone */
  function buttons() {
    $("micBtn").classList.toggle("listening", Boolean(rec) && single);
    $("liveBtn").classList.toggle("active", wantLive);
  }

  function startRec(live) {
    if (!Recognition) {
      say("Bu pencerede ses tanıma yok. Alttaki kutuya yazarak komut verebilirsin.", false);
      wantLive = false;
      buttons();
      return;
    }
    if (rec || speaking) return;
    rec = new Recognition();
    rec.lang = "tr-TR";
    rec.interimResults = false;
    rec.continuous = Boolean(live);
    rec.maxAlternatives = 1;
    single = !live;
    rec.onresult = (ev) => {
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        if (!ev.results[i].isFinal) continue;
        const heard = ev.results[i][0].transcript.trim();
        if (heard) run(heard, live); // always-on mode only reacts to a command that starts with "WACC"
      }
    };
    rec.onerror = (ev) => {
      if (ev.error === "not-allowed" || ev.error === "service-not-allowed") {
        say("Mikrofon izni verilmedi. Pencerede mikrofona izin ver, sonra tekrar dene.", false);
        wantLive = false;
      } else if (ev.error === "network") {
        say("Ses tanıma servisine ulaşılamadı (internet gerekir). Yazarak komut verebilirsin.", false);
        wantLive = false;
      }
    };
    rec.onend = () => {
      rec = null;
      buttons();
      if (wantLive && !speaking) setTimeout(() => startRec(true), 400);
    };
    try { rec.start(); } catch (e) { rec = null; }
    buttons();
  }

  $("micBtn").addEventListener("click", () => {
    if (rec) { rec.abort(); return; }
    startRec(false);
  });
  $("liveBtn").addEventListener("click", () => {
    wantLive = !wantLive;
    if (wantLive) { say("Sürekli dinleme açık. Komuttan önce 'WACC' de.", false); startRec(true); }
    else if (rec) rec.abort();
    buttons();
  });
  $("cmdForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const input = $("cmdInput");
    const text = input.value.trim();
    input.value = "";
    if (text) run(text, false);
  });
  if (!Recognition) $("micBtn").title = "Bu pencerede ses tanıma yok: yazarak komut ver";
  say("Hazır. Mikrofona bas ya da yaz: 'yardım'.", false);
})();
