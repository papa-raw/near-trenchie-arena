"""gen_kit.py — writes kit.json: the designer's kit of parts (V3), in the renderer-neutral item format.

Run: python3 -I near/items/gen_kit.py   (rewrites near/items/kit.json; the output is deterministic)

A base is a small tree of named primitives. Colours are roles ($main, $accent, $trim) that the menu and the bag fill with
palette ids p01-p16 (never the reserved danger hue). Spaces:
  head     origin on the axis at eye height; the crown starts at y = +0.082, the body's top is y = +0.251
  body     origin at the body's bottom; the body is about 0.66 tall; shells sit 0.012 proud of it
  weapon   grip at the origin, shaft along +y
  trinket  emblem on the left hip, front = +z; the tier plate under it belongs to the renderer
Node fields: type, color, translate [x,y,z], rotate [x,y,z] (radians, XYZ), scale [x,y,z] (0.25-4), and the type's size fields:
  sphere r | hemisphere r | cylinder r h [rTop] [arc arcStart open] | cone r h | box w h d | torus r tube [arc]
  tube points[2-8] r | plate w h t [radius]
"""
import json, math, os

H, R0, N, E, FLARE = 0.66, 0.226, 2.7, 2.1, 0.035
FACE_Y = H * 0.62          # eye height above the body's bottom
CROWN, TOP = 0.082, H - FACE_Y


def body_r(y):
    """Body radius at a height above its bottom (the same lathe the renderer draws)."""
    k = max(-1.0, min(1.0, 2 * y / H - 1))
    s = math.copysign(abs(k) ** (E / 2), k)
    c = math.sqrt(max(0.0, 1 - s * s))
    return R0 * (c ** (2 / N)) * (1 + FLARE * (1 - y / H))


def crown_r(dy):
    return body_r(FACE_Y + dy)


def r3(v):
    return [r3(x) if isinstance(x, (list, tuple)) else round(x, 4) for x in v]


def nd(kind, color, tr=(0, 0, 0), rot=(0, 0, 0), scale=None, **size):
    o = {'type': kind, 'color': color}
    o.update({k: (round(v, 4) if isinstance(v, float) else (r3(v) if isinstance(v, (list, tuple)) else v)) for k, v in size.items()})
    if any(tr): o['translate'] = r3(tr)
    if any(rot): o['rotate'] = r3(rot)
    if scale is not None: o['scale'] = r3(scale) if isinstance(scale, (list, tuple)) else round(scale, 4)
    return o


PI = math.pi
M, A, T = '$main', '$accent', '$trim'
kit = {'spec': 'trenchie-kit/1', 'item_spec': 'trenchie-item/3', 'units': 'item units: 2 per tile; angles in degrees; a tube is stroked at width = 2r',
       'note': 'Colours are palette ids p01-p15; p16 is the reserved danger hue and no item uses it. A node with a role recolours when a row names a colour for that role.',
       'spec_dir': 'specs', 'bases': {}, 'menu': []}
SPECS = {}   # row id -> kit-built item spec, written to specs/<id>.json
U = 2.0      # item units per tile


def conv(n, defaults, dy):
    """Tile-space authored node -> item units, degrees, literal palette id plus role."""
    o = dict(n)
    role = o['color'][1:] if o['color'].startswith('$') else None
    o['color'] = defaults[role] if role else o['color']
    if role: o['role'] = role
    for k in ('r', 'h', 'rTop', 'tube', 'w', 'd', 'radius', 't'):
        if k in o and not (k == 'r' and o['type'] == 'tube'): o[k] = round(o[k] * U, 4)
    if o['type'] == 'tube':
        o['points'] = [[round(p[0] * U, 4), round((p[1] + dy) * U, 4), round(p[2] * U, 4)] for p in o['points']]
        o['width'] = round(2 * o.pop('r') * U, 4)   # r (tiles) -> diameter in item units
    tr = o.get('translate', [0, 0, 0]) if o['type'] != 'tube' else [0, 0, 0]
    if o['type'] != 'tube':
        o['translate'] = [round(tr[0] * U, 4), round((tr[1] + dy) * U, 4), round(tr[2] * U, 4)]
    if o['type'] == 'torus':   # item format: a torus ring lies in the XZ plane (axis y); authored here for a ring in XY, so turn it
        rot = list(o.get('rotate', (0, 0, 0))); rot[0] -= math.pi / 2; o['rotate'] = rot
    if 'rotate' in o: o['rotate'] = [round(math.degrees(a), 2) for a in o['rotate']]
    if 'arc' in o: o['arc'] = round(math.degrees(o['arc']), 2)
    if 'arcStart' in o: o['arcStart'] = round(math.degrees(o['arcStart']), 2)
    return {k: o[k] for k in ['type', 'role', 'color', 'r', 'rTop', 'h', 'w', 'd', 'tube', 'width', 'radius', 't', 'points', 'arc', 'arcStart', 'open', 'translate', 'rotate', 'scale'] if k in o}


def finalize(slot, bases):
    out = {}
    for key, (name, cols, nodes) in bases.items():
        defaults = {k[1:]: v for k, v in cols.items()}
        dy = 0.11 if slot == 'trinket' else 0.0   # the trinket box starts at y = 0, so the emblem sits 0.11 tile above its origin
        out[key] = {'name': name, 'colors': defaults, 'nodes': [conv(n, defaults, dy) for n in nodes]}
    return out

# ------------------------------------------------------------------ helpers
def grow(nodes, k):
    """Scale an emblem or weapon part about its origin (sizes, offsets, points) so a piece can be drawn at one size and used at another."""
    out = []
    for n in nodes:
        n = dict(n)
        for f in ('r', 'h', 'w', 'd', 'tube', 'radius', 't', 'rTop'):
            if f in n: n[f] = n[f] * k
        if 'translate' in n: n['translate'] = tuple(v * k for v in n['translate'])
        if 'points' in n: n['points'] = [[v * k for v in p] for p in n['points']]
        out.append(n)
    return out


def skirt(y0, y1, r0=None, ex=0.014, cap=0.243):
    """A shell between two body heights that follows the body's own radius (capped by the slot box)."""
    return dict(r=min(cap, body_r(y0) + ex), rTop=min(cap, body_r(y1) + ex), h=y1 - y0)


def onbody(x, y, off=0.012):
    """A point on the front of a shell at height y and sideways x, plus the turn about the vertical that faces a flat piece outward."""
    r = min(0.249, body_r(y) + off)
    z = math.sqrt(max(r * r - x * x, 0.0))
    return (x, y, z), math.atan2(x, z)


def backbody(x, y, off=0.012):
    (px, py, pz), _ = onbody(x, y, off)
    return (px, py, -pz)


def mid(y0, y1):
    return (y0 + y1) / 2


def along(phi, s, lateral=0.0, z=0.0, y0=0.0):
    """A point s along an axis tilted phi from vertical (clockwise from above, like a pen in a pocket), with a sideways offset."""
    return (math.sin(phi) * s + math.cos(phi) * lateral, math.cos(phi) * s - math.sin(phi) * lateral + y0, z)


