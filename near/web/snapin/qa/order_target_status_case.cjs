// Render the existing owner panel with public target-return rows and an accepted browser plan.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const data=new Map([['trenchie.snapin.v1',JSON.stringify({name:'Coral Scout',door:{route:'key',door:'NEAR AI Cloud'}})]]);
const el={innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[]};
let writes=0;Object.defineProperty(el,'innerHTML',{get(){return this.html||'';},set(v){writes++;this.html=v;}});
const timers=[];let targets=[{id:'moonwood',name:'Moonwood',state:'bench',respawn_in_ms:12500,held:false}];
const context={URL,URLSearchParams,Date,console,location:{href:'https://arena.invalid/arena.html',search:''},innerWidth:1440,
  document:{addEventListener(){},getElementById:id=>id==='pn-target-status'?{set textContent(v){el.html=el.html.replace(/(<div class="readonly" id="pn-target-status" role="status">).*?(<\/div>)/,(_all,start,end)=>start+v+end);}}:null,createElement:()=>el,body:{appendChild(){}},activeElement:null},
  localStorage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)},sessionStorage:{getItem:()=>null,setItem(){}},
  addEventListener(){},dispatchEvent(){},CustomEvent:function(){},requestAnimationFrame:fn=>fn(),
  setInterval(fn,ms){if(ms===1000)timers.push(fn);return 1;},clearInterval(){},
  SnapRoom:{status:()=>({phase:'in',fighter:{id:'me',name:'Coral Scout'}}),on(){},roster:async()=>targets},
  SnapBrain:{active:{behaviour:{v:1,target:'moonwood',gate:{target_is:'moonwood'}}}},
  fetch:async()=>({ok:true,json:async()=>({fighter_id:'me',hp:80,max_hp:100,events:[],bench:{equipped:[],bag:[]}})})};
vm.createContext(context);
for(const file of ['guide-copy.js','panel.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'..',file),'utf8'),context);
(async()=>{
  if(process.argv.includes('--scalar-only')){
    context.SnapBrain.active.behaviour={v:1,gate:{target_is:'captain-banana-zone'}};
    targets=[{id:'captain-banana-zone',name:'Captain Banana Zone',state:'bench',respawn_in_ms:12500},
      {id:'banana',name:'Unrelated Fighter',state:'bench',respawn_in_ms:3000}];
    context.SnapPanel.start();await new Promise(setImmediate);context.SnapPanel.render();
    assert.match(el.innerHTML,/Captain Banana Zone is off the floor, back in 13 s/);
    assert.doesNotMatch(el.innerHTML,/Unrelated Fighter/,'scalar identity matches whole ids');
    targets[0].state='ring';await timers[0]();assert.doesNotMatch(el.innerHTML,/off the floor/);
    console.log('PASS scalar target status: gate-only target, exact id and automatic return');return;
  }
  context.SnapPanel.start();await new Promise(setImmediate);context.SnapPanel.render();
  assert.match(el.innerHTML,/Moonwood is off the floor, back in 13 s/);
  const before=writes;targets[0].respawn_in_ms=11000;await timers[0]();assert.match(el.innerHTML,/back in 11 s/,'fresh roster drives timer');
  assert.equal(writes,before,'countdown updates without replacing the order textarea or Send button');
  targets[0].held=true;targets[0].respawn_in_ms=null;await timers[0]();
  assert.match(el.innerHTML,/Moonwood is off the floor; return paused/);assert.doesNotMatch(el.innerHTML,/back in \d/);
  targets[0].held=false;targets[0].state='ring';await timers[0]();assert.doesNotMatch(el.innerHTML,/off the floor/);
  targets[0]={id:'moonwood',name:'Moonwood <reef>',state:'bench',respawn_in_ms:null};await timers[0]();
  assert.match(el.innerHTML,/Moonwood &lt;reef&gt; is off the floor; return time unavailable/);
  console.log('order-target-status: benched return countdown, held, returned, unknown and escaped name render correctly');
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
