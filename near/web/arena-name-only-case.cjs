// Real HUD and tag CSS: names remain clickable without style text, hover cards or native titles.
// NODE_PATH=<Playwright module directory> node near/web/arena-group-tags-off-case.cjs
'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..');
const MIME = { '.js': 'application/javascript', '.mjs': 'application/javascript', '.css': 'text/css', '.woff2': 'font/woff2' };

(async () => {
  const arena = await fs.readFile(path.join(__dirname, 'arena.html'), 'utf8');
  const style = arena.match(/<style>[\s\S]*?<\/style>/)[0];
  const html = style + '<link rel="stylesheet" href="/web/arena/board2.css"><script type="importmap">{"imports":{"three":"/web/vendor/three/three.module.min.js"}}</script><div id="tags"></div>';
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/') { res.setHeader('Content-Type', 'text/html'); res.end(html); return; }
    const file = path.resolve(ROOT, '.' + url.pathname);
    if (!file.startsWith(ROOT + path.sep)) { res.writeHead(404).end(); return; }
    try { const body = await fs.readFile(file); res.setHeader('Content-Type', MIME[path.extname(file)] || 'application/octet-stream'); res.end(body); }
    catch { res.writeHead(404).end(); }
  });
  let browser;
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(18736, '127.0.0.1', resolve); });
    browser = await chromium.launch(process.env.HTTPS_PROXY ? {
      headless: true, args: ['--mute-audio', '--single-process', '--no-zygote', '--proxy-bypass-list=<-loopback>'], proxy: { server: process.env.HTTPS_PROXY },
    } : {headless:true,args:['--mute-audio']});
    const page = await browser.newPage(), reports = [], errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    for (const width of [1440, 390]) {
      await page.setViewportSize({width,height:844}); await page.goto('http://127.0.0.1:18736/');
      const report=await page.evaluate(async()=>{
        const {Hud}=await import('/web/arena/hud.mjs');
        const h=Object.assign(Object.create(Hud.prototype),{w:innerWidth,h:innerHeight,tags:new Map(),styles:new Map([['moonwood','Survivor']]),bounties:new Set(),details:{rules:{item_quirks:{conviction:{text:'Conviction floats longer; the next boat takes longer.'}}}},
          KITS:{roster:[{trenchieId:'moonwood',tag:'Moonwood',name:'Kathie Moonwood',fightStyle:'Survivor'}],players:[]},
          tagLayer:document.getElementById('tags'),rects:{},toScreen:(x,y,z)=>({x,y:z})});
        h.placeTags(new Map([['moonwood',{x:innerWidth/2,z:400,state:'alive',f:{status:0,items:{weapon:'conviction'},target:null}}]]),null,0);
        const node=h.tags.get('moonwood');
        return {text:node.textContent,title:node.getAttribute('title'),quirks:node.querySelectorAll('.quirk-line').length,clickId:node.dataset.fighterId};
      });
      reports.push(report);
      assert.equal(report.text,'Moonwood'); assert.ok(!report.title); assert.equal(report.quirks,0); assert.equal(report.clickId,'moonwood');
      await page.locator('.atag').hover();
      assert.equal(await page.locator('.atag').innerText(),'Moonwood');
      assert.equal(await page.locator('.quirk-line:visible').count(),0);
      await page.locator('.atag').click();
    }
    assert.deepEqual(errors,[]); process.stdout.write(JSON.stringify({case:'arena-name-only',reports})+'\n');
  } finally { if (browser) await browser.close(); await new Promise(resolve=>server.close(resolve)); }
})().catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;});
