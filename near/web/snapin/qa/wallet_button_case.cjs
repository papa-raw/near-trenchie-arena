// The actual guide's single wallet row looks and acts like a button at desktop/phone widths.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/wallet_button_case.cjs
'use strict';
const assert=require('node:assert/strict');
const{chromium}=require('playwright'),HOSTS=require('./hosts.cjs');
const manifest={version:'1.1.0',wallets:[{id:'coral-wallet',name:'Coral Wallet',icon:'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg"/%3E',website:'https://example.invalid',version:'1',type:'sandbox',executor:'https://example.invalid/wallet.js',features:{mainnet:true,testnet:true,signInWithoutAddKey:true,signMessage:true},permissions:{}}]};
(async()=>{let browser;const failures=[];try{
 await HOSTS.start(['near/web/snapin/serve.py','--port','18734','--arena','http://127.0.0.1:9'],o=>o.includes('http://127.0.0.1:18734/'),HOSTS.REPO);
 browser=await chromium.launch(process.env.HTTPS_PROXY?{args:['--single-process','--no-zygote','--proxy-bypass-list=<-loopback>'],proxy:{server:process.env.HTTPS_PROXY}}:{});
 const context=await browser.newContext(),p=await context.newPage();
 await context.route(u=>u.hostname!=='127.0.0.1',r=>r.abort());
 for(const url of ['https://raw.githubusercontent.com/hot-dao/near-selector/refs/heads/main/repository/manifest.json','https://cdn.jsdelivr.net/gh/azbang/hot-connector/repository/manifest.json'])await context.route(url,r=>r.fulfill({json:manifest,headers:{'access-control-allow-origin':'*'}}));
 await context.route('**/dev/health',r=>r.fulfill({json:{chain_mode:{identity_network:'mainnet',identity_nft:'nft.trenchie-arena.near'}}}));
 for(const width of [1440,390]){
  await p.setViewportSize({width,height:width===390?844:900});await p.goto('http://127.0.0.1:18734/web/snapin/index.html?step=wallet');await p.waitForFunction(()=>window.__SNAPIN_READY&&window.SnapIdentity?.state().mode?.identity_network==='mainnet');
  const button=p.locator('[data-act="g:wallet:choose"]');await p.mouse.move(0,0);
  const before=await button.evaluate(e=>{const s=getComputedStyle(e);return{label:e.innerText,border:parseFloat(s.borderTopWidth),borderStyle:s.borderTopStyle,background:s.backgroundColor,cursor:s.cursor,arrow:getComputedStyle(e,'::after').content,box:e.getBoundingClientRect().toJSON()};});
  await button.hover();const hover=await button.evaluate(e=>getComputedStyle(e).backgroundColor);
  await button.focus();const focus=await button.evaluate(e=>{const s=getComputedStyle(e);return document.activeElement===e&&parseFloat(s.outlineWidth)>=2&&s.outlineStyle!=='none';});
  console.log(JSON.stringify({width,before,hover,focus}));
  if(!(before.border>=1&&before.borderStyle==='solid'&&before.background!=='rgba(0, 0, 0, 0)'&&before.cursor==='pointer'&&before.arrow.includes('→')&&hover!==before.background&&focus))failures.push(width+': visible button border/fill/arrow, hover and focus required');
  assert.match(before.label,/Connect wallet\s+MAINNET/);assert(before.box.x>=0&&before.box.right<=width);
  await button.press('Enter');await p.waitForSelector('.hot-connector-popup .connect-item[data-type="coral-wallet"]');
  assert.equal(await p.locator('.hot-connector-popup .connect-item').count(),1,'keyboard opens the stock manifest chooser');
 }
 assert.deepEqual(failures,[]);console.log('wallet-button-case: visible, hoverable, keyboard-operable stock chooser action at1440/390');
}finally{if(browser)await browser.close();assert.deepEqual(await HOSTS.finish(),[]);}})().catch(e=>{console.error(e.stack);process.exitCode=1;});
