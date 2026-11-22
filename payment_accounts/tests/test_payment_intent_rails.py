"""Prepared payments on every rail: one card shape, each rail's own machinery."""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock
import uuid

from django.test import SimpleTestCase, override_settings

from payment_accounts import intent_rails, local_money, payment_intents
from payment_accounts.models import PaymentIntent
from payment_accounts.payment_intents import IntentRefused
from payment_accounts.services import PaymentAccountError
from .test_payment_intents import PaymentIntentBase
from .test_pix_charges import DYNAMIC, charge_validation
from .test_local_money import qr, tlv

PIX = tlv('00', 'br.gov.bcb.pix')
OPEN_PIX = qr(('26', PIX + tlv('01', 'ana@example.com')), ('53', '986'), ('58', 'BR'), ('59', 'ANA SILVA'))
EVERY_LEVEL = ('holder_verified,confio_account,provider_named,institution_charge,institution_amount,'
               'signed_charge,signed_amount,saved_payee,self_reported,unverified')


class RoutingTests(SimpleTestCase):
    def test_a_code_declares_its_own_rail(self):
        self.assertEqual(intent_rails.route({'code': DYNAMIC}), ('local_charge', 'br_qr', 'infinia'))
        self.assertEqual(intent_rails.route({'code': OPEN_PIX}), ('local_transfer', 'br_qr', 'infinia'))
        argentina = qr(('01', '11'), ('53', '032'), ('58', 'AR'), ('59', 'KIOSCO'))
        self.assertEqual(intent_rails.route({'code': argentina}), ('local_transfer', 'ar_qr', 'infinia'))

    def test_named_rails(self):
        self.assertEqual(intent_rails.route({'method_id': 'mx_clabe', 'value': '1'}),
                         ('local_transfer', 'mx_clabe', 'infinia'))
        with override_settings(VE_PAGOMOVIL_SEND_PROVIDER='pagoasap'):
            self.assertEqual(intent_rails.route({'method_id': 've_pagomovil_send'}),
                             ('ramp_order', 've_pagomovil_send', 'pagoasap'))
        # The same rail, another provider: nothing else changes.
        with override_settings(VE_PAGOMOVIL_SEND_PROVIDER='dinaria'):
            self.assertEqual(intent_rails.route({'method_id': 've_pagomovil_send'}),
                             ('ramp_order', 've_pagomovil_send', 'dinaria'))
        with mock.patch('ramps.bolivia_qr.provider_name', return_value='mesadepagos'):
            self.assertEqual(intent_rails.route({'method_id': 'bo_qr', 'code': 'x'}),
                             ('ramp_order', 'bo_qr', 'mesadepagos'))
        self.assertEqual(intent_rails.route({'method_id': 'confio_send'}), ('confio_send', 'confio_send', 'confio'))

    def test_a_rail_with_no_provider_is_not_available(self):
        with mock.patch('ramps.bolivia_qr.provider_name', return_value=''), self.assertRaises(IntentRefused) as no:
            intent_rails.route({'method_id': 'bo_qr', 'code': 'x'})
        self.assertEqual(no.exception.code, 'rail')

    def test_the_provider_setting_is_read_strictly(self):
        with override_settings(VE_PAGOMOVIL_SEND_PROVIDER='pagoasap'):
            for value in (' VE_PAGOMOVIL_SEND = PagoAsap ', 've_pagomovil_send=pagoasap,'):
                with self.subTest(value=value), override_settings(PAYMENT_INTENTS_RAIL_PROVIDERS=value):
                    self.assertEqual(intent_rails.provider_for('ve_pagomovil_send'), 'pagoasap')
            # Spaces and capitals still mean what was written: no quiet default.
            with override_settings(PAYMENT_INTENTS_RAIL_PROVIDERS='VE_PAGOMOVIL_SEND = Dinaria'):
                self.assertIsNone(intent_rails.provider_for('ve_pagomovil_send'))
            # Two answers for one rail: neither.
            with override_settings(PAYMENT_INTENTS_RAIL_PROVIDERS='br_pix=infinia,br_pix=dinaria'):
                self.assertIsNone(intent_rails.provider_for('br_pix'))
            # A rail that does not exist is reported, and changes nothing else.
            with override_settings(PAYMENT_INTENTS_RAIL_PROVIDERS='ar_cvuu=dinaria'), \
                    self.assertLogs('payment_accounts.intent_rails', level='ERROR'):
                self.assertEqual(intent_rails.provider_for('ar_cvu'), 'infinia')

    def test_a_second_provider_for_a_rail_is_one_registration_and_one_setting(self):
        class DinariaCvu(intent_rails.OrderRail):
            rail = 'ar_cvu'

            def provider(self):
                return 'dinaria'
        try:
            intent_rails.register_order_rail(DinariaCvu())
            self.assertEqual(intent_rails.providers_of('ar_cvu'), ['infinia', 'dinaria'])
            # Unconfigured: the rail's default provider.
            self.assertEqual(intent_rails.route({'method_id': 'ar_cvu', 'value': '1'}),
                             ('local_transfer', 'ar_cvu', 'infinia'))
            with override_settings(PAYMENT_INTENTS_RAIL_PROVIDERS='ar_cvu=dinaria, br_pix=infinia'):
                self.assertEqual(intent_rails.route({'method_id': 'ar_cvu', 'value': '1'}),
                                 ('ramp_order', 'ar_cvu', 'dinaria'))
                self.assertEqual(intent_rails.provider_for('br_pix'), 'infinia')
            # A configured provider that does not carry the rail: no silent fall back.
            with override_settings(PAYMENT_INTENTS_RAIL_PROVIDERS='br_pix=dinaria'), \
                    self.assertRaises(IntentRefused) as refused:
                intent_rails.route({'method_id': 'br_pix', 'value': 'ana@example.com'})
            self.assertEqual(refused.exception.code, 'rail')
        finally:
            intent_rails.ORDER_RAILS.pop('ar_cvu', None)
        self.assertEqual(intent_rails.providers_of('ar_cvu'), ['infinia'])

    def test_what_is_not_a_payment_is_refused(self):
        for request in ({}, {'code': 'hola'}, {'method_id': 'br_pix_receive', 'value': 'x'}, {'method_id': 'card'}):
            with self.subTest(request=request), self.assertRaises(IntentRefused) as refused:
                intent_rails.route(request)
            self.assertEqual(refused.exception.code, 'no_code')

    def test_every_send_rail_of_the_app_has_a_family(self):
        sends = {m.id for m in local_money.METHODS.values() if m.direction == 'send'}
        self.assertEqual(sends, set(intent_rails.INFINIA_METHODS))
        self.assertEqual(sends, {'br_pix', 'br_qr', 'co_breb', 'co_qr', 'mx_clabe', 'ar_cvu', 'ar_qr'})

    def test_dollar_amounts(self):
        self.assertEqual(intent_rails.usd_amount('20'), Decimal('20.00'))
        self.assertEqual(intent_rails.usd_amount('20.019'), Decimal('20.01'))
        for bad in (None, '', 'veinte', '0', '-5', 'NaN', '1e12'):
            self.assertIsNone(intent_rails.usd_amount(bad))


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, INFINIA_ACCOUNT_VALIDATION_ENABLED=False)
class TransferTests(PaymentIntentBase):
    """A dollar amount to a key, an account or an open QR (Infinia journey)."""

    def setUp(self):
        super().setUp()
        self.minimum = Decimal('100.00')
        self.payout = mock.patch.object(local_money, 'payout_quote', side_effect=lambda owner, destination, **kw: {
            'source_amount': Decimal('19.5'), 'target_amount': Decimal('101.00'), 'minimum_target': self.minimum,
            'expected_source_amount': Decimal('19.6'), 'expected_target': Decimal('101.50'),
            'total_cost_percent': Decimal('2'), 'rate': Decimal('5.0750'), 'asset': 'BRL', 'expires_at': ''}).start()
        self.fee = mock.patch.object(local_money, 'payout_fee', return_value={'total_usd': '0.10'}).start()

    def transfer(self, **request):
        details = {'method_id': 'br_pix', 'value': 'ana@example.com', 'amount_usd': '20'}
        details.update(request)
        return payment_intents.prepare(self.owner, self.user, created_by='scan', source='form', request=details)

    def test_the_card_of_a_transfer_fixes_the_dollars_and_shows_a_minimum(self):
        intent = self.transfer()
        self.assertEqual((intent.family, intent.rail_method_id, intent.provider, intent.amount_exact),
                         ('local_transfer', 'br_pix', 'infinia', False))
        self.assertEqual((intent.total_usd, intent.amount_local, intent.currency, intent.fee_usd),
                         (Decimal('20.00'), Decimal('101.50'), 'BRL', Decimal('0.10')))
        # 100.00 less the half-percent margin: the least that is authorized.
        self.assertEqual(intent.minimum_local, Decimal('99.50'))
        # Nobody looked the key up: the card says so and shows the key itself.
        self.assertEqual((intent.payee_level, intent.payee_name, intent.payee_account),
                         ('unverified', 'Pix', 'ana@example.com'))
        self.assertEqual(intent.display_hash, payment_intents.display_hash(PaymentIntent.objects.get(pk=intent.pk)))
        self.assertIsNone(intent.charge_expires_at)

    def test_an_unlooked_up_key_gets_no_card_by_default(self):
        with override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=''), self.assertRaises(IntentRefused) as refused:
            self.transfer()
        self.assertEqual(refused.exception.code, 'payee_level')

    def test_a_verified_holder_is_shown_as_one(self):
        with override_settings(INFINIA_ACCOUNT_VALIDATION_ENABLED=True, PAYMENT_INTENTS_PAYEE_LEVELS=''):
            from payment_accounts.models import PayoutDestination
            PayoutDestination.objects.create(
                confio_account=self.owner, provider='infinia', kind='bank_account', country='BRA', asset='BRL',
                label='Pix', holder_name='ANA SILVA', details={'type': 'CHAVE PIX', 'chavePix': 'ana@example.com'},
                provider_data={'method_id': 'br_pix', 'validation': dict(charge_validation(), charge=None,
                                                                         holder_name='ANA SILVA')})
            intent = self.transfer()
        self.assertEqual((intent.payee_level, intent.payee_name, intent.institution),
                         ('holder_verified', 'ANA SILVA', 'Banco'))

    def test_an_open_qr_shows_its_own_text_as_unverified(self):
        intent = self.transfer(method_id=None, value=None, code=OPEN_PIX)
        self.assertEqual((intent.rail_method_id, intent.payee_level, intent.payee_name),
                         ('br_qr', 'self_reported', 'ANA SILVA'))

    def test_refusals(self):
        cases = {'no_amount': dict(amount_usd=None), 'no_code': dict(value='not a key at all !!')}
        for code, request in cases.items():
            with self.subTest(code), self.assertRaises(IntentRefused) as refused:
                self.transfer(**request)
            self.assertEqual(refused.exception.code, code)
        self.assertFalse(PaymentIntent.objects.exists())

    def test_confirm_prepares_the_bridge_and_the_journey_takes_the_shown_minimum(self):
        intent = self.transfer()
        (confirmed, transfer, *_), quote, *_ = self.confirm(intent)
        self.assertEqual(confirmed.state, 'awaiting_signature')
        self.assertEqual(quote.call_args.kwargs['amount'], Decimal('20.00'))
        self.assertEqual(payment_intents.journey_minimum(confirmed), Decimal('99.50'))
        args = dict(direction='to_bank', bridge=transfer, destination=confirmed.destination)
        self.assertEqual(payment_intents.journey_guard(self.owner, intent.request_id, minimum_fx_output='99.50',
                                                       **args).pk, intent.pk)
        for wrong in ('101.50', '99.49', '0'):
            with self.subTest(wrong), self.assertRaises(IntentRefused):
                payment_intents.journey_guard(self.owner, intent.request_id, minimum_fx_output=wrong, **args)

    def test_a_worse_rate_is_never_signed(self):
        intent = self.transfer()
        self.minimum = Decimal('98.00')
        with self.assertRaises(IntentRefused) as refused:
            self.confirm(intent)
        self.assertEqual(refused.exception.code, 'quote_changed')
        intent.refresh_from_db()
        self.assertEqual(intent.state, 'expired')

    def test_a_bridge_that_lands_less_than_shown_ends_the_card(self):
        intent = self.transfer()

        def quote(owner, destination, **kwargs):
            landed = Decimal('99.00') if kwargs.get('bridge') is not None else Decimal('100.00')
            return {'minimum_target': landed, 'expected_target': Decimal('101.50'), 'rate': Decimal('5.0750'),
                    'asset': 'BRL', 'expires_at': ''}
        self.payout.side_effect = quote
        with self.assertRaises(IntentRefused) as refused:
            self.confirm(intent)
        self.assertEqual(refused.exception.code, 'quote_changed')
        intent.refresh_from_db()
        self.assertEqual((intent.state, intent.bridge_id), ('expired', None))

    def test_a_recipient_that_reads_differently_at_the_journey_is_refused(self):
        intent = self.transfer()
        (confirmed, transfer, *_), *_ = self.confirm(intent)
        destination = confirmed.destination
        destination.provider_data = dict(destination.provider_data, validation={'status': 'ERROR'})
        destination.save()
        with self.assertRaises(IntentRefused) as refused:
            payment_intents.journey_guard(self.owner, intent.request_id, direction='to_bank', bridge=transfer,
                                          destination=destination, minimum_fx_output='99.50')
        self.assertEqual(refused.exception.code, 'charge_changed')

    def test_requote_reads_the_same_recipient_and_amount_again(self):
        intent = self.transfer()
        fresh = payment_intents.requote(self.owner, self.user, intent.internal_id)
        self.assertEqual((fresh.destination_id, fresh.total_usd, fresh.supersedes_id),
                         (intent.destination_id, intent.total_usd, intent.pk))
        intent.refresh_from_db()
        self.assertEqual(intent.state, 'expired')

    def test_colombia_needs_its_location_pass(self):
        with mock.patch('payment_accounts.breb_location.require_for_country',
                        side_effect=PaymentAccountError('Confirma tu ubicación para usar Bre-B.')), \
                self.assertRaises(IntentRefused) as refused:
            self.transfer()
        self.assertEqual(refused.exception.code, 'rail')


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL)
class OrderTests(PaymentIntentBase):
    """Pago Móvil and QR Bolivia: the order is made at confirmation, from the
    intent's own details, through the rail's own mutation."""

    def setUp(self):
        super().setUp()
        mock.patch('ramps.ve_pagomovil.enabled', return_value=True).start()
        mock.patch('ramps.ve_pagomovil.client_supports', return_value=True).start()
        self.ve_quote = {'usd_amount': '20.00', 'usdt_amount': '19.80', 'confio_fee_usd': '0.20',
                         'processor_fee_usd': '0.30', 'estimated_ves': '2500.50', 'rate': '128.2300'}
        adapter = mock.Mock()
        adapter.quote.side_effect = lambda amount: dict(self.ve_quote)
        mock.patch('ramps.ve_pagomovil.send_adapter', return_value=adapter).start()
        mock.patch('ramps.bolivia_qr.offered', return_value=True).start()
        mock.patch('ramps.bolivia_qr.provider_name', return_value='mesadepagos').start()
        self.preview = {'holder_name': 'TIENDA LA PAZ SRL', 'bank_name': 'Banco Unión', 'account_last4': '4321',
                        'fixed_amount': True, 'amount': '70.00'}
        self.bo_usd = '10.20'
        mock.patch('ramps.bolivia_qr_send.decode', side_effect=lambda text: dict(self.preview)).start()
        mock.patch('ramps.bolivia_qr_send.quote', side_effect=lambda text, amount=None: {
            'preview': dict(self.preview), 'bob_amount': self.preview['amount'] if self.preview['fixed_amount']
            else format(Decimal(str(amount)), '.2f'), 'usd_amount': self.bo_usd, 'usdt_amount': '10.10',
            'confio_fee_usd': '0.10', 'rate': '6.9600', 'usdc_units': '1'}).start()
        self.info = SimpleNamespace(context=SimpleNamespace(user=self.user, META={'HTTP_X_CONFIO_VERSION': '9'}))

    def pagomovil(self, **request):
        details = {'method_id': 've_pagomovil_send', 'amount_usd': '20', 'phone': '04141234567',
                   'cedula': 'V12345678', 'bank_code': '0102', 'holder_name': 'María Pérez'}
        details.update(request)
        return payment_intents.prepare(self.owner, self.user, created_by='scan', source='form', request=details)

    def bolivia(self, **request):
        details = {'method_id': 'bo_qr', 'code': 'BOLIVIA-QR-TEXT'}
        details.update(request)
        return payment_intents.prepare(self.owner, self.user, created_by='scan', source='scanned_qr',
                                       request=details)

    def test_pago_movil_card_says_nobody_checked_the_recipient(self):
        intent = self.pagomovil()
        self.assertEqual((intent.family, intent.payee_level, intent.payee_name, intent.currency),
                         ('ramp_order', 'unverified', 'María Pérez', 'VES'))
        self.assertEqual((intent.total_usd, intent.amount_local, intent.fee_usd, intent.amount_exact),
                         (Decimal('20.00'), Decimal('2500.50'), Decimal('0.50'), False))
        self.assertEqual(intent.payee_account, '584141234567 · V12345678')
        self.assertEqual(intent.params, {'cedula': 'V12345678', 'phone': '584141234567', 'bank_code': '0102',
                                         'holder_name': 'María Pérez'})
        self.assertIsNone(intent.destination)
        with override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=''), self.assertRaises(IntentRefused) as refused:
            self.pagomovil()
        self.assertEqual(refused.exception.code, 'payee_level')

    def test_a_recipient_the_owner_saved_is_allowed_by_default(self):
        from payment_accounts.models import AgendaEntry
        AgendaEntry.objects.create(confio_account=self.owner, rail='ve_pagomovil', holder_name='Mamá',
                                   relationship='third_party',
                                   details={'cedula': 'V12345678', 'phone': '584141234567', 'bank_code': '0102'})
        with override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=''):
            intent = self.pagomovil(holder_name='')
        self.assertEqual((intent.payee_level, intent.payee_name), ('saved_payee', 'Mamá'))
        # Another phone is another person: not that saved recipient.
        with override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=''), self.assertRaises(IntentRefused):
            self.pagomovil(phone='04241234567')
        # A recipient the owner deleted is no longer one they saved.
        from django.utils import timezone
        AgendaEntry.objects.update(deleted_at=timezone.now())
        with override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=''), self.assertRaises(IntentRefused):
            self.pagomovil(holder_name='')

    def test_bad_details_are_refused_in_the_rails_own_words(self):
        for request in (dict(phone='123'), dict(cedula='X'), dict(bank_code='9999'), dict(amount_usd='')):
            with self.subTest(request=request), self.assertRaises(IntentRefused):
                self.pagomovil(**request)
        self.assertFalse(PaymentIntent.objects.exists())

    def test_bolivia_qr_shows_the_holder_the_provider_named_and_the_exact_amount(self):
        with override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=''):
            intent = self.bolivia()
        self.assertEqual((intent.payee_level, intent.payee_name, intent.institution, intent.payee_account),
                         ('provider_named', 'TIENDA LA PAZ SRL', 'Banco Unión', '•••• 4321'))
        self.assertEqual((intent.amount_exact, intent.amount_local, intent.currency, intent.total_usd),
                         (True, Decimal('70.00'), 'BOB', Decimal('10.20')))
        self.assertEqual(intent.params, {'qr_text': 'BOLIVIA-QR-TEXT', 'bob_amount': ''})

    def test_an_open_bolivian_qr_needs_the_amount(self):
        self.preview = dict(self.preview, fixed_amount=False, amount=None)
        with self.assertRaises(IntentRefused) as refused:
            self.bolivia()
        self.assertEqual(refused.exception.code, 'no_amount')
        self.assertEqual(self.bolivia(amount_local='35').params['bob_amount'], '35.00')

    def confirm_order(self, intent, order_id=None, **result):
        order_id = order_id or str(uuid.uuid4())
        created = SimpleNamespace(success=True, order_id=order_id, error=None, **result)
        target = ('ramps.ve_pagomovil_schema.CreateVePagoMovilSend.mutate' if intent.rail_method_id ==
                  've_pagomovil_send' else 'ramps.bolivia_qr_schema.CreateBoliviaQrSend.mutate')
        with mock.patch(target, return_value=created) as create:
            out = payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash,
                                              self.info)
        return out, create, order_id

    def test_confirm_makes_the_order_from_the_intents_own_details(self):
        intent = self.pagomovil()
        (confirmed, signing), create, order_id = self.confirm_order(intent)
        self.assertEqual((signing['kind'], signing['order_id'], confirmed.state, confirmed.order_ref),
                         ('ramp_order', order_id, 'submitted', order_id))
        self.assertEqual(create.call_args.kwargs, {'usd_amount': '20.00', 'cedula': 'V12345678',
                                                   'phone': '584141234567', 'bank_code': '0102',
                                                   'beneficiary_name': 'María Pérez'})
        self.assertIs(create.call_args.args[0], self.info)
        intent = self.bolivia()
        (_, signing), create, _ = self.confirm_order(intent)
        self.assertEqual(create.call_args.kwargs, {'qr_text': 'BOLIVIA-QR-TEXT', 'max_usd_amount': '10.20',
                                                   'bob_amount': None})

    def test_the_provider_is_stored_and_a_switch_of_provider_ends_the_card(self):
        with override_settings(VE_PAGOMOVIL_SEND_PROVIDER='pagoasap'):
            intent = self.pagomovil()
        self.assertEqual((intent.provider, self.bolivia().provider), ('pagoasap', 'mesadepagos'))
        # Pago Móvil moves to Dinaria before the person confirms: that price was Pago ASAP's.
        with override_settings(VE_PAGOMOVIL_SEND_PROVIDER='dinaria'), \
                mock.patch('ramps.ve_pagomovil_schema.CreateVePagoMovilSend.mutate') as create, \
                self.assertRaises(IntentRefused) as refused:
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
        self.assertEqual(refused.exception.code, 'quote_changed')
        create.assert_not_called()
        intent.refresh_from_db()
        self.assertEqual(intent.state, 'expired')
        with override_settings(VE_PAGOMOVIL_SEND_PROVIDER='dinaria'):
            fresh = payment_intents.requote(self.owner, self.user, intent.internal_id)
        self.assertEqual((fresh.provider, fresh.state), ('dinaria', 'quoted'))

    def test_an_order_made_for_a_card_that_was_declared_dead_is_closed(self):
        from ramps import ve_send
        intent = self.pagomovil()
        order_id = str(uuid.uuid4())

        def slow_create(*args, **kwargs):
            # Meanwhile the card was declared dead (the request took too long).
            PaymentIntent.objects.filter(pk=intent.pk).update(state='expired', state_reason='order_failed')
            return SimpleNamespace(success=True, order_id=order_id, error=None)
        ramp = object()
        manager = mock.Mock()
        manager.filter.return_value.first.return_value = ramp
        with mock.patch('ramps.ve_pagomovil_schema.CreateVePagoMovilSend.mutate', side_effect=slow_create), \
                mock.patch('ramps.models.RampTransaction.objects', manager), \
                mock.patch.object(ve_send, 'cancel') as cancel, self.assertRaises(IntentRefused) as refused:
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
        self.assertEqual(refused.exception.code, 'expired')
        cancel.assert_called_once_with(ramp)
        intent.refresh_from_db()
        self.assertEqual((intent.state, intent.order_ref), ('expired', ''))

    def test_quoting_again_closes_a_dead_claim_so_a_late_confirmation_attaches_nothing(self):
        from datetime import timedelta
        from django.utils import timezone
        from ramps import ve_send
        intent = self.pagomovil()
        order_id = str(uuid.uuid4())
        stale = timezone.now() - timedelta(minutes=5)

        def slow_create(*args, **kwargs):
            # The request hangs past the claim window; the person quotes again meanwhile.
            PaymentIntent.objects.filter(pk=intent.pk).update(updated_at=stale)
            self.fresh = payment_intents.requote(self.owner, self.user, intent.internal_id)
            return SimpleNamespace(success=True, order_id=order_id, error=None)
        manager = mock.Mock()
        manager.filter.return_value.first.return_value = object()
        with mock.patch('ramps.ve_pagomovil_schema.CreateVePagoMovilSend.mutate', side_effect=slow_create), \
                mock.patch('ramps.models.RampTransaction.objects', manager), \
                mock.patch.object(ve_send, 'cancel') as cancel, self.assertRaises(IntentRefused) as refused:
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
        self.assertEqual(refused.exception.code, 'expired')
        cancel.assert_called_once()  # the order it made is closed, not left behind a dead card
        intent.refresh_from_db()
        self.assertEqual((intent.state, intent.order_ref, self.fresh.state), ('expired', '', 'quoted'))

    def test_a_card_whose_order_is_being_created_cannot_be_quoted_again(self):
        intent = self.pagomovil()
        PaymentIntent.objects.filter(pk=intent.pk).update(state='awaiting_signature')
        with self.assertRaises(IntentRefused) as refused:
            payment_intents.requote(self.owner, self.user, intent.internal_id)
        self.assertEqual(refused.exception.code, 'in_progress')

    def test_a_second_tap_never_makes_a_second_order(self):
        intent = self.pagomovil()
        (_, _), create, order_id = self.confirm_order(intent)
        with mock.patch.object(intent_rails, 'order_status', return_value=('awaiting_signature', object())), \
                mock.patch('ramps.ve_pagomovil_schema.CreateVePagoMovilSend.mutate') as again:
            _, signing = payment_intents.confirm_any(self.owner, self.user, intent.internal_id,
                                                     intent.display_hash, self.info)
        again.assert_not_called()
        self.assertEqual(signing['order_id'], order_id)
        # While the first tap is still creating it, a second one is told so.
        other = self.bolivia()
        PaymentIntent.objects.filter(pk=other.pk).update(state='awaiting_signature')
        with self.assertRaises(IntentRefused) as refused:
            payment_intents.confirm_any(self.owner, self.user, other.internal_id, other.display_hash, self.info)
        self.assertEqual(refused.exception.code, 'in_progress')

    def test_the_rails_refusal_ends_the_card_and_carries_its_next_step(self):
        intent = self.pagomovil()
        refused_order = SimpleNamespace(success=False, order_id=None, error='Ya tienes un envío pendiente.',
                                        next_step=None)
        with mock.patch('ramps.ve_pagomovil_schema.CreateVePagoMovilSend.mutate', return_value=refused_order), \
                self.assertRaises(IntentRefused) as refused:
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
        self.assertEqual((refused.exception.code, str(refused.exception), refused.exception.next_step),
                         ('rail', 'Ya tienes un envío pendiente.', ''))
        intent.refresh_from_db()
        self.assertEqual((intent.state, intent.state_reason, intent.order_ref), ('expired', 'order_failed', ''))

    def test_a_dearer_qr_or_another_holder_is_never_ordered(self):
        intent = self.bolivia()
        self.bo_usd = '10.90'
        with mock.patch('ramps.bolivia_qr_schema.CreateBoliviaQrSend.mutate') as create, \
                self.assertRaises(IntentRefused) as refused:
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
        self.assertEqual(refused.exception.code, 'quote_changed')
        create.assert_not_called()
        self.bo_usd = '10.20'
        intent = self.bolivia()
        self.preview = dict(self.preview, holder_name='OTRA TIENDA')
        with mock.patch('ramps.bolivia_qr_schema.CreateBoliviaQrSend.mutate') as create, \
                self.assertRaises(IntentRefused) as refused:
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
        self.assertEqual(refused.exception.code, 'charge_changed')
        create.assert_not_called()

    def test_the_wrong_hash_or_an_expired_card_orders_nothing(self):
        intent = self.pagomovil()
        with mock.patch('ramps.ve_pagomovil_schema.CreateVePagoMovilSend.mutate') as create:
            with self.assertRaises(IntentRefused) as refused:
                payment_intents.confirm_any(self.owner, self.user, intent.internal_id, 'x', self.info)
            self.assertEqual(refused.exception.code, 'changed')
            from datetime import timedelta
            from django.utils import timezone
            intent.expires_at = timezone.now() - timedelta(seconds=1)
            intent.display_hash = payment_intents.display_hash(intent)
            intent.save()
            with self.assertRaises(IntentRefused) as refused:
                payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash,
                                            self.info)
            self.assertEqual(refused.exception.code, 'expired')
        create.assert_not_called()

    def test_a_confirmation_that_died_does_not_leave_the_card_stuck(self):
        from datetime import timedelta
        from django.utils import timezone
        intent = self.pagomovil()
        PaymentIntent.objects.filter(pk=intent.pk).update(state='awaiting_signature',
                                                          updated_at=timezone.now() - timedelta(minutes=5))
        intent.refresh_from_db()
        self.assertEqual(payment_intents.status(intent)[0], 'expired')
        with self.assertRaises(IntentRefused) as refused:
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
        self.assertEqual(refused.exception.code, 'expired')
        self.assertEqual(payment_intents.requote(self.owner, self.user, intent.internal_id).state, 'quoted')

    def test_face_first_keeps_an_order_card_too(self):
        intent = self.pagomovil()
        needs_face = SimpleNamespace(success=False, order_id=None, error='Confirma que eres tú.',
                                     next_step='face_check')
        with mock.patch('ramps.ve_pagomovil_schema.CreateVePagoMovilSend.mutate', return_value=needs_face), \
                self.assertRaises(IntentRefused):
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
        intent.refresh_from_db()
        self.assertEqual(intent.state, 'quoted')

    def test_the_fee_line_of_a_fixed_dollar_send_may_move_inside_the_same_total(self):
        intent = self.pagomovil()
        self.ve_quote = dict(self.ve_quote, processor_fee_usd='0.45')
        (confirmed, _), _, _ = self.confirm_order(intent)
        self.assertEqual(confirmed.state, 'submitted')

    def test_status_follows_the_order(self):
        intent = self.pagomovil()
        self.assertEqual(payment_intents.status(intent)[0], 'quoted')
        (confirmed, _), _, _ = self.confirm_order(intent)
        for result, outcome in (('awaiting_signature', ''), ('paying', ''), ('under_review', ''), ('paid', 'paid')):
            with mock.patch.object(intent_rails, 'order_status', return_value=(result, object())):
                self.assertEqual(payment_intents.status(confirmed)[0], result)
            self.assertEqual(confirmed.outcome, outcome)
        # An order that cannot be found is never shown as open or paid.
        self.assertEqual(payment_intents.status(PaymentIntent.objects.get(pk=intent.pk))[0], 'under_review')
        with self.assertRaises(IntentRefused):
            payment_intents.cancel(self.owner, intent.internal_id)

    def test_requote_only_once_the_order_is_over(self):
        intent = self.bolivia()
        (confirmed, _), _, _ = self.confirm_order(intent)
        for alive, code in (('awaiting_signature', 'still_open'), ('paying', 'in_progress'), ('paid', 'in_progress')):
            with mock.patch.object(intent_rails, 'order_status', return_value=(alive, object())), \
                    self.assertRaises(IntentRefused) as refused:
                payment_intents.requote(self.owner, self.user, intent.internal_id)
            self.assertEqual(refused.exception.code, code)
        with mock.patch.object(intent_rails, 'order_status', return_value=('expired', object())):
            fresh = payment_intents.requote(self.owner, self.user, intent.internal_id)
        self.assertEqual((fresh.state, fresh.params, fresh.supersedes_id), ('quoted', intent.params, intent.pk))

    def test_real_order_states_map_to_card_states(self):
        from ramps import ve_send
        cases = [(('COMPLETED', '', 'paid'), 'paid'), (('FAILED', 'expired_unfunded', ''), 'expired'),
                 (('FAILED', 'cancelled_by_user', ''), 'cancelled'), (('FAILED', 'payout_not_sent', ''), 'expired'),
                 (('FAILED', 'refunded_to_wallet', 'refunded'), 'refunded'), (('FAILED', 'payment_refused', ''), 'expired'),
                 (('PROCESSING', '', 'payout_review'), 'under_review'), (('PENDING', '', 'awaiting_funding'),
                                                                         'awaiting_signature'),
                 (('PROCESSING', '', 'funded'), 'paying'),
                 (('PROCESSING', 'needs_review:funding_mismatch', 'funding_reported'), 'under_review')]
        intent = SimpleNamespace(order_ref='x', user_id=self.user.pk)
        for (status, detail, phase), expected in cases:
            ramp = SimpleNamespace(status=status, status_detail=detail, metadata={})
            with self.subTest(expected=expected, detail=detail), \
                    mock.patch.object(intent_rails, '_order', return_value=ramp), \
                    mock.patch.object(ve_send, 'view', return_value={'phase': phase}):
                self.assertEqual(intent_rails.order_status(intent)[0], expected)
        # A payout that failed AFTER the money left is a failed payment, not an expired card.
        funded = SimpleNamespace(status='FAILED', status_detail='payout_rejected',
                                 metadata={ve_send.SECTION: {'funding_tx_hash': '0x1', 'funded_wei': '5'}})
        with mock.patch.object(intent_rails, '_order', return_value=funded), \
                mock.patch.object(ve_send, 'view', return_value={'phase': ''}):
            self.assertEqual(intent_rails.order_status(intent)[0], 'failed')


