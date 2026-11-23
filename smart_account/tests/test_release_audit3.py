"""The audit of the rebuilt release, and Relay's shared rate limit. Each test
is named after what must hold. Synthetic ids, keys, names and addresses only."""
import itertools
import time
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache, caches
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from blockchain.models import SponsoredBatch
from notifications.models import Notification
from payment_accounts import contract_funding
from payment_accounts.relay import RelayError as ProviderError
from smart_account import automation, payouts, quotes, relayer
from smart_account.models import (
    SmartAccountPayout, SmartAccountPreparedAction, SmartAccountRelayTx, SmartAccountRule, SmartAccountRuleRun,
)

from . import infinia_world as w
from . import test_money_path_audit as mpa
from . import test_pagomovil_payouts as pm
from . import test_rule_retry_notices as rn
from .base import CUSD, WAD
from .infinia_base import InfiniaPayoutCase
from .test_tasks import RelayHarness

DAY, HOUR, MINUTE = timedelta(days=1), timedelta(hours=1), timedelta(minutes=1)
REQUESTS, STATUS = '/requests/v3', '/intents/status/v3'
VE = mpa.VE


def update_batch(user, account, rule, tx_hash, wallet, status='confirmed'):
    batch = SponsoredBatch.objects.create(
        user=user, user_bsc_address=wallet, kind='smart_rule', num_calls=1, calls_json='[]',
        tx_hash=tx_hash, gas_limit=1, max_fee_wei='1', status=status)
    SmartAccountPreparedAction.objects.create(
        request_id='fake-update', user=user, signer_address=wallet, target_address=account.contract_address.lower(),
        smart_account=account, kind='smart_rule', calls=[], calls_hash='f' * 64,
        payload={'replaces_pk': rule.pk}, expires_at=timezone.now() + 10 * MINUTE, consumed=True,
        sponsored_batch=batch)


class VeCase(mpa.VeBase):
    def setUp(self):
        super().setUp()
        self.offset = timedelta(0)
        self.base = timezone.now()
        for patcher in (mock.patch('django.utils.timezone.now', side_effect=lambda: self.base + self.offset),
                        mock.patch('time.time', side_effect=lambda: (self.base + self.offset).timestamp())):
            patcher.start()
            self.addCleanup(patcher.stop)
        type(self.account).objects.filter(pk=self.account.pk).update(paid_until=self.base + 90 * DAY)
        self.numbers = itertools.count(1)
        self.amount_out, self.deadline_in = '49400000', 900
        self.target.side_effect = self.fresh_target

    def fresh_target(self, ramp):
        number = next(self.numbers)
        return {'deposit_address': f'0x{0xd000 + number:040x}',
                'binding': {'provider': 'relay', 'request_id': f'0x{number:064x}', 'response': {},
                            'amount_out': self.amount_out, 'amount_out_min': self.amount_out,
                            'deadline': int((self.base + self.offset).timestamp()) + self.deadline_in}}

    def at(self, offset):
        self.offset = offset

    def pushed_failed(self):
        return Notification.objects.filter(user=self.owner, notification_type='RAMP_FAILED').count()

    def no_balance_then_funded(self):
        self.fund(CUSD, self.address, 0)
        self.run_rule()
        self.assertEqual(self.last_run().error, 'insufficient_balance')
        self.fund(CUSD, self.address, 500 * WAD)
        self.at(2 * DAY)


# ------------------------------------------------------------------- 2

