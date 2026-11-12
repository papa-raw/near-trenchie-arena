// rejoin-red, corner-pick M1 and guide-retry-ratelimit: the browser client's member-read expiry, the in-ring card's
// line for a queued pick, and the join retries while the chain read is out.
//   node near/web/snapin/test_join_pacing.cjs
// Before:
//  - room.js asked for a member read expiring at its now + 15 000 ms, the room's whole window, so a clock 1 ms ahead
//    of the room's was refused proof_required (snap_client.py had the same; LiveRejoin failed that way);
//  - the card said "not accepted" for a pick the room had locked and queued (room_full / ownership_unavailable);
//  - room.js asked again every 2 s, 15 times, while the room allows 5 join attempts a minute and a try costs 2
//    (a challenge and a join): a chain read slower than about 4 s ended in rate_limited.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { execFileSync } = require('child_process');
const ROOT = path.resolve(__dirname, '../../..');
let n = 0;

const ctx = { console, TextEncoder, TextDecoder, document: { currentScript: null } };
ctx.globalThis = ctx;
vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'ui.js'), 'utf8'), ctx);
vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'room.js'), 'utf8'), ctx);
const U = ctx.SnapUI, R = ctx.SnapRoom;

// ---- 1. the member-read expiry leaves 1 s for a client clock ahead of the room's, the same in both clients
const py = execFileSync('python3', ['-I', '-c', 'import sys; sys.path.insert(0, sys.argv[1]); from near.arena import snap_client as c; from room import service as s; print(c._MEMBER_READ_TTL_MS, s._OWNER_READ_WINDOW_MS)', ROOT]).toString().trim().split(' ').map(Number);
assert.strictEqual(R.MEMBER_READ_TTL_MS, py[0], 'room.js and snap_client.py ask for the same read expiry'); n++;
assert.strictEqual(py[1] - R.MEMBER_READ_TTL_MS, 1000, 'a 1 s margin under the room window ' + py[1]); n++;

// ---- 2. the in-ring card's "Prediction for this life"
const lines = [
  [null, 'not sent yet'],
  [{ state: 'accepted' }, 'locked in'],
  [{ state: 'queued', reason: 'room_full' }, 'locked in; waiting for a seat'],
  [{ state: 'queued', reason: 'ownership_unavailable' }, 'locked in; waiting for a seat'],
  [{ state: 'queued', reason: 'room_full', seated: 1794511532564 }, 'locked in'],
  [{ state: 'none' }, 'none (your AI chose none)'],
  [{ state: 'refused', reason: 'prediction_closed' }, 'not accepted'],
];
for (const [lp, want] of lines) { assert.strictEqual(U.pickLine(lp), want, JSON.stringify(lp)); n++; }
const app = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');
assert.ok(/U\.line\('Prediction for this life', esc\(U\.pickLine\(lp\)\)\)/.test(app), 'the in-ring card reads U.pickLine'); n++;
assert.ok(/lastPick\.seated \? '\+seated'/.test(app), 'the card redraws when a queued pick is seated'); n++;
// room.js marks a queued pick seated when the public view shows the fighter in the ring, never on the bench
const view = (state) => ({ fighters: [{ nft_token_id: 'other', state: 'ring' }, { nft_token_id: 'tok', state }] });
assert.strictEqual(R.seatSeen(view('ring'), 'tok'), true); n++;
assert.strictEqual(R.seatSeen(view('disconnected'), 'tok'), true); n++;
assert.strictEqual(R.seatSeen(view('bench'), 'tok'), false); n++;
assert.strictEqual(R.seatSeen({ fighters: [{ nft_token_id: 'other', state: 'ring' }] }, 'tok'), false); n++;
assert.strictEqual(R.seatSeen(null, 'tok'), false); n++;

// ---- 3. join retries against a model of the room's limits, on virtual time
// The model follows the code: room/service.py _attempt (5 a minute per account and per address, on the room's
// clock; a challenge and a join each count; a refused attempt is not counted), room/identity.py resolve (a
// challenge is used up by its join), snap_local.py start_hold (a challenge or join freezes the room's clock for
// 10 s, a new freeze only 5 s after the last ended; vnow is sim time) and the X-Dev-Now / X-Dev-Paused headers
// room.js's now() reads.
function room(landsAfterMs) {
  const m = { real: 0, room: 1794511500000, holdFrom: -1e9, holdUntil: -1e9, attempts: [], limited: 0, tries: 0, seen: null };
  m.advance = (dt) => {   // the room's clock stands still while a hold is on
    const from = m.real, to = m.real + dt;
    const paused = Math.max(0, Math.min(to, m.holdUntil) - Math.max(from, m.holdFrom));
    m.real = to; m.room += dt - paused;
  };
  m.reply = () => { m.seen = { now: m.room, at: m.real, paused: m.real < m.holdUntil }; };
  m.clientRoom = () => (m.seen.paused ? m.seen.now : m.seen.now + (m.real - m.seen.at));   // room.js now()
  m.hold = () => { if (m.real >= m.holdUntil + 5000) { m.holdFrom = m.real; m.holdUntil = m.real + 10000; } };
  m.attempt = () => {
    m.attempts = m.attempts.filter((t) => t > m.room - 60000);
    if (m.attempts.length >= 5) { m.limited++; return false; }
    m.attempts.push(m.room); return true;
  };
  m.tryOnce = async () => {   // one try: a fresh challenge, then a join with it
    m.tries++;
    m.hold(); m.advance(40);
    const challenged = m.attempt(); m.reply();
    if (!challenged) return { type: 'error', code: 'rate_limited' };
    m.hold(); m.advance(60);
    const joined = m.attempt(); m.reply();
    if (!joined) return { type: 'error', code: 'rate_limited' };
    if (m.real < landsAfterMs) return { type: 'error', code: 'ownership_unavailable' };
    return { type: 'grant', state: 'accepted' };
  };
  m.reply();
  return m;
}
async function newClient(landsAfterMs) {
  const m = room(landsAfterMs), said = [];
  const grant = await R.joinWithWait(m.tryOnce, {
    room: m.clientRoom, real: () => m.real,
    sleep: async (ms) => { m.advance(ms); }, refresh: async () => { m.advance(20); m.reply(); },
    waiting: (secs) => said.push(secs),
  });
  return { m, grant, said };
}
async function oldClient(landsAfterMs) {   // the loop this replaces: every 2 s, 15 times
  const m = room(landsAfterMs);
  let grant;
  for (let attempt = 0; ; attempt++) {
    grant = await m.tryOnce();
    if (grant.code === 'ownership_unavailable' && attempt < 15) { m.advance(2000); continue; }
    break;
  }
  return { m, grant };
}

