// Live check of the player brain's prompts on a real provider (node, no browser): the same chat() call, sheet prefix,
// ring view and validators brain.js uses in the page. It never prints the key.
// Run: NEARAI_API_KEY=... node near/web/snapin/brain_live_check.cjs [orders=10] [spreads=5]
'use strict';
const B = require('./brain.js');
const key = process.env.NEARAI_API_KEY;
if (!key) { console.error('brain_live_check: needs NEARAI_API_KEY in the environment'); process.exit(2); }
const nOrders = +(process.argv[2] || 10), nSpreads = +(process.argv[3] || 5);
const sheet = { game: { name: 'Dune Sprout', temperament: 'Sunny', voice: ['Sand in my shoes, tide in my fists.'], tics: ['Counts every wave out loud.'] },
                identity: { brief: 'A newcomer who washed ashore last week and swings first.' } };
const RING = { fighters: [
  { fighter_id: 'dev-sprout', public_name: 'DEV sprout', x_milli: 0, y_milli: 0, health_milli: '64000', state: 'ring', house: false },
  { fighter_id: 'satrenchi', public_name: 'satrenchi', x_milli: 3000, y_milli: 0, health_milli: '30000', state: 'ring', house: true },
  { fighter_id: 'laser-sailor', public_name: 'laser-sailor', x_milli: 9000, y_milli: 1000, health_milli: '100000', state: 'ring', house: true },
  { fighter_id: 'kain-warrior', public_name: 'kain-warrior', x_milli: -4000, y_milli: 2000, health_milli: '90000', state: 'ring', house: true }], items: [{}] };
const ORDER_ASK = 'Give your fighter one order. Answer one JSON object: {"focus": id or null, "avoid": id or null, "loot": "nearest"|"ignore", "sig": "auto"|"hold"|"use", "leave": false, "say": a short line or null}. Use only ids from "near".';
const SPREAD_ASK = 'Predict your NEXT life before it starts. Answer one JSON object: {"spread_pct": [p1, p2, p3, p4] (whole percents for exactly 1, 2, 3 and 4+ KOs, summing to 100), "zero_pct": your chance of 0 KOs, 0-100}.';

(async () => {
  const sys = B.prefix(sheet, 'Dune Sprout'), v = B.view(RING, 'dev-sprout'), ids = v.near.map((n) => n.id);
  const out = { orders: [], spreads: [], seconds: [], usd: 0, errors: [] };
  const ask = async (user, max) => {
    const t = Date.now(); const r = await B.chat('nearai', key, sys, user, { fetch: globalThis.fetch, maxTokens: max });
    out.seconds.push((Date.now() - t) / 1000);
    if (!r.ok) { out.errors.push(r.kind + ': ' + r.message); return null; }
    out.usd += B.costUsd('nearai', r.usage); return r.text;
  };
  for (let i = 0; i < nOrders; i++) {
    const text = await ask('Ring: ' + JSON.stringify(v) + '\n' + ORDER_ASK, 90); if (text === null) continue;
    let c; try { c = B.checkOrder(JSON.parse(text.slice(text.indexOf('{'), text.lastIndexOf('}') + 1)), ids); } catch (e) { c = { error: e.message }; }
    out.orders.push(c.error ? { error: c.error } : c.order);
  }
  for (let i = 0; i < nSpreads; i++) {
    const text = await ask('Your last life: {"lives":' + (i + 1) + '}\n' + SPREAD_ASK, 80); if (text === null) continue;
    let p = null; try { p = JSON.parse(text.slice(text.indexOf('{'), text.lastIndexOf('}') + 1)); } catch (e) { p = null; }
    const bad = p ? B.checkSpread(p) : 'no JSON';
    out.spreads.push(bad ? { error: bad } : { spread_pct: p.spread_pct, zero_pct: p.zero_pct });
  }
  const s = out.seconds.slice().sort((a, b) => a - b), q = (x) => s[Math.min(s.length - 1, Math.floor(x * s.length))];
  const valid = out.orders.filter((o) => !o.error), says = valid.filter((o) => o.say);
  console.log(JSON.stringify({ model: B.constants.PRICES ? 'deepseek-ai/DeepSeek-V4.1-Flash-1017' : '', orders_valid: valid.length + '/' + out.orders.length,
    focus_set: valid.filter((o) => o.focus).length, says: says.length, spreads_valid: out.spreads.filter((p) => !p.error).length + '/' + out.spreads.length,
    p50_s: q(0.5), p95_s: q(0.95), usd: +out.usd.toFixed(6), errors: out.errors, sample_orders: valid.slice(0, 4), sample_spreads: out.spreads.slice(0, 3) }, null, 1));
})();
