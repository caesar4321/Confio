"""One Conversion model, two rails — the invariants that keep them apart.

The savings saga (BSC) and the one-shot swap (Algorand) now share a model,
the way SendTransaction already spans both chains. These pin the seams where
a merge like this silently corrupts data.
"""
from unittest import mock

from django.test import SimpleTestCase

from conversion.models import Conversion
from users.models_unified import UnifiedTransactionTable


class RailSeparationTests(SimpleTestCase):
    def test_savings_types_are_flagged(self):
        for t in ('to_savings', 'from_savings'):
            self.assertTrue(Conversion(conversion_type=t).is_savings, t)
        for t in ('usdc_to_cusd', 'cusd_to_usdc', 'usdc_to_algo'):
            self.assertFalse(Conversion(conversion_type=t).is_savings, t)

    def test_every_type_has_a_token_pair(self):
        # A type with no pair renders as a bare amount with no denomination,
        # which is exactly how the savings rows used to look.
        for value, _label in Conversion.CONVERSION_TYPES:
            self.assertIn(value, UnifiedTransactionTable.CONVERSION_TOKENS, value)

    def test_saga_transitions_are_monotonic(self):
        conv = Conversion(conversion_type='to_savings', status='DEST_ARRIVED')
        self.assertTrue(conv.can_transition('COMPLETED'))
        self.assertFalse(conv.can_transition('SRC_COMMITTED'))
        self.assertFalse(Conversion(status='COMPLETED').can_transition('DEST_ARRIVED'))


class MirrorRoutingTests(SimpleTestCase):
    """The single post_save must not mirror a savings row as an Algorand one.

    create_unified_transaction_from_conversion ends in an `else` that labels
    anything unknown "Conversión: X USDC → Y cUSD". Before the delegation
    below, merging the models would have sent every savings row through it.
    """

    def _mirror(self, conversion_type):
        from users import signals
        # A real (unsaved) instance: the legacy branch touches many fields,
        # and a thin fake would fail for reasons unrelated to the routing.
        conv = Conversion(
            conversion_type=conversion_type, status='COMPLETED',
            from_amount='1.00', to_amount='1.00',
            actor_type='user', actor_display_name='X',
        )
        with mock.patch('cusd_plus.unified.sync_unified_from_cusd_plus_conversion') as savings, \
             mock.patch.object(UnifiedTransactionTable, 'objects') as legacy:
            signals.create_unified_transaction_from_conversion(conv)
        return savings.called, legacy.update_or_create.called

    def test_savings_row_uses_the_savings_mirror(self):
        savings_called, legacy_called = self._mirror('to_savings')
        self.assertTrue(savings_called)
        self.assertFalse(legacy_called, 'must not fall through to the USDC branch')

    def test_algorand_row_does_not_use_the_savings_mirror(self):
        savings_called, _ = self._mirror('usdc_to_cusd')
        self.assertFalse(savings_called)
