// Actual signed null terms, outage and trusted host publication are separate facts.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const captureReady=require('./capture-ready.cjs');
const [origin,shots]=process.argv.slice(2);
(async()=>{
  const proxy=process.env.HTTPS_PROXY||process.env.HTTP_PROXY;
  const browser=await chromium.launch({args:['--single-process','--no-zygote'],...(proxy?{proxy:{server:proxy}}:{})});
  const page=await browser.newPage({viewport:{width:600,height:720}});
  page.setDefaultTimeout(10000);
  const report={errors:[],captures:[],source_published:false,recorded_acceptance:false};
  page.on('pageerror',error=>report.errors.push(String(error)));
  async function control(action) {
    const response=await page.request.post(origin+'/__fixture',{headers:{'X-Fixture':'synthetic'},data:{action}});
    assert.equal(response.status(),200);return response.json();
  }
  async function state(value) {await page.waitForFunction(expected=>document.querySelector('#app').dataset.state===expected,value);}
  async function capture(name) {
    await captureReady(page);
    const facts=await page.evaluate(()=>({state:document.querySelector('#app').dataset.state,text:document.body.innerText,
      width:innerWidth,documentWidth:document.documentElement.scrollWidth,
      controls:[...document.querySelectorAll('.button')].map(node=>({height:node.getBoundingClientRect().height,disabled:node.disabled})),
      footer:document.querySelector('footer').getBoundingClientRect().height}));
    assert.ok(facts.documentWidth<=facts.width&&facts.footer>=80&&facts.controls.every(node=>node.height>=44&&!node.disabled));
    await page.screenshot({path:path.join(shots,name+'.png')});report.captures.push({name,...facts});return facts;
  }
  try {
    await page.goto(origin+'/#terms');await state('empty');
    const empty=await capture('terms-unpublished');
    assert.match(empty.text,/No terms yet/);assert.match(empty.text,/The room has not published its terms/);
    assert.equal(await page.getByRole('button',{name:'Accept terms',exact:true}).count(),0);
    for(const [width,height] of [[390,844],[768,900],[1200,800],[1440,1040]]) {
      await page.setViewportSize({width,height});await capture('terms-unpublished-'+width);
    }
    await page.setViewportSize({width:600,height:720});
    await page.getByRole('button',{name:'Back',exact:true}).click();await state('return');
    const waiting=await capture('room-waiting');assert.match(waiting.text,/Waiting for room terms/);assert.ok(!waiting.text.includes('Current terms accepted'));
    await page.getByRole('link',{name:'Room terms',exact:true}).click();await state('empty');
    await control('unavailable');await page.getByRole('button',{name:'Refresh',exact:true}).click();await state('unavailable');
    await capture('terms-failed-not-empty');
    await control('available');await page.getByRole('button',{name:'Refresh',exact:true}).click();await state('empty');
    await control('publish_terms');await page.getByRole('button',{name:'Refresh',exact:true}).click();await state('review');
    const published=await page.request.get(origin+'/api/member');const view=await published.json();
    assert.equal(view.snapshot.terms.version,'8');assert.equal(view.snapshot.terms.accepted,false);report.source_published=true;
    await capture('terms-published-review');
    await page.getByRole('button',{name:'Review room rules',exact:true}).click();await state('policy');
    await page.getByRole('button',{name:'Accept terms',exact:true}).click();await state('accepted');await capture('terms-published-accepted');
    await page.reload();await state('accepted');report.recorded_acceptance=true;
    assert.deepEqual(report.errors,[]);
    fs.writeFileSync(path.join(shots,'unpublished-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
