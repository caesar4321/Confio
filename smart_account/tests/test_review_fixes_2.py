"""Review fixes, round 2 (2026-11-20): logs of a not-yet-applied account,
an own account re-created after one was inherited away, protective tasks
with the flag off, forced-sale sizing against the contract's cap, the claim
note in the assistant thread, the personal rail's gates on account trades,
sends to an account contract, and ClaimExecuted to an unknown wallet."""
import time
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.core import checks
from django.test import override_settings
from django.utils import timezone

from cusd_plus.sponsor_7702 import PolicyError
from smart_account import abi, automation, entitlements, quotes, reconcile, relay_policy, services, tasks
from smart_account.assets import Asset
from smart_account.models import (
    SmartAccount, SmartAccountBeneficiary, SmartAccountClaim, SmartAccountEvent, SmartAccountPreparedAction,
    SmartAccountRule, SmartAccountScanCursor,
)

from .base import CUSD, FACTORY, STOCK_ROUTER, SWAP_ROUTER, VAULT, SmartAccountTestCase, WAD, new_address
from .test_tasks import RelayHarness


class LogNode:
    """A node answering eth_getLogs from a list, by address and block range."""

    def __init__(self):
        self.logs, self.calls = [], []
        self.index = 0

    def add(self, address, name, args, block):
        self.index += 1
        self.logs.append({'address': address.lower(), 'blockNumber': hex(block), 'logIndex': hex(self.index),
                          'transactionHash': '0x' + format(self.index, 'x').rjust(64, '0'),
                          '_decoded': (name, args)})

    def get_logs(self, addresses, from_block, to_block):
        self.calls.append((sorted(a.lower() for a in addresses), from_block, to_block))
        wanted = {a.lower() for a in addresses}
        return [log for log in self.logs
                if log['address'] in wanted and from_block <= int(log['blockNumber'], 16) <= to_block]

    def run(self, finalized, *, scan_only=False):
        with mock.patch('smart_account.chain.finalized_block', return_value=finalized), \
                mock.patch('smart_account.chain.get_logs', side_effect=self.get_logs), \
                mock.patch('smart_account.chain.block_time', return_value=(timezone.now(), '0x' + '0b' * 32)), \
                mock.patch('smart_account.abi.decode_log', side_effect=lambda log, factory: log['_decoded']):
            return reconcile.scan_events() if scan_only else reconcile.reconcile()


def _paid_until(days=365):
    return str(int((timezone.now() + timedelta(days=days)).timestamp()))


# ── 1. logs of an account whose AccountCreated is stored but unapplied ──

