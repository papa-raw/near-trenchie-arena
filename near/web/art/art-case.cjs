// art-case.cjs — the new case for the house models: node art-case.cjs  (needs playwright; run from a shell where chromium can start)
// Serves near/web over http, opens compare.html at DPR 2 and checks: 14/14 house models match the stored reference,
// 6 presets drawn, 0 console errors. Also sweeps this folder's text for words that must not appear in public files.
const http = require('node:http'), fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const ROOT = path.resolve(__dirname, '..', '..'), TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.png': 'image/png', '.css': 'text/css' };
const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'content-type': TYPES[path.extname(p)] || 'application/octet-stream' }); fs.createReadStream(p).pipe(res);
});
// the sweep: the two banned whole words (built from fragments so this file passes its own gate) plus lane and role names that never ship
const BANNED = new RegExp('\\b(' + ['jud' + 'ges?', 'fig' + 'ures?'].join('|') + ')\\b', 'gi'), INTERNAL = new RegExp(['critic', 'builder', 'coharn' + 'ess'].map((w, i) => i < 2 ? w + '-[bg]\\b' : w).join('|'), 'gi');
for (const f of fs.readdirSync(__dirname).filter((n) => /\.(js|cjs|html|md)$/.test(n))) {
  const t = fs.readFileSync(path.join(__dirname, f), 'utf8');
  assert.equal((t.match(BANNED) || []).length, 0, f + ': banned word');
  assert.equal((t.match(INTERNAL) || []).length, 0, f + ': internal name');
}
(async () => {
  const { chromium } = require('playwright');
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 })).newPage();
  const errors = []; page.on('pageerror', (e) => errors.push(String(e))); page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  try {
    const base = 'http://127.0.0.1:' + server.address().port + '/web/art/', ran = [];
    // each page sets a done flag and a result object; a page that is not in this folder yet is skipped
    const pages = [
      ['compare.html', '__ART_DONE', '__ART', (r) => { assert.equal(r.passed, 14, 'house models matching: ' + JSON.stringify(r.results.filter((x) => !x.pass))); assert.equal(r.presets, 6); }],
      ['motion.html', '__MOTION_DONE', '__MOTION', (r) => { assert.equal(r.rows, 18); assert.equal(r.frames, 144); assert.equal(r.deterministic, true); assert.equal(r.hasHook, true); }],
      ['kit-compare.html', '__CMP_DONE', '__CMP', (r) => { assert.equal(r.ok, true); }],
      ['legendary.html', '__LEG_DONE', '__LEG', (r) => { assert.equal(r.n, 14); assert.equal(r.ok, true); }],
      ['kit.html', '__KIT_DONE', '__KIT', (r) => { assert.equal(r.ok, true); }]
    ];
    for (const [file, done, key, check] of pages) {
      if (!fs.existsSync(path.join(__dirname, file))) continue;
      await page.goto(base + file);
      await page.waitForFunction((d) => window[d] === true, done, { timeout: 120000 });
      const r = await page.evaluate((k) => window[k], key);
      check(r); assert.deepEqual(r.errors, [], file + ' errors'); assert.deepEqual(errors, [], file + ' console'); ran.push(file);
    }
    console.log('art-case: ' + ran.join(', ') + ' pass with 0 console errors');
  } finally { await browser.close(); server.close(); }
})().catch((e) => { console.error(e); process.exit(1); });
