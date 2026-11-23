"""An exact local amount the person types for a key, an account or an open
QR: priced in dollars so the conversion's guaranteed minimum covers it; the
payout is exactly that amount and the rest stays in the person's own local
account. The payment carries the amount, never the recipient."""
from decimal import Decimal
from unittest import mock
import uuid

from django.test import override_settings

from payment_accounts import local_money, payment_intents
from payment_accounts.infinia_journeys import advance_journey, create_journey
from payment_accounts.models import PayoutDestination
from payment_accounts.payment_intents import IntentRefused
from payment_accounts.services import PaymentAccountError
from .test_breb_fixed_qr import breb
from .test_infinia_journeys import DEST_HASH, JourneyTests, reconcile_provider_credit
from .test_payment_intent_rails import EVERY_LEVEL
from .test_payment_intents import PaymentIntentBase


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class ExactLocalCardTests(PaymentIntentBase):
    def setUp(self):
        super().setUp()
        self.rate = Decimal('5.40')

        def quote(owner, destination, *, amount=None, **kw):
            expected = (amount * self.rate).quantize(Decimal('0.01'))
            return {'minimum_target': (expected * Decimal('0.99')).quantize(Decimal('0.01')),
                    'expected_target': expected, 'rate': self.rate, 'asset': 'BRL', 'expires_at': ''}
        mock.patch.object(local_money, 'payout_quote', side_effect=quote).start()
        mock.patch.object(local_money, 'payout_fee', return_value={'total_usd': '0.30'}).start()

    def send(self, **over):
        request = {'method_id': 'br_pix', 'value': 'ana@example.com', 'amount_local': '500.00', **over}
        return payment_intents.prepare(self.owner, self.user, created_by='scan', source='form', request=request)

    def test_the_card_is_the_exact_amount_priced_in_dollars(self):
        intent = self.send()
        self.assertEqual((intent.family, intent.amount_exact, intent.currency), ('local_transfer', True, 'BRL'))
        self.assertEqual((intent.amount_local, intent.minimum_local), (Decimal('500.00'),) * 2)
        self.assertEqual(intent.params, {'exact_local': '500.00'})
        floor = (intent.total_usd * self.rate).quantize(Decimal('0.01')) * Decimal('0.99')
        self.assertGreaterEqual(floor, Decimal('500.00'))
        self.assertLess(intent.total_usd, Decimal('95.00'))
        # Dollars typed alongside do not override the exact amount.
        self.assertEqual(self.send(amount_usd='1').amount_local, Decimal('500.00'))
        self.assertEqual(payment_intents.journey_minimum(intent), Decimal('500.00'))

    def test_requote_keeps_the_exact_amount(self):
        intent = self.send()
        fresh = payment_intents.requote(self.owner, self.user, intent.internal_id)
        self.assertEqual((fresh.amount_local, fresh.params, fresh.amount_exact),
                         (Decimal('500.00'), {'exact_local': '500.00'}, True))

    def test_refusals(self):
        for bad in ('0', '-5', '1.001', 'abc', '1e12'):
            with self.subTest(amount=bad), self.assertRaises(IntentRefused) as refused:
                self.send(amount_local=bad)
            self.assertEqual(refused.exception.code, 'no_amount')
        # A store's reference is only read off a checkout: with it the amount is not taken.
        with self.assertRaises(IntentRefused) as refused:
            self.send(reference='PEDIDO 1')
        self.assertEqual(refused.exception.code, 'no_amount')

    def test_the_pagar_screen_prices_and_holds_the_exact_amount(self):
        row = local_money.resolve_destination(self.owner, 'br_pix', 'ana@example.com')
        view = local_money.exact_send_quote(self.owner, row, '500.00')
        self.assertEqual((view['amount'], view['asset'], view['total_usd']),
                         (Decimal('500.00'), 'BRL', self.send().total_usd))
        held = local_money.exact_qr_quote(row, local_money.payout_quote(self.owner, row, amount=view['total_usd']),
                                          '500.00')
        self.assertEqual((held['minimum_target'], held['target_amount']), (Decimal('500.00'),) * 2)
        with self.assertRaisesRegex(PaymentAccountError, 'cambió'):
            local_money.exact_qr_quote(row, local_money.payout_quote(self.owner, row, amount=Decimal('5')), '500')
        for bad in ('0', '1.001'):
            with self.subTest(amount=bad), self.assertRaises(PaymentAccountError):
                local_money.exact_send_quote(self.owner, row, bad)
        # A QR that carries its own amount is never re-priced to another one.
        fixed = local_money.resolve_destination(self.owner, 'co_qr', breb('25000'))
        with self.assertRaisesRegex(PaymentAccountError, 'trae su monto'):
            local_money.exact_send_quote(self.owner, fixed, '1000')


