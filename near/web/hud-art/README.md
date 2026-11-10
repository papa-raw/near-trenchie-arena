# hud-art: the arena HUD as game art (panel set "candle", draft "a")

`hud-art.js` draws the arena's panels as SVG: the top-3 price tags on a twisted cord, the driftwood lead banner, the ticker feed,
the legendary drop receipt, HP candles, name tags and the sound and menu buttons. Fonts are in `fonts/` (SIL OFL 1.1, see
`fonts/LICENSES.txt`); no network is needed. This copy is comment-only edited from the approved drawing: no drawing code changed.

```js
HUDART.mount(frameEl, { concept: 'candle', draft: 'a', w: 1440, h: 900,
  fighters: [{ x, y, tag, hp, kos, state }],   // x, y in frame px at the feet; state 'followed' gets the second name tag
  lead: { tag, kos }, feed: [{ kind: 'ko' | 'drop', a, b, item }] })
// -> Promise<{ hudPct, cornerPct, worldPct, centre, rects }>; frameEl must be position:relative, w x h design px
HUDART.panels('candle', opts) // -> Promise<[{ id, node, w, h }]> one drawn node per panel (the receipt, a tag, a bar ...)
```

`w < 600` draws the phone layout.
