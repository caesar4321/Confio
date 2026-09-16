from datetime import timedelta
from decimal import Decimal
from unittest import mock
import uuid

from django.test import TestCase, override_settings
from django.utils import timezone

from payment_accounts.models import FinancialAccount, AccountCapability, LedgerEntry, PayoutDestination, InfiniaJourney, MoneyOperation
from payment_accounts.infinia_journeys import create_journey, advance_journey
from payment_accounts.bridge_execution import reconcile_provider_credit
from payment_accounts.services import PaymentAccountError, _sync_flow_status
from .test_bridge import BridgeQuoteTests
from .test_bridge_execution import BridgeExecutionTests, DEST_HASH


@override_settings(INFINIA_JOURNEYS_ENABLED=True, INFINIA_PAYMENT_ACCOUNTS_ENABLED=True,
    PAYMENT_BRIDGE_QUOTES_ENABLED=True, PAYMENT_BRIDGE_BSC_ENABLED=True, PAYMENT_BRIDGE_POLYGON_ENABLED=True,
    CUSD_PLUS_7702_ENABLED=True)
class JourneyTests(TestCase):
    quote = BridgeQuoteTests.quote
    prepared = BridgeExecutionTests.prepared

    def setUp(self):
        BridgeQuoteTests.setUp(self)
        self.crypto = self.instruction.financial_account
        self.crypto.provider_account_id = 'crypto'; self.crypto.save()
        self.local = FinancialAccount.objects.create(provider_profile=self.crypto.provider_profile,
            provider_account_id='local', country='PER', asset='PEN', status='active', ownership_structure='provider_named',
            payin_rail='BANK', payin_document_country='PE')
        profile = self.local.provider_profile
        profile.identity_snapshot = {'full_name': 'Holder', 'document_number': '123',
            'document_type': 'DNI', 'document_issuing_country': 'PE'}
        profile.save(update_fields=['identity_snapshot'])
        AccountCapability.objects.create(financial_account=self.local, capability='receive_same_name', status='enabled')
        for account in (self.local, self.crypto):
            for capability in ('convert', 'send_third_party'):
                AccountCapability.objects.create(financial_account=account, capability=capability, status='enabled')
        self.dest = PayoutDestination.objects.create(confio_account=self.owner, provider='infinia', kind='bank_account',
            country='PER', asset='PEN', label='Bank', holder_name='Holder', details={'type':'ACCOUNT_PERU','accountNumber':'123'})
        self.policies = mock.patch('payment_accounts.infinia_journeys.enforce_and_record').start()
        self.submit = mock.patch('payment_accounts.infinia_journeys.submit_money_operation', side_effect=lambda op: op).start()
        self.api = mock.Mock()
        self.api.find_operation.return_value = []
        from types import SimpleNamespace
        from payment_accounts.infinia_bridge import prepare_infinia_bridge
        from .test_bridge_execution import build, binding, tokens
        from payment_accounts import bridge_chain as chain
        self.bridge_api, self.intents = mock.Mock(), mock.Mock()
        def quote(source, destination, amount):
            return [{'sourceTokenId': source, 'destinationTokenId': destination, 'amount': amount,
                     'amountOut': '2490000000000000000', 'amountOutMin': '2470000000000000000', 'messenger': 'near-intents'}]
        self.bridge_api.quote.side_effect = quote
        def build_deposit(route, *, source_address, destination_address):
            q = SimpleNamespace(source_token_id=route['sourceTokenId'], destination_token_id=route['destinationTokenId'],
                                amount_units=route['amount'], source_address=source_address, destination_address=destination_address)
            self.intents.status.return_value = binding(q)
            self.intents.status.return_value['quoteResponse']['quote'].update(
                amountOut='2490000000000000000', minAmountOut='2480000000000000000')
            return dict(build(q), amountOut='2490000000000000000', amountOutMin='2480000000000000000')
        self.bridge_api.build.side_effect = build_deposit
        self.intents.tokens.return_value = tokens()
        mock.patch.object(chain, 'require_chain').start()
        mock.patch('payment_accounts.infinia_bridge.prepare_infinia_bridge', side_effect=lambda j, amount, **kw:
                   prepare_infinia_bridge(j, amount, client=self.bridge_api, intents=self.intents)).start()

    def credit(self, account, amount='10', **kwargs):
        if account.pk == self.local.pk and 'provider_data' not in kwargs:
            kwargs['provider_data'] = {'third_party': {'type': 'FIAT', 'full_name': 'Holder',
                'document_number': '123', 'document_type': 'DNI'}}
        return LedgerEntry.objects.create(provider='infinia', financial_account=account,
            provider_entry_id=str(uuid.uuid4()), direction='credit', asset=account.asset, amount=amount,
            occurred_at=timezone.now(), **kwargs)

    def inbound(self):
        return create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
            request_id=uuid.uuid4(), minimum_fx_output='2', minimum_wallet_output='2.4',
            direction='to_wallet', credit=self.credit(self.local))

    def fx_quote(self, source='local', target='crypto', amount='10', output='2.5'):
        self.api.create_transfer_quote.return_value = dict(id='fx-quote', status='ACTIVE',
            source_account_id=source, target_account_id=target, source_amount=amount, target_amount=output,
            expire_at=(timezone.now()+timedelta(minutes=1)).isoformat())

    def test_dead_review_journey_does_not_stall_a_later_operation(self):
        """The create gate is not enough: the submit guard had its own rule.

        A journey could start, get as far as moving money to the provider, then
        never submit its conversion, because an abandoned needs_review row on
        the same accounts still counted as reserving the funds.
        """
        from payment_accounts.services import submit_money_operation
        from payment_accounts.models import MoneyFlow
        dead = self.inbound()
        InfiniaJourney.objects.filter(pk=dead.pk).update(
            stage='needs_review', failure_code='bridge_not_delivered')
        flow = MoneyFlow.objects.create(
            confio_account=self.owner, kind='withdraw', source_asset='USDT_BSC',
            source_amount=Decimal('2'), target_asset=self.local.asset,
            metadata={'orchestrator': 'infinia'})
        live = InfiniaJourney.objects.create(
            money_flow=flow, confio_account=self.owner, request_id=uuid.uuid4(),
            direction='to_bank', local_account=self.local, crypto_account=self.crypto,
            minimum_fx_output=Decimal('2'), destination_snapshot=dead.destination_snapshot,
            wallet_address=dead.wallet_address, stage='converting')
        op = MoneyOperation.objects.create(
            provider='infinia', money_flow=flow, operation_type='conversion',
            source_account=self.crypto, destination_account=self.local,
            source_asset=self.crypto.asset, target_asset=self.local.asset,
            source_amount=Decimal('1'), idempotency_key=str(uuid.uuid4()), status='created')
        self.assertEqual(live.stage, 'converting')
        try:
            submit_money_operation(op)
        except Exception as exc:  # any later validation is fine; this one is not
            self.assertNotIn('reserved by an active journey', str(exc))

    def test_dead_review_journey_does_not_block_the_next_payment(self):
        """A needs_review row the worker will never touch must not gate anyone."""
        from payment_accounts.infinia_bridge import RECOVERABLE_DELAYS, live_journeys
        first = self.inbound()
        InfiniaJourney.objects.filter(pk=first.pk).update(
            stage='needs_review', failure_code='bridge_not_delivered')
        self.assertFalse(live_journeys(InfiniaJourney.objects.filter(pk=first.pk)).exists())
        second = create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
            request_id=uuid.uuid4(), minimum_fx_output='2', minimum_wallet_output='2.4',
            direction='to_wallet', credit=self.credit(self.local))
        self.assertNotEqual(second.pk, first.pk)
        # A review the worker WILL retry is still in flight and still blocks.
        InfiniaJourney.objects.filter(pk=second.pk).update(
            stage='needs_review', failure_code=sorted(RECOVERABLE_DELAYS)[0])
        with self.assertRaisesRegex(PaymentAccountError, 'en curso'):
            create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                request_id=uuid.uuid4(), minimum_fx_output='2', minimum_wallet_output='2.4',
                direction='to_wallet', credit=self.credit(self.local))

    def test_unidentified_deposit_cannot_create_journey(self):
        with self.assertRaisesRegex(PaymentAccountError, 'Pay-in requires review'):
            create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                request_id=uuid.uuid4(), minimum_fx_output='2', direction='to_wallet',
                credit=self.credit(self.local, provider_data={}))
        self.assertFalse(InfiniaJourney.objects.exists())

    def voucher_conversion(self):
        j = self.inbound(); self.fx_quote()
        advance_journey(j.pk, client=self.api); j.refresh_from_db()
        op = j.fx_operation
        op.provider_operation_id = 'voucher-transfer'
        op.status = 'settling'
        op.provider_data = dict(id=op.provider_operation_id, status='COMPLETED',
            compliance_hold=False, idempotency_key=op.idempotency_key,
            source_account_id='local', target_account_id='crypto', source_amount='10',
            destination_amount='2.5', voucher_ids=['voucher-one'])
        op.save()
        entry = self.credit(self.crypto, amount='2.5', provider_data={
            'operation': None, 'third_party': {'voucher_id': 'voucher-one'}})
        return op, entry

    def test_completed_conversion_voucher_binds_credit_without_rewriting_evidence(self):
        from payment_accounts.infinia_journeys import _credit_for_operation
        op, entry = self.voucher_conversion()
        self.assertEqual(_credit_for_operation(op, self.crypto), Decimal('2.5'))
        entry.refresh_from_db()
        self.assertIsNone(entry.provider_data['operation'])
        self.assertIsNone(entry.operation_id)

    def test_voucher_binding_requires_exact_completed_transfer_identity(self):
        from payment_accounts.infinia_journeys import _credit_for_operation
        op, entry = self.voucher_conversion()
        valid = dict(op.provider_data)
        for field, value in [('id', 'other'), ('idempotency_key', 'other'),
                ('source_account_id', 'other'), ('target_account_id', 'other'),
                ('source_amount', '11'), ('destination_amount', '3'), ('status', 'PENDING'),
                ('compliance_hold', True), ('voucher_ids', []),
                ('voucher_ids', ['voucher-one', 'voucher-one']), ('voucher_ids', ['other'])]:
            with self.subTest(field=field, value=value):
                op.provider_data = dict(valid, **{field: value})
                self.assertEqual(_credit_for_operation(op, self.crypto), Decimal(0))

    def test_duplicate_or_conflicting_voucher_credit_is_not_spendable(self):
        from payment_accounts.infinia_journeys import _credit_for_operation
        op, entry = self.voucher_conversion()
        duplicate = self.credit(self.crypto, amount='2.5', provider_data=entry.provider_data)
        self.assertEqual(_credit_for_operation(op, self.crypto), Decimal(0))
        duplicate.delete()
        entry.provider_data['operation'] = {'type': 'INTERNAL_TRANSFER', 'operation_id': 'other'}
        entry.save()
        self.assertEqual(_credit_for_operation(op, self.crypto), Decimal(0))

    def test_voucher_credit_advances_existing_journey_once(self):
        op, entry = self.voucher_conversion()
        j = op.money_flow.infinia_journey
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertEqual(j.stage, 'paying_out')
        payout_id = j.payout_operation_id
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertEqual(j.payout_operation_id, payout_id)
        self.assertEqual(j.money_flow.operations.filter(operation_type='payout').count(), 1)

    def test_verified_fiat_conversion_voucher_is_not_an_external_payin(self):
        from payment_accounts.payin_admission import is_external_fiat_credit, require_source_admitted
        op, entry = self.voucher_conversion()
        op.source_account = self.crypto; op.destination_account = self.local
        op.provider_data.update(source_account_id='crypto', target_account_id='local')
        op.save()
        entry.financial_account = self.local; entry.asset = self.local.asset; entry.save()
        self.assertFalse(is_external_fiat_credit(entry))
        require_source_admitted(self.local)
        # Matching voucher alone must not bypass sender checks.
        op.provider_data['destination_amount'] = '3'; op.save()
        self.assertTrue(is_external_fiat_credit(entry))
        self.credit(self.local, amount='2.5', provider_data={'operation': {
            'type': 'INTERNAL_TRANSFER', 'operation_id': op.provider_operation_id}})
        # A different, directly linked credit cannot exempt this voucher entry.
        self.assertTrue(is_external_fiat_credit(entry))

    def test_voucher_from_other_owners_flow_remains_external_payin(self):
        from payment_accounts.payin_admission import is_external_fiat_credit
        op, entry = self.voucher_conversion()
        op.source_account = self.crypto; op.destination_account = self.local
        op.provider_data.update(source_account_id='crypto', target_account_id='local')
        op.money_flow = None; op.save()
        entry.financial_account = self.local; entry.asset = self.local.asset; entry.save()
        self.assertTrue(is_external_fiat_credit(entry))

    def test_revocation_stops_worker_before_quote(self):
        j = self.inbound()
        AccountCapability.objects.filter(financial_account=self.local, capability='receive_same_name').update(status='disabled')
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertEqual(j.stage, 'needs_review')
        self.api.create_transfer_quote.assert_not_called()
        self.submit.assert_not_called()

    def test_revocation_stops_submission_after_quote(self):
        from payment_accounts.services import submit_money_operation
        j = self.inbound()
        self.fx_quote()
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        AccountCapability.objects.filter(financial_account=self.local, capability='receive_same_name').update(status='disabled')
        with mock.patch('payment_accounts.services.get_provider') as adapter:
            with self.assertRaisesRegex(PaymentAccountError, 'Pay-in requires review'):
                submit_money_operation(j.fx_operation)
            adapter.assert_not_called()

    def rejected_fx(self, provider_operation_id=None):
        """A journey whose conversion the provider refused outright."""
        from payment_accounts.services import _sync_flow_status
        j = self.inbound()
        self.fx_quote()
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        op = j.fx_operation
        op.status = 'failed'
        op.provider_operation_id = provider_operation_id
        op.failure_code = '400'
        op.provider_data = {'status': 'fail', 'message': f"Quote: {j.fx_quote['id']} is expired"}
        op.save()
        _sync_flow_status(j.money_flow)
        j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code), ('needs_review', 'provider_leg_requires_review'))
        return j

    def test_the_worker_actually_selects_a_requotable_journey(self):
        """advance_journey handling it is useless if the worker filters it out."""
        from payment_accounts.infinia_bridge import live_journeys
        j = self.rejected_fx()
        self.assertTrue(live_journeys(InfiniaJourney.objects.filter(pk=j.pk)).exists())
        # ...but not once the provider has an operation we cannot see.
        InfiniaJourney.objects.filter(pk=j.pk).update()
        j.fx_operation.provider_operation_id = 'transfer-id'
        j.fx_operation.save()
        self.assertFalse(live_journeys(InfiniaJourney.objects.filter(pk=j.pk)).exists())

    def test_expired_quote_is_requoted_in_place_not_queued_for_a_human(self):
        j = self.rejected_fx()
        before = j.fx_operation.idempotency_key
        self.fx_quote()
        self.api.create_transfer_quote.return_value = dict(
            self.api.create_transfer_quote.return_value, id='fx-quote-2')
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertEqual(j.stage, 'converting')
        self.assertEqual(j.fx_operation.status, 'created')
        self.assertEqual(j.fx_quote['id'], 'fx-quote-2')
        self.assertEqual(j.fx_operation.provider_data['quote_id'], 'fx-quote-2')
        # Same row, same key: a submission the provider did record deduplicates.
        self.assertEqual(j.fx_operation.idempotency_key, before)
        self.assertEqual(j.money_flow.metadata['fx_requote_count'], 1)
        self.assertEqual(j.fx_operation.failure_code, '')
        self.assertEqual(j.money_flow.metadata['fx_requote_history'][0]['previous_quote_id'], 'fx-quote')

    def test_a_leg_the_provider_did_create_is_never_requoted(self):
        """The safety boundary: an operation may exist on their side."""
        j = self.rejected_fx(provider_operation_id='transfer-id')
        self.fx_quote()
        self.api.create_transfer_quote.reset_mock()
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertEqual(j.stage, 'needs_review')
        self.assertEqual(j.fx_operation.status, 'failed')
        self.api.create_transfer_quote.assert_not_called()

    def test_requoting_is_bounded(self):
        from payment_accounts.infinia_journeys import FX_REQUOTE_LIMIT
        from payment_accounts.services import _sync_flow_status
        j = self.rejected_fx()
        for _ in range(FX_REQUOTE_LIMIT):
            self.fx_quote()
            advance_journey(j.pk, client=self.api)
            j.refresh_from_db()
            op = j.fx_operation
            op.status = 'failed'
            op.failure_code = '400'
            op.provider_data = {'status': 'fail', 'message': f"Quote: {j.fx_quote['id']} is expired"}
            op.save()
            _sync_flow_status(j.money_flow)
            j.refresh_from_db()
        self.assertEqual(j.money_flow.metadata['fx_requote_count'], FX_REQUOTE_LIMIT)
        # The next pass stops retrying instead of spinning on a dying quote.
        self.fx_quote()
        self.api.create_transfer_quote.reset_mock()
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertEqual(j.failure_code, 'fx_quote_retries_exhausted')
        self.api.create_transfer_quote.assert_not_called()

    def test_arbitrary_failed_response_does_not_authorize_requote(self):
        from payment_accounts.infinia_bridge import live_journeys
        j = self.rejected_fx()
        for payload in ({}, {'status': 'fail', 'message': 'Compliance rejected'},
                        {'status': 'fail', 'message': 'Quote: another-quote is expired'}):
            j.fx_operation.provider_data = payload; j.fx_operation.save()
            self.api.create_transfer_quote.reset_mock()
            self.assertFalse(live_journeys(InfiniaJourney.objects.filter(pk=j.pk)).exists())
            advance_journey(j.pk, client=self.api)
            self.api.create_transfer_quote.assert_not_called()

    def test_worker_runs_safe_requote_through_real_handler(self):
        from payment_accounts.tasks import reconcile_infinia_journeys
        j = self.rejected_fx()
        self.fx_quote()
        with mock.patch('payment_accounts.infinia_journeys.InfiniaClient', return_value=self.api):
            reconcile_infinia_journeys()
        j.refresh_from_db()
        self.assertEqual(j.stage, 'converting')
        self.assertEqual(j.money_flow.metadata['fx_requote_count'], 1)
        self.api.find_operation.assert_called_once_with('conversion', j.fx_operation.idempotency_key)

    def test_requote_requires_explicit_empty_provider_lookup(self):
        j = self.rejected_fx()
        for lookup in ({}, None, {'results': [], 'next': 'page2'},
                       {'results': [], 'count': 1}, {'data': [], 'status': 'error'},
                       [{'id': 'already-created'}]):
            InfiniaJourney.objects.filter(pk=j.pk).update(stage='needs_review', failure_code='provider_leg_requires_review')
            self.api.find_operation.return_value = lookup
            self.api.create_transfer_quote.reset_mock()
            advance_journey(j.pk, client=self.api)
            self.api.create_transfer_quote.assert_not_called()
            j.refresh_from_db()
            self.assertEqual(j.fx_operation.status, 'failed')

    def test_requote_refuses_existing_debit(self):
        j = self.rejected_fx()
        LedgerEntry.objects.create(provider='infinia', financial_account=self.local,
            operation=j.fx_operation, provider_entry_id='debit-proof', direction='debit',
            asset=self.local.asset, amount='10', occurred_at=timezone.now())
        self.api.create_transfer_quote.reset_mock()
        advance_journey(j.pk, client=self.api)
        self.api.create_transfer_quote.assert_not_called()

    def test_requote_preserves_customer_minimum(self):
        j = self.rejected_fx()
        self.fx_quote(output='1.99')
        self.submit.reset_mock()
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertEqual(j.failure_code, 'fx_quote_outside_authorization')
        self.assertEqual(j.fx_operation.status, 'failed')
        self.submit.assert_not_called()

    def test_requote_rechecks_inbound_bridge_prerequisites(self):
        from payment_accounts.infinia_bridge import InfiniaBridgeReview
        j = self.rejected_fx()
        self.fx_quote()
        self.submit.reset_mock()
        with mock.patch('payment_accounts.infinia_bridge.preflight', side_effect=InfiniaBridgeReview('disabled')):
            advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertEqual(j.failure_code, 'direct_bridge_unavailable')
        self.assertEqual(j.fx_operation.status, 'failed')
        self.submit.assert_not_called()

    def test_requote_does_not_overwrite_concurrent_provider_evidence(self):
        j = self.rejected_fx()
        self.fx_quote()
        quote = self.api.create_transfer_quote.return_value
        def concurrent_quote(*args, **kwargs):
            MoneyOperation.objects.filter(pk=j.fx_operation_id).update(
                provider_operation_id='arrived-concurrently', status='processing')
            return quote
        self.api.create_transfer_quote.side_effect = concurrent_quote
        self.submit.reset_mock()
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertEqual(j.fx_operation.status, 'processing')
        self.assertEqual(j.fx_operation.provider_operation_id, 'arrived-concurrently')
        self.submit.assert_not_called()

    def test_reviewed_journey_unknown_operation_still_reserves_funds(self):
        from payment_accounts.services import submit_money_operation
        from payment_accounts.models import MoneyFlow
        j = self.rejected_fx()
        j.fx_operation.status='unknown'; j.fx_operation.save()
        flow = MoneyFlow.objects.create(confio_account=self.owner, kind='transfer',
            source_asset=self.crypto.asset, source_amount='1')
        pending = MoneyOperation.objects.create(money_flow=j.money_flow, provider='infinia',
            operation_type='conversion', source_account=self.crypto, destination_account=self.local,
            source_asset=self.crypto.asset, target_asset=self.local.asset, source_amount='1',
            idempotency_key=str(uuid.uuid4()), status='unknown')
        op = MoneyOperation.objects.create(money_flow=flow, provider='infinia',
            operation_type='conversion', source_account=self.crypto, destination_account=self.local,
            source_asset=self.crypto.asset, target_asset=self.local.asset, source_amount='1',
            idempotency_key=str(uuid.uuid4()))
        with mock.patch('payment_accounts.services.get_provider') as provider:
            from payment_accounts.providers.common import ProviderResult
            provider.return_value.create_transfer.return_value = ProviderResult(
                'unexpected-second-operation', 'processing', 'PROCESSING', {})
            with self.assertRaisesRegex(PaymentAccountError, 'unresolved operation'):
                submit_money_operation(op)
            provider.assert_not_called()

    def settle_fx(self, j, account, amount='2.5'):
        j.refresh_from_db(); op=j.fx_operation
        op.provider_operation_id='transfer-id'; op.status='settling';op.save()
        return self.credit(account, amount=amount, provider_data={'operation': {'type':'INTERNAL_TRANSFER','operation_id':'transfer-id'}})

    def test_inbound_waits_for_credit_before_payout_and_preserves_parent(self):
        j=self.inbound(); self.fx_quote()
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db(); self.assertEqual(j.stage,'converting')
        self.assertEqual(j.fx_operation.source_amount, Decimal('10'))
        j.fx_operation.status='succeeded';j.fx_operation.save()
        _sync_flow_status(j.money_flow);j.money_flow.refresh_from_db()
        self.assertEqual(j.money_flow.status,'processing')
        advance_journey(j.pk, client=self.api);j.refresh_from_db()
        self.assertIsNone(j.payout_operation_id)
        self.settle_fx(j,self.crypto)
        advance_journey(j.pk, client=self.api);j.refresh_from_db()
        self.assertEqual(j.stage,'paying_out')
        from .test_bridge_execution import DEPOSIT
        self.assertEqual(j.payout_operation.external_destination['destination_account'], {
            'country': 'GLOBAL', 'currency': 'USDC', 'destinationType': {'type': 'POLYGON', 'address': DEPOSIT}})
        self.assertEqual(j.bridge.funding_mode, 'infinia')
        self.assertEqual(j.bridge.quote.destination_address, self.owner.bsc_address)
        self.assertEqual(j.payout_operation.source_amount,Decimal('2.5'))
        advance_journey(j.pk, client=self.api)
        self.assertEqual(MoneyOperation.objects.filter(money_flow=j.money_flow).count(),2)

    def test_bank_send_leaves_monthly_limit_enforcement_to_provider(self):
        t, _ = self.prepared()
        args = dict(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                    request_id=uuid.uuid4(), direction='to_bank', bridge=t,
                    destination=self.dest, minimum_fx_output='30')
        with mock.patch('payment_accounts.clients.InfiniaClient.get_account_limits',
                        side_effect=AssertionError('Monthly limits must not gate a journey')):
            first = create_journey(**args)
            self.assertEqual(create_journey(**args).pk, first.pk)

    def test_outbound_correlates_infinia_credit_to_bridge_then_pays_local_account(self):
        t,_=self.prepared(); t.status='delivered';t.destination_tx_hash=DEST_HASH;t.save()
        entry=self.credit(self.crypto, amount='10.008795', provider_data={'third_party':{'type':'CRYPTO','crypto_network':'POLYGON','transaction_hash':DEST_HASH}})
        reconcile_provider_credit(t);t.refresh_from_db();self.assertEqual(t.provider_credit_id,entry.pk)
        j=create_journey(owner=self.owner,local_account=self.local,crypto_account=self.crypto, request_id=uuid.uuid4(),
            direction='to_bank',bridge=t,destination=self.dest,minimum_fx_output='30')
        self.fx_quote('crypto','local',output='39')
        advance_journey(j.pk,client=self.api)
        self.settle_fx(j,self.local,'39')
        advance_journey(j.pk,client=self.api);j.refresh_from_db()
        op=j.payout_operation;op.status='succeeded';op.target_amount=Decimal('38.5');op.save()
        advance_journey(j.pk,client=self.api);j.refresh_from_db();j.money_flow.refresh_from_db()
        self.assertEqual(j.stage,'completed');self.assertEqual(j.money_flow.target_amount,Decimal('38.5'))
        self.assertEqual(j.fx_operation.source_amount, Decimal('10'))
        self.assertEqual(j.money_flow.metadata['fx_source_remainder'], {
            'amount': '0.008795000000000000', 'asset': 'USDC_POL',
            'financial_account_id': str(self.crypto.internal_id), 'funding_credit_id': str(entry.pk)})

    def test_quote_below_authorized_minimum_cannot_move_money(self):
        j=self.inbound();self.fx_quote(output='1.9')
        advance_journey(j.pk,client=self.api);j.refresh_from_db()
        self.assertEqual(j.stage,'needs_review');self.assertIsNone(j.fx_operation_id)
        self.submit.assert_not_called()

    def test_fx_rounding_preserves_owned_remainder_and_retry_operation(self):
        j = self.inbound()
        j.funding_credit.amount = Decimal('10.008795')
        j.funding_credit.save(update_fields=['amount'])
        self.fx_quote(amount='10.00')
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db(); j.money_flow.refresh_from_db()
        self.assertEqual(j.stage, 'converting')
        self.assertEqual(self.api.create_transfer_quote.call_args.args[0]['source_amount'], 10.0)
        self.assertEqual(j.fx_operation.source_amount, Decimal('10'))
        remainder = j.money_flow.metadata['fx_source_remainder']
        self.assertEqual(remainder, {'amount': '0.008795000000000000', 'asset': 'PEN',
            'financial_account_id': str(self.local.internal_id),
            'funding_credit_id': str(j.funding_credit_id)})
        self.assertEqual(j.funding_credit.amount, Decimal('10.008795'))
        operation_id = j.fx_operation_id
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db(); j.money_flow.refresh_from_db()
        self.assertEqual(j.fx_operation_id, operation_id)
        self.assertEqual(j.money_flow.metadata['fx_source_remainder'], remainder)
        self.api.create_transfer_quote.assert_called_once()

    def test_subcent_credit_is_held_without_quote_or_conversion(self):
        j = self.inbound()
        j.funding_credit.amount = Decimal('0.009999')
        j.funding_credit.save(update_fields=['amount'])
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertEqual((j.stage, j.failure_code), ('needs_review', 'fx_source_below_precision'))
        self.assertIsNone(j.fx_operation_id)
        self.api.create_transfer_quote.assert_not_called()
        self.submit.assert_not_called()

    def test_fractional_credit_submission_timeout_keeps_operation_and_remainder(self):
        from payment_accounts.clients import ProviderAPIError
        j = self.inbound()
        j.funding_credit.amount = Decimal('10.008795')
        j.funding_credit.save(update_fields=['amount'])
        self.fx_quote(amount='10.00')
        self.submit.side_effect = ProviderAPIError('timeout', retryable=True)
        with self.assertRaises(ProviderAPIError):
            advance_journey(j.pk, client=self.api)
        j.refresh_from_db(); j.money_flow.refresh_from_db()
        operation_id = j.fx_operation_id
        remainder = j.money_flow.metadata['fx_source_remainder']
        self.assertIsNotNone(operation_id)
        self.assertEqual(j.fx_operation.source_amount, Decimal('10'))
        self.submit.side_effect = lambda op: op
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db(); j.money_flow.refresh_from_db()
        self.assertEqual(j.fx_operation_id, operation_id)
        self.assertEqual(j.money_flow.metadata['fx_source_remainder'], remainder)
        self.assertEqual(MoneyOperation.objects.filter(money_flow=j.money_flow).count(), 1)
        self.api.create_transfer_quote.assert_called_once()

    def test_provider_cannot_quote_the_unrounded_credit_instead(self):
        j = self.inbound()
        j.funding_credit.amount = Decimal('10.008795')
        j.funding_credit.save(update_fields=['amount'])
        self.fx_quote(amount='10.008795')
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db(); j.money_flow.refresh_from_db()
        self.assertEqual(self.api.create_transfer_quote.call_args.args[0]['source_amount'], 10.0)
        self.assertEqual((j.stage, j.failure_code), ('needs_review', 'fx_quote_outside_authorization'))
        self.assertIsNone(j.fx_operation_id)
        self.assertNotIn('fx_source_remainder', j.money_flow.metadata)
        self.submit.assert_not_called()

    def test_default_quote_lock_is_used_and_short_provider_expiry_is_preserved(self):
        j = self.inbound()
        self.fx_quote()
        expires = (timezone.now() + timedelta(seconds=15)).isoformat()
        self.api.create_transfer_quote.return_value['expire_at'] = expires
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertNotIn('requested_lock_time', self.api.create_transfer_quote.call_args.args[0])
        self.assertEqual(j.fx_quote['expire_at'], expires)
        self.assertEqual(j.stage, 'converting')
        self.submit.assert_called_once()

    def test_expired_fx_quote_cannot_move_money(self):
        j = self.inbound()
        self.fx_quote()
        self.api.create_transfer_quote.return_value['expire_at'] = (
            timezone.now() - timedelta(seconds=1)).isoformat()
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertEqual(j.failure_code, 'fx_quote_outside_authorization')
        self.assertIsNone(j.fx_operation_id)
        self.submit.assert_not_called()

    def test_quote_for_wrong_accounts_is_rejected(self):
        j=self.inbound();self.fx_quote(source='unowned')
        advance_journey(j.pk,client=self.api);j.refresh_from_db()
        self.assertEqual(j.failure_code,'fx_quote_outside_authorization')
        self.submit.assert_not_called()

    def test_unrelated_equal_amount_credit_never_funds_payout(self):
        j=self.inbound();self.fx_quote();advance_journey(j.pk,client=self.api)
        self.credit(self.crypto,'2.5',provider_data={'operation':{'type':'INTERNAL_TRANSFER','operation_id':'someone-else'}})
        advance_journey(j.pk,client=self.api);j.refresh_from_db()
        self.assertIsNone(j.payout_operation_id)

    def test_unknown_submission_never_creates_a_new_leg(self):
        j=self.inbound();self.fx_quote();advance_journey(j.pk,client=self.api)
        j.refresh_from_db();op=j.fx_operation;op.status='unknown';op.save()
        self.submit.reset_mock();advance_journey(j.pk,client=self.api)
        self.submit.assert_not_called();self.api.create_transfer_quote.assert_called_once()
        self.assertEqual(MoneyOperation.objects.filter(money_flow=j.money_flow).count(),1)

    def test_user_request_is_idempotent_and_different_details_are_rejected(self):
        credit=self.credit(self.local);request=uuid.uuid4()
        args=dict(owner=self.owner,local_account=self.local,crypto_account=self.crypto,credit=credit,
            request_id=request,minimum_fx_output='2',minimum_wallet_output='2.4',direction='to_wallet')
        first=create_journey(**args);self.assertEqual(create_journey(**args).pk,first.pk)
        args['minimum_fx_output']='3'
        with self.assertRaises(PaymentAccountError):create_journey(**args)

    def test_successful_provider_withdrawal_waits_for_chain_delivery(self):
        j=self.inbound();self.fx_quote();advance_journey(j.pk,client=self.api)
        self.settle_fx(j,self.crypto);advance_journey(j.pk,client=self.api);j.refresh_from_db()
        op=j.payout_operation;op.status='succeeded';op.save()
        advance_journey(j.pk,client=self.api);j.refresh_from_db()
        self.assertEqual(j.stage,'bridging')
        self.assertNotEqual(j.money_flow.status,'succeeded')

    def test_late_reversal_reopens_completed_parent(self):
        j=self.inbound(); self.fx_quote(); advance_journey(j.pk,client=self.api)
        j.refresh_from_db();j.stage='completed';j.save();j.money_flow.status='succeeded';j.money_flow.save()
        op=j.fx_operation;op.status='reversed';op.save();_sync_flow_status(j.money_flow)
        j.refresh_from_db();j.money_flow.refresh_from_db()
        self.assertEqual(j.stage,'needs_review');self.assertEqual(j.money_flow.status,'needs_review')

    def test_posted_refund_does_not_restart_a_conversion(self):
        from payment_accounts.infinia_journeys import observe_refund
        j=self.inbound();self.fx_quote();advance_journey(j.pk,client=self.api);j.refresh_from_db()
        op=j.fx_operation;op.provider_operation_id='fx-original';op.save()
        refund=self.credit(self.local,provider_data={'operation':{'type':'INTERNAL_TRANSFER_REFUND','operation_id':'fx-original'}})
        observe_refund(refund);j.refresh_from_db()
        self.assertEqual(j.stage,'needs_review')
        self.submit.reset_mock();advance_journey(j.pk,client=self.api);self.submit.assert_not_called()

    def test_confirmed_polygon_receipt_enables_exact_return_bridge(self):
        from payment_accounts import bridge_chain as chain
        from .test_bridge_execution import receipt
        j=self.inbound();self.fx_quote();advance_journey(j.pk,client=self.api)
        self.settle_fx(j,self.crypto)
        # Existing payouts retain their original wallet destination on upgrade.
        from payment_accounts.infinia_journeys import _new_operation
        j.refresh_from_db()
        j.payout_operation = _new_operation(j, 'payout', self.crypto, None, Decimal('2.5'))
        j.save(update_fields=['payout_operation'])
        op=j.payout_operation;op.status='succeeded';op.provider_operation_id='payout-id';op.save()
        LedgerEntry.objects.create(provider='infinia',financial_account=self.crypto,provider_entry_id='withdrawal',
            direction='debit',amount='2.5',asset='USDC_POL',occurred_at=timezone.now(),provider_data={
                'operation':{'type':'PAYOUT','operation_id':'payout-id'},
                'third_party':{'type':'CRYPTO','crypto_network':'POLYGON','transaction_hash':DEST_HASH}})
        with mock.patch.object(chain,'final_receipt',return_value=receipt('POL:USDC',self.owner.bsc_address,2490000)):
            advance_journey(j.pk,client=self.api)
        j.refresh_from_db();self.assertEqual(j.stage,'awaiting_wallet_authorization')
        self.assertEqual(j.wallet_arrival_units,'2490000')

    def test_late_transport_error_cannot_overwrite_webhook_success(self):
        from payment_accounts.services import submit_money_operation
        from payment_accounts.clients import ProviderAPIError
        j=self.inbound();self.fx_quote();advance_journey(j.pk,client=self.api);j.refresh_from_db()
        def race(operation):
            MoneyOperation.objects.filter(pk=operation.pk).update(status='succeeded', provider_operation_id='accepted')
            raise ProviderAPIError('late timeout',retryable=True)
        adapter=mock.Mock();adapter.create_transfer.side_effect=race
        with mock.patch('payment_accounts.services.get_provider',return_value=adapter):
            result=submit_money_operation(j.fx_operation)
        self.assertEqual(result.status,'succeeded')

    def test_quote_binding_survives_error_payload_replacement(self):
        from payment_accounts.providers.infinia import InfiniaProvider
        j=self.inbound();self.fx_quote();advance_journey(j.pk,client=self.api);j.refresh_from_db()
        op=j.fx_operation;op.provider_data={'error':'temporary'};op.save()
        client=mock.Mock();client.create_internal_transfer.return_value={'id':'accepted','status':'PROCESSING'}
        InfiniaProvider(client=client).create_transfer(op)
        self.assertEqual(client.create_internal_transfer.call_args.args[0]['quote_id'],'fx-quote')

    def test_another_active_account_cannot_authorize_this_accounts_deposit(self):
        from users.models import Account
        other=Account.objects.create(user=self.user,account_type='personal',account_index=1,bsc_address='0x'+'aa'*20)
        with self.assertRaises(PaymentAccountError):
            create_journey(owner=other,local_account=self.local,crypto_account=self.crypto,
                credit=self.credit(self.local),request_id=uuid.uuid4(),minimum_fx_output='2',direction='to_wallet')
        self.assertEqual(InfiniaJourney.objects.count(),0)

    def test_early_refund_is_rechecked_after_provider_id_binding(self):
        j=self.inbound();self.fx_quote();advance_journey(j.pk,client=self.api);j.refresh_from_db()
        self.credit(self.local,provider_data={'operation':{'type':'INTERNAL_TRANSFER_REFUND','operation_id':'late-id'}})
        op=j.fx_operation;op.provider_operation_id='late-id';op.status='succeeded';op.save()
        self.credit(self.crypto,'2.5',provider_data={'operation':{'type':'INTERNAL_TRANSFER','operation_id':'late-id'}})
        advance_journey(j.pk,client=self.api);j.refresh_from_db()
        self.assertEqual(j.stage,'needs_review');self.assertIsNone(j.payout_operation_id)

    def test_malformed_quote_goes_to_review_without_a_money_operation(self):
        j=self.inbound();self.fx_quote();del self.api.create_transfer_quote.return_value['source_amount']
        advance_journey(j.pk,client=self.api);j.refresh_from_db()
        self.assertEqual(j.stage,'needs_review');self.assertIsNone(j.fx_operation_id)

    def test_late_http_response_keeps_terminal_webhook_evidence(self):
        from payment_accounts.services import apply_operation_result
        from payment_accounts.providers.common import ProviderResult
        j=self.inbound();self.fx_quote();advance_journey(j.pk,client=self.api);j.refresh_from_db()
        op=j.fx_operation;op.status='succeeded';op.provider_status='SUCCESS';op.provider_data={'settled':True};op.save()
        apply_operation_result(op,ProviderResult('late-id','processing','PROCESSING',{'old':True}))
        op.refresh_from_db();self.assertEqual(op.provider_operation_id,'late-id')
        self.assertEqual(op.provider_status,'SUCCESS');self.assertEqual(op.provider_data,{'settled':True})

    def test_contradictory_terminal_status_requires_review(self):
        from payment_accounts.services import apply_operation_result
        from payment_accounts.providers.common import ProviderResult
        j=self.inbound();self.fx_quote();advance_journey(j.pk,client=self.api);j.refresh_from_db()
        op=j.fx_operation;op.status='succeeded';op.provider_operation_id='fx-id';op.save()
        apply_operation_result(op,ProviderResult('fx-id','failed','FAILED',{}))
        j.refresh_from_db();self.assertEqual(j.stage,'needs_review')

    def test_late_provider_id_binding_detects_refund_on_completed_journey(self):
        from payment_accounts.services import apply_operation_result
        from payment_accounts.providers.common import ProviderResult
        j=self.inbound();self.fx_quote();advance_journey(j.pk,client=self.api);j.refresh_from_db()
        op=j.fx_operation;op.status='succeeded';op.save();j.stage='completed';j.save()
        self.credit(self.local,provider_data={'operation':{'type':'INTERNAL_TRANSFER_REFUND','operation_id':'late-id'}})
        apply_operation_result(op,ProviderResult('late-id','processing','PROCESSING',{}))
        j.refresh_from_db();self.assertEqual(j.stage,'needs_review')

    def direct_payout(self):
        j = self.inbound()
        self.fx_quote()
        advance_journey(j.pk, client=self.api)
        self.settle_fx(j, self.crypto)
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        op = j.payout_operation
        op.provider_operation_id, op.status = 'direct-payout', 'processing'
        op.save()
        return j

    def payout_movement(self, j, *, operation_id='direct-payout', tx_hash=None):
        from .test_bridge_execution import SOURCE_HASH
        return LedgerEntry.objects.create(
            provider='infinia', financial_account=j.crypto_account, provider_entry_id=str(uuid.uuid4()),
            direction='debit', asset='USDC_POL', amount='2.5', occurred_at=timezone.now(),
            provider_data={'operation': {'type': 'PAYOUT', 'operation_id': operation_id},
                           'third_party': {'type': 'CRYPTO', 'crypto_network': 'POLYGON',
                                           'transaction_hash': tx_hash or SOURCE_HASH}})

    def test_direct_bridge_never_checks_wallet_balance_or_requests_signature(self):
        from payment_accounts import bridge_chain as chain
        from payment_accounts.bridge_execution import submit_bridge
        from payment_accounts.allbridge_next import NextError
        with mock.patch.object(chain, 'token_balance') as balance, mock.patch.object(chain, 'rpc') as rpc:
            j = self.direct_payout()
        balance.assert_not_called()
        rpc.assert_not_called()
        self.assertEqual(j.bridge.binding['quoteResponse']['quoteRequest']['refundTo'], j.wallet_address)
        self.assertGreater(j.bridge.deadline, int(timezone.now().timestamp()) + 600)
        with self.assertRaisesRegex(NextError, 'funded by the provider'):
            submit_bridge(self.owner, j.bridge.internal_id, 'unused')

    def test_direct_bridge_completes_from_chain_receipts_before_payout_status_webhook(self):
        from payment_accounts import bridge_chain as chain
        from .test_bridge_execution import SOURCE_HASH, DEPOSIT, receipt
        j = self.direct_payout()
        self.payout_movement(j)
        self.intents.status.return_value = {
            'quoteResponse': j.bridge.binding['quoteResponse'], 'status': 'SUCCESS',
            'swapDetails': {'originChainTxHashes': [{'hash': SOURCE_HASH}],
                            'destinationChainTxHashes': [{'hash': DEST_HASH}], 'amountOut': '2485000000000000000'}}
        def final(network, tx_hash):
            if network == 'POL' and tx_hash == SOURCE_HASH:
                return receipt('POL:USDC', DEPOSIT, 2500000, sender='0x' + 'ab' * 20)
            if network == 'BSC' and tx_hash == DEST_HASH:
                return receipt('BSC:USDT', j.wallet_address, 2485000000000000000)
            self.fail('Unexpected chain evidence lookup')
        with mock.patch.object(chain, 'final_receipt', side_effect=final):
            advance_journey(j.pk, intents=self.intents)
        j.refresh_from_db()
        self.assertEqual(j.stage, 'completed')
        self.assertEqual(j.money_flow.target_amount, Decimal('2.485'))
        self.assertEqual(j.payout_operation.status, 'processing')
        self.assertEqual(j.bridge.source_tx_hash, SOURCE_HASH)
        self.assertFalse(j.bridge.signed_raw_tx)
        # The proven parent settlement releases reservations even if the
        # provider's status callback for its already-delivered payout is late.
        second = self.inbound()
        self.assertNotEqual(second.pk, j.pk)

    def test_direct_bridge_rejects_wrong_or_nonexact_source_receipts(self):
        from payment_accounts import bridge_chain as chain
        from payment_accounts.bridge_execution import reconcile_bridge
        from .test_bridge_execution import DEPOSIT, receipt
        j = self.direct_payout()
        self.payout_movement(j)
        for recipient, amount in [(DEPOSIT, 2490000), (DEPOSIT, 2510000), (j.wallet_address, 2500000)]:
            with self.subTest(recipient=recipient, amount=amount), mock.patch.object(
                    chain, 'final_receipt', return_value=receipt('POL:USDC', recipient, amount)):
                t = reconcile_bridge(j.bridge, intents=self.intents)
            self.assertEqual(t.status, 'needs_review')
            self.assertEqual(t.failure_code, 'source_transfer_mismatch')
        self.assertEqual(MoneyOperation.objects.filter(money_flow=j.money_flow, operation_type='payout').count(), 1)

    def test_unrelated_provider_movement_cannot_fund_direct_bridge(self):
        from payment_accounts.infinia_bridge import bind_payout_hash
        j = self.direct_payout()
        self.payout_movement(j, operation_id='another-payout')
        self.assertFalse(bind_payout_hash(j.bridge).source_tx_hash)

    def test_ambiguous_provider_hashes_require_review(self):
        from payment_accounts.infinia_bridge import bind_payout_hash
        j = self.direct_payout()
        self.payout_movement(j)
        self.payout_movement(j, tx_hash=DEST_HASH)
        t = bind_payout_hash(j.bridge)
        self.assertEqual(t.failure_code, 'ambiguous_provider_payout_hash')
        self.assertFalse(t.source_tx_hash)

    def test_expired_provider_deposit_still_adopts_late_authenticated_hash(self):
        from payment_accounts.infinia_bridge import bind_payout_hash
        from .test_bridge_execution import SOURCE_HASH
        j = self.direct_payout()
        j.bridge.deadline = 1
        j.bridge.save()
        self.assertEqual(bind_payout_hash(j.bridge).status, 'needs_review')
        self.payout_movement(j)
        self.assertEqual(bind_payout_hash(j.bridge).source_tx_hash, SOURCE_HASH)

    def test_expired_payout_is_not_submitted_or_retried(self):
        from payment_accounts.services import submit_money_operation
        j = self.direct_payout()
        j.bridge.deadline = 1
        j.bridge.save()
        op = j.payout_operation
        op.status = 'unknown'
        op.save()
        with mock.patch('payment_accounts.services.get_provider') as adapter:
            submit_money_operation(op)
        adapter.assert_not_called()
        j.refresh_from_db()
        self.assertEqual(j.stage, 'needs_review')
        self.assertEqual(j.payout_operation_id, op.pk)
        self.assertEqual(j.failure_code, 'provider_deposit_delayed')

    def test_direct_payout_terms_are_checked_before_submission(self):
        from payment_accounts.services import submit_money_operation
        j = self.direct_payout()
        op = j.payout_operation
        op.status = 'created'
        op.external_destination = {'destination_account': {'address': self.owner.bsc_address}}
        op.save()
        with mock.patch('payment_accounts.services.get_provider') as adapter:
            submit_money_operation(op)
        adapter.assert_not_called()
        j.refresh_from_db()
        self.assertEqual(j.failure_code, 'provider_bridge_submission_invalid')

    def test_direct_payout_submits_exact_amount_and_documented_destination(self):
        from payment_accounts.services import submit_money_operation
        from payment_accounts.providers.infinia import InfiniaProvider
        j = self.direct_payout()
        op = j.payout_operation
        op.status, op.provider_operation_id = 'created', ''
        op.save()
        api = mock.Mock()
        api.create_payout.return_value = {'id': 'accepted-payout', 'status': 'IN_PROGRESS'}
        with mock.patch('payment_accounts.services.get_provider', return_value=InfiniaProvider(client=api)):
            submit_money_operation(op)
            submit_money_operation(op)
        api.create_payout.assert_called_once()
        payload = api.create_payout.call_args.args[0]
        self.assertEqual(payload['amount'], 2.5)
        self.assertEqual(payload['sourceAccountId'], 'crypto')
        self.assertEqual(payload['originId'], op.idempotency_key)
        self.assertEqual(payload['destinationAccount'], op.external_destination['destination_account'])

    def test_wallet_change_blocks_direct_payout_retry(self):
        from payment_accounts.services import submit_money_operation
        j = self.direct_payout()
        self.owner.bsc_address = '0x' + 'ab' * 20
        self.owner.save(update_fields=['bsc_address'])
        op = j.payout_operation
        op.status = 'unknown'
        op.save()
        with mock.patch('payment_accounts.services.get_provider') as adapter:
            submit_money_operation(op)
        adapter.assert_not_called()
        j.refresh_from_db()
        self.assertEqual(j.stage, 'needs_review')

    def test_failed_deposit_preparation_does_not_create_payout_or_orphan_quote(self):
        from payment_accounts.models import PaymentBridgeQuote
        from payment_accounts.allbridge_next import NextError
        j = self.inbound()
        self.fx_quote()
        advance_journey(j.pk, client=self.api)
        self.settle_fx(j, self.crypto)
        self.bridge_api.build.side_effect = NextError('unavailable')
        with self.assertRaises(NextError):
            advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertIsNone(j.payout_operation_id)
        self.assertIsNone(j.bridge_id)
        self.assertFalse(PaymentBridgeQuote.objects.exists())

    def test_new_inbound_requires_explicit_wallet_minimum(self):
        with self.assertRaisesRegex(PaymentAccountError, 'minimum BSC USDT'):
            create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                request_id=uuid.uuid4(), minimum_fx_output='2', direction='to_wallet', credit=self.credit(self.local))
        self.assertFalse(InfiniaJourney.objects.exists())

    def test_wallet_minimum_cannot_change_on_request_retry(self):
        j = self.inbound()
        with self.assertRaisesRegex(PaymentAccountError, 'different journey details'):
            create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                request_id=j.request_id, minimum_fx_output='2', minimum_wallet_output='2.3',
                direction='to_wallet', credit=j.funding_credit)

    def test_bridge_below_wallet_minimum_never_submits_payout(self):
        from payment_accounts.models import PaymentBridgeQuote
        j = self.inbound()
        j.minimum_wallet_output = Decimal('2.49')
        j.save()
        self.fx_quote()
        advance_journey(j.pk, client=self.api)
        self.settle_fx(j, self.crypto)
        self.submit.reset_mock()
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertEqual(j.failure_code, 'direct_bridge_outside_authorization')
        self.assertIsNone(j.payout_operation_id)
        self.assertFalse(PaymentBridgeQuote.objects.exists())
        self.submit.assert_not_called()

    def test_disabled_bridge_stops_fx_before_spending(self):
        j = self.inbound()
        self.fx_quote()
        with self.settings(PAYMENT_BRIDGE_POLYGON_ENABLED=False):
            advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertEqual(j.failure_code, 'direct_bridge_unavailable')
        self.assertIsNone(j.fx_operation_id)
        self.submit.assert_not_called()

    def test_fx_output_over_bridge_cap_stops_before_spending(self):
        j = self.inbound()
        self.fx_quote(output='101')
        with self.settings(PAYMENT_BRIDGE_MAX_USDT='100'):
            advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertIsNone(j.fx_operation_id)
        self.assertEqual(j.failure_code, 'direct_bridge_unavailable')

    def test_missing_instruction_stops_fx_before_spending(self):
        j = self.inbound()
        self.instruction.status = 'expired'
        self.instruction.save()
        self.fx_quote()
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertIsNone(j.fx_operation_id)
        self.assertEqual(j.stage, 'needs_review')

    def test_prerequisite_loss_after_fx_requires_review_without_orphan_bridge(self):
        from payment_accounts.models import PaymentBridgeQuote
        j = self.inbound()
        self.fx_quote()
        advance_journey(j.pk, client=self.api)
        self.settle_fx(j, self.crypto)
        with self.settings(PAYMENT_BRIDGE_POLYGON_ENABLED=False):
            advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertEqual(j.failure_code, 'direct_bridge_outside_authorization')
        self.assertIsNone(j.payout_operation_id)
        self.assertFalse(PaymentBridgeQuote.objects.exists())

    def test_preflight_is_rechecked_on_persisted_fx_submission(self):
        from payment_accounts.services import submit_money_operation
        j = self.inbound()
        self.fx_quote()
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        with self.settings(PAYMENT_BRIDGE_QUOTES_ENABLED=False), mock.patch('payment_accounts.services.get_provider') as adapter:
            submit_money_operation(j.fx_operation)
        adapter.assert_not_called()
        j.refresh_from_db()
        self.assertEqual(j.stage, 'needs_review')

    def test_preupgrade_journey_without_wallet_minimum_keeps_wallet_payout(self):
        j = self.inbound()
        j.minimum_wallet_output = None
        j.save()
        self.fx_quote()
        advance_journey(j.pk, client=self.api)
        self.settle_fx(j, self.crypto)
        advance_journey(j.pk, client=self.api)
        j.refresh_from_db()
        self.assertIsNone(j.bridge_id)
        self.assertEqual(j.payout_operation.external_destination['destination_account']['address'], self.owner.bsc_address)
        self.bridge_api.quote.assert_not_called()

    def test_late_delivery_recovers_parent_without_resubmitting(self):
        from .test_bridge_execution import SOURCE_HASH, DEPOSIT, receipt
        from payment_accounts import bridge_chain as chain
        from payment_accounts.tasks import reconcile_infinia_journeys
        j = self.direct_payout()
        j.bridge.deadline = 1
        j.bridge.save()
        advance_journey(j.pk, intents=self.intents)
        j.refresh_from_db()
        self.assertEqual(j.failure_code, 'provider_deposit_delayed')
        self.payout_movement(j)
        self.intents.status.return_value = {
            'quoteResponse': j.bridge.binding['quoteResponse'], 'status': 'SUCCESS',
            'swapDetails': {'originChainTxHashes': [{'hash': SOURCE_HASH}],
                           'destinationChainTxHashes': [{'hash': DEST_HASH}], 'amountOut': '2485000000000000000'}}
        self.submit.reset_mock()
        with mock.patch.object(chain, 'final_receipt', side_effect=lambda network, tx:
                receipt('POL:USDC', DEPOSIT, 2500000) if network == 'POL' else
                receipt('BSC:USDT', j.wallet_address, 2485000000000000000)), \
                mock.patch('payment_accounts.bridge_execution.IntentsClient', return_value=self.intents):
            reconcile_infinia_journeys()
        j.refresh_from_db()
        self.assertEqual(j.stage, 'completed')
        self.assertEqual(j.money_flow.target_amount, Decimal('2.485'))
        self.submit.assert_not_called()

    def test_late_delivery_does_not_override_refund_or_other_review(self):
        j = self.direct_payout()
        j.stage, j.failure_code = 'needs_review', 'provider_deposit_delayed'
        j.save()
        op = j.payout_operation
        op.status = 'reversed'
        op.save()
        with mock.patch('payment_accounts.bridge_execution.reconcile_bridge') as reconcile:
            advance_journey(j.pk)
        reconcile.assert_not_called()
        j.refresh_from_db()
        self.assertEqual(j.failure_code, 'provider_leg_requires_review')

    def test_local_numeric_rejection_is_terminal_not_submitted(self):
        from payment_accounts.models import MoneyFlow
        from payment_accounts.services import submit_money_operation
        from payment_accounts.providers.infinia import InfiniaProvider
        flow = MoneyFlow.objects.create(confio_account=self.owner, kind='withdraw', source_asset='USDC_POL',
                                       source_amount=Decimal('1.000000000000000001'))
        op = MoneyOperation.objects.create(money_flow=flow, provider='infinia', operation_type='payout',
            source_account=self.crypto, source_asset='USDC_POL', source_amount=flow.source_amount,
            idempotency_key='precision-rejection', external_destination={'destination_account': {'country': 'GLOBAL'}})
        api = mock.Mock()
        with mock.patch('payment_accounts.services.get_provider', return_value=InfiniaProvider(client=api)):
            with self.assertRaisesRegex(PaymentAccountError, 'represented exactly'):
                submit_money_operation(op)
        op.refresh_from_db()
        self.assertEqual(op.status, 'failed')
        api.create_payout.assert_not_called()
