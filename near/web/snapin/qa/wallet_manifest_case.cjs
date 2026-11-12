// The wallet list is ours, and a wallet is picked by id and executor, never by name, and a list that fails to load says so plainly.
// In a real browser, on the guide (index.html, wallet step) and on the wallet test page (both networks), clicking Meteor:
//  1. the list comes from this origin (web/snapin/wallets-manifest.json); no request goes to near-connect's default list on
//     raw.githubusercontent.com or jsDelivr, and the only executor asked for is the pinned one;
//  2. a list whose entry is NAMED "Meteor Wallet" under another id, with another executor, is refused: its executor is
//     never requested;
//  3. a list with the real id "meteor-wallet" but another executor is refused the same way;
//  4. a list that does not load says "Wallet list didn’t load; try again.", not a wallet count;
//  5. the guide inside another site's frame, whose parent hands the selector its own "meteor-wallet": the page refuses to
//     sign in there and the parent never gets a sign-in request.
// The tampered lists are served by this case at our own address AND at the two default addresses, so the same case runs
// on a wallet.js that still uses the defaults. Every host but this machine's is cut (no wallet code runs, on any lane).
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/wallet_manifest_case.cjs
'use strict';
const { spawn } = require('child_process'), path = require('path'), fs = require('fs');
const { chromium } = require('playwright');
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
const DEFAULTS = ['https://raw.githubusercontent.com/hot-dao/near-selector/refs/heads/main/repository/manifest.json', 'https://cdn.jsdelivr.net/gh/azbang/hot-connector/repository/manifest.json'];
const OURS = '/web/snapin/wallets-manifest.json';
const REVIEWED = JSON.parse(fs.readFileSync(path.join(REPO, 'near', OURS.replace(/^\/web/, 'web')), 'utf8'));
const METEOR = REVIEWED.wallets.find((w) => w.id === 'meteor-wallet');
const EVIL = 'https://evil.example/meteor-near-connect.js';
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// hosts start through the shared harness: each ends with this case however it ends (qa/hosts.cjs)
const HOSTS = require('./hosts.cjs');
const start = (args, ready, cwd) => HOSTS.start(args, ready, cwd || REPO);
const list = (wallets) => JSON.stringify({ version: '1.1.0', wallets });
const LOOKALIKE = list([Object.assign({}, METEOR, { id: 'meteor-connect', name: 'Meteor Wallet', executor: EVIL })]);
const SAME_ID = list([Object.assign({}, METEOR, { executor: EVIL })]);
const REAL = JSON.stringify(REVIEWED);

