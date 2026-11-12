// Keep the approved frozen SVG art. Cache its filtered backgrounds and update only a changed panel's text layer.
const SAMPLE_LIMIT = 240; // A bounded history of recent panel work for the browser timing review.
const sample = (values, value) => { values.push(value); if (values.length > SAMPLE_LIMIT) values.shift(); };
const PAD = 64; // ropes, torn edges and cast shadows deliberately extend beyond the art's declared viewBox.
function textLayer(svg) {
  const copy = svg.cloneNode(true);
  function prune(node) {
    for (const child of [...node.children]) {
      if (['text', 'defs', 'style'].includes(child.localName)) continue;
      if (child.querySelector('text')) prune(child); else child.remove();
    }
  }
  prune(copy); return copy;
}
function backgroundLayer(svg) { const copy = svg.cloneNode(true); copy.querySelectorAll('text').forEach((text) => text.remove()); return copy; }
/** Bounded texture cache also shares in-flight decodes. Node tests inject a painter; raster timing belongs to Chrome. */
export class Backgrounds {
  constructor(limit = 128) { this.limit = limit; this.map = new Map(); this.rasters = 0; }
  get(key, draw) {
    if (this.map.has(key)) { const value = this.map.get(key); this.map.delete(key); this.map.set(key, value); return value; }
    this.rasters++;
    const value = Promise.resolve().then(draw).catch((error) => { if (this.map.get(key) === value) this.map.delete(key); throw error; });
    this.map.set(key, value);
    while (this.map.size > this.limit) this.map.delete(this.map.keys().next().value);
    return value;
  }
}
function raster(svg, dpr) {
  const width = Number(svg.getAttribute('width')), height = Number(svg.getAttribute('height'));
  const copy = svg.cloneNode(true), defs = document.querySelector('#hud-art-defs defs');
  if (defs) copy.insertBefore(defs.cloneNode(true), copy.firstChild);
  copy.setAttribute('width', width + 2 * PAD); copy.setAttribute('height', height + 2 * PAD);
  copy.setAttribute('viewBox', [-PAD, -PAD, width + 2 * PAD, height + 2 * PAD].join(' '));
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)], { type: 'image/svg+xml' }));
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      try {
        const canvas = document.createElement('canvas'); canvas.width = Math.ceil((width + PAD * 2) * dpr); canvas.height = Math.ceil((height + PAD * 2) * dpr);
        canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height); resolve(canvas);
      } catch (error) { reject(error); }
      finally { URL.revokeObjectURL(url); }
    };
    image.onerror = () => { URL.revokeObjectURL(url); reject(new Error('HUD background decode failed')); };
    image.src = url;
  });
}
export class HudPanelCache {
  constructor(art, { paint = null, dpr = 2 } = {}) {
    this.art = art; this.dpr = dpr; this.backgrounds = new Backgrounds(); this.hosts = new WeakMap(); this.paint = paint || ((node) => this.paintPanel(node));
    this.stats = { panelPaints: 0, reused: 0, builds: 0, buildMs: [], blitMs: [] };
  }
  async paintPanel(node) {
    const svg = node.querySelector('svg'); if (!svg) return node;
    const background = backgroundLayer(svg), overlay = textLayer(svg), key = this.dpr + ':' + background.outerHTML;
    const image = await this.backgrounds.get(key, () => raster(background, this.dpr));
    const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height;
    const started = performance.now(); canvas.getContext('2d').drawImage(image, 0, 0); sample(this.stats.blitMs, performance.now() - started);
    canvas.style.cssText = `position:absolute;left:-${PAD}px;top:-${PAD}px;width:${image.width / this.dpr}px;height:${image.height / this.dpr}px;pointer-events:none`;
    canvas.style.zIndex = '0'; overlay.style.position = 'relative'; overlay.style.zIndex = '1';
    node.style.isolation = 'isolate'; // Each panel keeps its text above its own positioned background.
    node.replaceChildren(canvas, overlay); return node;
  }
  panel(host, id) { return this.hosts.get(host)?.entries.get(id)?.node || null; }
  async prepare(node) { const painted = await this.paint(node); this.stats.panelPaints++; return painted; }
  async mount(host, options, { only = null } = {}) {
    const scratch = document.createElement('div'), started = performance.now();
    const measured = await this.art.mount(scratch, options); sample(this.stats.buildMs, performance.now() - started); this.stats.builds++;
    const freshLayer = scratch.querySelector(':scope > .ha-layer');
    if (!freshLayer) throw new Error('HUD art returned no panel layer');
    let state = this.hosts.get(host);
    if (!state) { state = { layer: freshLayer, entries: new Map() }; this.hosts.set(host, state); }
    const nodes = [...freshLayer.querySelectorAll('[data-panel]')], seen = new Set();
    for (const incoming of nodes) {
      const id = incoming.dataset.panel;
      if (only && !only.includes(id)) { incoming.remove(); continue; }
      seen.add(id); const key = incoming.innerHTML, old = state.entries.get(id);
      if (old && old.key === key) {
        old.node.style.transform = incoming.style.transform; incoming.remove(); this.stats.reused++;
      } else {
        const painted = await this.prepare(incoming);
        old?.node.remove(); state.layer.appendChild(painted); state.entries.set(id, { key, node: painted });
      }
    }
    for (const [id, entry] of state.entries) if (!seen.has(id)) { entry.node.remove(); state.entries.delete(id); }
    if (state.layer.parentNode !== host) host.appendChild(state.layer);
    state.layer.style.width = options.w + 'px'; state.layer.style.height = options.h + 'px';
    host.dataset.hudReady = '1'; return measured;
  }
}