@override_settings(**VE)
class HiccupAfterATopUpTests(VeCase):
    def keeps_the_slot(self, code):
        self.no_balance_then_funded()
        self.relay.side_effect = relayer.RelayError(code)
        self.run_rule()
        self.told.assert_not_called()
        run = self.last_run()
        self.assertTrue(run.error.startswith('insufficient_balance'), run.error)
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.scheduled_for, self.slot)
        self.relay.side_effect = None
        self.at(2 * DAY + 5 * MINUTE)
        self.assertEqual(self.run_rule()['sent'], 1)

    def test_a_contended_sponsor_lock(self):
        self.keeps_the_slot('sponsor_busy')

    def test_an_unreadable_node(self):
        self.keeps_the_slot('simulation_unreadable')

    def test_a_sponsor_without_gas_money(self):
        self.keeps_the_slot('sponsor_balance_low')

    def test_gas_over_the_cap(self):
        self.keeps_the_slot('gas_price_too_high')

    @override_settings(VE_PAGOMOVIL_SEND_USER_DAILY_USD='10')
    def test_a_passing_limit_waits(self):
        self.no_balance_then_funded()
        self.assertEqual(self.run_rule()['waiting'], 1)
        self.assertEqual(self.last_run().error, 'insufficient_balance: limit_exceeded')

    def test_a_refused_reservation_waits(self):
        from ramps import ve_send
        self.no_balance_then_funded()
        with mock.patch('ramps.ve_send.reserve', side_effect=ve_send.VeSendError('Ya hay un pago igual en curso.')):
            self.assertEqual(self.run_rule()['waiting'], 1)
        self.assertEqual(self.last_run().error, 'insufficient_balance: send_refused')
        self.at(2 * DAY + 5 * MINUTE)
        self.assertEqual(self.run_rule()['sent'], 1)

    def test_a_real_revert_still_keeps_24_hours(self):
        self.no_balance_then_funded()
        self.relay.side_effect = relayer.RelayError('simulation_reverted', 'execution reverted')
        self.run_rule()
        self.rule.refresh_from_db()
        self.assertGreater(self.rule.scheduled_for, self.slot + 20 * DAY)


class SimulationTests(RelayHarness):
    def code_for(self, error):
        self.simulate_error = error
        with self.assertRaises(relayer.RelayError) as raised:
            relayer.simulate('0x' + '5a' * 20, self.address, '0x', 100_000)
        return raised.exception.code

    def test_an_unreadable_node_is_not_a_revert(self):
        for error in ('all 4 BSC RPC endpoints failed: Read timed out.', '429 Client Error: Too Many Requests',
                      "bsc rpc: {'code': -32000, 'message': 'header not found'}"):
            self.assertEqual(self.code_for(error), 'simulation_unreadable', error)

    def test_a_revert_is_one(self):
        for error in ('execution reverted', "all 4 BSC RPC endpoints failed: bsc rpc: {'code': 3, 'message': "
                      "'execution reverted'}", 'out of gas'):
            self.assertEqual(self.code_for(error), 'simulation_reverted', error)


# ------------------------------------------------------------------- 3

@override_settings(**VE)
class DeadlineBeforeBuildingTests(VeCase):
    def not_paid_after(self, days):
        self.at(days * DAY)
        self.assertEqual(self.run_rule()['sent'], 0)
        self.relay.assert_not_called()
        self.assertFalse(self.ramps().exists())
        self.told.assert_called_once()
        self.rule.refresh_from_db()
        self.assertGreater(self.rule.scheduled_for, self.base + days * DAY)
        self.assertIn('No hicimos este pago', self.last_run().message)

    def test_a_pending_wait_is_not_paid_days_late(self):
        with override_settings(RELAY_API_KEY=''):
            self.assertEqual(self.run_rule()['waiting'], 1)
        self.not_paid_after(5)

    def test_a_retry_later_quote_is_not_paid_days_late(self):
        with mock.patch('smart_account.automation.build_rule_call',
                        side_effect=quotes.QuoteUnavailable('share_price_unavailable', retry_later=True)):
            self.assertEqual(self.run_rule()['waiting'], 1)
        self.not_paid_after(10)

    def test_a_pass_that_crashed_is_not_paid_days_late(self):
        with mock.patch('smart_account.automation.build_rule_call', side_effect=RuntimeError('rpc down')):
            self.run_rule()
        self.not_paid_after(2)

    def test_a_first_look_after_the_deadline_never_starts_a_wait(self):
        self.at(2 * DAY)
        with mock.patch('smart_account.automation.build_rule_call',
                        side_effect=quotes.QuoteUnavailable('share_price_unavailable', retry_later=True)):
            self.assertEqual(self.run_rule()['waiting'], 0)
        self.told.assert_called_once()


# ------------------------------------------------------------------- 4

