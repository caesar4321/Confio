from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from ramps import vexpay_offramp as off
from ramps.models import RampTransaction
from ramps.vexpay_client import VexPayAmbiguousError, VexPayError

WALLET = '0x' + '12' * 20
DEPOSIT = '0x' + 'de' * 20
OTHER = '0x' + '77' * 20
TX = '0x' + 'ab' * 32
TX2 = '0x' + 'cd' * 32
WEI = 19_820_000 * 10 ** 12  # 19.82 USDT
BENEFICIARY = {'cedula': 'V12345678', 'phone': '584141234567', 'bank_code': '0134', 'bank_name': 'Banesco'}

# Tests run with real AWS credentials: never reach the team's Telegram.
_ops_alert = mock.patch('config.ops_alerts.send_ops_alert', return_value=True)


def setUpModule():
    _ops_alert.start()


def tearDownModule():
    _ops_alert.stop()


def _topic(address):
    return '0x' + '0' * 24 + address[2:]


def transfer(amount_wei=WEI, sender=WALLET, to=DEPOSIT, tx=TX):
    return {'address': off.USDT_BSC, 'topics': [off.TRANSFER_TOPIC, _topic(sender), _topic(to)],
            'data': hex(amount_wei), 'logIndex': '0x1', 'transactionHash': tx}


def receipt(*logs, status='0x1'):
    return {'status': status, 'logs': list(logs) or [transfer()]}


class OffRampTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='vexpay-sender', firebase_uid='vexpay-sender')

    def _ramp(self, phase='funding_reported', status='PENDING', **section):
        values = {'phase': phase, 'gross_usd': '20.00', 'deposit_wei': str(WEI), 'gross_wei': str(20 * 10 ** 18),
                  'deposit_address': DEPOSIT, 'beneficiary': BENEFICIARY, 'estimated_ves': '19000.00',
                  'quoted_rate': '1007.5', 'created_block': 1000, 'credit_attempt': 0,
                  'funding_started_at': timezone.now().isoformat()}
        values.update(section)
        ramp = RampTransaction(provider='vexpay', direction='off_ramp', status=status, country_code='VE',
                               actor_user=self.user, actor_address=WALLET, destination='cusd_plus',
                               fiat_currency='VES', crypto_currency='USDT', final_currency='VES',
                               crypto_amount_estimated=Decimal('19.82'), metadata={'vexpay': values})
        ramp.external_id = str(ramp.internal_id)
        ramp.save()
        return ramp

    # ---- funding: one claim, proven on chain

    def test_funding_is_a_single_claim(self):
        ramp = self._ramp(phase='awaiting_funding', funding_started_at=None)
        self.assertTrue(off.can_fund(ramp))
        claimed = off.start_funding(ramp)
        self.assertEqual(off._phase(claimed), 'funding_reported')
        self.assertFalse(off.can_fund(claimed))
        with self.assertRaises(off.VexPayOffRampError):
            off.start_funding(claimed)

    def test_funding_window_closes(self):
        ramp = self._ramp(phase='awaiting_funding', funding_started_at=None)
        RampTransaction.objects.filter(pk=ramp.pk).update(created_at=timezone.now() - timedelta(hours=3))
        ramp.refresh_from_db()
        self.assertFalse(off.can_fund(ramp))
        ramp = off.sync_off_ramp(ramp, rpc=mock.Mock())
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', 'expired_unfunded'))

    def test_unclaimed_order_is_never_scanned(self):
        rpc = mock.Mock()
        off.sync_off_ramp(self._ramp(phase='awaiting_funding', funding_started_at=None), rpc=rpc)
        rpc.assert_not_called()

    def test_reported_hash_is_proven_by_exact_transfer(self):
        ramp = off.report_funding(self._ramp(), TX)
        ramp = off.sync_off_ramp(ramp, rpc=mock.Mock(return_value=receipt()))
        self.assertEqual((ramp.status, ramp.status_detail), ('PROCESSING', 'awaiting_conversion'))
        self.assertEqual(off._section(ramp)['funding_tx_hash'], TX)

    def test_wrong_amount_sender_or_recipient_is_not_funding(self):
        for log in (transfer(amount_wei=WEI - 1), transfer(sender=OTHER), transfer(to=OTHER)):
            ramp = off.report_funding(self._ramp(), TX)
            rpc = mock.Mock(side_effect=lambda method, params, log=log: (
                receipt(log) if method == 'eth_getTransactionReceipt' else ('0x3e8' if method == 'eth_blockNumber' else [])))
            ramp = off.sync_off_ramp(ramp, rpc=rpc)
            self.assertEqual(ramp.status, 'PENDING')

    def test_failed_receipt_is_not_funding(self):
        ramp = off.report_funding(self._ramp(), TX)
        rpc = mock.Mock(side_effect=lambda method, params: (
            receipt(status='0x0') if method == 'eth_getTransactionReceipt' else ('0x3e8' if method == 'eth_blockNumber' else [])))
        self.assertEqual(off.sync_off_ramp(ramp, rpc=rpc).status, 'PENDING')

    def test_lost_hash_is_found_by_its_log(self):
        ramp = self._ramp()

        def rpc(method, params):
            if method == 'eth_blockNumber':
                return hex(1500)
            if method == 'eth_getLogs':
                return [transfer()]
            raise AssertionError(method)
        ramp = off.sync_off_ramp(ramp, rpc=rpc)
        self.assertEqual(ramp.status_detail, 'awaiting_conversion')

    def test_one_transfer_funds_one_order(self):
        first = off.report_funding(self._ramp(), TX)
        off.sync_off_ramp(first, rpc=mock.Mock(return_value=receipt()))
        second = off.report_funding(self._ramp(), TX)
        rpc = mock.Mock(side_effect=lambda method, params: (
            receipt() if method == 'eth_getTransactionReceipt' else ('0x3e8' if method == 'eth_blockNumber' else [transfer()])))
        self.assertEqual(off.sync_off_ramp(second, rpc=rpc).status, 'PENDING')

    def test_rpc_outage_changes_nothing(self):
        ramp = off.report_funding(self._ramp(), TX)
        ramp = off.sync_off_ramp(ramp, rpc=mock.Mock(side_effect=RuntimeError('rpc down')))
        self.assertEqual((ramp.status, off._phase(ramp)), ('PENDING', 'funding_reported'))

    def test_claimed_but_never_sent_expires_then_late_funding_surfaces(self):
        started = (timezone.now() - timedelta(hours=7)).isoformat()
        ramp = self._ramp(funding_started_at=started)
        empty = mock.Mock(side_effect=lambda method, params: '0x3e8' if method == 'eth_blockNumber' else [])
        ramp = off.sync_off_ramp(ramp, rpc=empty)
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', 'expired_unfunded'))
        self.assertIn(ramp.pk, list(off.open_off_ramps().values_list('pk', flat=True)))
        found = mock.Mock(side_effect=lambda method, params: '0x3e8' if method == 'eth_blockNumber' else [transfer()])
        ramp = off.sync_off_ramp(ramp, rpc=found)
        self.assertEqual((ramp.status, ramp.status_detail), ('PROCESSING', 'needs_review:late_funding'))

    def test_reported_hash_never_proven_goes_to_review(self):
        started = (timezone.now() - timedelta(hours=7)).isoformat()
        ramp = off.report_funding(self._ramp(funding_started_at=started), TX)
        rpc = mock.Mock(side_effect=lambda method, params: (
            receipt(status='0x0') if method == 'eth_getTransactionReceipt' else ('0x3e8' if method == 'eth_blockNumber' else [])))
        ramp = off.sync_off_ramp(ramp, rpc=rpc)
        self.assertEqual((ramp.status, ramp.status_detail), ('PROCESSING', 'needs_review:funding_not_found'))

    # ---- cancel

    def test_cancel_before_claim(self):
        ramp = off.cancel_off_ramp(self._ramp(phase='awaiting_funding', funding_started_at=None), rpc=mock.Mock())
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', 'cancelled_by_user'))

    def test_claimed_order_cancels_only_after_quiet_and_clean_scan(self):
        ramp = self._ramp()
        with self.assertRaises(off.VexPayOffRampError):
            off.cancel_off_ramp(ramp, rpc=mock.Mock())
        quiet = self._ramp(funding_started_at=(timezone.now() - timedelta(minutes=20)).isoformat())
        found = mock.Mock(side_effect=lambda method, params: '0x3e8' if method == 'eth_blockNumber' else [transfer()])
        with self.assertRaises(off.VexPayOffRampError):
            off.cancel_off_ramp(quiet, rpc=found)
        self.assertEqual(RampTransaction.objects.get(pk=quiet.pk).status_detail, 'awaiting_conversion')

    def test_reported_hash_blocks_cancel(self):
        ramp = off.report_funding(self._ramp(funding_started_at=(timezone.now() - timedelta(hours=1)).isoformat()), TX)
        self.assertFalse(off.can_cancel(ramp))

    # ---- ops release and payout

    def _funded(self, **section):
        return self._ramp(phase='funded', status='PROCESSING', funding_tx_hash=TX, **section)

    def test_mark_converted_checks_the_figure(self):
        ramp = self._funded()
        with self.assertRaises(off.VexPayOffRampError):
            off.mark_converted(ramp, Decimal('5000'), operator='ops')
        ramp = off.mark_converted(ramp, Decimal('18750.50'), operator='ops')
        self.assertEqual((off._phase(ramp), ramp.fiat_amount), ('converted', Decimal('18750.50')))
        with self.assertRaises(off.VexPayOffRampError):
            off.mark_converted(ramp, Decimal('18750.50'), operator='ops')

    def _client(self, available='50000', credit=None):
        client = mock.Mock()
        client.balance.return_value = {'availableVes': available}
        if isinstance(credit, Exception):
            client.credit.side_effect = credit
        else:
            client.credit.return_value = credit or {'code': 'ACCP', 'reference': '16142940', 'id': 'op-1'}
        return client

    def test_payout_waits_for_free_balance(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        busy = self._ramp(phase='paying', status='PROCESSING', ves_amount='40000')
        ramp = off.pay_out(ramp, self._client(available='50000'))
        self.assertEqual((off._phase(ramp), ramp.status_detail), ('converted', 'waiting_balance'))
        busy.delete()
        ramp = off.pay_out(ramp, self._client(available='50000'))
        self.assertEqual((ramp.status, ramp.status_detail), ('COMPLETED', 'delivered'))
        self.assertEqual(off._section(ramp)['bank_reference'], '16142940')

    def test_payout_body_and_key_are_fixed(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        client = self._client()
        off.pay_out(ramp, client)
        kwargs = client.credit.call_args.kwargs
        self.assertEqual((kwargs['bank_code'], kwargs['cedula'], kwargs['phone']), ('0134', 'V12345678', '584141234567'))
        self.assertEqual(kwargs['ves_amount'], Decimal('19000.00'))
        self.assertEqual(kwargs['idempotency_key'], f'{ramp.external_id}:credit:0')

    def test_ambiguous_payout_replays_same_key_inside_window_only(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        ramp = off.pay_out(ramp, self._client(credit=VexPayAmbiguousError('timeout')))
        self.assertEqual(off._phase(ramp), 'paying')
        client = self._client()
        # Inside the dispatch lease nothing is replayed.
        off.sync_off_ramp(RampTransaction.objects.get(pk=ramp.pk), client)
        client.credit.assert_not_called()
        off._update(ramp.pk, dispatch_lease_until=(timezone.now() - timedelta(seconds=1)).isoformat())
        ramp = off.sync_off_ramp(RampTransaction.objects.get(pk=ramp.pk), client)
        self.assertEqual(client.credit.call_args.kwargs['idempotency_key'], f'{ramp.external_id}:credit:0')
        self.assertEqual(ramp.status, 'COMPLETED')

    def test_ambiguous_payout_past_window_goes_to_review(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        ramp = off.pay_out(ramp, self._client(credit=VexPayAmbiguousError('timeout')))
        late = (timezone.now() - timedelta(hours=21)).isoformat()
        off._update(ramp.pk, credit_sent_at=late, dispatch_lease_until=late)
        client = self._client()
        ramp = off.sync_off_ramp(RampTransaction.objects.get(pk=ramp.pk), client)
        client.credit.assert_not_called()
        self.assertEqual((off._phase(ramp), ramp.status_detail), ('credit_review', 'needs_review:credit_unknown:replay_window'))

    def test_bank_rejection_is_definite_and_retry_uses_a_new_key(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        rejected = VexPayError('rechazo', status=422, payload={'bankCode': 'AC01'})
        ramp = off.pay_out(ramp, self._client(credit=rejected))
        self.assertEqual((off._phase(ramp), ramp.status_detail), ('credit_failed', 'needs_review:credit_rejected:AC01'))
        with self.assertRaises(off.VexPayOffRampError):
            off.update_beneficiary(ramp, BENEFICIARY, operator='ops', reviewed_key='stale:credit:9', reviewed_revision=0)
        ramp = off.update_beneficiary(ramp, dict(BENEFICIARY, phone='584241234567'), operator='ops',
                                      reviewed_key=off._section(ramp)['credit_key'], reviewed_revision=0)
        with self.assertRaises(off.VexPayOffRampError):
            off.update_beneficiary(ramp, BENEFICIARY, operator='ops',
                                   reviewed_key=off._section(ramp)['credit_key'], reviewed_revision=0)
        ramp = off.retry_payout(ramp, operator='ops', reviewed_key=off._section(ramp)['credit_key'],
                                reviewed_revision=int(off._section(ramp).get('beneficiary_revision') or 0))
        client = self._client()
        ramp = off.pay_out(ramp, client)
        self.assertEqual(client.credit.call_args.kwargs['idempotency_key'], f'{ramp.external_id}:credit:1')
        self.assertEqual(client.credit.call_args.kwargs['phone'], '584241234567')

    def test_duplicate_or_unknown_errors_are_never_definite(self):
        for exc in (VexPayError('dup', status=422, payload={'bankCode': 'AM05'}),
                    VexPayError('conflict', status=409, code='idempotency_key_reused')):
            ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
            ramp = off.pay_out(ramp, self._client(credit=exc))
            self.assertEqual(off._phase(ramp), 'credit_review')
            with self.assertRaises(off.VexPayOffRampError):
                off.retry_payout(ramp, operator='ops', reviewed_key=off._section(ramp)['credit_key'],
                                reviewed_revision=int(off._section(ramp).get('beneficiary_revision') or 0))
            ramp = off.retry_payout(ramp, operator='ops', confirmed_unpaid=True, reviewed_key=off._section(ramp)['credit_key'],
                                reviewed_revision=int(off._section(ramp).get('beneficiary_revision') or 0))
            self.assertEqual(off._section(ramp)['credit_attempt'], 1)

    def test_credit_not_enabled_is_definite(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        ramp = off.pay_out(ramp, self._client(credit=VexPayError('forbidden', status=403)))
        self.assertEqual(ramp.status_detail, 'needs_review:credit_unavailable')

    def test_insufficient_balance_goes_back_to_waiting(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        exc = VexPayError('no', status=400, code='insufficient_balance')
        ramp = off.pay_out(ramp, self._client(credit=exc))
        self.assertEqual((off._phase(ramp), ramp.status_detail), ('converted', 'waiting_balance'))
        client = self._client()
        off.pay_out(ramp, client)
        self.assertEqual(client.credit.call_args.kwargs['idempotency_key'], f'{ramp.external_id}:credit:1')

    def test_pending_credit_is_polled_until_settled(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        ramp = off.pay_out(ramp, self._client(credit={'code': 'AC00', 'id': 'op-9'}))
        self.assertEqual(off._phase(ramp), 'credit_pending')
        client = mock.Mock()
        client.operation.return_value = {'code': 'ACCP', 'reference': '777', 'id': 'op-9'}
        ramp = off.sync_off_ramp(ramp, client)
        self.assertEqual((ramp.status, off._section(ramp)['bank_reference']), ('COMPLETED', '777'))

    def test_stale_pending_credit_goes_to_review(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        ramp = off.pay_out(ramp, self._client(credit={'code': 'AC00', 'id': 'op-9'}))
        off._update(ramp.pk, pending_since=(timezone.now() - timedelta(hours=25)).isoformat())
        client = mock.Mock()
        client.operation.return_value = {'code': 'AC00', 'id': 'op-9'}
        ramp = off.sync_off_ramp(RampTransaction.objects.get(pk=ramp.pk), client)
        self.assertEqual(ramp.status_detail, 'needs_review:credit_pending_stale')

    def test_late_answer_of_an_old_attempt_never_moves_a_new_one(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        rejected = VexPayError('rechazo', status=422, payload={'bankCode': 'AC01'})
        ramp = off.pay_out(ramp, self._client(credit=rejected))
        old_key = off._section(ramp)['credit_key']
        ramp = off.retry_payout(ramp, operator='ops', reviewed_key=off._section(ramp)['credit_key'],
                                reviewed_revision=int(off._section(ramp).get('beneficiary_revision') or 0))
        ramp = off.pay_out(ramp, self._client(credit=VexPayAmbiguousError('timeout')))
        self.assertEqual(off._phase(ramp), 'paying')
        # The first attempt's delayed rejection arrives now.
        ramp = off._credit_refused(ramp, rejected, old_key)
        self.assertEqual(off._phase(ramp), 'paying')
        ramp = off.apply_credit_answer(ramp, {'code': 'ACCP'}, old_key)
        self.assertEqual(ramp.status, 'PROCESSING')

    def test_pending_code_wins_over_success_flag(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        ramp = off.pay_out(ramp, self._client(credit={'code': 'AC00', 'success': True, 'id': 'op-1'}))
        self.assertEqual((ramp.status, off._phase(ramp)), ('PROCESSING', 'credit_pending'))
        ramp2 = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        ramp2 = off.pay_out(ramp2, self._client(credit={'code': 'XYZ', 'success': True}))
        self.assertEqual(off._phase(ramp2), 'credit_review')

    def test_retry_starts_clean(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        ramp = off.pay_out(ramp, self._client(credit={'code': 'AC00', 'id': 'op-9'}))
        off._update(ramp.pk, pending_since=(timezone.now() - timedelta(hours=25)).isoformat())
        client = mock.Mock()
        client.operation.return_value = {'code': 'AC00', 'id': 'op-9'}
        ramp = off.sync_off_ramp(RampTransaction.objects.get(pk=ramp.pk), client)
        ramp = off.retry_payout(ramp, operator='ops', confirmed_unpaid=True, reviewed_key=off._section(ramp)['credit_key'],
                                reviewed_revision=int(off._section(ramp).get('beneficiary_revision') or 0))
        section = off._section(ramp)
        self.assertIsNone(section['pending_since'])
        self.assertIsNone(section['operation_id'])
        ramp = off.pay_out(ramp, self._client(credit={'code': 'AC00', 'id': 'op-10'}))
        ramp = off.sync_off_ramp(ramp, client)
        self.assertEqual(off._phase(ramp), 'credit_pending')

    def test_scan_advances_through_the_late_watch(self):
        ramp = self._ramp(created_block=1000)
        calls = []

        def rpc(method, params):
            if method == 'eth_blockNumber':
                return hex(1000 + 200_000)
            calls.append(params[0])
            late = int(params[0]['fromBlock'], 16) <= 150_000 <= int(params[0]['toBlock'], 16)
            return [transfer()] if late else []
        found = None
        for _ in range(5):
            found = off._find_funding(RampTransaction.objects.get(pk=ramp.pk), rpc)
            if found not in (None, off._UNKNOWN):
                break
        self.assertEqual(found, (TX, WEI))
        self.assertLessEqual(max(len(calls), 1), 5 * off.MAX_CHUNKS_PER_SCAN)

    def test_retry_needs_the_reviewed_attempt_and_no_live_dispatch(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        ramp = off.pay_out(ramp, self._client(credit=VexPayError('x', status=500)))
        self.assertEqual(off._phase(ramp), 'credit_review')
        with self.assertRaises(off.VexPayOffRampError):
            off.retry_payout(ramp, operator='ops', confirmed_unpaid=True, reviewed_key='someone-else:credit:0', reviewed_revision=0)
        ramp = off.retry_payout(ramp, operator='ops', confirmed_unpaid=True,
                                reviewed_key=off._section(ramp)['credit_key'],
                                reviewed_revision=int(off._section(ramp).get('beneficiary_revision') or 0))
        self.assertEqual(off._section(ramp)['credit_attempt'], 1)
        # A stale form for attempt 0 cannot start attempt 2.
        with self.assertRaises(off.VexPayOffRampError):
            off.retry_payout(ramp, operator='ops', confirmed_unpaid=True, reviewed_key=f'{ramp.external_id}:credit:0', reviewed_revision=0)

    def test_replay_window_review_waits_for_the_lease(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        ramp = off.pay_out(ramp, self._client(credit=VexPayAmbiguousError('timeout')))
        off._update(ramp.pk, credit_sent_at=(timezone.now() - timedelta(hours=21)).isoformat())
        ramp = off.sync_off_ramp(RampTransaction.objects.get(pk=ramp.pk), self._client())
        self.assertEqual(off._phase(ramp), 'paying')  # lease still held

    def test_dropped_hash_stops_blocking_after_grace(self):
        started = (timezone.now() - timedelta(hours=7)).isoformat()
        ramp = off.report_funding(self._ramp(funding_started_at=started), TX)
        off._update(ramp.pk, funding_reported_at=(timezone.now() - timedelta(hours=1)).isoformat())
        rpc = mock.Mock(side_effect=lambda method, params: None if method == 'eth_getTransactionReceipt'
                        else ('0x3e8' if method == 'eth_blockNumber' else []))
        ramp = off.sync_off_ramp(RampTransaction.objects.get(pk=ramp.pk), rpc=rpc)
        self.assertEqual(ramp.status_detail, 'needs_review:funding_not_found')
        # Still watched: a transfer proven later is picked up.
        found = mock.Mock(side_effect=lambda method, params: None if method == 'eth_getTransactionReceipt'
                          else ('0x3e8' if method == 'eth_blockNumber' else [transfer()]))
        off._update(ramp.pk, scanned_to=None)
        ramp = off.sync_off_ramp(RampTransaction.objects.get(pk=ramp.pk), rpc=found)
        self.assertEqual(ramp.status_detail, 'awaiting_conversion')

    def test_refusal_after_a_timeout_is_not_proof_of_nonpayment(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        ramp = off.pay_out(ramp, self._client(credit=VexPayAmbiguousError('timeout')))
        off._update(ramp.pk, dispatch_lease_until=(timezone.now() - timedelta(seconds=1)).isoformat())
        for refusal in (VexPayError('forbidden', status=403),
                        VexPayError('rechazo', status=422, payload={'bankCode': 'AC01'})):
            current = RampTransaction.objects.get(pk=ramp.pk)
            if off._phase(current) != 'paying':
                break
            current = off.sync_off_ramp(current, self._client(credit=refusal))
            self.assertEqual(off._phase(current), 'credit_review')
        with self.assertRaises(off.VexPayOffRampError):
            off.retry_payout(current, operator='ops', reviewed_key=off._section(current)['credit_key'], reviewed_revision=0)

    def test_undelivered_conversion_request_is_retried(self):
        ramp = self._funded()
        with mock.patch('config.ops_alerts.send_ops_alert', return_value=False):
            off.ensure_alerted(ramp)
        self.assertNotIn('note:convertir', off._section(RampTransaction.objects.get(pk=ramp.pk)).get('alerted') or {})
        with mock.patch('config.ops_alerts.send_ops_alert', return_value=True) as send:
            off.ensure_alerted(RampTransaction.objects.get(pk=ramp.pk))
            off.ensure_alerted(RampTransaction.objects.get(pk=ramp.pk))
        self.assertEqual(send.call_count, 1)

    def test_scan_degrades_to_micro_chunks_and_keeps_progress(self):
        ramp = self._ramp(created_block=1000)
        sizes = []

        def rpc(method, params):
            if method == 'eth_blockNumber':
                return hex(1000 + 300)
            span = int(params[0]['toBlock'], 16) - int(params[0]['fromBlock'], 16) + 1
            sizes.append(span)
            if span > off.MICRO_CHUNK_BLOCKS:
                raise RuntimeError('range too large')
            return [transfer()] if int(params[0]['fromBlock'], 16) <= 1250 <= int(params[0]['toBlock'], 16) else []
        self.assertEqual(off._find_funding(ramp, rpc), (TX, WEI))
        self.assertTrue(all(size <= off.MICRO_CHUNK_BLOCKS for size in sizes[1:]))

    def test_unverifiable_funding_escalates_and_stays_watched(self):
        started = (timezone.now() - timedelta(hours=13)).isoformat()
        ramp = self._ramp(funding_started_at=started)
        ramp = off.sync_off_ramp(ramp, rpc=mock.Mock(side_effect=RuntimeError('rpc down')))
        self.assertEqual((ramp.status, ramp.status_detail), ('PROCESSING', 'needs_review:funding_unverifiable'))
        found = mock.Mock(side_effect=lambda method, params: '0x3e8' if method == 'eth_blockNumber' else [transfer()])
        ramp = off.sync_off_ramp(ramp, rpc=found)
        self.assertEqual(ramp.status_detail, 'awaiting_conversion')

    def test_retry_after_a_destination_change_needs_a_fresh_look(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        ramp = off.pay_out(ramp, self._client(credit=VexPayError('r', status=422, payload={'bankCode': 'AC01'})))
        key = off._section(ramp)['credit_key']
        ramp = off.update_beneficiary(ramp, dict(BENEFICIARY, phone='584241234567'), operator='ops2',
                                      reviewed_key=key, reviewed_revision=0)
        with self.assertRaises(off.VexPayOffRampError):
            off.retry_payout(ramp, operator='ops1', reviewed_key=key, reviewed_revision=0)
        self.assertEqual(off._phase(off.retry_payout(ramp, operator='ops1', reviewed_key=key,
                                                     reviewed_revision=1)), 'converted')

    def test_receipt_errors_do_not_block_the_log_scan(self):
        ramp = off.report_funding(self._ramp(), TX2)

        def rpc(method, params):
            if method == 'eth_getTransactionReceipt':
                raise RuntimeError('receipt endpoint down')
            if method == 'eth_blockNumber':
                return '0x3e8'
            return [transfer()]
        self.assertEqual(off.sync_off_ramp(ramp, rpc=rpc).status_detail, 'awaiting_conversion')

    def test_manual_paid(self):
        ramp = off.mark_converted(self._funded(), Decimal('19000'), operator='ops')
        ramp = off.pay_out(ramp, self._client(credit=VexPayError('x', status=500)))
        ramp = off.mark_paid_manually(ramp, '998877', operator='ops')
        self.assertEqual((ramp.status, off._section(ramp)['bank_reference']), ('COMPLETED', '998877'))

    def test_waiting_on_ops_costs_no_poll(self):
        self.assertFalse(off.due_for_sync(self._funded()))

    # ---- limits and creation

    @override_settings(VEXPAY_OFFRAMP_USER_DAILY_USD='30')
    def test_limits_count_open_sends(self):
        self._ramp(status='PROCESSING')
        with self.assertRaises(off.VexPayOffRampError):
            off.check_limits(self.user, Decimal('15'))
        off.check_limits(self.user, Decimal('10'))

    def test_deposit_address_is_validated(self):
        account = SimpleNamespace(pk=1, bsc_address=WALLET, display_name='')
        for bad in ({'address': off.USDT_BSC}, {'address': WALLET}, {'address': 'nope'},
                    {'network': 'TRC20'}, {'customerRef': 'someone-else'}, {'tagRequired': True}):
            ramp = self._ramp(phase='preparing', funding_started_at=None)
            payload = {'address': DEPOSIT, 'network': 'BEP20', 'currency': 'USDT',
                       'customerRef': off.customer_ref(ramp), 'tagRequired': False}
            payload.update(bad)
            client = mock.Mock()
            client.deposit_address.return_value = payload
            with self.assertRaises(off.VexPayOffRampError):
                off.prepare_deposit(ramp, client)
            self.assertEqual(RampTransaction.objects.get(pk=ramp.pk).status, 'FAILED')
        del account

    def test_good_deposit_address_opens_the_window(self):
        ramp = self._ramp(phase='preparing', funding_started_at=None)
        client = mock.Mock()
        client.deposit_address.return_value = {'address': DEPOSIT.upper().replace('0X', '0x'), 'network': 'BEP20',
                                               'currency': 'USDT', 'customerRef': off.customer_ref(ramp),
                                               'tagRequired': False}
        ramp = off.prepare_deposit(ramp, client)
        self.assertTrue(off.can_fund(ramp))
        self.assertEqual(off.funding_details(ramp)['confioDepositAddress'], DEPOSIT)
        self.assertEqual(client.deposit_address.call_args.kwargs['idempotency_key'], f'{ramp.external_id}:deposit')

    @override_settings(VEXPAY_OFFRAMP_USDT_FEE_PERCENT='2.5', VEXPAY_OFFRAMP_USDT_FEE_FIXED='0.50',
                       VEXPAY_OFFRAMP_SPREAD_PERCENT='1.5')
    def test_estimate_uses_configured_processor_terms(self):
        ves = off.estimate_ves(Decimal('20'), Decimal('1000'))
        self.assertEqual(ves, ((Decimal('20') * Decimal('0.975') - Decimal('0.5')) * 1000 / Decimal('1.015'))
                         .quantize(Decimal('0.01'), rounding='ROUND_DOWN'))


@override_settings(VEXPAY_WEBHOOK_SECRET='whsec_test')
class OffRampWebhookTests(TestCase):
    def test_usdt_deposit_event_routes_to_its_send(self):
        import json
        import time
        import hmac
        import hashlib
        from django.test import RequestFactory
        from ramps.views import vexpay_webhook
        user = get_user_model().objects.create(username='wh-sender', firebase_uid='wh-sender')
        ramp = RampTransaction(provider='vexpay', direction='off_ramp', status='PENDING', actor_user=user,
                               destination='cusd_plus', metadata={'vexpay': {'phase': 'funding_reported'}})
        ramp.external_id = str(ramp.internal_id)
        ramp.save()
        body = json.dumps({'event': 'payment.completed', 'data': {
            'paymentId': 'pay-usdt', 'customerRef': off.customer_ref(ramp), 'method': 'USDT'}}).encode()
        t = int(time.time())
        sig = hmac.new(b'whsec_test', f'{t}.'.encode() + body, hashlib.sha256).hexdigest()
        request = RequestFactory().post('/api/vexpay/webhook/', data=body, content_type='application/json',
                                        HTTP_VEXPAY_SIGNATURE=f't={t},v1={sig}', HTTP_VEXPAY_EVENT_ID='evt-usdt-1')
        with mock.patch('ramps.tasks.sync_vexpay_ramp_task.delay') as delay:
            response = vexpay_webhook(request)
        self.assertEqual(response.status_code, 200)
        delay.assert_called_once_with(ramp.pk)
