// Fixed provider answers through Brain.tell, real behaviour.ack and a seeded damage check.
'use strict';
const assert = require('node:assert/strict'), path = require('node:path'), {spawnSync} = require('node:child_process');
const B = require('../brain.js');
const rules = require('../../../arena/rules/integer-19.json');
const roster = [{id:'tommy-leeth',name:'Tommy Leeth',tag:'Leeth'}, {id:'sailor',name:'Sailor',tag:'Sailor'}];
function host(plan, damage = false) {
  const script = `import json,sys
sys.path.insert(0,sys.argv[1])
from near.arena import behaviour,sim
raw=json.load(sys.stdin)
ack=behaviour.ack(raw,sim.DEFAULT_RULES,'me',1,200,roster=${JSON.stringify(roster)})
if sys.argv[2]=='damage':
 g=sim.Sim(731)
 for name in ('me','sailor'):
  g.enqueue(sim.Input(0,'join',name,0,{'angle':0}))
 g._inputs();g.state['tick']=200
 for i,f in enumerate(g.state['fighters'].values()):
  f.update(x=i*700,y=0,hp=1000,max_hp=1000,shield_until=0,attack_at=0,sig_at=99999,direction=0,target=None)
  f['equipped']['weapon']='c-swing'
  g._set_behaviour(f,behaviour.normalise({'v':1,'gate':{'never':True}},g.rules,f['id'])[0])
 g._set_behaviour(g.state['fighters']['me'],ack['behaviour'])
 g._policy();g._attacks();g._projectiles();g._damage()
 ack['victim_hp']=g.state['fighters']['sailor']['hp']
print(json.dumps(ack))`;
  const r = spawnSync('python3',['-I','-c',script,path.resolve(__dirname,'../../../..'),damage?'damage':'ack'],{input:JSON.stringify(plan),encoding:'utf8',timeout:10000});
  assert.ifError(r.error); assert.equal(r.status,0,r.stderr); return JSON.parse(r.stdout);
}
async function order(said, plan) {
  let now=1000000; const values=new Map();
  const brain=B.create({room:{behaviour:async b=>host(b)},store:{get:k=>values.get(k)||null,set:(k,v)=>values.set(k,v),json:(_k,d)=>d},now:()=>now,wait:async ms=>{now+=ms;},log(){}});
  brain.choices=()=>({provider:'nearai',cap:1}); brain.gate=()=>null; brain.battleOn=()=>true; brain.fighter={id:'me'};
  brain.ringView=async()=>({roster,near:[],me:{hp:80}});
  brain.ask=async()=>JSON.stringify({behaviour:plan,reply:'On my way.'});
  const out=await brain.tell(said); assert.equal(out.receipt?.status,'applied',JSON.stringify(out));
  assert.equal(brain.conversation.filter(x=>x.who==='host').at(-1).text,out.receipt.summary);
  return out.receipt.behaviour;
}
(async()=>{
 const failures=[];
 async function check(name,fn){try{await fn();process.stdout.write('PASS '+name+'\n');}catch(e){failures.push(name+': '+e.message);}}
 await check('ordinary attack synonyms remove invented identity and HP gates',async()=>{
  for(const verb of ['kill','take out','beat','smash','punch','go after','hunt','destroy','finish','wreck','attack','fight','charge','hit','tue','tuer','attaque','mata','matar','ataca']) {
   const name=verb==='take out'?'Sailor':'Leeth',id=name==='Sailor'?'sailor':'tommy-leeth';
   const b=await order(verb+' '+name,{v:1,target:id,gate:{target_is:id,target_hp_below_pct:99},reflexes:[{if:{self_hp_below_pct:20},then:{stance:'flee'}}]});
   assert.equal(b.gate.target_is,undefined,verb); assert.equal(b.gate.target_hp_below_pct,undefined,verb); assert.equal(b.reflexes.length,0,verb);
  }
 });
 await check('explicit exclusive words preserve identity',async()=>{
  for(const said of ['only kill leeth','just kill Leeth','kill Leeth, nobody else','tue Leeth seulement','mata Leeth solo','mata Leeth únicamente']) {
   const b=await order(said,{v:1,target:'tommy-leeth',gate:{target_is:'tommy-leeth'}}); assert.equal(b.gate.target_is,'tommy-leeth',said);
  }
 });
 await check('defend drops invented rival base and reflex restrictions',async()=>{
  const b=await order('Defend yourself.',{v:1,stance:'defend',gate:{match:'any',rival:true},reflexes:[{if:{target_hp_below_pct:30},then:{gate:{rival:true},stance:'flee'}}]});
  assert.equal(b.gate.rival,undefined); assert.equal(b.reflexes.length,0);
 });
 await check('requested gates and reflexes survive',async()=>{
  const b=await order('Only hit rivals nearby when your health is low.',{v:1,gate:{rival:true,distance_under:3},reflexes:[{if:{self_hp_below_pct:30},then:{gate:{rival:true}}}]});
  assert.equal(b.gate.rival,true); assert.equal(b.gate.distance_under,3); assert.equal(b.reflexes.length,1);
 });
 await check('go after hunt get and weakest move and deal damage',async()=>{
  for(const said of ['go after Sailor','hunt Sailor','get Sailor','Go after whoever is weakest.']) {
   const target=said.includes('weakest')?'weakest':'sailor';
   const b=await order(said,{v:1,target,drives:{chase:0,hold:0,keep_away:0,loot:0,protect:0},gate:{never:true,rival:true}});
   assert.equal(b.target,target); assert.equal(b.drives.chase,rules.behaviour.stances['hunt-weakest'].drives.chase);
   assert.ok(host(b,true).victim_hp<1000,said+' must damage its target');
  }
 });
 if(failures.length)throw new Error(failures.join('\n'));
 process.stdout.write('kill-verb: real host ACKs preserve only requested restrictions; seeded target takes damage\n');
})().catch(e=>{process.stderr.write(e.stack+'\n');process.exitCode=1;});
