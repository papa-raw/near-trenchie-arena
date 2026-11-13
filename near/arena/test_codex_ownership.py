"""Codex door bootstrap on the real hosted routes and signed room, with delayed chain reads; no network."""
import asyncio
import inspect
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena')]
import snap
import snap_local
from near.chain import hosted_live
from near.chain import test_identity_desk as fixtures


class CodexOwnership(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        block = Path(self.tmp.name) / 'block.json'
        block.write_text(json.dumps({'names': [], 'handles': [], 'slurs': []}))
        self.enterContext(patch.dict(os.environ, {'TRENCHIE_BLOCKLIST': str(block)}))
        self.saved = {k: getattr(snap_local, k) for k in ('make_contexts', 'player_token', 'DevRoom', 'MODE_NOTE')}
        arena_cls = snap_local.server.Arena
        health = snap_local.DevRoom.health
        self.addCleanup(lambda: [setattr(snap_local, k, v) for k, v in self.saved.items()])
        self.addCleanup(setattr, snap_local.server, 'Arena', arena_cls)
        self.addCleanup(setattr, self.saved['DevRoom'], 'health', health)
        self.sk, self.pk = fixtures.wallet_key()
        sheet = json.loads((fixtures.PREMINT_SHEET.parent / 'pike-pennywhistle.json').read_text())
        self.sheet = sheet
        nft = fixtures.premint_nft(('preset-2-00', 'preset-2'))
        self.nft = nft
        nft.tokens['preset-2-00']['digest'] = snap_local.sheet_digest(sheet)
        desk, *_ = fixtures.desk(nft, fixtures.inventory(), {fixtures.PLAYER: {self.pk}})
        desk.check_persona = None
        self.desk = desk

        class Chain:
            cfg = desk.s.chain
            inventory_ready = False
            owner_ready = False
            waits = 0
            def claim_seeds(self, arena): return [11, 12, 13, 14, 15]
            def take_seeds(self, arena): return []
            def sealed(self, *args): pass
            def owner_ok(self, binding): return self.owner_ready
            def life_ended(self, token): pass
            def health(self): return {}
            def inventory_bag(self, token, items):
                self.waits += 1
                return {} if self.inventory_ready else None
            def saved_bag_update(self, *args): return None
        self.chain = Chain()
        self.responses = []
        room_cls = hosted_live.install(desk.s, self.chain, desk)
        self.room = room_cls(18733, str(Path(self.tmp.name) / 'host'))
        self.addCleanup(self.room.pool.shutdown, wait=True)
        self.page = fixtures.Page(desk, self.sk, self.pk)
        self.page.do('claim', {'preset': 'hunter-lunge'})
        status, code = self.route('POST', '/snap/code', self.page.env('code', {
            'agent': 'codex', 'name': 'Pebble', 'preset': 'hunter-lunge', 'sheet': sheet, 'nft_token_id': 'preset-2-00'}))
        self.assertEqual(status, 200, code)
        self.code = code['code']
        self.enterContext(patch.object(snap, 'call', self.call))

    def route(self, method, target, body=None):
        body = body if isinstance(body, bytes) else json.dumps(body or {}).encode()
        out = self.room.route(method, target, body, '127.0.0.1')
        return asyncio.run(out) if inspect.isawaitable(out) else out

    def call(self, url, method='GET', data=None, headers=None, **kwargs):
        u = urlsplit(url)
        status, reply = self.route(method, u.path + ('?' + u.query if u.query else ''), data)
        if status != 200:
            raise SystemExit('snap: ' + str(reply.get('error', status)))
        if isinstance(reply, dict):
            self.responses.append((u.path, reply.get('code') or reply.get('state') or reply.get('type')))
        return reply

    def keeper(self):
        case = self
        class Transport:
            def __init__(self, base, token): self.base = base
            def now(self): return case.room.round.vnow()
            def request(self, method, target, body=b''): return case.call(self.base + target, method, body)
            def open_control(self, url): return case.call(self.base + '/room/control/open', 'POST')
            def frame(self, cid, body): return case.call(self.base + '/room/control/frame?cid=' + cid, 'POST', body)
            def drain_private(self, cid): return case.call(self.base + '/room/control/private?cid=' + cid)
            def close(self): pass
        return snap.Keeper(SimpleNamespace(url='http://127.0.0.1:18733', name='ignored', preset='hunter', code=self.code), transport_factory=Transport)

    def test_pending_reads_retry_and_an_unjoined_code_can_recover_without_weakening_ownership(self):
        abandoned = self.keeper()  # registration alone must not spend the code
        self.assertEqual(abandoned.token, 'preset-2-00')
        with patch.object(snap.time, 'sleep', side_effect=SystemExit('simulated process exit')):
            with self.assertRaisesRegex(SystemExit, 'simulated process exit'):
                abandoned.start('1')  # stop the real initial join after its first refused inventory read
        self.assertIn(('/room/join', 'ownership_unavailable'), self.responses)
        self.assertTrue(all(s['revoked'] for s in self.room.round.host.service._sessions.values()),
                        'the refused join leaves no live partial grant')
        retry = self.keeper()      # a fresh process/key can recover while no life was reserved
        self.assertNotEqual(abandoned.public_key, retry.public_key)
        self.assertEqual(self.room.codes[self.code]['chain']['token_id'], retry.token)
        waits = []
        def read_lands(seconds):
            waits.append(seconds)
            self.assertLessEqual(len(waits), 8, self.responses[-10:])
            self.room.round.base += int(seconds * 1000)  # exercise the real room rate window without wall-clock sleep
            self.chain.inventory_ready = True
        with patch.object(snap.time, 'sleep', read_lands):
            retry.start('1')       # first inventory read is still pending; the same session retries
        self.assertTrue(waits, 'the first pending inventory read was retried')
        self.assertGreaterEqual(self.chain.waits, 2)
        self.assertTrue(self.room.codes[self.code]['joined'])
        self.room.codes[self.code]['joined'] = False
        with self.assertRaisesRegex(ValueError, 'code already used'):
            self.room.code_status(self.code, claim=True)  # even before pairing, a seated fighter cannot be replaced
        self.room.codes[self.code]['joined'] = True
        self.assertEqual(self.room.round.arena.members[retry.token]['binding']['account_id'], fixtures.PLAYER)
        self.assertFalse(self.chain.owner_ready, 'no owner read was bypassed')
        self.assertNotIn(retry.token, self.room.round.arena.sim.state['fighters'])
        self.chain.owner_ready = True
        self.room.round.arena.advance(50)
        self.assertIn(retry.token, self.room.round.arena.sim.state['fighters'])
        with self.assertRaisesRegex(SystemExit, 'code already used'):
            self.keeper()
        # Changing the confirmed owner still refuses before a new identity can register.
        self.assertEqual(self.room.codes[self.code]['chain']['account_id'], fixtures.PLAYER)
        self.nft.tokens['preset-2-00']['owner'] = 'other-player.testnet'
        status, refused = self.route('POST', '/snap/code', self.page.env('code', {
            'agent': 'codex', 'preset': 'hunter-lunge', 'sheet': self.sheet, 'nft_token_id': 'preset-2-00'}))
        self.assertEqual(status, 400)
        self.assertIn('owned by', refused['error'])

        from client_bundle import CLIENT_FILES, build_client_bundle
        from near.web.snapin.serve import make_handler
        handler_cls = make_handler('http://127.0.0.1:18733', [0])
        handler = handler_cls.__new__(handler_cls)
        handler.path, handler.own_host = '/snap-client.zip', lambda: True
        answers = []
        handler.reply = lambda *args: answers.append(args)
        handler_cls.do_GET(handler)
        status, body, content_type, headers = answers[0]
        self.assertEqual((status, content_type, headers['Cache-Control']), (200, 'application/zip', 'no-store'))
        self.assertEqual(body, build_client_bundle(), 'the route serves the current source bundle')
        class Wire:
            def __init__(self): self.data = bytearray()
            def get_extra_info(self, key): return ('127.0.0.1', 12345)
            def write(self, data): self.data.extend(data)
            async def drain(self): pass
            def close(self): pass
        async def direct_download():
            reader, writer = asyncio.StreamReader(), Wire()
            reader.feed_data(b'GET /snap-client.zip HTTP/1.1\r\nHost: 127.0.0.1:18733\r\n\r\n')
            reader.feed_eof()
            await self.room.handle(reader, writer)
            return bytes(writer.data)
        wire = asyncio.run(direct_download())
        head, direct = wire.split(b'\r\n\r\n', 1)
        self.assertIn(b'HTTP/1.1 200', head)
        self.assertIn(b'Content-Type: application/zip', head)
        self.assertEqual(direct, body, 'direct and frontend hosts both serve the matching client')
        with ZipFile(BytesIO(body)) as archive:
            self.assertEqual(set(archive.namelist()), {'trenchie-client/' + name for name in CLIENT_FILES})
            self.assertEqual(archive.read('trenchie-client/near/arena/snap.py'), (ROOT / 'near/arena/snap.py').read_bytes())
            extracted = Path(self.tmp.name) / 'fresh'
            archive.extractall(extracted)
        run = subprocess.run([sys.executable, '-I', str(extracted / 'trenchie-client/near/arena/snap.py'), '--help'],
                             cwd=extracted, text=True, capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('live', run.stdout)
        # Exercise the actual Copy formatter and the provider fallback without a browser or a model call.
        command_case = r'''
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const P = require('./near/web/snapin/providers.js');
const context = {SnapUI: {copyText: async (text) => {context.copied = text; return true;}}};
vm.createContext(context);
for (const name of ['guide-copy.js','guide.js']) vm.runInContext(fs.readFileSync('near/web/snapin/'+name,'utf8'),context);
context.SnapGuide.state.code = {code:'CASE-CODE',snapUrl:'https://arena.example/SNAP.md'};
const h = {P:{name:'Pebble',pick:{route:'plan',door:'Codex'}},render:()=>{}};
(async()=> {
  await context.SnapGuide.act('g:copy',h);
  const fallback=P.snap.buildHandoff({agent:'codex',code:'CASE-CODE',snapMdUrl:'https://arena.example/SNAP.md',name:'Pebble'});
  assert.equal(context.copied,fallback.command);
  assert.match(context.copied,/^codex -c sandbox_workspace_write.network_access=true /);
  assert.match(context.copied,/Download the current client.*\/snap-client\.zip.*do not use a local checkout/);
  h.P.pick.door='Claude Code';
  await context.SnapGuide.act('g:copy',h);
  assert.equal(context.copied,'claude "Join Trenchie Arena. Read https://arena.example/SNAP.md and follow it. Code CASE-CODE, Trenchie Pebble."');
  console.log('guide Copy and fallback agree: current client, network access, original code/name; Claude unchanged');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        commands = subprocess.run(['node', '-e', command_case], cwd=ROOT, text=True, capture_output=True, timeout=20)
        self.assertEqual(commands.returncode, 0, commands.stderr)
        self.assertIn('Copy and fallback agree', commands.stdout)


if __name__ == '__main__':
    unittest.main()
