"""Regression cases for missing name guard, speech feedback and the documented local door."""
from __future__ import annotations
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
REVIEW_ROOT = Path(os.environ.get('SNAP_REVIEW_ROOT', HERE.parents[1]))
sys.path[:0] = [str(REVIEW_ROOT / 'near/arena'), str(REVIEW_ROOT)]
import snap
import dev_persona
import snap_local
from test_agent_door import creator_sheet


class AgentReview(unittest.TestCase):
    def test_missing_name_list_is_explicitly_labelled_in_the_public_persona(self) -> None:
        with patch.object(dev_persona, 'load_blocklist', return_value=None):
            public = dev_persona.check_sheet(creator_sheet())
        self.assertIn('guard list missing', public.get('nameNotice', ''))
        self.assertIn('name unchecked', public['nameNotice'])
        self.assertFalse(public['nameChecked'])
        with tempfile.TemporaryDirectory() as directory, patch.object(dev_persona, 'load_blocklist', return_value=None):
            dev = snap_local.DevRoom(8765, directory)
            key = snap.Ed25519PrivateKey.generate()
            public_key = snap.encoded(key.public_key().public_bytes(snap.serialization.Encoding.Raw, snap.serialization.PublicFormat.Raw))
            identity = dev.create_identity('pebble', 'hunter', public_key, sheet=creator_sheet())
            self.assertFalse(identity['name_checked'])
            self.assertIn('name unchecked', identity['name_notice'])
            self.assertIn('guard list missing', dev.identities[identity['nft_token_id']]['persona']['nameNotice'])
            profile = dev.profile(dict(account_id=identity['account_id'], nft_token_id=identity['nft_token_id']))
            self.assertIn('name unchecked', profile['public_name'])

    def test_human_intent_output_reports_speech_refusal_blocking_and_muting_with_fixes(self) -> None:
        for speech, required in (
            (dict(refused='rate_limited', retry_after_s=17), ('speech refused', '17', 'wait')),
            (dict(blocked=True, muted=False, text='(o_o)', label=None), ('speech blocked', '(o_o)', 'change')),
            (dict(blocked=False, muted=True, text='(._.)', label='guard list missing'), ('speech muted', 'guard list missing', 'operator')),
        ):
            with self.subTest(speech=speech):
                answer = dict(state='accepted', applied_tick='9', focus=None, loot='nearest', sig='auto', leave=False, speech=speech)
                output = io.StringIO()
                with patch.object(snap, 'keeper_call', return_value=answer), contextlib.redirect_stdout(output):
                    snap.main(['intent', '--say', 'A calm shore.'])
                human = '\n'.join(output.getvalue().splitlines()[1:]).lower()
                for text in required:
                    self.assertIn(text, human)

    def test_documented_same_origin_server_pairs_a_real_signed_agent_and_reads_corner(self) -> None:
        doc = (REVIEW_ROOT / 'near/SNAP.md').read_text()
        self.assertIn('python3 -B near/web/snapin/serve.py --port 8181', doc)
        path = REVIEW_ROOT / 'near/web/snapin/serve.py'
        self.assertTrue(path.is_file(), 'documented local server ships beside SNAP.md')
        spec = importlib.util.spec_from_file_location('snap_review_serve', path)
        serve = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(serve)
        self.assertTrue(serve.passes('GET', '/dev/corner'))
        with tempfile.TemporaryDirectory() as directory:
            dev = snap_local.DevRoom(8765, directory)
            Handler = serve.make_handler('http://127.0.0.1:8765', [8181])
            class Connection:
                def __init__(self, *args, **kwargs): pass
                def request(self, method, target, body=None, headers=None):
                    self.status, self.value = dev.route(method, target, body or b'', '127.0.0.1')
                def getresponse(self): return self
                def read(self): return json.dumps(self.value).encode()
                def getheader(self, name, default=None):
                    return {'content-type':'application/json', 'x-dev-now':str(dev.round.vnow()), 'x-dev-paused':'1'}.get(name.lower(), default)
                def close(self): pass
            def same_origin(url, method='GET', body=None, headers=None, timeout=60, seen=None):
                target = urlsplit(url)
                raw = json.dumps(body).encode() if isinstance(body, dict) else body or b''
                handler = Handler.__new__(Handler)
                handler.path = target.path + ('?' + target.query if target.query else '')
                handler.headers = {'Host':'127.0.0.1:8181', 'Content-Length':str(len(raw)), 'Content-Type':'application/json'}
                handler.rfile = io.BytesIO(raw)
                answers = []
                handler.reply = lambda status, data, *args, **kwargs: answers.append((status, data))
                with patch.object(serve.http.client, 'HTTPConnection', Connection):
                    (handler.do_POST if method == 'POST' else handler.do_GET)()
                status, data = answers[0]
                self.assertEqual(status, 200, data)
                if seen is not None:
                    seen.update(now=dev.round.vnow(), at=0, paused=True)
                return json.loads(data)
            issued = same_origin('http://127.0.0.1:8181/snap/code', 'POST', dict(agent='codex', name='Pebble Skipper', sheet=creator_sheet()))
            with patch.object(snap, 'call', side_effect=same_origin):
                keeper = snap.Keeper(types.SimpleNamespace(url='http://127.0.0.1:8181', name='unused', preset='hunter', spread='40,30,20,10', zero=10, code=issued['code']))
                keeper.start('1')
            paired = same_origin('http://127.0.0.1:8181/snap/code/' + issued['code'])
            self.assertTrue(paired['joined'])
            self.assertEqual(paired['fighter_id'], keeper.token)
            self.assertEqual(same_origin('http://127.0.0.1:8181/dev/corner?fighter=' + keeper.token)['fighter_id'], keeper.token)


if __name__ == '__main__': unittest.main()
