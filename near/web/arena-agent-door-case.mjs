// New local agent-door case: a creator sheet reaches the real arena, speaks and retargets.
// Keys/state stay in a temporary folder; evidence contains public command output and frames only.
import assert from 'node:assert/strict';
import { spawn, execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createRequire } from 'node:module';
import { mkdtemp, mkdir, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import net from 'node:net';
import http from 'node:http';
import { decode } from './arena/codec.mjs';
import { chooseFocus, retargetResult } from './arena-agent-door-timing.mjs';
const exec = promisify(execFile), require = createRequire(import.meta.url);
const HOSTS = require('./snapin/qa/hosts.cjs');   // each host ends with this case however it ends
const root = process.env.SNAP_CASE_ROOT || fileURLToPath(new URL('../../', import.meta.url));
const evidence = resolve(process.env.SNAP_CASE_EVIDENCE || await mkdtemp(join(tmpdir(), 'agent-door-evidence-')));
await mkdir(evidence, { recursive: true });
const scratch = await mkdtemp(join(tmpdir(), 'agent-door-session-'));
const env = { ...process.env, NO_PROXY: '', no_proxy: '' };
const procs = [], errors = [], transcript = [], sessions = [], snapshots = [];
let chrome, seq = 0, carry = ''; const pending = new Map();
const pause = (ms) => new Promise((res) => setTimeout(res, ms));
const port = () => new Promise((res, rej) => { const s = net.createServer(); s.on('error', rej); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });
function processChild(args, more = {}) { const p = HOSTS.host(args, { cwd: root, env, stdio: ['ignore', 'ignore', 'pipe'], ...more }); p.stderr.on('data', () => {}); procs.push(p); return p; }
function get(url) {
  return new Promise((res, rej) => {
    const proxy = env.HTTP_PROXY || env.http_proxy;
    const options = proxy ? { hostname: new URL(proxy).hostname, port: new URL(proxy).port, path: url, headers: { Host: new URL(url).host } } : new URL(url);
    const req = http.get(options, (r) => { let text = ''; r.on('data', (d) => text += d); r.on('end', () => { try { res(JSON.parse(text)); } catch { rej(new Error('Non-JSON response from ' + url)); } }); }); req.on('error', rej); req.setTimeout(3000, () => req.destroy(new Error('HTTP timeout')));
  });
}
async function until(fn, ms = 30000) { const end = Date.now() + ms; while (Date.now() < end) { const value = await fn(); if (value) return value; await pause(50); } throw new Error('Timed out waiting for arena condition'); }
function rpc(method, params = {}, sessionId) {
  const id = ++seq;
  return new Promise((res, rej) => {
    const timer = setTimeout(() => { pending.delete(id); rej(new Error(method + ' timeout')); }, 30000);
    pending.set(id, { res, rej, timer }); chrome.stdio[3].write(JSON.stringify({ id, method, params, sessionId }) + '\0');
  });
}
async function cli(base, dir, ...args) {
  const command = ['-I', join(root, 'near/arena/snap.py'), '--url', base, ...args];
  const { stdout } = await exec('python3', command, { cwd: dir, env, timeout: 130000 });
  transcript.push('$ python3 ' + command.slice(0, 2).map((x) => x.includes('/') ? '<checkout>/near/arena/snap.py' : x).concat(command.slice(2)).join(' ') + '\n' + stdout);
  return JSON.parse(stdout.split('\n')[0]);
}
async function sheet(name, folder) {
  const creator = require(join(root, 'near/web/snapin/sheet.js'));
  const doc = creator.build({ name, temperament: 'serene', preset: 'hunter-lunge', door: 'Codex', look: { body: 'p09', eyes: 'sparkle' } });
  const file = join(folder, doc.identity.role + '.json'); await writeFile(file, JSON.stringify(doc, null, 2));
  const { stdout } = await exec('python3', ['-I', join(root, 'near/lore/check_personas.py'), file], { env });
  assert.match(stdout, /1\/1 valid/); transcript.push('$ check_personas.py <creator-sheet>\n' + stdout); return file;
}
try {
  const config = await exec('python3', ['-B', '-c', 'import sys,json;sys.path.insert(0,sys.argv[1]);from snap_local import RULES;print(json.dumps({"viewRadius":RULES["view_radius"]}))', join(root, 'near/arena')], { cwd: root, env });
  const { viewRadius } = JSON.parse(config.stdout);
  const hostPort = await port(), webPort = await port();
  const base = 'http://127.0.0.1:' + hostPort;
  const list = join(scratch, 'blocklist.json'); await writeFile(list, JSON.stringify({ names: [], handles: [], slurs: [] }));
  processChild(['-B', 'near/arena/snap_local.py', '--port', String(hostPort)], { env: { ...env, TRENCHIE_BLOCKLIST: list } });
  await until(async () => { try { return (await get(base + '/health')).dev; } catch { return false; } });
  processChild(['-B', '-m', 'http.server', String(webPort), '--bind', '127.0.0.1', '--directory', 'near']);
  const dir = join(scratch, 'pebble'); await mkdir(dir); sessions.push({ base, dir });
  const file = await sheet('Pebble Skipper', dir);
  await cli(base, dir, 'terms');
  const joined = await cli(base, dir, 'join', '--sheet', file, '--preset', 'hunter', '--accept-terms', '1');
  assert.equal(joined.joined, true);
  await until(async () => (await cli(base, dir, 'state')).you.state === 'ring');
  chrome = spawn(process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', '--no-first-run', '--no-default-browser-check', '--remote-debugging-pipe', '--user-data-dir=' + join(scratch, 'chrome'), ...(env.HTTP_PROXY || env.http_proxy ? ['--proxy-server=' + (env.HTTP_PROXY || env.http_proxy), '--proxy-bypass-list=<-loopback>'] : []), 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe', 'pipe', 'pipe'] });
  let chromeErrors = ''; chrome.stderr.on('data', (d) => { chromeErrors = (chromeErrors + d).slice(-8000); });
  chrome.on('exit', (code) => { for (const p of pending.values()) { clearTimeout(p.timer); p.rej(new Error('Chrome exited ' + code + ': ' + chromeErrors)); } pending.clear(); });
  chrome.stdio[4].on('data', (d) => { carry += d; let end; while ((end = carry.indexOf('\0')) >= 0) { const text = carry.slice(0, end); carry = carry.slice(end + 1); if (!text) continue; const m = JSON.parse(text), p = pending.get(m.id); if (p) { clearTimeout(p.timer); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); } if (m.method === 'Network.webSocketFrameReceived' && m.params.response.opcode === 1) { try { const value = JSON.parse(m.params.response.payloadData); if (Array.isArray(value)) { snapshots.push({ snap: decode(value), arrivedMs: Date.now() }); if (snapshots.length > 1200) snapshots.shift(); } } catch (error) { errors.push('spectator decode: ' + error.message); } } if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text); if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push(m.params.args.map((x) => x.value || x.description).join(' ')); } });
  const { targetId } = await rpc('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await rpc('Target.attachToTarget', { targetId, flatten: true });
  const call = (m, p) => rpc(m, p, sessionId);
  const evaluate = async (expression) => { const r = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.text); return r.result.value; };
  const shot = async (name) => { const s = await call('Page.captureScreenshot', { format: 'png' }); await writeFile(join(evidence, name + '.png'), Buffer.from(s.data, 'base64')); };
  await call('Runtime.enable'); await call('Page.enable'); await call('Network.enable');
  await call('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false });
  await call('Page.navigate', { url: 'http://127.0.0.1:' + webPort + '/web/arena.html?ws=' + encodeURIComponent('ws://127.0.0.1:' + hostPort) });
  const selector = '.atag[data-fighter-id="' + joined.id + '"]';
  await until(() => evaluate('document.querySelector(' + JSON.stringify(selector) + ')?.textContent.includes("Pebble Skipper")'));
  await shot('01-creator-name');
  let focus, order, publicSpeech, metrics;
  for (let attempt = 0; attempt < 4 && !metrics; attempt++) {
    const shown = await evaluate('document.querySelector(' + JSON.stringify(selector) + ')?.dataset.target');
    focus = await until(() => {
      const snap = snapshots.at(-1)?.snap;
      const current = snap?.fighters.find((f) => f.id === joined.id)?.target;
      return snap && chooseFocus(snap, joined.id, [current, shown], viewRadius);
    });
    await until(() => evaluate('Boolean(document.querySelector(' + JSON.stringify(selector) + '))'));
    await evaluate(`(() => {
      window.__doorTargetObserver?.disconnect(); window.__doorTargetChanges = [];
      const node = document.querySelector(${JSON.stringify(selector)});
      window.__doorTargetObserver = new MutationObserver(() => {
        window.__doorTargetChanges.push({ target: node.dataset.target, atMs: Date.now() });
        if (window.__doorTargetChanges.length > 2048) window.__doorTargetChanges.shift();
      });
      window.__doorTargetObserver.observe(node, { attributes: true, attributeFilter: ['data-target'] });
    })()`);
    const commandStartedMs = Date.now();
    order = await cli(base, dir, 'intent', '--focus', focus, '--loot', 'ignore',
      ...(publicSpeech ? [] : ['--say', 'One ripple at a time.']));
    assert.equal(order.state, 'accepted');
    if (!publicSpeech) { publicSpeech = order.speech; assert.equal(publicSpeech.text, 'One ripple at a time.'); }
    const appliedTick = Number(order.applied_tick);
    const transition = await until(() => {
      for (const frame of snapshots) {
        if (frame.snap.tick < appliedTick) continue;
        const own = frame.snap.fighters.find((f) => f.id === joined.id);
        const enemy = frame.snap.fighters.find((f) => f.id === focus);
        if (!own || !enemy || own.status !== 0 || enemy.status !== 0 || Math.hypot(own.x - enemy.x, own.y - enemy.y) > viewRadius)
          return { lost: true }; // The in-view/live precondition ended; use a fresh close enemy.
        if (own.target === focus) return frame;
        if (frame.snap.tick - appliedTick > 40) throw new Error('focus missed its40-sim-tick contract');
      }
      return null;
    });
    if (transition.lost) continue;
    const shownAt = await until(async () => {
      const atMs = await evaluate('window.__doorTargetChanges?.find((row) => row.target === ' +
        JSON.stringify(focus) + ' && row.atMs >= ' + commandStartedMs + ')?.atMs');
      if (atMs) return { atMs };
      const snap = snapshots.at(-1)?.snap;
      const own = snap?.fighters.find((f) => f.id === joined.id), enemy = snap?.fighters.find((f) => f.id === focus);
      if (!own || !enemy || own.status !== 0 || enemy.status !== 0 || Math.hypot(own.x - enemy.x, own.y - enemy.y) > viewRadius)
        return { lost: true };
      return null;
    }, 2000);
    if (shownAt.lost) continue;
    metrics = retargetResult({ appliedTick, switchedTick: transition.snap.tick, commandStartedMs,
      frameArrivedMs: transition.arrivedMs, visibleMs: shownAt.atMs });
    assert.ok(metrics.within, 'focus within40sim ticks after apply; tag within2s of the target snapshot: ' + JSON.stringify(metrics));
  }
  assert.ok(metrics, 'a focus target stayed alive and in view for the measurement');
  const latencyMs = metrics.renderLatencyMs;
  // Battle mode: the line goes only in the ticker, under its speaker's id; no bubble beside the fighter
  await until(() => evaluate('document.querySelector(' + JSON.stringify('.arena-say-feed [data-fighter-id="' + joined.id + '"]') + ')?.textContent.includes("One ripple at a time.")'), 2000);
  assert.equal(await evaluate('document.querySelectorAll(".say-line").length'), 0);
  await shot('02-target-and-speech');
  await call('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: false }); await pause(500); await shot('03-speech-390');
  const blockedDir = join(scratch, 'shell'); await mkdir(blockedDir); sessions.push({ base, dir: blockedDir });
  const blockedFile = await sheet('Shell Drifter', blockedDir);
  const blockedJoin = await cli(base, blockedDir, 'join', '--sheet', blockedFile, '--preset', 'hunter', '--accept-terms', '1');
  await until(async () => (await cli(base, blockedDir, 'state')).you.state === 'ring');
  const blocked = await cli(base, blockedDir, 'intent', '--say', 'fraud');
  assert.equal(blocked.speech.blocked, true); assert.notEqual(blocked.speech.text, 'fraud');
  await until(() => evaluate('document.querySelector(' + JSON.stringify('.arena-say-feed [data-fighter-id="' + blockedJoin.id + '"]') + ')?.textContent.includes(' + JSON.stringify(blocked.speech.text) + ')'), 2000);
  await shot('04-blocked-emote');
  assert.equal(await evaluate('document.querySelector(".arena-say-feed").textContent.includes("fraud")'), false);
  await cli(base, dir, 'intent', '--leave');
  const result = await cli(base, dir, 'result', '--wait', '90');
  assert.equal(result.signed, true); assert.equal(result.chain_result, false);
  const missingPort = await port(), missingBase = 'http://127.0.0.1:' + missingPort;
  processChild(['-B', 'near/arena/snap_local.py', '--port', String(missingPort)], { env: { ...env, TRENCHIE_BLOCKLIST: '' } });
  await until(async () => { try { return (await get(missingBase + '/health')).dev; } catch { return false; } });
  await call('Page.navigate', { url: 'http://127.0.0.1:' + webPort + '/web/arena.html?ws=' + encodeURIComponent('ws://127.0.0.1:' + missingPort) });
  const missingDir = join(scratch, 'dune'); await mkdir(missingDir); sessions.push({ base: missingBase, dir: missingDir });
  const missingFile = await sheet('Dune Ripple', missingDir);
  await cli(missingBase, missingDir, 'join', '--sheet', missingFile, '--preset', 'hunter', '--accept-terms', '1');
  await until(async () => (await cli(missingBase, missingDir, 'state')).you.state === 'ring');
  const missing = await cli(missingBase, missingDir, 'intent', '--say', 'A calm shore.');
  assert.equal(missing.speech.muted, true); assert.equal(missing.speech.label, 'guard list missing');
  await until(() => evaluate('document.querySelector(".arena-say-feed")?.textContent.includes("guard list missing")'), 2000);
  await shot('05-missing-list-390');
  await call('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false }); await pause(500); await shot('06-missing-list-1440');
  assert.deepEqual(errors, []);
  await writeFile(join(evidence, 'result.json'), JSON.stringify({ fighterId: joined.id, focus, latencyMs, errors, creator: 'Pebble Skipper', publicSpeech, focusTicks: metrics.focusTicks, commandToVisibleMs: metrics.commandToVisibleMs, blockedSpeech: blocked.speech, mutedSpeech: missing.speech, signedResult: result }, null, 2));
  process.stdout.write(JSON.stringify({ ok: true, evidence, fighterId: joined.id, focus, latencyMs, focusTicks: metrics.focusTicks, commandToVisibleMs: metrics.commandToVisibleMs }) + '\n');
} finally {
  for (const { base, dir } of sessions) { try { await cli(base, dir, 'stop'); } catch {} }
  await writeFile(join(evidence, 'commands.txt'), transcript.join('\n'));
  for (const { dir } of sessions) { try { await writeFile(join(evidence, 'keeper-' + dir.split('/').pop() + '.txt'), await readFile(join(dir, '.snap-dev.log'))); } catch (error) { if (error.code !== 'ENOENT') throw error; } }
  for (const p of procs) p.kill(); chrome?.kill();
  { const left = await HOSTS.finish(); if (left.length) { console.error('FAIL ' + left.length + ' host group(s) this case started survived it'); process.exitCode = 1; } }
  for (const { timer } of pending.values()) clearTimeout(timer);
  await pause(500); await rm(scratch, { recursive: true, force: true });
}
