// The hourly cap across tabs: two pages of one origin, in a real Chromium, each with its own brain, call the model at the
// same instant when the shared spend window has room for exactly one call. The page promises "It never spends more than
// your cap", so across ROUNDS rounds the calls actually sent to the provider must never cost more than the cap, and each
// round must still send one (the cap is not met by refusing everything). A third page without Web Locks must refuse to
// call and say why. No network: the provider is a fake fetch inside each page that answers after 300 ms with usage that
// meters to the call's reserved worst case, so two calls cost 2 W against a cap of 1.5 W.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/cap_tabs_case.cjs [rounds=20]
'use strict';
const fs = require('fs'), path = require('path');
const { chromium } = require('playwright');
const BRAIN = fs.readFileSync(path.resolve(__dirname, '..', 'brain.js'), 'utf8');
const ROUNDS = Number(process.argv[2]) || 20;
const ORIGIN = 'https://cap-tabs.test';   // a secure context: Chromium gives navigator.locks only there (the route is fulfilled, no certificate)
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) pass++; else fail++; console.log((c ? 'PASS ' : 'FAIL ') + m); };

// In each page: a brain on this origin's localStorage, a fake provider that counts what it is sent, and go(T, cap) that
// waits for the shared instant T and asks once.
const SETUP = () => {
  const B = window.SnapBrain, SPEND = B.constants.SPEND_STORE;
  const store = {
    get: (k) => localStorage.getItem(k), set: (k, v) => localStorage.setItem(k, v), del: (k) => localStorage.removeItem(k),
    json: (k, d) => { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } }
  };
  window.__sent = 0;
  const fakeFetch = async (url, init) => {
    window.__sent++;
    const body = JSON.parse(init.body), chars = body.messages.reduce((a, m) => a + String(m.content).length, 0);
    await new Promise((r) => setTimeout(r, 300));
    return { ok: true, status: 200, text: async () => JSON.stringify({ choices: [{ message: { content: '{"focus":null}' } }],
                                                                     usage: { prompt_tokens: chars, completion_tokens: body.max_tokens } }) };
  };
  const room = { on: () => () => {} };
  const brain = B.create({ room, store, fetch: fakeFetch });
  const sheet = { game: { name: 'Cap Sprout', temperament: 'Sunny', voice: ['Tide in my fists.'] }, identity: { brief: 'A newcomer.' } };
  const USER = 'Ring: {}\nOne order, please.', MAX = 90;
  const worst = B.costUsd('nearai', { in: B.prefix(sheet, 'Cap Sprout').length + USER.length, out: MAX, cached: 0 });
  window.__worst = worst;
  window.__clear = () => { localStorage.removeItem(SPEND); window.__sent = 0; };
  window.__go = async (T, cap) => {
    while (Date.now() < T) { /* the shared instant */ }
    const c = { provider: 'nearai', key: 'test-key', cap, sheet, name: 'Cap Sprout' };
    try { await brain.ask(c, USER, MAX); return { sent: window.__sent, result: 'answered' }; }
    catch (e) { return { sent: window.__sent, result: e.kind || 'error', message: e.message }; }
  };
  return worst;
};

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  await ctx.route(ORIGIN + '/**', (route) => {
    const u = new URL(route.request().url());
    if (u.pathname === '/brain.js') return route.fulfill({ contentType: 'text/javascript', body: BRAIN });
    return route.fulfill({ contentType: 'text/html', body: '<!doctype html><meta charset="utf-8"><title>cap</title><script src="/brain.js"></script>' });
  });
  const a = await ctx.newPage(), b = await ctx.newPage();
  await Promise.all([a.goto(ORIGIN + '/a'), b.goto(ORIGIN + '/b')]);
  const W = await a.evaluate(SETUP); await b.evaluate(SETUP);
  const haveLocks = await Promise.all([a, b].map((p) => p.evaluate(() => window.isSecureContext && !!(navigator.locks && navigator.locks.request))));
  ok(haveLocks.every(Boolean), 'both pages are secure contexts with Web Locks (else every round would only test the refusal): ' + JSON.stringify(haveLocks));
  const CAP = 1.5 * W;
  console.log('one call\'s worst case W = $' + W.toFixed(8) + ', cap = 1.5 W = $' + CAP.toFixed(8) + ', ' + ROUNDS + ' rounds');
  let over = 0, none = 0, worstTotal = 0;
  for (let i = 0; i < ROUNDS; i++) {
    await a.evaluate(() => window.__clear()); await b.evaluate(() => window.__clear());
    const T = Date.now() + 250;
    const [ra, rb] = await Promise.all([a.evaluate(([t, c]) => window.__go(t, c), [T, CAP]), b.evaluate(([t, c]) => window.__go(t, c), [T, CAP])]);
    const sent = ra.sent + rb.sent, total = sent * W;
    worstTotal = Math.max(worstTotal, total);
    if (total > CAP + 1e-12) over++;
    if (sent === 0) none++;
    console.log('round ' + (i + 1) + ': sent ' + sent + ' (' + ra.result + ' / ' + rb.result + '), spent $' + total.toFixed(8) + (total > CAP + 1e-12 ? '  OVER THE CAP' : ''));
  }
  ok(over === 0, 'two tabs calling at the same instant never send more than the cap allows: ' + over + '/' + ROUNDS + ' rounds over (most spent in a round $' + worstTotal.toFixed(8) + ' against a cap of $' + CAP.toFixed(8) + ')');
  ok(none === 0, 'each round still sends one call (the cap had room for one): ' + none + '/' + ROUNDS + ' rounds sent none');

  // A browser without Web Locks: the brain refuses to call rather than risk passing the cap, and says why.
  const n = await ctx.newPage();
  await n.addInitScript(() => { try { Object.defineProperty(Navigator.prototype, 'locks', { get: () => undefined, configurable: true }); } catch (e) { /* */ } });
  await n.goto(ORIGIN + '/n');
  await n.evaluate(SETUP);
  const rn = await n.evaluate(([t, c]) => window.__go(t, c), [Date.now(), CAP * 10]);
  ok(rn.sent === 0 && rn.result === 'no-locks' && /tabs/.test(rn.message || ''),
     'without Web Locks no call is sent and the reason names the tabs: sent ' + rn.sent + ', ' + rn.result + ': ' + (rn.message || ''));
  await browser.close();
  console.log(pass + '/' + (pass + fail) + ' passed');
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
