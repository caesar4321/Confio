#!/usr/bin/env python3
import os
import sys
from decimal import Decimal
from typing import Optional

from algosdk.v2client import algod
from algosdk import account, mnemonic
from algosdk import transaction


def _get_from_decouple(key: str) -> Optional[str]:
    try:
        from decouple import Config, RepositoryEnv
        env_path = os.getenv('DOTENV_PATH', '/opt/confio/.env')
        if not os.path.exists(env_path):
            env_path = '.env'
        cfg = Config(RepositoryEnv(env_path))
        return cfg(key)
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
    headers = {'User-Agent': 'Confio/park-asa'}
    if token:
        headers['X-API-Key'] = token
    return algod.AlgodClient(token, addr, headers)


def wait(client: algod.AlgodClient, txid: str, timeout=30):
    rnd = client.status().get('last-round')
    for _ in range(timeout):
        p = client.pending_transaction_info(txid)
        if p.get('confirmed-round', 0) > 0:
            return p
        rnd += 1
        client.status_after_block(rnd)
    raise TimeoutError(f'timeout waiting for {txid}')


def get_hold_amount(client: algod.AlgodClient, addr: str, asset_id: int) -> int:
    ai = client.account_info(addr)
    for h in ai.get('assets', []) or []:
        if int(h.get('asset-id')) == int(asset_id):
            return int(h.get('amount', 0))
    return 0


def main():
    asset_id = int(os.getenv('PARK_ASSET_ID', '3198567708'))
    fund_algo = Decimal(os.getenv('PARK_FUND_ALGO', '0.205'))  # ALGO
    sponsor_mn = (
        os.getenv('ALGORAND_SPONSOR_MNEMONIC')
        or _get_from_decouple('ALGORAND_SPONSOR_MNEMONIC')
        or _get_from_django('ALGORAND_SPONSOR_MNEMONIC')
    )
    if not sponsor_mn:
        print('Missing ALGORAND_SPONSOR_MNEMONIC', file=sys.stderr)
        sys.exit(1)

    sponsor_sk = mnemonic.to_private_key(sponsor_mn)
    sponsor_addr = account.address_from_private_key(sponsor_sk)

    # Generate new parking account
    park_sk, park_addr = account.generate_account()
    park_mn = mnemonic.from_private_key(park_sk)
    print('PARK_ADDRESS:', park_addr)
    print('PARK_MNEMONIC:', park_mn)

    client = get_algod()

    # Step 1: fund parking account minimally
    params = client.suggested_params()
    fund_amt_mu = int(fund_algo * Decimal(1_000_000))
    pay = transaction.PaymentTxn(sender=sponsor_addr, sp=params, receiver=park_addr, amt=fund_amt_mu)
    txid = client.send_transaction(pay.sign(sponsor_sk))
    wait(client, txid)
    print('TX_FUND:', txid, fund_amt_mu)

    # Step 2: opt-in parking account to the ASA
    params = client.suggested_params()
    optin = transaction.AssetTransferTxn(sender=park_addr, sp=params, receiver=park_addr, amt=0, index=asset_id)
    txid2 = client.send_transaction(optin.sign(park_sk))
    wait(client, txid2)
    print('TX_OPTIN:', txid2)

    # Step 3: transfer full sponsor holding to parking address
    sponsor_amt = get_hold_amount(client, sponsor_addr, asset_id)
    print('SPONSOR_ASA_BAL_BEFORE:', sponsor_amt)
    if sponsor_amt > 0:
        params = client.suggested_params()
        xfer = transaction.AssetTransferTxn(sender=sponsor_addr, sp=params, receiver=park_addr, amt=sponsor_amt, index=asset_id)
        txid3 = client.send_transaction(xfer.sign(sponsor_sk))
        wait(client, txid3)
        print('TX_ASA_XFER:', txid3, sponsor_amt)
    else:
        print('No ASA balance on sponsor; nothing to transfer.')

    # Step 4: send back any excess ALGO, leave ~0.200 ALGO minimum (base + 1 ASA)
    ai = client.account_info(park_addr)
    bal = int(ai.get('amount', 0))
    # Minimum balance: 0.1 ALGO base + 0.1 per ASA = 0.2 => 200000 microalgos
    min_mu = 200_000
    fee_mu = 1_000
    send_back = bal - min_mu - fee_mu
    if send_back > 0:
        params = client.suggested_params()
        refund = transaction.PaymentTxn(sender=park_addr, sp=params, receiver=sponsor_addr, amt=send_back)
        txid4 = client.send_transaction(refund.sign(park_sk))
        wait(client, txid4)
        print('TX_REFUND:', txid4, send_back)
    else:
        print('No excess ALGO to refund; balance at or below minimum.')

    ai2 = client.account_info(park_addr)
    sponsor_amt_after = get_hold_amount(client, sponsor_addr, asset_id)
    park_amt_after = get_hold_amount(client, park_addr, asset_id)
    print('FINAL_PARK_BAL_ALGO:', ai2.get('amount', 0))
    print('FINAL_SPONSOR_ASA_BAL:', sponsor_amt_after)
    print('FINAL_PARK_ASA_BAL:', park_amt_after)


if __name__ == '__main__':
    main()

