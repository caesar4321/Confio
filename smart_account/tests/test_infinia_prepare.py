"""CLABE / Pix rules at prepare: what could never run is refused before
Face; a rail with no adapter is off whatever the flags say. The assistant's
half is in test_assistant_payout_rules. Fake keys and names only."""
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from payment_accounts.models import (
    AccountActivation, EligibilityPolicy, FinancialAccount, FundingInstruction, PayoutDestination,
)
from smart_account import infinia_payouts, offer, payouts, schema, services
from smart_account.models import (
    SmartAccountPayout, SmartAccountRelayTx, SmartAccountRule, SmartAccountRuleRun, SmartAccountStandingAuthorization,
)

from . import infinia_world as w
from .infinia_base import InfiniaPayoutCase


def answer(status, name=''):
    return {'id': '', 'status': status, 'holder_name': name, 'checked_at': timezone.now().isoformat()}


class RailsAreOffWithoutAnAdapterTests(InfiniaPayoutCase):
    EVERY = 'co_breb,ar_cvu,co_qr,br_qr,ar_qr,br_pix_receive,nope,mx_clabe,br_pix'

    def test_only_the_rails_with_an_adapter_whatever_the_flags_say(self):
        with override_settings(SMART_ACCOUNT_PAYOUT_RAILS=self.EVERY,
                               SMART_ACCOUNT_PAYOUT_VERIFIED_ADAPTERS='infinia,co_breb,ar_cvu'):
            self.assertEqual(offer.payout_rails(), ['mx_clabe', 'br_pix'])
            for rail in ('co_breb', 'ar_cvu', 'co_qr', 'br_qr', 'ar_qr', 'nope', ''):
                self.assertFalse(payouts.rail_ready(rail), rail)

    def test_breb_and_cvu_alone_offer_nothing_and_run_nothing(self):
        with override_settings(SMART_ACCOUNT_PAYOUT_RAILS='co_breb,ar_cvu'):
            self.assertEqual((offer.payout_rails(), offer.payout_rail_options()), ([], []))
            with self.assertRaises(services.PrepareError) as raised:
                self.prepare()
            self.assertEqual(raised.exception.code, 'payout_not_available')

    def test_each_switch_the_path_needs(self):
        self.assertEqual(offer.payout_rails(), ['mx_clabe', 'br_pix'])
        for name in ('SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED', 'INFINIA_PAYMENT_ACCOUNTS_ENABLED',
                     'INFINIA_JOURNEYS_ENABLED', 'PAYMENT_BRIDGE_QUOTES_ENABLED', 'PAYMENT_BRIDGE_BSC_ENABLED',
                     'CUSD_PLUS_7702_ENABLED'):
            with override_settings(**{name: False}):
                self.assertEqual(offer.payout_rails(), [], name)
        with override_settings(RELAY_API_KEY=''):           # no key, no way to recognise a delivery
            self.assertEqual(offer.payout_rails(), [])
        with override_settings(LOCAL_MONEY_METHODS=['br_pix']):
            self.assertEqual(offer.payout_rails(), ['br_pix'])


