import importlib
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.apps import apps
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings

from payment_accounts import activation, local_money
from payment_accounts.models import AccountActivation, FinancialAccount, FundingInstruction, ProviderProfile
from payment_accounts.services import PaymentAccountError
from send.models import SendTransaction
from users.models import Account, User

WAD=10**18
COLLECTOR='0x'+'2'*40
TOKEN='0x'+'4'*40
VAULT='0x'+'5'*40


@override_settings(CUSD_PLUS_7702_ENABLED=True, BSC_SEND_ENABLED=True,
                   CUSD_VAULT_ADDRESS=TOKEN, CUSD_PLUS_VAULT_ADDRESS=VAULT)
class ActivationTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user(username='activation-user', firebase_uid='activation-user')
        self.owner=Account.objects.create(user=self.user, account_type='personal', bsc_address='0x'+'1'*40)
        self.ctx={'account_type':'personal','account_index':0}
        self.preflight=mock.patch('payment_accounts.local_money.activation_preflight', return_value=(local_money.METHODS['co_breb'],None))
        self.preflight.start(); self.addCleanup(self.preflight.stop)
        self.collector=mock.patch.object(activation,'collector',return_value=COLLECTOR)
        self.collector.start(); self.addCleanup(self.collector.stop)

    def open_accounts(self, *args):
        profile,_=ProviderProfile.objects.get_or_create(confio_account=self.owner, provider='infinia',
                                                       defaults={'owner_type':'individual','status':'active'})
        for country,asset,kind in [('COL','COP','breb_key'),('XXX','USDC_POL','crypto_address')]:
            account,_=FinancialAccount.objects.get_or_create(provider_profile=profile,country=country,asset=asset,
                     defaults={'status':'active','ownership_structure':'provider_named','provider_account_id':asset})
            FundingInstruction.objects.get_or_create(financial_account=account,kind=kind,
                                                       defaults={'status':'active','display_value':'instruction-'+asset})
        return 'active'

    def fake_payment(self, owner, ctx, row):
        return SendTransaction.objects.create(sender_user=owner.user,sender_address=owner.bsc_address,
            recipient_address=row.collector_address,recipient_type='external',amount=Decimal(row.amount),
            token_type='CUSD',status='PENDING',bsc_calls_json=json.dumps({'kind':'send_cusd','calls':[]}))

    def row(self, status='provisioning'):
        return AccountActivation.objects.create(confio_account=self.owner,country='COL',asset='COP',
            method_id='co_breb',status=status,collector_address=COLLECTOR,settlement_token_address=TOKEN)

    def prepare(self, accepted_fee=None):
        return activation.prepare(self.owner,None,'co_breb',self.ctx,accepted_fee=accepted_fee)

    def test_consent_quote_does_not_open_or_charge(self):
        with mock.patch('payment_accounts.local_money.activate') as opening, mock.patch.object(activation,'_prepare_send') as pay:
            row,payment=self.prepare()
        self.assertEqual(row.status,'consent_required')
        self.assertEqual(row.amount,Decimal('10.00'))
        self.assertIsNone(payment)
        self.assertFalse(AccountActivation.objects.exists())
        opening.assert_not_called(); pay.assert_not_called()

    def test_provider_failure_is_persisted_and_prepare_reports_safe_error(self):
        from payment_accounts.clients import ProviderAPIError
        with mock.patch('payment_accounts.local_money.activate', side_effect=ProviderAPIError(
                'secret provider payload', status_code=500, retryable=True)), \
                mock.patch.object(activation, '_prepare_send') as pay:
            with self.assertRaisesMessage(PaymentAccountError, 'Volveremos a intentarlo automáticamente') as failure:
                self.prepare('10.00')
        self.assertNotIn('secret', str(failure.exception))
        row = AccountActivation.objects.get(confio_account=self.owner)
        self.assertEqual(row.opening_failures, 1)
        self.assertEqual(row.opening_error, 'provider_unavailable')
        self.assertIsNotNone(row.next_opening_retry_at)
        self.assertIsNone(row.payment_id)
        pay.assert_not_called()

    def test_polling_and_worker_share_exponential_backoff_and_request_identity(self):
        from datetime import timedelta
        from django.utils import timezone
        from payment_accounts.clients import ProviderAPIError
        row = self.row()
        now = timezone.now()
        with mock.patch('payment_accounts.activation.timezone.now') as clock, \
                mock.patch('payment_accounts.local_money.activate', side_effect=ProviderAPIError(
                    'unavailable', status_code=503, retryable=True)) as opening:
            for count, delay in enumerate([30, 60, 120, 240, 480, 900, 900], 1):
                clock.return_value = now
                result = activation.reconcile(row.pk)
                self.assertEqual(result.opening_failures, count)
                self.assertEqual(result.next_opening_retry_at, now + timedelta(seconds=delay))
                self.assertEqual(result.internal_id, row.internal_id)
                self.assertEqual(result.attempt, 0)
                clock.return_value = now + timedelta(seconds=delay - 1)
                activation.reconcile(row.pk)
                self.assertEqual(opening.call_count, count)
                now += timedelta(seconds=delay)
        self.assertEqual(AccountActivation.objects.count(), 1)

    def test_permanent_failure_pauses_automatic_and_manual_retries(self):
        from payment_accounts.clients import ProviderAPIError
        row = self.row()
        with mock.patch('payment_accounts.local_money.activate', side_effect=ProviderAPIError(
                'invalid owner', status_code=400)) as opening:
            result = activation.reconcile(row.pk)
            activation.reconcile(row.pk)
            with self.assertRaisesMessage(PaymentAccountError, 'Contacta a soporte'):
                self.prepare()
        self.assertEqual(opening.call_count, 1)
        self.assertIsNone(result.next_opening_retry_at)
        self.assertEqual(result.opening_error, 'opening_needs_review')

    def test_rate_limit_schedules_retry_even_without_retryable_flag(self):
        from payment_accounts.clients import ProviderAPIError
        row = self.row()
        with mock.patch('payment_accounts.local_money.activate', side_effect=ProviderAPIError(
                'rate limit', status_code=429)):
            result = activation.reconcile(row.pk)
        self.assertIsNotNone(result.next_opening_retry_at)

    def test_policy_blocks_and_missing_policy_do_not_retry(self):
        from payment_accounts.eligibility import EligibilityDenied, EligibilityPolicyNotConfigured
        row = self.row()
        for failure in [EligibilityDenied(SimpleNamespace(decision='block', reason_code='country_disabled')),
                        EligibilityPolicyNotConfigured('missing policy')]:
            with self.subTest(failure=type(failure).__name__):
                AccountActivation.objects.filter(pk=row.pk).update(opening_error='', opening_failures=0)
                with mock.patch('payment_accounts.local_money.activate', side_effect=failure) as opening:
                    result = activation.reconcile(row.pk)
                    activation.reconcile(row.pk)
                self.assertEqual(opening.call_count, 1)
                self.assertEqual(result.opening_error, 'opening_needs_review')
                self.assertIsNone(result.next_opening_retry_at)

    def test_due_retry_clears_failure_after_recovery(self):
        from django.utils import timezone
        row = self.row()
        row.opening_error = 'provider_unavailable'
        row.opening_failures = 3
        row.next_opening_retry_at = timezone.now()
        row.save()
        with mock.patch('payment_accounts.local_money.activate', side_effect=self.open_accounts) as opening:
            result = activation.reconcile(row.pk)
        opening.assert_called_once()
        self.assertEqual(result.status, 'awaiting_payment')
        self.assertEqual(result.opening_error, '')
        self.assertEqual(result.opening_failures, 0)
        self.assertIsNone(result.next_opening_retry_at)
        self.assertIsNone(result.payment_id)

    def test_webhook_readiness_bypasses_cooldown_without_provider_retry(self):
        from datetime import timedelta
        from django.utils import timezone
        row = self.row()
        row.opening_error = 'provider_unavailable'
        row.next_opening_retry_at = timezone.now() + timedelta(minutes=15)
        row.save()
        self.open_accounts()
        with mock.patch('payment_accounts.local_money.activate') as opening:
            result = activation.reconcile(row.pk)
        opening.assert_not_called()
        self.assertEqual(result.status, 'awaiting_payment')
        self.assertEqual(result.opening_error, '')

    def test_activation_mutation_returns_failure_during_cooldown(self):
        from datetime import timedelta
        from django.utils import timezone
        from payment_accounts.local_money_schema import ActivateLocalMoney
        row = self.row()
        row.opening_error = 'provider_unavailable'
        row.next_opening_retry_at = timezone.now() + timedelta(minutes=1)
        row.save()
        with mock.patch('payment_accounts.local_money_schema._owner', return_value=self.owner), \
                mock.patch('payment_accounts.breb_location.require_for_country'), \
                mock.patch('payment_accounts.local_money.activate') as opening:
            result = ActivateLocalMoney.mutate(None, SimpleNamespace(context=SimpleNamespace(META={})), 'co_breb')
        self.assertFalse(result.success)
        self.assertIn('Volveremos a intentarlo', result.errors[0])
        self.assertIsNone(result.status)
        opening.assert_not_called()

    def test_wrong_fee_acceptance_rejected_without_provider_call(self):
        with self.assertRaises(PaymentAccountError): self.prepare('0')
        self.assertFalse(AccountActivation.objects.exists())

    def test_payment_rejects_changed_chain_or_token(self):
        row = self.row(status='awaiting_payment')
        for setting in [{'BSC_CHAIN_ID': row.chain_id + 1}, {'CUSD_VAULT_ADDRESS': VAULT}]:
            with self.subTest(setting=setting), override_settings(**setting), \
                    mock.patch.object(activation, '_prepare_send') as pay:
                with self.assertRaises(PaymentAccountError):
                    activation._payment(self.owner, row.pk, self.ctx)
                pay.assert_not_called()

    def test_opening_and_failure_never_prepare_a_payment(self):
        with mock.patch('payment_accounts.local_money.activate',return_value='provisioning'), mock.patch.object(activation,'_prepare_send') as pay:
            row,payment=self.prepare('10.00')
            self.assertEqual(row.status,'provisioning'); self.assertIsNone(payment)
            self.assertIsNotNone(row.accepted_at)
            pay.assert_not_called()
        with mock.patch('payment_accounts.local_money.activate',return_value='failed'), mock.patch.object(activation,'_prepare_send') as pay:
            row,payment=self.prepare()
            self.assertEqual(row.status,'failed'); self.assertIsNone(payment)
            pay.assert_not_called()

    def test_active_provider_without_details_is_not_ready_to_charge(self):
        with mock.patch('payment_accounts.local_money.activate',side_effect=self.open_accounts):
            row=activation._opening(self.owner,None,'co_breb','10')
            self.open_accounts()
            FundingInstruction.objects.filter(kind='breb_key').update(display_value='')
        with mock.patch('payment_accounts.local_money.activate',return_value='active'), mock.patch.object(activation,'_prepare_send') as pay:
            row,payment=self.prepare()
        self.assertEqual(row.status,'provisioning'); self.assertIsNone(payment)
        pay.assert_not_called()

    def test_prepared_payment_is_blocked_when_readiness_is_lost(self):
        from datetime import timedelta
        from django.utils import timezone
        from send.bsc_flow import _validate_send_batch
        from cusd_plus.sponsor_7702 import PolicyError
        self.open_accounts()
        row = self.row('payment_pending')
        row.payment = self.fake_payment(self.owner, self.ctx, row)
        row.save(update_fields=['payment'])
        meta = {'activation_id': str(row.internal_id), 'kind': 'send_cusd', 'units': str(10 * WAD)}
        for failure in ['closed', 'profile_suspended', 'inactive_instruction', 'expired_local', 'expired_crypto']:
            with self.subTest(failure=failure):
                FinancialAccount.objects.update(status='active')
                ProviderProfile.objects.update(status='active')
                FundingInstruction.objects.update(status='active', expires_at=None)
                if failure == 'closed':
                    FinancialAccount.objects.filter(country='COL').update(status='closed')
                elif failure == 'profile_suspended':
                    ProviderProfile.objects.update(status='suspended')
                elif failure == 'inactive_instruction':
                    FundingInstruction.objects.filter(kind='breb_key').update(status='inactive')
                else:
                    kind = 'breb_key' if failure == 'expired_local' else 'crypto_address'
                    FundingInstruction.objects.filter(kind=kind).update(expires_at=timezone.now() - timedelta(seconds=1))
                self.assertFalse(activation.opening_ready(row))
                with self.assertRaises(PaymentAccountError):
                    activation._payment(self.owner, row.pk, self.ctx)
                with self.assertRaisesMessage(PolicyError, 'invalid_activation_payment'):
                    _validate_send_batch([], row.payment, meta)

    def test_submit_checks_snapshotted_chain_and_token(self):
        from send.bsc_flow import _validate_send_batch
        from cusd_plus.sponsor_7702 import PolicyError
        self.open_accounts()
        row = self.row('payment_pending')
        row.payment = self.fake_payment(self.owner, self.ctx, row)
        row.save(update_fields=['payment'])
        meta = {'activation_id': str(row.internal_id), 'kind': 'send_cusd', 'units': str(10 * WAD)}
        for setting in [{'BSC_CHAIN_ID': row.chain_id + 1}, {'CUSD_VAULT_ADDRESS': VAULT}]:
            with self.subTest(setting=setting), override_settings(**setting):
                with self.assertRaisesMessage(PolicyError, 'invalid_activation_payment'):
                    _validate_send_batch([], row.payment, meta)

    def test_terminal_unpaid_account_releases_opening_allowance(self):
        self.open_accounts()
        row = self.row('awaiting_payment')
        FinancialAccount.objects.filter(country='COL').update(status='closed')
        with mock.patch('payment_accounts.local_money.activate') as opening:
            updated = activation.reconcile(row.pk)
        self.assertEqual(updated.status, 'failed')
        opening.assert_not_called()
        with mock.patch('payment_accounts.local_money.activation_preflight', return_value=(local_money.METHODS['mx_clabe'], None)):
            another = activation._opening(self.owner, None, 'mx_clabe', '10')
        self.assertEqual(another.status, 'provisioning')

    def test_terminal_profile_releases_only_without_executable_payment(self):
        self.open_accounts()
        row = self.row('payment_pending')
        row.payment = self.fake_payment(self.owner, self.ctx, row)
        row.save(update_fields=['payment'])
        ProviderProfile.objects.update(status='closed')
        for status in ['PENDING', 'SUBMITTED']:
            row.payment.status = status
            row.payment.save(update_fields=['status'])
            self.assertEqual(activation.reconcile(row.pk).status, 'payment_pending')
        row.payment.status = 'FAILED'
        row.payment.save(update_fields=['status'])
        self.assertEqual(activation.reconcile(row.pk).status, 'failed')

    def test_unready_unpaid_account_resyncs_without_new_activation_or_payment(self):
        self.open_accounts()
        row = self.row('awaiting_payment')
        FinancialAccount.objects.filter(country='COL').update(status='suspended')
        def recovered(*args):
            FinancialAccount.objects.filter(country='COL').update(status='active')
            return 'active'
        with mock.patch('payment_accounts.local_money.activate', side_effect=recovered) as opening:
            updated = activation.reconcile(row.pk)
        opening.assert_called_once()
        self.assertEqual(updated.status, 'awaiting_payment')
        self.assertEqual(AccountActivation.objects.count(), 1)
        self.assertIsNone(updated.payment_id)

    def test_ready_then_payment_confirmation_unlocks_account(self):
        with mock.patch('payment_accounts.local_money.activate',side_effect=self.open_accounts) as opening, \
             mock.patch.object(activation,'_prepare_send',side_effect=self.fake_payment) as pay:
            row,payment=self.prepare('10')
            self.assertEqual(row.status,'payment_pending')
            self.assertTrue(activation.opening_ready(row))
            self.assertFalse(activation.visible_accounts(FinancialAccount.objects.all()).exists())
            second,again=self.prepare()
            self.assertEqual(payment['send_id'],again['send_id'])
            self.assertEqual(pay.call_count,1); self.assertEqual(opening.call_count,1)
            row.payment.status='CONFIRMED'; row.payment.save(update_fields=['status'])
            row=activation.reconcile(row.pk)
            self.assertEqual(row.status,'active')
            self.assertEqual(activation.visible_accounts(FinancialAccount.objects.all()).count(),2)
            self.prepare(); pay.assert_called_once()

    def test_insufficient_balance_preserves_opening_records(self):
        with mock.patch('payment_accounts.local_money.activate',side_effect=self.open_accounts), \
             mock.patch.object(activation,'_prepare_send',side_effect=PaymentAccountError('insufficient_balance')):
            with self.assertRaises(PaymentAccountError): self.prepare('10')
        row=AccountActivation.objects.get()
        self.assertEqual(row.status,'awaiting_payment')
        self.assertEqual(FinancialAccount.objects.count(),2)
        self.assertIsNone(row.payment_id)

    def test_timeout_preserves_provider_ids_and_waits(self):
        def timeout(*args):
            ProviderProfile.objects.create(confio_account=self.owner,provider='infinia',owner_type='individual',provider_owner_id='persist-me')
            raise TimeoutError('lost response')
        with mock.patch('payment_accounts.local_money.activate',side_effect=timeout), mock.patch.object(activation,'_prepare_send') as pay:
            with self.assertRaisesMessage(PaymentAccountError, 'Volveremos a intentarlo'):
                self.prepare('10')
        row = AccountActivation.objects.get()
        self.assertEqual(row.status,'provisioning'); pay.assert_not_called()
        self.assertTrue(ProviderProfile.objects.filter(provider_owner_id='persist-me').exists())

    def test_only_one_unfinished_opening_per_customer_across_accounts(self):
        self.row('awaiting_payment')
        other=Account.objects.create(user=self.user,account_type='personal',account_index=1,bsc_address='0x'+'7'*40)
        with self.assertRaisesRegex(PaymentAccountError,'pendiente'):
            activation.prepare(other,None,'co_breb',{'account_type':'personal','account_index':1},accepted_fee='10')
        AccountActivation.objects.update(status='active')
        with mock.patch('payment_accounts.local_money.activate',return_value='provisioning'):
            row,_=activation.prepare(other,None,'co_breb',{'account_type':'personal','account_index':1},accepted_fee='10')
        self.assertEqual(row.confio_account_id,other.pk)

    def test_unpaid_details_hidden_and_operations_blocked(self):
        self.row('awaiting_payment'); self.open_accounts()
        local,crypto=local_money.accounts_for(self.owner,'COL','COP')
        from payment_accounts.schema import FinancialAccountType,FundingInstructionType
        self.assertFalse(FinancialAccountType.resolve_funding_instructions(local,None).exists())
        self.assertEqual(FundingInstructionType.resolve_display_value(local.funding_instructions.first(),None),'')
        view=local_money.receive_account(self.owner,'co_breb_receive')
        self.assertEqual(view['status'],'awaiting_payment'); self.assertIsNone(view['local'])
        self.assertEqual(view['value'],'')
        for account in (local,crypto):
            with self.assertRaises(PaymentAccountError): activation.require_usable(account)
        from payment_accounts.services import create_money_operation,create_funding_instruction
        with self.assertRaises(PaymentAccountError):
            create_money_operation(confio_account=self.owner,provider='infinia',operation_type='payout',
                                   source_asset='USDC_POL',source_amount='10',source_account=crypto)
        with override_settings(INFINIA_PAYMENT_ACCOUNTS_ENABLED=True), self.assertRaises(PaymentAccountError):
            create_funding_instruction(financial_account=local,kind='breb_key')
        from payment_accounts.infinia_journeys import validate_accounts
        with self.assertRaises(PaymentAccountError): validate_accounts(self.owner,local,crypto,'COL')
        from payment_accounts.bridge import verified_destination
        with self.assertRaises(PaymentAccountError): verified_destination(crypto.funding_instructions.first(),self.owner)

    def test_paid_account_graphql_values_match_mobile_account_contract(self):
        import graphene
        from payment_accounts.schema import FinancialAccountType
        from payment_accounts.models import AccountCapability
        self.row('active')
        self.open_accounts()
        local, crypto = local_money.accounts_for(self.owner, 'COL', 'COP')
        AccountCapability.objects.create(financial_account=crypto,
                                         capability='send_third_party', status='enabled')
        owner = self.owner

        class Query(graphene.ObjectType):
            my_payment_accounts = graphene.List(FinancialAccountType)

            def resolve_my_payment_accounts(root, info):
                return activation.visible_accounts(FinancialAccount.objects.filter(
                    provider_profile__confio_account=owner)).order_by('asset')

        schema = graphene.Schema(query=Query)
        result = schema.execute('''{ myPaymentAccounts {
            provider asset status ownershipStructure
            fundingInstructions { kind status }
            capabilities { capability status }
        } }''')
        self.assertIsNone(result.errors)
        rows = result.data['myPaymentAccounts']
        self.assertEqual([row['status'] for row in rows], ['active', 'active'])
        self.assertEqual([row['ownershipStructure'] for row in rows], ['provider_named'] * 2)
        self.assertEqual(rows[1]['fundingInstructions'], [{'kind': 'crypto_address', 'status': 'active'}])
        self.assertEqual(rows[1]['capabilities'], [{'capability': 'send_third_party', 'status': 'enabled'}])
        # Serialization must not loosen payment gating.
        AccountActivation.objects.filter(confio_account=owner).update(status='awaiting_payment')
        result = schema.execute('{ myPaymentAccounts { status } }')
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['myPaymentAccounts'], [])

    def test_provisioning_requires_consent_but_internal_account_has_no_separate_fee(self):
        with self.assertRaises(PaymentAccountError): activation.require_opening_intent(self.owner,'XXX','USDC_POL')
        self.row()
        activation.require_opening_intent(self.owner,'XXX','USDC_POL')
        activation.require_opening_intent(self.owner,'COL','COP')
        with self.assertRaises(PaymentAccountError): activation.require_opening_intent(self.owner,'MEX','MXN')
        self.assertEqual(AccountActivation.objects.count(),1)

    def test_definitive_payment_failure_can_retry_without_reopening(self):
        self.open_accounts(); row=self.row('payment_pending'); row.payment=self.fake_payment(self.owner,self.ctx,row)
        row.payment.status='FAILED';row.payment.save(update_fields=['status']);row.save(update_fields=['payment'])
        with mock.patch.object(activation,'_prepare_send',side_effect=self.fake_payment) as pay, mock.patch('payment_accounts.local_money.activate') as opening:
            updated,_=self.prepare()
        self.assertEqual(updated.attempt,1);self.assertNotEqual(row.payment_id,updated.payment_id)
        pay.assert_called_once();opening.assert_not_called()

    def test_real_signing_batch_delivers_exact_cusd_to_collector(self):
        from send.bsc_flow import _validate_send_batch
        from cusd_plus.sponsor_7702 import PolicyError,SEL_TRANSFER,SEL_UNWRAP_TO_CUSD
        self.open_accounts();row=self.row('awaiting_payment')
        with mock.patch('cusd_plus.vault.p_plus_wad',return_value=WAD), \
             mock.patch('cusd_plus.vault.last_oracle_price_wad',return_value=WAD), \
             mock.patch('cusd_plus.vault.erc20_balance_raw',side_effect=lambda token,holder: 6*WAD), \
             mock.patch('cusd_plus.vault.usdt_balance_raw',return_value=0):
            row,result=self.prepare()
        self.assertEqual(result['token_type'],'CUSD');self.assertEqual(result['fee_amount'],'0')
        calls=result['calls']
        self.assertEqual(calls[-1]['to'],TOKEN)
        self.assertEqual(calls[-1]['data'][2:10],SEL_TRANSFER)
        self.assertEqual(int(calls[-1]['data'][74:138],16),10*WAD)
        self.assertEqual(calls[0]['data'][2:10],SEL_UNWRAP_TO_CUSD)
        self.assertEqual(calls[0]['data'][-40:],self.owner.bsc_address[2:])
        meta=json.loads(row.payment.bsc_calls_json)
        _validate_send_batch(calls,row.payment,meta)
        with self.assertRaises(PolicyError): _validate_send_batch(calls,row.payment,{**meta,'units':str(11*WAD)})

    def test_split_balance_below_conversion_minimum_explains_recovery(self):
        self.open_accounts()
        row = self.row('awaiting_payment')
        with mock.patch('cusd_plus.vault.p_plus_wad', return_value=WAD), \
             mock.patch('cusd_plus.vault.last_oracle_price_wad', return_value=WAD), \
             mock.patch('cusd_plus.vault.erc20_balance_raw', side_effect=lambda token, holder: 95 * WAD // 10 if token == TOKEN else WAD // 2), \
             mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=0):
            with self.assertRaisesMessage(PaymentAccountError, 'mínimo de conversión'):
                self.prepare()
        row.refresh_from_db()
        self.assertEqual(row.status, 'awaiting_payment')
        self.assertIsNone(row.payment_id)

    def test_existing_account_migration_is_idempotent(self):
        self.open_accounts()
        migration=importlib.import_module('payment_accounts.migrations.0015_accountactivation')
        for _ in range(2): migration.preserve_existing_accounts(apps,SimpleNamespace(connection=connection))
        self.assertEqual(AccountActivation.objects.count(),1)
        self.assertEqual(AccountActivation.objects.get().status,'legacy')
        self.assertEqual(activation.visible_accounts(FinancialAccount.objects.all()).count(),2)


