#!/usr/bin/env python3
"""Preview a 50 USDT mainnet swap to @julianm; only a human runs --execute.

PancakeSwap V2 swapETHForExactTokens delivers USDT directly to the recipient
and refunds unused BNB to the sponsor. Default mode never signs or broadcasts.
Run from the repository with CONFIO_ENV=mainnet and the normal AWS credentials.
"""

import argparse
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

import requests
from eth_abi import decode, encode
from eth_utils import keccak, to_checksum_address

ROOT = Path(os.environ['CONFIO_PROJECT_ROOT']) if os.environ.get('CONFIO_PROJECT_ROOT') else Path(__file__).resolve().parents[2]
USDT = to_checksum_address('0x55d398326f99059fF775485246999027B3197955')
WBNB = to_checksum_address('0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c')
ROUTER = to_checksum_address('0x10ED43C718714eb63d5aA57B78B54704E256024E')
AMOUNT = 50 * 10**18
RESERVE = 5 * 10**15  # Preserve the existing sponsor-tool floor: 0.005 BNB.
JOURNAL = ROOT / '.kms-local' / 'infinia-julianm-50-usdt-submission.json'


def calldata(signature, types=(), values=()):
    return '0x' + (keccak(text=signature)[:4] + encode(list(types), list(values))).hex()


