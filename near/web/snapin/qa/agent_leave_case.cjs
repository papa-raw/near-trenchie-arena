// The wallet owner can leave an agent-driven seat without a local room key.
// node near/web/snapin/qa/agent_leave_case.cjs --markup-only
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const ROOT = path.resolve(__dirname, '../..');

async function signedRequestCase() {
  let pageKey, request;
  const context = vm.createContext({ crypto: webcrypto, TextEncoder, Buffer, setTimeout, clearTimeout,
    fetch: async (url, options) => {
      if (url === '/dev/health') return { ok: true, json: async () => ({ chain_mode: { identity_network: 'mainnet' } }) };
      const body = JSON.parse(options.body);
      if (body.op === 'challenge') { pageKey = body.page_key; return { ok: true, json: async () => ({ message: 'test', recipient: 'arena.invalid', nonce: 'fixture' }) }; }
      if (body.op === 'signin') return { ok: true, json: async () => ({ signin: 'fixture-signin', account_id: 'coral.invalid', trenchies: [] }) };
      request = body;
      return { ok: true, json: async () => ({ state: 'home', fighter_id: 'coral' }) };
    }, SnapWallet: { signMessage: async () => ({ ok: true, accountId: 'coral.invalid' }) }
  });
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'snapin/identity.js'), 'utf8'), context);
  const identity = context.SnapIdentity;
  await identity.mode(); await identity.signIn();
  assert.equal(typeof identity.leave, 'function', 'the wallet page exposes signed owner Leave');
  await identity.leave('coral');
  assert.equal(request.op, 'leave');
  assert.equal(JSON.parse(request.payload).nft_token_id, 'coral');
  const digest = require('node:crypto').createHash('sha256').update(request.payload).digest('hex');
  const message = Buffer.from('trenchie-desk|leave|' + request.signin + '|' + request.at + '|' + digest);
  const key = await webcrypto.subtle.importKey('raw', Buffer.from(pageKey, 'base64url'), { name: 'Ed25519' }, false, ['verify']);
  assert.equal(await webcrypto.subtle.verify('Ed25519', key, Buffer.from(request.sig, 'base64url'), message), true);
  process.stdout.write('agent Leave request: signed with wallet-authorized page key and bound to token\n');
}

async function markupCase() {
  let now = 1000, calls = 0, fail = false;
  const listeners = {}, store = new Map([['trenchie.snapin.v1', JSON.stringify({ name: 'Coral Scout',
    door: { route: 'plan', identity: 'Codex' }, planCode: 'fixture-code' })]]);
  const context = vm.createContext({ URL, URLSearchParams, innerWidth: 390,
    Date: class extends Date { static now() { return now; } },
    location: { href: 'http://localhost/arena.html', search: '' }, setTimeout, clearTimeout,
    localStorage: { getItem: k => store.get(k) || null, setItem: (k, v) => store.set(k, v) },
    document: { addEventListener: (kind, fn) => { listeners[kind] = fn; },
      createElement: () => ({ querySelector: () => null, contains: () => true }), body: { appendChild() {} } },
    addEventListener() {}, dispatchEvent() {}, requestAnimationFrame() {}, CustomEvent: function () {},
    SnapRoom: { status: () => ({ phase: 'idle', fighter: null }), leave: () => assert.fail('remote seat must use wallet proof') },
    SnapIdentity: { leave: async id => { assert.equal(id, 'coral'); calls++; if (fail) throw new Error('sign in with the owner wallet'); return { state: 'home' }; } }
  });
  for (const file of ['guide-copy.js', 'panel.js']) vm.runInContext(fs.readFileSync(path.join(ROOT, 'snapin', file), 'utf8'), context);
  const S = context.SnapPanel.state;
  S.codeLog = { joined: true, fighter_id: 'coral', life: 8, state: 'ring' };
  context.SnapPanel.render();
  assert.match(S.el.innerHTML, /Life 8/);
  assert.doesNotMatch(S.el.innerHTML, /data-pn="leave" disabled/, 'agent-driven Leave is enabled');
  const click = () => listeners.click({ target: { closest: () => ({ dataset: { pn: 'leave' }, tagName: 'BUTTON', disabled: false }) } });
  click(); assert.equal(calls, 0); assert.match(S.el.innerHTML, /Leave the arena\? This life ends/);
  now += 120; click(); assert.equal(calls, 0, 'accidental repeat stays armed');
  listeners.keydown({ key: 'Escape' }); assert.equal(S.leaveUntil, 0);
  fail = true; click(); now += 600; click();
  await new Promise(resolve => setImmediate(resolve));
  assert.match(S.leaveMsg, /sign in with the owner wallet/);
  assert.equal(JSON.parse(store.get('trenchie.snapin.v1')).left, undefined, 'refusal retains seat');
  fail = false; click(); now += 600; click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 2, 'one refusal then one confirmed owner request');
  assert.equal(S.codeLog, null);
  assert.equal(JSON.parse(store.get('trenchie.snapin.v1')).planCode, undefined, 'ended pairing is cleared');
  assert.match(context.location.href, /step=ring/);
  process.stdout.write('agent Leave panel: confirm, rapid-repeat, Escape, refusal, owner success and pairing reset pass\n');
}

