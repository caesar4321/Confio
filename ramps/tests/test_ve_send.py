import base64
import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from ramps import pagoasap_send, ve_pagomovil, ve_send
from ramps.models import RampTransaction
from ramps.pagoasap_client import PagoAsapAmbiguousError, PagoAsapError, idempotency_key
from ramps.ve_send import Outcome, Settlement

WALLET = '0x' + '12' * 20
TARGET = '0x' + 'de' * 20
OTHER = '0x' + '77' * 20
TX = '0x' + 'ab' * 32
TX2 = '0x' + 'cd' * 32
WEI = 19_819_999 * 10 ** 12  # 19.819999 USDT (tagged)
BENEFICIARY = {'cedula': 'V12345678', 'phone': '584141234567', 'bank_code': '0134'}

# Tests run with real AWS credentials: never reach the team's Telegram.
_ops_alert = mock.patch('config.ops_alerts.send_ops_alert', return_value=True)


def setUpModule():
    _ops_alert.start()


def tearDownModule():
    _ops_alert.stop()


def _topic(address):
    return '0x' + '0' * 24 + address[2:]


def transfer(amount_wei=WEI, sender=WALLET, to=TARGET, tx=TX):
    return {'address': ve_send.USDT_BSC, 'topics': [ve_send.TRANSFER_TOPIC, _topic(sender), _topic(to)],
            'data': hex(amount_wei), 'logIndex': '0x1', 'transactionHash': tx}


def receipt(*logs, status='0x1', block='0x3c0', block_hash='0xb1'):
    return {'status': status, 'blockNumber': block, 'blockHash': block_hash, 'logs': list(logs) or [transfer()]}


def chain(logs=(), head=0x3e8, receipt_value=None, finalized=None, canonical_hash='0xb1'):
    def rpc(method, params):
        if method == 'eth_blockNumber':
            return hex(head)
        if method == 'eth_getBlockByNumber':
            if params[0] == 'finalized':
                return {'number': hex(finalized if finalized is not None else head)}
            return {'hash': canonical_hash}
        if method == 'eth_getTransactionReceipt':
            return receipt_value
        return list(logs)
    return rpc


def pagoasap_client(*, balance='100', rate='1000', total=None, create=None, intent=None):
    client = mock.Mock()
    client.is_configured = True
    client.balances.return_value = {'USD': Decimal(balance)}
    client.rate.return_value = Decimal(rate)
    client.reference_rate.return_value = Decimal('1010')
    client.preview.side_effect = lambda ves: {'total': total if total is not None else str(Decimal(ves) / Decimal(rate))}
    if isinstance(create, Exception):
        client.create_payout.side_effect = create
    else:
        client.create_payout.return_value = create or 'intent-1'
    if isinstance(intent, Exception):
        client.payout.side_effect = intent
    else:
        client.payout.return_value = intent or {'state': 'completed', 'reference': 'ref-9', 'amountVES': 19819.99}
    return client


class SendCoreTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='ve-sender', firebase_uid='ve-sender')

    def _ramp(self, phase='funding_reported', status='PENDING', **section):
        values = {'phase': phase, 'gross_usd': '20.00', 'deposit_wei': str(WEI), 'gross_wei': str(20 * 10 ** 18),
                  'deposit_address': TARGET, 'beneficiary': BENEFICIARY, 'beneficiary_revision': 0,
                  'estimated_ves': '19800.00', 'created_block': 1000, 'payout_attempt': 0,
                  'funding_started_at': timezone.now().isoformat()}
        values.update(section)
        ramp = RampTransaction(provider='pagoasap', direction='off_ramp', status=status, country_code='VE',
                               actor_user=self.user, actor_address=WALLET, destination='cusd_plus',
                               fiat_currency='VES', crypto_currency='USDT', final_currency='USDT',
                               crypto_amount_estimated=Decimal('19.819999'), final_amount=Decimal('19.819999'),
                               metadata={ve_send.SECTION: values})
        ramp.external_id = str(ramp.internal_id)
        ramp.save()
        return ramp

    def _funded(self, **section):
        # Settled: Relay's delivery to Pago ASAP is proven; 19.819999 USDC credited.
        values = dict(funding_tx_hash=TX, funded_wei=str(WEI), credited_usd='19.819999')
        values.update(section)
        return self._ramp(phase='settled', status='PROCESSING', **values)

    # ---- funding claim and proof

    @mock.patch('ramps.pagoasap_send.funding_target', return_value={
        'deposit_address': TARGET, 'binding': {'request_id': '0x' + '11' * 32, 'deadline': 9999999999}})
    def test_funding_is_a_single_claim_with_its_target_made_at_claim(self, target):
        ramp = self._ramp(phase='awaiting_funding', funding_started_at=None, deposit_address=None)
        self.assertTrue(ve_send.can_fund(ramp))
        claimed = ve_send.start_funding(ramp)
        self.assertEqual((ve_send._phase(claimed), ve_send._section(claimed)['deposit_address']),
                         ('funding_reported', TARGET))
        self.assertEqual(ve_send.funding_details(claimed)['deposit_address'], TARGET)
        with self.assertRaises(ve_send.VeSendError):
            ve_send.start_funding(claimed)
        self.assertEqual(target.call_count, 1)

    @mock.patch('ramps.pagoasap_send.funding_target', return_value={'deposit_address': ve_send.USDT_BSC})
    def test_a_bad_target_is_never_claimed(self, _):
        ramp = self._ramp(phase='awaiting_funding', funding_started_at=None, deposit_address=None)
        with self.assertRaises(ve_send.VeSendError):
            ve_send.start_funding(ramp)
        self.assertTrue(ve_send.can_fund(RampTransaction.objects.get(pk=ramp.pk)))

    def test_funding_window_closes_and_unclaimed_is_never_scanned(self):
        ramp = self._ramp(phase='awaiting_funding', funding_started_at=None)
        rpc = mock.Mock()
        ve_send.sync(ramp, rpc=rpc)
        rpc.assert_not_called()
        RampTransaction.objects.filter(pk=ramp.pk).update(created_at=timezone.now() - timedelta(hours=3))
        ramp = ve_send.sync(RampTransaction.objects.get(pk=ramp.pk), rpc=rpc)
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', 'expired_unfunded'))

    def test_reported_hash_is_proven_by_exact_transfer(self):
        ramp = ve_send.report_funding(self._ramp(), TX)
        ramp = ve_send.sync(ramp, rpc=chain(receipt_value=receipt()))
        self.assertEqual((ramp.status, ve_send._phase(ramp)), ('PROCESSING', 'funded'))

    def test_wrong_amount_sender_or_recipient_is_not_funding(self):
        for log in (transfer(amount_wei=WEI - 1), transfer(sender=OTHER), transfer(to=OTHER)):
            ramp = ve_send.report_funding(self._ramp(), TX)
            self.assertEqual(ve_send.sync(ramp, rpc=chain(receipt_value=receipt(log))).status, 'PENDING')

    def test_lost_hash_is_found_by_its_log(self):
        ramp = ve_send.sync(self._ramp(), rpc=chain(logs=[transfer()], head=1500))
        self.assertEqual(ve_send._phase(ramp), 'funded')

    def test_one_transfer_funds_one_order(self):
        first = ve_send.sync(ve_send.report_funding(self._ramp(), TX), rpc=chain(receipt_value=receipt()))
        self.assertEqual(ve_send._phase(first), 'funded')
        second = ve_send.report_funding(self._ramp(), TX)
        self.assertEqual(ve_send.sync(second, rpc=chain(logs=[transfer()], receipt_value=receipt())).status, 'PENDING')

    def test_rpc_outage_changes_nothing(self):
        ramp = ve_send.report_funding(self._ramp(), TX)
        ramp = ve_send.sync(ramp, rpc=mock.Mock(side_effect=RuntimeError('rpc down')))
        self.assertEqual((ramp.status, ve_send._phase(ramp)), ('PENDING', 'funding_reported'))

    def test_claimed_never_sent_expires_then_late_funding_goes_to_ops(self):
        started = (timezone.now() - timedelta(hours=7)).isoformat()
        ramp = ve_send.sync(self._ramp(funding_started_at=started), rpc=chain())
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', 'expired_unfunded'))
        self.assertIn(ramp.pk, list(ve_send.open_sends().values_list('pk', flat=True)))
        ve_send._update(ramp.pk, scanned_to=None)
        ramp = ve_send.sync(RampTransaction.objects.get(pk=ramp.pk), rpc=chain(logs=[transfer()]))
        self.assertEqual((ramp.status, ramp.status_detail), ('PROCESSING', 'needs_review:late_funding'))
        # Never paid out automatically.
        self.assertEqual(ve_send._phase(ramp), 'payout_review')

    def test_unverifiable_funding_escalates_and_stays_watched(self):
        started = (timezone.now() - timedelta(hours=13)).isoformat()
        ramp = ve_send.sync(self._ramp(funding_started_at=started), rpc=mock.Mock(side_effect=RuntimeError('down')))
        self.assertEqual((ramp.status, ramp.status_detail), ('PROCESSING', 'needs_review:funding_unverifiable'))
        ramp = ve_send.sync(ramp, rpc=chain(logs=[transfer()]))
        self.assertEqual(ve_send._phase(ramp), 'funded')

    def test_scan_degrades_to_micro_chunks(self):
        ramp = self._ramp(created_block=1000)
        sizes = []

        def rpc(method, params):
            if method == 'eth_blockNumber':
                return hex(1300)
            span = int(params[0]['toBlock'], 16) - int(params[0]['fromBlock'], 16) + 1
            sizes.append(span)
            if span > ve_send.MICRO_CHUNK_BLOCKS:
                raise RuntimeError('range too large')
            return [transfer()] if int(params[0]['fromBlock'], 16) <= 1250 <= int(params[0]['toBlock'], 16) else []
        self.assertEqual(ve_send._find_funding(ramp, rpc), (TX, WEI))

    def test_receipt_errors_do_not_block_the_log_scan(self):
        ramp = ve_send.report_funding(self._ramp(), TX2)

        def rpc(method, params):
            if method == 'eth_getTransactionReceipt':
                raise RuntimeError('receipt endpoint down')
            return '0x3e8' if method == 'eth_blockNumber' else [transfer()]
        self.assertEqual(ve_send._phase(ve_send.sync(ramp, rpc=rpc)), 'funded')

    def test_scan_skips_a_transfer_another_order_owns(self):
        owner = self._ramp(phase='funded', status='COMPLETED', funding_tx_hash=TX)
        ramp = ve_send.sync(self._ramp(), rpc=chain(logs=[transfer(tx=TX), transfer(tx=TX2)], head=1500))
        self.assertEqual(ve_send._section(ramp).get('funding_tx_hash'), TX2)
        del owner

    def test_old_open_sends_keep_their_tag(self):
        old = self._ramp(status='PROCESSING')
        RampTransaction.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=10))
        self.assertIn(WEI, ve_send._watched_amounts(WALLET))

    def test_only_finalized_transfers_count(self):
        ramp = ve_send.report_funding(self._ramp(), TX)
        fresh = receipt(block=hex(0x3e0))
        ramp = ve_send.sync(ramp, rpc=chain(receipt_value=fresh, head=0x3e8, finalized=0x3d0))
        self.assertEqual(ve_send._phase(ramp), 'funding_reported')
        ramp = ve_send.sync(ramp, rpc=chain(receipt_value=fresh, head=0x3f8, finalized=0x3e5))
        self.assertEqual(ve_send._phase(ramp), 'funded')

    def test_receipt_from_a_reorged_block_is_not_funding(self):
        ramp = ve_send.report_funding(self._ramp(), TX)
        ramp = ve_send.sync(ramp, rpc=chain(receipt_value=receipt(block_hash='0xold'), canonical_hash='0xnew'))
        self.assertEqual(ve_send._phase(ramp), 'funding_reported')

    # ---- cancel

    def test_cancel_rules(self):
        self.assertEqual(ve_send.cancel(self._ramp(phase='awaiting_funding', funding_started_at=None)).status, 'FAILED')
        with self.assertRaises(ve_send.VeSendError):
            ve_send.cancel(self._ramp(), rpc=mock.Mock())
        quiet = self._ramp(funding_started_at=(timezone.now() - timedelta(minutes=20)).isoformat())
        with self.assertRaises(ve_send.VeSendError):
            ve_send.cancel(quiet, rpc=chain(logs=[transfer()]))
        self.assertEqual(ve_send._phase(RampTransaction.objects.get(pk=quiet.pk)), 'funded')

    # ---- shared deposit target

    def test_shared_target_tags_each_send_of_a_sender(self):
        account = SimpleNamespace(pk=None, bsc_address=WALLET, display_name='')
        locked = mock.Mock(bsc_address=WALLET)
        amounts = []
        with mock.patch('users.models.Account.objects') as accounts:
            accounts.select_for_update.return_value.filter.return_value.first.return_value = locked
            for _ in range(3):
                ramp = ve_send.reserve(provider='pagoasap', user=self.user, account=account, gross_usd=Decimal('20'),
                                       beneficiary=BENEFICIARY, gross_wei=20 * 10 ** 18, deposit_wei=19_82 * 10 ** 16,
                                       created_block=1000, estimate={'estimated_ves': '19800', 'rate': '1000'})
                amounts.append(int(ve_send._section(ramp)['deposit_wei']))
                RampTransaction.objects.filter(pk=ramp.pk).update(status='PROCESSING')
        self.assertEqual(len(set(amounts)), 3)
        self.assertTrue(all(19_82 * 10 ** 16 - a < 10 ** 16 for a in amounts))  # under one cent

    # ---- settlement (Relay to Polygon)

    def _proven(self, **section):
        return self._ramp(phase='funded', status='PROCESSING', funding_tx_hash=TX, funded_wei=str(WEI), **section)

    def test_settlement_outcomes(self):
        cases = [
            (Settlement('pending'), 'PROCESSING', 'funded', 'bridging'),
            (Settlement('delivered', credited_usd='19.77', evidence=TX2), 'PROCESSING', 'settled', 'settled'),
            (Settlement('refunded'), 'FAILED', 'refunded', 'refunded_to_wallet'),
            (Settlement('review', reason='destination_amount_mismatch'), 'PROCESSING', 'payout_review',
             'needs_review:settlement:destination_amount_mismatch'),
        ]
        for result, status, phase, detail in cases:
            with mock.patch('ramps.pagoasap_send.settle', return_value=result):
                ramp = ve_send.sync(self._proven())
            self.assertEqual((ramp.status, ve_send._phase(ramp), ramp.status_detail), (status, phase, detail))

    def test_one_delivery_settles_one_order(self):
        with mock.patch('ramps.pagoasap_send.settle', return_value=Settlement('delivered', credited_usd='19.77', evidence=TX2)):
            first = ve_send.sync(self._proven())
            second = ve_send.sync(self._proven())
        self.assertEqual(ve_send._phase(first), 'settled')
        self.assertEqual(second.status_detail, 'needs_review:settlement:delivery_claimed_elsewhere')

    def test_settle_maps_the_bridge_reconciler(self):
        ramp = self._proven(bridge={'request_id': '0x' + '11' * 32, 'response': {}, 'deadline': 9999999999,
                                    'recipient': TARGET, 'amount_out': '19800000', 'amount_out_min': '19700000'})

        def delivered(transfer, client=None):
            transfer.status, transfer.actual_out_units, transfer.destination_tx_hash = 'delivered', '19770000', TX2
        with mock.patch('payment_accounts.relay_settlement.reconcile_relay', side_effect=delivered) as rec:
            result = pagoasap_send.settle(ramp)
        self.assertEqual((result.kind, result.credited_usd, result.evidence), ('delivered', '19.77', TX2))
        transfer = rec.call_args.args[0]
        self.assertEqual((transfer.quote.amount_units, transfer.source_tx_hash, transfer.funding_mode),
                         (str(WEI), TX, 'wallet'))
        from payment_accounts.allbridge_next import NextError
        with mock.patch('payment_accounts.relay_settlement.reconcile_relay', side_effect=NextError('rpc')):
            self.assertEqual(pagoasap_send.settle(ramp).kind, 'pending')

    def test_a_mixed_delivery_never_overcredits(self):
        ramp = self._proven(bridge={'request_id': '0x' + '11' * 32, 'response': {}, 'deadline': 9999999999,
                                    'recipient': TARGET, 'amount_out': '19800000', 'amount_out_min': '19700000'})

        def mixed(transfer, client=None):
            transfer.status, transfer.actual_out_units, transfer.destination_tx_hash = 'delivered', '49530000', TX2
        with mock.patch('payment_accounts.relay_settlement.reconcile_relay', side_effect=mixed):
            result = pagoasap_send.settle(ramp)
        self.assertEqual((result.kind, result.reason), ('review', 'delivery_amount_unattributable'))

    def test_retry_from_a_settlement_review_settles_again(self):
        with mock.patch('ramps.pagoasap_send.settle', return_value=Settlement('review', reason='relay_failure')):
            ramp = ve_send.sync(self._proven())
        ramp = ve_send.retry_payout(ramp, operator='ops', reviewed_key='', reviewed_revision=0, confirmed_unpaid=True)
        self.assertEqual(ve_send._phase(ramp), 'funded')

    # ---- payout through Pago ASAP

    def _pay(self, ramp, client):
        with mock.patch('ramps.pagoasap_send._client', return_value=client):
            return ve_send.sync(ramp)

    def test_payout_is_priced_at_payout_time_and_completes(self):
        client = pagoasap_client()
        ramp = self._pay(self._funded(), client)
        self.assertEqual(ve_send._phase(ramp), 'payout_pending')
        kwargs = client.create_payout.call_args.kwargs
        self.assertEqual((kwargs['phone'], kwargs['cedula'], kwargs['bank_code']), ('04141234567', 'V12345678', '0134'))
        self.assertEqual(kwargs['amount_ves'], Decimal('19819.99'))
        self.assertEqual(kwargs['idempotency_key'], idempotency_key(f'{ramp.external_id}:payout:0'))
        ramp = self._pay(ramp, client)
        self.assertEqual((ramp.status, ve_send._section(ramp)['bank_reference']), ('COMPLETED', 'ref-9'))
        self.assertEqual(ramp.fiat_amount, Decimal('19819.99'))

    def test_payout_waits_until_the_balance_covers_it(self):
        busy = self._ramp(phase='payout_pending', status='PROCESSING', payout_claim={'cost': '90'})
        ramp = self._pay(self._funded(), pagoasap_client(balance='100'))
        self.assertEqual((ve_send._phase(ramp), ramp.status_detail), ('settled', 'waiting_balance'))
        busy.delete()
        self.assertEqual(ve_send._phase(self._pay(ramp, pagoasap_client(balance='100'))), 'payout_pending')

    def test_fees_scale_the_bolivares_down(self):
        client = pagoasap_client()
        client.preview.side_effect = lambda ves: {'total': str((Decimal(ves) / 1000) * Decimal('1.02'))}
        self._pay(self._funded(), client)
        sent = client.create_payout.call_args.kwargs['amount_ves']
        self.assertLessEqual(sent / 1000 * Decimal('1.02'), Decimal('19.819999'))

    def test_fixed_fees_are_solved_and_unpriceable_goes_to_review(self):
        client = pagoasap_client()
        client.preview.side_effect = lambda ves: {'total': str((Decimal(ves) / 1000 + 1).quantize(Decimal('0.01')))}
        self._pay(self._funded(), client)
        sent = client.create_payout.call_args.kwargs['amount_ves']
        self.assertLessEqual(sent / 1000 + 1, Decimal('19.819999'))
        self.assertGreater(sent, Decimal('18000'))
        broke = pagoasap_client()
        broke.preview.side_effect = lambda ves: {'total': '999'}
        ramp = self._pay(self._funded(), broke)
        self.assertEqual((ve_send._phase(ramp), ramp.status_detail), ('payout_review', 'needs_review:payout_unpriceable'))
        broke.create_payout.assert_not_called()

    def test_sends_too_small_to_pay_out_are_refused_before_funding(self):
        client = pagoasap_client()
        client.preview.side_effect = lambda ves: {'total': '1.00'}
        with self.assertRaisesRegex(ve_pagomovil.VePagoMovilError, 'muy pequeño'):
            pagoasap_send._require_payable(client, Decimal('1.40'))
        pagoasap_send._require_payable(client, Decimal('1.50'))
        client.preview.side_effect = lambda ves: {'total': '0'}
        with self.assertRaises(ve_pagomovil.VePagoMovilError):
            pagoasap_send._require_payable(client, Decimal('100'))

    def test_ambiguous_create_replays_the_same_key_inside_the_window(self):
        ramp = self._pay(self._funded(), pagoasap_client(create=PagoAsapAmbiguousError('timeout')))
        self.assertEqual(ve_send._phase(ramp), 'paying')
        client = pagoasap_client()
        ramp = self._pay(ramp, client)
        client.create_payout.assert_not_called()  # lease still held
        ve_send._update(ramp.pk, dispatch_lease_until=(timezone.now() - timedelta(seconds=1)).isoformat())
        ramp = self._pay(RampTransaction.objects.get(pk=ramp.pk), client)
        self.assertEqual(client.create_payout.call_args.kwargs['idempotency_key'],
                         idempotency_key(f'{ramp.external_id}:payout:0'))
        self.assertEqual(ve_send._phase(ramp), 'payout_pending')

    def test_ambiguous_create_past_the_window_goes_to_review(self):
        ramp = self._pay(self._funded(), pagoasap_client(create=PagoAsapAmbiguousError('timeout')))
        late = (timezone.now() - timedelta(hours=1)).isoformat()
        ve_send._update(ramp.pk, payout_sent_at=late, dispatch_lease_until=late)
        client = pagoasap_client()
        ramp = self._pay(RampTransaction.objects.get(pk=ramp.pk), client)
        client.create_payout.assert_not_called()
        self.assertEqual((ve_send._phase(ramp), ramp.status_detail),
                         ('payout_review', 'needs_review:payout_unknown:replay_window'))

    def test_validation_refusal_is_definite_and_retry_uses_a_new_key(self):
        ramp = self._pay(self._funded(), pagoasap_client(create=PagoAsapError('bad', status=400, code='bad_bank')))
        self.assertEqual(ve_send._phase(ramp), 'payout_failed')
        key = ve_send._section(ramp)['payout_key']
        ramp = ve_send.update_beneficiary(ramp, dict(BENEFICIARY, phone='584241234567'), operator='ops',
                                          reviewed_key=key, reviewed_revision=0)
        with self.assertRaises(ve_send.VeSendError):
            ve_send.retry_payout(ramp, operator='ops', reviewed_key=key, reviewed_revision=0)
        ramp = ve_send.retry_payout(ramp, operator='ops', reviewed_key=key, reviewed_revision=1)
        client = pagoasap_client()
        self._pay(ramp, client)
        self.assertEqual(client.create_payout.call_args.kwargs['idempotency_key'],
                         idempotency_key(f'{ramp.external_id}:payout:1'))
        self.assertEqual(client.create_payout.call_args.kwargs['phone'], '04241234567')

    def test_limit_and_allowlist_refusals_are_definite(self):
        for error in pagoasap_send.REFUSALS_403:
            ramp = self._pay(self._funded(), pagoasap_client(create=PagoAsapError(error, status=403, code=error)))
            self.assertEqual((ve_send._phase(ramp), ramp.status_detail),
                             ('payout_failed', f'needs_review:payout_failed:refused:{error}'))

    def test_other_forbidden_answers_stay_unknown(self):
        ramp = self._pay(self._funded(), pagoasap_client(create=PagoAsapError('x', status=403, code='Forbidden')))
        self.assertEqual(ve_send._phase(ramp), 'payout_review')

    def test_balance_reads_usd_under_either_symbol(self):
        from ramps.pagoasap_client import PagoAsapClient
        for symbol in ('USD', 'USDT'):
            client = PagoAsapClient.__new__(PagoAsapClient)
            with mock.patch.object(PagoAsapClient, '_request',
                                   return_value={'balances': [{'symbol': symbol, 'balance': '12.5'}]}):
                self.assertEqual(client.balances(), {'USD': Decimal('12.5')})

    def test_not_enough_funds_retries_with_a_fresh_key(self):
        ramp = self._pay(self._funded(), pagoasap_client())
        ramp = self._pay(ramp, pagoasap_client(intent={'state': 'failed', 'reason': 'not_enough_funds'}))
        self.assertEqual((ve_send._phase(ramp), ramp.status_detail), ('settled', 'waiting_balance'))
        client = pagoasap_client()
        self._pay(ramp, client)
        self.assertEqual(client.create_payout.call_args.kwargs['idempotency_key'],
                         idempotency_key(f'{ramp.external_id}:payout:1'))

    def test_bank_failure_is_definite(self):
        ramp = self._pay(self._funded(), pagoasap_client())
        ramp = self._pay(ramp, pagoasap_client(intent={'state': 'failed', 'reason': 'invalid_account'}))
        self.assertEqual((ve_send._phase(ramp), ramp.status_detail),
                         ('payout_failed', 'needs_review:payout_failed:invalid_account'))

    def test_refusal_after_a_timeout_is_not_proof_of_nonpayment(self):
        ramp = self._pay(self._funded(), pagoasap_client(create=PagoAsapAmbiguousError('timeout')))
        ve_send._update(ramp.pk, dispatch_lease_until=(timezone.now() - timedelta(seconds=1)).isoformat())
        ramp = self._pay(RampTransaction.objects.get(pk=ramp.pk),
                         pagoasap_client(create=PagoAsapError('bad', status=400)))
        self.assertEqual(ve_send._phase(ramp), 'payout_review')
        with self.assertRaises(ve_send.VeSendError):
            ve_send.retry_payout(ramp, operator='ops', reviewed_key=ve_send._section(ramp)['payout_key'],
                                 reviewed_revision=0)

    def test_late_answer_of_an_old_attempt_never_moves_a_new_one(self):
        ramp = self._pay(self._funded(), pagoasap_client(create=PagoAsapError('bad', status=400)))
        old_key = ve_send._section(ramp)['payout_key']
        ramp = ve_send.retry_payout(ramp, operator='ops', reviewed_key=old_key, reviewed_revision=0)
        ramp = self._pay(ramp, pagoasap_client(create=PagoAsapAmbiguousError('timeout')))
        ramp = ve_send.apply_outcome(ramp, Outcome('failed', reason='late'), old_key)
        self.assertEqual(ve_send._phase(ramp), 'paying')
        ramp = ve_send.apply_outcome(ramp, Outcome('paid', reference='x'), old_key)
        self.assertEqual(ramp.status, 'PROCESSING')

    def test_unknown_states_and_stale_pending_go_to_review(self):
        ramp = self._pay(self._funded(), pagoasap_client())
        ramp = self._pay(ramp, pagoasap_client(intent={'state': 'weird'}))
        self.assertEqual(ve_send._phase(ramp), 'payout_review')
        other = self._pay(self._funded(), pagoasap_client())
        ve_send._update(other.pk, pending_since=(timezone.now() - timedelta(hours=3)).isoformat())
        other = self._pay(RampTransaction.objects.get(pk=other.pk), pagoasap_client(intent={'state': 'processing'}))
        self.assertEqual(other.status_detail, 'needs_review:payout_pending_stale')

    def test_retry_needs_the_reviewed_attempt_and_no_live_dispatch(self):
        ramp = self._pay(self._funded(), pagoasap_client())
        ramp = self._pay(ramp, pagoasap_client(intent={'state': 'weird'}))
        key = ve_send._section(ramp)['payout_key']
        with self.assertRaises(ve_send.VeSendError):
            ve_send.retry_payout(ramp, operator='ops', reviewed_key='stale', reviewed_revision=0, confirmed_unpaid=True)
        ramp = ve_send.retry_payout(ramp, operator='ops', reviewed_key=key, reviewed_revision=0, confirmed_unpaid=True)
        self.assertEqual((ve_send._phase(ramp), ve_send._section(ramp)['payout_attempt']), ('settled', 1))
        with self.assertRaises(ve_send.VeSendError):
            ve_send.retry_payout(ramp, operator='ops', reviewed_key=key, reviewed_revision=0, confirmed_unpaid=True)

    def test_manual_paid_and_quiet_review(self):
        ramp = self._pay(self._funded(), pagoasap_client())
        ramp = self._pay(ramp, pagoasap_client(intent={'state': 'weird'}))
        self.assertFalse(ve_send.due_for_sync(ramp))
        with self.assertRaises(ve_send.VeSendError):
            ve_send.mark_paid_manually(ramp, '998877', operator='ops', reviewed_key='stale', reviewed_revision=0)
        ramp = ve_send.mark_paid_manually(ramp, '998877', operator='ops',
                                          reviewed_key=ve_send._section(ramp)['payout_key'], reviewed_revision=0)
        self.assertEqual((ramp.status, ve_send._section(ramp)['bank_reference']), ('COMPLETED', '998877'))

    @override_settings(VE_PAGOMOVIL_SEND_MIN_USD='', VE_PAGOMOVIL_SEND_MAX_USD='',
                       VE_PAGOMOVIL_SEND_USER_DAILY_USD='', VE_PAGOMOVIL_SEND_GLOBAL_DAILY_USD='')
    def test_no_caps_by_default(self):
        self._ramp(status='PROCESSING')
        ve_send.check_limits(self.user, Decimal('1'))
        ve_send.check_limits(self.user, Decimal('25000'))

    @override_settings(VE_PAGOMOVIL_SEND_USER_DAILY_USD='30')
    def test_limits_count_open_sends(self):
        self._ramp(status='PROCESSING')
        with self.assertRaises(ve_send.VeSendError):
            ve_send.check_limits(self.user, Decimal('15'))
        ve_send.check_limits(self.user, Decimal('10'))


