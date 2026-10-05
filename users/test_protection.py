"""'Tu dólar te protegió': replay, cap, the two bases and fail-closed rules
(Decision 3, R13; founder decision 2026-10-04: Binance P2P "today" everywhere)."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from users.cashflow import Movement
from users import protection as p

D = Decimal


def onramp(usd, local, currency='BOB'):
    rt = SimpleNamespace(direction='on_ramp', status='COMPLETED', provider='koywe', fiat_currency=currency,
                         fiat_amount=D(local))
    return SimpleNamespace(ramp_transaction=rt, transaction_date=None), \
        Movement(kind='top_up', direction='received', amount=D(usd))


def ev(kind, usd, direction='sent', **row):
    return SimpleNamespace(ramp_transaction=None, **row), Movement(kind=kind, direction=direction, amount=D(usd))


class ReplayTests(SimpleTestCase):
    def test_codex_counterexample_protects_nothing(self):
        lots = p.replay([onramp(100, 700), ev('own_transfer', 100, 'sent'),
                         ev('income_person', 100, 'received')], 'BOB')
        self.assertEqual(lots, [])

    def test_plain_dollars_are_spent_before_lots_then_oldest_lot_first(self):
        lots = p.replay([onramp(100, 690), ev('income_person', 30, 'received'), onramp(50, 360),
                         ev('p2p_send', 80)], 'BOB')
        self.assertEqual([(l.usd, l.local) for l in lots], [(D('50'), D('345')), (D('50'), D('360'))])

    def test_own_conversion_fees_spend_dollars_but_the_ramp_conversion_does_not(self):
        lots = p.replay([onramp(100, 700),
                         ev('savings_in', 100, fee_amount='0.90', conversion=SimpleNamespace(source='user')),
                         ev('conversion', 100, fee_amount='0.90', conversion=SimpleNamespace(source='ramp'))], 'BOB')
        self.assertEqual([l.usd for l in lots], [D('99.10')])

    def test_other_currencies_are_plain_dollars(self):
        lots = p.replay([onramp(100, 700), onramp(40, 500, currency='PEN'), ev('withdrawal', 40)], 'BOB')
        self.assertEqual([(l.usd, l.local) for l in lots], [(D('100'), D('700'))])

    def test_cap_trims_the_oldest_lots_first_like_spending(self):
        lots = [p.Lot(D('100'), D('800')), p.Lot(D('100'), D('1200'))]
        capped = p._cap(lots, D('100'))
        self.assertEqual([(l.usd, l.local) for l in capped], [(D('100'), D('1200'))])


class ProtectionValueTests(SimpleTestCase):
    def _value(self, *, country='BO', rate=('12.50', 0), lots=(), start_rate=None, net_in=D('0'),
               balance='150', account_type='personal'):
        user = SimpleNamespace(phone_country=country)
        account = SimpleNamespace(id=7, bsc_address='0xabc')
        now = None if rate is None else (D(rate[0]), timezone.now() - timedelta(minutes=rate[1]))

        def cache_get(key, *a):
            if key.endswith(':balance'):
                return D(balance)
            if ':lots:' in key:
                return list(lots)
            if ':held:' in key:
                return net_in
            return None
        with mock.patch.object(p, 'protection_countries', return_value={'BO', 'AR', 'VE'}), \
             mock.patch.object(p, 'current_rate', return_value=now), \
             mock.patch.object(p, 'month_start_rate', return_value=None if start_rate is None else D(start_rate)), \
             mock.patch.object(p, '_ledger', return_value=('v1', lambda: [])), \
             mock.patch.object(p.cache, 'get', side_effect=cache_get), \
             mock.patch.object(p.cache, 'set'):
            return p.protection_value(user, account, account_type, None, 2026, 10)

    def test_purchase_basis_paid_in_confio_vs_binance_p2p_today(self):
        r = self._value(lots=[p.Lot(D('100'), D('1150'))])
        self.assertEqual((r.basis, r.protected_usd, r.paid_local, r.today_local, r.gain_local),
                         ('purchase', D('100'), D('1150'), D('1250.00'), D('100.00')))

    def test_month_start_basis_counts_only_dollars_held_all_month(self):
        # 100 held since the 1st (cached "held" figure)
        r = self._value(country='VE', rate=('40', 0), start_rate='36', net_in=D('100'))
        self.assertEqual((r.basis, r.protected_usd, r.paid_local, r.today_local), ('month_start', D('100'), D('3600'), D('4000')))

    def test_every_unknown_hides_the_card(self):
        lots = [p.Lot(D('100'), D('1150'))]
        self.assertIsNone(self._value(rate=None, lots=lots))                          # stale / no P2P rate
        self.assertIsNone(self._value(lots=[]))                                       # no lots and no 1st-of-month rate yet
        self.assertIsNone(self._value(country='VE', rate=('40', 0), start_rate=None))  # no rate kept for the 1st
        self.assertIsNone(self._value(country='PE', lots=lots))
        self.assertIsNone(self._value(lots=lots, account_type='business'))

        self.assertIsNone(self._value(country='VE', rate=('40', 0), start_rate='36', net_in=D('0')))    # nothing held all month

    def test_country_switch_comes_from_settings(self):
        with self.settings(TU_MES_PROTECTION_COUNTRIES=['BO']):
            self.assertEqual(p.protection_countries(), {'BO'})
        with self.settings(TU_MES_PROTECTION_COUNTRIES=[]):
            self.assertEqual(p.protection_countries(), set())


class RatesTests(TestCase):
    def _rate(self, currency, rate, minutes_ago):
        from exchange_rates.models import ExchangeRate
        return ExchangeRate.objects.create(source_currency=currency, target_currency='USD', rate=rate,
                                           rate_type='parallel', source='binance_p2p',
                                           fetched_at=timezone.now() - timedelta(minutes=minutes_ago))

    def test_current_rate_is_the_freshest_and_refuses_stale_rows(self):
        self._rate('VES', '39.00', 90)
        self._rate('VES', '40.00', 10)
        self.assertEqual(p.current_rate('VES')[0], D('40.00'))
        self.assertIsNone(p.current_rate('ARS'))
        self._rate('ARS', '1200', 180)
        self.assertIsNone(p.current_rate('ARS'))                                       # older than 2 h

    def test_daily_snapshot_keeps_one_fresh_rate_per_day(self):
        from exchange_rates.models import DailyRateSnapshot
        from exchange_rates.tasks import snapshot_daily_rates
        self._rate('VES', '40.00', 10)
        self._rate('ARS', '1200', 300)                                                 # stale: skipped
        with mock.patch('exchange_rates.tasks.connection'):                          # the task closes its DB connection
            self.assertEqual(snapshot_daily_rates(), 'VES')
            self.assertEqual(snapshot_daily_rates(), 'none')                           # idempotent
        today = timezone.now().date()
        self.assertEqual(p.month_start_rate('VES', today.year, today.month),
                         D('40.00') if today.day == 1 else None)
        self.assertEqual(DailyRateSnapshot.objects.filter(date=today).count(), 1)


class HeldSinceTests(SimpleTestCase):
    """Venezuela's month_start basis: the LOWEST running balance since the 1st."""

    def test_spend_everything_then_get_paid_holds_nothing(self):
        # $300 on the 1st, spent by the 5th, salary $300 on the 28th: balance $300, held $0
        events = [ev('p2p_send', 300), ev('income_person', 300, 'received')]
        self.assertEqual(p.held_since(D('300'), events), D('0'))

    def test_money_received_this_month_is_not_held_since_the_1st(self):
        events = [ev('income_person', 50, 'received')]
        self.assertEqual(p.held_since(D('150'), events), D('100'))

    def test_spending_part_keeps_the_rest(self):
        events = [ev('p2p_send', 40)]
        self.assertEqual(p.held_since(D('60'), events), D('60'))

    def test_never_above_the_balance(self):
        events = [ev('p2p_send', 500)]
        self.assertEqual(p.held_since(D('20'), events), D('20'))