@override_settings(SMART_ACCOUNT_START_BLOCK=1000)
class UnappliedAccountLogsTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.heir = self.make_user('heir')
        self.contract = new_address()
        self.node = LogNode()

    def test_account_created_failing_twice_then_applying_keeps_its_earlier_events(self):
        node, contract = self.node, self.contract
        node.add(FACTORY, 'AccountCreated', {'owner': self.owner.wallet, 'account': contract}, 1010)
        node.add(contract, 'Subscribed', {'plan': '2', 'feeUsd': str(14999 * 10 ** 16),
                                          'paidUntil': _paid_until()}, 1010)
        node.add(contract, 'BeneficiaryNamed', {'pendingBeneficiary': self.heir.wallet,
                                                'challengeWindow': str(90 * 86400),
                                                'expiresAt': _paid_until(30)}, 1150)
        node.add(contract, 'BeneficiaryAccepted', {'beneficiary': self.heir.wallet,
                                                   'challengeWindow': str(90 * 86400)}, 1160)
        node.add(contract, 'ClaimInitiated', {'beneficiary': self.heir.wallet,
                                              'executableAt': _paid_until(90)}, 1250)
        real = reconcile._own_account_row
        attempts = []

        def flaky(user, address):
            attempts.append(address)
            if len(attempts) <= 2:
                raise RuntimeError('row not writable yet')
            return real(user, address)

        with mock.patch('smart_account.reconcile._own_account_row', side_effect=flaky):
            node.run(1100)
            self.assertFalse(SmartAccount.all_objects.filter(contract_address=contract).exists())
            node.run(1200)
            # The rowless account's new range WAS read (with the factory's).
            self.assertIn(contract, node.calls[-1][0])
            self.assertFalse(SmartAccount.all_objects.filter(contract_address=contract).exists())
            node.run(1300)
        self.assertEqual(len(attempts), 3)
        account = SmartAccount.objects.get(contract_address=contract)
        self.assertEqual((account.status, account.plan, account.owner_user), ('active', 'annual', self.owner))
        self.assertTrue(SmartAccountBeneficiary.objects.filter(smart_account=account, state='active').exists())
        self.assertTrue(SmartAccountClaim.objects.filter(beneficiary_row__smart_account=account,
                                                         state='pending').exists())
        self.assertFalse(SmartAccountEvent.objects.filter(applied_at__isnull=True).exists())

    def test_row_created_without_coverage_is_backfilled_from_its_creation_block(self):
        node, contract = self.node, self.contract
        node.add(FACTORY, 'AccountCreated', {'owner': self.owner.wallet, 'account': contract}, 1010)
        node.add(contract, 'Subscribed', {'plan': '1', 'feeUsd': str(1499 * 10 ** 16),
                                          'paidUntil': _paid_until(30)}, 1010)
        # At scan time the owner was not (yet) a Confío wallet: the account's
        # own logs were not read in its creation range.
        with mock.patch('smart_account.reconcile._confio_owner', return_value=False):
            node.run(1100, scan_only=True)
        self.assertFalse(SmartAccountEvent.objects.filter(address=contract).exists())
        self.assertEqual(reconcile.apply_pending()['failed'], 0)
        account = SmartAccount.objects.get(contract_address=contract)
        self.assertEqual(account.status, 'none')
        self.assertEqual(reconcile.backfill_pending(), {contract})
        node.run(1200)
        self.assertIn(([contract], 1010, 1100), node.calls)          # re-read from its creation block
        account.refresh_from_db()
        self.assertEqual((account.status, account.plan), ('active', 'monthly'))
        self.assertEqual(reconcile.backfill_pending(), set())
        self.assertFalse(SmartAccountScanCursor.objects.filter(key__startswith='a:').exists())

    def test_new_own_account_after_the_previous_one_was_inherited_away(self):
        from users.models import Account
        old = self.make_account(self.owner)
        old_row = old.account
        old_row.soft_delete()
        heir_row = Account.objects.create(user=self.heir, account_type='smart', account_index=1,
                                          bsc_address=old.contract_address)
        SmartAccount.objects.filter(pk=old.pk).update(
            owner_user=self.heir, owner_account=Account.objects.get(user=self.heir, account_type='personal'),
            account=heir_row, status='inherited', inherited_at=timezone.now(), inherited_from_user=self.owner,
            plan='', paid_until=None)
        SmartAccountEvent.objects.create(
            address=FACTORY, tx_hash='0x' + 'c3' * 32, log_index=1, name='AccountCreated',
            args={'owner': self.owner.wallet, 'account': self.contract}, block_number=1500,
            block_time=timezone.now())
        out = reconcile.apply_pending()
        self.assertEqual(out['failed'], 0)
        new = SmartAccount.objects.get(contract_address=self.contract)
        self.assertEqual((new.owner_user, new.account.account_index, new.account.bsc_address),
                         (self.owner, 0, self.contract))
        old_row.refresh_from_db()
        self.assertIsNotNone(old_row.deleted_at)
        self.assertEqual(old_row.bsc_address, old.contract_address)     # history keeps its address
        self.assertNotEqual(old_row.account_index, 0)
        from smart_account.context import owned_smart_account
        self.assertEqual(owned_smart_account(self.owner, 0), new)

    def test_a_live_second_own_row_is_still_refused(self):
        self.make_account(self.owner)
        event = SmartAccountEvent.objects.create(
            address=FACTORY, tx_hash='0x' + 'c4' * 32, log_index=1, name='AccountCreated',
            args={'owner': self.owner.wallet, 'account': self.contract}, block_number=1500,
            block_time=timezone.now())
        self.assertEqual(reconcile.apply_pending()['failed'], 1)
        event.refresh_from_db()
        self.assertIsNone(event.applied_at)


# ── 2 + 4. protective tasks with the flag off; the assistant-thread note ──

