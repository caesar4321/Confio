"""CoW solver round trip for an Ondo GM stock token on BNB Smart Chain.

Proves that a self-custody wallet can buy and then sell an Ondo stock token
through CoW Protocol solvers, with no Duende purchaser of record in between.

The test wallet is a dedicated EOA whose key lives in AWS Secrets Manager
(never only on disk). Every step that spends funds asks for the literal
`execute bsc` before broadcasting.

Usage (from the repo root):
    AWS_PROFILE=Julian myvenv/bin/python scripts/ops/cow_solver_roundtrip.py init
    AWS_PROFILE=Julian myvenv/bin/python scripts/ops/cow_solver_roundtrip.py status
    AWS_PROFILE=Julian myvenv/bin/python scripts/ops/cow_solver_roundtrip.py quote buy 10
    AWS_PROFILE=Julian myvenv/bin/python scripts/ops/cow_solver_roundtrip.py buy 10
    AWS_PROFILE=Julian myvenv/bin/python scripts/ops/cow_solver_roundtrip.py sell
    AWS_PROFILE=Julian myvenv/bin/python scripts/ops/cow_solver_roundtrip.py report
    AWS_PROFILE=Julian myvenv/bin/python scripts/ops/cow_solver_roundtrip.py sweep 0xYourAddress

Fund the address printed by `init` with about 11 USDT (BSC) and 0.0005 BNB
(only the two token approvals need gas; CoW settles the swaps).
"""
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

import boto3
import requests
from eth_abi import encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_checksum_address

RPC = 'https://bsc-dataseed.bnbchain.org'
CHAIN_ID = 56
COW_API = 'https://api.cow.fi/bnb/api/v1'
SETTLEMENT = '0x9008D19f58AAbD9eD0D60971565AA8510560ab41'
VAULT_RELAYER = '0xC92E8bdf79f0507f65a392b0ab4667716BFE0110'
EXPECTED_DOMAIN_SEPARATOR = '0x0cbb18dfca28d2ceac8c72a17289168e03c1ad121338f5573e3b0c3255207fc7'
USDT = to_checksum_address('0x55d398326f99059fF775485246999027B3197955')
STOCK_SYMBOL = 'AAPLon'
STOCK = to_checksum_address('0x390a684ef9cade28a7ad0dfa61ab1eb3842618c4')
DECIMALS = 18
SLIPPAGE_BPS = 100          # buyAmount floor = quote * (1 - 1%)
ORDER_TTL_SECONDS = 20 * 60
SECRET_NAME = 'ops/cow-solver-test-wallet'
SECRET_REGION = 'eu-central-2'
APP_DATA = json.dumps({'appCode': 'Confio', 'metadata': {}, 'version': '1.3.0'}, separators=(',', ':'))
LOG = Path(__file__).with_name('cow_solver_roundtrip.log.json')
CONFIRM = 'execute bsc'


# ---------------- chain helpers ----------------
def rpc(method, params):
    r = requests.post(RPC, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}, timeout=30).json()
    if 'error' in r:
        raise RuntimeError(f'{method}: {r["error"]}')
    return r['result']


def erc20_call(token, selector, args_types=(), args=()):
    data = selector + (encode(list(args_types), list(args)).hex() if args_types else '')
    return int(rpc('eth_call', [{'to': token, 'data': data}, 'latest']), 16)


def balance(token, owner):
    return erc20_call(token, '0x70a08231', ['address'], [owner])


def allowance(token, owner, spender):
    return erc20_call(token, '0xdd62ed3e', ['address', 'address'], [owner, spender])


def bnb_balance(owner):
    return int(rpc('eth_getBalance', [owner, 'latest']), 16)


def fmt(amount, decimals=DECIMALS):
    return f'{Decimal(amount) / Decimal(10) ** decimals:.6f}'


# ---------------- wallet ----------------
def secrets():
    return boto3.client('secretsmanager', region_name=SECRET_REGION)


def load_account():
    try:
        value = secrets().get_secret_value(SecretId=SECRET_NAME)['SecretString']
    except secrets().exceptions.ResourceNotFoundException:
        sys.exit(f'No test wallet yet. Run `init` first ({SECRET_NAME} in {SECRET_REGION}).')
    return Account.from_key(json.loads(value)['private_key'])


