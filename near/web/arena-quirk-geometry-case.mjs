import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import * as THREE from 'three';
import { CastDetails } from './arena/quirks.mjs';
import { Effects, hitArea } from './arena/fx.mjs';
import { Net } from './arena/net.mjs';
import { BudgetReplay } from './arena/budget-replay.mjs';
import { decode } from './arena/codec.mjs';
const cases = JSON.parse(await readFile(process.argv[2], 'utf8'));
let checks = 0;
for (const look of [null, 'old']) for (const scenario of cases) {
  const details = new CastDetails(); details.apply(scenario.metadata);
  const snap = decode(scenario.snapshot), scene = new THREE.Scene(), fx = new Effects(scene, {}, {}, {}, details, look);
  const positions = new Map(snap.fighters.map((f) => [f.id, { x: f.x / 1000, z: f.y / 1000, f }]));
  fx.sync(snap, snap, 0, snap.tick, 0, positions);
  const cast = snap.casts[0], mesh = fx.tele.get('c:' + cast.who + ':' + cast.resolveAt), expected = scenario.expected;
  const blink = cast.sig === 'blink_strike';
  const area = hitArea(mesh);
  assert.equal(area.r, blink ? 1.2 : Number(expected.radius_milli) / 1000, scenario.row + ' bound radius at ' + scenario.percent);
  if (expected.shape === 'cone') assert.ok(Math.abs(area.arc - Number(expected.arc_millidegrees) / 1000 * Math.PI / 180) < 1e-6, scenario.row + ' bound arc');
  assert.equal(mesh.position.x, Number(expected.x_milli) / 1000); assert.equal(mesh.position.z, Number(expected.y_milli) / 1000);
  assert.equal(area.shape, ['shockwave','bubble','chain_storm'].includes(cast.sig) ? 'ring' : expected.shape === 'cone' ? 'cone' : 'circle', 'signature visual shape stays approved');
  assert.equal(details.geometry(cast).radiusMilli, Number(expected.radius_milli), 'selection reach remains bound independently from the blink marker');
  if (blink) assert.equal(details.geometry(cast).strikeRadiusMilli, 1200);
  // A future removal must not erase the cast still on screen in the 150 ms buffer.
  details.apply({ ...scenario.metadata, full: false, revision: scenario.metadata.revision + 1, tick: cast.resolveAt, casts: { [cast.who + ':' + cast.resolveAt]: null }, rules: undefined });
  assert.ok(details.geometry(cast));
  checks++;
}
process.stdout.write(JSON.stringify({ ok: true, casts: checks, trinketSwap: true, rangePercentages: [100, 125, 150] }) + '\n');

const scenario = cases[0], details = new CastDetails(), snapshots = [], errors = [];
globalThis.WebSocket = class { constructor(url) { this.url = url; } close() {} };
const net = new Net('ws://127.0.0.1:8765', { onStatus: (status) => errors.push(status), onMetadata: (m) => { if (m) details.apply(m); else details.records.clear(); },
  onSnapshot: (snap) => { assert.ok(details.geometry(snap.casts[0]), 'metadata is installed before a snapshot is released'); snapshots.push(snap); } });
const send = (value) => net.ws.onmessage({ data: JSON.stringify(value) });
send(scenario.metadata); send(scenario.snapshot); assert.equal(snapshots.length, 1);
const revision = net.styles.revision;
send({ ...scenario.metadata, full: false, revision: revision + 1, casts: { broken: { radiusMilli: -1 } } });
assert.equal(net.bad, 1); assert.equal(net.styles.revision, revision, 'invalid metadata does not consume the style revision');
net.closed = true; net.ws.onclose(); assert.equal(details.records.size, 0); assert.equal(net.styles.map.size, 0);
const replayDetails = new CastDetails();
new BudgetReplay({ frames: [scenario.snapshot], metadata: [scenario.metadata], loadouts: Object.fromEntries(decode(scenario.snapshot).fighters.map((f) => [f.id, f.items])) },
  { push: (snap) => assert.ok(replayDetails.geometry(snap.casts[0]), 'recorded metadata precedes its frame') }, { onMetadata: (m) => replayDetails.apply(m) }).pump(0);
const snapshot = decode(scenario.snapshot), pos = new Map(snapshot.fighters.map((f) => [f.id, { f }])) , fallback = new Effects(new THREE.Scene(), {}, {}, {});
const warnings = [], warn = console.warn;
try {
  console.warn = (...args) => warnings.push(args.join(' '));
  fallback.sync(snapshot, snapshot, 0, snapshot.tick, 0, pos); fallback.sync(snapshot, snapshot, 0, snapshot.tick, 0, pos);
  assert.equal(warnings.length, 1, 'missing metadata warns once');
  fallback.details = replayDetails; fallback.sync(snapshot, snapshot, 0, snapshot.tick, 0, pos);
  assert.equal(hitArea([...fallback.tele.values()][0]).r, Number(scenario.expected.radius_milli) / 1000, 'late metadata replaces the fallback shape');
} finally { console.warn = warn; }
process.stdout.write(JSON.stringify({ ok: true, metadataBeforeSnapshot: true, disconnectClears: true, replay: true, fallbackWarnings: warnings.length }) + '\n');
