// The snap-in cases' host harness: every python host a case starts (near/arena/snap_local.py, near/web/snapin/serve.py)
// ends with the case, whatever ends it: a normal finish, a thrown error or rejection, process.exit, SIGINT/SIGTERM/SIGHUP,
// the hard timeout, or node itself killed outright (SIGKILL). On 2026-11-12 six arenas outlived their cases and burned
// ~30% CPU each for up to an hour, because each case killed its hosts only on its happy path.
//
// How: each host runs in its own process group (detached) under a small sh guard. The guard ends the host on SIGTERM and
// also when the case's end of a pipe closes, which happens however node exits, SIGKILL included. The case's own exit
// paths kill each group as well. finish() stops every group and reports any that survive, so a case can fail on a leak.
//
// usage:  const HOSTS = require('./hosts.cjs');
//         const arena = await HOSTS.start(['near/arena/snap_local.py', '--port', String(port)], (o) => ...ready match...);
//         ...; ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
// env:    CASE_TIMEOUT_MS (default 900000): the whole case's hard limit; on it, the hosts stop and the case exits 1.
'use strict';
const { spawn } = require('child_process'), path = require('path');
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
const live = new Set();
// sh: the host in the background; a TERM/INT/HUP ends it; a cat on the case's pipe ends it when the case is gone. The pipe
// is kept on fd 3 first: a non-interactive sh gives a background job /dev/null for stdin, so a bare cat would end at once.
const GUARD = 'exec 3<&0; "$@" 3<&- & h=$!; trap \'kill $h 2>/dev/null; exit 143\' TERM INT HUP; (cat <&3 >/dev/null; kill $h 2>/dev/null) & wait $h';
function alive(pgid) { try { process.kill(-pgid, 0); return true; } catch (e) { return e.code !== 'ESRCH'; } }
function killGroup(pgid, sig) { try { process.kill(-pgid, sig); } catch (e) { /* gone */ } }
/* start(args, ready, cwd): runs `python3 -B ...args` in its own group; resolves {child, m} once ready(output) is truthy */
function start(args, ready, cwd) {
  const child = spawn('sh', ['-c', GUARD, 'sh', 'python3', '-B', ...args], { cwd: cwd || REPO, stdio: ['pipe', 'pipe', 'pipe'], detached: true });
  live.add(child.pid);
  return new Promise((resolve, reject) => {
    let out = ''; const t = setTimeout(() => reject(new Error('no start line: ' + out.slice(0, 300))), 30000);
    const on = (d) => { out += d; const m = ready(out); if (m) { clearTimeout(t); resolve({ child, m }); } };
    child.stdout.on('data', on); child.stderr.on('data', (d) => { out += d; });
    child.on('exit', (c) => { clearTimeout(t); if (!child.done) reject(new Error('exited ' + c + ': ' + out.slice(0, 300))); });
  });
}
/* host(args, opts): the same guard for a case that starts a host and watches it itself: `python3 ...args` as given (put -B
   in args), opts.cwd, opts.env and opts.stdio ([_, out, err]: 'pipe' or 'ignore'; stdin is always the guard's pipe).
   Returns the child at once. */
function host(args, opts) {
  opts = opts || {}; const io = opts.stdio || ['pipe', 'pipe', 'pipe'];
  const child = spawn('sh', ['-c', GUARD, 'sh', 'python3', ...args], { cwd: opts.cwd || REPO, env: opts.env || process.env, stdio: ['pipe', io[1], io[2]], detached: true });
  live.add(child.pid); return child;
}
function stopAllSync() { live.forEach((g) => killGroup(g, 'SIGKILL')); }
/* finish(): stop every host group this case started; resolves to the groups still alive after 5 s (empty when clean) */
async function finish() {
  live.forEach((g) => killGroup(g, 'SIGTERM'));
  for (let i = 0; i < 50 && [...live].some(alive); i++) await new Promise((r) => setTimeout(r, 100));
  live.forEach((g) => { if (alive(g)) killGroup(g, 'SIGKILL'); });
  await new Promise((r) => setTimeout(r, 200));
  const left = [...live].filter(alive); live.clear(); return left;
}
process.on('exit', stopAllSync);
for (const [sig, n] of [['SIGINT', 130], ['SIGTERM', 143], ['SIGHUP', 129]]) process.on(sig, () => { stopAllSync(); process.exit(n); });
process.on('uncaughtException', (e) => { console.log('FAIL case crashed: ' + String(e && e.stack || e).slice(0, 400)); stopAllSync(); process.exit(1); });
process.on('unhandledRejection', (e) => { console.log('FAIL case crashed (unhandled rejection): ' + String(e && e.stack || e).slice(0, 400)); stopAllSync(); process.exit(1); });
const limit = Number(process.env.CASE_TIMEOUT_MS) || 900000;
setTimeout(() => { console.log('FAIL case timed out after ' + Math.round(limit / 1000) + ' s; its hosts were stopped'); stopAllSync(); process.exit(1); }, limit).unref();
module.exports = { start, host, finish, alive, REPO };
