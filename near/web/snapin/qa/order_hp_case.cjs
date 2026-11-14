// Fixed-answer self-HP regression; named-HP needs the separately agreed engine condition.
'use strict';
const assert=require('node:assert/strict');
const B=require(process.argv[2] || '../brain.js');
(async()=>{
  let now=1000000;
  const writes=[],prompts=[],values=new Map();
  const plan={v:1,stance:'loot',gate:{never:true},reflexes:[
    {if:{self_hp_above_pct:50},then:{stance:'berserk',gate:{}}}
  ]};
  const brain=B.create({room:{behaviour:async b=>{writes.push(b);return {status:'applied',behaviour:b,summary:'Signed HP receipt.'};}},
    store:{get:k=>values.get(k)||null,set:(k,v)=>values.set(k,v),json:(_k,d)=>d},
    now:()=>now,wait:async ms=>{now+=ms;},log(){}});
  brain.choices=()=>({provider:'nearai',cap:1});brain.gate=()=>null;brain.battleOn=()=>true;
  brain.fighter={id:'me'};brain.ringView=async()=>({roster:[],near:[],me:{hp:80}});
  brain.ask=async(_c,p)=>{prompts.push(p);return JSON.stringify({behaviour:plan,reply:'Only while I can take it.'});};
  const result=await brain.tell('only fight above half HP');
  assert.deepEqual(writes,[plan]);
  assert.equal(result.receipt.summary,'Signed HP receipt.');
  assert.match(prompts[0],/above half HP.*self_hp_above_pct.*50/);
  assert.match(prompts[0],/self.*HP.*never.*target_hp_below_pct/i);
  assert.ok(!('target_hp_below_pct' in writes[0].gate));
  process.stdout.write('order-hp: self-HP wording and fixed-answer host behaviour use the owner HP rule\n');
})().catch(e=>{process.stderr.write(e.stack+'\n');process.exitCode=1;});
