"""The outside of a CLABE / Pix payment rule, faked at HTTP: BSC and Polygon
JSON-RPC, Relay and Infinia, all behind requests.Session.request. Everything
on Confío's side of that boundary is the real code.

Fake values only. An unknown request is recorded and fails the test."""
import json
import uuid
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

import requests
from django.utils import timezone
from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import keccak

from payment_accounts.allbridge_next import TOKENS
from smart_account import abi

WAD = 10 ** 18
VAULT = '0x' + 'a1' * 20          # cUSD+
CUSD = '0x' + 'c1' * 20           # CusdVault
FACTORY = '0x' + 'fa' * 20
SPONSOR = '0x' + '5a' * 20
DEPOSITORY = '0x' + 'd0' * 20
SOLVER = '0x' + '70' * 20
OWNER_INFINIA = '0x' + '1f' * 20  # the owner's Infinia Polygon funding address
USDT = TOKENS['BSC:USDT'][0]
USDC = TOKENS['POL:USDC'][0]
TRANSFER = '0x' + keccak(text='Transfer(address,address,uint256)').hex()
POL_URL = 'https://pol.example.invalid'
BSC_URL = 'https://bsc.example.invalid'
INFINIA_URL = 'https://infinia.example.invalid/api'
RELAY_KEY = 'fake-relay-key'
RATES = {'MXN': Decimal('18.50'), 'BRL': Decimal('5.40')}


def word_address(value):
    return '0x' + value[2:].lower().rjust(64, '0')


def transfer_log(token, sender, recipient, amount):
    return {'address': token, 'topics': [TRANSFER, word_address(sender), word_address(recipient)],
            'data': f'0x{int(amount):064x}', 'removed': False}


def selector(signature):
    return keccak(text=signature)[:4].hex()


class Response:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status
        self.ok = 200 <= status < 300
        self.text = json.dumps(body)
        self.headers = {}

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f'HTTP {self.status_code}')


class Revert(Exception):
    pass


