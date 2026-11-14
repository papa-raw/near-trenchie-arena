"""A wallet may claim more held premints; concurrent requests and the claim rate remain bounded."""
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near' / 'arena')]
from near.chain import identity, test_identity_desk as fixture


class MultipleClaims(unittest.TestCase):
    def test_an_owner_claims_another_premint_after_a_host_restart_and_still_has_a_rate_limit(self):
        sk, pk = fixture.wallet_key()
        nft = fixture.premint_nft(*[(f'preset-{i}-00', f'preset-{i}') for i in range(1, 6)])
        with tempfile.TemporaryDirectory() as state:
            desk, *_ = fixture.desk(nft, fixture.inventory(), {fixture.PLAYER: {pk}}, state_dir=state)
            first = fixture.Page(desk, sk, pk).do('claim', {'preset': 'hunter-lunge'})['token_id']
            again, *_ = fixture.desk(nft, fixture.inventory(), {fixture.PLAYER: {pk}}, state_dir=state)
            page = fixture.Page(again, sk, pk)
            second = page.do('claim', {'preset': 'survivor-beam'})['token_id']
            self.assertNotEqual(first, second)
            self.assertEqual(nft.tokens[first]['owner'], fixture.PLAYER)
            self.assertEqual(nft.tokens[second]['owner'], fixture.PLAYER)
            for preset in ('brawler-swing', 'looter-lob'):
                page.do('claim', {'preset': preset})
            page.do('claim', {'preset': 'brawler-zap'})
            self.assertEqual(identity.LIMITS['claim'], (20, 3600))
            # Four requests reached this restarted desk; fill the remaining hourly allowance.
            for _ in range(16):
                again.limit(page.address, 'claim')
            with self.assertRaisesRegex(identity.IdentityError, 'too many claim requests'):
                page.do('claim', {'preset': 'brawler-zap'})

    def test_concurrent_second_claims_still_transfer_only_one_token(self):
        sk, pk = fixture.wallet_key()
        nft = fixture.premint_nft(('preset-1-00', 'preset-1'), ('preset-2-00', 'preset-2'), ('preset-3-00', 'preset-3'))
        desk, chain, *_ = fixture.desk(nft, fixture.inventory(), {fixture.PLAYER: {pk}})
        page = fixture.Page(desk, sk, pk)
        page.do('claim', {'preset': 'brawler-swing'})
        chain.call_delay = 0.1
        envelopes = [page.env('claim', {'preset': preset}) for preset in ('hunter-lunge', 'survivor-beam')]
        results = []

        def claim(envelope):
            try:
                results.append(desk.route('claim', envelope)['token_id'])
            except identity.IdentityError as error:
                results.append(str(error))

        threads = [threading.Thread(target=claim, args=(envelope,)) for envelope in envelopes]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(token['owner'] == fixture.PLAYER for token in nft.tokens.values()), 2, results)
        self.assertEqual(sum('still running' in result for result in results), 1, results)
        self.assertEqual(len([call for call in chain.calls if call[2] == 'claim']), 2)


if __name__ == '__main__':
    unittest.main()
