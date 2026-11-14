// Fixed facing-only answer through Brain.tell and the real host validator.
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const B = require('../brain.js');
function hostAck(plan) {
  const script = `import json,sys
sys.path.insert(0,sys.argv[1])
from near.arena import behaviour,sim
print(json.dumps(behaviour.ack(json.load(sys.stdin),sim.DEFAULT_RULES,'me',1,200)))`;
  const result = spawnSync('python3', ['-I', '-c', script, path.resolve(__dirname, '../../../..')],
    {input: JSON.stringify(plan), encoding: 'utf8', timeout: 10000});
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}
(async () => {
  let now = 1000000;
  const writes = [], prompts = [], values = new Map();
  const brain = B.create({room: {behaviour: async plan => {writes.push(plan); return hostAck(plan);}},
    store: {get: k => values.get(k) || null, set: (k,v) => values.set(k,v), json: (_k,d) => d},
    now: () => now, wait: async ms => {now += ms;}, log() {}});
  brain.choices = () => ({provider: 'nearai', cap: 1});
  brain.gate = () => null; brain.battleOn = () => true;
  brain.fighter = {id: 'me'};
  brain.ringView = async () => ({roster: [], near: [], me: {hp: 80}});
  const plan = {v: 1, stance: 'berserk', gate: {target_facing_away: true}};
  brain.ask = async (_c,p) => {prompts.push(p); return JSON.stringify({behaviour: plan, reply: 'I watch their backs.'});};
  const result = await brain.tell('Only attack fighters who are facing away from you');
  assert.equal(writes.length, 1, JSON.stringify(result));
  assert.deepEqual(writes[0], plan);
  assert.equal(result.receipt.status, 'applied', JSON.stringify(result.receipt));
  assert.equal(result.receipt.behaviour.gate.target_facing_away, true);
  assert.match(result.receipt.summary, /facing away/);
  assert.equal(brain.conversation.filter(x => x.who === 'host').pop().text, result.receipt.summary);
  assert.match(prompts[0], /facing away.*target_facing_away|target_facing_away.*facing away/i);
  assert.match(prompts[0], /facing away[^\n]*never/i);
  assert.match(B.planAsk('only attack fighters facing away', 'owner order', {}, null), /target_facing_away/);
  console.log('order-facing: facing-only gate reaches real behaviour.ack; receipt shown verbatim');
})().catch(error => {console.error(error.stack); process.exitCode = 1;});
