from copy import deepcopy
from types import SimpleNamespace
import time
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from payment_accounts.relay import RelayClient, RelayError, CHAINS, PROTOCOL_CHAINS
from payment_accounts.allbridge_next import TOKENS, NextError
from payment_accounts.relay_settlement import reconcile_relay

SENDER = '0x' + '11' * 20
RECIPIENT = '0x' + '22' * 20
DEPOSIT = '0x' + '33' * 20
REQUEST = '0x' + '44' * 32
SOURCE_HASH = '0x' + '55' * 32
DEST_HASH = '0x' + '66' * 32


def response(source='BSC:USDT', destination='POL:USDC', amount='1982000000000000000'):
    out = '1950000' if destination == 'POL:USDC' else '1950000000000000000'
    minimum = str(int(out) * 995 // 1000)
    currency = lambda token: {'chainId': CHAINS[token], 'address': TOKENS[token][0], 'decimals': TOKENS[token][1]}
    return {'requestId': REQUEST, 'details': {
        'sender': SENDER, 'recipient': RECIPIENT,
        'currencyIn': {'currency': currency(source), 'amount': amount},
        'currencyOut': {'currency': currency(destination), 'amount': out, 'minimumAmount': minimum},
        'refundCurrency': {'currency': currency(source)}},
        'steps': [{'id': 'deposit', 'kind': 'transaction', 'requestId': REQUEST, 'depositAddress': DEPOSIT,
                   'items': [{'data': {'from': SENDER, 'to': TOKENS[source][0], 'value': '0',
                     'chainId': CHAINS[source], 'data': '0xa9059cbb' + DEPOSIT[2:].rjust(64, '0') + f'{int(amount):064x}'},
                     'check': {'method': 'GET', 'endpoint': '/intents/status/v3?requestId=' + REQUEST}}]}],
        'protocol': {'v2': {'orderData': {
            'inputs': [{'payment': {'chainId': PROTOCOL_CHAINS[source], 'currency': TOKENS[source][0], 'amount': amount},
                        'refunds': [{'chainId': PROTOCOL_CHAINS[source], 'currency': TOKENS[source][0], 'recipient': SENDER}]}],
            'output': {'chainId': PROTOCOL_CHAINS[destination], 'payments': [
                {'recipient': RECIPIENT, 'currency': TOKENS[destination][0], 'minimumAmount': minimum, 'expectedAmount': out}],
                'calls': [], 'deadline': int(time.time()) + 900}, 'fees': []}}}}


class RelayTests(SimpleTestCase):
    def setUp(self):
        self.session = mock.Mock()
        self.client = RelayClient(self.session)
        self.payload = response()

    def route(self, payload=None):
        self.session.request.return_value = mock.Mock(status_code=200, json=lambda: payload or self.payload)
        return self.client.routes('BSC:USDT', 'POL:USDC', '1982000000000000000', SENDER, RECIPIENT)[0]

    def test_small_deposit_quote_is_executable_without_arbitrary_calldata(self):
        route = self.route()
        build = self.client.build(route, source_address=SENDER, destination_address=RECIPIENT)
        self.assertEqual(build['relay']['request_id'], REQUEST)
        self.assertEqual(build['tx']['contractAddress'], TOKENS['BSC:USDT'][0])
        body = self.session.request.call_args.kwargs['json']
        self.assertEqual(body['amount'], '1982000000000000000')
        self.assertEqual(body['refundTo'], SENDER)
        self.assertTrue(body['useDepositAddress'])
        self.assertNotIn('strict', body)
        self.assertNotIn('appFees', body)
        # Relay's own tolerance is amount-aware; a fixed 50 bps refused small sends.
        self.assertNotIn('slippageTolerance', body)
        self.assertFalse(self.session.request.call_args.kwargs['allow_redirects'])

    def test_reverse_small_quote(self):
        payload = response('POL:USDC', 'BSC:USDT', '2000000')
        self.session.request.return_value = mock.Mock(status_code=200, json=lambda: payload)
        route = self.client.routes('POL:USDC', 'BSC:USDT', '2000000', SENDER, RECIPIENT)[0]
        self.assertEqual(route['messenger'], 'relay')

    def test_rejects_tampered_terms(self):
        mutations = [
            lambda p: p['details'].update(recipient=DEPOSIT),
            lambda p: p['details']['currencyOut']['currency'].update(chainId=56),
            lambda p: p['details']['currencyOut']['currency'].update(address=TOKENS['BSC:USDT'][0]),
            lambda p: p['details']['currencyIn'].update(amount='1'),
            lambda p: p['details']['currencyOut'].update(minimumAmount='1'),
            lambda p: p['protocol']['v2']['orderData']['inputs'][0]['refunds'][0].update(recipient=DEPOSIT),
            lambda p: p['protocol']['v2']['orderData']['output']['payments'][0].update(recipient=DEPOSIT),
            lambda p: p['protocol']['v2']['orderData']['output'].update(calls=[{}]),
            lambda p: p['steps'][0].update(depositAddress=RECIPIENT),
            lambda p: p['steps'][0]['items'][0]['data'].update(value='1'),
            lambda p: p['steps'][0]['items'][0]['data'].update(data='0x095ea7b3' + '0'*128),
            lambda p: p['steps'][0]['items'][0]['check'].update(endpoint='https://attacker.invalid/'),
            lambda p: p['protocol']['v2']['orderData']['output'].update(deadline=1),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                payload = deepcopy(self.payload)
                mutate(payload)
                with self.assertRaises(NextError):
                    self.route(payload)

    def shaped(self, amount, out, minimum, source='BSC:USDT', destination='POL:USDC'):
        """A quote whose input and output are consistent with each other."""
        payload = response(source, destination, amount)
        payload['details']['currencyOut'].update(amount=str(out), minimumAmount=str(minimum))
        payload['protocol']['v2']['orderData']['output']['payments'][0].update(
            expectedAmount=str(out), minimumAmount=str(minimum))
        self.session.request.return_value = mock.Mock(status_code=200, json=lambda: payload)
        return self.client.routes(source, destination, amount, SENDER, RECIPIENT)[0]

    def test_accepts_relays_amount_aware_tier_on_small_sends(self):
        # Live tiers on 2026-09-15: 335 bps at $2, 409 bps at $1. A fixed 0.5%
        # clamp rejected both; the dollar-denominated ceiling accepts them.
        for amount, out, bps in [('1982000000000000000', 1947372, 335),
                                 ('1000000000000000000', 913213, 409)]:
            with self.subTest(out=out, bps=bps):
                self.assertIsNotNone(self.shaped(amount, out, out - out * bps // 10000))

    def test_rejects_deterioration_above_the_confio_ceiling(self):
        # Floor binds between ~$1.50 and ~$6: $0.15 allowed, $0.25 refused.
        amount = '1982000000000000000'
        self.assertIsNotNone(self.shaped(amount, 1950000, 1950000 - 150000))
        with self.assertRaisesRegex(RelayError, 'allowed slippage'):
            self.shaped(amount, 1950000, 1950000 - 250000)

    def test_bps_ceiling_binds_on_larger_sends(self):
        # At $100 the 250 bps term ($2.50) is the binding limit, not the floor.
        amount = '100000000000000000000'
        self.assertIsNotNone(self.shaped(amount, 100_000000, 98_000000))
        with self.assertRaisesRegex(RelayError, 'allowed slippage'):
            self.shaped(amount, 100_000000, 97_000000)

    def test_dollar_floor_cannot_disable_the_ceiling_on_small_sends(self):
        # $0.15 is 15.7% of a $1 output, so the floor alone authorized almost
        # anything exactly where it applies. The 10% cap is what binds here.
        amount = '1000000000000000000'
        self.assertIsNotNone(self.shaped(amount, 913213, 913213 - 91321))
        with self.assertRaisesRegex(RelayError, 'allowed slippage'):
            self.shaped(amount, 913213, 913213 - 91322)

    def test_rejects_a_route_that_destroys_the_amount(self):
        # Relay prices tiny routes it cannot serve (observed $0.05 -> $0.0031)
        # rather than returning AMOUNT_TOO_LOW. 11.5% at $0.75 is legitimate.
        amount = '1000000000000000000'
        self.assertIsNotNone(self.shaped(amount, 760000, 760000))
        with self.assertRaisesRegex(RelayError, 'muy pequeño'):
            self.shaped(amount, 740000, 740000)

    def test_cost_backstop_covers_the_reverse_direction(self):
        out = 740000000000000000
        with self.assertRaisesRegex(RelayError, 'muy pequeño'):
            self.shaped('1000000', out, out, source='POL:USDC', destination='BSC:USDT')

    def test_cost_backstop_applies_to_authorized_minimum_not_expected(self):
        with self.assertRaisesRegex(RelayError, 'muy pequeño'):
            self.shaped('1000000000000000000', 760000, 740000)

    def test_safe_structured_error(self):
        self.session.request.return_value = mock.Mock(status_code=400, json=lambda: {'errorCode': 'AMOUNT_TOO_LOW', 'message': SENDER})
        with self.assertRaisesRegex(RelayError, 'too low') as caught:
            self.client.status(REQUEST)
        self.assertEqual(caught.exception.status_code, 400)
        self.assertNotIn(SENDER, str(caught.exception))

    def test_status_request_id_cannot_supply_url(self):
        with self.assertRaises(RelayError):
            self.client.status('https://attacker.invalid')
        self.session.request.assert_not_called()


class RelaySettlementTests(SimpleTestCase):
    def setUp(self):
        self.transfer = SimpleNamespace(quote=SimpleNamespace(source_token_id='BSC:USDT', destination_token_id='POL:USDC',
            source_address=SENDER, destination_address=RECIPIENT, amount_units=str(2*10**18)),
            binding={'request_id': REQUEST}, source_tx_hash=SOURCE_HASH,
            amount_out_min='1900000', status='bridging', failure_code='', deadline=int(time.time()) + 600)
        self.status = {'status': 'success', 'originChainId': 56, 'destinationChainId': 137,
                       'inTxHashes': [SOURCE_HASH], 'txHashes': [DEST_HASH]}
        self.client = mock.Mock()
        self.client.status.return_value = self.status

    def collection_fixture(self):
        from .test_bridge_execution import receipt
        self.transfer.deposit_address = DEPOSIT
        self.transfer.funding_mode = 'wallet'
        depository = '0x' + '77' * 20
        self.transfer.binding['response'] = {'protocol': {'v2': {'paymentDetails': {
            'chainId': 'bnb', 'currency': TOKENS['BSC:USDT'][0],
            'amount': self.transfer.quote.amount_units, 'depository': depository}}}}
        self.status['inTxHashes'] = [REQUEST]
        funding = receipt('BSC:USDT', DEPOSIT, 2*10**18)
        collection = receipt('BSC:USDT', depository, 2*10**18)
        funding.update(blockNumber='0x10', transactionIndex='0x1')
        collection.update(blockNumber='0x10', transactionIndex='0x2')
        funding['logs'][0]['topics'][1] = '0x' + SENDER[2:].rjust(64, '0')
        collection['logs'][0]['topics'][1] = '0x' + DEPOSIT[2:].rjust(64, '0')
        return [funding, collection, receipt('POL:USDC', RECIPIENT, 1934823)]

    def test_collection_hash_proves_deposit_delivery(self):
        receipts = self.collection_fixture()
        with mock.patch('payment_accounts.relay_settlement.chain.final_receipt', side_effect=receipts):
            reconcile_relay(self.transfer, client=self.client)
        self.assertEqual(self.transfer.status, 'delivered')
        self.assertEqual(self.transfer.actual_out_units, '1934823')
        self.assertEqual(self.transfer.binding['settlement_evidence']['origin_transaction_hashes'], [REQUEST])

    def refund_fixture(self, returned):
        """A Relay refund landing back in the user's own wallet."""
        from .test_bridge_execution import receipt
        receipts = self.collection_fixture()
        self.status['status'] = 'refund'
        receipts[2] = receipt('BSC:USDT', SENDER, returned)
        return receipts

    def test_refund_net_of_gas_is_complete_not_a_review(self):
        # The live refund on 2026-09-15 returned 1.947534 of 1.982 USDT. Relay
        # documents that gas is deducted, so exact equality never holds and
        # every refund used to land in needs_review, which blocks the wallet.
        returned = 2 * 10**18 - 34465742240440549
        with mock.patch('payment_accounts.relay_settlement.chain.final_receipt',
                        side_effect=self.refund_fixture(returned)):
            reconcile_relay(self.transfer, client=self.client)
        self.assertEqual(self.transfer.status, 'refunded')
        self.assertEqual(self.transfer.failure_code, 'relay_refunded')

    def test_short_refund_still_requires_review(self):
        # $0.30 missing is beyond any refund gas; a human still looks at it.
        with mock.patch('payment_accounts.relay_settlement.chain.final_receipt',
                        side_effect=self.refund_fixture(2 * 10**18 - 3 * 10**17)):
            reconcile_relay(self.transfer, client=self.client)
        self.assertEqual(self.transfer.status, 'needs_review')
        self.assertEqual(self.transfer.failure_code, 'relay_refund_amount_mismatch')

    def test_zero_received_is_never_a_complete_refund(self):
        self.transfer.quote.amount_units = str(10**17)
        self.status['status'] = 'refund'
        with mock.patch('payment_accounts.relay_settlement._source_evidence', return_value=True), \
             mock.patch('payment_accounts.relay_settlement.chain.final_receipt', return_value={}), \
             mock.patch('payment_accounts.relay_settlement.chain.received_units', return_value=0):
            reconcile_relay(self.transfer, client=self.client)
        self.assertEqual(self.transfer.status, 'needs_review')

    def test_refund_larger_than_the_deposit_requires_review(self):
        with mock.patch('payment_accounts.relay_settlement.chain.final_receipt',
                        side_effect=self.refund_fixture(2 * 10**18 + 1)):
            reconcile_relay(self.transfer, client=self.client)
        self.assertEqual(self.transfer.status, 'needs_review')

    def test_collection_rejects_unrelated_or_wrong_amount_receipts(self):
        for kind in ('sender', 'recipient', 'token', 'amount', 'earlier', 'funding'):
            with self.subTest(kind=kind):
                receipts = self.collection_fixture()
                log = receipts[1]['logs'][0]
                if kind == 'sender':
                    log['topics'][1] = '0x' + SENDER[2:].rjust(64, '0')
                elif kind == 'recipient':
                    log['topics'][2] = '0x' + SENDER[2:].rjust(64, '0')
                elif kind == 'token':
                    log['address'] = SENDER
                elif kind == 'amount':
                    log['data'] = '0x' + f'{1:064x}'
                elif kind == 'earlier':
                    receipts[1]['transactionIndex'] = '0x0'
                else:
                    receipts[0]['logs'][0]['data'] = '0x' + f'{1:064x}'
                with mock.patch('payment_accounts.relay_settlement.chain.final_receipt', side_effect=receipts):
                    with self.assertRaises(RelayError):
                        reconcile_relay(self.transfer, client=self.client)

    def test_collection_waits_for_finality(self):
        receipts = self.collection_fixture()
        with mock.patch('payment_accounts.relay_settlement.chain.final_receipt', side_effect=[receipts[0], None]):
            reconcile_relay(self.transfer, client=self.client)
        self.assertEqual(self.transfer.status, 'bridging')

    def test_collection_binding_cannot_change_token_chain_amount_or_depository(self):
        for key, value in [('chainId', 'polygon'), ('currency', SENDER), ('amount', '1'), ('depository', '0x'+'00'*20)]:
            self.collection_fixture()
            self.transfer.binding['response']['protocol']['v2']['paymentDetails'][key] = value
            with mock.patch('payment_accounts.relay_settlement.chain.final_receipt') as rpc:
                with self.assertRaises(RelayError):
                    reconcile_relay(self.transfer, client=self.client)
                rpc.assert_not_called()

    @mock.patch('payment_accounts.relay_settlement.chain.received_units', return_value=1950000)
    @mock.patch('payment_accounts.relay_settlement.chain.final_receipt', return_value={'finalized': True})
    def test_delivery_requires_receipt(self, receipt, units):
        reconcile_relay(self.transfer, client=self.client)
        self.assertEqual(self.transfer.status, 'delivered')
        self.assertEqual(self.transfer.actual_out_units, '1950000')
        units.assert_called_once_with({'finalized': True}, 'POL:USDC', RECIPIENT)

    @mock.patch('payment_accounts.relay_settlement.chain.final_receipt', return_value=None)
    def test_success_without_final_receipt_is_not_delivery(self, receipt):
        reconcile_relay(self.transfer, client=self.client)
        self.assertEqual(self.transfer.status, 'bridging')

    @mock.patch('payment_accounts.relay_settlement.chain.final_receipt', return_value=None)
    def test_success_without_receipt_eventually_requires_review(self, receipt):
        self.transfer.deadline = int(time.time()) - 3601
        reconcile_relay(self.transfer, client=self.client)
        self.assertEqual(self.transfer.status, 'needs_review')
        self.assertEqual(self.transfer.failure_code, 'relay_settlement_delayed')

    def test_unavailable_status_retries_then_requires_review(self):
        self.client.status.side_effect = RelayError('Relay is temporarily unavailable')
        with self.assertRaises(RelayError):
            reconcile_relay(self.transfer, client=self.client)
        self.transfer.deadline = int(time.time()) - 3601
        reconcile_relay(self.transfer, client=self.client)
        self.assertEqual(self.transfer.status, 'needs_review')
        self.assertEqual(self.transfer.failure_code, 'relay_settlement_delayed')

    @mock.patch('payment_accounts.relay_settlement.chain.final_receipt', side_effect=NextError('Bridge RPC unavailable'))
    def test_unavailable_destination_rpc_eventually_requires_review(self, receipt):
        self.transfer.deadline = int(time.time()) - 3601
        reconcile_relay(self.transfer, client=self.client)
        self.assertEqual(self.transfer.status, 'needs_review')

    def test_wrong_source_or_chain_or_duplicate_hash_is_rejected(self):
        for change in ({'inTxHashes': [DEST_HASH]}, {'destinationChainId': 56}, {'txHashes': [DEST_HASH, DEST_HASH]}):
            self.client.status.return_value = dict(self.status, **change)
            with self.assertRaises(RelayError):
                reconcile_relay(self.transfer, client=self.client)

    @mock.patch('payment_accounts.relay_settlement.chain.received_units', return_value=1)
    @mock.patch('payment_accounts.relay_settlement.chain.final_receipt', return_value={'finalized': True})
    def test_small_delivery_requires_review(self, receipt, units):
        reconcile_relay(self.transfer, client=self.client)
        self.assertEqual(self.transfer.status, 'needs_review')

    @mock.patch('payment_accounts.relay_settlement.chain.received_units', return_value=2*10**18)
    @mock.patch('payment_accounts.relay_settlement.chain.final_receipt', return_value={'finalized': True})
    def test_full_refund_requires_origin_receipt(self, receipt, units):
        self.status['status'] = 'refund'
        reconcile_relay(self.transfer, client=self.client)
        self.assertEqual(self.transfer.status, 'refunded')
        units.assert_called_once_with({'finalized': True}, 'BSC:USDT', SENDER)


@override_settings(PAYMENT_BRIDGE_QUOTES_ENABLED=True, PAYMENT_BRIDGE_BSC_ENABLED=True,
                   PAYMENT_BRIDGE_POLYGON_ENABLED=True, INFINIA_PAYMENT_ACCOUNTS_ENABLED=True,
                   CUSD_PLUS_7702_ENABLED=True)
class RelayIntegrationTests(TestCase):
    def setUp(self):
        from .test_bridge import BridgeQuoteTests
        BridgeQuoteTests.setUp(self)
        self.session = mock.Mock()
        self.relay = RelayClient(self.session)
        self.session.request.side_effect = lambda method, *args, **kwargs: mock.Mock(
            status_code=200, json=lambda: response() if method == 'POST' else {'status': 'waiting'})

    @override_settings(CUSD_VAULT_ADDRESS=SENDER)
    def test_bridge_redemption_is_owned_but_unrelated_deposits_are_not(self):
        from cusd_plus.tasks import _source_row_covers, _system_addresses
        from payment_accounts.models import PaymentBridgeTransfer
        self.test_quote_and_prepare_use_relay_and_retry_never_requotes()
        transfer = PaymentBridgeTransfer.objects.get(source_tx_hash=SOURCE_HASH)
        self.assertIn(SENDER.lower(), _system_addresses())
        self.assertTrue(_source_row_covers(SOURCE_HASH, transfer.quote.source_address))
        self.assertFalse(_source_row_covers(SOURCE_HASH, DEPOSIT))
        self.assertFalse(_source_row_covers(REQUEST, transfer.quote.source_address))
        transfer.funding_mode = 'infinia'
        transfer.save(update_fields=['funding_mode'])
        self.assertFalse(_source_row_covers(SOURCE_HASH, transfer.quote.source_address))

    @override_settings(CUSD_VAULT_ADDRESS=DEPOSIT)
    def test_existing_false_deposit_is_corrected_idempotently_without_balance_changes(self):
        from decimal import Decimal
        from cusd_plus.tasks import repair_payment_bridge_deposit
        from payment_accounts.models import PaymentBridgeTransfer
        from send.models import SendTransaction
        from notifications.models import Notification
        from users.models_unified import UnifiedTransactionTable
        from .test_bridge_execution import receipt
        self.test_quote_and_prepare_use_relay_and_retry_never_requotes()
        transfer = PaymentBridgeTransfer.objects.get(source_tx_hash=SOURCE_HASH)
        row = SendTransaction.all_objects.create(transaction_hash=SOURCE_HASH,
            sender_type='external', sender_address=DEPOSIT, recipient_address=SENDER,
            recipient_user=self.owner.user, token_type='USDT', amount=Decimal('1.982'),
            status='CONFIRMED')
        notice = Notification.objects.create(user=self.owner.user,
            notification_type='SEND_FROM_EXTERNAL', title='Depósito recibido', message='Original',
            related_object_type='SendTransaction', related_object_id=str(row.internal_id),
            data={'tx_hash': SOURCE_HASH, 'sender_address': DEPOSIT,
                  'recipient_address': SENDER, 'pending_auto_mint': True})
        # A real outside deposit with the same tx is not enough to repair it.
        repair_payment_bridge_deposit(transfer, receipt('BSC:USDT', SENDER, 1982000000000000000, sender=RECIPIENT))
        row.refresh_from_db()
        self.assertIsNone(row.deleted_at)
        valid = receipt('BSC:USDT', SENDER, 1982000000000000000, sender=DEPOSIT)
        repair_payment_bridge_deposit(transfer, valid)
        row.refresh_from_db(); notice.refresh_from_db()
        self.assertIsNotNone(row.deleted_at)
        self.assertEqual(row.amount, Decimal('1.982'))
        self.assertFalse(UnifiedTransactionTable.objects.filter(send_transaction=row, deleted_at__isnull=True).exists())
        self.assertEqual(notice.notification_type, 'CONVERSION_COMPLETED')
        self.assertFalse(notice.data['pending_auto_mint'])
        self.assertIsNone(notice.related_object_id)
        self.assertEqual(notice.data['corrected_deposit_notice']['message'], 'Original')
        stamp = row.deleted_at
        repair_payment_bridge_deposit(transfer, valid)
        row.refresh_from_db(); notice.refresh_from_db()
        self.assertEqual(row.deleted_at, stamp)
        self.assertEqual(notice.data['corrected_deposit_notice']['message'], 'Original')

    def test_quote_and_prepare_use_relay_and_retry_never_requotes(self):
        from payment_accounts.bridge import quote_provider_funding
        from payment_accounts.bridge_execution import prepare_bridge
        with mock.patch('payment_accounts.bridge_routing.RelayClient', return_value=self.relay):
            quote = quote_provider_funding(confio_account=self.owner,
                funding_instruction_id=self.instruction.internal_id, amount='1.982', request_id=self.request_id)
        self.assertEqual(quote.routes[0]['messenger'], 'relay')
        with mock.patch('payment_accounts.bridge_execution.chain.require_chain'), \
             mock.patch('payment_accounts.bridge_execution.funding_calls', return_value=([], {})):
            transfer = prepare_bridge(self.owner, quote.internal_id, client=self.relay)
            self.assertEqual(transfer.deposit_address, DEPOSIT)
            self.assertEqual(transfer.binding['provider'], 'relay')
            self.assertEqual(transfer.binding['request_id'], REQUEST)
            self.assertEqual(len(transfer.calls), 1)
            self.assertEqual(transfer.calls[0]['to'], TOKENS['BSC:USDT'][0])
            count = self.session.request.call_count
            self.assertEqual(prepare_bridge(self.owner, quote.internal_id, client=self.relay).pk, transfer.pk)
            self.assertEqual(self.session.request.call_count, count)
        from payment_accounts.bridge_execution import reconcile_bridge
        from .test_bridge_execution import receipt
        transfer.source_tx_hash, transfer.status = SOURCE_HASH, 'submitted'
        transfer.save(update_fields=['source_tx_hash', 'status'])
        status_client = mock.Mock()
        status_client.status.return_value = {'status': 'success', 'originChainId': 56,
            'destinationChainId': 137, 'inTxHashes': [SOURCE_HASH], 'txHashes': [DEST_HASH]}
        with mock.patch('payment_accounts.relay_settlement.RelayClient', return_value=status_client), \
             mock.patch('payment_accounts.bridge_execution.chain.final_receipt', side_effect=[
                 receipt('BSC:USDT', DEPOSIT, int(quote.amount_units)),
                 receipt('POL:USDC', RECIPIENT, 1950000)]):
            reconcile_bridge(transfer)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'delivered')
        self.assertEqual(transfer.binding['settlement_evidence']['transaction_hashes'], [DEST_HASH])
        self.assertEqual(transfer.actual_out_units, '1950000')
        self.assertIsNone(transfer.provider_credit_id)  # Receipt is not an Infinia ledger credit.

    def test_default_router_does_not_call_next(self):
        from payment_accounts.bridge_routing import quote_routes
        with mock.patch('payment_accounts.bridge_routing.RelayClient', return_value=self.relay), \
             mock.patch('payment_accounts.allbridge_next.NextClient') as old:
            self.assertEqual(quote_routes('BSC:USDT', 'POL:USDC', '1982000000000000000', SENDER, RECIPIENT)[0]['messenger'], 'relay')
            old.assert_not_called()