@override_settings(SMART_ACCOUNT_START_BLOCK=1000, SMART_ACCOUNT_ENABLED=False)
class FlagOffProtectiveTests(RelayHarness):
    def setUp(self):
        super().setUp()
        self.node = LogNode()
        self.heir = self.make_user('heir')

    def _reconcile(self, finalized):
        with mock.patch('smart_account.chain.finalized_block', return_value=finalized), \
                mock.patch('smart_account.chain.get_logs', side_effect=self.node.get_logs), \
                mock.patch('smart_account.chain.block_time', return_value=(timezone.now(), '0x' + '0b' * 32)), \
                mock.patch('smart_account.abi.decode_log', side_effect=lambda log, factory: log['_decoded']):
            return tasks.reconcile_events()

    def test_a_cancellation_is_mirrored_and_the_return_runs(self):
        self.node.add(self.address, 'SubscriptionCancelled', {}, 1010)
        out = self._reconcile(1100)
        self.assertEqual(out['apply']['applied'], 1)
        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.cancel_requested_at)
        self.assertEqual(self.account.status, 'expired')          # period already over
        self.chain.views[(self.address, 'status')] = 3
        self.fund(CUSD, self.address, 2 * WAD)
        self.assertEqual(tasks.return_expired()['sent'], 1)
        self.assertEqual(self.signed[0]['data'], abi.encode_call('returnAsset', CUSD))
        # New activity stays behind the flag.
        self.assertEqual(tasks.collect_due_fees(), {'skipped': 'disabled'})

    def test_a_claim_is_mirrored_and_the_owner_is_told_in_every_channel(self):
        from inbox.models import SupportMessage
        from notifications.models import Notification
        SmartAccountBeneficiary.objects.create(
            smart_account=self.account, beneficiary_user=self.heir, beneficiary_address=self.heir.wallet,
            challenge_window_seconds=90 * 86400, state='active', designated_at=timezone.now(),
            accepted_at=timezone.now())
        self.node.add(self.address, 'ClaimInitiated', {'beneficiary': self.heir.wallet,
                                                       'executableAt': _paid_until(90)}, 1010)
        self._reconcile(1100)
        claim = SmartAccountClaim.objects.get(beneficiary_row__smart_account=self.account)
        self.assertEqual(claim.state, 'pending')
        self.assertTrue(Notification.objects.filter(user=self.owner,
                                                    data__smart_account_event='claim_initiated').exists())
        note = SupportMessage.objects.get(conversation__user=self.owner, metadata__notice__startswith='smart_claim:')
        self.assertEqual((note.sender_type, note.conversation.account.account_type), ('SYSTEM', 'personal'))
        self.assertIn('reclamo', note.body)
        # The reminder task runs with the flag off too.
        SmartAccountClaim.objects.filter(pk=claim.pk).update(last_owner_notice_at=timezone.now() - timedelta(days=8))
        out = tasks.claim_notices()
        self.assertEqual((out['owner_notices'], out['price']), (1, 0))


class AssistantNoteTests(SmartAccountTestCase):
    def test_system_note_is_posted_once_per_tag_in_the_personal_thread(self):
        from assistant.service import post_system_note
        from inbox.models import SupportMessage
        user = self.make_user('owner')
        message, created = post_system_note(user, 'Hay un reclamo en curso.', 'smart_claim:1:20261120')
        self.assertTrue(created)
        again, created = post_system_note(user, 'Hay un reclamo en curso.', 'smart_claim:1:20261120')
        self.assertEqual((again.pk, created), (message.pk, False))
        self.assertEqual(SupportMessage.objects.filter(metadata__notice='smart_claim:1:20261120').count(), 1)
        self.assertEqual(message.sender_type, 'SYSTEM')
        self.assertIsNone(message.conversation.business_id)

    def test_claim_notice_reaches_the_assistant_thread(self):
        from inbox.models import SupportMessage
        owner, heir = self.make_user('owner'), self.make_user('heir')
        account = self.make_account(owner)
        row = SmartAccountBeneficiary.objects.create(
            smart_account=account, beneficiary_user=heir, beneficiary_address=heir.wallet,
            challenge_window_seconds=90 * 86400, state='active')
        claim = SmartAccountClaim.objects.create(beneficiary_row=row, initiated_at=timezone.now(),
                                                 initiated_tx='0x' + '02' * 32,
                                                 executable_at=timezone.now() + timedelta(days=90))
        from smart_account import notifications
        notifications.claim_initiated_owner(claim)
        self.assertTrue(SupportMessage.objects.filter(conversation__user=owner,
                                                      metadata__notice__startswith=f'smart_claim:{claim.pk}:').exists())


