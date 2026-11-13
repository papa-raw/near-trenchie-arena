"""Public speech and persona names refuse links and wallet credential lures."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena')]
from near.house.guard import Guard
from near.house.feed import PublicFeed
import dev_persona


class PublicText(unittest.TestCase):
    def test_sentence_breaks_and_every_house_keyed_line_are_not_links(self):
        guard = Guard(dict(names=[], handles=[], slurs=[]), [])
        lines = ['Nice hit. Try again!', 'Mine now. Back off.', 'GG. Next round.', 'Polka dot dress']
        for path in (ROOT / 'near/lore/personas').glob('*.json'):
            game = json.loads(path.read_text())['game']
            lines += game['voice'] + list(game['reactions'].values()) + game.get('tics', [])
        for text in lines:
            with self.subTest(text=text):
                self.assertIsNone(guard.reason(text))

    def test_domains_of_any_suffix_are_muted_without_muting_ordinary_speech(self):
        guard = Guard(dict(names=[], handles=[], slurs=[]), [])
        domains = ['gift.top', 'gift.ru', 'prize.uk', 'gift.unlistedexample',
                   'loot.xn--p1ai', 'claim.gift.co.uk', 'gift[.]top', 'gift(.)ru',
                   'gift dot top', 'gift dot ru', 'prize dot uk', 'gift dot unlistedexample',
                   'gift DOT com', 'gift dot io', 'claim free NEAR at gift.top',
                   'collect rewards at gift.ru', 'visit prize.uk', 'gift.xyz',
                   'Polka dot dress gift.xyz', 'Polka dot dress dot top']
        for text in domains:
            with self.subTest(domain=text):
                self.assertEqual(guard.reason(text), 'link')
                self.assertNotEqual(PublicFeed(guard).post('visitor', text, source='player', tick=0)['text'], text)
        lines = ['Nice hit. Try again!', 'Mine now. Back off.', 'GG. Next round.',
                 'co-op, e.g. a nice day', 'i.e. try again', '0.5 s until my next swing',
                 'Polka dot dress']
        keyed = []
        for path in (ROOT / 'near/lore/personas').glob('*.json'):
            game = json.loads(path.read_text())['game']
            keyed += game['voice'] + list(game['reactions'].values()) + game.get('tics', [])
        self.assertEqual(len(keyed), 126)
        for text in lines + keyed:
            with self.subTest(speech=text):
                self.assertIsNone(guard.reason(text))
                self.assertEqual(PublicFeed(guard).post('visitor', text, source='player', tick=0)['text'], text)
        listed = Guard(dict(names=['Fakey McFakeface'], handles=[], slurs=[]), [])
        self.assertEqual(listed.reason('Fakey.McFakeface'), 'real-name')

    def test_phishing_cannot_reach_speech_names_or_unbounded_nft_titles(self):
        blocklist = dict(names=[], handles=[], slurs=[])
        guard = Guard(blocklist, [])
        lures = (
            'claim free NEAR at https://near-airdrop.example/claim',
            'connect wallet at neartrenchies-claim.xyz',
            'DM me your seed phrase for a free legendary',
            'Connect your wallet', 'share your recovery phrase', 'send your private key',
            'ｈｔｔｐｓ://gift.example', 'gift[.]xyz', 'gift dot xyz',
        )
        for text in lures:
            with self.subTest(text=text), patch.object(dev_persona, 'load_blocklist', return_value=blocklist):
                self.assertIsNotNone(guard.reason(text))
                row = PublicFeed(guard).post('visitor', text, source='player', tick=0)
                self.assertNotEqual(row['text'], text)
                with self.assertRaises(ValueError):
                    dev_persona.check_display_name(text, 'Visitor')
        schema = dev_persona.SCHEMA['properties']['game']['properties']['name']
        for name in ('x' * 65, 'Odd\nName', '<Odd>', 'odd.example'):
            with self.subTest(name=name):
                errors = []
                dev_persona.checker.validate(schema, name, dev_persona.SCHEMA, 'game.name', errors)
                self.assertTrue(errors, 'the persona schema must constrain the NFT title')
        for name in ('Pebble Captain', "Dune O'Bean", 'Laser Sailor'):
            self.assertIsNone(guard.reason(name))
        self.assertIsNone(guard.reason('0.5 s until my next swing'))
        for path in (ROOT / 'near/lore/personas').glob('*.json'):
            game = json.loads(path.read_text())['game']
            errors = []
            dev_persona.checker.validate(schema, game['name'], dev_persona.SCHEMA, 'game.name', errors)
            self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
