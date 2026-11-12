// When the DEV host holds new joins for a lapsed player's unread round
// result, only that player's own browser may read it. Two browsers on the real DEV arena:
//   X snaps in through the guide, closes every tab and lapses, so the host holds new joins for X's unread result.
//   Y (another browser) arrives and snaps in: Y waits on the host's countdown ("In the ring in N s…") and never asks
//   for the round's result.
//   X comes back and presses "Snap Xray Pip back in": X's browser says "Reading the last round's result…", reads it and
//   keeps it, which lifts the hold; X is back in the ring and Y gets in right after, still without reading it.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/held_result_case.cjs
'use strict';
const path = require('path'), fs = require('fs'), os = require('os');
const { chromium } = require('playwright');
const HOSTS = require('./hosts.cjs'), G = require('./board1_flow.cjs');
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const TMP = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'held-result-'));
(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  const arena = await HOSTS.start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await HOSTS.start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const guide = 'http://127.0.0.1:' + web.m + '/web/snapin/index.html';
  const present = async (name) => { try { const o = await (await fetch(arenaUrl + '/room/observe')).json(); return (o.fighters || []).some((f) => String(f.public_name).indexOf('DEV ' + name) === 0); } catch (e) { return true; } };
  const inRing = async (name) => { try { const o = await (await fetch(arenaUrl + '/room/observe')).json(); return (o.fighters || []).some((f) => String(f.public_name).indexOf('DEV ' + name) === 0 && f.state === 'ring'); } catch (e) { return false; } };
  const ready = (p) => p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
  let bx = null, by = null;
  try {
    // ---- X: in the ring through the guide's own state, then every tab closed until the seat lapses
    bx = await chromium.launchPersistentContext(path.join(TMP, 'x'), { args: ['--single-process', '--no-zygote'] });
    let reads = { x: 0, y: 0 };
    bx.on('request', (r) => { if (/\/room\/result/.test(r.url())) reads.x++; });
    await G.fakeNearAI(bx);
    let px = await bx.newPage(); const errs = []; px.on('pageerror', (e) => errs.push('x: ' + e.message));
    await G.snapIn(px, { url: guide, name: 'Xray Pip', preset: 'Survivor Beam' });   // through board 1's guide, as a player
    ok(await present('Xray Pip'), 'X (Xray Pip) is in the arena');
    // the host holds new joins for an unread result only once the round has passed its first segment (snap_local.py
    // maybe_restart): X stays in until the arena is past segment:0
    let seg = ''; for (let i = 0; i < 90 && !/segment:[1-9]/.test(seg); i++) { try { seg = (await (await fetch(arenaUrl + '/dev/clock')).json()).segment || ''; } catch (e) { seg = ''; } if (!/segment:[1-9]/.test(seg)) await sleep(1000); }
    ok(/segment:[1-9]/.test(seg), `the round is past its first segment (${seg})`);
    await px.close();
    let out = false; for (let i = 0; i < 90 && !out; i++) { out = !(await present('Xray Pip')); if (!out) await sleep(1000); }
    ok(out, 'every tab of X closed: its seat lapsed and it left the arena');
    // ---- Y: another browser arrives while the host holds the round for X's unread result
    by = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
    const cy = await by.newContext(); cy.on('request', (r) => { if (/\/room\/result/.test(r.url())) reads.y++; });
    const py = await cy.newPage(); py.on('pageerror', (e) => errs.push('y: ' + e.message));
    await py.goto(guide + '?step=wallet'); await ready(py);
    const seenY = []; const tickY = setInterval(() => { py.evaluate(() => SnapRoom.status().message).then((m) => seenY.push(m), () => {}); }, 400);
    py.evaluate(() => SnapRoom.join({ name: 'Yankee Pip', preset: 'survivor-beam', termsVersion: '1' }).catch(() => {}));
    await sleep(6000);
    console.log('  Y saw:', JSON.stringify([...new Set(seenY)]).slice(0, 400), '| Y phase:', await py.evaluate(() => SnapRoom.status().phase));
    const yWaits = seenY.filter((m) => /^In the ring in \d+ s/.test(m || ''));   // Y was never in: not "Back in the ring"
    ok(yWaits.length > 0 && reads.y === 0 && !(await present('Yankee Pip')), `Y waits on the host's countdown ("${yWaits[yWaits.length - 1] || 'none'}") and has not read the held result (reads ${reads.y})`);
    // ---- X comes back and snaps itself back in: its own browser reads its own result
    reads.x = 0; px = await bx.newPage(); px.on('pageerror', (e) => errs.push('x: ' + e.message));
    const seenX = []; await px.goto(guide + '?step=ring&from=arena'); await ready(px);
    await px.waitForSelector('[data-act="rejoin"]', { timeout: 30000 }).catch(async () => { console.log('  X shows:', (await px.evaluate(() => document.querySelector('#app').innerText)).replace(/\s+/g, ' ').slice(0, 300), '| draft:', (await px.evaluate(() => localStorage.getItem('trenchie.snapin.v1'))).slice(0, 300)); });
    const tickX = setInterval(() => { px.evaluate(() => SnapRoom.status().message).then((m) => seenX.push(m), () => {}); }, 200);
    await px.click('[data-act="rejoin"]');
    let xin = false; try { await px.waitForFunction(() => SnapRoom.status().phase === 'in', null, { timeout: 90000 }); xin = true; } catch (e) { /* reported */ }
    clearInterval(tickX);
    const kept = await px.evaluate(() => (SnapRoom.status().notes || []).some((n) => /kept the last round/.test(n.text)));
    ok(xin && await present('Xray Pip') && reads.x > 0 && kept && seenX.some((m) => /Reading the last round/.test(m || '')),
      `X's own browser says "Reading the last round's result…", reads it (${reads.x} reads), keeps it and is back in the ring`);
    let yin = false; for (let i = 0; i < 60 && !yin; i++) { yin = await py.evaluate(() => SnapRoom.status().phase === 'in') || await present('Yankee Pip'); if (!yin) await sleep(1000); }
    clearInterval(tickY);
    if (!yin) console.log('  Y at the end:', JSON.stringify(await py.evaluate(() => { const s = SnapRoom.status(); return { phase: s.phase, step: s.step, message: s.message, error: s.error }; })), '| Y saw after:', JSON.stringify([...new Set(seenY)].slice(-4)));
    ok(yin && reads.y === 0, `then Y gets in, never having read another fighter's result (Y reads ${reads.y})`);
    ok(errs.length === 0, 'no page errors' + (errs.length ? ': ' + errs.join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.stack || e).slice(0, 400)); }
  if (bx) await bx.close().catch(() => {}); if (by) await by.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  fs.rmSync(TMP, { recursive: true, force: true });
  console.log(`${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
