"""The reviewer demo must carry every portable-client dependency to its owner."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena')]
from near.web import demo
from test_snap_cold import SnapCold


class DemoClient(unittest.TestCase):
    def test_real_demo_packages_the_battle_contract_and_reaches_checked_replay(self) -> None:
        prepare = SnapCold.prepare_owner
        packages = []
        def checked_copy(*args: object) -> tuple[Path, Path]:
            owner, public = prepare(*args)
            self.assertEqual((public / 'near/arena/battle_protocol.py').read_bytes(),
                             (ROOT / 'near/arena/battle_protocol.py').read_bytes())
            packages.append(public)
            return owner, public
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(SnapCold, 'prepare_owner', side_effect=checked_copy):
            output = Path(directory) / 'demo'
            facts = demo.generate(output)
            self.assertEqual(len(packages), 1)
            self.assertEqual(facts['state'], 'checked')
            self.assertTrue((output / 'segment.json').is_file())
            self.assertTrue((output / 'evidence.json').is_file())


if __name__ == '__main__':
    unittest.main()
