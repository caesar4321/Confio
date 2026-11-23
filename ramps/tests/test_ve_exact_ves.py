"""Pago Móvil in exact bolívares: priced in dollars from Pago ASAP's own cost
for that payout (plus a margin); the payout is exactly that amount and what
the deposit buys above it stays in Confío's Pago ASAP balance."""
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from ramps import pagoasap_send, ve_pagomovil, ve_send
from .test_ve_send import WALLET, SendCoreTests, pagoasap_client


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
            return pagoasap_send.quote_exact(ves)

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

    def test_refusals(self):
        for bad in ('0', '9.99', '12.345', 'abc', '1e12'):
            with self.subTest(ves=bad), self.assertRaises(ve_pagomovil.VePagoMovilError):
                self.quote(bad)
        broken = pagoasap_client()
        broken.preview.side_effect = lambda ves: {'total': '0'}
        with self.assertRaises(ve_pagomovil.VePagoMovilError):
            self.quote('19800.00', client=broken)


class ExactPayoutTests(SendCoreTests):
    """Runs SendCoreTests' fixtures; only the tests below are new."""

    def test_pays_exactly_the_bolivares_and_the_rest_stays_with_the_provider(self):
        ramp = self._funded(estimate={'exact_ves': '15000.00'}, estimated_ves='15000.00')
        client = pagoasap_client()   # credited 19.82 USD buys 19,819.99 VES: only 15,000 are paid
        ramp = self._pay(ramp, client)
        self.assertEqual(ve_send._phase(ramp), 'payout_pending')
        self.assertEqual(client.create_payout.call_args.kwargs['amount_ves'], Decimal('15000.00'))

    def test_a_deposit_that_no_longer_covers_them_goes_to_review(self):
        ramp = self._funded(estimate={'exact_ves': '25000.00'}, estimated_ves='25000.00')
        client = pagoasap_client()
        ramp = self._pay(ramp, client)
        self.assertEqual((ve_send._phase(ramp), ramp.status_detail),
                         ('payout_review', 'needs_review:exact_payout_short'))
        client.create_payout.assert_not_called()

    def test_create_never_charges_more_than_approved(self):
        quote = {'usd_amount': '25.00', 'estimated_ves': '19800.00', 'exact_ves': '19800.00'}
        with mock.patch.object(pagoasap_send, '_polygon_address', return_value=WALLET), \
                mock.patch.object(pagoasap_send, 'quote_exact', return_value=quote), \
                self.assertRaisesRegex(ve_pagomovil.VePagoMovilError, 'cambió'):
            pagoasap_send.create(self.user, mock.Mock(), Decimal('20.00'), {}, exact_ves='19800.00')
