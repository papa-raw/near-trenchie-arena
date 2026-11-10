import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { Hud } from './arena/hud.mjs';
class Node {
  constructor() { this.children = []; this.style = {}; this.dataset = {}; this.className = ''; this.innerHTML = ''; this.attributes = {}; this.parentNode = null; }
  appendChild(node) { node.remove(); this.children.push(node); node.parentNode = this; return node; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((n) => n !== this); this.parentNode = null; }
  setAttribute(key, value) { this.attributes[key] = value; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    const nodes = this.children.flatMap((n) => [n, ...n.querySelectorAll('*')]);
    if (selector === '*') return nodes;
    if (selector.includes('.ha-layer')) return nodes.filter((n) => n.className.split(' ').includes('ha-layer'));
    if (selector === '[data-panel]') return nodes.filter((n) => n.dataset.panel);
    const name = /data-panel="([^"]+)"/.exec(selector)?.[1]; return nodes.filter((n) => n.dataset.panel === name);
  }
}
globalThis.document.createElement = () => new Node();
const host = new Node(), paints = [];
window.HUDART = { async mount(root, opts) {
  const old = root.querySelector(':scope > .ha-layer'); old?.remove();
  const layer = new Node(); layer.className = 'ha-layer';
  for (const id of ['board','feed','banner','btn0','btn1']) {
    const node = new Node(); node.dataset.panel = id;
    node.innerHTML = id === 'board' ? JSON.stringify(opts.fighters.map((f) => [f.tag, f.kos])) : id === 'feed' ? JSON.stringify(opts.feed) : id;
    layer.appendChild(node);
  }
  root.appendChild(layer); return { rects: ['board','feed','banner','btn0','btn1'].map((id) => ({ id, x: 0, y: 0, w: 100, h: 40 })) };
} };
const hud = Object.create(Hud.prototype);
Object.assign(hud, { w: 1440, h: 900, KITS: { roster: [{ trenchieId: 'sprout', tag: 'SPRT' }] }, layerHost: host, allIds: ['sprout'],
  feed: [], cards: [], stageKos: () => 0, buildCards: async () => {}, applyBanner() {}, soundState: 'muted' });
// New cache uses an injected painter so this case measures DOM redraw ownership, not browser raster timing.
try { const { HudPanelCache } = await import('./arena/hud-cache.mjs'); hud.artCache = new HudPanelCache(window.HUDART, { paint: async (node) => { paints.push(node.dataset.panel); return node; } }); }
catch (error) { if (error.code !== 'ERR_MODULE_NOT_FOUND') throw error; }
const list = [{ id: 'sprout', x: 100, y: 200, hp: 1, kos: 0 }];
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
hud.remount(list, null, 1000); await settle(); await settle();
const original = host.querySelector('[data-panel="board"]');
hud.remount(list, null, 2000); await settle(); await settle();
assert.equal(host.querySelector('[data-panel="board"]'), original, 'unchanged content must preserve its drawn panel');
list[0].kos = 1; hud.remount(list, null, 3000); await settle(); await settle();
assert.notEqual(host.querySelector('[data-panel="board"]'), original, 'a visible count change updates its panel');
assert.deepEqual(paints, ['board','feed','banner','btn0','btn1','board'], 'each panel draws once initially, then only the changed board');
process.stdout.write(JSON.stringify({ ok: true, initialPaints: 5, unchangedPaints: 0, changePaints: 1 }) + '\n');

// Exercise the real frozen art builder too. A Node font/canvas sink measures JS generation, never browser filters.
document.head = new Node(); document.body = new Node(); document.fonts = { load: async () => [], ready: Promise.resolve() };
document.createElement = (tag) => { const node = new Node(); if (tag === 'canvas') node.getContext = () => ({ measureText: (s) => ({ width: String(s).length * 8 }) }); return node; };
vm.runInNewContext(await readFile(new URL('./hud-art/hud-art.js', import.meta.url), 'utf8'), { window, document, console });
const { HudPanelCache, Backgrounds } = await import('./arena/hud-cache.mjs');
const boardSources = [], drawn = [], real = new HudPanelCache(window.HUDART, { paint: async (node) => { drawn.push(node.dataset.panel); if (node.dataset.panel === 'board') boardSources.push(node.innerHTML); return node; } }), root = new Node();
const options = { concept: 'candle', draft: 'a', w: 1440, h: 900, fighters: [{ tag: 'SPRT', name: 'Sprout', kos: 1, hp: 1, x: 200, y: 300 }], feed: [] };
const only = { only: ['board','feed','banner','btn0','btn1'] };
await real.mount(root, options, only); const initial = drawn.length;
for (let i = 0; i < 20; i++) await real.mount(root, options, only);
assert.equal(drawn.length, initial, 'real unchanged art is retained');
options.fighters[0].kos = 2; await real.mount(root, options, only); assert.equal(drawn.length, initial + 1); assert.equal(drawn.at(-1), 'board');
const withoutText = (svg) => svg.replace(/<text\b[^>]*>[\s\S]*?<\/text>/g, '');
assert.equal(withoutText(boardSources[0]), withoutText(boardSources[1]), 'a count change reuses the same filtered background');
let rasters = 0; const backgrounds = new Backgrounds(2), draw = async () => { rasters++; return {}; };
const one = backgrounds.get('same', draw), two = backgrounds.get('same', draw); assert.equal(one, two); await one; assert.equal(rasters, 1);
await backgrounds.get('next', draw); await backgrounds.get('third', draw); assert.equal(backgrounds.map.size, 2);
process.stdout.write(JSON.stringify({ ok: true, actualArt: true, unchangedFrames: 20, changedPanels: 1, jsBuildMsMax: +Math.max(...real.stats.buildMs).toFixed(2), browserFilterTiming: 'not measured' }) + '\n');
