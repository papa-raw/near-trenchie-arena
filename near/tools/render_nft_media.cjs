#!/usr/bin/env node
// Render the approved preset looks once. Publish v1 bytes unchanged: contract hashes pin these assets.
// NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/tools/render_nft_media.cjs
'use strict';
const fs = require('fs'), path = require('path'), http = require('http');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const html = `<!doctype html><html><head><link rel="icon" href="data:,"><script type="importmap">{"imports":{"three":"/web/vendor/three/three.module.min.js"}}</script></head><body><script type="module">
import * as THREE from 'three'; import {LOOK3} from '/web/art/index.js';
window.THREE=THREE; window.LOOK3=LOOK3;
for(const src of ['/web/snapin/art/parts-s3.js','/web/snapin/art/portrait.js']) {
 await new Promise((resolve,reject)=>{const s=document.createElement('script');s.src=src;s.onload=resolve;s.onerror=reject;document.head.appendChild(s)});
} window.ready=true;
</script></body></html>`;
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if(url.pathname === '/render') {res.setHeader('Content-Type','text/html');return res.end(html);}
  const file = path.resolve(root, '.' + decodeURIComponent(url.pathname));
  if(!file.startsWith(root+path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {res.statusCode=404;return res.end();}
  res.setHeader('Content-Type', file.endsWith('.js')?'text/javascript':file.endsWith('.json')?'application/json':'application/octet-stream');
  fs.createReadStream(file).pipe(res);
});
(async()=>{
  let browser;
  try {
    await new Promise(r=>server.listen(Number(process.env.NFT_RENDER_PORT || 18736),'127.0.0.1',r));
    const launch={args:['--no-zygote','--single-process','--use-angle=swiftshader','--enable-unsafe-swiftshader']};
    if(process.env.HTTPS_PROXY){launch.proxy={server:process.env.HTTPS_PROXY};launch.args.push('--proxy-bypass-list=<-loopback>');}
    browser=await chromium.launch(launch);
    const page=await browser.newPage();
    const errors=[];page.on('pageerror', e=>errors.push(e));
    await page.goto(`http://127.0.0.1:${server.address().port}/render`);
    await page.waitForFunction(()=>window.ready);
    if(errors.length)throw errors[0];
    const opts=JSON.parse(fs.readFileSync(path.join(root,'web/snapin/premint/meta/options.json')));
    fs.mkdirSync(path.join(root,'nft/v1'),{recursive:true});
    for(const [preset,meta] of Object.entries(opts)) {
      const kit=JSON.parse(fs.readFileSync(path.join(root,'nft/v1/starter-kits.json')))[preset].loadout;
      const look=JSON.parse(fs.readFileSync(path.join(root,'web/snapin/premint',meta.look))).look;
      const uri=await page.evaluate(({look,kit})=>{
        const original=LOOK3.makeTrenchie;LOOK3.makeTrenchie=row=>original(Object.assign({},row,{kit}));
        try{return SKP.portrait({s3:look,w:512,h:512,dpr:1,bg:'#c9dfd1'});}finally{LOOK3.makeTrenchie=original;}
      },{look,kit});
      const png=Buffer.from(uri.split(',')[1],'base64');
      fs.writeFileSync(path.join(root,`nft/v1/${preset}.png`),png);
      console.log(preset,png.length,'bytes');
    }
  } finally {if(browser)await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1});
