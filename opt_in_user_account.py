#!/usr/bin/env python
"""
Fund and opt-in user account to CONFIO and USDC tokens
"""
import os
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import PaymentTxn, AssetTransferTxn, wait_for_confirmation, assign_group_id
import time

def fund_and_opt_in_account():
    """Fund user account and opt it in to CONFIO and USDC"""
    
    # Configuration
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    CONFIO_ASSET_ID = 743890784
    USDC_ASSET_ID = 10458941
    
    # Creator account (has ALGO and CONFIO)
    creator_mnemonic = "toss vacuum table old mobile sound bid net evidence fee ticket skin twice invest over machine young dad travel custom offer target duck able air"
    creator_private_key = mnemonic.to_private_key(creator_mnemonic)
    creator_address = account.address_from_private_key(creator_private_key)
    
    # User account to fund and opt-in
    user_address = "XTITQDJSETDOQG3WMSDKE7QPPAX22ZMDX6PZ5B43E4JCFTEBPUJGDY2RGQ"
    
    print("=" * 60)
    print("FUND AND OPT-IN USER ACCOUNT")
    print("=" * 60)
    
    # Initialize client
    algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    print(f"\nCreator address: {creator_address}")
    print(f"User address: {user_address}")
    
    try:
        # Check creator balance
        creator_info = algod_client.account_info(creator_address)
        creator_algo = creator_info.get('amount', 0) / 1_000_000
        creator_assets = creator_info.get('assets', [])
        creator_confio = 0
        for asset in creator_assets:
            if asset['asset-id'] == CONFIO_ASSET_ID:
                creator_confio = asset['amount'] / 1_000_000
        
        print(f"\nCreator balances:")
        print(f"  ALGO: {creator_algo} ALGO")
        print(f"  CONFIO: {creator_confio:,.0f} CONFIO")
        
        # Check user balance
        user_info = algod_client.account_info(user_address)
        user_algo = user_info.get('amount', 0) / 1_000_000
        user_assets = user_info.get('assets', [])
        
        print(f"\nUser current status:")
        print(f"  ALGO: {user_algo} ALGO")
        print(f"  Assets opted in: {len(user_assets)}")
        
        # Get suggested parameters
        params = algod_client.suggested_params()
        
        # Step 1: Fund user account with ALGO
        if user_algo < 0.5:
            print("\n1. Funding user account with ALGO...")
            funding_amount = 500000  # 0.5 ALGO in microAlgos
            
            fund_txn = PaymentTxn(
                sender=creator_address,
                sp=params,
                receiver=user_address,
                amt=funding_amount
            )
            
            signed_fund_txn = fund_txn.sign(creator_private_key)
            tx_id = algod_client.send_transaction(signed_fund_txn)
            print(f"   Funding transaction ID: {tx_id}")
            
            wait_for_confirmation(algod_client, tx_id, 4)
            print(f"   ✓ Sent 0.5 ALGO to user account")
            
            # Wait a moment for balance to update
            time.sleep(1)
        else:
            print("\n1. User already has sufficient ALGO")
        
        # Refresh user info
        user_info = algod_client.account_info(user_address)
        user_assets = user_info.get('assets', [])
        
        # Step 2: Check and opt-in to CONFIO
        confio_opted_in = any(asset['asset-id'] == CONFIO_ASSET_ID for asset in user_assets)
        
        if not confio_opted_in:
            print("\n2. Opting in to CONFIO...")
            print(f"   ⚠️  User must sign this transaction themselves")
            print(f"   Since we don't have the user's private key, generating unsigned transaction...")
            
            confio_opt_in_txn = AssetTransferTxn(
                sender=user_address,
                sp=params,
                receiver=user_address,
                amt=0,
                index=CONFIO_ASSET_ID
            )
            
            # Save unsigned transaction for user to sign
            import base64
            import msgpack
            unsigned_txn = base64.b64encode(msgpack.packb(confio_opt_in_txn.dictify())).decode()
            
            print(f"\n   Unsigned CONFIO opt-in transaction (base64):")
            print(f"   {unsigned_txn[:50]}...")
            print(f"\n   User needs to sign and submit this transaction")
        else:
            print("\n2. User already opted in to CONFIO")
        
        # Step 3: Check and opt-in to USDC
        usdc_opted_in = any(asset['asset-id'] == USDC_ASSET_ID for asset in user_assets)
        
        if not usdc_opted_in:
            print("\n3. Opting in to USDC...")
            print(f"   ⚠️  User must sign this transaction themselves")
            
            usdc_opt_in_txn = AssetTransferTxn(
                sender=user_address,
                sp=params,
                receiver=user_address,
                amt=0,
                index=USDC_ASSET_ID
            )
            
            # Save unsigned transaction for user to sign
            import base64
            import msgpack
            unsigned_txn = base64.b64encode(msgpack.packb(usdc_opt_in_txn.dictify())).decode()
            
            print(f"\n   Unsigned USDC opt-in transaction (base64):")
            print(f"   {unsigned_txn[:50]}...")
            print(f"\n   User needs to sign and submit this transaction")
        else:
            print("\n3. User already opted in to USDC")
        
        # Step 4: Send CONFIO tokens (only if user is opted in)
        if confio_opted_in:
            print("\n4. Sending CONFIO tokens to user...")
            confio_amount = 1000_000_000  # 1000 CONFIO in micro units (6 decimals)
            
            confio_transfer_txn = AssetTransferTxn(
                sender=creator_address,
                sp=params,
                receiver=user_address,
                amt=confio_amount,
                index=CONFIO_ASSET_ID
            )
            
            signed_transfer_txn = confio_transfer_txn.sign(creator_private_key)
            tx_id = algod_client.send_transaction(signed_transfer_txn)
            print(f"   Transfer transaction ID: {tx_id}")
            
            wait_for_confirmation(algod_client, tx_id, 4)
            print(f"   ✓ Sent 1,000 CONFIO to user account")
        else:
            print("\n4. Cannot send CONFIO - user needs to opt-in first")
        
        # Final status
        print("\n" + "=" * 60)
        print("FINAL STATUS")
        print("=" * 60)
        
        user_info = algod_client.account_info(user_address)
        user_algo = user_info.get('amount', 0) / 1_000_000
        user_assets = user_info.get('assets', [])
        
        print(f"\nUser account: {user_address}")
        print(f"ALGO balance: {user_algo} ALGO")
        
        for asset in user_assets:
            if asset['asset-id'] == CONFIO_ASSET_ID:
                print(f"CONFIO balance: {asset['amount'] / 1_000_000:,.0f} CONFIO")
            elif asset['asset-id'] == USDC_ASSET_ID:
                print(f"USDC balance: {asset['amount'] / 1_000_000} USDC")
        
        if not confio_opted_in or not usdc_opted_in:
            print("\n⚠️  IMPORTANT: User must sign and submit the opt-in transactions above")
            print("   After opt-ins are complete, run this script again to transfer CONFIO")
            
    except Exception as e:
        print(f"\n✗ Error: {e}")


if __name__ == "__main__":
    fund_and_opt_in_account()