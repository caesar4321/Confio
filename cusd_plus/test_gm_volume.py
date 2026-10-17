from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from blockchain.models import SponsoredBatch
from users.models import User
from users.models_unified import UnifiedTransactionTable

from . import gm_volume


class TradedVolumeTests(TestCase):
    def setUp(self):
        cache.delete(gm_volume.CACHE_KEY)
        self.user = User.objects.create_user(username='vol-1', email='vol1@example.com', firebase_uid='vol-1')

    def trade(self, kind, amount, status='confirmed', n=[0]):
        n[0] += 1
        batch = SponsoredBatch.objects.create(user=self.user, user_bsc_address='0x' + '1' * 40, kind=kind,
                                              status=status, tx_hash=f'0x{n[0]:064x}', calls_json='[]', num_calls=1, source_id=n[0], gas_limit=1, max_fee_wei='1', client_request_id=f'vol-{n[0]}')
        return UnifiedTransactionTable.objects.create(
            transaction_type='send', amount=amount, token_type='CUSD_PLUS', status='CONFIRMED',
            transaction_date=timezone.now(), sponsored_batch=batch)

    def test_sums_settled_buys_and_sales_only(self):
        self.trade('stock_buy', '10.5')
        self.trade('stock_sell', '4.25')
        self.trade('stock_buy', '100', status='sent')  # not final
        hidden = self.trade('stock_buy', '7')
        hidden.deleted_at = timezone.now()
        hidden.save(update_fields=['deleted_at'])
        self.assertAlmostEqual(gm_volume.traded_usd(), 14.75)

    def test_nothing_traded_reads_zero(self):
        self.assertEqual(gm_volume.traded_usd(), 0.0)
