// Fixed model answers exercise the browser-to-host boundary; no model/network calls.
'use strict';
const assert=require('node:assert/strict'),path=require('node:path'),{spawnSync}=require('node:child_process');
const B=require(process.argv[2]&&!process.argv[2].startsWith('--')?process.argv[2]:'../brain.js');
const rules=require('../../../arena/rules/integer-19.json');
const roster=[{id:'moonwood',name:'Moonwood',tag:'Moonwood'},{id:'avichad',name:'Avichad',tag:'Avichad'},{id:'captain-banana-zone',name:'Captain Banana Zone',tag:'Banana Zone'}];
function hostAck(behaviour){
  const script=`import json,sys
sys.path.insert(0,sys.argv[1])
from near.arena import behaviour,sim
payload=json.load(sys.stdin)
print(json.dumps(behaviour.ack(payload['behaviour'],sim.DEFAULT_RULES,'me',1,100,roster=payload['roster'])))`;
  const result=spawnSync('python3',['-I','-c',script,path.resolve(__dirname,'../../../..')],{
    input:JSON.stringify({behaviour,roster}),encoding:'utf8',timeout:10000
  });
  assert.ifError(result.error);assert.equal(result.status,0,result.stderr);
  return JSON.parse(result.stdout);
}
async function order(said,behaviour,status='applied'){
  let now=1000000;const writes=[],prompts=[],values=new Map();
  const brain=B.create({room:{behaviour:async b=>{writes.push(b);return hostAck(b);}},
    store:{get:k=>values.get(k)||null,set:(k,v)=>values.set(k,v),json:(_k,d)=>d},now:()=>now,wait:async ms=>{now+=ms;},log(){}});
  brain.choices=()=>({provider:'nearai',cap:1});brain.gate=()=>null;brain.battleOn=()=>true;
  brain.fighter={id:'me'};brain.ringView=async()=>({roster,near:[],me:{hp:80}});
  brain.ask=async(_c,p)=>{prompts.push(p);return JSON.stringify({behaviour,reply:'I hear you.'});};
  const result=await brain.tell(said);assert.equal(writes.length,status==='refused'?2:1);assert.ok(result.receipt,JSON.stringify(result));assert.equal(result.receipt.status,status,JSON.stringify(result.receipt.refused));
  assert.equal(brain.conversation.filter(x=>x.who==='host').pop().text,result.receipt.summary,'host receipt is shown verbatim');
  return {sent:writes[0],prompt:prompts[0],receipt:result.receipt};
}
(async()=>{
  const failures=[];async function check(name,fn){if(process.argv.includes('--identity-only')&&!name.startsWith('identity '))return;try{await fn();console.log('PASS '+name);}catch(e){failures.push(name+': '+e.message);}}
  await check('identity scalar exclusive target accepted by host',async()=>{
    const id='captain-banana-zone',plan={v:1,stance:'berserk',target:id,gate:{target_is:id}};
    const r=await order('only attack Banana Zone',plan);
    assert.deepEqual(r.sent,plan);assert.equal(r.receipt.behaviour.gate.target_is,id);
    assert.match(r.prompt,/target_is:<id>/);assert.match(r.prompt,/"target_is":X/);
    assert.doesNotMatch(r.prompt,/target_is["']?\s*:\s*\[/);
    assert.match(B.planAsk('only attack Banana Zone','owner order',{roster},null),/target_is:<id>/);
  });
  await check('identity singleton answers normalise base and reflex gates',async()=>{
    const id='captain-banana-zone',plan={v:1,target:id,gate:{target_is:[id]},reflexes:[{if:{always:true},then:{gate:{target_is:[id]}}}]};
    const r=await order('only attack Banana Zone',plan);
    assert.equal(r.sent.gate.target_is,id);assert.equal(r.sent.reflexes[0].then.gate.target_is,id);
    assert.equal(r.receipt.behaviour.reflexes[0].then.gate.target_is,id);
    assert.deepEqual(plan.gate.target_is,[id],'normalisation leaves model answer untouched');
  });
  await check('identity exclusions remain lists and ambiguous arrays are refused',async()=>{
    const r=await order("don't attack Banana Zone",{v:1,gate:{target_is_not:['captain-banana-zone']}});
    assert.deepEqual(r.receipt.behaviour.gate.target_is_not,['captain-banana-zone']);
    for(const ids of [[],['captain-banana-zone','moonwood']]){
      const bad=await order('only attack Banana Zone',{v:1,gate:{target_is:ids}},'refused');
      assert.ok(bad.receipt.refused.some(x=>x.path==='gate.target_is'));
    }
  });
  await check('excluded fighter gate',async()=>{
    const plan={v:1,stance:'berserk',gate:{target_is_not:['avichad']}};
    for(const said of ["don't attack Avichad",'leave Avichad alone']){
      const r=await order(said,plan);assert.deepEqual(r.sent,plan);assert.match(r.prompt,/target_is_not/);assert.notEqual(r.sent.gate.never,true);
    }
  });
  await check('named HP changes target independently',async()=>{
    const plan={v:1,stance:'berserk',reflexes:[{if:{fighter_hp_below_pct:{who:'moonwood',pct:30}},then:{target:'moonwood',stance:'berserk',gate:{}}}]};
    const r=await order('if Moonwood is low, finish her',plan);assert.deepEqual(r.sent,plan);assert.match(r.prompt,/fighter_hp_below_pct/);
    assert.match(r.prompt,/named.*HP.*current target/i);
  });
  await check('pacifist fixed answer stays never',async()=>{
    const plan={v:1,stance:'loot',gate:{never:true}};
    const r=await order('pacifist mode pls',plan);assert.deepEqual(r.sent,plan);assert.match(r.prompt,/pacifist.*never/i);
  });
  await check('berserk neutral drive expansion does not disable preset',async()=>{
    const plan={v:1,stance:'berserk',drives:{chase:0,loot:0,keep_away:0,hold:0,protect:0},gate:{}};
    const r=await order('go berserk',plan);assert.equal(r.sent.drives.chase,rules.behaviour.stances.berserk.drives.chase);
    assert.ok(r.sent.drives.chase>0);assert.match(r.prompt,/sparse.*overrides/i);
    const constrained=await order('go berserk but do not chase',plan);assert.deepEqual(constrained.sent,plan,'explicit drive restriction stays model-authored');
  });
  if(failures.length)throw new Error(failures.join('\n'));
  console.log(process.argv.includes('--identity-only')?'order-wire: scalar identity and list exclusion contract accepted by real host validator':'order-wire: fixed answers carry identity/HP/pacifist gates and active berserk drives');
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
