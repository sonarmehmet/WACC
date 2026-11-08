// Pulls pickModel() out of app.js and checks it against realistic model lists. Prints a JSON list of failures.
const src = require("fs").readFileSync(__dirname + "/../public/app.js", "utf8");
const code = src.slice(src.indexOf("const NOT_CHAT"), src.indexOf("async function easyAdd"));
const pickModel = new Function(code + "; return pickModel;")();
const cases = [
  ["grok", ["grok-3", "grok-3-mini", "grok-4", "grok-4.7", "grok-imagine-image"], "grok-4-old", "grok-4.7"],
  ["grok", ["grok-3", "grok-4"], "grok-3", "grok-3"],              // the current one is listed: keep it
  ["grok", ["grok-3-mini", "grok-imagine-image"], "x", "grok-3-mini"],
  ["openai", ["text-embedding-3-small", "gpt-4o", "gpt-4o-mini"], "gpt-9", "gpt-4o-mini"],
  ["claude", ["claude-haiku-5-5", "claude-sonnet-5-5"], "claude-old", "claude-sonnet-5-5"],
  ["custom", ["a-embed", "b-chat"], "z", "b-chat"],
  ["groq", ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "whisper-large-v3"], "x", "openai/gpt-oss-120b"],
  ["gemini", ["gemini-3.8-flash-lite", "gemini-3.8-flash", "gemini-3.8-pro", "gemini-embedding-001"], "x", "gemini-3.8-flash"],
  ["orfree", ["openai/gpt-4o", "google/gemma-4-31b-it:free", "nvidia/nemotron-3:free"], "x", "google/gemma-4-31b-it:free"],
  ["grok", [], "grok-4.7", "grok-4.7"],                           // no list: keep what was typed
];
const failures = [];
for (const [provider, ids, current, want] of cases) {
  const got = pickModel(provider, ids, current);
  if (got !== want) failures.push({ provider, ids, current, want, got });
}
console.log(JSON.stringify(failures));
