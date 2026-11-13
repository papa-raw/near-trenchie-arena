// Real browser + real DEV room, controlled sim ticks and engine KO: last-life prediction stays with its life.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/corner_life_case.cjs
'use strict';
const assert=require('node:assert/strict');
const{chromium}=require('playwright'),HOSTS=require('./hosts.cjs');
let page;
async function step(data){return page.evaluate(async data=>{const r=await fetch('/case/step',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(!r.ok)throw new Error(await r.text());return r.json();},data);}
(async()=>{let browser;try{
 await HOSTS.start(['near/web/snapin/qa/corner_life_host.py'],o=>o.includes('corner-life-host:'),HOSTS.REPO);
 browser=await chromium.launch(process.env.HTTPS_PROXY?{args:['--single-process','--no-zygote','--proxy-bypass-list=<-loopback>'],proxy:{server:process.env.HTTPS_PROXY}}:{});
 const p=page=await browser.newPage();await p.route(u=>u.hostname!=='127.0.0.1',r=>r.abort());
 await p.goto('http://127.0.0.1:18734/web/snapin/index.html?step=wallet');await p.waitForFunction(()=>window.__SNAPIN_READY);
 await p.evaluate(async()=>{const terms=await SnapRoom.terms();await SnapRoom.join({name:'Coral Scout',preset:'hunter-lunge',termsVersion:terms.version,order:{preset:'hunter-lunge',prediction:false}});});
 const first=await p.evaluate(()=>SnapRoom.status().fighter);console.log('first browser state',JSON.stringify(first));
 await step({fighter:first.id,ticks:1});
 // Reach the real corner view from the browser URL, preserving its authenticated control key/session.
 await p.goto('http://127.0.0.1:18734/web/snapin/index.html?mode=workshop&tab=respawn');await p.waitForFunction(()=>window.__SNAPIN_READY&&window.SnapRoom?.status().phase==='in');
 await p.waitForSelector('[data-act="ready"]');
 for(let i=0;i<4;i++)await p.fill('[data-spread="'+i+'"]','25');await p.fill('#zero-ko','20');await p.click('[data-act="next-preset:brawler-zap"]');await p.click('[data-act="ready"]');await p.waitForFunction(()=>document.getElementById('locked')?.innerText.startsWith('Saved.'));
 const ready=await p.evaluate(()=>({fighter:SnapRoom.status().fighter,message:document.getElementById('locked').innerText}));console.log('ready',JSON.stringify(ready));
 assert.match(ready.message,/Saved/);
 // Reload while the first life's prediction window is still open: Ready is for the next life.
 await p.reload();await p.waitForFunction(()=>window.__SNAPIN_READY&&window.SnapRoom?.status().phase==='in');
 const resumed=await p.evaluate(()=>SnapRoom.status().fighter);console.log('resumed same life',JSON.stringify(resumed));
 assert.equal(resumed.lastPick.state,'none','reconnecting must not file the next-life Ready choice into this life');
 await step({fighter:first.id,ticks:50});
 await step({fighter:first.id,ko:true});
 const inspect=async label=>{await p.waitForTimeout(1200);const got=await p.evaluate(async()=>({host:await(await fetch('/dev/corner?fighter='+SnapRoom.status().fighter.id)).json(),drawn:Snapin.corner.data?.last_life,text:document.querySelector('main').innerText,fighter:SnapRoom.status().fighter}));console.log(label,JSON.stringify(got));return got;};
 const down=await inspect('first KO');
 assert.equal(down.host.last_life.life_id,first.life);assert.equal(down.host.last_life.prediction,null,'first life filed none, not the Ready prediction');assert.match(down.text,/You predicted\s*nothing filed/);
 let next;
 for(let i=0;i<20;i++){await step({fighter:first.id,ticks:20});await p.waitForTimeout(300);next=await p.evaluate(()=>SnapRoom.status().fighter);if(next.life!==first.life&&next.lastPick?.state==='accepted')break;}
 assert.notEqual(next.life,first.life);assert.deepEqual(next.lastPick.order.spread,[25,25,25,25]);
 const running=await inspect('next life running');assert.equal(running.host.last_life.life_id,first.life);assert.equal(running.host.last_life.prediction,null);
 // An already accepted current prediction also survives reconnect after another Ready edit.
 for(let i=0;i<4;i++)await p.fill('[data-spread="'+i+'"]',i===0?'100':'0');await p.fill('#zero-ko','7');await p.click('[data-act="ready"]');
 await p.waitForFunction(()=>document.getElementById('locked')?.innerText.includes('100/0/0/0'));
 await p.reload();await p.waitForFunction(()=>window.__SNAPIN_READY&&window.SnapRoom?.status().phase==='in');
 const accepted=await p.evaluate(()=>SnapRoom.status().fighter.lastPick);console.log('accepted after another Ready/reload',JSON.stringify(accepted));
 assert.equal(accepted.state,'accepted');assert.deepEqual(accepted.order.spread,[25,25,25,25]);assert.equal(accepted.order.zero,20);
 await step({fighter:first.id,ko:true});const ended=await inspect('next KO');assert.equal(ended.host.last_life.life_id,next.life);assert.equal(ended.host.last_life.prediction.spread_bps.one,2500);assert.match(ended.text,/1: 25%/);
 console.log('corner-life-case: no prediction and Ready prediction remain bound to their own lives');
}finally{if(browser)await browser.close();assert.deepEqual(await HOSTS.finish(),[]);}})().catch(e=>{console.error(e.stack);process.exitCode=1;});
