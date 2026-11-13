// qa/hosts.cjs must stop hosts when their cases end: six DEV arenas outlived their cases on 2026-11-12 and burned ~30%
// CPU each for up to an hour. A fixture case starts a host through the harness and ends in each way a case can end; the host
// must be gone within 5 s (its port refuses connections and its process group is empty):
//   finish (the normal end, with finish()'s own survivor check), throw, process.exit(1), SIGTERM to the case, SIGKILL to
//   the case (no handler can run), and the harness's hard timeout. The host is a real near/arena/snap_local.py.
// The "before" run's leaked arenas are killed by this case once counted.
// HOSTS_IMPL=old runs the same fixtures with the cases' old start() (spawn python3, kill only on the happy path): it fails.
// usage: node near/web/snapin/qa/hosts_case.cjs   (no browser; ~1 min)
'use strict';
const { spawn } = require('child_process'), path = require('path'), net = require('net');
const IMPL = process.env.HOSTS_IMPL === 'old' ? 'old' : 'new';
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const refused = (port) => new Promise((r) => { const s = net.connect({ port, host: '127.0.0.1' }); s.on('connect', () => { s.destroy(); r(false); }); s.on('error', () => r(true)); });
const groupGone = (g) => { try { process.kill(-g, 0); return false; } catch (e) { return e.code === 'ESRCH'; } };
const pidGone = (p) => { try { process.kill(p, 0); return false; } catch (e) { return e.code === 'ESRCH'; } };

// ---------------------------------------------------------------- the fixture: one case, ended one way
if (process.argv[2] === 'fixture') {
  const mode = process.argv[3];
  let start, finish = async () => [];
  if (IMPL === 'old') {   // the pattern every snap-in case used before the harness
    start = (args, ready) => { const child = spawn('python3', ['-B', ...args], { cwd: path.resolve(__dirname, '..', '..', '..', '..'), stdio: ['ignore', 'pipe', 'pipe'] });
      return new Promise((res) => { let o = ''; child.stdout.on('data', (d) => { o += d; const m = ready(o); if (m) res({ child, m }); }); }); };
  } else ({ start, finish } = require('./hosts.cjs'));
  (async () => {
    const port = 20000 + Math.floor(Math.random() * 20000);
    const host = await start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
    console.log('HOST ' + host.child.pid + ' ' + port);
    if (mode === 'finish') { const left = await finish(); console.log('LEFT ' + left.length); host.child.kill(); process.exit(0); }
    if (mode === 'throw') { setTimeout(() => { throw new Error('a case bug'); }, 100); return; }
    if (mode === 'exit') { setTimeout(() => process.exit(1), 100); return; }
    setInterval(() => {}, 1000);   // sigterm, sigkill, timeout: the case keeps running until it is ended from outside or by the limit
  })();
  return;
}

// ---------------------------------------------------------------- the case
function runFixture(mode) {
  const env = Object.assign({}, process.env, mode === 'timeout' ? { CASE_TIMEOUT_MS: '2000' } : {});
  const f = spawn(process.execPath, [__filename, 'fixture', mode], { env, stdio: ['ignore', 'pipe', 'pipe'] });
  return new Promise((resolve) => {
    let out = '', host = null, ended = false;
    const done = () => { if (!ended) { ended = true; resolve({ host, out }); } };
    f.stdout.on('data', (d) => {
      out += d; const m = out.match(/HOST (\d+) (\d+)/);
      if (m && !host) {
        host = { pid: Number(m[1]), port: Number(m[2]) };
        if (mode === 'sigterm') setTimeout(() => f.kill('SIGTERM'), 300);
        if (mode === 'sigkill') setTimeout(() => f.kill('SIGKILL'), 300);
      }
    });
    f.stderr.on('data', (d) => { out += d; });
    f.on('exit', done);
    setTimeout(() => { if (!ended) { f.kill('SIGKILL'); done(); } }, 30000);
  });
}
(async () => {
  console.log('harness: ' + IMPL);
  const leaked = [];
  for (const mode of ['finish', 'throw', 'exit', 'sigterm', 'sigkill', 'timeout']) {
    const r = await runFixture(mode);
    if (!r.host) { ok(false, `${mode}: the fixture never started its host: ${r.out.slice(0, 200)}`); continue; }
    let gone = false; for (let i = 0; i < 50 && !gone; i++) { gone = await refused(r.host.port) && (IMPL === 'old' ? pidGone(r.host.pid) : groupGone(r.host.pid)); if (!gone) await sleep(100); }
    if (!gone) leaked.push(r.host.pid);
    const clean = mode !== 'finish' || /LEFT 0/.test(r.out);
    ok(gone && clean, `${mode}: the case's snap_local.py is gone within 5 s of the case ending (port ${r.host.port} ${gone ? 'refused' : 'STILL OPEN'}${mode === 'finish' ? '; finish() reports ' + ((r.out.match(/LEFT (\d+)/) || [])[1] || '?') + ' survivors' : ''})`);
  }
  for (const p of leaked) { try { process.kill(p, 'SIGKILL'); } catch (e) { /* ends itself within 60 s */ } }   // the "before" run's leaks
  console.log(`${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
