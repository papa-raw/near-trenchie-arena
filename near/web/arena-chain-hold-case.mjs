// New fixture case for the chain writer's public owner-read hold status.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
let module;
try { module = await import('./arena/chain-hold.mjs'); }
catch (error) { if (error.code !== 'ERR_MODULE_NOT_FOUND') throw error; module = {}; }
assert.equal(typeof module.ChainHold, 'function', 'the arena has a chain hold notice');
const { ChainHold, placeChainHold } = module;
class Element {
  constructor() { this.hidden = true; this.textContent = ''; this.style = {}; this.attributes = {}; this.offsetWidth = 344; this.offsetHeight = 28; }
  setAttribute(name,value) { this.attributes[name] = value; }
  getBoundingClientRect() { return {width:this.offsetWidth,height:this.offsetHeight}; }
}
const element = new Element();
const notice = new ChainHold(element);
notice.update({ chain: { lives_held_for_owner_read: 0, owner_reads_waiting: 0, oldest_hold_s: null } });
assert.equal(element.hidden, true, 'zero holds shows nothing');
notice.update({ chain: { lives_held_for_owner_read: 3, owner_reads_waiting: 2, oldest_hold_s: 42.7 } });
assert.equal(element.hidden, false);
assert.match(element.textContent, /Fighters waiting to respawn while owners are checked: 3/);
assert.match(element.textContent, /longest 42 s/);
assert.match(element.attributes['aria-label'], /3/);
notice.update({ chain: { lives_held_for_owner_read: 0, owner_reads_waiting: 2, oldest_hold_s: null } });
assert.equal(element.hidden, true, 'pending reads alone are not held lives');
notice.update({}); assert.equal(element.hidden, true, 'no writer shows no hold');
notice.update({ chain: { lives_held_for_owner_read: 1, owner_reads_waiting: 1, oldest_hold_s: null } });
assert.match(element.textContent, /longest unknown/, 'missing age is never invented');
const realLayout = notice.layout;
let layoutCalls = 0; notice.layout = () => layoutCalls++;
await notice.refresh('/dev/health', async (url) => {
  assert.equal(url, '/dev/health');
  return {ok:true,json:async () => ({chain:{lives_held_for_owner_read:3,owner_reads_waiting:2,oldest_hold_s:42.7}})};
});
assert.match(element.textContent, /checked: 3/); assert.equal(layoutCalls,1);
await notice.refresh('/dev/health', async () => { throw new Error('unavailable'); });
assert.match(element.textContent, /last check unavailable/, 'an old hold is labelled if health is lost');
assert.equal(notice.lastError,'unavailable');
notice.layout = realLayout;
const intersects = (a,b) => a.x < b.x+b.w && a.x+a.w > b.x && a.y < b.y+b.h && a.y+a.h > b.y;
for (const width of [1440,390]) {
  const height = width === 390 ? 844 : 900;
  const cards = width === 390 ? [{x:8,y:8,w:115,h:112},{x:8,y:135,w:115,h:100}] : [{x:16,y:16,w:240,h:230}];
  const obstacles = [...cards, {x:8,y:height-120,w:300,h:110}, {x:width-70,y:height-70,w:60,h:60},
    {x:width-290,y:height-300,w:280,h:190}, {x:(width-300)/2,y:height-200,w:300,h:75},
    {x:width-160,y:8,w:150,h:60}];
  const box = placeChainHold({w:344,h:28},obstacles,width,height);
  assert.ok(box, 'a status line fits at '+width);
  assert.ok(obstacles.every((r) => !intersects(box,r)), 'line clears cards, feed, buttons, follow inset, CTA and diagnostics at '+width);
  assert.ok(box.x>=8 && box.y>=8 && box.x+box.w<=width-8 && box.y+box.h<=height-8);
  notice.layout(width,height,obstacles);
  const placed = /translate\(([-.\d]+)px,([-.\d]+)px\)/.exec(element.style.transform);
  assert.ok(placed, 'the notice applies its placement');
  const actual = {x:+placed[1],y:+placed[2],w:344,h:28};
  assert.ok(obstacles.every((r) => !intersects(actual,r)), 'the DOM transform also clears the HUD at '+width);
}
notice.layout(390,844,[{x:0,y:0,w:390,h:844}]);
assert.equal(element.style.visibility,'hidden', 'a full viewport never forces an overlap');
notice.layout(390,844,[]); assert.equal(element.style.visibility,'', 'the notice returns when a clear slot opens');
const source = await readFile(new URL('./arena/main.mjs',import.meta.url),'utf8');
assert.match(source,/ChainHold/); assert.match(source,/startHealth/); assert.match(source,/chainHold\.layout/);
process.stdout.write(JSON.stringify({ok:true,hiddenAtZero:true,count:3,oldestSeconds:42,widths:[1440,390],overlap:0})+'\n');