@override_settings(CUSD_PLUS_7702_ENABLED=True, BSC_SEND_ENABLED=True, PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL)
class ConfioSendTests(PaymentIntentBase):
    def setUp(self):
        super().setUp()
        from users.models import Account, User
        self.ana = User.objects.create_user(username='ana.silva', firebase_uid='ana', first_name='Ana')
        Account.objects.create(user=self.ana, account_type='personal', account_index=0,
                               bsc_address='0x' + '2' * 40)
        self.info = SimpleNamespace(context=SimpleNamespace(user=self.user, META={}))

    def send(self, recipient='@Ana.Silva', amount='15'):
        return payment_intents.prepare(self.owner, self.user, created_by='scan', source='form', request={
            'method_id': 'confio_send', 'recipient': recipient, 'amount_usd': amount})

    def test_a_confio_account_is_shown_by_the_apps_own_name_rule(self):
        with override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=''):
            intent = self.send()
        # Never the full name of someone they have not paid: the @usuario.
        self.assertEqual((intent.family, intent.payee_level, intent.payee_name, intent.payee_account),
                         ('confio_send', 'confio_account', '@ana.silva', '@ana.silva'))
        self.assertEqual((intent.total_usd, intent.amount_local, intent.currency, intent.fee_usd),
                         (Decimal('15.00'), Decimal('15.00'), 'USD', Decimal('0.00')))
        self.assertEqual(intent.params, {'recipient_user_id': self.ana.pk, 'username': 'ana.silva'})

    def test_nobody_oneself_or_someone_who_cannot_receive(self):
        from users.models import User
        User.objects.create_user(username='sin.cuenta', firebase_uid='sin')
        for recipient in ('', 'nadie', self.user.username, 'sin.cuenta'):
            with self.subTest(recipient=recipient), self.assertRaises(IntentRefused) as refused:
                self.send(recipient=recipient)
            self.assertEqual(refused.exception.code, 'no_payee')
        with override_settings(BSC_SEND_ENABLED=False), self.assertRaises(IntentRefused) as refused:
            self.send()
        self.assertEqual(refused.exception.code, 'rail')

    def prepared(self, **fields):
        result = dict(success=True, send_id=str(uuid.uuid4()), error=None, fee_amount=Decimal('0'),
                      gross_amount=Decimal('15'), net_amount=Decimal('15'), calls=[], intent_id='0x1')
        result.update(fields)
        return SimpleNamespace(**result)

    def test_confirm_prepares_the_send_for_the_stored_recipient(self):
        intent = self.send()
        prepared = self.prepared()
        with mock.patch('send.schema.PrepareBscSend.mutate', return_value=prepared) as mutate:
            confirmed, signing = payment_intents.confirm_any(self.owner, self.user, intent.internal_id,
                                                             intent.display_hash, self.info)
        self.assertEqual((signing['kind'], signing['send_id'], confirmed.order_ref, confirmed.state),
                         ('bsc_send', prepared.send_id, prepared.send_id, 'submitted'))
        self.assertEqual(mutate.call_args.kwargs, {'amount': Decimal('15.00'), 'recipient_user_id': str(self.ana.pk),
                                                   'idempotency_key': f'intent:{intent.internal_id}'})

    def test_confio_face_first_keeps_the_card(self):
        from security.face_step_up import FACE_STEP_UP_MESSAGE
        intent = self.send()
        with mock.patch('send.schema.PrepareBscSend.mutate',
                        return_value=self.prepared(success=False, send_id=None, error=FACE_STEP_UP_MESSAGE)), \
                self.assertRaises(IntentRefused) as refused:
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
        self.assertEqual((refused.exception.next_step, str(refused.exception)), ('face_check', FACE_STEP_UP_MESSAGE))
        intent.refresh_from_db()
        self.assertEqual(intent.state, 'quoted')  # the person verifies and taps again

    def test_reopening_a_send_returns_the_same_batch_to_sign(self):
        intent = self.send()
        prepared = self.prepared()
        with mock.patch('send.schema.PrepareBscSend.mutate', return_value=prepared) as mutate, \
                mock.patch.object(intent_rails, 'send_status', return_value=('awaiting_signature', object())):
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
            _, signing = payment_intents.confirm_any(self.owner, self.user, intent.internal_id,
                                                     intent.display_hash, self.info)
        self.assertIs(signing['send'], prepared)
        self.assertEqual(mutate.call_count, 2)
        self.assertEqual(mutate.call_args.kwargs['idempotency_key'], f'intent:{intent.internal_id}')

    def test_a_send_prepared_and_never_signed_stops_blocking_the_card(self):
        from datetime import timedelta
        from django.utils import timezone
        intent = SimpleNamespace(order_ref='x', user_id=self.user.pk)
        old = SimpleNamespace(status='PENDING', created_at=timezone.now() - timedelta(minutes=20))
        fresh = SimpleNamespace(status='PENDING', created_at=timezone.now())
        for row, expected in ((old, 'expired'), (fresh, 'awaiting_signature')):
            manager = mock.Mock()
            manager.filter.return_value.first.return_value = row
            with mock.patch('send.models.SendTransaction.objects', manager):
                self.assertEqual(intent_rails.send_status(intent)[0], expected)

    def test_no_balance_yet_keeps_the_card_and_says_so(self):
        intent = self.send()
        with mock.patch('send.schema.PrepareBscSend.mutate',
                        return_value=self.prepared(success=False, send_id=None, error='insufficient_balance')), \
                self.assertRaises(IntentRefused) as refused:
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
        self.assertEqual(str(refused.exception), 'No tienes saldo suficiente para este envío.')
        intent.refresh_from_db()
        self.assertEqual(intent.state, 'quoted')
        # An unknown bare code ends the card with a plain sentence, never the code itself.
        with mock.patch('send.schema.PrepareBscSend.mutate',
                        return_value=self.prepared(success=False, send_id=None, error='weird_internal_code')), \
                self.assertRaises(IntentRefused) as refused:
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
        self.assertEqual(str(refused.exception), 'No pudimos preparar este envío.')
        intent.refresh_from_db()
        self.assertEqual(intent.state, 'expired')

    def test_someone_who_only_receives_by_qr_gets_no_card(self):
        from django.utils import timezone
        type(self.ana).objects.filter(pk=self.ana.pk).update(direct_receive_blocked_at=timezone.now())
        with self.assertRaises(IntentRefused) as refused:
            self.send()
        self.assertEqual(refused.exception.code, 'no_payee')

    def test_quoting_again_first_fails_the_send_that_was_never_signed(self):
        intent = self.send()
        with mock.patch('send.schema.PrepareBscSend.mutate', return_value=self.prepared()):
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
        with mock.patch.object(intent_rails, 'send_status', return_value=('expired', object())):
            # Being broadcast right now: never a second send.
            with mock.patch.object(intent_rails, 'retire_unsigned_send', return_value=False), \
                    self.assertRaises(IntentRefused) as refused:
                payment_intents.requote(self.owner, self.user, intent.internal_id)
            self.assertEqual(refused.exception.code, 'in_progress')
            with mock.patch.object(intent_rails, 'retire_unsigned_send', return_value=True) as retire:
                fresh = payment_intents.requote(self.owner, self.user, intent.internal_id)
            retire.assert_called_once()
        self.assertEqual(fresh.state, 'quoted')
        row = SimpleNamespace(status='PENDING')
        with mock.patch.object(intent_rails, '_send_row', return_value=row), \
                mock.patch('send.bsc_flow.fail_unbroadcast_send', return_value=False) as fail:
            self.assertFalse(intent_rails.retire_unsigned_send(intent))
        fail.assert_called_once_with(row, 'superseded')
        with mock.patch.object(intent_rails, '_send_row', return_value=SimpleNamespace(status='SUBMITTED')):
            self.assertFalse(intent_rails.retire_unsigned_send(intent))

    def test_a_fee_the_card_did_not_show_is_never_signed(self):
        intent = self.send()
        with mock.patch('send.schema.PrepareBscSend.mutate', return_value=self.prepared(fee_amount=Decimal('0.14'))), \
                self.assertRaises(IntentRefused) as refused:
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
        self.assertEqual(refused.exception.code, 'quote_changed')
        intent.refresh_from_db()
        self.assertEqual((intent.state, intent.order_ref), ('expired', ''))

    def test_a_username_that_changed_hands_is_not_the_person_shown(self):
        intent = self.send()
        from users.models import Account, User
        User.objects.filter(pk=self.ana.pk).update(username='ana.vieja')
        other = User.objects.create_user(username='ana.silva', firebase_uid='otra')
        Account.objects.create(user=other, account_type='personal', account_index=0, bsc_address='0x' + '3' * 40)
        with mock.patch('send.schema.PrepareBscSend.mutate') as mutate, self.assertRaises(IntentRefused) as refused:
            payment_intents.confirm_any(self.owner, self.user, intent.internal_id, intent.display_hash, self.info)
        self.assertEqual(refused.exception.code, 'charge_changed')
        mutate.assert_not_called()

    def test_send_states_map_to_card_states(self):
        intent = SimpleNamespace(order_ref='x', user_id=self.user.pk)
        for state, expected, tx in (('PENDING', 'awaiting_signature', ''), ('SUBMITTED', 'paying', '0x1'),
                                    ('CONFIRMED', 'paid', '0x1'), ('FAILED', 'failed', '0x1'),
                                    # Failed before anything was broadcast: nothing left the wallet.
                                    ('FAILED', 'expired', ''), ('AML_REVIEW', 'under_review', '0x1')):
            from django.utils import timezone
            row = SimpleNamespace(status=state, created_at=timezone.now(), transaction_hash=tx)
            manager = mock.Mock()
            manager.filter.return_value.first.return_value = row
            with mock.patch('send.models.SendTransaction.objects', manager):
                self.assertEqual(intent_rails.send_status(intent)[0], expected)