# ------------------------------------------------------------------ head
rc = crown_r(CROWN)
def ring_at(dy, ex=0.0):
    return crown_r(dy) + ex
head = {
 'cap': ('Sun cap', {M: 'p14', A: 'p15'}, [
    nd('hemisphere', M, (0, CROWN, 0), scale=[1, 0.95, 1], r=rc + 0.014),
    nd('cylinder', A, (0, CROWN + 0.004, 0.012), scale=[1, 1, 1.3], r=(rc + 0.014) * 0.98, h=0.022, arc=PI * 0.9, arcStart=-PI * 0.45),
    nd('sphere', A, (0, TOP + 0.03, 0), r=0.026)]),
 'bucket': ('Bucket hat', {M: 'p09', A: 'p10'}, [
    nd('cylinder', M, (0, CROWN + 0.085, 0), r=ring_at(0.1, 0.018), rTop=ring_at(0.2, 0.0) * 0.8, h=0.17),
    nd('cylinder', M, (0, CROWN - 0.004, 0), r=rc + 0.09, h=0.02),
    nd('cylinder', A, (0, CROWN + 0.034, 0), r=ring_at(0.115, 0.022), h=0.034, open=True)]),
 'cone': ('Party cone', {M: 'p11', A: 'p12'}, [
    nd('cone', M, (-0.02, TOP + 0.07, 0), (0, 0, -0.22), r=crown_r(TOP - 0.05) * 0.85, h=0.26),
    nd('sphere', A, (-0.054, TOP + 0.195, 0), r=0.038),
    nd('torus', A, (-0.002, CROWN + 0.03, 0), (PI / 2, 0, -0.22), r=crown_r(CROWN + 0.03) * 0.78, tube=0.012)]),
 # Sweatband: a thick terry band round the forehead with two white stripes, a knot at the side with two tails, and a bright patch on the front
 'sweatband': ('Sweatband', {M: 'p15', A: 'p04'}, [
    nd('torus', M, (0, CROWN + 0.04, 0), (PI / 2, 0, 0), scale=[1, 1.9, 1], r=ring_at(CROWN + 0.04, 0.012), tube=0.034),
    nd('torus', A, (0, CROWN + 0.062, 0), (PI / 2, 0, 0), r=ring_at(CROWN + 0.062, 0.022), tube=0.008),
    nd('torus', A, (0, CROWN + 0.018, 0), (PI / 2, 0, 0), r=ring_at(CROWN + 0.018, 0.022), tube=0.008),
    nd('cylinder', A, (0, CROWN + 0.04, ring_at(CROWN + 0.04, 0.012) * 1.0 + 0.026), (PI / 2, 0, 0), r=0.03, h=0.012),
    nd('sphere', M, (ring_at(CROWN + 0.04, 0.012) + 0.012, CROWN + 0.04, -0.03), r=0.04),
    nd('cone', M, (ring_at(CROWN + 0.04, 0.012) + 0.03, CROWN - 0.012, -0.06), (PI, 0, -0.5), r=0.026, h=0.12),
    nd('cone', M, (ring_at(CROWN + 0.04, 0.012) + 0.0, CROWN - 0.012, -0.075), (PI, 0, 0.35), r=0.026, h=0.11)]),
 # Hard hat: a bright yellow dome with a centre ridge and two ribs, a round brim, a front lamp
 'hardhat': ('Hard hat', {M: 'p12', A: 'p13'}, [
    nd('hemisphere', M, (0, CROWN, 0), scale=[1, 0.92, 1], r=rc + 0.018),
    nd('cylinder', M, (0, CROWN + 0.008, 0.014), r=rc + 0.056, h=0.026),
    nd('tube', A, points=[[0, CROWN + 0.004 + 0.92 * (rc + 0.018) * 1.0 * math.sin(a), (rc + 0.018) * 1.0 * math.cos(a)] for a in [i * PI / 6 for i in range(7)]], r=0.02),
    nd('tube', A, points=[[-(rc + 0.018) * math.cos(a) * 0.97, CROWN + 0.004 + 0.92 * (rc + 0.018) * math.sin(a) * 0.97, 0] for a in [i * PI / 6 for i in range(1, 6)]], r=0.014),
    nd('cylinder', 'p06', (0, CROWN + 0.058, rc + 0.022), (PI / 2, 0, 0), r=0.032, h=0.026),
    nd('sphere', 'p04', (0, CROWN + 0.058, rc + 0.038), r=0.022)]),
 # Beanie: a ribbed knit dome with five ribs, a thick folded cuff with a gold stripe and a woven patch, a two-tone pom
 'beanie': ('Beanie', {M: 'p10', A: 'p09'}, [
    nd('hemisphere', M, (0, CROWN - 0.01, 0), scale=[1, 1.1, 1], r=rc + 0.014),
    nd('torus', A, (0, CROWN + 0.014, 0), (PI / 2, 0, 0), scale=[1, 1.4, 1], r=ring_at(CROWN + 0.014, 0.008), tube=0.03),
    nd('torus', 'p12', (0, CROWN + 0.03, 0), (PI / 2, 0, 0), r=ring_at(CROWN + 0.03, 0.022), tube=0.007),
    *[nd('tube', A, points=[[(rc + 0.03) * math.sin(th) * math.sin(a), CROWN - 0.01 + 1.1 * (rc + 0.03) * math.cos(th), (rc + 0.03) * math.sin(th) * math.cos(a)] for th in (0.35, 0.8, 1.2)], r=0.007) for a in (-1.0, -0.5, 0.0, 0.5, 1.0)],
    nd('plate', 'p12', (0, CROWN + 0.012, ring_at(CROWN + 0.012, 0.034)), w=0.052, h=0.036, t=0.01, radius=0.008),
    nd('sphere', 'p15', (0, CROWN + 0.012, ring_at(CROWN + 0.012, 0.044)), r=0.009),
    nd('sphere', A, (0, TOP + 0.05, 0), r=0.052), nd('sphere', 'p04', (-0.02, TOP + 0.07, 0.02), r=0.026), nd('sphere', 'p04', (0.025, TOP + 0.045, -0.015), r=0.022)]),
 # Visor: a wide sporty band, a big curved bill in a second colour, a side stripe and a front dot; open on top
 # Visor: a wide sporty band, a big bill that juts out and tilts down, a white dot and a thin white stripe; open on top
 'visor': ('Visor', {M: 'p07', A: 'p12'}, [
    nd('torus', M, (0, CROWN + 0.04, 0), (PI / 2, 0, 0), scale=[1, 1.7, 1], r=ring_at(CROWN + 0.04, 0.012), tube=0.034),
    nd('cylinder', A, (0, CROWN + 0.03, 0.115), (0.2, 0, 0), r=(rc * 0.78), h=0.026, arc=PI * 1.0, arcStart=-PI * 0.5),
    nd('cylinder', 'p13', (0, CROWN + 0.03, 0.115), (0.2, 0, 0), r=(rc * 0.78) + 0.002, h=0.008, arc=PI * 1.0, arcStart=-PI * 0.5),
    nd('sphere', 'p04', (0, CROWN + 0.06, ring_at(CROWN + 0.06, 0.026)), r=0.02),
    nd('torus', 'p04', (0, CROWN + 0.02, 0), (PI / 2, 0, 0), r=ring_at(CROWN + 0.02, 0.016), tube=0.006)]),
 # Crown: a tall gold band with five spikes tipped by round beads, and three jewels on the band
 'crown': ('Crown', {M: 'p12', A: 'p15'}, [
    nd('cylinder', M, (0, CROWN + 0.04, 0), r=ring_at(CROWN + 0.04, 0.018), h=0.07),
    *[nd('cone', M, (math.sin(a) * (ring_at(CROWN + 0.08, 0.014) - 0.004), CROWN + 0.125, math.cos(a) * (ring_at(CROWN + 0.08, 0.014) - 0.004)), r=0.036, h=0.12)
      for a in [i * 2 * PI / 5 + PI / 5 for i in range(5)]],
    *[nd('sphere', A, (math.sin(a) * (ring_at(CROWN + 0.19, 0.0) - 0.002), CROWN + 0.19, math.cos(a) * (ring_at(CROWN + 0.19, 0.0) - 0.002)), r=0.017)
      for a in [i * 2 * PI / 5 + PI / 5 for i in range(5)]],
    nd('sphere', A, (0, CROWN + 0.042, ring_at(CROWN + 0.042, 0.022)), r=0.02),
    nd('sphere', 'p10', (-0.06, CROWN + 0.042, ring_at(CROWN + 0.042, 0.022) - 0.012), r=0.016),
    nd('sphere', 'p10', (0.06, CROWN + 0.042, ring_at(CROWN + 0.042, 0.022) - 0.012), r=0.016)]),
}
kit['bases']['head'] = finalize('head', head)

