// One owner-order lifecycle regression. Model and host boundaries are deterministic, with no network.
'use strict';
const assert = require('node:assert/strict');
const B = require('./brain.js');
const OWNER = { v: 1, stance: 'berserk', target: 'kathie-moonwood', gate: { target_hp_below_pct: 30 } };
const NEXT = { v: 1, stance: 'hold' }, AUTO = { v: 1, stance: 'flee' };

function setup(values = new Map(), token = 'pike') {
  let time = 1000000, hp = 100, onRoom;
  const sends = [], asks = [], speech = [], predictions = [];
  const store = { get: k => values.get(k) ?? null, set: (k, v) => values.set(k, String(v)),
    json: (k, d) => values.has(k) ? JSON.parse(values.get(k)) : d, del: k => values.delete(k) };
  const snapshot = () => ({ fighters: [
    { fighter_id: token, public_name: 'Dune Sprout', state: 'ring', health_milli: String(hp * 1000), x_milli: 0, y_milli: 0 },
    { fighter_id: 'kathie-moonwood', public_name: 'Moonwood', state: 'ring', health_milli: '20000', x_milli: 5000, y_milli: 0 }
  ], items: [] });
  const h = { next: OWNER, status: 'applied', fail: false, blockAuto: null, values, sends, asks, speech, predictions };
  const room = { on: fn => { onRoom = fn; return () => {}; }, observe: async () => snapshot(),
    behaviour: async plan => { sends.push(plan); if (h.blockAck) await h.blockAck; return { type: 'battle_receipt', ack: {
      status: h.status, behaviour: plan, summary: 'Host receipt: ' + h.status,
      refused: h.status === 'refused' ? [{ fix: 'Keep the previous plan.' }] : []
    } }; },
    speech: async line => { speech.push(line); return { ack: { status: 'posted' } }; },
    setOrder: p => predictions.push(p) };
  const c = { provider: 'nearai', cap: 1, sheet: null };
  const brain = B.create({ room, store, now: () => time, wait: async ms => { time += ms; },
    setTimer: () => 1, clearTimer() {}, log() {} });
  // Isolate plan ownership from provider credentials/billing; exercise real tell, step, queues and receipts.
  brain.choices = () => c; brain.gate = () => null;
  brain.ask = async (_c, text) => {
    asks.push(text);
    if (text.includes('Predict your NEXT life')) return JSON.stringify({ level: 2 });
    if (text.includes('Trash-talk')) return JSON.stringify({ say: 'Still paddling.' });
    if (h.fail) throw Object.assign(new Error('Fixture provider unavailable'), { kind: 'bad-key' });
    if (text.includes('Write the behaviour you want now') && h.blockAuto) return h.blockAuto;
    return JSON.stringify({ behaviour: text.includes('Your owner just told you') ? h.next : AUTO, reply: 'On my way.' });
  };
  brain.start(); onRoom({ phase: 'in', fighter: { id: token, life: token + ':1', lives: 1 } });
  h.brain = brain;
  h.tick = async health => { hp = health; time += 25000; await brain.step(); };
  h.respawn = () => onRoom({ phase: 'in', fighter: { id: token, life: token + ':2', lives: 2 } });
  h.changeFighter = id => { token = id; onRoom({ phase: 'in', fighter: { id, life: id + ':1', lives: 1 } }); };
  return h;
}

