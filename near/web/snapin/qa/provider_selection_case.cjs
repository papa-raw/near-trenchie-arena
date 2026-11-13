// Real guide actions in Chromium, with deferred synthetic provider replies and no network calls.
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');
const B = require('../brain.js');
const SAVE = 'trenchie.snapin.v1';
(async () => {
  const browser = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  try {
    const page = await browser.newPage();
    await page.setContent('<input id="key"><button id="near">NEAR AI Cloud</button><button id="claude">Claude</button><button id="test">Test</button><button id="other">Other AI</button>');
    await page.evaluate(() => {
      const data = new Map([['trenchie.snapin.cap', '1']]);
      window.SnapUI = { store: { get:k=>data.get(k)||null, set:(k,v)=>data.set(k,String(v)), del:k=>data.delete(k), json:(k,d)=>data.has(k)?JSON.parse(data.get(k)):d } };
      window.pending = []; window.calls = [];
      const provider = name => ({ test: key => new Promise(resolve=>pending.push({name,key,resolve})) });
      window.SnapProviders = { nearai:provider('nearai'), claude:provider('claude') };
      window.h = { P:{}, V:{step:'doors'}, render(){}, go(step){this.V.step=step;}, save(){SnapUI.store.set('trenchie.snapin.v1',JSON.stringify(this.P));} };
      // panel.js reads the same persistent draft directly; this fixture uses the same map without origin-dependent storage.
      Object.defineProperty(window,'localStorage',{value:{getItem:k=>SnapUI.store.get(k),setItem:(k,v)=>SnapUI.store.set(k,v)}});
      window.SnapRoom = {status:()=>({phase:'in',fighter:{id:'synthetic-fighter',name:'Tide Sprig',lives:1}})};
    });
    for (const file of ['guide-copy.js','guide.js','panel.js']) await page.addScriptTag({path:path.join(__dirname,'..',file)});
    await page.evaluate(() => {
      for (const [id,act] of [['near','door:key:NEAR AI Cloud'],['claude','door:key:Claude'],['test','test'],['other','other']]) {
        document.querySelector('#'+id).onclick=()=>{calls.push(SnapGuide.act('g:'+act,h));};
      }
      document.querySelector('#key').oninput=e=>SnapGuide.input(e.target,h);
    });
    async function pick(id,key) { await page.click('#'+id); if(key) await page.fill('#key',key); }
    async function finish(index,reply) { await page.evaluate(async({index,reply})=>{pending[index].resolve(reply);await new Promise(resolve=>setTimeout(resolve,0));},{index,reply}); }
    const good = {ok:true,say:'Clouds clear.'};
    // Baseline774b5ae: NEAR's older reply overwrites the successful Claude choice.
    await pick('near','synthetic-near-key'); await page.click('#test');
    await pick('claude','synthetic-claude-key'); await page.click('#test');
    await finish(1,good); await finish(0,good);
    const saved = await page.evaluate(()=>JSON.parse(SnapUI.store.get('trenchie.snapin.v1')));
    assert.equal(saved.door.door,'Claude','stale NEAR success must not replace the tested Claude choice');
    assert.equal(await page.evaluate(()=>SnapPanel.mine().door),'Claude','panel source agrees with accepted provider');
    const rows = await page.evaluate(()=>Object.fromEntries(['trenchie.snapin.v1','trenchie.snapin.cap','trenchie.snapin.key.Claude','trenchie.snapin.key.NEAR AI Cloud'].map(k=>[k,SnapUI.store.get(k)])));
    const store = {get:k=>rows[k]??null,json:(k,d)=>rows[k]?JSON.parse(rows[k]):d};
    const choice = B.create({store,room:{}}).choices();
    assert.equal(choice.provider,'claude'); assert.equal(choice.key,'synthetic-claude-key');
    const requests=[];
    const reply=await B.chat(choice.provider,choice.key,'A synthetic instruction.','A synthetic order.',{fetch:async(url,init)=>{
      requests.push({url,init}); return {status:200,text:async()=>JSON.stringify({content:[{type:'text',text:'Ready.'}],usage:{input_tokens:1,output_tokens:1}})};
    }});
    assert.equal(reply.ok,true); assert.equal(requests.length,1); assert.match(requests[0].url,/api\.anthropic\.com/);
    assert.equal(requests[0].init.headers['x-api-key'],'synthetic-claude-key');
    assert.equal(rows['trenchie.snapin.key.NEAR AI Cloud'],null,'ignored test does not save its key');
    console.log('PASS stale result cannot change panel, saved provider, or actual provider request');
    await pick('near');
    assert.equal(await page.evaluate(()=>SnapGuide.aiReady(h)),false,'old Claude readiness cannot approve newly selected NEAR');
    await page.click('#claude');
    assert.equal(await page.evaluate(()=>SnapGuide.aiReady(h)),true,'returning to tested Claude preserves readiness');
    // Same-provider tests, key edits, abandoned doors and failed replies must also respect request order.
    await page.fill('#key','synthetic-old-key'); await page.click('#test');
    await page.fill('#key','synthetic-new-key'); await page.click('#test');
    await finish(3,good); await finish(2,{ok:false,kind:'bad-key'});
    assert.equal(await page.evaluate(()=>SnapGuide.state.keyStatus),'ok');
    assert.equal(await page.evaluate(()=>SnapUI.store.get('trenchie.snapin.key.Claude')),'synthetic-new-key');
    await page.fill('#key','synthetic-uncommitted-key'); await page.click('#test');
    await page.fill('#key','synthetic-edited-key'); await finish(4,good);
    assert.equal(await page.evaluate(()=>SnapUI.store.get('trenchie.snapin.key.Claude')),'synthetic-new-key');
    assert.equal(await page.evaluate(()=>SnapGuide.state.keyStatus),'');
    await page.click('#test'); await page.click('#other'); await finish(5,good);
    assert.equal(await page.evaluate(()=>h.P.pick),null);
    assert.equal(await page.evaluate(()=>SnapUI.store.get('trenchie.snapin.key.Claude')),'synthetic-new-key');
    assert.equal(await page.evaluate(()=>SnapGuide.aiReady(h)),true,'existing tested door remains available without a new selection');
    await page.evaluate(()=>{h.P.door={door:'Claude',route:'plan',identity:'Claude Code'};h.P.pick={route:'plan',door:'Claude Code'};});
    assert.equal(await page.evaluate(()=>SnapGuide.aiReady(h)),true,'matching agent-session door stays ready');
    await page.evaluate(()=>{h.P.pick={route:'plan',door:'Codex'};});
    assert.equal(await page.evaluate(()=>SnapGuide.aiReady(h)),false,'another agent-session door needs its own pairing');
    console.log('PASS current selection, same-provider retries, edited key, and abandoned test stay consistent');
    // Provider failure stays with the chosen provider; it never invokes a second endpoint.
    const failed=[];
    const failure=await B.chat(choice.provider,choice.key,'Synthetic.','Synthetic.',{fetch:async(url)=>{failed.push(url);return {status:401,text:async()=>JSON.stringify({error:{message:'invalid api key'}})};}});
    assert.equal(failure.ok,false); assert.equal(failed.length,1); assert.match(failed[0],/api\.anthropic\.com/);
    assert.equal(SAVE,B.constants.SAVE);
    console.log('PASS failed Claude call has no provider fallback');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
