// Expired owner Leave offers wallet sign-in and uses renewed page authority without reloading the arena.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/leave_signin_case.cjs
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const ROOT = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(ROOT, file), 'utf8');
const EXPIRED = 'sign in with your wallet first (the sign-in expired or is unknown)';

async function panelCase() {
  let now = 1000, expired = true;
  const listeners = {}, store = new Map([['trenchie.snapin.v1', JSON.stringify({ name: 'Coral Scout',
    door: { route: 'plan', identity: 'Codex' }, planCode: 'fixture-code' })]]);
  const context = vm.createContext({ URL, URLSearchParams, setTimeout, clearTimeout,
    Date: class extends Date { static now() { return now; } },
    location: { href: 'https://arena.invalid/web/arena.html?ws=wss%3A%2F%2Farena.invalid%2Fws', search: '?ws=wss%3A%2F%2Farena.invalid%2Fws' },
    localStorage: { getItem: key => store.get(key) || null, setItem: (key, value) => store.set(key, value) },
    document: { addEventListener: (kind, fn) => { listeners[kind] = fn; }, body: { appendChild() {} },
      currentScript: { src: 'https://arena.invalid/web/snapin/panel.js' },
      createElement: () => ({ querySelector: () => null, contains: () => true }) },
    addEventListener() {}, dispatchEvent() {}, requestAnimationFrame() {}, CustomEvent: function () {},
    SnapIdentity: { leave: async () => { if (expired) throw new Error(EXPIRED); return { state: 'home' }; } }
  });
  for (const file of ['guide-copy.js', 'panel.js']) vm.runInContext(read(file), context);
  const state = context.SnapPanel.state;
  state.codeLog = { joined: true, fighter_id: 'coral', life: 8, state: 'ring' };
  const click = () => listeners.click({ target: { closest: () => ({ dataset: { pn: 'leave' }, disabled: false, tagName: 'BUTTON' }) } });
  context.SnapPanel.render(); click(); now += 600; click();
  await new Promise(resolve => setImmediate(resolve));
  assert.match(state.el.innerHTML, /Sign in again/, 'expired Leave offers a recovery link');
  const link = state.el.innerHTML.match(/<a\b[^>]*href="([^"]+)"[^>]*>Sign in again<\/a>/);
  assert.ok(link, 'recovery is a native link');
  const url = new URL(link[1].replace(/&amp;/g, '&'), context.location.href);
  assert.equal(url.pathname, '/web/snapin/index.html');
  assert.equal(url.searchParams.get('step'), 'wallet');
  assert.equal(url.searchParams.get('ws'), 'wss://arena.invalid/ws');
  assert.equal(url.searchParams.has('from'), false, 'saved-progress routing cannot override the wallet step');
  assert.equal(JSON.parse(store.get('trenchie.snapin.v1')).planCode, 'fixture-code', 'expiry keeps the pairing');
  expired = false; click(); now += 600; click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(state.codeLog, null);
  assert.doesNotMatch(state.el.innerHTML || '', /Sign in again/, 'successful Leave clears recovery');
  process.stdout.write('leave-signin panel: expired authority offers wallet link and retained panel can retry\n');
}

async function identityCase() {
  let persisted, serial = 0, nextKey, expired = '';
  const keys = new Map(), seen = [];
  const indexedDB = { open: () => {
    const request = {};
    setImmediate(() => {
      request.result = { close() {}, transaction: () => {
        const tx = { objectStore: () => ({
          get: () => { const r = {}; setImmediate(() => { r.result = persisted; tx.oncomplete(); }); return r; },
          put: value => { const r = {}; setImmediate(() => { persisted = structuredClone(value); tx.oncomplete(); }); return r; }
        }) };
        return tx;
      } };
      request.onsuccess();
    });
    return request;
  } };
  const context = vm.createContext({ crypto: crypto.webcrypto, TextEncoder, Buffer, indexedDB, setTimeout, clearTimeout,
    fetch: async (url, init) => {
      if (url === '/dev/health') return { ok: true, json: async () => ({ chain_mode: { identity_network: 'mainnet' } }) };
      const body = JSON.parse(init.body);
      if (body.op === 'challenge') { nextKey = body.page_key; return { ok: true, json: async () => ({ message: 'fixture', recipient: 'arena.invalid', nonce: 'fixture' }) }; }
      if (body.op === 'signin') { const sid = 'S' + ++serial; keys.set(sid, nextKey); return { ok: true, json: async () => ({ signin: sid, account_id: 'coral.invalid', trenchies: [] }) }; }
      assert.equal(body.op, 'leave');
      seen.push(body.signin);
      const digest = crypto.createHash('sha256').update(body.payload).digest('hex');
      const key = crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: keys.get(body.signin) }, format: 'jwk' });
      assert.equal(crypto.verify(null, Buffer.from('trenchie-desk|leave|' + body.signin + '|' + body.at + '|' + digest), key, Buffer.from(body.sig, 'base64url')), true);
      return { ok: body.signin !== expired, json: async () => body.signin === expired ? { error: EXPIRED } : { state: 'home' } };
    }, SnapWallet: { signMessage: async () => ({ ok: true, accountId: 'coral.invalid' }) }
  });
  vm.runInContext(read('identity.js'), context);
  const arena = context.SnapIdentity;
  await arena.mode(); await arena.signIn(); await arena.leave('coral');
  expired = 'S1'; await assert.rejects(arena.leave('coral'), /sign in with your wallet first/);
  const guide = arena.make(); await guide.mode(); await guide.signIn();
  await arena.leave('coral');
  assert.deepEqual(seen, ['S1', 'S1', 'S2'], 'retained arena reads the renewed sign-in and corresponding key');
  process.stdout.write('leave-signin identity: expired S1 then guide S2; retained arena signs with renewed key\n');
}

