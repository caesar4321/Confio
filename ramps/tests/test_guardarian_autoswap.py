from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from conversion.models import Conversion
from ramps.models import RampTransaction
from ramps.signals import (
    GUARDARIAN_AUTOSWAP_FAILED_RETRYABLE,
    GUARDARIAN_WAITING_FOR_AUTOSWAP,
)
from usdc_transactions.models import USDCDeposit
from users.models import Account, User


class GuardarianAutoSwapReconciliationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='ramp-user',
            email='ramp@example.com',
            password='password123',
            firebase_uid='uid-ramp-user',
        )
        self.account = Account.objects.create(
            user=self.user,
            account_type='personal',
            account_index=0,
            algorand_address='D' * 58,
        )

    def _create_deposit(self, amount=Decimal('19.036097')):
        return USDCDeposit.objects.create(
            actor_user=self.user,
            actor_type='user',
            actor_display_name='Personal - ramp-user',
            actor_address=self.account.algorand_address,
            amount=amount,
            source_address='S' * 58,
            status='COMPLETED',
        )

    def _create_guardarian_ramp(self, deposit, amount=Decimal('19.036097')):
        ramp = RampTransaction.objects.create(
            provider='guardarian',
            direction='on_ramp',
            status='PROCESSING',
            status_detail=GUARDARIAN_WAITING_FOR_AUTOSWAP,
            provider_order_id='4517873549',
            actor_user=self.user,
            actor_type='user',
            actor_display_name='Ramp User',
            actor_address=self.account.algorand_address,
            fiat_currency='USD',
            fiat_amount=Decimal('20.000000'),
            crypto_currency='USDC',
            crypto_amount_actual=amount,
            final_currency='CUSD',
            final_amount=amount,
            usdc_deposit=deposit,
        )
        RampTransaction.objects.filter(pk=ramp.pk).update(
            created_at=timezone.now() - timedelta(days=4)
        )
        ramp.refresh_from_db()
        return ramp

    def _create_conversion(self, status='COMPLETED', amount=Decimal('19.036097')):
        return Conversion.objects.create(
            actor_user=self.user,
            actor_type='user',
            actor_display_name='Ramp User',
            actor_address=self.account.algorand_address,
            conversion_type='usdc_to_cusd',
            from_amount=amount,
            to_amount=amount,
            exchange_rate=Decimal('1.0'),
            fee_amount=Decimal('0.0'),
            status=status,
            completed_at=timezone.now() if status == 'COMPLETED' else None,
            error_message='Transaction expired or lost from pool' if status == 'FAILED' else None,
        )

    @patch('ramps.signals.emit_event')
    @patch('ramps.signals.create_notification')
    def test_completed_late_autoswap_links_and_completes_guardarian_ramp(self, *_):
        deposit = self._create_deposit()
        ramp = self._create_guardarian_ramp(deposit)
        conversion = self._create_conversion()

        ramp.refresh_from_db()
        self.assertEqual(ramp.conversion_id, conversion.id)
        self.assertEqual(ramp.status, 'COMPLETED')
        self.assertEqual(ramp.status_detail, 'conversion_completed')
        self.assertIsNotNone(ramp.completed_at)

    @patch('ramps.signals.emit_event')
    @patch('ramps.signals.create_notification')
    def test_failed_autoswap_attempt_does_not_occupy_guardarian_ramp(self, *_):
        deposit = self._create_deposit()
        ramp = self._create_guardarian_ramp(deposit)
        self._create_conversion(status='FAILED')

        ramp.refresh_from_db()
        self.assertIsNone(ramp.conversion_id)
        self.assertEqual(ramp.status, 'PROCESSING')
        self.assertEqual(ramp.status_detail, GUARDARIAN_WAITING_FOR_AUTOSWAP)

    @patch('ramps.signals.emit_event')
    @patch('ramps.signals.create_notification')
    def test_linked_failed_conversion_stays_retryable_not_provider_failed(self, *_):
        deposit = self._create_deposit()
        ramp = self._create_guardarian_ramp(deposit)
        conversion = self._create_conversion()
        ramp.refresh_from_db()

        conversion.status = 'FAILED'
        conversion.error_message = 'Transaction expired or lost from pool'
        conversion.completed_at = None
        conversion.save(update_fields=['status', 'error_message', 'completed_at', 'updated_at'])

        ramp.refresh_from_db()
        self.assertEqual(ramp.conversion_id, conversion.id)
        self.assertEqual(ramp.status, 'PROCESSING')
        self.assertEqual(ramp.status_detail, GUARDARIAN_AUTOSWAP_FAILED_RETRYABLE)
