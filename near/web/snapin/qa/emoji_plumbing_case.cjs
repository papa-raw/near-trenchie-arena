// The persona emoji plumbing in sheet.js (battle mode): a set is written to game.emoji only when the emoji rules accept it,
// never without the rules, never an invalid one; the sheet check accepts emoji as the one optional game key and refuses a
// tampered set. Node only, no browser.
// usage: node near/web/snapin/qa/emoji_plumbing_case.cjs [path/to/emoji-set.js]   (default: the sibling emoji-set.js)
'use strict';
const path = require('path');
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const SS = require(path.join(__dirname, '..', 'sheet.js'));
const state = (extra) => Object.assign({ name: 'Pip Shoals', temperament: 'sunny', quirks: [], voice: '', preset: 'brawler-zap', look: { body: 'p07', hairCol: 'p03' }, door: '' }, extra || {});
const base = SS.build(state({ emoji: ['🙂', '🌊', '🐚', '⚡', '🎉'] }));
ok(base && base.game && !('emoji' in base.game) && SS.validate(base).length === 0, 'without the emoji rules loaded, no set is written and the sheet still checks');
let E;
try { E = require(process.argv[2] ? path.resolve(process.argv[2]) : path.join(__dirname, '..', 'emoji-set.js')); } catch (e) { E = null; }
if (!E) { ok(false, 'emoji-set.js not found (pass its path)'); }
else {
  globalThis.SnapEmoji = E;
  const good = E.DEFAULTS.sunny.slice(0, 6);
  const a = SS.build(state({ emoji: good }));
  ok(JSON.stringify(a.game.emoji) === JSON.stringify(good) && SS.validate(a).length === 0, `a valid set is written and checks: ${good.join(' ')}`);
  const short = SS.build(state({ emoji: good.slice(0, 3) }));
  ok(!('emoji' in short.game), `a set the rules refuse (${E.checkSet(good.slice(0, 3))}) is not written; the temperament default applies`);
  const ascii = SS.build(state({ emoji: ['a', 'b', 'c', 'd', 'e'] }));
  ok(!('emoji' in ascii.game), 'ASCII letters are never written as emoji');
  const none = SS.build(state());
  ok(!('emoji' in none.game) && SS.validate(none).length === 0, 'no set chosen: none written, the sheet checks');
  const tampered = JSON.parse(JSON.stringify(a)); tampered.game.emoji = ['x', 'y', 'z', 'w', 'v'];
  const why = SS.validate(tampered);
  ok(why.some((f) => /emoji/.test(String(f))), `a tampered set fails the sheet check: ${why.filter((f) => /emoji/.test(String(f))).join(' | ')}`);
  const extra = JSON.parse(JSON.stringify(none)); extra.game.mood = 'x';
  ok(SS.validate(extra).some((f) => /game keys/.test(String(f))), 'any other extra game key is still refused');
}
console.log(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
