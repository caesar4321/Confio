"""What the owner signs on the rule screen, with no chat involved: what comes
out of a payout's amount, the Pago Móvil preflight and floor, the stored copy,
and a send's payee line. Imports nothing of the assistant or its guard.
Synthetic accounts, phones and names only; no provider, chain or model is
called."""
from decimal import ROUND_DOWN, Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings

from payment_accounts.models import PayoutDestination
from smart_account import payouts, relay_policy, reconcile, services
from smart_account.models import (
    SmartAccountPagoMovilDestination, SmartAccountPreparedAction, SmartAccountRule, SmartAccountStandingAuthorization,
)

from .base import CUSD, INFINIA_SWITCHES, VAULT, SmartAccountTestCase, priced_pagomovil, vault_preview
from .infinia_base import InfiniaPayoutCase

CLABE = '002180000000004322'
EMAIL = 'silva@example.com'
ON = dict(SMART_ACCOUNT_PAYOUT_RAILS='mx_clabe,br_pix,ve_pagomovil', SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=True,
          SMART_ACCOUNT_PAYOUT_VERIFIED_ADAPTERS='pagoasap', INFINIA_ACCOUNT_VALIDATION_ENABLED=False,
          VE_PAGOMOVIL_SEND_ENABLED=True, PAGOASAP_DEPOSIT_ADDRESS_POLYGON='0x' + '9a' * 20, **INFINIA_SWITCHES)


@override_settings(**ON)
class ScreenCase(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)
        self.face = mock.MagicMock(return_value='face-1')
        for patch in (mock.patch('payment_accounts.local_money.require_rail'),
                      mock.patch('smart_account.payouts.ramps_contract_funding_ready', return_value=True),
                      mock.patch('payment_accounts.services.require_outgoing_face', self.face),
                      mock.patch('security.face_step_up.step_up_applies', return_value=True),
                      mock.patch('smart_account.payouts.reference_ves_rate', return_value=Decimal('40'))):
            patch.start()
            self.addCleanup(patch.stop)

    def local(self, method='mx_clabe', value=CLABE):
        clabe = method == 'mx_clabe'
        from payment_accounts import local_money
        field = local_money.METHODS[method].field
        details = {'type': 'CLABE', 'reference': 'Confio', field: value} if clabe else {'type': 'PIX', field: value}
        return PayoutDestination.objects.create(
            confio_account=self.account.owner_account, provider='infinia', kind='bank_account',
            country='MEX' if clabe else 'BRA', asset='MXN' if clabe else 'BRL', label=f'x · {value}', holder_name='',
            status='active', details=details, provider_data={'method_id': method, 'validation': dict(
                id='', status='DISABLED', holder_name='', checked_at='2026-11-22T00:00:00+00:00')})

    def pagomovil(self):
        return SmartAccountPagoMovilDestination.objects.create(
            user=self.owner, phone='584141234567', bank_code='0134', id_number='V22222222', holder_name='Luis Prueba',
            label='Pago Móvil · Banesco · 4567')

    def prepare(self, destination, amount='100'):
        return services.prepare_payout_rule(self.viewer(self.owner), None, str(destination.internal_id), amount,
                                            'monthly')

    def priced(self, usdt):
        return mock.patch('smart_account.infinia_payouts.preflight', return_value=SimpleNamespace(
            rate=Decimal('18.5'), fee=None, units=int(Decimal(usdt) * 10 ** 18), cost_usd=Decimal('0.23'),
            cost_bps=24))


