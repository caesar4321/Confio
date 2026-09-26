from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from blockchain.tasks import scan_outbound_confirmations
from conversion.models import Conversion


class OutboundReaperScopeTests(TestCase):
    """The algod reaper must never judge a BSC conversion (conversion 961:
    a confirmed cUSD+ subscribe reaped to FAILED because algod can't see 0x
    hashes)."""

    def setUp(self):
        cache.delete('locks:scan_outbound_confirmations')
        self.user = get_user_model().objects.create_user(username='reaper', password='x')

    def _conv(self, tx_hash):
        conv = Conversion.objects.create(
            actor_user=self.user, actor_type='user', conversion_type='to_savings',
            from_amount=Decimal('2.65'), to_amount=Decimal('2.65'), exchange_rate=Decimal('1'),
            fee_amount=Decimal('0'), status='SUBMITTED', to_transaction_hash=tx_hash)
        Conversion.objects.filter(pk=conv.pk).update(updated_at=timezone.now() - timedelta(minutes=10))
        return conv

    def test_bsc_hash_is_left_to_the_bsc_confirmer_while_algorand_is_still_reaped(self):
        bsc, algo = self._conv('0x' + '1' * 64), self._conv('A' * 52)
        client = mock.Mock()
        client.algod.pending_transaction_info.side_effect = Exception('not found')
        with mock.patch('blockchain.tasks.AlgorandClient', return_value=client):
            scan_outbound_confirmations.run.__wrapped__()
        bsc.refresh_from_db(); algo.refresh_from_db()
        self.assertEqual(bsc.status, 'SUBMITTED')
        self.assertEqual(algo.status, 'FAILED')
