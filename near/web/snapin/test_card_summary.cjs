'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/app.js', 'utf8');
const start = source.indexOf('  var MIN_LIVES = 10, CARD =');
const end = source.indexOf('  // ------------------------------------------------------------------ views', start);
assert(start >= 0 && end > start);
const tail = Array.from({length: 123}, (_, i) => ({persona:'avichad', actual:1, prediction:true, score:100000, base_score:200000}));
const full = {persona:'avichad', scope:'all', lives:316, kos:630, scored:316, score_sum:31600000, base_score_sum:63200000, log_hash:'full-history-hash'};
const asked = [];
const context = {myFighter:()=> 'avichad', V:{mode:'none'}, root:{
  setTimeout:()=> {},
  fetch:async (url)=> {
    asked.push(url);
    if (url === '/room/observe') return {json:async()=> ({fighters:[]})};
    if (url.startsWith('/house/predictions/summary?')) return {ok:true, json:async()=> full};
    return {ok:true, headers:{get:(key)=> key === 'X-Log-Window' ? 'tail' : 'window-hash'}, text:async()=> tail.map(JSON.stringify).join('\n')};
  }
}};
vm.runInNewContext(source.slice(start, end) + ';this.api={loadCard,cardRecord,CARD};', context);
(async()=> {
  await context.api.loadCard();
  const record = context.api.cardRecord();
  assert.equal(record.lives,316);
  assert.equal(record.kos,630);
  assert.equal(record.scored,316);
  assert.equal(record.calibration,0.75);
  assert.equal(context.api.CARD.hash,full.log_hash);
  assert(asked.includes('/house/predictions/summary?persona=avichad'));
  console.info('card totals: full history survives a truncated row window');
})().catch(error=> { console.error(error); process.exitCode=1; });
