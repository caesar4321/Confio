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
from payment_accounts.models import InfiniaJourney, PayoutDestination
from payment_accounts.payment_intents import IntentRefused
from payment_accounts.services import PaymentAccountError
from .test_breb_fixed_qr import breb
from .test_local_money import qr

REAL_BUILD_SUPPORTED = local_money.fixed_qr_build_supported   # before any test patches it
# Fixture classes by module, so the loader does not run their tests here again.
from . import test_infinia_journeys as journey_fixture, test_payment_intents as intent_fixture
from .test_infinia_journeys import reconcile_provider_credit
from .test_payment_intent_rails import EVERY_LEVEL


# Tests run with real AWS credentials (the prod alert secret): nothing here may
# ever reach the team's Telegram. Every send stops at its lowest layer.
_telegram = mock.patch('config.ops_alerts._send', return_value=True)


def setUpModule():
    _telegram.start()


def tearDownModule():
    _telegram.stop()



@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class ExactLocalCardTests(intent_fixture.PaymentIntentBase):
    def setUp(self):
        super().setUp()
        mock.patch.object(local_money, 'fixed_qr_build_supported', return_value=True).start()   # a 5.4.1 build
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
        # Dollars and a local amount together: refused, never one silently dropped.
        with self.assertRaises(IntentRefused) as both:
            self.send(amount_usd='1')
        self.assertEqual(both.exception.code, 'no_amount')
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


