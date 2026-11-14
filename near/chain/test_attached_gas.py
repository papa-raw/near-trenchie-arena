"""Small results batches must fit the operator's prepaid gas balance; larger batches retain their budget."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near' / 'arena')]
from near.chain import test_chain, writer


class AttachedGas(unittest.TestCase):
    def test_small_batch_and_resolver_transactions_attach_sized_gas(self):
        # Baseline: post_batch attaches 300 Tgas even for two empty segments; resolver calls attach 30.
        with tempfile.TemporaryDirectory() as tmp:
            rig = test_chain.Rig(tmp, batch_segments=2, commit_size=5, lookahead=2)
            rig.arena()
            rig.run_segments(2)
            rig.writer.process()
            gas = [(action['method'], action['gas']) for tx in rig.rpc.sent for action in tx['actions']]
            posts = [value for method, value in gas if method == 'post_batch']
            self.assertEqual(posts, [60 * 10**12])
            for method in ('close_batch', 'resolve'):
                self.assertEqual([value for name, value in gas if name == method], [30 * 10**12])
            self.assertEqual(rig.batches()[0]['status'], 'applied')
            self.assertEqual(rig.batches()[0]['resolve']['status'], 'resolved')

    def test_larger_batch_budget_keeps_the_existing_worst_case_margin(self):
        for segments, rows in ((20, 0), (20, 14), (20, 72), (30, 107), (60, 100)):
            with self.subTest(segments=segments, rows=rows):
                estimate = writer.estimate_tgas(segments, rows)
                gas = writer.post_tgas(segments, rows)
                self.assertIsInstance(gas, int)
                self.assertGreaterEqual(gas, 60)
                self.assertLessEqual(gas, 300)
                self.assertGreaterEqual(gas * 0.9, estimate)

    def test_every_admitted_size_leaves_the_nft_hop_ten_tgas_of_headroom(self):
        # G0 measured arena fit and worst-case NFT bag rewrite, plus the contract's static 10 Tgas callback.
        for segments in range(1, 61):
            for rows in range(max(option['max_rows'] for option in writer.G0_OPTIONS.values()) + 1):
                if writer.estimate_tgas(segments, rows) > writer.SAFE_TGAS:
                    continue
                gas = writer.post_tgas(segments, rows)
                nft_available = gas - (4.4 + 0.48 * segments) - 10
                self.assertGreaterEqual(nft_available, 2.24 * rows + 10, (segments, rows, gas))


if __name__ == '__main__':
    unittest.main()
