"""A Bre-B QR with a fixed amount (EMV tag 54): priced in dollars so the
conversion's guaranteed minimum covers it; the payout is exactly the QR's
pesos and what the conversion lands above it stays in the person's own
peso account (the same path as a store's SPEI order)."""
from decimal import Decimal
from unittest import mock
import uuid

from django.test import override_settings

from payment_accounts import intent_rails, local_money, payment_intents
from payment_accounts.infinia_journeys import advance_journey, create_journey
from payment_accounts.models import InfiniaJourney, PayoutDestination
from payment_accounts.services import PaymentAccountError
from .test_infinia_journeys import DEST_HASH, JourneyTests, reconcile_provider_credit
from .test_local_money import qr, tlv
from .test_payment_intent_rails import EVERY_LEVEL
from .test_payment_intents import PaymentIntentBase


def argentina(amount=None, dynamic=True, name='KIOSCO'):
    fields = [('01', '12' if dynamic else '11'), ('43', 'com.mercadolibre'), ('53', '032')]
    fields += [('54', amount)] if amount else []
    return qr(*fields, ('58', 'AR'), ('59', name))


def breb(amount=None, dynamic=True, key='@tienda', name='TIENDA'):
    fields = [('01', '12' if dynamic else '11'), ('26', tlv('00', 'CO.COM.RBM.LLA') + tlv('04', key)),
              ('53', '170')]
    fields += [('54', amount)] if amount else []
    return qr(*fields, ('58', 'CO'), ('59', name))


