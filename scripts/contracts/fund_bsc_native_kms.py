#!/usr/bin/env python3
"""
Send BNB or USDT from the KMS sponsor hot wallet to an address.

Test-rig plumbing for the Direct-mode Salida de emergencia
(apps/src/services/emergencyExit/bscExit.ts):

  --bnb   put gas dust on a test wallet — the exit pays its own gas, so a
          fresh wallet with 0 BNB cannot execute at all.
  --usdt  hand the exit's proceeds back to the test wallet so the drill
          can be re-run. Note this only reloads the transferUsdt leg;
          exercising redeemCusdPlus again needs cUSD+ SHARES, which only
          a savings deposit from the wallet itself can create.

The sponsor key never leaves KMS: the tx digest is signed by
blockchain.evm_kms_signer.EVMKMSSigner, which also asserts the alias
resolves to settings.BSC_SPONSOR_ADDRESS before anything is built.

Dry run by default — it prints the plan and exits. Add the literal word
`execute` to broadcast.

Usage:
  aws-vault exec Julian -- env CONFIO_ENV=mainnet myvenv/bin/python \
      scripts/contracts/fund_bsc_native_kms.py --to 0x... --bnb 0.0005
  aws-vault exec Julian -- env CONFIO_ENV=mainnet myvenv/bin/python \
      scripts/contracts/fund_bsc_native_kms.py --to 0x... --usdt all
  # append the literal word `execute` to broadcast.
"""
import argparse
import os
import re
import sys
import time
from decimal import Decimal
from pathlib import Path

import django
import requests

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings  # noqa: E402

from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings  # noqa: E402

ADDR_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')

USDT_BSC = '0x55d398326f99059fF775485246999027B3197955'  # 18 decimals on BSC
TRANSFER_SELECTOR = '0xa9059cbb'  # transfer(address,uint256)

# Refuse to drain the sponsor: it still has to pay for 7702 batches.
SPONSOR_FLOOR_WEI = 5 * 10 ** 15  # 0.005 BNB
# Guard against a fat-fingered amount. Native sends here are dust only;
# USDT is capped at drill-sized returns, not treasury movements.
MAX_BNB_WEI = 5 * 10 ** 15       # 0.005 BNB
MAX_USDT_WEI = 25 * 10 ** 18     # 25 USDT
# Destinations are usually EIP-7702-delegated Confío wallets, so a value
# send is NOT a bare 21k transfer — it runs the delegate's receive()
# (CUSD_PLUS_BATCH_DELEGATE_ADDRESS costs ~21.2k). Always estimate; 21k
# hardcoded burns the whole limit and reverts.
GAS_FLOOR = 21_000
GAS_CEILING = 200_000  # anything above this means the dest is not a wallet
MIN_GAS_PRICE_WEI = 100_000_000  # 0.1 gwei; BSC floor is 0.05


def rpc(method: str, params: list):
    url = settings.BSC_RPC_URL
    r = requests.post(url, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}, timeout=20)
    r.raise_for_status()
    body = r.json()
    if 'error' in body:
        raise RuntimeError(f"{method} failed: {body['error']}")
    return body['result']


