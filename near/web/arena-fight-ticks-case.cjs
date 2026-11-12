// How fights move (board 3): the new renderer never moves a hit or KO tick and adds no sim input. In a real browser it draws
// the seeded 16-fighter dev brawl live; the same seed stepped headless in Python (no renderer) gives the sim's own events. The
// case compares the two: every hit, KO and attack the page received sits on the sim's tick, each drawn effect starts from that
// tick (never before it, beyond the documented look-ahead: the swing arc 60 ms, a beam's charge 150 ms), every SPEC item is
// drawn, and the page never writes to the arena socket. Frames of each item are saved for the reader's pass.
//
// Run:  NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/arena-fight-ticks-case.cjs [out-dir] [seconds]
//   FIGHT_CHROME=1  a headed Google Chrome (the real GPU) instead of headless Chromium.
// In a sandboxed lane (HTTPS_PROXY set) Chromium starts only with --single-process and software GL, at about 1 fps with 16
// fighters (main's renderer measures the same there). Every tick is still taken in (the buffer keeps 4.8 s), so the tick checks
// hold at any frame rate; whether an effect shorter than a frame got drawn is only checked at 20 fps or more, and the output
// says when it was not.
'use strict';
const { execFileSync } = require('child_process');
// the snap-in cases' host harness: each python host in its own process group under a guard, ended however this case ends
// (a finish, a crash, a signal, even node killed outright), and finish() reports any that survive
const HOSTS = require('./snapin/qa/hosts.cjs');
const net = require('net');
const path = require('path');
const fs = require('fs');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const SEED = 7, CROWD = 16, TICK_MS = 50;
const OUT = process.argv[2] || fs.mkdtempSync(path.join(require('os').tmpdir(), 'fight-ticks-'));
const SECONDS = +(process.argv[3] || 45);
const SIZES = [[1440, 900], [390, 844]];
// what each SPEC item may draw ahead of its own tick, from the buffer's look-ahead (final/SPEC.md sections 3-4)
const LEAD = { hit: 0, ko: 0, arc: 60, beam: 150, sweep: 150, wave: 0, shot: 0, lob: 0 };
const SPEC_ITEMS = ['hit', 'arc', 'shot', 'lob', 'beam', 'sweep', 'wave', 'ko'];

