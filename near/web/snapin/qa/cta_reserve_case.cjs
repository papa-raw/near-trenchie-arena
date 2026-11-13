// Actual HUD layers, frozen candle art and CTA placement: moving HP bars are never fixed-panel obstacles.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/cta_reserve_case.cjs
'use strict';
const assert=require('node:assert/strict'),http=require('node:http'),fs=require('node:fs/promises'),path=require('node:path');
const{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'../..'),MIME={'.js':'text/javascript','.mjs':'text/javascript','.css':'text/css','.woff2':'font/woff2','.png':'image/png'};
(async()=>{let browser,server;try{
 const source=await fs.readFile(path.join(ROOT,'arena.html'),'utf8');
 const html='<meta charset="utf-8">'+source.match(/<style>[\s\S]*?<\/style>/)[0]+'<link rel="stylesheet" href="/arena/board2.css"><script type="importmap">{"imports":{"three":"/vendor/three/three.module.min.js"}}</script><script src="/hud-art/hud-art.js"></script><div id="world" style="position:fixed;inset:0"></div>'+source.match(/<a id="snapin-cta"[\s\S]*?<\/a>\s*<script>[\s\S]*?<\/script>/)[0];
 server=http.createServer(async(req,res)=>{const u=new URL(req.url,'http://localhost');if(u.pathname==='/case'){res.setHeader('Content-Type','text/html');res.end(html);return;}const file=path.resolve(ROOT,'.'+u.pathname);if(!file.startsWith(ROOT+path.sep)){res.writeHead(404).end();return;}try{res.setHeader('Content-Type',MIME[path.extname(file)]||'application/octet-stream');res.end(await fs.readFile(file));}catch{res.writeHead(404).end();}});
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(18734,'127.0.0.1',resolve);});
 browser=await chromium.launch(process.env.HTTPS_PROXY?{args:['--single-process','--no-zygote','--proxy-bypass-list=<-loopback>'],proxy:{server:process.env.HTTPS_PROXY}}:{});const p=await browser.newPage(),failures=[];
 for(const width of [1440,390]){
  await p.setViewportSize({width,height:width===390?844:900});await p.goto('http://127.0.0.1:18734/case');
  const report=await p.evaluate(async()=>{
   const{Hud}=await import('/arena/hud.mjs');const hud=new Hud({stage:{},actors:{},KITS:{roster:[],players:[]},ITEMS:{},root:document.getElementById('world')});
   await hud.buildBars();hud.placeBars([{id:'coral',x:180,y:330,hp:0.8},{id:'pebble',x:260,y:420,hp:0.6}]);
   const art=document.createElement('div');document.body.append(art);await HUDART.mount(art,{concept:'candle',draft:'a',w:innerWidth,h:innerHeight,fighters:[],feed:[]});const board=art.querySelector('[data-panel="board"]');board.style.transform='translate(12px,20px)';hud.cardLayer.append(board);art.remove();
   const rect=e=>{const r=e.getBoundingClientRect();return{left:r.left,top:r.top,right:r.right,bottom:r.bottom};};
   const same=(a,b)=>['left','top','right','bottom'].every(k=>Math.abs(a[k]-b[k])<0.5);
   const candles=[...hud.bars.values()].map(b=>b.el);const originalMeta=candles.map(e=>({panel:e.dataset.panel||null,kind:e.dataset.kind||null}));
   // Exercise legacy/unexpected panel metadata on real moving candles, independently of the fixed-panel selector.
   candles.forEach((e,i)=>{e.dataset.panel='bar'+i;e.firstElementChild.dataset.panel='bar-inner'+i;});
   const count=()=>{const reserved=__ctaReserved();return candles.filter(e=>reserved.some(r=>same(r,rect(e)))).length;};
   dispatchEvent(new Event('resize'));const initial=count(),positions=[];
   const a=document.getElementById('snapin-cta');
   for(let i=0;i<3;i++){hud.placeBars([{id:'coral',x:120+i*55,y:370+i*30,hp:0.8},{id:'pebble',x:280-i*40,y:430-i*20,hp:0.6}]);dispatchEvent(new Event('resize'));positions.push({x:a.style.getPropertyValue('--cta-x'),y:a.style.getPropertyValue('--cta-y'),reserved:count()});}
   const sizes=candles.map(e=>{const r=e.getBoundingClientRect();return{w:r.width,h:r.height};});
   return{width:innerWidth,candles:candles.length,sizes,originalMeta,cardCalledCandle:hud.cardLayer.classList.contains('ha-candle'),initial,positions,boardReserved:__ctaReserved().some(r=>same(r,rect(board))),fixedPanels:document.querySelectorAll('#world [data-panel="board"]').length};
  });
  console.log(JSON.stringify(report));
  assert.equal(report.candles,2);assert(report.sizes.every(r=>r.w>0&&r.h>0),'real candle geometry is present');assert(report.fixedPanels>0&&report.boardReserved,'positive control: fixed board stays reserved');assert.equal(new Set(report.positions.map(p=>p.x+','+p.y)).size,1,'moving only HP bars keeps the CTA in one spot');
  if(report.cardCalledCandle||report.initial!==0||report.positions.some(p=>p.reserved!==0))failures.push(width+': fixed cards must be distinct from HP candles; moving candles reserve zero rectangles even with panel metadata');
 }
 assert.deepEqual(failures,[]);console.log('cta-reserve-case: nonempty moving HP candles excluded, fixed board retained at1440/390');
}finally{if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));}})().catch(e=>{console.error(e.stack);process.exitCode=1;});
