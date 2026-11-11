// New review-fix case: one missing-route probe, hosted fallback and bounded retries.
import assert from 'node:assert/strict';
import { ChainHold } from './arena/chain-hold.mjs';
class Element {
  constructor() { this.hidden = true; this.textContent = ''; this.style = {}; this.attributes = {}; }
  setAttribute(name, value) { this.attributes[name] = value; }
}
async function cadenceCase() {
  const saved = { setTimeout, clearTimeout, setInterval, clearInterval, fetch: globalThis.fetch };
  let clock = 0, serial = 0;
  const tasks = new Map(), calls = [];
  const schedule = (fn, delay, repeat = false) => { const id = ++serial; tasks.set(id, {fn, at:clock+delay, delay, repeat}); return id; };
  globalThis.setTimeout = (fn, delay) => schedule(fn, delay);
  globalThis.setInterval = (fn, delay) => schedule(fn, delay, true);
  globalThis.clearTimeout = globalThis.clearInterval = (id) => tasks.delete(id);
  globalThis.fetch = async (url) => { calls.push({url, at:clock}); return {ok:true,json:async()=>({chain:{lives_held_for_owner_read:3,owner_reads_waiting:2,oldest_hold_s:42.7}})}; };
  const flush = async () => { for (let i=0;i<20;i++) await Promise.resolve(); };
  const advance = async (milliseconds) => {
    clock += milliseconds;
    await flush();
    const due = [...tasks].filter(([,task])=>task.at<=clock);
    for (const [id,task] of due) {
      tasks.delete(id); await task.fn();
      if (task.repeat && !tasks.has(id)) tasks.set(id,{...task,at:clock+task.delay});
    }
    await flush();
  };
  const element = new Element(), notice = new ChainHold(element,{now:()=>clock,random:()=>0.5});
  notice.layout = () => {};
  try {
    notice.startHealth('/health'); await flush();
    assert.equal(calls.length,1);
    const copy = element.textContent;
    await advance(1000); notice.stopHealth(); notice.startHealth('/health'); await flush();
    assert.equal(calls.length,1,'page restore preserves the request spacing');
    await advance(28999); assert.equal(calls.length,1,'at most one hosted health request per 30 s');
    await advance(2500); assert.equal(calls.length,1,'this page adds 2.5 s jitter');
    await advance(1); assert.equal(calls.length,2);
    assert.equal(calls[1].at-calls[0].at,32500);
    assert.equal(element.textContent,copy,'cadence does not change the banner');
    await advance(32500); assert.equal(calls.length,3);
    notice.stopHealth(); await flush();
    const stopped = calls.length; await advance(70000); assert.equal(calls.length,stopped);
    const early = new ChainHold(new Element(),{random:()=>0}), late = new ChainHold(new Element(),{random:()=>1});
    assert.equal(early.pollDelay,30000); assert.equal(late.pollDelay,35000,'jitter spreads pages over up to five seconds');
  } finally {
    notice.stopHealth(); Object.assign(globalThis,saved);
  }
}
await cadenceCase();
if (process.argv.includes('--cadence-only')) {
  process.stdout.write(JSON.stringify({ok:true,minPollMs:30000,pageJitterMs:2500,maxJitterMs:5000,stopsOnPageHide:true})+'\n');
  process.exit(0);
}
let now = 0;
const element = new Element(), notice = new ChainHold(element, { now: () => now });
notice.layout = () => {};
const calls = [], failedResources = [];
let count = 3;
const fetcher = async (url) => {
  calls.push(url);
  if (url === '/dev/health') { failedResources.push(url); return { ok: false, status: 404 }; }
  assert.equal(url, '/health', 'hosted health stays on the same origin');
  return { ok: true, json: async () => ({ chain: { lives_held_for_owner_read: count, owner_reads_waiting: 2, oldest_hold_s: 42.7 } }) };
};
await notice.refresh('/dev/health', fetcher);
assert.deepEqual(calls, ['/dev/health', '/health'], 'missing DEV route falls back to the hosted route');
assert.equal(element.textContent, 'Fighters waiting to respawn while owners are checked: 3 (longest 42 s)');
assert.equal(element.title, 'Ownership checks pending: 2');
for (let i = 0; i < 30; i++) { now += 2000; await notice.refresh('/dev/health', fetcher); }
assert.equal(calls.filter((url) => url === '/dev/health').length, 1, 'the missing route is never polled again');
assert.equal(failedResources.length, 1, 'only the first probe produces a browser 404 line');
count = 0; now += 2000; await notice.refresh('/dev/health', fetcher);
assert.equal(element.hidden, true); assert.equal(element.textContent, '');

const missing = new ChainHold(new Element(), { now: () => now }); missing.layout = () => {};
const missingCalls = [];
const absent = async (url) => { missingCalls.push(url); return { ok: false, status: 404 }; };
await missing.refresh('/dev/health', absent);
for (let i = 0; i < 100; i++) { now += 2000; await missing.refresh('/dev/health', absent); }
assert.deepEqual(missingCalls, ['/dev/health', '/health'], 'no health routes stops requests for the rest of the page session');

const offline = new ChainHold(new Element(), { now: () => now }); offline.layout = () => {};
let attempts = 0;
const unavailable = async () => { attempts++; return { ok: false, status: 503 }; };
await offline.refresh('/health', unavailable);
now += 59999; await offline.refresh('/health', unavailable); assert.equal(attempts, 1);
now += 1; await offline.refresh('/health', unavailable); assert.equal(attempts, 2, 'failed health retries at most once a minute');
process.stdout.write(JSON.stringify({ok:true,missingRoute404s:failedResources.length,hostedFallback:true,backoffMs:60000,hiddenAtZero:true})+'\n');