class NeutralLayerTests(TestCase):
    def test_banks_are_ours_and_codes_validated(self):
        self.assertEqual(ve_pagomovil.normalize_bank('134'), '0134')
        with self.assertRaises(ve_pagomovil.VePagoMovilError):
            ve_pagomovil.normalize_bank('9999')

    def test_app_floor_per_direction(self):
        with override_settings(VE_PAGOMOVIL_SEND_MIN_APP_VERSION='5.2.8', VE_PAGOMOVIL_TOPUP_MIN_APP_VERSION=''):
            self.assertTrue(ve_pagomovil.client_supports(ve_pagomovil.SEND, {'HTTP_X_CONFIO_VERSION': '5.2.8'}))
            self.assertFalse(ve_pagomovil.client_supports(ve_pagomovil.SEND, {'HTTP_X_CONFIO_VERSION': '5.2.7'}))
            self.assertFalse(ve_pagomovil.client_supports(ve_pagomovil.TOPUP, {'HTTP_X_CONFIO_VERSION': '9.9.9'}))

    def test_provider_is_a_setting(self):
        with override_settings(VE_PAGOMOVIL_SEND_PROVIDER='pagoasap'):
            self.assertIs(ve_pagomovil.send_adapter(), pagoasap_send)
        with override_settings(VE_PAGOMOVIL_SEND_PROVIDER='nobody'):
            with self.assertRaises(ve_pagomovil.VePagoMovilError):
                ve_pagomovil.send_adapter()


