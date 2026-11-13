"""Creator-approved structural names agree with minted persona admission; plain DEV names retain slugs."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
import dev_persona


class NameAgreement(unittest.TestCase):
    def test_spoken_domain_names_are_refused_by_creator_host_and_next_button(self):
        names = ['Amber dot com', 'Pebble dot io', 'Amber dot top', 'Pebble dot ru',
                 'Pebble dot uk', 'Pebble dot unlistedexample', 'Polka dot dress', 'Pebble Captain']
        code = """
const S = require('./near/web/snapin/sheet.js');
globalThis.SnapSheet = S;
require('./near/web/snapin/guide-copy.js');
require('./near/web/snapin/guide.js');
let input = '';
process.stdin.on('data', x => input += x).on('end', () => {
  const rows = JSON.parse(input).map(name => {
    const state = {name, temper: 'sunny', quirks: [], fighterChosen: true};
    const sheet = S.build({name, temperament: 'sunny', preset: 'brawler-swing', door: 'Codex'});
    const html = SnapGuide.view({P: state, V: {step: 'personality'}});
    return {ok: S.guard(name).ok, errors: S.validate(sheet), sheet,
            next: /<button[^>]*data-act="g:step:doors"/.test(html),
            disabled: /disabled aria-describedby="needs">Next: AI/.test(html)};
  });
  process.stdout.write(JSON.stringify(rows));
});
"""
        result = subprocess.run(['node', '-e', code], input=json.dumps(names), text=True,
                                capture_output=True, cwd=ROOT, check=True, timeout=10)
        rows = json.loads(result.stdout)
        self.assertEqual([row['ok'] for row in rows],
                         [name in ('Polka dot dress', 'Pebble Captain') for name in names])
        with patch.object(dev_persona, 'load_blocklist', return_value=dict(names=[], handles=[], slurs=[])):
            for name, row in zip(names, rows):
                with self.subTest(name=name):
                    allowed = name in ('Polka dot dress', 'Pebble Captain')
                    self.assertEqual(row['ok'], allowed)
                    self.assertEqual(row['next'], allowed)
                    self.assertEqual(row['disabled'], not allowed)
                    if not allowed:
                        self.assertTrue(any('web address' in str(error) for error in row['errors']))
                        with self.assertRaises(ValueError):
                            dev_persona.check_sheet(row['sheet'])
                    else:
                        self.assertEqual(row['errors'], [])
                        dev_persona.check_sheet(row['sheet'])
        subprocess.run(['python3', '-I', 'near/tools/gen_link_policy.py', '--check'],
                       cwd=ROOT, check=True, timeout=10)

    def test_creator_and_minted_name_rules_agree_and_dev_names_keep_their_slug(self):
        names = ['Pebble Captain', "Dune O'Bean", 'Zoë', 'Dr. Pump', 'Señor Pip', 'Dune O’Bean',
                 'Amber  Captain', 'Amber Captain ', 'AAAAAmber', '1234', 'Connect Wallet', 'Seed Phrase',
                 'Amber River Pebble Captain Willow', 'Amber River Pebble Captain Willowx']
        code = "const S=require('./near/web/snapin/sheet.js');let b='';process.stdin.on('data',x=>b+=x).on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(b).map(n=>S.guard(n).ok))));"
        result = subprocess.run(['node', '-e', code], input=json.dumps(names), text=True, capture_output=True,
                                cwd=ROOT, check=True, timeout=10)
        creator = json.loads(result.stdout)
        with patch.object(dev_persona, 'load_blocklist', return_value=dict(names=[], handles=[], slurs=[])):
            for name, approved in zip(names, creator):
                with self.subTest(name=name):
                    try:
                        dev_persona.check_display_name(name, 'Visitor')
                        admitted = True
                    except ValueError:
                        admitted = False
                    self.assertEqual(admitted, approved)
            # This applies only to the local plain-name path, never minted persona admission.
            dev_persona.check_display_name('Tester!', 'Tester!', plain=True)


if __name__ == '__main__':
    unittest.main()