async function browserCase() {
  const http = require('node:http'), port = 18735;
  const server = http.createServer((req, res) => {
    if (req.url === '/') { res.setHeader('Content-Type', 'text/html'); res.end('<meta charset="utf-8"><link rel="stylesheet" href="/snapin/panel.css"><script src="/snapin/guide-copy.js"></script><script src="/snapin/panel.js"></script>'); return; }
    const file = path.resolve(ROOT, '.' + req.url);
    if (!file.startsWith(ROOT + path.sep)) { res.writeHead(404).end(); return; }
    try { res.setHeader('Content-Type', file.endsWith('.js') ? 'application/javascript' : 'text/css'); res.end(fs.readFileSync(file)); } catch { res.writeHead(404).end(); }
  });
  let browser;
  try {
    await new Promise(resolve => server.listen(port, '127.0.0.1', resolve));
    const options = { args: ['--single-process', '--no-zygote'] };
    if (process.env.HTTPS_PROXY) options.proxy = { server: process.env.HTTPS_PROXY, bypass: '127.0.0.1,localhost' };
    browser = await require('playwright').chromium.launch(options);
    const page = await browser.newPage();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto('http://127.0.0.1:' + port + '/');
      await page.evaluate(() => {
        localStorage.setItem('trenchie.snapin.v1', JSON.stringify({ name: 'Coral Scout', door: { route: 'plan', identity: 'Codex' }, planCode: 'fixture' }));
        window.calls = 0;
        window.SnapRoom = { status: () => ({ phase: 'idle', fighter: null }) };
        window.SnapIdentity = { leave: id => { if (id !== 'coral') throw Error('wrong token'); calls++; return new Promise(() => {}); } };
        SnapPanel.state.codeLog = { joined: true, fighter_id: 'coral', life: 8, state: 'ring' }; SnapPanel.render();
      });
      const leave = page.locator('[data-pn="leave"]');
      assert.equal(await leave.isEnabled(), true);
      assert.match(await page.locator('.ph .sub').innerText(), /Life 8/);
      await leave.click(); assert.equal(await page.evaluate(() => calls), 0);
      await page.waitForTimeout(600); await leave.click(); assert.equal(await page.evaluate(() => calls), 1);
      assert.equal(await leave.isDisabled(), true);
      process.stdout.write('agent Leave browser: ' + width + ' first tap0, confirmed1\n');
    }
  } finally { if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); }
}
(async () => {
  if (!process.argv.includes('--browser-only')) { await markupCase(); await signedRequestCase(); }
  if (!process.argv.includes('--markup-only')) await browserCase();
  process.stdout.write('agent-leave-case: PASS' + (process.argv.includes('--markup-only') ? '; browser NOT RUN' : '') + '\n');
})().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
