"""Address-keyed ledgers keep only trades signed by the people of the
account that holds the address now (or last held it: its retired row): an
address registered again after its account closed must not show the closed
account's trades."""
from django.test import TestCase
from django.utils import timezone

from cusd_plus import crypto_month, perps_portfolio, stock_month
from cusd_plus.wallet_signers import address_signer_ids
from inbox import activity_share
from users.models import Account, Business, User
from users.models_employee import BusinessEmployee

ADDR = '0x' + 'ab' * 20


def make_user(name):
    user = User(username=name, firebase_uid=name)
    User.objects.bulk_create([user])
    return User.objects.get(username=name)


class AddressSignerTests(TestCase):
    def setUp(self):
        self.owner = make_user('signer-owner')
        self.business = Business.objects.create(name='Tienda S', category='retail')
        self.account = Account.objects.create(
            user=self.owner, account_type='business', account_index=0, business=self.business,
            bsc_address=ADDR.upper().replace('0X', '0x'), is_keyless_migrated=True)

    def batch(self, user, kind='stock_buy', tx='01'):
        from blockchain.models import SponsoredBatch
        return SponsoredBatch.objects.create(
            user=user, user_bsc_address=ADDR, kind=kind, num_calls=2, calls_json='[]',
            tx_hash='0x' + tx * 32, status='confirmed', gas_limit=1, max_fee_wei=1, block_number=10)

    def claim(self):
        """The closed account's address held by someone else's live account."""
        Account.all_objects.filter(pk=self.account.pk).update(deleted_at=timezone.now())
        claimer = make_user('signer-claimer')
        Account.objects.create(user=claimer, account_type='personal', account_index=0,
                               bsc_address=ADDR, is_keyless_migrated=True)
        return claimer

    def test_business_signers_are_owner_and_employees(self):
        cashier = make_user('signer-cashier')
        BusinessEmployee.objects.create(business=self.business, user=cashier, role='cashier')
        self.assertEqual(address_signer_ids(ADDR), {self.owner.pk, cashier.pk})
        self.assertEqual(address_signer_ids('0x' + '00' * 20), frozenset())
        self.assertEqual(address_signer_ids(''), frozenset())

    def test_stock_ledger_drops_the_closed_accounts_trades(self):
        self.batch(self.owner)
        self.assertEqual(len(stock_month.confirmed_trades(ADDR)), 1)
        self.assertEqual(len(activity_share._wallet_trades(ADDR)), 1)
        claimer = self.claim()
        self.assertEqual(stock_month.confirmed_trades(ADDR), [])
        self.assertEqual(activity_share._wallet_trades(ADDR), [])
        self.batch(claimer, tx='02')
        self.assertEqual(len(stock_month.confirmed_trades(ADDR)), 1)

    def test_an_employees_batch_on_the_business_wallet_is_kept(self):
        cashier = make_user('signer-cashier2')
        BusinessEmployee.objects.create(business=self.business, user=cashier, role='cashier')
        self.batch(cashier)
        self.batch(make_user('signer-stranger'), tx='05')  # signed by nobody of this account
        self.assertEqual(len(stock_month.confirmed_trades(ADDR)), 1)

    def test_snapshot_days_of_the_previous_account_are_not_the_claimers(self):
        from datetime import date
        from decimal import Decimal

        from inbox.models import PortfolioDailySnapshot
        from teams import data
        claimer = self.claim()
        day = date(2026, 11, 1)
        row = PortfolioDailySnapshot.objects.create(
            user=self.owner, wallet=ADDR, day=day, daily_return=Decimal('0.5'), ledger_trusted=True)
        self.assertEqual(data._returns([claimer.pk], [day]), {})
        PortfolioDailySnapshot.objects.filter(pk=row.pk).update(user=claimer)
        self.assertIn(claimer.pk, data._returns([claimer.pk], [day]))

    def test_a_closed_accounts_own_history_still_reads_as_its_own(self):
        self.batch(self.owner)
        Account.objects.get(pk=self.account.pk).soft_delete()  # retires the address
        self.assertEqual(address_signer_ids(ADDR), {self.owner.pk})
        self.assertEqual(len(activity_share._wallet_trades(ADDR)), 1)

    def test_team_goals_skip_the_previous_accounts_days_and_buys(self):
        from datetime import date
        from decimal import Decimal
        from types import SimpleNamespace
        from unittest import mock

        from inbox.community import has_invested
        from inbox.models import PortfolioDailySnapshot
        from teams import data
        from teams.models import TeamGoalKind
        claimer = self.claim()
        row = PortfolioDailySnapshot.objects.create(
            user=self.owner, wallet=ADDR, day=date(2026, 11, 1), value_end_usd=Decimal('900'), ledger_trusted=True)
        buy = self.batch(self.owner, tx='06')  # this week, the previous account's
        team = SimpleNamespace()
        invested = SimpleNamespace(kind=TeamGoalKind.INVESTED_USD)
        weekly = SimpleNamespace(kind=TeamGoalKind.WEEKLY_INVESTORS)
        member = SimpleNamespace(user_id=claimer.pk)
        with mock.patch.object(data, '_visible', return_value=[member]):
            self.assertEqual(data.goal_contributors(team), 0)
            self.assertEqual(data.goal_progress(team, invested), 0)
            self.assertEqual(data.goal_progress(team, weekly), 0)
            self.assertFalse(has_invested(claimer.pk))
            # The member's own buy counts (no returns day of theirs yet)...
            type(buy).objects.filter(pk=buy.pk).update(user=claimer)
            self.assertTrue(has_invested(claimer.pk))
            # ...and so does their own day.
            PortfolioDailySnapshot.objects.filter(pk=row.pk).update(user=claimer)
            self.assertEqual(data.goal_contributors(team), 1)
            self.assertEqual(data.goal_progress(team, invested), Decimal('900'))
            self.assertEqual(data.goal_progress(team, weekly), 1)
            self.assertTrue(has_invested(claimer.pk))

    def test_plays_and_award_readiness_skip_the_previous_account(self):
        from datetime import date, timedelta
        from decimal import Decimal
        from types import SimpleNamespace
        from unittest import mock

        from inbox.models import PortfolioDailySnapshot
        from teams import data, league
        from blockchain.models import CryptoTrade

        def crypto_buy(user, tx):
            batch = self.batch(user, kind='crypto_buy', tx=tx)
            CryptoTrade.objects.create(batch=batch, wallet=ADDR, symbol='BTCB', kind='crypto_buy',
                                       units=Decimal('0.001'), usd=Decimal('66'), traded_at=timezone.now())
            return batch
        crypto_buy(self.owner, '08')  # the previous account's buy, after the member joined
        claimer = self.claim()
        member = SimpleNamespace(user_id=claimer.pk, user=claimer,
                                 joined_at=timezone.now() - timedelta(days=1))
        with mock.patch.object(data, '_visible', return_value=[member]), \
                mock.patch.object(data, '_names', return_value={}):
            self.assertEqual(data.plays(SimpleNamespace()), [])
            mine = crypto_buy(claimer, '09')
            self.assertEqual([p['id'] for p in data.plays(SimpleNamespace())], [mine.id])
        day1, day2 = date(2026, 11, 1), date(2026, 11, 2)
        # Only the previous account's day before, nothing on the last day:
        # the current holder has no final day to wait for.
        PortfolioDailySnapshot.objects.create(user=self.owner, wallet=ADDR, day=day1,
                                              daily_return=Decimal('0'), ledger_trusted=True,
                                              ledger_sig='abc' + 'p')
        self.assertTrue(league.month_complete([day1, day2]))
        # The holder's own day does wait for its final day.
        PortfolioDailySnapshot.objects.filter(wallet=ADDR).update(user=claimer, ledger_sig='abc')
        self.assertFalse(league.month_complete([day1, day2]))

    def test_an_unchanged_day_is_rewritten_for_its_holder(self):
        from datetime import date
        from decimal import Decimal

        from inbox import portfolio_returns
        from inbox.models import PortfolioDailySnapshot
        claimer = self.claim()
        values = {'daily_return': Decimal('0'), 'ledger_trusted': False, 'ledger_sig': ''}
        row = PortfolioDailySnapshot.objects.create(user=self.owner, wallet=ADDR, day=date(2026, 11, 1), **values)
        self.assertTrue(portfolio_returns._store(claimer, ADDR, row.day, values, row))
        row.refresh_from_db()
        self.assertEqual(row.user_id, claimer.pk)
        self.assertFalse(portfolio_returns._store(claimer, ADDR, row.day, values, row))

    def test_needs_write_rewrites_a_final_day_of_another_person(self):
        from types import SimpleNamespace
        from unittest import mock

        from inbox import portfolio_returns
        row = SimpleNamespace(user_id=self.owner.pk)
        with mock.patch.object(portfolio_returns, '_is_final', return_value=True):
            self.assertTrue(portfolio_returns._needs_write(row, None, holder=self.owner.pk + 1))
            self.assertFalse(portfolio_returns._needs_write(row, None, holder=self.owner.pk))

    def test_all_time_runs_count_only_the_holders_days(self):
        from datetime import date, timedelta
        from decimal import Decimal

        from inbox.models import PortfolioDailySnapshot
        from teams import league
        claimer = self.claim()
        first = date(2026, 11, 1)
        for n in range(3):
            PortfolioDailySnapshot.objects.create(
                user=self.owner, wallet=ADDR, day=first + timedelta(days=n), daily_return=Decimal('0.01'),
                gain_usd=Decimal('1'), value_start_usd=Decimal('100'), net_flow_usd=Decimal('0'),
                ledger_trusted=True)

        def runs():
            return league._runs(PortfolioDailySnapshot, 'wallet', 'daily_return',
                                f'ledger_trusted AND daily_return IS NOT NULL AND {league._OWN_SNAPSHOT_DAY}',
                                [ADDR], first, first + timedelta(days=2), gain='gain_usd',
                                start='value_start_usd', capital=league._SNAPSHOT_CAPITAL)
        self.assertEqual(runs(), {})
        PortfolioDailySnapshot.objects.filter(wallet=ADDR).update(user=claimer)
        self.assertEqual(runs()[ADDR].days, 3)
        # ...and the all-time table is the one that applies it.
        from unittest import mock
        with mock.patch.object(league, '_runs', return_value={}) as read:
            league._investor_table_all_time([first], {claimer.pk: ADDR})
        self.assertIn(league._OWN_SNAPSHOT_DAY, read.call_args.args[3])

    def test_a_closed_business_keeps_its_employees_trades(self):
        cashier = make_user('signer-cashier3')
        BusinessEmployee.objects.create(business=self.business, user=cashier, role='cashier')
        self.batch(cashier)
        Account.objects.get(pk=self.account.pk).soft_delete()
        self.assertEqual(address_signer_ids(ADDR), {self.owner.pk, cashier.pk})
        self.assertEqual(len(stock_month.confirmed_trades(ADDR)), 1)

    def test_a_closed_unretired_account_still_reads_its_own(self):
        self.batch(self.owner)
        Account.all_objects.filter(pk=self.account.pk).update(deleted_at=timezone.now())
        self.assertEqual(address_signer_ids(ADDR), {self.owner.pk})
        self.assertEqual(len(stock_month.confirmed_trades(ADDR)), 1)

    def test_a_retired_row_without_its_account_names_its_person(self):
        from users.models import RetiredWalletAddress
        Account.objects.filter(pk=self.account.pk).update(bsc_address='0x' + 'ef' * 20)
        RetiredWalletAddress.objects.create(chain='bsc', address=ADDR, account=None, user=self.owner)
        self.assertEqual(address_signer_ids(ADDR), {self.owner.pk})

    def test_shares_and_copies_refuse_the_previous_accounts_trade(self):
        from unittest import mock

        from inbox.community import CommunityPostError
        from teams import data
        from teams.models import CopiedPlay
        theirs = self.batch(self.owner)
        claimer = self.claim()
        mine = self.batch(claimer, tx='07')
        self.assertTrue(activity_share._not_own(claimer, theirs))
        self.assertFalse(activity_share._not_own(claimer, mine))
        viewer = make_user('signer-viewer')
        with mock.patch('teams.eligibility.eligible_user_ids', return_value={claimer.pk}), \
                mock.patch('inbox.community.portfolio_access', return_value='open') as access:
            with self.assertRaises(CommunityPostError):
                data.copy_play(viewer, theirs.id)
            access.assert_not_called()   # refused as not the holder's buy, before anything else
            with self.assertRaises(CommunityPostError):
                data.copy_play(viewer, mine.id)   # unreadable test calls; but it gets past the guard
            access.assert_called()
        self.assertFalse(CopiedPlay.objects.exists())

    def test_a_reconciled_wallets_old_address_reads_as_its_account(self):
        from users.models import RetiredWalletAddress
        self.batch(self.owner)
        Account.objects.filter(pk=self.account.pk).update(bsc_address='0x' + 'cd' * 20)
        self.assertEqual(address_signer_ids(ADDR), frozenset())
        RetiredWalletAddress.objects.create(chain='bsc', address=ADDR, account=self.account, user=self.owner)
        self.assertEqual(address_signer_ids(ADDR), {self.owner.pk})

    def test_crypto_ledger_drops_the_closed_accounts_trades(self):
        from decimal import Decimal

        from blockchain.models import CryptoTrade
        b = self.batch(self.owner, kind='crypto_buy')
        CryptoTrade.objects.create(batch=b, wallet=ADDR, symbol='BTCB', kind='crypto_buy',
                                   units=Decimal('0.001'), usd=Decimal('66'), traded_at=timezone.now())
        self.batch(self.owner, kind='crypto_sell', tx='03')  # confirmed, no ledger row: '?'
        self.assertEqual(len(crypto_month.confirmed_trades(ADDR)), 2)
        self.assertEqual(len(activity_share._crypto_wallet_trades(ADDR)), 2)
        self.claim()
        self.assertEqual(crypto_month.confirmed_trades(ADDR), [])
        self.assertEqual(activity_share._crypto_wallet_trades(ADDR), [])

    def test_perps_episodes_drop_the_closed_accounts_positions(self):
        from decimal import Decimal

        from blockchain.models import PerpMarket, PerpPosition
        market = PerpMarket.objects.create(coin='BTC', dex='', asset_id=0, sz_decimals=5, max_leverage=40,
                                           collateral='USDC', synced_at=timezone.now())
        batch = self.batch(self.owner, kind='perps_open', tx='04')
        PerpPosition.objects.create(user=self.owner, wallet=ADDR, market=market, side='long', leverage=5,
                                    margin_usd=Decimal('20'), state='open', open_batch=batch,
                                    credited_usdc=Decimal('19.9'), entry_avg_px=Decimal('100000'),
                                    size=Decimal('0.00099'), opened_at=timezone.now())
        # Found while the owner holds the address (no settlement row: unknown)...
        with self.assertRaises(perps_portfolio.PerpsLedgerUnknown):
            perps_portfolio.episodes(ADDR)
        self.claim()
        # ...and not at all once someone else's account holds it.
        self.assertEqual(perps_portfolio.episodes(ADDR), [])
