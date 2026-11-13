// Prediction circles on each individual name tag: empty at first, filling green as its prediction is met.
// One circle per predicted KO, filled green per KO this life, ringed green when met, "+N" for KOs beyond.
// Every fighter keeps these circles on its own individual name tag.

// The circles a tag shows. level: the life's predicted level (1-4) or null (no circles); kos: KOs this life.
export function circlesModel(level, kos) {
  if (!Number.isInteger(level) || level < 1) return null;
  const k = Math.max(0, kos | 0);
  return { n: level, filled: Math.min(k, level), met: k >= level, extra: Math.max(0, k - level) };
}

// The words a screen reader gets for the circles (the sheet's aria-label).
export function circlesLabel(m) { return m ? 'predicts ' + m.n + '+ KOs, ' + (m.filled + m.extra) + ' so far' : ''; }

export function circlesNode(doc, m, cls = '') {
  const s = doc.createElement('span');
  s.className = 'pips' + (m.met ? ' met' : '') + (cls ? ' ' + cls : '');
  s.setAttribute('role', 'img'); s.setAttribute('aria-label', circlesLabel(m));
  for (let i = 0; i < m.n; i++) { const c = doc.createElement('i'); if (i < m.filled) c.className = 'on'; s.appendChild(c); }
  if (m.extra) { const b = doc.createElement('b'); b.textContent = '+' + m.extra; s.appendChild(b); }
  return s;
}
// a stable key for a model, so a tag's circles are rebuilt only when they change
export const circlesKey = (m) => (m ? m.n + ':' + m.filled + ':' + m.extra : '');
