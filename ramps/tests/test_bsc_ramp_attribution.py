from contextlib import nullcontext
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from django.utils import timezone

from ramps.signals import (
    _attributed_bsc_ramps,
    _bsc_ramp_net_allocations,
    _derive_final_amount,
    attribute_bsc_ramp_arrival,
)


class BscRampAttributionTests(SimpleTestCase):
    ADDRESS = '0x' + '12' * 20
    TX_HASH = '0x' + 'ab' * 32

    def test_signal_derivation_agrees_with_koywe_for_bsc_cusd(self):
        conversion = SimpleNamespace(
            conversion_type='usdt_to_cusd',
            to_amount=Decimal('99.1'),
            from_amount=Decimal('100'),
        )
        ramp = SimpleNamespace(
            provider='koywe', direction='on_ramp', conversion_id=1,
            conversion=conversion, crypto_amount_actual=None,
            crypto_amount_estimated=None, final_currency='USDT BSC',
        )
        self.assertEqual(
            _derive_final_amount(ramp),
            (Decimal('99.1'), 'CUSD_BSC'),
        )

    def test_signal_derivation_agrees_with_koywe_for_cusd_plus(self):
        conversion = SimpleNamespace(
            conversion_type='to_savings',
            to_amount=Decimal('99.1'),
            from_amount=Decimal('100'),
        )
        ramp = SimpleNamespace(
            provider='koywe', direction='on_ramp', conversion_id=1,
            conversion=conversion, crypto_amount_actual=None,
            crypto_amount_estimated=None, final_currency='USDT BSC',
        )
        self.assertEqual(
            _derive_final_amount(ramp),
            (Decimal('99.1'), 'CUSD+'),
        )

    @mock.patch('ramps.signals.RampTransaction.objects')
    def test_arrival_persists_source_transfer_even_when_estimate_differs(self, objects):
        ramp = SimpleNamespace(
            metadata={'bsc_provider_transfer_tx_hash': self.TX_HASH},
            provider='guardarian',
            crypto_amount_actual=None,
            crypto_amount_estimated=Decimal('99.500000'),
            save=mock.Mock(),
        )
        objects.select_for_update.return_value.filter.return_value.exclude.return_value.order_by.return_value = [ramp]

        with mock.patch('ramps.signals.transaction.atomic', return_value=nullcontext()):
            found = attribute_bsc_ramp_arrival(
                actor_address=self.ADDRESS,
                amount=Decimal('99.480000'),
                tx_hash=self.TX_HASH,
                log_index=7,
            )

        self.assertIs(found, ramp)
        self.assertEqual(ramp.crypto_amount_actual, Decimal('99.480000'))
        self.assertEqual(ramp.metadata['bsc_arrival_tx_hash'], self.TX_HASH)
        self.assertEqual(ramp.metadata['bsc_arrival_log_index'], 7)
        self.assertEqual(ramp.metadata['bsc_arrival_amount'], '99.480000')
        ramp.save.assert_called_once()

    @mock.patch('ramps.signals.RampTransaction.objects')
    def test_one_foreground_mint_can_link_multiple_attributed_orders(self, objects):
        now = timezone.now()
        first = SimpleNamespace(metadata={'bsc_arrival_amount': '10.000000'})
        second = SimpleNamespace(metadata={'bsc_arrival_amount': '20.000000'})
        objects.select_for_update.return_value.filter.return_value.exclude.return_value.order_by.return_value = [first, second]
        conversion = SimpleNamespace(
            status='COMPLETED',
            conversion_type='to_savings',
            from_amount=Decimal('30.000000'),
            to_amount=Decimal('29.730000'),
            gross_amount_exact=Decimal('30.000000000000000000'),
            net_amount_exact=Decimal('29.730000000000000000'),
            actor_address=self.ADDRESS,
            user_bsc_address=self.ADDRESS,
            created_at=now - timedelta(minutes=1),
        )

        ramps = _attributed_bsc_ramps(conversion)
        self.assertEqual(ramps, [first, second])
        self.assertEqual(
            _bsc_ramp_net_allocations(conversion, ramps),
            [Decimal('9.910000'), Decimal('19.820000')],
        )

    @mock.patch('ramps.signals.RampTransaction.objects')
    def test_partial_prefix_is_not_misattributed_to_larger_conversion(self, objects):
        ramp = SimpleNamespace(metadata={'bsc_arrival_amount': '540.394125'})
        objects.select_for_update.return_value.filter.return_value.exclude.return_value.order_by.return_value = [ramp]
        conversion = SimpleNamespace(
            status='COMPLETED', conversion_type='usdt_to_cusd',
            from_amount=Decimal('643.300567'), actor_address=self.ADDRESS,
            user_bsc_address=self.ADDRESS, created_at=timezone.now(),
        )

        self.assertEqual(_attributed_bsc_ramps(conversion), [])

    @mock.patch('ramps.signals.RampTransaction.objects')
    def test_same_amount_unproven_wallet_transfer_is_not_a_ramp(self, objects):
        ramp = SimpleNamespace(
            metadata={}, provider='koywe', crypto_amount_actual=None,
            crypto_amount_estimated=Decimal('100.000000'), save=mock.Mock(),
        )
        objects.select_for_update.return_value.filter.return_value.exclude.return_value.order_by.return_value = [ramp]

        with mock.patch('ramps.signals.transaction.atomic', return_value=nullcontext()):
            found = attribute_bsc_ramp_arrival(
                actor_address=self.ADDRESS,
                amount=Decimal('100.000000'),
                tx_hash=self.TX_HASH,
                log_index=1,
                sender_address='0x' + '99' * 20,
            )

        self.assertIsNone(found)
        ramp.save.assert_not_called()

    @mock.patch('ramps.signals.RampTransaction.objects')
    @mock.patch('ramps.signals.settings.KOYWE_BSC_SETTLEMENT_ADDRESSES',
                ('0x' + '77' * 20,))
    def test_explicit_hash_mismatch_cannot_fall_back_to_sender(self, objects):
        ramp = SimpleNamespace(
            metadata={'provider_transfer_tx_hash': '0x' + 'cd' * 32},
            provider='koywe', crypto_amount_actual=None,
            crypto_amount_estimated=Decimal('100'), save=mock.Mock(),
        )
        objects.select_for_update.return_value.filter.return_value.exclude.return_value.order_by.return_value = [ramp]
        with mock.patch('ramps.signals.transaction.atomic', return_value=nullcontext()):
            found = attribute_bsc_ramp_arrival(
                actor_address=self.ADDRESS, amount=Decimal('100'),
                tx_hash=self.TX_HASH, log_index=1,
                sender_address='0x' + '77' * 20,
            )
        self.assertIsNone(found)
        ramp.save.assert_not_called()

    @mock.patch('ramps.signals.RampTransaction.objects')
    @mock.patch('ramps.signals.settings.KOYWE_BSC_SETTLEMENT_ADDRESSES',
                ('0x' + '77' * 20,))
    def test_sender_only_proof_fails_closed_when_orders_are_ambiguous(self, objects):
        ramps = [
            SimpleNamespace(
                metadata={}, provider='koywe', crypto_amount_actual=None,
                crypto_amount_estimated=Decimal('100'), save=mock.Mock(),
            ) for _ in range(2)
        ]
        objects.select_for_update.return_value.filter.return_value.exclude.return_value.order_by.return_value = ramps
        with mock.patch('ramps.signals.transaction.atomic', return_value=nullcontext()):
            found = attribute_bsc_ramp_arrival(
                actor_address=self.ADDRESS, amount=Decimal('100'),
                tx_hash=self.TX_HASH, log_index=1,
                sender_address='0x' + '77' * 20,
            )
        self.assertIsNone(found)
        for ramp in ramps:
            ramp.save.assert_not_called()
