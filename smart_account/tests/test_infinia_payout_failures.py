"""What goes wrong in a contract-funded CLABE / Pix run: money never moves
twice, never without its receipt, and never out of sight.
Fake values only."""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from payment_accounts import bridge_execution, contract_funding, infinia_journeys
from payment_accounts.models import (
    InfiniaFeeDebt, InfiniaJourney, LedgerEntry, MoneyFlow, MoneyOperation, PaymentBridgeTransfer,
)
from payment_accounts.services import PaymentAccountError
from smart_account import automation, infinia_payouts, payouts, tasks
from smart_account.models import (
    SmartAccountPayout, SmartAccountRelayTx, SmartAccountRule, SmartAccountRuleRun,
    SmartAccountStandingAuthorization,
)

from . import infinia_world as w
from .infinia_base import InfiniaPayoutCase


class NothingBroadcastTests(InfiniaPayoutCase):
    def test_an_interrupted_pass_keeps_one_order_and_then_sends_it(self):
        self.make_rule()
        for _ in range(3):      # inside the deposit's lifetime
            self.assertEqual(self.leave_order_open()['errors'], 1)
            self.advance(120)
        self.assertEqual((PaymentBridgeTransfer.objects.count(), InfiniaJourney.objects.count()), (1, 1))
        quoted, pk = len(self.world.orders), self.bridge().pk
        self.send_run()
        self.assertEqual((len(self.world.orders), self.bridge().pk), (quoted, pk))
        self.assertEqual(self.to_paid().status, 'paid')

    def test_an_order_past_its_lifetime_is_closed_then_replaced_and_paid(self):
        self.make_rule()
        self.leave_order_open()
        first = self.bridge()
        self.age(500)       # under three minutes left
        self.assertEqual(self.run_rules()['sent'], 1)
        first.refresh_from_db()
        self.assertEqual((first.status, first.infinia_journey.stage), ('expired', 'failed'))
        second = self.payout().journey.bridge
        self.assertNotEqual((second.deposit_address, second.quote.request_id),
                            (first.deposit_address, first.quote.request_id))
        bound = second.quote.money_flow.metadata['contract_funding']
        self.assertEqual((bound['attempt'], bound['replaces']), (2, str(first.internal_id)))
        self.assertEqual((len(self.world.signed), PaymentBridgeTransfer.objects.count()), (1, 2))

    def test_an_abandoned_order_expires_and_stops_holding_the_owner(self):
        self.make_rule()
        self.leave_order_open()
        SmartAccountRule.objects.update(active=False)      # nothing will resume it
        self.age(600)
        self.bridges()
        self.assertEqual(self.bridge().status, 'submitted')     # inside the grace
        self.age(400)
        self.workers()
        self.assertEqual((self.bridge().status, self.journey().stage, self.payout().status),
                         ('expired', 'failed', 'cancelled'))
        from payment_accounts.infinia_bridge import live_journeys
        self.assertFalse(live_journeys(InfiniaJourney.objects.filter(confio_account=self.personal)).exists())
        self.assertNotIn('puente', self.alert_text())       # only run_rules' own error report

    def test_a_slot_given_up_closes_its_order(self):
        self.make_rule()
        self.leave_order_open()
        self.world.revert_simulation = True
        with mock.patch.object(automation, 'RULE_SLOT_GIVE_UP', timedelta(0)):
            self.run_rules()
        self.assertEqual((self.bridge().status, self.payout().status), ('expired', 'cancelled'))

    def test_an_order_whose_call_may_land_is_not_closed(self):
        self.make_rule()
        self.world.hold_broadcast = True
        self.assertEqual(self.run_rules()['sent'], 1)
        self.age(1000)
        self.bridges()
        self.assertEqual(self.bridge().status, 'submitted')

    def test_a_fee_change_on_retry_replaces_the_order(self):
        self.make_rule()
        self.leave_order_open()
        first = self.bridge()
        self.world.fee_bps = 80
        self.assertEqual(self.run_rules()['sent'], 1)
        first.refresh_from_db()
        self.assertEqual(first.status, 'expired')
        second = self.payout().journey.bridge
        self.assertGreater(int(second.quote.amount_units), int(first.quote.amount_units))
        self.assertEqual(len(self.world.signed), 1)


