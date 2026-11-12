// The corner buttons and "How it works" (approved board 2, direction C; Pat's item 6: "this red menu does nothing", "the
// sound icon has no on/off states"). Both buttons always carry words, at both widths. Sound: waves + "Sound" when on; a
// slash + "Muted", greyed and pressed, when off; aria-pressed follows. "How it works" opens a dialog of eight sections;
// x, a click outside or Escape closes it, and focus returns to the button. The text is the one source, /web/docs.html
// (the game's docs page): the dialog renders its <main> sections, sanitised (docsSections); nothing of it lives here.
// On a phone with board 1's panel open the two buttons turn compact (40 px round, the icon alone; the words stay their
// labels and titles) so they fit the strip between the plank and the sheet.

export const COPY = {
  sound: { on: 'Sound', off: 'Muted', onAria: 'Sound is on. Turn it off.', offAria: 'Sound is off. Turn it on.' },
  menu: 'How it works', close: 'Close', loading: 'Loading…', failed: 'How it works could not load here. Read it at',
};

const ICON = {
  on: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M4 9h4l5-4v14l-5-4H4z" fill="currentColor"/><path d="M16 8.5a5 5 0 010 7M18.5 6a8.5 8.5 0 010 12" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/></svg>',
  off: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M4 9h4l5-4v14l-5-4H4z" fill="currentColor"/><path d="M16 9l6 6M22 9l-6 6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
  menu: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M5 7h14M5 12h14M5 17h14" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
};

/** The sound button's face for a Sound state ('on', 'muted' or 'waiting for a click'): before the first click the
 *  sound is about to play, so it reads "Sound" (on), not pressed. */
export function soundFace(state) {
  const off = state === 'muted', s = COPY.sound;
  return { off, label: off ? s.off : s.on, aria: off ? s.offAria : s.onAria, pressed: String(off), icon: off ? ICON.off : ICON.on };
}