class RefusedBeforeFaceTests(InfiniaPayoutCase):
    def refused(self, code, fragment, amount=None):
        """prepare refuses before Face (the assistant, with the same words: test_assistant_payout_rules)."""
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare(amount)
        self.assertEqual(raised.exception.code, code)
        self.assertIn(fragment, raised.exception.message)
        self.assertLessEqual(len(raised.exception.message), 260)
        self.face.assert_not_called()
        self.assertFalse(SmartAccountStandingAuthorization.objects.exists())
        self.assertFalse(SmartAccountRule.all_objects.exists())
        return raised.exception.message

    def test_no_local_account(self):
        FinancialAccount.objects.filter(pk=self.local.pk).delete()
        self.refused('local_account_required', 'necesitas tu cuenta de pesos mexicanos')

    def test_a_pair_for_another_country_is_no_pair(self):
        FinancialAccount.objects.filter(pk=self.local.pk).update(country='BRA', asset='BRL')
        self.refused('local_account_required', 'Ábrela desde Enviar')

    def test_account_still_opening(self):
        FinancialAccount.objects.filter(pk=self.local.pk).update(status='pending')
        self.refused('local_account_pending', 'todavía se está abriendo')

    def test_account_closed(self):
        FinancialAccount.objects.filter(pk=self.local.pk).update(status='closed')
        self.refused('local_account_inactive', 'no está activa')

    def test_opening_never_paid(self):
        AccountActivation.objects.filter(confio_account=self.personal).update(status='awaiting_payment')
        self.refused('local_account_unpaid', 'Termina de abrir')

    def test_no_dollar_deposit_address(self):
        FundingInstruction.objects.update(status='closed')
        self.refused('funding_account_unavailable', 'no puede recibir dólares')

    def test_not_eligible(self):
        EligibilityPolicy.objects.filter(provider='infinia', scope='payout', is_active=True).update(
            default_decision='block')
        self.refused('rail_not_eligible', 'no está disponible')

    def test_minor(self):
        with mock.patch('security.minors.is_known_minor', return_value=True):
            self.refused('minor', 'mayores de 18')

    def test_over_the_cap(self):
        with override_settings(PAYMENT_BRIDGE_MAX_USDT='20'):
            self.refused('limit_exceeded', 'supera el máximo')

    def test_one_dollar_names_the_cost_and_an_amount_that_works(self):
        message = self.refused('bridge_cost_above_limit', 'más del 1,5%', amount='1.00')
        self.assertIn('US$4.00', message)
        self.assertEqual(self.prepare('4.00').kind, 'smart_rule')

    def test_under_relays_minimum(self):
        self.world.quote_error = (400, {'errorCode': 'AMOUNT_TOO_LOW'})
        self.refused('amount_too_small', 'muy bajo', amount='1.00')

    def test_route_that_would_lose_a_quarter(self):
        self.world.relay_fixed = Decimal('0.40')
        self.refused('amount_too_small', 'muy bajo', amount='1.00')

    @override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES='MX,BR')
    def test_the_processor_fee_is_outside_the_limit(self):
        message = self.refused('bridge_cost_above_limit', 'va aparte de ese límite', amount='2.00')
        suggested = next(word.rstrip('.') for word in reversed(message.split()) if word.startswith('US$'))
        self.assertTrue(self.prepare(suggested[3:]))

    @override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES='MX')
    def test_a_fee_above_the_whole_amount(self):
        with override_settings(INFINIA_PROCESSING_FEE_TIER=0), \
                mock.patch('payment_accounts.contract_funding.processor_fee', return_value={'total_usd': '2'}):
            self.refused('amount_too_small', 'muy bajo', amount='1.00')

    def test_provider_down_promises_no_retry(self):
        self.world.quote_error = (503, {'message': 'down'})
        message = self.refused('bridge_unavailable', 'Inténtalo de nuevo')
        self.assertNotIn('Lo intentaremos', message)

    def test_unusable_destination(self):
        self.destination.country = 'BRA'
        self.destination.save()
        self.refused('destination_unusable', 'Guárdala de nuevo')

    def test_an_invalid_number(self):
        self.destination.details = dict(self.destination.details, clabe='002180000000004321')
        self.destination.save()
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare()
        self.assertEqual(raised.exception.code, 'payout_method_unverified')
        self.face.assert_not_called()

    def test_a_stale_verified_holder(self):
        self.destination.provider_data['validation'] = {
            'id': 'v1', 'status': 'SUCCESSFUL', 'holder_name': 'Ana Prueba',
            'checked_at': '2020-01-01T00:00:00+00:00'}
        self.destination.holder_name = 'Ana Prueba'
        self.destination.save()
        (row,) = services.payout_method_rows(self.viewer())
        self.assertEqual((row['holder_verified'], row['holder_name']), (False, ''))
        batch = self.prepare()      # lookup off: no worse than a row never checked
        self.assertTrue(any(services.UNVERIFIED_HOLDER_NOTE in line for line in batch.summary), batch.summary)
        self.destination.refresh_from_db()
        # Prepare never replaces the bank's answer: another rule may be pinned to it.
        self.assertEqual(self.destination.provider_data['validation']['status'], 'SUCCESSFUL')
        self.assertNotIn(payouts.RULE_HOLDERS_KEY, self.destination.provider_data)

    @override_settings(INFINIA_ACCOUNT_VALIDATION_ENABLED=True)
    def test_a_stale_holder_is_asked_again_before_face(self):
        self.destination.provider_data['validation'] = {
            'id': 'v1', 'status': 'SUCCESSFUL', 'holder_name': 'Ana Prueba',
            'checked_at': '2020-01-01T00:00:00+00:00'}
        self.destination.save()
        with mock.patch('payment_accounts.local_money._validate', return_value=answer('ERROR')):
            with self.assertRaises(services.PrepareError) as raised:
                self.prepare()
        self.assertEqual(raised.exception.code, 'payout_method_rejected')
        self.face.assert_not_called()
        self.assertFalse(SmartAccountStandingAuthorization.objects.exists())

    @override_settings(INFINIA_ACCOUNT_VALIDATION_ENABLED=True)
    def test_a_recheck_signs_the_holder_the_bank_names_now(self):
        self.destination.provider_data['validation'] = {
            'id': 'v1', 'status': 'SUCCESSFUL', 'holder_name': 'Ana Prueba',
            'checked_at': '2020-01-01T00:00:00+00:00'}
        self.destination.save()
        (row,) = services.payout_method_rows(self.viewer())
        self.assertEqual((row['holder_verified'], row['holder_name']), (False, ''))     # offered, not as verified
        with mock.patch('payment_accounts.local_money._validate',
                        return_value=answer('SUCCESSFUL', 'Bia Prueba')) as asked:
            batch = self.prepare()
        asked.assert_called_once()
        self.assertFalse(any(services.UNVERIFIED_HOLDER_NOTE in line for line in batch.summary), batch.summary)
        self.destination.refresh_from_db()
        self.assertEqual(list(self.destination.provider_data[payouts.RULE_HOLDERS_KEY].values()),
                         [payouts._holder_digest('Bia Prueba')])

    def test_the_graphql_mutation_returns_the_reason(self):
        FinancialAccount.objects.filter(pk=self.local.pk).delete()
        result = schema.PrepareSmartAccountPayoutRule.mutate(
            None, self.info(), payout_method_id=str(self.destination.internal_id), amount_usd='50.00',
            frequency='monthly')
        self.assertEqual((result.success, result.error_code), (False, 'local_account_required'))
        self.assertIn('pesos mexicanos', result.error_message)