(async () => {
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', 'http://127.0.0.1:9'], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m;
  // one fresh browser per scenario (the selector caches wallet code in IndexedDB; single-process Chromium keeps one context)
  const scenario = async (name, { ours, defaults, page, mainnet, framed }) => {
    const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
    const ctx = await b.newContext(); const reqs = [], errs = [];
    ctx.on('request', (r) => reqs.push(r.url()));
    // every host but this machine's is cut (as a name that does not resolve)
    await ctx.route((u) => !['127.0.0.1', 'localhost'].includes(u.hostname), (r) => r.abort('namenotresolved'));
    // the list, served by this case where the scenario says (null: the real file / the address is cut)
    const serve = (body) => (r) => (body === 404 ? r.fulfill({ status: 404, body: 'not found' }) : r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body }));
    if (defaults !== undefined) for (const u of DEFAULTS) await ctx.route(u, serve(defaults));
    if (ours !== undefined) await ctx.route(base + OURS, serve(ours));
    const parentGot = [];
    let p = await ctx.newPage(), host = p;
    p.on('pageerror', (e) => errs.push(e.message));
    if (framed) {
      // a parent page frames the guide and keeps handing the selector its own "meteor-wallet" (near-connect takes the
      // message from any parent; served on this origin because single-process Chromium does not draw a cross-origin frame)
      await ctx.route(base + '/qa-frame.html', (r) => r.fulfill({ status: 200, contentType: 'text/html', body:
        `<!doctype html><title>other site</title><iframe id="f" src="${base}/web/snapin/index.html?step=wallet" style="width:1200px;height:880px"></iframe><script>
          window.got = []; addEventListener('message', (e) => { if (e.data && /near-wallet-injected-request/.test(e.data.type || '')) window.got.push(e.data.method); });
          const fake = ${JSON.stringify(Object.assign({}, METEOR, { executor: EVIL }))};
          setInterval(() => { const f = document.getElementById('f').contentWindow; f && f.postMessage({ type: 'near-wallet-injected', manifest: fake }, '*'); }, 50);
        </script>` }));
      await p.setViewportSize({ width: 1280, height: 900 });
      await p.goto(base + '/qa-frame.html');
      host = p; await p.waitForFunction(() => !!document.getElementById('f').contentWindow, null, { timeout: 10000 });
      for (let i = 0; i < 100 && !p.frames().find((f) => /index\.html/.test(f.url())); i++) await sleep(100);
      p = p.frames().find((f) => /index\.html/.test(f.url()));
    }
    let out = '';
    if (page === 'guide') {
      if (!framed) await p.goto(base + '/web/snapin/index.html?step=wallet');
      await p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
      await p.click('[data-act="wallet:meteor"]');
      await p.waitForFunction(() => { const t = (document.querySelector('#feedback') || {}).textContent || ''; return t && !/^Opening /.test(t); }, null, { timeout: 30000 }).catch(() => {});
      out = await p.$eval('#feedback', (e) => e.textContent).catch(() => '');
    } else {
      await p.goto(base + '/web/snapin/spike/mainnet-signin.html');
      await p.waitForFunction(() => window.SnapWallet && document.querySelectorAll('#btns button').length === 4, null, { timeout: 30000 });
      if (mainnet) await p.check('#mainnet');
      await p.click('#btns button:first-child');
      await p.waitForFunction(() => /"wallet": "meteor"/.test(document.getElementById('out').textContent), null, { timeout: 30000 }).catch(() => {});
      const o = await p.$eval('#out', (e) => e.textContent); out = o.slice(o.lastIndexOf('"wallet": "meteor"')).replace(/\s+/g, ' ');   // the sign-in's own entry
    }
    await sleep(800);   // any request the click starts has been made
    if (framed) parentGot.push(...await host.evaluate(() => window.got));
    await b.close().catch(() => {});
    const r = { name, out, reqs, errs, parentGot,
      asked: (u) => reqs.some((x) => x.split('?')[0] === u),
      defaultsAsked: reqs.filter((x) => DEFAULTS.includes(x.split('?')[0]) || (/raw\.githubusercontent\.com|cdn\.jsdelivr\.net/.test(x) && /manifest\.json/.test(x))),
      executors: [...new Set(reqs.filter((x) => !/^http:\/\/(127\.0\.0\.1|localhost)/.test(x) && !/manifest\.json/.test(x)).map((x) => x.split('?')[0]))] };
    console.log(`  ${name}: page says ${JSON.stringify(out.slice(0, 200))}; outside requests ${JSON.stringify(r.executors.concat(r.defaultsAsked.map((x) => x.split('?')[0])))}`);
    return r;
  };
  try {
    // 1. our list only, on the guide and on the wallet test page (testnet, then the mainnet switch)
    for (const [page, mainnet] of [['guide', false], ['test page', false], ['test page', true]]) {
      const r = await scenario(`clean ${page}${mainnet ? ' (mainnet switch on)' : ''}`, { page, mainnet });
      ok(r.asked(base + OURS) && r.defaultsAsked.length === 0, `${r.name}: the wallet list comes from this origin (${OURS}) and no request goes to the default list on raw.githubusercontent.com or jsDelivr (${r.defaultsAsked.length} made)`);
      ok(r.executors.length === 1 && r.executors[0] === METEOR.executor, `${r.name}: the only wallet code asked for is the pinned Meteor executor (${r.executors.join(', ') || 'none'})`);
    }
    // 2. a look-alike: named "Meteor Wallet", another id and executor
    { const r = await scenario('look-alike by name', { page: 'guide', ours: LOOKALIKE, defaults: LOOKALIKE });
      ok(!r.asked(EVIL) && /Wallet not connected: Meteor is not in the reviewed wallet list/.test(r.out), `${r.name}: an entry named "Meteor Wallet" with another id and executor is refused, its executor never requested: "${r.out.slice(0, 140)}"`); }
    // 3. the real id with another executor, on the guide and on the test page's mainnet switch
    { const r = await scenario('same id, other executor (guide)', { page: 'guide', ours: SAME_ID, defaults: SAME_ID });
      ok(!r.asked(EVIL) && /Meteor’s entry is not the reviewed one, so it was not opened/.test(r.out), `${r.name}: "meteor-wallet" with another executor is refused, its executor never requested: "${r.out.slice(0, 140)}"`); }
    { const r = await scenario('same id, other executor (test page, mainnet switch on)', { page: 'test page', mainnet: true, ours: SAME_ID, defaults: SAME_ID });
      ok(!r.asked(EVIL) && /"kind": "untrusted-wallet"/.test(r.out), `${r.name}: refused on the mainnet switch too, its executor never requested: ${r.out.slice(0, 160)}`); }
    // 4. the list does not load
    { const r = await scenario('list does not load', { page: 'guide', ours: 404, defaults: 404 });
      ok(r.out === 'Wallet list didn’t load; try again.', `${r.name}: the guide says "${r.out}" (not a wallet count)`); }
    // 5. framed by another site whose parent injects its own "meteor-wallet" (the defaults serve the real list here)
    { const r = await scenario('framed, parent injects meteor-wallet', { page: 'guide', framed: true, defaults: REAL });
      ok(r.parentGot.length === 0 && !r.asked(EVIL) && r.out === 'Open this page in its own tab to sign in: wallets do not open inside another site.', `${r.name}: no sign-in request reaches the parent (${r.parentGot.length}: ${r.parentGot.join(', ')}), and the page says "${r.out.slice(0, 120)}"`); }
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 300)); }
  web.child.kill();
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  console.log(`${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
