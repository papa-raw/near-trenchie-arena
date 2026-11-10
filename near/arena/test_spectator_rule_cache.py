"""A rules hash converts its spectator dictionary once, even across game instances."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
import spectator_styles
import os
import importlib.util
if os.environ.get('SPECTATOR_RULE_BASE'):
    spec = importlib.util.spec_from_file_location('spectator_rules_before', os.environ['SPECTATOR_RULE_BASE'])
    before = importlib.util.module_from_spec(spec); spec.loader.exec_module(before)
    spectator_styles = before
import test_quirks as fixture

class RulesCache(unittest.TestCase):
    def test_converts_rules_once_per_hash(self) -> None:
        game, fighter = fixture.arena('leg-router-drone')
        with patch.object(spectator_styles, 'rules_dict', wraps=spectator_styles.rules_dict) as convert:
            channel = spectator_styles.SpectatorStyles(game, lambda data: data)
            initial = channel.rules
            for _ in range(20): channel.refresh(game)
            another, _ = fixture.arena('leg-laser-eyes'); channel.refresh(another)
            self.assertIs(channel.rules, initial)
            self.assertEqual(convert.call_count, 1)

if __name__ == '__main__': unittest.main()
