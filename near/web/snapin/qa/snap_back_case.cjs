// Returning expired seats use their saved AI door; they never start a browser fighter for a plan session.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/snap_back_case.cjs
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright'), HOSTS = require('./hosts.cjs');
const origin = 'http://127.0.0.1:18734';

async function ended(page, route, agreed) {
  await page.evaluate(async ({ route, agreed }) => {
    const options = await (await fetch('premint/meta/options.json')).json(), meta = options['hunter-lunge'];
    const sheet = await (await fetch('premint/' + meta.file)).json();
    Object.assign(Snapin.state, {
      name: meta.name, preset: 'Hunter Lunge', sheet, fighterChosen: true,
      wallet: { id: 'dev-throwaway', network: 'testnet', accountId: 'fixture' },
      door: { door: route === 'plan' ? 'Codex' : 'Claude', route, identity: route === 'plan' ? 'Codex' : 'Claude Console' },
      pick: null, planCode: route === 'plan' ? 'old-expired-code' : null, agreed,
      ended: { name: meta.name, why: 'no page was open to keep it', at: Date.now() }, fighter: null
    });
    Snapin.view.step = 'presets'; Snapin.view.msg = 'Checking hunter-lunge-08 is still yours…'; Snapin.view.msgErr = true;
    Snapin.render();
  }, { route, agreed });
}

async function buildNew(page) {
  await page.evaluate(() => {
    Snapin.state.door = { route: 'plan', door: 'Codex', identity: 'Codex' };
    SnapUI.store.set('trenchie.snapin.cap', '0.2'); Snapin.view.step = 'presets'; Snapin.render();
  });
  assert.equal(await page.locator('.return-sign').count(), 1, 'an owned fighter uses the approved return card');
  await page.click('[data-act="g:return-new"]');
  await page.click('[data-act="g:build"]');
  const fresh = await page.evaluate(() => ({ name: Snapin.state.name, wallet: Snapin.state.wallet.accountId,
    door: Snapin.state.door.door, cap: SnapUI.store.get('trenchie.snapin.cap'), newFighter: Snapin.state.newFighter }));
  assert.ok(['', 'Newcomer'].includes(fresh.name), 'a new draft has an empty or default name, never the old persona');
  delete fresh.name;
  assert.deepEqual(fresh, { wallet: 'player.near', door: 'Codex', cap: '0.2', newFighter: true });
  assert.equal(await page.isEnabled('#name'), true, 'a new draft can edit its own name');
  await page.fill('#name', 'Coral Piper');
  await page.waitForFunction(() => SnapGuide.state.name.free === true && SnapGuide.state.name.checked === 'Coral Piper');
  await page.click('[data-act="g:step:doors"]');
  await page.click('[data-act="g:door:plan:Codex"]');
  await page.waitForFunction(() => SnapGuide.state.code?.code === 'fresh-chain-code' && Snapin.state.wallet.chain.token === 'paid-new');
  const minted = await page.evaluate(() => ({ token: Snapin.state.minted.token, name: Snapin.state.minted.sheet.game.name,
    newFighter: Snapin.state.newFighter, walletMints: window.fixtureWalletMints }));
  assert.deepEqual(minted, { token: 'paid-new', name: 'Coral Piper', newFighter: false, walletMints: 1 });
}

async function claimAnother(page) {
  await page.evaluate(() => {
    const offer = { kind: 'claim', held: 2, cost_yocto: '0' };
    SnapIdentity.state().offer = offer; Snapin.state.wallet.chain.offer = offer;
    Snapin.view.step = 'presets'; Snapin.view.flash = ''; Snapin.render();
  });
  assert.doesNotMatch(await page.innerText('body'), /one per wallet/i);
  assert.equal(await page.locator('.return-sign').count(), 1);
  await page.click('[data-act="g:return-new"]');
  await page.click('[data-act="g:preset:Survivor Beam"]');
  await page.click('[data-act="g:use"]');
  await page.waitForFunction(() => Snapin.view.step === 'personality' && SnapGuide.state.name.free === true);
  await page.click('[data-act="g:step:doors"]');
  await page.click('[data-act="g:door:plan:Codex"]');
  await page.waitForFunction(() => Snapin.state.wallet.chain.token === 'survivor-beam-01' && !!SnapGuide.state.code);
  assert.equal(await page.evaluate(() => window.fixtureWalletMints), 0, 'another held premint needs no paid wallet mint');
  assert.equal(await page.evaluate(() => Snapin.state.newFighter), false);
}