class LateFundingTests(InfiniaPayoutCase):
    def closed_but_still_out_there(self):
        self.make_rule()
        self.world.hold_broadcast = True
        self.assertEqual(self.run_rules()['sent'], 1)
        # The node lost it: dropped, the slot released, the order closed.
        SmartAccountRelayTx.objects.update(status='dropped')
        SmartAccountRuleRun.objects.update(status='failed')
        self.age(1000)
        self.workers()
        self.assertEqual((self.bridge().status, self.payout().status), ('expired', 'cancelled'))

    def test_money_after_closure_reaches_review_and_never_pays(self):
        self.closed_but_still_out_there()
        self.world.mine_held()
        with mock.patch('smart_account.notifications.payout_resumed') as resumed:
            self.mirror_chain()
        resumed.assert_called_once()
        self.workers()
        self.assertEqual((self.journey().stage, self.payout().status), ('needs_review', 'review'))
        self.assertTrue(self.bridge().source_tx_hash)       # attributable
        self.deliver()
        for _ in range(3):
            self.run_rules()
            self.workers()
        self.assertEqual(self.bridge().status, 'delivered')
        self.assertIsNotNone(self.bridge().provider_credit_id)
        self.assertEqual((self.world.transfers, self.world.payouts, len(self.world.signed)), ([], [], 1))
        self.assertEqual((self.payout().status, self.journey().stage), ('review', 'needs_review'))
        self.assertIn('ya cerrado', self.alert_text())

    def test_money_after_closure_that_relay_returns_is_refunded(self):
        self.closed_but_still_out_there()
        self.world.mine_held()
        self.mirror_chain()
        self.bridges()
        self.world.relay_refunds()
        self.workers()
        self.assertEqual((self.bridge().status, self.payout().status, self.world.payouts), ('refunded', 'refunded', []))

    def test_a_confirmed_call_without_its_event_goes_to_review_and_frees_the_owner(self):
        self.make_rule()
        self.assertEqual(self.run_rules()['sent'], 1)
        self.relay_receipts()           # confirmed, its event not read yet
        self.age(4300)
        self.bridges()
        self.journeys()
        self.assertEqual(self.bridge().failure_code, 'contract_funding_unreported')
        self.assertEqual(self.journey().stage, 'needs_review')
        from payment_accounts.infinia_bridge import live_journeys
        self.assertFalse(live_journeys(InfiniaJourney.objects.filter(confio_account=self.personal)).exists())
        self.mirror()
        self.assertEqual(self.payout().status, 'prepared')      # a late event still finds it
        self.step(tasks.reconcile_events)
        self.workers()
        self.assertTrue(self.bridge().source_tx_hash)
        self.assertEqual((self.payout().status, self.world.payouts), ('review', []))

    def test_a_lost_report_is_made_again_by_the_mirror(self):
        self.make_rule()
        self.assertEqual(self.run_rules()['sent'], 1)
        with mock.patch('payment_accounts.contract_funding.report_funding', side_effect=RuntimeError('db')):
            self.mirror_chain()
        self.assertEqual(self.bridge().binding['contract_funding']['reported'], [])
        self.mirror()
        self.assertEqual(self.bridge().binding['contract_funding']['reported'], [self.last_run().tx_hash])
        self.assertEqual(self.to_paid().status, 'paid')


