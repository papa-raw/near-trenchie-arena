// Render every guide header with the real guide and local CSS/fonts; no host or wallet is needed.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/close_x_case.cjs
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ROOT = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(ROOT, name), 'utf8');
const fonts = read('board1.css').replace(/url\((fonts\/[^)]+)\)/g, (_, name) =>
  'url(data:font/woff2;base64,' + fs.readFileSync(path.join(ROOT, name)).toString('base64') + ')');

(async () => {
  const options = { args: ['--single-process', '--no-zygote'] };
  if (process.env.HTTPS_PROXY) options.proxy = { server: process.env.HTTPS_PROXY, bypass: '127.0.0.1,localhost' };
  const browser = await require('playwright').chromium.launch(options);
  const failures = [], errors = [];
  try {
    const page = await browser.newPage();
    page.on('pageerror', error => errors.push(String(error)));
    // All assets used for header measurement are in memory. The island and avatars do not affect its geometry.
    await page.route('**/*', route => route.abort());
    await page.setContent('<!doctype html><meta charset="utf-8"><div id="app"></div>');
    await page.addStyleTag({ content: fonts + '\n.stage{background-image:none}' });
    for (const file of ['art/ska.js', 'guide-copy.js', 'guide.js']) await page.addScriptTag({ content: read(file) });
    await page.evaluate(async () => {
      window.SnapUI = { store: { get: () => null } };
      window.SnapMarks = { mark: () => '' };
      await document.fonts.ready;
      window.fixture = {
        P: { name: 'Coral Scout', preset: 'Hunter Lunge', fighterChosen: true, quirks: [], wallet: { accountId: 'coral.invalid' } },
        V: { step: 'wallet' }, shortAcct: value => value,
        chain: () => ({ known: true, on: true, network: 'mainnet' }),
        backToArena: () => { window.closeCalls++; }
      };
      window.closeCalls = 0;
      document.addEventListener('click', event => {
        if (event.target.closest('[data-act="g:close"]')) SnapGuide.act('g:close', fixture);
      });
    });
    const states = [['wallet'], ['presets'], ['personality'], ['doors'], ['agree'],
      ...['NEAR AI Cloud', 'Claude', 'OpenRouter', 'Codex'].map(door => ['doors', 'key', door]),
      ...['Claude Code', 'Codex'].map(door => ['doors', 'plan', door])];
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      for (const [step, route, door] of states) {
        const label = [width, step, route, door].filter(Boolean).join(' ');
        await page.evaluate(({ step, route, door, width }) => {
          document.body.className = width === 390 ? 'w390' : 'w1440';
          fixture.V.step = step;
          fixture.P.pick = route ? { route, door } : null;
          document.querySelector('#app').innerHTML = SnapGuide.view(fixture);
          SnapGuide.paint(document.querySelector('#app'));
        }, { step, route, door, width });
        await page.evaluate(() => document.fonts.ready);
        const geometry = await page.evaluate(() => {
          const head = document.querySelector('.face-head'), close = head.querySelector('[data-act="g:close"]');
          const button = close.getBoundingClientRect(), bounds = head.getBoundingClientRect();
          const text = [...close.childNodes].find(node => node.nodeType === Node.TEXT_NODE && node.textContent.includes('×'));
          const range = document.createRange(); range.selectNodeContents(text);
          const glyph = range.getBoundingClientRect();
          const other = head.querySelector('[data-act="g:other"]');
          let link = null;
          if (other) {
            range.selectNodeContents(other);
            const rects = [...range.getClientRects()];
            link = { lines: new Set(rects.map(rect => Math.round(rect.top))).size, right: other.getBoundingClientRect().right };
          }
          return { width: button.width, height: button.height,
            dx: (glyph.left + glyph.right - button.left - button.right) / 2,
            dy: (glyph.top + glyph.bottom - button.top - button.bottom) / 2,
            inside: button.left >= bounds.left && button.right <= bounds.right && button.bottom <= innerHeight,
            reachable: close.contains(document.elementFromPoint(button.x + button.width / 2, button.y + button.height / 2)),
            left: button.left, link };
        });
        const checks = [
          [Math.abs(geometry.width - geometry.height) <= 1, 'close plate is square'],
          [geometry.width === 44, 'close plate retains its fixed 44 px size'],
          [Math.abs(geometry.dx) <= 1 && Math.abs(geometry.dy) <= 1, '× is centred on both axes'],
          [geometry.inside && geometry.reachable, 'close remains in the header and reachable'],
          [!route || geometry.link?.lines === 1, 'Other AIs stays on one line'],
          [!route || geometry.link?.right < geometry.left, 'Other AIs stays left of close']
        ];
        for (const [ok, message] of checks) if (!ok) failures.push(label + ': ' + message + ' ' + JSON.stringify(geometry));
        const before = await page.evaluate(() => closeCalls);
        await page.locator('[data-act="g:close"]').click();
        assert.equal(await page.evaluate(() => closeCalls), before + 1, label + ' close action');
        process.stdout.write(JSON.stringify({ state: label, ...geometry }) + '\n');
      }
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(failures, []);
    process.stdout.write('close-x-case: PASS; 11 guide states at 1440 and 390, square centred close, single-line link and close action\n');
  } finally { await browser.close(); }
})().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
