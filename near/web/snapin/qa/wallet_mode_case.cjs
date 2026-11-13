// The actual wallet guide must not offer a DEV throwaway while the host's identity mode is unknown.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/wallet_mode_case.cjs
'use strict';
const assert=require('node:assert/strict');
const{chromium}=require('playwright'),HOSTS=require('./hosts.cjs');
(async()=>{let browser;const failures=[];try{
 await HOSTS.start(['near/web/snapin/serve.py','--port','18734','--arena','http://127.0.0.1:9'],o=>o.includes('http://127.0.0.1:18734/'),HOSTS.REPO);
 browser=await chromium.launch(process.env.HTTPS_PROXY?{args:['--single-process','--no-zygote','--proxy-bypass-list=<-loopback>'],proxy:{server:process.env.HTTPS_PROXY}}:{});
 const context=await browser.newContext();await context.route(u=>u.hostname!=='127.0.0.1',r=>r.abort());
 for(const width of [1440,390])for(const mode of ['chain','dev','unavailable']){
  const p=await context.newPage();await p.addInitScript(()=>localStorage.clear());await p.setViewportSize({width,height:width===390?844:900});
  let release;const gate=new Promise(r=>release=r);
  await p.route('**/dev/health',async r=>{await gate;await r.fulfill({status:mode==='unavailable'?503:200,json:mode==='chain'?{chain_mode:{identity_network:'mainnet',identity_nft:'nft.trenchie-arena.near'}}:mode==='dev'?{dev:true}:{error:'fixture unavailable'}});});
  await p.goto('http://127.0.0.1:18734/web/snapin/index.html?step=wallet',{waitUntil:'domcontentloaded'});await p.waitForFunction(()=>window.__SNAPIN_READY);
  const pending=await p.locator('[data-act="g:wallet:dev-throwaway"]').count(), prematureConnect=await p.locator('[data-act="g:wallet:choose"]').isEnabled();
  const response=p.waitForResponse(r=>new URL(r.url()).pathname==='/dev/health');release();await(await response).finished();
  await p.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const settled=await p.locator('[data-act="g:wallet:dev-throwaway"]').count(), connectReady=await p.locator('[data-act="g:wallet:choose"]').isEnabled();
  console.log(JSON.stringify({width,mode,pending,settled,prematureConnect,connectReady,known:await p.evaluate(()=>SnapIdentity.state().modeKnown)}));
  if(prematureConnect||connectReady!==(mode!=='unavailable'))failures.push(width+'/'+mode+': connect must wait for a known wallet network');
  if(pending!==0)failures.push(width+'/'+mode+': no throwaway until a successful mode response');
  if(settled!==(mode==='dev'?1:0))failures.push(width+'/'+mode+': only a confirmed DEV host offers a throwaway');
  await p.close();
 }
 assert.deepEqual(failures,[]);console.log('wallet-mode-case: delayed mainnet/DEV/failure modes offer no premature throwaway at1440/390');
}finally{if(browser)await browser.close();assert.deepEqual(await HOSTS.finish(),[]);}})().catch(e=>{console.error(e.stack);process.exitCode=1;});
