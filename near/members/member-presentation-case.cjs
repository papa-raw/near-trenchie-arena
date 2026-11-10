// New L5/L6 comparison over real source application and refused private reads.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const captureReady=require('./capture-ready.cjs');
const [origin,shots]=process.argv.slice(2);
(async()=>{
  const proxy=process.env.HTTPS_PROXY||process.env.HTTP_PROXY;
  const browser=await chromium.launch({args:['--single-process','--no-zygote'],...(proxy?{proxy:{server:proxy}}:{})});
  const page=await browser.newPage({viewport:{width:600,height:720}});
  page.setDefaultTimeout(10000);
  const report={failures:[],captures:[],errors:[]};
  page.on('pageerror',error=>report.errors.push(String(error)));
  let visit=0;
  const check=(value,label)=>{if(!value)report.failures.push(label);};
  async function control(action,fields={}) {
    const response=await page.request.post(origin+'/__fixture',{headers:{'X-Fixture':'synthetic'},data:{action,...fields}});
    assert.equal(response.status(),200);return response.json();
  }
  async function state(expected) {await page.waitForFunction(value=>document.querySelector('#app').dataset.state===value,expected);}
  async function open(screen,expected) {await page.goto(origin+'/?presentation='+(++visit)+'#'+screen);await state(expected);}
  async function capture(name) {
    await captureReady(page);
    const facts=await page.evaluate(()=>({text:document.body.innerText,state:document.querySelector('.state').innerText,
      tone:getComputedStyle(document.querySelector('.state')).color,paper:getComputedStyle(document.querySelector('.paper')).backgroundColor,
      width:innerWidth,documentWidth:document.documentElement.scrollWidth,
      footer:document.querySelector('footer').getBoundingClientRect().height,
      controls:[...document.querySelectorAll('.button,.room-return a')].map(node=>({text:node.innerText,height:node.getBoundingClientRect().height,disabled:node.disabled||node.getAttribute('aria-disabled')==='true'}))}));
    check(facts.width>=facts.documentWidth,name+': no overflow');
    check(facts.footer>=80&&facts.controls.every(node=>node.height>=44&&!node.disabled),name+': usable controls');
    await page.screenshot({path:path.join(shots,name+'.png')});report.captures.push({name,...facts});return facts;
  }
  try {
    await control('reset',{proposal:true});const applied=await control('apply');assert.equal(applied.terms.input_interval_ms,'1500');
    await open('change','applied');const current=await capture('applied');
    check(current.state==='Applied','applied: explicit effective status');
    check(await page.locator('.compare .new').evaluate(node=>getComputedStyle(node).color)==='rgb(44, 114, 86)','applied: green current value');
    check(current.text.includes('Current\n1.5 seconds'),'applied: source effective value retained');
    for(const kind of ['terms','change','wallet','stale']) {
      await control('reset',{accepted:kind==='stale'});
      if(kind==='stale') {await open('terms','accepted');await control('unavailable');await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await state('unavailable');}
      else {await control(kind==='wallet'?'disconnect':'unavailable');await open(kind==='change'?'change':'terms',kind==='wallet'?'wallet':'unavailable');}
      await page.getByRole('button',{name:'Back',exact:true}).click();await state('return');
      const returned=await capture('return-'+kind);
      check(returned.state==='Unavailable'&&returned.tone==='rgb(168, 62, 48)',kind+': red unavailable status');
      check(returned.paper==='rgb(255, 252, 244)',kind+': opaque paper');
      check(returned.text.includes('Private room details are unavailable.'),kind+': private context explanation');
      check(!returned.text.includes('Current game rules')&&!returned.text.includes('Your persona ·')&&!returned.text.includes('Current terms accepted'),kind+': no private/stale timing or success');
      const actions=await page.locator('footer .button').allTextContents();
      check(actions.length===1&&actions[0]==='Refresh'&&await page.locator('footer .button.primary').count()===1,kind+': sole prominent Refresh');
      check(await page.getByRole('link',{name:'Room terms',exact:true}).count()===1,kind+': terms navigation');
      const change=page.getByRole('link',{name:'Room change',exact:true});
      check(await change.count()===1,kind+': change navigation');
      check(returned.text.includes(kind==='wallet'?'Wallet disconnected':'Wallet state unknown'),kind+': source auth wording');
      if(await change.count()) {await change.click();await state(kind==='wallet'?'wallet':'unavailable');check(page.url().endsWith('#change'),kind+': actual change destination');}
      await control('available');
    }
    await page.setViewportSize({width:390,height:844});await open('room','return');await capture('return-phone');
    check(report.errors.length===0,'no browser exceptions');
    fs.writeFileSync(path.join(shots,'presentation-report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({failures:report.failures,captures:report.captures.length}));assert.deepEqual(report.failures,[]);
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
