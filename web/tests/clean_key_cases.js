// Pulls cleanKey() out of app.js: pasted keys lose whitespace/quotes/"Bearer "; unusable ones come back null.
const src = require("fs").readFileSync(__dirname + "/../public/app.js", "utf8");
const code = src.slice(src.indexOf("function cleanKey"), src.indexOf("// One line per AI account"));
const cleanKey = new Function(code + "; return cleanKey;")();
const cases = [
  ["xai-abc123", "xai-abc123"],
  ["  xai-abc123\n", "xai-abc123"],
  ['"xai-abc123"', "xai-abc123"],
  ["'xai-abc123'", "xai-abc123"],
  ["“xai-abc123”", "xai-abc123"],
  ["Bearer xai-abc123", "xai-abc123"],
  ['"Bearer xai-abc123"', "xai-abc123"],
  ["xai-abc​123", "xai-abc123"],
  ["xai-abc 123", null],
  ["xai-abcş123", null],
  ["", ""],
];
const failures = [];
for (const [input, want] of cases) {
  const got = cleanKey(input);
  if (got !== want) failures.push({ input, want, got });
}
console.log(JSON.stringify(failures));
