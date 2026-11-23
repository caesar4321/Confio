"""Sending and closing an automatic payment's order exclude each other, with
two real database connections really waiting on each other's locks.
Fake values only."""
import threading
import time
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from payment_accounts import contract_funding
from payment_accounts.models import PaymentBridgeTransfer
from ramps import ve_send
from ramps.models import RampTransaction
from smart_account import abi, automation, relayer
from smart_account.models import (
    SmartAccount, SmartAccountPayout, SmartAccountRelayTx, SmartAccountRule, SmartAccountRuleRun,
    SmartAccountStandingAuthorization,
)

from .base import SETTINGS as BASE_SETTINGS
from .base import own_nonce_lock
from .infinia_base import SETTINGS, InfiniaPayoutSteps

PATIENCE = 20
STILL_WAITING = 0.8


class Worker(threading.Thread):
    """One worker with its own database connection."""

    def __init__(self, fn, *args):
        super().__init__(daemon=True)
        self.fn, self.args = fn, args
        self.result = self.error = None
        self.start()

    def run(self):
        try:
            self.result = self.fn(*self.args)
        except BaseException as exc:    # noqa: BLE001 — raised in the test's thread
            self.error = exc
        finally:
            connection.close()

    def done(self):
        self.join(PATIENCE)
        assert not self.is_alive(), 'the worker never finished (deadlock?)'
        if self.error is not None:
            raise self.error
        return self.result


class Paused:
    """Holds the first caller just after `real` returned, its locks held."""

    def __init__(self, real):
        self.real, self.inside, self.release = real, threading.Event(), threading.Event()
        self._first = threading.Lock()

    def __call__(self, *args, **kwargs):
        result = self.real(*args, **kwargs)
        if self._first.acquire(blocking=False):
            self.inside.set()
            assert self.release.wait(PATIENCE), 'never released'
        return result


class Waits:
    def paused(self, real):
        paused = Paused(real)
        self.addCleanup(paused.release.set)     # a failed test never leaves a thread holding locks
        return paused

    def assert_waits(self, worker):
        worker.join(STILL_WAITING)
        self.assertTrue(worker.is_alive(), f'did not wait for the lock: {worker.result!r} {worker.error!r}')


