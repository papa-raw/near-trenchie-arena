// Four focused provider cases: recorded responses only, no real keys or provider connections.
'use strict';
const assert = require('node:assert/strict'), B = require('../brain.js'), F = require('./brain_robust_responses.json');
const OLD = { stance: 'hold' }, RECEIPT = 'New behaviour recorded: target moonwood';
function response(provider, kind, answer = F.answer) {
  if (provider === 'claude') return { status: 200, text: async () => JSON.stringify({
    stop_reason: kind === 'truncated' ? 'max_tokens' : 'end_turn', usage: F.claude_usage,
    content: kind === 'empty' ? [] : [{ type: 'text', text: ['truncated', 'parse'].includes(kind) ? '{"behaviour":' :
      kind === 'fenced' ? 'A plan.\n```json\n' + JSON.stringify(answer) + '\n```\nNotes: {"extra":true}' : JSON.stringify(answer) }]
  }) };
  return { status: 200, text: async () => JSON.stringify({ usage: F.chat_usage, choices: [{
    finish_reason: kind === 'truncated' ? 'length' : 'stop', message: { content: kind === 'empty' ? '' :
      ['truncated', 'parse'].includes(kind) ? '{"behaviour":' : kind === 'fenced' ? 'A plan.\n```json\n' + JSON.stringify(answer) + '\n```\nNotes: {"extra":true}' : JSON.stringify(answer) }
  }] }) };
}
function setup(provider, script, options = {}) {
  const door = provider === 'claude' ? { door: 'Claude', route: 'key', identity: 'Claude Console' } : provider === 'codex'
    ? { door: 'Codex', route: 'key' } : provider === 'openrouter' ? { door: 'OpenRouter', route: 'key' } : { door: 'NEAR AI Cloud', route: 'key' };
  const values = new Map([[B.constants.SAVE, JSON.stringify({ door, sheet: { game: { name: 'Dune Sprout' } } })],
    [B.constants.CAP_STORE, String(options.cap || 1)], [B.constants.KEY_STORE + door.door, 'fixture-not-a-real-key']]);
  const store = { get: key => values.get(key) ?? null, set: (key, value) => values.set(key, String(value)), del: key => values.delete(key),
    json: (key, fallback) => values.has(key) ? JSON.parse(values.get(key)) : fallback };
  const calls = [], behaviours = [], sends = [], states = [], logs = [], timers = [];
  let time = 1000000, listener;
  const room = { on(fn) { listener = fn; return () => {}; }, observe: async () => ({ fighters: [
    { fighter_id: 'me', public_name: 'Dune Sprout', state: 'ring', x_milli: 0, y_milli: 0, health_milli: '100000' },
    { fighter_id: 'moonwood', public_name: 'Moonwood', state: 'ring', x_milli: 1000, y_milli: 0, health_milli: '100000' }], items: [] }),
    behaviour: async behaviour => { sends.push(time); behaviours.push(behaviour); return { type: 'battle_receipt', ack: options.refuseFirst && behaviours.length === 1 ?
      F.refused_receipt : { status: 'applied', summary: RECEIPT, behaviour, applies_in_ms: 100 } }; } };
  const brain = B.create({ room, store, fetch: async (_url, init) => {
    const call = { body: JSON.parse(init.body), signal: init.signal, reserved: store.json(B.constants.SPEND_STORE, []).reduce((sum, row) => sum + row.usd, 0) };
    calls.push(call); const next = script[Math.min(calls.length - 1, script.length - 1)];
    if (next === 'timeout' || next === 'network') throw Object.assign(new Error(next), { name: next === 'timeout' ? 'AbortError' : 'TypeError' });
    if (next === 'bad-key' || next === 'no-credits') return { status: next === 'bad-key' ? 401 : 402, text: async () => JSON.stringify({ error: { message: next } }) };
    if (typeof next === 'function') return next(call);
    return response(provider, next);
  }, locks: { request: async (_name, fn) => fn() }, now: () => time, setTimer: () => 1, clearTimer() {},
    wait: async ms => { time += ms; }, log: event => logs.push(event), visibility: () => options.hidden ? 'hidden' : 'visible',
    requestTimers: { setTimeout(fn, ms) { const t = { fn, ms }; timers.push(t); return t; }, clearTimeout() {} } }).start();
  listener({ phase: 'in', fighter: { id: 'me', life: 'life-1', lives: 1 } });
  brain.behaviour = OLD; brain.planned = true; brain.on(state => states.push(state));
  return { brain, calls, behaviours, sends, states, logs, timers, store, room,
    changeFighter: id => listener({ phase: 'in', fighter: { id, life: 'life-2' } }), advance: ms => { time += ms; } };
}
const settled = async check => { for (let i = 0; i < 50; i++) { if (check()) return; await new Promise(resolve => setImmediate(resolve)); } throw new Error('fixture did not reach expected state'); };

