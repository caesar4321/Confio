from decimal import Decimal
from types import SimpleNamespace
from unittest import mock
import uuid

from django.test import SimpleTestCase, TestCase, override_settings

from payment_accounts import local_money
from payment_accounts.clients import ProviderAPIError
from payment_accounts.models import (
    AccountActivation, AccountCapability, FinancialAccount, InfiniaJourney, LimitIncreaseRequest, MoneyFlow, PayoutDestination,
    ProviderProfile,
)
from payment_accounts.services import PaymentAccountError, _infinia_capabilities
from security.models import IdentityVerification
from users.models import Account, User

FLAGS = dict(INFINIA_PAYMENT_ACCOUNTS_ENABLED=True, INFINIA_JOURNEYS_ENABLED=True,
             INFINIA_ACCOUNT_VALIDATION_ENABLED=True)


def tlv(tag, value):
    return f'{tag}{len(value):02d}{value}'


def qr(*fields):
    body = '000201' + ''.join(tlv(tag, value) for tag, value in fields) + '6304'
    return body + local_money.emv_crc(body)


class IdentifierTests(SimpleTestCase):
    def test_malformed_emv_headers_fail_closed(self):
        for payload in ('000', '000201991', '00020199²²', '000201９９00'):
            with self.subTest(payload=payload):
                self.assertIsNone(local_money.emv_fields(payload))
                with self.assertRaises(PaymentAccountError):
                    local_money.normalize_value(local_money.METHODS['br_qr'], payload)

    def test_oversized_qr_is_rejected(self):
        with self.assertRaises(PaymentAccountError):
            local_money.normalize_value(local_money.METHODS['br_qr'], '000201' + 'x' * 4096)

    def test_fx_precision_never_rounds_up_or_allows_a_zero_conversion(self):
        from payment_accounts.infinia_journeys import fx_source_amount
        for raw, expected in [('1.958795', '1.95'), ('1.999999', '1.99'), ('1.95', '1.95'),
                              ('0.01', '0.01'), ('999999999.999999', '999999999.99')]:
            with self.subTest(raw=raw):
                self.assertEqual(fx_source_amount(raw), Decimal(expected))
        for raw in ('0.009999', '0', '-1', 'NaN', 'Infinity'):
            with self.subTest(raw=raw), self.assertRaises(PaymentAccountError):
                fx_source_amount(raw)

    def test_crc_matches_ccitt_false_check_value(self):
        self.assertEqual(local_money.emv_crc('123456789'), '29B1')

    def test_clabe_checksum(self):
        self.assertTrue(local_money.clabe_valid('032180000118359719'))
        self.assertFalse(local_money.clabe_valid('032180000118359710'))
        self.assertFalse(local_money.clabe_valid('03218000011835971'))

    def test_cbu_checksum(self):
        self.assertTrue(local_money.cbu_valid('2850590940090418135201'))
        self.assertFalse(local_money.cbu_valid('2850590940090418135200'))

    def test_cvu_input_is_normalized_to_digits(self):
        method = local_money.METHODS['ar_cvu']
        self.assertEqual(local_money.normalize_value(method, '2850590940 0904181352-01'), '2850590940090418135201')

    def test_static_argentine_qr_is_accepted(self):
        payload = qr(('01', '11'), ('43', 'com.mercadolibre'), ('53', '032'), ('58', 'AR'), ('59', 'Kiosco'))
        self.assertEqual(local_money.normalize_value(local_money.METHODS['ar_qr'], payload), payload)

    def test_fixed_amount_qr_is_rejected(self):
        payload = qr(('01', '12'), ('53', '032'), ('54', '1500.00'), ('58', 'AR'))
        with self.assertRaisesRegex(PaymentAccountError, 'monto fijo'):
            local_money.normalize_value(local_money.METHODS['ar_qr'], payload)

    def test_brazil_static_qr_and_pix_key_validation(self):
        method = local_money.METHODS['br_qr']
        payload = qr(('26', tlv('00', 'br.gov.bcb.pix') + tlv('01', 'ana@example.com')),
                     ('53', '986'), ('58', 'BR'), ('59', 'Loja'))
        self.assertEqual(local_money.normalize_value(method, payload), payload)
        self.assertEqual(local_money._validation_request(method, payload),
                         {'country': 'BR', 'account': {'dataType': 'PIX_KEY', 'pixKey': 'ana@example.com'}})
        from payment_accounts.services import _validate_infinia_destination
        _validate_infinia_destination(kind='qr', country='BRA', details={'type': 'BR_CODE', 'brCode': payload})

    def test_brazil_qr_rejects_unsafe_or_wrong_rail_payloads(self):
        pix = tlv('00', 'br.gov.bcb.pix') + tlv('01', 'ana@example.com')
        for fields in [
                (('26', pix), ('53', '032'), ('58', 'BR')),
                (('26', pix), ('53', '986'), ('58', 'AR')),
                (('26', pix), ('53', '986'), ('58', 'BR'), ('54', '10')),
                (('01', '12'), ('26', pix), ('53', '986'), ('58', 'BR')),
                (('26', pix + tlv('25', 'example.com')), ('53', '986'), ('58', 'BR')),
                (('26', pix), ('26', pix), ('53', '986'), ('58', 'BR')),
                (('26', tlv('00', 'other.network')), ('53', '986'), ('58', 'BR'))]:
            with self.subTest(fields=fields), self.assertRaises(PaymentAccountError):
                local_money.normalize_value(local_money.METHODS['br_qr'], qr(*fields))

    def test_qr_does_not_validate_a_different_normalized_pix_key(self):
        payload = qr(('26', tlv('00', 'br.gov.bcb.pix') + tlv('01', 'abc12345678901')),
                     ('53', '986'), ('58', 'BR'))
        with self.assertRaises(PaymentAccountError):
            local_money.normalize_value(local_money.METHODS['br_qr'], payload)

    def test_tampered_or_foreign_qr_is_rejected(self):
        payload = qr(('01', '11'), ('58', 'AR'))
        for bad in (payload[:-1] + ('0' if payload[-1] != '0' else '1'), qr(('01', '11'), ('58', 'BR')), 'hola'):
            with self.assertRaises(PaymentAccountError):
                local_money.normalize_value(local_money.METHODS['ar_qr'], bad)

    def test_pix_keys(self):
        method = local_money.METHODS['br_pix']
        self.assertEqual(local_money.normalize_value(method, '123.456.789-09'), '12345678909')
        self.assertEqual(local_money.normalize_value(method, '+5511912345678'), '+5511912345678')
        self.assertEqual(local_money.normalize_value(method, 'Ana@Example.com'), 'Ana@Example.com')
        evp = '123E4567-E89B-12D3-A456-426614174000'
        self.assertEqual(local_money.normalize_value(method, evp), evp.lower())
        for bad in ('5511912345678', '+5711912345678', '1234'):
            with self.assertRaises(PaymentAccountError):
                local_money.normalize_value(method, bad)

    def test_breb_key_uses_the_shared_validator(self):
        method = local_money.METHODS['co_breb']
        self.assertEqual(local_money.normalize_value(method, ' @maria.rod '), '@maria.rod')
        with self.assertRaises(PaymentAccountError):
            local_money.normalize_value(method, '+57300')

    def test_validation_states(self):
        self.assertEqual(local_money.verification_state({'status': 'SUCCESSFUL', 'holder_name': 'Ana'}), 'verified')
        self.assertEqual(local_money.verification_state({'status': 'SUCCESSFUL', 'holder_name': ''}), 'unverified')
        self.assertEqual(local_money.verification_state({'status': 'IN_PROGRESS'}), 'pending')
        self.assertEqual(local_money.verification_state({'status': 'ERROR'}), 'not_found')
        self.assertEqual(local_money.verification_state({'status': 'TEMPORARY_FAILURE'}), 'unverified')
        self.assertEqual(local_money.verification_state({'status': 'DISABLED'}), 'not_checked')
        self.assertEqual(local_money.verification_state(None), 'unverified')

    def test_summary_reads_owner_name_and_masks_document(self):
        summary = local_money.summarize_validation({
            'id': 'v1', 'status': 'SUCCESSFUL',
            'countryData': {'account': {'bankName': 'Bancolombia'},
                            'owners': [{'name': 'María Rodríguez', 'documentNumber': '1020304821'}]},
        })
        self.assertEqual((summary['holder_name'], summary['holder_document'], summary['institution']),
                         ('María Rodríguez', '•••• 4821', 'Bancolombia'))


class LocalMoneyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='local-money', firebase_uid='local-money')
        self.owner = Account.objects.create(user=self.user, account_type='personal')
        self.identity = IdentityVerification.objects.create(
            user=self.user, status='verified', verified_date_of_birth='1990-01-01',
            verified_country='COL', verified_nationality='VEN', document_type='national_id',
            document_number='CC-1', document_issuing_country='COL', risk_factors={'provider': 'didit'})
        self.profile = ProviderProfile.objects.create(
            confio_account=self.owner, provider='infinia', owner_type='individual', status='active',
            identity_verification=self.identity,
            identity_snapshot={'full_name': 'Ana Pérez', 'nationality': 'VEN', 'residence_country': 'COL'})
        self.client_api = mock.Mock()

    def pair(self, country='COL', asset='COP'):
        crypto = FinancialAccount.objects.create(
            provider_profile=self.profile, provider_account_id='crypto', country='XXX', asset='USDC_POL',
            ownership_structure='provider_named', status='active')
        local = FinancialAccount.objects.create(
            provider_profile=self.profile, provider_account_id='local', country=country, asset=asset,
            ownership_structure='provider_named', status='active')
        AccountActivation.objects.get_or_create(confio_account=self.owner, country=country, asset=asset,
                                                defaults={'status': 'legacy'})
        return local, crypto

    # ---- availability

    def test_rails_are_unavailable_until_both_flags_are_on(self):
        rows = local_money.methods(self.owner, self.identity, 'send')
        self.assertEqual({row['method'].id for row in rows}, {'br_pix', 'br_qr', 'co_breb', 'mx_clabe', 'ar_cvu', 'ar_qr'})
        self.assertEqual({row['status'] for row in rows}, {'unavailable'})

    @override_settings(**FLAGS)
    def test_unverified_user_is_sent_to_verification(self):
        status, _ = local_money.method_status(None, local_money.METHODS['mx_clabe'])
        self.assertEqual(status, 'needs_verification')

    @override_settings(**FLAGS)
    def test_missing_policy_fails_closed(self):
        # A fresh test DB carries the seeded Infinia policies; remove them.
        from payment_accounts.models import EligibilityPolicy
        EligibilityPolicy.objects.filter(provider='infinia').update(is_active=False)
        self.assertEqual(local_money.method_status(self.identity, local_money.METHODS['mx_clabe']),
                         ('unavailable', 'policy_not_configured'))

    @override_settings(**FLAGS)
    def test_every_journey_scope_must_allow(self):
        verdicts = iter([True, True, True, False])
        allowed = lambda **kw: SimpleNamespace(allowed=next(verdicts), reason_code='blocked', decision='block')
        with mock.patch.object(local_money, 'evaluate_active_policy', side_effect=allowed) as evaluate:
            self.assertEqual(local_money.method_status(self.identity, local_money.METHODS['co_breb']),
                             ('unavailable', 'blocked'))
        scopes = [(c.kwargs['scope'], c.kwargs['context'].account_country) for c in evaluate.call_args_list]
        self.assertEqual(scopes, [('account_opening', 'COL'), ('account_opening', 'XXX'),
                                  ('conversion', 'COL'), ('payout', 'COL')])

    @override_settings(**FLAGS, LOCAL_MONEY_METHODS=['co_breb'])
    def test_method_allowlist(self):
        with mock.patch.object(local_money, 'evaluate_active_policy',
                               return_value=SimpleNamespace(allowed=True)):
            self.assertEqual(local_money.method_status(self.identity, local_money.METHODS['co_breb'])[0], 'live')
            self.assertEqual(local_money.method_status(self.identity, local_money.METHODS['br_pix'])[0], 'unavailable')

    @override_settings(**FLAGS)
    def test_activation_opens_dollar_then_local_account_without_a_checkbox(self):
        local, crypto = self.pair()
        calls = []

        def provision(**kwargs):
            calls.append((kwargs['country'], kwargs['asset'], kwargs['compliance_consent']))
            return self.profile, crypto if kwargs['country'] == 'XXX' else local
        with mock.patch.object(local_money, 'method_status', return_value=('live', '')), \
                mock.patch('ramps.schema._is_ramp_address_complete', return_value=True), \
                mock.patch.object(local_money, 'provision_payment_account', side_effect=provision):
            self.assertEqual(local_money.activate(self.owner, self.identity, 'co_breb'), 'active')
        self.assertEqual(calls, [('XXX', 'USDC_POL', True), ('COL', 'COP', True)])

    @override_settings(**FLAGS)
    def test_activation_waits_for_the_self_declared_address(self):
        with mock.patch.object(local_money, 'method_status', return_value=('live', '')), \
                mock.patch('ramps.schema._is_ramp_address_complete', return_value=False), \
                mock.patch.object(local_money, 'provision_payment_account') as provision:
            with self.assertRaisesRegex(PaymentAccountError, 'Completa tu dirección'):
                local_money.activate(self.owner, self.identity, 'co_breb')
        provision.assert_not_called()

    def test_domicile_comes_from_the_declared_address_first(self):
        local, _ = self.pair()
        self.profile.identity_snapshot = {**self.profile.identity_snapshot,
                                          'residence_country': 'VEN', 'address_country': 'COL'}
        self.profile.save(update_fields=['identity_snapshot'])
        local.refresh_from_db()
        _infinia_capabilities(local)
        status = AccountCapability.objects.get(financial_account=local, capability='receive_same_name').status
        self.assertEqual(status, 'enabled')

    # ---- recipients

    @override_settings(**{**FLAGS, 'INFINIA_ACCOUNT_VALIDATION_ENABLED': False})
    def test_disabled_validation_resolves_and_rechecks_without_provider_calls(self):
        destination = local_money.resolve_destination(self.owner, 'co_breb', '@maria.rod', client=self.client_api)
        self.assertEqual(local_money.destination_view(destination)['verification'], 'not_checked')
        destination = local_money.recheck_destination(destination, client=self.client_api)
        local_money.require_current_destination(destination)
        self.assertEqual(destination.holder_name, '')
        self.client_api.create_bank_account_validation.assert_not_called()
        self.client_api.get_bank_account_validation.assert_not_called()

    @override_settings(**FLAGS)
    def test_disabling_validation_releases_pending_recipient_without_polling(self):
        self.client_api.create_bank_account_validation.return_value = {'id': 'v1', 'status': 'IN_PROGRESS'}
        destination = local_money.resolve_destination(self.owner, 'co_breb', '@maria.rod', client=self.client_api)
        self.client_api.reset_mock()
        with override_settings(INFINIA_ACCOUNT_VALIDATION_ENABLED=False):
            destination = local_money.refresh_destination(destination, client=self.client_api)
        self.assertEqual(local_money.destination_view(destination)['verification'], 'not_checked')
        self.client_api.create_bank_account_validation.assert_not_called()
        self.client_api.get_bank_account_validation.assert_not_called()

    @override_settings(**{**FLAGS, 'INFINIA_ACCOUNT_VALIDATION_ENABLED': False})
    def test_disabled_lookups_keep_qr_recipients_distinguishable(self):
        labels = []
        for merchant, city in [('Kiosco', 'CORDOBA'), ('Kiosco', 'ROSARIO'), ('', 'ROSARIO')]:
            payload = qr(('43', 'com.mercadolibre'), ('53', '032'), ('58', 'AR'),
                         ('59', merchant), ('60', city))
            row = local_money.resolve_destination(self.owner, 'ar_qr', payload, client=self.client_api)
            view = local_money.destination_view(row)
            self.assertEqual(view['verification'], 'not_checked')
            self.assertEqual(view['holder_name'], '')
            self.assertIn(merchant or 'Código de pago', view['label'])
            labels.append(view['label'])
        self.assertEqual(len(set(labels)), 3)
        self.client_api.create_bank_account_validation.assert_not_called()

    @override_settings(**{**FLAGS, 'INFINIA_ACCOUNT_VALIDATION_ENABLED': False})
    def test_review_shows_full_long_key_even_for_older_truncated_saved_label(self):
        value = 'a' * 120 + '@example.com'
        row = local_money.resolve_destination(self.owner, 'co_breb', value, client=self.client_api)
        self.assertLessEqual(len(row.label), 100)
        self.assertEqual(local_money.destination_view(row)['label'], f'Llave Bre-B · {value}')
        row.label = 'Llave Bre-B · old truncated label'
        row.save(update_fields=['label'])
        self.assertEqual(local_money.destination_view(local_money.recheck_destination(row))['label'],
                         f'Llave Bre-B · {value}')

    @override_settings(**FLAGS)
    def test_disabling_lookups_reuses_fresh_names_but_clears_expired_names(self):
        from datetime import timedelta
        from django.utils import timezone
        self.client_api.create_bank_account_validation.return_value = self.validation()
        row = local_money.resolve_destination(self.owner, 'co_breb', '@maria.rod', client=self.client_api)
        self.client_api.reset_mock()
        with override_settings(INFINIA_ACCOUNT_VALIDATION_ENABLED=False):
            self.assertEqual(local_money.destination_view(local_money.recheck_destination(row))['verification'], 'verified')
            row.provider_data['validation']['checked_at'] = (timezone.now() - timedelta(days=2)).isoformat()
            row.save(update_fields=['provider_data'])
            row = local_money.recheck_destination(row, client=self.client_api)
            self.assertEqual(local_money.destination_view(row)['verification'], 'not_checked')
            self.assertEqual(row.holder_name, '')
            local_money.require_current_destination(row)
        self.client_api.create_bank_account_validation.assert_not_called()
        self.client_api.get_bank_account_validation.assert_not_called()

    @override_settings(**{**FLAGS, 'INFINIA_ACCOUNT_VALIDATION_ENABLED': False})
    def test_reenabling_lookups_rechecks_a_previously_skipped_recipient(self):
        row = local_money.resolve_destination(self.owner, 'co_breb', '@maria.rod', client=self.client_api)
        self.client_api.create_bank_account_validation.return_value = self.validation()
        with override_settings(INFINIA_ACCOUNT_VALIDATION_ENABLED=True):
            row = local_money.recheck_destination(row, client=self.client_api)
        self.assertEqual(local_money.destination_view(row)['verification'], 'verified')
        self.client_api.create_bank_account_validation.assert_called_once()

    def validation(self, status='SUCCESSFUL', name='María Rodríguez'):
        return {'id': 'v1', 'status': status, 'countryData': {
            'account': {'bankName': 'Bancolombia'}, 'owners': [{'name': name, 'documentNumber': '1020304821'}]}}

    @override_settings(**FLAGS)
    def test_verified_recipient_is_saved_and_reused(self):
        self.client_api.create_bank_account_validation.return_value = self.validation()
        first = local_money.resolve_destination(self.owner, 'co_breb', '@maria.rod', client=self.client_api)
        self.assertEqual(first.details, {'type': 'BREB_KEY', 'brebKey': '@maria.rod'})
        self.assertEqual(first.holder_name, 'María Rodríguez')
        self.client_api.create_bank_account_validation.assert_called_once_with(
            {'country': 'CO', 'account': {'dataType': 'BREB_KEY', 'brebKey': '@maria.rod'}})
        again = local_money.resolve_destination(self.owner, 'co_breb', '@maria.rod', client=self.client_api)
        self.assertEqual(again.pk, first.pk)
        self.client_api.create_bank_account_validation.assert_called_once()
        view = local_money.destination_view(again)
        self.assertEqual((view['verification'], view['country'], view['method_id']), ('verified', 'CO', 'co_breb'))

    @override_settings(**FLAGS)
    def test_clabe_carries_the_required_reference(self):
        self.client_api.create_bank_account_validation.return_value = self.validation()
        row = local_money.resolve_destination(self.owner, 'mx_clabe', '032 180 000118359719', client=self.client_api)
        self.assertEqual(row.details, {'type': 'CLABE', 'clabe': '032180000118359719', 'reference': 'Confio'})
        self.assertEqual(row.label, 'CLABE · 032180000118359719')

    @override_settings(**FLAGS)
    def test_provider_failure_is_unverified_never_verified(self):
        self.client_api.create_bank_account_validation.side_effect = ProviderAPIError('down')
        row = local_money.resolve_destination(self.owner, 'br_pix', '12345678909', client=self.client_api)
        self.assertEqual(row.holder_name, '')
        self.assertEqual(local_money.destination_view(row)['verification'], 'unverified')

    @override_settings(**FLAGS)
    def test_not_found_recipient_is_hidden_from_saved(self):
        self.client_api.create_bank_account_validation.return_value = self.validation(status='ERROR', name='')
        local_money.resolve_destination(self.owner, 'ar_cvu', '2850590940090418135201', client=self.client_api)
        self.assertEqual(local_money.saved_destinations(self.owner, 'ar_cvu'), [])
        self.client_api.create_bank_account_validation.assert_called_once_with(
            {'country': 'AR', 'account': {'dataType': 'CBU', 'cbu': '2850590940090418135201'}})

    @override_settings(**FLAGS)
    def test_pending_validation_refreshes(self):
        self.client_api.create_bank_account_validation.return_value = {'id': 'v9', 'status': 'IN_PROGRESS'}
        row = local_money.resolve_destination(self.owner, 'co_breb', '@ana', client=self.client_api)
        self.client_api.get_bank_account_validation.return_value = self.validation()
        row = local_money.refresh_destination(row, client=self.client_api)
        self.client_api.get_bank_account_validation.assert_called_once_with('v9')
        self.assertEqual(local_money.destination_view(row)['verification'], 'verified')

    @override_settings(**FLAGS)
    def test_an_old_verification_is_checked_again(self):
        from datetime import timedelta
        from django.utils import timezone
        self.client_api.create_bank_account_validation.return_value = self.validation()
        row = local_money.resolve_destination(self.owner, 'co_breb', '@maria.rod', client=self.client_api)
        local_money.require_current_destination(row)  # fresh: allowed
        self.assertEqual(local_money.recheck_destination(row, client=self.client_api).pk, row.pk)
        self.client_api.create_bank_account_validation.assert_called_once()  # a fresh check is reused
        old = (timezone.now() - timedelta(hours=25)).isoformat()

        def age(destination):
            validation = {**destination.provider_data['validation'], 'checked_at': old}
            destination.provider_data = {**destination.provider_data, 'validation': validation}
            destination.save(update_fields=['provider_data'])
        age(row)
        with self.assertRaisesRegex(PaymentAccountError, 'Revisa de nuevo'):
            local_money.require_current_destination(row)
        # The key now belongs to someone else: the re-check shows the new holder.
        self.client_api.create_bank_account_validation.return_value = self.validation(name='Pedro Gómez')
        row = local_money.recheck_destination(row, client=self.client_api)
        self.assertEqual(row.holder_name, 'Pedro Gómez')
        local_money.require_current_destination(row)
        # "Revisar" never reuses an old verification either.
        age(row)
        local_money.resolve_destination(self.owner, 'co_breb', '@maria.rod', client=self.client_api)
        self.assertEqual(self.client_api.create_bank_account_validation.call_count, 3)

    @override_settings(**FLAGS)
    def test_an_abandoned_pending_check_starts_again(self):
        from datetime import timedelta
        from django.utils import timezone
        self.client_api.create_bank_account_validation.return_value = {'id': 'v9', 'status': 'IN_PROGRESS'}
        row = local_money.resolve_destination(self.owner, 'co_breb', '@ana', client=self.client_api)
        started = row.provider_data['validation']['checked_at']
        self.client_api.get_bank_account_validation.return_value = self.validation()
        polled = local_money.refresh_destination(row, client=self.client_api)
        self.assertEqual(polled.provider_data['validation']['checked_at'], started)  # the check's own time
        # A check abandoned for days is not today's answer: a new one runs.
        self.client_api.reset_mock()
        self.client_api.create_bank_account_validation.return_value = {'id': 'v10', 'status': 'IN_PROGRESS'}
        other = local_money.resolve_destination(self.owner, 'co_breb', '@beto', client=self.client_api)
        validation = {**other.provider_data['validation'],
                      'checked_at': (timezone.now() - timedelta(hours=25)).isoformat()}
        other.provider_data = {**other.provider_data, 'validation': validation}
        other.save(update_fields=['provider_data'])
        self.client_api.create_bank_account_validation.return_value = self.validation(name='Beto Ruiz')
        other = local_money.refresh_destination(other, client=self.client_api)
        self.client_api.get_bank_account_validation.assert_not_called()
        self.assertEqual(other.holder_name, 'Beto Ruiz')

    @override_settings(**FLAGS)
    def test_a_late_poll_never_overwrites_a_newer_check(self):
        self.client_api.create_bank_account_validation.return_value = {'id': 'v9', 'status': 'IN_PROGRESS'}
        row = local_money.resolve_destination(self.owner, 'co_breb', '@ana', client=self.client_api)
        stale = PayoutDestination.objects.get(pk=row.pk)  # a poll of v9 is still running on this copy
        # Meanwhile a newer check found that the key now belongs to someone else.
        newer = {**local_money.summarize_validation(self.validation(name='Pedro Gómez')), 'id': 'v10'}
        PayoutDestination.objects.filter(pk=row.pk).update(
            holder_name='Pedro Gómez', provider_data={**row.provider_data, 'validation': newer})
        self.client_api.get_bank_account_validation.return_value = self.validation(name='Ana Pérez')
        polled = local_money.refresh_destination(stale, client=self.client_api)
        self.client_api.get_bank_account_validation.assert_called_once_with('v9')
        row.refresh_from_db()
        self.assertEqual((polled.holder_name, row.holder_name), ('Pedro Gómez', 'Pedro Gómez'))
        self.assertEqual(row.provider_data['validation']['id'], 'v10')

    @override_settings(**FLAGS)
    def test_an_older_fresh_check_never_overwrites_a_newer_one(self):
        from datetime import timedelta
        from django.utils import timezone
        self.client_api.create_bank_account_validation.return_value = self.validation(name='Ana Pérez')
        row = local_money.resolve_destination(self.owner, 'co_breb', '@maria.rod', client=self.client_api)
        old = (timezone.now() - timedelta(hours=25)).isoformat()
        PayoutDestination.objects.filter(pk=row.pk).update(provider_data={
            **row.provider_data, 'validation': {**row.provider_data['validation'], 'checked_at': old}})

        def older_check_waits(request):
            # While the older re-check waits on the provider, a newer one runs
            # and finds that the key now belongs to someone else.
            api = self.client_api.create_bank_account_validation
            api.side_effect = None
            api.return_value = self.validation(name='Pedro Gómez')
            local_money.recheck_destination(PayoutDestination.objects.get(pk=row.pk), client=self.client_api)
            return self.validation(name='Ana Pérez')

        self.client_api.create_bank_account_validation.side_effect = older_check_waits
        kept = local_money.recheck_destination(PayoutDestination.objects.get(pk=row.pk), client=self.client_api)
        row.refresh_from_db()
        self.assertEqual((kept.holder_name, row.holder_name), ('Pedro Gómez', 'Pedro Gómez'))

    @override_settings(**FLAGS)
    def test_overlapping_first_lookups_share_one_destination(self):
        def older_lookup_waits(request):
            # While the first lookup waits on the provider, a second one for the
            # same new key runs and finishes first with the current holder.
            api = self.client_api.create_bank_account_validation
            api.side_effect = None
            api.return_value = self.validation(name='Pedro Gómez')
            local_money.resolve_destination(self.owner, 'co_breb', '@nuevo', client=self.client_api)
            return self.validation(name='Ana Pérez')

        self.client_api.create_bank_account_validation.side_effect = older_lookup_waits
        kept = local_money.resolve_destination(self.owner, 'co_breb', '@nuevo', client=self.client_api)
        self.assertEqual(PayoutDestination.objects.filter(confio_account=self.owner, details=kept.details).count(), 1)
        self.assertEqual(kept.holder_name, 'Pedro Gómez')
        again = local_money.resolve_destination(self.owner, 'co_breb', '@nuevo', client=self.client_api)
        self.assertEqual((again.pk, again.holder_name), (kept.pk, 'Pedro Gómez'))

    def test_a_journey_reports_whether_its_bridge_still_needs_signing(self):
        from payment_accounts.journey_schema import InfiniaJourneyType
        unsigned = SimpleNamespace(bridge_id=1, bridge=SimpleNamespace(status='prepared'))
        self.assertEqual(InfiniaJourneyType.resolve_bridge_status(unsigned, None), 'prepared')
        self.assertIsNone(InfiniaJourneyType.resolve_bridge_status(SimpleNamespace(bridge_id=None, bridge=None), None))

    def test_deposit_hold_resolvers_take_the_ledger_entry(self):
        from payment_accounts.journey_schema import InfiniaDepositType
        entry = SimpleNamespace()  # graphene passes the model instance as `self`
        with mock.patch('payment_accounts.payin_admission.is_external_fiat_credit', return_value=True), \
                mock.patch('payment_accounts.payin_admission.decision',
                           return_value=(False, 'sender_identity_missing', None, None)):
            self.assertTrue(InfiniaDepositType.resolve_held(entry, None))
            self.assertEqual(InfiniaDepositType.resolve_held_reason(entry, None), 'sender_identity_missing')
        with mock.patch('payment_accounts.payin_admission.is_external_fiat_credit', return_value=False):
            self.assertFalse(InfiniaDepositType.resolve_held(entry, None))

    # ---- quotes

    def test_incoming_history_excludes_provider_legs_before_pagination(self):
        from django.utils import timezone
        from payment_accounts.models import LedgerEntry, MoneyOperation, MoneyFlow, InfiniaJourney
        from payment_accounts.journey_schema import JourneyQuery
        local, crypto = self.pair()
        def entry(key, *, kind='CREDIT', op=None, voucher=None):
            sender = {'type': 'FIAT', 'full_name': 'Sender', 'document_number': '123'}
            if voucher:
                sender['voucher_id'] = voucher
            return LedgerEntry.objects.create(provider='infinia', financial_account=local,
                provider_entry_id=key, direction='credit', asset=local.asset, amount='32.51',
                occurred_at=timezone.now(), operation=op,
                provider_data={'operation': {'type': kind, 'operation_id': None}, 'third_party': sender})
        receipt = entry('real-incoming')
        flow = MoneyFlow.objects.create(confio_account=self.owner, kind='fund', source_asset='COP', source_amount='32.51')
        InfiniaJourney.objects.create(confio_account=self.owner, money_flow=flow, request_id=uuid.uuid4(),
            local_account=local, crypto_account=crypto, direction='to_wallet', funding_credit=receipt,
            minimum_fx_output='1', minimum_wallet_output='0.9', stage='completed', wallet_address='0x'+'1'*40)
        conversion = MoneyOperation.objects.create(provider='infinia', operation_type='conversion',
            source_account=crypto, destination_account=local, source_asset='USDC_POL', source_amount='2',
            idempotency_key='conversion-history', provider_data={'voucher_ids': ['conversion-voucher']})
        # These newer entries must not consume the first page or masquerade as pay-ins.
        for n in range(21):
            entry(f'conversion-{n}', op=conversion)
        entry('voucher-only', voucher='conversion-voucher')
        entry('null-operation-voucher', kind=None, voucher='conversion-voucher')
        entry('refund', kind='PAYOUT_REFUND')
        entry('internal', kind='INTERNAL_TRANSFER')
        with mock.patch('payment_accounts.schema._active_account', return_value=self.owner):
            rows = JourneyQuery.resolve_local_incoming_deposits(None, SimpleNamespace(), local.internal_id)
            self.assertEqual([r.pk for r in rows], [receipt.pk])
            self.assertEqual(JourneyQuery.resolve_local_incoming_deposits(None, SimpleNamespace(), local.internal_id, 1), [])
            self.assertEqual(JourneyQuery.resolve_local_incoming_deposits(None, SimpleNamespace(), uuid.uuid4()), [])

    def fx(self, target):
        self.client_api.create_transfer_quote.return_value = {
            'id': 'q', 'status': 'ACTIVE', 'target_amount': target, 'expire_at': '2026-09-14T12:00:00Z'}

    def test_payout_quote_derives_the_minimum(self):
        local, crypto = self.pair()
        from payment_accounts.models import FundingInstruction
        FundingInstruction.objects.create(financial_account=crypto, kind='crypto_address', status='active',
                                          display_value='0x' + '22' * 20)
        destination = PayoutDestination.objects.create(
            confio_account=self.owner, provider='infinia', kind='breb_key', country='COL', asset='COP',
            label='Llave', holder_name='Ana', details={'type': 'BREB_KEY', 'brebKey': '@ana'})
        self.fx('205300')
        with mock.patch('payment_accounts.bridge.net_funding_units', return_value='49550000000000000000') as net, \
                mock.patch('payment_accounts.bridge_routing.quote_routes') as bridge, \
                mock.patch('payment_accounts.bridge._require_provider_enabled'):
            bridge.return_value = [
                {'messenger': 'cctp', 'amountOut': '50000000'},
                {'messenger': 'relay', 'amountOut': '49300000', 'amountOutMin': '49000000'}]
            quote = local_money.payout_quote(self.owner, destination, amount='50', client=self.client_api)
            net.assert_called_once_with(self.owner, 50 * 10**18)
            bridge.assert_called_once_with('BSC:USDT', 'POL:USDC', '49550000000000000000',
                                           self.owner.bsc_address, '0x' + '22' * 20)
        self.assertEqual(quote['minimum_target'], Decimal('203247.00'))
        self.assertEqual(quote['rate'], Decimal('4106.0000'))
        payload = self.client_api.create_transfer_quote.call_args.args[0]
        self.assertEqual((payload['source_account_id'], payload['target_account_id'], payload['source_amount']),
                         ('crypto', 'local', 49.0))
        self.assertNotIn('requested_lock_time', payload)
        self.assertEqual(quote['expires_at'], '2026-09-14T12:00:00Z')

    def test_quote_requires_an_active_pair(self):
        destination = PayoutDestination.objects.create(
            confio_account=self.owner, provider='infinia', kind='breb_key', country='COL', asset='COP',
            label='Llave', holder_name='Ana', details={})
        with self.assertRaisesRegex(PaymentAccountError, 'no está activa'):
            local_money.payout_quote(self.owner, destination, amount='50', client=self.client_api)

    def test_fractional_bridge_output_is_floored_for_estimate_and_review(self):
        _, crypto = self.pair()
        from payment_accounts.models import FundingInstruction
        FundingInstruction.objects.create(financial_account=crypto, kind='crypto_address', status='active',
                                          display_value='0x' + '22' * 20)
        destination = SimpleNamespace(country='COL', asset='COP')
        self.fx('7800')
        response = self.client_api.create_transfer_quote.return_value
        def strict_quote(payload):
            value = Decimal(str(payload['source_amount']))
            self.assertEqual(value, value.quantize(Decimal('.01')))
            return response
        self.client_api.create_transfer_quote.side_effect = strict_quote
        with mock.patch('payment_accounts.bridge.net_funding_units', return_value=str(2 * 10**18)), \
                mock.patch('payment_accounts.bridge_routing.quote_routes') as api, \
                mock.patch('payment_accounts.bridge._require_provider_enabled'):
            api.return_value = [{'messenger': 'relay',
                'amountOut': '1960000', 'amountOutMin': '1958795'}]
            estimate = local_money.payout_quote(self.owner, destination, amount='2', client=self.client_api)
        bridge = SimpleNamespace(amount_out_min='1958795', amount_out='1960000', quote=SimpleNamespace(
            confio_account_id=self.owner.pk, source_token_id='BSC:USDT',
            funding_instruction=SimpleNamespace(financial_account_id=crypto.pk),
            money_flow=SimpleNamespace(source_amount=Decimal('2'))))
        review = local_money.payout_quote(self.owner, destination, bridge=bridge, client=self.client_api)
        for result in (estimate, review):
            self.assertEqual(result['source_amount'], Decimal('1.95'))
            self.assertEqual(result['rate'], Decimal('3900'))
            # Disclosure: what should land sits above the minimum we authorize,
            # and the cost is measured against the user's whole $2 budget.
            self.assertEqual(result['expected_source_amount'], Decimal('1.96'))
            self.assertEqual(result['target_amount'], Decimal('7800'))
            self.assertEqual(result['expected_target'], Decimal('7840'))
            self.assertGreater(result['expected_target'], result['minimum_target'])
            self.assertEqual(result['total_cost_percent'], Decimal('2.00'))

    def test_subcent_bridge_output_does_not_request_a_zero_quote(self):
        _, crypto = self.pair()
        bridge = SimpleNamespace(amount_out_min='9999', amount_out='10000', quote=SimpleNamespace(
            confio_account_id=self.owner.pk, source_token_id='BSC:USDT',
            funding_instruction=SimpleNamespace(financial_account_id=crypto.pk),
            money_flow=SimpleNamespace(source_amount=Decimal('0.02'))))
        with self.assertRaisesRegex(PaymentAccountError, '0.01'):
            local_money.payout_quote(self.owner, SimpleNamespace(country='COL', asset='COP'),
                                    bridge=bridge, client=self.client_api)
        self.client_api.create_transfer_quote.assert_not_called()

    @override_settings(PAYMENT_BRIDGE_MAX_USDT='10')
    def test_estimate_respects_the_same_spend_cap_as_preparation(self):
        self.pair()
        destination = SimpleNamespace(country='COL', asset='COP')
        with mock.patch('payment_accounts.bridge.net_funding_units') as funding:
            with self.assertRaisesRegex(PaymentAccountError, 'bridge limit'):
                local_money.payout_quote(self.owner, destination, amount='11', client=self.client_api)
            funding.assert_not_called()
            self.client_api.create_transfer_quote.assert_not_called()

    def test_review_uses_total_budget_for_rate_and_rejects_reverse_bridge(self):
        _, crypto = self.pair()
        destination = SimpleNamespace(country='COL', asset='COP')
        bridge = SimpleNamespace(amount_out_min='49000000', amount_out='49500000', quote=SimpleNamespace(
            confio_account_id=self.owner.pk, source_token_id='BSC:USDT',
            funding_instruction=SimpleNamespace(financial_account_id=crypto.pk),
            money_flow=SimpleNamespace(source_amount=Decimal('50'))))
        self.fx('980')
        result = local_money.payout_quote(self.owner, destination, bridge=bridge, client=self.client_api)
        self.assertEqual(result['rate'], Decimal('19.6000'))
        self.assertEqual(result['source_amount'], Decimal('49'))
        bridge.quote.source_token_id = 'POL:USDC'
        with self.assertRaisesRegex(PaymentAccountError, 'no corresponde'):
            local_money.payout_quote(self.owner, destination, bridge=bridge, client=self.client_api)
        self.client_api.create_transfer_quote.assert_called_once()

    @override_settings(PAYMENT_BRIDGE_MAX_USDT='1000')
    def test_deposit_over_the_bridge_cap_is_refused_before_a_journey(self):
        from payment_accounts.models import LedgerEntry
        from django.utils import timezone
        self.owner.bsc_address = '0x' + '11' * 20
        local, _ = self.pair('MEX', 'MXN')
        credit = LedgerEntry.objects.create(
            provider='infinia', financial_account=local, provider_entry_id='e1', direction='credit', asset='MXN',
            amount='4250.008795', occurred_at=timezone.now(), provider_data={'operation': {'type': 'INTERNAL_TRANSFER'}})
        with mock.patch('payment_accounts.payin_admission.is_external_fiat_credit', return_value=False), \
                mock.patch('payment_accounts.bridge_routing.quote_routes', return_value=[{
                    'messenger': 'relay', 'amountOut': str(209 * 10**18),
                    'amountOutMin': str(208 * 10**18)}]) as bridge:
            self.fx('212.40')
            quote = local_money.deposit_quote(self.owner, credit, client=self.client_api)
            self.assertEqual(quote['source_amount'], Decimal('4250'))
            self.assertEqual(self.client_api.create_transfer_quote.call_args.args[0]['source_amount'], 4250.0)
            self.assertEqual(quote['minimum_fx_output'], Decimal('210.276000'))
            self.assertEqual(quote['minimum_wallet_output'], Decimal('204.880000'))
            bridge.assert_called_once_with('POL:USDC', 'BSC:USDT', '210276000',
                                           self.owner.bsc_address, self.owner.bsc_address)
            with override_settings(PAYMENT_BRIDGE_MAX_USDT='200'):
                with self.assertRaisesRegex(PaymentAccountError, 'máximo por conversión'):
                    local_money.deposit_quote(self.owner, credit, client=self.client_api)

    @override_settings(PAYMENT_BRIDGE_MAX_USDT='')
    def test_bridge_has_no_per_transfer_cap_by_default(self):
        from payment_accounts.bridge import bridge_cap, exceeds_bridge_cap
        self.assertIsNone(bridge_cap())
        self.assertFalse(exceeds_bridge_cap('100000'))
        self.assertIsNone(local_money.limits(self.owner, client=self.client_api)['per_transfer_max'])
        # Still usable as an emergency brake; a malformed brake refuses everything.
        with override_settings(PAYMENT_BRIDGE_MAX_USDT='250'):
            self.assertTrue(exceeds_bridge_cap('250.01'))
            self.assertFalse(exceeds_bridge_cap('250'))
        with override_settings(PAYMENT_BRIDGE_MAX_USDT='0'):
            self.assertTrue(exceeds_bridge_cap('1'))

    def test_small_deposit_prices_real_bridge_cost_at_fx_lower_bound(self):
        from payment_accounts.models import LedgerEntry
        from django.utils import timezone
        self.owner.bsc_address = '0x' + '11' * 20
        local, _ = self.pair('MEX', 'MXN')
        credit = LedgerEntry.objects.create(provider='infinia', financial_account=local,
            provider_entry_id='small-relay', direction='credit', asset='MXN', amount='40',
            occurred_at=timezone.now(), provider_data={'operation': {'type': 'INTERNAL_TRANSFER'}})
        self.fx('2')
        with mock.patch('payment_accounts.payin_admission.is_external_fiat_credit', return_value=False), \
                mock.patch('payment_accounts.bridge_routing.quote_routes', return_value=[{
                    'messenger': 'relay', 'amountOut': str(193 * 10**16),
                    'amountOutMin': str(192 * 10**16)}]) as bridge:
            quote = local_money.deposit_quote(self.owner, credit, client=self.client_api)
        bridge.assert_called_once_with('POL:USDC', 'BSC:USDT', '1980000',
                                       self.owner.bsc_address, self.owner.bsc_address)
        self.assertEqual(quote['minimum_wallet_output'], Decimal('1.891200'))
        self.assertLess(quote['minimum_wallet_output'], Decimal('1.92'))

    # ---- limits

    def test_explicit_null_limit_defers_to_infinia(self):
        local, crypto = self.pair()
        self.client_api.get_account_limits.return_value = {'monthly': {
            'used': 0, 'limit': None, 'remaining': None, 'resets_at': '2026-10-01T00:00:00'}}
        self.journey(local, crypto, '800')
        view = local_money.limits(self.owner, client=self.client_api)
        self.assertFalse(view['known'])
        self.assertTrue(view['has_account'])
        self.assertIsNone(view['limit'])
        self.assertIsNone(view['available'])
        self.assertFalse(view['near_limit'])

    def test_zero_numeric_limit_is_displayed(self):
        _, crypto = self.pair()
        self.client_api.get_account_limits.return_value = {'monthly': {
            'used': 0, 'limit': 0, 'remaining': 0}}
        self.assertEqual(local_money.limits(self.owner, client=self.client_api)['available'], Decimal('0'))

    def journey(self, local, crypto, amount, stage='awaiting_credit'):
        flow = MoneyFlow.objects.create(confio_account=self.owner, kind='withdraw', source_asset='USDT_BSC',
                                        source_amount=amount, target_asset='COP')
        return InfiniaJourney.objects.create(
            money_flow=flow, confio_account=self.owner, request_id=uuid.uuid4(), direction='to_bank',
            stage=stage, local_account=local, crypto_account=crypto, minimum_fx_output='1', wallet_address='0x0')

    def test_unknown_limit_is_informational(self):
        self.pair()
        for response in ({'monthly': {'used': 10, 'resets_at': 'x'}}, {},
                         {'monthly': {'used': 0, 'limit': 'invalid'}},
                         {'monthly': {'used': 0, 'limit': 'NaN'}}):
            self.client_api.get_account_limits.return_value = response
            self.assertFalse(local_money.limits(self.owner, client=self.client_api)['known'])
        self.client_api.get_account_limits.side_effect = ProviderAPIError('down')
        self.assertFalse(local_money.limits(self.owner, client=self.client_api)['known'])

    def test_in_flight_sends_reduce_the_allowance(self):
        local, crypto = self.pair()
        self.client_api.get_account_limits.return_value = {'monthly': {
            'used': 9000, 'limit': 10000, 'remaining': 1000, 'resets_at': '2026-10-01T00:00:00Z'}}
        self.journey(local, crypto, '800')
        self.journey(local, crypto, '5000', stage='completed')
        view = local_money.limits(self.owner, client=self.client_api)
        self.assertEqual((view['available'], view['used'], view['near_limit']),
                         (Decimal('200'), Decimal('9800'), True))

    def test_a_send_completing_right_after_the_snapshot_still_counts(self):
        local, crypto = self.pair()
        sending = self.journey(local, crypto, '800')

        def snapshot_then_complete(_account_id):
            # The provider answered before the send posted; the send completes
            # right after. It was counted before the snapshot, so it still is.
            InfiniaJourney.objects.filter(pk=sending.pk).update(stage='completed')
            return {'monthly': {'used': 9000, 'limit': 10000, 'remaining': 1000, 'resets_at': '2026-10-01T00:00:00Z'}}

        self.client_api.get_account_limits.side_effect = snapshot_then_complete
        self.assertEqual(local_money.limits(self.owner, client=self.client_api)['available'], Decimal('200'))

    # ---- capabilities

    def test_national_means_domicile_not_nationality(self):
        local, _ = self.pair()
        _infinia_capabilities(local)
        status = AccountCapability.objects.get(financial_account=local, capability='receive_same_name').status
        self.assertEqual(status, 'enabled')

    # ---- EDD requirements (what to have at hand before the Didit session)

    def test_edd_asks_for_proof_of_address_then_income_documents(self):
        kinds = [kind for kind, _, _ in local_money.edd_requirements(self.owner, 'employed')]
        self.assertEqual(kinds, ['proof_of_address', 'bank_statements', 'income_proof'])

    def test_brazil_individual_requirements_replace_the_standard_list(self):
        self.pair('BRA', 'BRL')
        kinds = [kind for kind, _, _ in local_money.edd_requirements(self.owner, 'employed')]
        self.assertEqual(kinds, ['proof_of_address', 'irpf', 'irpf_receipt', 'bank_statements'])


class SchemaTests(SimpleTestCase):
    def test_local_money_fields_are_exposed(self):
        from django.conf import settings
        from django.utils.module_loading import import_string
        schema = str(import_string(settings.GRAPHENE['SCHEMA']))
        for field in ('localMoneyMethods', 'localMoneyLimits', 'localPayoutQuote', 'localDepositQuote',
                      'activateLocalMoney', 'resolveLocalDestination', 'startLimitIncreaseVerification',
                      'syncLimitIncreaseVerification', 'documentTypes', 'infiniaJourney(', 'heldReason'):
            self.assertIn(field, schema)
