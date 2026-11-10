"""The dev brawl serves house-trenchie snapshots to a raw WebSocket spectator."""

import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev_brawl
import sim


async def read_server_frame(reader):
    b1, b2 = await reader.readexactly(2)
    size = b2 & 0x7F
    if size == 126:
        size = int.from_bytes(await reader.readexactly(2), "big")
    elif size == 127:
        size = int.from_bytes(await reader.readexactly(8), "big")
    return b1 & 0x0F, await reader.readexactly(size)


class DevBrawl(unittest.IsolatedAsyncioTestCase):
    async def test_spectator_gets_advancing_house_snapshots_and_http_health(self):
        brawl = dev_brawl.Brawl(seed=3, ticks=400)
        ready = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(dev_brawl.serve(brawl, 0, ready))
        port = await ready
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        key = base64.b64encode(os.urandom(16)).decode()
        writer.write(("GET / HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % key).encode())
        head = await reader.readuntil(b"\r\n\r\n")
        self.assertIn(b"101 Switching Protocols", head)
        ticks = []
        for _ in range(3):
            opcode, data = await read_server_frame(reader)
            self.assertEqual(opcode, 1)
            snap = json.loads(data)
            ticks.append(snap[1])
            self.assertEqual(snap[2], sorted(sim.DEFAULT_RULES["house"]))
            self.assertEqual(len(snap[4]), 14)
            self.assertEqual(snap[0], 1)
        self.assertEqual(ticks, sorted(set(ticks)))
        reader2, writer2 = await asyncio.open_connection("127.0.0.1", port)
        writer2.write(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
        body = (await reader2.read()).split(b"\r\n\r\n", 1)[1]
        self.assertEqual(json.loads(body)["fighters"], 14)
        writer.close()
        writer2.close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_codec_query_sends_a_tables_frame_then_compact_ticks_that_decode_to_the_canonical_snapshot(self):
        import codec
        brawl = dev_brawl.Brawl(seed=3, ticks=400)
        ready = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(dev_brawl.serve(brawl, 0, ready))
        port = await ready
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(("GET /?codec=1 HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % base64.b64encode(os.urandom(16)).decode()).encode())
        await reader.readuntil(b"\r\n\r\n")
        _, first = await read_server_frame(reader)
        tables = json.loads(first)
        self.assertEqual(tables[0], "T")
        _, tick = await read_server_frame(reader)
        mine = {"table_id": tables[1], "names": tables[2], "rows": tables[3], "signatures": tables[4], "kinds": tables[5]}
        snap = codec.decode_tick(tick, mine)
        self.assertEqual(snap[2], sorted(sim.DEFAULT_RULES["house"]))
        self.assertEqual(len(snap[4]), 14)
        writer.close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def test_fourteen_house_trenchies_fight_loot_and_ko(self):
        game = dev_brawl.new_brawl(1)
        game.run(2400)
        total_kos = sum(f["kos"] for f in game.state["fighters"].values())
        self.assertGreater(total_kos, 0)
        self.assertEqual(len(game.state["fighters"]), 14)


if __name__ == "__main__":
    unittest.main()
