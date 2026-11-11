// SnapRoom.behaviour / SnapRoom.speech (the host's signed battle envelope v1) in a real browser, against a FIXTURE host:
// qa/battle_fixture_host.py = the real DEV arena (identity, join, terms, controls, sim) with only "arena.battle.v1" frames
// answered in the contract's shape, signed by the DEV room key; its inner ack words are the fixture's (labelled).
// Checks: a behaviour comes back as the signed battle_receipt with the ack verbatim (applied, and refused with fixes);
// a line with its emoji comes back posted; an empty line is refused before sending; a receipt with a wrong digest, a wrong
// binding or a wrong signature is refused ("did not check out") and never used; the session keeps its seat and later frames
// (renewals, more battle frames) still go through on the same sequence.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/battle_case.cjs
'use strict';
const { spawn } = require('child_process'), path = require('path');
const { chromium } = require('playwright');
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function start(args, ready) {
  const child = spawn('python3', ['-B', ...args], { cwd: REPO, stdio: ['ignore', 'pipe', 'pipe'] });
  return new Promise((resolve, reject) => {
    let out = ''; const t = setTimeout(() => reject(new Error('no start line: ' + out.slice(0, 300))), 30000);
    const on = (d) => { out += d; const m = ready(out); if (m) { clearTimeout(t); resolve({ child, m }); } };
    child.stdout.on('data', on); child.stderr.on('data', (d) => { out += d; });
    child.on('exit', (c) => reject(new Error('exited ' + c + ': ' + out.slice(0, 300))));
  });
}
(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  const arena = await start(['near/web/snapin/qa/battle_fixture_host.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m;
  const tamper = (mode) => fetch(arenaUrl + '/fixture/tamper', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode }) });
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const p = await (await b.newContext()).newPage(); const errs = [];
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
  try {
    await p.goto(base + '/web/snapin/index.html?step=wallet'); await p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
    const joined = await p.evaluate(async () => { try { await SnapRoom.join({ name: 'battlepip', preset: 'brawler-zap', termsVersion: '1' }); return SnapRoom.status().phase; } catch (e) { return 'ERR ' + e.message; } });
    ok(joined === 'in', `joined the DEV arena through the fixture host (${joined})`);
    const call = (fn, arg) => p.evaluate(async ([fn, arg]) => { try { const r = await SnapRoom[fn](arg); return { ok: true, r }; } catch (e) { return { ok: false, code: e.code, message: e.message }; } }, [fn, arg]);
    // a behaviour, applied
    let r = await call('behaviour', { v: 1, drives: { guard: 10, chase: 0, loot: 2 } });
    ok(r.ok && r.r.type === 'battle_receipt' && r.r.domain === 'arena.battle.receipt.v1' && r.r.kind === 'behaviour' && r.r.ack.summary === 'New drive recorded: chase 0 · guard 10 · loot 2 (fixture)' && /^[0-9a-f]{64}$/.test(r.r.request_digest),
      `behaviour → the checked battle_receipt, ack.summary verbatim: "${r.ok ? r.r.ack.summary : r.message}"`);
    // refused, with its fix
    r = await call('behaviour', { v: 1, target: 'goblin' });
    ok(r.ok && r.r.ack.state === 'refused' && r.r.ack.fixes[0] === 'Name a fighter in the ring, or say nearest.', `a refused behaviour comes back with its fix: "${r.ok ? r.r.ack.summary : r.message}"`);
    // speech
    r = await call('speech', { text: 'Hello, ring', emoji: '🦀' });
    ok(r.ok && r.r.kind === 'speech' && r.r.ack.status === 'posted' && r.r.ack.speech.emoji === '🦀' && r.r.ack.speech.text === 'Hello, ring', `speech → posted with its emoji: "${r.ok ? r.r.ack.summary : r.message}"`);
    r = await call('speech', { text: '   ' });
    ok(!r.ok && r.code === 'bad_message', 'an empty line is refused before anything is sent');
    // wrong receipts are refused and never used
    // every field the client checks, each made wrong on its own (the fixture signs after the change, so only that field is off)
    for (const mode of ['digest', 'binding', 'signature', 'kind', 'sequence', 'life_id', 'type', 'domain', 'key_id', 'no_ack', 'no_summary', 'summary_number']) {
      await tamper(mode);
      r = await call('behaviour', { v: 1, drives: { guard: 1 } });
      ok(!r.ok && r.code === 'bad_receipt' && /did not check out, so it was not used/.test(r.message), `a receipt with a wrong ${mode} is refused: "${r.message}"`);
    }
    // an unsigned error whose code is markup: never shown as given
    await tamper('error_html');
    r = await call('behaviour', { v: 1, drives: { guard: 1 } });
    ok(!r.ok && r.code === 'unknown_error' && !/[<>]/.test(r.message) && /unknown error/.test(r.message), `an error code that is not a plain word becomes "unknown error": "${r.message}"`);
    await tamper('');
    // the seat and the sequence survive: renewals keep the fighter in, later frames go through
    await sleep(12000);
    const st = await p.evaluate(() => SnapRoom.status().phase);
    r = await call('speech', { text: 'Still here', emoji: null });
    ok(st === 'in' && r.ok && r.r.ack.status === 'posted', `after the refused receipts the fighter keeps its seat (${st}) and the next frame goes through on the same sequence`);
    const players = await p.evaluate(async () => (await (await fetch('/dev/players')).json()).map((x) => x.fighter_id + ':' + x.state));
    ok(players.some((x) => /^dev-battlepip:/.test(x)), `/dev/players still lists the fighter (${players.join(', ')})`);
    ok(errs.length === 0, 'no page errors' + (errs.length ? ': ' + errs.join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 300)); }
  await b.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  arena.child.kill(); web.child.kill();
  console.log(`${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
