// The hourly cap across tabs, without a browser: two worker threads stand in for two tabs of one origin. Each runs its
// own brain on one shared store (each read and each write is atomic, as localStorage's are, but nothing makes a
// read-check-write atomic) and one shared lock manager (a cross-thread stand-in for navigator.locks: exclusive per
// name, granted in turn). At a barrier both call the model at the same instant, when the shared spend window has room
// for exactly one call. Across ROUNDS rounds the calls actually sent must never cost more than the cap, and each round
// must still send one. Last, a brain with no lock manager must refuse to call and say why.
// The fake provider answers after 300 ms with usage that meters to the call's reserved worst case W; the cap is 1.5 W.
// The same check in two real Chromium pages is qa/cap_tabs_case.cjs.
// usage: node near/web/snapin/test_brain_cap_tabs.cjs [rounds=20]
'use strict';
const { Worker, isMainThread, parentPort, workerData } = require('worker_threads');
const path = require('path');
const B = require('./brain.js');
const STORE_BYTES = 1 << 16;

// --- shared memory: [0] store mutex, [1] store length, [2] lock-manager word, [3] barrier, [4] calls sent; then the bytes
function shared(sab) {
  const w = new Int32Array(sab, 0, 8), bytes = new Uint8Array(sab, 32, STORE_BYTES);
  const hold = () => { while (Atomics.compareExchange(w, 0, 0, 1) !== 0) Atomics.wait(w, 0, 1, 1); };
  const free = () => { Atomics.store(w, 0, 0); Atomics.notify(w, 0); };
  const readAll = () => { hold(); try { const n = w[1]; return n ? JSON.parse(Buffer.from(bytes.slice(0, n)).toString('utf8')) : {}; } finally { free(); } };
  const writeKey = (k, v) => {
    hold();
    try {
      const n = w[1], m = n ? JSON.parse(Buffer.from(bytes.slice(0, n)).toString('utf8')) : {};
      if (v === undefined) delete m[k]; else m[k] = v;
      const out = Buffer.from(JSON.stringify(m), 'utf8'); bytes.set(out); w[1] = out.length;
    } finally { free(); }
  };
  const store = {
    get: (k) => { const v = readAll()[k]; return v === undefined ? null : v; },
    set: (k, v) => writeKey(k, String(v)), del: (k) => writeKey(k, undefined),
    json: (k, d) => { const v = readAll()[k]; try { return v ? JSON.parse(v) : d; } catch (e) { return d; } }
  };
  // One lock word for every name: exclusive, waited for without blocking the thread's event loop.
  const locks = {
    request: async (name, fn) => {
      while (Atomics.compareExchange(w, 2, 0, 1) !== 0) { const r = Atomics.waitAsync(w, 2, 1, 20); if (r.async) await r.value; }
      try { return await fn({ name, mode: 'exclusive' }); } finally { Atomics.store(w, 2, 0); Atomics.notify(w, 2); }
    }
  };
  return { w, store, locks };
}

const SHEET = { game: { name: 'Cap Sprout', temperament: 'Sunny', voice: ['Tide in my fists.'] }, identity: { brief: 'A newcomer.' } };
const USER = 'Ring: {}\nOne order, please.', MAX = 90;
const W = B.costUsd('nearai', { in: B.prefix(SHEET, 'Cap Sprout').length + USER.length, out: B.outputAllowance('nearai', MAX), cached: 0 });
const CAP = 1.5 * W;