class ExactLocalJourneyTests(journey_fixture.JourneyTests):
    def destination(self):
        return PayoutDestination.objects.create(
            confio_account=self.owner, provider='infinia', kind='bank_account', country='PER', asset='PEN',
            label='Cuenta', holder_name='', details={'type': 'CCI', 'cci': '00219300123456789012'},
            provider_data={'method_id': 'br_pix'})

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
        destination = self.destination()
        done = lambda j: InfiniaJourney.objects.filter(pk=j.pk).update(stage='completed')   # one at a time
        one = self.journey(destination, Decimal('1249.00'))
        done(one)
        two = self.journey(destination, Decimal('1249.00'))   # separately funded
        done(two)
        self.assertNotEqual(one.pk, two.pk)
        self.assertNotEqual(one.destination_snapshot['store_order']['key'],
                            two.destination_snapshot['store_order']['key'])
        # A typed "500" is stored as the card shows it.
        self.assertEqual(self.journey(destination, Decimal('1249'))
                         .destination_snapshot['store_order']['amount'], '1249.00')

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
class PagoMovilExactCardTests(intent_fixture.PaymentIntentBase):
    """Pago Móvil in exact bolívares, on the provider that can price them."""

    def setUp(self):
        super().setUp()
        mock.patch.object(local_money, 'fixed_qr_build_supported', return_value=True).start()   # a 5.4.1 build
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

    def test_the_order_is_made_with_the_cards_bolivares(self):
        from payment_accounts.intent_rails import PagoMovilRail
        intent = self.send()
        with mock.patch('ramps.ve_pagomovil_schema.CreateVePagoMovilSend.mutate') as mutate:
            PagoMovilRail().create(self.info if hasattr(self, 'info') else mock.Mock(), intent)
        self.assertEqual(mutate.call_args.kwargs['ves_amount'], '15000.00')
        self.assertEqual(mutate.call_args.kwargs['usd_amount'], '16.40')

    def test_confirmation_binds_the_total_not_the_moving_fee_line(self):
        from payment_accounts import intent_rails
        intent = self.send()
        base = self.adapter.quote_exact.side_effect
        self.adapter.quote_exact.side_effect = lambda ves: {**base(ves), 'processor_fee_usd': '0.45'}
        intent_rails.reread_order(self.owner, self.user, intent)          # same total: still the card
        self.adapter.quote_exact.side_effect = lambda ves: {**base(ves), 'usd_amount': '16.41'}
        with self.assertRaises(IntentRefused) as refused:
            intent_rails.reread_order(self.owner, self.user, intent)
        self.assertEqual(refused.exception.code, 'quote_changed')

    def test_a_provider_that_cannot_price_bolivares_refuses(self):
        self.adapter = mock.Mock(spec=['quote'])
        mock.patch('ramps.ve_pagomovil.send_adapter', return_value=self.adapter).start()
        with self.assertRaises(IntentRefused) as refused:
            self.send()
        self.assertEqual(refused.exception.code, 'rail')


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class ExactLocalApiTests(intent_fixture.PaymentIntentBase):
    """The GraphQL edges: the card's amount wins, and older builds never pay a
    fixed-amount QR without being told it is one."""

    def setUp(self):
        super().setUp()
        mock.patch.object(local_money, 'fixed_qr_build_supported', return_value=True).start()   # a 5.4.1 build
        self.rate = Decimal('5.40')

        def quote(owner, destination, *, amount=None, **kw):
            expected = (Decimal(str(amount)) * self.rate).quantize(Decimal('0.01'))
            return {'minimum_target': (expected * Decimal('0.99')).quantize(Decimal('0.01')),
                    'expected_target': expected, 'target_amount': expected, 'rate': self.rate, 'asset': 'BRL',
                    'expires_at': '', 'source_amount': amount, 'expected_source_amount': amount,
                    'total_cost_percent': Decimal('1')}
        mock.patch.object(local_money, 'payout_quote', side_effect=quote).start()
        mock.patch.object(local_money, 'payout_fee', return_value={'total_usd': '0.30'}).start()
        mock.patch('payment_accounts.breb_location.require_for_country').start()
        self.info = mock.Mock(context=mock.Mock(user=self.user, META={}))
        mock.patch('payment_accounts.local_money_schema._owner', return_value=self.owner).start()

    def journey(self, destination, intent=None, **kwargs):
        from payment_accounts.journey_schema import CreateInfiniaJourney
        with mock.patch('payment_accounts.schema._active_account', return_value=self.owner), \
                mock.patch('payment_accounts.schema._require_adult'), \
                mock.patch('payment_accounts.breb_location.require_for_country'), \
                mock.patch.object(payment_intents, 'journey_guard', return_value=intent), \
                mock.patch.object(payment_intents, 'journey_created'), \
                mock.patch('payment_accounts.local_money.require_current_destination'), \
                mock.patch('payment_accounts.journey_schema.create_journey') as create:
            result = CreateInfiniaJourney.mutate(
                None, self.info, local_account_id=self.local.internal_id, crypto_account_id=self.crypto.internal_id,
                destination_id=destination.internal_id, direction='to_bank', request_id=uuid.uuid4(),
                minimum_fx_output=Decimal('500.00'), **kwargs)
        return result, create

    def test_a_cards_exact_amount_wins_over_the_client(self):
        row = local_money.resolve_destination(self.owner, 'br_pix', 'ana@example.com')
        card = mock.Mock(params={'exact_local': '500.00'})
        result, create = self.journey(row, intent=card)
        self.assertTrue(result.success, result.errors)
        self.assertEqual(create.call_args.kwargs['exact_payout'], '500.00')
        result, create = self.journey(row, intent=card, exact_local_amount=Decimal('400'))
        self.assertFalse(result.success)
        create.assert_not_called()
        # Without a card the typed amount is the client's own choice, passed on as given.
        result, create = self.journey(row, exact_local_amount=Decimal('500'))
        self.assertEqual(create.call_args.kwargs['exact_payout'], Decimal('500'))

    def test_an_older_build_never_pays_a_fixed_amount_qr(self):
        fixed = local_money.resolve_destination(self.owner, 'co_qr', breb('25000'))
        result, create = self.journey(fixed)
        self.assertFalse(result.success)
        self.assertIn('Actualiza la app', result.errors[0])
        create.assert_not_called()
        from payment_accounts.local_money_schema import LocalMoneyQuery
        with self.assertRaisesRegex(Exception, 'Actualiza la app'):
            LocalMoneyQuery().resolve_local_payout_quote(self.info, fixed.internal_id, amount=Decimal('50'))
        with self.assertRaisesRegex(Exception, 'no coincide'):
            LocalMoneyQuery().resolve_local_payout_quote(self.info, fixed.internal_id, amount=Decimal('50'),
                                                         exact_local=Decimal('1000'))

    def test_the_exact_send_query_and_its_held_quote(self):
        from payment_accounts.local_money_schema import LocalMoneyQuery
        row = local_money.resolve_destination(self.owner, 'br_pix', 'ana@example.com')
        view = LocalMoneyQuery().resolve_local_exact_send(self.info, row.internal_id, Decimal('500'))
        self.assertEqual((view.amount, view.asset, view.merchant_source), ('500.00', 'BRL', 'typed'))
        held = LocalMoneyQuery().resolve_local_payout_quote(self.info, row.internal_id, amount=view.total_usd,
                                                            exact_local=Decimal('500'))
        self.assertEqual((held.minimum_target, held.target_amount), ('500.00', '500.00'))
        for bad in (Decimal('0'), Decimal('-1'), Decimal('1.001')):
            with self.subTest(exact=bad), self.assertRaises(Exception):
                LocalMoneyQuery().resolve_local_payout_quote(self.info, row.internal_id, amount=view.total_usd,
                                                             exact_local=bad)

    def test_argentine_amounts_must_be_in_pesos(self):
        from .test_breb_fixed_qr import argentina
        from .test_local_money import qr
        dollars = qr(('01', '12'), ('43', 'com.mercadolibre'), ('53', '840'), ('54', '15.00'), ('58', 'AR'))
        with self.assertRaisesRegex(PaymentAccountError, 'moneda'):
            local_money.normalize_value(local_money.METHODS['ar_qr'], dollars)
        row = local_money.resolve_destination(self.owner, 'ar_qr', argentina('15000.00'))
        self.assertEqual(local_money.destination_view(row)['qr_amount'], '15000.00')


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class ExactLocalApiEdgeTests(ExactLocalApiTests):
    """Cards and retries through the journey mutation."""

    def test_a_qr_card_pays_the_qrs_own_amount(self):
        fixed = local_money.resolve_destination(self.owner, 'co_qr', breb('25000'))
        card = mock.Mock(params={}, amount_exact=True)
        result, create = self.journey(fixed, intent=card)
        self.assertTrue(result.success, result.errors)
        self.assertIsNone(create.call_args.kwargs['exact_payout'])   # the QR's own order is used
        # A dollar card shown before fixed-amount QRs were paid exactly is over.
        result, create = self.journey(fixed, intent=mock.Mock(params={}, amount_exact=False))
        self.assertFalse(result.success)
        create.assert_not_called()

    def test_an_older_builds_retry_returns_its_journey(self):
        fixed = local_money.resolve_destination(self.owner, 'co_qr', breb('25000'))
        with mock.patch('payment_accounts.journey_schema.InfiniaJourney') as journeys:
            journeys.objects.filter.return_value.exists.return_value = True   # the same request was made before
            result, create = self.journey(fixed)
        self.assertTrue(result.success, result.errors)
        create.assert_called_once()

    def test_a_clients_exact_amount_is_checked(self):
        row = local_money.resolve_destination(self.owner, 'br_pix', 'ana@example.com')
        for bad in (Decimal('12.345'), Decimal('0'), Decimal('-1')):
            with self.subTest(exact=bad):
                result, create = self.journey(row, exact_local_amount=bad)
                self.assertFalse(result.success)
                create.assert_not_called()

    def test_an_unreadable_stored_qr_is_never_an_open_one(self):
        fixed = local_money.resolve_destination(self.owner, 'co_qr', breb('25000'))
        fixed.provider_data = dict(fixed.provider_data, breb_qr=dict(fixed.provider_data['breb_qr'], payload='garbage'))
        fixed.save()
        self.assertTrue(local_money.is_fixed_amount_qr(fixed))
        with self.assertRaises(PaymentAccountError):
            local_money.store_order_snapshot(fixed)
        self.assertNotIn(fixed.pk, [r.pk for r in local_money.saved_destinations(self.owner, 'co_qr')])

    def test_a_reference_outside_a_checkout_is_refused_not_ignored(self):
        with self.assertRaises(IntentRefused) as refused:
            payment_intents.prepare(self.owner, self.user, created_by='scan', source='form', request={
                'method_id': 'br_pix', 'value': 'ana@example.com', 'amount_local': '500', 'reference': 'X',
                'amount_usd': '100'})
        self.assertEqual(refused.exception.code, 'no_amount')