# ------------------------------------------------------------------ body (body space: origin at the bottom). Garments are shells that follow the body, with the pieces that make each one itself.
def flower(x, y, petal, heart, rad=0.032):
    p, ry = onbody(x, y, 0.016)
    q, _ = onbody(x, y, 0.022)
    return [nd('cylinder', petal, p, (PI / 2, ry, 0), r=rad, h=0.01), nd('sphere', heart, q, r=rad * 0.42)]


def sleeve(side, y, color, cuff, length=0.1, r=0.05, lean=0.3):
    """A short sleeve hanging off the shoulder: a tube leaning out at the bottom, a cuff band on its end."""
    x = side * (body_r(y) + 0.03)
    th = side * lean
    c = (x, y, 0.01)
    bottom = (x + (length / 2) * math.sin(th), y - (length / 2) * math.cos(th), 0.01)
    return [nd('cylinder', color, c, (0, 0, th), r=r, rTop=r * 0.9, h=length),
            nd('cylinder', cuff, bottom, (0, 0, th), r=r * 1.06, h=0.022)]


body = {
 # Beach tee: a roomy tee with short sleeves and a crew neck, a wave stripe at the hem, a sun on the chest
 'tee': ('Tee', {M: 'p05', A: 'p09', T: 'p12'}, [
    nd('cylinder', M, (0, mid(0.05, 0.30), 0), **skirt(0.05, 0.30, ex=0.016)),
    nd('cylinder', A, (0, 0.085, 0), **skirt(0.06, 0.11, ex=0.024)),
    nd('cylinder', A, (0, 0.135, 0), **skirt(0.125, 0.14, ex=0.02)),
    nd('torus', A, (0, 0.298, 0), (PI / 2, 0, 0), r=body_r(0.298) + 0.014, tube=0.018),
    *sleeve(-1, 0.25, M, A, length=0.09, r=0.055), *sleeve(1, 0.25, M, A, length=0.09, r=0.055),
    nd('cylinder', T, onbody(0, 0.215, 0.022)[0], (PI / 2, 0, 0), r=0.04, h=0.012),
    nd('torus', 'p13', onbody(0, 0.215, 0.024)[0], r=0.05, tube=0.008)]),
 # Life vest: a bright orange vest with a fat collar roll, two white reflective bands, a black belt strap with a buckle, a whistle
 'vest': ('Life vest', {M: 'p14', A: 'p04', T: 'p12'}, [
    nd('cylinder', M, (0, mid(0.08, 0.30), 0), **skirt(0.08, 0.30, ex=0.02)),
    nd('torus', M, (0, 0.295, 0), (PI / 2, 0, 0), r=body_r(0.295) + 0.024, tube=0.028),
    nd('plate', A, (-0.075, 0.2, onbody(-0.075, 0.2, 0.03)[0][2]), w=0.04, h=0.17, t=0.012, radius=0.008),
    nd('plate', A, (0.075, 0.2, onbody(0.075, 0.2, 0.03)[0][2]), w=0.04, h=0.17, t=0.012, radius=0.008),
    nd('cylinder', 'p01', (0, 0.155, 0), **skirt(0.14, 0.17, ex=0.032)),
    nd('box', T, (0, 0.155, onbody(0, 0.155, 0.04)[0][2]), w=0.04, h=0.04, d=0.012),
    nd('box', 'p01', (0, 0.22, onbody(0, 0.22, 0.026)[0][2]), w=0.012, h=0.16, d=0.01),
    nd('sphere', T, (0.1, 0.25, onbody(0.1, 0.25, 0.034)[0][2]), r=0.018)]),
 # Hawaiian shirt: mint shirt, cream collar flaps, short sleeves, hem band, and a loud print of five two-tone flowers
 'hawaiian': ('Hawaiian shirt', {M: 'p08', A: 'p14', T: 'p12'}, [
    nd('cylinder', M, (0, mid(0.06, 0.30), 0), **skirt(0.06, 0.30, ex=0.016)),
    nd('cylinder', A, (0, 0.075, 0), **skirt(0.06, 0.092, ex=0.024)),
    nd('plate', 'p04', onbody(-0.062, 0.255, 0.022)[0], (0, 0.5, 0.65), w=0.05, h=0.062, t=0.01, radius=0.012),
    nd('plate', 'p04', onbody(0.062, 0.255, 0.022)[0], (0, -0.5, -0.65), w=0.05, h=0.062, t=0.01, radius=0.012),
    nd('sphere', M, (-(body_r(0.27) + 0.032), 0.265, 0.01), scale=[0.9, 1.15, 0.9], r=0.066),
    nd('sphere', M, ((body_r(0.27) + 0.032), 0.265, 0.01), scale=[0.9, 1.15, 0.9], r=0.066),
    *flower(-0.15, 0.235, A, T, 0.04), *flower(0.1, 0.24, T, A, 0.04), *flower(-0.02, 0.165, A, T, 0.044),
    *flower(0.16, 0.16, A, T, 0.036), *flower(-0.13, 0.1, T, A, 0.036)]),
 # Wetsuit: dark suit, two bright side panels, a collar ring and a hem, short sleeves with bright cuffs, a centre zip with a gold pull
 'wetsuit': ('Wetsuit', {M: 'p01', A: 'p09', T: 'p12'}, [
    nd('cylinder', M, (0, mid(0.03, 0.30), 0), **skirt(0.03, 0.30, ex=0.016)),
    nd('cylinder', A, (0, mid(0.03, 0.30), 0), arc=0.5, arcStart=0.55, **skirt(0.03, 0.30, ex=0.024)),
    nd('cylinder', A, (0, mid(0.03, 0.30), 0), arc=0.5, arcStart=-1.05, **skirt(0.03, 0.30, ex=0.024)),
    nd('torus', A, (0, 0.295, 0), (PI / 2, 0, 0), r=body_r(0.295) + 0.012, tube=0.02),
    nd('cylinder', A, (0, 0.05, 0), **skirt(0.03, 0.075, ex=0.026)),
    *sleeve(-1, 0.23, M, A), *sleeve(1, 0.23, M, A),
    nd('box', 'p06', (0, 0.17, onbody(0, 0.17, 0.02)[0][2]), w=0.014, h=0.22, d=0.01),
    nd('box', T, (0, 0.275, onbody(0, 0.275, 0.026)[0][2]), w=0.028, h=0.036, d=0.012)]),
 # Overalls: cream tee under blue dungarees; a bright yellow bib with a blue pocket and two thick yellow straps over the shoulders, gold buttons
 'overalls': ('Overalls', {M: 'p10', A: 'p12', T: 'p04'}, [
    nd('cylinder', T, (0, mid(0.18, 0.31), 0), **skirt(0.18, 0.31, ex=0.01)),
    nd('cylinder', M, (0, mid(0.03, 0.22), 0), **skirt(0.03, 0.22, ex=0.022)),
    nd('plate', A, (0, 0.265, onbody(0, 0.265, 0.016)[0][2]), w=0.16, h=0.13, t=0.016, radius=0.024),
    nd('plate', M, (0, 0.24, onbody(0, 0.24, 0.026)[0][2]), w=0.08, h=0.06, t=0.012, radius=0.012),
    nd('sphere', 'p13', (-0.062, 0.318, onbody(-0.062, 0.318, 0.026)[0][2]), r=0.018),
    nd('sphere', 'p13', (0.062, 0.318, onbody(0.062, 0.318, 0.026)[0][2]), r=0.018),
    nd('tube', A, points=[onbody(-0.062, 0.316, 0.018)[0], onbody(-0.15, 0.345, 0.018)[0], onbody(-0.2, 0.41, 0.016)[0], backbody(-0.15, 0.45, 0.014)], r=0.03),
    nd('tube', A, points=[onbody(0.062, 0.316, 0.018)[0], onbody(0.15, 0.345, 0.018)[0], onbody(0.2, 0.41, 0.016)[0], backbody(0.15, 0.45, 0.014)], r=0.03),
    nd('torus', 'p01', (0, 0.222, 0), (PI / 2, 0, 0), r=body_r(0.222) + 0.026, tube=0.011)]),
 # Robe: a long lavender drape that flares at the hem, a gold hem and belt, a belt knot with two tails, V trim, bell sleeves
 'robe': ('Robe', {M: 'p11', A: 'p13', T: 'p04'}, [
    nd('cylinder', M, (0, mid(0.15, 0.30), 0), scale=[1.1, 1, 1], **skirt(0.15, 0.30, ex=0.016)),
    nd('cylinder', M, (0, 0.075, 0), scale=[1.25, 1, 1], r=0.243, rTop=body_r(0.15) + 0.018, h=0.15),
    nd('cylinder', A, (0, 0.02, 0), scale=[1.25, 1, 1], r=0.248, rTop=0.2445, h=0.04),
    nd('cylinder', A, (0, 0.2, 0), scale=[1.1, 1, 1], **skirt(0.18, 0.22, ex=0.024)),
    nd('sphere', A, (0.06, 0.2, onbody(0.06, 0.2, 0.03)[0][2]), r=0.03),
    nd('plate', A, (0.05, 0.135, onbody(0.05, 0.135, 0.03)[0][2]), (0, 0, 0.14), w=0.036, h=0.12, t=0.012, radius=0.01),
    nd('plate', A, (0.085, 0.13, onbody(0.085, 0.13, 0.03)[0][2]), (0, 0, -0.16), w=0.036, h=0.11, t=0.012, radius=0.01),
    nd('plate', T, onbody(-0.045, 0.265, 0.022)[0], (0, 0.3, 0.55), w=0.03, h=0.105, t=0.01, radius=0.008),
    nd('plate', T, onbody(0.045, 0.265, 0.022)[0], (0, -0.3, -0.55), w=0.03, h=0.105, t=0.01, radius=0.008),
    nd('cone', M, (-(body_r(0.24) + 0.026), 0.17, 0.01), r=0.082, h=0.19), nd('cone', M, ((body_r(0.24) + 0.026), 0.17, 0.01), r=0.082, h=0.19)]),
 # Poncho: a striped cape in five widening bands (mint, coral, gold), a neck ring and a fringe along the front hem
 'poncho': ('Poncho', {M: 'p07', A: 'p13', T: 'p14'}, [
    *[nd('cylinder', [M, T, M, A, M][k], (0, mid(0.06 + 0.048 * k, 0.108 + 0.048 * k), 0), scale=[1 + 1.33 * (0.30 - mid(0.06 + 0.048 * k, 0.108 + 0.048 * k)), 1, 1],
         r=min(0.249, body_r(0.06 + 0.048 * k) + 0.016 + 0.33 * (0.30 - 0.06 - 0.048 * k)),
         rTop=min(0.249, body_r(0.108 + 0.048 * k) + 0.016 + 0.33 * (0.30 - 0.108 - 0.048 * k)), h=0.048) for k in range(5)],
    nd('torus', T, (0, 0.3, 0), (PI / 2, 0, 0), r=body_r(0.3) + 0.018, tube=0.015),
    *[nd('cylinder', A if i % 2 else T, (0.322 * math.sin(a), 0.036, 0.249 * math.cos(a)), r=0.011, h=0.05) for i, a in enumerate([-1.2 + 0.3 * k for k in range(9)])]]),
 # Sash: cream tunic and a wide coral sash slanting across the chest to a knot at the hip, a gold medal, two hanging tails
 'sash': ('Sash', {M: 'p15', A: 'p12', T: 'p04'}, [
    nd('cylinder', T, (0, mid(0.04, 0.30), 0), **skirt(0.04, 0.30, ex=0.012)),
    nd('torus', M, (0, 0.215, 0), (PI / 2, 0, -0.42), scale=[1, 2.1, 1], r=body_r(0.215) + 0.018, tube=0.03),
    nd('torus', A, (0, 0.255, 0), (PI / 2, 0, -0.42), scale=[1, 0.5, 1], r=body_r(0.255) + 0.026, tube=0.008),
    nd('cylinder', A, onbody(0.0, 0.215, 0.042)[0], (PI / 2, 0, 0), r=0.036, h=0.014),
    nd('sphere', 'p13', onbody(0.0, 0.215, 0.052)[0], r=0.015),
    nd('sphere', M, (-0.145, 0.1, onbody(-0.145, 0.1, 0.032)[0][2]), r=0.038),
    nd('plate', M, (-0.17, 0.085, onbody(-0.17, 0.085, 0.03)[0][2]), (0, 0, 0.22), w=0.05, h=0.15, t=0.013, radius=0.012),
    nd('plate', M, (-0.115, 0.08, onbody(-0.115, 0.08, 0.034)[0][2]), (0, 0, -0.2), w=0.05, h=0.14, t=0.013, radius=0.012),
    nd('plate', A, (-0.17, 0.03, onbody(-0.17, 0.03, 0.034)[0][2]), (0, 0, 0.22), w=0.05, h=0.02, t=0.014),
    nd('plate', A, (-0.115, 0.03, onbody(-0.115, 0.03, 0.038)[0][2]), (0, 0, -0.2), w=0.05, h=0.02, t=0.014)]),
 # Apron: one cream apron shape, a bib narrowing to the neck above a wide skirt panel, thin blue trim all round, a blue waist band tied in a bow at the hip, a pocket with a spoon, two thin neck straps
 'apron': ('Apron', {M: 'p04', A: 'p10', T: 'p05'}, [
    nd('cylinder', M, (0, mid(0.03, 0.2), 0), arc=PI * 1.2, arcStart=-PI * 0.6, **skirt(0.03, 0.2, ex=0.02)),
    nd('plate', A, (0, 0.118, onbody(0, 0.118, 0.016)[0][2]), w=0.215, h=0.19, t=0.012, radius=0.03),
    nd('plate', M, (0, 0.118, onbody(0, 0.118, 0.022)[0][2]), w=0.2, h=0.175, t=0.012, radius=0.026),
    nd('plate', A, (0, 0.262, onbody(0, 0.262, 0.016)[0][2]), w=0.12, h=0.12, t=0.012, radius=0.02),
    nd('plate', M, (0, 0.262, onbody(0, 0.262, 0.022)[0][2]), w=0.105, h=0.105, t=0.012, radius=0.016),
    nd('plate', A, (0, 0.205, onbody(0, 0.205, 0.032)[0][2]), w=0.215, h=0.03, t=0.012, radius=0.01),
    nd('plate', A, (0, 0.09, onbody(0, 0.09, 0.034)[0][2]), w=0.1, h=0.07, t=0.01, radius=0.014),
    nd('plate', T, (0, 0.088, onbody(0, 0.088, 0.04)[0][2]), w=0.085, h=0.056, t=0.01, radius=0.011),
    nd('tube', 'p06', points=[[0.02, 0.1, onbody(0, 0.1, 0.048)[0][2]], [0.032, 0.14, onbody(0, 0.12, 0.048)[0][2]]], r=0.007),
    nd('sphere', 'p06', (0.034, 0.153, onbody(0, 0.12, 0.048)[0][2]), scale=[0.9, 1.25, 0.5], r=0.02),
    nd('tube', A, points=[onbody(-0.045, 0.318, 0.02)[0], onbody(-0.12, 0.345, 0.02)[0], onbody(-0.19, 0.4, 0.018)[0], backbody(-0.15, 0.47, 0.016)], r=0.012),
    nd('tube', A, points=[onbody(0.045, 0.318, 0.02)[0], onbody(0.12, 0.345, 0.02)[0], onbody(0.19, 0.4, 0.018)[0], backbody(0.15, 0.47, 0.016)], r=0.012),
    nd('tube', A, points=[onbody(0.105, 0.205, 0.03)[0], onbody(0.2, 0.205, 0.03)[0], backbody(0.12, 0.205, 0.03)], r=0.013),
    nd('sphere', A, (0.15, 0.205, 0.075), r=0.028),
    nd('plate', A, (0.178, 0.14, 0.066), (0, 0.4, 0.22), w=0.04, h=0.11, t=0.012, radius=0.01),
    nd('plate', A, (0.205, 0.155, 0.026), (0, 0.9, -0.25), w=0.04, h=0.1, t=0.012, radius=0.01)]),
}
kit['bases']['body'] = finalize('body', body)

