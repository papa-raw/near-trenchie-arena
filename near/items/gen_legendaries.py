"""gen_legendaries.py — the 14 named legendaries (F39) as free-drawn items in the renderer-neutral format.

Run: python3 -I near/items/gen_legendaries.py   (writes the leg-*.json files into the items' spec folder; deterministic)
Each is drawn on the trinket's emblem space (front +z, centred, about 0.1 tile across; the renderer adds the gold tier plate),
authored in tiles like the kit and converted to item units by the kit generator's own converter. Names, ids, stats and signatures
come from near/lore/kits.json, so the art follows the rows.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python -I leaves the script's folder off sys.path
import gen_kit as G  # noqa: E402

PI = math.pi
nd = G.nd
Z = 0.02    # emblems sit this far in front of the plate
SIZE = 1.7   # drawn at 0.1 tile, grown to the kit's hip-badge size (about 0.17 tile) so it reads at game size


def coin(x, y, z, col, r=0.02, h=0.007, rot=0.0):
    return nd('cylinder', col, (x, y, z), (PI / 2, 0, rot), r=r, h=h)


def ring(x, y, z, col, r, tube, rot=(0, 0, 0)):
    return nd('torus', col, (x, y, z), rot, r=r, tube=tube)


def spiral(cx, cy, z, col, turns, r0, r1, n=8, w=0.006):
    pts = [[cx + math.cos(i * turns * 2 * PI / (n - 1)) * (r0 + (r1 - r0) * i / (n - 1)), cy + math.sin(i * turns * 2 * PI / (n - 1)) * (r0 + (r1 - r0) * i / (n - 1)), z] for i in range(n)]
    return nd('tube', col, points=pts, r=w)


L = {}
L['leg-stack-sats'] = [   # a grey hood over a stack of gold coins; it spirals open and sucks loot in
    *[nd('cylinder', 'p13' if i % 2 else 'p12', (0.0, -0.034 + i * 0.0085, Z + 0.006), r=0.024, h=0.0085) for i in range(5)],
    nd('hemisphere', 'p06', (0, 0.01, Z + 0.006), r=0.021, scale=[1, 1, 1]),
    nd('sphere', 'p05', (0.0, 0.034, Z + 0.006), r=0.005)]
L['leg-liquidity-wave'] = [   # a rolling blue wave with a foam curl, a banana-yellow surfboard riding out of it
    nd('tube', 'p10', points=[[-0.05, -0.012, Z + 0.004], [-0.03, 0.006, Z + 0.004], [-0.008, -0.01, Z + 0.004], [0.014, 0.01, Z + 0.004], [0.036, -0.008, Z + 0.004], [0.052, 0.006, Z + 0.004]], r=0.0095),
    nd('tube', 'p09', points=[[-0.05, -0.034, Z + 0.004], [-0.03, -0.018, Z + 0.004], [-0.008, -0.032, Z + 0.004], [0.014, -0.014, Z + 0.004], [0.036, -0.03, Z + 0.004], [0.052, -0.018, Z + 0.004]], r=0.008),
    nd('tube', 'p10', points=[[-0.05, -0.05, Z + 0.004], [-0.03, -0.038, Z + 0.004], [-0.008, -0.05, Z + 0.004], [0.014, -0.04, Z + 0.004], [0.036, -0.05, Z + 0.004], [0.052, -0.042, Z + 0.004]], r=0.007),
    nd('plate', 'p12', (0.0, 0.022, Z + 0.008), (0, 0, -0.4), w=0.034, h=0.085, t=0.008, radius=0.016),
    nd('plate', 'p10', (0.0, 0.022, Z + 0.013), (0, 0, -0.4), w=0.008, h=0.07, t=0.004, radius=0.003),
    *[nd('sphere', 'p04', (x, y, Z + 0.012), r=0.007) for x, y in ((-0.03, 0.01), (0.014, 0.016), (0.04, 0.0))]]
L['leg-tinker-coil'] = [   # a copper coil wound on a core, two metal terminals and a lilac arc of electricity leaping between them
    nd('cylinder', 'p01', (0, -0.006, Z + 0.004), (0, 0, PI / 2), r=0.01, h=0.074),
    *[nd('torus', 'p02' if i % 2 else 'p03', (x, -0.006, Z + 0.004), (0, PI / 2, 0), r=0.02, tube=0.0065) for i, x in enumerate((-0.026, -0.013, 0.0, 0.013, 0.026))],
    nd('sphere', 'p06', (-0.043, -0.006, Z + 0.004), r=0.011), nd('sphere', 'p06', (0.043, -0.006, Z + 0.004), r=0.011),
    nd('tube', 'p11', points=[[-0.043, 0.008, Z + 0.01], [-0.022, 0.03, Z + 0.01], [-0.004, 0.018, Z + 0.01], [0.018, 0.036, Z + 0.01], [0.043, 0.008, Z + 0.01]], r=0.0055),
    nd('sphere', 'p04', (0.0, 0.026, Z + 0.012), r=0.006)]
L['leg-laser-eyes'] = [   # two big glowing eyes firing red beams out to both sides
    nd('sphere', 'p04', (-0.022, 0.0, Z + 0.004), scale=[1.2, 0.9, 0.4], r=0.02), nd('sphere', 'p04', (0.022, 0.0, Z + 0.004), scale=[1.2, 0.9, 0.4], r=0.02),
    nd('sphere', 'p15', (-0.022, 0.0, Z + 0.01), scale=[1, 1, 0.5], r=0.0125), nd('sphere', 'p15', (0.022, 0.0, Z + 0.01), scale=[1, 1, 0.5], r=0.0125),
    nd('sphere', 'p01', (-0.022, 0.0, Z + 0.014), r=0.0055), nd('sphere', 'p01', (0.022, 0.0, Z + 0.014), r=0.0055),
    nd('plate', 'p15', (-0.05, -0.022, Z + 0.004), (0, 0, 0.55), w=0.036, h=0.009, t=0.005, radius=0.0035), nd('plate', 'p15', (0.05, -0.022, Z + 0.004), (0, 0, -0.55), w=0.036, h=0.009, t=0.005, radius=0.0035),
    nd('plate', 'p12', (-0.05, -0.022, Z + 0.008), (0, 0, 0.55), w=0.03, h=0.0035, t=0.004, radius=0.0015), nd('plate', 'p12', (0.05, -0.022, Z + 0.008), (0, 0, -0.55), w=0.03, h=0.0035, t=0.004, radius=0.0015),
    nd('plate', 'p03', (0, 0.026, Z + 0.004), w=0.07, h=0.007, t=0.005, radius=0.003)]
L['leg-ether-stack'] = [   # a tower of lilac ether coins that whirls into a spiral
    *[nd('cylinder', 'p11' if i % 2 else 'p10', (0.0, -0.034 + i * 0.0085, Z + 0.006), r=0.022 - i * 0.002, h=0.0085) for i in range(4)],
    nd('cone', 'p11', (0, 0.026, Z + 0.006), r=0.015, h=0.03), nd('cone', 'p09', (0, 0.0, Z + 0.006), (0, 0, PI), r=0.015, h=0.026)]
L['leg-fast-finality'] = [   # a green speed streak that ends in a stamped FINAL tick mark
    *[nd('plate', c, (x, y, Z + 0.002), (0, 0, 0.35), w=0.05 - i * 0.006, h=0.008, t=0.005, radius=0.003) for i, (c, x, y) in enumerate((('p08', -0.022, 0.018), ('p07', -0.028, 0.004), ('p08', -0.024, -0.01)))],
    coin(0.018, -0.002, Z + 0.004, 'p04', 0.026, 0.006),
    nd('tube', 'p08', points=[[0.004, -0.004, Z + 0.01], [0.014, -0.015, Z + 0.01], [0.034, 0.012, Z + 0.01]], r=0.004)]
L['leg-lifeboat'] = [   # a little wooden boat hull closes over her as a peach bubble
    nd('hemisphere', 'p03', (0, -0.012, Z + 0.004), (PI, 0, 0), r=0.026, scale=[1.4, 0.8, 0.8]),
    nd('box', 'p02', (0, -0.001, Z + 0.004), w=0.058, h=0.005, d=0.02), nd('cylinder', 'p05', (0, 0.02, Z + 0.004), r=0.003, h=0.04),
    nd('plate', 'p14', (0.012, 0.022, Z + 0.004), w=0.018, h=0.014, t=0.004, radius=0.004),
    ring(0, 0.0, Z + 0.002, 'p14', 0.044, 0.004, (PI / 2, 0, 0)), nd('sphere', 'p04', (-0.026, 0.026, Z + 0.012), r=0.005)]
L['leg-hydra-halo'] = [   # a halo of eight tiny heads, each firing a thin sky-blue beam
    ring(0, 0, Z, 'p12', 0.034, 0.004),
    *[nd('sphere', 'p04' if i % 2 else 'p09', (math.cos(i * PI / 4) * 0.034, math.sin(i * PI / 4) * 0.034, Z + 0.004), r=0.008) for i in range(8)],
    nd('sphere', 'p10', (0, 0, Z + 0.004), r=0.012)]
L['leg-loop-flywheel'] = [   # a flywheel on the back spins up and throws a grey ring outward
    ring(0, 0, Z, 'p06', 0.03, 0.008), ring(0, 0, Z - 0.004, 'p05', 0.044, 0.003),
    nd('cylinder', 'p05', (0, 0, Z + 0.004), (PI / 2, 0, 0), r=0.01, h=0.014),
    *[nd('box', 'p06', (0, 0, Z + 0.002), (0, 0, i * PI / 4), w=0.056, h=0.005, d=0.004) for i in range(4)]]
L['leg-priority-fee'] = [   # a mint toll gate; floor items queue through it, fastest first
    nd('box', 'p07', (-0.026, -0.004, Z + 0.004), w=0.01, h=0.06, d=0.01), nd('box', 'p07', (0.026, -0.004, Z + 0.004), w=0.01, h=0.06, d=0.01),
    nd('box', 'p08', (0, 0.03, Z + 0.004), w=0.062, h=0.01, d=0.012),
    coin(0.0, -0.012, Z + 0.002, 'p12', 0.012, 0.006), coin(-0.056 + 0.0, -0.012, Z, 'p13', 0.008, 0.005),
    nd('cone', 'p08', (0.01, -0.03, Z + 0.004), (0, 0, -PI / 2), r=0.008, h=0.016)]
L['leg-builder-census'] = [   # a clipboard that crackles; yellow tally marks jump from head to head
    nd('plate', 'p03', (0, 0, Z + 0.002), w=0.05, h=0.07, t=0.006, radius=0.006), nd('plate', 'p04', (0, -0.004, Z + 0.006), w=0.04, h=0.054, t=0.004, radius=0.003),
    nd('box', 'p06', (0, 0.036, Z + 0.008), w=0.02, h=0.008, d=0.008),
    *[nd('box', 'p12', (x, -0.004, Z + 0.01), w=0.004, h=0.024, d=0.003) for x in (-0.012, -0.004, 0.004, 0.012)],
    nd('box', 'p13', (0, -0.004, Z + 0.012), (0, 0, 1.0), w=0.004, h=0.034, d=0.003)]
L['leg-harvest-quake'] = [   # a pitchfork stamped into the dirt; a ring of sprouting crops bursts outward
    nd('box', 'p03', (0, -0.008, Z + 0.004), w=0.006, h=0.06, d=0.006), nd('box', 'p06', (0, 0.014, Z + 0.004), w=0.032, h=0.006, d=0.006),
    *[nd('cone', 'p06', (x, 0.03, Z + 0.004), r=0.004, h=0.02) for x in (-0.014, 0.0, 0.014)],
    *[nd('cone', 'p08', (math.cos(a) * 0.036, -0.034 + math.sin(a) * 0.01, Z + 0.004), (0, 0, (a - PI / 2) * 0.4), r=0.006, h=0.018) for a in (0.2, PI / 2 - 0.3, PI / 2 + 0.3, PI - 0.2)]]
L['leg-poker-face'] = [   # a fanned hand of cards closes into a shield; it pops like a table flip
    *[nd('plate', c, (i * 0.014, 0.0, Z + 0.003 + (i + 1) * 0.003), (0, 0, -i * 0.38), w=0.03, h=0.044, t=0.003, radius=0.004) for i, c in ((-1, 'p04'), (0, 'p14'), (1, 'p04'))],
    nd('sphere', 'p15', (0.0, 0.006, Z + 0.016), r=0.007), nd('box', 'p01', (0.0, -0.01, Z + 0.016), w=0.004, h=0.01, d=0.002)]
L['leg-router-drone'] = [   # a small blue drone with two coral rotors and a dark eye, circled by a dark orbit ring; reads on pale and dark bodies alike
    nd('sphere', 'p10', (0, -0.004, Z + 0.006), scale=[1.4, 0.8, 1], r=0.018), nd('sphere', 'p01', (0, -0.002, Z + 0.022), r=0.0075), nd('sphere', 'p04', (0.002, 0.0, Z + 0.027), r=0.0025),
    *[nd('cylinder', 'p15', (x, 0.018, Z + 0.006), r=0.013, h=0.004) for x in (-0.03, 0.03)],
    *[nd('box', 'p01', (x, 0.006, Z + 0.006), (0, 0, s * 0.5), w=0.02, h=0.004, d=0.004) for x, s in ((-0.016, 1), (0.016, -1))],
    ring(0, -0.004, Z, 'p01', 0.044, 0.0028, (PI / 2.6, 0, 0))]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    d = json.load(open(os.path.join(here, '..', 'lore', 'kits.json')))
    rows = {r['id']: r for r in d['items']}
    os.makedirs(os.path.join(here, 'specs'), exist_ok=True)
    out = 0
    for t in d['trenchies']:
        lid = t['legendary']['id']; r = rows[lid]
        nodes = [G.conv(n, {}, 0.11) for n in G.grow(L[lid], SIZE)]
        spec = {'spec': 'trenchie-item/3', 'id': lid, 'name': r['name'], 'slot': 'trinket', 'tier': 'legendary', 'stats': r['stats'], 'sig': r['signature'], 'nodes': nodes}
        with open(os.path.join(here, 'specs', lid + '.json'), 'w') as f:
            json.dump(spec, f, indent=1); f.write('\n')
        out += 1
    print('legendaries: %d specs, %d nodes' % (out, sum(len(v) for v in L.values())))


if __name__ == '__main__':
    main()
