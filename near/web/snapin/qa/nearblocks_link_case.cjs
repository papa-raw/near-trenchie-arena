// Gear links use the host's minted player identity and identity network, including hybrid mainnet/testnet hosts.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/nearblocks_link_case.cjs
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ROOT = path.resolve(__dirname, '../..');
const ORIGIN = 'https://arena.invalid';
const TOKEN = 'coral/reef #1?'; // path delimiters must stay inside the token id
const items = ['head', 'body', 'weapon', 'trinket'].map(slot => ({ slot, item_id: slot, name: 'Coral ' + slot }));
const HTML = '<meta charset="utf-8"><style>body{margin:0}</style><link rel="stylesheet" href="/snapin/panel.css"><script src="/snapin/guide-copy.js"></script><script src="/snapin/identity.js"></script><script src="/snapin/panel.js"></script>';
let fixture;
(async () => {
  let browser;
  try {
    const options = { args: ['--single-process', '--no-zygote'] };
    if (process.env.HTTPS_PROXY) options.proxy = { server: process.env.HTTPS_PROXY };
    browser = await require('playwright').chromium.launch(options);
    const context = await browser.newContext(), page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== ORIGIN) return route.fulfill({ contentType: 'text/html', body: '<title>Explorer destination fixture</title>' });
      const json = body => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
      if (url.pathname === '/dev/health') {
        fixture.healthReads++;
        if (fixture.retryHealth && fixture.healthReads === 1) return route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"temporarily unavailable"}' });
        return json(fixture.health);
      }
      if (url.pathname === '/dev/players') return json(fixture.players);
      if (url.pathname === '/dev/corner') return json({ fighter_id: fixture.id, hp: 80, max_hp: 100,
        bench: { down: fixture.bench, held: fixture.bench, next_life: 2, equipped: items, bag: [] }, events: [] });
      if (url.pathname.startsWith('/snap/code/')) return json({ joined: true, state: 'ring', fighter_id: fixture.id, life: 2 });
      if (url.pathname === '/case') return route.fulfill({ contentType: 'text/html', body: HTML });
      const file = path.resolve(ROOT, '.' + url.pathname);
      if (!file.startsWith(ROOT + path.sep) || !fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
      return route.fulfill({ contentType: path.extname(file) === '.css' ? 'text/css' : 'application/javascript', body: fs.readFileSync(file) });
    });
    await page.addInitScript(() => {
      localStorage.clear();
      window.SnapRoom = { status: () => ({ phase: 'in', fighter: { id: window.caseId, name: 'Coral Scout', lives: 2 } }), on() {}, leave() {} };
    });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      for (const scenario of ['mainnet', 'testnet', 'plan-bench', 'retry-health', 'house', 'unminted', 'dev']) {
        const testnet = scenario === 'testnet', plan = scenario === 'plan-bench';
        const network = testnet ? 'testnet' : 'mainnet';
        const contract = testnet ? 'identity.coral.testnet' : 'identity.coral.near';
        fixture = { healthReads: 0, retryHealth: scenario === 'retry-health', id: scenario === 'house' ? 'house-coral' : TOKEN, bench: plan,
          health: scenario === 'dev' ? { dev: true } : { dev: true, chain_mode: { network: 'testnet', identity_network: network, identity_nft: contract, nft: 'inventory.coral.testnet' } },
          players: scenario === 'house' || scenario === 'unminted' ? [] : [{ fighter_id: TOKEN, label: network.toUpperCase() }] };
        await page.goto(ORIGIN + '/case');
        await page.evaluate(({ id, plan }) => {
          window.caseId = id;
          localStorage.setItem('trenchie.snapin.v1', JSON.stringify({ name: 'Coral Scout', preset: 'Hunter Lunge',
            door: plan ? { route: 'plan', identity: 'Codex' } : { route: 'key', door: 'NEAR AI Cloud' }, planCode: plan ? 'fixture' : undefined }));
          SnapPanel.start();
        }, { id: fixture.id, plan });
        await page.locator('#pn-tab-gear').click();
        await page.waitForFunction(() => document.querySelector('#pn-gear .gi, #pn-gear .slot'));
        const link = page.locator('#pn-gear a[aria-label="NearBlocks"]');
        if (['house', 'unminted', 'dev'].includes(scenario)) {
          await page.waitForTimeout(150);
          assert.equal(await link.count(), 0, width + '/' + scenario + ': no identity link');
        } else {
          try { await link.waitFor({ state: 'visible', timeout: 3000 }); }
          catch (error) {
            const state = await page.evaluate(() => ({ modeKnown: SnapIdentity.state().modeKnown, explorerFor: SnapPanel.state.explorerFor }));
            throw new Error(width + '/' + scenario + ': ' + JSON.stringify({ healthReads: fixture.healthReads, ...state }) + '\n' + error.message);
          }
          assert.equal(await link.getAttribute('href'), 'https://' + (testnet ? 'testnet.' : '') + 'nearblocks.io/nft-token/' + contract + '/' + encodeURIComponent(TOKEN));
          assert.equal(await link.getAttribute('target'), '_blank');
          assert.equal(await link.getAttribute('title'), 'NearBlocks');
          assert.equal(await link.innerText(), '', 'icon has no visible text');
          assert.equal(await link.locator('svg').count(), 1);
          assert.ok((await link.getAttribute('rel')).split(/\s+/).includes('noopener'));
          await link.scrollIntoViewIfNeeded();
          assert.equal(await link.evaluate(el => {
            const r = el.getBoundingClientRect(), pane = el.closest('#pn-gear').getBoundingClientRect();
            const gear = el.closest('#pn-gear').querySelector('.benchb, .gearrow').getBoundingClientRect();
            return r.left >= pane.left && r.right <= pane.right + 1 && r.bottom <= gear.top + 1 && r.bottom <= innerHeight && r.width > 0;
          }), true, width + '/' + scenario + ': icon fits above gear');
          const popup = page.waitForEvent('popup');
          await link.click();
          const opened = await popup;
          await opened.waitForLoadState();
          assert.equal(opened.url(), await link.getAttribute('href'), 'native click opens the token URL');
          await opened.close();
        }
        if (scenario === 'mainnet' && process.env.NEARBLOCKS_CASE_EVIDENCE) {
          fs.mkdirSync(process.env.NEARBLOCKS_CASE_EVIDENCE, { recursive: true });
          await page.screenshot({ path: path.join(process.env.NEARBLOCKS_CASE_EVIDENCE, width + '.png') });
        }
        process.stdout.write('nearblocks-link ' + width + '/' + scenario + ': PASS\n');
      }
    }
    assert.deepEqual(errors, [], 'no browser errors');
  } finally { if (browser) await browser.close(); }
})().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
