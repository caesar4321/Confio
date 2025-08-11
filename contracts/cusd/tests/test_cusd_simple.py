#!/usr/bin/env python3
"""
Simple test of cUSD functionality
Requires running complete_localnet_test.py first to set up accounts
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCallTxn,
    AssetTransferTxn,
    wait_for_confirmation,
    OnComplete
)
from algosdk.abi import ABIType, Method, Argument, Returns
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN

# Initialize client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

# Load configuration
try:
    from localnet_test_config import (
        APP_ID, APP_ADDRESS, CUSD_ID, USDC_ID,
        ADMIN_ADDRESS, USER1_ADDRESS, USER2_ADDRESS
    )
    print(f"Loaded config: App {APP_ID}, cUSD {CUSD_ID}, USDC {USDC_ID}")
except ImportError:
    print("Error: Run complete_localnet_test.py first")
    sys.exit(1)

# Hardcode the keys from the latest deployment
# These change every time complete_localnet_test.py runs
ADMIN_KEY = "9kW7/Kya7cT3NeXhpXUtuKP7yD1qscxoOLdlazJzBEmOrcfBrP8GU/Wt78dL0rV5PoTXqpjME9F1itaxnCPgw=="
USER1_KEY = "Q/7pxUw7rWD1mP18KMsRBT+KYDKBzNSl3jRAg7yBZ6MzBKqpLGTGPiEycGZOQYa0iAB6pS3f5lJX8QINW3/EXg=="
USER2_KEY = "sjG+/mAOFJJVCGHSP8f7K6O3sJOOGT0YzIXHCbRrbQIj+lfJYqjXXNDLtqy69J76ORI23BLIR2VVKcXn6rfMrQ=="

def get_balance(address, asset_id):
    """Get asset balance"""
    try:
        account_info = algod_client.account_info(address)
        for asset in account_info.get("assets", []):
            if asset["asset-id"] == asset_id:
                return asset["amount"] / 1_000_000
    except:
        pass
    return 0

def print_balances():
    """Print current balances"""
    print("\nCurrent Balances:")
    print("-" * 40)
    print(f"Admin: {get_balance(ADMIN_ADDRESS, CUSD_ID):,.2f} cUSD")
    print(f"User1: {get_balance(USER1_ADDRESS, CUSD_ID):,.2f} cUSD")
    print(f"User2: {get_balance(USER2_ADDRESS, CUSD_ID):,.2f} cUSD")
    print(f"App:   {get_balance(APP_ADDRESS, CUSD_ID):,.2f} cUSD")

def test_simple_transfer():
    """Test a simple cUSD transfer"""
    print("\n" + "=" * 60)
    print("TEST: Transfer cUSD (User1 → User2)")
    print("=" * 60)
    
    transfer_amount = 250_000_000  # 250 cUSD
    
    params = algod_client.suggested_params()
    
    # Simple asset transfer
    transfer = AssetTransferTxn(
        sender=USER1_ADDRESS,
        sp=params,
        receiver=USER2_ADDRESS,
        amt=transfer_amount,
        index=CUSD_ID
    )
    
    signed = transfer.sign(USER1_KEY)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    
    print(f"✅ Transferred {transfer_amount/1_000_000} cUSD")
    print_balances()

def test_admin_mint():
    """Test admin minting more cUSD"""
    print("\n" + "=" * 60)
    print("TEST: Admin Mint to User2")
    print("=" * 60)
    
    mint_amount = 500_000_000  # 500 cUSD
    
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = 2000
    
    mint_selector = Method(
        name="mint_admin",
        args=[
            Argument(arg_type="uint64", name="amount"),
            Argument(arg_type="address", name="recipient")
        ],
        returns=Returns("void")
    ).get_selector()
    
    amount_arg = ABIType.from_string("uint64").encode(mint_amount)
    recipient_arg = ABIType.from_string("address").encode(USER2_ADDRESS)
    
    mint_txn = ApplicationCallTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        index=APP_ID,
        on_complete=OnComplete.NoOpOC,
        app_args=[mint_selector, amount_arg, recipient_arg],
        foreign_assets=[CUSD_ID],
        accounts=[USER2_ADDRESS]
    )
    
    signed = mint_txn.sign(ADMIN_KEY)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    
    print(f"✅ Minted {mint_amount/1_000_000} cUSD to User2")
    print_balances()

def test_pause_system():
    """Test pausing the system"""
    print("\n" + "=" * 60)
    print("TEST: Pause/Unpause System")
    print("=" * 60)
    
    params = algod_client.suggested_params()
    
    # Pause
    pause_selector = Method(
        name="pause",
        args=[],
        returns=Returns("void")
    ).get_selector()
    
    pause_txn = ApplicationCallTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        index=APP_ID,
        on_complete=OnComplete.NoOpOC,
        app_args=[pause_selector]
    )
    
    signed = pause_txn.sign(ADMIN_KEY)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print("✅ System paused")
    
    # Try to mint while paused (should fail)
    print("Testing mint while paused...")
    try:
        test_amount = 100_000_000
        params = algod_client.suggested_params()
        params.flat_fee = True
        params.fee = 2000
        
        mint_selector = Method(
            name="mint_admin",
            args=[
                Argument(arg_type="uint64", name="amount"),
                Argument(arg_type="address", name="recipient")
            ],
            returns=Returns("void")
        ).get_selector()
        
        amount_arg = ABIType.from_string("uint64").encode(test_amount)
        recipient_arg = ABIType.from_string("address").encode(USER1_ADDRESS)
        
        mint_txn = ApplicationCallTxn(
            sender=ADMIN_ADDRESS,
            sp=params,
            index=APP_ID,
            on_complete=OnComplete.NoOpOC,
            app_args=[mint_selector, amount_arg, recipient_arg],
            foreign_assets=[CUSD_ID],
            accounts=[USER1_ADDRESS]
        )
        
        signed = mint_txn.sign(ADMIN_KEY)
        txid = algod_client.send_transaction(signed)
        wait_for_confirmation(algod_client, txid, 4)
        print("❌ Mint succeeded when paused!")
    except Exception as e:
        print("✅ Mint correctly blocked while paused")
    
    # Unpause
    unpause_selector = Method(
        name="unpause",
        args=[],
        returns=Returns("void")
    ).get_selector()
    
    unpause_txn = ApplicationCallTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        index=APP_ID,
        on_complete=OnComplete.NoOpOC,
        app_args=[unpause_selector]
    )
    
    signed = unpause_txn.sign(ADMIN_KEY)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print("✅ System unpaused")

def main():
    print("=" * 60)
    print("SIMPLE cUSD FUNCTIONALITY TEST")
    print("=" * 60)
    
    # Check connection
    try:
        status = algod_client.status()
        print(f"\nConnected to LocalNet (round {status.get('last-round', 0)})")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Show initial balances
    print_balances()
    
    # Run tests
    try:
        test_simple_transfer()
        test_admin_mint()
        test_pause_system()
        
        print("\n" + "=" * 60)
        print("TESTS COMPLETED! 🎉")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()