class UnmirroredUpdateTests(InfiniaPayoutCase):
    amount = '100.00'

    def test_a_confirmed_update_with_the_same_next_run_waits_for_its_event(self):
        self.make_rule()
        keep = self.world.rules[(self.contract, 1)]['next_run_at']
        tx = self.update_on_chain()
        self.world.rules[(self.contract, 1)]['next_run_at'] = keep
        update_batch(self.user, self.account, self.rule, tx, self.wallet)
        self.assertEqual(self.run_rules()['waiting'], 1)
        self.assertEqual((self.last_run().error, self.world.signed), ('rule_mirror_behind', {}))
        self.mirror_chain()             # RuleUpdated applied
        self.send_run()
        self.workers()
        self.assertNotIn('terms_changed', self.bridge().binding['contract_funding'])
        self.assertEqual(self.to_paid().status, 'paid')

    def test_one_confirmed_while_signing_aborts(self):
        self.make_rule()
        real = relayer.simulate

        def confirmed(*args):
            real(*args)
            update_batch(self.user, self.account, self.rule, '0x' + '8b' * 32, self.wallet)
        with mock.patch('smart_account.relayer.simulate', side_effect=confirmed):
            self.assertEqual(self.run_rules()['waiting'], 1)
        self.assertEqual((self.world.signed, SmartAccountRelayTx.objects.count()), ({}, 0))


class UnmirroredSendUpdateTests(rn.RetryCase):
    def test_a_send_behind_its_update_waits_instead_of_being_deactivated(self):
        self.make_rule(balance=500)
        self.chain.rules[(self.address, 4)]['amount_usd_wei'] = 30 * WAD
        update_batch(self.owner, self.account, self.rule, '0x' + '8c' * 32, self.owner.wallet)
        self.assertEqual(self.tick()['waiting'], 1)
        self.rule.refresh_from_db()
        self.assertTrue(self.rule.active)


# ------------------------------------------------------------------- 5, 8, 10, 11, 12

