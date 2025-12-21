#!/usr/bin/env python3
"""
Withdraw exactly 200.00 CONFIO tokens from KMS sponsor address.

CONFIO has 6 decimals, so 200.00 = 200,000,000 base units
"""

import sys
sys.path.insert(0, '/Users/julian/Confio')

from algosdk.v2client import algod
from algosdk import transaction
from blockchain.kms_manager import KMSSigner

# Mainnet configuration
ALGOD_ADDRESS = 'https://mainnet-api.4160.nodely.dev'
ALGOD_TOKEN = ''
CONFIO_ASSET_ID = 3351104258  # Mainnet CONFIO from .env.mainnet
SPONSOR_ADDRESS = 'ZS2HK5N7BZV46ZZGDOQBGFTN3JSXGAFVJFG33WAEP47JQMASSSJIQL7HI4'
RECIPIENT_ADDRESS = 'NQAW4AE7BTDHGNLWYESMYL3JOJGKJ2WM7ULVUEJWUDKMFMHEGLDUMGG5OI'
KMS_KEY_ALIAS = 'confio-mainnet-sponsor'
KMS_REGION = 'eu-central-2'

# CONFIO has 6 decimals: 200.00 CONFIO = 200,000,000 base units
AMOUNT = 200_000_000

print('=' * 80)
print('WITHDRAW 200.00 CONFIO FROM KMS SPONSOR ADDRESS')
print('=' * 80)
print()
print(f'Network:       Mainnet')
print(f'From:          {SPONSOR_ADDRESS}')
print(f'To:            {RECIPIENT_ADDRESS}')
print(f'Asset ID:      {CONFIO_ASSET_ID}')
print(f'Amount:        200.00 CONFIO ({AMOUNT:,} base units)')
print(f'KMS Key:       {KMS_KEY_ALIAS} ({KMS_REGION})')
print()

# Connect to Algorand
client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

# Check sponsor balance
print('1️⃣  Checking sponsor CONFIO balance...')
sponsor_info = client.account_info(SPONSOR_ADDRESS)
sponsor_confio = 0
for asset in sponsor_info.get('assets', []):
    if asset['asset-id'] == CONFIO_ASSET_ID:
        sponsor_confio = asset['amount']
        break

print(f'   Sponsor balance: {sponsor_confio / 1_000_000:.6f} CONFIO ({sponsor_confio:,} base units)')

if sponsor_confio < AMOUNT:
    print(f'   ❌ Insufficient balance! Need {AMOUNT:,} base units')
    sys.exit(1)

print(f'   ✅ Sufficient balance')
print()

# Check recipient is opted in
print('2️⃣  Checking recipient is opted into CONFIO...')
try:
    recipient_info = client.account_info(RECIPIENT_ADDRESS)
    is_opted_in = any(asset['asset-id'] == CONFIO_ASSET_ID for asset in recipient_info.get('assets', []))

    if not is_opted_in:
        print(f'   ❌ Recipient is not opted into CONFIO (Asset ID: {CONFIO_ASSET_ID})')
        print(f'   Recipient must opt-in before receiving tokens')
        sys.exit(1)

    print(f'   ✅ Recipient is opted in')
except Exception as e:
    print(f'   ❌ Error checking recipient: {e}')
    sys.exit(1)

print()

# Prepare transaction
print('3️⃣  Preparing asset transfer transaction...')
params = client.suggested_params()

txn = transaction.AssetTransferTxn(
    sender=SPONSOR_ADDRESS,
    sp=params,
    receiver=RECIPIENT_ADDRESS,
    amt=AMOUNT,
    index=CONFIO_ASSET_ID
)

print(f'   Transaction prepared')
print()

# Sign with KMS
print('4️⃣  Signing transaction with KMS...')
print(f'   Using KMS key: {KMS_KEY_ALIAS}')
print(f'   Region: {KMS_REGION}')

signer = KMSSigner(KMS_KEY_ALIAS, KMS_REGION)
signed_txn = signer.sign_transaction(txn)

print(f'   ✅ Transaction signed')
print()

# Submit transaction
print('5️⃣  Submitting transaction to network...')
try:
    txid = client.send_transaction(signed_txn)
    print(f'   Transaction ID: {txid}')
    print()

    # Wait for confirmation
    print('6️⃣  Waiting for confirmation...')
    confirmed_txn = transaction.wait_for_confirmation(client, txid, 4)
    print(f'   ✅ Confirmed in round {confirmed_txn["confirmed-round"]}')
    print()

except Exception as e:
    print(f'   ❌ Error: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Check final balances
print('7️⃣  Final balances...')
sponsor_info_final = client.account_info(SPONSOR_ADDRESS)
recipient_info_final = client.account_info(RECIPIENT_ADDRESS)

sponsor_confio_final = 0
recipient_confio_final = 0

for asset in sponsor_info_final.get('assets', []):
    if asset['asset-id'] == CONFIO_ASSET_ID:
        sponsor_confio_final = asset['amount']
        break

for asset in recipient_info_final.get('assets', []):
    if asset['asset-id'] == CONFIO_ASSET_ID:
        recipient_confio_final = asset['amount']
        break

print(f'   Sponsor:   {sponsor_confio_final / 1_000_000:.6f} CONFIO (was {sponsor_confio / 1_000_000:.6f})')
print(f'   Recipient: {recipient_confio_final / 1_000_000:.6f} CONFIO (was {0:.6f})')
print()

print('=' * 80)
print('✅ SUCCESS! 200.00 CONFIO TRANSFERRED')
print('=' * 80)
print()
print(f'View on AlloInfo:')
print(f'https://allo.info/tx/{txid}')
print()