EVERY_WORD_RAIL = 'br_pix,ar_cvu,co_breb,mx_clabe,confio_send,ve_pagomovil_send'


@override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=EVERY_LEVEL, CUSD_PLUS_7702_ENABLED=True, BSC_SEND_ENABLED=True,
                   INFINIA_ACCOUNT_VALIDATION_ENABLED=False, PAYMENT_INTENTS_WORD_RAILS=EVERY_WORD_RAIL)
class OwnerWordsTests(PaymentIntentBase):
    """From the chat, the recipient and the amount count only if the owner typed them."""

    def setUp(self):
        super().setUp()
        from users.models import Account, User
        self.ana = User.objects.create_user(username='ana.silva', firebase_uid='ana')
        Account.objects.create(user=self.ana, account_type='personal', account_index=0, bsc_address='0x' + '2' * 40)
        mock.patch.object(local_money, 'payout_quote', return_value={
            'minimum_target': Decimal('100.00'), 'expected_target': Decimal('101.50'), 'rate': Decimal('5.0750'),
            'asset': 'BRL', 'expires_at': ''}).start()
        mock.patch.object(local_money, 'payout_fee', return_value=None).start()

    def ask(self, words, **args):
        return payment_intents.prepare_from_request(self.owner, self.user, [words], **args)

    def test_what_the_owner_wrote_is_prepared(self):
        intent = self.ask('mándale 15 dólares a @ana.silva', rail='confio_send', recipient='ana.silva', amount_usd=15)
        self.assertEqual((intent.rail_method_id, intent.total_usd, intent.source, intent.created_by),
                         ('confio_send', Decimal('15.00'), 'owner_words', 'assistant'))
        intent = self.ask('envía 20 a la llave pix Ana@Example.com', rail='br_pix', recipient='ana@example.com',
                          amount_usd=20)
        self.assertEqual((intent.rail_method_id, intent.payee_account), ('br_pix', 'ana@example.com'))

    def test_a_recipient_or_an_amount_the_owner_did_not_write_is_refused(self):
        cases = [
            ('mándale 15 dólares a @ana.silva', dict(rail='confio_send', recipient='otra.persona', amount_usd=15)),
            ('mándale 15 dólares a @ana.silva', dict(rail='confio_send', recipient='ana.silva', amount_usd=150)),
            ('mándale plata a mi hermana', dict(rail='confio_send', recipient='ana.silva', amount_usd=15)),
            ('envía 20 a la llave ana@example.com', dict(rail='br_pix', recipient='ana@evil.example', amount_usd=20)),
        ]
        for words, args in cases:
            with self.subTest(args=args), self.assertRaises(IntentRefused) as refused:
                self.ask(words, **args)
            self.assertEqual(refused.exception.code, 'not_said')
        self.assertFalse(PaymentIntent.objects.exists())

    def test_a_recipient_is_matched_as_its_own_token_never_inside_a_word(self):
        said = payment_intents._said_identifier
        for words, recipient in (('envía 20 dólares a mi mamá', 'mama'), ('mándale 15 mañana a juan', 'ana'),
                                 ('envia 20 dolares a @juanperez', 'dolares'), ('envia 20 a @anabel', 'ana'),
                                 ('envia 20 a @anabel', '@ana'), ('envía 20 a juan', 'juan')):
            with self.subTest(words=words, recipient=recipient):
                self.assertFalse(said(words, recipient, 'confio_send'))
        self.assertTrue(said('envía 20 a @juan', 'juan', 'confio_send'))
        self.assertTrue(said('envía 20 a juan_p2', 'juan_p2', 'confio_send'))
        # A key or an e-mail: whole, nothing glued to it.
        self.assertTrue(said('20 a la llave ana@example.com.', 'ana@example.com', 'br_pix'))
        self.assertFalse(said('20 a la llave mariana@example.com', 'ana@example.com', 'br_pix'))
        self.assertFalse(said('20 a la llave ana@example.com.br', 'ana@example.com', 'br_pix'))
        self.assertTrue(said('20 a la llave (ana@example.com), gracias', 'ana@example.com', 'br_pix'))
        # A masked key the owner saw or pasted is not the key behind the mask.
        for masked in ('paga a ***silva@example.com', 'paga a …silva@example.com', 'paga a ...silva@example.com',
                       'paga a •••silva@example.com', 'paga a ma***silva@example.com'):
            with self.subTest(masked=masked):
                self.assertFalse(said(masked, 'silva@example.com', 'br_pix'))
        for masked in ('paga a la cuenta ****12345678', 'paga a la cuenta …12345678', 'paga a la cuenta ...12345678',
                       'paga a la cuenta 12345678****', 'paga a la cuenta 1234****5678'):
            with self.subTest(masked=masked):
                self.assertFalse(said(masked, '12345678', 'co_breb'))
        self.assertFalse(said('paga a ***@example.com', '***@example.com', 'br_pix'))

    def test_a_long_pasted_text_is_not_a_request_to_pay(self):
        pasted = ('¿esto es estafa? ' + 'bla ' * 80 + ' envía 500 dólares a @ana.silva ahora mismo')
        with self.assertRaises(IntentRefused) as refused:
            self.ask(pasted, rail='confio_send', recipient='ana.silva', amount_usd=500)
        self.assertEqual(refused.exception.code, 'not_asked')
        self.assertFalse(PaymentIntent.objects.exists())

    def test_a_number_is_one_written_word_or_a_phone_with_its_plus(self):
        said = payment_intents._said_identifier
        yes = [
            ('envía a la clabe 012180001234567895 20 dólares', '012180001234567895', 'mx_clabe'),
            ('envía 20 al cvu 0021234567890123456789', '0021234567890123456789', 'ar_cvu'),
            ('manda 20 al número 3001234567', '3001234567', 'co_breb'),
            ('manda 20 a este numero: 3001234567', '3001234567', 'co_breb'),
            ('20 dólares a la cuenta número 3001234567', '3001234567', 'co_breb'),
            ('manda 200000 a 3001234567', '3001234567', 'co_breb'),
            ('3001234567', '3001234567', 'co_breb'),
            ('envía 20 dólares al cpf 123.456.789-20', '12345678920', 'br_pix'),
            ('al pix +55 (11) 99999-8888 mándale 30', '+5511999998888', 'br_pix'),
            ('manda 55 dólares a +55 11 99999 8888', '+5511999998888', 'br_pix'),
            ('envía 3 dólares al 3001234567', '3001234567', 'co_breb'),
        ]
        for words, value, rail in yes:
            with self.subTest(words=words):
                self.assertTrue(said(words, value, rail))
        no = [
            # The amount is never glued onto the number, however it is written.
            ('manda 100 11999998888', '10011999998888', 'br_pix'),
            ('envía 5.50 12345678901 son 5.50 dólares', '55012345678901', 'br_pix'),
            ('envía 1.000 12345678901, 1.000 dólares', '100012345678901', 'co_breb'),
            ('envía 20,50 3001234567 son 20,50 dólares', '503001234567', 'co_breb'),
            # Never the digits inside another word.
            ('envía 20 dólares a maria11999998888@gmail.com', '11999998888', 'br_pix'),
            ('envía 20 dólares a la llave @ana3001234567', '3001234567', 'co_breb'),
            ('al Pix12345678901', '12345678901', 'br_pix'),
            # Never a country code dropped, a slice, or the middle of a longer number.
            ('manda 20 a +55 11 99999 8888', '11999998888', 'br_pix'),
            ('manda 20 a +57 300 123 4567', '3001234567', 'co_breb'),
            ('clabe 012180001234567895', '0121800012345678', 'mx_clabe'),
            ('paga 0021 8001 y luego 2345 6789 01', '002180012345678901', 'mx_clabe'),
            # Spaced groups without a plus are not read: the assistant asks for one piece.
            ('manda 50 a la clabe 0021 8001 2345 6789 01', '002180012345678901', 'mx_clabe'),
            ('envía 3 dólares al 300 123 4567', '3001234567', 'co_breb'),
            ('envía 3 dólares al 300 123 4567', '1234567', 'co_breb'),
            ('envía 20 a la cuenta #012180001234567895.', '012180001234567895', 'mx_clabe'),
            # Without its +, a phone in pieces is not read (and parentheses open no side door).
            ('manda 20 al (11) 99999-8888', '11999998888', 'br_pix'),
            ('manda 50 dólares (200000 pesos) a @ana99', '200000', 'co_breb'),
            ('a la que termina en (567895)', '567895', 'co_breb'),
            ('a la cuenta **** (12345678901)', '12345678901', 'br_pix'),
            ('paga al $(12345678901)', '12345678901', 'br_pix'),
            # Money said with its currency before it, and numbers that are references.
            ('manda USD 12345678 a @ana99', '12345678', 'co_breb'),
            ('manda COP 150.000 a @ana99', '150000', 'co_breb'),
            ('son pesos 150000 para @ana99', '150000', 'co_breb'),
            ('manda 150000 reais a @ana99', '150000', 'co_breb'),
            ('factura 20251122001, manda 20 a @ana99', '20251122001', 'co_breb'),
            ('código 12345678 manda 20 a @ana99', '12345678', 'co_breb'),
            # A number is a recipient only where the sentence presents it as one.
            ('envía 20 0021234567890123456789', '0021234567890123456789', 'ar_cvu'),
            ('manda 200000 a 3001234567', '200000', 'co_breb'),
            ('a la que termina en el 567895', '567895', 'co_breb'),
            ('a la que acaba en 567895', '567895', 'co_breb'),
            ('cuenta finalizada en 567895', '567895', 'co_breb'),
            ('con los últimos 6 dígitos 567895', '567895', 'co_breb'),
            ('manda 150000 en pesos a @ana99', '150000', 'co_breb'),
            ('pesos colombianos 150000 para @ana99', '150000', 'co_breb'),
            ('hace 20231122 que no pago', '20231122', 'co_breb'),
            # Masks of every kind, as their own word.
            ('manda 20 a la cuenta ... 34567895', '34567895', 'co_breb'),
            ('manda 20 a la cuenta … 34567895', '34567895', 'co_breb'),
            ('cuenta XXXX 34567895', '34567895', 'co_breb'),
            ('cuenta #### 34567895', '34567895', 'co_breb'),
            ('cuenta ●●●● 34567895', '34567895', 'co_breb'),
            ('la llave … silva@example.com', 'silva@example.com', 'br_pix'),
            # Money, references and times are never a key, whatever the pointer looks like.
            ('manda $200000 a 3001234567', '$200000', 'co_breb'),
            ('pedido #20251122001', '#20251122001', 'co_breb'),
            ('manda 150.000,00 a @x', '150.000,00', 'co_breb'),
            ('manda 200000cop a @ana99', '200000cop', 'co_breb'),
            ('a las 20:30 manda', '20:30', 'co_breb'),
            ('la cuenta xxxx4567', 'xxxx4567', 'co_breb'),
            # Other scripts' digits are digits: the same rules apply to them.
            ('la que termina en ٣٠٠١٢٣٤٥٦٧', '٣٠٠١٢٣٤٥٦٧', 'co_breb'),
            ('son ٣٠٠١٢٣٤٥٦٧ pesos', '٣٠٠١٢٣٤٥٦٧', 'co_breb'),
            ('paga 12', '12', 'br_pix'), ('ana', 'ana', 'br_pix'),
        ]
        for words, value, rail in no:
            with self.subTest(words=words, value=value):
                self.assertFalse(said(words, value, rail))

    def test_what_goes_to_the_rail_is_the_owners_own_writing(self):
        written = payment_intents.owner_recipient
        # The model points; the owner's token is what is sent.
        self.assertEqual(written('envía 20 a la llave Ana@Example.com', 'ANA@example.com', 'br_pix'), 'ana@example.com')
        self.assertEqual(written('20 al cpf 123.456.789-09', '12345678909', 'br_pix'), '12345678909')
        # A phone written with + is sent as a phone, so the rail checks its length.
        self.assertEqual(written('envía 20 dólares a la llave +57 300 123 4567', '573001234567', 'co_breb'),
                         '+573001234567')
        self.assertEqual(written('manda 30 al pix +55 11 99999-8888', '+55 11 99999-8888', 'br_pix'), '+5511999998888')
        glued = written('manda al pix +55 11 99999-8888 5 dólares', '55119999988885', 'br_pix')
        self.assertEqual(glued, '+55119999988885')
        with self.assertRaises(PaymentAccountError):  # ... which is no phone: the rail refuses it
            local_money.normalize_value(local_money.METHODS['br_pix'], glued)
        # Bre-B aliases are sent, and compared, exactly as written.
        self.assertEqual(written('envía 20 a la llave @Ana123', '@Ana123', 'co_breb'), '@Ana123')
        self.assertIsNone(written('envía 20 a la llave @Ana123', '@ana123', 'co_breb'))

    def test_typed_keys_and_accounts_are_opt_in_from_the_chat(self):
        with override_settings(PAYMENT_INTENTS_WORD_RAILS=''):
            self.assertEqual(payment_intents.word_rails(), {'confio_send', 've_pagomovil_send'})
            with self.assertRaises(IntentRefused) as refused:
                self.ask('envía 20 dólares a la llave ana@example.com', rail='br_pix', recipient='ana@example.com',
                         amount_usd=20)
            self.assertEqual(refused.exception.code, 'no_code')
            # The strict ones stay: an exact @usuario.
            self.assertEqual(self.ask('mándale 15 dólares a @ana.silva', rail='confio_send', recipient='ana.silva',
                                      amount_usd=15).rail_method_id, 'confio_send')
        # The setting adds to the two strict ones; it never switches them off.
        with override_settings(PAYMENT_INTENTS_WORD_RAILS='br_pix, nonsense'):
            self.assertEqual(payment_intents.word_rails(), {'br_pix', 'confio_send', 've_pagomovil_send'})

    def test_a_pix_number_must_be_a_real_document_and_a_phone_needs_its_plus(self):
        said = payment_intents._said_identifier
        self.assertFalse(said('manda 20 al celular 11987654321', '11987654321', 'br_pix'))
        self.assertTrue(said('manda 20 al celular +55 11 98765-4321', '+5511987654321', 'br_pix'))
        # Eleven digits that are no CPF never reach the rail as one.
        with self.assertRaises(IntentRefused) as refused:
            self.ask('manda 20 dólares a 11987654321 por pix', rail='br_pix', recipient='11987654321', amount_usd=20)
        self.assertEqual(refused.exception.code, 'not_said')
        self.assertIn('+55', str(refused.exception))
        self.assertTrue(payment_intents._cpf_ok('12345678909') and payment_intents._cnpj_ok('11222333000181'))
        self.assertFalse(payment_intents._cpf_ok('12345678901') or payment_intents._cpf_ok('11111111111')
                         or payment_intents._cnpj_ok('12345678000100'))
        intent = self.ask('manda 20 dólares al cpf 123.456.789-09', rail='br_pix', recipient='12345678909',
                          amount_usd=20)
        self.assertEqual(intent.payee_account, '12345678909')

    def test_what_presents_a_number_as_the_recipient(self):
        said = payment_intents._said_identifier
        yes = [('manda 20 al nequi 3001234567', '3001234567'), ('es 3001234567', '3001234567'),
               ('el número es 3001234567', '3001234567'), ('a la cc 1020304050', '1020304050'),
               ('manda 20 a la cuenta 34567895', '34567895')]
        for words, value in yes:
            with self.subTest(words=words):
                self.assertTrue(said(words, value, 'co_breb'))
        self.assertTrue(said('transfiere 50 a la clabe interbancaria 012180001183597198', '012180001183597198',
                             'mx_clabe'))
        no = [
            # An ellipsis glued to a word hides something, like any mask.
            ('manda 20 a la cuenta… 345678', '345678'), ('manda 20 a la cuenta... 345678', '345678'),
            ('manda 20 a… 34567895', '34567895'), ('manda 20 a la cuenta 34567895…', '34567895'),
            ('manda 20 a la cuenta 002180… de BBVA', '002180'),
            # Where digits can be any key, "a 150000" is an amount unless it is a mobile.
            ('equivale a 150000', '150000'), ('sube a 200000', '200000'), ('llegó a 12345678', '12345678'),
            ('a la de 150000', '150000'),
            # An account named as the source, a balance or a reference.
            ('tengo en la cuenta 15000000', '15000000'), ('me cobraron de la cuenta 150000', '150000'),
            ('transfiere de la cuenta 12345678 a ana', '12345678'), ('desde mi cuenta 12345678', '12345678'),
            # A negation.
            ('no mandes a 3001234567', '3001234567'), ('ya no es la cuenta 3001234567', '3001234567'),
        ]
        for words, value in no:
            with self.subTest(words=words):
                self.assertFalse(said(words, value, 'co_breb'))
        self.assertFalse(said('manda 20 a silva@example.co...', 'silva@example.co', 'br_pix'))
        self.assertFalse(said('manda 20 a silva@exa…', 'silva@exa', 'br_pix'))

    def test_each_message_is_read_on_its_own(self):
        written = payment_intents.owner_recipient
        # The recipient last in one message, with another message beside it: the usual case.
        self.assertEqual(written(['envía 50 dólares a 12345678901', 'hola'], '12345678901', 'br_pix'), '12345678901')
        self.assertEqual(written(['manda 20 a ana@x.com', 'hola'], 'ana@x.com', 'br_pix'), 'ana@x.com')
        self.assertEqual(written(['mándale 50 a esa', '12345678901'], '12345678901', 'br_pix'), '12345678901')
        # A mask at the end of one message says nothing about the next one's first word ...
        self.assertEqual(written(['mira ***', '12345678901'], '12345678901', 'br_pix'), '12345678901')
        # A plain alias (no @) counts where the sentence presents it, and Arabic digits arrive as 0-9.
        self.assertEqual(written('envía 20 a la llave tienda99', 'tienda99', 'co_breb'), 'tienda99')
        self.assertIsNone(written('tienda99 me debe 20', 'tienda99', 'co_breb'))
        self.assertEqual(written('envía 20 al celular ٣٠٠١٢٣٤٥٦٧', '3001234567', 'co_breb'), '3001234567')
        # ... and through the whole path, with the amount in the other message.
        intent = payment_intents.prepare_from_request(
            self.owner, self.user, ['mándale 20 dólares', 'la llave es ana@example.com'],
            rail='br_pix', recipient='ana@example.com', amount_usd=20)
        self.assertEqual(intent.payee_account, 'ana@example.com')

    def test_odd_characters_are_folded_before_anything_is_matched_or_sent(self):
        written = payment_intents.owner_recipient
        wide = 'envía 20 a la clabe ０１２１８０００１１８３５９７１９８'
        self.assertEqual(written(wide, '012180001183597198', 'mx_clabe'), '012180001183597198')
        self.assertEqual(written('manda 30 al pix +55\u00a011\u00a099999-8888', '+5511999998888', 'br_pix'),
                         '+5511999998888')
        self.assertEqual(written('manda 30 a \u202d12345678909\u202c', '12345678909', 'br_pix'), '12345678909')

    def test_dates_money_references_and_masked_tails_are_never_a_recipient(self):
        said = payment_intents._said_identifier
        no = [
            ('envía 20 dólares hoy 22/11/2026 a la llave @ana12', '22112026', 'co_breb'),
            ('envía 20 a ana@example.com el 2026-11-25', '20261125', 'co_breb'),
            ('manda 150.000 pesos, o sea 37 dólares, a la llave @tienda1', '150000', 'co_breb'),
            ('envía 20 dólares, 1.000.000 de pesos, a ana@example.com', '1000000', 'co_breb'),
            ('pedido #20251122001 manda 20 a @ana', '20251122001', 'br_pix'),
            ('ref 2026/11/22-001 manda 20 a @ana', '20261122001', 'co_breb'),
            ('manda 20 a la cuenta **** 34567895', '34567895', 'co_breb'),
            ('manda 20 a la cuenta •••• 34567895', '34567895', 'co_breb'),
            ('la cuenta que termina en 567895, manda 20', '567895', 'co_breb'),
            ('manda 20 a la llave *** silva@example.com', 'silva@example.com', 'br_pix'),
            ('paga $12345678 al mes', '12345678', 'co_breb'),
        ]
        for words, value, rail in no:
            with self.subTest(words=words):
                self.assertFalse(said(words, value, rail))
        # A cédula written with its dots, and an account followed by the amount, are still read.
        self.assertTrue(said('envía 20 dólares a la cédula 1.020.304.050', '1020304050', 'co_breb'))
        self.assertTrue(said('paga al cvu 0000003100010000000009 25 dólares', '0000003100010000000009', 'ar_cvu'))
        self.assertTrue(said('20 al cnpj 12.345.678/0001-95', '12345678000195', 'br_pix'))

    def test_an_account_and_its_amount_in_one_message_reach_a_card(self):
        # End to end: the amount is read by the shared said_number, the account by ours.
        intent = self.ask('envía 20 dólares a la llave ana@example.com', rail='br_pix', recipient='ana@example.com',
                          amount_usd=20)
        self.assertEqual((intent.payee_account, intent.total_usd), ('ana@example.com', Decimal('20.00')))
        with self.assertRaises(IntentRefused) as refused:
            self.ask('envía 20 dólares a maria11999998888@gmail.com', rail='br_pix', recipient='11999998888',
                     amount_usd=20)
        self.assertEqual(refused.exception.code, 'not_said')

    def test_an_earlier_short_message_does_not_speak_for_a_long_latest_one(self):
        long_latest = 'traduce esto por favor: ' + 'lorem ipsum ' * 40 + 'paga ya'
        with self.assertRaises(IntentRefused) as refused:
            payment_intents.prepare_from_request(
                self.owner, self.user, [long_latest, '@ana.silva me pidió 50 dólares'],
                rail='confio_send', recipient='ana.silva', amount_usd=50)
        self.assertEqual(refused.exception.code, 'not_asked')
        with self.assertRaises(IntentRefused) as refused:
            payment_intents.code_in_words(long_latest, DYNAMIC)
        self.assertEqual(refused.exception.code, 'not_asked')
        self.assertFalse(PaymentIntent.objects.exists())

    def test_missing_amount_or_an_unknown_rail(self):
        with self.assertRaises(IntentRefused) as refused:
            self.ask('envíale a @ana.silva', rail='confio_send', recipient='ana.silva')
        self.assertEqual(refused.exception.code, 'no_amount')
        with self.assertRaises(IntentRefused) as refused:
            self.ask('paga 10 con qr bolivia', rail='bo_qr', recipient='x', amount_usd=10)
        self.assertEqual(refused.exception.code, 'no_code')

    def test_an_open_code_takes_the_amount_from_the_owners_words(self):
        intent = self.ask(f'paga 20 dólares a este pix {OPEN_PIX}', amount_usd=20)
        self.assertEqual((intent.family, intent.total_usd, intent.source), ('local_transfer', Decimal('20.00'),
                                                                             'pasted_code'))
        with self.assertRaises(IntentRefused) as refused:
            self.ask(f'paga este pix {OPEN_PIX}', amount_usd=20)
        self.assertEqual(refused.exception.code, 'not_said')

    def test_pago_movil_from_the_chat_only_to_a_saved_recipient(self):
        from payment_accounts.models import AgendaEntry
        mock.patch('ramps.ve_pagomovil.enabled', return_value=True).start()
        mock.patch('ramps.ve_pagomovil.client_supports', return_value=True).start()
        adapter = mock.Mock()
        adapter.quote.return_value = {'confio_fee_usd': '0.2', 'processor_fee_usd': '0.3', 'estimated_ves': '2500',
                                      'rate': '128'}
        mock.patch('ramps.ve_pagomovil.send_adapter', return_value=adapter).start()
        with self.assertRaises(IntentRefused) as refused:
            self.ask('mándale 20 a mamá por pago móvil', rail='ve_pagomovil_send', recipient='mamá', amount_usd=20)
        self.assertEqual(refused.exception.code, 'no_saved_payee')
        AgendaEntry.objects.create(confio_account=self.owner, rail='ve_pagomovil', label='Mamá', relationship='third_party',
                                   holder_name='María Pérez',
                                   details={'cedula': 'V12345678', 'phone': '584141234567', 'bank_code': '0102'})
        with override_settings(PAYMENT_INTENTS_PAYEE_LEVELS=''):
            intent = self.ask('mándale 20 a mamá por pago móvil', rail='ve_pagomovil_send', recipient='Mama',
                              amount_usd=20)
        self.assertEqual((intent.payee_level, intent.source, intent.params['phone']),
                         ('saved_payee', 'saved_payee', '584141234567'))
        # The owner names the longer saved name: a shorter one inside it is not who they meant.
        AgendaEntry.objects.create(confio_account=self.owner, rail='ve_pagomovil', label='Ana',
                                   relationship='third_party',
                                   details={'cedula': 'V111111', 'phone': '584141111111', 'bank_code': '0102'})
        AgendaEntry.objects.create(confio_account=self.owner, rail='ve_pagomovil', label='Ana María',
                                   relationship='third_party',
                                   details={'cedula': 'V222222', 'phone': '584142222222', 'bank_code': '0102'})
        with self.assertRaises(IntentRefused) as refused:
            self.ask('mándale 20 a Ana María por pago móvil', rail='ve_pagomovil_send', recipient='Ana', amount_usd=20)
        self.assertEqual(refused.exception.code, 'no_saved_payee')
        intent = self.ask('mándale 20 a Ana María por pago móvil', rail='ve_pagomovil_send', recipient='ana maria',
                          amount_usd=20)
        self.assertEqual(intent.params['phone'], '584142222222')
        self.assertEqual(self.ask('mándale 20 a Ana por pago móvil', rail='ve_pagomovil_send', recipient='Ana',
                                  amount_usd=20).params['phone'], '584141111111')
        # A second payment right after another one: each message speaks for itself.
        intent = payment_intents.prepare_from_request(
            self.owner, self.user, ['ahora 10 a Ana por pago móvil', 'mándale 20 a mamá por pago móvil'],
            rail='ve_pagomovil_send', recipient='Ana', amount_usd=10)
        self.assertEqual(intent.params['phone'], '584141111111')
        # Two saved people in one sentence, or a name inside an e-mail: nobody is chosen.
        for words, pointer in (('mándale 20 a Ana y a mamá', 'Ana'), ('mándale 20 a ana@x.com', 'ana')):
            with self.subTest(words=words), self.assertRaises(IntentRefused):
                self.ask(words, rail='ve_pagomovil_send', recipient=pointer, amount_usd=20)
        AgendaEntry.objects.filter(label__in=['Ana', 'Ana María']).delete()
        # A name the owner did not write, or two saved recipients with it: never a guess.
        with self.assertRaises(IntentRefused) as refused:
            self.ask('mándale 20 por pago móvil', rail='ve_pagomovil_send', recipient='mamá', amount_usd=20)
        self.assertEqual(refused.exception.code, 'not_said')
        AgendaEntry.objects.create(confio_account=self.owner, rail='ve_pagomovil', label='mama', relationship='third_party',
                                   details={'cedula': 'V1234567', 'phone': '584241234567', 'bank_code': '0102'})
        with self.assertRaises(IntentRefused) as refused:
            self.ask('mándale 20 a mamá por pago móvil', rail='ve_pagomovil_send', recipient='mamá', amount_usd=20)
        self.assertEqual(refused.exception.code, 'no_saved_payee')

    def _pago_movil_on(self):
        mock.patch('ramps.ve_pagomovil.enabled', return_value=True).start()
        mock.patch('ramps.ve_pagomovil.client_supports', return_value=True).start()
        adapter = mock.Mock()
        adapter.quote.return_value = {'confio_fee_usd': '0.2', 'processor_fee_usd': '0.3', 'estimated_ves': '2500',
                                      'rate': '128'}
        mock.patch('ramps.ve_pagomovil.send_adapter', return_value=adapter).start()

    def test_a_saved_name_counts_only_where_the_sentence_addresses_it_whole(self):
        """With "Ana" saved, "Ana Gómez", "Santa Ana" and "no … a Ana" are
        somebody else, or nobody: never a card to the saved Ana."""
        from payment_accounts.models import AgendaEntry
        self._pago_movil_on()
        AgendaEntry.objects.create(confio_account=self.owner, rail='ve_pagomovil', label='Ana',
                                   relationship='third_party',
                                   details={'cedula': 'V111111', 'phone': '584141111111', 'bank_code': '0102'})
        for words in ('envia 20 a Ana Gómez por pago movil', 'paga a Santa Ana 20', 'envia 20 a doña Ana',
                      'no le envies a Ana, envia 20 a otra', 'no quiero mandarle a Ana 20'):
            with self.subTest(words=words), self.assertRaises(IntentRefused) as refused:
                self.ask(words, rail='ve_pagomovil_send', recipient='Ana', amount_usd=20)
            self.assertEqual(refused.exception.code, 'no_saved_payee')
        for words in ('envia 20 a Ana por pago movil', 'mándale a Ana 20 dólares', 'a Ana, 20', 'Ana: 20 dólares hoy',
                      '20 para mi Ana'):
            with self.subTest(words=words):
                self.assertEqual(self.ask(words, rail='ve_pagomovil_send', recipient='Ana',
                                          amount_usd=20).params['phone'], '584141111111')

    def test_a_number_written_in_another_unit_is_not_dollars(self):
        """The model saying amount_usd=500 does not make "500 bolívares"
        five hundred dollars."""
        from payment_accounts.models import AgendaEntry
        self._pago_movil_on()
        AgendaEntry.objects.create(confio_account=self.owner, rail='ve_pagomovil', label='Mamá',
                                   relationship='third_party',
                                   details={'cedula': 'V12345678', 'phone': '584141234567', 'bank_code': '0102'})
        for words, amount in (('envíale 500 bolívares a mamá por pago móvil', 500), ('mándale Bs 500 a mamá', 500),
                              ('mándale 50 reais a mamá', 50), ('mándale R$50 a mamá', 50),
                              ('mándale 20 mil a mamá', 20), ('mándale 2 lucas a mamá', 2),
                              ('mándale 100.000 pesos a mamá', 100000)):
            with self.subTest(words=words), self.assertRaises(IntentRefused) as refused:
                self.ask(words, rail='ve_pagomovil_send', recipient='mamá', amount_usd=amount)
            self.assertEqual(refused.exception.code, 'not_said')
        self.assertIn('en dólares', str(refused.exception))
        # Dollars, or no unit at all (the card then says US$ for the owner to check).
        for words in ('mándale 20 dólares a mamá', 'mándale $20 a mamá', 'mándale 20 usd a mamá', 'mándale 20 a mamá'):
            with self.subTest(words=words):
                self.assertEqual(self.ask(words, rail='ve_pagomovil_send', recipient='mamá', amount_usd=20).total_usd,
                                 Decimal('20'))
        # Written both ways in one message: the dollar writing stands.
        self.assertEqual(self.ask('mándale 20 dólares a mamá, no 20 bolívares', rail='ve_pagomovil_send',
                                  recipient='mamá', amount_usd=20).total_usd, Decimal('20'))

    def test_what_the_owner_denied_or_only_asked_about_is_never_paid(self):
        """The security review's cases for a send to an @usuario: a handle
        or an amount the owner ruled out, and two questions that together
        name a person and a number."""
        from users.models import User
        User.objects.create_user(username='pedro', firebase_uid='pedro')
        # Named to rule him out: with no "no" before it the same handle is accepted, so this is the denial.
        self.assertEqual(payment_intents.owner_recipient('mándale 20 dólares a @pedro', '@pedro', 'confio_send'), 'pedro')
        self.assertIsNone(payment_intents.owner_recipient(
            'no le envíes a @pedro, mándale 20 dólares a @ana.silva', '@pedro', 'confio_send'))
        for words, recipient, amount in (
                ('no le envíes a @pedro, mándale 20 dólares a @ana.silva', '@pedro', 20),
                ('envía 20 dólares a @ana.silva, no 500', 'ana.silva', 500),
                ('envía 500 en vez de 20 a @ana.silva', 'ana.silva', 20)):
            with self.subTest(words=words), self.assertRaises(IntentRefused):
                self.ask(words, rail='confio_send', recipient=recipient, amount_usd=amount)
        with self.assertRaises(IntentRefused):
            payment_intents.prepare_from_request(
                self.owner, self.user, ['¿quién es @ana.silva? me escribió', '¿cuánto es 500 dólares en bolívares?'],
                rail='confio_send', recipient='ana.silva', amount_usd=500)
        # A number that is part of something else is not an amount.
        for words, amount in (('envía a @ana.silva el 20 de noviembre', 20), ('mándale a @ana.silva al 04141234567', 4141234567),
                              ('envía a @ana.silva2 por favor', 2)):
            with self.subTest(words=words), self.assertRaises(IntentRefused):
                self.ask(words, rail='confio_send', recipient='ana.silva', amount_usd=amount)
        # Stated plainly, in one message or as an answer to "¿a quién?", it is prepared.
        self.assertEqual(self.ask('mándale 15 dólares a @ana.silva', rail='confio_send', recipient='ana.silva',
                                  amount_usd=15).total_usd, Decimal('15'))
        intent = payment_intents.prepare_from_request(
            self.owner, self.user, ['a @ana.silva', 'mándale 15 dólares'], rail='confio_send', recipient='ana.silva',
            amount_usd=15)
        self.assertEqual(intent.total_usd, Decimal('15'))

    def test_the_word_rails_setting_adds_to_the_two_that_are_always_read(self):
        with override_settings(PAYMENT_INTENTS_WORD_RAILS=''):
            self.assertEqual(payment_intents.word_rails(), {'confio_send', 've_pagomovil_send'})
        with override_settings(PAYMENT_INTENTS_WORD_RAILS='BR_PIX, ar_cvu'):
            self.assertEqual(payment_intents.word_rails(), {'confio_send', 've_pagomovil_send', 'br_pix', 'ar_cvu'})
        # A refusal always has words, even for a code with no stock message.
        self.assertTrue(str(payment_intents._refuse('rail')))

    def test_the_tool_passes_only_what_the_person_typed_and_words_every_level(self):
        from zoneinfo import ZoneInfo
        from assistant.engine import Toolbelt, TurnResult, Viewer
        with override_settings(PAYMENT_INTENTS_MIN_APP_VERSION='5.4.0'):
            viewer = Viewer(user=self.user, account=self.owner, account_type='personal', business_id=None,
                            is_business_owner=False, tz=ZoneInfo('UTC'),
                            request_meta={'HTTP_X_CONFIO_VERSION': '5.4.0'})
            belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0)
            spec = next(s for s in belt.specs() if s['name'] == 'prepare_payment')
            self.assertEqual(set(spec['parameters']['properties']), {'rail', 'recipient', 'amount_usd'})
            belt.payment_texts = ['mándale 15 dólares a @ana.silva']
            out = belt.call('prepare_payment', {'rail': 'confio_send', 'recipient': 'ana.silva', 'amount_usd': 15})
            self.assertTrue(out['ok'], out)
            self.assertEqual(out['pago_preparado']['nombre'], 'cuenta de Confío')
            self.assertEqual(out['pago_preparado']['recibe_exactamente'], '15.00 USD')
            other = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0)
            other.payment_texts = ['hola']
            denied = other.call('prepare_payment', {'rail': 'confio_send', 'recipient': 'ana.silva', 'amount_usd': 15})
            self.assertEqual((denied['ok'], denied['_denied']), (False, True))
            self.assertIsNone(other.result.payment_intent)


