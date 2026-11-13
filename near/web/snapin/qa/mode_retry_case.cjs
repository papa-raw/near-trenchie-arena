// A failed initial health read must recover the real wallet step without reloading.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/mode_retry_case.cjs
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright'), HOSTS = require('./hosts.cjs');

(async () => {
  let browser;
  try {
    await HOSTS.start(['near/web/snapin/serve.py', '--port', '18734', '--arena', 'http://127.0.0.1:9'],
      out => out.includes('http://127.0.0.1:18734/'));
    browser = await chromium.launch(process.env.HTTPS_PROXY ? {
      args: ['--single-process', '--no-zygote', '--proxy-bypass-list=<-loopback>'],
      proxy: { server: process.env.HTTPS_PROXY }
    } : {});
    const context = await browser.newContext();
    await context.route(url => url.hostname !== '127.0.0.1', route => route.abort());
    for (const width of [1440, 390]) for (const mode of ['chain', 'dev']) {
      const page = await context.newPage(), calls = [], errors = [];
      let release, documents = 0;
      const gate = new Promise(resolve => { release = resolve; });
      page.on('pageerror', error => errors.push(error.message));
      page.on('request', request => { if (request.isNavigationRequest()) documents++; });
      await page.addInitScript(() => localStorage.clear());
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.route('**/dev/health', async route => {
        calls.push(Date.now());
        if (calls.length === 1) return route.fulfill({ status: 503, json: { error: 'fixture restarting' } });
        await gate;
        return route.fulfill({ json: mode === 'chain' ? {
          chain_mode: { identity_network: 'mainnet', identity_nft: 'nft.trenchie-arena.near' }
        } : { dev: true } });
      });
      await page.goto('http://127.0.0.1:18734/web/snapin/index.html?step=wallet', { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => window.__SNAPIN_READY);
      const button = page.locator('[data-act="g:wallet:choose"]');
      // Wait beyond the first one-second retry, so the baseline proves it never makes another request.
      for (let n = 0; n < 25 && calls.length < 2; n++) await new Promise(resolve => setTimeout(resolve, 100));
      const waiting = { attempts: calls.length, label: await button.innerText(), disabled: await button.isDisabled(),
        throwaway: await page.locator('[data-act="g:wallet:dev-throwaway"]').count() };
      console.log(JSON.stringify({ width, mode, waiting }));
      assert.equal(waiting.attempts, 2, '503 must schedule a second health read without reload');
      assert.match(waiting.label, /Retrying…/, 'the waiting wallet explains that it is retrying');
      assert.equal(waiting.disabled, true);
      assert.equal(waiting.throwaway, 0);
      assert.ok(calls[1] - calls[0] >= 900, 'failed health reads must back off rather than spin');
      const response = page.waitForResponse(r => new URL(r.url()).pathname === '/dev/health');
      release(); await (await response).finished();
      await page.waitForFunction(() => SnapIdentity.state().modeKnown &&
        !document.querySelector('[data-act="g:wallet:choose"]').disabled);
      assert.equal(await page.locator('[data-act="g:wallet:dev-throwaway"]').count(), mode === 'dev' ? 1 : 0);
      assert.match(await button.innerText(), mode === 'chain' ? /MAINNET/ : /TESTNET/);
      assert.doesNotMatch(await button.innerText(), /Retrying|Loading/);
      assert.equal(documents, 1, 'recovery must use the existing document');
      assert.deepEqual(errors, []);
      console.log(JSON.stringify({ width, mode, recovered: true, documents, retryMs: calls[1] - calls[0] }));
      await page.close();
    }
    // Advance browser time through a hung read and repeated failures to cover the capped,
    // continuing backoff without making a reviewer wait more than a minute for this case.
    const page = await context.newPage();
    await page.clock.install();
    await page.addInitScript(() => {
      localStorage.clear(); window.healthReads = [];
      const fetch = window.fetch;
      window.fetch = function (...args) {
        if (args[0] === '/dev/health') window.healthReads.push(Date.now());
        return fetch.apply(this, args);
      };
    });
    let attempts = 0;
    await page.route('**/dev/health', route => {
      attempts++;
      if (attempts === 1) return; // Leave this request pending until the real AbortController fires.
      return route.fulfill(attempts < 8 ? { status: 503, json: { error: 'fixture restarting' } } : {
        json: { chain_mode: { identity_network: 'mainnet' } }
      });
    });
    await page.goto('http://127.0.0.1:18734/web/snapin/index.html?step=wallet', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => window.__SNAPIN_READY && healthReads.length === 1);
    await page.clock.runFor(10050);
    await page.waitForFunction(() => document.querySelector('[data-act="g:wallet:choose"]').textContent.includes('Retrying…'));
    for (const [index, delay] of [1000, 2000, 4000, 8000, 15000, 15000, 15000].entries()) {
      await page.clock.runFor(delay + 100);
      await page.waitForFunction(count => healthReads.length === count, index + 2);
      await page.waitForTimeout(50); // Let the real fetch response settle before advancing the next browser timer.
    }
    await page.waitForFunction(() => SnapIdentity.state().modeKnown &&
      !document.querySelector('[data-act="g:wallet:choose"]').disabled);
    const reads = await page.evaluate(() => healthReads), gaps = reads.slice(1).map((time, i) => time - reads[i]);
    for (const [i, expected] of [11000, 2000, 4000, 8000, 15000, 15000, 15000].entries()) {
      assert.ok(Math.abs(gaps[i] - expected) < 500, 'health retry interval ' + i + ': ' + gaps[i]);
    }
    console.log(JSON.stringify({ stalledReadRecovered: true, attempts, backoffMs: gaps }));
    await page.close();
    console.log('mode-retry-case: 503 then 200 enables the same wallet page at 1440/390, for chain and DEV');
  } finally {
    if (browser) await browser.close();
    assert.deepEqual(await HOSTS.finish(), []);
  }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
