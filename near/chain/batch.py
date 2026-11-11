"""The batch formats the writer sends, and the two digests `arena.post_batch` computes over them.

`arena` stores `fight_hash = sha256(borsh(Vec<Segment>))` and `rows_digest = sha256(borsh(Vec<Row>))`
(near/contracts/arena/src/lib.rs, `post_batch`). The same borsh layout is written here so the writer,
the fake RPC and the archival reader can recompute both from a transaction's JSON arguments alone.
Field order follows the Rust structs exactly; a change there must change this file.
"""

import hashlib
import json
import re
import struct
from pathlib import Path

HEX64 = re.compile(r"[0-9a-f]{64}")
ID = re.compile(r"[A-Za-z0-9_.\-]{1,64}")
SEGMENT_HASHES = ("seed_hash", "inputs_hash", "rules_hash", "final_state_hash", "predictions_log_hash")
MAX_BAG = 48


def seed_hash(value: int) -> str:
    """The sealed record's seed_hash: sha256 of the canonical JSON string of the u64, quotes included."""
    return hashlib.sha256(json.dumps(str(value)).encode()).hexdigest()


def derive_seed(secret: bytes, random_seed: bytes, i: int) -> bytes:
    """seed_i = sha256(secret || the commit block's random seed || u32be(i)), as `arena.commit_seeds`."""
    return hashlib.sha256(secret + random_seed + struct.pack(">I", i)).digest()


def seed_u64(seed_hex: str) -> int:
    """The u64 the sim runs on: the committed seed's first 8 bytes, big-endian."""
    raw = bytes.fromhex(seed_hex)
    if len(raw) != 32:
        raise ValueError("a committed seed is 32 bytes")
    return int.from_bytes(raw[:8], "big")