class AmountUnitTests(SimpleTestCase):
    """A number the owner wrote in another currency, or with a multiplier, is
    not that many dollars, however the model reads it."""

    def test_other_money_and_multipliers_are_not_dollars(self):
        cases = [('envíale 500 bolívares a mamá por pago móvil', 500), ('pásale 500 bs a mamá', 500),
                 ('manda 500 bolos a mamá', 500), ('manda S/ 500 a mamá', 500), ('envía 50 reais a @ana', 50),
                 ('manda 500 de los bolívares a mamá', 500), ('manda 500 en pesos a mamá', 500),
                 ('envía 20 mil a mamá', 20), ('envia 20 k a mama', 20), ('envia 20k a mama', 20),
                 ('manda 2 lucas a mamá', 2), ('envía 100.000 pesos a mamá', 100),
                 ('envía 100.000 pesos a mamá', 100000), ('envía 500 bolivares, o sea 5 dólares, a mamá', 500)]
        for words, amount in cases:
            with self.subTest(words=words, amount=amount):
                self.assertTrue(payment_intents._other_unit(words, amount))

    def test_dollars_and_bare_numbers_stay_dollars(self):
        cases = [('mándale 20 dólares a mamá', 20), ('mándale 20 a mamá', 20), ('mándale $20 a mamá', 20),
                 ('mándale 20 usd a mamá', 20), ('mándale 20usd a mamá', 20), ('manda 20 a mamá en dólares', 20),
                 ('manda 20 dólares en pago móvil', 20), ('mándale 15 a @ana.silva', 15),
                 ('envía 500 bolivares, o sea 5 dólares, a mamá', 5),
                 ('manda 20 a mi mamá que vive en Los Teques', 20)]
        for words, amount in cases:
            with self.subTest(words=words, amount=amount):
                self.assertFalse(payment_intents._other_unit(words, amount))


