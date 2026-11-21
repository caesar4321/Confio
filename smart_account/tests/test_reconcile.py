"""Events -> mirrors, entitlement and timestamps (spec 7.6, 10.3)."""
from datetime import timedelta
from unittest import mock

from django.utils import timezone
from eth_abi import encode as abi_encode

from assistant.billing import has_plus
from smart_account import abi, entitlements, reconcile, services
from smart_account.models import (
    SmartAccount, SmartAccountBeneficiary, SmartAccountCharge, SmartAccountClaim, SmartAccountEvent,
    SmartAccountPreparedAction, SmartAccountRule,
)

from .base import FACTORY, VAULT, SmartAccountTestCase, WAD, new_address


class ReconcileTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.heir = self.make_user('heir')
        self.contract = new_address()
        self.block = 1000
        self.index = 0
        self.now = timezone.now().replace(microsecond=0)

    def emit(self, name, args, *, address=None, tx=None, when=None):
        self.index += 1
        return SmartAccountEvent.objects.create(
            address=(address or self.contract).lower(), tx_hash=tx or ('0x' + format(self.index, 'x').rjust(64, '0')),
            log_index=self.index, name=name, args=args, block_number=self.block + self.index,
            block_time=when or self.now)

    def apply(self):
        out = reconcile.apply_pending()
        self.assertEqual(out['failed'], 0)
        return out

    def subscribe(self, plan=2, days=365):
        paid_until = int((self.now + timedelta(days=days)).timestamp())
        self.emit('AccountCreated', {'owner': self.owner.wallet, 'account': self.contract}, address=FACTORY, tx='0xaa')
        self.emit('FeeCollected', {'plan': str(plan), 'feeUsd': str(14999 * 10 ** 16), 'cusdAmount': '0',
                                   'cusdPlusShares': str(140 * WAD), 'pPlus': str(WAD),
                                   'paidUntil': str(paid_until)}, tx='0xaa')
        self.emit('Subscribed', {'plan': str(plan), 'feeUsd': str(14999 * 10 ** 16),
                                 'paidUntil': str(paid_until)}, tx='0xaa')
        self.apply()
        return SmartAccount.objects.get(contract_address=self.contract)

    def test_account_created_and_subscribed_build_the_mirror(self):
        from users.models import Account
        account = self.subscribe()
        self.assertEqual((account.status, account.billing_status, account.plan), ('active', 'current', 'annual'))
        self.assertEqual(account.owner_user, self.owner)
        row = Account.objects.get(user=self.owner, account_type='smart', account_index=0)
        self.assertEqual(row.bsc_address, self.contract)
        charge = SmartAccountCharge.objects.get()
        self.assertEqual((charge.plan, charge.paid_with, str(charge.fee_usd.quantize(charge.fee_usd.__class__('0.01')))),
                         ('annual', 'cusd_plus', '149.99'))
        self.assertEqual(charge.period_end, account.paid_until)
        # Applying again changes nothing (idempotent).
        SmartAccountEvent.objects.update(applied_at=None)
        self.apply()
        self.assertEqual(SmartAccountCharge.objects.count(), 1)
        self.assertEqual(SmartAccount.objects.count(), 1)

    def test_entitlement_on_at_fee_collected_off_after_paid_until_never_inherited(self):
        self.assertFalse(has_plus(self.owner))
        account = self.subscribe(plan=1, days=30)
        self.assertTrue(has_plus(self.owner))
        # Off after paid_until with no further event and no task run.
        from assistant.models import AssistantSubscription
        sub = AssistantSubscription.objects.get(user=self.owner)
        self.assertEqual((sub.platform, sub.expires_at), ('confio', account.paid_until))
        with mock.patch('django.utils.timezone.now', return_value=account.paid_until + timedelta(seconds=1)):
            self.assertFalse(has_plus(self.owner))
        # A renewal extends it.
        later = int((self.now + timedelta(days=60)).timestamp())
        self.emit('FeeCollected', {'plan': '1', 'feeUsd': str(1499 * 10 ** 16), 'cusdAmount': str(1499 * 10 ** 16),
                                   'cusdPlusShares': '0', 'pPlus': '0', 'paidUntil': str(later)})
        self.apply()
        sub.refresh_from_db()
        self.assertEqual(int(sub.expires_at.timestamp()), later)
        self.assertEqual(SmartAccountCharge.objects.order_by('-id').first().paid_with, 'cusd')
        # Inherited: the new owner never gets it, the previous owner loses it.
        self._accept_and_claim(account)
        self.emit('ClaimExecuted', {'previousOwner': self.owner.wallet, 'newOwner': self.heir.wallet})
        self.apply()
        self.assertFalse(has_plus(self.owner))
        self.assertFalse(has_plus(self.heir))
        account.refresh_from_db()
        self.assertFalse(entitlements.sync_account(account))
        self.assertFalse(has_plus(self.heir))

    def _name(self, account, tx='0xb1'):
        batch = services.prepare_designation(self.viewer(self.owner), 'heir', 180, True)
        from blockchain.models import SponsoredBatch
        sponsored = SponsoredBatch.objects.create(
            user=self.owner, user_bsc_address=self.owner.wallet, kind='smart_beneficiary', num_calls=1,
            calls_json='[]', tx_hash=tx, gas_limit=1, max_fee_wei='1', status='confirmed')
        SmartAccountPreparedAction.objects.filter(request_id=batch.request_id).update(
            consumed=True, sponsored_batch=sponsored)
        expires = int((self.now + timedelta(days=30)).timestamp())
        self.emit('BeneficiaryNamed', {'pendingBeneficiary': self.heir.wallet,
                                       'challengeWindow': str(180 * 86400), 'expiresAt': str(expires)},
                  tx=tx, when=self.now + timedelta(minutes=1))

    def _accept_and_claim(self, account):
        self._name(account)
        self.emit('BeneficiaryAccepted', {'beneficiary': self.heir.wallet, 'challengeWindow': str(180 * 86400)},
                  when=self.now + timedelta(hours=2))
        executable = int((self.now + timedelta(days=180)).timestamp())
        self.emit('ClaimInitiated', {'beneficiary': self.heir.wallet, 'executableAt': str(executable)},
                  tx='0xc1')
        self.apply()

    def test_designated_at_and_accepted_at_are_both_stored_from_block_times(self):
        account = self.subscribe()
        self._name(account)
        self.apply()
        row = SmartAccountBeneficiary.objects.get()
        self.assertEqual(row.state, 'pending_acceptance')
        self.assertEqual(row.designated_at, self.now + timedelta(minutes=1))
        self.assertEqual(row.designated_tx, '0xb1')
        self.assertIsNotNone(row.disclosure_accepted_at)
        self.assertIsNone(row.accepted_at)
        self.emit('BeneficiaryAccepted', {'beneficiary': self.heir.wallet, 'challengeWindow': str(180 * 86400)},
                  when=self.now + timedelta(hours=2))
        self.apply()
        row.refresh_from_db()
        self.assertEqual((row.state, row.accepted_at), ('active', self.now + timedelta(hours=2)))
        self.assertIsNotNone(row.designated_at)

    def test_a_designation_the_relay_did_not_prepare_raises_an_alert(self):
        self.subscribe()
        self.emit('BeneficiaryNamed', {'pendingBeneficiary': self.heir.wallet,
                                       'challengeWindow': str(90 * 86400), 'expiresAt': '1900000000'})
        self.apply()
        self.assertTrue(self.ops_alert_mock.called)
        row = SmartAccountBeneficiary.objects.get()
        self.assertEqual((row.residence_check, row.verified_at_designation), ('unchecked', False))

    def test_claim_cancel_and_execute(self):
        account = self.subscribe()
        self._accept_and_claim(account)
        claim = SmartAccountClaim.objects.get()
        self.assertEqual(claim.state, 'pending')
        cooldown = int((self.now + timedelta(days=30)).timestamp())
        self.emit('ClaimCancelled', {'beneficiary': self.heir.wallet, 'cooldownUntil': str(cooldown)})
        self.apply()
        claim.refresh_from_db()
        self.assertEqual(claim.state, 'cancelled')
        row = SmartAccountBeneficiary.objects.get(state='active')
        self.assertEqual(int(row.cooldown_until.timestamp()), cooldown)
        with self.assertRaises(services.PrepareError):
            services.prepare_claim(self.viewer(self.heir), str(row.designation_id))
        # Second claim, then execution: the same row changes owner and becomes inherited.
        self.emit('ClaimInitiated', {'beneficiary': self.heir.wallet, 'executableAt': '1900000000'}, tx='0xc2')
        self.emit('ClaimExecuted', {'previousOwner': self.owner.wallet, 'newOwner': self.heir.wallet})
        self.apply()
        account.refresh_from_db()
        self.assertEqual((account.status, account.owner_user, account.inherited_from_user, account.plan),
                         ('inherited', self.heir, self.owner, ''))
        self.assertEqual(account.account.account_index, 1)
        self.assertEqual(account.account.user, self.heir)
        self.assertEqual(SmartAccountClaim.objects.get(initiated_tx='0xc2').state, 'executed')
        self.assertFalse(SmartAccountBeneficiary.objects.filter(state='active').exists())
        from smart_account import context
        self.assertIsNone(context.own_account(self.owner))
        self.assertIsNone(context.own_account(self.heir))   # an inherited account is not their own
        self.assertEqual(context.owned_smart_account(self.heir, 1), account)
        self.assertIsNone(context.owned_smart_account(self.owner, 0))

    def test_mirror_is_never_written_from_a_mutation(self):
        account = self.subscribe()
        services.prepare_cancel(self.viewer(self.owner))
        services.prepare_plan_change(self.viewer(self.owner), 'monthly')
        account.refresh_from_db()
        self.assertIsNone(account.cancel_requested_at)
        self.assertEqual((account.status, account.next_plan), ('active', ''))
        self.emit('SubscriptionCancelled', {'paidUntil': str(int(account.paid_until.timestamp()))})
        self.apply()
        account.refresh_from_db()
        self.assertEqual(account.status, 'cancel_pending')
        with mock.patch('django.utils.timezone.now', return_value=account.paid_until + timedelta(seconds=5)):
            self.assertEqual(reconcile.derive_status(account), ('expired', 'current'))

    def test_billing_states_follow_time_and_notice(self):
        account = self.subscribe(plan=1, days=30)
        after = account.paid_until + timedelta(hours=1)
        self.assertEqual(reconcile.derive_status(account, after), ('active', 'payment_due'))
        sale_at = int((after + timedelta(days=7)).timestamp())
        self.emit('PaymentNoticeStarted', {'forPeriod': str(int(account.paid_until.timestamp())),
                                           'saleAllowedAt': str(sale_at)}, when=after)
        self.apply()
        account.refresh_from_db()
        self.assertEqual(reconcile.derive_status(account, after + timedelta(days=1)), ('active', 'notice'))
        self.assertEqual(reconcile.derive_status(account, after + timedelta(days=8)), ('active', 'sale_allowed'))

    def test_rule_created_links_the_draft_and_reads_the_chain(self):
        account = self.subscribe()
        payee = self.make_user('payee')
        self.fund(VAULT, account.contract_address, 500 * WAD)
        batch = services.prepare_send_rule(self.viewer(self.owner), None, 'payee', '25.00', 'weekly')
        from blockchain.models import SponsoredBatch
        sponsored = SponsoredBatch.objects.create(
            user=self.owner, user_bsc_address=self.owner.wallet, kind='smart_rule', num_calls=1,
            calls_json='[]', tx_hash='0xd1', gas_limit=1, max_fee_wei='1', status='confirmed')
        SmartAccountPreparedAction.objects.filter(request_id=batch.request_id).update(
            consumed=True, sponsored_batch=sponsored)
        draft = SmartAccountRule.objects.get()
        self.assertEqual((draft.state, draft.active, draft.onchain_id), ('draft', False, None))
        self.chain.rules[(account.contract_address, 0)] = {
            'kind': 'send', 'frequency': 'weekly', 'active': True, 'token_in': VAULT,
            'token_out': abi.ZERO_ADDRESS, 'payee': payee.wallet, 'payout_ref': '0x' + '00' * 32,
            'amount_usd_wei': 25 * WAD, 'next_run_at': int(self.now.timestamp())}
        self.emit('RuleCreated', {'id': '0', 'kind': '0'}, tx='0xd1')
        self.apply()
        draft.refresh_from_db()
        self.assertEqual((draft.state, draft.active, draft.onchain_id, draft.payee_user),
                         ('onchain', True, 0, payee))
        self.emit('RuleCancelled', {'id': '0'})
        self.apply()
        draft.refresh_from_db()
        self.assertEqual((draft.state, draft.active), ('cancelled', False))

    def test_an_event_that_cannot_be_applied_blocks_only_its_own_account(self):
        account = self.subscribe()
        other_owner = self.make_user('other')
        other_contract = new_address()
        # A rule the chain read cannot return (unreadable): cannot be applied.
        bad = self.emit('RuleCreated', {'id': '99', 'kind': '0'})
        later = self.emit('PlanChanged', {'nextPlan': '1'})
        self.emit('AccountCreated', {'owner': other_owner.wallet, 'account': other_contract}, address=FACTORY)
        out = reconcile.apply_pending()
        self.assertEqual(out['failed'], 1)
        bad.refresh_from_db()
        later.refresh_from_db()
        self.assertIsNone(bad.applied_at)
        self.assertIsNone(later.applied_at)        # order is kept for that account
        self.assertTrue(SmartAccount.objects.filter(contract_address=other_contract).exists())
        account.refresh_from_db()
        self.assertEqual(account.next_plan, '')

    def test_scan_stores_logs_and_keeps_the_cursor_on_failure(self):
        topic = abi.event_topic('AccountCreated', abi.FACTORY_EVENTS['AccountCreated'])
        log = {'address': FACTORY, 'topics': [topic, '0x' + self.owner.wallet[2:].rjust(64, '0'),
                                              '0x' + self.contract[2:].rjust(64, '0')],
               'data': '0x', 'blockNumber': hex(120), 'transactionHash': '0x' + 'ee' * 32, 'logIndex': '0x0'}
        sub_fields = abi.ACCOUNT_EVENTS['Subscribed']
        sub = {'address': self.contract, 'topics': [abi.event_topic('Subscribed', sub_fields)],
               'data': '0x' + abi_encode(['uint8', 'uint256', 'uint64'], [2, 5, 1_900_000_000]).hex(),
               'blockNumber': hex(120), 'transactionHash': '0x' + 'ee' * 32, 'logIndex': '0x1'}

        def get_logs(addresses, start, end):
            return [log] if FACTORY in addresses else [sub]
        with mock.patch('smart_account.chain.finalized_block', return_value=200), \
                mock.patch('smart_account.chain.block_time', return_value=(self.now, '0xbb')), \
                mock.patch('smart_account.chain.get_logs', side_effect=get_logs), \
                self.settings(SMART_ACCOUNT_START_BLOCK=100):
            out = reconcile.scan_events()
        self.assertEqual(out['stored'], 2)   # the new account's own events of the same range are read too
        self.assertEqual(reconcile._cursor(), 200)
        with mock.patch('smart_account.chain.finalized_block', return_value=300), \
                mock.patch('smart_account.chain.get_logs', side_effect=RuntimeError('rpc down')):
            with self.assertRaises(RuntimeError):
                reconcile.scan_events()
        self.assertEqual(reconcile._cursor(), 200)