def bnb(wei):
    return format(Decimal(wei) / Decimal(10**18), 'f')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Sign with KMS and broadcast; human-operated only')
    parser.add_argument('--expected-to', help='Require the database recipient to match this reviewed address')
    parser.add_argument('--max-bnb', help='Absolute BNB input cap, excluding gas; required to execute')
    args = parser.parse_args()
    if args.execute and not (args.expected_to and args.max_bnb):
        parser.error('--execute requires --expected-to and --max-bnb from a reviewed preview')
    if JOURNAL.exists():
        raise SystemExit(f'An execution was already attempted. Inspect {JOURNAL}; do not blindly retry.')

    sys.path.insert(0, str(ROOT))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.conf import settings
    from users.models import Account
    from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings

    def rpc(method, params):
        response = requests.post(settings.BSC_RPC_URL, json={
            'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params,
        }, timeout=20)
        response.raise_for_status()
        body = response.json()
        if 'error' in body:
            raise RuntimeError(f'{method}: {body["error"]}')
        return body['result']

    def call(target, signature, types=(), values=()):
        return bytes.fromhex(rpc('eth_call', [{
            'to': target, 'data': calldata(signature, types, values),
        }, 'latest'])[2:])

    def recipient():
        accounts = list(Account.objects.filter(
            user__username__iexact='julianm', account_type='personal',
        ).values('id', 'account_index', 'bsc_address'))
        if len(accounts) != 1 or not accounts[0]['bsc_address']:
            raise SystemExit(f'Expected exactly one active personal wallet for @julianm: {accounts}')
        return accounts[0], to_checksum_address(accounts[0]['bsc_address'])

    if settings.BSC_CHAIN_ID != 56 or int(rpc('eth_chainId', []), 16) != 56:
        raise SystemExit('This command requires BSC mainnet (chain 56).')
    if not settings.BSC_SPONSOR_ADDRESS:
        raise SystemExit('BSC_SPONSOR_ADDRESS must be configured.')
    signer = get_bsc_sponsor_signer_from_settings()  # GetPublicKey only; no signature.
    sponsor = to_checksum_address(signer.address)
    account, destination = recipient()
    if destination == sponsor or int(destination, 16) == 0:
        raise SystemExit('Invalid recipient.')
    if args.expected_to and destination != to_checksum_address(args.expected_to):
        raise SystemExit('Recipient differs from the reviewed address.')
    for contract in (ROUTER, USDT, WBNB):
        if rpc('eth_getCode', [contract, 'latest']) == '0x':
            raise SystemExit(f'Contract has no code: {contract}')
    if to_checksum_address(decode(['address'], call(ROUTER, 'WETH()'))[0]) != WBNB:
        raise SystemExit('Router WBNB mismatch.')
    if decode(['uint256'], call(USDT, 'decimals()'))[0] != 18:
        raise SystemExit('Unexpected USDT decimals.')
    amounts = decode(['uint256[]'], call(
        ROUTER, 'getAmountsIn(uint256,address[])', ['uint256', 'address[]'],
        [AMOUNT, [WBNB, USDT]],
    ))[0]
    if len(amounts) != 2 or amounts[1] != AMOUNT or amounts[0] <= 0:
        raise SystemExit('Invalid quote.')
    quoted = amounts[0]
    maximum = (quoted * 10050 + 9999) // 10000  # 0.5% maximum input slippage.
    if args.max_bnb:
        cap = Decimal(args.max_bnb) * Decimal(10**18)
        if not cap.is_finite() or cap <= 0 or cap != cap.to_integral_value():
            raise SystemExit('--max-bnb must be positive with at most 18 decimal places.')
        maximum = min(maximum, int(cap))
    if maximum < quoted:
        raise SystemExit('Fresh quote exceeds the reviewed BNB cap. Preview again.')

    nonce = int(rpc('eth_getTransactionCount', [sponsor, 'latest']), 16)
    if nonce != int(rpc('eth_getTransactionCount', [sponsor, 'pending']), 16):
        raise SystemExit('Sponsor has pending transactions; wait before retrying.')
    balance = int(rpc('eth_getBalance', [sponsor, 'latest']), 16)
    gas_price = max(100_000_000, int(rpc('eth_gasPrice', []), 16))
    deadline = int(time.time()) + 300
    data = calldata('swapETHForExactTokens(uint256,address[],address,uint256)',
                    ['uint256', 'address[]', 'address', 'uint256'],
                    [AMOUNT, [WBNB, USDT], destination, deadline])
    simulation = {'from': sponsor, 'to': ROUTER, 'value': hex(maximum), 'data': data}
    estimate = int(rpc('eth_estimateGas', [simulation]), 16)
    gas = (estimate * 15 + 9) // 10
    if gas > 500_000:
        raise SystemExit('Unexpected gas estimate exceeds 500,000.')
    remaining = balance - maximum - gas * gas_price
    if remaining < RESERVE:
        raise SystemExit('Swap would leave less than 0.005 BNB in the sponsor wallet.')
    simulated = decode(['uint256[]'], bytes.fromhex(rpc('eth_call', [simulation, 'latest'])[2:]))[0]
    if len(simulated) != 2 or simulated[-1] != AMOUNT or simulated[0] > maximum:
        raise SystemExit('Swap simulation did not return the expected amounts.')
    before = decode(['uint256'], call(USDT, 'balanceOf(address)', ['address'], [destination]))[0]
    tx = {'chainId': 56, 'nonce': nonce, 'gasPrice': gas_price, 'gas': gas,
          'to': ROUTER, 'value': maximum, 'data': data}
    plan = {'username': 'julianm', 'personal_account_id': account['id'],
            'recipient': destination, 'sponsor': sponsor, 'usdt_out': '50',
            'recipient_usdt_before': bnb(before), 'sponsor_bnb_before': bnb(balance),
            'quoted_bnb': bnb(quoted), 'maximum_bnb_input': bnb(maximum),
            'maximum_gas_bnb': bnb(gas * gas_price), 'minimum_sponsor_bnb_after': bnb(remaining),
            'unsigned_transaction': tx}
    print(json.dumps(plan, indent=2), flush=True)
    if not args.execute:
        print('Preview only: nothing signed or broadcast.')
        print(f'Execution arguments for the human operator: --expected-to {destination} --max-bnb {bnb(maximum)} --execute')
        return

    # Recheck the mutable destination and nonce immediately before signing.
    if recipient() != (account, destination):
        raise SystemExit('Recipient record changed; preview again.')
    if int(rpc('eth_getTransactionCount', [sponsor, 'pending']), 16) != nonce:
        raise SystemExit('Sponsor nonce changed; preview again.')
    if int(time.time()) > deadline - 60:
        raise SystemExit('Preview is stale; retry to obtain a fresh quote.')
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open('x') as journal:
        json.dump({'state': 'signing_started', 'plan': plan}, journal, indent=2)
        journal.flush()
        os.fsync(journal.fileno())
        raw, tx_hash = signer.sign_transaction(tx)
        journal.seek(0)
        json.dump({'state': 'signed_broadcast_may_follow', 'tx_hash': tx_hash, 'plan': plan}, journal, indent=2)
        journal.truncate()
        journal.flush()
        os.fsync(journal.fileno())
    print(f'Transaction hash: {tx_hash}. Check this hash before any retry.', flush=True)
    sent = rpc('eth_sendRawTransaction', [raw])
    if sent.lower() != tx_hash.lower():
        raise SystemExit('Unexpected broadcast response. Check the recorded transaction hash.')
    print(f'https://bscscan.com/tx/{tx_hash}', flush=True)
    for _ in range(40):
        receipt = rpc('eth_getTransactionReceipt', [tx_hash])
        if receipt:
            if int(receipt['status'], 16) != 1:
                raise SystemExit(f'Transaction reverted: {tx_hash}')
            topic = '0x' + keccak(text='Transfer(address,address,uint256)').hex()
            delivered = sum(int(log['data'], 16) for log in receipt['logs']
                            if log['address'].lower() == USDT.lower()
                            and len(log['topics']) == 3 and log['topics'][0].lower() == topic.lower()
                            and log['topics'][2][-40:].lower() == destination[2:].lower())
            if delivered != AMOUNT:
                raise SystemExit(f'Mined, but unexpected recipient transfer total: {delivered}; inspect {tx_hash}')
            print('Mined successfully: receipt confirms exactly 50 USDT delivered to the personal wallet.')
            return
        time.sleep(3)
    raise SystemExit(f'Receipt not yet available. Check {tx_hash}; do not rerun the transfer.')


if __name__ == '__main__':
    main()