let failures = 0, checks = 0;
const ok = (cond, msg) => { checks++; if (!cond) { failures++; console.log('FAIL ' + msg); } };
const freePort = () => new Promise((res) => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });
const until = async (fn, ms) => { const end = Date.now() + ms; while (Date.now() < end) { if (await fn()) return true; await new Promise((r) => setTimeout(r, 200)); } return false; };

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const [wsPort, webPort] = [await freePort(), await freePort()];
  const quiet = { stdio: ['pipe', 'ignore', 'ignore'] };
  HOSTS.host(['-B', path.join(ROOT, 'near/arena/dev_brawl.py'), '--port', String(wsPort), '--seed', String(SEED), '--crowd', String(CROWD)], quiet);
  HOSTS.host(['-m', 'http.server', String(webPort), '--bind', '127.0.0.1', '--directory', path.join(ROOT, 'near')], quiet);
  const up = (port) => until(() => new Promise((res) => { const c = net.connect(port, '127.0.0.1', () => { c.end(); res(true); }); c.on('error', () => res(false)); }), 15000);
  ok(await up(wsPort) && await up(webPort), 'the dev brawl and the page server start');

  const lane = !!process.env.HTTPS_PROXY;
  const launch = () => process.env.FIGHT_CHROME ? chromium.launch({ channel: 'chrome', headless: false })
    : chromium.launch(lane ? { args: ['--single-process', '--no-zygote', '--use-gl=angle', '--use-angle=swiftshader-webgl', '--enable-unsafe-swiftshader'], proxy: { server: process.env.HTTPS_PROXY, bypass: '127.0.0.1,localhost' } } : {});
  const runs = [];
  for (const [w, h] of SIZES) {
    const browser = await launch();   // one browser per width: a single-process Chromium does not outlive its first page
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    const errs = []; page.on('pageerror', (e) => errs.push(String(e).slice(0, 200)));
    // the page must only read the arena socket: any send on a WebSocket is recorded
    await page.addInitScript(() => { const send = WebSocket.prototype.send; window.__wsSends = 0; WebSocket.prototype.send = function (d) { window.__wsSends++; return send.call(this, d); }; });
    await page.goto(`http://127.0.0.1:${webPort}/web/arena.html?ws=ws://127.0.0.1:${wsPort}`);
    await page.waitForFunction(() => window.ARENA && window.ARENA.fx && window.ARENA.actors, null, { timeout: 60000 });
    await page.evaluate(() => {
      const A = window.ARENA, L = window.__log = { hits: [], kos: [], attacks: [] };
      const onHit = A.actors.onHit.bind(A.actors), onKo = A.actors.onKo.bind(A.actors), onEvent = A.fx.fight.onEvent.bind(A.fx.fight);
      // a body not built yet (the page's first frame) takes its hold when it is built: read it then
      const later = (id, read) => { const t = A.actors.get(id); if (t) return read(t); return new Promise((res) => { const iv = setInterval(() => { const u = A.actors.get(id); if (u) { clearInterval(iv); res(read(u)); } }, 50); }); };
      L.pending = [];
      A.actors.onHit = (ev, tick, ...rest) => { const built = !!A.actors.get(ev.target); onHit(ev, tick, ...rest); const row = [tick, ev.source, ev.target, ev.move || '', null, built]; L.hits.push(row); if (built) { const t = A.actors.get(ev.target), hd = t.holds[t.holds.length - 1]; row[4] = hd ? hd.from : null; } };
      A.actors.onKo = (ev, tick, ...rest) => { onKo(ev, tick, ...rest); const row = [tick, ev.fighter, ev.source || null, null]; L.kos.push(row); L.pending.push(Promise.resolve(later(ev.fighter, (t) => { row[3] = t.koAt; }))); };
      A.fx.fight.onEvent = (ev, tick, ...rest) => { if (ev.kind === 'attack') L.attacks.push([tick, ev.fighter, ev.weapon]); return onEvent(ev, tick, ...rest); };
      const add = A.fx.fight.add.bind(A.fx.fight); L.taken = [];
      A.fx.fight.add = (r) => { L.taken.push([r.kind, r.tick]); return add(r); };
    });
    const tag = w + 'x' + h, saved = new Set(); let bodies = 0, peak = 0;
    const end = Date.now() + SECONDS * 1000;
    while (Date.now() < end) {
      const st = await page.evaluate(() => {
        const A = window.ARENA, rt = A.buffer.sample(performance.now()), ms = rt ? rt.tick * 50 : 0, now = {};
        for (const r of A.fx.fight.records) if (r.seen !== null && ms - r.seen < 250) now[r.kind] = true;
        return { now, bodies: A.actors.map.size, peak: A.fx.counts.peak };
      });
      bodies = Math.max(bodies, st.bodies); peak = Math.max(peak, st.peak);
      for (const k of Object.keys(st.now)) if (!saved.has(k)) { saved.add(k); await page.screenshot({ path: path.join(OUT, `fight-${tag}-${k}.png`), timeout: 120000 }).catch(() => saved.delete(k)); }
      await page.waitForTimeout(250);
    }
    const fps = await page.evaluate(() => new Promise((res) => { let n = 0; const t0 = performance.now(); const f = () => { n++; if (performance.now() - t0 < 3000) requestAnimationFrame(f); else res(n / 3); }; requestAnimationFrame(f); }));
    await page.evaluate(() => Promise.race([Promise.all(window.__log.pending), new Promise((r) => setTimeout(r, 5000))]));
    const res = await page.evaluate(() => ({ log: { ...window.__log, pending: undefined }, drawn: window.ARENA.fx.fight.log, drops: [...window.ARENA.fx.fight.drops.values()].filter(Boolean).map((d) => d.at), sends: window.__wsSends }));
    runs.push({ tag, errs, bodies, peak, fps, saved: [...saved], ...res });
    await browser.close();
  }
  const left = await HOSTS.finish();
  ok(left.length === 0, `no host this case started survives it (${left.length} left)`);

  const hi = Math.max(...runs.flatMap((r) => r.log.hits.concat(r.log.kos, r.log.attacks).map((e) => e[0]))) + 5;
  const sim = JSON.parse(execFileSync('python3', ['-I', path.join(ROOT, 'near/web/arena-fight-ticks.py'), '--seed', String(SEED), '--crowd', String(CROWD), '--to', String(hi)], { maxBuffer: 64 << 20 }).toString());
  const key = (e) => e.join('|');
  for (const r of runs) {
    ok(r.errs.length === 0, `${r.tag}: no page errors (${r.errs.join('; ')})`);
    ok(r.sends === 0, `${r.tag}: the page sends nothing on the arena socket (${r.sends} sends): it adds no sim input`);
    ok(r.bodies >= CROWD, `${r.tag}: the 16-fighter crowd is drawn (${r.bodies} bodies)`);
    ok(r.peak <= 150, `${r.tag}: at most 150 live effect shapes (peak ${r.peak})`);
    // the window the page saw: from its first to its last logged event
    const all = r.log.hits.concat(r.log.kos, r.log.attacks), lo = Math.min(...all.map((e) => e[0])), top = Math.max(...all.map((e) => e[0])) - 4;
    const simIn = (kind) => sim.events.filter((e) => e[1] === kind && e[0] >= lo && e[0] <= top);
    const pageHits = r.log.hits.filter((e) => e[0] >= lo && e[0] <= top).map((e) => key([e[0], e[1], e[2], e[3]]));
    const pageKos = r.log.kos.filter((e) => e[0] >= lo && e[0] <= top).map((e) => key([e[0], e[1], e[2]]));
    const pageAtk = r.log.attacks.filter((e) => e[0] >= lo && e[0] <= top).map((e) => key([e[0], e[1], e[2]]));
    const simHits = simIn('hit').map((e) => key([e[0], e[2], e[3], e[4]])), simKos = simIn('ko').map((e) => key([e[0], e[2], e[3]])), simAtk = simIn('attack').map((e) => key([e[0], e[2], e[4]]));
    // no tick moved and nothing invented: every event the page took in is one of the sim's, on the same tick. (A page that
    // stalls longer than its 4.8 s buffer, as a software-GL lane does during a screenshot, misses some: counted, not failed.)
    const inSim = (page, sim) => { const pool = new Map(); for (const k of sim) pool.set(k, (pool.get(k) || 0) + 1); return page.filter((k) => { const n = pool.get(k) || 0; if (!n) return true; pool.set(k, n - 1); return false; }); };
    const extraH = inSim(pageHits, simHits), extraK = inSim(pageKos, simKos), extraA = inSim(pageAtk, simAtk);
    ok(pageHits.length > 20 && extraH.length === 0, `${r.tag}: every hit the page took in is the sim's, on the sim's tick (${pageHits.length} of the sim's ${simHits.length} in ticks ${lo}-${top}; not the sim's: ${extraH.slice(0, 3).join(', ') || 'none'})`);
    ok(pageKos.length > 0 && extraK.length === 0, `${r.tag}: every KO the page took in is the sim's, on its tick (${pageKos.length} of ${simKos.length}; not the sim's: ${extraK.slice(0, 3).join(', ') || 'none'})`);
    ok(extraA.length === 0, `${r.tag}: every attack the page wound up is the sim's, on its tick (${pageAtk.length} of ${simAtk.length}; not the sim's: ${extraA.slice(0, 3).join(', ') || 'none'})`);
    r.missed = (simHits.length - pageHits.length) + (simKos.length - pageKos.length) + (simAtk.length - pageAtk.length);
    // the renderer's own clocks start at the event's tick: the hold, the KO beat and every drawn effect
    // (a hit on a body the page had not built yet, at its first frames, takes its hold when the body is built: counted apart)
    const offHold = r.log.hits.filter((e) => e[5] && e[4] !== e[0] * TICK_MS), unbuilt = r.log.hits.filter((e) => !e[5]).length;
    ok(offHold.length === 0, `${r.tag}: each hit's hold starts at its tick x 50 ms (${offHold.length} not: ${offHold.slice(0, 3).map((e) => JSON.stringify(e)).join(' ')}; ${unbuilt} before the body was built)`);
    ok(r.log.kos.every((e) => e[3] === e[0] * TICK_MS), `${r.tag}: each KO's beat starts at its tick x 50 ms`);
    const early = r.drawn.filter((d) => d.firstMs < d.tick * TICK_MS - (LEAD[d.kind] || 0) - 1e-6);
    ok(early.length === 0, `${r.tag}: no effect is drawn before its own tick, beyond its look-ahead (${early.slice(0, 3).map((d) => d.kind + '@' + d.tick + ' ' + d.firstMs).join(', ')})`);
    const kinds = new Set(r.drawn.map((d) => d.kind)), taken = new Set(r.log.taken.map((t) => t[0]).concat([...kinds]));
    ok(SPEC_ITEMS.every((k) => taken.has(k)), `${r.tag}: every SPEC item is taken in from real sim events (${SPEC_ITEMS.filter((k) => !taken.has(k)).join(', ') || 'none'} missing)`);
    if (r.fps >= 20) ok(SPEC_ITEMS.every((k) => kinds.has(k)), `${r.tag}: every SPEC item is drawn (${SPEC_ITEMS.filter((k) => !kinds.has(k)).join(', ') || 'none'} missing) at ${r.fps.toFixed(0)} fps`);
    else console.log(`NOT CHECKED ${r.tag}: drawn coverage at ${r.fps.toFixed(1)} fps (software GL); drawn: ${[...kinds].sort().join(' ')}`);
    // a beam and a shockwave hit land on the tick their effect is drawn from
    const beamTicks = new Set(r.log.taken.filter((t) => t[0] === 'beam').map((t) => t[1])), waveTicks = new Set(r.log.taken.filter((t) => t[0] === 'wave').map((t) => t[1]));
    const since = Math.min(...r.log.taken.map((t) => t[1])) + 10;   // a beam taken in before the case listened is not in its log
    const beamHits = r.log.hits.filter((e) => e[3] === 'beam' && e[0] >= since), waveHits = r.log.hits.filter((e) => e[3] === 'shockwave' && e[0] >= since);
    ok(beamHits.every((e) => beamTicks.has(e[0])), `${r.tag}: each beam hit is on its beam's tick (${beamHits.length})`);
    ok(waveHits.every((e) => waveTicks.has(e[0])), `${r.tag}: each shockwave hit is on its wave's tick (${waveHits.length})`);
    const koMs = new Set(r.log.kos.map((e) => e[0] * TICK_MS + 200));
    ok(r.drops.length > 0 && r.drops.every((at) => koMs.has(at) || at < lo * TICK_MS + 200), `${r.tag}: each dropped item flies from its KO when the freeze ends (${r.drops.length})`);
    console.log(`${r.tag} (${r.fps.toFixed(1)} fps; ${r.missed} sim events missed in stalls): ${pageHits.length} hits, ${pageKos.length} KOs, ${pageAtk.length} attacks in ticks ${lo}-${top}; drawn: ${[...kinds].sort().join(' ')}; peak ${r.peak} shapes; frames: ${r.saved.sort().join(' ')}`);
  }
  console.log(`arena-fight-ticks-case: ${checks - failures}/${checks} checks passed; frames in ${OUT}`);
  process.exit(failures ? 1 : 0);
}
main().catch((e) => { console.log('FAIL crashed: ' + (e && e.stack || e)); process.exit(1); });