class CostLineTests(ScreenCase):
    def test_a_cusd_rule(self):
        with self.priced('99.10'), mock.patch('smart_account.services.account_dollar_token', return_value=CUSD):
            shown = ' '.join(self.prepare(self.local()).summary)
        self.assertIn('US$0.90 de comisión de conversión', shown)
        self.assertIn('US$0.23 de costo de envío', shown)
        self.assertIn('1.829,09 MXN', shown)
        self.assertNotIn('margen', shown)

    def test_a_dollar_plus_rule_shows_its_margin_apart(self):
        with self.priced('99.050474'), mock.patch('smart_account.services.account_dollar_token', return_value=VAULT):
            shown = ' '.join(self.prepare(self.local()).summary)
        self.assertIn('US$0.90 de comisión de conversión', shown)
        self.assertIn('Hasta US$0.05 de margen no se envía: queda en tu cuenta.', shown)

    def test_the_stored_copy_is_masked_and_confirm_and_reconcile_still_find_the_rule(self):
        from blockchain.models import SponsoredBatch
        for number, (method, value) in enumerate((('mx_clabe', CLABE), ('br_pix', EMAIL)), 1):
            destination = self.local(method, value)
            with self.priced('99.10'):
                batch = self.prepare(destination)
            action = SmartAccountPreparedAction.objects.get(request_id=batch.request_id)
            whole, stored = services._signed_destination(destination), ' '.join(action.payload['summary'])
            self.assertIn(whole, batch.summary)
            self.assertNotIn(whole, stored)
            self.assertNotIn(value, stored)
            checked = relay_policy.validate_batch(batch.calls, self.owner, self.owner.wallet, batch.request_id + '_a0')
            sponsored = SponsoredBatch.objects.create(
                user=self.owner, user_bsc_address=self.owner.wallet, kind='smart_rule', num_calls=1, calls_json='[]',
                tx_hash=f'0x{number:064x}', gas_limit=1, max_fee_wei='1', status='sent',
                client_request_id=batch.request_id + '_a0')
            relay_policy.consume(checked, sponsored)
            event = SimpleNamespace(args={'id': str(number)}, tx_hash=sponsored.tx_hash)
            self.assertEqual(reconcile._draft_rule(event, self.account, 'rule_pk').pk, action.payload['rule_pk'])


class PagoMovilScreenTests(ScreenCase):
    def setUp(self):
        super().setUp()
        self.payout_cost, self.route_cost = Decimal('0.003'), None
        client = SimpleNamespace(preview=lambda ves: {'total': str(Decimal(ves) / 40 * (1 + self.payout_cost))})
        for patch in (mock.patch('ramps.pagoasap_send.quote', side_effect=self.quote),
                      mock.patch('ramps.pagoasap_send.funding_target', side_effect=self.route),
                      mock.patch('ramps.pagoasap_send._client', return_value=client),
                      mock.patch('cusd_plus.cusd_vault.preview_redeem_wei', side_effect=vault_preview(90))):
            patch.start()
            self.addCleanup(patch.stop)

    @staticmethod
    def quote(amount):
        usdt = Decimal(amount) * Decimal('0.991')
        delivered = usdt - Decimal('0.043') - usdt * Decimal('0.0019')
        return dict(rate='40', usdt_amount=str(usdt),
                    estimated_ves=str((delivered * 40).quantize(Decimal('0.01'), rounding=ROUND_DOWN)))

    def route(self, order):
        sent = Decimal(order.metadata['ve_send']['deposit_wei']) / 10 ** 18
        cost = sent * Decimal('0.0019') + Decimal('0.043') if self.route_cost is None else sent * self.route_cost
        return {'binding': {'amount_out': str(int((sent - cost) * 10 ** 6))}}

    def refused(self, amount, code):
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare(self.pagomovil(), amount)
        self.assertEqual(raised.exception.code, code)
        self.assertNotIn('próxima fecha', raised.exception.message)
        self.face.assert_not_called()
        self.assertFalse(SmartAccountStandingAuthorization.objects.exists())
        self.assertFalse(SmartAccountRule.all_objects.exists())

    def test_one_dollar(self):
        self.refused('1', 'bridge_cost_above_limit')

    def test_three_dollars(self):
        self.refused('3', 'bridge_cost_above_limit')

    def test_the_route_that_gets_the_money(self):
        self.route_cost = Decimal('0.02')
        self.refused('100', 'bridge_cost_above_limit')

    def test_the_floor_counts_the_providers_cost(self):
        self.payout_cost = Decimal('0.035')
        self.refused('100', 'fx_rate_below_limit')

    def test_an_outage(self):
        with mock.patch('ramps.pagoasap_send.quote', side_effect=RuntimeError('down')):
            self.refused('100', 'payout_quote_unavailable')

    def test_the_signed_lines(self):
        shown = ' '.join(self.prepare(self.pagomovil()).summary)
        self.assertIn('US$0.90 de comisión de conversión', shown)
        self.assertIn('de costo de envío', shown)
        self.assertIn('contando el costo del proveedor por pagarlo', shown)
        self.assertNotIn('4.000,00', shown)


