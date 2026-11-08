"use strict";

/* Turns a spoken or typed Turkish command into an intent. Pure text in, plain object out: no DOM,
 * no network, no tokens, so it can be tested on its own (node) and loaded by the panel (browser).
 * Nothing here acts on anything: voice.js decides what each intent may do. */

(function (root) {
  const MAP = { "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c", "â": "a", "î": "i", "û": "u" };

  // 1:1 fold (same length as the input) so positions found in the folded text point into the original.
  function fold(text) {
    let out = "";
    for (const ch of String(text)) out += MAP[ch] || ch.toLowerCase();
    return out;
  }

  const TABS = [
    [/\b(yapay zeka|yapay zek|ai hesap)/, "ai", "Yapay Zeka"],
    [/\bonay(lar|lari|ları)?\b/, "approvals", "Onaylar"],
    [/\bproje(ler|leri)?\b/, "projects", "Projeler"],
    [/\b(gorev|gorevler|gorevleri)\b/, "tasks", "Görevler"],
    [/\b(akis|mesajlar|mesajlari)\b/, "feed", "Akış"],
    [/\b(kilit|kilitler|kilitleri)\b/, "locks", "Kilitler"],
    [/\bbackend\b/, "backend", "Backend"],
    [/\b(ajan|ajanlar|ajanlari)\b/, "agents", "Ajanlar"],
  ];
  const PROVIDERS = [
    [/\b(grok|xai|x ai)\b/, "grok"], [/\b(chatgpt|openai|gpt)\b/, "openai"], [/\b(claude|anthropic)\b/, "claude"],
    [/\bgroq\b/, "groq"], [/\bgemini\b/, "gemini"], [/\bopenrouter\b/, "openrouter"], [/\b(ollama|yerel)\b/, "ollama"],
  ];
  const WAKE = /^(hey |hi |ok )?(wacc|wack|wak|vak|vaks|vack|jarvis|cervis)\b[ ,:.!-]*/;

  function parseCommand(raw, options) {
    const opts = options || {};
    let original = String(raw || "").trim();
    let text = fold(original).replace(/['\u2019\u02bc`\u00b4]/g, " "); // apostrophes -> space; same length, so positions still match the original
    const wake = WAKE.exec(text);
    if (wake) { text = text.slice(wake[0].length); original = original.slice(wake[0].length); }
    else if (opts.needWake) return { intent: "ignore" };
    text = text.trim();
    original = original.trim();
    if (!text) return { intent: wake ? "listening" : "ignore" };

    if (/\b(acil durdur|acil dur|hepsini durdur|her seyi durdur|sistemi durdur)\b/.test(text)) return { intent: "stop" };
    if (/\b(devam ettir|devam et|durdurmayi kaldir|acil durdurmayi kaldir)\b/.test(text)) return { intent: "resume" };
    if (/\b(onayla|onay ver|kabul et|izin ver)\b/.test(text)) return { intent: "approve" };
    if (/\b(reddet|red et|reddediyorum)\b/.test(text)) return { intent: "deny" };
    if (/\b(yardim|ne yapabilirsin|komutlar|neler yapabilirsin)\b/.test(text)) return { intent: "help" };
    if (/\b(durum|rapor|ozet|ne durumda|nasil gidiyor|ne var ne yok)\b/.test(text)) return { intent: "status" };
    if (/\bayarlar\b/.test(text)) return { intent: "settings" };

    const task = /^(yeni )?gorev (ekle|olustur|ac|yaz)\b[ :,-]*/.exec(text);
    if (task) return { intent: "task", title: original.slice(task[0].length).trim() };

    const names = (opts.agents || []).map(fold);
    if (names.length) {
      // "claude 2" (spoken) must match the agent "claude2"
      const group = names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/([a-z])(\d)/, "$1 ?$2")).join("|");
      const suffix = "(?:\\s+(?:ya|ye|a|e))?";
      const msg = new RegExp("^(?:mesaj gonder|mesaj|yaz|soyle)\\s+(" + group + ")" + suffix + "[ :,-]+(.+)$").exec(text)
        || new RegExp("^(" + group + ")" + suffix + "\\s+(?:soyle|mesaj gonder|mesaj yaz|yaz)[ :,-]+(.+)$").exec(text);
      if (msg) {
        const to = names.find((n) => n.replace(/ /g, "") === msg[1].replace(/ /g, ""));
        return { intent: "message", to, text: original.slice(original.length - msg[2].length).trim() };
      }
    }

    if (/\b(ekle|kur|bagla|ekleyelim)\b/.test(text)) {
      for (const [re, provider] of PROVIDERS) if (re.test(text)) return { intent: "addai", provider };
      if (/\b(yapay zeka|ajan|model|hesap)\b/.test(text)) return { intent: "addai", provider: null };
    }

    for (const [re, tab, label] of TABS) if (re.test(text)) return { intent: "tab", tab, label };
    return { intent: "unknown", text };
  }

  const api = { parseCommand, fold };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.WACCParse = api;
})(typeof window !== "undefined" ? window : globalThis);
