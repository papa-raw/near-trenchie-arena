// Synthetic Messages fixtures; no live key or recorded private conversation.
// Run: node near/web/snapin/qa/claude_json_case.cjs
'use strict';
const assert = require('node:assert/strict');
const B = require('../brain.js');
const ORDER = 'only attack moonwood. always attack him. do not do anything but attack him.';
const ANSWER = {
  behaviour: { stance: 'berserk', target: 'moonwood', drives: { chase: 10, loot: 0 },
    reflexes: [{ if: { no_target: true }, then: { target: 'moonwood', drives: { chase: 10 } } }] },
  reply: 'Moonwood alone. My map says "{there}", and my boots agree.'
};
const RECEIPT = 'New behaviour recorded: target moonwood · applies at tick 42 (in 0.1 s)';
const text = (s) => ({ type: 'text', text: s });
const tool = (input = ANSWER, name = 'arena_answer') => ({ type: 'tool_use', id: 'fixture-call', name, input });
const thinking = { type: 'thinking', thinking: 'Compare the visible fighter ids before answering.', signature: 'fixture' };
const usage = { input_tokens: 250, cache_read_input_tokens: 600, output_tokens: 500 };

function setup(response, provider = 'claude', cap = 1) {
  const door = provider === 'claude' ? { door: 'Claude', route: 'key', identity: 'Claude Console' }
    : provider === 'openrouter' ? { door: 'OpenRouter', route: 'oauth' }
    : provider === 'codex' ? { door: 'Codex', route: 'key' } : { door: 'NEAR AI Cloud', route: 'key' };
  const values = new Map([
    [B.constants.SAVE, JSON.stringify({ door, sheet: { game: { name: 'Dune Sprout', temperament: 'Sunny' } } })],
    [B.constants.CAP_STORE, String(cap)], [B.constants.KEY_STORE + door.door, 'synthetic-fixture-key']
  ]);
  const store = { get: (k) => values.get(k) ?? null, set: (k, v) => values.set(k, String(v)),
    del: (k) => values.delete(k), json: (k, d) => values.has(k) ? JSON.parse(values.get(k)) : d };
  const calls = [], behaviours = [], listeners = [];
  const room = {
    on: (fn) => { listeners.push(fn); return () => {}; },
    observe: async () => ({ fighters: [
      { fighter_id: 'dev-me', public_name: 'Dune Sprout', state: 'ring', x_milli: 0, y_milli: 0, health_milli: '100000' },
      { fighter_id: 'moonwood', public_name: 'Moonwood', state: 'ring', x_milli: 1000, y_milli: 0, health_milli: '100000' }
    ], items: [] }),
    behaviour: async (b) => { behaviours.push(b); return { type: 'battle_receipt', kind: 'behaviour',
      ack: { status: 'applied', behaviour: b, summary: RECEIPT, applies_in_ms: 100 } }; }
  };
  const fetch = async (url, init) => {
    const body = JSON.parse(init.body);
    const reservations = store.json(B.constants.SPEND_STORE, []);
    calls.push({ url, init, body, reserved: reservations.reduce((n, r) => n + r.usd, 0) });
    const reply = typeof response === 'function' ? response(body) : response;
    return { status: 200, text: async () => JSON.stringify(reply) };
  };
  const b = B.create({ room, store, fetch, locks: { request: async (_name, fn) => fn() },
    now: () => 1000000, setTimer: () => 1, clearTimer: () => {} }).start();
  listeners.forEach((fn) => fn({ phase: 'in', fighter: { id: 'dev-me', life: 'fixture-life', lives: 1 } }));
  return { b, calls, behaviours, store };
}
const messages = (content, stop_reason = 'end_turn') => ({ type: 'message', role: 'assistant', content, stop_reason, usage });
async function accepted(response) {
  const h = setup(response);
  const out = await h.b.tell(ORDER);
  assert.equal(out.chip, undefined, out.chip);
  assert.deepEqual(h.behaviours, [{ ...ANSWER.behaviour, v: 1 }]);
  assert.equal(out.reply, ANSWER.reply);
  assert.equal(out.receipt.summary, RECEIPT);
  assert.equal(h.b.status().conversation.at(-1).text, RECEIPT);
  assert.equal(h.b.status().thinking, null);
  return h;
}