@override_settings(**VE)
class ContractFundedOrderTests(VeCase):
    def test_a_target_hiccup_is_not_pushed_as_a_failed_withdrawal(self):
        from ramps.ve_pagomovil import VePagoMovilError
        self.target.side_effect = VePagoMovilError('relay hiccup')
        self.assertEqual(self.run_rule()['waiting'], 1)
        self.assertEqual(self.pushed_failed(), 0)
        self.target.side_effect = self.fresh_target
        self.assertEqual(self.run_rule()['sent'], 1)
        self.assertEqual(self.pushed_failed(), 0)

    def expires_quietly(self, offset, phase='funding_reported', **values):
        from ramps import ve_send
        self.relay.side_effect = relayer.RelayError('claim_busy')
        self.run_rule()
        ramp = ve_send._update(self.ramps().get().pk, phase=phase, **values)
        self.at(offset)
        self.assertEqual(ve_send.sync(ramp).status, 'FAILED')
        self.assertEqual(self.pushed_failed(), 0)

    def test_an_expired_quote_closes_quietly(self):
        self.expires_quietly(HOUR)

    def test_an_expired_claim_without_a_deadline_closes_quietly(self):
        with mock.patch('ramps.ve_send._find_funding', return_value=None):
            self.expires_quietly(7 * HOUR, bridge={})

    def test_an_unclaimed_order_closes_quietly(self):
        self.expires_quietly(3 * HOUR, phase='awaiting_funding')

    def history(self):
        from users.models_unified import UnifiedTransactionTable
        return UnifiedTransactionTable.objects.filter(ramp_transaction__isnull=False, deleted_at__isnull=True)

    def test_replaced_attempts_leave_one_row_in_history(self):
        from ramps.ve_pagomovil import VePagoMovilError
        self.target.side_effect = VePagoMovilError('relay hiccup')
        for hour in range(8):
            self.at(hour * HOUR + 4 * MINUTE)
            self.run_rule()
        self.assertGreater(self.ramps().count(), 1)
        self.assertEqual(self.history().count(), 1)

    def test_a_replaced_attempt_funded_late_is_shown_again(self):
        from ramps import ve_send
        self.relay.side_effect = relayer.RelayError('simulation_reverted', 'execution reverted')
        self.run_rule()
        self.at(5 * MINUTE)
        self.run_rule()
        first = self.ramps().order_by('pk').first()
        self.assertFalse(self.history().filter(ramp_transaction=first).exists())
        ve_send._mark_funded(first, pm.TX, pm.EXACT, late=True)
        self.assertTrue(self.history().filter(ramp_transaction=first).exists())

    def test_the_funded_route_is_held_to_the_signed_cost_limit(self):
        self.amount_out = '47000000'        # about 515 bps; the estimate was inside
        self.assertEqual(self.run_rule()['sent'], 0)
        self.relay.assert_not_called()
        self.assertEqual(self.last_run().error, 'bridge_cost_above_limit')
        self.assertEqual((self.ramps().get().status, self.pushed_failed()), ('FAILED', 0))

    def test_a_route_without_its_output_is_never_funded(self):
        self.amount_out = ''
        self.assertEqual(self.run_rule()['waiting'], 1)
        self.relay.assert_not_called()

    def test_a_resumed_order_is_held_to_it_too(self):
        from ramps import ve_send
        self.relay.side_effect = relayer.RelayError('claim_busy')
        self.run_rule()
        ramp = self.ramps().get()
        ve_send._update(ramp.pk, bridge=dict(ve_send._section(ramp)['bridge'], amount_out='47000000'))
        self.relay.side_effect = None
        self.relay.reset_mock()
        self.assertEqual(self.run_rule()['sent'], 0)
        self.relay.assert_not_called()

    def test_the_route_is_a_one_time_address(self):
        seen = []

        def routes(client, *args, **kwargs):
            seen.append(client)
            return [{}]
        build = {'amountOut': '49400000', 'amountOutMin': '49000000',
                 'relay': {'request_id': '0x' + '11' * 32, 'response': {}, 'deadline': 2_000_000_000}}
        with mock.patch('payment_accounts.relay.RelayClient.routes', routes), \
                mock.patch('payment_accounts.relay.RelayClient.build', return_value=build), \
                mock.patch('payment_accounts.bridge_binding.deposit_call', return_value=('0x' + 'de' * 20, {})), \
                mock.patch('ramps.pagoasap_send._require_payable'):
            for recovery in ('0x' + '11' * 20, ''):     # an order with none recorded, too
                ramp = SimpleNamespace(pk=1, actor_address=self.address, metadata={'ve_send': {
                    'deposit_wei': str(pm.EXACT), 'funding_sender': CUSD, 'funding_terms': {'recovery': recovery}}})
                self.real_target(ramp)
                self.assertIsInstance(seen[-1], contract_funding.OneTimeDepositRelay)
            ramp = SimpleNamespace(pk=1, actor_address=self.address, metadata={'ve_send': {
                'deposit_wei': str(pm.EXACT)}})
            self.real_target(ramp)
            self.assertNotIsInstance(seen[-1], contract_funding.OneTimeDepositRelay)    # the wallet's own send

    def test_an_address_another_order_was_given_is_refused(self):
        from ramps import ve_send
        used = f'0x{0xd001:040x}'
        other = self.make_user('other')
        row = self.ramps().model(provider='pagoasap', direction='off_ramp', status='FAILED', country_code='VE',
                                 actor_user=other, destination='cusd_plus', fiat_currency='VES',
                                 external_id='earlier', status_detail='expired_unfunded',
                                 metadata={ve_send.SECTION: {'deposit_address': used}})
        row.save()
        self.assertEqual(self.run_rule()['waiting'], 1)
        self.relay.assert_not_called()
        self.assertIn('deposit_address_reused', str(self.ops_alert_mock.call_args_list))
        self.assertEqual(self.run_rule()['sent'], 1)        # the next one is unused

    def test_a_short_deadline_waits(self):
        self.deadline_in = 30
        self.assertEqual(self.run_rule()['waiting'], 1)
        self.assertEqual((self.last_run().status, self.last_run().error, self.pushed_failed()),
                         ('pending', 'provider_quote_expired', 0))
        self.deadline_in = 900
        self.assertEqual(self.run_rule()['sent'], 1)


# ------------------------------------------------------------------- 6, 7

@override_settings(**VE)
class RateClockTests(VeCase):
    def test_a_recovered_rate_restarts_the_hour(self):
        ramp = self.settled()
        self.rate('30')
        self.sync(ramp)
        self.rate('40')
        self.provider.balances.return_value = {'USD': Decimal('0')}
        self.at(5 * MINUTE)
        self.assertEqual(self.sync(ramp).status_detail, 'waiting_balance')
        self.rate('30')
        self.at(2 * HOUR)
        self.assertEqual(self.sync(ramp).status_detail, 'waiting_rate')
        self.at(3 * HOUR + MINUTE)
        self.assertEqual(self.sync(ramp).status_detail, 'needs_review:fx_quote_outside_authorization')