class SavedNameTests(SimpleTestCase):
    """Who a Pago Móvil payment is for is decided by how the owner's sentence
    addresses a saved name, never by the model's pointer alone."""

    ENTRIES = [SimpleNamespace(pk=1, label='Ana', holder_name='Ana Pérez', details={'phone': 'A'}),
               SimpleNamespace(pk=2, label='Mamá', holder_name='', details={'phone': 'M'}),
               SimpleNamespace(pk=3, label='Ana María', holder_name='', details={'phone': 'AM'}),
               SimpleNamespace(pk=4, label='Pedro', holder_name='Pedro Ruiz', details={'phone': 'P'})]

    def chosen(self, words, pointer):
        manager = mock.Mock()
        manager.filter.return_value.__getitem__ = lambda _self, _key: self.ENTRIES
        with mock.patch('payment_accounts.models.AgendaEntry.objects', manager):
            try:
                return payment_intents._saved_pagomovil_by_name(None, [words], pointer)['phone']
            except IntentRefused as refused:
                return refused.code

    def test_the_person_the_sentence_pays(self):
        cases = [('envia 20 a Ana por pago movil', 'Ana', 'A'), ('mándale 20 a mi mamá por pago móvil', 'Mama', 'M'),
                 ('20 dólares para Ana', 'Ana', 'A'), ('Ana 20 dólares', 'Ana', 'A'),
                 ('mándale 20 a Ana María', 'Ana María', 'AM'), ('mándale 20 a Ana Pérez', 'Ana Pérez', 'A'),
                 ('pásale 20 a la mamá', 'mamá', 'M'), ('20 para mi mamá, porfa', 'mamá', 'M'),
                 ('mándale 20 dólares a Pedro hoy', 'Pedro', 'P'),
                 # A name the owner ruled out is out; the other one is who is paid.
                 ('nunca le mandes a Ana, 20 para mamá', 'mamá', 'M'), ('jamás a Ana; 20 a mamá', 'mamá', 'M'),
                 ('lo de la mamá ya está, 20 a Pedro', 'Pedro', 'P')]
        for words, pointer, expected in cases:
            with self.subTest(words=words, pointer=pointer):
                self.assertEqual(self.chosen(words, pointer), expected)

    def test_never_someone_the_sentence_only_mentions(self):
        cases = [
            # A longer name that is not saved, or a saved name inside another word group.
            ('envia 20 a Ana Gómez por pago movil', 'Ana'), ('paga a Santa Ana 20', 'Ana'),
            ('mándale 20 a Ana María', 'Ana'),
            # Somebody's relative, or the one it comes from.
            ('mándale 20 a la mamá de Pedro', 'Pedro'), ('mándale 20 a la mamá de Pedro', 'mamá'),
            ('mándale 20 al hermano de Ana', 'Ana'), ('mándale 20 a Ana de parte de Pedro', 'Pedro'),
            # Talk about a person, a negation, an exception.
            ('dile a Ana que ya le pagué 20', 'Ana'), ('fui con mi mamá y gasté 20', 'mamá'),
            ('no le envies a Ana, envia 20 a otra', 'Ana'), ('nunca le mandes a Ana, 20 para mamá', 'Ana'),
            ('mándale 20 a todos menos a Ana', 'Ana'), ('lo de la mamá ya está, 20 a Pedro', 'mamá'),
            # Two people at once: never a pick.
            ('mándale 20 a Ana y 10 a Pedro', 'Ana'),
        ]
        for words, pointer in cases:
            with self.subTest(words=words, pointer=pointer):
                self.assertIn(self.chosen(words, pointer), ('no_saved_payee', 'not_said'))
