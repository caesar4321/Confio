#!/usr/bin/env python3
"""
Test cUSD operations on LocalNet
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import base64
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import (
    PaymentTxn,
    ApplicationCallTxn,
    AssetTransferTxn,
    AssetOptInTxn,
    wait_for_confirmation,
    assign_group_id
)
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    TransactionWithSigner,
    AccountTransactionSigner
)
from algosdk.abi import Method, Argument, Returns, Contract
from contracts.config.localnet_accounts import (
    ADMIN_ADDRESS, ADMIN_PRIVATE_KEY,
    USER1_ADDRESS, USER1_PRIVATE_KEY,
    USER2_ADDRESS, USER2_PRIVATE_KEY
)
from contracts.config.localnet_assets import CUSD_ASSET_ID, TEST_USDC_ID
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN
import json

# Initialize Algod client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

# First, let's just get the app ID by checking recent transactions
def find_app_id():
    """Find the deployed app ID from recent transactions"""
    # For now, we'll use the app ID from the error message
    return 1006  # From the error we saw

def get_app_address(app_id):
    """Get app address from app ID"""
    try:
        app_info = algod_client.application_info(app_id)
        return app_info["params"]["address"]
    except:
        # Calculate app address manually
        from algosdk.encoding import encode_address
        import struct
        app_bytes = b"appID" + struct.pack(">Q", app_id)
        import hashlib
        hash = hashlib.sha512_256(app_bytes).digest()
        return encode_address(hash)

def setup_assets_simple(app_id, app_address):
    """Setup assets with a simpler approach"""
    print("\n" + "=" * 60)
    print("SETTING UP ASSETS")
    print("=" * 60)
    
    admin = {
        "address": ADMIN_ADDRESS,
        "private_key": ADMIN_PRIVATE_KEY
    }
    
    # First, fund the app account
    params = algod_client.suggested_params()
    
    print(f"Funding app address: {app_address}")
    fund_txn = PaymentTxn(
        sender=admin["address"],
        sp=params,
        receiver=app_address,
        amt=1_000_000  # 1 ALGO for safety
    )
    
    signed_fund = fund_txn.sign(admin["private_key"])
    txid = algod_client.send_transaction(signed_fund)
    wait_for_confirmation(algod_client, txid, 4)
    print(f"App funded with 1 ALGO, txid: {txid}")
    
    # Now call setup_assets
    print(f"\nCalling setup_assets with:")
    print(f"  cUSD ID: {CUSD_ASSET_ID}")
    print(f"  USDC ID: {TEST_USDC_ID}")
    
    # Create the method call using ABI
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = 3000  # Cover app call + 2 inner transactions
    
    # Build the method selector and arguments
    from algosdk.abi import ABIType
    method_selector = Method(
        name="setup_assets",
        args=[
            Argument(arg_type="uint64", name="cusd_id"),
            Argument(arg_type="uint64", name="usdc_id")
        ],
        returns=Returns(return_type="void")
    ).get_selector()
    
    # Encode arguments
    cusd_arg = ABIType.from_string("uint64").encode(CUSD_ASSET_ID)
    usdc_arg = ABIType.from_string("uint64").encode(TEST_USDC_ID)
    
    # Create grouped transactions
    payment_txn = PaymentTxn(
        sender=admin["address"],
        sp=params,
        receiver=app_address,
        amt=600000  # 0.6 ALGO for opt-ins
    )
    
    app_call_txn = ApplicationCallTxn(
        sender=admin["address"],
        sp=params,
        index=app_id,
        app_args=[method_selector, cusd_arg, usdc_arg]
    )
    
    # Group transactions
    group_txns = [payment_txn, app_call_txn]
    group_id = assign_group_id(group_txns)
    
    # Sign transactions
    signed_payment = payment_txn.sign(admin["private_key"])
    signed_app_call = app_call_txn.sign(admin["private_key"])
    
    # Send grouped transaction
    txid = algod_client.send_transactions([signed_payment, signed_app_call])
    print(f"Setup assets transaction sent: {txid}")
    
    # Wait for confirmation
    confirmed = wait_for_confirmation(algod_client, txid, 4)
    print(f"Setup assets confirmed in round: {confirmed['confirmed-round']}")
    
    return True

def opt_in_users():
    """Opt in users to cUSD asset"""
    print("\n" + "=" * 60)
    print("OPT-IN USERS TO cUSD")
    print("=" * 60)
    
    users = [
        {"name": "User1", "address": USER1_ADDRESS, "private_key": USER1_PRIVATE_KEY},
        {"name": "User2", "address": USER2_ADDRESS, "private_key": USER2_PRIVATE_KEY},
        {"name": "Admin", "address": ADMIN_ADDRESS, "private_key": ADMIN_PRIVATE_KEY}
    ]
    
    params = algod_client.suggested_params()
    
    for user in users:
        # Opt-in to cUSD
        opt_in_txn = AssetTransferTxn(
            sender=user["address"],
            sp=params,
            receiver=user["address"],
            amt=0,
            index=CUSD_ASSET_ID
        )
        
        signed = opt_in_txn.sign(user["private_key"])
        txid = algod_client.send_transaction(signed)
        wait_for_confirmation(algod_client, txid, 4)
        print(f"{user['name']} opted in to cUSD")

def test_mint_admin(app_id):
    """Test admin minting"""
    print("\n" + "=" * 60)
    print("TESTING ADMIN MINT")
    print("=" * 60)
    
    admin = {
        "address": ADMIN_ADDRESS,
        "private_key": ADMIN_PRIVATE_KEY
    }
    
    user1 = {
        "address": USER1_ADDRESS,
        "private_key": USER1_PRIVATE_KEY
    }
    
    # Mint 1000 cUSD to User1
    amount = 1_000_000_000  # 1000 cUSD (6 decimals)
    
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = 2000  # Cover app call + inner transaction
    
    # Build the method call
    from algosdk.abi import ABIType
    method_selector = Method(
        name="mint_admin",
        args=[
            Argument(arg_type="uint64", name="amount"),
            Argument(arg_type="address", name="recipient")
        ],
        returns=Returns(return_type="void")
    ).get_selector()
    
    # Encode arguments
    amount_arg = ABIType.from_string("uint64").encode(amount)
    recipient_arg = ABIType.from_string("address").encode(user1["address"])
    
    # Create app call
    app_call_txn = ApplicationCallTxn(
        sender=admin["address"],
        sp=params,
        index=app_id,
        app_args=[method_selector, amount_arg, recipient_arg]
    )
    
    # Sign and send
    signed = app_call_txn.sign(admin["private_key"])
    txid = algod_client.send_transaction(signed)
    print(f"Mint transaction sent: {txid}")
    
    # Wait for confirmation
    confirmed = wait_for_confirmation(algod_client, txid, 4)
    print(f"Mint confirmed in round: {confirmed['confirmed-round']}")
    
    # Check User1's cUSD balance
    try:
        account_info = algod_client.account_info(user1["address"])
        for asset in account_info.get("assets", []):
            if asset["asset-id"] == CUSD_ASSET_ID:
                balance = asset["amount"] / 1_000_000  # Convert to cUSD
                print(f"User1 cUSD balance: {balance} cUSD")
                break
    except Exception as e:
        print(f"Error checking balance: {e}")

def main():
    print("=" * 60)
    print("Testing cUSD Contract on LocalNet")
    print("=" * 60)
    
    # Check connection
    try:
        status = algod_client.status()
        print(f"\nConnected to LocalNet:")
        print(f"  Last round: {status.get('last-round', 0)}")
    except Exception as e:
        print(f"Error connecting to LocalNet: {e}")
        sys.exit(1)
    
    # Find app ID
    app_id = find_app_id()
    app_address = get_app_address(app_id)
    
    print(f"\nUsing App ID: {app_id}")
    print(f"App Address: {app_address}")
    
    try:
        # Step 1: Setup assets
        setup_assets_simple(app_id, app_address)
        
        # Step 2: Opt-in users
        opt_in_users()
        
        # Step 3: Test admin mint
        test_mint_admin(app_id)
        
        print("\n" + "=" * 60)
        print("TEST COMPLETE!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nError during testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()