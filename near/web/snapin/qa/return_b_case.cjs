// Approved B returning-owner flow. Wallet and chain replies are explicit local boundary fixtures.
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const { chromium } = require('playwright'), ROOT = require('./hosts.cjs').REPO;
const origin = 'http://127.0.0.1:18734', web = path.join(ROOT, 'near/web');
const meta = require('../premint/meta/options.json')['hunter-lunge'];
const sheet = JSON.parse(fs.readFileSync(path.join(web, 'snapin/premint', meta.file), 'utf8'));
const token = { token_id: 'hunter-lunge-08', preset_id: 'hunter-lunge', persona_digest: meta.digest };
const draft = { name: 'Pike Pennywhistle', preset: 'Hunter Lunge', step: 'wallet', fighterChosen: true,
  minted: { account: 'owner.near', token: token.token_id, digest: meta.digest, sheet }, sheet,
  wallet: { accountId: 'owner.near', chain: { owned: [token] } }, door: { route: 'plan', door: 'Codex', identity: 'Codex' } };
const mime = { '.js': 'text/javascript', '.mjs': 'text/javascript', '.html': 'text/html', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml', '.woff2': 'font/woff2' };

async function inspect(page, state, width) {
  await page.evaluate(() => document.fonts.ready);
  const screen = await page.evaluate(() => {
    const sign = document.querySelector('.return-sign'), primary = sign?.querySelector('.return-primary'), secondary = sign?.querySelector('.return-new'), note = sign?.querySelector('.return-note');
    const rect = el => el ? { x: el.getBoundingClientRect().x, y: el.getBoundingClientRect().y, width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height } : null;
    return { sign: !!sign, heading: sign?.querySelector('h1')?.textContent, text: document.querySelector('#app').innerText, primary: rect(primary), secondary: rect(secondary), note: rect(note), picture: rect(sign?.querySelector('.return-identity img')), centered: note && getComputedStyle(note).textAlign,
      gold: sign?.querySelectorAll('button.gold:not(:disabled)').length, portrait: sign?.querySelector('.return-identity img')?.getAttribute('src'),
      status: sign?.querySelector('.return-status')?.textContent || '', noteText: note?.textContent, pending: !!sign?.querySelector('.return-primary:disabled'), overflow: document.documentElement.scrollWidth > innerWidth };
  });
  assert.equal(screen.sign, true, width + '/' + state + ': approved return surface');
  assert.equal(screen.heading, ['wallet', 'waiting', 'cancelled'].includes(state) ? 'Your Trenchie' : 'Your fighter');
  assert.match(screen.text, /Pike Pennywhistle/);
  assert.doesNotMatch(screen.text, /DEV|hunter-lunge-08|no page was open|is out of the arena/);
  assert.match(screen.portrait, /avatar-1\.png/);
  assert.ok(screen.primary.y < screen.secondary.y, 'return primary comes first');
  assert.ok(screen.note.y >= screen.secondary.y + screen.secondary.height, 'note follows the secondary');
  assert.ok(screen.note.y - screen.secondary.y - screen.secondary.height <= 16, 'note sits directly under its button');
  assert.equal(screen.centered, 'center');
  assert.ok(Math.abs((screen.note.x + screen.note.width / 2) - (screen.secondary.x + screen.secondary.width / 2)) < 1);
  assert.ok(Math.abs((screen.picture.x + screen.picture.width / 2) - (screen.secondary.x + screen.secondary.width / 2)) < 1, 'B centers the portrait over the actions');
  assert.equal(screen.overflow, false);
  assert.equal(screen.gold, ['waiting', 'checking'].includes(state) ? 0 : 1);
  if (state === 'missing') {
    assert.equal(screen.status, 'Pike belongs to another wallet.');
    assert.equal(screen.noteText, 'Free while premints last.');
  } else assert.equal(screen.noteText, 'Pike stays yours. Free while premints last.');
  if (state === 'checking') { assert.equal(screen.status, ''); assert.equal(screen.pending, true); assert.equal((screen.text.match(/Checking…/g) || []).length, 1); }
  console.log(JSON.stringify({ width, state, gold: screen.gold, centered: screen.centered }));
  if (process.env.RETURN_B_ARTIFACTS) {
    fs.mkdirSync(process.env.RETURN_B_ARTIFACTS, { recursive: true });
    await page.screenshot({ path: path.join(process.env.RETURN_B_ARTIFACTS, state + '-' + width + '.png') });
  }
}

(async () => {
  let browser;
  try {
    browser = await chromium.launch({ args: ['--single-process', '--no-zygote', '--proxy-bypass-list=<-loopback>'], ...(process.env.HTTPS_PROXY ? { proxy: { server: process.env.HTTPS_PROXY } } : {}) });
    const context = await browser.newContext(), page = await context.newPage();
    page.setDefaultTimeout(10000);
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    let ownership = 'verified', release, waiting;
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) return route.abort();
      if (url.pathname === '/dev/health') return route.fulfill({ json: { chain_mode: { identity_network: 'mainnet' } } });
      if (url.pathname === '/room/observe') return route.fulfill({ json: { fighters: [] } });
      if (url.pathname === '/dev/identity') {
        const body = route.request().postDataJSON();
        if (body.op === 'inspect') {
          if (ownership === 'checking') await waiting;
          if (ownership === 'error') return route.fulfill({ status: 503, json: { error: 'Ownership read unavailable. Try again.' } });
          if (ownership === 'missing') return route.fulfill({ status: 403, json: { error: 'This token is owned by another.near, not by owner.near' } });
        }
        const reply = { challenge: { nonce: 'fixture-nonce', message: 'Fixture sign-in', recipient: origin }, signin: { signin: 'fixture-session', account_id: 'owner.near', trenchies: [token], offer: { kind: 'claim', held: 4 } }, inspect: token }[body.op];
        return route.fulfill({ json: reply || { error: 'Unexpected operation' } });
      }
      if (!url.pathname.startsWith('/web/')) return route.fulfill({ status: 404, json: { error: 'No fixture route' } });
      const file = path.resolve(web, decodeURIComponent(url.pathname.slice(5)));
      if (!file.startsWith(web + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return route.fulfill({ status: 404, body: '' });
      return route.fulfill({ contentType: mime[path.extname(file)] || 'application/octet-stream', body: fs.readFileSync(file) });
    });
    await page.addInitScript(draft => { localStorage.clear(); localStorage.setItem('trenchie.snapin.v1', JSON.stringify(draft)); }, draft);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto(origin + '/web/snapin/index.html?step=wallet');
      await page.waitForFunction(() => window.__SNAPIN_READY && SnapIdentity.state().modeKnown);
      await page.evaluate(() => {
        SnapWallet.connect = async () => new Promise(resolve => { window.fixtureWalletReply = resolve; });
        SnapWallet.signMessage = async () => ({ ok: true, accountId: 'owner.near', publicKey: 'fixture-key', signature: 'fixture-signature' });
      });
      await inspect(page, 'wallet', width);
      await page.click('[data-act="g:wallet:choose"]');
      await page.waitForFunction(() => !!window.fixtureWalletReply);
      await inspect(page, 'waiting', width);
      await page.evaluate(() => fixtureWalletReply({ ok: false, kind: 'cancelled', message: 'Sign-in cancelled' }));
      await page.waitForFunction(() => !Snapin.view.busy);
      await inspect(page, 'cancelled', width);
      ownership = 'checking'; waiting = new Promise(resolve => { release = resolve; });
      await page.click('[data-act="g:wallet:choose"]');
      await page.evaluate(() => fixtureWalletReply({ ok: true, accountId: 'owner.near', walletId: 'fixture' }));
      await page.waitForFunction(() => Snapin.view.returnState === 'checking');
      await inspect(page, 'checking', width);
      ownership = 'error'; release();
      await page.waitForFunction(() => Snapin.view.returnState === 'error');
      await inspect(page, 'error', width);
      await page.click('[data-act="g:step:wallet"]');
      assert.equal(await page.locator('.return-sign h1').innerText(), 'Your Trenchie', 'Back returns to the wallet card');
      ownership = 'missing'; await page.click('[data-act="g:return-retry"]');
      await page.waitForFunction(() => Snapin.view.returnState === 'missing');
      await inspect(page, 'missing', width);
      await page.click('[data-act="g:wallet:choose"]');
      await inspect(page, 'waiting', width);
      await page.evaluate(() => fixtureWalletReply({ ok: false, kind: 'cancelled', message: 'Sign-in cancelled' }));
      await page.waitForFunction(() => !Snapin.view.busy);
      await inspect(page, 'cancelled', width);
      ownership = 'verified';
      // A fresh wallet sign-in retries the owner read instead of carrying the missing verdict forward.
      await page.click('[data-act="g:wallet:choose"]');
      await page.evaluate(() => fixtureWalletReply({ ok: true, accountId: 'owner.near', walletId: 'fixture' }));
      await page.waitForFunction(() => Snapin.view.returnState === 'verified');
      await inspect(page, 'verified', width);
      await page.click('[data-act="g:use"]');
      await page.waitForFunction(() => Snapin.view.step === 'personality');
      assert.equal(await page.isDisabled('#name'), true, 'the existing minted personality stays fixed');
      await page.evaluate(() => { Snapin.view.step = 'presets'; Snapin.render(); });
      await page.click('[data-act="g:return-new"]');
      assert.equal(await page.evaluate(() => Snapin.state.newFighter), true);
      assert.equal(await page.evaluate(() => Snapin.state.wallet.accountId), 'owner.near');
      assert.equal(await page.locator('.return-sign').count(), 0, 'the new fighter flow has the preset choices');

      // The first wallet screen can start a new fighter without signing in or releasing the old seat.
      await page.goto(origin + '/web/snapin/index.html?step=wallet');
      await page.waitForFunction(() => window.__SNAPIN_READY && SnapIdentity.state().modeKnown);
      await page.evaluate(() => {
        window.fixtureLeaves = 0; SnapRoom.leave = async () => { window.fixtureLeaves++; };
        SnapUI.store.set('trenchie.snapin.cap', '0.2');
      });
      await page.click('[data-act="g:return-new"]');
      assert.deepEqual(await page.evaluate(() => ({ newFighter: Snapin.state.newFighter, wallet: Snapin.state.wallet,
        door: Snapin.state.door.door, cap: SnapUI.store.get('trenchie.snapin.cap'), leaves: window.fixtureLeaves })),
      { newFighter: true, wallet: null, door: 'Codex', cap: '0.2', leaves: 0 });

      // A reply for the old fighter must not overwrite a new draft chosen during the lookup.
      await page.goto(origin + '/web/snapin/index.html?step=wallet');
      await page.waitForFunction(() => window.__SNAPIN_READY && SnapIdentity.state().modeKnown);
      await page.evaluate(() => {
        SnapWallet.connect = async () => ({ ok: true, accountId: 'owner.near', walletId: 'fixture' });
        SnapWallet.signMessage = async () => ({ ok: true, accountId: 'owner.near', publicKey: 'fixture-key', signature: 'fixture-signature' });
      });
      ownership = 'checking'; waiting = new Promise(resolve => { release = resolve; });
      await page.click('[data-act="g:wallet:choose"]');
      await page.waitForFunction(() => Snapin.view.returnState === 'checking');
      await page.click('[data-act="g:return-new"]');
      const reply = page.waitForResponse(response => response.url().endsWith('/dev/identity') && response.request().postDataJSON().op === 'inspect');
      ownership = 'verified'; release(); await (await reply).finished(); await page.waitForTimeout(100);
      assert.equal(await page.evaluate(() => Snapin.state.newFighter), true);
      assert.equal(await page.evaluate(() => Snapin.state.minted || null), null);
      assert.equal(await page.locator('.return-sign').count(), 0);
    }
    assert.deepEqual(errors, []);
    console.log('return-b-case: approved return states and centered note at 1440/390; existing and new fighter paths work');
  } finally { if (browser) await browser.close(); }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