class HoldingPaymentsTests(ExactLocalJourneyTests):
    """Who holds a paid-once QR: never someone who only opened a payment."""

    def test_an_unsigned_expired_payment_does_not_hold_a_qr(self):
        fixed = self.destination()
        fixed.provider_data = {'method_id': 'co_qr', 'breb_qr': local_money.decode_breb_qr(breb('1249'))}
        fixed.save()
        first = create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                               request_id=uuid.uuid4(), direction='to_bank', bridge=self.bridge(),
                               destination=fixed, minimum_fx_output='1249.00')
        key = first.destination_snapshot['store_order']['key']
        first.bridge.status = 'prepared'; first.bridge.save(update_fields=['status'])
        self.assertTrue(local_money.holding_payments(key).exists())          # can still be signed
        first.bridge.deadline = 1; first.bridge.save(update_fields=['deadline'])
        self.assertFalse(local_money.holding_payments(key).exists())         # never signed, now cannot be
        first.bridge.status = 'submitted'; first.bridge.save(update_fields=['status'])
        self.assertTrue(local_money.holding_payments(key).exists())          # signed: it holds


class ExactLocalRound3Tests(ExactLocalJourneyTests):
    """Retries, paid QRs and the real journey mutation."""

    def fixed(self, payload):
        row = self.destination()
        row.provider_data = {'method_id': 'co_qr', 'breb_qr': local_money.decode_breb_qr(payload)}
        row.save()
        return row

    def test_a_retry_of_a_journey_made_before_returns_it(self):
        row, t, request = self.fixed(breb('1249')), self.bridge(), uuid.uuid4()
        args = dict(owner=self.owner, local_account=self.local, crypto_account=self.crypto, request_id=request,
                    direction='to_bank', bridge=t, destination=row, minimum_fx_output='1249.00')
        first = create_journey(**args)
        snapshot = dict(first.destination_snapshot); snapshot.pop('store_order')   # as made before this change
        InfiniaJourney.objects.filter(pk=first.pk).update(destination_snapshot=snapshot)
        self.assertEqual(create_journey(**args).pk, first.pk)

    def test_an_exact_amount_is_only_for_a_send_to_an_account(self):
        with self.assertRaisesRegex(PaymentAccountError, 'monto exacto'):
            create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                           request_id=uuid.uuid4(), direction='to_wallet', credit=mock.Mock(),
                           minimum_fx_output='10', exact_payout=Decimal('10'))

    def test_a_qr_without_its_kind_is_paid_once(self):
        argentine = qr(('53', '032'), ('54', '1500.00'), ('58', 'AR'))
        row = self.destination()
        row.provider_data = {'method_id': 'ar_qr'}
        row.details = {'type': 'QR_CODE', 'qrCode': argentine}
        row.save()
        self.assertTrue(local_money.store_order_snapshot(row)['once'])

    def test_the_real_mutation_pays_a_typed_amount_and_ends_a_paid_qrs_card(self):
        from payment_accounts.journey_schema import CreateInfiniaJourney
        info = mock.Mock(context=mock.Mock(user=self.owner.user, META={}))
        def mutate(destination, **kwargs):
            with mock.patch('payment_accounts.schema._active_account', return_value=self.owner), \
                    mock.patch('payment_accounts.schema._require_adult'), \
                    mock.patch('payment_accounts.breb_location.require_for_country'):
                return CreateInfiniaJourney.mutate(
                    None, info, local_account_id=self.local.internal_id, crypto_account_id=self.crypto.internal_id,
                    destination_id=destination.internal_id, direction='to_bank', request_id=uuid.uuid4(),
                    minimum_fx_output=Decimal('1249.00'), bridge_id=self.bridge().internal_id, **kwargs)
        result = mutate(self.destination(), exact_local_amount=Decimal('1249'))
        self.assertTrue(result.success, result.errors)
        self.assertEqual(result.journey.destination_snapshot['store_order']['amount'], '1249.00')
        InfiniaJourney.objects.update(stage='completed')
        dynamic = self.fixed(breb('1249'))
        self.assertTrue(mutate(dynamic, exact_local_amount=Decimal('1249')).success)
        InfiniaJourney.objects.update(stage='completed')
        with mock.patch.object(payment_intents, 'journey_refused') as refused:
            again = mutate(dynamic, exact_local_amount=Decimal('1249'))
        self.assertEqual((again.success, again.error_code), (False, 'charge_changed'))
        refused.assert_called_once()

    def test_a_spei_order_is_held_only_while_it_can_be_paid(self):
        order = {'amount': '1249.00', 'reference': 'MLM 1'}
        row = self.destination()
        row.provider_data = {'method_id': 'mx_clabe', 'fixed_charge': True, 'store_order': order}
        row.details = {'type': 'CLABE', 'clabe': '646180157000000004', 'reference': 'MLM 1'}
        row.save()
        first = create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                               request_id=uuid.uuid4(), direction='to_bank', bridge=self.bridge(),
                               destination=row, minimum_fx_output='1249.00')
        key = first.destination_snapshot['store_order']['key']
        self.assertTrue(local_money.holding_payments(key).exists())
        first.bridge.status = 'prepared'; first.bridge.deadline = 1
        first.bridge.save(update_fields=['status', 'deadline'])
        self.assertFalse(local_money.holding_payments(key).exists())


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class ExactLocalApiRound3Tests(ExactLocalApiTests):
    def test_an_older_build_is_told_before_any_recipient_or_quote(self):
        from payment_accounts.local_money_schema import ResolveLocalDestination, LocalMoneyQuery
        local_money.fixed_qr_build_supported.side_effect = REAL_BUILD_SUPPORTED   # the real version check
        def resolve(version):
            info = mock.Mock(context=mock.Mock(user=self.user, META={'HTTP_X_CONFIO_VERSION': version}))
            with mock.patch('payment_accounts.local_money_schema._identity'), \
                    mock.patch.object(local_money, 'require_rail'):
                return ResolveLocalDestination.mutate(None, info, method_id='co_qr', value=breb('25000'))
        old = resolve('5.3.7')
        self.assertFalse(old.success)
        self.assertIn('Actualiza la app', old.errors[0])
        self.assertTrue(resolve('5.4.1').success)
        # 5.4.0 builds were made before this change; no version at all is no build we know.
        self.assertTrue(resolve('5.4.0').success is False and resolve('').success is False)
        fixed = local_money.resolve_destination(self.owner, 'co_qr', breb('25000'))
        with mock.patch.object(local_money, 'payout_quote') as quote, self.assertRaisesRegex(Exception, 'Actualiza'):
            LocalMoneyQuery().resolve_local_payout_quote(self.info, fixed.internal_id, amount=Decimal('50'))
        quote.assert_not_called()

    def test_a_paid_dynamic_qr_ends_its_card(self):
        from payment_accounts import intent_rails
        fixed = local_money.resolve_destination(self.owner, 'co_qr', breb('25000'))
        with mock.patch.object(local_money, 'qr_hold', return_value=local_money.PAID), \
                self.assertRaises(IntentRefused) as refused:
            self.prepare(breb('25000'))
        self.assertEqual(refused.exception.code, 'charge_changed')

    def test_the_price_search_is_kept_a_few_seconds(self):
        from django.core.cache import cache
        cache.clear()
        row = local_money.resolve_destination(self.owner, 'br_pix', 'ana@example.com')
        first = local_money.exact_send_quote(self.owner, row, '500')
        calls = local_money.payout_quote.call_count
        self.assertEqual(local_money.exact_send_quote(self.owner, row, '500.00')['total_usd'], first['total_usd'])
        self.assertEqual(local_money.payout_quote.call_count, calls)   # no provider asked again

    def test_amount_messages(self):
        row = local_money.resolve_destination(self.owner, 'br_pix', 'ana@example.com')
        with self.assertRaisesRegex(PaymentAccountError, 'demasiado alto'):
            local_money.exact_send_quote(self.owner, row, '1000000000')
        order_row = local_money.resolve_destination(self.owner, 'br_pix', 'ana@example.com')
        order_row.provider_data = dict(order_row.provider_data, store_order={'amount': '10.00', 'reference': 'X'})
        order_row.save()
        with self.assertRaisesRegex(PaymentAccountError, 'pedido ya trae'):
            local_money.exact_send_quote(self.owner, order_row, '10')