if (!isMainThread) {
  const { w, store, locks } = shared(workerData.sab);
  const fakeFetch = async (url, init) => {
    Atomics.add(w, 4, 1);
    const body = JSON.parse(init.body), chars = body.messages.reduce((a, m) => a + String(m.content).length, 0);
    await new Promise((r) => setTimeout(r, 300));
    return { ok: true, status: 200, text: async () => JSON.stringify({ choices: [{ message: { content: '{"focus":null}' } }],
                                                                     usage: { prompt_tokens: chars, completion_tokens: body.max_tokens } }) };
  };
  const brain = B.create({ room: { on: () => () => {} }, store, fetch: fakeFetch, locks });
  parentPort.on('message', async (m) => {
    if (m === 'stop') { parentPort.close(); return; }
    Atomics.add(w, 3, 1); while (Atomics.load(w, 3) < 2) { /* the barrier: both tabs call at once */ }
    let result;
    try { await brain.ask({ provider: 'nearai', key: 'test-key', cap: CAP, sheet: SHEET, name: 'Cap Sprout' }, USER, MAX); result = 'answered'; }
    catch (e) { result = e.kind || 'error'; }
    parentPort.postMessage(result);
  });
  return;
}

(async () => {
  const rounds = Number(process.argv[2]) || 20;
  const sab = new SharedArrayBuffer(32 + STORE_BYTES), { w, store } = shared(sab);
  store.set(B.constants.SAVE, JSON.stringify({ door: { door: 'NEAR AI Cloud', route: 'key' }, sheet: SHEET, name: 'Cap Sprout' }));
  store.set(B.constants.KEY_STORE + 'NEAR AI Cloud', 'test-key');
  store.set(B.constants.CAP_STORE, CAP);
  const tabs = [0, 1].map(() => new Worker(__filename, { workerData: { sab } }));
  const ask = (t) => new Promise((r) => t.once('message', r));
  let pass = 0, fail = 0, over = 0, none = 0, most = 0;
  const ok = (c, m) => { if (c) pass++; else fail++; console.log((c ? 'PASS ' : 'FAIL ') + m); };
  console.log('one call\'s worst case W = $' + W.toFixed(8) + ', cap = 1.5 W = $' + CAP.toFixed(8) + ', ' + rounds + ' rounds');
  for (let i = 0; i < rounds; i++) {
    store.del(B.constants.SPEND_STORE); Atomics.store(w, 3, 0); Atomics.store(w, 4, 0);
    const answers = Promise.all(tabs.map(ask)); tabs.forEach((t) => t.postMessage('go'));
    const res = await answers, sent = Atomics.load(w, 4), spent = sent * W;
    most = Math.max(most, spent); if (spent > CAP + 1e-12) over++; if (sent === 0) none++;
    console.log('round ' + (i + 1) + ': sent ' + sent + ' (' + res.join(' / ') + '), spent $' + spent.toFixed(8) + (spent > CAP + 1e-12 ? '  OVER THE CAP' : ''));
  }
  tabs.forEach((t) => t.postMessage('stop'));
  ok(over === 0, 'two tabs calling at the same instant never send more than the cap allows: ' + over + '/' + rounds +
     ' rounds over (most spent in a round $' + most.toFixed(8) + ' against a cap of $' + CAP.toFixed(8) + ')');
  ok(none === 0, 'each round still sends one call (the cap had room for one): ' + none + '/' + rounds + ' rounds sent none');

  // No lock manager at all (a browser without Web Locks): no call is sent, and the reason says why.
  let sentBare = 0;
  const memo = new Map(), bareStore = { get: (k) => (memo.has(k) ? memo.get(k) : null), set: (k, v) => memo.set(k, String(v)), del: (k) => memo.delete(k),
                                         json: (k, d) => { const v = memo.get(k); return v ? JSON.parse(v) : d; } };
  const bare = B.create({ room: { on: () => () => {} }, store: bareStore, fetch: async () => { sentBare++; throw new Error('must not be called'); }, locks: null });
  let why = null; try { await bare.ask({ provider: 'nearai', key: 'k', cap: CAP * 10, sheet: SHEET, name: 'Cap Sprout' }, USER, MAX); } catch (e) { why = e; }
  ok(sentBare === 0 && why && why.kind === 'no-locks' && /tabs/.test(why.message),
     'without a lock manager no call is sent and the reason names the tabs: sent ' + sentBare + ', ' + (why && why.kind) + ': ' + (why && why.message));
  console.log(pass + '/' + (pass + fail) + ' passed');
  process.exitCode = fail ? 1 : 0;
})();
