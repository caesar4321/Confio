"""A payment rule may pay a CLABE whose holder the bank could not verify
because the paid lookup is off (INFINIA_ACCOUNT_VALIDATION_ENABLED False):
well-formed for its rail, labelled "Titular no verificado por el banco",
never one the bank definitely did not find. The owner saves a
new CLABE to their address book. The assistant's half is in test_assistant_payout_rules.
Fake values only."""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from payment_accounts.models import PayoutDestination
from smart_account import context, payouts, schema, services
from smart_account.models import SmartAccountRule

from .base import INFINIA_SWITCHES, SmartAccountTestCase, priced_payout

# Fake CLABEs with a valid check digit, and one with a wrong one.
CLABE = '002180000000004322'
CLABE_2 = '012180000000001234'
BAD_CLABE = '002180000000004321'
MX_ON = dict(SMART_ACCOUNT_PAYOUT_RAILS='mx_clabe', SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=True,
             INFINIA_ACCOUNT_VALIDATION_ENABLED=False, **INFINIA_SWITCHES)


def _resolve_info(field_name, ctx):
    return SimpleNamespace(
        path=SimpleNamespace(prev=None),
        operation=SimpleNamespace(operation=SimpleNamespace(value='mutation')),
        field_name=field_name, context=ctx)


class ClabeBase(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)
        self.personal = self.account.owner_account
        # These owners have no document; the rail gate itself is tested on a
        # verified owner (test_infinia_prepare.SaveGateTests).
        rail_gate = mock.patch('payment_accounts.local_money.require_rail')
        rail_gate.start()
        self.addCleanup(rail_gate.stop)

    def destination(self, clabe=CLABE, validation=None, **extra):
        data = {'method_id': 'mx_clabe', **extra}
        if validation is not None:
            data['validation'] = validation
        return PayoutDestination.objects.create(
            confio_account=self.personal, provider='infinia', kind='bank_account', country='MEX', asset='MXN',
            label=f'CLABE · {clabe}', holder_name='', status='active',
            details={'type': 'CLABE', 'clabe': clabe, 'reference': 'Confio'}, provider_data=data)


def status(value, name=''):
    return {'id': '', 'status': value, 'holder_name': name, 'checked_at': timezone.now().isoformat()}


@override_settings(**MX_ON)
class DestinationStateTests(ClabeBase):
    def test_lookup_off_and_well_formed_is_usable_and_labelled(self):
        row = self.destination(validation=status('DISABLED'), owner_holder_name='Ana Prueba')
        self.assertEqual(services.payout_destination_state(row), services.HOLDER_UNVERIFIED)
        (method,) = services.payout_method_rows(self.viewer(self.owner))
        self.assertEqual((method['rail'], method['available'], method['holder_verified'], method['holder_name'],
                          method['owner_holder']), ('mx_clabe', True, False, '', 'Ana Prueba'))

    def test_a_bad_check_digit_is_never_usable(self):
        self.destination(clabe=BAD_CLABE, validation=status('DISABLED'))
        self.assertEqual(services.payout_method_rows(self.viewer(self.owner)), [])

    def test_a_definite_or_running_answer_that_is_not_verified_is_refused(self):
        for answer in ('ERROR', 'IN_PROGRESS', 'TEMPORARY_FAILURE', 'REJECTED'):
            row = self.destination(validation=status(answer))
            self.assertEqual(services.payout_destination_state(row), '', answer)
        self.assertEqual(services.payout_method_rows(self.viewer(self.owner)), [])

    def test_a_bank_verified_holder_is_shown_as_verified(self):
        row = self.destination(validation=status('SUCCESSFUL', 'Ana Prueba'))
        PayoutDestination.objects.filter(pk=row.pk).update(holder_name='Ana Prueba')
        (method,) = services.payout_method_rows(self.viewer(self.owner))
        self.assertEqual((method['holder_verified'], method['holder_name']), (True, 'Ana Prueba'))

    def test_no_answer_recorded_counts_only_while_the_lookup_is_off(self):
        row = self.destination()
        self.assertEqual(services.payout_destination_state(row), services.HOLDER_UNVERIFIED)
        with override_settings(INFINIA_ACCOUNT_VALIDATION_ENABLED=True):
            self.assertEqual(services.payout_destination_state(row), '')

    def test_graphql_list_carries_holder_verified(self):
        self.destination(validation=status('DISABLED'))
        (method,) = schema.Query.resolve_smart_account_payout_methods(None, self.info(self.owner))
        self.assertIs(method.holder_verified, False)


