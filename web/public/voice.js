"use strict";

/* Voice and typed commands for the control room. Speech comes from the browser's own speech
 * recognition and synthesis (Edge/Chrome); this file never sends audio anywhere itself and never holds a token.
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

  /* ------------------------------------------------------------- the voice */
  // A warm, natural Turkish woman's voice. Edge ships "Microsoft Emel Online (Natural)" (neural, much better than
  // the old robotic voices); Chrome has "Google Türkçe"; other systems have their own. The pick is automatic and
  // can be changed in Ayarlar. Only a voice NAME and a speed are remembered (nothing secret).
  const PREF_KEY = "wacc.voice";
  const FEMALE_FIRST = [/emel/i, /(natural|neural).*(turk|türk)|(turk|türk).*(natural|neural)/i, /google.*(turk|türk)/i,
                        /yelda|filiz|seda|sevil|zeynep|damla|aylin|tr-tr.*female/i];
  const MALE = /tolga|ahmet|cem|kerem|male/i;
  let voice = null;
  let rate = 1;
  let muted = false;

  function pref() {
    try { return JSON.parse(window.localStorage.getItem(PREF_KEY) || "{}"); } catch (e) { return {}; }
  }
  function savePref(update) {
    try { window.localStorage.setItem(PREF_KEY, JSON.stringify(Object.assign(pref(), update))); } catch (e) { /* ignore */ }
  }
  function turkishVoices() {
    return (synth ? synth.getVoices() : []).filter((v) => /^tr/i.test(v.lang) || /turk|türk/i.test(v.name));
  }
  function pickVoice() {
    const list = turkishVoices();
    const saved = pref();
    rate = typeof saved.rate === "number" ? saved.rate : 1;
    muted = Boolean(saved.muted);
    voice = list.find((v) => v.name === saved.name)
      || FEMALE_FIRST.map((re) => list.find((v) => re.test(v.name))).find(Boolean)
      || list.find((v) => !MALE.test(v.name))
      || list[0] || null;
    fillVoiceControls(list);
  }
  function fillVoiceControls(list) {
    const select = $("voiceSelect");
    if (!select) return;
    select.replaceChildren(...(list.length ? list : [{ name: "(Türkçe ses bulunamadı)" }]).map((v) => {
      const o = document.createElement("option");
      o.value = v.name;
      o.textContent = v.name;
      return o;
    }));
    if (voice) select.value = voice.name;
    $("voiceRate").value = String(rate);
    $("voiceMute").checked = muted;
  }

  // Speak like a person: no markdown noise, sentence by sentence (long single utterances get cut off in Chromium).
  function cleanForSpeech(text) {
    return String(text)
      .replace(/```[\s\S]*?```/g, " ")
      .replace(/https?:\/\/\S+/g, " bağlantı ")
      .replace(/[*_#`>~|]+/g, " ")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, " ")
      .replace(/\s+/g, " ")
      .trim();
  }
  function sentences(text) {
    const out = [];
    for (const part of (text.match(/[^.!?…]+[.!?…]*/g) || [text])) {
      let chunk = part.trim();
      while (chunk.length > 180) {
        const cut = chunk.lastIndexOf(",", 180) > 60 ? chunk.lastIndexOf(",", 180) + 1 : chunk.lastIndexOf(" ", 180);
        out.push(chunk.slice(0, cut > 0 ? cut : 180).trim());
        chunk = chunk.slice(cut > 0 ? cut : 180).trim();
      }
      if (chunk) out.push(chunk);
    }
    return out;
  }

  function speak(text, done) {
    if (!synth || muted) { if (done) done(); return; }
    try {
      if (rec) rec.abort(); // do not hear ourselves
      synth.cancel();
      const parts = sentences(cleanForSpeech(text).slice(0, 700));
      if (!parts.length) { if (done) done(); return; }
      speaking = true;
      parts.forEach((part, i) => {
        const u = new SpeechSynthesisUtterance(part);
        u.lang = "tr-TR";
        if (voice) u.voice = voice;
        u.rate = rate;
        u.pitch = 1.04;
        u.volume = 1;
        if (i === parts.length - 1) {
          u.onend = u.onerror = () => { speaking = false; if (done) done(); if (wantLive) startRec(true); };
        }
        synth.speak(u);
      });
    } catch (e) { speaking = false; if (done) done(); }
  }

  function say(text, voiced) {
    line("bot", text);
    if (voiced === false) return;
    speak(text);
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
        say("Sıradan bir cümle yazarsan yapay zekâ hesabın cevap verir. Komutlar: durum; ajanlar, görevler, onaylar, kilitler, yapay zeka; görev ekle ve başlık; claude1'e söyle ve mesaj; grok ekle; acil durdur; ayarlar.");
        break;
      default:
        chat(cmd.text || text);
    }
  }

  // Anything that is not a fixed command is a conversation with the person's own AI account.
  let chatBusy = false;
  async function chat(text) {
    if (chatBusy) { say("Bir önceki cevabı bekliyorum.", false); return; }
    chatBusy = true;
    line("bot", "düşünüyorum…");
    try {
      const r = await askAI(text);
      logBox.lastChild.remove(); // the "thinking" line
      say(r.text || "Boş cevap geldi.");
    } catch (e) {
      logBox.lastChild.remove();
      if (e.code === "NO_PROVIDER") {
        setTab("agents");
        say("Henüz bir yapay zekâ hesabın yok, o yüzden sohbet edemiyorum. Ajanlar sekmesinde sağlayıcıyı seç, API anahtarını yapıştır, Ekle'ye bas.");
      } else if (e.code === "ALL_FAILED") {
        say("Yapay zekâ hesabı cevap vermedi: " + (e.message || "") + " Ajanlar sekmesindeki hesabın anahtarını ve model adını kontrol et.");
      } else if (e.code === "BUDGET_EXCEEDED") {
        say("Günlük yapay zekâ bütçesi doldu.");
      } else {
        say("Cevap alamadım: " + (e.message || "bağlantı hatası") + ". Ayarlar > Tanı raporu'na bak.");
      }
    } finally { chatBusy = false; }
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
  if (synth) {
    pickVoice();
    synth.addEventListener("voiceschanged", pickVoice); // voices load asynchronously
  }
  $("voiceSelect").addEventListener("change", () => {
    voice = turkishVoices().find((v) => v.name === $("voiceSelect").value) || voice;
    savePref({ name: voice && voice.name });
  });
  $("voiceRate").addEventListener("input", () => { rate = Number($("voiceRate").value) || 1; savePref({ rate }); });
  $("voiceMute").addEventListener("change", () => {
    muted = $("voiceMute").checked;
    savePref({ muted });
    if (muted && synth) synth.cancel();
  });
  $("voiceTest").addEventListener("click", () => {
    const wasMuted = muted;
    muted = false;
    speak("Merhaba, ben WACC. Seni duyuyorum, nasıl yardımcı olabilirim?", () => { muted = wasMuted; });
  });
  if (!Recognition) $("micBtn").title = "Bu pencerede ses tanıma yok: yazarak komut ver";
  say("Hazır. Mikrofona bas ya da yaz: 'yardım'.", false);
})();