class NeutralSchemaTests(TestCase):
    def test_quote_refusals_are_answers_not_crashes(self):
        from ramps import ve_pagomovil_schema as schema
        info = SimpleNamespace(context=SimpleNamespace(user=get_user_model().objects.create(
            username='q-ve', firebase_uid='q-ve'), META={}))
        with override_settings(VE_PAGOMOVIL_SEND_ENABLED=False, VE_PAGOMOVIL_TOPUP_ENABLED=False):
            send = schema.Query.resolve_ve_pagomovil_send_quote(None, info, '10')
            topup = schema.Query.resolve_ve_pagomovil_top_up_quote(None, info, '10')
        self.assertEqual((send.success, send.error), (False, schema.SEND_UNAVAILABLE))
        self.assertEqual((topup.success, topup.error), (False, schema.TOPUP_UNAVAILABLE))


class PublicNameTests(TestCase):
    def test_ve_orders_never_show_a_provider_name(self):
        for provider in ('vexpay', 'pagoasap'):
            ramp = RampTransaction(provider=provider, direction='on_ramp')
            self.assertEqual(ve_pagomovil.public_provider_name(ramp), 'Pago Móvil')
        self.assertEqual(ve_pagomovil.public_provider_name(RampTransaction(provider='koywe')), 'Koywe')