class InfiniaRateClockTests(mpa.InfiniaCase):
    def test_a_rate_inside_the_limit_clears_the_hour(self):
        self.funded()
        self.world.rates['MXN'] = mpa.BELOW
        self.journeys()
        self.assertTrue(self.journey().money_flow.metadata.get('fx_wait_since'))
        self.world.rates['MXN'] = mpa.ABOVE
        self.journeys()
        self.assertFalse(self.journey().money_flow.metadata.get('fx_wait_since'))


@override_settings(**VE)
class ReachedAndNeverExecutedTests(VeCase):
    def test_a_superseded_slot_in_review_tells_owner_and_ops_once(self):
        from ramps import ve_send
        self.assertEqual(self.run_rule()['sent'], 1)
        row = SmartAccountRelayTx.objects.create(
            smart_account=self.account, kind='smart_execute_rule', calldata='0x', signed_tx_hash=pm.TX,
            source_id=f'rule:{self.rule.pk}:{int(self.slot.timestamp())}', status='sent')
        self.at(7 * HOUR)
        ve_send.sync(self.ramps().get())
        payouts.mirror_ramp_payouts()
        self.assertEqual(SmartAccountPayout.objects.get().status, 'review')
        SmartAccountRelayTx.objects.filter(pk=row.pk).update(status='dropped')
        row.refresh_from_db()
        automation.on_relay_tx_final(row)
        with mock.patch('smart_account.notifications._send') as sent:
            self.at(32 * DAY)
            self.run_rule()
            self.run_rule()
        sent.assert_called_once()
        self.assertIn('no lo repitas', sent.call_args.args[2])
        self.assertNotIn('No hicimos', sent.call_args.args[2])
        self.assertIn('sin ejecución confirmada', str(self.ops_alert_mock.call_args_list))
        first = SmartAccountRuleRun.objects.get(scheduled_for=self.slot)
        self.assertNotEqual(first.status, 'ok')
        self.assertIn('no lo repitas', first.message)


# ------------------------------------------------------------------- 9

class NonceLockRenewalTests(InfiniaPayoutCase):
    def test_a_killed_worker_frees_the_lock_in_seconds_and_a_live_one_keeps_it(self):
        self.make_rule()
        backend = type(caches['default'])     # each thread has an instance of its own
        touches, real_touch, real_rpc = [], backend.touch, self.world.rpc

        def touch(store, key, timeout=None, *args, **kwargs):
            if key == relayer.NONCE_LOCK:
                touches.append(timeout)
            return real_touch(store, key, timeout, *args, **kwargs)

        def rpc(chain, method, params):
            if method == 'eth_sendRawTransaction':
                before = len(touches)
                for _ in range(200):
                    if len(touches) >= before + 2:
                        break
                    time.sleep(0.01)
                self.renewed = len(touches) - before
            return real_rpc(chain, method, params)
        with mock.patch.object(backend, 'touch', touch), \
                mock.patch.object(self.world, 'rpc', side_effect=rpc), \
                mock.patch('smart_account.relayer.RENEW_SECONDS', 0.02, create=True):
            self.assertEqual(self.run_rules()['sent'], 1)
        self.assertLessEqual(max(touches), 15)      # what a killed worker leaves behind
        self.assertGreaterEqual(self.renewed, 2)
        after = len(touches)
        time.sleep(0.06)
        self.assertEqual(len(touches), after)       # nothing renews a released lock


# ------------------------------------------------------------------- 13

class LateMinedTests(rn.RetryCase):
    def test_given_up_then_mined_does_not_skip_a_month(self):
        self.make_rule()
        self.tick()
        self.tick(3 * DAY + HOUR)
        self.rule.refresh_from_db()
        next_date = self.rule.scheduled_for
        tx = '0x' + 'ab' * 32
        SmartAccountRuleRun.objects.update(tx_hash=tx)
        self.executed(tx)
        self.rule.refresh_from_db()
        self.assertLess(self.rule.scheduled_for, next_date + 7 * DAY)
        self.assertGreaterEqual(self.rule.scheduled_for, self.rule.next_run_at)


# ------------------------------------------------------------------- 14

class LookupBudgetTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.clock = 1_000_000.0
        patcher = mock.patch('time.time', side_effect=lambda: self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, who):
        from payment_accounts import relay_lookups
        if relay_lookups.take(who):
            relay_lookups.done(who)
            return True
        return False

    def test_the_normal_path_is_not_slowed_to_two_a_minute(self):
        self.assertTrue(all(self.get(f't{n}') for n in range(60)))
        self.assertFalse(self.get('t60'))

    @override_settings(RELAY_REQUESTS_PER_MINUTE=2)
    def test_whoever_waited_longest_is_next_whichever_worker_asks_first(self):
        self.assertTrue(self.get('a') and self.get('b'))
        for who in ('c', 'd', 'e'):
            self.clock += 1
            self.assertFalse(self.get(who))
        self.clock += 62
        self.assertFalse(self.get('a'))         # back of the line
        self.assertFalse(self.get('e'))
        self.assertTrue(self.get('c') and self.get('d'))

    def test_a_429_falls_back_for_every_worker_then_recovers(self):
        from payment_accounts import relay_lookups
        self.assertTrue(relay_lookups.take('a'))
        relay_lookups.refused('a')
        self.assertFalse(self.get('b'))
        self.clock += 62
        self.assertFalse(self.get('c') and self.get('d'))
        self.assertTrue(self.get('a'))          # kept its place
        self.assertTrue(self.get('b'))
        self.clock += relay_lookups.FALLBACK_SECONDS + 1
        self.assertTrue(all(self.get(f'n{n}') for n in range(30)))


class FollowedRequestTests(InfiniaPayoutCase):
    CHILD = '0x' + '7c' * 32

    def sent(self):
        self.make_rule()
        self.send_run()
        self.order = self.world.orders[-1]
        self.tx = self.last_run().tx_hash

    def bound_pending(self):
        self.sent()
        self.world.settle(self.order, self.tx, None, {'status': 'pending'})
        self.bridges()

    def gets(self):
        return self.world.count('relay', REQUESTS)

    def throttle(self, *paths):
        real = self.world.relay

        def relay(method, path, body, params, headers):
            if path in paths:
                self.world.log.append(('relay', path))
                return w.Response({'error': 'RATE_LIMITED'}, 429)
            return real(method, path, body, params, headers)
        return mock.patch.object(self.world, 'relay', side_effect=relay)

    def assert_waiting(self):
        self.assertEqual((self.bridge().status, self.bridge().failure_code), ('bridging', ''))
        self.assertEqual(self.journey().stage, 'awaiting_credit')
        self.assertNotIn(self.payout().status, ('review', 'cancelled', 'refunded'))

    def test_a_bound_request_is_followed_by_status_alone(self):
        self.bound_pending()
        asked, polled = self.gets(), self.world.count('relay', STATUS)
        for _ in range(4):
            self.bridges()
        self.assertEqual(self.gets(), asked)
        self.assertEqual(self.world.count('relay', STATUS), polled + 4)
        bound = self.bridge().binding['contract_funding']['relay_request']
        self.assertEqual((bound['id'], bound['tx']), (self.order['request_id'], self.tx))
        self.assertEqual(self.to_paid().status, 'paid')
        self.assertEqual(self.gets(), asked)

    def test_a_bound_request_of_another_funding_hash_is_not_followed(self):
        self.bound_pending()
        bridge = self.bridge()
        data = bridge.binding['contract_funding']
        data['relay_request'].update(id='0x' + '6a' * 32, tx='0x' + '6b' * 32)
        type(bridge).objects.filter(pk=bridge.pk).update(binding=bridge.binding)
        asked = self.gets()
        self.bridges()
        self.assertGreater(self.gets(), asked)
        self.assertEqual(self.bridge().binding['contract_funding']['relay_request']['id'], self.order['request_id'])

    def test_a_regenerated_request_replaces_a_stale_bound_one(self):
        self.bound_pending()
        self.world.relay_fills(self.order, request_id=self.CHILD)
        self.advance(301)
        self.bridges()
        self.assertEqual((self.bridge().status, self.bridge().binding['settlement_evidence']['request_id']),
                         ('delivered', self.CHILD))

    def test_a_child_refund_wins_over_a_parent_that_needs_a_manual_one(self):
        self.sent()
        self.world.settle(self.order, self.tx, None, {
            'status': 'failure', 'originChainId': 56, 'destinationChainId': 137, 'inTxHashes': [], 'txHashes': [],
            'refundFailReason': 'MANUAL_REFUND_REQUIRED'})
        self.world.relay_refunds(self.order, request_id=self.CHILD, child=True)
        self.workers()
        self.assertEqual(self.bridge().status, 'refunded')

    def test_a_waiting_request_is_never_bound(self):
        self.sent()
        self.world.settle(self.order, self.tx, None, {'status': 'waiting'})
        self.bridges()
        self.assertNotIn('relay_request', self.bridge().binding['contract_funding'])
        self.assertEqual(self.to_paid().status, 'paid')

    def test_a_429_on_the_lookup_never_parks_and_backs_off(self):
        self.sent()
        with self.throttle(REQUESTS):
            self.bridges()
            self.assertEqual(self.gets(), 1)
            self.age(4500)
            self.workers()
            self.assert_waiting()
            self.assertNotIn('limita', self.alert_text())
            self.age(8000)
            self.workers()
            self.assert_waiting()
        self.assertIn('limita', self.alert_text())      # ops, after longer
        self.assertEqual(self.to_paid().status, 'paid')

    def test_a_429_on_the_status_never_parks(self):
        self.bound_pending()
        with self.throttle(STATUS):
            self.age(8000)
            self.workers()
            self.assert_waiting()
        self.assertEqual(self.to_paid().status, 'paid')

    @override_settings(RELAY_REQUESTS_PER_MINUTE=0)
    def test_an_empty_budget_sends_no_get_and_parks_nothing(self):
        self.sent()
        self.age(8000)
        self.workers()
        self.assert_waiting()
        self.assertEqual(self.gets(), 0)

    def test_a_429_never_unparks_a_delayed_one(self):
        self.sent()
        self.age(4500)
        self.bridges()
        self.assertEqual(self.bridge().failure_code, 'relay_settlement_delayed')
        with self.throttle(REQUESTS):
            self.bridges()
            self.assertEqual((self.bridge().status, self.bridge().failure_code),
                             ('needs_review', 'relay_settlement_delayed'))


