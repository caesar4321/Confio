"""Daily cUSD+ snapshots and "Tu ahorro ganó" earnings (tu-mes-insights R20/R26/R28)."""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from cusd_plus import savings_snapshots as snaps

WAD = 10 ** 18


class SavingsEarnedTests(TestCase):
    def setUp(self):
        from users.models import Account, User
        self.user = User.objects.create_user(username='saver', email='saver@example.com', password='x',
                                             firebase_uid='saver')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0,
                                              algorand_address='S' * 58, bsc_address='0x' + 'ef' * 20)

    def _price(self, d, pps, failed=()):
        from users.models_cashflow import CusdPlusPriceSnapshot
        CusdPlusPriceSnapshot.objects.create(date=d, pps_wad=pps, block_number=1, complete=True,
                                             failed_account_ids=list(failed))

    def _hold(self, d, shares):
        from users.models_cashflow import CusdPlusHoldingSnapshot
        CusdPlusHoldingSnapshot.objects.create(account=self.account, date=d, shares_raw=shares, block_number=1)

    def test_daily_accrual_sums_and_credits_the_earlier_day(self):
        # 100 shares; price +0.001 per day across Sep 1→4
        for i, d in enumerate([date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]):
            self._price(d, WAD + i * 10 ** 15)
            self._hold(d, 100 * WAD)
        total, daily = snaps.savings_earned(self.account.id, 2026, 9, today=date(2026, 9, 3))
        # today = 3rd → accruals of the 1st and 2nd are known
        self.assertEqual([d for d, _ in daily], [date(2026, 9, 1), date(2026, 9, 2)])
        self.assertEqual(total, Decimal('0.2'))

    def test_zero_share_day_counts_as_zero_not_missing(self):
        self._price(date(2026, 9, 1), WAD); self._hold(date(2026, 9, 1), 100 * WAD)
        self._price(date(2026, 9, 2), WAD + 10 ** 15)                 # withdrew everything: no holding row
        self._price(date(2026, 9, 3), WAD + 2 * 10 ** 15)
        total, daily = snaps.savings_earned(self.account.id, 2026, 9, today=date(2026, 9, 3))
        self.assertEqual([u for _, u in daily], [Decimal('0.1'), Decimal('0')])
        self.assertEqual(total, Decimal('0.1'))

    def test_missing_day_or_failed_read_hides_the_month(self):
        self._price(date(2026, 9, 1), WAD); self._hold(date(2026, 9, 1), WAD)
        self._price(date(2026, 9, 3), WAD + 10 ** 15)                 # the 2nd is missing
        self.assertIsNone(snaps.savings_earned(self.account.id, 2026, 9, today=date(2026, 9, 4)))

        from users.models_cashflow import CusdPlusPriceSnapshot
        CusdPlusPriceSnapshot.objects.all().delete()
        self._price(date(2026, 9, 1), WAD, failed=[self.account.id])
        self._price(date(2026, 9, 2), WAD + 10 ** 15)
        self.assertIsNone(snaps.savings_earned(self.account.id, 2026, 9, today=date(2026, 9, 2)))

    def test_first_day_of_the_month_has_nothing_yet(self):
        self.assertEqual(snaps.savings_earned(self.account.id, 2026, 9, today=date(2026, 9, 1)), (Decimal('0'), []))

    def test_past_month_needs_the_next_months_first_snapshot(self):
        for d in range(1, 31):
            self._price(date(2026, 9, d), WAD + d * 10 ** 12)
        self.assertIsNone(snaps.savings_earned(self.account.id, 2026, 9, today=date(2026, 10, 20)))
        self._price(date(2026, 10, 1), WAD + 31 * 10 ** 12)
        total, daily = snaps.savings_earned(self.account.id, 2026, 9, today=date(2026, 10, 20))
        self.assertEqual((len(daily), total), (30, Decimal('0')))     # no holdings → 0 each day


class SnapshotDayTests(TestCase):
    def setUp(self):
        from users.models import Account, User
        self.accounts = []
        for i in range(3):
            u = User.objects.create_user(username=f'h{i}', email=f'h{i}@example.com', password='x', firebase_uid=f'h{i}')
            self.accounts.append(Account.objects.create(
                user=u, account_type='personal', account_index=0, algorand_address=str(i) * 58,
                bsc_address='0x' + format(i + 1, '040x')))
        self.registered = {a.bsc_address.lower(): a.id for a in self.accounts}

    def _run(self, balances_side_effect):
        with mock.patch.object(snaps.vault, 'vault_address', return_value='0x' + '11' * 20), \
             mock.patch.object(snaps.vault, '_rpc', return_value=hex(1234)), \
             mock.patch.object(snaps, '_pps_at', return_value=WAD), \
             mock.patch.object(snaps, '_balances_at', side_effect=balances_side_effect), \
             mock.patch.object(snaps, 'CHUNK', 2):
            return snaps.snapshot_day(date(2026, 9, 5))

    def test_writes_nonzero_holdings_at_the_pinned_block(self):
        def balances(_token, addresses, block):
            self.assertEqual(block, 1234)
            return {a: (0 if a.endswith('1') else 5 * WAD) for a in addresses}
        self.assertTrue(self._run(balances).startswith('ok holders=2 failed=0'))
        from users.models_cashflow import CusdPlusHoldingSnapshot, CusdPlusPriceSnapshot
        price = CusdPlusPriceSnapshot.objects.get(date=date(2026, 9, 5))
        self.assertEqual((price.block_number, price.complete, price.failed_account_ids), (1234, True, []))
        self.assertEqual(CusdPlusHoldingSnapshot.objects.filter(date=date(2026, 9, 5)).count(), 2)
        self.assertEqual(self._run(balances), 'exists')                 # idempotent

    def test_failing_batch_is_retried_then_only_its_accounts_are_marked(self):
        calls = []
        def balances(_token, addresses, block):
            calls.append(tuple(addresses))
            if len(addresses) == 1:                                     # the second batch always fails
                raise RuntimeError('rpc down')
            return {a: WAD for a in addresses}
        self._run(balances)
        from users.models_cashflow import CusdPlusPriceSnapshot
        price = CusdPlusPriceSnapshot.objects.get(date=date(2026, 9, 5))
        self.assertEqual(len(price.failed_account_ids), 1)
        self.assertEqual(sum(1 for c in calls if len(c) == 1), snaps.BATCH_RETRIES)
