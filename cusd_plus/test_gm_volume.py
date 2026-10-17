from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from blockchain.models import SponsoredBatch
from users.models import User
from users.models_unified import UnifiedTransactionTable

from . import gm_volume


class TradedVolumeTests(TestCase):
    def setUp(self):
        from . import gm_trading_stats
        for key in (gm_trading_stats.CACHE_KEY, gm_trading_stats.FRESH_KEY, gm_trading_stats.LOCK_KEY):
            cache.delete(key)
        self.user = User.objects.create_user(username='vol-1', email='vol1@example.com', firebase_uid='vol-1')

    def trade(self, kind, amount, status='confirmed', wallet=None, n=[0]):
        n[0] += 1
        batch = SponsoredBatch.objects.create(user=self.user, user_bsc_address=wallet or f'0x{n[0]:040x}', kind=kind,
                                              status=status, tx_hash=f'0x{n[0]:064x}', calls_json='[]', num_calls=1, source_id=n[0], gas_limit=1, max_fee_wei='1', client_request_id=f'vol-{n[0]}')
        return UnifiedTransactionTable.objects.create(
            transaction_type='send', amount=amount, token_type='CUSD_PLUS', status='CONFIRMED',
            transaction_date=timezone.now(), sponsored_batch=batch)

    def test_sums_settled_buys_and_sales_only(self):
        self.trade('stock_buy', '10.5')
        self.trade('stock_sell', '4.25')
        self.trade('stock_buy', '1')  # a third trader: above the privacy floor
        self.trade('stock_buy', '100', status='sent')  # not final
        hidden = self.trade('stock_buy', '7')
        hidden.deleted_at = timezone.now()
        hidden.save(update_fields=['deleted_at'])
        self.assertAlmostEqual(gm_volume.traded_usd(), 15.75)

    def test_below_three_traders_home_states_nothing(self):
        self.trade('stock_buy', '5', wallet='0x' + 'a' * 40)
        self.trade('stock_buy', '5', wallet='0x' + 'b' * 40)
        self.assertIsNone(gm_volume.traded_usd())

    def test_no_total_while_the_shared_snapshot_is_being_built(self):
        from . import gm_trading_stats

        for i in range(3):
            self.trade('stock_buy', '2')
        cache.add(gm_trading_stats.LOCK_KEY, 'someone-else', 60)
        self.assertIsNone(gm_volume.traded_usd())
