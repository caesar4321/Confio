"""Regression tests for dynamic Koywe ramp limits.

Koywe rejects preview quotes whose fiat output exceeds the pair maximum.
The off-ramp limit estimator deliberately probes above the target (1.25x),
so those rejections must be treated as an upper bound, not a fatal error —
otherwise get_dynamic_ramp_limits raises for every country and the API
falls back to the stale static minimums in ramps/koywe.py.
"""
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from ramps.koywe_client import KoyweClient, KoyweMaximumAmountError


RATE = Decimal('1500')  # 1 USDC -> 1500 ARS
FIAT_MIN = Decimal('24000')
FIAT_MAX = Decimal('8500000')


def _fake_preview_quote(*, symbol_in, symbol_out, amount):
    amount_out = Decimal(amount) * RATE
    if amount_out > FIAT_MAX:
        raise KoyweMaximumAmountError(
            f'Currency amount exceeds the maximun available for ARS. {amount_out} > {FIAT_MAX}',
            currency='ARS',
            actual=str(amount_out),
            maximum=str(FIAT_MAX),
        )
    return {'amountIn': str(amount), 'amountOut': str(amount_out)}


class DynamicRampLimitsTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.client = KoyweClient()

    def test_max_rejection_is_treated_as_upper_bound(self):
        with mock.patch.object(KoyweClient, 'create_preview_quote', side_effect=_fake_preview_quote):
            estimate = self.client._estimate_crypto_amount_for_fiat_output(
                crypto_symbol='USDC Algorand',
                fiat_symbol='ARS',
                target_amount=FIAT_MAX,
            )
        expected = FIAT_MAX / RATE  # ~5666.67 USDC
        self.assertLess(abs(estimate - expected), Decimal('1'))

    def test_dynamic_limits_survive_max_rejections(self):
        pair_limits = {'min': str(FIAT_MIN), 'max': str(FIAT_MAX)}
        with mock.patch.object(KoyweClient, '_get_pair_limits', return_value=pair_limits), \
                mock.patch.object(KoyweClient, 'create_preview_quote', side_effect=_fake_preview_quote):
            limits = self.client.get_dynamic_ramp_limits(fiat_symbol='ARS')

        self.assertEqual(limits['on_ramp_min_amount'], FIAT_MIN)
        self.assertEqual(limits['on_ramp_max_amount'], FIAT_MAX)
        self.assertLess(abs(limits['off_ramp_min_amount'] - FIAT_MIN / RATE), Decimal('1'))
        self.assertLess(abs(limits['off_ramp_max_amount'] - FIAT_MAX / RATE), Decimal('1'))