def erc20_balance(token: str, holder: str) -> int:
    ret = rpc('eth_call', [{
        'to': token, 'data': '0x70a08231' + holder[2:].lower().rjust(64, '0'),
    }, 'latest'])
    return int(ret, 16) if ret and ret != '0x' else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--to', required=True, help='destination address (0x…40 hex)')
    ap.add_argument('--bnb', help='native amount in BNB, e.g. 0.0005')
    ap.add_argument('--usdt', help="USDT amount, or 'all' for the sponsor's whole balance")
    ap.add_argument('confirm', nargs='?', default='', help="literal 'execute' to broadcast")
    args = ap.parse_args()

    if bool(args.bnb) == bool(args.usdt):
        print('Pass exactly one of --bnb or --usdt.', file=sys.stderr)
        return 2

    to = args.to
    if not ADDR_RE.match(to):
        print(f'Bad destination address: {to}', file=sys.stderr)
        return 2

    signer = get_bsc_sponsor_signer_from_settings()  # asserts alias == BSC_SPONSOR_ADDRESS
    sponsor = signer.address

    chain_id = int(rpc('eth_chainId', []), 16)
    if chain_id != settings.BSC_CHAIN_ID:
        print(f'RPC chainId {chain_id} != settings.BSC_CHAIN_ID {settings.BSC_CHAIN_ID}', file=sys.stderr)
        return 2

    balance = int(rpc('eth_getBalance', [sponsor, 'latest']), 16)
    nonce = int(rpc('eth_getTransactionCount', [sponsor, 'pending']), 16)
    gas_price = max(int(rpc('eth_gasPrice', []), 16), MIN_GAS_PRICE_WEI)

    if args.usdt:
        held = erc20_balance(USDT_BSC, sponsor)
        amount = held if args.usdt == 'all' else int(Decimal(args.usdt) * Decimal(10 ** 18))
        if amount <= 0:
            print('Nothing to send: sponsor holds 0 USDT.', file=sys.stderr)
            return 1
        if amount > held:
            print(f'Sponsor holds {held / 1e18:.6f} USDT, cannot send {amount / 1e18:.6f}.', file=sys.stderr)
            return 1
        if amount > MAX_USDT_WEI:
            print(f'Refusing to move more than {MAX_USDT_WEI / 1e18} USDT with this script.', file=sys.stderr)
            return 1
        tx_to, tx_value = USDT_BSC, 0
        tx_data = TRANSFER_SELECTOR + to[2:].lower().rjust(64, '0') + format(amount, 'x').rjust(64, '0')
        what = f'{amount / 1e18:.18f}'.rstrip('0') + ' USDT'
    else:
        amount = int(Decimal(args.bnb) * Decimal(10 ** 18))
        if amount <= 0 or amount > MAX_BNB_WEI:
            print(f'--bnb must be > 0 and <= {MAX_BNB_WEI / 1e18} BNB (dust only)', file=sys.stderr)
            return 2
        tx_to, tx_value, tx_data = to, amount, ''
        what = f'{amount / 1e18:.9f} BNB'

    estimated = int(rpc('eth_estimateGas', [{
        'from': sponsor, 'to': tx_to, 'value': hex(tx_value), 'data': tx_data or '0x',
    }]), 16)
    gas_limit = max(GAS_FLOOR, (estimated * 15) // 10)  # 1.5x — receive() can branch on state
    if gas_limit > GAS_CEILING:
        print(f'ABORT: estimate {estimated} exceeds the {GAS_CEILING} ceiling — '
              f'{to} is not a plain wallet.', file=sys.stderr)
        return 1

    fee = gas_price * gas_limit
    remaining = balance - tx_value - fee

    code = rpc('eth_getCode', [to, 'latest'])
    print(f'network      : chainId {chain_id} via {settings.BSC_RPC_URL}')
    print(f'sponsor      : {sponsor} (KMS alias {settings.BSC_KMS_KEY_ALIAS})')
    print(f'sponsor bal  : {balance / 1e18:.9f} BNB / '
          f'{erc20_balance(USDT_BSC, sponsor) / 1e18:.6f} USDT')
    print(f'destination  : {to}')
    print(f'dest bal     : {int(rpc("eth_getBalance", [to, "latest"]), 16) / 1e18:.9f} BNB / '
          f'{erc20_balance(USDT_BSC, to) / 1e18:.6f} USDT')
    if code.startswith('0xef0100'):
        print(f'dest 7702    : delegated to 0x{code[8:]}')
    print(f'sending      : {what}')
    print(f'gas          : est {estimated} -> limit {gas_limit} @ {gas_price / 1e9:.4f} gwei '
          f'= {fee / 1e18:.9f} BNB')
    print(f'nonce        : {nonce}')
    print(f'sponsor after: {remaining / 1e18:.9f} BNB')

    if remaining < SPONSOR_FLOOR_WEI:
        print(f'ABORT: would leave sponsor under the {SPONSOR_FLOOR_WEI / 1e18} BNB floor.', file=sys.stderr)
        return 1

    if args.confirm != 'execute':
        print("\nDry run — nothing broadcast. Re-run with the literal word 'execute' to send.")
        return 0

    raw, tx_hash = signer.sign_transaction({
        'chainId': chain_id,
        'nonce': nonce,
        'gasPrice': gas_price,
        'gas': gas_limit,
        'to': tx_to,
        'value': tx_value,
        'data': bytes.fromhex(tx_data[2:]) if tx_data else b'',
    })
    sent = rpc('eth_sendRawTransaction', [raw])
    print(f'\nbroadcast {sent}')
    print(f'https://bscscan.com/tx/{sent}')

    for _ in range(30):
        time.sleep(2)
        receipt = rpc('eth_getTransactionReceipt', [sent])
        if receipt:
            status = int(receipt['status'], 16)
            print(f"mined in block {int(receipt['blockNumber'], 16)} status={status}")
            print(f'dest bal now : {int(rpc("eth_getBalance", [to, "latest"]), 16) / 1e18:.9f} BNB / '
                  f'{erc20_balance(USDT_BSC, to) / 1e18:.6f} USDT')
            return 0 if status == 1 else 1
    print('no receipt after 60s — check BscScan', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
