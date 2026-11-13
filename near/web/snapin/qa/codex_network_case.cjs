// Actual guide Copy action, with a supplied pairing reply; no model session or screenshot.
'use strict';
const assert = require('node:assert/strict'), path = require('node:path');
const { chromium } = require('playwright');
const HOSTS = require(path.resolve('near/web/snapin/qa/hosts.cjs'));
const note = 'This lets Codex reach the internet so it can play. Run it in an empty folder.';
(async () => {
  let browser;
  try {
    const web = await HOSTS.start(['near/web/snapin/serve.py', '--port', process.env.HOT_WALLET_PORT || '18733', '--arena', 'http://127.0.0.1:9'], (s) => (s.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
    const base = 'http://127.0.0.1:' + web.m, launch = { args: ['--single-process', '--no-zygote'] };
    if (process.env.HTTPS_PROXY) { launch.proxy = { server: process.env.HTTPS_PROXY }; launch.args.push('--proxy-bypass-list=<-loopback>'); }
    browser = await chromium.launch(launch);
    const ctx = await browser.newContext(), p = await ctx.newPage();
    await ctx.route((u) => !['127.0.0.1', 'localhost'].includes(u.hostname), (r) => r.abort('namenotresolved'));
    await ctx.route(base + '/dev/health', (r) => r.fulfill({ json: {} }));
    await ctx.route(base + '/snap/code', (r) => r.fulfill({ json: { code: 'CASE-NETWORK', expires_at: Date.now() + 600000, snap_url: base + '/SNAP.md' } }));
    await ctx.route(base + '/snap/code/*', (r) => r.fulfill({ json: { joined: false } }));
    const prompt = '"Join Trenchie Arena. Read ' + base + '/SNAP.md and follow it. Code CASE-NETWORK, Trenchie Pebble."';
    for (const width of [390, 1440]) {
      await p.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await p.goto(base + '/web/snapin/index.html?step=wallet');
      await p.waitForFunction(() => window.__SNAPIN_READY);
      await p.evaluate(() => {
        Object.assign(Snapin.state, { wallet: { id: 'case', accountId: 'case.testnet', network: 'testnet' }, fighterChosen: true, name: 'Pebble', pick: null });
        SnapUI.copyText = async (text) => { window.copiedCommand = text; return true; };
      });
      await p.click('[data-act="g:step:doors"]');
      for (const [door, prefix] of [['Codex', 'codex -c sandbox_workspace_write.network_access=true '], ['Claude Code', 'claude ']]) {
        await p.click('[data-act="g:door:plan:' + door + '"]');
        await p.waitForFunction(() => !!SnapGuide.state.code);
        const command = prefix + prompt;
        assert.equal(await p.locator('.cmd').textContent(), command, door + ': displayed command');
        await p.click('[data-act="g:copy"]');
        assert.equal(await p.evaluate(() => window.copiedCommand), command, door + ': Copy sends exactly the displayed command');
        const pageText = await p.innerText('#app');
        assert.equal(pageText.includes(note), door === 'Codex', 'network explanation is Codex-only');
        assert.ok(!pageText.includes('Your own Codex session plays your Trenchie.'), 'removed Codex lead stays absent');
        const rect = await p.locator('.cmd').evaluate((el) => { const r = el.getBoundingClientRect(); return { x: r.x, right: r.right }; });
        assert.ok(rect.x >= 0 && rect.right <= width + 1, 'command remains within the existing panel');
        await p.click('[data-act="g:other"]');
      }
      console.log('PASS Codex network flag in displayed/copied command, plain note, unchanged Claude command at ' + width);
    }
    console.log('codex-network-case: actual Copy includes network access and preserves the join prompt');
  } catch (e) { console.error(e.stack || e); process.exitCode = 1; }
  finally { if (browser) await browser.close(); assert.deepEqual(await HOSTS.finish(), []); }
})();
