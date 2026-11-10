// Focused browser case. Run: node near/web/arena-view-remainder-case.mjs
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const scratch = await mkdtemp(join(process.env.ARENA_EVIDENCE_DIR || tmpdir(), 'arena-view-'));
const near = fileURLToPath(new URL('../', import.meta.url));
const server = spawn('python3', ['-B', '-u', '-m', 'http.server', '0', '--bind', '127.0.0.1', '--directory', near], { stdio: ['ignore', 'pipe', 'pipe'] });
let browser, ws, seq = 0; const pending = new Map(), errors = [];
function match(stream, pattern) {
  return new Promise((res, rej) => {
    let text = ''; const timer = setTimeout(() => rej(new Error('Startup timeout: ' + text)), 20000);
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
try {
  const port = +(await match(server.stdout, /port (\d+)/))[1];
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
  await call('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false });
  await call('Page.navigate', { url: 'http://127.0.0.1:' + port + '/web/arena-view-remainder-fixture.html' });
  await new Promise((r) => setTimeout(r, 500));
  const result = await call('Runtime.evaluate', { expression: "import('./arena-view-remainder-checks.mjs').then(m => m.check())", awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  assert.equal(result.result.value.ok, true); assert.deepEqual(errors, []);
  const shot = await call('Page.captureScreenshot', { format: 'png' });
  await writeFile(join(scratch, 'items-60px.png'), Buffer.from(shot.data, 'base64'));
  await writeFile(join(scratch, 'result.json'), JSON.stringify({ ...result.result.value, errors }, null, 2));
  process.stdout.write(JSON.stringify({ ...result.result.value, errors, evidence: scratch }) + '\n');
} finally {
  ws?.close(); browser?.kill(); server.kill();
  if (browser && browser.exitCode === null && browser.signalCode === null) await Promise.race([new Promise((res) => browser.once('exit', res)), new Promise((res) => setTimeout(res, 2000))]);
  await rm(join(scratch, 'profile'), { recursive: true, force: true });
}
