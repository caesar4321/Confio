#!/usr/bin/env python3
import os
import sys
from typing import Optional

from algosdk.v2client import algod
from algosdk import account, mnemonic
from algosdk import transaction


ASSET_ID = int(os.getenv('CONFIO_DUPLICATE_ASSET_ID', '3198567708'))
MIN_ADMIN_BAL_ALGO = float(os.getenv('ADMIN_MIN_BAL_ALGO', '0.2'))  # 0.2 ALGO for opt-in + fees


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


def get_algod_client() -> algod.AlgodClient:
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
    headers = {'User-Agent': 'Confio/cleanup-tool'}
    if token:
        headers['X-API-Key'] = token
    return algod.AlgodClient(token, addr, headers)


def microalgos_to_algo(x: int) -> float:
    return x / 1_000_000.0


def get_account_info(client: algod.AlgodClient, addr: str) -> dict:
    return client.account_info(addr)


def get_asset_holding(client: algod.AlgodClient, addr: str, asset_id: int) -> Optional[dict]:
    ai = get_account_info(client, addr)
    for holding in ai.get('assets', []) or []:
        if holding.get('asset-id') == asset_id:
            return holding
    return None


def ensure_admin_funded(client: algod.AlgodClient, sponsor_addr: str, sponsor_pk: str, admin_addr: str):
    admin_info = get_account_info(client, admin_addr)
    bal = admin_info.get('amount', 0)
    needed = int((MIN_ADMIN_BAL_ALGO * 1_000_000))
    if bal >= needed:
        return
    delta = needed - bal + 200_000  # add a cushion for tx fees and min-balance jitter
    params = client.suggested_params()
    ptxn = transaction.PaymentTxn(sender=sponsor_addr, sp=params, receiver=admin_addr, amt=delta)
    stxn = ptxn.sign(sponsor_pk)
    txid = client.send_transaction(stxn)
    wait_for_confirmation(client, txid, timeout=20)


def wait_for_confirmation(client: algod.AlgodClient, txid: str, timeout=20) -> dict:
    last_round = client.status().get('last-round')
    current_round = last_round
    for _ in range(timeout):
        try:
            pending_txn = client.pending_transaction_info(txid)
        except Exception:
            pending_txn = {}
        if pending_txn.get('confirmed-round', 0) > 0:
            return pending_txn
        current_round += 1
        client.status_after_block(current_round)
    raise TimeoutError(f'Transaction {txid} not confirmed after {timeout} rounds')


def main():
    client = get_algod_client()

    sponsor_mn = (
        os.getenv('ALGORAND_SPONSOR_MNEMONIC')
        or _get_from_decouple('ALGORAND_SPONSOR_MNEMONIC')
        or _get_from_django('ALGORAND_SPONSOR_MNEMONIC')
    )
    admin_mn = (
        os.getenv('ALGORAND_ADMIN_MNEMONIC')
        or _get_from_decouple('ALGORAND_ADMIN_MNEMONIC')
        or _get_from_django('ALGORAND_ADMIN_MNEMONIC')
    )
    if not sponsor_mn or not admin_mn:
        print('Missing ALGORAND_SPONSOR_MNEMONIC or ALGORAND_ADMIN_MNEMONIC in environment.', file=sys.stderr)
        sys.exit(1)

    sponsor_pk = mnemonic.to_private_key(sponsor_mn)
    sponsor_addr = account.address_from_private_key(sponsor_pk)
    admin_pk = mnemonic.to_private_key(admin_mn)
    admin_addr = account.address_from_private_key(admin_pk)

    print(f"Sponsor: {sponsor_addr}")
    print(f"Admin:   {admin_addr}")
    print(f"Target duplicate ASA: {ASSET_ID}")

    # Ensure admin has enough ALGO to opt-in and receive
    ensure_admin_funded(client, sponsor_addr, sponsor_pk, admin_addr)

    # Opt-in admin if not already
    admin_hold = get_asset_holding(client, admin_addr, ASSET_ID)
    if not admin_hold:
        print('Admin not opted-in. Opting in...')
        params = client.suggested_params()
        optin = transaction.AssetTransferTxn(sender=admin_addr, sp=params, receiver=admin_addr, amt=0, index=ASSET_ID)
        stx = optin.sign(admin_pk)
        txid = client.send_transaction(stx)
        wait_for_confirmation(client, txid, timeout=20)
        print('Admin opted-in.')
    else:
        print('Admin already opted-in.')

    # Check sponsor balance for the asset
    sponsor_hold = get_asset_holding(client, sponsor_addr, ASSET_ID)
    sponsor_bal = int((sponsor_hold or {}).get('amount', 0))
    print(f'Sponsor current balance for {ASSET_ID}: {sponsor_bal}')

    # If sponsor has balance, transfer all to admin
    if sponsor_bal > 0:
        print(f'Transferring {sponsor_bal} units from sponsor to admin...')
        params = client.suggested_params()
        xfer = transaction.AssetTransferTxn(sender=sponsor_addr, sp=params, receiver=admin_addr, amt=sponsor_bal, index=ASSET_ID)
        stx = xfer.sign(sponsor_pk)
        txid = client.send_transaction(stx)
        wait_for_confirmation(client, txid, timeout=40)
        print('Transfer complete.')

    # Close-out sponsor holding
    print('Closing-out sponsor holding (opt-out sponsor)...')
    params = client.suggested_params()
    close = transaction.AssetTransferTxn(sender=sponsor_addr, sp=params, receiver=admin_addr, amt=0, index=ASSET_ID, close_assets_to=admin_addr)
    stx = close.sign(sponsor_pk)
    txid = client.send_transaction(stx)
    wait_for_confirmation(client, txid, timeout=40)
    print('Sponsor holding closed.')

    # Verify sponsor no longer holds the asset
    sponsor_hold2 = get_asset_holding(client, sponsor_addr, ASSET_ID)
    print('Sponsor holding after close:', sponsor_hold2)

    # Print admin holding summary
    admin_hold2 = get_asset_holding(client, admin_addr, ASSET_ID)
    print('Admin holding after operations:', admin_hold2)


if __name__ == '__main__':
    main()