def cmd_init():
    sm = secrets()
    try:
        sm.get_secret_value(SecretId=SECRET_NAME)
        acct = load_account()
        print(f'Test wallet already exists: {acct.address}')
        return
    except sm.exceptions.ResourceNotFoundException:
        pass
    acct = Account.create()
    sm.create_secret(
        Name=SECRET_NAME,
        Description='Throwaway EOA for the CoW solver round-trip test (Ondo GM on BSC). Holds ~$11 at most.',
        SecretString=json.dumps({'private_key': acct.key.hex(), 'address': acct.address}),
    )
    # Prove custody before anyone funds it: read the key back and re-derive the address.
    again = load_account()
    assert again.address == acct.address, 'stored key does not reproduce the address'
    print(f'Created and verified test wallet: {acct.address}')
    print('Fund it with ~11 USDT (BSC) and ~0.0005 BNB, then run `status`.')


# ---------------- transactions ----------------
def confirm(summary):
    print(summary)
    if input(f'Type "{CONFIRM}" to broadcast: ').strip() != CONFIRM:
        sys.exit('Cancelled. Nothing was sent.')


def send_tx(acct, to, data, value=0):
    nonce = int(rpc('eth_getTransactionCount', [acct.address, 'pending']), 16)
    gas_price = int(rpc('eth_gasPrice', []), 16)
    tx = {'to': to, 'data': data, 'value': value, 'nonce': nonce, 'gasPrice': gas_price, 'chainId': CHAIN_ID}
    tx['gas'] = int(int(rpc('eth_estimateGas', [{'from': acct.address, 'to': to, 'data': data,
                                                  'value': hex(value)}]), 16) * 1.3)
    signed = acct.sign_transaction(tx)
    tx_hash = rpc('eth_sendRawTransaction', ['0x' + signed.raw_transaction.hex().removeprefix('0x')])
    print(f'  sent {tx_hash}, waiting for receipt...')
    for _ in range(60):
        receipt = rpc('eth_getTransactionReceipt', [tx_hash])
        if receipt:
            if int(receipt['status'], 16) != 1:
                sys.exit(f'  transaction reverted: {tx_hash}')
            print(f'  confirmed in block {int(receipt["blockNumber"], 16)}')
            return tx_hash
        time.sleep(2)
    sys.exit(f'  no receipt after 2 minutes: {tx_hash}')


def ensure_allowance(acct, token, amount):
    if allowance(token, acct.address, VAULT_RELAYER) >= amount:
        return None
    data = '0x095ea7b3' + encode(['address', 'uint256'], [VAULT_RELAYER, amount]).hex()
    print(f'Approving the CoW vault relayer for exactly {fmt(amount)} of {token}')
    return send_tx(acct, token, data)


# ---------------- CoW ----------------
def quote(sell_token, buy_token, sell_amount, owner):
    body = {
        'sellToken': sell_token, 'buyToken': buy_token, 'from': owner, 'receiver': owner,
        'sellAmountBeforeFee': str(sell_amount), 'kind': 'sell', 'appData': APP_DATA,
        'signingScheme': 'eip712', 'onchainOrder': False, 'priceQuality': 'verified',
    }
    r = requests.post(f'{COW_API}/quote', json=body, timeout=30)
    if r.status_code != 200:
        sys.exit(f'Quote failed ({r.status_code}): {r.text}')
    return r.json()


def domain_separator():
    type_hash = keccak(text='EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)')
    return '0x' + keccak(type_hash + keccak(text='Gnosis Protocol') + keccak(text='v2')
                         + encode(['uint256', 'address'], [CHAIN_ID, SETTLEMENT])).hex()


def sign_order(acct, order):
    typed = {
        'types': {
            'EIP712Domain': [
                {'name': 'name', 'type': 'string'}, {'name': 'version', 'type': 'string'},
                {'name': 'chainId', 'type': 'uint256'}, {'name': 'verifyingContract', 'type': 'address'},
            ],
            'Order': [
                {'name': 'sellToken', 'type': 'address'}, {'name': 'buyToken', 'type': 'address'},
                {'name': 'receiver', 'type': 'address'}, {'name': 'sellAmount', 'type': 'uint256'},
                {'name': 'buyAmount', 'type': 'uint256'}, {'name': 'validTo', 'type': 'uint32'},
                {'name': 'appData', 'type': 'bytes32'}, {'name': 'feeAmount', 'type': 'uint256'},
                {'name': 'kind', 'type': 'string'}, {'name': 'partiallyFillable', 'type': 'bool'},
                {'name': 'sellTokenBalance', 'type': 'string'}, {'name': 'buyTokenBalance', 'type': 'string'},
            ],
        },
        'primaryType': 'Order',
        'domain': {'name': 'Gnosis Protocol', 'version': 'v2', 'chainId': CHAIN_ID, 'verifyingContract': SETTLEMENT},
        'message': order,
    }
    return '0x' + acct.sign_message(encode_typed_data(full_message=typed)).signature.hex().removeprefix('0x')


