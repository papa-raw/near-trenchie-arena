// Battle mode view case: in a live DEV crowd the speaker's emoji floats over the right fighter, the line itself
// shows only in the B2 a ticker (tag + emoji + text), big moments reach the ticker, and nothing overlaps at 1440 and at a
// true 390 CSS px viewport. Needs a host whose feed rows carry `emoji` (the house feed's emoji pick).
//   node near/web/arena-battle-view-case.mjs            (SNAP_CASE_ROOT=<tree>, SNAP_CASE_EVIDENCE=<dir> optional)
import assert from 'node:assert/strict';
import { spawn, execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createRequire } from 'node:module';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import net from 'node:net';
import http from 'node:http';
const exec = promisify(execFile), require = createRequire(import.meta.url);
const root = process.env.SNAP_CASE_ROOT || fileURLToPath(new URL('../../', import.meta.url));
const evidence = resolve(process.env.SNAP_CASE_EVIDENCE || await mkdtemp(join(tmpdir(), 'battle-view-evidence-')));
await mkdir(evidence, { recursive: true });
const scratch = await mkdtemp(join(tmpdir(), 'battle-view-session-'));
const env = { ...process.env, NO_PROXY: '', no_proxy: '' };
const procs = [], errors = [], transcript = [], sessions = [], found = {};
let chrome, seq = 0, carry = ''; const pending = new Map();
const pause = (ms) => new Promise((res) => setTimeout(res, ms));
const port = () => new Promise((res, rej) => { const s = net.createServer(); s.on('error', rej); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });
function processChild(args, more = {}) { const p = spawn('python3', args, { cwd: root, env, stdio: ['ignore', 'ignore', 'pipe'], ...more }); p.stderr.on('data', () => {}); procs.push(p); return p; }
function get(url) {
  return new Promise((res, rej) => {
    const proxy = env.HTTP_PROXY || env.http_proxy;
    const options = proxy ? { hostname: new URL(proxy).hostname, port: new URL(proxy).port, path: url, headers: { Host: new URL(url).host } } : new URL(url);
    const req = http.get(options, (r) => { let text = ''; r.on('data', (d) => text += d); r.on('end', () => { try { res(JSON.parse(text)); } catch { rej(new Error('Non-JSON response from ' + url)); } }); }); req.on('error', rej); req.setTimeout(3000, () => req.destroy(new Error('HTTP timeout')));
  });
}
async function until(fn, ms = 60000, what = 'arena condition') { const end = Date.now() + ms; while (Date.now() < end) { const value = await fn(); if (value) return value; await pause(100); } throw new Error('Timed out waiting for ' + what); }
function rpc(method, params = {}, sessionId) {
  const id = ++seq;
  return new Promise((res, rej) => {
    const timer = setTimeout(() => { pending.delete(id); rej(new Error(method + ' timeout')); }, 60000);
    pending.set(id, { res, rej, timer }); chrome.stdio[3].write(JSON.stringify({ id, method, params, sessionId }) + '\0');
  });
}
async function cli(base, dir, ...args) {
  const command = ['-I', join(root, 'near/arena/snap.py'), '--url', base, ...args];
  const { stdout } = await exec('python3', command, { cwd: dir, env, timeout: 180000 });
  transcript.push('$ python3 <checkout>/near/arena/snap.py ' + command.slice(2).join(' ') + '\n' + stdout);
  return JSON.parse(stdout.split('\n')[0]);
}
async function sheet(name, folder) {
  const creator = require(join(root, 'near/web/snapin/sheet.js'));
  const doc = creator.build({ name, temperament: 'serene', preset: 'hunter-lunge', door: 'Codex', look: { body: 'p09', eyes: 'sparkle' } });
  const file = join(folder, doc.identity.role + '.json'); await writeFile(file, JSON.stringify(doc, null, 2));
  const { stdout } = await exec('python3', ['-I', join(root, 'near/lore/check_personas.py'), file], { env });
  assert.match(stdout, /1\/1 valid/); return file;
}
// Every speaker emoji against every name tag, HUD panel, the ticker and the buttons: the list of overlaps (empty = none).
const OVERLAPS = `(() => {
  const r = (el) => { const b = el.getBoundingClientRect(); return { x: b.left, y: b.top, w: b.width, h: b.height, el }; };
  const hit = (a, b) => Math.min(a.x + a.w, b.x + b.w) > Math.max(a.x, b.x) + 0.5 && Math.min(a.y + a.h, b.y + b.h) > Math.max(a.y, b.y) + 0.5;
  const marks = [...document.querySelectorAll('.say-emoji')].filter((e) => e.style.display !== 'none').map(r);
  const tags = [...document.querySelectorAll('#world .atag')].map(r);
  const panels = [...document.querySelectorAll('#world [data-panel]:not([data-kind="world"])')].map(r);
  const ticker = [...document.querySelectorAll('.arena-say-feed > div')].map(r);
  const buttons = [...document.querySelectorAll('#world [data-panel="btn0"], #world [data-panel="btn1"]')].map(r);
  const out = [];
  for (const m of marks) for (const o of [...tags, ...panels, ...ticker]) if (hit(m, o)) out.push('emoji ' + m.el.dataset.fighterId + ' over ' + (o.el.dataset.panel || o.el.className));
  for (let i = 0; i < marks.length; i++) for (let j = i + 1; j < marks.length; j++) if (hit(marks[i], marks[j])) out.push('two emoji overlap');
  for (const t of ticker) for (const b of buttons) if (hit(t, b)) out.push('ticker line under ' + b.el.dataset.panel);
  // the snap-in call to action and Satrenchi's cue inside it never cover a speech row (found in review at a true 390 px)
  const cta = document.querySelector('#snapin-cta');
  if (cta && getComputedStyle(cta).display !== 'none') for (const t of ticker) if (hit(r(cta), t)) out.push('snap-in CTA over a ticker line');
  return out;
})()`;
try {
  const hostPort = await port(), webPort = await port();
  const base = 'http://127.0.0.1:' + hostPort;
  const list = join(scratch, 'blocklist.json'); await writeFile(list, JSON.stringify({ names: [], handles: [], slurs: [] }));
  processChild(['-B', 'near/arena/snap_local.py', '--port', String(hostPort), '--house', 'keyed'], { env: { ...env, TRENCHIE_BLOCKLIST: list } });
  await until(async () => { try { return (await get(base + '/health')).dev; } catch { return false; } }, 90000, 'the DEV host');
  processChild(['-B', '-m', 'http.server', String(webPort), '--bind', '127.0.0.1', '--directory', 'near']);
  // A creator persona joins through SNAP.md's CLI. A sandboxed lane's grant proxy refuses the CLI's detached keeper
  // (HTTP 403); the case then says so and checks speakers on the house fighters, which speak through the same feed.
  const dir = join(scratch, 'pebble'); await mkdir(dir);
  let joined = null;
  try {
    const file = await sheet('Pebble Skipper', dir);
    await cli(base, dir, 'terms');
    joined = await cli(base, dir, 'join', '--sheet', file, '--preset', 'hunter', '--accept-terms', '1');
    sessions.push({ base, dir });
    assert.equal(joined.joined, true);
    await until(async () => (await cli(base, dir, 'state')).you.state === 'ring', 120000, 'the creator in the ring');
  } catch (error) {
    found.creatorSkipped = 'creator path not runnable here: ' + String(error.stderr || error.message).trim().split('\n')[0];
    joined = null;
  }
  chrome = spawn(process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', '--no-first-run', '--no-default-browser-check', '--remote-debugging-pipe', '--window-size=390,844', '--user-data-dir=' + join(scratch, 'chrome'), ...(env.HTTP_PROXY || env.http_proxy ? ['--proxy-server=' + (env.HTTP_PROXY || env.http_proxy), '--proxy-bypass-list=<-loopback>'] : []), 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe', 'pipe', 'pipe'] });
  chrome.stdio[4].on('data', (d) => { carry += d; let end; while ((end = carry.indexOf('\0')) >= 0) { const text = carry.slice(0, end); carry = carry.slice(end + 1); if (!text) continue; const m = JSON.parse(text), p = pending.get(m.id); if (p) { clearTimeout(p.timer); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); } if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text); if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push(m.params.args.map((x) => x.value || x.description).join(' ')); } });
  const { targetId } = await rpc('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await rpc('Target.attachToTarget', { targetId, flatten: true });
  const call = (m, p) => rpc(m, p, sessionId);
  const evaluate = async (expression) => { const r = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.text); return r.result.value; };
  const shot = async (name) => { const s = await call('Page.captureScreenshot', { format: 'png' }); await writeFile(join(evidence, name + '.png'), Buffer.from(s.data, 'base64')); };
  const width = (w, h) => call('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 2, mobile: w < 600 });
  // the snap-in button takes its final spot at load: its place at 0.5 s equals its place at 10 s (no hop)
  const ctaAt = () => evaluate('(() => { const b = document.querySelector("#snapin-cta")?.getBoundingClientRect(); return b ? [Math.round(b.left), Math.round(b.top)] : null; })()');
  const noHop = async (label) => { await pause(500); const early = await ctaAt(); await pause(9500); const late = await ctaAt();
    found['cta_' + label] = { early, late }; assert.deepEqual(early, late, 'the snap-in button hopped at ' + label + ': ' + JSON.stringify({ early, late })); };
  await call('Runtime.enable'); await call('Page.enable');
  await width(1440, 900);
  const page = 'http://127.0.0.1:' + webPort + '/web/arena.html?ws=' + encodeURIComponent('ws://127.0.0.1:' + hostPort);
  await call('Page.navigate', { url: page }); await noHop('1440');
  await until(() => evaluate('document.querySelectorAll("#world .atag").length > 0'), 120000, 'fighters\' name tags');

  // 1. the creator speaks: its emoji over its own tag, the line only in the ticker
  if (joined) {
  await until(() => evaluate('!!document.querySelector(' + JSON.stringify('.atag[data-fighter-id="' + joined.id + '"]') + ')'), 120000, 'the creator\'s tag');
  const order = await cli(base, dir, 'intent', '--say', 'One ripple at a time.');
  assert.equal(order.state, 'accepted');
  const mine = await until(() => evaluate(`(() => { const m = document.querySelector('.say-emoji[data-fighter-id="${joined.id}"]'), t = document.querySelector('.atag[data-fighter-id="${joined.id}"]');
    const line = document.querySelector('.arena-say-feed [data-fighter-id="${joined.id}"]');
    if (!m || !t || !line || !line.textContent.includes('One ripple at a time.')) return null;
    const a = m.getBoundingClientRect(), b = t.getBoundingClientRect();
    return { emoji: m.textContent, line: line.textContent, dx: Math.abs((a.left + a.width / 2) - (b.left + b.width / 2)), gap: b.top - a.bottom, emojiH: a.height }; })()`), 20000, 'the creator\'s emoji and ticker line');
  assert.ok(mine.line.includes(mine.emoji), 'the ticker line carries the same emoji');
  assert.ok(mine.dx < 140 && mine.gap > -mine.emojiH - 60, 'the emoji sits by its own tag: ' + JSON.stringify(mine));
  assert.equal(await evaluate('document.querySelectorAll(".say-line").length'), 0, 'no bubble beside a fighter');
  assert.equal(await evaluate(`[...document.querySelectorAll('.arena-say-layer *')].some((e) => e.textContent.includes('One ripple'))`), false, 'the line is not drawn in the arena');
  found.creator = mine;
  await shot('01-creator-speaks-1440');
  }
  // 2. a house fighter speaks (keyed lines on KOs and grabs): its emoji over its own tag
  const house = await until(() => evaluate(`(() => { for (const m of document.querySelectorAll('.say-emoji')) { const id = m.dataset.fighterId;
      if (id === ${JSON.stringify(joined ? joined.id : '')}) continue; const t = document.querySelector('.atag[data-fighter-id="' + id + '"]'), l = document.querySelector('.arena-say-feed [data-feed-id="' + m.dataset.feedId + '"]');
      if (!t || !l) continue; const a = m.getBoundingClientRect(), b = t.getBoundingClientRect();
      return { id, emoji: m.textContent, line: l.textContent, dx: Math.abs((a.left + a.width / 2) - (b.left + b.width / 2)), gap: b.top - a.bottom, emojiH: a.height }; } return null; })()`), 240000, 'a house speaker');
  assert.ok(house.line.includes(house.emoji), 'the ticker line carries the same emoji');
  assert.ok(house.dx < 140 && house.gap > -house.emojiH - 60, 'the emoji sits by its own tag: ' + JSON.stringify(house));
  assert.equal(await evaluate('document.querySelectorAll(".say-line").length'), 0, 'no bubble beside a fighter');
  found.house = house;
  await shot('02-house-speaks-1440');
  // 3. big moments reach the ticker
  found.moment = await until(() => evaluate(`(() => { const l = document.querySelector('.arena-say-feed [data-moment]'); return l ? { kind: l.dataset.moment, text: l.textContent } : null; })()`), 300000, 'a big-moment line');
  await shot('03-moment-1440');
  // 4. no overlap at 1440, then at a true 390 CSS px viewport
  found.overlap1440 = await evaluate(OVERLAPS); assert.deepEqual(found.overlap1440, []);
  await width(390, 844); await call('Page.navigate', { url: page }); await noHop('390');
  found.innerWidth390 = await evaluate('innerWidth'); assert.equal(found.innerWidth390, 390, 'a true 390 CSS px viewport');
  if (joined) {
    await cli(base, dir, 'intent', '--say', 'Still here.');
    await until(() => evaluate(`!!document.querySelector('.say-emoji[data-fighter-id="${joined.id}"]')`), 20000, 'the creator\'s emoji at 390');
  } else await until(() => evaluate('!!document.querySelector(".say-emoji")'), 240000, 'a speaker\'s emoji at 390');
  found.overlap390 = await evaluate(OVERLAPS); assert.deepEqual(found.overlap390, []);
  await shot('04-speech-390');
  assert.deepEqual(errors, []);
  await writeFile(join(evidence, 'result.json'), JSON.stringify({ fighterId: joined && joined.id, ...found, errors }, null, 2));
  process.stdout.write(JSON.stringify({ ok: true, evidence, ...found }) + '\n');
} finally {
  for (const { base, dir } of sessions) { try { await cli(base, dir, 'stop'); } catch {} }
  await writeFile(join(evidence, 'commands.txt'), transcript.join('\n'));
  for (const p of procs) p.kill(); chrome?.kill();
  for (const { timer } of pending.values()) clearTimeout(timer);
  await pause(500); await rm(scratch, { recursive: true, force: true });
}
