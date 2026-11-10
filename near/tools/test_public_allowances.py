"""Narrow public-export allowances retain real-hit detection and runtime item-name checks."""
import json
from pathlib import Path
import re
import sys
import unittest
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'items')]
from test_gate import Fixture, BANNED_A, BANNED_B, REL
import check_items
import gate
from arena import sim

NEAR = Path(__file__).resolve().parents[1]
VENDOR = 'near/web/snapin/vendor/near-api-js/near-api-js-7.3.1.min.js'

class PublicAllowances(unittest.TestCase):
    def test_certified_vendor_constants_only_pass_at_the_exact_path(self) -> None:
        fx = Fixture(self)
        fx.put(VENDOR, (NEAR / VENDOR.removeprefix('near/')).read_text())
        fx.commit()
        code, output = fx.run('private')
        self.assertEqual(code, 0, output)
        for rel in ('near/web/app.js', 'near/web/other/vendor/unknown.js'):
            fx.put(rel, "const value = '" + '0' + 'x' + 'a' * 64 + "';\n")
        code, output = fx.run('private')
        self.assertEqual(code, 1, output)
        self.assertIn('near/web/app.js:1', output)
        self.assertIn('near/web/other/vendor/unknown.js:1', output)
        # A changed pinned file and every other secret kind remain scanned.
        fx.put(VENDOR, "const value = '" + '0' + 'x' + 'b' * 64 + "';\nconst token = '" + 'gh' + 'p_' + 'A' * 36 + "';\n")
        code, output = fx.run('private')
        self.assertEqual(code, 1, output)
        self.assertIn(VENDOR + ':1', output)
        self.assertIn(VENDOR + ':2', output)

    def test_lock_version_line_only_and_release_elsewhere_is_caught(self) -> None:
        fx = Fixture(self)
        release = REL.split()[-1]
        fx.put('near/contracts/Cargo.lock', '[[package]]\nname = "plain"\nversion = "' + release + '"\n')
        fx.commit()
        code, output = fx.run('leak')
        self.assertEqual(code, 0, output)
        fx.put('README.md', 'version = "' + release + '"\n')
        fx.put('near/contracts/Cargo.lock', 'version = "' + release + '"\nname = "' + release + '"\nversion = "' + release + '" # ' + REL + '\n')
        fx.put('note.md', 'G' + '1' + '-E\n')
        code, output = fx.run('leak')
        self.assertEqual(code, 1, output)
        self.assertIn('README.md:1', output)
        self.assertIn('Cargo.lock:2', output)
        self.assertIn('Cargo.lock:3', output)
        self.assertNotIn('Cargo.lock:1:', output)
        # Check the real release marker pattern separately from the temp pattern file.
        hits = gate.scan_regex('leak', fx.repo, ['note.md'], re.compile('G' + '1' + '-E'), gate.LEAK_ALLOW)
        self.assertEqual(len(hits), 1)

    def test_split_words_still_refuse_all_seven_item_name_tokens(self) -> None:
        source = (NEAR / 'items/limits.json').read_text().lower()
        for term in (BANNED_A, BANNED_B):
            self.assertNotIn(term, source)
        limits = check_items.load_limits()
        words = [BANNED_A, BANNED_A + 's', BANNED_B, BANNED_B + 's', 'scam', 'fraud', 'jail']
        self.assertEqual(limits['banned_words'], words)
        kit = json.loads((NEAR / 'items/fixtures/kit/kit.json').read_text())
        item = json.loads((NEAR / 'items/fixtures/known-good-weapon.json').read_text())
        for word in words:
            item['name'] = word.title() + ' Club'
            errors = check_items.check_item(item, sim.DEFAULT_RULES, kit, limits)
            self.assertTrue(any('banned' in error for error in errors), word)

if __name__ == '__main__': unittest.main()
