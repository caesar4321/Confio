"""Comunidad shares for crypto & metals swaps (group 'crypto')."""
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone

from blockchain.models import CryptoTrade, SponsoredBatch
from users.models import Account
from users.models_unified import UnifiedTransactionTable
from . import activity_share
from .activity_share import CRYPTO_BUY, CRYPTO_SELL
from .test_activity_share import as_item, trade
from .test_community import CommunityTestBase, make_user

WALLET = '0x' + 'c1' * 20


def crypto_buy_activity(**extra):
    return {'kind': CRYPTO_BUY, 'symbol': 'BTCB', 'ticker': 'BTC', 'name': 'Bitcoin', 'category': 'crypto',
            'units': '0.0001', 'amount_usd': '10.00', 'price_usd': '100000.0000', 'date': '2026-10-19',
            'wallet': WALLET, 'batch_id': 1, 'show_amount': True, **extra}


class CryptoPnlTests(CommunityTestBase):
    def payload(self, activity, trades, prices):
        with patch.object(activity_share, '_crypto_wallet_trades', return_value=trades), \
                patch.object(activity_share, '_crypto_price_map', return_value=prices), \
                patch.object(activity_share, '_price_map', side_effect=AssertionError('stock prices')):
            return activity_share.activity_payloads([as_item(activity)])[1]

    def test_open_crypto_purchase_uses_pancakeswap_prices(self):
        trades = [(1, trade(CRYPTO_BUY, '0.0001', '10', symbol='BTCB'))]
        public = self.payload(crypto_buy_activity(), trades, {'BTCB': Decimal('110000')})
        self.assertEqual(public['position'], 'open')
        self.assertEqual(public['pnl_pct'], '10.00')
        self.assertEqual(public['pnl_usd'], '1.00')
        self.assertEqual(public['category'], 'crypto')
        self.assertNotIn('wallet', public)

    def test_sold_out_crypto_purchase_freezes(self):
        trades = [(1, trade(CRYPTO_BUY, '0.0001', '10', symbol='BTCB')),
                  (2, trade(CRYPTO_SELL, '0.0001', '9', symbol='BTCB', minutes=5))]
        public = self.payload(crypto_buy_activity(), trades, {'BTCB': Decimal('999999')})
        self.assertEqual(public['position'], 'closed')
        self.assertEqual(public['pnl_pct'], '-10.00')

    def test_realized_pnl_on_a_crypto_sale(self):
        trades = [(1, trade(CRYPTO_BUY, '2', '20', symbol='WBNB')), (2, trade(CRYPTO_SELL, '1', '13', symbol='WBNB'))]
        self.assertEqual(activity_share._realized(trades, 2), (Decimal('10'), Decimal('13')))

    def test_headline(self):
        self.assertEqual(activity_share.activity_headline(crypto_buy_activity()), 'Compró BTC · US$10.00')
        sale = crypto_buy_activity(kind=CRYPTO_SELL, ticker='XAUT', pnl_pct='2.50')
        self.assertEqual(activity_share.activity_headline(sale), 'Vendió XAUT · US$10.00 · +2.50%')


class CryptoSnapshotTests(CommunityTestBase):
    def setUp(self):
        super().setUp()
        self.member = make_user('cryptosharer')
        Account.objects.filter(user=self.member).update(bsc_address=WALLET)
        if not Account.objects.filter(user=self.member, bsc_address=WALLET).exists():
            Account.objects.create(user=self.member, account_type='personal', account_index=0, bsc_address=WALLET)

    def _swap(self, kind, units, usd, tx='0x' + 'ab' * 32):
        batch = SponsoredBatch.objects.create(
            user=self.member, user_bsc_address=WALLET, kind=kind, num_calls=2, calls_json='[]',
            tx_hash=tx, status='confirmed', gas_limit=1, max_fee_wei=1)
        CryptoTrade.objects.create(batch=batch, wallet=WALLET, symbol='BTCB', kind=kind,
                                   units=Decimal(units), usd=Decimal(usd), traded_at=timezone.now())
        row = UnifiedTransactionTable.objects.create(
            sponsored_batch=batch, transaction_type='send', amount=usd, token_type='CUSD_PLUS',
            amount_denomination='USD_VALUE', status='CONFIRMED', transaction_hash=tx,
            description=f"Cripto: {'Compra' if kind == CRYPTO_BUY else 'Venta'} de BTC",
            sender_user=self.member, sender_type='user', sender_address=WALLET,
            counterparty_type='business', counterparty_display_name='PancakeSwap',
            from_address=WALLET, to_address='0x' + '5a' * 20, transaction_date=timezone.now())
        return batch, row

    def test_a_confirmed_buy_is_shareable_in_the_crypto_group(self):
        batch, row = self._swap(CRYPTO_BUY, '0.0001', '10')
        snap = activity_share.snapshot_for(row, self.member)
        self.assertEqual(snap.kind, CRYPTO_BUY)
        self.assertEqual(snap.data['ticker'], 'BTC')
        self.assertEqual(snap.data['amount_usd'], '10.00')
        found = activity_share.find_activity(self.member, group='crypto', reference=batch.tx_hash)
        self.assertIsNotNone(found)
        self.assertIsNone(activity_share.find_activity(self.member, group='stock', reference=batch.tx_hash))

    def test_a_sale_carries_realized_pnl(self):
        self._swap(CRYPTO_BUY, '0.0002', '20', tx='0x' + '01' * 32)
        _batch, row = self._swap(CRYPTO_SELL, '0.0001', '12', tx='0x' + '02' * 32)
        snap = activity_share.snapshot_for(row, self.member)
        self.assertEqual(snap.data['pnl_usd'], '2.00')
        self.assertEqual(snap.data['pnl_pct'], '20.00')

    def test_someone_else_cannot_share_it(self):
        _batch, row = self._swap(CRYPTO_BUY, '0.0001', '10')
        self.assertIsNone(activity_share.snapshot_for(row, make_user('stranger')))


class LegacyKindTests(CommunityTestBase):
    def test_older_builds_get_the_stock_twin_newer_get_crypto(self):
        from django.test import override_settings

        from .schema import _client_kind

        old = {'HTTP_X_CONFIO_VERSION': '5.2.5'}
        new = {'HTTP_X_CONFIO_VERSION': '5.3.0'}
        self.assertEqual(_client_kind('crypto_sell', old), 'stock_sell')
        self.assertEqual(_client_kind('crypto_buy', {}), 'stock_buy')
        with override_settings(CRYPTO_SHARE_MIN_APP_VERSION='5.3.0'):
            self.assertEqual(_client_kind('crypto_sell', new), 'crypto_sell')
            self.assertEqual(_client_kind('crypto_sell', old), 'stock_sell')
        self.assertEqual(_client_kind('top_up', old), 'top_up')


class MissingLedgerTests(CryptoSnapshotTests):
    def test_a_confirmed_swap_without_its_ledger_row_hides_pnl(self):
        self._swap(CRYPTO_BUY, '0.0002', '20', tx='0x' + '01' * 32)
        # A confirmed buy whose ledger row never got written.
        SponsoredBatch.objects.create(
            user=self.member, user_bsc_address=WALLET, kind=CRYPTO_BUY, num_calls=2, calls_json='[]',
            tx_hash='0x' + '03' * 32, status='confirmed', gas_limit=1, max_fee_wei=1)
        _batch, row = self._swap(CRYPTO_SELL, '0.0001', '12', tx='0x' + '02' * 32)
        snap = activity_share.snapshot_for(row, self.member)
        self.assertNotIn('pnl_usd', snap.data)