@override_settings(**SETTINGS)
class InfiniaSendOrCloseTests(Waits, InfiniaPayoutSteps, TransactionTestCase):
    def step(self, fn, *args, **kwargs):
        cache.clear()       # no test transaction: callbacks run at each commit
        return fn(*args, **kwargs)

    def open_order(self):
        self.make_rule()
        self.leave_order_open()
        self.assertEqual(self.bridge().status, 'submitted')

    def broadcasts(self):
        return self.world.count('BSC', 'eth_sendRawTransaction')

    def test_a_sender_holding_the_order_makes_the_closer_refuse(self):
        self.open_order()
        bridge = self.bridge().pk
        paused = self.paused(contract_funding.lock_fundable)
        with mock.patch('payment_accounts.contract_funding.lock_fundable', side_effect=paused):
            sender = Worker(automation.run_rules)
            self.assertTrue(paused.inside.wait(PATIENCE), sender.error)
            closer = Worker(contract_funding.close_unfunded, bridge)
            self.assert_waits(closer)
            paused.release.set()
            self.assertEqual(sender.done()['sent'], 1)
            self.assertFalse(closer.done())
        self.assertEqual((self.bridge().status, self.journey().stage), ('submitted', 'awaiting_credit'))
        self.assertEqual((self.last_run().status, self.broadcasts()), ('sent', 1))
        self.mirror_chain()
        self.assertEqual(self.to_paid().status, 'paid')

    def test_a_closer_holding_the_order_makes_the_sender_broadcast_nothing(self):
        self.open_order()
        bridge = self.bridge().pk
        paused = self.paused(contract_funding._set_flow)
        with mock.patch('payment_accounts.contract_funding._set_flow', side_effect=paused):
            closer = Worker(contract_funding.close_unfunded, bridge)
            self.assertTrue(paused.inside.wait(PATIENCE), closer.error)
            sender = Worker(automation.run_rules)
            self.assert_waits(sender)
            paused.release.set()
            self.assertTrue(closer.done())
            self.assertEqual(sender.done()['waiting'], 1)
        self.assertEqual(self.broadcasts(), 0)
        self.assertFalse(SmartAccountRelayTx.objects.exists())
        self.assertEqual(self.last_run().error, 'order_closed')
        # Closed and unfunded: the slot's next pass makes a fresh one and pays.
        self.assertEqual(self.run_rules()['sent'], 1)
        self.assertEqual(PaymentBridgeTransfer.objects.filter(funding_mode='contract').count(), 2)
        self.assertEqual(self.broadcasts(), 1)

    def test_two_overlapping_run_rules_broadcast_one_call(self):
        self.open_order()
        paused = self.paused(contract_funding.lock_fundable)
        with mock.patch('payment_accounts.contract_funding.lock_fundable', side_effect=paused):
            first = Worker(automation.run_rules)
            self.assertTrue(paused.inside.wait(PATIENCE), first.error)
            second = Worker(automation.run_rules)
            self.assert_waits(second)
            paused.release.set()
            self.assertEqual(first.done()['sent'], 1)
            self.assertEqual(second.done()['sent'], 0)
        self.assertEqual((self.broadcasts(), SmartAccountRelayTx.objects.count()), (1, 1))
        self.assertEqual((self.last_run().status, self.bridge().status), ('sent', 'submitted'))

    def test_a_stale_finisher_waits_and_writes_nothing_over_a_send(self):
        self.open_order()
        rule, run = SmartAccountRule.objects.get(), self.last_run()
        paused = self.paused(contract_funding.lock_fundable)
        with mock.patch('payment_accounts.contract_funding.lock_fundable', side_effect=paused), \
                mock.patch('smart_account.notifications.rule_run') as told:
            sender = Worker(automation.run_rules)
            self.assertTrue(paused.inside.wait(PATIENCE), sender.error)
            finisher = Worker(lambda: automation._finish_run(rule, run, 'skipped', 'no', 'stale', final=True))
            self.assert_waits(finisher)
            paused.release.set()
            self.assertEqual(sender.done()['sent'], 1)
            finisher.done()
        told.assert_not_called()
        self.assertEqual((self.last_run().status, self.bridge().status), ('sent', 'submitted'))
        self.assertEqual(SmartAccountRule.objects.get().scheduled_for, self.slot)

    def test_a_finisher_first_means_the_sender_broadcasts_nothing(self):
        self.open_order()
        rule, run = SmartAccountRule.objects.get(), self.last_run()
        paused = self.paused(automation.schedule_next)
        with mock.patch('smart_account.automation.schedule_next', side_effect=paused), \
                mock.patch('smart_account.notifications.rule_run'):
            finisher = Worker(lambda: automation._finish_run(rule, run, 'skipped', 'no', 'limit', final=True))
            self.assertTrue(paused.inside.wait(PATIENCE), finisher.error)
            sender = Worker(automation.run_rules)
            self.assert_waits(sender)
            paused.release.set()
            finisher.done()
            self.assertEqual(sender.done()['sent'], 0)
        self.assertEqual((self.broadcasts(), self.bridge().status), (0, 'expired'))


CONTRACT, DEPOSIT, VAULT = '0x' + '24' * 20, '0x' + 'de' * 20, '0x' + 'c1' * 20
UNITS = 99_100_000_000_000_000_000


