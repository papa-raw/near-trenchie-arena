// The arena page: connect to the spectator stream, hold it in the 150 ms buffer, draw it.
import * as THREE from 'three';
import { SnapshotBuffer, TICK_MS } from './buffer.mjs';
import { Net } from './net.mjs';
import { Social } from './social.mjs';
import { Moments } from './moments.mjs';
import { ChainHold } from './chain-hold.mjs';
import { createStage } from './scene.mjs';
import { CastDetails } from './quirks.mjs';
import { ActorInstances } from './instances.mjs';
import { guardedFrame } from './guard.mjs';
import { Actors, weaponRenderScale } from './actors.mjs';
import { CamFollow } from './cam-follow.mjs';
import { Effects } from './fx.mjs';
import { milliToWorld, lerpAngle, pickMilli, ARENA_RADIUS_MILLI, MILLI } from './frame.mjs';
import { Hud } from './hud.mjs';
import { phoneStrip } from './hud-layout.mjs';
import { Budget, FrameGate, measureIdle } from './budget.mjs';
import { BudgetReplay, budgetEffects } from './budget-replay.mjs';
import { loadItems } from '../items3d.js';
import { hasBounty } from './style.mjs';
import { Sound, soundForEvent } from './sound.mjs';
import { SignFeed, signUrl } from './sign.mjs';
import { Leaderboard } from './leaderboard.mjs';
import { RosterFeed, rosterUrl } from './roster.mjs';
import { Inset, pickFighter } from './inset.mjs';
import { arenaView } from './follow.mjs';
import { Slowmo } from './slowmo.mjs';
import { LOOK3, ROSTER, ITEMS } from '../art/index.js';

const $ = (id) => document.getElementById(id);
const statusEl = $('status'), diagEl = $('diag');
const qs = new URLSearchParams(location.search);
if (qs.has('diag')) document.body.classList.add('diag');
// Hosted over https (behind nginx): the spectator socket is wss://<this host>/arena-ws. Local: the DEV host's own port.
const WS_URL = qs.get('ws') || (location.protocol === 'https:' ? 'wss://' + location.host + '/arena-ws'
                                                               : 'ws://' + (location.hostname || '127.0.0.1') + ':8765');

function setStatus(text, cls) { statusEl.textContent = text; statusEl.className = cls || ''; }

function loadScript(src) {
  return new Promise((res, rej) => { const s = document.createElement('script'); s.src = src; s.onload = res; s.onerror = () => rej(new Error('script failed: ' + src)); document.head.appendChild(s); });
}

