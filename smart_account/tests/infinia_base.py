"""A verified owner with an active Infinia account pair, and the real steps
of one CLABE / Pix run: prepare, run_rules, executeRule, the event mirror,
the bridge and journey workers, the payout mirror. Only HTTP (infinia_world),
the KMS signer, Confío Face and outgoing pushes/alerts are faked."""
import time
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from payment_accounts import tasks as payment_tasks
from payment_accounts.models import (
    AccountActivation, AccountCapability, EligibilityPolicy, FinancialAccount, FundingInstruction, InfiniaJourney,
    PaymentBridgeTransfer, PayoutDestination, ProviderProfile,
)
from payment_accounts.webhooks import process_webhook_event, store_webhook
from security.models import IdentityVerification
from smart_account import abi, automation, context, relayer, services, tasks
from smart_account.models import (
    SmartAccount, SmartAccountPayout, SmartAccountRelayTx, SmartAccountRule, SmartAccountRuleRun,
)

from . import infinia_world as w
from .base import own_nonce_lock

BUILD = {'HTTP_X_CONFIO_VERSION': '6.0.0'}
CLABE = '002180000000004322'        # fake, valid check digit
PIX = 'recebedor@example.com'
RAILS = {
    'mx_clabe': dict(country='MEX', asset='MXN', label=f'CLABE · {CLABE}',
                     details={'type': 'CLABE', 'clabe': CLABE, 'reference': 'Confio'}),
    'br_pix': dict(country='BRA', asset='BRL', label=f'Pix · {PIX}',
                   details={'type': 'CHAVE PIX', 'chavePix': PIX}),
}

SETTINGS = dict(
    SMART_ACCOUNT_ENABLED=True, SMART_ACCOUNT_FACTORY_ADDRESS=w.FACTORY, SMART_ACCOUNT_ALLOWED_USER_IDS='*',
    SMART_ACCOUNT_MIN_APP_VERSION='6.0.0', SMART_ACCOUNT_BENEFICIARY_ENABLED=False,
    SMART_ACCOUNT_REQUIRE_CANCEL_CLAIM=False, SMART_ACCOUNT_RELAYER_REFERRAL_ENABLED=False,
    SMART_ACCOUNT_START_BLOCK=1000, SMART_ACCOUNT_PAYOUT_RAILS='mx_clabe,br_pix',
    SMART_ACCOUNT_PAYOUT_ADAPTER_VERIFIED=True, SMART_ACCOUNT_PAYOUT_MAX_BRIDGE_COST_BPS=150,
    SMART_ACCOUNT_PAYOUT_FX_TOLERANCE_BPS=300,
    CUSD_PLUS_VAULT_ADDRESS=w.VAULT, CUSD_VAULT_ADDRESS=w.CUSD, CUSD_PLUS_ORACLE_ADDRESS='',
    CUSD_PLUS_RATE_ORACLE_ADDRESS='', BSC_CONFIO_TOKEN_ADDRESS='', BSC_RPC_URL=w.BSC_URL,
    PAYMENT_BRIDGE_POLYGON_RPC_URL=w.POL_URL, RELAY_API_KEY=w.RELAY_KEY,
    CUSD_PLUS_7702_ENABLED=True, PAYMENT_BRIDGE_QUOTES_ENABLED=True, PAYMENT_BRIDGE_BSC_ENABLED=True,
    PAYMENT_BRIDGE_POLYGON_ENABLED=True, PAYMENT_BRIDGE_MAX_USDT='',
    INFINIA_PAYMENT_ACCOUNTS_ENABLED=True, INFINIA_JOURNEYS_ENABLED=True, INFINIA_API_URL=w.INFINIA_URL,
    INFINIA_SECRET_ID='fake-id', INFINIA_SECRET_PASSWORD='fake-password', INFINIA_COMPANY_ID='',
    INFINIA_ACCOUNT_VALIDATION_ENABLED=False, INFINIA_PASS_THROUGH_FEE_COUNTRIES='',
    INFINIA_MAINTENANCE_FEES_ENABLED=False, INFINIA_LEGACY_PAYOUT_FEES_ENABLED=False, INFINIA_FEE_ROLLOUT_AT='',
    INFINIA_UNSUPPORTED_REGIONS='VE', INFINIA_PROCESSING_FEE_TIER=0, PAYMENT_ACCOUNTS_CALLBACK_BASE_URL='',
    LOCAL_MONEY_METHODS=None,
)


