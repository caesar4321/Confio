"""'Tu dólar te protegió' replay, cap and fail-closed rules (Decision 3, R13, R14, R27)."""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from users.cashflow import Movement
from users import protection as p

D = Decimal


def onramp(usd, bob):
    rt = SimpleNamespace(direction='on_ramp', status='COMPLETED', provider='koywe', fiat_currency='BOB',
                         fiat_amount=D(bob))
    return SimpleNamespace(ramp_transaction=rt), Movement(kind='top_up', direction='received', amount=D(usd))


def ev(kind, usd, direction='sent'):
    return SimpleNamespace(ramp_transaction=None), Movement(kind=kind, direction=direction, amount=D(usd))


class ReplayTests(SimpleTestCase):
    def test_codex_counterexample_protects_nothing(self):
        # on-ramp $100 → own business → unrelated $100 in  ⇒  $0 protected
        lots = p.replay([onramp(100, 700), ev('own_transfer', 100, 'sent'),
                         ev('income_person', 100, 'received')], 'BOB')
        self.assertEqual(lots, [])

    def test_plain_dollars_are_spent_before_lots_then_oldest_lot_first(self):
        lots = p.replay([onramp(100, 690), ev('income_person', 30, 'received'), onramp(50, 360),
                         ev('p2p_send', 80)], 'BOB')
        # 30 plain spent, then 50 from the oldest lot (half of it: Bs 345 left)
        self.assertEqual([(l.usd, l.local) for l in lots], [(D('50'), D('345')), (D('50'), D('360'))])

    def test_savings_and_conversions_are_neutral_and_other_currencies_are_plain(self):
        other = onramp(40, 500); other[0].ramp_transaction.fiat_currency = 'PEN'
        lots = p.replay([onramp(100, 700), ev('savings_in', 100), ev('conversion', 100), other,
                         ev('withdrawal', 40)], 'BOB')
        self.assertEqual([(l.usd, l.local) for l in lots], [(D('100'), D('700'))])

    def test_cap_trims_newest_lots_to_the_wallet_balance(self):
        lots = [p.Lot(D('100'), D('690')), p.Lot(D('50'), D('360'))]
        capped = p._cap(lots, D('120'))
        self.assertEqual([(l.usd, l.local) for l in capped], [(D('100'), D('690')), (D('20'), D('144'))])


class ProtectionValueTests(SimpleTestCase):
    def _value(self, *, quote, lots, balance='150', country='BO', account_type='personal'):
        user = SimpleNamespace(phone_country=country)
        account = SimpleNamespace(id=7, bsc_address='0xabc')
        scope = mock.MagicMock()
        scope.aggregate.return_value = {'n': 3, 'last': 9, 'touched': None}
        with mock.patch('users.graphql_views.account_unified_queryset', return_value=scope), \
             mock.patch.object(p, 'protection_countries', return_value={'BO', 'VE'}), \
             mock.patch.object(p, 'cached_quote', return_value=quote), \
             mock.patch.object(p.cache, 'get', side_effect=lambda k, *a: lots if not k.endswith(':balance') else None), \
             mock.patch.object(p.cache, 'set'), \
             mock.patch('cusd_plus.vault.withdrawable_usdt_wei', return_value=int(D(balance) * 10 ** 18)):
            return p.protection_value(user, account, account_type, None)

    def test_gain_is_today_minus_paid_on_held_lots(self):
        result = self._value(quote={'rate': '7.40', 'quoted_at': 't'}, lots=[p.Lot(D('100'), D('690'))])
        self.assertEqual((result.protected_usd, result.paid_local, result.today_local, result.gain_local),
                         (D('100'), D('690'), D('740.00'), D('50.00')))

    def test_every_unknown_hides_the_card(self):
        lots = [p.Lot(D('100'), D('690'))]
        self.assertIsNone(self._value(quote=None, lots=lots))                                    # no quote
        self.assertIsNone(self._value(quote={'rate': '7.40', 'quoted_at': 't'}, lots=[]))         # no lots
        self.assertIsNone(self._value(quote={'rate': '7.40', 'quoted_at': 't'}, lots=lots, country='PE'))
        self.assertIsNone(self._value(quote={'rate': '7.40', 'quoted_at': 't'}, lots=lots, account_type='business'))
        self.assertIsNone(self._value(quote={'rate': '6.95', 'quoted_at': 't'}, lots=lots))       # gain Bs 5 < 10
        self.assertIsNone(self._value(quote={'rate': '6.00', 'quoted_at': 't'}, lots=lots))       # a loss: never shown


class ReplayFeeAndSwitchTests(SimpleTestCase):
    def test_own_conversion_fees_spend_dollars_but_the_ramp_conversion_does_not(self):
        conv = SimpleNamespace(ramp_transaction=None, fee_amount='0.90', conversion=SimpleNamespace(source='user'))
        ramp_conv = SimpleNamespace(ramp_transaction=None, fee_amount='0.90', conversion=SimpleNamespace(source='ramp'))
        lots = p.replay([onramp(100, 700), (conv, Movement(kind='savings_in', direction='sent', amount=D('100'))),
                         (ramp_conv, Movement(kind='conversion', direction='sent', amount=D('100')))], 'BOB')
        self.assertEqual([l.usd for l in lots], [D('99.10')])

    def test_country_switch_comes_from_settings(self):
        with self.settings(TU_MES_PROTECTION_COUNTRIES=['BO']):
            self.assertEqual(p.protection_countries(), {'BO'})
        with self.settings(TU_MES_PROTECTION_COUNTRIES=[]):
            self.assertEqual(p.protection_countries(), set())