class ExactLocalRound4JourneyTests(ExactLocalRound3Tests):
    def mutate(self, destination, bridge=None, **kwargs):
        from payment_accounts.journey_schema import CreateInfiniaJourney
        info = mock.Mock(context=mock.Mock(user=self.owner.user, META={}))
        with mock.patch('payment_accounts.schema._active_account', return_value=self.owner), \
                mock.patch('payment_accounts.schema._require_adult'), \
                mock.patch('payment_accounts.breb_location.require_for_country'):
            return CreateInfiniaJourney.mutate(
                None, info, local_account_id=self.local.internal_id, crypto_account_id=self.crypto.internal_id,
                destination_id=destination.internal_id, direction='to_bank', request_id=uuid.uuid4(),
                minimum_fx_output=Decimal('1249.00'), bridge_id=(bridge or self.bridge()).internal_id, **kwargs)

    def test_a_current_build_pays_a_fixed_qr_with_its_own_amount_only(self):
        fixed = self.fixed(breb('1249', dynamic=False))
        wrong = self.mutate(fixed, exact_local_amount=Decimal('1000'))
        self.assertFalse(wrong.success)
        self.assertIn('no coincide', wrong.errors[0])
        right = self.mutate(fixed, exact_local_amount=Decimal('1249'))
        self.assertTrue(right.success, right.errors)
        self.assertEqual(right.journey.destination_snapshot['store_order']['amount'], '1249.00')

    def test_a_dynamic_qr_paid_in_dollars_before_still_holds_it(self):
        fixed = self.fixed(breb('1249'))
        old = create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                             request_id=uuid.uuid4(), direction='to_bank', bridge=self.bridge(),
                             destination=fixed, minimum_fx_output='1249.00')
        snapshot = dict(old.destination_snapshot); snapshot.pop('store_order')   # as paid before this change
        InfiniaJourney.objects.filter(pk=old.pk).update(destination_snapshot=snapshot, stage='completed')
        other = self.fixed(breb('1249'))   # the same QR, scanned again (any account)
        # Real Bre-B recipients are Colombian (the fixture's journeys need PER to run).
        PayoutDestination.objects.filter(pk__in=[fixed.pk, other.pk]).update(country='COL')
        other.refresh_from_db()
        with self.assertRaisesRegex(PaymentAccountError, 'QR ya tiene un pago'):
            local_money.require_unpaid_qr(other)

    def test_the_retry_exception_is_only_for_qrs(self):
        row, t, request = self.destination(), self.bridge(), uuid.uuid4()
        args = dict(owner=self.owner, local_account=self.local, crypto_account=self.crypto, request_id=request,
                    direction='to_bank', bridge=t, destination=row, minimum_fx_output='1249.00')
        create_journey(**args)   # a dollar journey
        with self.assertRaisesRegex(PaymentAccountError, 'Request id already used'):
            create_journey(**args, exact_payout=Decimal('1249.00'))   # never silently returned as exact

    def test_a_row_without_its_rail_yet_is_still_its_qr(self):
        row = self.fixed(breb('1249'))
        row.provider_data = {'breb_qr': row.provider_data['breb_qr']}   # no method_id written yet
        row.save()
        self.assertTrue(local_money.is_fixed_amount_qr(row))
        argentine = self.destination()
        argentine.provider_data = {}
        argentine.country = 'ARG'
        argentine.details = {'type': 'QR_CODE', 'qrCode': qr(('01', '12'), ('53', '032'), ('54', '1500.00'), ('58', 'AR'))}
        argentine.save()
        self.assertEqual(local_money.fixed_qr_amount(argentine), '1500.00')

    def test_an_unreadable_qr_says_so_not_update_the_app(self):
        row = self.fixed(breb('1249'))
        row.provider_data = dict(row.provider_data, breb_qr=dict(row.provider_data['breb_qr'], payload='garbage'))
        row.save()
        with self.assertRaisesRegex(PaymentAccountError, 'No pudimos leer'):
            local_money.require_exact_for_fixed(row, None)


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class ExactLocalApiRound4Tests(ExactLocalApiTests):
    def test_an_old_dollar_card_for_a_now_fixed_qr_ends(self):
        from payment_accounts import intent_rails
        fixed = local_money.resolve_destination(self.owner, 'co_qr', breb('25000'))
        card = mock.Mock(rail_method_id='co_qr', destination=fixed, amount_exact=False, params={})
        with mock.patch.object(intent_rails, 'transfer_payee', return_value={}), \
                self.assertRaises(IntentRefused) as refused:
            intent_rails.reread_transfer(self.owner, card)
        self.assertEqual(refused.exception.code, 'charge_changed')

    def test_hostile_amounts_get_words_not_a_crash(self):
        from payment_accounts import intent_rails
        with self.assertRaises(IntentRefused) as refused:
            intent_rails.exact_local({'amount_local': '1e30'})
        self.assertEqual(refused.exception.code, 'no_amount')
        with self.assertRaisesRegex(PaymentAccountError, 'demasiado alto'):
            local_money._exact_amount('1e30')

    def test_a_moved_price_is_priced_again_not_remembered(self):
        from django.core.cache import cache
        from payment_accounts import intent_rails
        cache.clear()
        row = local_money.resolve_destination(self.owner, 'br_pix', 'ana@example.com')
        local_money.exact_send_quote(self.owner, row, '500')
        key = intent_rails._order_price_key(self.owner.pk, row.pk, '500')
        self.assertIsNotNone(cache.get(key))
        short = local_money.payout_quote(self.owner, row, amount=Decimal('5'))
        with self.assertRaisesRegex(PaymentAccountError, 'cambió'):
            local_money.exact_qr_quote(row, short, '500')
        self.assertIsNone(cache.get(key))


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class ExactLocalApiRound5Tests(ExactLocalApiTests):
    def test_an_older_build_gets_no_card_for_a_fixed_qr(self):
        local_money.fixed_qr_build_supported.return_value = False
        with self.assertRaises(IntentRefused) as refused:
            self.prepare(breb('25000'))
        self.assertIn('Actualiza la app', str(refused.exception))
        fixed = local_money.resolve_destination(self.owner, 'co_qr', breb('25000'))
        result, create = self.journey(fixed, intent=mock.Mock(params={}, amount_exact=True))
        self.assertFalse(result.success)
        self.assertIn('Actualiza la app', result.errors[0])
        create.assert_not_called()

    def test_a_charge_never_takes_a_typed_amount(self):
        row = local_money.resolve_destination(self.owner, 'br_pix', 'ana@example.com')
        with mock.patch.object(local_money, 'charge_snapshot', return_value={'amount': '10'}), \
                self.assertRaisesRegex(PaymentAccountError, 'cobro ya trae'):
            local_money.exact_qr_quote(row, {'minimum_target': '1000'}, '500')

    def test_a_refused_exact_card_is_priced_fresh_next_time(self):
        from django.core.cache import cache
        from payment_accounts import intent_rails
        cache.clear()
        intent = ExactLocalCardTests.send(self)
        key = intent_rails._order_price_key(self.owner.pk, intent.destination.pk, intent.minimum_local)
        self.assertIsNotNone(cache.get(key))
        with mock.patch.object(intent_rails, '_transfer_price',
                               return_value={'minimum_local': Decimal('1'), 'fee_usd': intent.fee_usd,
                                             'currency': intent.currency}), \
                self.assertRaises(IntentRefused):
            intent_rails.reread_transfer(self.owner, intent)
        self.assertIsNone(cache.get(key))

    def test_more_copies_of_a_qr_than_can_be_checked_count_as_held(self):
        fixed = local_money.resolve_destination(self.owner, 'co_qr', breb('25000'))
        key = local_money.store_order_snapshot(fixed)['key']
        self.assertFalse(bool(local_money.held(key, destination=fixed)))
        with mock.patch.object(local_money, 'SAME_QR_LIMIT', 0):
            self.assertTrue(bool(local_money.held(key, destination=fixed)))

    def test_a_rail_less_argentine_row_gets_its_rail(self):
        from .test_breb_fixed_qr import argentina
        row = local_money.resolve_destination(self.owner, 'ar_qr', argentina('15000.00'))
        row.provider_data = {}
        row.save()
        self.assertEqual(local_money.method_of(row).id, 'ar_qr')


