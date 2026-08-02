"""Notification copy must never show a database value to a person.

Written after a real payroll payout pushed

    "Enviaste 1.089 CUSD_PLUS a Julian Moon"

— the wire token AND an unrounded DecimalField(decimal_places=6), in a
sentence a user reads.

    myvenv/bin/python manage.py test notifications.test_token_display
"""
from decimal import Decimal

from django.test import SimpleTestCase

from notifications.token_display import TOKEN_LABELS, amount_str, token_label


class TokenLabelTests(SimpleTestCase):
    def test_the_token_that_leaked(self):
        self.assertEqual(token_label('CUSD_PLUS'), 'cUSD+')

    def test_every_token_the_models_can_store_has_a_label(self):
        """The old per-site maps knew only CUSD, so each new token silently
        leaked the moment it was added to a model's choices."""
        from payroll.models import PayrollRun
        for wire, _human in PayrollRun.TOKEN_TYPES:
            self.assertIn(wire, TOKEN_LABELS, f'{wire} would reach a user raw')
        # The ones whose wire value is NOT how a person writes it. CONFIO,
        # USDT and USDC are already their own symbols and pass through
        # unchanged by design.
        self.assertEqual(token_label('CUSD'), 'cUSD')
        self.assertEqual(token_label('CUSD_PLUS'), 'cUSD+')

    def test_unknown_token_passes_through_rather_than_vanishing(self):
        self.assertEqual(token_label('SOMETHING_NEW'), 'SOMETHING_NEW')

    def test_applying_twice_is_safe(self):
        self.assertEqual(token_label(token_label('CUSD_PLUS')), 'cUSD+')

    def test_empty_is_empty_not_none(self):
        self.assertEqual(token_label(None), '')
        self.assertEqual(token_label(''), '')


class AmountStringTests(SimpleTestCase):
    def test_the_amount_that_leaked(self):
        """gross_amount is a DecimalField(decimal_places=6); nobody writes a
        wage as 1.089000."""
        self.assertEqual(amount_str(Decimal('1.089000')), '1.09')

    def test_trailing_zeros_are_trimmed(self):
        self.assertEqual(amount_str(Decimal('5.00')), '5')
        self.assertEqual(amount_str(Decimal('5.50')), '5.5')

    def test_none_does_not_crash_the_copy(self):
        self.assertEqual(amount_str(None), '0')

    def test_a_garbage_value_never_raises(self):
        """A notification must not fail to send because a number was odd."""
        self.assertEqual(amount_str('not-a-number'), 'not-a-number')
