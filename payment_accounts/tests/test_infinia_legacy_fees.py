from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from payment_accounts.infinia_legacy_fees import remember, resolve
from payment_accounts.services import PaymentAccountError


@override_settings(INFINIA_LEGACY_PAYOUT_FEES_ENABLED=True, INFINIA_PASS_THROUGH_FEE_COUNTRIES='CO')
class LegacyFeeBindingTests(SimpleTestCase):
    def setUp(self):
        self.owner = NS(pk=1)
        self.instruction = NS(pk=2, financial_account=NS(provider='infinia'))
        self.old = patch('payment_accounts.infinia_legacy_fees.PaymentBridgeQuote.objects.filter').start()
        self.old.return_value.first.return_value = None
        self.accounts = patch('payment_accounts.infinia_legacy_fees.FinancialAccount.objects.filter').start()
        self.accounts.return_value.exclude.return_value.values_list.return_value = ['COL']
        self.bindings = {}
        store = patch('payment_accounts.infinia_legacy_fees.InfiniaPayoutEstimateBinding.objects').start()
        def save(**kwargs):
            dest = kwargs.pop('defaults')['destination']
            self.bindings[tuple(sorted(kwargs.items()))] = NS(destination=dest)
        store.update_or_create.side_effect = save
        def lookup(**kwargs):
            result = NS(first=lambda: self.bindings.get(tuple(sorted(kwargs.items()))))
            return NS(select_related=lambda *args: result)
        store.filter.side_effect = lookup
        self.addCleanup(patch.stopall)

    def test_owned_estimate_is_bound_to_exact_amount_and_instruction(self):
        remember(self.owner, self.instruction, '345', NS(internal_id='recipient'))
        self.assertEqual(resolve(self.owner, self.instruction, Decimal('345.000'), 'request'), 'recipient')
        with self.assertRaises(PaymentAccountError):
            resolve(self.owner, self.instruction, '350', 'request')
        with self.assertRaises(PaymentAccountError):
            resolve(NS(pk=99), self.instruction, '345', 'request')

    def test_retry_uses_frozen_destination_not_new_estimate(self):
        remember(self.owner, self.instruction, '345', NS(internal_id='new'))
        self.old.return_value.first.return_value = NS(money_flow=NS(metadata={'local_destination_id':'original'}))
        self.assertEqual(resolve(self.owner, self.instruction, '345', 'request'), 'original')

    def test_pre_rollout_retry_remains_unpriced(self):
        self.old.return_value.first.return_value = NS(money_flow=NS(metadata={}))
        self.assertIsNone(resolve(self.owner, self.instruction, '345', 'request'))

    def test_missing_hint_never_guesses_a_recipient(self):
        with self.assertRaisesMessage(PaymentAccountError, 'Abre Enviar a cuenta local y espera la cotización antes de continuar.'):
            resolve(self.owner, self.instruction, '345', 'request')

    def test_other_providers_are_not_affected(self):
        self.instruction.financial_account.provider = 'koywe'
        self.assertIsNone(resolve(self.owner, self.instruction, '345', 'request'))
        self.old.assert_not_called()


    @override_settings(INFINIA_FEE_ROLLOUT_AT='2026-09-24T22:00:00+00:00')
    def test_rollout_cutoff_protects_only_preexisting_quotes(self):
        from django.utils.dateparse import parse_datetime
        from payment_accounts.infinia_legacy_fees import predates_rollout
        self.assertTrue(predates_rollout(NS(created_at=parse_datetime('2026-09-24T21:59:59+00:00'))))
        self.assertFalse(predates_rollout(NS(created_at=parse_datetime('2026-09-24T22:00:00+00:00'))))
