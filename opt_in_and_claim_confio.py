#!/usr/bin/env python
"""
Opt-in creator account to CONFIO and claim the tokens
"""
import os
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import AssetTransferTxn, wait_for_confirmation

def opt_in_and_claim():
    """Opt-in creator to CONFIO to receive the 1 billion tokens"""
    
    # Configuration
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    CONFIO_ASSET_ID = 743890784
    
    # Creator account
    creator_mnemonic = "toss vacuum table old mobile sound bid net evidence fee ticket skin twice invest over machine young dad travel custom offer target duck able air"
    creator_private_key = mnemonic.to_private_key(creator_mnemonic)
    creator_address = account.address_from_private_key(creator_private_key)
    
    print("=" * 60)
    print("OPT-IN TO CONFIO TOKEN")
    print("=" * 60)
    
    # Initialize client
    algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    # Check current balance
    print(f"\nCreator address: {creator_address}")
    print(f"CONFIO Asset ID: {CONFIO_ASSET_ID}")
    
    try:
        account_info = algod_client.account_info(creator_address)
        algo_balance = account_info.get('amount', 0) / 1_000_000
        print(f"ALGO balance: {algo_balance} ALGO")
        
        # Check if already opted in
        assets = account_info.get('assets', [])
        already_opted_in = any(asset['asset-id'] == CONFIO_ASSET_ID for asset in assets)
        
        if already_opted_in:
            # Already opted in, check balance
            for asset in assets:
                if asset['asset-id'] == CONFIO_ASSET_ID:
                    balance = asset['amount'] / 1_000_000  # 6 decimals
                    print(f"\n✓ Already opted in!")
                    print(f"CONFIO balance: {balance:,.0f} CONFIO")
                    return
        else:
            print(f"\n⚠️  Not opted in to CONFIO yet")
            print("Creating opt-in transaction...")
            
            # Get suggested parameters
            params = algod_client.suggested_params()
            
            # Create opt-in transaction (0 amount transfer to self)
            txn = AssetTransferTxn(
                sender=creator_address,
                sp=params,
                receiver=creator_address,
                amt=0,
                index=CONFIO_ASSET_ID
            )
            
            # Sign transaction
            signed_txn = txn.sign(creator_private_key)
            
            # Send transaction
            tx_id = algod_client.send_transaction(signed_txn)
            print(f"Opt-in transaction ID: {tx_id}")
            
            # Wait for confirmation
            print("Waiting for confirmation...")
            wait_for_confirmation(algod_client, tx_id, 4)
            
            print("\n✅ Successfully opted in to CONFIO!")
            
            # Check balance again
            account_info = algod_client.account_info(creator_address)
            assets = account_info.get('assets', [])
            for asset in assets:
                if asset['asset-id'] == CONFIO_ASSET_ID:
                    balance = asset['amount'] / 1_000_000  # 6 decimals
                    print(f"CONFIO balance: {balance:,.0f} CONFIO")
                    
                    if balance == 1_000_000_000:
                        print("\n🎉 All 1 billion CONFIO tokens successfully received!")
                    break
            
    except Exception as e:
        print(f"\n✗ Error: {e}")


def create_opt_in_helper():
    """Create a helper function for opting in any account"""
    
    print("\n" + "-" * 60)
    print("OPT-IN HELPER CODE")
    print("-" * 60)
    
    code = '''
# Helper function to opt-in any account to an asset
async def opt_in_to_asset(client, address: str, private_key: str, asset_id: int):
    """Opt-in an account to receive an ASA token"""
    
    # Get suggested parameters
    params = client.algod.suggested_params()
    
    # Create opt-in transaction (0 amount transfer to self)
    from algosdk.transaction import AssetTransferTxn
    txn = AssetTransferTxn(
        sender=address,
        sp=params,
        receiver=address,
        amt=0,
        index=asset_id
    )
    
    # Sign and send
    signed_txn = txn.sign(private_key)
    tx_id = client.algod.send_transaction(signed_txn)
    
    # Wait for confirmation
    from algosdk.transaction import wait_for_confirmation
    wait_for_confirmation(client.algod, tx_id, 4)
    
    return tx_id

# For new users, you'll need to:
# 1. Fund them with ~0.5 ALGO (0.1 per asset + fees)
# 2. Opt them in to: USDC (10458941), CONFIO (743890784), and future cUSD
'''
    
    print(code)
    
    print("\nCost breakdown per user:")
    print("- 0.1 ALGO minimum balance for USDC")
    print("- 0.1 ALGO minimum balance for CONFIO")
    print("- 0.1 ALGO minimum balance for cUSD (future)")
    print("- 0.001 ALGO per opt-in transaction")
    print("- Total: ~0.4 ALGO per user ($0.08 at current prices)")


if __name__ == "__main__":
    opt_in_and_claim()
    create_opt_in_helper()