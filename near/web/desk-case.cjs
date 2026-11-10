const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const [preview, ready, corrupt, shots] = process.argv.slice(2);
(async () => {
  const proxyServer = process.env.HTTPS_PROXY || process.env.HTTP_PROXY;
  const browser = await chromium.launch({args:['--single-process','--no-zygote'],
    ...(proxyServer ? {proxy:{server:proxyServer}} : {})});
  const context = await browser.newContext({viewport:{width:640,height:800}, permissions:['clipboard-read','clipboard-write']});
  const page = await context.newPage();
  const errors = [], states = [], geometry = [];
  page.on('pageerror', error => errors.push(String(error)));
  async function capture(name) {
    await page.evaluate(async () => {
      await document.fonts.ready;
      await Promise.all([...document.images].map(image => image.decode()));
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    const measures = await page.evaluate(() => ({width:innerWidth, scrollWidth:document.documentElement.scrollWidth,
      footer:document.querySelector('footer').getBoundingClientRect().height,
      targets:[...document.querySelectorAll('a, button, summary')].filter(node=>node.getClientRects().length)
        .map(node=>({text:node.innerText,height:node.getBoundingClientRect().height}))}));
    assert.ok(measures.scrollWidth <= measures.width, name + ' overflow');
    assert.ok(measures.footer >= 80, name + ' footer');
    for (const target of measures.targets) assert.ok(target.height >= 44, `${name}: ${target.text}`);
    await page.screenshot({path:path.join(shots,name+'.png'),fullPage:true});
    states.push(name);geometry.push({name,...measures});
  }
  async function open(origin) {
    await page.goto(origin);
    await page.waitForFunction(()=>document.documentElement.dataset.ready==='true');
  }
  async function route(name) {
    await page.locator(`.row a[data-view="${name}"]`).click();
    assert.equal(await page.locator('#detail').getAttribute('data-route'),name);
    assert.equal(await page.locator('[aria-current="step"]').count(),1);
  }
  try {
    await open(preview);await capture('a-native-preview');
    assert.equal(await page.locator('.rows .row').count(),4);
    await page.getByRole('link',{name:'Open preview',exact:false}).click();
    assert.match(await page.locator('#detail').innerText(),/still.*Live play is pending/s);
    await capture('a-arena');
    await route('agent');
    assert.match(await page.locator('#detail').innerText(),/hosted join command is not ready/i);
    const guide=await page.request.get(preview+'/SNAP.md');
    assert.equal(guide.status(),200);assert.match(await guide.text(),/BEGIN COLD AGENT/);
    await page.getByText('Rehearse the client',{exact:false}).click();
    await page.getByRole('button',{name:'Copy rehearsal command',exact:true}).click();
    await page.getByText('Rehearsal command copied.',{exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'make -C near demo');
    await capture('a-agent');
    await route('forecast');assert.match(await page.locator('#detail').innerText(),/No local run yet/);
    await capture('a-forecast-pending');
    await route('replay');assert.match(await page.locator('#detail').innerText(),/No local run yet/);
    await capture('a-replay-pending');
    await page.locator('[data-close]').click();assert.equal(new URL(page.url()).hash,'');
    await page.getByRole('link',{name:/Outside-agent recording/}).click();
    assert.match(await page.locator('#detail').innerText(),/recording is not available/);
    await capture('a-recording');
    for (const width of [390,768,1440]) {
      await page.setViewportSize({width,height:width===390?844:900});
      await open(preview);await capture('a-preview-'+width);
    }
    await page.setViewportSize({width:640,height:800});
    await open(ready);await route('forecast');
    assert.match(await page.locator('#detail').innerText(),/Synthetic local run/);
    assert.match(await page.locator('#detail').innerText(),/alice:life:0/);
    assert.match(await page.locator('#detail').innerText(),/25%/);
    await capture('a-forecast-locked');
    await route('replay');
    assert.match(await page.locator('#detail').innerText(),/Replay checked locally/);
    assert.match(await page.locator('#detail').innerText(),/Chain check pending/);
    await page.getByText('What must match',{exact:false}).click();
    const hashes=await page.locator('[data-hash]').allTextContents();
    assert.equal(hashes.length,2);assert.equal(hashes[0],hashes[1]);
    await capture('a-replay-checked');
    await page.locator('[data-close]').click();await route('replay');
    assert.match(await page.locator('#detail').innerText(),/Replay checked locally/);
    await page.reload();await page.waitForFunction(()=>document.documentElement.dataset.ready==='true');
    assert.match(await page.locator('#detail').innerText(),/Replay checked locally/);
    const privatePath=await page.request.get(ready+'/../room/requirements.txt');assert.equal(privatePath.status(),404);
    const foreign=await page.request.get(ready+'/api/evidence',{headers:{Origin:'https://foreign.example'}});
    assert.equal(foreign.status(),403);
    const write=await page.request.post(ready+'/api/evidence',{data:{}});assert.equal(write.status(),405);
    await open(corrupt);await route('replay');
    assert.match(await page.locator('#detail').innerText(),/Replay unavailable/);
    assert.doesNotMatch(await page.locator('#detail').innerText(),/Replay checked locally/);
    await capture('a-replay-unavailable');
    await page.route('**/api/evidence',route=>route.abort());
    await open(ready);await route('forecast');
    assert.match(await page.locator('#detail').innerText(),/Evidence unavailable/);
    await capture('a-evidence-offline');
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(shots,'case-report.json'),JSON.stringify({four_actions:true,states,geometry,errors},null,2));
    process.stdout.write(JSON.stringify({four_actions:true,captures:states.length,errors})+'\n');
  } finally {await browser.close();}
})().catch(error=>{process.stderr.write(String(error.stack)+'\n');process.exitCode=1;});
