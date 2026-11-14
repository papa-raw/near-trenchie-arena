// Browser timers reject a plain-object receiver; Node's native timers do not.
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const sandbox = vm.createContext({ module: { exports: {} }, AbortController });
vm.runInContext(`
  globalThis.timerCalls = [];
  globalThis.setTimeout = function (fn, ms) {
    'use strict';
    if (this !== undefined && this !== globalThis) throw new TypeError('Illegal invocation');
    timerCalls.push(['set', ms]); return 1;
  };
  globalThis.clearTimeout = function (id) {
    'use strict';
    if (this !== undefined && this !== globalThis) throw new TypeError('Illegal invocation');
    timerCalls.push(['clear', id]);
  };
`, sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../brain.js'), 'utf8'), sandbox);
(async () => {
  for (const provider of ['nearai', 'openrouter', 'codex', 'claude']) {
    const body = provider === 'claude' ? {content:[{type:'text',text:'{"level":2}'}],usage:{input_tokens:10,output_tokens:10}} :
      {choices:[{message:{content:'{"level":2}'}}],usage:{prompt_tokens:10,completion_tokens:10}};
    const result = await sandbox.module.exports.chat(provider, 'fixture-key', 'system', 'user', {
      fetch: async () => ({status:200,text:async () => JSON.stringify(body)}), maxTokens:80
    });
    assert.equal(result.ok,true); assert.equal(result.text,'{"level":2}');
  }
  assert.equal(sandbox.timerCalls.length,8,'every provider sets and clears its default request timer');
  assert.ok(sandbox.timerCalls.filter(x=>x[0]==='set').every(x=>x[1]===60000));
  console.log('PASS browser timer receivers: all four default provider paths');
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
