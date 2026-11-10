"""New cross-language case: compare actual drawn meshes to the server's bound projection."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'near/arena'))
import server
import test_quirks as fixture
from test_quirk_telegraphs import observe_cast
from spectator_styles import SpectatorStyles
ROWS = ['leg-laser-eyes', 'leg-hydra-halo', 'leg-tinker-coil', 'leg-harvest-quake', 'leg-ether-stack', 'leg-router-drone']
cases = []
for row in ROWS:
    for pct in (100, 125, 150):
        game, fighter = fixture.arena(row)
        fighter['sig_range_pct'] = pct
        fixture.start(game, fighter)
        # A different trinket and live stats cannot change the old cast's public geometry.
        fighter['equipped']['trinket'] = 'leg-poker-face'
        fighter['sig_range_pct'] = 250
        projection = observe_cast(game)
        meta = SpectatorStyles(game, lambda data: data)
        cases.append({'row': row, 'percent': pct, 'expected': projection, 'snapshot': json.loads(server.encode_snapshot(game)), 'metadata': json.loads(meta.full)})
with tempfile.TemporaryDirectory(prefix='arena-quirks-') as directory:
    path = Path(directory) / 'fixtures.json'; path.write_text(json.dumps(cases))
    subprocess.run(['node', '--no-warnings', '--experimental-loader', './near/web/arena-view-remainder-loader.mjs', 'near/web/arena-quirk-geometry-case.mjs', str(path)], cwd=ROOT, check=True)
