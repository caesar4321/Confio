import json
from decimal import Decimal
import uuid
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings

from blockchain.models import SponsoredBatch
from cusd_plus.cusd_vault import ConversionPreview
from cusd_plus.sponsor_7702 import PolicyError, SEL_CUSD_MINT, SEL_CUSD_REDEEM
from payment_accounts.infinia_fee_collection import mint_policy_calls, collection_evidence, wallet_received
from payment_accounts.infinia_fee_funding import collection_call, funding_plan, funding_calls, net_units
from payment_accounts.infinia_journeys import create_journey
from payment_accounts.services import PaymentAccountError
from . import test_infinia_journeys as helpers

TOKEN = '0x' + '66'*20
COLLECTOR = '0x' + '77'*20
WAD = 10**18


def preview(gross):
    net = net_units(gross, 90)
    return ConversionPreview(gross_wei=gross, net_wei=net, fee_wei=gross-net, fee_bps=90)


@override_settings(INFINIA_JOURNEYS_ENABLED=True, INFINIA_PAYMENT_ACCOUNTS_ENABLED=True,
    PAYMENT_BRIDGE_QUOTES_ENABLED=True, PAYMENT_BRIDGE_BSC_ENABLED=True, PAYMENT_BRIDGE_POLYGON_ENABLED=True,
    CUSD_PLUS_7702_ENABLED=True, CUSD_VAULT_ADDRESS=TOKEN, CUSD_PLUS_VAULT_ADDRESS='0x'+'88'*20,
    INFINIA_PASS_THROUGH_FEE_COUNTRIES='PE')
