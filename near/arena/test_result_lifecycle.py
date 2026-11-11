"""Deterministic result projection cases for cancelled lifecycle inputs."""
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[2])]
import snap
import snap_local
import portable_records as port
from room.ledger import Refusal, canonical
from engine_evidence import replay_evidence


@contextmanager
def pending_join() -> Iterator[tuple[snap_local.DevRoom, snap.Keeper]]:
    """Real DEV routes and signing, starting at tick zero without a socket."""
    with tempfile.TemporaryDirectory() as directory, patch.object(snap_local.secrets,'randbelow',return_value=1):
        dev=snap_local.DevRoom(8765,directory)
        def call(url: str, method: str = 'GET', body: dict | bytes | None = None,
                 headers: dict | None = None, timeout: int = 60, seen: dict | None = None) -> dict:
            parsed=urlsplit(url)
            target=parsed.path+('?' + parsed.query if parsed.query else '')
            raw=json.dumps(body).encode() if isinstance(body,dict) else body or b''
            status,value=dev.route(method,target,raw,'127.0.0.1')
            if status!=200:raise ValueError('fixture HTTP '+str(status))
            if seen is not None:seen.update(now=dev.round.vnow(),at=0,paused=True)
            return value
        args=types.SimpleNamespace(url='http://127.0.0.1:8765',name='tideturn',preset='hunter',spread='40,30,20,10',zero=10)
        with patch.object(snap,'call',side_effect=call):
            keeper=snap.Keeper(args)
            first=keeper.start('1')
            assert first['state']=='accepted'
            yield dev,keeper


class ResultLifecycle(unittest.TestCase):
    def test_ko_while_leaving_cancels_next_spawn_without_refusing_result(self) -> None:
        with pending_join() as (dev,keeper):
            arena=dev.round.arena
            arena.advance(12)
            # Existing house fighters keep their own autonomous combat, with a
            # legal focus order that makes this a reproducible exit under fire.
            arena.house_runtime=None
            for name,member in list(arena.members.items()):
                if not member['profile']['house']:continue
                arena.bridge.apply(member['binding'],dict(kind='intent',sequence='10000',life_id=member['life_id'],
                    payload=dict(fighter_id=name,focus=keeper.token,avoid=None,loot='ignore',sig='auto',leave=False,say=None)))
            sent=False
            for _ in range(1000):
                fighter=arena.sim.state['fighters'].get(keeper.token)
                if fighter is None:break
                if not sent and fighter['state']=='alive' and fighter['hp']<=60:
                    receipt=keeper.client.control('intent',dict(fighter_id=keeper.token,focus=None,avoid=None,
                        loot='ignore',sig='hold',leave=True,say=None),life_id=keeper.life_id)
                    sent=receipt['state']=='accepted'
                arena.advance()
                ko=any(event['kind']=='ko' and event.get('fighter')==keeper.token for event in arena.sim.state['events'])
                if sent and ko and arena.sim.state['fighters'][keeper.token]['leave']:
                    keeper.tick()  # file the next-life pick before the next scheduling tick retires the body
                    break
                keeper.tick()
            else:self.fail('the deterministic exit did not encounter a KO')
            self.assertTrue(sent)
            self.assertTrue(ko,'the player must be KOed while leaving, not finish a normal swim home')
            while arena.sim.state['tick']<1201:
                arena.advance()
                if arena.sim.state['tick']%20==0:keeper.tick()
            native=arena.store.segment('segment:0')
            evidence=replay_evidence(native)
            original = canonical(native)
            omitted = port._check_commands(native, evidence['input_lives'])
            self.assertEqual(len(omitted), 1, 'exactly one next-life spawn was cancelled')
            announcement = native['sealed']['input_events'][next(iter(omitted))]
            self.assertEqual(announcement['kind'], 'life_start')
            self.assertEqual(announcement['fighter_id'], keeper.token)
            projected = port._events(native, omitted)
            self.assertFalse(any(row['kind'] == 'life_start' and row['life_id'] == announcement['life_id']
                                 for row in projected))
            self.assertTrue(any(row['kind'] == 'prediction_lock' and row['life_id'] == announcement['life_id']
                                for row in projected), 'the cancelled life keeps its immutable forecast')
            self.assertEqual(evidence['final_state_hash'], native['sealed']['final_state_hash'])
            self.assertTrue(keeper.client.result('segment:0')['completed'])
            self.assertEqual(canonical(arena.store.segment('segment:0')), original)

            # Cancellation is a narrow exception: neither an absent proof nor
            # a changed announced life can use it to obtain a signed result.
            absent = deepcopy(native)
            absent['commands'] = [row for row in absent['commands'] if row['kind'] not in ('retire', 'cancel_spawn')]
            with self.assertRaises(Refusal):
                port._check_commands(absent, evidence['input_lives'])
            wrong_life = deepcopy(native)
            wrong_life['sealed']['input_events'][next(iter(omitted))]['life_id'] = 'different-life'
            with self.assertRaises(Refusal):
                port._check_commands(wrong_life, evidence['input_lives'])
            duplicate = deepcopy(native)
            command = next(row for row in duplicate['commands'] if row['kind'] == 'input'
                           and row['value']['kind'] == 'spawn'
                           and row['value']['payload']['life_id'] == announcement['life_id'])
            duplicate['commands'].insert(duplicate['commands'].index(command), deepcopy(command))
            with self.assertRaises(Refusal):
                port._check_commands(duplicate, evidence['input_lives'])


if __name__=='__main__':unittest.main()