(async () => {
  let browser;
  const failures = [];
  try {
    await HOSTS.start(['near/web/snapin/qa/corner_life_host.py'], out => out.includes('corner-life-host:'), HOSTS.REPO);
    browser = await chromium.launch({ args: ['--single-process', '--no-zygote', '--proxy-bypass-list=<-loopback>'],
      ...(process.env.HTTPS_PROXY ? { proxy: { server: process.env.HTTPS_PROXY } } : {}) });
    const context = await browser.newContext();
    await context.route(url => !['127.0.0.1', 'localhost'].includes(url.hostname), route => route.abort());
    await context.route(origin + '/web/arena.html*', route => route.fulfill({ contentType: 'text/html', body: '<p>Joined the arena</p>' }));
    const page = await context.newPage(), errors = [];
    page.setDefaultTimeout(15000);
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin + '/web/snapin/index.html?step=wallet');
    for (const width of process.env.SNAP_BACK_ONLY ? [] : [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      if (width === 390) await page.evaluate(() => localStorage.clear());
      let registrations = 0;
      const count = request => { if (request.method() === 'POST' && new URL(request.url()).pathname === '/dev/identity') registrations++; };
      page.on('request', count);
      await page.goto(origin + '/web/snapin/index.html?step=wallet');
      await page.waitForFunction(() => window.__SNAPIN_READY && SnapIdentity.state().modeKnown);
      await ended(page, 'plan', false);
      await page.click('[data-act="rejoin"]');
      await page.waitForTimeout(1000);
      const plan = await page.evaluate(() => ({ step: Snapin.view.step, pick: Snapin.state.pick,
        feedback: document.querySelector('#feedback')?.textContent, code: !!SnapGuide.state.code, error: SnapGuide.state.codeErr }));
      console.log(JSON.stringify({ width, plan, registrations }));
      if (plan.step !== 'doors' || plan.pick?.door !== 'Codex' || registrations !== 0) failures.push(width + ': ended Codex seat must return to its own door without a browser registration');
      if (/Checking/.test(plan.feedback || '') || (!plan.code && !plan.error)) failures.push(width + ': the request must settle with a new code or an explanation');
      if (await page.evaluate(() => SnapRoom.status().phase === 'in')) await page.evaluate(() => SnapRoom.leave());
      page.off('request', count);

      // A browser fighter with consent already saved really joins the DEV ring, using the real room protocol.
      const p = page;
      await page.evaluate(() => localStorage.clear());
      await p.goto(origin + '/web/snapin/index.html?step=wallet');
      await p.waitForFunction(() => window.__SNAPIN_READY && SnapIdentity.state().modeKnown);
      await ended(p, 'key', true);
      const browserName = width === 1440 ? 'Pike Pennywhistle' : 'Coral Scout';
      await p.evaluate(name => { Snapin.state.name = name; Snapin.state.ended.name = name; Snapin.render(); }, browserName);
      await p.click('[data-act="rejoin"]');
      await p.waitForURL('**/web/arena.html?follow=*');
      const joined = await p.evaluate(async name => (await (await fetch('/room/observe')).json()).fighters.some(f => f.public_name.includes(name)), browserName);
      assert.equal(joined, true, 'browser rejoin reaches the real DEV ring');
      // Leave while its key/session is still on the guide, before closing the browser context.
      if (new URL(p.url()).pathname !== '/web/arena.html') await p.evaluate(() => SnapRoom.leave());
      else { await p.goto(origin + '/web/snapin/index.html?step=ring'); await p.waitForFunction(() => window.__SNAPIN_READY && SnapRoom.status().phase === 'in'); await p.evaluate(() => SnapRoom.leave()); }
      assert.deepEqual(errors, []);
    }
    // The chain boundary is a local fixture: real page-key creation/signing, with controlled ownership replies.
    // In particular, a stalled confirmation must release the page for retry instead of saying Checking forever.
    await page.evaluate(() => localStorage.clear());
    const token = { token_id: 'hunter-lunge-08', preset_id: 'hunter-lunge', persona_digest:
      require('../premint/meta/options.json')['hunter-lunge'].digest };
    let confirmation = 'stalled', confirms = 0, permits = 0, claims = 0;
    await page.route('**/dev/health', route => route.fulfill({ json: { chain_mode: { identity_network: 'mainnet' } } }));
    await page.route('**/dev/identity', route => {
      const body = route.request().postDataJSON();
      const payload = body.payload ? JSON.parse(body.payload) : {};
      if (body.op === 'permit') { permits++; assert.equal(payload.sheet.game.name, 'Coral Piper'); }
      if (body.op === 'claim') { claims++; assert.equal(payload.preset, 'survivor-beam'); }
      if (body.op === 'confirm') {
        confirms++;
        if (confirmation === 'stalled') return;
        if (confirmation === 'refused') return route.fulfill({ status: 503, json: { error: 'Ownership read unavailable. Try again.' } });
      }
      const reply = {
        challenge: { nonce: 'fixture-nonce', message: 'Fixture sign-in', recipient: origin },
        signin: { signin: 'fixture-signin', account_id: 'player.near', trenchies: [token] },
        inspect: token, confirm: payload.token_id === 'paid-new' ? { token_id: 'paid-new' } : token,
        claim: { token_id: 'survivor-beam-01', claim_tx: 'fixture-claim' },
        permit: { token_id: 'paid-new', contract_id: 'nft.fixture.near', method: 'paid_mint', args: { fixture: true }, deposit_yocto: '10000000000000000000000', tgas: 50 }
      }[body.op];
      return route.fulfill({ json: reply || { error: 'Unexpected identity operation: ' + body.op } });
    });
    await page.route('**/snap/code', route => route.fulfill({ json: { code: 'fresh-chain-code', expires_at: Date.now() + 120000 } }));
    await page.goto(origin + '/web/snapin/index.html?step=wallet');
    await page.waitForFunction(() => window.__SNAPIN_READY && SnapIdentity.state().modeKnown);
    await page.evaluate(() => {
      SnapWallet.connect = async () => ({ ok: true, accountId: 'player.near', walletId: 'fixture' });
      SnapWallet.signMessage = async () => ({ ok: true, accountId: 'player.near', publicKey: 'fixture-public', signature: 'fixture-signature' });
      window.fixtureWalletMints = 0;
      SnapWallet.callContract = async () => { window.fixtureWalletMints++; return { ok: true, txHash: 'fixture-mint' }; };
    });
    await page.click('[data-act="g:wallet:choose"]');
    await page.waitForFunction(() => Snapin.view.step === 'presets' && !!Snapin.state.wallet?.chain);
    if (process.env.SNAP_BACK_ONLY === 'build') {
      confirmation = 'ok';
      await claimAnother(page); assert.equal(claims, 1);
      await buildNew(page); assert.equal(permits, 1);
      console.log('snap-back build: owned fighter starts an explicit paid-mint draft and keeps wallet, AI door and cap');
      return;
    }
    await page.evaluate(() => {
      Object.assign(Snapin.state, { door: { route: 'plan', door: 'Codex', identity: 'Codex' }, planCode: 'old-code',
        ended: { name: 'Pike Pennywhistle', why: 'no page was open to keep it', at: Date.now() } });
      Snapin.view.msgErr = true; Snapin.render();
    });
    assert.doesNotMatch(await page.innerText('body'), /DEV Pike/, 'chain return banner must use the minted name');
    assert.equal(await page.locator('.return-sign').count(), 1, 'expired chain fighter uses B, not the legacy banner');
    assert.equal(await page.locator('[data-act="rejoin"]').count(), 0, 'B replaces the legacy rejoin link');
    await page.clock.install();
    await page.click('[data-act="g:use"]');
    await page.waitForFunction(() => ['doors', 'personality'].includes(Snapin.view.step));
    assert.equal(await page.evaluate(() => Snapin.view.step), 'doors', 'Continue with an expired plan seat re-pairs its saved AI door');
    assert.equal(await page.evaluate(() => Snapin.state.planCode), null, 'the old pairing cannot be reused');
    assert.equal(await page.evaluate(() => Snapin.state.pick.door), 'Codex');
    assert.doesNotMatch(await page.innerText('body'), /DEV Pike/, 'legacy guide banners must also omit DEV on a chain host');
    await page.waitForFunction(() => document.querySelector('#feedback')?.textContent.includes('Checking'));
    assert.equal(await page.locator('#feedback').evaluate(el => el.classList.contains('bad')), false, 'progress clears the previous error colour');
    await page.waitForFunction(() => SnapGuide.state.requesting);
    for (let attempt = 0; confirms < 1 && attempt < 100; attempt++) await page.waitForTimeout(20);
    assert.equal(confirms, 1, 'the first ownership confirmation reached its stalled fixture');
    await page.clock.runFor(15100);
    await page.waitForTimeout(100);
    assert.equal(await page.evaluate(() => SnapGuide.state.requesting), false, 'ownership check must stop after its 15-second deadline');
    assert.match(await page.innerText('body'), /ownership check took too long/i);
    assert.doesNotMatch(await page.innerText('body'), /DEV Pike/);
    assert.doesNotMatch(await page.locator('#feedback').innerText(), /Checking/);
    await page.clock.resume();
    confirmation = 'refused';
    await page.click('[data-act="g:newcode"]');
    await page.waitForFunction(() => !SnapGuide.state.requesting && SnapGuide.state.codeErr.includes('Ownership read unavailable'));
    confirmation = 'ok';
    await page.click('[data-act="g:newcode"]');
    await page.waitForFunction(() => SnapGuide.state.code?.code === 'fresh-chain-code');
    assert.doesNotMatch(await page.locator('#feedback').innerText(), /Checking/);
    await claimAnother(page); assert.equal(claims, 1);
    await buildNew(page); assert.equal(permits, 1);
    // A successful new pairing clears the old ended/left flags, so Snap in can reach the arena.
    await page.route('**/snap/code/fresh-chain-code', route => route.fulfill({ json: { joined: true } }));
    await page.evaluate(() => { Snapin.state.ended = { name: Snapin.state.name, why: 'expired' }; Snapin.state.left = Date.now(); });
    await page.waitForFunction(() => SnapGuide.state.joinedFor === 'Codex');
    assert.equal(await page.evaluate(() => Snapin.state.ended), null);
    assert.equal(await page.evaluate(() => Snapin.state.left), 0);
    await page.click('[data-act="g:step:agree"]');
    await page.waitForFunction(() => !!Snapin.view.terms?.version);
    await page.click('[data-act="g:snap"]');
    await page.waitForURL('**/web/arena.html');
    assert.deepEqual(errors, []);
    assert.deepEqual(failures, []);
    console.log('snap-back-case: plan re-pairing, real DEV browser rejoin at 1440/390, bounded ownership retry, second free claim and custom paid mint');
  } finally {
    if (browser) await browser.close();
    assert.deepEqual(await HOSTS.finish(), []);
  }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
