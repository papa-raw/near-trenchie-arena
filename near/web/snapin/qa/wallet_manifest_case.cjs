// Stock NEAR Connect chooser through the real guide and vendored SDK. The upstream manifest and wallet replies are
// case-supplied: no provider, real wallet, signature or chain is contacted. This replaces the retired shortlist probes.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/wallet_manifest_case.cjs
// The host uses HOT_WALLET_PORT (default 18733); proxied lanes need that loopback port granted.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const { chromium } = require('playwright');
const HOSTS = require('./hosts.cjs');
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
const OUT = process.env.HOT_WALLET_EVIDENCE || fs.mkdtempSync(path.join(os.tmpdir(), 'stock-wallet-'));
fs.mkdirSync(OUT, { recursive: true });
const DEFAULTS = ['https://raw.githubusercontent.com/hot-dao/near-selector/refs/heads/main/repository/manifest.json', 'https://cdn.jsdelivr.net/gh/azbang/hot-connector/repository/manifest.json'];
const ICON = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><circle cx="12" cy="12" r="10" fill="#9FDCC5"/></svg>');
const ENTRIES = [['hot-wallet', 'HOT Wallet'], ['near-mobile', 'NEAR Mobile'], ['meteor-wallet', 'Meteor Wallet'], ['intear-wallet', 'Intear Wallet'], ['nightly-wallet', 'Nightly Wallet'], ['ethereum-wallets', 'Ethereum Wallets'], ['sweat-wallet', 'Sweat Wallet']];
const MANIFEST = { version: '1.1.0', wallets: ENTRIES.map(([id, name]) => ({
  id, name, icon: ICON, website: 'https://example.invalid/', version: '1', type: 'sandbox', executor: 'https://example.invalid/' + id + '.js',
  features: { mainnet: true, testnet: true, signInWithoutAddKey: true, signMessage: true }, permissions: {},
})) };
(async () => {
  let browser;
  const requests = [], signatures = [], errors = [];
  try {
    const web = await HOSTS.start(['near/web/snapin/serve.py', '--port', process.env.HOT_WALLET_PORT || '18733', '--arena', 'http://127.0.0.1:9'],
      (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1], REPO);
    const base = 'http://127.0.0.1:' + web.m;
    const launch = { args: ['--single-process', '--no-zygote'] };
    if (process.env.HTTPS_PROXY) { launch.proxy = { server: process.env.HTTPS_PROXY }; launch.args.push('--proxy-bypass-list=<-loopback>'); }
    browser = await chromium.launch(launch);
    const context = await browser.newContext();
    context.on('request', (r) => requests.push(r.url()));
    await context.route((u) => !['127.0.0.1', 'localhost'].includes(u.hostname), (r) => r.abort('namenotresolved'));
    for (const url of DEFAULTS) await context.route(url, (r) => r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify(MANIFEST) }));
    await context.route(base + '/dev/health', (r) => r.fulfill({ json: { chain_mode: { identity_network: 'mainnet', identity_nft: 'nft.trenchie-arena.near' } } }));
    await context.route(base + '/dev/identity', async (r) => {
      const body = r.request().postDataJSON();
      if (body.op === 'challenge') return r.fulfill({ json: { message: 'Sign in for the wallet case', recipient: base, nonce: Buffer.alloc(32, 7).toString('base64url') } });
      assert.equal(body.op, 'signin'); signatures.push(body);
      return r.fulfill({ json: { signin: 'case-signin', account_id: 'selector-case.near', trenchies: [], offer: { kind: 'claim', held: 1, cost_yocto: '0' } } });
    });
    const page = await context.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    for (const width of [390, 1440]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto(base + '/web/snapin/index.html?step=wallet');
      await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); }); await page.reload();
      await page.waitForFunction(() => window.__SNAPIN_READY && window.SnapIdentity?.state().mode?.identity_network === 'mainnet', null, { timeout: 30000 });
      assert.equal(await page.locator('[data-act="g:wallet:choose"]').count(), 1, 'one Connect wallet action opens the stock chooser');
      assert.equal(await page.locator('[data-act="g:wallet:dev-throwaway"]').count(), 0, 'a chain sign-in has no DEV wallet');
      await page.screenshot({ path: path.join(OUT, 'wallet-' + width + '.png') });
      // Keep the genuine connector's manifest load, registration and popup. Only the chosen wallet's remote replies are
      // supplied here; this is an adapter check, not a claim that a real wallet signed a mainnet challenge.
      await page.evaluate(() => {
        window.__walletCalls = [];
        const wallet = NearConnectLib.SandboxWallet.prototype;
        wallet.signIn = async function (o) { window.__walletCalls.push({ method: 'signIn', id: this.manifest.id, network: o.network }); return [{ accountId: 'selector-case.near' }]; };
        wallet.getAccounts = async function () { return [{ accountId: 'selector-case.near' }]; };
        wallet.signMessage = async function (o) { window.__walletCalls.push({ method: 'signMessage', id: this.manifest.id, network: o.network, message: o.message, recipient: o.recipient, nonce: Array.from(o.nonce) }); return { accountId: 'selector-case.near', publicKey: 'case-public-key', signature: 'case-signature' }; };
      });
      await page.click('[data-act="g:wallet:choose"]');
      await page.waitForSelector('.hot-connector-popup .connect-item', { timeout: 15000 });
      await page.waitForFunction(() => {
        const el = document.querySelector('.hot-connector-popup .modal-container');
        return el && getComputedStyle(el).position === 'fixed' && Number(getComputedStyle(el).opacity) >= 0.99;
      }, null, { timeout: 5000 });
      const ids = await page.locator('.hot-connector-popup .connect-item').evaluateAll((els) => els.map((el) => el.dataset.type));
      assert.deepEqual(ids.sort(), ENTRIES.map(([id]) => id).sort(), 'the stock popup shows the complete supplied list, including HOT, NEAR Mobile and Sweat');
      const box = await page.locator('.hot-connector-popup .modal-content').boundingBox();
      assert.ok(box.x >= -1 && box.x + box.width <= width + 1, 'the stock chooser fits the viewport');
      assert.ok(box.y >= -1 && box.y + box.height <= (width === 390 ? 844 : 900) + 1, 'the chooser is in view');
      const hot = await page.locator('.hot-connector-popup .connect-item[data-type="hot-wallet"]').boundingBox();
      assert.ok(await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.closest('.connect-item')?.dataset.type === 'hot-wallet',
        { x: hot.x + hot.width / 2, y: hot.y + hot.height / 2 }), 'HOT is the visible click target, above the guide');
      await page.screenshot({ path: path.join(OUT, 'chooser-' + width + '.png') });
      await page.click('.hot-connector-popup .connect-item[data-type="hot-wallet"]');
      await page.waitForFunction(() => window.Snapin.state.wallet?.chain && window.Snapin.view.step === 'presets', null, { timeout: 15000 });
      const result = await page.evaluate(() => ({ wallet: Snapin.state.wallet, calls: window.__walletCalls }));
      assert.equal(result.wallet.id, 'hot-wallet');
      assert.equal(result.wallet.network, 'mainnet');
      const signed = result.calls.find((c) => c.method === 'signMessage');
      assert.ok(signed, 'the existing mainnet NEP-413 path runs after selection');
      assert.equal(signed.network, 'mainnet'); assert.equal(signed.message, 'Sign in for the wallet case');
      assert.equal(signed.recipient, base); assert.deepEqual(signed.nonce, Array(32).fill(7));
      assert.equal(signatures.at(-1).public_key, 'case-public-key'); assert.equal(signatures.at(-1).signature, 'case-signature');
      console.log('PASS stock chooser and mainnet NEP-413 adapter at ' + width);
    }
    assert.ok(requests.some((u) => DEFAULTS.includes(u)), 'the SDK requests its own default manifest');
    assert.ok(!requests.some((u) => /wallets-manifest\.json/.test(u)), 'there is no local shortlist manifest request');
    assert.ok(!requests.some((u) => u.startsWith('https://example.invalid/')), 'no remote wallet code runs in this case');
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(OUT, 'requests.json'), JSON.stringify(requests, null, 2));
    console.log('wallet-manifest-case: full stock list loads; mainnet sign-in adapter preserved');
  } catch (e) {
    console.error(e.stack || e); process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    assert.deepEqual(await HOSTS.finish(), [], 'no test host survives');
  }
})();
