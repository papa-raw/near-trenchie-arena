"""House-only retargeting of the model's accepted plan; emits ordinary logged behaviour orders.

The engine, player orders and released tables are unchanged. A useful approach keeps its target.
"""
import copy
from dataclasses import dataclass
from math import isqrt
from typing import Callable

STALE_SECONDS = 6
MAX_PURSUIT_SECONDS = 10           # even a slowly closing chase must yield after ten seconds without an attack
PROGRESS_SECONDS = 2
PROGRESS_MILLI = 250                # a quarter tile of closing counts as useful pursuit
TARGET_MODES = ('auto', 'nearest', 'weakest', 'attacker')


def distance(a: dict, b: dict) -> int:
    return isqrt((a['x'] - b['x']) ** 2 + (a['y'] - b['y']) ** 2)


def target_mode(fighter: dict) -> str | None:
    """Read the same first-reflex-wins target override from the accepted plan and emitted reflex state."""
    plan = fighter['behaviour']
    mode = plan['target']
    for reflex, state in reversed(list(zip(plan['reflexes'], fighter['battle_reflexes']))):
        if state['on']:
            mode = reflex['then'].get('target', mode)
    return mode


def replace_target(plan: dict, old: str, new: str) -> dict:
    """Retarget the accepted plan and overrides which would otherwise immediately restore that pursuit."""
    out = copy.deepcopy(plan)
    out['target'] = new
    for reflex in out['reflexes']:
        then = reflex['then']
        if then.get('target') in (old, 'auto', 'weakest', 'attacker'):
            then['target'] = new
    return out


@dataclass
class Approach:
    life: str
    target: str
    since: int
    progress: int
    best: int


class Pursuits:
    """Bounded observations for the house roster; no model calls, hidden sim mutations or wall-clock deadlines."""
    def __init__(self) -> None:
        self.approaches: dict[str, Approach] = {}
        self.sent: dict[str, int] = {}
        self.tick = -1

    def prune(self, names: list[str], tick: int) -> None:
        if tick < self.tick:
            self.approaches.clear()
            self.sent.clear()
        keep = set(names)
        self.approaches = {n: a for n, a in self.approaches.items() if n in keep}
        self.sent = {n: t for n, t in self.sent.items() if n in keep}
        self.tick = tick

    def observe(self, name: str, state: dict, rules: dict,
                eligible: Callable[[dict, dict], bool]) -> tuple[dict, str] | None:
        f, tick = state['fighters'][name], state['tick']
        if f['state'] != 'alive' or not f.get('behaviour'):
            self.approaches.pop(name, None)
            return None
        mode = target_mode(f)
        old = f.get('target') or (mode if mode not in TARGET_MODES else None)
        if not old or tick - self.sent.get(name, -rules['tick_hz']) < rules['tick_hz']:
            return None
        target = state['fighters'].get(old)
        candidates = [g for g in state['fighters'].values()
                      if g['id'] not in (name, old) and g['state'] == 'alive' and eligible(f, g)]
        alternative = min(candidates, key=lambda g: (distance(f, g), g['id'])) if candidates else None
        if target is None or target['state'] != 'alive':
            return self._order(name, f, old, alternative, tick, 'target left the fight')
        dist = distance(f, target)
        approach = self._approach(f, old, dist, state, rules)
        if alternative is None:
            return None
        reach = rules['weapons'][rules['items'][f['equipped']['weapon']]['weapon']]['range'] * f['range_pct'] // rules['percent']
        reason = self._reason(tick, approach, dist, distance(f, alternative), reach, rules)
        return self._order(name, f, old, alternative, tick, reason) if reason else None

    def _approach(self, f: dict, old: str, dist: int, state: dict, rules: dict) -> Approach:
        name, tick = f['id'], state['tick']
        a = self.approaches.get(name)
        if a is None or (a.life, a.target) != (f['life_id'], old):
            a = Approach(f['life_id'], old, tick, tick, dist)
            self.approaches[name] = a
        if any(e['kind'] == 'attack' and e.get('fighter') == name for e in state['events']):
            a.since = tick
        if a.best - dist >= PROGRESS_MILLI:
            a.best, a.progress = dist, tick
        return a

    @staticmethod
    def _reason(tick: int, approach: Approach, dist: int, alternative: int, reach: int, rules: dict) -> str | None:
        if dist <= reach:
            return None
        if alternative <= reach:
            return 'target out of weapon reach; another opponent is reachable'
        if tick - approach.since >= MAX_PURSUIT_SECONDS * rules['tick_hz']:
            return 'pursuit lasted ten seconds without an attack; try another enemy'
        if alternative < dist and tick - approach.since >= STALE_SECONDS * rules['tick_hz'] and tick - approach.progress >= PROGRESS_SECONDS * rules['tick_hz']:
            return 'pursuit made no useful progress; another opponent is closer'
        return None

    def _order(self, name: str, fighter: dict, old: str, alternative: dict | None,
               tick: int, reason: str) -> tuple[dict, str]:
        self.sent[name] = tick
        self.approaches.pop(name, None)
        return replace_target(fighter['behaviour'], old, alternative['id'] if alternative else 'nearest'), reason
