from datetime import timedelta
from decimal import Decimal
from unittest import mock
import uuid

from django.test import TestCase, override_settings
from django.utils import timezone

from payment_accounts.models import FinancialAccount, AccountCapability, LedgerEntry, PayoutDestination, MoneyOperation, CobreJourney
from payment_accounts.cobre_journeys import create_journey, advance_journey, attach_return_bridge, observe_refund
from payment_accounts.services import PaymentAccountError, _sync_flow_status, submit_money_operation
from payment_accounts.providers.cobre import CobreProvider
from payment_accounts.providers.base import ProviderCapabilityError
from payment_accounts.bridge_execution import reconcile_provider_credit
from .test_bridge import BridgeQuoteTests
from .test_bridge_execution import BridgeExecutionTests, DEST_HASH, receipt


@override_settings(COBRE_JOURNEYS_ENABLED=True, COBRE_PAYMENT_ACCOUNTS_ENABLED=True,
    PAYMENT_BRIDGE_QUOTES_ENABLED=True, PAYMENT_BRIDGE_BSC_ENABLED=True, PAYMENT_BRIDGE_POLYGON_ENABLED=True,
    CUSD_PLUS_7702_ENABLED=True)
class CobreJourneyTests(TestCase):
    quote = BridgeQuoteTests.quote
    prepared = BridgeExecutionTests.prepared

    def setUp(self):
        BridgeQuoteTests.setUp(self)
        self.crypto = self.instruction.financial_account
        profile = self.crypto.provider_profile
        profile.provider = 'cobre'; profile.save()
        self.crypto.asset='USD_STABLE';self.crypto.provider_account_id='crypto';self.crypto.save()
        self.local = FinancialAccount.objects.create(provider_profile=profile, provider_account_id='local', country='COL',
            asset='COP', status='active', ownership_structure='omnibus_subledger')
        self.copco = FinancialAccount.objects.create(provider_profile=profile, provider_account_id='copco', country='XXX',
            asset='COPCO', status='active', ownership_structure='omnibus_subledger')
        for account in (self.local,self.crypto,self.copco):
            for capability in ('convert','send_third_party','crypto_payout'):
                AccountCapability.objects.create(financial_account=account,capability=capability,status='enabled')
        self.dest=PayoutDestination.objects.create(confio_account=self.owner,provider='cobre',kind='breb_key',country='COL',
            asset='COP',label='Bre-B',holder_name='Holder',status='active',provider_destination_id='bank',details={'key_value':'key'})
        self.wallet=PayoutDestination.objects.create(confio_account=self.owner,provider='cobre',kind='crypto_wallet',country='XXX',
            asset='USDC_POL',label='Wallet',holder_name='Holder',status='active',provider_destination_id='wallet',details={'address':self.owner.bsc_address})
        mock.patch('payment_accounts.cobre_journeys.enforce_and_record').start()
        self.submit=mock.patch('payment_accounts.cobre_journeys.submit_money_operation',side_effect=lambda op:op).start()
        self.api=mock.Mock()
        self.api.create_money_movement.return_value={'id':'mm-response','status':{'state':'initiated'}}
        self.api.create_cross_border_movement.return_value={'id':'fx-response','status':{'state':'initiated'}}
        self.api.get_counterparty.return_value={'id':'wallet','type':'global_deposit_np','metadata':{
            'counterparty_verification_status':'verified','counterparty_chain':'polygon','counterparty_wallet_address':self.owner.bsc_address}}

    def credit(self, account, amount, kind, op_id='', **extra):
        return LedgerEntry.objects.create(provider='cobre',financial_account=account,provider_entry_id=str(uuid.uuid4()),
            direction='credit',asset=account.asset,amount=amount,occurred_at=timezone.now(),provider_data={'content':{
                'type':kind,'credit_debit_type':'credit','metadata':{'money_movement_id':op_id,**extra}}})

    def start(self, direction='to_wallet', **overrides):
        args=dict(owner=self.owner,local_account=self.local,crypto_account=self.crypto,copco_account=self.copco,
            request_id=uuid.uuid4(),minimum_fx_output='2' if direction=='to_wallet' else '30000',direction=direction)
        if direction=='to_wallet':args['credit']=self.credit(self.local,'10000','breb_credit')
        else:
            bridge,_=self.prepared();bridge.status='delivered';bridge.destination_tx_hash=DEST_HASH;bridge.save()
            e=self.credit(self.crypto,'10','global_credit',tracking_key=DEST_HASH,chain='polygon',token='usdc',
                beneficiary_wallet_address=bridge.quote.destination_address)
            reconcile_provider_credit(bridge);bridge.refresh_from_db();self.assertEqual(bridge.provider_credit_id,e.pk)
            args.update(bridge=bridge,destination=self.dest)
        args.update(overrides)
        return create_journey(**args)

    def quote_response(self, direction='to_wallet', output=None):
        self.api.create_fx_quote.return_value=dict(id='fx-quote',type='static_quote',
            currency_pair='copco/usd_stable' if direction=='to_wallet' else 'usd_stable/copco',
            source_amount=1000000 if direction=='to_wallet' else 1000,
            destination_amount=output if output is not None else (250 if direction=='to_wallet' else 3900000),
            valid_until=(timezone.now()+timedelta(minutes=1)).isoformat())

    def post_leg(self,j,leg,target,amount,kind):
        j.refresh_from_db();op=getattr(j,leg+'_operation');op.provider_operation_id=leg+'-'+str(j.internal_id);op.status='succeeded';op.save()
        # Intentionally leave LedgerEntry.operation null: transaction webhook
        # can precede the create response that stores the provider ID.
        return self.credit(target,amount,kind,op.provider_operation_id)

    def inbound_payout(self):
        j=self.start();self.quote_response();advance_journey(j.pk,client=self.api)
        self.post_leg(j,'ramp',self.copco,'10000','onramp_credit');advance_journey(j.pk,client=self.api)
        self.post_leg(j,'fx',self.crypto,'2.5','cbmm_credit');advance_journey(j.pk,client=self.api);j.refresh_from_db()
        return j

    def test_inbound_requires_onramp_and_fx_credits_before_wallet_payout(self):
        j=self.start();self.quote_response();advance_journey(j.pk,client=self.api);j.refresh_from_db()
        self.assertEqual(j.ramp_operation.operation_type,'internal_transfer');self.assertIsNone(j.fx_operation_id)
        j.ramp_operation.status='succeeded';j.ramp_operation.save();_sync_flow_status(j.money_flow)
        advance_journey(j.pk,client=self.api);j.refresh_from_db();self.assertIsNone(j.fx_operation_id)
        self.post_leg(j,'ramp',self.copco,'10000','onramp_credit');advance_journey(j.pk,client=self.api)
        j.refresh_from_db();self.assertEqual(j.fx_operation.source_asset,'COPCO');self.assertIsNone(j.payout_operation_id)
        self.post_leg(j,'fx',self.crypto,'2.5','cbmm_credit');advance_journey(j.pk,client=self.api);j.refresh_from_db()
        self.assertEqual(j.payout_operation.source_amount,Decimal('2.5'))
        self.assertEqual(j.payout_operation.external_destination['wallet_address'],self.owner.bsc_address)
        j.money_flow.refresh_from_db();self.assertEqual(j.money_flow.status,'processing')

    def test_outbound_requires_stablefx_then_standard_offramp_before_breb(self):
        j=self.start('to_bank');self.quote_response('to_bank');advance_journey(j.pk,client=self.api)
        self.post_leg(j,'fx',self.copco,'39000','cbmm_credit');advance_journey(j.pk,client=self.api);j.refresh_from_db()
        adapter=CobreProvider(client=self.api);adapter.create_transfer(j.ramp_operation)
        self.assertEqual(self.api.create_money_movement.call_args.args[0]['metadata']['settlement_type'],'standard')
        self.post_leg(j,'ramp',self.local,'39000','offramp_credit');advance_journey(j.pk,client=self.api);j.refresh_from_db()
        self.assertEqual(j.payout_operation.source_account_id,self.local.pk)
        j.payout_operation.status='succeeded';j.payout_operation.save();advance_journey(j.pk,client=self.api);j.refresh_from_db()
        self.assertEqual(j.stage,'completed');self.assertIsNone(j.money_flow.target_amount)

    def test_wrong_credit_id_or_reward_does_not_fund_next_leg(self):
        j=self.start();advance_journey(j.pk);j.refresh_from_db()
        op=j.ramp_operation;op.status='succeeded';op.provider_operation_id='ramp-id';op.save()
        self.credit(self.copco,'10000','onramp_credit','someone-else')
        self.credit(self.copco,'10000','reward_credit','ramp-id')
        advance_journey(j.pk);j.refresh_from_db();self.assertIsNone(j.fx_operation_id)

    def test_bad_quote_never_executes_fx(self):
        for change in ({'destination_amount':199},{'currency_pair':'usd/cop'},{'source_amount':1},
                       {'valid_until':(timezone.now()-timedelta(seconds=1)).isoformat()}):
            with self.subTest(change=change):
                j=self.start();advance_journey(j.pk)
                self.post_leg(j,'ramp',self.copco,'10000','onramp_credit');self.quote_response()
                self.api.create_fx_quote.return_value.update(change);advance_journey(j.pk,client=self.api);j.refresh_from_db()
                self.assertEqual(j.stage,'needs_review');self.assertIsNone(j.fx_operation_id)
                j.stage='failed';j.save() # release owner only for independent test case

    def test_credit_mismatch_requires_review(self):
        j=self.start();advance_journey(j.pk);self.post_leg(j,'ramp',self.copco,'9999','onramp_credit')
        advance_journey(j.pk);j.refresh_from_db();self.assertEqual(j.stage,'needs_review');self.assertIsNone(j.fx_operation_id)

    def test_retry_retains_original_quote_after_error_payload_replacement(self):
        j=self.inbound_payout();op=j.fx_operation;op.provider_data={'timeout':True};op.save()
        self.api.create_fx_quote.reset_mock();CobreProvider(client=self.api).create_transfer(op)
        self.api.create_fx_quote.assert_not_called()
        self.assertEqual(self.api.create_cross_border_movement.call_args.args[0]['forex_quote_id'],'fx-quote')

    def test_unknown_leg_is_not_recreated(self):
        j=self.start();advance_journey(j.pk);j.refresh_from_db();op=j.ramp_operation;op.status='unknown';op.save()
        self.submit.reset_mock();advance_journey(j.pk);self.submit.assert_not_called()
        self.assertEqual(j.money_flow.operations.count(),1)

    def test_refund_reopens_even_completed_journey(self):
        j=self.inbound_payout();j.stage='completed';j.save()
        e=self.credit(self.copco,'10000','misc_credit',j.fx_operation.provider_operation_id)
        observe_refund(e);j.refresh_from_db();self.assertEqual(j.stage,'needs_review')

    def test_late_child_failure_reopens_parent(self):
        j=self.inbound_payout();j.stage='completed';j.save();op=j.fx_operation;op.status='reversed';op.save()
        _sync_flow_status(j.money_flow);j.refresh_from_db();self.assertEqual(j.stage,'needs_review')

    def test_provider_success_is_not_polygon_delivery(self):
        j=self.inbound_payout();op=j.payout_operation;op.status='succeeded';op.provider_operation_id='payout-id';op.save()
        advance_journey(j.pk);j.refresh_from_db();self.assertEqual(j.stage,'awaiting_wallet_delivery')

    def test_polygon_receipt_binds_hash_token_wallet_and_actual_amount(self):
        from payment_accounts import bridge_chain as chain
        j=self.inbound_payout();op=j.payout_operation;op.status='succeeded';op.provider_operation_id='payout-id';op.save()
        LedgerEntry.objects.create(provider='cobre',financial_account=self.crypto,provider_entry_id='payout-debit',
            direction='debit',asset='USD_STABLE',amount='2.5',occurred_at=timezone.now(),provider_data={'content':{
                'type':'stable_payout_debit','credit_debit_type':'debit','metadata':{'money_movement_id':'payout-id',
                'beneficiary_chain':'polygon','beneficiary_token':'USDC','beneficiary_account_number':self.owner.bsc_address,
                'tracking_key':DEST_HASH}}})
        with mock.patch.object(chain,'final_receipt',return_value=receipt('POL:USDC',self.owner.bsc_address,2490000)):
            advance_journey(j.pk)
        j.refresh_from_db();self.assertEqual(j.stage,'awaiting_wallet_authorization');self.assertEqual(j.wallet_arrival_units,'2490000')

    def test_unverified_or_changed_counterparty_cannot_receive_payout(self):
        j=self.inbound_payout();adapter=CobreProvider(client=self.api)
        for key,value in [('counterparty_verification_status','processing'),('counterparty_chain','ethereum'),
                          ('counterparty_wallet_address','0x'+'ab'*20)]:
            original=self.api.get_counterparty.return_value['metadata'][key]
            self.api.get_counterparty.return_value['metadata'][key]=value
            with self.assertRaises(ProviderCapabilityError):adapter.create_payout(j.payout_operation)
            self.api.get_counterparty.return_value['metadata'][key]=original
        self.api.create_money_movement.assert_not_called()
        adapter.create_payout(j.payout_operation)
        self.assertEqual(self.api.create_money_movement.call_args.args[0]['destination_id'],'wallet')

    def test_ramp_retrieval_uses_money_movements_not_cross_border(self):
        j=self.start();advance_journey(j.pk);j.refresh_from_db()
        self.api.find_money_movement.return_value={'items':[{'id':'ramp-id','status':{'state':'completed'}}]}
        CobreProvider(client=self.api).retrieve_operation_by_idempotency(j.ramp_operation)
        self.api.find_money_movement.assert_called_once();self.api.find_cross_border_movement.assert_not_called()

    def test_owned_request_idempotency_and_immutable_terms(self):
        e=self.credit(self.local,'10000','breb_credit');request=uuid.uuid4()
        j=self.start(credit=e,request_id=request)
        self.assertEqual(self.start(credit=e,request_id=request).pk,j.pk)
        with self.assertRaises(PaymentAccountError):self.start(credit=e,request_id=request,minimum_fx_output='3')

    def test_other_owner_and_refund_deposits_are_rejected(self):
        other=type(self.owner).objects.create(user=self.user,account_type='personal',account_index=1,bsc_address="0x"+"ab"*20)
        with self.assertRaises(PaymentAccountError):self.start(owner=other)
        e=self.credit(self.local,'10000','breb_rejected')
        with self.assertRaises(PaymentAccountError):self.start(credit=e)

    def test_unrelated_submission_cannot_spend_reserved_copco(self):
        j=self.start();op=MoneyOperation.objects.create(provider='cobre',operation_type='conversion',source_account=self.copco,
            source_amount='1',source_asset='COPCO',idempotency_key=str(uuid.uuid4()))
        with self.assertRaisesRegex(PaymentAccountError,'reserved'):submit_money_operation(op)

    def test_late_unknown_operation_is_not_retried_after_idempotency_window(self):
        from payment_accounts.tasks import reconcile_operations
        j=self.start();advance_journey(j.pk);j.refresh_from_db();op=j.ramp_operation
        MoneyOperation.objects.filter(pk=op.pk).update(status='unknown',submitted_at=timezone.now()-timedelta(hours=24),updated_at=timezone.now()-timedelta(hours=1))
        with mock.patch('payment_accounts.tasks.get_provider') as provider, mock.patch('payment_accounts.tasks.submit_money_operation') as submit:
            provider.return_value.retrieve_operation_by_idempotency.return_value=None
            reconcile_operations();submit.assert_not_called()
        op.refresh_from_db();j.refresh_from_db();self.assertEqual(op.status,'needs_review');self.assertEqual(j.stage,'needs_review')

    def test_early_refund_is_detected_when_provider_id_becomes_known(self):
        j=self.start();advance_journey(j.pk);j.refresh_from_db()
        self.credit(self.local,'10000','misc_credit','late-bound-id')
        op=j.ramp_operation;op.provider_operation_id='late-bound-id';op.status='succeeded';op.save()
        self.credit(self.copco,'10000','onramp_credit','late-bound-id')
        self.quote_response();self.submit.reset_mock();advance_journey(j.pk,client=self.api);j.refresh_from_db()
        self.assertEqual(j.stage,'needs_review');self.assertIsNone(j.fx_operation_id);self.submit.assert_not_called()

    def test_queued_leg_cannot_submit_after_journey_enters_review(self):
        j=self.start();advance_journey(j.pk);j.refresh_from_db();j.stage='needs_review';j.save()
        with self.assertRaisesRegex(PaymentAccountError,'further submissions'):submit_money_operation(j.ramp_operation)

    def test_explicit_debit_event_with_positive_amount_is_not_a_credit(self):
        import json
        from payment_accounts.webhooks import store_webhook, process_webhook_event
        body=json.dumps({'id':'event-debit','event_key':'accounts.balance.debit','content':{
            'id':'tx-debit','account_id':'crypto','amount':250,'currency':'usd_stable',
            'type':'stable_payout_debit','credit_debit_type':'debit','metadata':{}}}).encode()
        event,_=store_webhook(provider='cobre',raw_body=body,headers={});process_webhook_event(event)
        entry=LedgerEntry.objects.get(provider_entry_id='tx-debit')
        self.assertEqual(entry.direction,'debit');self.assertEqual(entry.amount,Decimal('2.5'))

    def test_return_bridge_requires_exact_proven_amount_and_current_owner(self):
        j=self.inbound_payout();j.stage='awaiting_wallet_authorization';j.wallet_arrival_units='2490000';j.save()
        bridge,_=self.prepared('to_wallet')
        with self.assertRaises(PaymentAccountError):attach_return_bridge(owner=self.owner,journey_id=j.internal_id,bridge=bridge)
        bridge.quote.amount_units='2490000';bridge.quote.save()
        linked=attach_return_bridge(owner=self.owner,journey_id=j.internal_id,bridge=bridge)
        self.assertEqual(linked.stage,'bridging')
        self.assertEqual(attach_return_bridge(owner=self.owner,journey_id=j.internal_id,bridge=bridge).pk,j.pk)