# ── 3. forced sale sized against the contract's cap ─────────────────────

class ForcedSaleSizingTests(SmartAccountTestCase):
    FEE_BPS = 90
    MONTHLY = 1499 * 10 ** 16

    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner, plan='monthly')
        self.quotes = []
        for p in (mock.patch('smart_account.quotes.stock_sell_call', side_effect=self._stock_quote),
                  mock.patch('smart_account.quotes.crypto_sell_call', side_effect=self._crypto_quote),
                  mock.patch('cusd_plus.crypto_catalog.by_address', side_effect=self._token),
                  mock.patch('cusd_plus.crypto_policy.live_fee_bps', return_value=self.FEE_BPS)):
            p.start()
            self.addCleanup(p.stop)
        self.assets = {}
        self.rich = Decimal('1')

    # Realistic estimates, mirroring quotes.py: a stock order is at least
    # US$1, quoted to the cent, floored at 99.5% and net of the 0.9% fee; a
    # crypto sale is floored between the quote and its slippage floor.
    def _stock_quote(self, symbol, notional):
        self.quotes.append(('stock', symbol, notional))
        notional = max(notional, quotes.MIN_STOCK_ORDER_USD).quantize(Decimal('0.01'))
        min_usdt = notional * Decimal('0.995')
        net = min_usdt - min_usdt * self.FEE_BPS / 10_000
        asset = self.assets[f'stock:{symbol}']
        return {'call': {'data': '0x' + 'ab' * 8}, 'token': asset.address, 'max_in': int(notional * WAD),
                'expected_dollars_wei': int(net * self.rich * WAD), 'quote_ref': '7'}

    def _crypto_quote(self, token, dollar, amount_in):
        asset = self.assets[token]
        value = Decimal(amount_in) / Decimal(asset.units) * asset.value_usd
        min_usdt = value * Decimal('0.9975')
        net = min_usdt - min_usdt * self.FEE_BPS / 10_000
        return {'call': {'data': '0x' + 'cd' * 8}, 'token': asset.address, 'max_in': amount_in,
                'expected_dollars_wei': int(net * self.rich * WAD)}

    def _token(self, address, include_unlisted=False):
        return address   # the crypto quote looks the asset up by it

    def stock(self, symbol, value):
        value = Decimal(value)
        asset = Asset(f'stock:{symbol}', 'stock', symbol, symbol, new_address(), int(value * WAD), 18,
                      value, True)
        self.assets[asset.key] = asset
        return asset

    def crypto(self, symbol, value):
        asset = Asset(f'crypto:{symbol}', 'crypto', symbol, symbol, new_address(), 10 ** 8, 8,
                      Decimal(value), True)
        self.assets[asset.address] = asset
        return asset

    def plan(self, candidates, shortfall=MONTHLY):
        with mock.patch('smart_account.automation.sale_candidates', return_value=candidates):
            return automation.plan_forced_sale(self.account, shortfall, abi.DOLLAR_PLUS)

    def assertInsideCap(self, legs, shortfall=MONTHLY):
        _target, cap = automation.forced_sale_target_wei(shortfall)
        raised = sum(leg['expected_dollars_wei'] for leg in legs)
        self.assertGreaterEqual(raised, shortfall)
        self.assertLessEqual(raised, cap)
        return raised

    def test_monthly_fee_two_stocks_never_overshoots_the_cap(self):
        # One position covers the fee alone: one leg, no top-up order of
        # US$1 (that top-up used to push the plan over the cap: 16.76 > 16.74).
        legs = self.plan([self.stock('SPYon', '16.40'), self.stock('QQQon', '5.00')])
        self.assertEqual([leg['asset_key'] for leg in legs], ['stock:SPYon'])
        self.assertInsideCap(legs)
        for first in range(2, 40):
            for second in ('1.50', '6.00', '30.00'):
                self.quotes.clear()
                candidates = [self.stock('AAAon', Decimal(first) / 2 + Decimal('0.37')), self.stock('BBBon', second)]
                try:
                    legs = self.plan(candidates)
                except automation.NothingSellable:
                    total = sum(a.value_usd for a in candidates) * Decimal('0.98')
                    self.assertLess(total, Decimal('15.30'), (first, second))   # truly not enough
                    continue
                self.assertInsideCap(legs)

    def test_monthly_fee_crypto_and_stock(self):
        legs = self.plan([self.crypto('BTCB', '9.00'), self.stock('SPYon', '20.00')])
        self.assertEqual([leg['kind'] for leg in legs], ['crypto', 'stock'])
        self.assertInsideCap(legs)
        for crypto_value in range(1, 40):
            legs = self.plan([self.crypto('BTCB', Decimal(crypto_value) / 2 + Decimal('0.11')),
                              self.stock('SPYon', '20.00')])
            self.assertInsideCap(legs)

    def test_a_quote_richer_than_its_estimate_is_resized_into_the_cap(self):
        self.rich = Decimal('1.08')
        legs = self.plan([self.stock('SPYon', '30.00')])
        self.assertInsideCap(legs)
        self.assertEqual(len([q for q in self.quotes if q[1] == 'SPYon']), 2)    # requoted once, smaller