class FixedBrebDestinationTests(JourneyTests):
    def destination(self, payload):
        return PayoutDestination.objects.create(
            confio_account=self.owner, provider='infinia', kind='breb_key', country='PER', asset='PEN',
            label='QR Bre-B', holder_name='', details={'type': 'BREB_KEY', 'brebKey': '@tienda'},
            provider_data={'method_id': 'co_qr', 'breb_qr': local_money.decode_breb_qr(payload)})

    def funded(self, destination, minimum='1249.00', bridge=None):
        t = bridge or self.bridge()
        return create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                              request_id=uuid.uuid4(), direction='to_bank', bridge=t, destination=destination,
                              minimum_fx_output=minimum)

    def bridge(self):
        # A new request id and transaction each time: a separately funded bridge.
        self.request_id = uuid.uuid4()
        tx = '0x' + uuid.uuid4().hex + uuid.uuid4().hex
        from . import test_bridge_execution as bridge_fixture
        deposit = '0x' + (uuid.uuid4().hex + uuid.uuid4().hex)[:40]   # each bridge its own address
        bound = bridge_fixture.binding
        with mock.patch.object(bridge_fixture, 'DEPOSIT', deposit), \
                mock.patch.object(bridge_fixture, 'binding', lambda q, deposit=deposit: bound(q, deposit)):
            t, _ = self.prepared()
        t.status = 'delivered'; t.destination_tx_hash = tx; t.save()
        self.credit(self.crypto, amount='10.008795', provider_data={'third_party': {
            'type': 'CRYPTO', 'crypto_network': 'POLYGON', 'transaction_hash': tx}})
        reconcile_provider_credit(t)
        return t

    def test_the_snapshot_is_the_qr_amount(self):
        dynamic = self.destination(breb('1249'))
        self.assertEqual(local_money.store_order_snapshot(dynamic)['amount'], '1249.00')
        self.assertTrue(local_money.store_order_snapshot(dynamic)['once'])
        self.assertFalse(local_money.store_order_snapshot(self.destination(breb('1249', dynamic=False)))['once'])
        self.assertIsNone(local_money.store_order_snapshot(self.destination(breb())))
        self.assertTrue(local_money.is_fixed_amount_qr(dynamic))

    def test_pays_exactly_the_qr_and_the_rest_stays_local(self):
        j = self.funded(self.destination(breb('1249')))
        self.fx_quote('crypto', 'local', output='1262.40')
        advance_journey(j.pk, client=self.api)
        self.settle_fx(j, self.local, '1262.40')
        advance_journey(j.pk, client=self.api); j.refresh_from_db(); j.money_flow.refresh_from_db()
        self.assertEqual(j.payout_operation.source_amount, Decimal('1249.00'))
        self.assertEqual(Decimal(j.money_flow.metadata['store_order_remainder']['amount']), Decimal('13.40'))

    def test_an_authorization_below_the_qr_is_refused(self):
        with self.assertRaisesRegex(PaymentAccountError, 'no cubre'):
            self.funded(self.destination(breb('1249')), minimum='1200.00')
        self.assertFalse(InfiniaJourney.objects.exists())

    def test_a_dynamic_qr_is_paid_once_a_static_one_again(self):
        dynamic = self.destination(breb('1249'))
        first = self.funded(dynamic)
        done = lambda j: InfiniaJourney.objects.filter(pk=j.pk).update(stage='completed')   # one at a time
        done(first)
        local_money.require_unpaid_qr(self.destination(breb('1249', dynamic=False)))
        with self.assertRaisesRegex(PaymentAccountError, 'QR ya tiene un pago'):
            local_money.require_unpaid_qr(dynamic)     # the charge view says so before any bridge
        with self.assertRaisesRegex(PaymentAccountError, 'QR ya tiene un pago'):
            self.funded(dynamic)                       # a separately funded second payment
        # A failed first payment does not count: it can be paid then.
        InfiniaJourney.objects.filter(pk=first.pk).update(stage='failed')
        local_money.require_unpaid_qr(dynamic)
        # A static QR with an amount is paid again, each time exactly.
        static = self.destination(breb('1249', dynamic=False))
        one = self.funded(static)
        done(one)
        two = self.funded(static)
        self.assertNotEqual(one.pk, two.pk)
        self.assertEqual({one.destination_snapshot['store_order']['amount'],
                          two.destination_snapshot['store_order']['amount']}, {'1249.00'})

    def test_a_payment_rule_never_pays_a_fixed_amount_qr(self):
        with self.assertRaisesRegex(PaymentAccountError, 'pagos automáticos'):
            create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                           request_id=uuid.uuid4(), direction='to_bank', bridge=self.bridge(),
                           destination=self.destination(breb('1249')), minimum_fx_output='1249.00',
                           funding=mock.Mock())


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class FixedBrebCardTests(PaymentIntentBase):
    def setUp(self):
        super().setUp()
        self.rate = Decimal('4100.00')

        def quote(owner, destination, *, amount=None, **kw):
            expected = (amount * self.rate).quantize(Decimal('0.01'))
            return {'minimum_target': (expected * Decimal('0.99')).quantize(Decimal('0.01')),
                    'expected_target': expected, 'rate': self.rate, 'asset': 'COP', 'expires_at': ''}
        mock.patch.object(local_money, 'payout_quote', side_effect=quote).start()
        mock.patch.object(local_money, 'payout_fee', return_value={'total_usd': '0.30'}).start()
        mock.patch('payment_accounts.breb_location.require_for_country').start()

    def test_route_is_a_dollar_transfer(self):
        self.assertEqual(intent_rails.route({'code': breb('25000')}), ('local_transfer', 'co_qr', 'infinia'))

    def test_the_card_is_the_exact_qr_priced_in_dollars_on_every_entry(self):
        for label, attempt in (
                ('assistant', lambda: self.prepare(breb('25000'))),
                ('pagar', lambda: payment_intents.prepare(self.owner, self.user, created_by='scan', source='form',
                                                          request={'method_id': 'co_qr', 'value': breb('25000'),
                                                                   'amount_usd': '1'}))):
            with self.subTest(entry=label):
                intent = attempt()
                self.assertEqual((intent.family, intent.rail_method_id, intent.amount_exact, intent.currency),
                                 ('local_transfer', 'co_qr', True, 'COP'))
                self.assertEqual((intent.amount_local, intent.minimum_local),
                                 (Decimal('25000.00'), Decimal('25000.00')))
                # The dollars typed (if any) do not matter: the QR's pesos are covered.
                floor = (intent.total_usd * self.rate).quantize(Decimal('0.01')) * Decimal('0.99')
                self.assertGreaterEqual(floor, Decimal('25000.00'))
                self.assertLess(intent.total_usd, Decimal('6.50'))
                self.assertEqual((intent.payee_level, intent.payee_name), ('self_reported', 'TIENDA'))
        self.assertEqual(local_money.saved_destinations(self.owner, 'co_qr'), [])

    def test_an_open_qr_still_needs_dollars(self):
        with self.assertRaises(payment_intents.IntentRefused) as refused:
            self.prepare(breb())
        self.assertEqual(refused.exception.code, 'no_amount')

    def test_requote_keeps_the_exact_amount(self):
        intent = self.prepare(breb('25000'))
        fresh = payment_intents.requote(self.owner, self.user, intent.internal_id)
        self.assertEqual((fresh.destination_id, fresh.amount_local, fresh.amount_exact),
                         (intent.destination_id, Decimal('25000.00'), True))

    def test_the_pagar_screen_gets_the_dollars_and_the_exact_pesos(self):
        row = local_money.resolve_destination(self.owner, 'co_qr', breb('25000'))
        charge = local_money.fixed_qr_charge_quote(self.owner, row)
        card = self.prepare(breb('25000'))
        self.assertEqual((charge['amount'], charge['asset'], charge['merchant_name'], charge['merchant_source']),
                         (Decimal('25000.00'), 'COP', 'TIENDA', 'qr'))
        self.assertEqual(charge['total_usd'], card.total_usd)   # the same dollars as the assistant's card
        self.assertEqual(charge['estimated_return_usd'], Decimal('0.00'))
        # The screen's quote at those dollars: the merchant receives exactly the QR.
        quote = local_money.exact_qr_quote(row, local_money.payout_quote(self.owner, row, amount=charge['total_usd']),
                                           charge['amount'])
        self.assertEqual((quote['minimum_target'], quote['target_amount'], quote['expected_target']),
                         (Decimal('25000.00'),) * 3)
        # Dollars that no longer cover it: priced again, never signed short.
        short = local_money.payout_quote(self.owner, row, amount=Decimal('5.00'))
        with self.assertRaisesRegex(PaymentAccountError, 'cambió'):
            local_money.exact_qr_quote(row, short, '25000')
        # Asked without the QR's own amount (an older build): refused, never a dollar send.
        with self.assertRaisesRegex(PaymentAccountError, 'Actualiza la app'):
            local_money.exact_qr_quote(row, short)
        # Any other recipient: the quote is untouched.
        open_row = local_money.resolve_destination(self.owner, 'co_qr', breb())
        self.assertEqual(local_money.exact_qr_quote(open_row, short), short)

    def test_the_charge_query_answers_for_a_fixed_breb_qr(self):
        from types import SimpleNamespace
        from payment_accounts.local_money_schema import LocalMoneyQuery as Query
        row = local_money.resolve_destination(self.owner, 'co_qr', breb('25000'))
        info = SimpleNamespace(context=SimpleNamespace(user=self.user, META={}))
        with mock.patch('payment_accounts.local_money_schema._owner', return_value=self.owner):
            view = Query().resolve_local_pix_charge(info, row.internal_id)
            self.assertEqual((view.amount, view.asset, view.merchant_source), ('25000.00', 'COP', 'qr'))
            open_row = local_money.resolve_destination(self.owner, 'co_qr', breb())
            self.assertIsNone(Query().resolve_local_pix_charge(info, open_row.internal_id))


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class FixedArgentineQrTests(PaymentIntentBase):
    """Argentina's interoperable QR with a fixed amount: the same exact payout."""

    def setUp(self):
        super().setUp()
        self.rate = Decimal('1150.00')

        def quote(owner, destination, *, amount=None, **kw):
            expected = (amount * self.rate).quantize(Decimal('0.01'))
            return {'minimum_target': (expected * Decimal('0.99')).quantize(Decimal('0.01')),
                    'expected_target': expected, 'rate': self.rate, 'asset': 'ARS', 'expires_at': ''}
        mock.patch.object(local_money, 'payout_quote', side_effect=quote).start()
        mock.patch.object(local_money, 'payout_fee', return_value={'total_usd': '0.30'}).start()

    def test_the_card_and_the_screen_price_the_exact_pesos(self):
        intent = self.prepare(argentina('15000.00'))
        self.assertEqual((intent.family, intent.rail_method_id, intent.amount_exact, intent.currency),
                         ('local_transfer', 'ar_qr', True, 'ARS'))
        self.assertEqual((intent.amount_local, intent.minimum_local), (Decimal('15000.00'),) * 2)
        floor = (intent.total_usd * self.rate).quantize(Decimal('0.01')) * Decimal('0.99')
        self.assertGreaterEqual(floor, Decimal('15000.00'))
        self.assertLess(intent.total_usd, Decimal('14.00'))
        row = intent.destination
        self.assertTrue(local_money.is_fixed_amount_qr(row))
        self.assertEqual(local_money.store_order_snapshot(row)['amount'], '15000.00')
        self.assertTrue(local_money.store_order_snapshot(row)['once'])
        charge = local_money.fixed_qr_charge_quote(self.owner, row)
        self.assertEqual((charge['amount'], charge['asset'], charge['merchant_name'], charge['total_usd']),
                         (Decimal('15000.00'), 'ARS', 'KIOSCO', intent.total_usd))
        self.assertEqual(local_money.saved_destinations(self.owner, 'ar_qr'), [])

    def test_an_open_argentine_qr_still_takes_dollars(self):
        row =local_money.resolve_destination(self.owner, 'ar_qr', argentina())
        self.assertFalse(local_money.is_fixed_amount_qr(row))
        self.assertIsNone(local_money.store_order_snapshot(row))