def _string(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _vec(items, encode) -> bytes:
    return struct.pack("<I", len(items)) + b"".join(encode(x) for x in items)


def borsh_segment(s: dict) -> bytes:
    return (_string(s["segment_id"]) + struct.pack("<Q", int(s["commit_id"])) + struct.pack("<H", s["seed_index"])
            + b"".join(_string(s[k]) for k in SEGMENT_HASHES) + struct.pack("<I", s["kos"]))


def borsh_entry(e: dict) -> bytes:
    return struct.pack("<HHIHBB", e["row"], e["serial"], e["born_batch"], e["kos"], e["hands"], e["flags"])


def borsh_row(r: dict) -> bytes:
    rec = r["record"]
    sale = r.get("sale_ready")
    return (_string(r["token_id"]) + _vec(r["bag"], borsh_entry) + struct.pack("<IIi", rec["lives"], rec["kos"], rec["skill"])
            + (b"\x00" if sale is None else b"\x01" + (b"\x01" if sale else b"\x00")))


def fight_hash(segments: list[dict]) -> str:
    return hashlib.sha256(_vec(segments, borsh_segment)).hexdigest()


def rows_digest(rows: list[dict]) -> str:
    return hashlib.sha256(_vec(rows, borsh_row)).hexdigest()


def check_segment(s: dict) -> None:
    """The checks `post_batch` makes on a segment, run before anything is sent."""
    if not ID.fullmatch(s["segment_id"]):
        raise ValueError(f"invalid segment id {s['segment_id']!r}")
    for k in SEGMENT_HASHES:
        if not HEX64.fullmatch(s[k]):
            raise ValueError(f"segment {s['segment_id']} {k} is not 64 lowercase hex")
    if not 0 <= int(s["commit_id"]) < 2 ** 64 or not 0 <= s["seed_index"] < 2 ** 16 or not 0 <= s["kos"] < 2 ** 32:
        raise ValueError("segment numbers out of range")


def check_row(r: dict, row_count: int | None = None) -> None:
    if len(r["bag"]) > MAX_BAG:
        raise ValueError(f"{r['token_id']}: a bag holds at most 48 entries")
    seen = set()
    for e in r["bag"]:
        for k, bits in (("row", 16), ("serial", 16), ("born_batch", 32), ("kos", 16), ("hands", 8), ("flags", 8)):
            if type(e[k]) is not int or not 0 <= e[k] < 2 ** bits:
                raise ValueError(f"{r['token_id']}: bag {k} out of range")
        if e["row"] in seen:
            raise ValueError(f"{r['token_id']}: a second copy of a row in one bag")
        if row_count is not None and e["row"] >= row_count:
            raise ValueError(f"{r['token_id']}: bag row outside the rules table")
        seen.add(e["row"])
    rec = r["record"]
    if not (0 <= rec["lives"] < 2 ** 32 and 0 <= rec["kos"] < 2 ** 32 and -2 ** 31 <= rec["skill"] < 2 ** 31):
        raise ValueError(f"{r['token_id']}: record out of range")


ITEM_ROWS = Path(__file__).resolve().with_name("item_rows.json")


def item_rows(path=None) -> list[str]:
    """The append-only row registry: an inventory row number names rows[row], whatever the rules table."""
    return list(json.loads(Path(path or ITEM_ROWS).read_text())["rows"])


RULES_DIR = Path(__file__).resolve().parents[1] / "arena" / "rules"


def released_tables(rules_dir=RULES_DIR) -> list[tuple[str, dict]]:
    """Every released rules table's items, in release order (integer-N by N)."""
    files = sorted(Path(rules_dir).glob("integer-*.json"), key=lambda f: int(f.stem.split("-")[1]))
    return [(f.name, json.loads(f.read_text())["items"]) for f in files]


def check_registry(rows: list[str], tables: list[tuple[str, dict]]) -> list[str]:
    """What is wrong with the row registry against the released rules tables, as plain sentences (empty when sound).
    The order is fixed by the tables themselves, so it cannot be edited to agree with itself: the first table's items
    sorted, then each later table's new items sorted, appended. Rows past the last table's are allowed (an item
    registered ahead of its table); a row is never reused."""
    problems, seen = [], []
    if len(rows) != len(set(rows)):
        problems.append("a row is reused")
    for name, items in tables:
        new = sorted(set(items) - set(seen))
        got = rows[len(seen):len(seen) + len(new)]
        if got != new:
            problems.append(f"{name}: rows {len(seen)}..{len(seen) + len(new) - 1} should be its new items sorted "
                            f"{new[:3]}..., found {got[:3]}...: rows are only ever appended, in release order")
            break
        seen += new
    return problems


def row_index(items, rows: list[str]) -> dict:
    """{item id: its registry row} for every item of a rules table; an item the registry lacks stops here (append it)."""
    missing = sorted(set(items) - set(rows))
    if missing:
        raise ValueError(f"items not in the inventory row registry {ITEM_ROWS.name}: {missing}; append them "
                         f"(rows never move, so stored gear keeps its meaning)")
    at = {name: i for i, name in enumerate(rows)}
    return {name: at[name] for name in items}


def bag_entries(bag: dict, row_index: dict) -> list[dict]:
    """A sim bag ({row id: entry}) as the contract's entries, sorted by row index."""
    out = [dict(row=row_index[rid], **{k: int(bag[rid][k]) for k in ("serial", "born_batch", "kos", "hands", "flags")})
           for rid in bag]
    return sorted(out, key=lambda e: e["row"])


def segment_kos(sealed: dict) -> int:
    """KOs scored by the lives that completed in the segment, as the sealed record lists them.

    Recomputable from the sealed record alone (its `lives`), so a reader can check it without a replay.
    """
    return sum(int(life["ko_count"]) for life in sealed["lives"])


def batch_log_hash(segments: list[dict], house_log_hash: str | None) -> str:
    """The predictions-log hash `market.resolve` carries for a batch, from the batch's own arguments.

    sha256 of compact JSON {"house_log": <the F79 public log's hash at the batch's last segment, or null>,
    "segments": [each segment's predictions_log_hash, in order]}: anyone holding the `post_batch` args and
    the public log can recompute it.
    """
    body = {"house_log": house_log_hash, "segments": [s["predictions_log_hash"] for s in segments]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
