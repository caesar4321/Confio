"""A VE send funded by a contract (the Cuenta inteligente payout path): the
USDT Transfer comes from the cUSD vault, not from the wallet of record."""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from ramps import pagoasap_send, ve_send
from ramps.models import RampTransaction

WALLET = '0x' + '12' * 20   # the account contract (actor_address)
VAULT = '0x' + '5a' * 20    # the cUSD vault (redeemWithFee sends the USDT)
TARGET = '0x' + 'de' * 20
TX = '0x' + 'ab' * 32
TX2 = '0x' + 'cd' * 32
EXACT = 19_812_345_678_901_234_567  # an exact previewRedeem net, not cent-aligned
BENEFICIARY = {'cedula': 'V12345678', 'phone': '584141234567', 'bank_code': '0134'}

_ops_alert = mock.patch('config.ops_alerts.send_ops_alert', return_value=True)


def setUpModule():
    _ops_alert.start()


def tearDownModule():
    _ops_alert.stop()


def _topic(address):
    return '0x' + '0' * 24 + address[2:]


def transfer(sender, amount_wei=EXACT, to=TARGET, tx=TX):
    return {'address': ve_send.USDT_BSC, 'topics': [ve_send.TRANSFER_TOPIC, _topic(sender), _topic(to)],
            'data': hex(amount_wei), 'logIndex': '0x1', 'transactionHash': tx}


def chain(logs=(), head=0x3e8, receipt_value=None):
    seen = []

    def rpc(method, params):
        if method == 'eth_blockNumber':
            return hex(head)
        if method == 'eth_getBlockByNumber':
            if params[0] == 'finalized':
                return {'number': hex(head)}
            return {'hash': '0xb1'}
        if method == 'eth_getTransactionReceipt':
            return receipt_value
        seen.append(params[0])
        # Honour the topic filter the way a node does.
        topics = params[0].get('topics') or []
        return [log for log in logs
                if all(t is None or t.lower() == log['topics'][i].lower() for i, t in enumerate(topics))]
    rpc.seen = seen
    return rpc


def receipt(*logs):
    return {'status': '0x1', 'blockNumber': '0x3c0', 'blockHash': '0xb1', 'logs': list(logs)}


class ContractFundingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='ve-contract', firebase_uid='ve-contract')
        # These are ramps alone, with no rule behind the order: the executed
        # terms (smart_account.tests.test_payout_signed_terms) are given.
        executed = mock.patch('smart_account.payouts.ramp_funding_problem', return_value='')
        self.executed = executed.start()
        self.addCleanup(executed.stop)

    def _ramp(self, funding_sender=VAULT, **section):
        values = {'phase': 'funding_reported', 'gross_usd': '20.00', 'deposit_wei': str(EXACT),
                  'gross_wei': str(20 * 10 ** 18), 'deposit_address': TARGET, 'beneficiary': BENEFICIARY,
                  'beneficiary_revision': 0, 'estimated_ves': '19800.00', 'created_block': 1000,
                  'payout_attempt': 0, 'funding_started_at': timezone.now().isoformat()}
        if funding_sender:
            values['funding_sender'] = funding_sender
        values.update(section)
        ramp = RampTransaction(provider='pagoasap', direction='off_ramp', status='PENDING', country_code='VE',
                               actor_user=self.user, actor_address=WALLET, destination='cusd_plus',
                               fiat_currency='VES', crypto_currency='USDT', final_currency='USDT',
                               crypto_amount_estimated=Decimal('19.812345'), final_amount=Decimal('19.812345'),
                               metadata={ve_send.SECTION: values})
        ramp.external_id = str(ramp.internal_id)
        ramp.save()
        return ramp

    def _reserve(self, **kwargs):
        account = SimpleNamespace(pk=None, bsc_address=WALLET, display_name='')
        with mock.patch('users.models.Account.objects') as accounts:
            accounts.select_for_update.return_value.filter.return_value.first.return_value = \
                mock.Mock(bsc_address=WALLET)
            return ve_send.reserve(provider='pagoasap', user=self.user, account=account, gross_usd=Decimal('20'),
                                   beneficiary=BENEFICIARY, gross_wei=20 * 10 ** 18, deposit_wei=EXACT,
                                   created_block=1000, estimate={'estimated_ves': '19800', 'rate': '1000'},
                                   **kwargs)

    def test_flag_is_declared(self):
        self.assertIs(ve_send.CONTRACT_FUNDING, True)

    # ---- reserve

    def test_reserve_with_funding_sender_stores_it_and_keeps_the_exact_amount(self):
        ramp = self._reserve(funding_sender='  ' + VAULT.upper().replace('0X', '0x') + ' ')
        section = ve_send._section(ramp)
        self.assertEqual(section['funding_sender'], VAULT)
        self.assertEqual(int(section['deposit_wei']), EXACT)
        self.assertEqual(ramp.actor_address, WALLET)

    def test_reserve_without_funding_sender_is_unchanged(self):
        section = ve_send._section(self._reserve())
        self.assertNotIn('funding_sender', section)
        self.assertNotEqual(int(section['deposit_wei']), EXACT)  # tagged as before
        self.assertTrue(0 < EXACT - int(section['deposit_wei']) < 10 ** 16)

    def test_reserve_refuses_a_malformed_funding_sender(self):
        for bad in ('', 'vault', '0x1234', ve_send.USDT_BSC, '0x' + '0' * 40):
            with self.assertRaises(ve_send.VeSendError):
                self._reserve(funding_sender=bad)
        self.assertFalse(RampTransaction.objects.exists())

    def test_the_vault_cannot_be_the_deposit_target(self):
        ramp = self._ramp()
        self.assertFalse(ve_send._valid_target(ramp, VAULT))
        self.assertTrue(ve_send._valid_target(ramp, TARGET))

    # ---- funding proof

    def test_receipt_accepts_the_vault_and_refuses_the_actor(self):
        ramp = ve_send.report_funding(self._ramp(), TX, by_payout=True)
        refused = ve_send.sync(ramp, rpc=chain(receipt_value=receipt(transfer(WALLET))))
        self.assertEqual((refused.status, ve_send._phase(refused)), ('PENDING', 'funding_reported'))
        funded = ve_send.sync(ve_send.report_funding(self._ramp(), TX2, by_payout=True),
                              rpc=chain(receipt_value=receipt(transfer(VAULT, tx=TX2))))
        self.assertEqual((funded.status, ve_send._phase(funded)), ('PROCESSING', 'funded'))

    def test_never_found_by_a_log_scan(self):
        # Even the vault's exact transfer to the target is not this order's
        # proof unless its hash was reported: no eth_getLogs at all.
        rpc = chain(logs=[transfer(VAULT)], head=1500)
        ramp = ve_send.sync(self._ramp(), rpc=rpc)
        self.assertEqual((ramp.status, ve_send._phase(ramp)), ('PENDING', 'funding_reported'))
        self.assertEqual(rpc.seen, [])

    def test_without_funding_sender_only_the_actor_funds(self):
        ramp = ve_send.report_funding(self._ramp(funding_sender=None), TX)
        refused = ve_send.sync(ramp, rpc=chain(receipt_value=receipt(transfer(VAULT))))
        self.assertEqual(ve_send._phase(refused), 'funding_reported')
        funded = ve_send.sync(ve_send.report_funding(self._ramp(funding_sender=None), TX2),
                              rpc=chain(receipt_value=receipt(transfer(WALLET, tx=TX2))))
        self.assertEqual(ve_send._phase(funded), 'funded')
        rpc = chain(logs=[transfer(WALLET)], head=1500)
        self.assertEqual(ve_send._phase(ve_send.sync(self._ramp(funding_sender=None), rpc=rpc)), 'funded')
        self.assertEqual(rpc.seen[0]['topics'][1], _topic(WALLET))

    # ---- settlement

    def _proven(self, **kwargs):
        return self._ramp(phase='funded', funding_tx_hash=TX, funded_wei=str(EXACT),
                          bridge={'request_id': '0x' + '11' * 32, 'response': {}, 'deadline': 9999999999,
                                  'recipient': TARGET, 'amount_out': '19800000', 'amount_out_min': '19700000'},
                          **kwargs)

    def _settle(self, ramp):
        def delivered(transfer, client=None):
            transfer.status, transfer.actual_out_units, transfer.destination_tx_hash = 'delivered', '19770000', TX2
        with mock.patch('payment_accounts.relay_settlement.reconcile_relay', side_effect=delivered) as rec:
            result = pagoasap_send.settle(ramp)
        return result, rec.call_args.args[0]

    def test_settle_uses_contract_mode_and_keeps_the_refund_address(self):
        result, transfer = self._settle(self._proven())
        self.assertEqual(result.kind, 'delivered')
        self.assertEqual(transfer.funding_mode, 'contract')
        # A Relay refund returns to the account contract, never the vault.
        self.assertEqual(transfer.quote.source_address, WALLET)
        self.assertEqual(transfer.quote.amount_units, str(EXACT))

    def test_settle_without_funding_sender_stays_wallet_mode(self):
        _, transfer = self._settle(self._proven(funding_sender=None))
        self.assertEqual((transfer.funding_mode, transfer.quote.source_address), ('wallet', WALLET))

    def _sweep_evidence(self, mode, funded_units, received, payment_amount=EXACT):
        from payment_accounts import relay_settlement
        transfer = SimpleNamespace(
            quote=SimpleNamespace(source_token_id='BSC:USDT', amount_units=str(EXACT), source_address=WALLET),
            binding={'response': {'protocol': {'v2': {'paymentDetails': {
                'chainId': relay_settlement.PROTOCOL_CHAINS['BSC:USDT'],
                'currency': relay_settlement.TOKENS['BSC:USDT'][0], 'amount': str(payment_amount),
                'depository': '0x' + '99' * 20}}}}},
            source_tx_hash=TX, deposit_address=TARGET, funding_mode=mode, funded_units=funded_units)
        final = {'blockNumber': '0x1', 'transactionIndex': '0x1'}
        with mock.patch.object(relay_settlement.chain, 'final_receipt',
                               side_effect=[final, {'blockNumber': '0x2', 'transactionIndex': '0x0'}]), \
                mock.patch.object(relay_settlement.chain, 'received_units', return_value=received):
            return relay_settlement._source_evidence(transfer, [TX2])

    def test_an_accepted_vault_overfunding_settles_through_the_sweep(self):
        from payment_accounts.relay_settlement import RelayError
        over = EXACT + 5 * 10 ** 12
        # Contract mode with the proven funded amount: the sweep of that
        # whole balance is this order's collection.
        self.assertTrue(self._sweep_evidence('contract', str(over), over))
        # Still exact everywhere else: a wallet send, a contract send without
        # the funded amount, and never a funded amount below the quote.
        for mode, funded, received in (('wallet', str(over), over), ('contract', None, over),
                                       ('contract', str(EXACT - 1), EXACT - 1),
                                       ('contract', str(over), over + 1)):
            with self.assertRaises(RelayError, msg=(mode, funded, received)):
                self._sweep_evidence(mode, funded, received)
        self.assertTrue(self._sweep_evidence('contract', str(EXACT), EXACT))

    def test_settle_passes_the_proven_funded_amount_only_in_contract_mode(self):
        over = str(EXACT + 5 * 10 ** 12)
        proven = self._proven(funding_excess_wei=str(5 * 10 ** 12))
        proven.metadata[ve_send.SECTION]['funded_wei'] = over
        _, transfer = self._settle(proven)
        self.assertEqual((transfer.funding_mode, transfer.funded_units), ('contract', over))
        self.assertEqual(transfer.quote.amount_units, str(EXACT))  # Relay's quote is unchanged
        _, transfer = self._settle(self._proven(funding_sender=None))
        self.assertIsNone(transfer.funded_units)

    def test_relay_source_evidence_skips_the_sender_only_in_contract_mode(self):
        from payment_accounts import relay_settlement
        for mode, expected in (('contract', None), ('wallet', WALLET)):
            transfer = SimpleNamespace(
                quote=SimpleNamespace(source_token_id='BSC:USDT', amount_units=str(EXACT), source_address=WALLET),
                binding={'response': {'protocol': {'v2': {'paymentDetails': {
                    'chainId': relay_settlement.PROTOCOL_CHAINS['BSC:USDT'],
                    'currency': relay_settlement.TOKENS['BSC:USDT'][0], 'amount': str(EXACT),
                    'depository': '0x' + '99' * 20}}}}},
                source_tx_hash=TX, deposit_address=TARGET, funding_mode=mode)
            final = {'blockNumber': '0x1', 'transactionIndex': '0x1'}
            with mock.patch.object(relay_settlement.chain, 'final_receipt',
                                   side_effect=[final, {'blockNumber': '0x2', 'transactionIndex': '0x0'}]), \
                    mock.patch.object(relay_settlement.chain, 'received_units', return_value=EXACT) as units:
                self.assertTrue(relay_settlement._source_evidence(transfer, [TX2]))
            self.assertEqual(units.call_args_list[0].kwargs['sender'], expected)


