"""Regressions for unfunded Colombian orders caused by fee precision drift."""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from ramps import schema
from ramps.koywe_client import KoyweOrderStatusResult


PRODUCTION_AMOUNTS = (
    ('54.797025898', '54.797025'),
    ('54.806052917', '54.806052'),
    ('54.810567913', '54.810567'),
    ('54.815081918', '54.815081'),
)
ADDRESS = '0x' + '1' * 40
WAD = Decimal(10 ** 18)


class KoyweFundingPrecisionTests(SimpleTestCase):
    def ramp(self, net='54.806052917', provider='54.806052'):
        return SimpleNamespace(
            direction='off_ramp', destination='cusd_plus',
            crypto_amount_estimated=Decimal(provider),
            metadata={'auth_email': 'owner@example.com', 'provider_payload_created': {
                'confioNetAmount': net, 'confioGrossAmount': '55.303787',
                'confioProviderAmount': provider, 'amountIn': provider,
            }},
        )

    def test_provider_grain_floors_all_four_observed_orders(self):
        for net, provider in PRODUCTION_AMOUNTS:
            with self.subTest(net=net):
                canonical = schema._koywe_provider_amount(Decimal(net))
                self.assertEqual(canonical, Decimal(provider))
                self.assertTrue(schema._provider_amount_matches(provider, canonical, enforce=True))

    def test_invalid_and_dust_provider_amounts_are_rejected(self):
        for value in ('NaN', 'sNaN', 'Infinity', '-Infinity', '-1', '0', '0.0000009', 'bad'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                schema._koywe_provider_amount(value)

    def test_provider_echo_requires_exact_finite_amount_even_below_one_micro(self):
        for echoed in ('54.8060521', '54.806053', '54.806051', 'NaN', 'sNaN', 'Infinity', None):
            with self.subTest(echoed=echoed):
                self.assertFalse(schema._provider_amount_matches(
                    echoed, Decimal('54.806052'), enforce=True))

    def test_stored_voucher_uses_provider_amount_not_unrounded_net(self):
        for net, provider in PRODUCTION_AMOUNTS:
            with self.subTest(net=net):
                ramp = self.ramp(net, provider)
                self.assertEqual(schema._stored_koywe_deposit_wei(ramp), int(Decimal(provider) * WAD))
                del ramp.metadata['provider_payload_created']['confioProviderAmount']
                self.assertEqual(schema._stored_koywe_deposit_wei(ramp), int(Decimal(provider) * WAD))

    def test_stored_voucher_rejects_inconsistent_metadata(self):
        for field, value in (
            ('confioProviderAmount', '54.806051'),
            ('confioProviderAmount', '54.8060521'),
            ('confioNetAmount', '54.806051999'),
            ('confioNetAmount', 'NaN'),
            ('confioProviderAmount', 'Infinity'),
        ):
            with self.subTest(field=field, value=value):
                ramp = self.ramp()
                ramp.metadata['provider_payload_created'][field] = value
                self.assertIsNone(schema._stored_koywe_deposit_wei(ramp))

    def test_legacy_order_without_fee_metadata_does_not_get_amount_voucher(self):
        ramp = self.ramp()
        ramp.metadata = {}
        self.assertIsNone(schema._stored_koywe_deposit_wei(ramp))
        self.assertIsNone(schema._stored_koywe_deposit_wei(None))

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_quote_sends_canonical_net_for_each_production_amount(self):
        info = SimpleNamespace(context=SimpleNamespace(user=None))
        for net, provider in PRODUCTION_AMOUNTS:
            with self.subTest(net=net):
                preview = SimpleNamespace(net=Decimal(net), gross=Decimal('55.3'),
                                          fee=Decimal('0.49'), fee_bps=90)
                client = mock.Mock(is_configured=True)
                client.get_ramp_quote.return_value = dict(
                    direction='OFF_RAMP', amount_in=provider, amount_out='170021',
                    exchange_rate='3100', fee_amount='0', fee_currency='COP',
                    network_fee_amount='0', network_fee_currency='USDT BSC',
                    rate_display='', total_change_display='', token_symbol='USDT',
                    network_symbol='BSC', network_display='BSC', asset_note='',
                )
                with mock.patch.object(schema, '_resolve_ramp_country_code', return_value='CO'), \
                     mock.patch.object(schema, 'KoyweClient', return_value=client), \
                     mock.patch('cusd_plus.cusd_vault.preview_redeem_wei', return_value=preview):
                    result = schema.Query().resolve_ramp_quote(
                        info, direction='OFF_RAMP', amount='55.3', country_code='CO',
                        fiat_currency='COP', destination='cusd_plus')
                self.assertEqual(client.get_ramp_quote.call_args.kwargs['amount'], Decimal(provider))
                self.assertEqual(Decimal(result.amount_in), Decimal('55.3'))

    def status(self, ramp, payload, sync_side_effect=None):
        info = SimpleNamespace(context=SimpleNamespace(user=SimpleNamespace(is_authenticated=True)))
        client = mock.Mock(is_configured=True)
        client.get_ramp_order_status.return_value = KoyweOrderStatusResult(
            order_id='order', status='PENDING', raw_response=payload)
        with mock.patch.object(schema, '_resolve_ramp_country_code', return_value='CO'), \
             mock.patch.object(schema, 'KoyweClient', return_value=client), \
             mock.patch.object(schema.RampTransaction.objects, 'filter') as find, \
             mock.patch.object(schema, 'sync_koywe_ramp_transaction_from_order', side_effect=sync_side_effect):
            find.return_value.first.return_value = ramp
            return schema.Query().resolve_ramp_order_status(info, 'order', country_code='CO')

    def test_status_real_dto_recovers_exact_funding_amount_after_resume(self):
        result = self.status(self.ramp(), {'amountIn': '54.806052', 'depositAddress': ADDRESS})
        self.assertTrue(result.success)
        self.assertEqual(result.payment_details['confioDepositAddress'], ADDRESS)
        self.assertEqual(result.payment_details['confioDepositAmountWei'], str(int(Decimal('54.806052') * WAD)))
        self.assertEqual(result.payment_details['confioGrossDebitAmountWei'], str(int(Decimal('55.303787') * WAD)))

    def test_status_provider_mismatch_withholds_funding_including_submicro(self):
        for amount in ('54.806053', '54.8060521', 'NaN', None):
            with self.subTest(amount=amount):
                result = self.status(self.ramp(), {'amountIn': amount, 'depositAddress': ADDRESS})
                self.assertNotIn('confioDepositAddress', result.payment_details)
                self.assertNotIn('confioDepositAmountWei', result.payment_details)

    def test_status_accepts_order_destination_address_only_for_off_ramp(self):
        payload = {'amountIn': '54.806052', 'destinationAddress': ADDRESS}
        result = self.status(self.ramp(), payload)
        self.assertEqual(result.payment_details['confioDepositAddress'], ADDRESS)
        ramp = self.ramp()
        ramp.direction = 'on_ramp'
        result = self.status(ramp, payload)
        self.assertNotIn('confioDepositAddress', result.payment_details)

    def test_status_conflicting_destination_address_fails_closed(self):
        result = self.status(self.ramp(), {
            'amountIn': '54.806052', 'destinationAddress': ADDRESS,
            'depositAddress': '0x' + '2' * 40,
        })
        self.assertNotIn('confioDepositAddress', result.payment_details)

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_create_vouches_exact_provider_amount_and_persists_precision_snapshot(self):
        from contextlib import ExitStack, nullcontext
        from cusd_plus.cusd_vault import ConversionPreview
        from ramps.koywe_client import KoyweOrderResult

        user = SimpleNamespace(is_authenticated=True, ramp_user_address=None)
        account = SimpleNamespace(pk=1, account_type='personal', display_name='Owner',
                                  bsc_address=ADDRESS)
        info = SimpleNamespace(context=SimpleNamespace(
            user=user, META={'HTTP_X_CONFIO_FEE_CAPABLE': '1'}))
        gross = Decimal('55.303787')
        for net, provider in PRODUCTION_AMOUNTS:
            with self.subTest(net=net), ExitStack() as stack:
                preview = ConversionPreview(int(gross * WAD), int((gross - Decimal(net)) * WAD),
                                            int(Decimal(net) * WAD), 90)
                client = mock.Mock(is_configured=True)
                client.create_ramp_order.return_value = KoyweOrderResult(
                    order_id='order', amount_in=provider, amount_out='170021',
                    total_change_display='', rate_display='', payment_method_display='Bank',
                    next_step='deposit', raw_response={'amountIn': provider, 'depositAddress': ADDRESS})
                for name, value in {
                    'KoyweClient': client, '_employee_ramp_denial': None,
                    '_get_wallet_upgrade_blocker': None, '_resolve_ramp_country_code': 'CO',
                    '_get_ramp_account_for_user': account, '_get_saved_bank_info': {'id': 1},
                    '_get_koywe_auth_email': 'owner@example.com', '_store_koywe_auth_email': None,
                    '_get_koywe_contact_profile': {'activity': 'EMPLOYEE'},
                    '_get_koywe_profile_previous_emails': [],
                }.items():
                    stack.enter_context(mock.patch.object(schema, name, return_value=value))
                stack.enter_context(mock.patch('cusd_plus.cusd_vault.require_operational'))
                stack.enter_context(mock.patch('cusd_plus.cusd_vault.preview_redeem_wei', return_value=preview))
                for name, value in {'usdt_balance_raw': 0, 'cusd_withdrawable_usdt_wei': 100 * 10**18,
                                    'withdrawable_usdt_wei': 100 * 10**18}.items():
                    stack.enter_context(mock.patch('cusd_plus.vault.' + name, return_value=value))
                stack.enter_context(mock.patch.object(schema.transaction, 'atomic', return_value=nullcontext()))
                accounts = stack.enter_context(mock.patch.object(schema.Account.objects, 'select_for_update'))
                accounts.return_value.filter.return_value.first.return_value = account
                ramps = stack.enter_context(mock.patch.object(schema.RampTransaction.objects, 'filter'))
                ramps.return_value.exists.return_value = False
                stack.enter_context(mock.patch.object(schema.RampTransaction.objects, 'create'))
                upsert = stack.enter_context(mock.patch.object(schema, 'upsert_koywe_ramp_transaction'))
                upsert.return_value = self.ramp(net, provider)
                result = schema.CreateRampOrder().mutate(
                    info, direction='OFF_RAMP', amount=str(gross), payment_method_code='BANK',
                    country_code='CO', fiat_currency='COP', bank_info_id='1', destination='cusd_plus')
                self.assertTrue(result.success, result.error)
                self.assertEqual(client.create_ramp_order.call_args.kwargs['amount'], Decimal(provider))
                self.assertEqual(result.payment_details['confioDepositAddress'], ADDRESS)
                self.assertEqual(result.payment_details['confioDepositAmountWei'], str(int(Decimal(provider) * WAD)))
                self.assertEqual(result.payment_details['confioGrossDebitAmountWei'], str(int(gross * WAD)))
                snapshot = upsert.call_args.kwargs['order_payload']
                self.assertEqual(Decimal(snapshot['confioProviderAmount']), Decimal(provider))
                self.assertEqual(Decimal(snapshot['confioNetAmount']), Decimal(net))
                self.assertEqual(Decimal(result.amount_in), gross)

    def test_status_malformed_fee_voucher_never_falls_back_to_legacy_funding(self):
        for field, value in (('confioNetAmount', None), ('confioNetAmount', 'NaN'),
                             ('confioNetAmount', '54.806051'), ('confioProviderAmount', '54.806051')):
            with self.subTest(field=field, value=value):
                ramp = self.ramp()
                if value is None:
                    del ramp.metadata['provider_payload_created'][field]
                else:
                    ramp.metadata['provider_payload_created'][field] = value
                result = self.status(ramp, {'amountIn': '54.806052', 'depositAddress': ADDRESS})
                self.assertNotIn('confioDepositAddress', result.payment_details)
                self.assertNotIn('confioDepositAmountWei', result.payment_details)

    def test_nonfinite_recorded_amount_never_gets_vouched(self):
        ramp = self.ramp()
        ramp.crypto_amount_estimated = Decimal('NaN')
        ramp.metadata['provider_payload_created']['amountIn'] = 'NaN'
        self.assertIsNone(schema._stored_koywe_deposit_wei(ramp))
        result = self.status(ramp, {'amountIn': '54.806052', 'depositAddress': ADDRESS})
        self.assertNotIn('confioDepositAddress', result.payment_details)

    def test_status_sync_cannot_reauthorize_a_changed_provider_amount(self):
        def sync_amount(*, ramp_tx, order_payload, **kwargs):
            ramp_tx.crypto_amount_estimated = Decimal(order_payload['amountIn'])

        for modern in (True, False):
            for immutable_snapshot in (True, False):
                with self.subTest(modern=modern, immutable_snapshot=immutable_snapshot):
                    ramp = self.ramp()
                    created = ramp.metadata['provider_payload_created']
                    if not modern:
                        del created['confioProviderAmount']
                    if immutable_snapshot:
                        created['amountIn'] = '54.806052'
                    else:
                        del created['amountIn']
                    result = self.status(ramp, {
                        'amountIn': '50', 'depositAddress': ADDRESS,
                    }, sync_side_effect=sync_amount)
                    self.assertEqual(ramp.crypto_amount_estimated, Decimal('50'))
                    self.assertNotIn('confioDepositAddress', result.payment_details)
                    self.assertNotIn('confioDepositAmountWei', result.payment_details)

    def test_status_uses_creation_snapshot_even_after_previous_poll_mutated_row(self):
        for modern in (True, False):
            with self.subTest(modern=modern):
                ramp = self.ramp()
                created = ramp.metadata['provider_payload_created']
                created['amountIn'] = '54.806052'
                if not modern:
                    del created['confioProviderAmount']
                ramp.crypto_amount_estimated = Decimal('50')
                result = self.status(ramp, {'amountIn': '50', 'depositAddress': ADDRESS})
                self.assertNotIn('confioDepositAddress', result.payment_details)

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_quote_rejects_nonfinite_amount_before_provider_or_preview(self):
        info = SimpleNamespace(context=SimpleNamespace(user=None))
        with mock.patch.object(schema, '_resolve_ramp_country_code', return_value='CO'), \
             mock.patch.object(schema, 'KoyweClient') as client, \
             mock.patch('cusd_plus.cusd_vault.preview_redeem_wei') as preview:
            for amount in ('NaN', 'sNaN', 'Infinity', '-Infinity'):
                with self.subTest(amount=amount), self.assertRaises(ValidationError):
                    schema.Query().resolve_ramp_quote(
                        info, direction='OFF_RAMP', amount=amount, country_code='CO',
                        fiat_currency='COP', destination='cusd_plus')
            preview.assert_not_called()
            client.assert_not_called()

    def test_invalid_gross_or_net_above_gross_cannot_be_treated_as_legacy(self):
        for gross in (None, 'NaN', 'Infinity', '0', '-1', '54'):
            with self.subTest(gross=gross):
                ramp = self.ramp()
                created = ramp.metadata['provider_payload_created']
                if gross is None:
                    del created['confioGrossAmount']
                else:
                    created['confioGrossAmount'] = gross
                self.assertIsNone(schema._stored_koywe_deposit_wei(ramp))
                result = self.status(ramp, {'amountIn': '54.806052', 'depositAddress': ADDRESS})
                self.assertNotIn('confioDepositAddress', result.payment_details)
                self.assertNotIn('confioDepositAmountWei', result.payment_details)

    def test_repeated_poll_without_immutable_amount_never_vouches(self):
        ramp = self.ramp()
        created = ramp.metadata['provider_payload_created']
        del created['amountIn']
        del created['confioProviderAmount']
        def sync_amount(*, ramp_tx, order_payload, **kwargs):
            ramp_tx.crypto_amount_estimated = Decimal(order_payload['amountIn'])
        for amount in ('50', '50', '54.806052'):
            result = self.status(ramp, {'amountIn': amount, 'depositAddress': ADDRESS},
                                 sync_side_effect=sync_amount)
            self.assertNotIn('confioDepositAddress', result.payment_details)
            self.assertNotIn('confioDepositAmountWei', result.payment_details)
