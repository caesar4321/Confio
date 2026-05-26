from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from conversion.models import Conversion
from blockchain.models import PendingAutoSwap
from ramps.models import RampTransaction
from ramps.signals import (
    GUARDARIAN_AUTOSWAP_FAILED_RETRYABLE,
    GUARDARIAN_WAITING_FOR_AUTOSWAP,
)
from usdc_transactions.models import GuardarianTransaction, USDCDeposit, USDCWithdrawal
from users.models_unified import UnifiedTransactionTable
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

    def _create_guardarian_transaction(self, guardarian_id, deposit, amount):
        return GuardarianTransaction.objects.create(
            guardarian_id=guardarian_id,
            user=self.user,
            from_currency='USD',
            from_amount=Decimal('20.000000'),
            to_currency='USDC',
            to_amount_estimated=amount,
            to_amount_actual=amount,
            network='ALGO',
            status='finished',
            onchain_deposit=deposit,
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

    @patch('ramps.signals.emit_event')
    @patch('ramps.signals.create_notification')
    def test_autoswap_does_not_steal_prior_guardarian_ramp_by_address_only(self, *_):
        first_deposit = self._create_deposit(amount=Decimal('71.382067'))
        prior_ramp = self._create_guardarian_ramp(first_deposit, amount=Decimal('71.382067'))
        prior_ramp.provider_order_id = '6407224612'
        prior_ramp.save(update_fields=['provider_order_id', 'updated_at'])

        conversion = self._create_conversion(amount=Decimal('70.927202'))

        prior_ramp.refresh_from_db()
        self.assertIsNone(prior_ramp.conversion_id)
        self.assertEqual(prior_ramp.final_amount, Decimal('71.382067'))
        self.assertEqual(conversion.ramp_transactions.count(), 0)

    @patch('ramps.signals.emit_event')
    @patch('ramps.signals.create_notification')
    def test_guardarian_sync_uses_completed_deposit_pending_autoswap(self, *_):
        deposit = self._create_deposit(amount=Decimal('70.927202'))
        conversion = self._create_conversion(amount=Decimal('70.927202'))
        PendingAutoSwap.objects.create(
            account=self.account,
            actor_user=self.user,
            actor_type='user',
            actor_address=self.account.algorand_address,
            asset_type='USDC',
            amount_micro=70927202,
            amount_decimal=Decimal('70.927202'),
            status='COMPLETED',
            usdc_deposit=deposit,
            conversion=conversion,
            completed_at=timezone.now(),
        )

        self._create_guardarian_transaction('5455572678', deposit, Decimal('70.927201'))

        ramp = RampTransaction.objects.get(provider_order_id='5455572678')
        self.assertEqual(ramp.conversion_id, conversion.id)
        self.assertEqual(ramp.status, 'COMPLETED')
        self.assertEqual(ramp.status_detail, 'conversion_completed')
        self.assertEqual(ramp.final_amount, Decimal('70.927202'))

    @patch('ramps.signals.emit_event')
    @patch('ramps.signals.create_notification')
    def test_failed_koywe_off_ramp_conversion_marks_ramp_and_withdrawal_failed(self, *_):
        conversion = Conversion.objects.create(
            actor_user=self.user,
            actor_type='user',
            actor_display_name='Ramp User',
            actor_address=self.account.algorand_address,
            conversion_type='cusd_to_usdc',
            from_amount=Decimal('23.080000'),
            to_amount=Decimal('23.080000'),
            exchange_rate=Decimal('1.0'),
            fee_amount=Decimal('0.0'),
            status='PENDING_SIG',
        )
        withdrawal = USDCWithdrawal.objects.create(
            actor_user=self.user,
            actor_type='user',
            actor_display_name='Ramp User',
            actor_address=self.account.algorand_address,
            amount=Decimal('23.080000'),
            destination_address='B' * 58,
            status='PENDING',
        )
        ramp = RampTransaction.objects.create(
            provider='koywe',
            direction='off_ramp',
            status='PENDING',
            status_detail='waiting',
            provider_order_id='5633606c-3df4-49a3-8cc5-9d8d5e8ebbad',
            actor_user=self.user,
            actor_type='user',
            actor_display_name='Ramp User',
            actor_address=self.account.algorand_address,
            fiat_currency='ARS',
            fiat_amount=Decimal('33538.430000'),
            crypto_currency='USDC Algorand',
            crypto_amount_actual=Decimal('23.080000'),
            final_currency='USDC Algorand',
            final_amount=Decimal('23.080000'),
            usdc_withdrawal=withdrawal,
            conversion=conversion,
        )

        conversion.status = 'FAILED'
        conversion.error_message = 'signature_verification_failed:index=1'
        conversion.save(update_fields=['status', 'error_message', 'updated_at'])

        ramp.refresh_from_db()
        withdrawal.refresh_from_db()
        self.assertEqual(ramp.status, 'FAILED')
        self.assertEqual(ramp.status_detail, 'conversion_failed')
        self.assertEqual(ramp.final_currency, 'USDC Algorand')
        unified = UnifiedTransactionTable.objects.get(ramp_transaction=ramp)
        self.assertEqual(unified.status, 'FAILED')
        self.assertEqual(unified.token_type, 'USDC ALGORAND')
        self.assertEqual(withdrawal.status, 'FAILED')
        self.assertEqual(withdrawal.error_message, 'signature_verification_failed:index=1')
