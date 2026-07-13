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

from ramps.koywe_client import KoyweClient, KoyweMaximumAmountError, KoyweMinimumAmountError


RATE = Decimal('1500')  # 1 USDC -> 1500 ARS, before the flat fee
FLAT_FEE = Decimal('3000')  # flat fee in ARS; dominates small quotes
FIAT_MIN = Decimal('24000')
FIAT_MAX = Decimal('8500000')


def _make_fake_preview_quote(fiat_min=FIAT_MIN, fiat_max=FIAT_MAX):
    """Mirrors real Koywe quoting: out = rate*x - flat_fee, and the fiat
    OUTPUT (which can be negative) is validated against the pair min/max —
    rejection messages carry fiat-output values, never crypto amounts."""
    def fake(*, symbol_in, symbol_out, amount):
        amount_out = Decimal(amount) * RATE - FLAT_FEE
        if amount_out < fiat_min:
            raise KoyweMinimumAmountError(
                f'Currency amount is less than the minimun available for ARS. {amount_out} < {fiat_min}',
                currency='ARS',
                actual=str(amount_out),
                minimum=str(fiat_min),
            )
        if amount_out > fiat_max:
            raise KoyweMaximumAmountError(
                f'Currency amount exceeds the maximun available for ARS. {amount_out} > {fiat_max}',
                currency='ARS',
                actual=str(amount_out),
                maximum=str(fiat_max),
            )
        return {'amountIn': str(amount), 'amountOut': str(amount_out)}
    return fake


_fake_preview_quote = _make_fake_preview_quote()

# True crypto boundaries under the affine model: x = (out + fee) / rate
TRUE_MIN_CRYPTO = (FIAT_MIN + FLAT_FEE) / RATE  # 18
TRUE_MAX_CRYPTO = (FIAT_MAX + FLAT_FEE) / RATE  # ~5668.67


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
                bias='at_most',
            )
        # Must be accepted by Koywe (not past the boundary) and close to it.
        self.assertLessEqual(estimate * RATE - FLAT_FEE, FIAT_MAX)
        self.assertGreater(estimate, TRUE_MAX_CRYPTO * Decimal('0.99'))

    def test_dynamic_limits_survive_max_rejections(self):
        pair_limits = {'min': str(FIAT_MIN), 'max': str(FIAT_MAX)}
        with mock.patch.object(KoyweClient, '_get_pair_limits', return_value=pair_limits), \
                mock.patch.object(KoyweClient, 'create_preview_quote', side_effect=_fake_preview_quote):
            limits = self.client.get_dynamic_ramp_limits(fiat_symbol='ARS')

        self.assertEqual(limits['on_ramp_min_amount'], FIAT_MIN)
        self.assertEqual(limits['on_ramp_max_amount'], FIAT_MAX)
        self.assertLess(abs(limits['off_ramp_min_amount'] - TRUE_MIN_CRYPTO), TRUE_MIN_CRYPTO * Decimal('0.05'))
        self.assertLess(abs(limits['off_ramp_max_amount'] - TRUE_MAX_CRYPTO), TRUE_MAX_CRYPTO * Decimal('0.05'))

    def test_dynamic_limits_stay_within_quote_call_budget(self):
        """Each quote call is a sequential HTTP round trip made inline on a
        cache miss; the old bracket+bisection estimator issued ~38 of them,
        which took rampAvailability (Recargar/Retiro screens) past 10s."""
        pair_limits = {'min': str(FIAT_MIN), 'max': str(FIAT_MAX)}
        quote_mock = mock.Mock(side_effect=_fake_preview_quote)
        with mock.patch.object(KoyweClient, '_get_pair_limits', return_value=pair_limits), \
                mock.patch.object(KoyweClient, 'create_preview_quote', quote_mock):
            self.client.get_dynamic_ramp_limits(fiat_symbol='ARS')

        self.assertLessEqual(quote_mock.call_count, 14)

    def test_min_estimate_covers_target(self):
        """The advertised off-ramp minimum must actually deliver the fiat
        minimum when quoted, otherwise users at the shown min get rejected."""
        with mock.patch.object(KoyweClient, 'create_preview_quote', side_effect=_fake_preview_quote):
            estimate = self.client._estimate_crypto_amount_for_fiat_output(
                crypto_symbol='USDC Algorand',
                fiat_symbol='ARS',
                target_amount=FIAT_MIN,
            )
        # Advertised minimum must actually deliver the target when quoted.
        self.assertGreaterEqual(estimate * RATE - FLAT_FEE, FIAT_MIN)
        self.assertLess(estimate, TRUE_MIN_CRYPTO * Decimal('1.05'))

    def test_min_estimate_survives_flat_fee_dominated_quotes(self):
        """ARS/BOB regression: with a small fiat minimum, the naive
        rate-converted probe quotes a NEGATIVE output (flat fee dominates)
        and Koywe rejects it. The estimator must recover from the rejection
        message (which carries the real output) instead of exhausting its
        probe budget below the boundary and failing the whole limits fetch."""
        pair_min = Decimal('100')  # sandbox ARS: min 100, true answer ~2.07 USDC
        fake = _make_fake_preview_quote(fiat_min=pair_min)
        with mock.patch.object(KoyweClient, 'create_preview_quote', side_effect=fake):
            estimate = self.client._estimate_crypto_amount_for_fiat_output(
                crypto_symbol='USDC Algorand',
                fiat_symbol='ARS',
                target_amount=pair_min,
            )
        true_min = (pair_min + FLAT_FEE) / RATE  # ~2.07
        self.assertGreaterEqual(estimate * RATE - FLAT_FEE, pair_min)
        self.assertLess(estimate, true_min * Decimal('1.05'))

    def test_rejection_parsing_keeps_negative_outputs_signed(self):
        """Live Koywe rejections quote the real (possibly negative) output:
        'less than the minimun available for ARS. -2962.91 < 100'. Dropping
        the sign feeds a garbage point into the estimator's secant model,
        which broke the limits fetch for every currency."""
        import json
        from unittest.mock import Mock
        response = Mock()
        response.ok = False
        response.json.return_value = {
            'message': 'Currency amount is less than the minimun available for ARS. -2962.91 < 100',
        }
        with self.assertRaises(KoyweMinimumAmountError) as ctx:
            self.client._parse_response(response, 'failed')
        self.assertEqual(ctx.exception.actual, '-2962.91')
        self.assertEqual(ctx.exception.minimum, '100')
