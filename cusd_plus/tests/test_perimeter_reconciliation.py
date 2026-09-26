"""Finalized chain evidence must reach Movido without a client callback."""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from conversion.models import Conversion
from cusd_plus.tasks import _reconcile_cusd_fee_event
from ramps.metrics import fund_flow_breakdown
from users.models import Account, User


class PerimeterReconciliationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='perimeter', firebase_uid='perimeter')
        self.wallet = '0x' + 'a' * 40
        Account.objects.create(user=self.user, account_type='personal', account_index=0,
                               bsc_address=self.wallet)
        self.batch = SimpleNamespace(user_bsc_address=self.wallet, kind='subscribe',
                                     tx_hash='0x' + 'ab' * 32, client_request_id='')
        self.event = dict(gross_wei=10 * 10**18, fee_wei=9 * 10**16,
                          net_wei=991 * 10**16, direction='entry',
                          conversion_type='to_savings', log_index=7, fee_bps=90)

    def reconcile(self):
        with patch('cusd_plus.tasks._cusd_fee_events', return_value=[self.event]):
            return _reconcile_cusd_fee_event(batch=self.batch, receipt={})[0]

    def test_finalized_entry_without_foreground_history_counts_once(self):
        row = self.reconcile()
        self.assertEqual(row.status, 'COMPLETED')
        completed_at = row.completed_at
        self.assertEqual(self.reconcile().pk, row.pk)
        row.refresh_from_db()
        self.assertEqual(row.completed_at, completed_at)
        flow = fund_flow_breakdown()
        self.assertEqual((flow['deposited_usd'], flow['deposit_count']), (Decimal('10'), 1))

    def test_finalized_event_recovers_failed_entry(self):
        row = Conversion.objects.create(actor_user=self.user, actor_type='user',
            conversion_type='to_savings', from_amount=10, to_amount=10,
            user_bsc_address=self.wallet, to_transaction_hash=self.batch.tx_hash,
            status='FAILED', error_message='stale confirmation')
        self.assertEqual(self.reconcile().pk, row.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, 'COMPLETED')
        self.assertEqual(row.error_message, '')

    def test_finalized_entry_claims_arrived_saga(self):
        row = Conversion.objects.create(actor_user=self.user, actor_type='user',
            conversion_type='to_savings', from_amount=11, to_amount=10,
            user_bsc_address=self.wallet, status='DEST_ARRIVED')
        self.assertEqual(self.reconcile().pk, row.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, 'COMPLETED')
        self.assertEqual(row.from_amount, Decimal('10'))
        self.assertEqual(Conversion.objects.count(), 1)

    def test_hash_case_does_not_duplicate_a_finalized_event(self):
        row = self.reconcile()
        self.batch.tx_hash = '0x' + 'AB' * 32
        self.assertEqual(self.reconcile().pk, row.pk)
        self.assertEqual(Conversion.objects.count(), 1)

    def test_same_actor_other_wallet_saga_is_not_claimed(self):
        saga = Conversion.objects.create(actor_user=self.user, actor_type='user',
            conversion_type='to_savings', from_amount=10, to_amount=10,
            user_bsc_address='0x' + 'b' * 40, status='DEST_ARRIVED')
        self.assertNotEqual(self.reconcile().pk, saga.pk)
        saga.refresh_from_db()
        self.assertEqual(saga.status, 'DEST_ARRIVED')

    def test_named_mint_claims_its_saga_not_the_oldest_equal_arrival(self):
        def arrived():
            return Conversion.objects.create(actor_user=self.user, actor_type='user',
                conversion_type='to_savings', from_amount=10, to_amount=10,
                user_bsc_address=self.wallet, status='DEST_ARRIVED')
        older, newer = arrived(), arrived()
        self.batch.client_request_id = f'savings-mint-{newer.internal_id}_r1_a0'
        self.assertEqual(self.reconcile().pk, newer.pk)
        self.assertEqual(self.reconcile().pk, newer.pk)
        older.refresh_from_db()
        self.assertEqual(older.status, 'DEST_ARRIVED')
        self.assertEqual(fund_flow_breakdown()['deposit_count'], 1)

    def test_named_mint_cannot_consume_unrelated_saga(self):
        import uuid
        saga = Conversion.objects.create(actor_user=self.user, actor_type='user',
            conversion_type='to_savings', from_amount=10, to_amount=10,
            user_bsc_address=self.wallet, status='DEST_ARRIVED')
        self.batch.client_request_id = f'savings-mint-{uuid.uuid4()}_a0'
        self.assertNotEqual(self.reconcile().pk, saga.pk)
        saga.refresh_from_db()
        self.assertEqual(saga.status, 'DEST_ARRIVED')

    def test_arrived_saga_can_settle_into_universal_cusd_once(self):
        from cusd_plus.tasks import record_cusd_mint
        saga = Conversion.objects.create(actor_user=self.user, actor_type='user',
            conversion_type='to_savings', from_amount=10, to_amount=10,
            user_bsc_address=self.wallet, status='DEST_ARRIVED')
        mint = record_cusd_mint(user=self.user, business=None, actor_type='user',
            display_name='', amount_wei=10 * 10**18, tx_hash=self.batch.tx_hash,
            bsc_address=self.wallet)
        self.assertIsNone(mint)
        self.event['conversion_type'] = 'usdt_to_cusd'
        self.assertEqual(self.reconcile().pk, saga.pk)
        saga.refresh_from_db()
        self.assertEqual((saga.status, saga.conversion_type, saga.to_asset_id),
                         ('COMPLETED', 'usdt_to_cusd', 'CUSD_BSC'))
        self.assertEqual(Conversion.objects.count(), 1)

    def test_replay_prefers_bound_event_to_newer_unbound_row(self):
        original = self.reconcile()
        Conversion.objects.create(actor_user=self.user, actor_type='user',
            conversion_type='to_savings', from_amount=10, to_amount=10,
            user_bsc_address=self.wallet, to_transaction_hash=self.batch.tx_hash,
            status='SUBMITTED')
        self.assertEqual(self.reconcile().pk, original.pk)

    @override_settings(CUSD_VAULT_ADDRESS='0x' + 'c' * 40,
                       CUSD_VAULT_FEE_EVENTS_START_BLOCK=1, BSC_CHAIN_ID=56)
    def test_scanner_recovers_entry_on_rpc_with_fifty_block_limit(self):
        from eth_utils import keccak
        from conversion.models import CusdFeeScanState
        from cusd_plus.tasks import monitor_cusd_fee_events
        log = {
            'address': '0x' + 'c' * 40,
            'topics': ['0x' + keccak(text='SavingsEntrySettled(uint256,uint256,uint256,uint256)').hex()],
            'data': '0x' + ''.join(f'{value:064x}' for value in (
                self.event['gross_wei'], self.event['fee_wei'], self.event['net_wei'], 90)),
            'logIndex': '0x7', 'transactionHash': self.batch.tx_hash,
        }

        def rpc(method, params):
            if method == 'eth_getLogs':
                lo, hi = int(params[0]['fromBlock'], 16), int(params[0]['toBlock'], 16)
                if hi - lo + 1 > 50:
                    raise RuntimeError('block range exceeds 50')
                return [log] if lo <= 51 <= hi else []
            if method == 'eth_getTransactionByHash':
                return {'from': self.wallet}
            if method == 'eth_getBlockByNumber':
                return {'hash': '0x' + 'f' * 64}
            raise AssertionError(method)

        cache.delete('cusd_fee_scan_lock:56')
        self.addCleanup(cache.delete, 'cusd_fee_scan_lock:56')
        with patch('cusd_plus.tasks._rpc', side_effect=rpc), \
                patch('cusd_plus.tasks._finalized_block_number', return_value=51):
            self.assertEqual(monitor_cusd_fee_events.run(), 1)
        self.assertEqual(Conversion.objects.get().status, 'COMPLETED')
        self.assertEqual(CusdFeeScanState.objects.get(chain_id=56).last_finalized_block, 51)