class ExactLocalJourneyTests(JourneyTests):
    def destination(self):
        return PayoutDestination.objects.create(
            confio_account=self.owner, provider='infinia', kind='bank_account', country='PER', asset='PEN',
            label='Cuenta', holder_name='', details={'type': 'CCI', 'cci': '00219300123456789012'},
            provider_data={'method_id': 'br_pix'})

    def bridge(self):
        t, _ = self.prepared(); t.status = 'delivered'; t.destination_tx_hash = DEST_HASH; t.save()
        self.credit(self.crypto, amount='10.008795', provider_data={'third_party': {
            'type': 'CRYPTO', 'crypto_network': 'POLYGON', 'transaction_hash': DEST_HASH}})
        reconcile_provider_credit(t)
        return t

    def journey(self, destination, exact, minimum='1249.00', bridge=None):
        return create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                              request_id=uuid.uuid4(), direction='to_bank', bridge=bridge or self.bridge(),
                              destination=destination, minimum_fx_output=minimum, exact_payout=exact)

    def test_pays_exactly_the_typed_amount_and_the_rest_stays_local(self):
        j = self.journey(self.destination(), Decimal('1249.00'))
        self.assertEqual(j.destination_snapshot['store_order']['amount'], '1249.00')
        self.assertFalse(j.destination_snapshot['store_order']['once'])
        self.fx_quote('crypto', 'local', output='1262.40')
        advance_journey(j.pk, client=self.api)
        self.settle_fx(j, self.local, '1262.40')
        advance_journey(j.pk, client=self.api); j.refresh_from_db(); j.money_flow.refresh_from_db()
        self.assertEqual(j.payout_operation.source_amount, Decimal('1249.00'))
        self.assertEqual(Decimal(j.money_flow.metadata['store_order_remainder']['amount']), Decimal('13.40'))

    def test_an_authorization_below_the_amount_is_refused(self):
        with self.assertRaisesRegex(PaymentAccountError, 'no cubre'):
            self.journey(self.destination(), Decimal('1249.00'), minimum='1200.00')

    def test_the_same_recipient_can_be_paid_again(self):
        t = self.bridge()
        destination = self.destination()
        self.journey(destination, Decimal('1249.00'), bridge=t)
        try:   # a reused bridge may be refused for its own reasons, never as "paid once"
            self.journey(destination, Decimal('1249.00'), bridge=t)
        except PaymentAccountError as exc:
            self.assertNotIn('otra vez', str(exc))

    def test_an_amount_that_disagrees_with_the_recipient_is_refused(self):
        t = self.bridge()   # one funded bridge per test (the fixture)
        for exact in (Decimal('12.345'), Decimal('0')):
            with self.subTest(exact=exact), self.assertRaises(PaymentAccountError):
                self.journey(self.destination(), exact, bridge=t)
        fixed = self.destination()
        fixed.provider_data = {'method_id': 'co_qr', 'breb_qr': local_money.decode_breb_qr(breb('1249'))}
        fixed.save()
        with self.assertRaisesRegex(PaymentAccountError, 'no coincide'):
            self.journey(fixed, Decimal('1000.00'), bridge=t)


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL)
class PagoMovilExactCardTests(PaymentIntentBase):
    """Pago Móvil in exact bolívares, on the provider that can price them."""

    def setUp(self):
        super().setUp()
        mock.patch('ramps.ve_pagomovil.enabled', return_value=True).start()
        mock.patch('ramps.ve_pagomovil.client_supports', return_value=True).start()
        self.adapter = mock.Mock()
        self.adapter.quote_exact.side_effect = lambda ves: {
            'usd_amount': '16.40', 'usdt_amount': '16.20', 'confio_fee_usd': '0.20', 'processor_fee_usd': '0.30',
            'estimated_ves': format(Decimal(ves), '.2f'), 'exact_ves': format(Decimal(ves), '.2f'),
            'rate': '1000.0000'}
        mock.patch('ramps.ve_pagomovil.send_adapter', return_value=self.adapter).start()

    def send(self, **over):
        request = {'method_id': 've_pagomovil_send', 'amount_local': '15000', 'phone': '04141234567',
                   'cedula': 'V12345678', 'bank_code': '0102', 'holder_name': 'María Pérez', **over}
        return payment_intents.prepare(self.owner, self.user, created_by='scan', source='form', request=request)

    def test_the_card_is_the_exact_bolivares_priced_in_dollars(self):
        intent = self.send()
        self.assertEqual((intent.family, intent.amount_exact, intent.currency), ('ramp_order', True, 'VES'))
        self.assertEqual((intent.amount_local, intent.minimum_local, intent.total_usd),
                         (Decimal('15000.00'), Decimal('15000.00'), Decimal('16.40')))
        self.assertEqual(intent.params['exact_ves'], '15000.00')
        from payment_accounts.intent_rails import PagoMovilRail
        self.assertEqual(PagoMovilRail().request_of(intent)['amount_local'], '15000.00')

    def test_a_provider_that_cannot_price_bolivares_refuses(self):
        self.adapter = mock.Mock(spec=['quote'])
        mock.patch('ramps.ve_pagomovil.send_adapter', return_value=self.adapter).start()
        with self.assertRaises(IntentRefused) as refused:
            self.send()
        self.assertEqual(refused.exception.code, 'rail')
