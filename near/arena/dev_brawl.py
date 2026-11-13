"""Dev spectator server: the 14 house trenchies brawl on the current rules table.

Run:  python3 -B near/arena/dev_brawl.py [--port 8765] [--seed 1] [--ticks N] [--crowd 16]

--crowd N adds newcomers (crowd-1, crowd-2, ...) to the 14 house trenchies until N fight, each on a fixed free-menu kit
that cycles the lob, beam, shot and swing with the beam sweep and the shockwave, so every move is on screen in a crowd.

Spectator-only WebSocket (text frames) on 127.0.0.1. Add ?codec=1 to the URL for the compact W14 frames
(codec.py: a tables frame, then a tick frame per tick) instead of the canonical snapshot. Every frame is one
`server.encode_snapshot` payload: canonical JSON
[version, tick, names, rows, fighters, drops, objects, casts, events].
Standard library only, so it runs where `websockets` is not installed. It is a
development harness: the production arena server (F6) keeps its own transport.
A client never sends game input; its frames are read only to answer ping and close.
"""

import asyncio
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim
import codec
import server
from spectator_styles import SpectatorStyles

GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_BUFFER = 1 << 20


# the newcomers' kits for --crowd: free-menu items only (no bag), weapon and signature cycling
CROWD_KITS = (("looter", "c-lob", "c-beam-sweep"), ("guardian", "c-beam", "c-shockwave"),
              ("hunter", "c-shot", "c-shockwave"), ("brawler", "c-swing", "c-beam-sweep"))


