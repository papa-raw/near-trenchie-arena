// Full identity roster in an owner order, including bench and non-nearby fighters.
'use strict';
const assert = require('node:assert/strict'), B = require('../brain.js');
const fighters = [{ fighter_id: 'me', public_name: 'Dune Sprout', state: 'ring', health_milli: '100000', x_milli: 0, y_milli: 0 },
  { fighter_id: 'laser-sailor', public_name: 'laser-sailor', state: 'bench', health_milli: '100000', x_milli: 0, y_milli: 0 }];
const roster = [{ id: 'me', name: 'Dune Sprout', tag: 'Sprout', state: 'ring' },
  { id: 'laser-sailor', name: 'Laser Sailor', tag: 'Sailor', state: 'bench' }];
const vals = new Map([[B.constants.SAVE, JSON.stringify({door: {door:'NEAR AI Cloud',route:'key'}})],
  [B.constants.KEY_STORE + 'NEAR AI Cloud','fixture-key'], [B.constants.CAP_STORE,'1']]);
const store = { get: k => vals.get(k) ?? null, set: (k,v) => vals.set(k,String(v)), del: k => vals.delete(k), json: (k,d) => vals.has(k) ? JSON.parse(vals.get(k)) : d };
let observeListener, prompt;
const room = { on: fn => { observeListener=fn; return () => {}; }, observe: async () => ({fighters,items:[]}), roster: async () => roster,
  behaviour: async b => ({status:'applied',behaviour:b,summary:'New behaviour recorded: target Laser Sailor (laser-sailor)'}) };
const brain = B.create({room,store,locks:{request:async(_n,fn)=>fn()},setTimer:()=>1,clearTimer(){},fetch:async(_url,init)=> {
  prompt=JSON.parse(init.body).messages[1].content;
  return {status:200,text:async()=>JSON.stringify({choices:[{message:{content:JSON.stringify({behaviour:{target:'laser-sailor'},reply:'Sailor alone.'})}}],usage:{prompt_tokens:100,completion_tokens:50}})};
}}).start();
(async()=>{
  observeListener({phase:'in',fighter:{id:'me',life:'one'}});
  assert.equal((await brain.tell('Charge Sailor and only Sailor.')).receipt.status,'applied');
  assert.ok(prompt.includes('"id":"laser-sailor","name":"Laser Sailor","tag":"Sailor","state":"bench"'), 'bench target has id, name and arena tag');
  assert.match(prompt,/use.*roster.*id/i,'prompt explicitly requires resolved ids');
  fighters[0].state='bench'; await brain.tell('Wait for Sailor.');
  assert.ok(prompt.includes('"id":"laser-sailor"'),'bench owner still gets the roster');
  console.log('PASS order roster: full names, tags and ids on ring and bench');
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
