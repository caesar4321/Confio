"""A store's SPEI order, read off its own checkout (agent_tasks): exact pesos
with the order's reference, priced in dollars; the payout is the order and
what the conversion lands above it stays in the person's local account."""
from decimal import Decimal
from unittest import mock
import uuid


from payment_accounts import local_money, payment_intents
from payment_accounts.infinia_journeys import advance_journey, create_journey
from payment_accounts.models import InfiniaJourney, PaymentIntent, PayoutDestination
from payment_accounts.payment_intents import IntentRefused
from payment_accounts.services import PaymentAccountError
from django.test import TestCase, override_settings

from payment_accounts.bridge_execution import reconcile_provider_credit
from . import test_infinia_journeys as journey_tests
from .test_bridge_execution import DEST_HASH
from .test_payment_intents import PaymentIntentBase

CLABE = '646180157000000004'   # a valid check digit (STP)
ORDER = {'amount': '1249.00', 'reference': 'MLM 4021 77'}


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=payment_intents.DEFAULT_LEVELS)
class StoreOrderCardTests(PaymentIntentBase):
    def setUp(self):
        super().setUp()
        self.rate = Decimal('18.20')

        def quote(owner, destination, *, amount=None, bridge=None, **kw):
            amount = Decimal('70.00') if amount is None else amount   # what the prepared bridge lands
            expected = (amount * self.rate).quantize(Decimal('0.01'))
            return {'minimum_target': (expected * Decimal('0.99')).quantize(Decimal('0.01')),
                    'expected_target': expected, 'rate': self.rate, 'asset': 'MXN', 'expires_at': ''}
        self.payout = mock.patch.object(local_money, 'payout_quote', side_effect=quote).start()
        mock.patch.object(local_money, 'payout_fee', return_value={'total_usd': '0.30'}).start()

    def order(self, source='agent_checkout', **over):
        request = {'method_id': 'mx_clabe', 'value': CLABE, 'amount_local': ORDER['amount'],
                   'reference': ORDER['reference'], **over}
        return payment_intents.prepare(self.owner, self.user, created_by='assistant', source=source,
                                       request=request)

    def test_the_card_is_the_exact_order_priced_in_dollars(self):
        intent = self.order()
        self.assertEqual((intent.family, intent.rail_method_id, intent.amount_exact, intent.currency),
                         ('local_transfer', 'mx_clabe', True, 'MXN'))
        self.assertEqual((intent.amount_local, intent.minimum_local), (Decimal('1249.00'), Decimal('1249.00')))
        # The conversion's guaranteed minimum covers the order at the dollars shown.
        minimum = (intent.total_usd * self.rate).quantize(Decimal('0.01')) * Decimal('0.99')
        self.assertGreaterEqual(minimum, Decimal('1249.00'))
        self.assertLess(intent.total_usd, Decimal('70.00'))
        self.assertEqual((intent.payee_level, intent.payee_name, intent.institution, intent.payee_account),
                         ('store_checkout', 'Cuenta de la tienda', 'STP', CLABE))
        self.assertEqual(intent.params, {'store_order': ORDER})
        details = intent.destination.details
        self.assertEqual((details['clabe'], details['reference']), (CLABE, 'MLM 4021 77'))
        # Never a saved recipient, never "Confio" as the order's reference.
        self.assertEqual(local_money.saved_destinations(self.owner, 'mx_clabe'), [])

    def test_only_the_checkout_screen_makes_one(self):
        for source in ('pasted_code', 'form', 'owner_words'):
            with self.subTest(source=source), self.assertRaises(IntentRefused) as refused:
                self.order(source=source)
            self.assertEqual(refused.exception.code, 'no_amount')   # a dollar send, and no dollars given
        with self.assertRaises(IntentRefused):
            self.order(_source='agent_checkout', source='form')
        self.assertFalse(PaymentIntent.objects.exists())

    def test_refusals(self):
        for over, code in (({'reference': 'ref<script>'}, 'no_code'), ({'reference': 'x' * 41}, 'no_code'),
                           ({'reference': 'Pedido ñ'}, 'no_code'), ({'amount_local': '0'}, 'no_amount'),
                           ({'amount_local': '12.345'}, 'no_amount'), ({'amount_local': 'abc'}, 'no_amount'),
                           ({'value': '646180157000000005'}, 'no_code')):
            with self.subTest(over=over), self.assertRaises(IntentRefused) as refused:
                self.order(**over)
            self.assertEqual(refused.exception.code, code)

    def test_two_orders_never_share_a_row(self):
        first = self.order()
        second = self.order(reference='MLM 4021 78')
        other_amount = self.order(amount_local='1250.00')
        self.assertEqual(len({first.destination_id, second.destination_id, other_amount.destination_id}), 3)
        self.assertEqual(self.order().destination_id, first.destination_id)

    def test_confirm_takes_the_order_as_the_journeys_minimum(self):
        intent = self.order()
        (confirmed, transfer, *_), *_ = self.confirm(intent)
        self.assertEqual(payment_intents.journey_minimum(confirmed), Decimal('1249.00'))
        args = dict(direction='to_bank', bridge=transfer, destination=confirmed.destination)
        self.assertEqual(payment_intents.journey_guard(self.owner, intent.request_id, minimum_fx_output='1249.00',
                                                       **args).pk, intent.pk)
        changed = confirmed.destination
        changed.provider_data = dict(changed.provider_data, store_order={**ORDER, 'amount': '1.00'})
        changed.save()
        with self.assertRaises(IntentRefused) as refused:
            payment_intents.journey_guard(self.owner, intent.request_id, minimum_fx_output='1249.00', **args)
        self.assertEqual(refused.exception.code, 'charge_changed')

    def test_a_worse_rate_is_never_signed(self):
        intent = self.order()
        self.rate = Decimal('17.00')
        with self.assertRaises(IntentRefused) as refused:
            self.confirm(intent)
        self.assertEqual(refused.exception.code, 'quote_changed')

    def test_requote_reads_the_same_order(self):
        intent = self.order()
        fresh = payment_intents.requote(self.owner, self.user, intent.internal_id)
        self.assertEqual((fresh.destination_id, fresh.amount_local, fresh.params, fresh.payee_level),
                         (intent.destination_id, intent.amount_local, intent.params, 'store_checkout'))


