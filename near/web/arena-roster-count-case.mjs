// Roster browser case: the arena page's card labels count the same admitted members as the host's public roster.
// Run: node near/web/arena-roster-count-case.mjs   (needs Chrome; starts a keyed DEV host, no key, no network)
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const scratch = await mkdtemp(join(process.env.ARENA_EVIDENCE_DIR || tmpdir(), 'arena-roster-'));
const near = fileURLToPath(new URL('../', import.meta.url));
const env = { ...process.env }; delete env.NEARAI_API_KEY; delete env.TRENCHIE_BLOCKLIST;
const host = spawn('python3', ['-B', '-u', join(near, 'house/live_run.py'), '--seconds', '120', '--data-dir', join(scratch, 'host')], { env, stdio: ['ignore', 'pipe', 'pipe'] });
const server = spawn('python3', ['-B', '-u', '-m', 'http.server', '0', '--bind', '127.0.0.1', '--directory', near], { stdio: ['ignore', 'pipe', 'pipe'] });
let browser, ws, seq = 0; const pending = new Map(), errors = [];
function match(stream, pattern) {
  return new Promise((res, rej) => {
    let text = ''; const timer = setTimeout(() => rej(new Error('Startup timeout: ' + text)), 30000);
    stream.on('data', (d) => { text += d; const m = pattern.exec(text); if (m) { clearTimeout(timer); res(m); } });
  });
}
function rpc(method, params = {}, sessionId) {
  const id = ++seq;
  return new Promise((res, rej) => {
    const timer = setTimeout(() => { pending.delete(id); rej(new Error(method + ' timeout')); }, 30000);
    pending.set(id, { res, rej, timer }); ws.send(JSON.stringify({ id, method, params, sessionId }));
  });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
try {
  const hostPort = +(await match(host.stdout, /DEV host on http:\/\/127\.0\.0\.1:(\d+)/))[1];
  const port = +(await match(server.stdout, /port (\d+)/))[1];
  const roster = async () => (await fetch('http://127.0.0.1:' + hostPort + '/house/roster')).json();
  browser = spawn(process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', '--user-data-dir=' + join(scratch, 'profile'), 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
  ws = new WebSocket((await match(browser.stderr, /DevTools listening on (ws:\/\/[^\s]+)/))[1]);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = ({ data }) => {
    const m = JSON.parse(data), p = pending.get(m.id);
    if (p) { clearTimeout(p.timer); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); }
    if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push(m.params.args.map((v) => v.value || v.description).join(' '));
  };
  const { targetId } = await rpc('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await rpc('Target.attachToTarget', { targetId, flatten: true });
  const call = (method, params) => rpc(method, params, sessionId);
  await call('Runtime.enable'); await call('Page.enable');
  const results = [];
  for (const [w, h] of [[1440, 900], [390, 844]]) {
    await call('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 2, mobile: w < 600 });
    await call('Page.navigate', { url: 'http://127.0.0.1:' + port + '/web/arena.html?ws=ws://127.0.0.1:' + hostPort });
    let seen = null, truth = null;
    for (let i = 0; i < 40; i++) {                 // the labels follow the 5 s roster poll; the house yields seats at life ends
      await sleep(1000);
      const r = await call('Runtime.evaluate', { expression: "JSON.stringify([...document.querySelectorAll('[data-card]')].map((n) => [n.dataset.card, n.textContent]))", returnByValue: true });
      seen = JSON.parse(r.result.value || '[]'); truth = await roster();
      const house = seen.find(([card]) => card === 'house-roster');
      const want = truth.members.filter((m) => m.house).length;
      if (house && new RegExp('^' + want + ' admitted').test(house[1])) break;
    }
    const house = seen.find(([card]) => card === 'house-roster');
    assert.ok(house, 'the house roster tag is drawn: ' + JSON.stringify(seen));
    assert.ok(seen.some(([card, text]) => card === 'house' && /^House( · since you arrived)?$/.test(text)), 'the House label is the board’s words');
    const count = +/^(\d+) admitted/.exec(house[1])[1];
    assert.equal(count, truth.members.filter((m) => m.house).length, 'the label counts the roster projection\'s house members');
    assert.equal(truth.admitted, truth.members.length);
    assert.match(house[1], /autopilot \(no model key\)/, 'the keyed house shows its chip');
    for (const key of ['calls_per_min', 'status', 'prompt', 'cap']) assert.ok(!(key in truth), 'no private field: ' + key);
    const shot = await call('Page.captureScreenshot', { format: 'png' });
    await writeFile(join(scratch, 'roster-' + w + '.png'), Buffer.from(shot.data, 'base64'));
    results.push({ width: w, label: house[1], rosterHouse: count, admitted: truth.admitted, chip: truth.chip });
  }
  assert.deepEqual(errors, []);
  await writeFile(join(scratch, 'result.json'), JSON.stringify({ results, errors }, null, 2));
  process.stdout.write(JSON.stringify({ ok: true, results, evidence: scratch }) + '\n');
} finally {
  ws?.close(); browser?.kill(); server.kill(); host.kill();
  if (browser && browser.exitCode === null && browser.signalCode === null) await Promise.race([new Promise((res) => browser.once('exit', res)), new Promise((res) => setTimeout(res, 2000))]);
  await rm(join(scratch, 'profile'), { recursive: true, force: true });
}