class FundingProofTests(InfiniaPayoutCase):
    def reported(self, change):
        self.make_rule()
        self.send_run()
        receipt = self.world.mined['BSC'][self.last_run().tx_hash]
        change(receipt, next(e for e in receipt['logs'] if e['address'] == w.USDT))
        self.bridges()
        self.journeys()
        self.mirror()

    def assert_unfunded_review(self):
        self.assertEqual((self.bridge().status, self.bridge().failure_code, self.bridge().source_tx_hash),
                         ('needs_review', 'source_transfer_mismatch', ''))
        self.assertEqual((self.journey().stage, self.payout().status), ('needs_review', 'review'))
        self.assertEqual((self.world.transfers, self.world.payouts), ([], []))
        self.assertIn('no pagó', self.alert_text())

    def test_wrong_sender(self):
        self.reported(lambda r, e: e['topics'].__setitem__(1, w.word_address(self.contract)))
        self.assert_unfunded_review()

    def test_wrong_recipient(self):
        self.reported(lambda r, e: e['topics'].__setitem__(2, w.word_address(w.SOLVER)))
        self.assert_unfunded_review()

    def test_wrong_token(self):
        self.reported(lambda r, e: e.__setitem__('address', '0x' + '99' * 20))
        self.assert_unfunded_review()

    def test_less_than_quoted(self):
        self.reported(lambda r, e: e.__setitem__('data', f'0x{int(e["data"], 16) - 1:064x}'))
        self.assert_unfunded_review()

    def test_a_reverted_transaction_funds_nothing(self):
        self.reported(lambda r, e: r.__setitem__('status', '0x0'))
        self.assert_unfunded_review()

    def test_more_than_quoted_from_the_vault_funds_it_and_tells_ops(self):
        self.make_rule()
        self.world.hold_broadcast = True
        self.assertEqual(self.run_rules()['sent'], 1)
        self.world.fee_bps = 80     # the fee fell before inclusion: the cUSD floor still holds
        self.world.mine_held()
        self.mirror_chain()
        self.assertEqual(self.to_paid().status, 'paid')
        self.assertGreater(int(self.bridge().binding['contract_funding']['funded_units']),
                           int(self.bridge().quote.amount_units))
        self.assertIn('más de lo cotizado', self.alert_text())
        self.assertIn('no coincide', self.alert_text())

    def test_an_excess_refund_is_verified_against_what_was_sent(self):
        self.make_rule()
        self.world.hold_broadcast = True
        self.run_rules()
        self.world.fee_bps = 80
        self.world.mine_held()
        self.mirror_chain()
        self.bridges()
        self.world.relay_refunds()
        self.workers()
        self.assertEqual(self.payout().status, 'refunded')

    def test_a_hash_that_funded_another_bridge_never_funds_this_one(self):
        self.make_rule()
        self.send_run()
        tx_hash = self.last_run().tx_hash
        mine = self.bridge()
        flow = MoneyFlow.objects.create(confio_account=self.personal, kind='withdraw', source_asset='USDT_BSC',
                                        source_amount=1, target_asset='USDC_POL')
        quote = type(mine.quote).objects.create(
            confio_account=self.personal, request_id=uuid.uuid4(), money_flow=flow,
            funding_instruction=self.instruction, source_address=self.wallet,
            destination_address=w.OWNER_INFINIA, amount_units='1', routes=[], expires_at=timezone.now())
        PaymentBridgeTransfer.objects.create(
            quote=quote, deposit_address='0x' + '77' * 20, amount_out='1', amount_out_min='1', deadline=1,
            status='failed', source_tx_hash=tx_hash)
        self.bridges()
        self.assertEqual((self.bridge().failure_code, self.bridge().source_tx_hash), ('funding_hash_claimed', ''))
        self.assertEqual(self.world.payouts, [])

    def test_a_second_reported_hash_never_replaces_the_first(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        proven = self.bridge().source_tx_hash
        self.step(contract_funding.report_funding, self.bridge().pk, '0x' + '9c' * 32)
        self.step(contract_funding.report_funding, self.bridge().pk, proven)
        self.assertEqual(self.bridge().source_tx_hash, proven)
        self.assertIn('segundo financiamiento', self.alert_text())
        self.assertEqual(self.to_paid().status, 'paid')
        self.assertEqual(len(self.world.payouts), 1)

    def test_an_unfinal_receipt_waits(self):
        self.make_rule()
        self.send_run()
        receipt = self.world.mined['BSC'][self.last_run().tx_hash]
        mined, receipt['blockNumber'] = receipt['blockNumber'], hex(self.world.head['BSC'] + 5)
        self.bridges()
        self.assertEqual((self.bridge().status, self.bridge().source_tx_hash), ('submitted', ''))
        receipt['blockNumber'] = mined
        self.bridges()
        self.assertEqual(self.bridge().source_tx_hash, self.last_run().tx_hash)

    def test_nothing_is_proven_without_a_reported_hash(self):
        self.make_rule()
        self.assertEqual(self.run_rules()['sent'], 1)       # mined, and not reported
        self.bridges()
        self.assertEqual(self.bridge().source_tx_hash, '')
        # tearDown fails on any USDT eth_getLogs: no scan stood in for the report.


class SingleUseAddressTests(InfiniaPayoutCase):
    """A single-use address fills its first deposit, whoever sent it and
    whatever the amount, and refunds every later one."""
    REFUND_REQUEST = '0x' + '5e' * 32

    def front_run(self, amount):
        self.make_rule()
        self.world.hold_broadcast = True
        self.assertEqual(self.run_rules()['sent'], 1)
        order = self.world.orders[-1]
        amount = order['amount'] if amount == 'exactly' else amount
        theirs = self.world.stranger_pays(order['deposit'], amount)
        self.world.mine_held()
        self.mirror_chain()
        self.bridges()
        ours = self.last_run().tx_hash
        self.assertEqual(self.bridge().source_tx_hash, ours)      # the vault's transfer, never theirs
        return order, theirs, ours

    def assert_theirs_never_counts_and_ours_comes_back(self, amount, child=False, destination_chain=137):
        order, theirs, ours = self.front_run(amount)
        fill, units = self.world.relay_fills(order, deposit_tx=theirs)
        self.credit_usdc(fill, units)       # it even reaches the owner's Infinia account
        self.workers()
        bridge = self.bridge()
        self.assertEqual((bridge.status, bridge.provider_credit_id, bridge.destination_tx_hash),
                         ('bridging', None, ''))
        self.assertIsNone(self.journey().funding_credit_id)
        self.assertEqual((self.world.transfers, self.world.payouts), ([], []))

        back = self.world.relay_refunds(order, deposit_tx=ours, request_id=self.REFUND_REQUEST, child=child,
                                        destination_chain=destination_chain)
        self.workers()
        bridge = self.bridge()
        evidence = bridge.binding['settlement_evidence']
        self.assertEqual((bridge.status, evidence['recipient'], evidence['received_units'], evidence['request_id']),
                         ('refunded', self.contract, str(back), self.REFUND_REQUEST))
        self.assertEqual((self.payout().status, self.journey().stage), ('refunded', 'failed'))
        for _ in range(3):
            self.run_rules()
            self.mirror_chain()
            self.workers()
        self.assertEqual((self.world.transfers, self.world.payouts, len(self.world.signed)), ([], [], 1))
        self.assertIsNone(self.bridge().provider_credit_id)
        self.assertEqual(PaymentBridgeTransfer.objects.count(), 1)

    def test_dust_first(self):
        self.assert_theirs_never_counts_and_ours_comes_back(3 * 10 ** 18)

    def test_a_first_deposit_of_exactly_our_amount(self):
        self.assert_theirs_never_counts_and_ours_comes_back('exactly')

    def test_a_refund_request_found_only_by_our_hash(self):
        self.assert_theirs_never_counts_and_ours_comes_back(3 * 10 ** 18, child=True)

    def test_a_refund_request_that_never_left_the_origin_chain(self):
        self.assert_theirs_never_counts_and_ours_comes_back(3 * 10 ** 18, destination_chain=56)

    def test_our_hash_on_another_address_is_not_our_request(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        order = dict(self.world.orders[-1], deposit='0x' + '67' * 20)
        self.world.settle(order, self.last_run().tx_hash, '0x' + '6a' * 32, {'status': 'success'})
        self.workers()
        self.assertEqual((self.bridge().status, self.world.payouts), ('bridging', []))

    def test_a_regenerated_request_is_followed_while_the_quotes_stays_waiting(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        order, regenerated = self.world.orders[-1], '0x' + '7e' * 32
        fill, units = self.world.relay_fills(order, request_id=regenerated)
        self.assertEqual(order['status']['status'], 'waiting')
        self.bridges()
        self.assertEqual(self.bridge().status, 'delivered')     # at once, not in review after an hour
        self.assertEqual(self.bridge().binding['settlement_evidence']['request_id'], regenerated)
        self.credit_usdc(fill, units)
        self.bridges()
        self.journeys()
        self.credit_conversion()
        self.journeys()
        self.workers()
        self.assertEqual((self.payout().status, len(self.world.payouts)), ('paid', 1))

    def test_a_deposit_relay_never_binds_is_not_settled_by_amount(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.world.publish_deposit_hash = False
        self.world.relay_fills()
        self.workers()
        self.assertEqual(self.bridge().status, 'bridging')
        self.age(4300)
        self.workers()
        self.assertEqual((self.bridge().failure_code, self.payout().status), ('relay_settlement_delayed', 'review'))
        self.assertEqual(self.world.payouts, [])
        self.assertIn('en revisión', self.alert_text())

    def test_manual_refund_required_reaches_review_with_an_alert(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.world.relay_fails('MANUAL_REFUND_REQUIRED')
        self.workers()
        self.assertEqual((self.bridge().status, self.bridge().failure_code),
                         ('needs_review', 'relay_refund_failed_manual_refund_required'))
        self.assertEqual((self.journey().stage, self.payout().status), ('needs_review', 'review'))
        self.assertIn('no devolverá solo', self.alert_text())
        self.assertEqual(self.world.payouts, [])
        # Refunded by hand later: recognised from the receipts.
        self.world.relay_refunds()
        self.workers()
        self.assertEqual(self.payout().status, 'refunded')

    def test_a_failure_relay_may_still_retry_is_not_review_yet(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.world.relay_fails()
        self.workers()
        self.assertEqual((self.bridge().status, self.journey().stage), ('bridging', 'awaiting_credit'))
        self.assertEqual(self.to_paid().status, 'paid')


class AfterConversionTests(InfiniaPayoutCase):
    def funded(self):
        self.make_rule()
        self.send_run()
        self.deliver()

    def test_fx_out_of_bounds_after_delivery_keeps_the_usdc_and_alerts(self):
        self.funded()
        self.world.rates['MXN'] = Decimal('15.00')
        self.journeys()
        self.mirror()
        self.assertEqual(self.payout().status, 'funded')        # waits for the rate, for a while
        self.advance(contract_funding.RATE_WAIT_SECONDS + 1)
        self.journeys()
        self.mirror()
        self.assertEqual((self.journey().failure_code, self.payout().status),
                         ('fx_quote_outside_authorization', 'review'))
        self.assertEqual((self.world.transfers, self.world.payouts), ([], []))
        self.assertIsNotNone(self.bridge().provider_credit_id)
        self.assertIn('en USDC en la cuenta Infinia del dueño', self.alert_text())

    def test_a_refused_payout_keeps_the_pesos_and_alerts(self):
        self.funded()
        self.journeys()
        self.world.payout_answer = 'REFUSED'
        self.credit_conversion()
        for _ in range(3):
            self.journeys()
            self.mirror()
        self.assertEqual((self.journey().stage, self.payout().status), ('needs_review', 'review'))
        self.assertEqual(self.journey().payout_operation.status, 'failed')
        self.assertIn('en la cuenta local', self.alert_text())
        self.assertEqual(self.world.count('infinia', 'POST /v2/payouts/'), 1)     # never paid again by itself

    def test_a_payout_returned_after_it_was_paid_goes_to_review(self):
        self.funded()
        self.journeys()
        self.credit_conversion()
        with mock.patch('smart_account.notifications.payout_delivered') as delivered:
            self.journeys()
            self.workers()
            self.assertEqual(self.payout().status, 'paid')
            sent = self.world.payouts[-1]
            self.webhook({'id': uuid.uuid4().hex, 'account_id': self.local.provider_account_id,
                          'amount': str(sent['amount']), 'created_at': timezone.now().isoformat(),
                          'operation': {'type': 'PAYOUT_REFUND', 'operation_id': sent['id']}})
            self.workers()
        self.assertEqual(self.payout().status, 'review')
        delivered.assert_called_once()
        self.assertIn('en revisión', self.alert_text())
        self.assertEqual(len(self.world.payouts), 1)

    def test_a_short_delivery_goes_to_review(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.world.relay_fills(out=self.world.orders[-1]['minimum'] - 1)
        self.workers()
        self.assertEqual((self.bridge().failure_code, self.payout().status), ('destination_amount_mismatch', 'review'))
        self.assertEqual(self.world.payouts, [])

    def test_a_partial_refund_is_not_called_refunded(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.world.relay_refunds(kept=5 * w.WAD)
        self.workers()
        self.assertEqual((self.bridge().failure_code, self.payout().status), ('relay_refund_amount_mismatch', 'review'))

    def test_a_refund_to_the_owners_wallet_is_not_this_bridges_refund(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.world.relay_refunds(to=self.wallet)
        self.workers()
        self.assertNotEqual(self.payout().status, 'refunded')

    def test_a_stalled_payout_alerts_with_where_the_money_is(self):
        self.funded()
        SmartAccountPayout.objects.update(created_at=timezone.now() - timedelta(hours=3))
        self.mirror()
        self.assertIn('detenido más de 2 horas', self.alert_text())
        self.assertIn('USDC', self.alert_text())

    def test_money_in_flight_is_mirrored_with_the_product_switched_off(self):
        self.funded()
        self.journeys()
        self.credit_conversion()
        self.journeys()
        self.journeys()
        with override_settings(SMART_ACCOUNT_ENABLED=False):
            self.step(tasks.reconcile_events)
        self.assertEqual(self.payout().status, 'paid')


class LimitsAtRunTests(InfiniaPayoutCase):
    def refused(self, code, out='skipped'):
        self.assertEqual(self.run_rules()[out], 1)
        self.assertEqual(self.last_run().error, code)
        self.assertEqual((PaymentBridgeTransfer.objects.count(), SmartAccountPayout.objects.count(),
                          self.world.signed), (0, 0, {}))

    def test_fx_under_the_signed_floor(self):
        self.make_rule()
        self.world.rates['MXN'] = Decimal('17.00')
        self.refused('fx_rate_below_limit', 'errors')      # today's rate: asked again inside the slot

    def test_the_fx_floor_signed_binds_the_journey(self):
        self.make_rule()
        self.world.rates['MXN'] = Decimal('18.00')          # inside the 3%, above its floor
        self.send_run()
        journey = self.journey()
        source = (Decimal(self.world.orders[-1]['minimum']) / 10 ** 6).quantize(Decimal('0.01'), 'ROUND_DOWN')
        self.assertGreaterEqual(journey.minimum_fx_output,
                                (source * Decimal('18.00') * Decimal('0.99')) - Decimal('0.02'))
        self.assertGreaterEqual(journey.minimum_fx_output,
                                (source * Decimal('18.50') * Decimal('0.97')) - Decimal('0.10'))

    def test_cost_over_the_signed_limit(self):
        self.make_rule()
        self.world.relay_fixed = Decimal('2')
        self.refused('bridge_cost_above_limit', 'errors')  # today's cost: asked again inside the slot

    def test_relay_says_too_small(self):
        self.make_rule()
        self.world.quote_error = (400, {'errorCode': 'AMOUNT_TOO_LOW'})
        self.refused('amount_too_small')

    def test_relay_outage_waits_untold_then_sends(self):
        self.make_rule()
        self.world.quote_error = (503, {'message': 'down'})
        with mock.patch('smart_account.notifications.rule_run') as told:
            self.refused('bridge_unavailable', 'waiting')
        told.assert_not_called()
        self.world.quote_error = None
        self.send_run()

    def test_fx_outage_waits(self):
        self.make_rule()
        self.world.fx_error = (503, {'message': 'down'})
        self.refused('fx_unavailable', 'waiting')

    def test_fx_refusal_is_final(self):
        self.make_rule()
        self.world.fx_error = (400, {'message': 'below minimum'})
        self.refused('fx_quote_refused')

    def test_banned_since_signing(self):
        self.make_rule()
        with mock.patch('security.utils.check_user_banned', return_value=(True, 'test')):
            self.refused('account_suspended', 'waiting')     # a ban may be lifted

    def test_known_minor(self):
        self.make_rule()
        with mock.patch('security.minors.is_known_minor', return_value=True):
            self.refused('minor')

    def test_identity_hold(self):
        self.make_rule()
        with mock.patch('security.identity_reuse.outgoing_identity_restriction', return_value='held'):
            self.refused('identity_hold', 'waiting')

    def test_eligibility_changed(self):
        from payment_accounts.models import EligibilityPolicy
        self.make_rule()
        EligibilityPolicy.objects.filter(provider='infinia', scope='payout', is_active=True).update(
            default_decision='block')
        self.refused('rail_not_eligible')

    def test_region_not_served(self):
        self.make_rule()
        with mock.patch('payment_accounts.local_money.region_unsupported', return_value=True):
            self.refused('region_not_supported')

    def test_capability_withdrawn(self):
        from payment_accounts.models import AccountCapability
        self.make_rule()
        AccountCapability.objects.filter(financial_account=self.local, capability='send_third_party').update(
            status='disabled')
        self.refused('account_not_able')

    @override_settings(PAYMENT_BRIDGE_MAX_USDT='20')
    def test_the_bridge_cap_applies(self):
        with override_settings(PAYMENT_BRIDGE_MAX_USDT=''):
            self.make_rule()
        self.refused('limit_exceeded')

    def test_a_rule_signed_again_mid_pass_waits(self):
        rule = self.make_rule()
        run = SmartAccountRuleRun.objects.create(rule=rule, scheduled_for=rule.scheduled_for)
        newer = SmartAccountStandingAuthorization.objects.get()
        newer.pk, newer.internal_id = None, uuid.uuid4()
        newer.max_bridge_cost_bps = 10
        newer.save()
        SmartAccountRule.objects.update(standing_authorization=newer)
        with self.assertRaises(payouts.PayoutSkip) as raised:
            infinia_payouts.open_run(rule, run)      # `rule` still holds the old limits
        self.assertEqual((raised.exception.code, raised.exception.wait), ('authorization_changed', True))
        self.assertFalse(PaymentBridgeTransfer.objects.exists())

    def test_revoked_authorization(self):
        self.make_rule()
        SmartAccountStandingAuthorization.objects.update(revoked_at=timezone.now())
        self.refused('no_standing_authorization')
        self.assertFalse(SmartAccountRule.objects.get().active)

    def test_authorization_of_another_user(self):
        self.make_rule()
        other = type(self.user).objects.create_user(username='other', password='x', firebase_uid='uid-other')
        SmartAccountStandingAuthorization.objects.update(user=other)
        self.refused('no_standing_authorization')

    def test_edited_destination(self):
        self.make_rule()
        self.destination.details = dict(self.destination.details, clabe='012180000000001234')
        self.destination.save()
        self.refused('destination_changed')

    def test_another_holder_on_the_same_key(self):
        self.destination.holder_name = 'Ana Prueba'
        self.destination.provider_data['validation'] = {
            'id': 'v1', 'status': 'SUCCESSFUL', 'holder_name': 'Ana Prueba', 'checked_at': timezone.now().isoformat()}
        self.destination.save()
        self.make_rule()
        self.destination.refresh_from_db()
        self.destination.holder_name = 'Otra Persona'
        self.destination.provider_data['validation'].update(holder_name='Otra Persona')
        self.destination.save()
        self.refused('destination_changed')

    def test_a_stale_verified_holder_is_checked_again(self):
        self.destination.holder_name = 'Ana Prueba'
        self.destination.provider_data['validation'] = {
            'id': 'v1', 'status': 'SUCCESSFUL', 'holder_name': 'Ana Prueba', 'checked_at': timezone.now().isoformat()}
        self.destination.save()
        self.make_rule()
        self.destination.refresh_from_db()
        self.destination.provider_data['validation']['checked_at'] = (timezone.now() - timedelta(days=30)).isoformat()
        self.destination.save()
        answers = [{'id': '', 'status': 'TEMPORARY_FAILURE', 'holder_name': '', 'checked_at': timezone.now().isoformat()},
                   {'id': 'v2', 'status': 'SUCCESSFUL', 'holder_name': 'Ana Prueba',
                    'checked_at': timezone.now().isoformat()}]
        with override_settings(INFINIA_ACCOUNT_VALIDATION_ENABLED=True), \
                mock.patch('payment_accounts.local_money._validate', side_effect=answers):
            self.refused('holder_check_pending', 'waiting')
            self.send_run()

    def test_a_mirror_behind_an_update_waits(self):
        self.make_rule()
        self.world.rules[(self.contract, 1)]['amount_usd_wei'] = 500 * w.WAD
        self.refused('rule_mirror_behind', 'waiting')

    def test_a_reused_deposit_address_is_refused_and_alerted(self):
        self.make_rule()
        used = '0x' + '66' * 20
        self.world.same_deposit = used
        flow = MoneyFlow.objects.create(confio_account=self.personal, kind='withdraw', source_asset='USDT_BSC',
                                        source_amount=1, target_asset='USDC_POL')
        from payment_accounts.models import PaymentBridgeQuote
        quote = PaymentBridgeQuote.objects.create(
            confio_account=self.personal, request_id=uuid.uuid4(), money_flow=flow,
            funding_instruction=self.instruction, source_address=self.contract,
            destination_address=w.OWNER_INFINIA, amount_units='1', routes=[], expires_at=timezone.now())
        PaymentBridgeTransfer.objects.create(quote=quote, deposit_address=used, amount_out='1', amount_out_min='1',
                                             deadline=1, status='expired')
        self.assertEqual(self.run_rules()['waiting'], 1)
        self.assertEqual((self.last_run().error, SmartAccountPayout.objects.count(), self.world.signed),
                         ('deposit_address_reused', 0, {}))
        self.assertIn('ya usada', self.alert_text())

    def test_a_used_relay_request_is_not_funded(self):
        self.make_rule()
        original = self.world.relay_quote

        def used(body):
            response = original(body)
            self.world.orders[-1]['status'] = {'status': 'depositing', 'inTxHashes': ['0x' + 'ee' * 32]}
            return response
        self.world.relay_quote = used
        self.refused('deposit_not_unused', 'waiting')


class TwoWorkersTests(InfiniaPayoutCase):
    def test_two_workers_on_one_slot_make_one_order(self):
        self.make_rule()
        run = SmartAccountRuleRun.objects.create(rule=self.rule, scheduled_for=self.rule.scheduled_for)
        real, other = contract_funding.require_unused, []

        def second_worker_first(priced):
            real(priced)
            if not other:
                other.append(None)
                other.append(self.step(infinia_payouts.open_run, self.rule, run))
        with mock.patch('payment_accounts.contract_funding.require_unused', side_effect=second_worker_first):
            with self.assertRaises(payouts.PayoutSkip) as raised:
                infinia_payouts.open_run(self.rule, run)
        self.assertTrue(raised.exception.wait)
        self.assertEqual((PaymentBridgeTransfer.objects.count(), InfiniaJourney.objects.count(),
                          SmartAccountPayout.objects.count()), (1, 1, 1))
        self.assertEqual(self.payout().deposit_address, other[1].deposit_address)
        # The retry is that same order.
        self.assertEqual(infinia_payouts.open_run(self.rule, run).deposit_address, other[1].deposit_address)


class OwnerSendTests(InfiniaPayoutCase):
    def owner_journey(self, stage='converting', failure=''):
        flow = MoneyFlow.objects.create(
            confio_account=self.personal, kind='withdraw', source_asset='USDT_BSC', source_amount=Decimal('10'),
            target_asset='MXN', metadata={'orchestrator': 'infinia'})
        return InfiniaJourney.objects.create(
            money_flow=flow, confio_account=self.personal, request_id=uuid.uuid4(), direction='to_bank',
            local_account=self.local, crypto_account=self.crypto, minimum_fx_output=Decimal('1'),
            destination_snapshot={'country': 'MEX'}, wallet_address=self.wallet, stage=stage, failure_code=failure)

    def owner_bridge(self):
        """A send the owner is making right now, through the real manual path."""
        from payment_accounts.bridge import quote_provider_funding
        self.world.balances[(w.USDT, self.wallet)] = 100 * w.WAD
        quote = quote_provider_funding(confio_account=self.personal,
                                       funding_instruction_id=self.instruction.internal_id, amount='20',
                                       request_id=uuid.uuid4(), destination_id=self.destination.internal_id)
        return bridge_execution.prepare_bridge(self.personal, quote.internal_id)

    def test_the_rule_waits_untold_for_the_owners_journey_then_pays(self):
        self.make_rule()
        manual = self.owner_journey()
        with mock.patch('smart_account.notifications.rule_run') as told:
            for _ in range(3):
                self.assertEqual(self.run_rules()['waiting'], 1)
        told.assert_not_called()
        self.assertEqual((self.last_run().status, self.last_run().error), ('pending', 'account_busy'))
        InfiniaJourney.objects.filter(pk=manual.pk).update(stage='completed')
        self.send_run()
        self.assertEqual(self.to_paid().status, 'paid')

    def test_the_rule_waits_for_a_bridge_the_owner_just_prepared(self):
        self.make_rule()
        manual = self.owner_bridge()
        self.assertEqual(self.run_rules()['waiting'], 1)
        # And the owner's send goes through in front of it.
        journey = infinia_journeys.create_journey(
            owner=self.personal, local_account=self.local, crypto_account=self.crypto, request_id=uuid.uuid4(),
            minimum_fx_output='1', direction='to_bank', bridge=manual, destination=self.destination)
        self.assertEqual(journey.wallet_address, self.wallet)
        self.assertEqual(self.run_rules()['waiting'], 1)

    def test_an_expired_preparation_does_not_hold_the_rule(self):
        self.make_rule()
        manual = self.owner_bridge()
        PaymentBridgeTransfer.objects.filter(pk=manual.pk).update(deadline=1)
        self.send_run()

    def test_a_parked_review_does_not_hold_the_rule(self):
        self.make_rule()
        self.owner_journey('needs_review', 'bridge_not_delivered')
        self.send_run()

    def test_an_unresolved_provider_operation_holds_the_rule(self):
        self.make_rule()
        flow = MoneyFlow.objects.create(confio_account=self.personal, kind='withdraw', source_asset='USDC_POL',
                                        source_amount=1, target_asset='MXN')
        MoneyOperation.objects.create(money_flow=flow, provider='infinia', operation_type='conversion',
                                      source_account=self.crypto, source_asset='USDC_POL', source_amount=1,
                                      idempotency_key=uuid.uuid4().hex, status='unknown')
        self.assertEqual(self.run_rules()['waiting'], 1)

    def test_a_held_deposit_waits_before_converting_anything(self):
        self.make_rule()
        with mock.patch('payment_accounts.payin_admission.require_source_admitted',
                        side_effect=PaymentAccountError('review')):
            self.assertEqual(self.run_rules()['waiting'], 1)
        self.assertEqual(self.world.signed, {})

    def test_waiting_gives_up_after_a_day_and_the_next_date_stands(self):
        self.make_rule()
        self.owner_journey()
        with mock.patch.object(automation, 'RULE_SLOT_GIVE_UP', timedelta(0)), \
                mock.patch('smart_account.notifications.rule_run') as told:
            self.run_rules()
        told.assert_called_once()
        rule = SmartAccountRule.objects.get()
        self.assertTrue(rule.active)
        self.assertGreater(rule.scheduled_for, self.slot)

    def test_the_owner_sends_again_once_the_rule_settles(self):
        self.make_rule()
        self.send_run()
        manual = self.owner_bridge()        # the wallet itself is never held by the contract's bridge
        with self.assertRaisesRegex(PaymentAccountError, 'en curso'):
            infinia_journeys.create_journey(
                owner=self.personal, local_account=self.local, crypto_account=self.crypto, request_id=uuid.uuid4(),
                minimum_fx_output='1', direction='to_bank', bridge=manual, destination=self.destination)
        self.to_paid()
        self.assertTrue(infinia_journeys.create_journey(
            owner=self.personal, local_account=self.local, crypto_account=self.crypto, request_id=uuid.uuid4(),
            minimum_fx_output='1', direction='to_bank', bridge=manual, destination=self.destination))

    def test_a_lost_race_for_the_accounts_writes_nothing(self):
        self.make_rule()
        real = contract_funding.require_unused

        def race(priced):
            real(priced)
            self.owner_journey()
        with mock.patch('payment_accounts.contract_funding.require_unused', side_effect=race):
            self.assertEqual(self.run_rules()['waiting'], 1)
        self.assertEqual((PaymentBridgeTransfer.objects.count(), SmartAccountPayout.objects.count()), (0, 0))


class OwnerMutationTests(InfiniaPayoutCase):
    def setUp(self):
        super().setUp()
        self.make_rule()
        self.send_run()

    def test_quote_prepare_submit_and_journey_mutations_refuse(self):
        from payment_accounts import schema
        from payment_accounts.journey_schema import CreateInfiniaJourney
        bridge, journey = self.bridge(), self.journey()
        before = (bridge.status, bridge.source_tx_hash, journey.stage)
        refusal = [contract_funding.OWNER_REFUSAL]
        result = schema.QuotePaymentBridge.mutate(
            None, self.info(), self.instruction.internal_id, Decimal(self.amount), bridge.quote.request_id,
            destination_id=self.destination.internal_id)
        self.assertEqual((result.success, result.errors), (False, refusal))
        result = schema.PreparePaymentBridge.mutate(None, self.info(), bridge.quote.internal_id)
        self.assertEqual((result.success, result.errors), (False, refusal))
        result = schema.SubmitPaymentBridge.mutate(None, self.info(), bridge.internal_id, '0x' + '00' * 65)
        self.assertEqual((result.success, result.errors), (False, refusal))
        for request_id in (journey.request_id, uuid.uuid4()):
            result = CreateInfiniaJourney.mutate(
                None, self.info(), local_account_id=self.local.internal_id, crypto_account_id=self.crypto.internal_id,
                bridge_id=bridge.internal_id, destination_id=self.destination.internal_id, direction='to_bank',
                request_id=request_id, minimum_fx_output=Decimal('1'))
            self.assertEqual((result.success, result.errors), (False, refusal))
        with self.assertRaises(PaymentAccountError):
            infinia_journeys.attach_return_bridge(owner=self.personal, journey_id=journey.internal_id, bridge=bridge)
        self.assertEqual((self.bridge().status, self.bridge().source_tx_hash, self.journey().stage), before)
        self.assertEqual(InfiniaJourney.objects.count(), 1)

    def test_cobre_cannot_take_the_bridge_either(self):
        from payment_accounts import cobre_journeys
        with override_settings(COBRE_JOURNEYS_ENABLED=True, COBRE_PAYMENT_ACCOUNTS_ENABLED=True), \
                self.assertRaises(PaymentAccountError):
            cobre_journeys.create_journey(
                owner=self.personal, local_account=self.local, crypto_account=self.crypto, copco_account=self.local,
                request_id=uuid.uuid4(), minimum_fx_output='1', direction='to_bank', bridge=self.bridge(),
                destination=self.destination)

    def test_a_changed_owner_wallet_does_not_stop_the_journey(self):
        # The money left the immutable contract: the wallet pinned is its own.
        type(self.personal).objects.filter(pk=self.personal.pk).update(bsc_address='0x' + '88' * 20)
        self.assertEqual(self.to_paid().status, 'paid')

    def test_no_mutation_takes_a_funding_argument(self):
        from payment_accounts.journey_schema import CreateInfiniaJourney
        self.assertNotIn('funding', CreateInfiniaJourney._meta.arguments)

    def test_only_an_issued_object_is_authority(self):
        with self.assertRaises(TypeError):
            contract_funding.ContractFunding(self.last_run().pk)
        bridge = self.bridge()
        for forged in (True, {'run': self.last_run().pk}, mock.Mock(), 'contract'):
            with self.assertRaises(PaymentAccountError):
                contract_funding.authorize_journey(forged, owner=self.personal, destination=self.destination,
                                                   bridge=bridge, local_account=self.local)

    def test_authority_is_bound_to_the_exact_bridge_destination_and_amount(self):
        with self.assertRaises(contract_funding.Refused):
            contract_funding.ContractFunding.for_run(self.last_run().pk)    # a run already sent is no authority
        run = self.last_run()
        SmartAccountRuleRun.objects.update(status='failed')
        SmartAccountRule.objects.update(scheduled_for=run.scheduled_for)
        bridge = self.bridge()
        funding = contract_funding.ContractFunding.for_run(self.last_run().pk)
        for key, value in (('units', '1'), ('amount', '99.00'), ('destination', str(uuid.uuid4())),
                           ('run', 987654), ('authorization', str(uuid.uuid4())), ('contract', self.wallet)):
            changed = self.bridge()
            flow = changed.quote.money_flow
            flow.metadata = dict(flow.metadata, contract_funding=dict(flow.metadata['contract_funding'], **{key: value}))
            changed.source_tx_hash = ''
            with self.assertRaises(PaymentAccountError, msg=key):
                contract_funding.authorize_journey(funding, owner=self.personal, destination=self.destination,
                                                   bridge=changed, local_account=self.local)
        self.assertEqual(bridge.funding_mode, 'contract')

    def test_the_apps_see_nothing_to_sign(self):
        from payment_accounts.journey_schema import InfiniaJourneyType
        from payment_accounts.schema import PaymentBridgeTransferType
        journey = self.journey()
        self.assertNotEqual(InfiniaJourneyType.resolve_bridge_status(journey, self.info()), 'prepared')
        self.assertEqual(PaymentBridgeTransferType.resolve_calls(self.bridge(), self.info()), [])
        self.assertEqual(PaymentBridgeTransferType.resolve_fee_units(self.bridge(), self.info()), '0')


@override_settings(INFINIA_PASS_THROUGH_FEE_COUNTRIES='MX')
class ProcessorFeeTests(InfiniaPayoutCase):
    def test_the_fee_becomes_the_carry_forward_debt_once(self):
        from payment_accounts.infinia_fee_debt import quoted
        batch = self.prepare()
        self.assertTrue(any('US$0.50 por pago' in line for line in batch.summary), batch.summary)
        self.assertTrue(any('próxima' in line for line in batch.summary), batch.summary)
        SmartAccountRule.all_objects.all().delete()
        self.make_rule()
        self.send_run()
        self.assertFalse(InfiniaFeeDebt.objects.exists())
        self.assertEqual(self.to_paid().status, 'paid')
        self.mirror()
        debt = InfiniaFeeDebt.objects.get()
        self.assertEqual((debt.amount_usd, debt.source_flow_id), (Decimal('0.50'), self.bridge().quote.money_flow_id))
        self.assertEqual(quoted(self.personal), ([debt.pk], Decimal('0.50')))
        # The run itself never claimed to have collected it in a batch.
        self.assertNotIn('infinia_fee', self.journey().money_flow.metadata)

    def test_an_older_debt_is_not_charged_to_a_run(self):
        flow = MoneyFlow.objects.create(confio_account=self.personal, kind='withdraw', source_asset='USDT_BSC',
                                        source_amount=1, target_asset='MXN')
        old = InfiniaFeeDebt.objects.create(source_flow=flow, amount_usd=Decimal('3'))
        self.make_rule()
        self.send_run()
        old.refresh_from_db()
        self.assertIsNone(old.reserved_flow_id)
        self.assertEqual(self.bridge().quote.money_flow.metadata['contract_funding']['fee']['total_usd'], '0.500000')

    def test_no_debt_for_a_refunded_run(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.world.relay_refunds()
        self.workers()
        self.assertFalse(InfiniaFeeDebt.objects.exists())