@override_settings(INFINIA_JOURNEYS_ENABLED=True, INFINIA_PAYMENT_ACCOUNTS_ENABLED=True,
                   PAYMENT_BRIDGE_QUOTES_ENABLED=True, PAYMENT_BRIDGE_BSC_ENABLED=True,
                   PAYMENT_BRIDGE_POLYGON_ENABLED=True, CUSD_PLUS_7702_ENABLED=True)
class StoreOrderJourneyTests(TestCase):
    quote = journey_tests.JourneyTests.quote
    prepared = journey_tests.JourneyTests.prepared
    credit = journey_tests.JourneyTests.credit
    settle_fx = journey_tests.JourneyTests.settle_fx
    fx_quote = journey_tests.JourneyTests.fx_quote

    def setUp(self):
        journey_tests.JourneyTests.setUp(self)

    def tearDown(self):
        mock.patch.stopall()

    def order_destination(self, order=ORDER):
        return PayoutDestination.objects.create(
            confio_account=self.owner, provider='infinia', kind='bank_account', country='PER', asset='PEN',
            label='CLABE', holder_name='', details={'type': 'CLABE', 'clabe': CLABE, 'reference': order['reference']},
            provider_data={'method_id': 'mx_clabe', 'fixed_charge': True, 'store_order': order})

    def funded(self, destination, minimum='1249.00'):
        if not hasattr(self, 'bridge'):   # one prepared transfer per test
            t, _ = self.prepared(); t.status = 'delivered'; t.destination_tx_hash = DEST_HASH; t.save()
            self.credit(self.crypto, amount='10.008795', provider_data={'third_party': {
                'type': 'CRYPTO', 'crypto_network': 'POLYGON', 'transaction_hash': DEST_HASH}})
            reconcile_provider_credit(t)
            self.bridge = t
        t = self.bridge
        return create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                              request_id=uuid.uuid4(), direction='to_bank', bridge=t, destination=destination,
                              minimum_fx_output=minimum)

    def test_pays_exactly_the_order_and_the_rest_stays_local(self):
        j = self.funded(self.order_destination())
        self.assertEqual(j.destination_snapshot['store_order']['amount'], '1249.00')
        self.fx_quote('crypto', 'local', output='1262.40')
        advance_journey(j.pk, client=self.api)
        self.settle_fx(j, self.local, '1262.40')
        advance_journey(j.pk, client=self.api); j.refresh_from_db(); j.money_flow.refresh_from_db()
        self.assertEqual(j.payout_operation.source_amount, Decimal('1249.00'))
        self.assertEqual(j.payout_operation.external_destination['destination_account']['reference'], 'MLM 4021 77')
        self.assertEqual(j.money_flow.metadata['store_order_remainder']['amount'], '13.40')

    def test_an_authorization_below_the_order_is_refused(self):
        with self.assertRaisesRegex(PaymentAccountError, 'no cubre'):
            self.funded(self.order_destination(), minimum='1200.00')
        self.assertFalse(InfiniaJourney.objects.exists())

    def test_an_order_is_paid_once_from_any_account(self):
        destination = self.order_destination()
        j = self.funded(destination)
        with self.assertRaisesRegex(PaymentAccountError, 'no se puede pagar otra vez'):
            self.funded(destination)
        # Refunded: the order may be paid again (the check passes; the spent bridge is what stops it here).
        InfiniaJourney.objects.filter(pk=j.pk).update(stage='failed')
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.funded(destination)

    def test_a_conversion_below_the_order_is_never_paid_out(self):
        j = self.funded(self.order_destination())
        InfiniaJourney.objects.filter(pk=j.pk).update(minimum_fx_output=Decimal('1000'))
        self.fx_quote('crypto', 'local', output='1200.00')
        advance_journey(j.pk, client=self.api)
        self.settle_fx(j, self.local, '1200.00')
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code, j.payout_operation_id), ('needs_review', 'store_order_short', None))