@override_settings(**MX_ON)
class SaveClabeTests(ClabeBase):
    def test_invalid_clabe_is_refused_in_plain_spanish(self):
        with self.assertRaises(services.PrepareError) as raised:
            services.save_clabe_destination(self.viewer(self.owner), BAD_CLABE)
        self.assertEqual(raised.exception.message, 'Esa CLABE no es válida: revisa los 18 dígitos.')
        self.assertFalse(PayoutDestination.objects.exists())

    def test_saved_to_the_personal_address_book_once(self):
        viewer = self.viewer(self.owner)
        first = services.save_clabe_destination(viewer, '0021 8000 0000 0043 22', 'Ana Prueba')
        again = services.save_clabe_destination(viewer, CLABE)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(PayoutDestination.objects.count(), 1)
        again.refresh_from_db()
        self.assertEqual(again.confio_account_id, self.personal.pk)
        self.assertEqual(again.provider_data['method_id'], 'mx_clabe')
        self.assertEqual(again.provider_data['validation']['status'], 'DISABLED')
        self.assertEqual(again.provider_data[services.OWNER_HOLDER_KEY], 'Ana Prueba')
        self.assertEqual(again.holder_name, '')   # never presented as the bank's answer

    def test_only_on_a_live_rail(self):
        with override_settings(SMART_ACCOUNT_PAYOUT_RAILS=''):
            with self.assertRaises(services.PrepareError) as raised:
                services.save_clabe_destination(self.viewer(self.owner), CLABE)
        self.assertEqual(raised.exception.code, 'payout_not_available')

    def test_a_clabe_the_bank_did_not_find_is_refused(self):
        with override_settings(INFINIA_ACCOUNT_VALIDATION_ENABLED=True), \
                mock.patch('payment_accounts.local_money._validate', return_value=status('ERROR')):
            with self.assertRaises(services.PrepareError) as raised:
                services.save_clabe_destination(self.viewer(self.owner), CLABE)
        self.assertEqual(raised.exception.code, 'payout_method_rejected')

    def test_mutation_from_a_smart_context_and_the_gate(self):
        gate = context.SmartContextGateMiddleware()
        smart = self.info(self.owner, 'smart', 0)
        self.assertIn('saveSmartAccountClabeDestination', context.ALLOWED_MUTATIONS)
        self.assertEqual(gate.resolve(lambda *a, **k: 'ran', None,
                                      _resolve_info('saveSmartAccountClabeDestination', smart.context)), 'ran')
        result = schema.SaveSmartAccountClabeDestination.mutate(None, smart, clabe=CLABE, holder_name='Ana Prueba')
        self.assertTrue(result.success, result.error_message)
        self.assertEqual((result.payout_method.rail, result.payout_method.holder_verified,
                          result.payout_method.holder_name, result.payout_method.label),
                         ('mx_clabe', False, '', f'CLABE · {CLABE} (escribiste: Ana Prueba)'))
        bad = schema.SaveSmartAccountClabeDestination.mutate(None, smart, clabe=BAD_CLABE)
        self.assertEqual((bad.success, bad.error_code), (False, 'bad_clabe'))


@override_settings(**MX_ON)
class UnverifiedPayoutRuleTests(ClabeBase):
    def setUp(self):
        super().setUp()
        for p in (mock.patch('payment_accounts.services.require_outgoing_face', return_value='face-key-1'),
                  priced_payout(), mock.patch('security.face_step_up.step_up_applies', return_value=True)):
            p.start()
            self.addCleanup(p.stop)
        self.row = self.destination(validation=status('DISABLED'), owner_holder_name='Ana Prueba')

    def _prepare(self):
        return services.prepare_payout_rule(self.viewer(self.owner), None, str(self.row.internal_id), '1.00',
                                            'monthly')

    def test_rule_is_prepared_with_face_bound_and_the_note_in_its_summary(self):
        batch = self._prepare()
        self.assertTrue(any('Titular no verificado por el banco' in line and 'Ana Prueba' in line
                            for line in batch.summary), batch.summary)
        rule = SmartAccountRule.all_objects.get()
        self.assertEqual(rule.standing_authorization.binding_hash,
                         payouts.binding_hash(self.row, Decimal('1.00'), 'monthly'))
        self.assertEqual(rule.standing_authorization.face_action_key, 'face-key-1')

    def test_run_time_check_accepts_it_until_the_bank_says_not_found(self):
        self._prepare()
        rule = SmartAccountRule.all_objects.get()
        SmartAccountRule.all_objects.filter(pk=rule.pk).update(state='onchain', active=True, onchain_id=1)
        rule.refresh_from_db()
        self.assertIsNone(payouts.authorization_problem(rule))
        self.row.provider_data = {**self.row.provider_data, 'validation': status('ERROR')}
        self.row.save()
        rule.refresh_from_db()
        self.assertEqual(payouts.authorization_problem(rule), 'destination_unverified')
        with self.assertRaises(services.PrepareError) as raised:
            self._prepare()
        self.assertEqual(raised.exception.code, 'payout_method_unverified')

    def test_an_edited_clabe_still_breaks_the_binding(self):
        self._prepare()
        rule = SmartAccountRule.all_objects.get()
        SmartAccountRule.all_objects.filter(pk=rule.pk).update(state='onchain', active=True, onchain_id=1)
        self.row.details = {**self.row.details, 'clabe': CLABE_2}
        self.row.save()
        rule.refresh_from_db()
        self.assertEqual(payouts.authorization_problem(rule), 'destination_changed')