# ── 5. the personal rail's gates on an account trade ────────────────────

class _GateHarness(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)
        self.stock_params = {
            'kind': 'stock_buy', 'venue': STOCK_ROUTER, 'token_in': VAULT, 'token_out': '0x' + '91' * 20,
            'max_in': 10 * WAD, 'min_out': 9, 'call': {'to': STOCK_ROUTER, 'value': '0', 'data': '0x12'},
            'action': {'kind': 'stock_buy', 'asset': '0x' + '91' * 20, 'history_amount_wei': 10 * WAD}}
        self.crypto_params = {
            'kind': 'crypto_buy', 'venue': SWAP_ROUTER, 'token_in': VAULT, 'token_out': '0x' + '71' * 20,
            'max_in': 10 * WAD, 'min_out': 9, 'call': {'to': SWAP_ROUTER, 'value': '0', 'data': '0x34'},
            'action': {'kind': 'crypto_buy', 'dollar': abi.DOLLAR_PLUS, 'amount_in': 10 * WAD}}
        self.complex, self.acked, self.over_cap, self.crypto_refusal = False, True, False, None
        for p in (
                mock.patch('cusd_plus.eligibility.ONDO_POLICY',
                           mock.Mock(evaluate=mock.Mock(return_value=mock.Mock(allowed=True)))),
                mock.patch('cusd_plus.eligibility.check_stock_buy_eligibility', return_value=True),
                mock.patch('cusd_plus.complex_products.buys_complex_product', side_effect=lambda c: self.complex),
                mock.patch('cusd_plus.complex_products.acknowledged', side_effect=lambda u: self.acked),
                mock.patch('security.geo.review_cap_exceeded_wei', side_effect=lambda u, a: self.over_cap),
                mock.patch('security.geo.store_review_exempt', return_value=True),
                mock.patch('cusd_plus.crypto_policy.expected_exit_usdt', return_value=(10 * WAD, 10 * WAD)),
                mock.patch('cusd_plus.crypto_risk.sponsor_gate', side_effect=lambda *a, **k: self.crypto_refusal)):
            p.start()
            self.addCleanup(p.stop)


