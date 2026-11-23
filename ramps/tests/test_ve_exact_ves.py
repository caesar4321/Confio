"""Pago Móvil in exact bolívares: priced in dollars from Pago ASAP's own cost
for that payout (plus a margin); the payout is exactly that amount and what
the deposit buys above it stays in Confío's Pago ASAP balance."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from ramps import pagoasap_send, ve_pagomovil, ve_send
# The send fixtures by module, so the loader does not run send_fixture.SendCoreTests here again.
from . import test_ve_send as send_fixture
from .test_ve_send import WALLET, pagoasap_client


def relay_delivering(ratio=Decimal('0.98')):
    """A Relay estimate that delivers `ratio` of the deposited USDT."""
    relay = mock.Mock()
    relay.quote.side_effect = lambda source, destination, wei, **kw: {
        'details': {'currencyOut': {'amount': str(int(Decimal(wei) / 10 ** 12 * ratio))}}}
    return relay


class ExactQuoteTests(TestCase):
    def quote(self, ves, client=None, relay=None):
        with mock.patch.object(pagoasap_send, '_client', return_value=client or pagoasap_client()), \
                mock.patch.object(pagoasap_send, '_polygon_address', return_value=WALLET), \
                mock.patch('payment_accounts.relay.RelayClient', return_value=relay or relay_delivering()):
            return pagoasap_send.quote_exact_now(ves)

    def test_dollars_cover_the_exact_bolivares_without_overcharging(self):
        quote = self.quote('19800.00')   # Pago ASAP: 19.80 USD at 1000 VES/USD
        self.assertEqual((quote['estimated_ves'], quote['exact_ves']), ('19800.00', '19800.00'))
        usd = Decimal(quote['usd_amount'])
        # What arrives after Confío's fee and Relay covers the cost plus the 1% margin...
        _, deposit = ve_send.confio_amounts(usd)
        delivered = Decimal(deposit) / Decimal(10 ** 18) * Decimal('0.98')
        self.assertGreaterEqual(delivered, Decimal('19.80') * Decimal('1.01'))
        # ...and not much more than that.
        self.assertLess(usd, Decimal('22.00'))

    def test_the_lines_add_up_and_the_rates_are_read_once(self):
        client = pagoasap_client()
        quote = self.quote('19800.00', client=client)
        usd, ves = Decimal(quote['usd_amount']), Decimal('19800.00')
        self.assertEqual(Decimal(quote['rate']), (ves / usd).quantize(Decimal('0.0001'), rounding='ROUND_DOWN'))
        self.assertEqual(client.rate.call_count, 1)
        self.assertEqual(client.reference_rate.call_count, 1)
        # Confío's fee and the processor's share (cost, bridge and the margin) are all of it.
        self.assertGreaterEqual(Decimal(quote['confio_fee_usd']) + Decimal(quote['processor_fee_usd']),
                                usd - ves / Decimal('1010') - Decimal('0.01'))

    def test_refusals(self):
        for bad in ('0', '9.99', '12.345', 'abc', '1e12'):
            with self.subTest(ves=bad), self.assertRaises(ve_pagomovil.VePagoMovilError):
                self.quote(bad)
        broken = pagoasap_client()
        broken.preview.side_effect = lambda ves: {'total': '0'}
        with self.assertRaises(ve_pagomovil.VePagoMovilError):
            self.quote('19800.00', client=broken)


class ExactPayoutTests(TestCase):
    """send_fixture.SendCoreTests' fixtures, without running its tests again."""
    setUp = send_fixture.SendCoreTests.setUp
    _ramp = send_fixture.SendCoreTests._ramp
    _funded = send_fixture.SendCoreTests._funded
    _pay = send_fixture.SendCoreTests._pay

    def test_pays_exactly_the_bolivares_and_the_rest_stays_with_the_provider(self):
        ramp = self._funded(estimate={'exact_ves': '15000.00'}, estimated_ves='15000.00')
        client = pagoasap_client()   # credited 19.82 USD buys 19,819.99 VES: only 15,000 are paid
        ramp = self._pay(ramp, client)
        self.assertEqual(ve_send._phase(ramp), 'payout_pending')
        self.assertEqual(client.create_payout.call_args.kwargs['amount_ves'], Decimal('15000.00'))

    def test_a_deposit_that_no_longer_covers_them_waits_then_goes_to_review(self):
        ramp = self._funded(estimate={'exact_ves': '25000.00'}, estimated_ves='25000.00')
        client = pagoasap_client()
        ramp = self._pay(ramp, client)
        self.assertEqual(ramp.status_detail, 'waiting_rate')   # the rate may come back
        section = ve_send._section(ramp)
        section['payout_wait_since'] = (timezone.now() - ve_send.RATE_WAIT - timedelta(minutes=1)).isoformat()
        ramp.metadata = {**ramp.metadata, ve_send.SECTION: section}
        ramp.save(update_fields=['metadata'])
        ramp = self._pay(ramp, client)
        self.assertEqual((ve_send._phase(ramp), ramp.status_detail),
                         ('payout_review', 'needs_review:exact_payout_short'))
        client.create_payout.assert_not_called()

    def test_create_charges_the_fresh_price_and_stores_the_exact_bolivares(self):
        quote = {'usd_amount': '19.50', 'usdt_amount': '19.30', 'confio_fee_usd': '0.20',
                 'processor_fee_usd': '0.40', 'estimated_ves': '18000.00', 'exact_ves': '18000.00', 'rate': '923.0769'}
        with mock.patch.object(pagoasap_send, '_polygon_address', return_value=WALLET), \
                mock.patch.object(pagoasap_send, 'quote_exact_now', return_value=quote), \
                mock.patch.object(ve_send, 'current_block', return_value=1000), \
                mock.patch.object(ve_send, 'reserve') as reserve, mock.patch.object(ve_send, 'prepare') as prepare:
            pagoasap_send.create(self.user, mock.Mock(), Decimal('25.00'), {'phone': '584141234567'},
                                 exact_ves='18000.00')
        kwargs = reserve.call_args.kwargs
        # A stale screen that approved $25 pays the fresh $19.50, never more.
        self.assertEqual(kwargs['gross_usd'], Decimal('19.50'))
        self.assertEqual(kwargs['estimate']['exact_ves'], '18000.00')
        self.assertEqual(kwargs['gross_wei'], ve_send.confio_amounts(Decimal('19.50'))[0])
        prepare.assert_called_once()

    def test_create_never_charges_more_than_approved(self):
        quote = {'usd_amount': '25.00', 'estimated_ves': '19800.00', 'exact_ves': '19800.00'}
        with mock.patch.object(pagoasap_send, '_polygon_address', return_value=WALLET), \
                mock.patch.object(pagoasap_send, 'quote_exact_now', return_value=quote), \
                self.assertRaisesRegex(ve_pagomovil.VePagoMovilError, 'cambió'):
            pagoasap_send.create(self.user, mock.Mock(), Decimal('20.00'), {}, exact_ves='19800.00')


class ExactSchemaTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create(username='ve-exact', firebase_uid='ve-exact')
        self.info = mock.Mock(context=mock.Mock(user=self.user, META={}))

    def test_a_provider_without_exact_bolivares_refuses_in_words(self):
        from ramps.ve_pagomovil_schema import Query
        with mock.patch('ramps.ve_pagomovil_schema._preflight', return_value=(self.user, mock.Mock())), \
                mock.patch.object(ve_pagomovil, 'send_adapter', return_value=mock.Mock(spec=['quote'])):
            result = Query().resolve_ve_pagomovil_send_exact_quote(self.info, '15000')
        self.assertFalse(result.success)
        self.assertIn('dólares', result.error)

    def test_the_exact_quote_answers_without_its_internal_key(self):
        from ramps.ve_pagomovil_schema import Query
        adapter = mock.Mock()
        adapter.quote_exact.return_value = {'usd_amount': '16.40', 'usdt_amount': '16.20', 'confio_fee_usd': '0.20',
                                            'processor_fee_usd': '0.30', 'estimated_ves': '15000.00',
                                            'exact_ves': '15000.00', 'rate': '914.6341'}
        with mock.patch('ramps.ve_pagomovil_schema._preflight', return_value=(self.user, mock.Mock())), \
                mock.patch.object(ve_pagomovil, 'send_adapter', return_value=adapter):
            result = Query().resolve_ve_pagomovil_send_exact_quote(self.info, '15000')
        self.assertTrue(result.success)
        self.assertEqual((result.usd_amount, result.estimated_ves), ('16.40', '15000.00'))


class ExactPayoutBalanceTests(TestCase):
    setUp = send_fixture.SendCoreTests.setUp
    _ramp = send_fixture.SendCoreTests._ramp
    _funded = send_fixture.SendCoreTests._funded
    _pay = send_fixture.SendCoreTests._pay

    def test_waits_for_balance_and_for_a_price(self):
        ramp = self._funded(estimate={'exact_ves': '15000.00'}, estimated_ves='15000.00')
        low = pagoasap_client(balance='10')            # 15 USD needed, 10 in the balance
        ramp = self._pay(ramp, low)
        self.assertEqual(ramp.status_detail, 'waiting_balance')
        low.create_payout.assert_not_called()
        unpriced = pagoasap_client(total='0')          # no preview cost: not payable yet, never guessed
        ramp = self._pay(ramp, unpriced)
        unpriced.create_payout.assert_not_called()
        self.assertEqual(ramp.status_detail, 'waiting_rate')


