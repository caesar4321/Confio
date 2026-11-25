"""A hands-off chat trade (the Cuenta inteligente's relayTrade) is shared in
Comunidad like a signed one: by its tx hash, only by its owner, once."""
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone

from smart_account.models import SmartAccount, SmartAccountEvent, SmartRelayTrade
from users.models import Account

from . import account_trades, activity_share
from .activity_share import ActivityShareError
from .models import ActivityShareIntent, CommunityActivityShare
from .test_community import CommunityTestBase, make_user

ACCT = '0x' + 'b2' * 20
OTHER_ACCT = '0x' + 'b3' * 20
NVDA = '0x' + 'd4' * 20
CUSD = '0x' + 'e5' * 20
PLUS = '0x' + 'f6' * 20
USDT = '0x' + '17' * 20
WEI = 10 ** 18
HASH = '0x' + 'ab' * 32


class HandsOffShareTests(CommunityTestBase):
    def setUp(self):
        super().setUp()
        for target, value in (('smart_account.chain.cusd_address', CUSD),
                              ('smart_account.chain.cusd_plus_address', PLUS),
                              ('smart_account.chain.usdt_address', USDT),
                              ('smart_account.chain.confio_address', ''),
                              ('cusd_plus.gm_holdings.registry', {'NVDAon': {'address': NVDA, 'decimals': 18}}),
                              ('cusd_plus.gm_holdings._fallback_registry', {}),
                              ('cusd_plus.crypto_catalog.by_address', None),
                              ('smart_account.relay_trades.asset_token', NVDA),
                              ('inbox.activity_share._ticker_and_name', ('NVDA', 'NVIDIA'))):
            p = patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.user = make_user()
        self.account = self.smart_account(self.user, ACCT)
        self.n = 0

    def smart_account(self, user, address):
        personal = Account.objects.get(user=user, account_type='personal')
        return SmartAccount.all_objects.create(owner_user=user, owner_account=personal, contract_address=address,
                                               status='active')

    def relay(self, user=None, account=None, tx=HASH, status='done', side='buy', kind='stock'):
        self.n += 1
        return SmartRelayTrade.objects.create(
            user=user or self.user, smart_account=account or self.account, nonce=f'n{self.n}', side=side,
            asset_kind=kind, ticker='NVDA', amount_usd=Decimal('100'), status=status, tx_hash=tx,
            amount_in=str(100 * WEI), amount_out=str(2 * WEI), usd_counted=str(100 * WEI))

    def settle(self, tx=HASH, address=ACCT):
        self.n += 1
        event = SmartAccountEvent.objects.create(
            address=address, tx_hash=tx, log_index=0, name='RelayTraded',
            args={'id': '1', 'venue': USDT, 'tokenIn': CUSD, 'tokenOut': NVDA, 'spent': str(100 * WEI),
                  'got': str(2 * WEI), 'usdCounted': str(100 * WEI)},
            block_number=1000 + self.n, block_time=timezone.now())
        return account_trades.index_event(event)

    def test_the_owner_shares_a_settled_hands_off_buy(self):
        self.relay()
        trade = self.settle()
        _row, snap, final = activity_share.preview_activity(self.user, 'stock', HASH)
        self.assertTrue(final)
        self.assertEqual((snap.kind, snap.data['ticker'], snap.data['units'], snap.data['amount_usd']),
                         ('stock_buy', 'NVDA', '2', '100.00'))
        outcome, item = activity_share.share_or_schedule(self.user, None, 'stock', HASH)
        self.assertEqual(outcome, 'published')
        share = CommunityActivityShare.objects.get(content_item=item)
        self.assertEqual((share.account_trade_id, share.unified_transaction_id), (trade.id, None))
        self.assertEqual(item.metadata['activity']['account'], ACCT)
        public = activity_share.public_activity(item.metadata['activity'])
        self.assertNotIn('account', public)

    def test_already_shared_is_refused_and_not_offered_again(self):
        self.relay()
        self.settle()
        activity_share.share_or_schedule(self.user, None, 'stock', HASH)
        self.assertIsNone(activity_share.preview_activity(self.user, 'stock', HASH))
        with self.assertRaises(ActivityShareError) as caught:
            activity_share.share_or_schedule(self.user, None, 'stock', HASH)
        self.assertEqual(caught.exception.code, 'already_shared')

    def test_another_member_cannot_share_it(self):
        self.relay()
        self.settle()
        stranger = make_user('pedro', 'pérez')
        self.assertIsNone(activity_share.preview_activity(stranger, 'stock', HASH))
        with self.assertRaises(ActivityShareError) as caught:
            activity_share.share_or_schedule(stranger, None, 'stock', HASH)
        self.assertEqual(caught.exception.code, 'not_shareable')
        self.assertFalse(CommunityActivityShare.objects.exists())

    def test_a_trade_row_on_an_account_someone_else_owns_is_refused(self):
        stranger = make_user('pedro', 'pérez')
        theirs = self.smart_account(stranger, OTHER_ACCT)
        self.relay(account=theirs)
        self.settle(address=OTHER_ACCT)
        self.assertIsNone(activity_share.preview_activity(self.user, 'stock', HASH))

    def test_a_failed_trade_or_the_wrong_group_is_not_shareable(self):
        self.relay(status='failed')
        self.settle()
        self.assertIsNone(activity_share.preview_activity(self.user, 'stock', HASH))
        SmartRelayTrade.objects.update(status='done')
        self.assertIsNone(activity_share.preview_activity(self.user, 'crypto', HASH))

    def test_before_the_account_trade_is_indexed_the_tap_waits_then_publishes(self):
        self.relay()
        _row, snap, final = activity_share.preview_activity(self.user, 'stock', HASH)
        self.assertFalse(final)
        self.assertEqual((snap.data['units'], snap.data['amount_usd']), ('2', '100.00'))
        outcome, intent = activity_share.share_or_schedule(self.user, None, 'stock', HASH, 'nota')
        self.assertEqual(outcome, 'scheduled')
        self.assertEqual(activity_share.resolve_share_intents(), {'published': 0, 'expired': 0, 'failed': 0})
        trade = self.settle()
        with patch('inbox.community.notify_post_reviewed'):
            self.assertEqual(activity_share.resolve_share_intents()['published'], 1)
        intent = ActivityShareIntent.objects.get(pk=intent.pk)
        self.assertEqual(CommunityActivityShare.objects.get(content_item=intent.content_item).account_trade_id,
                         trade.id)

    def test_one_hands_off_share_never_counts_as_another(self):
        self.relay()
        self.settle()
        second = '0x' + 'cd' * 32
        self.relay(tx=second)
        self.settle(tx=second)
        _o, first_item = activity_share.share_or_schedule(self.user, None, 'stock', HASH)
        _o, second_item = activity_share.share_or_schedule(self.user, None, 'stock', second)
        self.assertFalse(activity_share.has_other_share(first_item, include_pending=True))
        self.assertFalse(activity_share.has_other_share(second_item, include_pending=True))

    def test_a_sale_shows_its_result_against_the_accounts_own_cost(self):
        self.relay()
        self.settle()
        sale = '0x' + 'ef' * 32
        self.relay(tx=sale, side='sell')
        self.n += 1
        event = SmartAccountEvent.objects.create(
            address=ACCT, tx_hash=sale, log_index=0, name='RelayTraded',
            args={'id': '1', 'venue': USDT, 'tokenIn': NVDA, 'tokenOut': CUSD, 'spent': str(WEI),
                  'got': str(60 * WEI), 'usdCounted': str(60 * WEI)},
            block_number=1000 + self.n, block_time=timezone.now())
        account_trades.index_event(event)
        _row, snap, final = activity_share.preview_activity(self.user, 'stock', sale)
        self.assertTrue(final)
        self.assertEqual((snap.kind, snap.data['pnl_usd'], snap.data['pnl_pct']), ('stock_sell', '10.00', '20.00'))

    def test_an_unindexed_earlier_trade_leaves_the_sale_without_a_result(self):
        # Review 2026-11-25: a trade the ledger has not indexed yet must not let a sale freeze a wrong P&L.
        self.relay()
        self.settle()
        SmartAccountEvent.objects.create(
            address=ACCT, tx_hash='0x' + 'cd' * 32, log_index=0, name='RelayTraded',
            args={'id': '2'}, block_number=1000, block_time=timezone.now())   # never indexed
        sale = '0x' + 'ef' * 32
        self.relay(tx=sale, side='sell')
        self.n += 1
        event = SmartAccountEvent.objects.create(
            address=ACCT, tx_hash=sale, log_index=0, name='RelayTraded',
            args={'id': '1', 'venue': USDT, 'tokenIn': NVDA, 'tokenOut': CUSD, 'spent': str(WEI),
                  'got': str(60 * WEI), 'usdCounted': str(60 * WEI)},
            block_number=1000 + self.n, block_time=timezone.now())
        account_trades.index_event(event)
        _row, snap, _final = activity_share.preview_activity(self.user, 'stock', sale)
        self.assertEqual(snap.kind, 'stock_sell')
        self.assertIsNone(snap.data.get('pnl_usd'))
