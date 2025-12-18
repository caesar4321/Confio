
import os
import sys
from pathlib import Path
from algosdk import transaction, encoding
from algosdk.v2client import algod
from blockchain.kms_manager import KMSSigner

# Ensure project root in sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# Configuration
DESTINATION = "HUMXG7VX5RFOKQM3GJQ3CTIR3SM34TROVNVXG6FQGR6NC2YEIQLD5TBCTU"
NETWORK = os.environ.get('ALGORAND_NETWORK', 'mainnet')

# Algod config
if NETWORK == 'mainnet':
    ALGOD_ADDRESS = "https://mainnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    CUSD_ASSET_ID = int(os.environ.get('ALGORAND_CUSD_ASSET_ID', '0') or 744368179)
    CONFIO_ASSET_ID = int(os.environ.get('ALGORAND_CONFIO_ASSET_ID', '0') or 751116135)
else:
    # Testnet defaults
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    CUSD_ASSET_ID = int(os.environ.get('ALGORAND_CUSD_ASSET_ID', '0') or 0)
    CONFIO_ASSET_ID = int(os.environ.get('ALGORAND_CONFIO_ASSET_ID', '0') or 0)

def main():
    print(f"Draining Sponsor Assets on {NETWORK}...")
    
    # Initialize Algod
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    # Get Sponsor Signer
    kms_alias = os.environ.get('KMS_KEY_ALIAS')
    kms_region = os.environ.get('KMS_REGION', 'eu-central-2')
    
    if not kms_alias:
        print("Error: KMS_KEY_ALIAS not set")
        sys.exit(1)
        
    print(f"Using KMS Key: {kms_alias} ({kms_region})")
    signer = KMSSigner(kms_alias, region_name=kms_region)
    sponsor_address = signer.address
    print(f"Sponsor Address: {sponsor_address}")
    
    # Get balances
    info = client.account_info(sponsor_address)
    assets = info.get('assets', [])
    
    txns = []
    
    # Check cUSD
    cusd_bal = next((a['amount'] for a in assets if a['asset-id'] == CUSD_ASSET_ID), 0)
    if cusd_bal > 0:
        print(f"Found {cusd_bal} base units of cUSD ({CUSD_ASSET_ID})")
        params = client.suggested_params()
        txn = transaction.AssetTransferTxn(
            sender=sponsor_address,
            sp=params,
            receiver=DESTINATION,
            amt=cusd_bal,
            index=CUSD_ASSET_ID
        )
        txns.append(txn)
    else:
        print(f"No cUSD balance found")

    # Check CONFIO
    confio_bal = next((a['amount'] for a in assets if a['asset-id'] == CONFIO_ASSET_ID), 0)
    if confio_bal > 0:
        print(f"Found {confio_bal} base units of CONFIO ({CONFIO_ASSET_ID})")
        params = client.suggested_params()
        txn = transaction.AssetTransferTxn(
            sender=sponsor_address,
            sp=params,
            receiver=DESTINATION,
            amt=confio_bal,
            index=CONFIO_ASSET_ID
        )
        txns.append(txn)
    else:
        print(f"No CONFIO balance found")
        
    if not txns:
        print("Nothing to transfer.")
        return

    # Sign and Send
    for i, txn in enumerate(txns):
        print(f"Signing transaction {i+1}/{len(txns)}...")
        signed_txn = signer.sign_transaction(txn)
        
        try:
            txid = client.send_transaction(signed_txn)
            print(f"Submitted TxID: {txid}")
            confirmed = transaction.wait_for_confirmation(client, txid, 4)
            print(f"✅ Confirmed in round {confirmed['confirmed-round']}")
        except Exception as e:
            print(f"❌ Failed: {e}")

if __name__ == "__main__":
    main()
