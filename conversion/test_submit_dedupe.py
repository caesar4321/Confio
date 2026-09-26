import base64
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from conversion.models import Conversion
from conversion.ws_consumers import ConvertSessionConsumer

TXID = 'A' * 52


class SubmitDedupeTests(TestCase):
    """A double tap prepares twice; identical groups mean the second submit
    only re-sends the first transaction. It must not become a second
    conversion (prod 942/943: one US$190.70 mint counted twice)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username='dedupe', password='x')

    def _conv(self):
        return Conversion.objects.create(
            actor_user=self.user, actor_type='user', actor_display_name='Dedupe',
            actor_address='A' * 58, conversion_type='usdc_to_cusd',
            from_amount=Decimal('190.702269'), to_amount=Decimal('190.702269'),
            exchange_rate=Decimal('1'), fee_amount=Decimal('0'), status='PENDING',
        )

    def _submit(self, conv, algod):
        submit = ConvertSessionConsumer.__dict__['_submit'].func
        with patch('blockchain.algorand_client.get_algod_client', return_value=algod):
            return submit(ConvertSessionConsumer(), str(conv.internal_id),
                          [base64.b64encode(b'signed').decode()], [])

    def test_second_submit_of_same_group_retires_the_duplicate(self):
        first, second = self._conv(), self._conv()
        algod = type('Algod', (), {})()
        algod.send_raw_transaction = lambda _b64: TXID
        self.assertEqual(self._submit(first, algod), {'success': True, 'txid': TXID})

        def already(_b64):
            raise Exception(f'TransactionPool.Remember: transaction already in ledger: {TXID}')
        algod.send_raw_transaction = already
        self.assertEqual(self._submit(second, algod), {'success': True, 'txid': TXID})

        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual((first.status, first.to_transaction_hash, first.is_deleted), ('SUBMITTED', TXID, False))
        self.assertTrue(second.is_deleted)
        self.assertEqual(second.status, 'FAILED')
        self.assertEqual(second.error_message, f'duplicate_of:{first.internal_id}')
        self.assertEqual(Conversion.objects.filter(to_transaction_hash=TXID, is_deleted=False).count(), 1)

    def test_distinct_transactions_both_submit(self):
        first, second = self._conv(), self._conv()
        algod = type('Algod', (), {})()
        algod.send_raw_transaction = lambda _b64: TXID
        self._submit(first, algod)
        algod.send_raw_transaction = lambda _b64: 'B' * 52
        self._submit(second, algod)
        second.refresh_from_db()
        self.assertEqual((second.status, second.is_deleted), ('SUBMITTED', False))
