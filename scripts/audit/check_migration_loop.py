import os
from algosdk.v2client import algod

# Constants from .env.mainnet
CONFIO_ASSET_ID = 3351104258
CUSD_ASSET_ID = 3198259450
USDC_ASSET_ID = 31566704
RELEVANT_ASSETS = [CONFIO_ASSET_ID, CUSD_ASSET_ID, USDC_ASSET_ID]

# juliansdailygmailcoom
V1_ADDRESS = "TR4LDVJ43O6KUEF7XM3O2RV6PWFW3CJWYZHUFN5RSQ6TDBZRSUA6ZEXN2I"
V2_ADDRESS = "JCST5343ORH4RSK7DTPWP2PGE53Y3BNBPP7TY7LBPQAKKQXKZOLUT2VPR4"

# AlgoNode Public Endpoint (Mainnet)
ALGOD_ADDRESS = "https://mainnet-api.algonode.cloud"
ALGOD_TOKEN = ""

def check_account(address, label):
    print(f"\n--- Checking {label} [{address}] ---")
    try:
        client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
        info = client.account_info(address)
        
        micro_algos = info.get('amount', 0)
        algos = micro_algos / 1_000_000
        print(f"ALGO Balance: {micro_algos} microAlgos ({algos} ALGO)")
        
        assets = info.get('assets', [])
        relevant_found = []
        for a in assets:
            aid = a['asset-id']
            amount = a['amount']
            if aid in RELEVANT_ASSETS:
                relevant_found.append(f"ID {aid}: {amount} units")
                if amount > 0:
                     print(f"  -> Has RELEVANT ASSET: ID {aid} with amount {amount}")
        
        if not relevant_found:
            print("  -> No Relevant Assets found (even opted-in).")
        else:
             print(f"  -> Relevant Assets Opted-In: {relevant_found}")

        return info
    except Exception as e:
        print(f"Error checking {label}: {e}")
        return None

if __name__ == "__main__":
    v1_info = check_account(V1_ADDRESS, "V1 Wallet")
    v2_info = check_account(V2_ADDRESS, "V2 Wallet")
