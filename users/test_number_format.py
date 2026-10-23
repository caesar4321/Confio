from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from notifications.token_display import amount_str
from users.number_format import format_amount, format_usd, separators_for

VE = SimpleNamespace(phone_country='VE')
MX = SimpleNamespace(phone_country='MX')


class NumberFormatTests(SimpleTestCase):
    def test_country_decides_the_separators(self):
        self.assertEqual(separators_for(VE), ('.', ','))
        self.assertEqual(separators_for(MX), (',', '.'))
        self.assertEqual(separators_for(SimpleNamespace(phone_country=None)), (',', '.'))

    def test_amounts(self):
        self.assertEqual(format_amount('1234.5', VE), '1.234,5')
        self.assertEqual(format_amount('1234.5', MX), '1,234.5')
        self.assertEqual(format_amount('5.00', VE), '5')
        self.assertEqual(format_amount(Decimal('0.123456'), VE, decimals=6), '0,123456')
        self.assertEqual(format_amount('-2.5', VE, trim=False), '-2,50')
        self.assertEqual(format_amount('abc', VE), 'abc')

    def test_dollars(self):
        self.assertEqual(format_usd('2.5', VE), '$2,50')
        self.assertEqual(format_usd('2.5', VE, trim=True), '$2,5')
        self.assertEqual(format_usd('-1234.5', MX), '-$1,234.50')

    def test_token_display_amounts_follow_the_recipient(self):
        self.assertEqual(amount_str('1.089', VE), '1,09')
        self.assertEqual(amount_str('1.089'), '1.09')


class ReaderCountryTests(SimpleTestCase):
    def test_text_written_for_a_reader_uses_their_format(self):
        from inbox.activity_share import activity_headline
        from users.number_format import reading_as

        activity = {'kind': 'stock_buy', 'ticker': 'NVDA', 'amount_usd': '1234.5', 'show_amount': True}
        with reading_as(VE):
            self.assertEqual(activity_headline(activity), 'Compró NVDA · US$1.234,50')
        with reading_as(MX):
            self.assertEqual(activity_headline(activity), 'Compró NVDA · US$1,234.50')
        sell = {'kind': 'stock_sell', 'ticker': 'NVDA', 'amount_usd': '20', 'pnl_pct': '12.5'}
        with reading_as(VE):
            self.assertEqual(activity_headline(sell), 'Vendió NVDA · US$20,00 · +12,50%')
