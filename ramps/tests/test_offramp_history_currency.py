import importlib
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.apps import apps
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from ramps.models import RampTransaction
from ramps.signals import _derive_final_amount, sync_unified_transaction_from_ramp
from users.models_unified import UnifiedTransactionTable


class OfframpCurrencyTests(SimpleTestCase):
    def test_provider_amount_keeps_correct_settlement_token(self):
        for destination, token in [('cusd_plus', 'USDT'), ('cusd', 'USDC')]:
            with self.subTest(destination=destination):
                ramp = SimpleNamespace(provider='koywe', direction='off_ramp',
                                       destination=destination,
                                       final_amount=Decimal('54.806052'))
                self.assertEqual(_derive_final_amount(ramp), (ramp.final_amount, token))


class OfframpCurrencyRepairTests(TestCase):
    def make_row(self, *, destination='cusd_plus', direction='off_ramp',
                 provider='koywe', final_amount=Decimal('54.806052'),
                 token='USDC', hidden=False):
        ramp = RampTransaction(provider=provider, direction=direction,
                               destination=destination, final_amount=final_amount,
                               final_currency='USDT BSC', status='PENDING')
        RampTransaction.objects.bulk_create([ramp])
        ledger = UnifiedTransactionTable.objects.create(
            ramp_transaction=ramp, transaction_type='ramp', token_type=token,
            amount='54.806052', status='PENDING', transaction_date=timezone.now(),
            deleted_at=timezone.now() if hidden else None,
        )
        return ramp, ledger

    def test_writer_persists_usdt_and_provider_amount(self):
        ramp, ledger = self.make_row()
        sync_unified_transaction_from_ramp(ramp)
        ledger.refresh_from_db()
        self.assertEqual(ledger.token_type, 'USDT')
        self.assertEqual(Decimal(ledger.amount), ramp.final_amount)

    def test_migration_repairs_only_labels_and_is_idempotent(self):
        affected = [self.make_row()[1], self.make_row(hidden=True)[1]]
        controls = [
            self.make_row(destination='cusd')[1],
            self.make_row(direction='on_ramp')[1],
            self.make_row(provider='guardarian')[1],
            self.make_row(final_amount=None)[1],
            self.make_row(token='CUSD_PLUS')[1],
        ]
        before = {r.pk: UnifiedTransactionTable.objects.filter(pk=r.pk).values().get()
                  for r in affected + controls}
        repair = importlib.import_module(
            'ramps.migrations.0018_repair_bsc_offramp_history_currency').repair_currency
        with mock.patch('ramps.signals._notify_ramp_status') as notify:
            repair(apps, SimpleNamespace(connection=connection))
            repair(apps, SimpleNamespace(connection=connection))
            notify.assert_not_called()
        for row in affected + controls:
            expected = before[row.pk]
            if row in affected:
                expected['token_type'] = 'USDT'
            self.assertEqual(
                UnifiedTransactionTable.objects.filter(pk=row.pk).values().get(), expected)
