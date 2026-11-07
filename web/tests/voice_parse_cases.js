// Run with node: prints a JSON list of failures (empty = all good).
const { parseCommand } = require("../public/voice-parse.js");
const agents = ["claude1", "claude2", "claude3", "gemini", "grok1"];
const cases = [
  ["durum", {}, { intent: "status" }],
  ["WACC durum nasıl gidiyor", { needWake: true }, { intent: "status" }],
  ["durum", { needWake: true }, { intent: "ignore" }],  // always-on mode ignores speech without the wake word
  ["acil durdur", {}, { intent: "stop" }],
  ["devam ettir", {}, { intent: "resume" }],
  ["onayla", {}, { intent: "approve" }],
  ["reddet", {}, { intent: "deny" }],
  ["görev ekle Kurulum rehberini düzelt", {}, { intent: "task", title: "Kurulum rehberini düzelt" }],
  ["grok ekle", {}, { intent: "addai", provider: "grok" }],
  ["ChatGPT ekle", {}, { intent: "addai", provider: "openai" }],
  ["yapay zeka ekle", {}, { intent: "addai", provider: null }],
  ["onaylar", {}, { intent: "tab", tab: "approvals" }],
  ["görevler", {}, { intent: "tab", tab: "tasks" }],
  ["claude 2 ye söyle testleri çalıştır", { agents }, { intent: "message", to: "claude2", text: "testleri çalıştır" }],
  ["yardım", {}, { intent: "help" }],
  ["bambaşka bir şey", {}, { intent: "unknown" }],
];
const failures = [];
for (const [text, opts, want] of cases) {
  const got = parseCommand(text, Object.assign({ agents: [] }, opts));
  for (const [k, v] of Object.entries(want)) if (got[k] !== v) failures.push({ text, key: k, want: v, got: got[k] });
}
console.log(JSON.stringify(failures));
