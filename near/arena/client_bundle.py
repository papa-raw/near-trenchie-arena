"""The public terminal client, assembled from a fixed source/data allowlist; no runtime state or credentials."""
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

CLIENT_FILES = (
    'near/SNAP.md', 'near/requirements.txt', 'near/constraints.txt',
    'near/onboarding/requirements.txt', 'near/chain/requirements.txt',
    'near/arena/snap.py', 'near/arena/snap_client.py', 'near/arena/snap_live.py',
    'near/arena/battle_protocol.py', 'near/arena/battle_transport.py', 'near/arena/dev_persona.py',
    'near/arena/presets.py', 'near/arena/balance.py', 'near/arena/sim.py',
    'near/arena/catalog.py', 'near/arena/behaviour.py', 'near/arena/replay.py',
    'near/lore/check_personas.py', 'near/lore/check_sheets.py', 'near/lore/emoji.py',
    'near/lore/persona.schema.json', 'near/lore/kits.json',
    'near/house/guard.py', 'near/house/link_policy.json', 'near/house/confusables.json',
    'room/__init__.py', 'room/ledger.py', 'room/policy.py', 'room/protocol.py',
    'room/protocol.schema.json', 'room/requirements.txt',
)


def build_client_bundle(root: Path | None = None) -> bytes:
    """Return this deployment's client in a fresh-folder ZIP. Missing public dependencies fail closed."""
    root = root or Path(__file__).resolve().parents[2]
    out = BytesIO()
    with ZipFile(out, 'w', compression=ZIP_DEFLATED) as archive:
        for name in CLIENT_FILES:
            path = root / name
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('client source must be a regular file inside the deployment')
            entry = ZipInfo('trenchie-client/' + name, date_time=(2000, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, path.read_bytes())
    return out.getvalue()