def place_and_wait(acct, sell_token, buy_token, sell_amount, label):
    q = quote(sell_token, buy_token, sell_amount, acct.address)['quote']
    total_sell = int(q['sellAmount']) + int(q['feeAmount'])   # signed orders carry feeAmount 0
    if total_sell > sell_amount:
        sys.exit(f'Quote needs {total_sell} > available {sell_amount}')
    min_buy = int(q['buyAmount']) * (10_000 - SLIPPAGE_BPS) // 10_000
    app_data_hash = '0x' + keccak(text=APP_DATA).hex()
    if q.get('appDataHash') and q['appDataHash'].lower() != app_data_hash.lower():
        sys.exit('appData hash mismatch between quote and local encoding')
    order = {
        'sellToken': sell_token, 'buyToken': buy_token, 'receiver': acct.address,
        'sellAmount': total_sell, 'buyAmount': min_buy,
        'validTo': int(time.time()) + ORDER_TTL_SECONDS, 'appData': bytes.fromhex(app_data_hash[2:]),
        'feeAmount': 0, 'kind': 'sell', 'partiallyFillable': False,
        'sellTokenBalance': 'erc20', 'buyTokenBalance': 'erc20',
    }
    confirm(f'{label}: sell {fmt(total_sell)} of {sell_token} for at least {fmt(min_buy)} of {buy_token} '
            f'(quote {fmt(q["buyAmount"])}, network fee {fmt(q["feeAmount"])}, slippage floor {SLIPPAGE_BPS} bps)')
    ensure_allowance(acct, sell_token, total_sell)
    signature = sign_order(acct, order)
    body = {**order, 'appData': APP_DATA, 'appDataHash': app_data_hash,
            'sellAmount': str(total_sell), 'buyAmount': str(min_buy), 'feeAmount': '0',
            'signingScheme': 'eip712', 'signature': signature, 'from': acct.address}
    r = requests.post(f'{COW_API}/orders', json=body, timeout=30)
    if r.status_code not in (200, 201):
        sys.exit(f'Order rejected ({r.status_code}): {r.text}')
    uid = r.json()
    print(f'Order posted: {uid}')
    started = time.time()
    while time.time() - started < ORDER_TTL_SECONDS + 60:
        o = requests.get(f'{COW_API}/orders/{uid}', timeout=30).json()
        if o.get('status') in ('fulfilled', 'cancelled', 'expired'):
            break
        print(f'  status {o.get("status")}, {int(time.time() - started)}s')
        time.sleep(10)
    trades = requests.get(f'{COW_API}/trades', params={'orderUid': uid}, timeout=30).json()
    record = {
        'label': label, 'uid': uid, 'status': o.get('status'), 'posted_at': int(started),
        'sell_token': sell_token, 'buy_token': buy_token,
        'quoted_buy': q['buyAmount'], 'min_buy': str(min_buy), 'network_fee': q['feeAmount'],
        'executed_sell': o.get('executedSellAmount'), 'executed_buy': o.get('executedBuyAmount'),
        'settlement_txs': [t.get('txHash') for t in trades if isinstance(t, dict)],
    }
    log = json.loads(LOG.read_text()) if LOG.exists() else []
    log.append(record)
    LOG.write_text(json.dumps(log, indent=1))
    print(json.dumps(record, indent=1))
    if record['status'] != 'fulfilled':
        sys.exit(f'{label} did not fill (status {record["status"]}). See {LOG.name}.')
    return record


# ---------------- commands ----------------
def cmd_status():
    acct = load_account()
    a = acct.address
    print(f'wallet  {a}')
    print(f'BNB     {fmt(bnb_balance(a))}')
    print(f'USDT    {fmt(balance(USDT, a))}  (allowance to relayer {fmt(allowance(USDT, a, VAULT_RELAYER))})')
    print(f'{STOCK_SYMBOL:7} {fmt(balance(STOCK, a))}  (allowance to relayer {fmt(allowance(STOCK, a, VAULT_RELAYER))})')
    ds = domain_separator()
    print(f'domain separator {"OK" if ds == EXPECTED_DOMAIN_SEPARATOR else "MISMATCH " + ds}')


