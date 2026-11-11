// The creator's emoji-set rules agree with near/lore/emoji.py on the same inputs.
//   node near/web/snapin/test_emoji_set.cjs
const assert = require('assert');
const path = require('path');
const fs = require('fs');
const { execFileSync } = require('child_process');
const E = require('./emoji-set.js');
const ROOT = path.resolve(__dirname, '../../..');
const lore = JSON.parse(fs.readFileSync(path.join(ROOT, 'near/lore/emoji_defaults.json'), 'utf8')).sets;
let n = 0;
for (const [name, set] of Object.entries(lore)) {
  assert.deepStrictEqual(E.DEFAULTS[name.toLowerCase()], set, name + ' default matches the lore file'); n++;
  assert.strictEqual(E.checkSet(set), null, name); n++;
  const s = E.suggest(name.toLowerCase());
  assert.ok(s.length >= 8 && E.checkSet(s.slice(0, 8)) === null, name + ' suggestions are pickable'); n++;
}
const sample = ['😀', 'a', '😀a', '😵‍💫', '☀️', '👍🏽', '🫠', '😀😀😀😀😀', '', '#️⃣', '❤', '©', '©️', '™', '😀\u200d', '\u200d😀', '🧑‍💻', '🏳️‍🌈'];
const py = JSON.parse(execFileSync('python3', ['-I', '-c',
  'import json,sys; sys.path.insert(0, sys.argv[1]); from near.lore import emoji; ' +
  'print(json.dumps([emoji.check_glyph(g) is None for g in json.loads(sys.argv[2])]))', ROOT, JSON.stringify(sample)]).toString());
sample.forEach((g, i) => { assert.strictEqual(E.checkGlyph(g) === null, py[i], 'agree on ' + JSON.stringify(g)); n++; });
assert.notStrictEqual(E.checkSet(['😀', '😀', '😃', '😄', '😁']), null); n++;
assert.notStrictEqual(E.checkSet(['😀', '😃']), null); n++;
assert.notStrictEqual(E.checkSet(['☀', '☀️', '🌈', '🎉', '😎']), null); n++;
console.log(n + ' PASS, 0 FAIL');