def new_brawl(seed, rules=sim.DEFAULT_RULES, crowd=0):
    """All house trenchies joined at spread angles, plus newcomers up to `crowd` fighters; combat, loot and respawn on."""
    game = sim.Sim(seed, rules)
    names = sim.ordered_ids(rules["house"])
    extra = max(0, crowd - len(names))
    total = len(names) + extra
    for index, name in enumerate(names):
        game.enqueue(sim.Input(0, "join", name, 0,
                               {"house": True, "angle": index * rules["full_turn"] // total}))
    for i in range(extra):
        style, weapon, trinket = CROWD_KITS[i % len(CROWD_KITS)]
        loadout = dict(rules["default_loadout"], weapon=weapon, trinket=trinket)
        game.enqueue(sim.Input(0, "join", "crowd-" + str(i + 1), 0,
                               {"style": style, "loadout": loadout, "bag": {},
                                "angle": (len(names) + i) * rules["full_turn"] // total}))
    return game


def frame(payload: bytes, opcode=0x1) -> bytes:
    size = len(payload)
    if size < 126:
        head = struct.pack("!BB", 0x80 | opcode, size)
    elif size < 1 << 16:
        head = struct.pack("!BBH", 0x80 | opcode, 126, size)
    else:
        head = struct.pack("!BBQ", 0x80 | opcode, 127, size)
    return head + payload


async def read_frame(reader):
    """One client frame as (opcode, payload); clients must mask."""
    b1, b2 = await reader.readexactly(2)
    size = b2 & 0x7F
    if size == 126:
        size = struct.unpack("!H", await reader.readexactly(2))[0]
    elif size == 127:
        size = struct.unpack("!Q", await reader.readexactly(8))[0]
    if b1 & 0x08 and (size > 125 or not b1 & 0x80):
        raise ValueError("control frames must be final and at most 125 bytes")
    if size > 4096:
        raise ValueError("client frame too large")
    mask = await reader.readexactly(4) if b2 & 0x80 else b"\0\0\0\0"
    data = bytes(c ^ mask[i % 4] for i, c in enumerate(await reader.readexactly(size)))
    return b1 & 0x0F, data


class Brawl:
    def __init__(self, seed=1, rules=sim.DEFAULT_RULES, ticks=None, crowd=0):
        self.game = new_brawl(seed, rules, crowd)
        self.rules = rules
        self.limit = ticks
        self.latest = server.encode_snapshot(self.game)
        self.tables = codec.tables_for(self.game)
        self.latest_codec = None
        self.clients = {}
        self.styles = SpectatorStyles(self.game, frame)
        self.dropped = 0
        self.slowest = 0.0

    async def handle(self, reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.close()
            return
        lines = head.decode("latin-1").split("\r\n")
        headers = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:] if ":" in l)}
        key = headers.get("sec-websocket-key")
        if headers.get("upgrade", "").lower() != "websocket" or not key:
            body = json.dumps(self.health()).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n"
                         b"Content-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
            await writer.drain()
            writer.close()
            return
        accept = base64.b64encode(hashlib.sha1(key.encode() + GUID).digest())
        writer.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                     b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n")
        compact = "codec=1" in lines[0].split(" ")[1] if len(lines[0].split(" ")) > 1 else False
        query = parse_qs(urlsplit(lines[0].split(" ")[1]).query)
        if query.get("styles") == ["1"]:
            self.styles.connect(writer)
        if compact:
            writer.write(frame(codec.encode_tables(self.tables)))
            writer.write(frame(self.latest_codec or codec.encode_tick(self.game, self.tables)))
        else:
            writer.write(frame(self.latest))
        self.clients[writer] = compact
        try:
            while True:
                opcode, data = await read_frame(reader)
                if opcode == 0x8:
                    writer.write(frame(b"", 0x8))
                    break
                if opcode == 0x9:
                    writer.write(frame(data, 0xA))
        except (asyncio.IncompleteReadError, ConnectionError, ValueError):
            pass
        finally:
            self.clients.pop(writer, None)
            self.styles.forget(writer)
            writer.close()

    def health(self):
        return {"tick": self.game.state["tick"], "spectators": len(self.clients),
                "fighters": len(self.game.state["fighters"]), "dropped_sends": self.dropped,
                "slowest_step_ms": round(self.slowest * 1000, 2), "rules_hash": self.game.rules_hash,
                "format": "canonical JSON [version, tick, names, rows, fighters, drops, objects, casts, events]"}

    def publish(self):
        self.styles.refresh(self.game)
        plain, small = frame(self.latest), frame(self.latest_codec)
        for writer, compact in tuple(self.clients.items()):
            if writer.transport.get_write_buffer_size() > MAX_BUFFER:
                self.dropped += 1
                continue
            self.styles.send(writer)
            writer.write(small if compact else plain)

    async def run(self):
        period = 1 / self.rules["tick_hz"]
        deadline = time.monotonic()
        while self.limit is None or self.game.state["tick"] < self.limit:
            started = time.monotonic()
            self.game.step()
            self.latest = server.encode_snapshot(self.game)
            self.tables = codec.tables_for(self.game)
            self.latest_codec = codec.encode_tick(self.game, self.tables)
            self.slowest = max(self.slowest, time.monotonic() - started)
            self.publish()
            deadline += period
            await asyncio.sleep(max(0, deadline - time.monotonic()))


async def serve(brawl, port, ready=None):
    listener = await asyncio.start_server(brawl.handle, "127.0.0.1", port)
    bound = listener.sockets[0].getsockname()[1]
    if ready is not None:
        ready.set_result(bound)
    async with listener:
        await brawl.run()


def main(argv):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--ticks", type=int, default=None, help="stop after N ticks (default: run forever)")
    parser.add_argument("--crowd", type=int, default=0, help="fighters in all: newcomers join the 14 house Trenchies up to N")
    args = parser.parse_args(argv)
    brawl = Brawl(args.seed, ticks=args.ticks, crowd=args.crowd)
    print("brawl: %d fighters (%d house), rules %s, ws://127.0.0.1:%d (spectator only, 20 Hz)"
          % (len(brawl.game.state["fighters"]) or max(args.crowd, len(brawl.rules["house"])), len(brawl.rules["house"]),
             brawl.game.rules_hash[:12], args.port), flush=True)
    try:
        asyncio.run(serve(brawl, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
