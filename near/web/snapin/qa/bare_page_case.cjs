// Browser Claude API door -> local DEV registration refusal, with the inactive sheet still loading.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/bare_page_case.cjs
// No wallet or provider signs/calls out; the provider reply and refusal are explicit local fixtures.
'use strict';
const assert=require('node:assert/strict');
const{chromium}=require('playwright'),HOSTS=require('./hosts.cjs'),G=require('./board1_flow.cjs');
(async()=>{let browser;const failures=[];try{
 await HOSTS.start(['near/web/snapin/qa/bare_page_host.py'],o=>o.includes('bare-page-host: 18734'),HOSTS.REPO);
 browser=await chromium.launch(process.env.HTTPS_PROXY?{args:['--single-process','--no-zygote','--proxy-bypass-list=<-loopback>'],proxy:{server:process.env.HTTPS_PROXY}}:{});
 const context=await browser.newContext();
 await context.route(u=>u.hostname!=='127.0.0.1',r=>r.abort());
 await context.route('https://api.anthropic.com/v1/messages',r=>r.fulfill({status:200,headers:{'access-control-allow-origin':'*','access-control-allow-headers':'*'},json:{content:[{type:'text',text:'The tide is ready.'}],usage:{input_tokens:1,output_tokens:1}}}));
 for(const width of [1440,390]){
  const p=await context.newPage();await p.addInitScript(()=>localStorage.clear());await p.setViewportSize({width,height:width===390?844:900});
  let release,requested=false;const pending=new Promise(r=>release=r);
  await p.route('**/snapin.css',async r=>{requested=true;await pending;await r.continue();});
  await p.goto('http://127.0.0.1:18734/web/snapin/index.html?step=wallet',{waitUntil:'domcontentloaded'});await G.ready(p);
  await G.snapIn(p,{skipGoto:true,name:'Coral Scout',preset:'Hunter Lunge',door:'Claude',key:'fixture-claude-key',cap:'0.20',snap:false});
  assert.equal(await p.evaluate(()=>Snapin.state.door.door),'Claude','actual browser Claude API route selected');
  await p.click('[data-act="g:snap"]');await p.waitForFunction(()=>SnapRoom.status().phase==='error');
  const during=await p.evaluate(()=>({font:getComputedStyle(document.body).font,materialPosition:getComputedStyle(document.querySelector('svg.material')).position,links:[...document.querySelectorAll('link[rel=stylesheet]')].map(e=>({id:e.id,disabled:e.disabled,sheet:!!e.sheet})),text:document.getElementById('app').innerText}));
  console.log(JSON.stringify({width,phase:'refused while other sheet loads',requested,...during}));
  if(!during.font.includes('Space Mono')||during.materialPosition!=='absolute')failures.push(width+': refused transition has a bare document while replacement CSS is pending');
  release();await p.waitForFunction(()=>document.querySelector('main h1')?.textContent==='Not in yet'&&getComputedStyle(document.querySelector('main')).position==='relative');
  await p.evaluate(()=>document.fonts.ready);
  const after=await p.evaluate(()=>({font:getComputedStyle(document.body).font,heading:getComputedStyle(document.querySelector('main h1')).fontFamily,materialPosition:getComputedStyle(document.querySelector('main>svg.material')).position,refusal:document.querySelector('[role=alert]').innerText,links:[...document.querySelectorAll('link[rel=stylesheet]')].map(e=>({id:e.id,disabled:e.disabled,sheet:!!e.sheet}))}));
  console.log(JSON.stringify({width,phase:'styled refusal',...after}));assert(after.font.includes('Space Mono'));assert(after.heading.includes('Lilita One'));assert.equal(after.materialPosition,'absolute');assert.match(after.refusal,/not the Trenchie's persona/);
  // Repeated refusal renders and a return to the guide keep the appropriate sheet active.
  await p.evaluate(()=>{Snapin.render();Snapin.render();Snapin.view.step='wallet';Snapin.render();});
  await p.waitForFunction(()=>document.querySelector('.sign')&&getComputedStyle(document.querySelector('.sign')).position==='absolute');
  const back=await p.evaluate(()=>({font:getComputedStyle(document.body).font,heading:document.querySelector('.sign h1').innerText,active:[...document.styleSheets].filter(s=>!s.disabled&&s.href&&matchMedia(s.media.mediaText||'all').matches).map(s=>s.href)}));
  console.log(JSON.stringify({width,phase:'back to guide',...back}));assert(back.font.includes('Space Mono'));assert.match(back.heading,/Connect a NEAR wallet/);assert.equal(back.active.length,1);
  await p.close();
 }
 assert.deepEqual(failures,[]);console.log('bare-page-case: Claude browser refusal and return stay styled at1440/390 during CSS load');
}finally{if(browser)await browser.close();assert.deepEqual(await HOSTS.finish(),[]);}})().catch(e=>{console.error(e.stack);process.exitCode=1;});