async function main() {
  const KITS = window.KITS = { roster: ROSTER }; // the HUD art looks short tags up here
  await loadScript('./hud-art/hud-art.js');
  window.THREE = THREE; window.LOOK3 = LOOK3;
  await loadScript('./snapin/art/parts-s3.js');
  // the wall sign's plank (the shared art kit) and a player's face on it (the snap-in portrait still); both optional
  loadScript('./snapin/art/portrait.js').catch((e) => console.warn('player faces unavailable', String(e)));
  const stage = createStage($('stage'), LOOK3, { dprCap: qs.has('dpr') ? +qs.get('dpr') : 2, shadowMap: qs.has('shadow') ? +qs.get('shadow') : 1024, dprForce: qs.has('dprforce') ? +qs.get('dprforce') : 0 });
  const { renderer, scene, camera, view } = stage;
  const itemRenderer = await loadItems(ITEMS);
  const details = new CastDetails();
  const actors = new Actors(scene, LOOK3, KITS, itemRenderer, { arenaQuality: qs.get('tessellation') === 'reduced' }), fx = new Effects(scene, LOOK3, ITEMS, itemRenderer, details);
  const instances = new ActorInstances(scene);
  const cam = new CamFollow(stage);   // board 3: on a phone, the camera follows the action
  // a dropped weapon lies at the size it was held: the grip's world scale at mount scale 1, x the held scale, over the floor's 1.5
  fx.floorWeaponScale = (id) => ((ITEMS[id] || {}).slot === 'weapon' ? weaponRenderScale(itemRenderer, id) * (actors.mountWorldScale() || 1) * 0.95 / 1.5 : 1);
  const buffer = new SnapshotBuffer();
  const fps = qs.has('fps') ? +qs.get('fps') : 0, gate = new FrameGate(fps);
  const budget = qs.has('budget') ? new Budget(+qs.get('budget') || 60, await measureIdle(renderer, camera, 90, fps), { throttled: qs.get('throttle') === '4' }) : null;
  let replay = null, stress = null;
  if (qs.has('replay')) {
    const response = await fetch(qs.get('replay'));
    if (!response.ok) throw new Error('Recording: HTTP ' + response.status);
    replay = new BudgetReplay(await response.json(), buffer, { crowd: +(qs.get('crowd') || 0), teleN: Math.max(0, +(qs.get('tele_n') || 0)), onMetadata: (message) => details.apply(message) });
    stress = budgetEffects(scene);
    setStatus('Recorded arena', 'replay');
  }
  const budgetWarmUntil = performance.now() + 4000;
  let teleMin = Infinity, teleMax = 0;   // live telegraphs over the measured frames (the budget log states both)
  const hud = new Hud({ stage, actors, KITS, ITEMS, root: $('world'), status: statusEl, itemRenderer, LOOK3 }); hud.details = details;
  // the social frame: speech into the one merged feed, each fighter's life (its prediction and KOs) into the tags
  const social = new Social(KITS, { onSay: (item) => hud.feed.push(item), onLives: (map) => hud.lives.receive(map, performance.now()) }); hud.names = social.names;
  const moments = new Moments(ITEMS, (id) => hud.tagOf(id)); // big moments for the feed (Battle mode)
  const chainHold = new ChainHold($('chain-hold'));
  if (!replay) chainHold.startHealth('/dev/health');
  addEventListener('pagehide', () => chainHold.stopHealth());
  addEventListener('pageshow', () => { if (!replay) chainHold.startHealth('/dev/health'); });
  if (replay) hud.styles = new Map(Object.entries(replay.record.styles));
  if (qs.has('nohud')) hud.remount = function () {}; // diagnostics only: the budget test with the panel art's 4 Hz redraw switched off
  if (!replay) { const feed = new SignFeed(signUrl(WS_URL), (json) => hud.setBoards(json)); window.SIGN_FEED = feed.start(); } // the wall sign's two boards, from the public record
  const inset = new Inset({ stage, tagOf: (id) => hud.tagOf(id) }), slowmo = new Slowmo(buffer);
  let lastPos = new Map(), lastLead = null;
  $('stage').addEventListener('click', (ev) => {
    const ids = [...lastPos.keys()].filter((id) => lastPos.get(id).state === 'alive');
    const id = pickFighter(ids, (q) => { const p = lastPos.get(q); return p ? hud.toScreen(p.x, 0.8, p.z) : null; }, ev.clientX, ev.clientY);
    if (id) inset.follow(id); else inset.clear();
    followView.clicked();
  });
  // ?follow=<fighter id> (the snap-in guide's "Watch your trenchie"): open the follow view on it once it is in the ring
  const followWant = qs.get('follow');
  // window.ArenaView (board 1's Follow button): follow(id) now or once it is back in the ring, unfollow(), followed()
  const followView = window.ArenaView = arenaView({ inset, hud, positions: () => lastPos,
    announce: (id) => dispatchEvent(new CustomEvent('arenaview:follow', { detail: { id } })) });
  const closeInset = inset.close.onclick; inset.close.onclick = () => { closeInset(); followView.clicked(); };
  if (followWant) window.ArenaView.follow(followWant);
  // the ring's outline on screen, its edge projected at 64 points: the page's own panels (the order box) keep off it
  window.__arenaRingOutline = () => { const r = ARENA_RADIUS_MILLI / MILLI + 0.3, out = []; for (let i = 0; i < 64; i++) { const a = i * Math.PI / 32, p = hud.toScreen(Math.cos(a) * r, 0, Math.sin(a) * r); out.push([p.x, p.y]); } return out; };
  const board = new Leaderboard({ isHouse: (id) => ROSTER.some((r) => r.trenchieId === id) }); hud.board = board;   // the top-left KO banner's counts (as at ebb97a0)
  if (!replay) window.ROSTER_FEED = new RosterFeed(rosterUrl(WS_URL), (r) => { hud.roster = r; }).start();   // the host's public roster (the banner's label)
  const sound = new Sound(); hud.soundState = sound.state; sound.onChange = (st) => { hud.soundState = st; }; hud.onMute = () => sound.toggle();
  const pan = (p) => (p ? Math.max(-0.8, Math.min(0.8, (hud.toScreen(p.x, 0.5, p.z).x - innerWidth / 2) / (innerWidth / 2))) : 0);
  const kos = new Map();
  let netState = { state: 'connecting' }, firedTick = -1, lookTick = -1, lastNow = performance.now(), frames = 0, dropped = 0;
  const net = replay ? { frames: 0, bad: 0 } : new Net(WS_URL, {
    onSocial: (message) => social.apply(message),
    onMetadata: (message) => { if (message) details.apply(message); else { details.records.clear(); details.rules = null; details.revision = -1; details.tick = -1; } },
    onStyles: (styles) => { hud.styles = styles; },
    onSnapshot: (s) => { buffer.push(s, performance.now()); },
    onStatus: (st) => { netState = st; if (st.state === 'live') setStatus('Live', 'live'); else if (st.state === 'bad-frame') setStatus('Bad frame: ' + st.message, 'warn'); else setStatus(st.state === 'connecting' ? 'Connecting to ' + st.url : 'No arena at ' + st.url + ' — retrying', 'warn'); },
  });

  // On a phone with board 1's panel open the arena draws only in the strip above the panel, with the ring framed between
  // the sign's bottom and the panel's top (board 1's 390 frame keeps the ring in view); otherwise the whole window.
  let fitKey = '';
  const fit = () => {
    const strip = phoneStrip(document, innerWidth, innerHeight), h = strip ? strip.h : innerHeight, key = innerWidth + 'x' + innerHeight + ':' + (strip ? strip.h + '/' + strip.top : '');
    if (key === fitKey) return;
    fitKey = key;
    const canvas = $('stage'); canvas.style.height = strip ? h + 'px' : ''; canvas.style.bottom = strip ? 'auto' : '';
    stage.resize(innerWidth, h, strip ? { top: strip.top + 6, bottom: 6 } : undefined); hud.resize(innerWidth, innerHeight);
  };
  addEventListener('resize', fit); addEventListener('snappanel', () => requestAnimationFrame(fit)); fit();

  // bench seats: the north-west shore arc, 2.4 tiles apart
  function benchSeats(ids) {
    const r = 13.7, step = 2.4 / r, map = new Map();
    ids.slice().sort().forEach((id, i) => { const a = (225 + 0) * Math.PI / 180 + (i - (ids.length - 1) / 2) * step; map.set(id, { x: Math.round(Math.cos(a) * r * 1000), y: Math.round(Math.sin(a) * r * 1000), dir: 45 }); });
    return map;
  }

  const frame = guardedFrame(function drawFrame(nowMs) {
    if (!gate.ready(nowMs)) return;
    if (replay) replay.pump(nowMs);
    const dt = Math.min(100, nowMs - lastNow); lastNow = nowMs; frames++;
    if (!replay) slowmo.update(nowMs);
    const s = buffer.sample(nowMs);
    if (!s) { renderer.render(scene, camera); hud.idle(nowMs); chainHold.layout(); return; }
    const rt = s.tick, a = s.a, b = s.b, k = s.k;

    // events: anything the viewer has not yet seen. Attacks are read ahead (up to 3 ticks) so the wind-up leads the strike.
    const posOf = (snap, id) => { const f = snap.fighters.find((q) => q.id === id); return f ? milliToWorld(f.x, f.y) : null; };
    const posAt = (snap) => (id) => { const f = snap.fighters.find((q) => q.id === id); return f ? { ...milliToWorld(f.x, f.y), dir: f.dir } : null; };
    const tip = (id) => actors.tip(id);
    for (const snap of buffer.ring) {
      if (snap.tick > lookTick && snap.tick <= rt + 3.2) {
        lookTick = snap.tick;
        fx.fight.onObjects(snap, posAt(snap), tip, (c) => { const g = details.geometry(c); return g && g.radiusMilli ? g.radiusMilli / 1000 : null; });   // shots, lobs, beams, sweeps and shockwaves, from every snapshot
        for (const ev of snap.events) if (ev.kind === 'attack') {
          const f = snap.fighters.find((q) => q.id === ev.fighter); const d = f ? f.dir : 0;
          // the one a swing slams: its first hit on this tick (a swing's hits land on its attack tick), else its target
          const hit = snap.events.find((h) => h.kind === 'hit' && h.source === ev.fighter && h.move === ev.weapon);
          const target = hit ? hit.target : f && f.target;
          actors.onAttack(ev, snap.tick, { dx: Math.cos(d * Math.PI / 180), dz: Math.sin(d * Math.PI / 180), src: posOf(snap, ev.fighter), dst: target ? posOf(snap, target) : null, target });
          fx.fight.onEvent({ ...ev, target }, snap.tick, posAt(snap), tip);   // the slam's floor arc and the head's trail
        }
      }
      if (snap.tick > firedTick && snap.tick <= rt) {
        firedTick = snap.tick;
        const ambushed = new Set();   // a KO that was an ambush is one KO line that says so
        for (const ev of snap.events) for (const m of moments.onEvent(ev, snap)) { if (m.kind === 'ambush') ambushed.add(m.other); else hud.onMoment(m); }
        for (const ev of snap.events) {
          if (ev.kind === 'hit') {
            actors.onHit(ev, snap.tick, nowMs, posOf(snap, ev.source), posOf(snap, ev.target));
            fx.fight.onEvent(ev, snap.tick, posAt(snap), tip);
            const p = posOf(snap, ev.target); sound.play(soundForEvent(ev), nowMs, pan(p));
          } else if (ev.kind === 'ko') {
            if (ev.fighter === lastLead && (kos.get(ev.fighter) || 0) >= 2) slowmo.trigger('leader_ko', nowMs); // the hour's leader goes down
            actors.onKo(ev, snap.tick, nowMs, posOf(snap, ev.source), posOf(snap, ev.fighter)); const p = posOf(snap, ev.fighter); sound.play(soundForEvent(ev), nowMs, pan(p));
            fx.fight.onEvent(ev, snap.tick, posAt(snap), tip);
            if (ev.source) { kos.set(ev.source, (kos.get(ev.source) || 0) + 1); board.onKo(ev.source, nowMs, ev.fighter); }
            hud.onKo(ev, ambushed.has(ev.fighter));
          } else if (ev.kind === 'respawn') {
            // a life that predicts: its card stamps first and the body drops after it (prejump.mjs)
            actors.onRespawn(ev, snap.tick, nowMs, hud.onRespawn(ev, nowMs)); sound.play(soundForEvent(ev), nowMs, pan(posOf(snap, ev.fighter)));
          }
          else if (ev.kind === 'attack') {
            const f = snap.fighters.find((q) => q.id === ev.fighter), p = f && milliToWorld(f.x, f.y);
            sound.play(soundForEvent(ev), nowMs, pan(p));
          } else if (ev.kind === 'grab' || ev.kind === 'floor_loss' || ev.kind === 'signature') {
            { const it = ITEMS[ev.row]; if (ev.kind === 'grab' && it && it.tier === 'legendary' && it.origin !== 'house:' + ev.fighter && !ev.destroyed) slowmo.trigger('steal', nowMs); } // a legendary lands in a stranger's hands
            if (ev.kind !== 'floor_loss') sound.play(soundForEvent(ev, { tier: (ITEMS[ev.row] || {}).tier }), nowMs, pan(posOf(snap, ev.fighter)));
          }
        }
        for (const m of moments.onSnapshot(snap)) hud.onMoment(m);   // after the KO lines: a legendary knocked loose joins its KO's line
        fx.fight.onDrops(snap);   // after this tick's KOs: each KO's drop flies from its body
      }
    }

    // interpolate fighters by id between the two snapshots around the render tick
    const prev = new Map(a.fighters.map((f) => [f.id, f]));
    const fighters = b.fighters.map((f) => {
      const p = prev.get(f.id) || f;
      const jump = p.status !== f.status || Math.abs(p.x - f.x) + Math.abs(p.y - f.y) > 3000;
      return { ...f, x: jump ? f.x : p.x + (f.x - p.x) * k, y: jump ? f.y : p.y + (f.y - p.y) * k, dir: lerpAngle(p.dir, f.dir, k) };
    });
    const benchIds = fighters.filter((f) => f.status !== 0).map((f) => f.id);
    // a fighter in a telegraph or its signature holds the stick out (no shouldering): its cast, or its sweep still turning
    const casting = new Set(b.casts.map((c) => c.who));
    for (const o of b.objects) if (o.kind === 'beam_sweep') { const w = fx.fight.ownerOf(b, o); if (w) casting.add(w); }
    const pos = actors.update(fighters, rt, nowMs, dt, benchSeats(benchIds), casting);
    board.presence(fighters.filter((f) => f.status !== 2).map((f) => f.id), nowMs);
    lastPos = pos;
    fx.sync(a, b, k, rt, nowMs, pos);
    const hunted = fighters.filter((f) => hasBounty(f, ITEMS));
    fx.setBounty(hunted.map((f) => pos.get(f.id)), nowMs);
    hud.bounties = new Set(hunted.map((f) => f.id));
    hud.syncDrops(b.drops, nowMs);
    fx.tick(nowMs, rt, actors);
    if (stress) {
      const count = Math.max(0, 150 - fx.liveShapes);
      stress.children.forEach((m, i) => { m.visible = i < count; m.rotation.y = nowMs / 800 + i; });
    }

    // the crown over the KO leader
    const top1 = hud.leader(), lead = top1 && pos.get(top1) && pos.get(top1).state === 'alive' ? top1 : null; // the sign's KO leader of the hour
    fx.setCrown(lead ? pos.get(lead) : null, 1.55, nowMs);

    stage.placeCamera(0, 0);
    cam.apply(nowMs, rt * TICK_MS, fx.fight.records, inset.followId, (id) => { const a = actors.get(id); return a && a.h.object3d.visible ? a.h.object3d.position : null; });
    stage.lights.update(new THREE.Vector3(0, 0, 0));
    instances.sync(actors);
    const r0 = performance.now();
    renderer.render(scene, camera);
    if (budget && nowMs > budgetWarmUntil) teleMin = Math.min(teleMin, fx.tele.size), teleMax = Math.max(teleMax, fx.tele.size);
    if (budget && nowMs > budgetWarmUntil) budget.sample(performance.now() - r0, nowMs, renderer, { teleLook: fx.teleLook, teleStress: replay ? replay.teleN : 0, telegraphsLive: { min: teleMin, max: teleMax }, fighters: fighters.length, fxPeak: fx.counts.peak, bufferDelayMs: +buffer.delayMs.toFixed(1), jitterMs: +buffer.jitter.toFixed(1), late: buffer.late, lever: qs.get('lever') || 'none', fpsCap: fps, recordingSeed: replay ? replay.record.seed : null, crowdSeed: replay ? replay.crowd : null, effectShapes: stress ? 150 : fx.liveShapes, primitiveTypes: replay ? replay.record.primitiveTypes : null });
    lastLead = lead;
    if (inset.followId !== null && !pos.get(inset.followId)) { inset.clear(); hud.followed = null; }
    inset.render(inset.followId !== null ? pos.get(inset.followId) : null); // the follow view, drawn after the main pass
    hud.frame({ pos, lead, nowMs, delayMs: buffer.delayMs });
    chainHold.layout();

    if (diagEl && document.body.classList.contains('diag')) {
      diagEl.textContent = 'tick ' + rt.toFixed(1) + ' | delay ' + buffer.delayMs.toFixed(0) + ' ms | jitter ' + buffer.jitter.toFixed(1) + ' | late ' + buffer.late + ' | frames ' + net.frames + ' | bad ' + net.bad + '\n' +
        'fx ' + fx.counts.effects + ' (peak ' + fx.counts.peak + ') | draws ' + renderer.info.render.calls + ' tris ' + renderer.info.render.triangles + ' | ppt ' + view.ppt.toFixed(1);
    }
  }, requestAnimationFrame, console.error, () => setStatus('Render error', 'warn'));
  requestAnimationFrame(frame);
  window.ARENA = { social, chainHold, details, instances, itemRenderer, replay, budget, stress, stage, actors, fx, buffer, net, hud, kos, sound, inset, slowmo, THREE, LOOK3, KITS, ITEMS, pick: (nx, ny) => pickMilli(nx, ny, camera) };
}

main().catch((e) => { console.error(e); setStatus('Could not start: ' + (e && e.message || e), 'warn'); });
