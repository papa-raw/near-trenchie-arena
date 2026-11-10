// The single new browser case; fixture controls operate the real copied service.
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const captureReady = require('./capture-ready.cjs');
const [origin, shots] = process.argv.slice(2);
(async () => {
  const proxyServer=process.env.HTTPS_PROXY || process.env.HTTP_PROXY;
  const browser = await chromium.launch({args:['--single-process','--no-zygote'],...(proxyServer ? {proxy:{server:proxyServer}} : {})});
  const page = await browser.newPage({viewport:{width:600,height:720}});
  page.setDefaultTimeout(15000);page.setDefaultNavigationTimeout(15000);
  const states = [], geometry = [], errors = [];
  let visits=0;
  page.on('pageerror',error=>errors.push(String(error)));
  async function fixture(action, fields={}) {
    const response=await page.request.post(origin+'/__fixture',{headers:{'X-Fixture':'synthetic'},data:{action,...fields}});
    assert.equal(response.status(),200,await response.text());
    return response.json();
  }
  async function state(expected) {
    try {await page.waitForFunction(value=>document.querySelector('#app')?.dataset.state === value,expected);}
    catch(error){
      const actual=await page.evaluate(()=>({state:document.querySelector('#app')?.dataset.state,text:document.body.innerText}));
      fs.writeFileSync(path.join(shots,'failure-state.json'),JSON.stringify({expected,...actual,errors},null,2));
      throw new Error(`${error.message}; wanted ${expected}, got ${actual.state}; ${actual.text.slice(0,800)}; page errors: ${errors.join('; ')}`);
    }
  }
  async function open(screen='terms') {
    await page.goto(origin+'/?visit='+(++visits)+'#'+screen);
    await page.waitForFunction(()=>document.documentElement.dataset.ready === 'true');
    await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(image=>image.decode()));});
  }
  async function snapshot(screen, expected, label=expected) {
    await state(expected);
    await captureReady(page);
    const name=`b-${screen}-${label}`;
    const metrics=await page.evaluate(()=>({width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,documentHeight:document.documentElement.scrollHeight,footerBottom:document.querySelector('footer').getBoundingClientRect().bottom,footerHeight:document.querySelector('footer').getBoundingClientRect().height,buttons:[...document.querySelectorAll('.button')].map(node=>({text:node.innerText,height:node.getBoundingClientRect().height,disabled:node.disabled||node.getAttribute('aria-disabled')==='true'}))}));
    assert.ok(metrics.documentWidth <= metrics.width,`${name}: horizontal overflow`);
    assert.ok(metrics.footerHeight >= 80,`${name}: action area`);
    for(const control of metrics.buttons){assert.ok(control.height >= 44,`${name}: ${control.text} target`);assert.equal(control.disabled,false,`${name}: no inert consent control`);}
    await page.screenshot({path:path.join(shots,name+'.png'),fullPage:false});
    states.push(name);geometry.push({name,...metrics});
  }
  async function refresh() {await page.evaluate(()=>window.dispatchEvent(new Event('focus')));}
  async function revisit(expected, heading) {
    await page.getByRole('button',{name:'Return to room',exact:true}).click();
    await state('return');
    await page.getByRole('link',{name:'Room terms',exact:true}).click();
    await state('accepted');
    await page.getByRole('link',{name:/View answer/}).click();
    await state(expected);
    await page.reload();await state(expected);
    assert.equal(await page.locator('h1').innerText(),heading);
    assert.equal(await page.getByRole('button',{name:'Accept change',exact:true}).count(),0);
    assert.equal(await page.getByRole('button',{name:'Decline',exact:true}).count(),0);
  }
  try {
    await open();await snapshot('terms','review');
    await page.getByRole('button',{name:'Review room rules',exact:true}).click();
    await snapshot('terms','policy');
    await page.getByText('All room rules',{exact:true}).click();
    assert.match(await page.locator('.content').innerText(),/ownership or custody/);
    await page.getByText('All room rules',{exact:true}).click();
    await fixture('hold');
    await page.getByRole('button',{name:'Accept terms',exact:true}).click();
    await snapshot('terms','sending');
    assert.equal(await page.getByRole('heading',{name:'Terms accepted',exact:true}).count(),0);
    await fixture('release');
    await snapshot('terms','accepted');
    await page.reload();await state('accepted');
    const reloadKeepsAnswer=await page.getByRole('heading',{name:'Terms accepted',exact:true}).count()===1;
    await page.getByRole('button',{name:'Return to room',exact:true}).click();
    await snapshot('room','return');
    await fixture('reset',{version:'8'});await open();await snapshot('terms','changed');
    await fixture('unavailable');await open();await snapshot('terms','unavailable');
    assert.equal(await page.getByRole('button',{name:'Accept terms',exact:true}).count(),0);
    await fixture('available');await page.getByRole('button',{name:'Refresh',exact:true}).click();await state('changed');
    await fixture('disconnect');await open();await snapshot('terms','wallet');
    await page.getByRole('button',{name:'Connect wallet',exact:true}).click();await state('changed');

    await fixture('reset',{proposal:true});await open('change');await snapshot('change','review');
    await page.getByRole('button',{name:'Review change',exact:true}).click();await snapshot('change','confirm');
    await page.getByText('2 of 4 members accepted',{exact:true}).click();
    assert.match(await page.locator('.members').innerText(),/Clover · You\s+No answer/);
    await page.getByText('2 of 4 members accepted',{exact:true}).click();
    await fixture('hold');await page.getByRole('button',{name:'Accept change',exact:true}).click();
    await snapshot('change','sending');await fixture('release');await snapshot('change','answered');
    await revisit('answered','You accepted');
    await fixture('accept_last');await refresh();await snapshot('change','scheduled');
    const facts=await fixture('facts');assert.equal(facts.current_interval,'2000');
    await revisit('scheduled','Change agreed');

    await fixture('reset',{proposal:true});await open('change');
    await page.getByRole('button',{name:'Review change',exact:true}).click();
    await page.getByRole('button',{name:'Decline',exact:true}).click();await snapshot('change','declined');
    await revisit('declined','You declined');
    await fixture('reset',{proposal:true});await fixture('expire');await open('change');await snapshot('change','expired');
    await revisit('expired','The change expired');
    await fixture('reset',{accepted:true});await open('change');await snapshot('change','empty');
    await fixture('unavailable');await open('change');await snapshot('change','unavailable');
    assert.equal(await page.locator('.compare').count(),0);

    // The room records the write, but transport loses its response. Check never resends it.
    await fixture('reset');await open();
    await page.getByRole('button',{name:'Review room rules',exact:true}).click();
    await fixture('drop');
    const lostResponse=page.waitForResponse(response=>response.url()===origin+'/api/member' && response.request().method()==='POST');
    await page.getByRole('button',{name:'Accept terms',exact:true}).click();await state('sending');await lostResponse;
    await page.getByRole('button',{name:'Check answer',exact:true}).click();await state('accepted');
    const lost=await fixture('facts');assert.equal(lost.write_count,1);

    for(const screen of ['terms','change']){
      await fixture('reset',{proposal:screen==='change'});
      for(const [label,width,height] of [['desktop',1200,800],['tablet',768,900],['phone',390,844],['board',1440,1040]]){
        await page.setViewportSize({width,height});await open(screen);await snapshot(screen,'review','review-'+label);
      }
    }
    assert.deepEqual(errors,[]);
    const separateCases={terms_empty:'near/members/test_member_unpublished.py:MemberUnpublished.test_signed_unpublished_state_stays_distinct_from_failure_and_publish_requires_review'};
    const report={real_room:true,states,geometry,reload_keeps_answer:reloadKeepsAnswer,uncertain_write_count:lost.write_count,all_requests_self_bound:lost.self_bound,unsupported:[],separate_cases:separateCases};
    fs.writeFileSync(path.join(shots,'case-report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({states:states.length,reload_keeps_answer:reloadKeepsAnswer,uncertain_write_count:lost.write_count,all_requests_self_bound:lost.self_bound,unsupported:report.unsupported,separate_cases:report.separate_cases}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