class ExactLocalRound6JourneyTests(ExactLocalRound4JourneyTests):
    def test_a_qr_paid_in_dollars_before_snapshots_named_recipients_still_holds_it(self):
        fixed = self.fixed(breb('1249'))
        old = create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                             request_id=uuid.uuid4(), direction='to_bank', bridge=self.bridge(),
                             destination=fixed, minimum_fx_output='1249.00')
        snapshot = dict(old.destination_snapshot)
        snapshot.pop('store_order'); snapshot.pop('destination_internal_id')   # as in September
        InfiniaJourney.objects.filter(pk=old.pk).update(destination_snapshot=snapshot, stage='completed')
        flow = old.bridge.quote.money_flow
        flow.metadata = dict(flow.metadata or {}, local_destination_id=str(fixed.internal_id))
        flow.save(update_fields=['metadata'])
        other = self.fixed(breb('1249'))
        PayoutDestination.objects.filter(pk__in=[fixed.pk, other.pk]).update(country='COL')
        other.refresh_from_db()
        with self.assertRaisesRegex(PaymentAccountError, 'QR ya tiene un pago'):
            local_money.require_unpaid_qr(other)

    def test_another_accounts_request_id_is_not_its_own_retry(self):
        fixed = self.fixed(breb('1249'))
        first = create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                               request_id=uuid.uuid4(), direction='to_bank', bridge=self.bridge(),
                               destination=fixed, minimum_fx_output='1249.00')
        key = first.destination_snapshot['store_order']['key']
        stranger = type(self.owner).objects.create(user=self.owner.user, account_type='business', account_index=9)
        self.assertTrue(bool(local_money.held(key, exclude_request_id=first.request_id, destination=fixed,
                                            owner=stranger)))
        self.assertFalse(bool(local_money.held(key, exclude_request_id=first.request_id, destination=fixed,
                                             owner=self.owner)))

    def test_the_paid_once_lookups_use_their_indexes(self):
        from django.db import connection
        # The very querysets held() runs, not look-alikes.
        fixed = self.fixed(breb('1249'))
        argentine = self.destination()
        argentine.provider_data = {'method_id': 'ar_qr'}
        argentine.details = {'type': 'QR_CODE', 'qrCode': qr(('01', '12'), ('53', '032'), ('54', '1500.00'), ('58', 'AR'))}
        argentine.save()
        lookups = (local_money.holding_payments('co_qr:qr:k'),
                   local_money.legacy_payments(['a'])[0],
                   local_money.legacy_flows(['a']),
                   local_money.same_qr_rows(fixed),
                   local_money.same_qr_rows(argentine))
        with connection.cursor() as cursor:
            cursor.execute('SET LOCAL enable_seqscan = off')
            for qs, index in zip(lookups, ('infinia_journey_order_key_idx', 'infinia_journey_destination_id_idx',
                                           'money_flow_local_destination_idx',
                                           'payout_destination_breb_qr_idx', 'payout_destination_qr_code_idx')):
                sql, params = qs.query.sql_with_params()
                cursor.execute('EXPLAIN ' + sql, params)
                with self.subTest(index=index):
                    self.assertIn(index, ' '.join(row[0] for row in cursor.fetchall()))


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class ExactLocalApiRound6Tests(ExactLocalApiTests):
    def test_exact_prices_are_paced_per_person(self):
        from django.core.cache import cache
        cache.clear()
        row = local_money.resolve_destination(self.owner, 'br_pix', 'ana@example.com')
        with mock.patch.object(local_money, 'EXACT_QUOTES_PER_WINDOW', 2):
            local_money.exact_send_quote(self.owner, row, '500')
            local_money.exact_send_quote(self.owner, row, '501')
            with self.assertRaisesRegex(PaymentAccountError, 'Espera'):
                local_money.exact_send_quote(self.owner, row, '502')

    def test_a_moved_pago_movil_price_is_a_new_quote_not_a_failure(self):
        from payment_accounts import intent_rails
        from ramps.pagoasap_send import PRICE_MOVED
        rail = mock.Mock()
        rail.create.return_value = mock.Mock(success=False, order_id=None, error=PRICE_MOVED, next_step=None)
        with mock.patch.object(intent_rails, '_rail_of', return_value=rail), self.assertRaises(IntentRefused) as refused:
            intent_rails.create_order(mock.Mock(), mock.Mock())
        self.assertEqual(refused.exception.code, 'quote_changed')