class SuggestedMinimumTests(SimpleTestCase):
    def test_with_the_measured_costs(self):
        """The amounts the report quotes: no fee, Pix tier 0, CLABE tier 0."""
        for fixed, fee, expected in (('0.043', '0', 4), ('0.043', '0.10', 4), ('0.043', '0.50', 4),
                                     ('0.09', '0.50', 8), ('0.001', '2', 3)):
            amount = Decimal('1')
            usdt = amount * Decimal('0.991')
            cost = Decimal(fixed) + usdt * Decimal('0.0019')
            self.assertEqual(infinia_payouts.suggested_minimum(cost, Decimal(fee), usdt, amount, 150), expected,
                             (fixed, fee))

    def test_no_amount_fits_a_limit_under_the_variable_cost(self):
        self.assertIsNone(infinia_payouts.suggested_minimum(Decimal('1'), Decimal(0), Decimal('1'), Decimal('1'), 10))


class SmallestAmountTests(InfiniaPayoutCase):
    """The smallest rule that really clears the limit on the measured model."""
    def smallest(self, rail_fee):
        with override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES=rail_fee):
            low, high = 1, 100
            while low < high:
                middle = (low + high) // 2
                try:
                    infinia_payouts.preflight(self.personal, self.contract, self.destination, self.rail,
                                              Decimal(middle), self.token)
                    high = middle
                except payouts.PayoutSkip:
                    low = middle + 1
        return low

    def test_clabe(self):
        self.assertEqual((self.smallest(''), self.smallest('MX')), (4, 4))


class SmallestAmountFromPlusTests(SmallestAmountTests):
    token = w.VAULT


class SmallestPixAmountTests(SmallestAmountTests):
    rail = 'br_pix'

    def test_clabe(self):
        self.assertEqual((self.smallest(''), self.smallest('BR')), (4, 4))


class SmallestPixAmountFromPlusTests(SmallestPixAmountTests):
    token = w.VAULT