class PagoAsapWebhookTests(TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        self.key = Ed25519PrivateKey.generate()
        self.pem = self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        user = get_user_model().objects.create(username='wh-ve', firebase_uid='wh-ve')
        self.ramp = RampTransaction(provider='pagoasap', direction='off_ramp', status='PROCESSING', country_code='VE',
                                    actor_user=user, actor_address=WALLET, destination='cusd_plus',
                                    metadata={ve_send.SECTION: {'phase': 'payout_pending', 'operation_id': 'intent-7'}})
        self.ramp.external_id = str(self.ramp.internal_id)
        self.ramp.save()

    def _post(self, body: dict, sign=True):
        from ramps.views import pagoasap_webhook
        raw = json.dumps(body).encode()
        signature = base64.b64encode(self.key.sign(raw)).decode() if sign else 'AAAA'
        request = RequestFactory().post('/api/pagoasap/webhook/', data=raw, content_type='application/json',
                                        HTTP_X_WEBHOOK_SIGNATURE=signature)
        with override_settings(PAGOASAP_PAYMENT_WEBHOOK_PUBLIC_KEY=self.pem, PAGOASAP_DEPOSIT_WEBHOOK_PUBLIC_KEY=''), \
                mock.patch('ramps.tasks.sync_ve_pagomovil_order.delay') as delay:
            return pagoasap_webhook(request), delay

    def test_signed_payout_event_routes_to_its_send(self):
        response, delay = self._post({'version': 1, 'event': 'payment_intent_state_termination',
                                      'payload': {'state': 'completed', 'intent': {'id': 'intent-7'}}})
        self.assertEqual(response.status_code, 200)
        delay.assert_called_once_with(self.ramp.pk)

    def test_deposit_event_routes_by_sender(self):
        _, delay = self._post({'version': 1, 'event': 'blockchain_deposit_state_termination',
                               'payload': {'state': 'credited', 'movement': {'counterpartyAddress': WALLET.upper()}}})
        delay.assert_called_once_with(self.ramp.pk)

    def test_unsigned_is_rejected(self):
        response, delay = self._post({'event': 'x'}, sign=False)
        self.assertEqual(response.status_code, 403)
        delay.assert_not_called()
