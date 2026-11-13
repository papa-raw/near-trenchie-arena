"""Unknown model outcomes consume budget and unreadable spend history stops calls."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime


class SpendFailures(unittest.TestCase):
    def test_unknown_outcomes_are_charged_and_damaged_meters_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'spend.json'
            for raw in (b'broken', b'{}', b'{"days":{},"total":-1}'):
                with self.subTest(raw=raw):
                    path.write_bytes(raw)
                    budget = runtime.Budget(runtime.JsonMeter(path), 'building')
                    self.assertTrue(budget.state()['autopilot'])
                    self.assertFalse(budget.allow('visitor', 100))
                    self.assertEqual(path.read_bytes(), raw, 'damaged history must be retained for recovery')
            path.unlink()
            with self.subTest(kind='unreadable'), patch.object(Path, 'read_bytes', side_effect=PermissionError('unreadable')):
                self.assertTrue(runtime.Budget(runtime.JsonMeter(path)).state()['autopilot'])
            meter = runtime.JsonMeter(path)
            budget = runtime.Budget(meter, 'building', clock=lambda: 100)
            host = runtime.Runtime.__new__(runtime.Runtime)
            host.budget, host.clock = budget, lambda: 100
            host.sheets = {'visitor': {'prefix': 'A' * 2000}}
            host.voices = {'visitor': SimpleNamespace(card_lines=lambda: [])}
            host.call_times, host.stats = {}, {'calls': 0}
            def timeout(*args, **kwargs):
                raise runtime.ModelCallError('curl exit 28', 'timed out')
            host.client = SimpleNamespace(chat=timeout)
            with self.assertRaises(runtime.ModelCallError):
                host._ask('visitor', 'Fight', 'Plan', max_tokens=450)
            charged = meter.total()
            self.assertGreaterEqual(charged, 1140, 'uncached prompt bytes plus maximum output must be allowed for')
            self.assertEqual(runtime.JsonMeter(path).total(), charged)
            usage = dict(prompt_tokens=10, completion_tokens=2, cached_tokens=0)
            host.client = SimpleNamespace(chat=lambda *a, **kw: dict(text='ok', usage=usage))
            self.assertEqual(host._ask('visitor', 'Fight', 'Plan'), 'ok')
            self.assertEqual(meter.total() - charged, runtime.cost_microusd(usage))
            with patch.object(runtime.os, 'replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    budget.charge(usage)
            self.assertTrue(budget.state()['autopilot'], 'a failed meter write must stop subsequent calls')


if __name__ == '__main__':
    unittest.main()