# ------------------------------------------------------------------ weapon (grip at origin, shaft +y; the renderer leans it out like the roster's)
weapon = {
 'club': ('Bat', {M: 'p02', A: 'p03'}, [
    nd('cylinder', M, (0, 0.16, 0), r=0.018, rTop=0.042, h=0.34),
    nd('sphere', M, (0, 0.335, 0), r=0.042), nd('torus', A, (0, 0.02, 0), (PI / 2, 0, 0), r=0.02, tube=0.012),
    nd('sphere', A, (0.0, 0.22, 0.04), r=0.014)]),
 'oar': ('Oar', {M: 'p05', A: 'p10'}, [
    nd('cylinder', A, (0, 0.1, 0), r=0.018, h=0.34),
    nd('sphere', M, (0, 0.38, 0), scale=[0.85, 1.9, 0.26], r=0.075), nd('cylinder', 'p13', (0, 0.22, 0), r=0.026, h=0.03)]),
 # Narwhal pike: a long shaft with gold rings, a round blue narwhal head with an eye and a spotted back, and its spiral tusk as the point
 'spear': ('Narwhal pike', {M: 'p05', A: 'p10'}, [
    nd('cylinder', 'p03', (0, 0.17, 0), r=0.02, h=0.34),
    nd('torus', 'p13', (0, 0.06, 0), (PI / 2, 0, 0), r=0.024, tube=0.009), nd('torus', 'p13', (0, 0.28, 0), (PI / 2, 0, 0), r=0.024, tube=0.009),
    nd('sphere', A, (0, 0.38, 0), scale=[1.05, 0.9, 1.0], r=0.085),
    nd('sphere', 'p01', (0.03, 0.4, 0.07), r=0.014), nd('sphere', 'p14', (-0.045, 0.37, 0.065), r=0.015),
    nd('cone', M, (0, 0.545, 0), r=0.04, h=0.26),
    *[nd('torus', A, (0, 0.46 + 0.045 * i, 0), (PI / 2, 0, 0), r=0.04 - 0.0058 * (i + 0.5), tube=0.006) for i in range(4)]]),
 # Sling: a forked wooden handle, a thick rubber band and a leather pouch holding a big pebble
 'sling': ('Sling', {M: 'p03', A: 'p14'}, [
    nd('cylinder', M, (0, 0.09, 0), r=0.024, rTop=0.02, h=0.2),
    nd('torus', 'p01', (0, 0.03, 0), (PI / 2, 0, 0), r=0.026, tube=0.01),
    nd('tube', M, points=[[0, 0.18, 0], [-0.04, 0.24, 0], [-0.075, 0.31, 0]], r=0.02),
    nd('tube', M, points=[[0, 0.18, 0], [0.04, 0.24, 0], [0.075, 0.31, 0]], r=0.02),
    nd('tube', A, points=[[-0.075, 0.31, 0], [-0.04, 0.265, 0.01], [0, 0.245, 0.012], [0.04, 0.265, 0.01], [0.075, 0.31, 0]], r=0.011),
    nd('plate', 'p02', (0, 0.255, 0.014), w=0.07, h=0.045, t=0.014, radius=0.018),
    nd('sphere', 'p06', (0, 0.285, 0.02), r=0.045), nd('sphere', 'p05', (-0.014, 0.3, 0.052), r=0.012)]),
 # Jelly zapper: a brass cup holding a big wobbling jelly with a lighter core and two shines, a drip, two spark prongs with ball tips, wrapped grip
 'jelly': ('Jelly zapper', {M: 'p11', A: 'p12'}, [
    nd('cylinder', 'p03', (0, 0.11, 0), r=0.02, h=0.22),
    nd('torus', A, (0, 0.05, 0), (PI / 2, 0, 0), r=0.024, tube=0.01), nd('torus', A, (0, 0.11, 0), (PI / 2, 0, 0), r=0.024, tube=0.01),
    nd('cylinder', A, (0, 0.25, 0), r=0.045, rTop=0.085, h=0.07),
    nd('sphere', M, (0, 0.37, 0), scale=[1.05, 0.92, 1.0], r=0.135),
    nd('sphere', 'p04', (-0.01, 0.375, 0.04), r=0.07),
    nd('sphere', 'p04', (-0.07, 0.43, 0.09), scale=[0.6, 1.0, 0.5], r=0.026), nd('sphere', 'p04', (-0.04, 0.46, 0.1), r=0.012),
    nd('sphere', M, (0.115, 0.31, 0.05), r=0.04),
    nd('cylinder', A, (-0.085, 0.55, 0), (0, 0, 0.6), r=0.012, h=0.15), nd('cylinder', A, (0.085, 0.55, 0), (0, 0, -0.6), r=0.012, h=0.15),
    nd('sphere', 'p15', (-0.125, 0.62, 0), r=0.028), nd('sphere', 'p15', (0.125, 0.62, 0), r=0.028)]),
 # Lantern: a pole with a hook, a hanging cage lantern with a base, four bars, a glowing glass chamber and a flame, a pointed cap with a finial and a tassel
 'lens': ('Lantern', {M: 'p14', A: 'p12'}, [
    nd('cylinder', 'p03', (0, 0.12, 0), r=0.017, h=0.3),
    nd('tube', 'p03', points=[[0, 0.27, 0], [0.0, 0.31, 0], [0.04, 0.335, 0], [0.07, 0.31, 0]], r=0.011),
    nd('cylinder', M, (0.07, 0.2, 0), r=0.052, rTop=0.044, h=0.03),
    nd('sphere', A, (0.07, 0.255, 0), scale=[1, 1.15, 1], r=0.05),
    nd('cone', 'p15', (0.07, 0.252, 0), r=0.016, h=0.044),
    *[nd('cylinder', M, (0.07 + 0.047 * math.sin(a), 0.255, 0.047 * math.cos(a)), r=0.006, h=0.09) for a in (0.8, 2.4, 3.9, 5.5)],
    nd('cone', M, (0.07, 0.325, 0), r=0.06, h=0.05), nd('torus', 'p13', (0.07, 0.3, 0), (PI / 2, 0, 0), r=0.052, tube=0.007),
    nd('sphere', 'p13', (0.07, 0.356, 0), r=0.014), nd('cone', 'p15', (0.07, 0.17, 0), (PI, 0, 0), r=0.014, h=0.04),
    nd('torus', 'p13', (0, 0.05, 0), (PI / 2, 0, 0), r=0.021, tube=0.008)]),
 # Coconut mortar: a stubby wooden barrel on a flat-footed grip, gold bands, a flared muzzle, a coconut with three eyes in the mouth, a lit fuse
 'mortar': ('Coconut mortar', {M: 'p03', A: 'p12'}, [
    nd('cylinder', 'p01', (0, 0.1, 0), r=0.02, h=0.2),
    nd('cylinder', 'p01', (0, 0.012, 0), r=0.05, h=0.024),
    nd('torus', A, (0, 0.06, 0), (PI / 2, 0, 0), r=0.024, tube=0.009), nd('torus', A, (0, 0.12, 0), (PI / 2, 0, 0), r=0.024, tube=0.009),
    nd('cylinder', 'p01', (0, 0.215, 0), r=0.058, h=0.032),
    nd('cylinder', M, (0, 0.34, 0), r=0.064, rTop=0.074, h=0.22),
    nd('torus', A, (0, 0.28, 0), (PI / 2, 0, 0), r=0.07, tube=0.012),
    nd('cylinder', 'p01', (0, 0.485, 0), r=0.074, rTop=0.1, h=0.07),
    nd('torus', A, (0, 0.52, 0), (PI / 2, 0, 0), r=0.1, tube=0.012),
    nd('sphere', 'p02', (0, 0.575, 0), r=0.082),
    nd('sphere', 'p01', (-0.03, 0.598, 0.072), r=0.012), nd('sphere', 'p01', (0.03, 0.598, 0.072), r=0.012), nd('sphere', 'p01', (0, 0.562, 0.079), r=0.012),
    nd('tube', 'p01', points=[[0, 0.654, 0], [0.02, 0.69, 0], [0.05, 0.7, 0]], r=0.007), nd('sphere', 'p15', (0.058, 0.704, 0), r=0.017)]),
 'fish': ('Trout', {M: 'p09', A: 'p10'}, [
    nd('cylinder', 'p03', (0, 0.06, 0), r=0.017, h=0.22),
    nd('sphere', M, (0, 0.3, 0), scale=[0.6, 1.5, 0.45], r=0.075), nd('cone', A, (0, 0.425, 0), (PI, 0, 0), r=0.05, h=0.09),
    nd('sphere', 'p04', (0.02, 0.34, 0.034), r=0.014), nd('sphere', 'p01', (0.024, 0.34, 0.044), r=0.007)]),
}
kit['bases']['weapon'] = finalize('weapon', weapon)

