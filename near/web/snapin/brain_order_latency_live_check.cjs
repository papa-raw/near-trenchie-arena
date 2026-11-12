// Live check of an owner's order on the real model, no browser: the brain's own tell() (the same prompt, provider and
// cap code the guide runs) on NEAR AI Cloud, with a room whose ACK applies 0.1 s after receipt as the arena's does.
// Prints, per order, the Send-to-receipt time the brain measured (lastOrderTiming) and what the AI wrote, then p50/p95.
// The arena leg (behaviour frame to signed ACK) is measured separately on a running host; this measures the model leg.
// Run: NEARAI_API_KEY=... NODE_USE_ENV_PROXY=1 node near/web/snapin/brain_order_latency_live_check.cjs [orders=10]
'use strict';
const B = require('./brain.js');
const key = process.env.NEARAI_API_KEY;
if (!key) { console.error('needs NEARAI_API_KEY'); process.exit(2); }
const NEAR = { door: 'NEAR AI Cloud', route: 'key', identity: 'NEAR AI Cloud' };
const SHEET = { game: { name: 'Barnacle Bertie', temperament: 'Restless', voice: ['Barnacles hold, so do I.'], emoji: ['🦀', '🔥', '💥', '😤', '🏃'] },
                identity: { brief: 'A newcomer who sticks to whatever she grabs.' } };
const ORDERS = ['kill Leeth', 'run away from everyone', 'grab the loot and stay away from fights', 'hold the center',
                'protect nobody, hunt the weakest', 'fight everyone', 'stay away from Sailor', 'loot first, then hunt',
                'only hit people below half health', 'go berserk'];
const m = new Map([[B.constants.SAVE, JSON.stringify({ door: NEAR, sheet: SHEET })], [B.constants.CAP_STORE, '0.05'], [B.constants.KEY_STORE + 'NEAR AI Cloud', key]]);
const store = { get: (k) => (m.has(k) ? m.get(k) : null), set: (k, v) => { m.set(k, String(v)); }, del: (k) => { m.delete(k); },
                json: (k, d) => { const v = m.get(k); return v ? JSON.parse(v) : d; } };
const RING = { fighters: [
  { fighter_id: 'dev-bertie', public_name: 'DEV Barnacle Bertie', x_milli: 0, y_milli: 0, health_milli: '100000', state: 'ring', house: false },
  { fighter_id: 'tommy-leeth', public_name: 'Leeth', x_milli: 4000, y_milli: 0, health_milli: '90000', state: 'ring', house: true },
  { fighter_id: 'laser-sailor', public_name: 'Sailor', x_milli: -6000, y_milli: 2000, health_milli: '100000', state: 'ring', house: true }], items: [] };
const room = { listeners: [], on(fn) { room.listeners.push(fn); return () => {}; }, async observe() { return RING; },
  async intent() { return { state: 'accepted' }; }, setOrder() { return true; },
  async behaviour(b) { return { type: 'battle_receipt', kind: 'behaviour', ack: { type: 'behaviour_ack', status: 'applied', behaviour: b, applies_in_ms: 100, summary: 'recorded' } }; } };
(async () => {
  const n = Math.max(1, Math.min(ORDERS.length, Number(process.argv[2]) || ORDERS.length));
  const brain = B.create({ room, store, fetch: globalThis.fetch.bind(globalThis), setTimer: () => 1, clearTimer: () => {} });
  room.listeners.push(() => {}); brain.fighter = { id: 'dev-bertie', life: 'dev-bertie:life:0', lives: 1 };
  const rows = [];
  for (const order of ORDERS.slice(0, n)) {
    const before = brain.hourSpend();
    const out = await brain.tell(order);
    const t = brain.status().lastOrderTiming;
    rows.push({ order, ok: !!out.receipt, send_to_receipt_ms: t && t.order === order ? t.receipt_ms : null,
                applies_in_ms: t && t.order === order ? t.applies_in_ms : null, reply: out.reply, chip: out.chip || null,
                behaviour: out.receipt && out.receipt.behaviour, usd: +(brain.hourSpend() - before).toFixed(6) });
  }
  const ms = rows.filter((r) => r.send_to_receipt_ms != null).map((r) => r.send_to_receipt_ms + r.applies_in_ms).sort((a, b) => a - b);
  const q = (p) => ms.length ? ms[Math.min(ms.length - 1, Math.ceil(p * ms.length) - 1)] : null;
  console.log(JSON.stringify({ model: 'NEAR AI Cloud (the brain default)', orders: rows,
    send_to_apply_ms: { n: ms.length, p50: q(0.5), p95: q(0.95), max: ms.at(-1) || null },
    usd_total: +rows.reduce((a, r) => a + r.usd, 0).toFixed(6) }, null, 1));
})();