class TradeGateTests(_GateHarness):
    def test_gate_codes_match_the_personal_rail(self):
        gate = services.trade_gate
        self.assertIsNone(gate(self.owner, {}, self.stock_params))
        self.complex, self.acked = True, False
        self.assertEqual(gate(self.owner, {}, self.stock_params), 'complex_product_ack_required')
        self.acked = True
        self.assertIsNone(gate(self.owner, {}, self.stock_params))
        self.over_cap = True
        self.assertEqual(gate(self.owner, {}, self.stock_params), 'review_amount_cap')
        self.assertEqual(gate(self.owner, {}, self.crypto_params), 'review_amount_cap')
        self.over_cap = False
        self.assertIsNone(gate(self.owner, {}, self.crypto_params))
        self.crypto_refusal = 'crypto_ack_required'
        self.assertEqual(gate(self.owner, {}, self.crypto_params), 'crypto_ack_required')

    def test_prepare_refuses_with_the_specific_code(self):
        self.complex, self.acked = True, False
        with mock.patch('smart_account.services.trade_parameters', return_value=self.stock_params):
            with self.assertRaises(services.PrepareError) as raised:
                services.prepare_trade(self.viewer(self.owner), 'stock', '0x' + 'ab' * 40)
        self.assertEqual(raised.exception.code, 'complex_product_ack_required')
        self.complex, self.over_cap = False, True
        with mock.patch('smart_account.services.trade_parameters', return_value=self.crypto_params):
            with self.assertRaises(services.PrepareError) as raised:
                services.prepare_trade(self.viewer(self.owner), 'crypto', '0x' + 'ab' * 40)
        self.assertEqual(raised.exception.code, 'review_amount_cap')

    def test_submit_reruns_the_gates(self):
        with mock.patch('smart_account.services.trade_parameters', return_value=self.stock_params):
            batch = services.prepare_trade(self.viewer(self.owner), 'stock', '0x' + 'ab' * 40)
            action = SmartAccountPreparedAction.objects.get(request_id=batch.request_id)
            calls = [{'to': c['to'].lower(), 'value': c['value'], 'data': c['data'].lower()} for c in batch.calls]
            self.assertIsNone(relay_policy.trade_refusal(action, calls, self.owner, {}))
            # Acknowledgement withdrawn / amount over the review cap after prepare.
            self.complex, self.acked = True, False
            self.assertEqual(relay_policy.trade_refusal(action, calls, self.owner, {}),
                             'complex_product_ack_required')
            self.complex, self.over_cap = False, True
            self.assertEqual(relay_policy.trade_refusal(action, calls, self.owner, {}), 'review_amount_cap')
        # Unreadable: fails closed.
        with mock.patch('smart_account.services.trade_parameters', side_effect=RuntimeError('quote down')):
            self.assertEqual(relay_policy.trade_refusal(action, calls, self.owner, {}), 'trade_not_available')


@override_settings(CUSD_PLUS_7702_ENABLED=True, BSC_CHAIN_ID=56)
class SponsorSmartTradeGateTests(_GateHarness):
    def test_sponsor_refuses_an_account_trade_the_personal_rail_would_refuse(self):
        from cusd_plus.schema import SponsorBscBatch
        broadcasts = []

        def broadcast(*args, **kwargs):
            broadcasts.append(args)
            return '0x' + 'ab' * 32, SimpleNamespace(executed_early=None)
        with mock.patch('smart_account.services.trade_parameters', return_value=self.stock_params):
            batch = services.prepare_trade(self.viewer(self.owner), 'stock', '0x' + 'ab' * 40)
        self.complex, self.acked = True, False
        gql = [mock.Mock(to=c['to'], value_wei=c['value'], data=c['data']) for c in batch.calls]
        with mock.patch('smart_account.services.trade_parameters', return_value=self.stock_params), \
                mock.patch('cusd_plus.sponsor_7702.delegate_address', return_value='0x' + 'de' * 20), \
                mock.patch('cusd_plus.sponsor_7702.is_delegated', return_value=True), \
                mock.patch('cusd_plus.sponsor_7702.send_sponsored_batch', side_effect=broadcast), \
                mock.patch('cusd_plus.sponsor_7702.recover_intent_signer', return_value=self.owner.wallet), \
                mock.patch('payment_accounts.infinia_fee_collection.mint_policy_calls',
                           side_effect=lambda calls, *a, **k: calls):
            res = SponsorBscBatch.mutate(None, self.info(self.owner, 'smart', 0), gql, '0',
                                         str(int(time.time()) + 600), '0x' + '00' * 65, None,
                                         batch.request_id + '_a0')
        self.assertEqual((res.success, res.error), (False, 'complex_product_ack_required'))
        self.assertEqual(broadcasts, [])


# ── 6. a send to an account contract ────────────────────────────────────

class SendToAccountContractTests(SmartAccountTestCase):
    def test_reverse_lookup_never_resolves_an_account_contract(self):
        from send import bsc_flow
        owner = self.make_user('owner')
        account = self.make_account(owner)
        user, business, addr, err = bsc_flow._resolve_recipient(None, None, account.contract_address)
        self.assertEqual((user, business, addr, err), (None, None, None, 'recipient_is_smart_account'))
        self.assertIn('Cuenta inteligente', bsc_flow.SMART_ACCOUNT_RECIPIENT_MESSAGE)
        # An account inherited away (its row closed) is still a contract.
        account.account.soft_delete()
        self.assertEqual(bsc_flow._resolve_recipient(None, None, account.contract_address)[3],
                         'recipient_is_smart_account')
        # A personal wallet still resolves to its person.
        user, _business, addr, err = bsc_flow._resolve_recipient(None, None, owner.wallet)
        self.assertEqual((user, addr, err), (owner, owner.wallet, None))


