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
        self.assertEqual(body['slippageTolerance'], '50')
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
