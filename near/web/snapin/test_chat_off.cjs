// The order box (chat.js) is off, with the AI's own reason, whenever the AI cannot take an order. Run: node near/web/snapin/test_chat_off.cjs
// Real brains (brain.js) are driven into the two states where they send no call: no Web Locks (the cap could not hold across
// tabs) and no storage (the hourly spend could not be kept). Each status is handed to chat.js exactly as the page's
// SnapBrain.on hook hands it over, and the box is drawn: it must be disabled, Send disabled, the brain's chip shown as the
// reason, no "Try again", and Send must not reach the brain. A driving brain is the control: the box is on.
'use strict';
const assert = require('node:assert/strict'), fs = require('fs'), path = require('path'), vm = require('vm');
const B = require('./brain.js');
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const NEAR = { door: 'NEAR AI Cloud', route: 'key', identity: 'NEAR AI Cloud' };
function store() {
  const m = new Map([[B.constants.SAVE, JSON.stringify({ door: NEAR, sheet: { game: { name: 'Dune Sprout', temperament: 'Sunny', voice: ['Sand in my shoes.'] }, identity: { brief: 'A newcomer.' } } })],
    [B.constants.CAP_STORE, '0.5'], [B.constants.KEY_STORE + NEAR.door, 'sk-test-PLAYER-KEY-0123456789']]);
  return { get: (k) => (m.has(k) ? m.get(k) : null), set: (k, v) => { m.set(k, String(v)); }, del: (k) => { m.delete(k); }, json: (k, d) => { const v = m.get(k); return v ? JSON.parse(v) : d; } };
}
function room() { const ls = []; return { on(fn) { ls.push(fn); return () => {}; }, async observe() { return { fighters: [], items: [] }; }, async intent() { return { state: 'accepted' }; }, setOrder() { return true; }, push(s) { ls.forEach((f) => f(s)); } }; }
const LOCKS = { request: (n, fn) => fn() };
async function brainIn({ st, locks }) {
  const calls = [], r = room();
  const b = B.create({ room: r, store: st, fetch: async (u) => { calls.push(u); throw new Error('no call expected'); }, now: () => 1e6, setTimer: () => 1, clearTimer: () => {}, locks }).start();
  r.push({ phase: 'in', fighter: { id: 'dev-sprout', life: 'dev-sprout:life:0', lives: 1 } });
  await b.step();
  return { b, calls };
}
// chat.js in its own page-like global, with SnapBrain.on/tell standing for the page's hook
function chatWith(status) {
  const told = [], g = { SnapBrain: { on() {}, tell: async (t) => { told.push(t); return { reply: null, receipt: null, chip: status.chip }; } } };
  g.globalThis = g; vm.createContext(g);
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'chat.js'), 'utf8'), g, { filename: 'chat.js' });
  g.SnapChat.state.brain = status;   // what SnapBrain.on(fn) stores (chat.js hook: S.brain = st)
  return { C: g.SnapChat, told };
}
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
(async () => {
  const broken = store(); broken.set = () => { throw new Error('QuotaExceededError'); };
  const cases = [['no-locks', { st: store(), locks: null }], ['no-storage', { st: broken, locks: LOCKS }]];
  for (const [want, deps] of cases) {
    const { b, calls } = await brainIn(deps), s = b.status();
    assert.equal(s.state, want, 'the brain is in ' + want); assert.equal(calls.length, 0);
    const { C, told } = chatWith(s); C.state.draft = 'Grab the loot and stay away from fights';
    const h = C.html({ name: 'Dune Sprout' });
    const box = (h.match(/<textarea id="order"[^>]*>/) || [''])[0], btn = (h.match(/<button type="submit"[^>]*>/) || [''])[0];
    ok(/ disabled/.test(box) && / disabled/.test(btn), `${want}: the order box and Send are off (box ${/ disabled/.test(box) ? 'disabled' : 'ENABLED'}, Send ${/ disabled/.test(btn) ? 'disabled' : 'ENABLED'})`);
    ok(h.includes('<div class="sub" role="status">' + esc(s.chip) + '</div>') && !/Try again/i.test(h), `${want}: the box says the brain's own reason and no "Try again": "${s.chip.slice(0, 110)}…"`);
    await C.send(() => {});
    ok(told.length === 0 && !C.state.sending, `${want}: Send while the box is off does not reach the brain (${told.length} orders told)`);
  }
  // the control: a brain that can drive leaves the box on
  { const { C } = chatWith({ state: 'driving', chip: 'Your AI is driving.' }); C.state.draft = 'hold the centre';
    const h = C.html({ name: 'Dune Sprout' });
    ok(!/<textarea id="order"[^>]* disabled/.test(h) && !/<button type="submit"[^>]* disabled/.test(h), 'control: a driving brain leaves the box and Send on'); }
  console.log(`${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('FAIL case crashed: ' + (e && e.stack || e)); process.exit(1); });
