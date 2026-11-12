// Item 22: the Arena rules step says what the sim does with a dropped item, in the Gear drops line itself.
//   node near/web/snapin/test_gear_line.cjs
// The sim (near/arena/sim.py): a KO drops one worn non-starter item; anyone may grab it, except that the house never
// grabs a player's item (_can_grab); a drop nobody grabs is deleted after floor_ticks (a floor_loss, no return to the
// owner and no hand-over to the KO-er; prd v3.1 :508, Pat's :336).
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const ROOT = path.resolve(__dirname, '../../..');
const app = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');
let n = 0;
const m = app.match(/>(Gear drops:[^<]*)<\/label>/);
assert.ok(m, 'the Gear drops line is a checkbox label'); n++;
const secs = Number(execFileSync('python3', ['-I', '-c', 'import sys; sys.path.insert(0, sys.argv[1]); from near.arena import sim; r = sim.DEFAULT_RULES; print(r["floor_ticks"] // r["tick_hz"])', ROOT]).toString());
assert.strictEqual(m[1], 'Gear drops: a KO can knock one worn item loose; whoever grabs it keeps it (the house never takes yours); ungrabbed for ' + secs + ' s, it is gone'); n++;
assert.ok(!/Unclaimed drops disappear/.test(app), 'no separate sentence under the ticks'); n++;
console.log(n + ' PASS, 0 FAIL');
