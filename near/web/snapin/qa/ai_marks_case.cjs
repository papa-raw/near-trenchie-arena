// Only the requested AI marks/copy: actual guide markup at390/1440, supplied local state, no screenshot or provider call.
// Run from repo root with Playwright on NODE_PATH. HOT_WALLET_PORT defaults to18733.
'use strict';
const assert = require('node:assert/strict'), path = require('node:path');
const { chromium } = require('playwright');
const HOSTS = require(path.resolve('near/web/snapin/qa/hosts.cjs'));
(async () => {
  let browser;
  try {
    const web = await HOSTS.start(['near/web/snapin/serve.py', '--port', process.env.HOT_WALLET_PORT || '18733', '--arena', 'http://127.0.0.1:9'], (s) => (s.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
    const base = 'http://127.0.0.1:' + web.m, launch = { args: ['--single-process', '--no-zygote'] };
    if (process.env.HTTPS_PROXY) { launch.proxy = { server: process.env.HTTPS_PROXY }; launch.args.push('--proxy-bypass-list=<-loopback>'); }
    browser = await chromium.launch(launch); const ctx = await browser.newContext(), p = await ctx.newPage();
    await ctx.route((u) => !['127.0.0.1','localhost'].includes(u.hostname), (r) => r.abort('namenotresolved'));
    await ctx.route(base + '/dev/health', (r) => r.fulfill({ json: {} }));
    await ctx.route(base + '/snap/code', (r) => r.fulfill({ json: { code: 'CASE-ICONS', expires_at: Date.now()+600000, snap_url: base+'/SNAP.md' } }));
    const expected = [['key','NEAR AI Cloud','NEAR AI Cloud','KEY'],['key','Claude','Claude','KEY'],['key','OpenRouter','OpenRouter','KEY'],['plan','Claude Code','Claude','PLAN'],['plan','Codex','Codex','PLAN']];
    for (const width of [390,1440]) {
      await p.setViewportSize({ width, height: width===390 ? 844 : 900 });
      await p.goto(base+'/web/snapin/index.html?step=wallet'); await p.waitForFunction(() => window.__SNAPIN_READY);
      await p.evaluate(() => { Object.assign(Snapin.state,{wallet:{id:'case',accountId:'case.testnet',network:'testnet'},fighterChosen:true,name:'Pebble',pick:null}); });
      await p.click('[data-act="g:step:doors"]');
      assert.equal(await p.locator('.door2').count(),expected.length,'the existing three KEY/two PLAN doors remain');
      for (const [route,name,mark,tag] of expected) {
        const button=p.locator('[data-act="g:door:'+route+':'+name+'"]');
        const value=await button.evaluate((el,want) => {
          const icon=el.querySelector('.ai-mark'), sample=document.createElement('div'); sample.innerHTML=SnapMarks.mark(want);
          const r=(n) => {const x=n?.getBoundingClientRect();return x&&{x:x.x,y:x.y,w:x.width,h:x.height};};
          return {mark:icon?.dataset.mark,svg:icon?.querySelector('svg')?.outerHTML,sample:sample.querySelector('svg').outerHTML,tag:el.querySelector('.r')?.textContent,button:r(el),icon:r(icon),name:r(el.querySelector('.door-label > span:last-child')),label:el.querySelector('.door-label')?.textContent};
        },mark);
        assert.equal(value.mark,mark,name+': approved mark present'); assert.equal(value.svg,value.sample,name+': existing inline SVG reused'); assert.equal(value.tag,tag);
        assert.equal(value.label,name); assert.ok(value.icon.w>0&&value.icon.h>0);
        assert.ok(value.icon.x+value.icon.w<=value.name.x,name+': mark beside text');
        assert.ok(value.button.x>=0&&value.button.x+value.button.w<=width+1,name+': row fits');
        assert.ok(value.icon.y>=value.button.y-1&&value.icon.y+value.icon.h<=value.button.y+value.button.h+1,name+': mark fits its existing row');
      }
      await p.click('[data-act="g:door:plan:Codex"]'); await p.waitForFunction(() => !!SnapGuide.state.code);
      assert.ok(!(await p.innerText('#app')).includes('Your own Codex session plays your Trenchie. It uses your ChatGPT plan, not a key.'),'requested Codex sentence removed');
      assert.ok(await p.locator('.cmd').textContent(),'command remains present');
      console.log('PASS existing AI marks, tags and Codex copy at '+width);
    }
    console.log('ai-marks-case: five existing marks beside provider names; KEY/PLAN kept; requested sentence gone');
  } catch(e) { console.error(e.stack||e); process.exitCode=1; }
  finally {if(browser) await browser.close(); assert.deepEqual(await HOSTS.finish(),[]);}
})();