async function providerCase(provider) {
  for (const first of ['timeout', 'network', 'parse', 'truncated', 'empty']) {
    const h = setup(provider, [first, 'ok']);
    const result = await h.brain.tell('Only attack Moonwood.');
    assert.equal(result.receipt?.status, 'applied', provider + '/' + first + ': retry succeeds');
    assert.equal(h.calls.length, 2); assert.equal(h.behaviours.length, 1);
    assert.equal(h.brain.status().thinking, null);
    assert.ok(h.states.some(state => state.thinking?.attempt === 2), 'thinking remains visible during retry');
    assert.ok(!h.states.some(state => state.state === 'failed'), 'first attempt is not presented as final failure');
    assert.ok(h.logs.some(event => event.kind === first && event.provider === provider), 'failure kind is recorded');
    assert.equal(h.store.json(B.constants.SPEND_STORE, []).length, 2, 'both attempts have a cap row');
    assert.ok(h.calls.every(call => (call.body.max_tokens || call.body.max_completion_tokens) >= 2048));
    assert.ok(h.brain.status().spendHourUsd > 0);
    if (first === 'timeout' || first === 'network') assert.equal(h.store.json(B.constants.SPEND_STORE, [])[0].usd, h.calls[0].reserved, 'unknown billed usage keeps its reservation');
    if (first === 'truncated') assert.equal(h.calls[1].body.max_tokens || h.calls[1].body.max_completion_tokens, 4096);
    assert.equal(h.brain.status().conversation.at(-1).text, RECEIPT, 'receipt is verbatim');
  }
  const fenced = setup(provider, ['fenced']);
  assert.equal((await fenced.brain.tell('Attack Moonwood.')).receipt.status, 'applied');
  assert.equal(fenced.calls.length, 1, 'complete fenced answer needs no retry');

  let release;
  const slow = setup(provider, [() => new Promise(resolve => { release = resolve; })], { hidden: true });
  const pending = slow.brain.tell('Attack Moonwood.'); await settled(() => !!release);
  assert.ok(slow.brain.status().thinking); assert.deepEqual(slow.brain.behaviour, OLD);
  assert.equal(slow.timers[0].ms, 60000, 'all doors allow a slow answer');
  slow.advance(45000); release(response(provider, 'ok')); assert.equal((await pending).receipt.status, 'applied');

  const deadline = setup(provider, [call => new Promise((_resolve, reject) => call.signal.addEventListener('abort', () =>
    reject(Object.assign(new Error('deadline expired'), { name: 'AbortError' })))), 'ok']);
  const expired = deadline.brain.tell('Attack.'); await settled(() => deadline.calls.length === 1);
  deadline.timers[0].fn(); assert.equal((await expired).receipt.status, 'applied'); assert.equal(deadline.calls.length, 2);

  const failed = setup(provider, ['empty', 'empty']);
  assert.equal((await failed.brain.tell('Attack.')).receipt, null);
  assert.equal(failed.calls.length, 2); assert.deepEqual(failed.brain.behaviour, OLD); assert.equal(failed.behaviours.length, 0);
  assert.equal(failed.brain.status().lastFailure.kind, 'empty');
  for (const kind of ['bad-key', 'no-credits']) {
    const h = setup(provider, [kind, 'ok']); await h.brain.tell('Attack.'); assert.equal(h.calls.length, 1, kind + ' is not retried');
  }
  const schema = setup(provider, ['ok', 'ok'], { refuseFirst: true });
  assert.equal((await schema.brain.tell('Attack.')).receipt.status, 'applied');
  assert.equal(schema.calls.length, 2); assert.ok(schema.sends[1] - schema.sends[0] >= 500, 'host retry respects 0.5 s rate');
  assert.ok(schema.logs.some(event => event.kind === 'host-refused'));

  const cap = setup(provider, [() => { cap.store.set(B.constants.CAP_STORE, '0.000001'); return response(provider, 'empty'); }, 'ok']);
  assert.equal((await cap.brain.tell('Attack.')).receipt, null); assert.equal(cap.calls.length, 1, 'retry rechecks a changed cap');
  assert.deepEqual(cap.brain.behaviour, OLD);

  let firstDone;
  const queued = setup(provider, [() => new Promise(resolve => { firstDone = resolve; }), 'ok']);
  const one = queued.brain.tell('First order.'); await settled(() => !!firstDone);
  const two = queued.brain.tell('Second order.'); assert.ok(queued.brain.status().thinking);
  firstDone(response(provider, 'ok')); assert.equal((await one).receipt.status, 'applied'); assert.equal((await two).receipt.status, 'applied');
  assert.equal(queued.behaviours.length, 2); assert.ok(queued.sends[1] - queued.sends[0] >= 500);
  assert.equal(queued.brain.status().thinking, null);

  let oldDone;
  const stale = setup(provider, [() => new Promise(resolve => { oldDone = resolve; }), 'ok']);
  stale.brain.pendingTrigger = 'a hit';
  const automatic = stale.brain.battleStep(stale.brain.choices(), B.view(await stale.room.observe(), 'me'));
  await settled(() => !!oldDone); const owner = stale.brain.tell('Attack Moonwood.');
  oldDone(response(provider, 'ok', { behaviour: { stance: 'flee' } }));
  await automatic; assert.equal((await owner).receipt.status, 'applied');
  assert.equal(stale.behaviours.length, 1, 'superseded automatic answer cannot replace an owner order');
  assert.equal(stale.behaviours[0].stance, F.answer.behaviour.stance);
  assert.ok(stale.logs.some(event => event.kind === 'superseded'));

  let fighterDone;
  const moved = setup(provider, [() => new Promise(resolve => { fighterDone = resolve; })]);
  const moving = moved.brain.tell('Attack.'); await settled(() => !!fighterDone); moved.changeFighter('another');
  fighterDone(response(provider, 'ok')); assert.equal((await moving).receipt, null);
  assert.equal(moved.calls.length, 1); assert.equal(moved.behaviours.length, 0); assert.equal(moved.brain.status().lastFailure.kind, 'stale-fighter');
}
(async () => {
  let failures = 0;
  for (const provider of ['nearai', 'openrouter', 'codex', 'claude']) {
    try { await providerCase(provider); console.log('PASS ' + provider); }
    catch (error) { failures++; console.error('FAIL ' + provider + '\n' + error.stack); }
  }
  console.log('brain-robust-case: ' + (4 - failures) + '/4 provider cases passed'); process.exitCode = failures ? 1 : 0;
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
