#!/usr/bin/env python3
import os
import sys
from typing import Tuple, Optional
from algosdk.v2client import algod
from algosdk import account, mnemonic
from algosdk import transaction

def _get_from_decouple(key: str) -> Optional[str]:
    try:
        from decouple import Config, RepositoryEnv
        env_path = os.getenv('DOTENV_PATH', '/opt/confio/.env')
        if not os.path.exists(env_path):
            env_path = '.env'
        config = Config(RepositoryEnv(env_path))
        return config(key)
    except Exception:
        return None

def _get_from_django(key: str) -> Optional[str]:
    try:
        import django
        from django.conf import settings as dj_settings
        if not os.getenv('DJANGO_SETTINGS_MODULE'):
            os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
        try:
            django.setup()
        except Exception:
            pass
        return getattr(dj_settings, key, None)
    except Exception:
        return None

ASSET_ID = int(os.getenv('BURN_ASSET_ID', '3198567708'))
MIN_FUND_ALGO = int(float(os.getenv('BURN_MIN_FUND_ALGO', '0.3')) * 1_000_000)  # 0.3 ALGO buffer


def get_algod() -> algod.AlgodClient:
    addr = (
        os.getenv('ALGORAND_ALGOD_ADDRESS')
        or _get_from_decouple('ALGORAND_ALGOD_ADDRESS')
        or _get_from_django('ALGORAND_ALGOD_ADDRESS')
        or 'https://mainnet-api.algonode.cloud'
    )
    token = (
        os.getenv('ALGORAND_ALGOD_TOKEN')
        or _get_from_decouple('ALGORAND_ALGOD_TOKEN')
        or _get_from_django('ALGORAND_ALGOD_TOKEN')
        or ''
    )
    headers = {'User-Agent': 'Confio/burn-tool'}
    if token:
        headers['X-API-Key'] = token
    return algod.AlgodClient(token, addr, headers)


def wait(client: algod.AlgodClient, txid: str, timeout=20):
    rnd = client.status().get('last-round')
    for _ in range(timeout):
        p = client.pending_transaction_info(txid)
        if p.get('confirmed-round', 0) > 0:
            return p
        rnd += 1
        client.status_after_block(rnd)
    raise TimeoutError('timeout')


def compile_burn_program(client: algod.AlgodClient, asset_id: int) -> bytes:
    teal = f"""
#pragma version 8
// Allow only a single self opt-in for the specific asset, nothing else
global GroupSize
int 1
==
txn TypeEnum
int axfer
==
&&
txn XferAsset
int {asset_id}
==
&&
txn AssetAmount
int 0
==
&&
txn Sender
txn Receiver
==
&&
txn AssetSender
global ZeroAddress
==
&&
txn AssetCloseTo
global ZeroAddress
==
&&
txn RekeyTo
global ZeroAddress
==
&&
txn Fee
int 2000
<=
&&
&&
"""
    res = client.compile(teal)
    prog_b64 = res['result']
    import base64
    return base64.b64decode(prog_b64)


def ensure_funded(client: algod.AlgodClient, funder_addr: str, funder_pk: str, addr: str, min_fund: int):
    info = client.account_info(addr)
    amt = info.get('amount', 0)
    if amt >= min_fund:
        return
    delta = min_fund - amt + 200_000
    params = client.suggested_params()
    pay = transaction.PaymentTxn(sender=funder_addr, sp=params, receiver=addr, amt=delta)
    txid = client.send_transaction(pay.sign(funder_pk))
    wait(client, txid)


def main():
    sponsor_mn = (
        os.getenv('ALGORAND_SPONSOR_MNEMONIC')
        or _get_from_decouple('ALGORAND_SPONSOR_MNEMONIC')
        or _get_from_django('ALGORAND_SPONSOR_MNEMONIC')
    )
    if not sponsor_mn:
        print('ALGORAND_SPONSOR_MNEMONIC missing', file=sys.stderr)
        sys.exit(1)
    sponsor_pk = mnemonic.to_private_key(sponsor_mn)
    sponsor_addr = account.address_from_private_key(sponsor_pk)

    client = get_algod()
    prog = compile_burn_program(client, ASSET_ID)
    # py-algorand-sdk>=2.7 provides LogicSigAccount under algosdk.transaction
    from algosdk.transaction import LogicSigAccount
    lsa = LogicSigAccount(prog)
    burn_addr = lsa.address()
    print('Burn address (lsig):', burn_addr)

    # fund burn to cover min balance + opt-in
    ensure_funded(client, sponsor_addr, sponsor_pk, burn_addr, MIN_FUND_ALGO)

    # opt-in (burn_addr signs via LogicSig)
    params = client.suggested_params()
    optin = transaction.AssetTransferTxn(sender=burn_addr, sp=params, receiver=burn_addr, amt=0, index=ASSET_ID)
    lstx = transaction.LogicSigTransaction(optin, lsa)
    txid1 = client.send_transaction(lstx)
    wait(client, txid1)
    print('Burn address opted-in.')

    # transfer all sponsor balance to burn
    # read sponsor balance
    s_ai = client.account_info(sponsor_addr)
    bal = 0
    for h in s_ai.get('assets', []) or []:
        if h.get('asset-id') == ASSET_ID:
            bal = int(h.get('amount', 0))
            break
    if bal <= 0:
        print('Sponsor holds 0 units for this asset; nothing to burn.')
        print('DONE')
        return
    print('Transferring to burn:', bal)
    params = client.suggested_params()
    xfer = transaction.AssetTransferTxn(sender=sponsor_addr, sp=params, receiver=burn_addr, amt=bal, index=ASSET_ID)
    txid2 = client.send_transaction(xfer.sign(sponsor_pk))
    wait(client, txid2)
    print('Transfer complete. Supply now stuck in burn address.')
    print('DONE')


if __name__ == '__main__':
    main()