(async () => {
  // Numeric baseline: one accepted owner behaviour must remain exactly one host write through all auto triggers.
  const h = setup();
  assert.equal((await h.brain.tell('Run away, then charge Moonwood below thirty percent.')).receipt.status, 'applied');
  await h.tick(100); // first observation / next-life prediction
  await h.tick(70);  // hit
  assert.equal(h.sends.length, 1, 'damage must not replace the accepted owner plan');
  await h.tick(15);  // low HP
  h.respawn(); await h.tick(100); // respawn, with a new life prediction
  h.brain.pendingTrigger = 'a rival came near'; await h.tick(100); // pending auto triggers from any source
  assert.deepEqual(h.sends, [OWNER]);
  assert.ok(h.predictions.length >= 2, 'next-life predictions continue');
  assert.ok(h.speech.length > 0, 'event speech continues without writing a behaviour');
  assert.ok(!h.asks.some(text => text.includes('Write the behaviour you want now')), 'owner control makes no auto-plan model calls');
  await assert.rejects(h.brain.sendBehaviour(AUTO, h.brain.orderRevision, 'pike'),
    error => error.kind === 'superseded', 'even a queued automatic write at the current revision is fenced');

  h.next = NEXT;
  assert.equal((await h.brain.tell('Hold this position.')).receipt.status, 'applied');
  await h.tick(15); assert.deepEqual(h.sends.at(-1), NEXT, 'only the next owner command replaces the plan');
  h.status = 'refused';
  assert.equal((await h.brain.tell('Try a different plan.')).receipt.status, 'refused');
  assert.deepEqual(h.brain.behaviour, NEXT, 'refused owner replacement keeps accepted plan');
  h.status = 'applied'; h.fail = true;
  assert.equal((await h.brain.tell('A provider failure.')).receipt, null);
  h.fail = false;
  const afterFailure = h.sends.length;
  await h.tick(100); assert.equal(h.sends.length, afterFailure, 'failures do not release owner control');

  const reload = setup(h.values);
  await reload.tick(100); await reload.tick(10);
  assert.equal(reload.sends.length, 0, 'reload keeps control with the existing engine plan');
  const other = setup(h.values, 'another-fighter'); await other.tick(100);
  assert.deepEqual(other.sends, [AUTO], 'owner control is scoped to the fighter');

  const clipped = setup(); clipped.status = 'clipped'; await clipped.brain.tell('Keep clear.');
  await clipped.tick(100); await clipped.tick(10); assert.equal(clipped.sends.length, 1, 'clipped acceptance also holds');
  const refused = setup(); refused.status = 'refused'; await refused.brain.tell('An invalid first plan.');
  refused.status = 'applied'; await refused.tick(100); await refused.tick(70);
  assert.deepEqual(refused.sends.at(-1), AUTO, 'a refused first command does not invent an accepted owner plan');

  const autonomous = setup(); await autonomous.tick(100); await autonomous.tick(70);
  assert.equal(autonomous.sends.length, 2, 'fighters without an owner command still plan and react autonomously');
  let release;
  const race = setup(); race.blockAuto = new Promise(resolve => { release = resolve; });
  const automatic = race.tick(100);
  for (let i = 0; i < 20 && !race.asks.some(text => text.includes('Write the behaviour you want now')); i++) await new Promise(setImmediate);
  assert.ok(race.asks.some(text => text.includes('Write the behaviour you want now')));
  const attack = {...OWNER, gate:{}}; // This plain attack has no requested HP restriction.
  race.next = attack;
  await race.brain.tell('Attack Moonwood.');
  release(JSON.stringify({ behaviour: AUTO })); await automatic;
  assert.deepEqual(race.sends, [attack], 'an in-flight auto answer cannot overwrite a newer owner order');
  await race.tick(15); assert.deepEqual(race.sends, [attack]);

  let ack;
  const moved = setup(); moved.blockAck = new Promise(resolve => { ack = resolve; });
  const owner = moved.brain.tell('Keep this fighter on Moonwood.');
  for (let i = 0; i < 20 && !moved.sends.length; i++) await new Promise(setImmediate);
  assert.equal(moved.sends.length, 1);
  moved.changeFighter('another-fighter'); ack(); await owner;
  moved.brain.pendingTrigger = 'a rival came near';
  await moved.tick(100);
  assert.deepEqual(moved.sends, [OWNER, AUTO], 'late ACK ownership belongs to the fighter that received the order');
  console.log('order-keep: owner plan survives automatic triggers, reload, failed replacement and stale replies; autonomous plans, speech and predictions remain');
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