class World:
    def __init__(self):
        self.unknown = []
        self.log = []               # (service, what)
        # chains
        self.head = {'BSC': 1000, 'POL': 5000}
        self.mined = {'BSC': {}, 'POL': {}}
        self.signed = {}            # raw -> (hash, tx)
        self.held = []              # broadcast, not mined yet
        self.hold_broadcast = False
        self.revert_simulation = False
        self.revert_mined = False
        self.balances = {}
        self.rules = {}
        self.fee_bps = 90
        self.p_plus = WAD
        self.accounts = {}          # contract -> owner wallet
        self._nonce = 0
        # Relay
        self.orders = []
        self.requests = {}          # request id -> its /requests/v3 row and /intents/status/v3 answer
        self.publish_deposit_hash = True
        self.recovery_recorded = None   # else what the quote sent
        self.depositor = None
        self.quote_error = None     # (status, body)
        self.same_deposit = None
        self.relay_fixed = Decimal('0.043')
        self.relay_share = Decimal('0.0019')
        # Infinia
        self.rates = dict(RATES)
        self.account_assets = {}    # provider account id -> asset
        self.quotes, self.transfers, self.payouts = {}, [], []
        self.payout_answer = 'COMPLETED'
        self.fx_error = None

    # ── transport ──────────────────────────────────────────────────────

    def request(self, session, method, url, **kwargs):
        body, params = kwargs.get('json'), kwargs.get('params') or {}
        if isinstance(body, dict) and body.get('jsonrpc'):
            chain = 'POL' if url.startswith(POL_URL) else 'BSC'
            try:
                return Response({'jsonrpc': '2.0', 'id': 1,
                                 'result': self.rpc(chain, body['method'], body['params'])})
            except Revert as exc:
                return Response({'jsonrpc': '2.0', 'id': 1,
                                 'error': {'code': 3, 'message': f'execution reverted: {exc}'}})
        if url.startswith('https://api.relay.link'):
            return self.relay(method, url[len('https://api.relay.link'):], body, params,
                              kwargs.get('headers') or {})
        if url.startswith(INFINIA_URL):
            return self.infinia(method, url[len(INFINIA_URL):], body, params)
        self.unknown.append((method, url))
        raise requests.ConnectionError(f'unexpected request {method} {url}')

    def count(self, service, what):
        return sum(1 for entry in self.log if entry == (service, what))

    # ── chains ─────────────────────────────────────────────────────────

    def mine(self, chain, tx_hash, logs, status=1):
        self.head[chain] += 1
        number = self.head[chain]
        receipt = {'transactionHash': tx_hash, 'status': hex(status), 'blockNumber': hex(number),
                   'blockHash': '0x' + format(number, 'x').rjust(64, '0'), 'transactionIndex': '0x0', 'logs': []}
        for index, entry in enumerate(logs):
            receipt['logs'].append(dict(entry, transactionHash=tx_hash, blockNumber=receipt['blockNumber'],
                                        logIndex=hex(index)))
        self.mined[chain][tx_hash.lower()] = receipt
        return receipt

    def new_hash(self):
        return '0x' + uuid.uuid4().hex + uuid.uuid4().hex

    def sign(self, tx):
        tx_hash = self.new_hash()
        raw = '0xraw' + tx_hash[2:]
        self.signed[raw] = (tx_hash, tx)
        return raw, tx_hash

    def fee(self, gross):
        return -(-gross * self.fee_bps // 10_000)

    def execute_rule(self, account, calldata):
        """ConfioSmartAccount._runPayout + CusdVault.redeemWithFee."""
        name, args = abi.decode_call(calldata)
        if name != 'executeRule':
            raise Revert(name)
        rule_id, data = args[0], bytes(args[1])
        rule = self.rules.get((account.lower(), rule_id))
        if rule is None or not rule['active']:
            raise Revert('BadRule')
        if rule['next_run_at'] > int(timezone.now().timestamp()):
            raise Revert('TooEarly')
        plus = rule['token_in'].lower() == VAULT
        if plus:
            destination, minimum, gross = abi_decode(['address', 'uint256', 'uint256'], data)
            if not 0 < gross <= rule['amount_usd_wei']:
                raise Revert('BadAmount')
            spent = (gross + gross * 5 // 10_000) * WAD // self.p_plus
        else:
            if len(data) != 64:
                raise Revert('BadCall')
            destination, minimum = abi_decode(['address', 'uint256'], data)
            gross = spent = rule['amount_usd_wei']
        out = gross - self.fee(gross)
        if out < minimum or (plus and out != minimum):
            raise Revert('Slippage')
        return rule_id, rule, destination.lower(), spent, out

    def mine_execute(self, tx_hash, tx):
        account = tx['to'].lower()
        try:
            if self.revert_mined:
                raise Revert('forced')
            rule_id, rule, destination, spent, out = self.execute_rule(account, tx['data'])
        except Revert:
            return self.mine('BSC', tx_hash, [], status=0)
        rule['next_run_at'] = int(timezone.now().timestamp()) + abi.MIN_GAP_DAYS[rule['frequency']] * 86400
        events = []
        for name, values in (
                ('PayoutSent', [rule_id, bytes.fromhex(rule['payout_ref'][2:]), destination, rule['token_in'],
                                spent, out]),
                ('RuleExecuted', [rule_id, rule['token_in'], USDT, spent, out])):
            fields = abi.ACCOUNT_EVENTS[name]
            topics = [abi.event_topic(name, fields)]
            plain_types, plain_values = [], []
            for (kind, indexed, _arg), value in zip(fields, values):
                if indexed:
                    topics.append('0x' + abi_encode([kind], [value]).hex())
                else:
                    plain_types.append(kind)
                    plain_values.append(value)
            events.append({'address': account, 'topics': topics, 'removed': False,
                           'data': '0x' + abi_encode(plain_types, plain_values).hex()})
        return self.mine('BSC', tx_hash, [transfer_log(USDT, CUSD, destination, out)] + events)

    def mine_held(self):
        held, self.held = self.held, []
        return [self.mine_execute(tx_hash, tx) for tx_hash, tx in held]

    def eth_call(self, chain, call):
        to, data = call['to'].lower(), call['data'].lower()
        sel, args = data[2:10], bytes.fromhex(data[10:])
        enc = lambda types, values: '0x' + abi_encode(types, values).hex()
        if sel == selector('executeRule(uint256,bytes,address,uint256)'):
            if self.revert_simulation:
                raise Revert('forced')
            self.execute_rule(to, data)
            return '0x'
        if sel == selector('balanceOf(address)'):
            holder = abi_decode(['address'], args)[0].lower()
            return enc(['uint256'], [self.balances.get((to, holder), 0)])
        if to == CUSD:
            if sel == selector('feeBps()'):
                return enc(['uint256'], [self.fee_bps])
            if sel == selector('previewRedeem(uint256)'):
                gross = abi_decode(['uint256'], args)[0]
                return enc(['uint256', 'uint256'], [self.fee(gross), gross - self.fee(gross)])
            if sel == selector('paused()'):
                return enc(['bool'], [False])
        if to == VAULT:
            if sel == selector('pPlus()'):
                return enc(['uint256'], [self.p_plus])
            if sel == selector('lastOraclePrice()'):
                return enc(['uint256'], [WAD])
            if sel == selector('CONFIO_YIELD_SHARE_BPS()'):
                return enc(['uint256'], [1500])
        if to == FACTORY and sel == selector('relayerPaused()'):
            return enc(['bool'], [False])
        if to in self.accounts:
            if sel == selector('owner()'):
                return enc(['address'], [self.accounts[to]])
            for name, value in (('status', 1), ('billingStatus', 0), ('inherited', 0), ('claimStatus', 0),
                                ('claimStartedAt', 0)):
                if sel == selector(f'{name}()'):
                    return enc(['uint256'], [value])
            if sel == selector('rule(uint256)'):
                rule = self.rules[(to, abi_decode(['uint256'], args)[0])]
                return enc([abi.RULE_ABI], [(
                    abi.RULE_PAYOUT, abi.FREQUENCY_IDS[rule['frequency']], rule['active'], rule['token_in'],
                    abi.ZERO_ADDRESS, abi.ZERO_ADDRESS, bytes.fromhex(rule['payout_ref'][2:]),
                    rule['amount_usd_wei'], rule['next_run_at'], rule['epoch'])])
        self.unknown.append(('eth_call', to, sel))
        raise Revert('unknown view')

    def rpc(self, chain, method, params):
        self.log.append((chain, method))
        if method == 'eth_chainId':
            return hex(56 if chain == 'BSC' else 137)
        if method == 'eth_blockNumber':
            return hex(self.head[chain])
        if method == 'eth_getBlockByNumber':
            number = self.head[chain] if params[0] in ('finalized', 'latest') else int(params[0], 16)
            return {'number': hex(number), 'hash': '0x' + format(number, 'x').rjust(64, '0'),
                    'timestamp': hex(int(timezone.now().timestamp()))}
        if method == 'eth_getTransactionReceipt':
            return self.mined[chain].get(params[0].lower())
        if method == 'eth_getTransactionByHash':
            receipt = self.mined[chain].get(params[0].lower())
            return {'hash': params[0]} if receipt else None
        if method == 'eth_getCode':
            return '0x60'
        if method == 'eth_gasPrice':
            return hex(100_000_000)
        if method == 'eth_getTransactionCount':
            self._nonce += 1
            return hex(self._nonce)
        if method == 'eth_getBalance':
            return hex(WAD)
        if method == 'eth_call':
            return self.eth_call(chain, params[0])
        if method == 'eth_sendRawTransaction':
            tx_hash, tx = self.signed[params[0]]
            if self.hold_broadcast:
                self.held.append((tx_hash, tx))
            else:
                self.mine_execute(tx_hash, tx)
            return tx_hash
        if method == 'eth_getLogs':
            query = params[0]
            wanted = query.get('address')
            wanted = [wanted] if isinstance(wanted, str) else list(wanted or [])
            wanted = {a.lower() for a in wanted}
            if USDT.lower() in wanted:
                self.unknown.append(('eth_getLogs', 'USDT'))     # funding is never found by a scan
            low, high = int(query['fromBlock'], 16), int(query['toBlock'], 16)
            return [entry for receipt in self.mined[chain].values()
                    if low <= int(receipt['blockNumber'], 16) <= high
                    for entry in receipt['logs'] if entry['address'].lower() in wanted]
        self.unknown.append((chain, method))
        raise Revert(method)

    # ── Relay ──────────────────────────────────────────────────────────

    def relay(self, method, path, body, params, headers):
        self.log.append(('relay', path))
        if path == '/quote/v2':
            if self.quote_error:
                return Response(self.quote_error[1], self.quote_error[0])
            return Response(self.relay_quote(body))
        if path == '/intents/status/v3':
            if params['requestId'] in self.requests:
                return Response(self.requests[params['requestId']]['status'])
            order = next(o for o in self.orders if o['request_id'] == params['requestId'])
            return Response(order['status'])
        if path == '/requests/v3':
            if headers.get('x-api-key') != RELAY_KEY:
                return Response({'error': 'UNAUTHORIZED'}, 401)
            rows = [dict(id=o['request_id'], status=o['status']['status'],
                         depositAddress={'address': o['deposit'], 'type': 'strict', 'depositTxHash': None})
                    for o in self.orders if o['request_id'] not in self.requests]
            rows += [r['row'] for r in self.requests.values()]
            address, tx = params.get('depositAddress'), params.get('depositTxHash')
            if address:
                rows = [r for r in rows if r['depositAddress']['address'].lower() == address.lower()
                        and not r.get('child')]
            if tx:
                rows = [r for r in rows if (r['depositAddress']['depositTxHash'] or '').lower() == tx.lower()]
            return Response({'requests': rows})
        self.unknown.append(('relay', path))
        return Response({}, 404)

    def relay_quote(self, body):
        amount = int(body['amount'])
        dollars = Decimal(amount) / WAD
        out = int((dollars - self.relay_fixed - dollars * self.relay_share) * 10 ** 6)
        out = max(out, 1)
        minimum = out - out * 200 // 10_000
        number = len(self.orders) + 1
        deposit = self.same_deposit or '0x' + keccak(text=f'deposit-{id(self)}-{number}')[:20].hex()
        request_id = '0x' + keccak(text=f'request-{id(self)}-{number}').hex()
        currency = lambda chain_id, token, decimals: {'chainId': chain_id, 'address': token, 'decimals': decimals}
        source = currency(56, USDT, 18)
        response = {
            'requestId': request_id,
            'details': {
                'sender': body['user'], 'recipient': body['recipient'],
                'currencyIn': {'currency': source, 'amount': body['amount']},
                'currencyOut': {'currency': currency(137, USDC, 6), 'amount': str(out), 'minimumAmount': str(minimum)},
                'refundCurrency': {'currency': source}},
            'steps': [{'id': 'deposit', 'kind': 'transaction', 'requestId': request_id, 'depositAddress': deposit,
                       'items': [{'data': {'from': body['user'], 'to': USDT, 'value': '0', 'chainId': 56,
                                           'data': '0xa9059cbb' + deposit[2:].rjust(64, '0') + f'{amount:064x}'},
                                  'check': {'method': 'GET',
                                            'endpoint': '/intents/status/v3?requestId=' + request_id}}]}],
            'protocol': {'v2': {
                'paymentDetails': {'chainId': 'bnb', 'currency': USDT, 'amount': body['amount'],
                                   'depository': DEPOSITORY},
                'orderData': {
                    'inputs': [{'payment': {'chainId': 'bnb', 'currency': USDT, 'amount': body['amount']},
                                'refunds': [{'chainId': 'bnb', 'currency': USDT, 'recipient': body['refundTo']}]}],
                    'output': {'chainId': 'polygon', 'calls': [],
                               'deadline': int(timezone.now().timestamp()) + 900,
                               'payments': [{'recipient': body['recipient'], 'currency': USDC,
                                             'minimumAmount': str(minimum), 'expectedAmount': str(out)}]},
                    'fees': []}}}}
        self.orders.append({'request_id': request_id, 'deposit': deposit, 'amount': amount, 'out': out,
                            'minimum': minimum, 'body': body, 'status': {'status': 'waiting'}})
        return response

    def deposited(self, deposit):
        return sum(int(entry['data'], 16) for receipt in self.mined['BSC'].values() for entry in receipt['logs']
                   if entry['address'] == USDT and entry['topics'][0] == TRANSFER
                   and entry['topics'][2] == word_address(deposit))

    def deposits_to(self, deposit):
        """(tx hash, amount, sender) of each transfer into the address, in order."""
        found = []
        for receipt in self.mined['BSC'].values():
            for entry in receipt['logs']:
                if (entry['address'].lower() == USDT.lower() and entry['topics'][0] == TRANSFER
                        and entry['topics'][2] == word_address(deposit)):
                    found.append((receipt['transactionHash'], int(entry['data'], 16), entry['topics'][1]))
        return found

    def stranger_pays(self, deposit, amount):
        tx = self.new_hash()
        self.mine('BSC', tx, [transfer_log(USDT, '0x' + 'ba' * 20, deposit, amount)])
        return tx

    def settle(self, order, deposit_tx, request_id, status, *, child=False):
        """Relay's two views of the request one deposit got."""
        request_id = request_id or order['request_id']
        row = {'id': request_id, 'status': status['status'], 'child': child,
               'depositAddress': {'address': order['deposit'], 'type': 'strict',
                                  'recoveryAddress': self.recovery_recorded or order['body'].get('recoveryAddress'),
                                  'depositTxHash': deposit_tx if self.publish_deposit_hash else None}}
        if self.depositor:
            row['protocol'] = {'deposit': {'origin': {'depositor': self.depositor}}}
        self.requests[request_id] = {'row': row, 'status': status}
        if request_id == order['request_id']:
            order['status'] = status

    def deposit_of(self, order, deposit_tx=None):
        found = self.deposits_to(order['deposit'])
        if deposit_tx:
            return next(d for d in found if d[0] == deposit_tx)
        ours = [d for d in found if d[2] == word_address(CUSD)]
        return (ours or found or [(None, 0, None)])[-1]

    def relay_fills(self, order=None, out=None, deposit_tx=None, request_id=None):
        order = order or self.orders[-1]
        deposit_tx, received, _ = self.deposit_of(order, deposit_tx)
        sweep = self.mine('BSC', self.new_hash(),
                          [transfer_log(USDT, order['deposit'], DEPOSITORY, received)])
        out = order['out'] if out is None else out
        fill = self.mine('POL', self.new_hash(), [transfer_log(USDC, SOLVER, order['body']['recipient'], out)])
        self.settle(order, deposit_tx, request_id, {
            'status': 'success', 'originChainId': 56, 'destinationChainId': 137,
            'inTxHashes': [sweep['transactionHash']], 'txHashes': [fill['transactionHash']]})
        return fill['transactionHash'], out

    def relay_refunds(self, order=None, kept=34_466_000_000_000_000, to=None, deposit_tx=None, request_id=None,
                      destination_chain=137, child=False):
        order = order or self.orders[-1]
        deposit_tx, received, _ = self.deposit_of(order, deposit_tx)
        sweep = self.mine('BSC', self.new_hash(),
                          [transfer_log(USDT, order['deposit'], DEPOSITORY, received)])
        back = self.mine('BSC', self.new_hash(), [transfer_log(
            USDT, SOLVER, to or order['body']['refundTo'], received - kept)])
        self.settle(order, deposit_tx, request_id, {
            'status': 'refund', 'originChainId': 56, 'destinationChainId': destination_chain,
            'inTxHashes': [sweep['transactionHash']], 'txHashes': [back['transactionHash']]}, child=child)
        return received - kept

    def relay_fails(self, refund_fail_reason=None, order=None, request_id=None):
        order = order or self.orders[-1]
        deposit_tx, received, _ = self.deposit_of(order)
        sweep = self.mine('BSC', self.new_hash(), [transfer_log(USDT, order['deposit'], DEPOSITORY, received)])
        self.settle(order, deposit_tx, request_id, {
            'status': 'failure', 'originChainId': 56, 'destinationChainId': 137,
            'inTxHashes': [sweep['transactionHash']], 'txHashes': [], 'refundFailReason': refund_fail_reason})

    # ── Infinia ────────────────────────────────────────────────────────

    def infinia(self, method, path, body, params):
        self.log.append(('infinia', f'{method} {path}'))
        if path == '/v1/accounts/internal-transfer/quote/':
            if self.fx_error:
                return Response(self.fx_error[1], self.fx_error[0])
            asset = self.account_assets[body['target_account_id']]
            source = Decimal(str(body['source_amount']))
            target = (source * self.rates[asset]).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
            quote = {'id': f'quote-{len(self.quotes) + 1}', 'status': 'ACTIVE',
                     'expire_at': (timezone.now() + timedelta(minutes=2)).isoformat(),
                     'source_account_id': body['source_account_id'], 'target_account_id': body['target_account_id'],
                     'source_amount': float(source), 'target_amount': float(target)}
            self.quotes[quote['id']] = quote
            return Response(quote)
        if path == '/v1/accounts/internal-transfer/' and method == 'POST':
            row = dict(body, id=f'transfer-{uuid.uuid4().hex}', status='COMPLETED',
                       destination_amount=self.quotes[body['quote_id']]['target_amount'])
            self.transfers.append(row)
            return Response(row)
        if path == '/v2/payouts/' and method == 'POST':
            if self.payout_answer == 'REFUSED':
                return Response({'status': 'fail', 'message': 'Invalid destination'}, 400)
            row = dict(body, id=f'payout-{uuid.uuid4().hex}', status=self.payout_answer)
            self.payouts.append(row)
            return Response(row)
        self.unknown.append(('infinia', method, path))
        return Response({}, 404)