class ExactCreateSchemaTests(TestCase):
    def test_a_provider_without_exact_bolivares_refuses_the_order(self):
        from ramps.ve_pagomovil_schema import CreateVePagoMovilSend
        user, account = mock.Mock(), mock.Mock()
        info = mock.Mock(context=mock.Mock(user=user, META={}))
        with mock.patch('ramps.ve_pagomovil_schema._preflight', return_value=(user, account)), \
                mock.patch('security.face_step_up.missing_face_step_up', return_value=None), \
                mock.patch.object(ve_pagomovil, 'send_adapter', return_value=mock.Mock(spec=['quote', 'create'])) as adapter:
            result = CreateVePagoMovilSend().mutate(info, usd_amount='16.40', cedula='V12345678',
                                                    phone='04141234567', bank_code='0102', ves_amount='15000')
        self.assertFalse(result.success)
        self.assertIn('dólares', result.error)
        adapter.return_value.create.assert_not_called()


class ExactRound3Tests(TestCase):
    setUp = send_fixture.SendCoreTests.setUp
    _ramp = send_fixture.SendCoreTests._ramp
    _funded = send_fixture.SendCoreTests._funded
    _pay = send_fixture.SendCoreTests._pay

    def test_an_unreadable_exact_amount_goes_to_review_never_a_dollar_payout(self):
        ramp = self._funded(estimate={'exact_ves': 'abc'}, estimated_ves='15000.00')
        client = pagoasap_client()
        ramp = self._pay(ramp, client)
        self.assertEqual(ramp.status_detail, 'needs_review:exact_ves_unreadable')
        client.create_payout.assert_not_called()

    def test_no_price_keeps_the_wait_clock(self):
        ramp = self._funded(estimate={'exact_ves': '15000.00'}, estimated_ves='15000.00')
        ramp = self._pay(ramp, pagoasap_client(total='0'))
        self.assertEqual(ramp.status_detail, 'waiting_rate')
        self.assertTrue(ve_send._section(ramp).get('payout_wait_since'))

    def test_the_quote_is_kept_a_few_seconds_but_never_for_the_order(self):
        from django.core.cache import cache
        cache.clear()
        quote = {'usd_amount': '16.40', 'exact_ves': '15000.00'}
        with mock.patch.object(pagoasap_send, 'quote_exact_now', return_value=quote) as now:
            pagoasap_send.quote_exact('15000.00')
            pagoasap_send.quote_exact('15000')
        self.assertEqual(now.call_count, 1)


class ExactRound4Tests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create(username='ve-exact-4', firebase_uid='ve-exact-4')

    def test_a_huge_amount_gets_words(self):
        with mock.patch.object(pagoasap_send, '_client', return_value=pagoasap_client()), \
                self.assertRaisesRegex(ve_pagomovil.VePagoMovilError, 'bolívares'):
            pagoasap_send.quote_exact_now('1e30')

    def test_a_moved_price_is_quoted_fresh_next_time(self):
        from django.core.cache import cache
        cache.clear()
        cache.set(pagoasap_send._exact_cache_key('19800'), {'usd_amount': '19.00'})
        quote = {'usd_amount': '25.00', 'estimated_ves': '19800.00', 'exact_ves': '19800.00'}
        with mock.patch.object(pagoasap_send, '_polygon_address', return_value=WALLET), \
                mock.patch.object(pagoasap_send, 'quote_exact_now', return_value=quote), \
                self.assertRaisesRegex(ve_pagomovil.VePagoMovilError, 'cambió'):
            pagoasap_send.create(self.user, mock.Mock(), Decimal('20.00'), {}, exact_ves='19800.00')
        self.assertIsNone(cache.get(pagoasap_send._exact_cache_key('19800')))


class ExactRound5Tests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.core.cache import cache
        cache.clear()
        self.user = get_user_model().objects.create(username='ve-exact-5', firebase_uid='ve-exact-5')
        self.info = mock.Mock(context=mock.Mock(user=self.user, META={}))

    def test_the_exact_quote_is_for_those_who_can_send_and_paced(self):
        from ramps.ve_pagomovil_schema import Query
        with mock.patch('ramps.ve_pagomovil_schema._preflight',
                        side_effect=ve_pagomovil.VePagoMovilError('Verifica tu identidad para usar Pago Móvil.')):
            refused = Query().resolve_ve_pagomovil_send_exact_quote(self.info, '15000')
        self.assertFalse(refused.success)
        adapter = mock.Mock()
        adapter.quote_exact.return_value = {'usd_amount': '16.40', 'estimated_ves': '15000.00', 'exact_ves': '15000.00'}
        with mock.patch('ramps.ve_pagomovil_schema._preflight', return_value=(self.user, mock.Mock())), \
                mock.patch.object(ve_pagomovil, 'send_adapter', return_value=adapter):
            from ramps.ve_pagomovil_schema import EXACT_QUOTES_PER_WINDOW
            answers = [Query().resolve_ve_pagomovil_send_exact_quote(self.info, str(15000 + n))
                       for n in range(EXACT_QUOTES_PER_WINDOW + 1)]
        self.assertTrue(all(a.success for a in answers[:-1]))
        self.assertFalse(answers[-1].success)
        self.assertIn('Espera', answers[-1].error)
