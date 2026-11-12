// Where the legendary floor signs go (approved board 2: "LEGENDARY: <ITEM>" with the item's picture). Under board 3's
// phone camera (2.8x) two drops and the bodies around them crowd one spot, and a sign covered another sign's text or a
// body. Each sign keeps its pin on the item and takes the first clear spot right next to it: above (centred,
// or slid so the pin sits under either end), below, the sides, the corners; on screen, clear of the bodies, the tags,
// the crowd cards, the fixed HUD panels (the guide's snap-in button among them), every pin and the signs already
// placed. The words are kept wherever they fit (the full words are part of the sign's design): the full sign
// ("LEGENDARY: <NAME>" and the picture), else the picture and the name alone (never cut), else the picture alone next
// to the pin or on the pin itself (a tap on a phone, or hover, opens the full sign; the full text is also its label); with no room even for that, only the pin shows until there is. A pin off screen or under
// a HUD panel hides its sign. A word is never cut, and no line joins a sign to its pin (Pat's item 35: no thin line on
// the sign). Pure: the legend-place case runs it in node.

export const GAP = 14, LIFT = 22, NEAR = 8, MARGIN = 6, PIN = 5;   // NEAR: the short form sits closer (it is only a picture)
const hit = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;

// the spots right next to a pin, nearest first: above (centred, then slid so the pin sits under either end), below,
// the sides, the four corners
function spots(s, w, h, lift, gap) {
  const up = s.ay - lift - h, below = s.ay + gap, left = s.ax - gap - w, right = s.ax + gap, mid = s.ay - h / 2;
  return [
    { pos: 'up', x: s.ax - w / 2, y: up }, { pos: 'up', x: s.ax - w + 16, y: up }, { pos: 'up', x: s.ax - 16, y: up },
    { pos: 'below', x: s.ax - w / 2, y: below }, { pos: 'below', x: s.ax - w + 16, y: below }, { pos: 'below', x: s.ax - 16, y: below },
    { pos: 'left', x: left, y: mid }, { pos: 'right', x: right, y: mid },
    { pos: 'up-left', x: left, y: up }, { pos: 'up-right', x: right, y: up }, { pos: 'below-left', x: left, y: below }, { pos: 'below-right', x: right, y: below },
  ];
}

/** signs: [{key, ax, ay (the pin, screen px), w, h (full form), nw, nh (picture + name; optional), cw, ch (the picture
 *  alone)}]; obstacles: [{x, y, w, h}]; view {w, h}; panels: the fixed HUD boxes (also in obstacles).
 *  -> Map key -> {x, y, w, h, pos, form: 'full' | 'name' | 'picture'} or
 *  {hidden: 'off screen' | 'under the HUD' | 'no room'}. Signs are placed
 *  in key order (stable frame to frame): the full form right next to the pin, else the name form right next to it,
 *  else the picture right next to it, else the picture on the pin itself (pos 'at'). A sign whose pin is off screen or under a HUD panel (its item is
 *  not in view), or with none of those spots clear, is hidden (the pin still marks the item); a hidden sign takes no
 *  room. */
export function placeLegendSigns(signs, obstacles, view, panels = []) {
  const placed = [], out = new Map();
  // every pin is an obstacle too: no sign sits on another sign's pin (a red dot on its text), nor a full sign on its own
  const pins = signs.map((s) => ({ key: s.key, x: s.ax - PIN, y: s.ay - PIN, w: 2 * PIN, h: 2 * PIN }));
  const onScreen = (r) => r.x >= MARGIN && r.y >= MARGIN && r.x + r.w <= view.w - MARGIN && r.y + r.h <= view.h - MARGIN;
  const clear = (r, own) => onScreen(r) && !obstacles.some((o) => hit(r, o)) && !pins.some((o) => o.key !== own && hit(r, o)) && !placed.some((o) => hit(r, o));
  for (const s of [...signs].sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))) {
    if (s.ax < 0 || s.ay < 0 || s.ax > view.w || s.ay > view.h) { out.set(s.key, { hidden: 'off screen' }); continue; }
    if (panels.some((p) => s.ax >= p.x && s.ax <= p.x + p.w && s.ay >= p.y && s.ay <= p.y + p.h)) { out.set(s.key, { hidden: 'under the HUD' }); continue; }
    let got = null;
    const forms = [['full', s.w, s.h, LIFT, GAP], ...(s.nw ? [['name', s.nw, s.nh, LIFT, GAP]] : []), ['picture', s.cw, s.ch, NEAR, NEAR]];
    forms: for (const [form, w, h, lift, gap] of forms) {
      for (const c of spots(s, w, h, lift, gap)) { const r = { x: c.x, y: c.y, w, h }; if (clear(r)) { got = { ...r, pos: c.pos, form }; break forms; } }
    }
    if (!got) {   // the picture on the pin itself: it marks the item in the pin's place
      const r = { x: s.ax - s.cw / 2, y: s.ay - s.ch / 2, w: s.cw, h: s.ch };
      if (clear(r, s.key)) got = { ...r, pos: 'at', form: 'picture' };
    }
    if (!got) { out.set(s.key, { hidden: 'no room' }); continue; }
    placed.push(got); out.set(s.key, got);
  }
  return out;
}

/** A body's on-screen box from its projected feet (y 0) and head point (y 1.5): the round trenchie bodies draw about
 *  1.1 times as wide as that span, reach about a third of it below the feet point and, with a head item, about a third
 *  above the head point (measured on the 390 page at 2.8x against the drawn meshes; a very tall hat can still rise
 *  past it). */
export function bodyBox(feet, head) {
  const span = Math.max(8, feet.y - head.y), w = span * 1.1;
  return { x: feet.x - w / 2, y: head.y - span * 0.35, w, h: span * 1.7 };
}
