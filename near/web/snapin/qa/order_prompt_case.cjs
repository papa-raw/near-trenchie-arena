// Recorded-answer regression from a real-model playtest of typed orders; numeric baseline: four defective orders.
'use strict';
const assert = require('node:assert/strict');
const B = require('../brain.js');
const roster = [{id:'laser-sailor',name:'Laser Sailor',tag:'Sailor'},
  {id:'kathie-moonwood',name:'Kathie Moonwood',tag:'Moonwood'}];
const old = {v:1,stance:'follow-ally',drives:{protect:8,protect_ally:'kathie-moonwood'}};
function setup(answers, current = null) {
  let now = 1000000;
  const writes = [], prompts = [], events = [], values = new Map();
  const store = {get:k=>values.get(k)||null,set:(k,v)=>values.set(k,v),json:(_k,d)=>d};
  const brain = B.create({room:{behaviour:async b=>{writes.push(b);return {status:'applied',behaviour:b,summary:'Signed receipt unchanged.'};}},
    store,now:()=>now,wait:async ms=>{now+=ms;},log(){}});
  brain.choices=()=>({provider:'nearai',cap:1,key:'fixture'}); brain.gate=()=>null; brain.battleOn=()=>true;
  brain.fighter={id:'me'}; brain.behaviour=current; brain.ringView=async()=>({roster,near:[],me:{hp:40}});
  brain.on(s=>events.push(s));
  brain.ask=async(_c,p)=>{prompts.push(p);const a=answers.shift();if(a instanceof Error)throw a;return JSON.stringify(a);};
  return {brain,writes,prompts,events};
}
(async()=>{
  const failures=[];
  async function check(name, fn) {try{await fn();process.stdout.write('PASS '+name+'\n');}catch(e){failures.push(name+': '+e.message);}}
  await check('A3 unconditional target drops invented self-preservation and fallback',async()=>{
    const h=setup([{behaviour:{stance:'berserk',drives:{chase:9},target:'laser-sailor',gate:{},
      reflexes:[{if:{self_hp_below_pct:40},then:{stance:'defend'}},{if:{no_target:true},then:{stance:'loot'}}]},reply:'Sailor is mine.'}]);
    const pending=h.brain.tell('attack laser-sailor');
    assert.ok(h.events.at(-1).thinking,'thinking emits before yielding');
    const r=await pending;assert.ok(r.receipt);assert.equal(h.writes.length,1);
    assert.equal(h.writes[0].target,'laser-sailor');assert.deepEqual(h.writes[0].reflexes||[],[]);assert.deepEqual(h.writes[0].gate,{});
    assert.equal(r.receipt.summary,'Signed receipt unchanged.');
  });
  await check('P1 only Sailor always has no 99 percent gate or fallback',async()=>{
    const h=setup([{behaviour:{stance:'berserk',target:'laser-sailor',gate:{target_hp_below_pct:99},
      reflexes:[{if:{no_target:true},then:{stance:'berserk'}}]},reply:'Sailor alone.'}]);
    await h.brain.tell("Let's be super aggressive. Charge and attack Sailor and only Sailor always.");
    assert.deepEqual(h.writes[0].gate,{});assert.deepEqual(h.writes[0].reflexes||[],[]);
  });
  await check('H3 fresh order cannot silently inherit Moonwood protection',async()=>{
    const h=setup([{behaviour:{stance:'hunt-weakest',target:'weakest',drives:{protect:4,protect_ally:'kathie-moonwood'}},reply:'Weakest first.'},
      {behaviour:{stance:'hunt-weakest',target:'weakest'},reply:'Weakest first.'}],old);
    await h.brain.tell('Go after whoever is weakest.');
    assert.equal(h.writes.length,1);assert.equal(h.writes[0].drives?.protect_ally,undefined);
    assert.ok(!h.prompts[0].includes('"protect_ally":"kathie-moonwood"'),'old plan must not be in fresh prompt');
    assert.match(h.prompts[1],/previous.*ally|inherited.*ally/i);
  });
  await check('FR1 empty French answer retries before writing; flee has no attack',async()=>{
    const h=setup([{behaviour:{drives:{keep_away:10,keep_away_radius:10},reflexes:[{if:{enemy_within:2},then:{stance:'flee'}}]},reply:''},
      {behaviour:{stance:'flee',drives:{keep_away:10}},reply:'Je file, gardez vos coups !'}]);
    const r=await h.brain.tell('Fuis tout le monde !');assert.equal(h.writes.length,1);
    assert.equal(h.writes[0].stance,'flee');assert.deepEqual(h.writes[0].gate,{never:true});assert.ok(r.reply.trim());
    assert.equal(h.prompts.length,2);
  });
  await check('explicit conditional orders retain gates and reflexes',async()=>{
    const plan={stance:'flee',target:'kathie-moonwood',gate:{target_hp_below_pct:30},
      reflexes:[{if:{target_hp_below_pct:30},then:{stance:'berserk'}}]};
    const h=setup([{behaviour:plan,reply:'I run until Moonwood weakens.'}]);
    await h.brain.tell("run from everyone and attack moonwood when moonwood's hp is less than 30%");
    assert.deepEqual(h.writes[0],{...plan,v:1});
  });
  await check('continuations retain old context and intentional previous ally',async()=>{
    const h=setup([{behaviour:old,reply:'Still guarding Moonwood.'}],old);
    await h.brain.tell('Also keep guarding her and chase harder.');
    assert.ok(h.prompts[0].includes('"protect_ally":"kathie-moonwood"'));assert.equal(h.writes[0].drives.protect_ally,'kathie-moonwood');
  });
  await check('keep away is a fresh instruction, not continuation',async()=>{
    const p=B.tellAsk('', 'Keep away from everyone.', {roster}, old);
    assert.ok(!p.includes('"protect_ally":"kathie-moonwood"'));
  });
  await check('go hit is unconditional and a no-attack order preserves never',async()=>{
    const h=setup([{behaviour:{stance:'berserk',gate:{target_hp_below_pct:50},reflexes:[{if:{self_hp_below_pct:30},then:{stance:'flee'}}]},reply:'On my way.'}]);
    await h.brain.tell('Go hit Avichad.');assert.deepEqual(h.writes[0].gate,{});assert.deepEqual(h.writes[0].reflexes||[],[]);
    const n=setup([{behaviour:{stance:'hold',gate:{never:true}},reply:'No atacaré a nadie.'}]);
    await n.brain.tell('No ataques a nadie.');assert.deepEqual(n.writes[0].gate,{never:true});
  });
  await check('prompt requires exact multilingual minimal answer and neutral replacement',async()=>{
    const p=B.tellAsk('', 'attack Sailor', {roster}, old);
    assert.match(p,/any language/i);assert.match(p,/temperament.*only.*reply/i);
    assert.match(p,/no .*reflex.*gate.*condition.*fallback/i);assert.match(p,/neutral/i);
    assert.match(p,/one short sentence/i);assert.match(p,/no reasoning/i);assert.match(p,/never.*empty/i);
    assert.ok(!p.includes('"protect":8'));
  });
  await check('network error is shown once',async()=>{
    const msg='Your AI did not answer (the network failed): your Trenchie keeps its last plan.';
    const h=setup([Object.assign(new Error(msg),{kind:'network',chip:msg}),Object.assign(new Error(msg),{kind:'network',chip:msg})]);
    const r=await h.brain.tell('attack Sailor');assert.equal(r.chip,msg);assert.equal(h.writes.length,0);
  });
  if(failures.length)throw new Error(failures.join('\n'));
  process.stdout.write('order-prompt: recorded A3/P1/H3/FR1 and prompt/error boundaries pass\n');
})().catch(e=>{process.stderr.write(e.stack+'\n');process.exitCode=1;});