# ------------------------------------------------------------------ trinket (emblem on the hip, front +z): bigger, about 0.1 tile across
trinket = {
 # Dodge roll: a rolled-up sleeping mat seen end-on with a blue spiral and two straps, and a yellow roll arrow curling round it
 'roll': ('Dodge roll', {M: 'p05', A: 'p10'}, [
    nd('cylinder', M, (0, 0, 0.05), (PI / 2, 0, 0), r=0.068, h=0.1),
    nd('tube', A, points=[[(0.056 - 0.0065 * i) * math.cos(0.95 * i), (0.056 - 0.0065 * i) * math.sin(0.95 * i), 0.103] for i in range(8)], r=0.0095),
    nd('torus', 'p03', (0, 0, 0.026), r=0.07, tube=0.008), nd('torus', 'p03', (0, 0, 0.074), r=0.07, tube=0.008),
    nd('torus', 'p12', (0, 0, 0.05), r=0.098, tube=0.0085, arc=2.5, arcStart=0.45),
    nd('cone', 'p12', (0.098 * math.cos(2.95) + 0.0, 0.098 * math.sin(2.95), 0.05), (0, 0, 2.95 + PI / 2 + 0.2), r=0.021, h=0.045)]),
 # Pocket laser: a blue pen torch tilted on the hip, a pocket clip, a click button, a dark lens ring, a lit tip and a short red beam
 'pen': ('Pocket laser', {M: 'p10', A: 'p12'}, [
    nd('cylinder', M, along(0.7, 0.0, z=0.03), (0, 0, -0.7), r=0.026, h=0.15),
    nd('sphere', M, along(0.7, -0.075, z=0.03), r=0.026),
    nd('cylinder', A, along(0.7, -0.035, z=0.03), (0, 0, -0.7), r=0.028, h=0.022),
    nd('cylinder', 'p01', along(0.7, 0.088, z=0.03), (0, 0, -0.7), r=0.034, rTop=0.026, h=0.04),
    nd('sphere', 'p04', along(0.7, 0.11, z=0.03), r=0.022),
    nd('sphere', 'p15', along(0.7, 0.122, z=0.03), r=0.013),
    nd('tube', 'p15', points=[along(0.7, 0.13, z=0.03), along(0.7, 0.19, z=0.03)], r=0.007),
    nd('plate', A, along(0.7, 0.01, lateral=-0.031, z=0.03), (0, 0, -0.7), w=0.012, h=0.1, t=0.012, radius=0.005),
    nd('sphere', A, along(0.7, -0.045, lateral=-0.033, z=0.03), r=0.011),
    nd('sphere', 'p04', along(0.7, -0.062, z=0.056), r=0.012)]),
 # Static sock: a blue sock with white cuff and toe stripes, kicking out two yellow sparks
 'bolt': ('Static sock', {M: 'p10', A: 'p12'}, [
    nd('cylinder', M, (-0.01, 0.045, 0.03), r=0.04, h=0.1),
    nd('cylinder', 'p04', (-0.01, 0.1, 0.03), r=0.046, h=0.024),
    nd('cylinder', M, (0.025, -0.022, 0.03), (0, 0, PI / 2), r=0.04, h=0.09),
    nd('sphere', M, (-0.018, -0.012, 0.03), r=0.044), nd('sphere', 'p04', (0.07, -0.022, 0.03), r=0.04),
    nd('cylinder', 'p04', (-0.01, 0.055, 0.03), r=0.0415, h=0.014),
    nd('tube', A, points=[[0.07, 0.07, 0.04], [0.05, 0.05, 0.04], [0.08, 0.04, 0.04], [0.06, 0.012, 0.04]], r=0.0085),
    nd('tube', A, points=[[-0.075, 0.08, 0.04], [-0.06, 0.055, 0.04], [-0.085, 0.045, 0.04]], r=0.0075)]),
 # Thump shell: a flat spiral shell on its tier plate, a cream rim, a coral spiral of 1.5 turns, a spire tip, three sound arcs thumping off its upper left
 'shell': ('Thump shell', {M: 'p14', A: 'p15'}, [
    nd('sphere', M, (0.012, -0.004, 0.026), scale=[1, 1, 0.55], r=0.062),
    nd('torus', 'p04', (0.012, -0.004, 0.044), r=0.058, tube=0.0085),
    nd('tube', A, points=[[0.012 + 0.05 * math.cos(t), -0.004 + 0.05 * math.sin(t), 0.062] for t in []] or [[0.012 + (0.046 - 0.0036 * i) * math.cos(0.9 * i), -0.004 + (0.046 - 0.0036 * i) * math.sin(0.9 * i), 0.064] for i in range(8)], r=0.0095),
    nd('cone', M, (0.062, 0.04, 0.026), (0, 0, -0.9), r=0.033, h=0.07),
    nd('torus', 'p12', (-0.03, 0.045, 0.026), (0, 0, 0), r=0.088, tube=0.0085, arc=1.0, arcStart=2.1),
    nd('torus', 'p12', (-0.03, 0.045, 0.026), (0, 0, 0), r=0.11, tube=0.0085, arc=0.85, arcStart=2.18),
    nd('torus', 'p12', (-0.03, 0.045, 0.026), (0, 0, 0), r=0.132, tube=0.0085, arc=0.7, arcStart=2.26)]),
 # Smoke bomb: a black bomb with a grey cap and a lit fuse, puffing a cloud of cream and grey smoke
 'bomb': ('Smoke bomb', {M: 'p01', A: 'p15'}, [
    nd('sphere', M, (-0.015, -0.012, 0.03), r=0.058),
    nd('cylinder', 'p06', (-0.015, 0.044, 0.03), r=0.022, h=0.022),
    nd('tube', 'p03', points=[[-0.015, 0.056, 0.03], [0.0, 0.082, 0.03], [0.022, 0.092, 0.03]], r=0.007),
    nd('sphere', A, (0.03, 0.098, 0.03), r=0.017),
    nd('sphere', 'p04', (0.01, 0.13, 0.026), r=0.034), nd('sphere', 'p05', (0.05, 0.145, 0.022), r=0.03), nd('sphere', 'p06', (-0.025, 0.155, 0.02), r=0.026),
    nd('sphere', 'p04', (0.03, 0.18, 0.016), r=0.022), nd('sphere', 'p04', (-0.03, -0.01, 0.075), r=0.012)]),
 # Horseshoe magnet: a fat red U with silver tips and a little spark
 'magnet': ('Magnet', {M: 'p15', A: 'p06'}, [
    nd('tube', M, points=[[-0.045, 0.045, 0.03], [-0.047, -0.005, 0.03], [-0.025, -0.05, 0.03], [0.025, -0.05, 0.03], [0.047, -0.005, 0.03], [0.045, 0.045, 0.03]], r=0.02),
    nd('cylinder', A, (-0.045, 0.062, 0.03), r=0.024, h=0.04), nd('cylinder', A, (0.045, 0.062, 0.03), r=0.024, h=0.04),
    nd('tube', 'p12', points=[[-0.015, 0.1, 0.03], [0.0, 0.082, 0.03], [0.012, 0.1, 0.03]], r=0.006)]),
 # Fridge magnet: a red horseshoe magnet with silver tips pinning a cream paper note with two scribbled lines and a gold star
 'fridge': ('Fridge magnet', {M: 'p15', A: 'p06'}, [
    nd('plate', 'p04', (0.0, 0.0, 0.03), (0, 0, 0.1), w=0.115, h=0.13, t=0.012, radius=0.008),
    nd('box', 'p03', (-0.005, -0.03, 0.04), (0, 0, 0.1), w=0.07, h=0.008, d=0.004), nd('box', 'p03', (-0.002, -0.048, 0.04), (0, 0, 0.1), w=0.05, h=0.008, d=0.004),
    nd('tube', M, points=[[-0.032, 0.02, 0.05], [-0.034, 0.0, 0.05], [-0.02, -0.02, 0.05], [0.02, -0.02, 0.05], [0.034, 0.0, 0.05], [0.032, 0.02, 0.05]], r=0.0155),
    nd('cylinder', A, (-0.032, 0.036, 0.05), r=0.0185, h=0.032), nd('cylinder', A, (0.032, 0.036, 0.05), r=0.0185, h=0.032),
    nd('sphere', 'p13', (0.0, 0.05, 0.044), scale=[1, 1, 0.4], r=0.012)]),
 # Bubble wand: a blue loop on a gold handle blowing three round bubbles with shines
 'ring': ('Bubble wand', {M: 'p10', A: 'p12'}, [
    nd('torus', M, (-0.01, 0.03, 0.03), r=0.05, tube=0.012),
    nd('cylinder', A, (-0.04, -0.05, 0.03), (0, 0, -0.55), r=0.014, h=0.1),
    nd('sphere', 'p09', (0.07, 0.11, 0.03), r=0.034), nd('sphere', 'p09', (0.1, 0.045, 0.03), r=0.022), nd('sphere', 'p09', (0.0, 0.12, 0.03), r=0.017),
    nd('sphere', 'p04', (0.06, 0.12, 0.062), r=0.01), nd('sphere', 'p04', (0.094, 0.052, 0.049), r=0.006)]),
 # Coins: a stack of four gold coins and a bigger coin leaning on it with a rim and a bright S mark, two sparkles
 'coins': ('Coins', {M: 'p12', A: 'p13'}, [
    *[nd('cylinder', M if i % 2 == 0 else A, (-0.025, -0.045 + i * 0.016, 0.03), r=0.04, h=0.016) for i in range(4)],
    nd('cylinder', M, (0.03, 0.01, 0.04), (PI / 2, 0, 0), r=0.052, h=0.014),
    nd('torus', A, (0.03, 0.01, 0.049), r=0.052, tube=0.007),
    nd('tube', 'p13', points=[[0.045, 0.03, 0.058], [0.018, 0.028, 0.058], [0.04, 0.0, 0.058], [0.016, -0.012, 0.058]], r=0.0065),
    nd('box', 'p04', (0.075, 0.07, 0.04), w=0.018, h=0.004, d=0.004), nd('box', 'p04', (0.075, 0.07, 0.04), w=0.004, h=0.018, d=0.004),
    nd('box', 'p04', (-0.06, 0.07, 0.04), w=0.012, h=0.003, d=0.003), nd('box', 'p04', (-0.06, 0.07, 0.04), w=0.003, h=0.012, d=0.003)]),
}
kit['bases']['trinket'] = finalize('trinket', trinket)