class InfiniaPayoutSteps:
    """The steps, for a TestCase or (true interleavings) a TransactionTestCase."""
    rail = 'mx_clabe'
    token = w.CUSD
    amount = '50.00'

    def setUp(self):
        super().setUp()
        cache.clear()
        self.world = world = w.World()
        self.alerts = mock.Mock(return_value=True)
        self.face = mock.Mock(return_value=None)        # Confío Face passed
        self.pushed = mock.Mock(return_value={'success': True, 'sent': 0, 'failed': 0})
        signer = mock.Mock(address=w.SPONSOR)
        signer.sign_typed_transaction.side_effect = world.sign

        def request(session, method, url, **kwargs):
            return world.request(session, method, url, **kwargs)
        for patcher in (
                mock.patch('requests.sessions.Session.request', autospec=True, side_effect=request),
                mock.patch('blockchain.evm_kms_signer.get_bsc_sponsor_signer_from_settings', return_value=signer),
                mock.patch('cusd_plus.sponsor_7702.acquire_sponsor_nonce_lock', side_effect=own_nonce_lock),
                mock.patch('cusd_plus.sponsor_7702.release_sponsor_nonce_lock'),
                mock.patch('smart_account.tasks.check_relay_tx.apply_async'),
                mock.patch('smart_account.tasks.reconcile_events.apply_async'),
                mock.patch('security.face_step_up.require_face_step_up', self.face),
                mock.patch('security.face_step_up.step_up_applies', return_value=True),
                mock.patch('config.ops_alerts.send_ops_alert', self.alerts),
                mock.patch('config.ops_alerts.send_public_notice', return_value=True),
                mock.patch('config.ops_alerts._send', return_value=True),
                mock.patch('notifications.utils.send_push_notification', self.pushed),
                mock.patch('smart_account.assistant_ops._starts_late_in_month', return_value=False, create=True),
                mock.patch('notifications.fcm_service.send_push_notification', self.pushed)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.build_owner()

    def tearDown(self):
        self.assertEqual(self.world.unknown, [], 'a request the fake world does not know')
        super().tearDown()

    # ── fixtures ───────────────────────────────────────────────────────

    def build_owner(self):
        from users.models import Account
        world, spec = self.world, RAILS[self.rail]
        self.user = get_user_model().objects.create_user(
            username='payer', password='x', firebase_uid='uid-payer', first_name='Pagador')
        self.wallet = '0x' + '11' * 20
        self.contract = '0x' + '22' * 20
        self.personal = Account.objects.create(user=self.user, account_type='personal', account_index=0,
                                               bsc_address=self.wallet)
        smart = Account.objects.create(user=self.user, account_type='smart', account_index=0,
                                       bsc_address=self.contract)
        self.account = SmartAccount.objects.create(
            owner_user=self.user, owner_account=self.personal, account=smart, contract_address=self.contract,
            status='active', plan='annual', paid_until=timezone.now() + timedelta(days=30))
        world.accounts[self.contract] = self.wallet
        world.balances[(self.token, self.contract)] = 100_000 * w.WAD

        self.identity = IdentityVerification.objects.create(
            user=self.user, status='verified', verified_first_name='Pagador', verified_last_name='Prueba',
            verified_date_of_birth='1990-01-01', verified_nationality='MEX', verified_country='MEX',
            verified_at=timezone.now(), document_type='passport', document_number='TEST0001',
            document_issuing_country='MEX', risk_factors={'provider': 'didit', 'account_type': 'personal'})
        EligibilityPolicy.objects.filter(provider='infinia').update(is_active=False)
        for scope in ('account_opening', 'conversion', 'payout'):
            EligibilityPolicy.objects.create(provider='infinia', scope=scope, version=9000, is_active=True,
                                             default_decision='allow', default_reason_code='test_allow',
                                             effective_from=timezone.now() - timedelta(days=1))
        self.profile = ProviderProfile.objects.create(
            confio_account=self.personal, provider='infinia', owner_type='individual', status='active',
            provider_owner_id='owner-test', identity_verification=self.identity)
        self.crypto = FinancialAccount.objects.create(
            provider_profile=self.profile, provider_account_id='acct-usdc', country='XXX', asset='USDC_POL',
            ownership_structure='provider_named', status='active')
        self.local = FinancialAccount.objects.create(
            provider_profile=self.profile, provider_account_id=f'acct-{spec["asset"].lower()}',
            country=spec['country'], asset=spec['asset'], ownership_structure='provider_named', status='active')
        world.account_assets = {self.local.provider_account_id: spec['asset']}
        AccountActivation.objects.create(confio_account=self.personal, country=spec['country'],
                                         asset=spec['asset'], status='legacy')
        for account in (self.local, self.crypto):
            for capability in ('convert', 'send_third_party'):
                AccountCapability.objects.create(financial_account=account, capability=capability, status='enabled')
        self.instruction = FundingInstruction.objects.create(
            financial_account=self.crypto, kind='crypto_address', status='active', reusable=True,
            display_value=w.OWNER_INFINIA)
        self.destination = PayoutDestination.objects.create(
            confio_account=self.personal, provider='infinia', kind='bank_account', status='active', holder_name='',
            provider_data={'method_id': self.rail,
                           'validation': {'id': '', 'status': 'DISABLED', 'holder_name': '',
                                          'checked_at': timezone.now().isoformat()}},
            **spec)

    def viewer(self):
        return context.Viewer(user=self.user, personal_account=self.personal, context_type='personal',
                              meta=dict(BUILD))

    def prepare(self, amount=None, **kwargs):
        args = dict(rule_id=None, payout_method_id=str(self.destination.internal_id),
                    amount_usd=amount or self.amount, frequency='monthly')
        args.update(kwargs)
        return services.prepare_payout_rule(self.viewer(), **args)

    def make_rule(self, amount=None):
        """Prepared (with Face), then on chain exactly as the batch says."""
        batch = self.prepare(amount)
        _name, args = abi.decode_call(batch.calls[0]['data'])
        kind, _frequency, token_in, _out, _payee, ref, amount_wei, _first = args[0]
        assert kind == abi.RULE_PAYOUT
        self.slot = timezone.now().replace(microsecond=0) - timedelta(minutes=3)
        rule = SmartAccountRule.objects.get(state='draft')
        SmartAccountRule.objects.filter(pk=rule.pk).update(
            state='onchain', active=True, onchain_id=1, scheduled_for=self.slot, next_run_at=self.slot)
        self.world.rules[(self.contract, 1)] = {
            'active': True, 'frequency': 'monthly', 'token_in': token_in.lower(),
            'payout_ref': '0x' + bytes(ref).hex(), 'amount_usd_wei': int(amount_wei),
            'next_run_at': int(self.slot.timestamp()), 'epoch': int(rule.epoch)}
        self.face_at_prepare = self.face.call_count
        rule.refresh_from_db()
        self.rule = rule
        return rule

    # ── steps ──────────────────────────────────────────────────────────

    def step(self, fn, *args, **kwargs):
        cache.clear()       # finality and fee reads are cached for seconds
        with self.captureOnCommitCallbacks(execute=True):
            return fn(*args, **kwargs)

    def run_rules(self):
        return self.step(automation.run_rules)

    def relay_receipts(self):
        for row in SmartAccountRelayTx.objects.filter(status__in=('signed', 'sent')):
            self.step(relayer.resolve_receipt, row)
            self.step(automation.on_relay_tx_final, row)

    def leave_order_open(self):
        """An order reserved and nothing broadcast, still open: the worker died
        before the relayer answered. (A refused call closes its order.)"""
        with mock.patch('smart_account.relayer.send_relayer_call', side_effect=RuntimeError('the worker died')):
            return self.run_rules()

    def mirror_chain(self):
        self.relay_receipts()
        self.step(tasks.reconcile_events)

    def bridges(self):
        self.step(payment_tasks.reconcile_bridges)

    def journeys(self):
        self.step(payment_tasks.reconcile_infinia_journeys)

    def mirror(self):
        from smart_account import infinia_payouts
        return self.step(infinia_payouts.mirror_payouts)

    def workers(self):
        self.bridges()
        self.journeys()
        self.mirror()

    def webhook(self, payload, event='movement.created'):
        row, _ = store_webhook(provider='infinia', raw_body=__import__('json').dumps(payload).encode(),
                               headers={'event': event, 'X-Idempotency-Key': uuid.uuid4().hex})
        self.step(process_webhook_event, row)

    def credit_usdc(self, tx_hash, units):
        self.webhook({'id': uuid.uuid4().hex, 'account_id': self.crypto.provider_account_id,
                      'amount': str(Decimal(units) / 10 ** 6), 'created_at': timezone.now().isoformat(),
                      'operation': {'type': 'PAYIN'},
                      'third_party': {'type': 'CRYPTO', 'crypto_network': 'POLYGON', 'transaction_hash': tx_hash}})

    def credit_conversion(self):
        transfer = self.world.transfers[-1]
        self.webhook({'id': uuid.uuid4().hex, 'account_id': self.local.provider_account_id,
                      'amount': str(transfer['destination_amount']), 'created_at': timezone.now().isoformat(),
                      'operation': {'type': 'INTERNAL_TRANSFER', 'operation_id': transfer['id']}})

    def send_run(self):
        """Slot due -> broadcast -> mined -> PayoutSent mirrored."""
        out = self.run_rules()
        self.assertEqual(out.get('sent'), 1, (out, list(SmartAccountRuleRun.objects.values('error', 'message'))))
        self.mirror_chain()
        return self.payout()

    def deliver(self):
        self.bridges()
        deposit = self.payout().journey.bridge.deposit_address      # the slot's current order
        tx_hash, units = self.world.relay_fills(next(o for o in self.world.orders if o['deposit'] == deposit))
        self.bridges()
        self.credit_usdc(tx_hash, units)
        self.bridges()
        return tx_hash, units

    def to_paid(self):
        self.deliver()
        self.journeys()             # conversion
        self.credit_conversion()
        self.journeys()             # payout
        self.workers()
        return self.payout()

    # ── reads ──────────────────────────────────────────────────────────

    def payout(self):
        return SmartAccountPayout.objects.select_related(
            'journey__bridge__quote__money_flow', 'journey__money_flow').get()

    def last_run(self):
        return SmartAccountRuleRun.objects.order_by('-pk').first()

    def journey(self):
        return InfiniaJourney.objects.select_related('bridge__quote__money_flow', 'money_flow').get(
            confio_account=self.personal, bridge__funding_mode='contract')

    def bridge(self):
        return PaymentBridgeTransfer.objects.select_related('quote__money_flow').get(funding_mode='contract')

    def age(self, seconds):
        """The bridge as if `seconds` had passed since it was quoted."""
        bridge = self.bridge()
        PaymentBridgeTransfer.objects.filter(pk=bridge.pk).update(deadline=bridge.deadline - seconds)

    def advance(self, seconds):
        """Time passes: for Confío, Relay's deadlines and the chain."""
        if not hasattr(self, '_clock'):
            self._clock = 0
            now, clock = timezone.now, time.time
            for patcher in (
                    mock.patch('django.utils.timezone.now',
                               side_effect=lambda: now() + timedelta(seconds=self._clock)),
                    mock.patch('time.time', side_effect=lambda: clock() + self._clock)):
                patcher.start()
                self.addCleanup(patcher.stop)
        self._clock += seconds

    def update_on_chain(self, *, amount_usd=None, payout_ref=None):
        """The owner's updateRule, mined now (RuleUpdated)."""
        rule = self.world.rules[(self.contract, 1)]
        if amount_usd is not None:
            rule['amount_usd_wei'] = int(Decimal(amount_usd) * w.WAD)
        if payout_ref is not None:
            rule['payout_ref'] = payout_ref
        rule['next_run_at'] = int(timezone.now().timestamp())
        topics = [abi.event_topic('RuleUpdated', abi.ACCOUNT_EVENTS['RuleUpdated']), f'0x{1:064x}']
        tx_hash = self.world.new_hash()
        self.world.mine('BSC', tx_hash, [{'address': self.contract, 'topics': topics, 'data': '0x',
                                          'removed': False}])
        return tx_hash

    def alert_text(self):
        return '\n'.join(str(call.args[0]) for call in self.alerts.call_args_list)

    def info(self, meta=None):
        from graphql_jwt.utils import jwt_encode
        now = int(timezone.now().timestamp())
        payload = {'user_id': self.user.pk, 'username': self.user.username,
                   'auth_token_version': getattr(self.user, 'auth_token_version', 1),
                   'account_type': 'personal', 'account_index': 0, 'business_id': None,
                   'exp': now + 3600, 'origIat': now}
        headers = {'HTTP_AUTHORIZATION': 'JWT ' + jwt_encode(payload), **BUILD, **(meta or {})}
        return SimpleNamespace(context=SimpleNamespace(user=self.user, META=headers))


@override_settings(**SETTINGS)
class InfiniaPayoutCase(InfiniaPayoutSteps, TestCase):
    pass
