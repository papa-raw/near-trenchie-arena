const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const [empty, omitted, present, shots] = process.argv.slice(2);
(async () => {
  const proxyServer = process.env.HTTPS_PROXY || process.env.HTTP_PROXY;
  const browser = await chromium.launch({args:['--single-process','--no-zygote'],
    ...(proxyServer ? {proxy:{server:proxyServer}} : {})});
  const page = await browser.newPage({viewport:{width:640,height:800}});
  const failures = [], errors = [], receipts = [];
  page.on('pageerror', error => errors.push(String(error)));
  function check(label, operation) {
    try {operation();} catch (error) {failures.push(label + ': ' + error.message);}
  }
  async function capture(name) {
    await page.evaluate(async () => {
      await document.fonts.ready;
      await Promise.all([...document.images].map(image => image.decode()));
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    await page.screenshot({path:path.join(shots,name+'.png'),fullPage:true});
  }
  try {
    for (const [state, origin] of [['empty',empty],['omitted',omitted],['present',present]]) {
      await page.goto(origin);
      await page.waitForFunction(()=>document.documentElement.dataset.ready==='true');
      const summary = await page.locator('[data-step="forecast"] .row-note').innerText();
      const source = await (await page.request.get(origin+'/api/evidence')).json();
      check(state+' source check',()=>assert.equal(source.state,'checked'));
      await page.locator('[data-view="forecast"]').click();
      const forecast = await page.locator('#detail').innerText();
      if (state === 'empty') {
        check('empty summary',()=>assert.equal(summary,'No forecasts in this record'));
        check('empty forecast',()=>assert.match(forecast,/No forecasts in this record/));
        check('empty has no fixture call',()=>assert.doesNotMatch(forecast,/fixture's call|Locked before the fight/));
      } else if (state === 'omitted') {
        check('omitted summary',()=>assert.equal(summary,'All forecasts omitted'));
        check('omitted forecast',()=>assert.match(forecast,/No forecasts for these lives/));
        check('omitted keeps life',()=>assert.match(forecast,/alice:life:0/));
        check('omitted has no locked claim',()=>assert.doesNotMatch(forecast,/fixture's call|Locked before the fight/));
      } else {
        check('present summary',()=>assert.match(summary,/1 forecast locked/));
        check('present forecast',()=>assert.match(forecast,/Locked before the fight/));
        check('present percentage',()=>assert.match(forecast,/25%/));
      }
      await capture(state+'-forecast');
      await page.locator('[data-view="replay"]').click();
      const replay = await page.locator('#detail').innerText();
      check(state+' replay stays checked',()=>assert.match(replay,/Replay checked locally/));
      const relation = await page.locator('.resultpair').innerText();
      if (state !== 'present') {
        check(state+' replay no forecast',()=>assert.match(relation,/No forecasts/));
        check(state+' replay no locked claim',()=>assert.doesNotMatch(relation,/Locked before the fight/));
      } else check('present replay relation',()=>assert.match(relation,/1 forecast locked/));
      check(state+' chain pending',()=>assert.match(replay,/Chain check pending/));
      await page.getByText('What must match',{exact:false}).click();
      const hashes = await page.locator('[data-hash]').allTextContents();
      check(state+' retained hash',()=>assert.deepEqual(hashes,[source.recorded_hash,source.recorded_hash]));
      await capture(state+'-replay');
      await page.locator('[data-close]').click();
      await page.locator('[data-view="replay"]').click();
      const returned = await page.locator('.resultpair').innerText();
      check(state+' return keeps relation',()=>assert.equal(returned,relation));
      await page.reload();
      await page.waitForFunction(()=>document.documentElement.dataset.ready==='true');
      const reloaded = await page.locator('.resultpair').innerText();
      check(state+' reload keeps relation',()=>assert.equal(reloaded,relation));
      receipts.push({state,summary,forecast,relation,recorded_hash:source.recorded_hash});
    }
    check('browser exceptions',()=>assert.deepEqual(errors,[]));
    fs.writeFileSync(path.join(shots,'presence-report.json'),JSON.stringify({receipts,failures,errors},null,2));
    assert.deepEqual(failures,[]);
    process.stdout.write(JSON.stringify({states:receipts.length,captures:6,failures,errors})+'\n');
  } finally {await browser.close();}
})().catch(error=>{process.stderr.write(String(error.stack)+'\n');process.exitCode=1;});
