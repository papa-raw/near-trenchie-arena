"""Public tick-local battle events for an authenticated fighter's live session."""
import time


class BattleEvents:
    def __init__(self):
        self.tick = None
        self.life = None
        self.alive = False
        self.low = set()
        self.near = set()
        self.speech_ready = False

    def read(self, arena, who, *, allies=(), feed=None, feed_tick=None):
        state, rules = arena.sim.state, arena.sim.rules
        tick = state['tick']
        if self.tick == tick:
            return []
        self.tick = tick
        fighter = state['fighters'].get(who)
        if fighter is None:
            return []
        alive = fighter['state'] == 'alive'
        life = arena.members.get(who, {}).get('life_id')
        events = []
        if alive and (not self.alive or life != self.life):
            events.append(dict(kind='life_start', life_id=life, hp=fighter['hp'], max_hp=fighter['max_hp']))
        if not alive and self.alive:
            events.append(dict(kind='life_end', life_id=self.life, reason='ko' if fighter['state'] == 'ko' else fighter['state']))
        self.life, self.alive = life, alive
        events.extend(self._actions(state['events'], who, rules))
        events.extend(self._low_health(state['fighters'], who, allies))
        if alive:
            events.extend(self._loot(state['drops'], fighter, rules))
            ready = feed is not None and (who not in feed.last_tick or feed_tick - feed.last_tick[who] >= feed.rate)
            if ready and not self.speech_ready:
                events.append(dict(kind='speech_ready', summary='You may send one guarded line now.'))
            self.speech_ready = ready
        else:
            self.near.clear()
        emitted_at_ms = time.time_ns() // 1000000
        return [dict(event, tick=tick, emitted_at_ms=emitted_at_ms) for event in events]

    @staticmethod
    def _actions(actions, who, rules):
        rows = []
        for event in actions:
            kind = event['kind']
            if kind == 'hit' and who in (event.get('source'), event.get('target')):
                rows.append(dict(kind='hit', source=event.get('source'), target=event.get('target'), damage=event['damage']))
            elif kind == 'ko' and who in (event.get('source'), event.get('fighter')):
                rows.append(dict(kind='ko', source=event.get('source'), target=event.get('fighter')))
            elif kind in ('attack', 'signature', 'grab') and event.get('fighter') == who:
                rows.append(dict(kind={'signature': 'signature', 'attack': 'attack', 'grab': 'loot_taken'}[kind],
                                 fighter_id=who, item_id=event.get('row')))
            elif kind in ('behaviour', 'reflex', 'intent_refused') and event.get('fighter') == who:
                row = dict(kind=kind, fighter_id=who)
                if kind == 'reflex':
                    row.update(index=event['index'], on=event['on'])
                if kind == 'intent_refused':
                    ms = rules['intent_interval'] * rules.get('milliseconds_per_second', 1000) // rules['tick_hz']   # integer-1/-2 predate the key
                    row['fix'] = f'Wait until the {ms / 1000:g} s order window opens, then send a new order.'
                rows.append(row)
        return rows

    def _low_health(self, fighters, who, allies):
        current, rows = set(), []
        for name in (who, *allies):
            fighter = fighters.get(name)
            if fighter is None or fighter['state'] != 'alive' or fighter['hp'] * 4 > fighter['max_hp']:
                continue
            current.add(name)
            if name not in self.low:
                rows.append(dict(kind='low_hp' if name == who else 'ally_low', fighter_id=name,
                                 hp=fighter['hp'], max_hp=fighter['max_hp']))
        self.low = current
        return rows

    def _loot(self, drops, fighter, rules):
        current, rows = set(), []
        for serial, drop in drops.items():
            dx, dy = drop['x'] - fighter['x'], drop['y'] - fighter['y']
            if dx * dx + dy * dy > rules['view_radius'] ** 2:
                continue
            current.add(serial)
            if serial not in self.near:
                rows.append(dict(kind='loot_near', serial_id=serial, item_id=drop['row'],
                                 x=drop['x'], y=drop['y']))
        self.near = current
        return rows
