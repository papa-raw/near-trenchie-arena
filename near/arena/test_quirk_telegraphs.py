"""Public danger geometry follows the bound cast, including legendary tradeoffs."""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server
import sim
import test_quirks as fixture


def observe_cast(game: sim.Sim) -> dict:
    """Exercise the real public projection without room authentication or I/O."""
    arena = SimpleNamespace(sim=game, members={}, context={}, segment_id="segment:0")
    view = server.ArenaBridge(arena).observe(None)
    return next(t for t in view["telegraphs"] if t["telegraph_id"] == "cast:a")


def contains(shape: dict, x: int, y: int, rules: dict) -> bool:
    dx, dy = x - shape["x_milli"], y - shape["y_milli"]
    radius = sim.isqrt(dx * dx + dy * dy)
    if radius > int(shape["radius_milli"]):
        return False
    if shape["shape"] != "cone":
        return True
    vx, vy = shape["direction_x_milli"], shape["direction_y_milli"]
    length = sim.isqrt(vx * vx + vy * vy)
    half_arc = int(shape["arc_millidegrees"]) // (2 * rules["tile"])
    cosine = sim.sin_deg(half_arc + rules["quarter_turn"], rules)
    return (dx * vx + dy * vy) * rules["trig_scale"] >= radius * length * cosine


class Telegraphs(unittest.TestCase):
    def shape(self, row: str, radius: int, arc: int, probe_radius: int,
              probe_angle: int = 0, shared_contains_probe: bool = False) -> None:
        game, f = fixture.arena(row)
        fixture.start(game, f)
        before_hash, before_tick = game.state_hash(), server.encode_snapshot(game)
        shape = observe_cast(game)
        self.assertEqual((int(shape["radius_milli"]), int(shape["arc_millidegrees"])), (radius, arc))
        bound = f["cast"]["parameters"]
        self.assertEqual(int(shape["radius_milli"]), bound["range"] * f["cast"]["sig_range_pct"] // 100)
        self.assertEqual(int(shape["arc_millidegrees"]), bound.get("half_arc", 0) * 2000)
        x, y = sim.vector(probe_angle, probe_radius, game.rules)
        x += shape["x_milli"]
        y += shape["y_milli"]
        self.assertTrue(contains(shape, x, y, game.rules))
        shared = dict(shape)
        base = game.rules["signatures"][f["cast"]["kind"]]
        shared.update(radius_milli=str(base["range"]), arc_millidegrees=str(base.get("half_arc", 0) * 2000))
        self.assertEqual(contains(shared, x, y, game.rules), shared_contains_probe)
        # The +1 radial point uses an axis so integer vector rounding cannot
        # accidentally move it back inside the boundary.
        self.assertFalse(contains(shape, shape["x_milli"] + radius + 1, shape["y_milli"], game.rules))
        if arc:
            x, y = sim.vector(arc // 2000 + 2, radius // 2, game.rules)
            self.assertFalse(contains(shape, shape["x_milli"] + x, shape["y_milli"] + y, game.rules))
        self.assertEqual(game.state_hash(), before_hash)
        self.assertEqual(server.encode_snapshot(game), before_tick)

    def test_laser_eyes_longer_narrower_cone(self) -> None:
        self.shape("leg-laser-eyes", 4950, 48000, 4800)

    def test_hydra_halo_shorter_wider_cone(self) -> None:
        self.shape("leg-hydra-halo", 4050, 72000, 3000, 33)

    def test_tinker_coil_longer_circle(self) -> None:
        self.shape("leg-tinker-coil", 4400, 0, 4200)

    def test_harvest_quake_longer_circle(self) -> None:
        self.shape("leg-harvest-quake", 3300, 0, 3200)

    def test_ether_stack_longer_circle(self) -> None:
        self.shape("leg-ether-stack", 4400, 0, 4200)

    def test_router_drone_shorter_circle(self) -> None:
        self.shape("leg-router-drone", 5400, 0, 5300, shared_contains_probe=True)
        game, f = fixture.arena("leg-router-drone")
        fixture.start(game, f)
        shape = observe_cast(game)
        x, y = shape["x_milli"] + 5700, shape["y_milli"]
        self.assertFalse(contains(shape, x, y, game.rules))
        shared = {**shape, "radius_milli": "6000"}
        self.assertTrue(contains(shared, x, y, game.rules))

    def test_range_stays_bound_after_live_stats_change(self) -> None:
        game, f = fixture.arena("leg-laser-eyes")
        f["sig_range_pct"] = 125
        fixture.start(game, f)
        f["sig_range_pct"] = 250
        shape = observe_cast(game)
        self.assertEqual((int(shape["radius_milli"]), int(shape["arc_millidegrees"])), (6187, 48000))

    def test_legacy_cast_uses_shared_parameters_and_live_range(self) -> None:
        game, f = fixture.arena("leg-laser-eyes")
        fixture.start(game, f)
        f["cast"].pop("parameters")
        f["cast"].pop("sig_range_pct")
        f["sig_range_pct"] = 125
        shape = observe_cast(game)
        self.assertEqual((int(shape["radius_milli"]), int(shape["arc_millidegrees"])), (5625, 60000))


class ShieldText(unittest.TestCase):
    def test_magnet_lines_describe_burst_size_and_loot_cadence(self) -> None:
        rules = fixture.table()
        expected = {
            "leg-priority-fee": "Pulls loot more often; each shield is smaller.",
            "leg-stack-sats": "Larger shield bursts, with longer waits between loot pulls."}
        for row, text in expected.items():
            with self.subTest(row=row):
                quirk = rules["item_quirks"][row]
                self.assertEqual(quirk["text"], text)
                values = quirk["overrides"]
                self.assertEqual(values["shield"] * 240, 30 * values["cooldown"])


if __name__ == "__main__":
    unittest.main()