@override_settings(**BASE_SETTINGS)
class PagoMovilSendOrCloseTests(Waits, TransactionTestCase):
    def setUp(self):
        from users.models import Account
        self.user = get_user_model().objects.create_user(username='payer', password='x', firebase_uid='uid-payer')
        wallet = '0x' + '13' * 20
        personal = Account.objects.create(user=self.user, account_type='personal', account_index=0,
                                          bsc_address=wallet)
        smart = Account.objects.create(user=self.user, account_type='smart', account_index=0, bsc_address=CONTRACT)
        self.account = SmartAccount.objects.create(
            owner_user=self.user, owner_account=personal, account=smart, contract_address=CONTRACT, status='active',
            plan='annual', paid_until=timezone.now() + timedelta(days=30))
        authorization = SmartAccountStandingAuthorization.objects.create(
            kind='payout', user=self.user, rail='ve_pagomovil', amount_usd=Decimal('100'), frequency='monthly',
            binding_hash='h', face_required=False)
        slot = timezone.now().replace(microsecond=0)
        self.rule = SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=1, state='onchain', active=True, kind='payout', token_in=VAULT,
            payout_ref='0x' + '71' * 32, payout_rail='ve_pagomovil', standing_authorization=authorization,
            amount=Decimal('100.00'), frequency='monthly', scheduled_for=slot, next_run_at=slot)
        self.slot_run = SmartAccountRuleRun.objects.create(rule=self.rule, scheduled_for=slot)
        ramp = RampTransaction(
            provider='pagoasap', direction='off_ramp', status='PENDING', country_code='VE', actor_user=self.user,
            actor_address=CONTRACT, destination='cusd_plus', fiat_currency='VES', crypto_currency='USDT',
            final_currency='USDT', metadata={ve_send.SECTION: {
                'phase': 'funding_reported', 'gross_usd': '100.00', 'deposit_wei': str(UNITS),
                'deposit_address': DEPOSIT, 'funding_sender': VAULT,
                'funding_started_at': timezone.now().isoformat(),
                'bridge': {'deadline': int(time.time()) + 600},
                'funding_terms': {'run': self.slot_run.pk, 'rule': str(self.rule.internal_id),
                                  'authorization': str(authorization.internal_id),
                                  'payout_ref': self.rule.payout_ref, 'amount': '100.00', 'rule_event': ''}}})
        ramp.external_id = str(ramp.internal_id)
        ramp.save()
        self.ramp = ramp
        SmartAccountPayout.objects.create(rule_run=self.slot_run, provider='pagoasap', rail='ve_pagomovil', ramp=ramp,
                                          deposit_address=DEPOSIT, status='prepared')
        self.sent = []

        def rpc(method, params):
            if method == 'eth_sendRawTransaction':
                self.sent.append(params[0])
                return '0x'
            return {'eth_gasPrice': hex(10 ** 8), 'eth_getTransactionCount': hex(7),
                    'eth_getBalance': hex(10 ** 18)}[method]
        signer = mock.Mock(address='0x' + '5a' * 20)
        signer.sign_typed_transaction.return_value = ('0xraw', '0x' + '9e' * 32)
        for patcher in (
                mock.patch('blockchain.evm_kms_signer.get_bsc_sponsor_signer_from_settings', return_value=signer),
                mock.patch('smart_account.chain.rpc', side_effect=rpc),
                mock.patch('smart_account.relayer.simulate'),
                mock.patch('smart_account.inflight.invalidate_address'),
                mock.patch('cusd_plus.sponsor_7702.acquire_sponsor_nonce_lock', side_effect=own_nonce_lock),
                mock.patch('cusd_plus.sponsor_7702.release_sponsor_nonce_lock'),
                mock.patch('smart_account.tasks.check_relay_tx.apply_async'),
                mock.patch('config.ops_alerts.send_ops_alert', return_value=True),
                mock.patch('notifications.utils.send_push_notification', return_value={'success': True})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def send(self):
        calldata = abi.encode_call('executeRule', 1, abi.payout_rule_data(DEPOSIT, UNITS), abi.ZERO_ADDRESS, 0)
        send = automation._Send(self.rule, self.slot_run, {}, calldata, 'Pago en camino.')
        source = f'rule:{self.rule.pk}:{int(self.slot_run.scheduled_for.timestamp())}'
        try:
            relayer.send_relayer_call(self.account, calldata, 'smart_execute_rule', source, claim=send.claim,
                                      gas=abi.RELAY_GAS_RULE['payout'])
        except relayer.RelayError as exc:
            return exc.code
        return 'sent'

    def test_a_sender_holding_the_order_makes_close_unsent_refuse(self):
        paused = self.paused(ve_send.lock_fundable)
        with mock.patch('ramps.ve_send.lock_fundable', side_effect=paused):
            sender = Worker(self.send)
            self.assertTrue(paused.inside.wait(PATIENCE), sender.error)
            closer = Worker(ve_send.close_unsent, self.ramp)
            self.assert_waits(closer)
            paused.release.set()
            self.assertEqual(sender.done(), 'sent')
            self.assertEqual(closer.done().status, 'PENDING')
        self.assertEqual(len(self.sent), 1)
        self.slot_run.refresh_from_db()
        self.assertEqual(self.slot_run.status, 'sent')

    def test_close_unsent_holding_the_order_makes_the_sender_broadcast_nothing(self):
        paused = self.paused(ve_send._may_land)
        with mock.patch('ramps.ve_send._may_land', side_effect=paused):
            closer = Worker(ve_send.close_unsent, self.ramp)
            self.assertTrue(paused.inside.wait(PATIENCE), closer.error)
            sender = Worker(self.send)
            self.assert_waits(sender)
            paused.release.set()
            self.assertEqual(closer.done().status_detail, 'payout_not_sent')
            self.assertEqual(sender.done(), 'order_closed')
        self.assertEqual(self.sent, [])
        self.assertFalse(SmartAccountRelayTx.objects.exists())

    def test_the_orders_own_expiry_never_closes_one_that_may_land(self):
        self.assertEqual(self.send(), 'sent')
        ramp = RampTransaction.objects.get(pk=self.ramp.pk)
        section = ramp.metadata[ve_send.SECTION]
        section['bridge']['deadline'] = int(time.time()) - 7200
        ramp.save(update_fields=['metadata'])
        self.assertEqual(ve_send.sync(ramp, rpc=mock.Mock()).status, 'PENDING')