const cases = [
  ['default thinking cannot consume the entire answer allowance', async () => {
    const h = await accepted((body) => body.tool_choice?.type === 'tool'
      ? messages([tool()], 'tool_use') : messages([thinking], 'max_tokens'));
    const req = h.calls[0];
    assert.deepEqual(req.body.tool_choice, { type: 'tool', name: 'arena_answer', disable_parallel_tool_use: true });
    assert.equal(req.body.tools[0].name, 'arena_answer');
    assert.equal(req.body.tools[0].input_schema.type, 'object');
    assert.ok(req.body.max_tokens >= 1024, 'long targeted behaviours need room after tool framing');
    assert.equal(req.init.headers['anthropic-dangerous-direct-browser-access'], 'true');
    const chars = req.body.system[0].text.length + req.body.messages[0].content.length + JSON.stringify(req.body.tools).length;
    assert.ok(req.reserved >= B.costUsd('claude', { in: chars, out: req.body.max_tokens }), 'reserve the enlarged answer and tool definition before fetch');
    assert.equal(h.b.status().spendHourUsd, B.costUsd('claude', { in: 850, cached: 600, out: 500 }));
  }],
  ['thinking first, prose and fenced nested JSON', () => accepted(messages([thinking, text('Here is my plan.\n```json\n' + JSON.stringify(ANSWER) + '\n```')]))],
  ['text split across Messages blocks', () => {
    const s = JSON.stringify(ANSWER), split = s.indexOf('reflexes');
    return accepted(messages([thinking, text(s.slice(0, split)), text(s.slice(split))]));
  }],
  ['first balanced object excludes a trailing separate object', () => accepted(messages([
    text('```json\n' + JSON.stringify(ANSWER) + '\n```\nDiagnostic only: {"note":"extra"}')
  ]))],
  ['malformed balanced prose does not hide the following JSON', () => accepted(messages([text('Plan {unquoted}.\n' + JSON.stringify(ANSWER))]))],
  ['named tool input is the answer, independent of prose and thinking', () => accepted(messages([
    thinking, text('Untrusted prose {"behaviour":{"stance":"flee"}}'), tool()
  ], 'tool_use'))],
  ['long targeted answer survives nested reflexes and escaped braces', async () => {
    const long = structuredClone(ANSWER);
    long.behaviour.reflexes = Array.from({ length: 8 }, (_, i) => ({ if: { self_hp_below_pct: 10 + i * 10 },
      then: { stance: 'berserk', target: 'moonwood', drives: { chase: 10, loot: 0 }, say: 'Moonwood alone. Keep chasing.' } }));
    const h = setup(messages([tool(long)], 'tool_use'));
    const out = await h.b.tell(ORDER);
    assert.equal(out.chip, undefined, out.chip);
    assert.deepEqual(h.behaviours[0], { ...long.behaviour, v: 1 });
    assert.equal(out.receipt.summary, RECEIPT);
  }],
  ['truncated tool answer never replaces the prior plan and is still metered', async () => {
    const h = setup(messages([tool()], 'max_tokens'));
    h.b.behaviour = { stance: 'hold' };
    const out = await h.b.tell(ORDER);
    assert.equal(out.receipt, null);
    assert.match(out.chip, /output limit.*shorter order|incomplete.*try again/i);
    assert.deepEqual(h.b.behaviour, { stance: 'hold' });
    assert.equal(h.behaviours.length, 0);
    assert.ok(h.b.status().spendHourUsd > 0, 'failed output was billed');
    assert.equal(h.b.status().thinking, null);
  }],
  ['empty, malformed, truncated text and unknown tool answers fail without sending a plan', async () => {
    for (const content of [[], [thinking], [text('No plan available.')], [text('{"behaviour":{"stance":"hold"}')],
      [text('{"behaviour": nope}')], [tool(ANSWER, 'unknown_tool')], [tool(null)], [tool([])]]) {
      const h = setup(messages(content)); h.b.behaviour = { stance: 'hold' };
      const out = await h.b.tell(ORDER);
      assert.equal(out.receipt, null, JSON.stringify(content));
      assert.deepEqual(h.b.behaviour, { stance: 'hold' });
      assert.equal(h.behaviours.length, 0);
      assert.equal(h.b.status().thinking, null);
    }
  }],
  ['hourly cap refuses before any provider request', async () => {
    const h = setup(messages([tool()], 'tool_use'), 'claude', 0.000001);
    const out = await h.b.tell(ORDER);
    assert.match(out.chip, /Hourly cap reached/);
    assert.equal(h.calls.length, 0);
    assert.equal(h.behaviours.length, 0);
  }],
  ['other providers retain their request and answer paths', async () => {
    for (const provider of ['nearai', 'openrouter', 'codex']) {
      const h = setup({ choices: [{ message: { content: JSON.stringify(ANSWER) } }],
        usage: { prompt_tokens: 250, completion_tokens: 100 } }, provider);
      const out = await h.b.tell(ORDER);
      assert.equal(out.receipt.summary, RECEIPT);
      const req = h.calls[0].body;
      assert.equal(req.tools, undefined); assert.equal(req.tool_choice, undefined);
      assert.equal(req.messages[0].role, 'system');
      assert.ok((provider === 'codex' ? req.max_completion_tokens : req.max_tokens) >= 2048, 'nested behaviour JSON has enough output room');
    }
  }]
];

(async () => {
  let failures = 0;
  for (const [name, run] of cases) {
    try { await run(); console.log('PASS ' + name); }
    catch (e) { failures++; console.error('FAIL ' + name + '\n' + e.stack); }
  }
  console.log(`claude_json_case: ${cases.length - failures}/${cases.length} passed`);
  process.exitCode = failures ? 1 : 0;
})();