class SaveGateTests(InfiniaPayoutCase):
    """Saving for a rule passes Enviar's gates before any lookup or write."""
    NEW = '012180000000001234'

    def refused(self, code):
        with mock.patch('payment_accounts.local_money._validate') as asked:
            with self.assertRaises(services.PrepareError) as raised:
                services.save_clabe_destination(self.viewer(), self.NEW)
        self.assertEqual(raised.exception.code, code)
        asked.assert_not_called()
        self.assertEqual(PayoutDestination.objects.count(), 1)

    def test_not_eligible_gets_no_lookup_and_no_name(self):
        EligibilityPolicy.objects.filter(provider='infinia', scope='payout', is_active=True).update(
            default_decision='block')
        with override_settings(INFINIA_ACCOUNT_VALIDATION_ENABLED=True):
            self.refused('rail_not_eligible')

    def test_no_identity(self):
        with mock.patch('payment_accounts.local_money.rail_status',
                        return_value=('needs_verification', 'identity_required', None)):
            self.refused('rail_not_eligible')

    def test_unsupported_region(self):
        with mock.patch('payment_accounts.local_money.region_unsupported', return_value=True):
            self.refused('rail_not_eligible')

    def test_minor(self):
        with mock.patch('security.minors.is_known_minor', return_value=True):
            self.refused('minor')

    def test_needs_their_own_active_account(self):
        type(self.account).objects.filter(pk=self.account.pk).update(status='expired')
        self.refused('account_not_active')

    def test_the_address_book_is_capped(self):
        with mock.patch.object(services, 'MAX_LOCAL_DESTINATIONS', 1):
            self.refused('too_many_destinations')
            # The same CLABE again is no new row.
            self.assertEqual(services.save_clabe_destination(self.viewer(), '002180000000004322').pk,
                             self.destination.pk)

    @override_settings(INFINIA_ACCOUNT_VALIDATION_ENABLED=True)
    def test_paid_lookups_are_limited(self):
        with mock.patch.object(services, 'DESTINATION_LOOKUPS_PER_HOUR', 1), mock.patch(
                'payment_accounts.local_money._validate', return_value=answer('TEMPORARY_FAILURE')) as asked:
            codes = []
            for _ in range(2):
                with self.assertRaises(services.PrepareError) as raised:
                    services.save_clabe_destination(self.viewer(), self.NEW)
                codes.append(raised.exception.code)
        self.assertEqual(codes, ['payout_method_check_failed', 'too_many_lookups'])
        asked.assert_called_once()


class LookupSwitchTests(InfiniaPayoutCase):
    """Turning the lookup on or off never changes a bank's answer."""
    def set_answer(self, validation):
        self.destination.provider_data = {**self.destination.provider_data, 'validation': validation}
        self.destination.save()

    def save_again(self):
        return services.save_clabe_destination(self.viewer(), '002180000000004322')

    def test_saving_again_never_turns_not_found_into_disabled(self):
        for status, code in (('ERROR', 'payout_method_rejected'), ('REJECTED', 'payout_method_rejected'),
                             ('IN_PROGRESS', 'payout_method_pending'),
                             ('TEMPORARY_FAILURE', 'payout_method_check_failed')):
            self.set_answer(answer(status))
            with self.assertRaises(services.PrepareError) as raised:
                self.save_again()
            self.assertEqual(raised.exception.code, code)
            self.destination.refresh_from_db()
            self.assertEqual(self.destination.provider_data['validation']['status'], status)

    def test_saving_again_keeps_a_verified_answer(self):
        self.set_answer(dict(answer('SUCCESSFUL', 'Ana Prueba'), checked_at='2020-01-01T00:00:00+00:00'))
        self.save_again()
        self.destination.refresh_from_db()
        self.assertEqual(self.destination.provider_data['validation']['status'], 'SUCCESSFUL')

    @override_settings(INFINIA_ACCOUNT_VALIDATION_ENABLED=True)
    def test_a_disabled_row_is_unusable_until_rechecked(self):
        self.assertEqual(services.payout_destination_state(self.destination), '')
        self.assertEqual(services.payout_holder_state(self.destination), services.HOLDER_RECHECK)
        with mock.patch('payment_accounts.local_money._validate', return_value=answer('TEMPORARY_FAILURE')):
            with self.assertRaises(services.PrepareError) as raised:
                self.prepare()
        self.assertEqual(raised.exception.code, 'payout_method_check_failed')
        self.face.assert_not_called()

    @override_settings(INFINIA_ACCOUNT_VALIDATION_ENABLED=True)
    def test_an_ineligible_owner_gets_no_recheck(self):
        EligibilityPolicy.objects.filter(provider='infinia', scope='payout', is_active=True).update(
            default_decision='block')
        with mock.patch('payment_accounts.local_money._validate') as asked:
            with self.assertRaises(services.PrepareError) as raised:
                self.prepare()
        self.assertEqual(raised.exception.code, 'rail_not_eligible')
        asked.assert_not_called()
        self.face.assert_not_called()


class StaleWhileOffRunTests(InfiniaPayoutCase):
    def test_a_rule_signed_as_unverified_on_a_stale_answer_runs(self):
        self.destination.holder_name = 'Ana Prueba'
        self.destination.provider_data['validation'] = {
            'id': 'v1', 'status': 'SUCCESSFUL', 'holder_name': 'Ana Prueba',
            'checked_at': '2020-01-01T00:00:00+00:00'}
        self.destination.save()
        self.make_rule()
        self.send_run()