class ExactLocalRound7JourneyTests(ExactLocalRound6JourneyTests):
    def test_an_unsigned_payment_waits_rather_than_paid(self):
        fixed = self.fixed(breb('1249'))
        first = create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                               request_id=uuid.uuid4(), direction='to_bank', bridge=self.bridge(),
                               destination=fixed, minimum_fx_output='1249.00')
        first.bridge.status = 'prepared'; first.bridge.save(update_fields=['status'])   # not signed yet
        key = first.destination_snapshot['store_order']['key']
        self.assertEqual(local_money.held(key, destination=fixed), local_money.SIGNING)
        with self.assertRaisesRegex(PaymentAccountError, 'esperando firma'):
            local_money.require_unpaid_qr(fixed)
        first.bridge.status = 'submitted'; first.bridge.save(update_fields=['status'])
        self.assertEqual(local_money.held(key, destination=fixed), local_money.PAID)


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class ExactLocalApiRound7Tests(ExactLocalApiTests):
    def test_every_exact_card_needs_a_build_that_explains_it_and_is_paced(self):
        request = {'method_id': 'br_pix', 'value': 'ana@example.com', 'amount_local': '500'}
        local_money.fixed_qr_build_supported.return_value = False
        with self.assertRaises(IntentRefused) as refused:
            payment_intents.prepare(self.owner, self.user, created_by='scan', source='form', request=dict(request))
        self.assertIn('Actualiza la app', str(refused.exception))
        local_money.fixed_qr_build_supported.return_value = True
        from django.core.cache import cache
        cache.clear()
        with mock.patch.object(local_money, 'EXACT_QUOTES_PER_WINDOW', 0), self.assertRaises(IntentRefused) as paced:
            payment_intents.prepare(self.owner, self.user, created_by='scan', source='form', request=dict(request))
        self.assertEqual(paced.exception.code, 'rate_limited')