async function browserCase() {
  const options = { args: ['--single-process', '--no-zygote'] };
  if (process.env.HTTPS_PROXY) options.proxy = { server: process.env.HTTPS_PROXY, bypass: '127.0.0.1,localhost' };
  const browser = await require('playwright').chromium.launch(options);
  try {
      const context = await browser.newContext();
      // A reserved fixture origin fulfilled in memory: no DNS, HTTP server or external service is contacted.
      await context.route('https://arena.invalid/**', route => {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith('/index.html')) return route.fulfill({ contentType: 'text/html', body: '<h1>Wallet sign-in fixture</h1><button onclick="localStorage.setItem(\'fixture.fresh\',\'1\')">Finish sign-in</button>' });
        if (url.pathname.endsWith('/arena.html')) return route.fulfill({ contentType: 'text/html', body: '<meta charset="utf-8"><script src="/web/snapin/guide-copy.js"></script><script src="/web/snapin/panel.js"></script>' });
        const file = path.basename(url.pathname);
        if (['guide-copy.js', 'panel.js'].includes(file)) return route.fulfill({ contentType: 'application/javascript', body: read(file) });
        return route.fulfill({ status: 404, body: '' });
      });
      const page = await context.newPage();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto('https://arena.invalid/web/arena.html');
      await page.addStyleTag({ content: read('panel.css') });
      await page.evaluate(() => {
        localStorage.clear();
        localStorage.setItem('trenchie.snapin.v1', JSON.stringify({ name: 'Coral Scout', door: { route: 'plan', identity: 'Codex' }, planCode: 'fixture' }));
        window.success = 0;
        window.SnapIdentity = { leave: async () => {
          if (!localStorage.getItem('fixture.fresh')) throw new Error('sign in with your wallet first (the sign-in expired or is unknown)');
          success++; return new Promise(() => {});
        } };
        SnapPanel.state.codeLog = { joined: true, fighter_id: 'coral', life: 8, state: 'ring' }; SnapPanel.render();
      });
      const leave = page.locator('[data-pn="leave"]');
      await leave.click(); await page.waitForTimeout(600); await leave.click();
      const link = page.getByRole('link', { name: 'Sign in again' });
      assert.equal(await link.isVisible(), true);
      const popup = page.waitForEvent('popup'); await link.click(); const guide = await popup;
      await guide.waitForLoadState();
      assert.equal(new URL(guide.url()).searchParams.get('step'), 'wallet');
      await guide.getByRole('button', { name: 'Finish sign-in' }).click();
      await page.bringToFront();
      assert.match(page.url(), /arena.html$/);
      await leave.click(); await page.waitForTimeout(600); await leave.click();
      assert.equal(await page.evaluate(() => success), 1);
      assert.equal(await link.count(), 0);
      await guide.close();
      process.stdout.write('leave-signin browser: ' + width + ' recovery opens wallet and original panel retries\n');
    }
  } finally { await browser.close(); }
}
(async () => {
  if (!process.argv.includes('--identity-only')) await panelCase();
  await identityCase();
  if (!process.argv.includes('--markup-only') && !process.argv.includes('--identity-only')) await browserCase();
  process.stdout.write('leave-signin-case: PASS\n');
})().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