# ------------------------------------------------------------------ the default menu: 24 rows (4 starters + 20 commons) over the bases
LORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lore', 'kits.json')
def row(rid, slot, base, main, accent=None):
    cols = {'main': main}
    if accent: cols['accent'] = accent
    kit['menu'].append({'row': rid, 'kit': slot + '/' + base, 'colors': cols})
    SPECS[rid] = (slot, base, cols)
for r in [
    ('st-cap', 'head', 'cap', 'p14', 'p15'), ('c-head-maxi', 'head', 'bucket', 'p09', 'p10'), ('c-head-degen', 'head', 'cone', 'p11', 'p12'),
    ('c-head-speedrunner', 'head', 'sweatband', 'p15', 'p04'), ('c-head-builder', 'head', 'hardhat', 'p12', 'p13'),
    ('st-tee', 'body', 'tee', 'p05', 'p09'), ('c-body-maxi', 'body', 'vest', 'p14', 'p04'), ('c-body-degen', 'body', 'hawaiian', 'p08', 'p14'),
    ('c-body-speedrunner', 'body', 'wetsuit', 'p01', 'p09'), ('c-body-builder', 'body', 'overalls', 'p10', 'p12'),
    ('st-bonk', 'weapon', 'club', 'p02', 'p03'), ('c-swing', 'weapon', 'oar', 'p05', 'p10'), ('c-shot', 'weapon', 'sling', 'p03', 'p14'),
    ('c-beam', 'weapon', 'fish', 'p09', 'p10'), ('c-lob', 'weapon', 'mortar', 'p03', 'p12'), ('c-zap', 'weapon', 'jelly', 'p11', 'p12'), ('c-lunge', 'weapon', 'spear', 'p05', 'p10'),
    ('st-roll', 'trinket', 'roll', 'p05', 'p10'), ('c-beam-sweep', 'trinket', 'pen', 'p10', 'p12'), ('c-chain-storm', 'trinket', 'bolt', 'p10', 'p12'),
    ('c-shockwave', 'trinket', 'shell', 'p14', 'p15'), ('c-blink-strike', 'trinket', 'bomb', 'p01', 'p15'), ('c-magnet', 'trinket', 'fridge', 'p15', 'p06'),
    ('c-bubble', 'trinket', 'ring', 'p10', 'p12')]:
    row(*r)