class ExactLocalRound8JourneyTests(ExactLocalRound7JourneyTests):
    def test_waiting_for_a_signature_keeps_the_card(self):
        fixed = self.fixed(breb('1249'))
        first = create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                               request_id=uuid.uuid4(), direction='to_bank', bridge=self.bridge(),
                               destination=fixed, minimum_fx_output='1249.00')
        second_bridge = self.bridge()   # made first: an unsigned bridge reserves the wallet
        first.bridge.status = 'prepared'; first.bridge.save(update_fields=['status'])
        from payment_accounts import intent_rails
        with self.assertRaises(IntentRefused) as waiting:
            intent_rails._require_unpaid(fixed)
        self.assertEqual(waiting.exception.code, 'in_progress')     # not charge_changed: the card stays
        with mock.patch.object(payment_intents, 'journey_refused') as refused:
            result = self.mutate(fixed, bridge=second_bridge, exact_local_amount=Decimal('1249'))
        self.assertEqual((result.success, result.error_code), (False, 'in_progress'))
        refused.assert_not_called()
        first.bridge.status = 'submitted'; first.bridge.save(update_fields=['status'])
        with self.assertRaises(IntentRefused) as paid:
            intent_rails._require_unpaid(fixed)
        self.assertEqual(paid.exception.code, 'charge_changed')


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class ExactLocalApiRound8Tests(ExactLocalApiTests):
    def test_pagars_typed_amount_has_the_same_build_floor(self):
        from payment_accounts.local_money_schema import LocalMoneyQuery
        row = local_money.resolve_destination(self.owner, 'br_pix', 'ana@example.com')
        local_money.fixed_qr_build_supported.return_value = False
        with self.assertRaisesRegex(Exception, 'Actualiza la app'):
            LocalMoneyQuery().resolve_local_exact_send(self.info, row.internal_id, Decimal('500'))

    def test_the_held_quote_rate_is_what_each_dollar_buys(self):
        row = local_money.resolve_destination(self.owner, 'br_pix', 'ana@example.com')
        quote = {'minimum_target': Decimal('540'), 'target_amount': Decimal('540'), 'expected_target': Decimal('540'),
                 'rate': Decimal('5.4000'), 'source_amount': Decimal('100')}
        held = local_money.exact_qr_quote(row, quote, '500')
        self.assertEqual(held['rate'], Decimal('5.0000'))   # 500 for the same 100 dollars


class ExactLocalRound9JourneyTests(ExactLocalRound8JourneyTests):
    def test_a_bridge_that_never_delivered_does_not_hold_a_qr(self):
        fixed = self.fixed(breb('1249'))
        first = create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                               request_id=uuid.uuid4(), direction='to_bank', bridge=self.bridge(),
                               destination=fixed, minimum_fx_output='1249.00')
        key = first.destination_snapshot['store_order']['key']
        for status in ('expired', 'failed', 'refunded'):
            with self.subTest(status=status):
                first.bridge.status = status; first.bridge.save(update_fields=['status'])
                self.assertEqual(local_money.held(key, destination=fixed), '')   # the journey is not failed yet

    def test_a_card_started_from_an_older_build_is_refused(self):
        row = self.destination()
        card = mock.Mock(params={'exact_local': '1249.00'}, amount_exact=True)
        with mock.patch.object(payment_intents, 'journey_guard', return_value=card), \
                mock.patch.object(local_money, 'fixed_qr_build_supported', return_value=False):
            result = self.mutate(row)
        self.assertFalse(result.success)
        self.assertIn('Actualiza la app', result.errors[0])


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class ExactLocalApiRound9Tests(ExactLocalApiTests):
    def test_an_exact_cards_rate_is_what_each_dollar_buys(self):
        intent = payment_intents.prepare(self.owner, self.user, created_by='scan', source='form', request={
            'method_id': 'br_pix', 'value': 'ana@example.com', 'amount_local': '500'})
        self.assertEqual(intent.rate, (Decimal('500') / intent.total_usd).quantize(Decimal('0.0001'), rounding='ROUND_DOWN'))


