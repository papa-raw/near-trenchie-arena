// w2-wallet-gaps in a real browser (no wallet, no console edits): the wallet test page and the guide both take the
// deployed testnet market from chain.js; the test page names that receiver before the wallet's approval, and "Test my key"
// is there, off until a guest key is added. Testnet first: opened with no clicks the page is testnet; mainnet is one labelled
// switch (sign-in only); every grey button says why; a sign-in uses the network shown. The live call through a guest key is
// spike/test-key-live.mjs (testnet).
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/wallet_page_case.cjs
'use strict';
const { spawn } = require('child_process'), path = require('path');
const { chromium } = require('playwright');
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
const MARKET = 'market.trenchie-r4b-20261111.testnet';
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
// hosts start through the shared harness: each ends with this case however it ends (qa/hosts.cjs)
const HOSTS = require('./hosts.cjs');
const start = (args, ready, cwd) => HOSTS.start(args, ready, cwd || REPO);
(async () => {
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', 'http://127.0.0.1:9'], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const p = await (await b.newContext()).newPage(); const errs = [];
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
  try {
    await p.goto(base + '/web/snapin/spike/mainnet-signin.html'); await p.waitForFunction(() => window.SnapWallet && /importCheck/.test(document.getElementById('out').textContent), null, { timeout: 30000 });
    const t = await p.evaluate(() => ({ receiver: document.getElementById('receiver').textContent, approval: document.getElementById('approval').innerText, market: SnapWallet.config.marketAccount, rpc: SnapWallet.config.rpc,
      test: !!document.getElementById('testkey'), testOff: document.getElementById('testkey').disabled, testLabel: document.getElementById('testkey').textContent, out: document.getElementById('out').textContent }));
    ok(t.market === MARKET && t.receiver === MARKET, `the wallet test page uses the deployed market with no console edit (${t.market})`);
    ok(new RegExp('can call only ' + MARKET.replace(/\./g, '\\.') + ', with an allowance of 0\\.25 NEAR for gas and no payment').test(t.approval) && /do not approve/.test(t.approval), `the approval step names the receiver before the wallet asks: "${t.approval.slice(0, 120)}…"`);
    ok(t.test && t.testOff && t.testLabel === 'Test my key', `"Test my key" is on the page and off until a guest key is added`);
    ok(t.out.includes('"market": "' + MARKET + '"') && /"rpc": "https:\/\/rpc\.testnet\./.test(t.out), 'the page prints the market and the testnet RPC it will use');
    // ---- testnet first (w2-testnet-first): no clicks = testnet; mainnet is one deliberate, labelled switch; every grey button says why
    const t0 = await p.evaluate(() => ({ title: document.title, h1: document.querySelector('h1').textContent, net: document.getElementById('net').textContent, sw: document.getElementById('mainnet').checked,
      signins: [...document.querySelectorAll('#btns button')].map((x) => x.textContent), grey: [...document.querySelectorAll('button:disabled')].map((x) => [x.textContent, (document.getElementById(x.getAttribute('aria-describedby')) || {}).textContent || '']),
      swLabel: document.querySelector('label[for], fieldset label').innerText }));
    ok(/testnet/i.test(t0.title) && !/mainnet/i.test(t0.title + t0.h1) && /^Network: TESTNET/.test(t0.net) && t0.sw === false && t0.signins.length === 1 && t0.signins.every((x) => / \(testnet\)$/.test(x)),
      `opened with no clicks the page is testnet: title "${t0.title}", "${t0.net.slice(0, 40)}…", sign-in buttons "${t0.signins[0]}"…`);
    ok(t0.grey.length === 2 && t0.grey.every(([, why]) => why.trim().length > 0), `each grey button says why: ${t0.grey.map(([b2, w]) => b2 + ' (' + w + ')').join('; ')}`);
    ok(/Switch to MAINNET/.test(t0.swLabel) && /real mainnet account/.test(t0.swLabel) && /adds no key, sends no transaction and moves no money/.test(t0.swLabel), `the mainnet switch says what it does: "${t0.swLabel.slice(0, 150)}…"`);
    // the sign-in uses the network the page shows (SnapWallet.connect is a case-supplied recorder here: no wallet in headless)
    await p.evaluate(() => { window.__nets = []; SnapWallet.connect = async (id, a) => { window.__nets.push(a.network); return { ok: true, network: a.network, accountId: 'case-supplied.' + a.network }; }; });
    await p.click('#mainnet'); await p.waitForTimeout(200);
    const m = await p.evaluate(() => ({ net: document.getElementById('net').textContent, cls: document.getElementById('net').className, signins: [...document.querySelectorAll('#btns button')].map((x) => x.textContent),
      add: [document.getElementById('addkey').disabled, document.getElementById('addkey-why').textContent], test: [document.getElementById('testkey').disabled, document.getElementById('testkey-why').textContent] }));
    ok(/^Network: MAINNET \(a real account\)\. Sign-in only: no key, no transaction, no money\./.test(m.net) && m.cls === 'mainnet' && m.signins.every((x) => / \(mainnet\)$/.test(x)) && m.add[0] && /Testnet only/.test(m.add[1]) && m.test[0] && /Testnet only/.test(m.test[1]),
      `the switch turns the page to mainnet and says so: "${m.net}"; the key buttons stay off with "${m.add[1]}"`);
    await p.click('#btns button'); await p.waitForTimeout(200);
    const afterMain = await p.evaluate(() => ({ nets: window.__nets.slice(), add: document.getElementById('addkey').disabled }));
    await p.click('#mainnet'); await p.waitForTimeout(200);
    const backAdd = await p.evaluate(() => [document.getElementById('addkey').disabled, document.getElementById('addkey-why').textContent]);
    await p.click('#btns button'); await p.waitForTimeout(200);
    const afterTest = await p.evaluate(() => ({ nets: window.__nets.slice(), add: [document.getElementById('addkey').disabled, document.getElementById('addkey-why').textContent] }));
    ok(afterMain.nets[0] === 'mainnet' && afterMain.add && backAdd[0] && /Sign in on testnet first/.test(backAdd[1]) && afterTest.nets[1] === 'testnet' && afterTest.add[0] === false,
      `a sign-in uses the network shown (${afterTest.nets.join(' then ')}); a mainnet sign-in never turns the key button on, a testnet one does`);
    await p.goto(base + '/web/snapin/index.html?step=wallet'); await p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
    const g = await p.evaluate(() => ({ market: window.SnapWallet && SnapWallet.config.marketAccount, chain: window.SNAPIN_CHAIN && SNAPIN_CHAIN.marketAccount }));
    ok(g.market === MARKET && g.chain === MARKET, `the guide's wallet door uses the same market from chain.js (${g.market})`);
    ok(errs.length === 0, 'no page errors' + (errs.length ? ': ' + errs.join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 300)); }
  await b.close().catch(() => {}); web.child.kill();
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  console.log(`${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
