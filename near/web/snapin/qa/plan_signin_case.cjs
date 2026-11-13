// A real guide/identity client signs in, then creates both agent-door codes with the same page-key authority.
// Wallet and chain replies are supplied; the case host verifies the real Ed25519 envelope. No actual wallet/chain calls.
// NODE_PATH=<Playwright modules> node near/web/snapin/qa/plan_signin_case.cjs; HOT_WALLET_PORT defaults to18733.
'use strict';
const assert = require('node:assert/strict'), crypto = require('node:crypto');
const { chromium } = require('playwright');
const HOSTS = require('./hosts.cjs');
const PREMINT = require('../premint/meta/options.json')['brawler-swing'];
const DEFAULTS = ['https://raw.githubusercontent.com/hot-dao/near-selector/refs/heads/main/repository/manifest.json', 'https://cdn.jsdelivr.net/gh/azbang/hot-connector/repository/manifest.json'];
(async () => {
  let browser, pageKey, claimCount = 0;
  const codes = [], used = new Set(), ops = [];
  function opened(op, env) {
    if (env.signin !== 'case-signed-in') return null;
    const raw = 'trenchie-desk|' + op + '|' + env.signin + '|' + env.at + '|' + crypto.createHash('sha256').update(env.payload).digest('hex');
    const pub = crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: pageKey }, format: 'jwk' });
    assert.ok(crypto.verify(null, Buffer.from(raw), pub, Buffer.from(env.sig, 'base64url')), 'signed by the page key from sign-in');
    assert.ok(Math.abs(Date.now() - Number(env.at)) < 60000); assert.ok(!used.has(env.sig)); used.add(env.sig);
    return JSON.parse(env.payload);
  }
  try {
    const web = await HOSTS.start(['near/web/snapin/serve.py', '--port', process.env.HOT_WALLET_PORT || '18733', '--arena', 'http://127.0.0.1:9'], (s) => (s.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
    const base = 'http://127.0.0.1:' + web.m, launch = { args: ['--single-process', '--no-zygote'] };
    if (process.env.HTTPS_PROXY) { launch.proxy = { server: process.env.HTTPS_PROXY }; launch.args.push('--proxy-bypass-list=<-loopback>'); }
    browser = await chromium.launch(launch);
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await context.route((u) => !['127.0.0.1', 'localhost'].includes(u.hostname), (r) => r.abort('namenotresolved'));
    for (const url of ['https://cloud-api.near.ai/v1/chat/completions', 'https://api.anthropic.com/v1/messages', 'https://openrouter.ai/api/v1/chat/completions']) {
      await context.route(url, (r) => r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*', 'access-control-allow-methods': 'POST, OPTIONS', 'access-control-allow-headers': '*' },
        body: JSON.stringify({ choices: [{ message: { content: 'Case AI answered.' } }], content: [{ type: 'text', text: 'Case AI answered.' }] }) }));
    }
    for (const url of DEFAULTS) await context.route(url, (r) => r.fulfill({ json: { version: '1', wallets: [{ id: 'hot-wallet', name: 'Case wallet', type: 'sandbox', icon: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg"/%3E', website: 'https://example.invalid', executor: 'https://example.invalid/wallet.js', features: { mainnet: true, signMessage: true }, permissions: {} }] } }));
    await context.route(base + '/dev/health', (r) => r.fulfill({ json: { chain_mode: { identity_network: 'mainnet', identity_nft: 'nft.trenchie-arena.near' } } }));
    await context.route(base + '/room/observe', (r) => r.fulfill({ json: { fighters: [] } }));
    await context.route(base + '/dev/identity', (r) => {
      const e = r.request().postDataJSON(); ops.push(e.op);
      if (e.op === 'challenge') { pageKey = e.page_key; return r.fulfill({ json: { message: 'Case mainnet sign-in', recipient: base, nonce: Buffer.alloc(32, 7).toString('base64url') } }); }
      if (e.op === 'signin') return r.fulfill({ json: { signin: 'case-signed-in', account_id: 'case-owner.near', trenchies: [], offer: { kind: 'claim', held: 1, cost_yocto: '0' } } });
      const payload = opened(e.op, e); assert.ok(payload);
      if (e.op === 'claim') { claimCount++; return r.fulfill({ json: { token_id: 'brawler-swing-case', account_id: 'case-owner.near', claim_tx: 'case-claim' } }); }
      assert.ok(['confirm', 'inspect'].includes(e.op)); assert.equal(payload.token_id, 'brawler-swing-case');
      return r.fulfill({ json: { token_id: payload.token_id, account_id: 'case-owner.near', persona_digest: PREMINT.digest, preset_id: 'brawler-swing' } });
    });
    await context.route(base + '/snap/code', (r) => {
      const e = r.request().postDataJSON(), payload = opened('code', e); codes.push({ env: e, payload });
      if (!payload) return r.fulfill({ status: 400, json: { error: 'sign in with your wallet first (the sign-in expired or is unknown)' } });
      assert.equal(payload.nft_token_id, 'brawler-swing-case'); assert.equal(payload.preset, 'brawler-swing');
      assert.ok(payload.sheet?.game?.name); assert.equal(payload.plan_stop_pct, 10);
      return r.fulfill({ json: { code: 'CASE-' + payload.agent, expires_at: Date.now() + 600000, snap_url: base + '/SNAP.md' } });
    });
    const p = await context.newPage();
    await p.goto(base + '/web/snapin/index.html?step=wallet');
    await p.waitForFunction(() => window.__SNAPIN_READY && window.SnapIdentity?.state().mode?.identity_network === 'mainnet');
    await p.evaluate(() => {
      const w = NearConnectLib.SandboxWallet.prototype;
      w.signIn = async () => [{ accountId: 'case-owner.near' }]; w.getAccounts = w.signIn;
      w.signMessage = async () => ({ accountId: 'case-owner.near', publicKey: 'case-public', signature: 'case-signature' });
    });
    await p.click('[data-act="g:wallet:choose"]'); await p.click('.connect-item[data-type="hot-wallet"]');
    await p.waitForFunction(() => Snapin.view.step === 'presets' && Snapin.state.wallet?.chain);
    assert.equal(await p.evaluate(() => SnapIdentity.state().signin), 'case-signed-in', 'wallet sign-in is live before the AI door');
    await p.click('[data-act="g:use"]');
    await p.waitForFunction(() => Snapin.view.step === 'personality' && SnapGuide.state.name.free === true);
    await p.click('[data-act="g:step:doors"]');
    for (const [door, agent, bin] of [['Codex', 'codex', 'codex'], ['Claude Code', 'claude-code', 'claude']]) {
      if (door !== 'Codex') await p.click('[data-act="g:other"]');
      await p.click('[data-act="g:door:plan:' + door + '"]');
      await p.waitForFunction(() => SnapGuide.state.code || SnapGuide.state.codeErr, null, { timeout: 15000 });
      const view = await p.evaluate(() => ({ error: SnapGuide.state.codeErr, command: document.querySelector('.cmd')?.textContent, disabled: document.querySelector('[data-act="g:copy"]')?.disabled }));
      assert.ok(view.command?.startsWith(bin + ' '), door + ': command available after wallet sign-in: ' + view.error);
      assert.equal(view.disabled, false, door + ': Copy enabled');
      assert.equal(codes.at(-1).payload.agent, agent);
      assert.equal(codes.filter((c) => c.payload?.agent === agent).length, 1, 'one authenticated request per door, no duplicate claim/code on entering');
    }
    assert.equal(claimCount, 1, 'both doors use the same owned token; no second mint/claim');
    assert.equal(ops.filter((op) => op === 'signin').length, 1, 'no second wallet sign-in needed');
    for (const door of ['NEAR AI Cloud', 'Claude', 'OpenRouter']) {
      await p.click('[data-act="g:other"]'); await p.click('[data-act="g:door:key:' + door + '"]');
      await p.fill('#key', 'case-supplied-not-a-real-key'); await p.click('[data-act="g:test"]');
      await p.waitForFunction(() => SnapGuide.state.keyStatus !== 'testing', null, { timeout: 15000 });
      assert.equal(await p.evaluate(() => SnapGuide.state.keyStatus), 'ok', door + ': its API key test answers after wallet sign-in');
      await p.click('[data-act="g:cap:0.20"]');
      assert.ok(await p.evaluate(() => SnapGuide.aiReady({ P: Snapin.state })), door + ': the AI is ready after setting a cap');
      assert.equal(await p.evaluate(() => SnapIdentity.state().signin), 'case-signed-in', 'the same wallet sign-in remains active');
    }
    console.log('plan-signin-case: all five AI doors work after sign-in; both plan commands/Copy enabled; one claim; three key tests/caps ready');
  } catch (e) { console.error(e.stack || e); process.exitCode = 1; }
  finally { if (browser) await browser.close(); assert.deepEqual(await HOSTS.finish(), []); }
})();
