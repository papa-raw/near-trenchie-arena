// Four fixed-answer regressions: three owner restrictions and one unconditional attack.
'use strict';
const assert = require('node:assert/strict');
const B = require(process.argv[2] || '../brain.js');
const roster = [
  {id:'laser-sailor',name:'Laser Sailor',tag:'Sailor'},
  {id:'captain-banana-zone',name:'Captain Banana Zone',tag:'Banana Zone'},
  {id:'avichad',name:'Avichad',tag:'Avichad'}
];
async function order(said, behaviour) {
  let now = 1000000;
  const writes = [], prompts = [], values = new Map();
  const brain = B.create({
    room:{behaviour:async b=>{writes.push(b);return {status:'applied',behaviour:b,summary:'Signed receipt unchanged.'};}},
    store:{get:k=>values.get(k)||null,set:(k,v)=>values.set(k,v),json:(_k,d)=>d},
    now:()=>now,wait:async ms=>{now+=ms;},log(){}
  });
  brain.choices=()=>({provider:'nearai',cap:1});brain.gate=()=>null;brain.battleOn=()=>true;
  brain.fighter={id:'me'};brain.ringView=async()=>({roster,near:[],me:{hp:80}});
  brain.ask=async(_c,p)=>{prompts.push(p);return JSON.stringify({behaviour,reply:'I hear you.'});};
  const result=await brain.tell(said);
  assert.equal(writes.length,1,said+': one accepted host write');
  assert.equal(result.receipt.summary,'Signed receipt unchanged.');
  return {sent:writes[0],prompts};
}
(async()=>{
  const failures=[];
  async function check(name,fn){try{await fn();process.stdout.write('PASS '+name+'\n');}catch(e){failures.push(name+': '+e.message);}}
  await check('facing-away restriction survives',async()=>{
    const plan={v:1,stance:'berserk',gate:{target_busy:true}};
    assert.deepEqual((await order('Only attack fighters who are facing away from you.',plan)).sent,plan);
  });
  await check('named keep-away reflex survives',async()=>{
    const plan={v:1,stance:'loot',reflexes:[{if:{enemy_within:{radius:5,who:'captain-banana-zone'}},then:{stance:'flee',gate:{never:true}}}]};
    assert.deepEqual((await order('Keep at least 5 tiles away from Banana Zone.',plan)).sent,plan);
  });
  await check('scoped negation never becomes attack nobody',async()=>{
    // The current schema has no exclusion gate: keep the model gate rather than imposing never.
    const plan={v:1,stance:'berserk',target:'laser-sailor',gate:{}};
    const h=await order("don't attack Avichad",plan);
    assert.deepEqual(h.sent,plan);assert.notEqual(h.sent.gate.never,true);
    assert.match(h.prompts[0],/negation.*one.*fighter|scoped negation/i);
  });
  await check('plain attack Sailor drops invented restrictions',async()=>{
    const plan={v:1,stance:'berserk',target:'laser-sailor',gate:{target_hp_below_pct:99},
      reflexes:[{if:{self_hp_below_pct:40},then:{stance:'flee'}}]};
    assert.deepEqual((await order('attack Sailor',plan)).sent,{v:1,stance:'berserk',target:'laser-sailor',gate:{}});
  });
  if(failures.length)throw new Error(failures.join('\n'));
  process.stdout.write('order-conditions: all four fixed-answer owner orders preserved\n');
})().catch(e=>{process.stderr.write(e.stack+'\n');process.exitCode=1;});