class ContractFundingIsolationTests(TestCase):
    """Review fixes: per-user pending check, run N / run N+1 on a shared
    route, prompt close, overfunding from the vault."""
    setUp = ContractFundingTests.setUp
    _ramp = ContractFundingTests._ramp
    _reserve = ContractFundingTests._reserve

    def _open_manual(self):
        return self._ramp(funding_sender=None, phase='awaiting_funding')

    # ---- fix 1: per-user pending check

    def test_a_pending_payout_order_does_not_block_a_manual_send(self):
        self._ramp()  # contract-funded, PENDING
        manual = self._reserve()
        self.assertNotIn('funding_sender', ve_send._section(manual))
        self.assertIsNone(ve_send.active_order(self.user, 'pagoasap').metadata[ve_send.SECTION].get(
            'funding_sender'))

    def test_a_pending_manual_send_does_not_block_a_payout_order(self):
        self._open_manual()
        ramp = self._reserve(funding_sender=VAULT)
        self.assertEqual(ve_send._section(ramp)['funding_sender'], VAULT)

    def test_manual_sends_still_block_each_other(self):
        self._open_manual()
        with self.assertRaises(ve_send.VeSendError):
            self._reserve()

    def test_active_order_never_returns_a_payout_order(self):
        self._ramp()
        self.assertIsNone(ve_send.active_order(self.user, 'pagoasap'))

    def test_a_second_open_payout_order_of_the_same_account_and_amount_is_refused(self):
        self._ramp()  # same actor_address, same EXACT amount, PENDING
        with self.assertRaises(ve_send.VeSendError):
            self._reserve(funding_sender=VAULT)
        # A different amount is a different payout.
        ramp = ve_send.reserve(**self._reserve_kwargs(deposit_wei=EXACT - 10 ** 12))
        self.assertEqual(int(ve_send._section(ramp)['deposit_wei']), EXACT - 10 ** 12)

    def _reserve_kwargs(self, **over):
        account = SimpleNamespace(pk=None, bsc_address=WALLET, display_name='')
        patcher = mock.patch('users.models.Account.objects')
        accounts = patcher.start()
        self.addCleanup(patcher.stop)
        accounts.select_for_update.return_value.filter.return_value.first.return_value = mock.Mock(bsc_address=WALLET)
        kwargs = dict(provider='pagoasap', user=self.user, account=account, gross_usd=Decimal('20'),
                      beneficiary=BENEFICIARY, gross_wei=20 * 10 ** 18, deposit_wei=EXACT, created_block=1000,
                      estimate={'estimated_ves': '19800', 'rate': '1000'}, funding_sender=VAULT)
        kwargs.update(over)
        return kwargs

    def test_limits_still_count_payout_orders(self):
        self._ramp()
        with self.settings(VE_PAGOMOVIL_SEND_USER_DAILY_USD='30'):
            with self.assertRaises(ve_send.VeSendError):
                ve_send.check_limits(self.user, Decimal('20'), 'pagoasap')

    # ---- prompt close of an order no executeRule was sent for

    def test_close_unsent_closes_only_an_unreported_contract_order(self):
        closed = ve_send.close_unsent(self._ramp())
        self.assertEqual((closed.status, closed.status_detail), ('FAILED', 'payout_not_sent'))
        reported = ve_send.close_unsent(ve_send.report_funding(self._ramp(), TX, by_payout=True))
        self.assertEqual(reported.status, 'PENDING')
        manual = ve_send.close_unsent(self._ramp(funding_sender=None))
        self.assertEqual(manual.status, 'PENDING')

    def test_sync_closes_an_unreported_order_once_its_quote_is_long_dead(self):
        dead = int((timezone.now() - ve_send.CLAIMED_FUNDING_QUIET).timestamp()) - 60
        ramp = ve_send.sync(self._ramp(bridge={'deadline': dead}), rpc=chain())
        self.assertEqual((ramp.status, ramp.status_detail), ('FAILED', 'expired_unfunded'))
        alive = int(timezone.now().timestamp()) + 600
        self.assertEqual(ve_send.sync(self._ramp(bridge={'deadline': alive}), rpc=chain()).status, 'PENDING')

    # ---- fix 2: run N fails, run N+1 funds the same route and amount

    def test_run_n_closed_never_claims_run_n_plus_1s_transfer(self):
        first = ve_send.close_unsent(self._ramp())       # run N: executeRule never sent
        self.assertEqual(first.status_detail, 'payout_not_sent')
        second = self._ramp()                              # run N+1: same address, same amount
        rpc = chain(logs=[transfer(VAULT, tx=TX2)], head=1500,
                    receipt_value=receipt(transfer(VAULT, tx=TX2)))
        # The late watch over run N sees nothing: no reported hash, no scan.
        first = ve_send.sync(first, rpc=rpc)
        self.assertEqual((first.status, first.status_detail), ('FAILED', 'payout_not_sent'))
        self.assertIn(first, ve_send.open_sends())
        # Run N+1's own reported hash proves run N+1.
        second = ve_send.sync(ve_send.report_funding(second, TX2, by_payout=True), rpc=rpc)
        self.assertEqual((second.status, ve_send._phase(second)), ('PROCESSING', 'funded'))
        self.assertEqual(ve_send._section(second)['funding_tx_hash'], TX2)
        first = ve_send.sync(first, rpc=rpc)
        self.assertEqual(first.status, 'FAILED')
        self.assertNotIn('funding_tx_hash', ve_send._section(first))
        self.assertEqual(rpc.seen, [])

    def test_a_closed_orders_own_late_reported_hash_goes_to_review(self):
        closed = ve_send.close_unsent(self._ramp())
        closed = ve_send.report_funding(closed, TX, by_payout=True)
        self.assertEqual(ve_send._section(closed)['funding_tx_hashes'], [TX])
        late = ve_send.sync(closed, rpc=chain(receipt_value=receipt(transfer(VAULT))))
        self.assertEqual((late.status, late.status_detail, ve_send._phase(late)),
                         ('PROCESSING', 'needs_review:late_funding', 'payout_review'))

    def test_a_closed_wallet_send_does_not_take_reported_hashes(self):
        closed = self._ramp(funding_sender=None)
        type(closed).objects.filter(pk=closed.pk).update(status='FAILED', status_detail='expired_unfunded')
        self.assertNotIn('funding_tx_hashes', ve_send._section(ve_send.report_funding(closed, TX)))

    # ---- only the payout path drives a contract-funded order

    def test_owner_cannot_report_junk_hashes_on_a_contract_funded_order(self):
        ramp = ve_send.report_funding(self._ramp(), TX, by_payout=True)
        junk = ['0x' + f'{i:02x}' * 32 for i in range(1, 7)]
        for tx in junk:
            with self.assertRaises(ve_send.VeSendError):
                ve_send.report_funding(ramp, tx)   # the app mutation's call
        with self.assertRaises(ve_send.VeSendError):
            ve_send.report_funding(ramp, None)
        self.assertEqual(ve_send._section(RampTransaction.objects.get(pk=ramp.pk))['funding_tx_hashes'], [TX])

    def test_owner_cannot_cancel_or_claim_a_contract_funded_order(self):
        ramp = self._ramp(phase='awaiting_funding')
        with self.assertRaises(ve_send.VeSendError):
            ve_send.cancel(ramp, rpc=chain())
        with self.assertRaises(ve_send.VeSendError):
            ve_send.start_funding(ramp)
        ramp.refresh_from_db()
        self.assertEqual((ramp.status, ve_send._phase(ramp)), ('PENDING', 'awaiting_funding'))
        # The payout path still can.
        self.assertEqual(ve_send.cancel(ramp, rpc=chain(), by_payout=True).status_detail, 'cancelled_by_user')

    def test_a_wallet_send_is_still_the_owners_to_report_and_cancel(self):
        reported = ve_send.report_funding(self._ramp(funding_sender=None), TX)
        self.assertEqual(ve_send._section(reported)['funding_tx_hashes'], [TX])
        cancelled = ve_send.cancel(self._ramp(funding_sender=None, phase='awaiting_funding'), rpc=chain())
        self.assertEqual(cancelled.status_detail, 'cancelled_by_user')

    # ---- fix 4: the vault's exit may carry more than the order's amount

    def test_overfunding_from_the_vault_by_the_reported_hash_is_accepted_and_recorded(self):
        over = EXACT + 5 * 10 ** 12
        with self.settings(CUSD_VAULT_ADDRESS=VAULT):
            ramp = ve_send.report_funding(self._ramp(), TX, by_payout=True)
            funded = ve_send.sync(ramp, rpc=chain(receipt_value=receipt(transfer(VAULT, amount_wei=over))))
        section = ve_send._section(funded)
        self.assertEqual((funded.status, section['phase']), ('PROCESSING', 'funded'))
        self.assertEqual((section['funded_wei'], section['funding_excess_wei']), (str(over), str(5 * 10 ** 12)))

    def test_overfunding_is_refused_when_the_sender_is_not_the_vault(self):
        over = EXACT + 5 * 10 ** 12
        with self.settings(CUSD_VAULT_ADDRESS='0x' + '77' * 20):
            ramp = ve_send.report_funding(self._ramp(), TX, by_payout=True)
            refused = ve_send.sync(ramp, rpc=chain(receipt_value=receipt(transfer(VAULT, amount_wei=over))))
        self.assertEqual(ve_send._phase(refused), 'funding_reported')

    def test_an_order_whose_executed_rule_cannot_be_read_is_parked(self):
        self.executed.side_effect = None
        self.executed.return_value = 'run_not_found'
        with self.settings(CUSD_VAULT_ADDRESS=VAULT):
            ramp = ve_send.report_funding(self._ramp(), TX, by_payout=True)
            parked = ve_send.sync(ramp, rpc=chain(receipt_value=receipt(transfer(VAULT))))
        self.assertEqual((parked.status, ve_send._phase(parked), parked.status_detail),
                         ('PROCESSING', 'payout_review', 'needs_review:contract_funding_terms_changed'))

    def test_over_the_signed_gross_is_parked_whatever_the_rule_says(self):
        with self.settings(CUSD_VAULT_ADDRESS=VAULT):
            ramp = ve_send.report_funding(self._ramp(), TX, by_payout=True)
            parked = ve_send.sync(ramp, rpc=chain(
                receipt_value=receipt(transfer(VAULT, amount_wei=20 * 10 ** 18 + 1))))
        section = ve_send._section(parked)
        self.assertEqual((section['phase'], section['funding_terms_problem']),
                         ('payout_review', 'amount_above_signed'))
        self.assertEqual(section['funded_wei'], str(20 * 10 ** 18 + 1))      # tracked

    def test_underfunding_is_never_accepted(self):
        with self.settings(CUSD_VAULT_ADDRESS=VAULT):
            ramp = ve_send.report_funding(self._ramp(), TX, by_payout=True)
            refused = ve_send.sync(ramp, rpc=chain(receipt_value=receipt(transfer(VAULT, amount_wei=EXACT - 1))))
        self.assertEqual(ve_send._phase(refused), 'funding_reported')

    def test_a_wallet_send_still_needs_the_exact_amount(self):
        with self.settings(CUSD_VAULT_ADDRESS=WALLET):
            ramp = ve_send.report_funding(self._ramp(funding_sender=None), TX)
            refused = ve_send.sync(ramp, rpc=chain(receipt_value=receipt(transfer(WALLET, amount_wei=EXACT + 1))))
        self.assertEqual(ve_send._phase(refused), 'funding_reported')