(async () => {
  // positive control: the model catches the old loop on a 30 s read
  const old = await oldClient(30000);
  assert.ok(old.m.limited > 0 && old.grant.code === 'rate_limited', 'control: the old 2 s loop ends rate_limited on a 30 s read, ' + JSON.stringify(old.grant)); n++;

  // the handoff's case: the chain read is out for 30 s, then lands; the player is seated with no rate_limited
  const c30 = await newClient(30000);
  assert.strictEqual(c30.grant.state, 'accepted', 'seated after a 30 s read: ' + JSON.stringify(c30.grant)); n++;
  assert.strictEqual(c30.m.limited, 0, 'no attempt refused rate_limited'); n++;
  assert.ok(c30.said.length > 0 && c30.said.every((s) => s >= 1 && s <= 63), 'the page counts down to the next ask: ' + c30.said.slice(0, 3)); n++;
  assert.ok(c30.m.real < 90000, 'seated within 90 s of real time (two 10 s join holds freeze the room clock the limit counts on): ' + c30.m.real); n++;

  // a fast read (5 s) seats on the quick second try, within 10 s
  const c5 = await newClient(5000);
  assert.strictEqual(c5.grant.state, 'accepted', 'seated after a 5 s read'); n++;
  assert.ok(c5.m.real <= 10000 && c5.m.tries === 2, 'a 5 s read is seated within 10 s on the second try: ' + c5.m.real + ' ms, ' + c5.m.tries + ' tries'); n++;
  assert.strictEqual(c5.m.limited, 0); n++;
  // the window: after 2 tries, the next waits for the one before last to leave 63 s of room time
  assert.strictEqual(R.joinNextAt([0]), -Infinity); n++;
  assert.strictEqual(R.joinNextAt([0, 100]), 63000); n++;
  assert.strictEqual(R.joinNextAt([0, 100, 63000]), 63100); n++;

  // a read that never lands inside the wait: every try stays under the limit, and the page stops after 180 s
  for (const lands of [0, 3000, 5000, 8000, 30000, 45000, 70000, 140000, 1e12]) {
    const c = await newClient(lands);
    assert.strictEqual(c.m.limited, 0, 'no rate_limited with the read out ' + lands + ' ms'); n++;
    if (lands < 1e12) { assert.strictEqual(c.grant.state, 'accepted', 'seated, read out ' + lands + ' ms'); n++; }
    else { assert.strictEqual(c.grant.code, 'ownership_unavailable', 'the last refusal is the chain read, not the limit'); n++;
           assert.ok(c.m.real >= 180000 && c.m.real < 250000, 'it asks for at least 180 s of waiting, stopping at the first refusal after: ' + c.m.real); n++; }
  }
  // and the room's own count never holds more than 4 of its 5 in any minute
  const busy = await newClient(1e12);
  const at = [], m = room(1e12);
  m.attempt = ((orig) => () => { const ok = orig(); if (ok) at.push(m.room); return ok; })(m.attempt);
  await R.joinWithWait(m.tryOnce, { room: m.clientRoom, real: () => m.real, sleep: async (ms) => { m.advance(ms); }, refresh: async () => { m.advance(20); m.reply(); }, waiting: () => {} });
  const worst = Math.max(...at.map((t) => at.filter((u) => u >= t && u < t + 60000).length));
  assert.ok(worst <= 4 && busy.m.limited === 0, 'at most 4 attempts in any 60 s of room time: ' + worst); n++;

  // the join flow calls joinWithWait, and no fixed 2 s retry is left
  const src = fs.readFileSync(path.join(__dirname, 'room.js'), 'utf8');
  assert.ok(/grant = await joinWithWait\(async function \(\) \{/.test(src), 'the join flow runs through joinWithWait'); n++;
  assert.ok(!/ownership_unavailable' && attempt < 15/.test(src), 'the 15 x 2 s loop is gone'); n++;
  console.log(n + ' PASS, 0 FAIL');
})().catch((e) => { console.error('FAIL', e.message); process.exit(1); });