class FeeCollectionTests(TestCase):
    quote = helpers.JourneyTests.quote
    prepared = helpers.JourneyTests.prepared
    credit = helpers.JourneyTests.credit
    inbound = helpers.JourneyTests.inbound

    def setUp(self):
        helpers.JourneyTests.setUp(self)
        mock.patch('payment_accounts.activation.collector', return_value=COLLECTOR).start()
        mock.patch('cusd_plus.cusd_vault.preview_mint_wei', side_effect=preview).start()
        self.journey = self.inbound()
        transfer, _ = self.prepared(direction='to_wallet')
        transfer.status, transfer.actual_out_units = 'delivered', str(5*WAD)
        transfer.save()
        self.journey.bridge = transfer
        self.journey.save()
        self.fee = self.journey.money_flow.metadata['infinia_fee']
        self.request = f'local-mint-{self.journey.internal_id}_a0'
        self.mint = {'to': TOKEN, 'value': '0', 'data': '0x'+SEL_CUSD_MINT
            + f'{5*WAD:064x}' + f'{preview(5*WAD).net_wei:064x}' + self.owner.bsc_address[2:].rjust(64,'0')}
        self.calls = [self.mint, collection_call(self.fee)]

    def batch(self, status='confirmed', request=None):
        return SponsoredBatch.objects.create(user=self.user, user_bsc_address=self.owner.bsc_address,
            kind='mint_cusd', num_calls=2, calls_json=json.dumps(self.calls), tx_hash='0x'+'aa'*32,
            client_request_id=request or self.request, gas_limit=500000, max_fee_wei='1', status=status)

    def policy(self, calls=None, request=None):
        return mint_policy_calls(calls if calls is not None else self.calls, self.user,
                                 self.owner.bsc_address, request or self.request)

    def test_exact_mint_and_fee_are_authorized(self):
        self.assertEqual(self.policy(), [self.mint])

    def test_missing_changed_or_duplicate_fee_is_rejected(self):
        altered = dict(self.calls[-1], data=self.calls[-1]['data'][:-1]+'1')
        for calls in ([self.mint], [self.mint, altered], self.calls+self.calls[-1:]):
            with self.subTest(calls=calls), self.assertRaises(PolicyError):
                self.policy(calls)

    def test_fee_cannot_be_collected_from_existing_balance_without_exact_arrival(self):
        wrong = dict(self.mint, data=self.mint['data'][:10]+f'{WAD:064x}'+self.mint['data'][74:])
        with self.assertRaisesRegex(PolicyError, 'amount_mismatch'):
            self.policy([wrong, self.calls[-1]])

    def test_mint_must_preserve_authorized_net(self):
        wrong = dict(self.mint, data=self.mint['data'][:74]+f'{WAD:064x}'+self.mint['data'][138:])
        with self.assertRaisesRegex(PolicyError, 'below_minimum'):
            self.policy([wrong, self.calls[-1]])

    def test_confirmed_or_unknown_attempt_cannot_charge_again_under_a1(self):
        batch = self.batch()
        for status in ('confirmed', 'signed', 'sent', 'reorged'):
            batch.status = status
            batch.save()
            with self.subTest(status=status), self.assertRaisesRegex(PolicyError, 'already_pending'):
                self.policy(request=self.request[:-1]+'1')
        self.assertEqual(self.policy(), [self.mint])  # exact HTTP replay remains recoverable

    def test_generic_mint_cannot_consume_reserved_fee_bearing_arrival(self):
        with mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=5*WAD), \
             mock.patch('cusd_plus.vault.reserved_usdt_wei', return_value=5*WAD):
            with self.assertRaisesRegex(PolicyError, 'local_mint_request_required'):
                self.policy([self.mint], request='generic_a0')

    def test_only_confirmed_atomic_collection_reduces_received_amount(self):
        batch = self.batch(status='sent')
        journey = SimpleNamespace(direction='to_wallet', money_flow=self.journey.money_flow,
            confio_account=self.owner, wallet_address=self.owner.bsc_address,
            internal_id=self.journey.internal_id, wallet_conversion_id=1,
            wallet_conversion=SimpleNamespace(status='COMPLETED', to_transaction_hash=batch.tx_hash,
                net_amount_exact=Decimal('4.955'), to_amount=Decimal('4.955')))
        self.assertIsNone(collection_evidence(journey))
        self.assertIsNone(wallet_received(journey))
        batch.status = 'confirmed'; batch.save()
        self.assertEqual(collection_evidence(journey)['units'], str(WAD))
        self.assertEqual(wallet_received(journey), Decimal('3.955'))
        batch.status = 'reorged'; batch.save()
        self.assertIsNone(wallet_received(journey))

    def test_old_fee_free_outgoing_quote_is_rejected_before_funding(self):
        # The prior incoming fixture must not interfere with the fee preflight.
        self.request_id = uuid.uuid4()
        self.journey.bridge.deposit_address = '0x'+'bb'*20
        self.journey.bridge.save(update_fields=['deposit_address'])
        transfer, _ = self.prepared()
        with self.assertRaisesRegex(PaymentAccountError, 'nueva cotización'):
            create_journey(owner=self.owner, local_account=self.local, crypto_account=self.crypto,
                request_id=uuid.uuid4(), minimum_fx_output='1', direction='to_bank',
                bridge=transfer, destination=self.dest)

    def test_outgoing_calls_collect_cusd_and_redeem_only_principal(self):
        plan = funding_plan(budget=10*WAD, fee=WAD, wallet_usdt=0, wallet_cusd=10*WAD, fee_bps=90)
        with mock.patch('cusd_plus.cusd_vault.require_operational'), \
             mock.patch('cusd_plus.cusd_vault.preview_redeem_wei', side_effect=preview), \
             mock.patch('payment_accounts.bridge_chain.token_balance', return_value=0), \
             mock.patch('cusd_plus.vault.reserved_usdt_wei', return_value=0), \
             mock.patch('cusd_plus.vault.erc20_balance_raw', return_value=10*WAD):
            calls, funding = funding_calls(self.owner, plan, self.fee)
        self.assertEqual(calls[-1], collection_call(self.fee))
        self.assertEqual(calls[0]['data'][2:10], SEL_CUSD_REDEEM)
        self.assertEqual(int(calls[0]['data'][10:74],16), 9*WAD)
        self.assertEqual(funding['provider_fee_units'], str(WAD))

    def test_fee_quote_is_frozen_and_retry_does_not_reprice(self):
        self.request_id = uuid.uuid4()
        plan = funding_plan(budget=10*WAD, fee=WAD, wallet_usdt=0, wallet_cusd=10*WAD, fee_bps=90)
        with mock.patch('payment_accounts.local_money._active_pair', return_value=(self.local,self.crypto)), \
             mock.patch('payment_accounts.local_money.require_current_destination'), \
             mock.patch('payment_accounts.infinia_fee_funding.quote_funding', return_value=plan):
            quote = self.quote(destination_id=self.dest.internal_id)
        self.assertEqual(quote.amount_units, str(net_units(9*WAD,90)))
        self.assertEqual(quote.money_flow.source_amount, Decimal('10'))
        self.assertEqual(quote.money_flow.metadata['infinia_fee']['collector'], COLLECTOR)
        with mock.patch('payment_accounts.infinia_fee_policy.freeze', side_effect=AssertionError('must not reprice')):
            self.assertEqual(self.quote(destination_id=self.dest.internal_id).pk, quote.pk)
        with self.assertRaisesRegex(PaymentAccountError, 'different local destination'):
            self.quote(destination_id=uuid.uuid4())

    @override_settings(INFINIA_LEGACY_PAYOUT_FEES_ENABLED=True)
    def test_released_app_without_destination_freezes_fee_from_owned_estimate(self):
        from payment_accounts.infinia_legacy_fees import remember
        self.request_id = uuid.uuid4()
        remember(self.owner, self.instruction, '10', self.dest)
        plan = funding_plan(budget=10*WAD, fee=WAD, wallet_usdt=0, wallet_cusd=10*WAD, fee_bps=90)
        with mock.patch('payment_accounts.local_money._active_pair', return_value=(self.local, self.crypto)), \
             mock.patch('payment_accounts.local_money.require_current_destination'), \
             mock.patch('payment_accounts.infinia_fee_funding.quote_funding', return_value=plan):
            quoted = self.quote()  # exact old-client call: no destination_id
        self.assertEqual(quoted.money_flow.metadata['local_destination_id'], str(self.dest.internal_id))
        self.assertEqual(quoted.money_flow.metadata['infinia_fee']['units'], str(WAD))
        self.assertEqual(quoted.money_flow.source_amount, Decimal('10'))
        from payment_accounts.infinia_legacy_fees import require_review, record_review
        with self.assertRaises(PaymentAccountError):
            require_review(quoted.money_flow)
        record_review(quoted.money_flow, self.dest)
        quoted.money_flow.refresh_from_db()
        require_review(quoted.money_flow)
        with mock.patch('payment_accounts.infinia_fee_policy.freeze', side_effect=AssertionError('repriced')):
            self.assertEqual(self.quote().pk, quoted.pk)

    def test_small_deposit_collects_available_and_carries_residual_once(self):
        from payment_accounts.infinia_fee_debt import finalize_incoming, reconcile, quoted, reserve
        from payment_accounts.models import InfiniaFeeDebt, MoneyFlow
        self.journey.bridge.actual_out_units = str(WAD//2)
        self.journey.bridge.save(update_fields=['actual_out_units'])
        flow = self.journey.money_flow
        flow.metadata['infinia_fee']['minimum_net_units'] = '0'
        flow.save(update_fields=['metadata'])
        fee = finalize_incoming(self.journey)
        available = preview(WAD//2).net_wei
        self.assertEqual(int(fee['units']), available)
        self.assertEqual(int(fee['deferred_units']), WAD-available)
        self.assertEqual(finalize_incoming(self.journey), fee)
        self.assertEqual(InfiniaFeeDebt.objects.count(), 0)
        evidence = {'transaction_hash':'0x'+'ab'*32}
        reconcile(self.journey, evidence); reconcile(self.journey, evidence)
        self.assertEqual(InfiniaFeeDebt.objects.count(), 1)
        ids, amount = quoted(self.owner)
        self.assertEqual(amount, Decimal(WAD-available)/WAD)
        next_flow = MoneyFlow.objects.create(confio_account=self.owner,kind='fund',status='created',
            source_asset='PEN',source_amount='10',target_asset='USDT_BSC')
        reserve({'debt_ids':ids},next_flow)
        self.assertEqual(quoted(self.owner), ([], Decimal(0)))
        from payment_accounts.infinia_fees import FeePricingError
        with self.assertRaises(FeePricingError): reserve({'debt_ids':ids},flow)
        # Reorg/reconciliation cannot manufacture a second residual invoice.
        reconcile(self.journey,None); reconcile(self.journey,evidence)
        self.assertEqual(InfiniaFeeDebt.objects.count(),1)

    def test_small_deposit_policy_allows_zero_user_receipt_without_existing_funds(self):
        from payment_accounts.infinia_fee_debt import finalize_incoming
        self.journey.bridge.actual_out_units = str(WAD//2)
        self.journey.bridge.save(update_fields=['actual_out_units'])
        self.journey.money_flow.metadata['infinia_fee']['minimum_net_units'] = '0'
        self.journey.money_flow.save(update_fields=['metadata'])
        fee = finalize_incoming(self.journey)
        mint = dict(self.mint, data='0x'+SEL_CUSD_MINT+f'{WAD//2:064x}'
            +f'{int(fee["units"]):064x}'+self.owner.bsc_address[2:].rjust(64,'0'))
        self.assertEqual(self.policy([mint,collection_call(fee)]),[mint])

    def test_partial_fee_reprices_before_signing_but_never_after_signing(self):
        from payment_accounts.infinia_fee_debt import finalize_incoming
        self.journey.bridge.actual_out_units = str(WAD//2)
        self.journey.bridge.save(update_fields=['actual_out_units'])
        self.journey.money_flow.metadata['infinia_fee']['minimum_net_units'] = '0'
        self.journey.money_flow.save(update_fields=['metadata'])
        first = finalize_incoming(self.journey)
        with mock.patch('cusd_plus.cusd_vault.preview_mint_wei', return_value=ConversionPreview(
                gross_wei=WAD//2, net_wei=WAD//2, fee_wei=0, fee_bps=0)):
            second = finalize_incoming(self.journey)
            self.assertEqual(int(second['units']),WAD//2)
            self.assertEqual(second['invoice_units'],first['invoice_units'])
            self.batch(status='signed')
        self.assertEqual(finalize_incoming(self.journey),second)

    def test_persistence_rechecks_competing_attempt_before_broadcast(self):
        from django.db import transaction
        from payment_accounts.infinia_fee_collection import persist_local_fee
        self.policy()  # Both requests can pass the earlier check.
        first = self.batch(status='signed')
        first.tx_hash = '0x'+'bb'*32
        first.save(update_fields=['tx_hash'])
        competing_request = self.request[:-1]+'1'
        with self.assertRaisesRegex(PolicyError, 'already_pending'):
            with transaction.atomic():
                competing = self.batch(status='signed', request=competing_request)
                persist_local_fee(competing, b'unsigned-test')
        self.assertFalse(SponsoredBatch.objects.filter(client_request_id=competing_request).exists())
        persist_local_fee(first, b'unsigned-test')

    def test_persistence_rejects_fee_changed_after_initial_validation(self):
        from django.db import transaction
        from payment_accounts.infinia_fee_collection import persist_local_fee
        self.policy()
        self.journey.money_flow.refresh_from_db()
        self.journey.money_flow.metadata['infinia_fee']['units'] = str(WAD+1)
        self.journey.money_flow.save(update_fields=['metadata'])
        with self.assertRaisesRegex(PolicyError, 'transfer_required'):
            with transaction.atomic():
                batch = self.batch(status='signed')
                persist_local_fee(batch,b'unsigned-test')
        self.assertFalse(SponsoredBatch.objects.filter(client_request_id=self.request).exists())

    def test_bridge_cannot_submit_after_its_debt_reservation_is_reassigned(self):
        from payment_accounts.infinia_fee_collection import persist_bridge_fee
        from payment_accounts.models import InfiniaFeeDebt, MoneyFlow
        from payment_accounts.infinia_fees import FeePricingError
        source = MoneyFlow.objects.create(confio_account=self.owner,kind='fund',status='completed',
            source_asset='PEN',source_amount='1',target_asset='USDT_BSC')
        flow = self.journey.money_flow
        debt = InfiniaFeeDebt.objects.create(source_flow=source, amount_usd='0.10', reserved_flow=flow)
        flow.metadata['infinia_fee']['debt_ids'] = [debt.pk]
        flow.save(update_fields=['metadata'])
        persist_bridge_fee(self.owner,flow.pk,self.calls)
        debt.reserved_flow=None; debt.save(update_fields=['reserved_flow'])
        with self.assertRaises(FeePricingError):
            persist_bridge_fee(self.owner,flow.pk,self.calls)

    def test_reorg_retracts_completed_mint_and_keeps_arrival_reserved(self):
        from conversion.models import Conversion
        from cusd_plus.tasks import settle_savings_mint
        from cusd_plus.vault import reserved_usdt_wei
        from django.utils import timezone
        batch = self.batch()
        conversion = Conversion.objects.create(actor_user=self.user,actor_type='user',
            conversion_type='usdt_to_cusd',source='external_deposit',user_bsc_address=self.owner.bsc_address,
            from_amount='5',to_amount='4.955',gross_amount_exact='5',net_amount_exact='4.955',
            fee_amount_exact='.045',to_transaction_hash=batch.tx_hash,status='COMPLETED',completed_at=timezone.now())
        self.journey.wallet_conversion=conversion
        self.journey.save(update_fields=['wallet_conversion'])
        self.assertEqual(reserved_usdt_wei(self.user,self.owner.bsc_address),0)
        settle_savings_mint(batch.tx_hash,'reorged')
        batch.status='reorged'; batch.save(update_fields=['status'])
        conversion.refresh_from_db()
        self.assertEqual(conversion.status,'SUBMITTED')
        self.assertIsNone(conversion.completed_at)
        self.assertEqual(reserved_usdt_wei(self.user,self.owner.bsc_address),5*WAD)
        # Seeing the same reorg twice must retain the same pending conversion.
        settle_savings_mint(batch.tx_hash,'reorged')
        settle_savings_mint(batch.tx_hash,'confirmed')
        batch.status='confirmed'; batch.save(update_fields=['status'])
        conversion.refresh_from_db()
        self.assertEqual(conversion.status,'COMPLETED')
        self.assertEqual(conversion.error_message,'')
        self.assertEqual(reserved_usdt_wei(self.user,self.owner.bsc_address),0)

    def test_another_business_actor_cannot_sweep_the_wallets_local_arrival(self):
        from django.contrib.auth import get_user_model
        from cusd_plus.vault import reserved_usdt_wei
        actor = get_user_model().objects.create_user(username='business-actor',email='actor@example.test')
        self.assertEqual(reserved_usdt_wei(actor,self.owner.bsc_address),5*WAD)
        with mock.patch('cusd_plus.vault.usdt_balance_raw',return_value=5*WAD):
            with self.assertRaisesRegex(PolicyError,'local_mint_request_required'):
                mint_policy_calls([self.mint],actor,self.owner.bsc_address,'generic_a0')
        with self.assertRaisesRegex(PolicyError,'local_mint_owner_required'):
            mint_policy_calls(self.calls,actor,self.owner.bsc_address,self.request)