@override_settings(CUSD_PLUS_7702_ENABLED=True,CUSD_VAULT_ADDRESS=TOKEN)
class ConcurrentActivationTests(TransactionTestCase):
    def test_simultaneous_app_and_worker_attempt_only_one_failed_request(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections
        from payment_accounts.clients import ProviderAPIError
        user = User.objects.create_user(username='parallel-retry', firebase_uid='parallel-retry')
        owner = Account.objects.create(user=user, account_type='personal')
        row = AccountActivation.objects.create(confio_account=owner, country='ARG', asset='ARS',
                                               method_id='ar_cvu_receive')
        barrier = Barrier(2)
        def worker(_):
            try:
                barrier.wait(timeout=5)
                return activation.reconcile(row.pk).opening_failures
            finally:
                connections.close_all()
        with mock.patch('payment_accounts.local_money.activate', side_effect=ProviderAPIError(
                'unavailable', status_code=500, retryable=True)) as opening, \
                ThreadPoolExecutor(max_workers=2) as pool:
            counts = list(pool.map(worker, range(2)))
        self.assertEqual(counts, [1, 1])
        self.assertEqual(opening.call_count, 1)

    def test_simultaneous_countries_cannot_open_two_unpaid_accounts(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections
        user=User.objects.create_user(username='parallel-open',firebase_uid='parallel-open')
        owner=Account.objects.create(user=user,account_type='personal',bsc_address='0x'+'1'*40)
        barrier=Barrier(2)
        def preflight(owner,identity,method):
            barrier.wait(timeout=5)
            return local_money.METHODS[method],None
        def worker(method):
            try:
                account=Account.objects.select_related('user').get(pk=owner.pk)
                return activation.prepare(account,None,method,{},accepted_fee='10')[0].status
            except PaymentAccountError: return 'blocked'
            finally: connections.close_all()
        with mock.patch('payment_accounts.local_money.activation_preflight',side_effect=preflight), \
             mock.patch.object(activation,'collector',return_value=COLLECTOR), \
             mock.patch('payment_accounts.local_money.activate',return_value='provisioning'), \
             ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(worker,['co_breb','mx_clabe']))
        self.assertCountEqual(statuses,['provisioning','blocked'])
        self.assertEqual(AccountActivation.objects.count(),1)