# ── 7. ClaimExecuted to a wallet Confío does not know ───────────────────

class ClaimExecutedUnknownWalletTests(RelayHarness):
    def setUp(self):
        super().setUp()
        SmartAccount.objects.filter(pk=self.account.pk).update(
            paid_until=timezone.now() + timedelta(days=20), plan='monthly')
        self.account.refresh_from_db()
        entitlements.sync_account(self.account)
        self.heir = self.make_user('heir')
        self.row = SmartAccountBeneficiary.objects.create(
            smart_account=self.account, beneficiary_user=self.heir, beneficiary_address=self.heir.wallet,
            challenge_window_seconds=90 * 86400, state='active')
        self.claim = SmartAccountClaim.objects.create(
            beneficiary_row=self.row, initiated_at=timezone.now(), initiated_tx='0x' + '03' * 32,
            executable_at=timezone.now())
        slot = timezone.now() - timedelta(minutes=3)
        self.rule = SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=4, state='onchain', kind='buy', token_in=VAULT,
            token_out='0x' + '71' * 20, amount=Decimal('25.00'), frequency='weekly',
            next_run_at=slot, scheduled_for=slot, active=True)

    def test_inherited_state_is_mirrored_and_ops_alerted(self):
        from assistant.billing import has_plus
        self.assertTrue(has_plus(self.owner))
        old_row = self.account.account
        SmartAccountEvent.objects.create(
            address=self.address, tx_hash='0x' + 'e9' * 32, log_index=1, name='ClaimExecuted',
            args={'previousOwner': self.owner.wallet, 'newOwner': '0x' + '99' * 20}, block_number=1001,
            block_time=timezone.now())
        self.assertEqual(reconcile.apply_pending()['failed'], 0)
        self.account.refresh_from_db()
        self.assertEqual((self.account.status, self.account.plan, self.account.paid_until, self.account.account),
                         ('inherited', '', None, None))
        self.assertIsNotNone(self.account.inherited_at)
        self.assertEqual(self.account.inherited_from_user, self.owner)
        self.rule.refresh_from_db()
        self.assertEqual((self.rule.active, self.rule.state, self.rule.deactivated_reason),
                         (False, 'cancelled', 'inherited'))
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.state, 'executed')
        self.assertFalse(has_plus(self.owner))
        old_row.refresh_from_db()
        self.assertIsNotNone(old_row.deleted_at)
        self.assertTrue(self.ops_alert_mock.called)
        # The previous owner neither owns it nor holds it as inherited.
        from smart_account.context import own_account
        self.assertIsNone(own_account(self.owner))
        with self.assertRaises(services.PrepareError):
            services.inherited_account_for(self.viewer(self.owner), self.account.internal_id)
        self.assertFalse(relay_policy._inherited_target(self.owner, self.address))
        # Tasks no longer simulate a fee or a rule for it.
        self.assertFalse(automation._billing_candidates().filter(pk=self.account.pk).exists())
        self.assertFalse(automation.due_rules().filter(smart_account=self.account).exists())
        self.chain.views[(self.address, 'status')] = 1
        self.chain.views[(self.address, 'billingStatus')] = 1
        self.fund(VAULT, self.address, 500 * WAD)
        automation.collect_due_fees()
        automation.run_rules()
        self.assertEqual(self.signed, [])


# ── 8. startup check ────────────────────────────────────────────────────

class CancelClaimSettingCheckTests(SmartAccountTestCase):
    def test_warns_when_beneficiaries_are_on_without_required_cancel_claim(self):
        from smart_account.checks import cancel_claim_required_with_beneficiaries as check
        with override_settings(SMART_ACCOUNT_BENEFICIARY_ENABLED=True, SMART_ACCOUNT_REQUIRE_CANCEL_CLAIM=False):
            warnings = check()
        self.assertEqual([w.id for w in warnings], ['smart_account.W001'])
        self.assertIsInstance(warnings[0], checks.Warning)
        for beneficiary, required in ((True, True), (False, False), (False, True)):
            with override_settings(SMART_ACCOUNT_BENEFICIARY_ENABLED=beneficiary,
                                   SMART_ACCOUNT_REQUIRE_CANCEL_CLAIM=required):
                self.assertEqual(check(), [])
        self.assertIn(check, checks.registry.registry.get_checks())