class ExactLocalRound10JourneyTests(ExactLocalRound9JourneyTests):
    def test_a_payment_in_review_that_paid_no_one_holds_but_is_not_called_paid(self):
        fixed = self.fixed(breb('1249'))
        first = create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                               request_id=uuid.uuid4(), direction='to_bank', bridge=self.bridge(),
                               destination=fixed, minimum_fx_output='1249.00')
        InfiniaJourney.objects.filter(pk=first.pk).update(stage='needs_review')
        key = first.destination_snapshot['store_order']['key']
        self.assertEqual(local_money.held(key, destination=fixed), local_money.REVIEW)
        with self.assertRaisesRegex(PaymentAccountError, 'en revisión'):
            local_money.require_unpaid_qr(fixed)
        InfiniaJourney.objects.filter(pk=first.pk).update(stage='failed')   # ops' release
        self.assertEqual(local_money.held(key, destination=fixed), '')


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class ExactLocalApiRound10Tests(ExactLocalApiTests):
    def test_another_amount_for_a_qr_with_its_own_is_refused(self):
        with self.assertRaises(IntentRefused) as refused:
            payment_intents.prepare(self.owner, self.user, created_by='scan', source='form', request={
                'method_id': 'co_qr', 'value': breb('80000'), 'amount_local': '50000'})
        self.assertEqual(refused.exception.code, 'no_amount')
        self.assertIn('ya trae su monto', str(refused.exception))

    def test_an_exact_card_confirmed_from_an_older_build_is_refused_before_a_bridge(self):
        from payment_accounts import intent_rails
        card = mock.Mock(rail_method_id='br_pix', amount_exact=True, params={'exact_local': '500.00'})
        local_money.fixed_qr_build_supported.return_value = False
        with self.assertRaises(IntentRefused) as refused:
            intent_rails.reread_transfer(self.owner, card, {})
        self.assertIn('Actualiza la app', str(refused.exception))

    def test_one_text_per_qr(self):
        method = local_money.METHODS['co_qr']
        upper = breb('25000')
        lower = upper[:-4] + upper[-4:].lower()
        self.assertEqual(local_money.normalize_value(method, lower), upper)
        from .test_breb_fixed_qr import argentina
        ar = argentina('1500.00')
        self.assertEqual(local_money.normalize_value(local_money.METHODS['ar_qr'], ar[:-4] + ar[-4:].lower()), ar)

    def test_a_fixed_qrs_mismatch_is_refused_before_a_provider(self):
        from payment_accounts.local_money_schema import LocalMoneyQuery
        fixed = local_money.resolve_destination(self.owner, 'co_qr', breb('25000'))
        with mock.patch.object(local_money, 'payout_quote') as quote, self.assertRaisesRegex(Exception, 'no coincide'):
            LocalMoneyQuery().resolve_local_payout_quote(self.info, fixed.internal_id, amount=Decimal('50'),
                                                         exact_local=Decimal('1000'))
        quote.assert_not_called()


def only_own_tests(cls, *bases):
    """Run only the tests a class defines itself, not the ones its fixture
    base classes bring along (they run in their own modules)."""
    for base in bases:
        for name in dir(base):
            if name.startswith('test') and name not in cls.__dict__:
                setattr(cls, name, None)
    return cls


only_own_tests(ExactLocalJourneyTests, journey_fixture.JourneyTests)
only_own_tests(HoldingPaymentsTests, journey_fixture.JourneyTests, ExactLocalJourneyTests)
only_own_tests(ExactLocalApiEdgeTests, ExactLocalApiTests)
only_own_tests(ExactLocalRound3Tests, journey_fixture.JourneyTests, ExactLocalJourneyTests)
only_own_tests(ExactLocalApiRound3Tests, ExactLocalApiTests)
only_own_tests(ExactLocalRound4JourneyTests, journey_fixture.JourneyTests, ExactLocalJourneyTests, ExactLocalRound3Tests)
only_own_tests(ExactLocalApiRound4Tests, ExactLocalApiTests)
only_own_tests(ExactLocalApiRound5Tests, ExactLocalApiTests)
only_own_tests(ExactLocalRound6JourneyTests, journey_fixture.JourneyTests, ExactLocalJourneyTests, ExactLocalRound3Tests,
               ExactLocalRound4JourneyTests)
only_own_tests(ExactLocalApiRound6Tests, ExactLocalApiTests)
only_own_tests(ExactLocalRound7JourneyTests, journey_fixture.JourneyTests, ExactLocalJourneyTests, ExactLocalRound3Tests,
               ExactLocalRound4JourneyTests, ExactLocalRound6JourneyTests)
only_own_tests(ExactLocalApiRound7Tests, ExactLocalApiTests)
only_own_tests(ExactLocalRound8JourneyTests, journey_fixture.JourneyTests, ExactLocalJourneyTests, ExactLocalRound3Tests,
               ExactLocalRound4JourneyTests, ExactLocalRound6JourneyTests, ExactLocalRound7JourneyTests)
only_own_tests(ExactLocalApiRound8Tests, ExactLocalApiTests)
only_own_tests(ExactLocalRound9JourneyTests, journey_fixture.JourneyTests, ExactLocalJourneyTests, ExactLocalRound3Tests,
               ExactLocalRound4JourneyTests, ExactLocalRound6JourneyTests, ExactLocalRound7JourneyTests,
               ExactLocalRound8JourneyTests)
only_own_tests(ExactLocalApiRound9Tests, ExactLocalApiTests)
only_own_tests(ExactLocalRound10JourneyTests, journey_fixture.JourneyTests, ExactLocalJourneyTests, ExactLocalRound3Tests,
               ExactLocalRound4JourneyTests, ExactLocalRound6JourneyTests, ExactLocalRound7JourneyTests,
               ExactLocalRound8JourneyTests, ExactLocalRound9JourneyTests)
only_own_tests(ExactLocalApiRound10Tests, ExactLocalApiTests)