def cmd_quote(side, usdt_amount=None):
    acct = load_account()
    if side == 'buy':
        amount = int(Decimal(usdt_amount or '10') * 10 ** DECIMALS)
        print(json.dumps(quote(USDT, STOCK, amount, acct.address), indent=1))
    else:
        amount = balance(STOCK, acct.address) or int(Decimal('0.03') * 10 ** DECIMALS)
        print(json.dumps(quote(STOCK, USDT, amount, acct.address), indent=1))


def cmd_buy(usdt_amount):
    acct = load_account()
    if domain_separator() != EXPECTED_DOMAIN_SEPARATOR:
        sys.exit('CoW domain separator mismatch; refusing to sign.')
    amount = int(Decimal(usdt_amount) * 10 ** DECIMALS)
    if balance(USDT, acct.address) < amount:
        sys.exit(f'Wallet holds {fmt(balance(USDT, acct.address))} USDT, needs {usdt_amount}.')
    place_and_wait(acct, USDT, STOCK, amount, f'BUY {STOCK_SYMBOL}')


def cmd_sell():
    acct = load_account()
    if domain_separator() != EXPECTED_DOMAIN_SEPARATOR:
        sys.exit('CoW domain separator mismatch; refusing to sign.')
    amount = balance(STOCK, acct.address)
    if not amount:
        sys.exit(f'No {STOCK_SYMBOL} to sell.')
    place_and_wait(acct, STOCK, USDT, amount, f'SELL {STOCK_SYMBOL}')


def cmd_report():
    log = json.loads(LOG.read_text()) if LOG.exists() else []
    buy = next((r for r in reversed(log) if r['label'].startswith('BUY') and r['status'] == 'fulfilled'), None)
    sell = next((r for r in reversed(log) if r['label'].startswith('SELL') and r['status'] == 'fulfilled'), None)
    if not (buy and sell):
        sys.exit('Need one fulfilled BUY and one fulfilled SELL in the log.')
    usdt_in, usdt_out = int(buy['executed_sell']), int(sell['executed_buy'])
    stock_bought, stock_sold = int(buy['executed_buy']), int(sell['executed_sell'])
    cost_bps = (usdt_in - usdt_out) * 10_000 / usdt_in
    print(f'USDT in {fmt(usdt_in)} -> {STOCK_SYMBOL} {fmt(stock_bought)} -> sold {fmt(stock_sold)} -> USDT out {fmt(usdt_out)}')
    print(f'round-trip cost {cost_bps:.1f} bps (includes CoW network fees and the market move between legs)')
    print(f'buy settled in  {buy["settlement_txs"]}')
    print(f'sell settled in {sell["settlement_txs"]}')
    print(f'time between legs {sell["posted_at"] - buy["posted_at"]}s')


def cmd_sweep(to):
    acct = load_account()
    to = to_checksum_address(to)
    for token, symbol in ((USDT, 'USDT'), (STOCK, STOCK_SYMBOL)):
        amount = balance(token, acct.address)
        if amount:
            confirm(f'Send {fmt(amount)} {symbol} to {to}')
            send_tx(acct, token, '0xa9059cbb' + encode(['address', 'uint256'], [to, amount]).hex())
    bal = bnb_balance(acct.address)
    gas_price = int(rpc('eth_gasPrice', []), 16)
    rest = bal - 21_000 * gas_price
    if rest > 0:
        confirm(f'Send {fmt(rest)} BNB to {to}')
        nonce = int(rpc('eth_getTransactionCount', [acct.address, 'pending']), 16)
        signed = acct.sign_transaction({'to': to, 'value': rest, 'gas': 21_000, 'gasPrice': gas_price,
                                        'nonce': nonce, 'chainId': CHAIN_ID, 'data': b''})
        print(rpc('eth_sendRawTransaction', ['0x' + signed.raw_transaction.hex().removeprefix('0x')]))


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    cmd, rest = args[0], args[1:]
    {'init': cmd_init, 'status': cmd_status, 'quote': cmd_quote, 'buy': cmd_buy,
     'sell': cmd_sell, 'report': cmd_report, 'sweep': cmd_sweep}.get(cmd, lambda *_: sys.exit(__doc__))(*rest)
