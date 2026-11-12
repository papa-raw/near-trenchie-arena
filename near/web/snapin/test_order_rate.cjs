// Item 23: the guide shows the arena's one order rate as the host advertises it, never rounded to a whole second.
//   node near/web/snapin/test_order_rate.cjs
// Before: app.js printed Math.round(500 / 1000) = 1, so "Orders: one every 1 s" while the host takes one per 0.5 s.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { execFileSync } = require('child_process');
const ROOT = path.resolve(__dirname, '../../..');
const ctx = { console };
ctx.globalThis = ctx;
vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'ui.js'), 'utf8'), ctx);
const U = ctx.SnapUI;
let n = 0;
for (const [ms, shown] of [['500', '0.5 s'], [500, '0.5 s'], ['1000', '1 s'], ['1500', '1.5 s'], ['60000', '60 s'], ['250', '0.25 s'], ['x', '?']]) {
  assert.strictEqual(U.seconds(ms), shown, JSON.stringify(ms)); n++;
}
// the host's value is the rules table's (battle_room.ORDER_INTERVAL_MS); the guide shows it as 0.5 s
const host = execFileSync('python3', ['-I', '-c', 'import sys; sys.path.insert(0, sys.argv[1]); from near.arena import battle_room; print(battle_room.ORDER_INTERVAL_MS)', ROOT]).toString().trim();
assert.strictEqual(U.seconds(host), '0.5 s', 'host ' + host); n++;
// the Orders line on the Arena rules panel goes through SnapUI.seconds, with no rounding of input_interval_ms
const app = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');
assert.ok(/U\.line\('Orders', 'one every ' \+ U\.seconds\(t\.input_interval_ms\)\)/.test(app), 'the Orders line reads U.seconds'); n++;
assert.ok(!/Math\.round\([^)]*input_interval_ms/.test(app), 'no whole-second rounding of the order rate'); n++;
assert.ok(/'<div class="eyebrow">Arena rules · version '/.test(app), 'the panel is headed Arena rules'); n++;
console.log(n + ' PASS, 0 FAIL');