class SignedSummaryTests(InfiniaPayoutCase):
    def test_the_rate_floor_is_signed(self):
        batch = self.prepare()
        signed = SmartAccountStandingAuthorization.objects.get()
        (line,) = [line for line in batch.summary if 'bajo la tasa' in line]
        self.assertEqual([line], services.fx_floor_lines(signed, 'MXN'))
        self.assertIn('3%', line)
        self.assertIn('MXN', line)

    def test_the_floor_is_the_authorizations(self):
        signed = SmartAccountStandingAuthorization(reference_fx_rate=Decimal('18.5'), fx_tolerance_bps=300)
        self.assertIn('menos de 17,945 MXN', services.fx_floor_lines(signed, 'MXN')[0])

    def test_money_already_out_is_explained_before_signing(self):
        signed = SmartAccountStandingAuthorization(reference_fx_rate=Decimal('18.5'), fx_tolerance_bps=300)
        (line,) = services.fx_floor_lines(signed, 'MXN')
        self.assertIn('Si el dinero ya salió', line)
        self.assertIn('hasta una hora', line)
        self.assertIn('en revisión', line)


class EditWhileInFlightTests(InfiniaPayoutCase):
    MESSAGE = 'Este pago se está haciendo ahora. Podrás cambiar la regla cuando termine.'

    def update(self, amount='60.00'):
        return self.prepare(amount, rule_id=str(self.rule.internal_id))

    def refused(self):
        faces = self.face.call_count
        with self.assertRaises(services.PrepareError) as raised:
            self.update()
        self.assertEqual((raised.exception.code, raised.exception.message), ('payout_run_in_flight', self.MESSAGE))
        self.assertEqual(self.face.call_count, faces)       # before Face
        self.assertTrue(services.prepare_cancel_rule(self.viewer(), str(self.rule.internal_id)))     # stop works

    def test_a_sent_run(self):
        self.make_rule()
        SmartAccountRuleRun.objects.create(rule=self.rule, scheduled_for=self.slot, status='sent')
        self.refused()

    def test_an_open_order(self):
        self.make_rule()
        run = SmartAccountRuleRun.objects.create(rule=self.rule, scheduled_for=self.slot, status='failed')
        payout = SmartAccountPayout.objects.create(rule_run=run, rail=self.rail)
        for status in ('reserving', 'prepared', 'pending', 'onchain_sent', 'funded'):
            SmartAccountPayout.objects.filter(pk=payout.pk).update(status=status)
            self.refused()
        for status in ('paid', 'refunded', 'cancelled', 'review'):
            SmartAccountPayout.objects.filter(pk=payout.pk).update(status=status)
            self.assertFalse(services.rule_run_in_flight(self.rule), status)
        self.assertEqual(self.update().kind, 'smart_rule')

    def test_a_relay_transaction_that_may_land(self):
        self.make_rule()
        sent = SmartAccountRelayTx.objects.create(
            smart_account=self.account, kind='smart_execute_rule', calldata='0x', signed_tx_hash='0x' + 'ab' * 32,
            source_id=f'rule:{self.rule.pk}:{int(self.slot.timestamp())}')
        for status in ('signed', 'sent', 'confirmed', 'reorged'):
            SmartAccountRelayTx.objects.filter(pk=sent.pk).update(status=status)
            self.refused()
        for status in ('reverted', 'dropped'):
            SmartAccountRelayTx.objects.filter(pk=sent.pk).update(status=status)
            self.assertFalse(services.rule_run_in_flight(self.rule), status)


class PixEmailCaseTests(InfiniaPayoutCase):
    rail = 'br_pix'

    def test_the_same_email_in_any_case_is_one_row(self):
        mixed = 'Recebedor@Example.com'
        self.assertEqual(services.save_pix_destination(self.viewer(), mixed).pk, self.destination.pk)
        new = services.save_pix_destination(self.viewer(), 'Nova.Chave@Example.com')
        self.assertEqual(new.details['chavePix'], 'nova.chave@example.com')
        self.assertEqual(services.save_pix_destination(self.viewer(), 'NOVA.CHAVE@example.com').pk, new.pk)
        self.assertEqual(PayoutDestination.objects.count(), 2)

    def test_a_row_saved_in_mixed_case_is_reused(self):
        self.destination.details = dict(self.destination.details, chavePix='Recebedor@Example.com')
        self.destination.save()
        self.assertEqual(services.save_pix_destination(self.viewer(), 'recebedor@example.com').pk,
                         self.destination.pk)