class StableStateTests(ProtectionValueTests):
    """A small gain or a reversal is 'stable', never a loss and never hidden."""

    def test_small_gain_and_reversal_are_stable(self):
        lots = [p.Lot(D('100'), D('1150'))]
        self.assertEqual(self._value(rate=('11.55', 0), lots=lots).state, 'stable')     # gain Bs 5 < US$1
        self.assertEqual(self._value(rate=('10.00', 0), lots=lots).state, 'stable')     # the boliviano strengthened
        self.assertEqual(self._value(rate=('12.50', 0), lots=lots).state, 'gained')
        venezuela_calm_month = self._value(country='VE', rate=('35', 0), start_rate='36', net_in=D('100'))
        self.assertEqual((venezuela_calm_month.basis, venezuela_calm_month.state), ('month_start', 'stable'))


class StableGateTests(TestCase):
    """Older apps (no `state`) must never receive a stable result: it would render as a loss."""

    def test_stable_only_when_the_app_asks(self):
        from users.cashflow_schema import MonthSummaryQuery
        from users.models import Account, User
        user = User.objects.create_user(username='gate', email='gate@example.com', password='x', firebase_uid='gate',
                                        phone_country='BO')
        Account.objects.create(user=user, account_type='personal', account_index=0, algorand_address='G' * 58,
                               bsc_address='0x' + '12' * 20)
        stable = p.Protection(currency='BOB', basis='purchase', protected_usd=D('100'), paid_local=D('1150'),
                              today_local=D('1000'), avg_rate=D('11.5'), today_rate=D('10'), quoted_at='t',
                              state='stable')
        info = SimpleNamespace(context=SimpleNamespace(user=user))
        jwt = {'account_type': 'personal', 'account_index': 0, 'business_id': None}
        with mock.patch('users.jwt_context.get_jwt_business_context_with_validation', return_value=jwt), \
             mock.patch('users.protection.protection_value', return_value=stable):
            self.assertIsNone(MonthSummaryQuery().resolve_protection_value(info))
            self.assertEqual(MonthSummaryQuery().resolve_protection_value(info, include_stable=True).state, 'stable')


class NoPurchaseFallbackTests(ProtectionValueTests):
    """BO/AR users who never bought dollars in Confío get the month-start basis."""

    def test_bolivian_without_purchases_compares_with_the_1st(self):
        r = self._value(lots=[], start_rate='11.80', rate=('12.50', 0), net_in=D('100'))
        self.assertEqual((r.basis, r.currency, r.protected_usd, r.paid_local), ('month_start', 'BOB', D('100'), D('1180.00')))

    def test_purchases_still_use_what_was_paid(self):
        r = self._value(lots=[p.Lot(D('100'), D('1150'))], start_rate='11.80', rate=('12.50', 0), net_in=D('100'))
        self.assertEqual(r.basis, 'purchase')
