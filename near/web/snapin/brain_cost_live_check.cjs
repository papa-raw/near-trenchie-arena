// What battle mode really costs a browser player per hour: the real brain.js loop on the real model (NEAR AI Cloud,
// DeepSeek V4.1 Flash), against a room that replays a measured fight rhythm (hits as often as a house fighter took them in
// the live DEV crowd, a KO every few minutes), one step per 5 s of a fake clock. It prints the calls by kind, the metered
// spend and the per-hour number, so the AI door's cost line can say what it is based on. No browser; the key is never printed.
// Run: NEARAI_API_KEY=... NODE_USE_ENV_PROXY=1 node near/web/snapin/brain_cost_live_check.cjs [steps=72]
'use strict';
const B = require('./brain.js');
const key = process.env.NEARAI_API_KEY;
if (!key) { console.error('needs NEARAI_API_KEY'); process.exit(2); }
const steps = +(process.argv[2] || 72);
const SHEET = { game: { name: 'Dune Sprout', temperament: 'Sunny', voice: ['Sand in my shoes, tide in my fists.'], emoji: ['🦀', '🌊', '🏝️', '😤', '🥥'] },
                identity: { brief: 'A newcomer who washed ashore last week and swings first.' } };
const m = new Map([[B.constants.SAVE, JSON.stringify({ door: { door: 'NEAR AI Cloud', route: 'key', identity: 'NEAR AI Cloud' }, sheet: SHEET })],
                   [B.constants.CAP_STORE, '5'], [B.constants.KEY_STORE + 'NEAR AI Cloud', key]]);
const store = { get: (k) => (m.has(k) ? m.get(k) : null), set: (k, v) => { m.set(k, String(v)); }, del: (k) => { m.delete(k); },
                json: (k, d) => { const v = m.get(k); return v ? JSON.parse(v) : d; } };
// A live DEV crowd run: 111 hits over 5 fighters in 3 min = 7.4 hits/min each, 8 KOs (~0.5/min each).
let hp = 200, step = 0;
const kinds = { plan: 0, line: 0, prediction: 0, tell: 0 };
const room = {
  on(fn) { this.fn = fn; return () => {}; },
  async observe() {
    return { fighters: [{ fighter_id: 'dev-me', public_name: 'DEV sprout', x_milli: 0, y_milli: 0, health_milli: String(hp * 1000), state: 'ring', house: false },
                        { fighter_id: 'satrenchi', public_name: 'satrenchi', x_milli: 3000, y_milli: 0, health_milli: '150000', state: 'ring', house: true },
                        { fighter_id: 'kain-warrior', public_name: 'kain-warrior', x_milli: -4000, y_milli: 2000, health_milli: '120000', state: 'ring', house: true }], items: [{}] };
  },
  async behaviour(b) { return { type: 'battle_receipt', ack: { status: 'applied', behaviour: b, summary: 'New behaviour recorded' } }; },
  async speech() { kinds.line++; return { type: 'battle_receipt', ack: { status: 'posted' } }; },
  async intent() { return { state: 'accepted' }; },
  setOrder() { return true; }
};
const fetchCounting = async (url, init) => {
  const ask = JSON.parse(init.body).messages[1].content;
  if (ask.includes('Predict your NEXT life')) kinds.prediction++; else if (ask.includes('Write the behaviour you want now')) kinds.plan++;
  return globalThis.fetch(url, init);
};
(async () => {
  const clock = { t: 1e6 };
  const b = B.create({ room, store, fetch: fetchCounting, now: () => clock.t, setTimer: () => 1, clearTimer: () => {} }).start();
  room.fn({ phase: 'in', fighter: { id: 'dev-me', life: 'dev-me:life:0', lives: 1 } });
  for (step = 0; step < steps; step++) {
    if (step % 24 === 23) { hp = 200; room.fn({ phase: 'in', fighter: { id: 'dev-me', life: 'dev-me:life:' + (step / 24 | 0 + 1), lives: 2 } }); }   // a KO every 2 min
    else if (step % 2 === 1) hp = Math.max(20, hp - 15);                                        // ~6 hits a minute
    await b.step();
    clock.t += 5000;
  }
  const rows = JSON.parse(m.get(B.constants.SPEND_STORE) || '[]'), usd = rows.reduce((a, r) => a + r.usd, 0), minutes = steps * 5 / 60;
  console.log(JSON.stringify({ model: 'deepseek-ai/DeepSeek-V4.1-Flash-1017 on NEAR AI Cloud', sim_minutes: minutes, calls: kinds, metered_usd: +usd.toFixed(6),
    usd_per_hour: +(usd * 60 / minutes).toFixed(4), per_call_usd: { mean: +(usd / Math.max(1, rows.length)).toFixed(6) },
    basis: 'one step per 5 s; a hit every ~10 s (live DEV crowd rhythm), a KO every 2 min; plan rewrites at most every 20 s on hits, plus on low hp, a KO and a refused plan; lines at most every 10 s; the next life\'s prediction once per life' }, null, 1));
})();