export const DOCS_URL = './docs.html';
const KEEP = new Set(['h2', 'h3', 'p', 'ul', 'ol', 'li', 'a', 'strong', 'em', 'code']);
const DROP = new Set(['script', 'style', 'template', 'iframe', 'object', 'svg', 'math']);
const HEAD = { h2: 'h3', h3: 'h4' };   // one level under the dialog's own title (h2)
const safeHref = (v) => (/^(\/(?!\/)|https:\/\/|#)/.test(v) ? v : null);
/** The docs page's <main> sections, sanitised for the dialog: [{id, html}]. Only the text tags above survive, every
 *  attribute is dropped except a link's href (same-origin path, https or an in-page #; links open in a new tab), any
 *  other tag is unwrapped to its text, and script/style-like tags go with their content. Headings move one level
 *  down. Pure (strings in, strings out), so the case runs it on the real file. */
export function docsSections(html) {
  const main = /<main\b[^>]*>([\s\S]*?)<\/main>/i.exec(String(html));
  if (!main) return [];
  let body = main[1].replace(/<!--[\s\S]*?-->/g, '');
  for (const t of DROP) body = body.replace(new RegExp('<' + t + '\\b[\\s\\S]*?</' + t + '\\s*>', 'gi'), '');
  const out = [], re = /<section\b([^>]*)>([\s\S]*?)<\/section\s*>/gi;
  for (let m; (m = re.exec(body));) {
    const id = (/\bid\s*=\s*"([a-z0-9-]+)"/i.exec(m[1]) || [])[1] || null;
    // one pass over complete tags only (no '<' or '>' inside one): an allowlisted tag is rebuilt with no attributes but a
    // safe href; every other piece is text, with each '<' and '>' escaped, so a tag left open (no closing '>') can only
    // ever show as text and never becomes an element
    const tag = (all) => {
      const m2 = /^<(\/?)([a-z0-9]+)([^<>]*)>$/i.exec(all), close = m2[1], t = m2[2].toLowerCase(), attrs = m2[3];
      if (!KEEP.has(t)) return '';
      const name = HEAD[t] || t;
      if (close) return '</' + name + '>';
      if (t === 'a') { const href = safeHref(((/\bhref\s*=\s*"([^"]*)"/i.exec(attrs)) || [])[1] || ''); return href ? '<a href="' + href.replace(/"/g, '&quot;') + '"' + (href.startsWith('#') ? '' : ' target="_blank" rel="noopener"') + '>' : '<a>'; }
      return '<' + name + '>';
    };
    const clean = m[2].split(/(<\/?[a-z0-9]+[^<>]*>)/i).map((part, i) => (i % 2 ? tag(part) : part.replace(/</g, '&lt;').replace(/>/g, '&gt;'))).join('');
    out.push({ id, html: clean.trim() });
  }
  return out;
}

export class Corner {
  constructor(doc, root, { onSound }) {
    this.doc = doc; this.state = null;
    const box = this.box = doc.createElement('div'); box.className = 'corner';
    this.sound = doc.createElement('button'); this.sound.type = 'button'; this.sound.className = 'rb'; this.sound.dataset.panel = 'btn0';
    this.sound.addEventListener('click', () => onSound && onSound());
    this.menu = doc.createElement('button'); this.menu.type = 'button'; this.menu.className = 'rb menu'; this.menu.dataset.panel = 'btn1';
    this.menu.setAttribute('aria-haspopup', 'dialog'); this.menu.setAttribute('aria-label', COPY.menu); this.menu.title = COPY.menu; this.menu.innerHTML = ICON.menu + '<span>' + COPY.menu + '</span>';
    this.compact = false;
    this.menu.addEventListener('click', () => this.open());
    box.append(this.sound, this.menu); root.appendChild(box);
    this.dialog = null;
    this.onKey = (e) => { if (e.key === 'Escape' && this.dialog) { e.preventDefault(); this.close(); } };
  }
  setSound(state) {
    if (state === this.state) return;
    this.state = state; const f = soundFace(state);
    this.sound.classList.toggle('off', f.off); this.sound.setAttribute('aria-pressed', f.pressed); this.sound.setAttribute('aria-label', f.aria);
    this.sound.innerHTML = f.icon + '<span>' + f.label + '</span>'; this.sound.title = f.label;
  }
  setCompact(on) { if (on === this.compact) return; this.compact = on; this.box.classList.toggle('compact', on); }
  // place at the bottom-right corner, or left of / above an open panel. pos {right, bottom} in px from the window edges
  place(pos) { this.box.style.right = Math.round(pos.right) + 'px'; this.box.style.bottom = Math.round(pos.bottom) + 'px'; }
  rect() { const r = this.box.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; }
  isOpen() { return !!this.dialog; }
  open() {
    if (this.dialog) return;
    const d = this.doc, wrap = this.dialog = d.createElement('div'); wrap.className = 'b2-how';
    wrap.innerHTML = '<div class="scrim"></div><div class="how" role="dialog" aria-modal="true" aria-labelledby="b2-how-title"><div class="hh"><h2 id="b2-how-title">' + COPY.menu +
      '</h2><button type="button" class="rb x" aria-label="' + COPY.close + '">×</button></div><div class="hb" aria-busy="true"><p class="loading">' + COPY.loading + '</p></div></div>';
    wrap.querySelector('.scrim').addEventListener('click', () => this.close());
    wrap.querySelector('.x').addEventListener('click', () => this.close());
    d.body.appendChild(wrap); d.addEventListener('keydown', this.onKey);
    this.menu.setAttribute('aria-expanded', 'true'); wrap.querySelector('.x').focus();
    this.fill(wrap.querySelector('.hb'));
  }
  // the docs page's sections, fetched once per page; a failure says so, with the page's own link (no stale copy here)
  async fill(hb) {
    let sections = this.sections;
    if (!sections) {
      try { const r = await (this.fetchFn || ((...a) => globalThis.fetch(...a)))(DOCS_URL, { cache: 'no-store' }); if (!r.ok) throw new Error('docs ' + r.status); sections = docsSections(await r.text()); }
      catch (e) { console.warn('How it works unavailable', String(e)); sections = null; }
      if (sections && sections.length) this.sections = sections;
    }
    if (!hb.isConnected && hb.isConnected !== undefined) return;   // closed meanwhile
    hb.removeAttribute('aria-busy');
    hb.innerHTML = sections && sections.length
      ? sections.map((x) => '<section' + (x.id ? ' data-doc="' + x.id + '"' : '') + '>' + x.html + '</section>').join('')
      : '<p class="loading">' + COPY.failed + ' <a href="/web/docs.html" target="_blank" rel="noopener">/web/docs.html</a></p>';
  }
  close() {
    if (!this.dialog) return;
    this.dialog.remove(); this.dialog = null; this.doc.removeEventListener('keydown', this.onKey);
    this.menu.setAttribute('aria-expanded', 'false'); this.menu.focus();
  }
}
