"""What a prepared payment is short of: said around the card, never a refusal."""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from payment_accounts import shortfall

WEI = 10 ** 18
ACCOUNT = SimpleNamespace(bsc_address='0x' + 'a' * 40, user=object())


def vault(reserved=0, out=None, address='0xv', fail=None):
    """The vault reads: reserved USDT and what redeeming shares yields."""
    patches = [
        mock.patch('cusd_plus.vault.reserved_usdt_wei', return_value=reserved * WEI),
        mock.patch('cusd_plus.vault.vault_address', return_value=address),
        mock.patch('cusd_plus.vault.p_plus_wad', return_value=WEI),
        mock.patch('cusd_plus.vault.current_oracle_price_wad', return_value=WEI),
        mock.patch('cusd_plus.vault.redeem_gross_usdt_out',
                   side_effect=fail or (lambda shares, pps, oracle: int(out * WEI) if out is not None else shares)),
    ]

    class Both:
        def __enter__(self):
            for p in patches:
                p.start()

        def __exit__(self, *exc):
            for p in patches:
                p.stop()
    return Both()


def balances(cusd=0, plus=0, usdt=0, **missing):
    raw = {'CUSD_BSC': cusd * WEI, 'CUSD_PLUS': plus * WEI, 'USDT_BSC': usdt * WEI}
    for token in missing:
        raw.pop(token)
    return mock.patch('blockchain.bsc_balance_service.BscBalanceService.balances_raw', return_value=raw)


class DollarsHeldTests(SimpleTestCase):
    def test_counts_every_dollar_a_payment_spends(self):
        # Confío Dollar, what redeeming Confío Dollar+ yields, and wallet USDT not committed elsewhere.
        with balances(cusd=10, plus=20, usdt=5), vault(reserved=2, out=Decimal('20.9')):
            self.assertEqual(shortfall.dollars_held(ACCOUNT), Decimal('33.9'))
        # USDT already counted on by a send or an off-ramp order is never more than there is.
        with balances(cusd=1, usdt=5), vault(reserved=9):
            self.assertEqual(shortfall.dollars_held(ACCOUNT), Decimal('1'))

    def test_anything_not_read_is_unknown_never_zero(self):
        for token in ('CUSD_BSC', 'CUSD_PLUS', 'USDT_BSC'):
            with balances(cusd=10, **{token: True}):
                self.assertIsNone(shortfall.dollars_held(ACCOUNT), token)
        with balances(plus=3), vault(address=''):
            self.assertIsNone(shortfall.dollars_held(ACCOUNT))
        with balances(plus=3), vault(fail=RuntimeError('rpc')):
            self.assertIsNone(shortfall.dollars_held(ACCOUNT))
        with balances(cusd=3), mock.patch('cusd_plus.vault.reserved_usdt_wei', side_effect=RuntimeError('db')):
            self.assertIsNone(shortfall.dollars_held(ACCOUNT))
        self.assertIsNone(shortfall.dollars_held(SimpleNamespace(bsc_address='')))
        with mock.patch('blockchain.bsc_balance_service.BscBalanceService.balances_raw', side_effect=RuntimeError):
            self.assertIsNone(shortfall.dollars_held(ACCOUNT))

    def test_no_shares_needs_no_vault(self):
        with balances(cusd=4), mock.patch('cusd_plus.vault.reserved_usdt_wei', return_value=0), \
                mock.patch('cusd_plus.vault.redeem_gross_usdt_out', side_effect=AssertionError('not read')):
            self.assertEqual(shortfall.dollars_held(ACCOUNT), Decimal('4'))


class ShortfallTests(SimpleTestCase):
    def test_what_is_missing_rounded_up_to_the_cent(self):
        with mock.patch.object(shortfall, 'dollars_held', return_value=Decimal('10.004')):
            self.assertEqual(shortfall.shortfall(ACCOUNT, Decimal('12.50')), Decimal('2.50'))
            self.assertEqual(shortfall.shortfall(ACCOUNT, '10.01'), Decimal('0.01'))
            self.assertIsNone(shortfall.shortfall(ACCOUNT, Decimal('10.00')))

    def test_nothing_said_when_enough_or_unknown(self):
        with mock.patch.object(shortfall, 'dollars_held', return_value=Decimal('50')):
            self.assertIsNone(shortfall.shortfall(ACCOUNT, Decimal('49.99')))
        with mock.patch.object(shortfall, 'dollars_held', return_value=None):
            self.assertIsNone(shortfall.shortfall(ACCOUNT, Decimal('5')))
        self.assertIsNone(shortfall.shortfall(ACCOUNT, 'not a number'))

    def test_written_as_the_cards_write_it(self):
        self.assertEqual(shortfall.usd(Decimal('1234.5')), 'US$1,234.50')
        # What is missing rounds up; what someone has never shows a cent more than is there.
        self.assertEqual(shortfall.usd(Decimal('12.305')), 'US$12.31')
        self.assertEqual(shortfall.usd(Decimal('12.309'), down=True), 'US$12.30')


class PricingRefusalTests(SimpleTestCase):
    """local_money._bridge_estimate prices against the wallet: too few dollars
    is a PaymentAccountError in Spanish with what is missing."""

    def test_the_funding_refusal_becomes_the_persons(self):
        from payment_accounts import local_money
        from payment_accounts.infinia_fees import FeePricingError
        from payment_accounts.services import PaymentAccountError
        for message in shortfall.TOO_FEW_DOLLARS:
            with self.subTest(message=message), \
                    mock.patch('payment_accounts.infinia_fee_funding.quote_funding',
                               side_effect=FeePricingError(message)), \
                    mock.patch.object(shortfall, 'dollars_held', return_value=Decimal('3')), \
                    self.assertRaises(PaymentAccountError) as refused:
                local_money._bridge_estimate(ACCOUNT, object(), Decimal('10.00'), {'units': '1'})
            self.assertEqual(str(refused.exception),
                             'No tienes saldo suficiente para este pago: te faltan US$7.00. Recarga y vuelve a prepararlo.')
            self.assertEqual(refused.exception.missing, Decimal('7.00'))

    def test_savings_under_the_redeem_floor_are_not_spendable(self):
        with balances(cusd=4, plus=1), vault(out=Decimal('0.5')):
            self.assertEqual(shortfall.dollars_held(ACCOUNT), Decimal('4'))

    def test_a_refusal_re_raised_under_another_code_is_still_known_as_short(self):
        from payment_accounts.payment_intents import IntentRefused
        with mock.patch.object(shortfall, 'dollars_held', return_value=None):
            short = shortfall.short_of_dollars(ACCOUNT, Decimal('5'))
        try:
            try:
                raise short
            except Exception as exc:
                raise IntentRefused('rail', str(exc)) from exc
        except IntentRefused as wrapped:
            self.assertTrue(shortfall.is_short_of_dollars(wrapped))
        self.assertFalse(shortfall.is_short_of_dollars(IntentRefused('rail', 'otro')))
        self.assertFalse(shortfall.is_short_of_dollars(None))
