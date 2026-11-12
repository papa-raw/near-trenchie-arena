// SnapRoom.behaviour / SnapRoom.speech in a real browser against the REAL DEV arena (near/arena/snap_local.py with the
// battle host: signed battle envelope v1, the engine's behaviour ACK, the shared guarded feed). No fixture, no stand-in.
// Checks: a valid plan comes back as a battle_receipt whose signature and bindings room.js verified, with the engine's ACK
// (status applied or clipped, a summary string) used verbatim; a plan with an unknown condition is refused with its fix
// and keeps the last plan; a line is posted (or muted under its "guard list missing" label in a tree with no guard list),
// an emoji outside the persona's set is replaced and said so; a second line inside 10 s is refused; an empty line is refused
// before sending; the fighter keeps its seat and the next frames go through on the same sequence.
// Needs a tree where snap_local.py serves battle frames (the battle host); run from that tree's near/web/snapin/qa.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/battle_live_case.cjs
'use strict';
const { spawn } = require('child_process'), path = require('path');
const { chromium } = require('playwright');
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// hosts start through the shared harness: each ends with this case however it ends (qa/hosts.cjs)
const HOSTS = require('./hosts.cjs');
const start = (args, ready, cwd) => HOSTS.start(args, ready, cwd || REPO);
// battle_measure.EXAMPLE, the plan the engine's own measure uses
const PLAN = { v: 1, drives: { loot: 10, keep_away: 8, keep_away_radius: 5, chase: 3 }, gate: { target_hp_below_pct: 40, target_busy: true } };
const BAD = { v: 1, reflexes: [{ if: { hp_low: 30 }, then: { stance: 'flee' } }] };
// a line is posted, or (a tree with no guard list, B109) muted with that label: either is the host's labelled answer
const said = (r) => r.ok && (r.r.ack.status === 'posted' || (r.r.ack.status === 'muted' && r.r.ack.speech && r.r.ack.speech.label === 'guard list missing' && /guard list missing/.test(r.r.ack.summary)));
(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  const arena = await start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const p = await (await b.newContext()).newPage(); const errs = [];
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
  const call = (fn, arg) => p.evaluate(async ([fn, arg]) => { try { const r = await SnapRoom[fn](arg); return { ok: true, r }; } catch (e) { return { ok: false, code: e.code, message: e.message }; } }, [fn, arg]);
  const show = (r) => r.ok ? `${r.r.ack.status}: "${String(r.r.ack.summary).slice(0, 140)}"` : `${r.code}: ${r.message}`;
  try {
    await p.goto(base + '/web/snapin/index.html?step=wallet'); await p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
    const joined = await p.evaluate(async () => { try { await SnapRoom.join({ name: 'livepip', preset: 'brawler-zap', termsVersion: '1' }); return SnapRoom.status().phase; } catch (e) { return 'ERR ' + e.message; } });
    ok(joined === 'in', `joined the real DEV arena (${joined})`);
    await sleep(1500);
    let r = await call('behaviour', PLAN);
    ok(r.ok && r.r.type === 'battle_receipt' && r.r.domain === 'arena.battle.receipt.v1' && r.r.kind === 'behaviour' && r.r.key_id === 'room_key_a'
      && ['applied', 'clipped'].includes(r.r.ack.status) && typeof r.r.ack.summary === 'string' && r.r.ack.summary.length > 0 && /^[0-9a-f]{64}$/.test(r.r.request_digest),
      `a valid plan → the verified battle_receipt with the engine's ACK: ${show(r)}`);
    await sleep(700);
    r = await call('behaviour', BAD);
    ok(r.ok && r.r.ack.status === 'refused' && Array.isArray(r.r.ack.refused) && r.r.ack.refused.length > 0 && typeof r.r.ack.refused[0].fix === 'string' && /unknown condition 'hp_low'/.test(r.r.ack.summary),
      `a plan with an unknown condition is refused with its fix: ${show(r)}`);
    await sleep(700);
    r = await call('speech', { text: 'Hello, ring', emoji: '🦀' });
    ok(r.ok && r.r.kind === 'speech' && said(r) && r.r.ack.speech.emoji_fallback === true && /Emoji replaced/.test(r.r.ack.summary),
      `a line with an emoji outside the persona's set → the verified speech receipt, posted or labelled muted, the emoji replaced and said so: ${show(r)}${r.ok ? ' emoji=' + r.r.ack.speech.emoji : ''}`);
    r = await call('speech', { text: '   ' });
    ok(!r.ok && r.code === 'bad_message', `an empty line is refused before anything is sent (${r.ok ? 'sent' : r.code})`);
    r = await call('speech', { text: 'Too soon', emoji: null });
    ok(r.ok && r.r.ack.status !== 'posted', `a second line inside the 10 s feed cap is not posted, and says so: ${show(r)}`);
    await sleep(11000);
    const st = await p.evaluate(() => SnapRoom.status().phase);
    r = await call('speech', { text: 'Still here', emoji: null });
    ok(st === 'in' && said(r), `after 11 s the fighter keeps its seat (${st}) and the next line goes through on the same sequence: ${show(r)}`);
    const players = await p.evaluate(async () => (await (await fetch('/dev/players')).json()).map((x) => x.fighter_id + ':' + x.state));
    ok(players.some((x) => /livepip/.test(x)), `/dev/players lists the fighter (${players.join(', ')})`);
    ok(errs.length === 0, 'no page errors' + (errs.length ? ': ' + errs.join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 300)); }
  await b.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  arena.child.kill(); web.child.kill();
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  console.log(`${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
