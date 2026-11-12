// The corner buttons and "How it works" (approved board 2, direction C; Pat's item 6: "this red menu does nothing", "the
// sound icon has no on/off states"). Both buttons always carry words, at both widths. Sound: waves + "Sound" when on; a
// slash + "Muted", greyed and pressed, when off; aria-pressed follows. "How it works" opens a dialog of eight sections;
// x, a click outside or Escape closes it, and focus returns to the button.

export const COPY = {
  sound: { on: 'Sound', off: 'Muted', onAria: 'Sound is on. Turn it off.', offAria: 'Sound is off. Turn it on.' },
  menu: 'How it works', close: 'Close',
  how: [
    ['Watch', 'Anyone can watch. No wallet, no key.'],
    ['Snap in', 'Sign in with a NEAR wallet and bring your own AI: an API key in this browser, or your Claude or Codex plan through an agent session.'],
    ['Your trenchie', 'A NEAR mainnet NFT. The first 50 are free to claim; after that a mint costs 0.01 NEAR. Its fights, gear and record live on NEAR testnet, under its token id.'],
    ['Orders', 'Tell your trenchie what to do in plain words. It answers in its own voice, and the arena shows what it set and why.'],
    ['Predictions', 'Before each life, a trenchie predicts its KOs: 2 means 2 or more. The circles by its name fill green as it gets there.'],
    ['Rewards and failure', 'A correct prediction earns reward points, more for a rarer level. A prediction may carry an optional 0.01 testnet NEAR; on a failure it goes to the reward fund.'],
    ['Gear', 'A KO drops one item. A rival can grab it; ungrabbed for 60 s, it is gone. Legendaries glow on the floor.'],
    ['What it costs', 'Watching is free. Your AI spends from your own key or plan, under the cap you set.'],
  ],
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

export class Corner {
  constructor(doc, root, { onSound }) {
    this.doc = doc; this.state = null;
    const box = this.box = doc.createElement('div'); box.className = 'corner';
    this.sound = doc.createElement('button'); this.sound.type = 'button'; this.sound.className = 'rb'; this.sound.dataset.panel = 'btn0';
    this.sound.addEventListener('click', () => onSound && onSound());
    this.menu = doc.createElement('button'); this.menu.type = 'button'; this.menu.className = 'rb menu'; this.menu.dataset.panel = 'btn1';
    this.menu.setAttribute('aria-haspopup', 'dialog'); this.menu.innerHTML = ICON.menu + '<span>' + COPY.menu + '</span>';
    this.menu.addEventListener('click', () => this.open());
    box.append(this.sound, this.menu); root.appendChild(box);
    this.dialog = null;
    this.onKey = (e) => { if (e.key === 'Escape' && this.dialog) { e.preventDefault(); this.close(); } };
  }
  setSound(state) {
    if (state === this.state) return;
    this.state = state; const f = soundFace(state);
    this.sound.classList.toggle('off', f.off); this.sound.setAttribute('aria-pressed', f.pressed); this.sound.setAttribute('aria-label', f.aria);
    this.sound.innerHTML = f.icon + '<span>' + f.label + '</span>';
  }
  // place at the bottom-right corner, or left of / above an open panel. pos {right, bottom} in px from the window edges
  place(pos) { this.box.style.right = Math.round(pos.right) + 'px'; this.box.style.bottom = Math.round(pos.bottom) + 'px'; }
  rect() { const r = this.box.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; }
  isOpen() { return !!this.dialog; }
  open() {
    if (this.dialog) return;
    const d = this.doc, wrap = this.dialog = d.createElement('div'); wrap.className = 'b2-how';
    wrap.innerHTML = '<div class="scrim"></div><div class="how" role="dialog" aria-modal="true" aria-labelledby="b2-how-title"><div class="hh"><h2 id="b2-how-title">' + COPY.menu +
      '</h2><button type="button" class="rb x" aria-label="' + COPY.close + '">×</button></div><div class="hb">' +
      COPY.how.map((h) => '<section><h3>' + h[0] + '</h3><p>' + h[1] + '</p></section>').join('') + '</div></div>';
    wrap.querySelector('.scrim').addEventListener('click', () => this.close());
    wrap.querySelector('.x').addEventListener('click', () => this.close());
    d.body.appendChild(wrap); d.addEventListener('keydown', this.onKey);
    this.menu.setAttribute('aria-expanded', 'true'); wrap.querySelector('.x').focus();
  }
  close() {
    if (!this.dialog) return;
    this.dialog.remove(); this.dialog = null; this.doc.removeEventListener('keydown', this.onKey);
    this.menu.setAttribute('aria-expanded', 'false'); this.menu.focus();
  }
}
