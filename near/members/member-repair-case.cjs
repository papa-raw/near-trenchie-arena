// New focused browser reproduction over the actual room-backed owner runtime.
const fs=require('fs'), path=require('path'), assert=require('node:assert/strict');
const {chromium}=require('playwright');
const captureReady=require('./capture-ready.cjs');
const [origin,shots]=process.argv.slice(2);
(async()=>{
  const proxy=process.env.HTTPS_PROXY||process.env.HTTP_PROXY;
  const browser=await chromium.launch({args:['--single-process','--no-zygote'],...(proxy?{proxy:{server:proxy}}:{})});
  const page=await browser.newPage({viewport:{width:600,height:720}});
  page.setDefaultTimeout(10000);
  const report={failures:[],exits:[],captures:[],errors:[]};
  page.on('pageerror',error=>report.errors.push(String(error)));
  let visit=0;
  const check=(ok,message)=>{if(!ok)report.failures.push(message);};
  async function control(action,fields={}) {
    const response=await page.request.post(origin+'/__fixture',{headers:{'X-Fixture':'synthetic'},data:{action,...fields}});
    assert.equal(response.status(),200,await response.text());return response.json();
  }
  async function state(expected) {await page.waitForFunction(value=>document.querySelector('#app').dataset.state===value,expected);}
  async function open(screen,expected) {await page.goto(origin+'/?repair='+(++visit)+'#'+screen);await state(expected);}
  async function capture(name) {
    await captureReady(page);
    const facts=await page.evaluate(()=>({state:document.querySelector('#app').dataset.state,text:document.body.innerText,
      images:[...document.images].map(image=>({width:image.naturalWidth,complete:image.complete})),
      width:innerWidth,documentWidth:document.documentElement.scrollWidth,
      buttons:[...document.querySelectorAll('.button')].map(node=>({height:node.getBoundingClientRect().height,disabled:node.disabled})),
      footer:document.querySelector('footer').getBoundingClientRect().height}));
    check(facts.images.every(image=>image.complete&&image.width>0),name+': current image ready');
    check(facts.documentWidth<=facts.width,name+': no overflow');
    check(facts.buttons.every(button=>button.height>=44&&!button.disabled)&&facts.footer>=80,name+': active sized controls');
    await page.screenshot({path:path.join(shots,name+'.png')});report.captures.push({name,...facts});return facts;
  }
  try {
    // Keep the current policy image, including a freshly inserted SPA image.
    await open('terms','review');await page.getByRole('button',{name:'Review room rules',exact:true}).click();
    await state('policy');await capture('policy-painted');
    for(const kind of ['terms','change','wallet','stale']) {
      await control('reset',{accepted:kind==='stale'});
      if(kind==='stale') {await open('terms','accepted');await control('unavailable');await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await state('unavailable');}
      else {await control(kind==='wallet'?'disconnect':'unavailable');await open(kind==='change'?'change':'terms',kind==='wallet'?'wallet':'unavailable');}
      const before=await capture('fault-'+kind);
      check(before.text.includes('Meadow ring'),kind+': trusted room label survives failure');
      check(before.text.includes(kind==='wallet'?'Wallet disconnected':'Wallet state unknown'),kind+': truthful wallet status');
      check(await page.locator('.wallet').evaluate(node=>node.classList.contains('off')),kind+': unknown auth uses neutral marker');
      await page.getByRole('button',{name:'Back',exact:true}).click();
      await page.waitForFunction(()=>location.hash==='#room');
      const after=await capture('return-'+kind);report.exits.push({kind,before,after});
      check(after.state==='return'&&await page.locator('h1').innerText()==='Meadow ring',kind+': Back reaches room');
      check(!after.text.includes('Current terms accepted')&&!after.text.includes('Your persona ·'),kind+': no stale private success');
      check(await page.getByRole('button',{name:'Accept terms',exact:true}).count()===0,kind+': no unreviewed consent');
      if(await page.getByRole('button',{name:'Room terms',exact:true}).count()) await page.getByRole('button',{name:'Room terms',exact:true}).click();
      else await page.evaluate(()=>{location.hash='terms';});
      await state(kind==='wallet'?'wallet':'unavailable');
      await control('available');
    }
    await control('reset',{proposal:true});
    const source=await control('apply');assert.equal(source.applied,true);report.source_terms=source.terms;
    assert.equal(source.terms.input_interval_ms,'1500');
    await open('change','applied');const applied=await capture('change-applied');
    const values=await page.locator('.compare-values').innerText();
    check(/Previous\s+2 seconds/.test(values),'applied: old interval is historical');
    check(/Current\s+1.5 seconds/.test(values),'applied: effective interval is current');
    check(!/Current\s+2 seconds|Proposed/.test(values),'applied: no contradicted current/proposed claim');
    check(applied.text.includes('The interval is now 1.5 seconds.'),'applied: source interval shown');
    await page.getByRole('button',{name:'Return to room',exact:true}).click();await state('return');await capture('applied-room');
    await page.getByRole('link',{name:'View change',exact:true}).click();await state('applied');
    await page.reload();await state('applied');check(/Current\s+1.5 seconds/.test(await page.locator('.compare-values').innerText()),'applied: reload retains effective value');
    check(report.errors.length===0,'no browser exceptions');
    fs.writeFileSync(path.join(shots,'repair-report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({failures:report.failures,captures:report.captures.length,exits:report.exits.length,source_terms:report.source_terms}));
    assert.deepEqual(report.failures,[]);
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