class SavedAgainTests(ScreenCase):
    def save(self, name, phone='0414 1234567'):
        return services.save_pagomovil_destination(self.viewer(self.owner), phone, '0134', 'V22222222', name)

    def test_the_name_typed_last_is_the_one_shown_as_typed_and_the_payee_is_the_same(self):
        with priced_pagomovil():
            row = self.save('Luis Prueba')
            self.prepare(row)
            rule = SmartAccountRule.all_objects.get()
            SmartAccountRule.all_objects.filter(pk=rule.pk).update(state='onchain', active=True, onchain_id=1)
            rule.refresh_from_db()
            ref, binding = rule.payout_ref, rule.standing_authorization.binding_hash

            again = self.save('  Carlos   Nuevo ', phone='+58 414-1234567')
            self.assertEqual(again.holder_name, 'Carlos Nuevo')
            shown = ' '.join(self.prepare(again, '120').summary)
        self.assertIn('(escribiste: Carlos Nuevo)', shown)
        self.assertNotIn('Luis Prueba', shown)

        # Who is paid: the same row, identity, ref and Face binding, and the signed rule still runs.
        stored = SmartAccountPagoMovilDestination.objects.get()
        self.assertEqual((again.pk, stored.pk), (row.pk, row.pk))
        self.assertEqual((stored.phone, stored.bank_code, stored.id_number), ('584141234567', '0134', 'V22222222'))
        self.assertEqual('0x' + payouts.pagomovil_ref_for(stored).hex(), ref)
        self.assertEqual(payouts.pagomovil_binding_hash(stored, Decimal('100.00'), 'monthly'), binding)
        rule.refresh_from_db()
        self.assertTrue(services.rule_pays(rule, stored))
        self.assertIsNone(payouts.authorization_problem(rule))


class SendLineTests(ScreenCase):
    def test_the_payees_name_is_one_clean_line(self):
        payee = self.make_user('casero')
        payee.first_name, payee.last_name = 'Ana‮', 'Prueba\nTitular verificado'
        payee.save()
        with mock.patch('smart_account.services.account_dollar_token', return_value=CUSD):
            (line,) = services.prepare_send_rule(self.viewer(self.owner), None, 'casero', '100', 'monthly').summary
        self.assertNotIn('\n', line)
        self.assertNotIn('‮', line)
        self.assertIn('(@casero)', line)


@override_settings(CUSD_CONVERSION_FEE_ENABLED=False)
class InfiniaScreenTests(InfiniaPayoutCase):
    amount = '100.00'

    def test_the_lines_are_built_from_the_real_preflight(self):
        priced = services.preflight_payout(
            self.viewer(), self.account, services.payable_preview(self.destination), Decimal(self.amount), self.token)
        shown = ' '.join(self.prepare().summary)
        paid = Decimal(priced.units) / 10 ** 18 - priced.cost_usd
        fiat = (paid * priced.rate.quantize(Decimal('1e-8'))).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        self.assertIn(f'{fiat:,.2f}'.translate(str.maketrans(',.', '.,')), shown)