@override_settings(**VE)
class TenPayoutsTests(pm.RunBase):
    """Ten owners due at once, Relay allowing 2 lookups a minute App-wide."""
    COUNT = 10
    RECIPIENT = '0x' + '9a' * 20

    def setUp(self):
        from ramps import ve_send
        real = ve_send.reserve
        super().setUp()
        for patcher in (mock.patch('ramps.ve_send.reserve', side_effect=real),
                        mock.patch('smart_account.payouts.ramp_funding_problem', return_value=''),
                        mock.patch('ramps.ve_send.pay_out', side_effect=lambda ramp: ramp)):
            patcher.start()
            self.addCleanup(patcher.stop)
        for number in range(2, self.COUNT + 1):
            user = self.make_user(f'owner{number}')
            account = self.make_account(user)
            address = account.contract_address.lower()
            self.fund(CUSD, address, 500 * WAD)
            saved = self.save(user)
            from smart_account import services
            services.prepare_payout_rule(self.viewer(user), None, saved.payout_method.payout_method_id,
                                         '50.00', 'monthly')
            rule = SmartAccountRule.objects.get(smart_account=account, state='draft')
            SmartAccountRule.objects.filter(pk=rule.pk).update(
                state='onchain', active=True, onchain_id=1, scheduled_for=self.slot, next_run_at=self.slot)
            self.chain.rules[(address, 1)] = dict(self.chain.rules[(self.address, 1)])
            self.chain.views[(address, 'status')] = 1
            self.chain.views[(address, 'billingStatus')] = 0
        numbers, hashes = itertools.count(1), itertools.count(1)

        def target(ramp):
            number = next(numbers)
            return {'deposit_address': f'0x{0xd000 + number:040x}', 'binding': {
                'provider': 'relay', 'request_id': f'0x{number:064x}', 'recipient': self.RECIPIENT,
                'amount_out': '49400000', 'amount_out_min': '48500000',
                'deadline': int(timezone.now().timestamp()) + 600,
                'response': {'protocol': {'v2': {'paymentDetails': {
                    'chainId': 'bnb', 'currency': w.USDT, 'amount': str(pm.EXACT), 'depository': w.DEPOSITORY}}}}}}
        self.target.side_effect = target
        self.relay.side_effect = lambda *a, **k: (SimpleNamespace(signed_tx_hash=f'0x{next(hashes):064x}'), True)

    def funded(self):
        from ramps import ve_send
        self.assertEqual(self.run_rule()['sent'], self.COUNT)
        self.transfers = {}
        for number, payout in enumerate(SmartAccountPayout.objects.select_related('ramp').order_by('pk'), start=1):
            section = ve_send._section(payout.ramp)
            names = {key: f'0x{0x100000 * kind + number:064x}'
                     for kind, key in enumerate(('tx', 'request', 'sweep', 'fill'), start=1)}
            names['deposit'] = section['deposit_address']
            self.transfers[payout.ramp_id] = names
            # An hour behind already: a throttled lookup would cross the delay.
            ve_send._update(payout.ramp_id, status='PROCESSING', detail='funded', phase='funded', quiet=True,
                            funding_tx_hash=names['tx'], funded_wei=str(pm.EXACT),
                            bridge=dict(section['bridge'], deadline=int(timezone.now().timestamp()) - 3500))

    def receipts(self):
        out = {}

        def put(tx, block, entry):
            out[tx] = {'transactionHash': tx, 'status': '0x1', 'blockNumber': hex(block), 'transactionIndex': '0x0',
                       'logs': [dict(entry, transactionHash=tx, logIndex='0x0')]}
        for t in self.transfers.values():
            put(t['tx'], 100, w.transfer_log(w.USDT, pm.CUSD, t['deposit'], pm.EXACT))
            put(t['sweep'], 101, w.transfer_log(w.USDT, t['deposit'], w.DEPOSITORY, pm.EXACT))
            put(t['fill'], 9, w.transfer_log(w.USDC, w.SOLVER, self.RECIPIENT, 49_400_000))
        return out

    def all_settle(self):
        from ramps import tasks, ve_send
        self.funded()
        by_request = {t['request']: t for t in self.transfers.values()}
        clock, start = [0], timezone.now()
        served, self.refused = [], 0

        def request(client, method, path, body=None, params=None):
            if path == STATUS:
                t = by_request[params['requestId']]         # only ever a request some deposit owns
                return {'status': 'success', 'originChainId': 56, 'destinationChainId': 137,
                        'inTxHashes': [t['sweep']], 'txHashes': [t['fill']]}
            self.assertEqual(path, REQUESTS)
            if len([at for at in served if at > clock[0] - 60]) >= 2:
                self.refused += 1
                raise ProviderError('Relay request failed', status_code=429)
            served.append(clock[0])
            # Everybody's rows, whatever was asked: only deposit + hash may bind.
            return {'requests': [{'id': t['request'], 'status': 'success', 'depositAddress': {
                'address': t['deposit'], 'depositTxHash': t['tx']}} for t in self.transfers.values()]}

        receipts = self.receipts()
        with mock.patch('payment_accounts.relay.RelayClient._request', request), \
                mock.patch('payment_accounts.bridge_chain.final_receipt', side_effect=lambda c, tx: receipts.get(tx)), \
                mock.patch('time.time', side_effect=lambda: start.timestamp() + clock[0]), \
                mock.patch('django.utils.timezone.now', side_effect=lambda: start + timedelta(seconds=clock[0])):
            for _ in range(20):
                tasks.poll_ve_pagomovil()
                rows = list(self.ramps())
                for ramp in rows:
                    self.assertNotIn('needs_review', ramp.status_detail)
                if all(ve_send._phase(ramp) == 'settled' for ramp in rows):
                    break
                clock[0] += 60
            else:
                self.fail([ramp.status_detail for ramp in rows])
        for ramp in rows:
            section, own = ve_send._section(ramp), self.transfers[ramp.pk]
            self.assertEqual((section['delivered_tx'], section['relay_follow']['relay_request']['id']),
                             (own['fill'], own['request']))

    @override_settings(RELAY_REQUESTS_PER_MINUTE=2)
    def test_all_settle_at_two_a_minute_without_ever_being_refused(self):
        self.all_settle()
        self.assertEqual(self.refused, 0)

    def test_all_settle_when_relay_refuses_over_two_a_minute(self):
        self.all_settle()
        self.assertLessEqual(self.refused, 3)       # one refusal and everybody slows
