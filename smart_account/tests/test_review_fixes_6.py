"""Re-open after inheritance (decision 33, spec 3.1, 4.3, invariant 17).

An owner whose account passed to their beneficiary opens a new account from
the same wallet: the factory keeps one current account per owner and deploys
the new one one generation on. The offer shows plans again, the subscribe
batch creates the account at factory.predictAddress(signer), the relay
accepts exactly that address (never the inherited one), reconcile gives the
new account index 0 without an ops alert, the new subscription grants IA+,
and an inherited withdraw can go to the heir's own (new) account."""
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from assistant.billing import has_plus
from cusd_plus import sponsor_7702
from cusd_plus.sponsor_7702 import PolicyError
from smart_account import abi, context, entitlements, offer, reconcile, relay_policy, schema, services
from smart_account.models import SmartAccount, SmartAccountEvent, SmartAccountPreparedAction

from .base import BUILD, CUSD, FACTORY, VAULT, SmartAccountTestCase, WAD


class ReopenAfterInheritanceTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.previous = self.make_user('previous')
        self.heir = self.make_user('heir')
        self.fund(VAULT, self.previous.wallet, 500 * WAD)
        self.offer_patch = mock.patch('smart_account.offer.crypto_investing_enabled', return_value=False)
        self.offer_patch.start()
        self.addCleanup(self.offer_patch.stop)
        self.block, self.index = 1000, 0
        self.now = timezone.now().replace(microsecond=0)
        # The previous owner's first account (generation 0), then the claim
        # executed on chain and mirrored: the heir owns it now.
        self.old = self.make_account(self.previous)
        self.assertEqual(self.chain.account_of(self.previous.wallet), self.old.contract_address)
        self.inherit_on_chain()
        self.emit('ClaimExecuted', {'newOwner': self.heir.wallet}, address=self.old.contract_address)
        self.apply()
        self.old.refresh_from_db()
        self.assertEqual((self.old.status, self.old.owner_user), ('inherited', self.heir))

    # ── helpers ──
    def inherit_on_chain(self):
        self.chain.views[(self.old.contract_address, 'inherited')] = True
        self.chain.views[(self.old.contract_address, 'owner')] = self.heir.wallet

    def emit(self, name, args, *, address, tx=None, block=None):
        self.index += 1
        return SmartAccountEvent.objects.create(
            address=address.lower(), tx_hash=tx or ('0x' + format(self.index, 'x').rjust(64, '0')),
            log_index=self.index, name=name, args=args, block_number=block or (self.block + self.index),
            block_time=self.now)

    def apply(self, failed=0):
        out = reconcile.apply_pending()
        self.assertEqual(out['failed'], failed)
        return out

    def prepare(self):
        return services.prepare_subscribe(self.viewer(self.previous), 'annual',
                                          [{'asset_key': 'cusd_plus', 'units': str(200 * WAD)}], True)

    def mine_subscribe(self, address):
        """The relayed batch: createAccount, then the subscription's events."""
        self.assertEqual(self.chain.create_account(self.previous.wallet), address)
        paid_until = str(int((self.now + timedelta(days=365)).timestamp()))
        self.emit('AccountCreated', {'owner': self.previous.wallet, 'account': address}, address=FACTORY, tx='0xaa')
        self.emit('FeeCollected', {'plan': '2', 'feeUsd': str(14999 * 10 ** 16), 'cusdAmount': '0',
                                   'cusdPlusShares': str(140 * WAD), 'pPlus': str(WAD),
                                   'paidUntil': paid_until}, address=address, tx='0xaa')
        self.emit('Subscribed', {'plan': '2', 'feeUsd': str(14999 * 10 ** 16), 'paidUntil': paid_until},
                  address=address, tx='0xaa')

    def second_own_alerts(self):
        return [c for c in self.ops_alert_mock.call_args_list
                if str(c.kwargs.get('dedupe_key', '')).startswith('smart_second_own_')]

    # ── offer and prepare ──
    def test_offer_shows_plans_again(self):
        self.assertIsNone(context.own_account(self.previous))
        self.assertIsNone(offer.subscribe_block(self.previous, personal_context=True, meta=BUILD))
        result = schema.Query.resolve_smart_account_offer(None, self.info(self.previous))
        self.assertTrue(result.can_subscribe)
        self.assertIsNone(result.blocked_code)

    def test_prepare_creates_a_new_account_one_generation_on(self):
        batch = self.prepare()
        new = self.chain.predict_address_at(self.previous.wallet, 1)
        self.assertNotEqual(new, self.old.contract_address)
        self.assertEqual(self.chain.predict_address(self.previous.wallet), new)
        self.assertEqual(batch.calls[0], abi.call(FACTORY, abi.encode_call('createAccount')))
        self.assertEqual(batch.calls[1], abi.transfer_call(VAULT, new, 200 * WAD))
        self.assertEqual(batch.calls[2]['to'], new)
        self.assertEqual(abi.decode_call(batch.calls[2]['data'])[0], 'subscribe')
        action = SmartAccountPreparedAction.objects.get(request_id=batch.request_id)
        self.assertEqual(action.target_address, new)
        self.assertIsNone(action.smart_account)

    def test_a_factory_that_cannot_reopen_is_refused(self):
        # predictAddress still naming the inherited account (a factory
        # without generations) would give a batch that only reverts.
        with mock.patch('smart_account.chain.predict_address', side_effect=lambda o: self.old.contract_address):
            with self.assertRaises(services.PrepareError) as raised:
                self.prepare()
        self.assertEqual(raised.exception.code, 'chain_unavailable')
        self.assertFalse(SmartAccountPreparedAction.objects.exists())

    def test_unreadable_factory_fails_closed(self):
        self.chain.fail.add('account_of')
        self.assertEqual(offer.subscribe_block(self.previous, personal_context=True, meta=BUILD),
                         'chain_unavailable')
        result = schema.Query.resolve_smart_account_offer(None, self.info(self.previous))
        self.assertFalse(result.can_subscribe)
        self.assertEqual(result.blocked_code, 'chain_unavailable')
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare()
        self.assertEqual(raised.exception.code, 'chain_unavailable')

    def test_unreadable_prediction_fails_closed(self):
        self.chain.fail.add('predict_address')
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare()
        self.assertEqual(raised.exception.code, 'chain_unavailable')
        self.assertFalse(SmartAccountPreparedAction.objects.exists())

    def test_unknown_wallet_heir_also_reopens(self):
        # The unknown-wallet branch of _claim_executed keeps the previous
        # owner on the row, marked inherited, with no users.Account row.
        SmartAccount.objects.filter(pk=self.old.pk).update(owner_user=self.previous, account=None)
        self.assertIsNone(offer.subscribe_block(self.previous, personal_context=True, meta=BUILD))
        batch = self.prepare()
        self.assertEqual(batch.calls[-1]['to'], self.chain.predict_address_at(self.previous.wallet, 1))

    # ── relay policy ──
    def test_policy_accepts_the_predicted_new_address(self):
        batch = self.prepare()
        sponsor_7702.validate_policy(batch.calls, self.previous, self.previous.wallet,
                                     request_id=batch.request_id + '_a0')

    def test_policy_refuses_a_subscribe_on_the_inherited_account(self):
        old = self.old.contract_address
        calls = [abi.call(FACTORY, abi.encode_call('createAccount')),
                 abi.transfer_call(VAULT, old, 200 * WAD),
                 abi.call(old, abi.encode_call('subscribe', abi.PLAN_ANNUAL, self.chain.fees['annual']))]
        request_id = 'sa-' + 'e' * 32
        SmartAccountPreparedAction.objects.create(
            request_id=request_id, user=self.previous, signer_address=self.previous.wallet,
            target_address=old, kind='smart_subscribe', calls=calls, calls_hash=services.calls_hash(calls),
            expires_at=timezone.now() + timedelta(minutes=5))
        with self.assertRaises(PolicyError) as raised:
            relay_policy.validate_batch(calls, self.previous, self.previous.wallet, request_id)
        self.assertEqual(raised.exception.code, 'smart_account_not_registered')

    def test_policy_refuses_the_new_address_for_another_signer(self):
        batch = self.prepare()
        with self.assertRaises(PolicyError):
            relay_policy.validate_batch(batch.calls, self.heir, self.heir.wallet, batch.request_id)

    # ── reconcile, entitlement ──
    def test_second_account_created_takes_index_zero_without_alert(self):
        from users.models import Account
        batch = self.prepare()
        new = batch.calls[-1]['to']
        self.mine_subscribe(new)
        self.apply()
        account = SmartAccount.objects.get(contract_address=new)
        self.assertEqual((account.owner_user, account.status, account.plan), (self.previous, 'active', 'annual'))
        self.assertEqual((account.account.account_index, account.account.bsc_address), (0, new))
        old_row = Account.all_objects.get(user=self.previous, account_type='smart', bsc_address=self.old.contract_address)
        self.assertIsNotNone(old_row.deleted_at)
        self.assertNotEqual(old_row.account_index, 0)
        self.assertEqual(context.own_account(self.previous), account)
        self.assertEqual(context.owned_smart_account(self.previous, 0), account)
        # The heir keeps the inherited account at their own index.
        self.old.refresh_from_db()
        self.assertEqual((self.old.owner_user, self.old.account.account_index), (self.heir, 1))
        self.assertEqual(self.second_own_alerts(), [])
        self.assertEqual(SmartAccountPreparedAction.objects.get(request_id=batch.request_id).smart_account, account)
        # IA+ through the new subscription, never through the inherited one.
        self.assertTrue(entitlements.account_grants_plus(self.previous))
        self.assertTrue(has_plus(self.previous))
        self.assertFalse(entitlements.sync_account(self.old))
        # The offer now sees an active own account.
        self.assertIsNone(offer.subscribe_block(self.previous, personal_context=True, meta=BUILD))
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare()
        self.assertEqual(raised.exception.code, 'already_subscribed')

    def test_account_created_before_the_claim_is_mirrored_waits_without_alert(self):
        # A second owner whose claim executed on chain, ClaimExecuted not stored yet.
        other = self.make_user('other')
        heir2 = self.make_user('heir2')
        first = self.make_account(other, status='expired')
        self.chain.views[(first.contract_address, 'inherited')] = True
        self.chain.views[(first.contract_address, 'owner')] = heir2.wallet
        new = self.chain.create_account(other.wallet)
        self.emit('AccountCreated', {'owner': other.wallet, 'account': new}, address=FACTORY)
        self.apply(failed=1)
        self.assertFalse(SmartAccount.objects.filter(contract_address=new).exists())
        self.assertEqual(self.second_own_alerts(), [])
        # Stored late (a backfill, say) but mined first: createAccount only
        # succeeds once the claim executed.
        created_block = SmartAccountEvent.objects.get(name='AccountCreated', args__account=new).block_number
        self.emit('ClaimExecuted', {'newOwner': heir2.wallet}, address=first.contract_address,
                  block=created_block - 1)
        self.apply()
        account = SmartAccount.objects.get(contract_address=new)
        self.assertEqual((account.owner_user, account.account.account_index), (other, 0))
        first.refresh_from_db()
        self.assertEqual((first.owner_user, first.status), (heir2, 'inherited'))
        self.assertEqual(self.second_own_alerts(), [])

    def test_account_created_while_the_own_account_is_live_still_alerts(self):
        other = self.make_user('other')
        self.make_account(other)            # the chain still names `other` as its owner
        stray = '0x' + 'cd' * 20
        event = self.emit('AccountCreated', {'owner': other.wallet, 'account': stray}, address=FACTORY)
        self.apply(failed=1)
        event.refresh_from_db()
        self.assertIsNone(event.applied_at)
        self.assertEqual(len(self.second_own_alerts()), 1)

    # ── inherited withdraw into the heir's own new account ──
    def test_inherited_withdraw_goes_to_the_heirs_new_account(self):
        # `previous` re-opened, and inherits a third person's account.
        new = self.prepare().calls[-1]['to']
        self.mine_subscribe(new)
        self.apply()
        third = self.make_user('third')
        inherited = self.make_account(third, status='inherited', index=0)
        SmartAccount.objects.filter(pk=inherited.pk).update(owner_user=self.previous,
                                                            owner_account=context.personal_account(self.previous))
        from users.models import Account
        Account.all_objects.filter(pk=inherited.account_id).update(user=self.previous, account_index=5)
        self.chain.views[(inherited.contract_address, 'owner')] = self.previous.wallet
        self.fund(CUSD, inherited.contract_address, 3 * WAD)
        batch = services.prepare_inherited_withdraw(self.viewer(self.previous), inherited.internal_id, [],
                                                    'smart_account')
        name, args = abi.decode_call(batch.calls[0]['data'])
        self.assertEqual((name, args[-1].lower()), ('withdrawAllTo', new))
        relay_policy.validate_batch(batch.calls, self.previous, self.previous.wallet, batch.request_id)
        # Never the inherited previous account, nor a current one the chain
        # shows inherited.
        self.assertNotEqual(args[-1].lower(), self.old.contract_address)
        self.chain.views[(new, 'inherited')] = True
        with self.assertRaises(services.PrepareError) as raised:
            services.prepare_inherited_withdraw(self.viewer(self.previous), inherited.internal_id, [],
                                                'smart_account')
        self.assertEqual(raised.exception.code, 'no_own_account')

    def test_inherited_withdraw_refuses_when_account_of_names_another_account(self):
        own = self.make_account(self.heir)
        inherited = self.old
        self.chain.accounts[self.heir.wallet] = '0x' + 'ab' * 20
        self.fund(CUSD, inherited.contract_address, 3 * WAD)
        with self.assertRaises(services.PrepareError) as raised:
            services.prepare_inherited_withdraw(self.viewer(self.heir), inherited.internal_id, [], 'smart_account')
        self.assertEqual(raised.exception.code, 'no_own_account')
        self.chain.accounts[self.heir.wallet] = own.contract_address
        batch = services.prepare_inherited_withdraw(self.viewer(self.heir), inherited.internal_id, [],
                                                    'smart_account')
        self.assertEqual(abi.decode_call(batch.calls[0]['data'])[1][-1].lower(), own.contract_address)
        self.chain.fail.add('account_of')
        with self.assertRaises(services.PrepareError) as raised:
            services.prepare_inherited_withdraw(self.viewer(self.heir), inherited.internal_id, [], 'smart_account')
        self.assertEqual(raised.exception.code, 'chain_unavailable')

    def test_the_heir_and_a_new_wallet_are_unaffected(self):
        self.assertIsNone(offer.subscribe_block(self.heir, personal_context=True, meta=BUILD))
        self.assertTrue(schema.Query.resolve_smart_account_offer(None, self.info(self.heir)).can_subscribe)
        newcomer = self.make_user('newcomer')
        self.assertTrue(schema.Query.resolve_smart_account_offer(None, self.info(newcomer)).can_subscribe)
        # An owner with their own row is never checked against the factory.
        own = self.make_account(newcomer, status='none')
        self.chain.fail.add('account_of')
        self.assertIsNone(offer.subscribe_block(newcomer, personal_context=True, meta=BUILD))
        self.assertTrue(SmartAccount.objects.filter(pk=own.pk, owner_user=newcomer).exists())