def item_spec(rid, rows):
    """A kit-built item: the lore row's name and stats, the base it names, and the colours the menu gives it."""
    it = rows[rid]; slot, base, cols = SPECS[rid]
    spec = {'spec': 'trenchie-item/3', 'id': rid, 'name': it['name'], 'slot': slot, 'tier': it['tier'], 'stats': it['stats']}
    if slot == 'weapon': spec['move'] = it['weapon']
    if slot == 'trinket': spec['sig'] = it['signature']
    if it.get('setTag') and slot != 'trinket': spec['tag'] = it['setTag']
    spec['kit'] = slot + '/' + base
    spec['colors'] = cols     # the recolour: palette ids for the base's roles (an addition to the item format, see the kit board notes)
    return spec


if __name__ == '__main__':
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, 'kit.json'), 'w') as f:
        json.dump(kit, f, indent=1); f.write('\n')
    rows = {r['id']: r for r in json.load(open(LORE))['items']}
    os.makedirs(os.path.join(here, 'specs'), exist_ok=True)
    for rid in SPECS:
        with open(os.path.join(here, 'specs', rid + '.json'), 'w') as f:
            json.dump(item_spec(rid, rows), f, indent=1); f.write('\n')
    nb = sum(len(v) for v in kit['bases'].values()); nn = sum(len(b['nodes']) for v in kit['bases'].values() for b in v.values())
    print('kit.json: %d bases, %d nodes; %d menu rows; specs/: %d' % (nb, nn, len(kit['menu']), len(SPECS)))
