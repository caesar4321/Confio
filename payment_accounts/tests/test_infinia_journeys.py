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
            provider_account_id='local', country='PER', asset='PEN', status='active', ownership_structure='provider_named')
        for account in (self.local, self.crypto):
            for capability in ('convert', 'send_third_party'):
                AccountCapability.objects.create(financial_account=account, capability=capability, status='enabled')
        self.dest = PayoutDestination.objects.create(confio_account=self.owner, provider='infinia', kind='bank_account',
            country='PER', asset='PEN', label='Bank', holder_name='Holder', details={'type':'ACCOUNT_PERU','accountNumber':'123'})
        self.policies = mock.patch('payment_accounts.infinia_journeys.enforce_and_record').start()
        self.submit = mock.patch('payment_accounts.infinia_journeys.submit_money_operation', side_effect=lambda op: op).start()
        self.api = mock.Mock()

    def credit(self, account, amount='10', **kwargs):
        return LedgerEntry.objects.create(provider='infinia', financial_account=account,
            provider_entry_id=str(uuid.uuid4()), direction='credit', asset=account.asset, amount=amount,
            occurred_at=timezone.now(), **kwargs)

    def inbound(self):
        return create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
            request_id=uuid.uuid4(), minimum_fx_output='2', direction='to_wallet', credit=self.credit(self.local))

    def fx_quote(self, source='local', target='crypto', amount='10', output='2.5'):
        self.api.create_transfer_quote.return_value = dict(id='fx-quote', status='ACTIVE',
            source_account_id=source, target_account_id=target, source_amount=amount, target_amount=output,
            expire_at=(timezone.now()+timedelta(minutes=1)).isoformat())

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
        self.assertEqual(j.payout_operation.external_destination['destination_account']['address'],self.owner.bsc_address)
        self.assertEqual(j.payout_operation.source_amount,Decimal('2.5'))
        advance_journey(j.pk, client=self.api)
        self.assertEqual(MoneyOperation.objects.filter(money_flow=j.money_flow).count(),2)

    def test_outbound_correlates_infinia_credit_to_bridge_then_pays_local_account(self):
        t,_=self.prepared(); t.status='delivered';t.destination_tx_hash=DEST_HASH;t.save()
        entry=self.credit(self.crypto, provider_data={'third_party':{'type':'CRYPTO','crypto_network':'POLYGON','transaction_hash':DEST_HASH}})
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

    def test_quote_below_authorized_minimum_cannot_move_money(self):
        j=self.inbound();self.fx_quote(output='1.9')
        advance_journey(j.pk,client=self.api);j.refresh_from_db()
        self.assertEqual(j.stage,'needs_review');self.assertIsNone(j.fx_operation_id)
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
            request_id=request,minimum_fx_output='2',direction='to_wallet')
        first=create_journey(**args);self.assertEqual(create_journey(**args).pk,first.pk)
        args['minimum_fx_output']='3'
        with self.assertRaises(PaymentAccountError):create_journey(**args)

    def test_successful_provider_withdrawal_waits_for_chain_delivery(self):
        j=self.inbound();self.fx_quote();advance_journey(j.pk,client=self.api)
        self.settle_fx(j,self.crypto);advance_journey(j.pk,client=self.api);j.refresh_from_db()
        op=j.payout_operation;op.status='succeeded';op.save()
        advance_journey(j.pk,client=self.api);j.refresh_from_db()
        self.assertEqual(j.stage,'awaiting_wallet_delivery')
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
        self.settle_fx(j,self.crypto);advance_journey(j.pk,client=self.api);j.refresh_from_db()
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
