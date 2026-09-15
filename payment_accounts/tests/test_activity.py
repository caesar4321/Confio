from decimal import Decimal
from unittest import mock
import uuid

from django.test import TestCase, override_settings
from payment_accounts.activity import sync_activity, display_stage, arrival_owned
from payment_accounts.infinia_journeys import create_journey
from payment_accounts.models import InfiniaJourney
from users.models_unified import UnifiedTransactionTable
from notifications.models import Notification
from .test_infinia_journeys import JourneyTests


@override_settings(INFINIA_JOURNEYS_ENABLED=True, INFINIA_PAYMENT_ACCOUNTS_ENABLED=True,
    PAYMENT_BRIDGE_QUOTES_ENABLED=True, PAYMENT_BRIDGE_BSC_ENABLED=True,
    PAYMENT_BRIDGE_POLYGON_ENABLED=True, CUSD_PLUS_7702_ENABLED=True)
class ActivityTests(TestCase):
    setUp = JourneyTests.setUp
    credit = JourneyTests.credit
    inbound = JourneyTests.inbound
    prepared = JourneyTests.prepared
    quote = JourneyTests.quote

    def outgoing(self):
        bridge, _ = self.prepared()
        j = create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
            direction='to_bank', request_id=uuid.uuid4(), bridge=bridge,
            destination=self.dest, minimum_fx_output='30')
        return j, bridge

    def test_outgoing_one_parent_only_after_broadcast(self):
        j, bridge = self.outgoing()
        self.assertIsNone(sync_activity(j.pk))
        bridge.source_tx_hash = '0x'+'ab'*32
        bridge.status = 'submitted'; bridge.save()
        row = sync_activity(j.pk)
        self.assertEqual(row.status, 'PENDING')
        self.assertEqual(Decimal(row.amount), j.money_flow.source_amount)
        self.assertEqual(row.sender_user, self.owner.user)
        sync_activity(j.pk)
        self.assertEqual(UnifiedTransactionTable.objects.filter(local_money_flow=j.money_flow).count(), 1)
        self.assertEqual(Notification.objects.filter(data__local_transfer_id=str(j.internal_id)).count(), 1)
        j.stage='completed'; j.save()
        self.assertEqual(sync_activity(j.pk).status, 'CONFIRMED')

    def incoming_arrived(self):
        j = self.inbound()
        bridge, _ = self.prepared()
        bridge.status='delivered'; bridge.actual_out_units=str(2*10**18)
        bridge.destination_tx_hash='0x'+'cd'*32; bridge.save()
        j.bridge=bridge; j.stage='completed'; j.save()
        return j, bridge

    def mint(self, j, request_id=None, amount=Decimal('2')):
        from blockchain.models import SponsoredBatch
        from conversion.models import Conversion
        tx = '0x'+'ef'*32
        SponsoredBatch.objects.create(user=self.owner.user, user_bsc_address=j.wallet_address,
            kind='mint_cusd', client_request_id=request_id or f'local-mint-{j.internal_id}_a0',
            num_calls=1, calls_json='[]', tx_hash=tx, status='confirmed', gas_limit=500000)
        return Conversion.objects.create(actor_user=self.owner.user, actor_type='user',
            conversion_type='usdt_to_cusd', source='external_deposit', user_bsc_address=j.wallet_address,
            from_amount=amount, to_amount=Decimal('1.982'), gross_amount_exact=amount,
            net_amount_exact=Decimal('1.982'), fee_amount_exact=Decimal('.018'),
            to_transaction_hash=tx, status='SUBMITTED')

    def test_incoming_waits_for_explicit_mint_and_uses_final_net(self):
        j, bridge = self.incoming_arrived()
        self.assertTrue(arrival_owned(bridge.destination_tx_hash, j.wallet_address))
        self.assertEqual(display_stage(j), 'awaiting_wallet_conversion')
        self.assertEqual(sync_activity(j.pk).status, 'PENDING')
        mint = self.mint(j)
        self.assertEqual(sync_activity(j.pk).status, 'PENDING')
        mint.status='COMPLETED'; mint.save()
        row = sync_activity(j.pk)
        self.assertEqual(row.status, 'CONFIRMED')
        self.assertEqual(Decimal(row.amount), Decimal('1.982'))
        self.assertEqual(row.counterparty_user, self.owner.user)
        self.assertFalse(UnifiedTransactionTable.objects.filter(conversion=mint, deleted_at__isnull=True).exists())

    def test_matching_amount_without_request_identity_is_not_linked(self):
        j, _ = self.incoming_arrived()
        mint = self.mint(j, request_id='unrelated')
        mint.status='COMPLETED'; mint.save()
        row = sync_activity(j.pk)
        self.assertEqual(row.status, 'PENDING')
        j.refresh_from_db(); self.assertIsNone(j.wallet_conversion_id)

    def test_wrong_amount_with_request_identity_is_not_linked(self):
        j, _ = self.incoming_arrived()
        self.mint(j, amount=Decimal('3'))
        sync_activity(j.pk)
        j.refresh_from_db(); self.assertIsNone(j.wallet_conversion_id)

    def test_graphql_direction_and_navigation_identity(self):
        from users.graphql_views import UnifiedTransactionType
        j, bridge = self.outgoing()
        bridge.source_tx_hash='0x'+'12'*32; bridge.save()
        row=sync_activity(j.pk)
        self.assertEqual(UnifiedTransactionType.resolve_direction(row, None), 'sent')
        self.assertEqual(UnifiedTransactionType.resolve_local_transfer_id(row, None), str(j.internal_id))

    def test_mint_identity_is_accepted_by_sponsor_validation(self):
        from cusd_plus.schema import _SPONSOR_REQUEST_ID_RE
        self.assertIsNotNone(_SPONSOR_REQUEST_ID_RE.fullmatch(f'local-mint-{uuid.uuid4()}_a0'))

    def test_only_proven_mint_failure_changes_retry_identity(self):
        from payment_accounts.activity import mint_request_id
        from blockchain.models import SponsoredBatch
        j, _ = self.incoming_arrived()
        original = mint_request_id(j)
        self.mint(j)
        batch=SponsoredBatch.objects.get(client_request_id=original+'_a0')
        for state in ['signed', 'sent', 'confirmed', 'reorged', 'dropped']:
            batch.status=state; batch.save()
            self.assertEqual(mint_request_id(j), original)
        batch.status='reverted'; batch.save()
        self.assertEqual(mint_request_id(j), original+'_r1')

    def test_refund_stays_on_original_transfer(self):
        from payment_accounts.journey_schema import InfiniaJourneyType
        j, bridge = self.outgoing()
        bridge.source_tx_hash='0x'+'12'*32
        refunded_hash='0x'+'34'*32
        bridge.status='refunded'
        bridge.binding = dict(bridge.binding, settlement_evidence={
            'transaction_hashes': [refunded_hash], 'token_id': 'BSC:USDT',
            'received_units': '1982000000000000000'})
        bridge.save(); j.refresh_from_db()
        self.assertEqual(display_stage(j), 'refunded')
        self.assertEqual(InfiniaJourneyType.resolve_refund_amount(j, None), '1.982')
        self.assertTrue(arrival_owned(refunded_hash, j.wallet_address))
        self.assertEqual(sync_activity(j.pk).description, 'Envío reembolsado')

    def test_backfill_dry_run_does_not_create_activity(self):
        from django.core.management import call_command
        j, bridge = self.outgoing()
        bridge.source_tx_hash='0x'+'56'*32; bridge.save()
        call_command('backfill_local_transfer_activity', journey=str(j.internal_id))
        self.assertFalse(UnifiedTransactionTable.objects.filter(local_money_flow=j.money_flow).exists())

    def test_linked_conversion_cannot_reappear_after_save(self):
        from users.graphql_views import _visible_unified
        j, _ = self.incoming_arrived()
        mint = self.mint(j); mint.status='COMPLETED'; mint.save()
        sync_activity(j.pk)
        mint.save()  # The legacy mirror writer runs again.
        self.assertFalse(_visible_unified().filter(conversion=mint).exists())

    def test_periodic_repair_recovers_terminal_journey_without_callback(self):
        from payment_accounts.activity import refresh_stale_activity
        j, bridge = self.outgoing()
        bridge.source_tx_hash = '0x'+'78'*32; bridge.save()
        j.stage = 'completed'; j.save()
        refresh_stale_activity()
        self.assertEqual(UnifiedTransactionTable.objects.get(local_money_flow=j.money_flow).status, 'CONFIRMED')

    def test_local_mint_does_not_complete_unrelated_external_deposit(self):
        from types import SimpleNamespace
        from django.utils import timezone
        from users.graphql_views import _external_deposit_conversion, _preload_external_deposit_conversions
        j, _ = self.incoming_arrived()
        mint = self.mint(j); mint.status = 'COMPLETED'; mint.save()
        sync_activity(j.pk)
        receipt = SimpleNamespace(sender_type='external', token_type='USDT',
            recipient_business_id=None, recipient_user_id=self.owner.user_id,
            amount=Decimal('2'), created_at=timezone.now())
        row = SimpleNamespace(transaction_type='send', send_transaction=receipt)
        self.assertIsNone(_external_deposit_conversion(row))
        _preload_external_deposit_conversions([row])
        self.assertIsNone(row._external_deposit_conversion_cache)

    def test_local_savings_mint_does_not_claim_existing_saga(self):
        from conversion.models import Conversion
        from cusd_plus.tasks import record_savings_mint, _reconcile_cusd_fee_event
        from types import SimpleNamespace
        j, _ = self.incoming_arrived()
        saga = Conversion.objects.create(actor_user=self.owner.user, actor_type='user',
            conversion_type='to_savings', from_amount=2, to_amount=2,
            user_bsc_address=j.wallet_address, status='DEST_ARRIVED')
        request_id = f'local-mint-{j.internal_id}_a0'
        with override_settings(CUSD_CONVERSION_FEE_ENABLED=False):
            mint = record_savings_mint(user=self.owner.user, business=None, actor_type='user',
                display_name='', amount_wei=2*10**18, tx_hash='0x'+'98'*32,
                bsc_address=j.wallet_address, request_id=request_id)
        self.assertIsNotNone(mint)
        self.assertNotEqual(mint.pk, saga.pk)
        # Missing best-effort history must also recover a separate record.
        event = dict(gross_wei=2*10**18, fee_wei=18*10**15, net_wei=1982*10**15,
            direction='entry', conversion_type='to_savings', log_index=1, fee_bps=90)
        batch = SimpleNamespace(user_bsc_address=j.wallet_address, kind='subscribe',
            tx_hash='0x'+'97'*32, client_request_id=request_id)
        with mock.patch('cusd_plus.tasks._cusd_fee_events', return_value=[event]):
            recovered = _reconcile_cusd_fee_event(batch=batch, receipt={})
        self.assertNotEqual(recovered[0].pk, saga.pk)
        saga.refresh_from_db()
        self.assertEqual(saga.status, 'DEST_ARRIVED')
        self.assertFalse(saga.to_transaction_hash)

    def test_mint_scanner_race_is_reconciled_to_the_parent(self):
        from send.models import SendTransaction
        j, _ = self.incoming_arrived()
        mint = self.mint(j); mint.status = 'COMPLETED'; mint.save()
        receipt = SendTransaction.all_objects.create(recipient_user=self.owner.user,
            recipient_type='user', recipient_address=j.wallet_address,
            sender_type='external', sender_address='', token_type='CUSD_PLUS',
            amount='1.982', status='CONFIRMED', transaction_hash=mint.to_transaction_hash)
        notice = Notification.objects.create(user=self.owner.user,
            notification_type='SEND_RECEIVED', title='Deposit', message='Deposit',
            data={'tx_hash': mint.to_transaction_hash, 'recipient_address': j.wallet_address})
        row = sync_activity(j.pk)
        receipt.refresh_from_db(); notice.refresh_from_db()
        self.assertIsNotNone(receipt.deleted_at)
        self.assertEqual(notice.data['local_transfer_id'], str(j.internal_id))
        self.assertEqual(row.created_at, j.created_at)

    def test_known_arrival_cannot_be_recreated_as_external_deposit(self):
        from cusd_plus.tasks import _record_deposit_receipt
        j, bridge = self.incoming_arrived()
        with mock.patch('send.models.SendTransaction.all_objects.create') as create:
            _record_deposit_receipt(account=self.owner, is_business=False,
                to_addr=j.wallet_address, from_addr='0x'+'11'*20, amount_usd=Decimal('2'),
                tx_ref=bridge.destination_tx_hash, tx_hash=bridge.destination_tx_hash,
                source='external', conv=None)
        create.assert_not_called()

    def test_completion_push_waits_for_committed_activity(self):
        j, bridge = self.outgoing()
        bridge.source_tx_hash = '0x'+'76'*32; bridge.save()
        with mock.patch('payment_accounts.activity._push_notice') as push:
            with self.captureOnCommitCallbacks(execute=True):
                sync_activity(j.pk)
                push.assert_not_called()
            push.assert_called_once()
