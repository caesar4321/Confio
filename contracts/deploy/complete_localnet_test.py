#!/usr/bin/env python3
"""
Complete LocalNet test for cUSD contract
Sets up accounts, creates assets, deploys contract, and tests operations
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import base64
import time
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCreateTxn,
    AssetConfigTxn,
    AssetTransferTxn,
    PaymentTxn,
    ApplicationCallTxn,
    wait_for_confirmation,
    assign_group_id,
    OnComplete,
    StateSchema
)
from algosdk.abi import ABIType, Method, Argument, Returns
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN

# Initialize client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

def get_funded_account():
    """Get a funded LocalNet account"""
    # Use the second funded account with 4M ALGO (changes on each reset)
    funded_address = "I7UUSBGRVLML5O6I7JFGARIZEFM6DH4VMG7D5XLVLXZUX2QCVLIA4RZ5QU"
    
    # Export its mnemonic
    import subprocess
    export_result = subprocess.run(
        ["algokit", "goal", "account", "export", "-a", funded_address],
        capture_output=True,
        text=True
    )
    
    if export_result.returncode == 0:
        output = export_result.stdout.strip()
        mnemonic_start = output.find('"') + 1
        mnemonic_end = output.rfind('"')
        dispenser_mnemonic = output[mnemonic_start:mnemonic_end]
        
        return {
            "address": funded_address,
            "private_key": mnemonic.to_private_key(dispenser_mnemonic),
            "mnemonic": dispenser_mnemonic
        }
    return None

def create_account(name):
    """Create a new account"""
    private_key, address = account.generate_account()
    passphrase = mnemonic.from_private_key(private_key)
    print(f"{name}: {address[:8]}...")
    return {
        "address": address,
        "private_key": private_key,
        "mnemonic": passphrase
    }

def fund_account(sender, recipient_address, amount):
    """Fund an account"""
    params = algod_client.suggested_params()
    txn = PaymentTxn(
        sender=sender["address"],
        sp=params,
        receiver=recipient_address,
        amt=amount
    )
    signed_txn = txn.sign(sender["private_key"])
    txid = algod_client.send_transaction(signed_txn)
    wait_for_confirmation(algod_client, txid, 4)
    return txid

def create_asset(creator, name, unit, total, clawback=None):
    """Create an ASA"""
    params = algod_client.suggested_params()
    txn = AssetConfigTxn(
        sender=creator["address"],
        sp=params,
        total=total,
        default_frozen=False,
        unit_name=unit,
        asset_name=name,
        manager=creator["address"],
        reserve=creator["address"],
        freeze=creator["address"],
        clawback=clawback if clawback else creator["address"],
        url="https://confio.lat",
        decimals=6
    )
    signed_txn = txn.sign(creator["private_key"])
    txid = algod_client.send_transaction(signed_txn)
    confirmed = wait_for_confirmation(algod_client, txid, 4)
    asset_id = confirmed["asset-index"]
    print(f"{name} created: ID {asset_id}")
    return asset_id

def compile_program(source_code):
    """Compile TEAL"""
    compile_response = algod_client.compile(source_code)
    return base64.b64decode(compile_response['result'])

def deploy_contract(admin):
    """Deploy the cUSD contract"""
    # Read and compile programs
    with open("contracts/cusd_approval.teal", "r") as f:
        approval_program = compile_program(f.read())
    
    with open("contracts/cusd_clear.teal", "r") as f:
        clear_program = compile_program(f.read())
    
    # Calculate extra pages
    approval_len = len(approval_program)
    extra_pages = max(0, (approval_len - 2048 + 2047) // 2048)
    
    # Define schemas
    global_schema = StateSchema(num_uints=10, num_byte_slices=2)
    local_schema = StateSchema(num_uints=2, num_byte_slices=0)
    
    # Create app (ABI router expects a selector in ApplicationArgs[0])
    params = algod_client.suggested_params()
    create_selector = Method(
        name="create",
        args=[],
        returns=Returns("void")
    ).get_selector()
    txn = ApplicationCreateTxn(
        sender=admin["address"],
        sp=params,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=global_schema,
        local_schema=local_schema,
        extra_pages=extra_pages,
        app_args=[create_selector]
    )
    
    signed_txn = txn.sign(admin["private_key"])
    txid = algod_client.send_transaction(signed_txn)
    confirmed = wait_for_confirmation(algod_client, txid, 4)
    app_id = confirmed["application-index"]
    
    # Get app address
    from algosdk.encoding import encode_address
    import struct
    import hashlib
    app_bytes = b"appID" + struct.pack(">Q", app_id)
    hash = hashlib.new('sha512_256', app_bytes).digest()
    app_address = encode_address(hash)
    
    print(f"Contract deployed: App ID {app_id}")
    print(f"App Address: {app_address}")
    return app_id, app_address

def update_clawback(admin, asset_id, new_clawback):
    """Update asset clawback"""
    params = algod_client.suggested_params()
    txn = AssetConfigTxn(
        sender=admin["address"],
        sp=params,
        index=asset_id,
        manager=admin["address"],
        reserve=admin["address"],
        freeze=admin["address"],
        clawback=new_clawback
    )
    signed_txn = txn.sign(admin["private_key"])
    txid = algod_client.send_transaction(signed_txn)
    wait_for_confirmation(algod_client, txid, 4)
    print(f"Clawback updated for asset {asset_id}")

def setup_assets(admin, app_id, app_address, cusd_id, usdc_id):
    """Setup assets in the contract"""
    # Fund the app
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = 3000
    
    # Create grouped transactions
    payment_txn = PaymentTxn(
        sender=admin["address"],
        sp=params,
        receiver=app_address,
        amt=600000
    )
    
    # Build method call
    method_selector = Method(
        name="setup_assets",
        args=[
            Argument(arg_type="uint64", name="cusd_id"),
            Argument(arg_type="uint64", name="usdc_id")
        ],
        returns=Returns("void")
    ).get_selector()
    
    cusd_arg = ABIType.from_string("uint64").encode(cusd_id)
    usdc_arg = ABIType.from_string("uint64").encode(usdc_id)
    
    app_call_txn = ApplicationCallTxn(
        sender=admin["address"],
        sp=params,
        index=app_id,
        on_complete=OnComplete.NoOpOC,
        app_args=[method_selector, cusd_arg, usdc_arg],
        foreign_assets=[cusd_id, usdc_id]
    )
    
    # Group and send
    assign_group_id([payment_txn, app_call_txn])
    signed_payment = payment_txn.sign(admin["private_key"])
    signed_app_call = app_call_txn.sign(admin["private_key"])
    
    txid = algod_client.send_transactions([signed_payment, signed_app_call])
    wait_for_confirmation(algod_client, txid, 4)
    print("Assets setup complete")

def test_mint(admin, app_id, cusd_id, recipient_address, amount):
    """Test admin minting"""
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = 2000
    
    method_selector = Method(
        name="mint_admin",
        args=[
            Argument(arg_type="uint64", name="amount"),
            Argument(arg_type="address", name="recipient")
        ],
        returns=Returns("void")
    ).get_selector()
    
    amount_arg = ABIType.from_string("uint64").encode(amount)
    recipient_arg = ABIType.from_string("address").encode(recipient_address)
    
    app_call_txn = ApplicationCallTxn(
        sender=admin["address"],
        sp=params,
        index=app_id,
        on_complete=OnComplete.NoOpOC,
        app_args=[method_selector, amount_arg, recipient_arg],
        foreign_assets=[cusd_id],
        accounts=[recipient_address]
    )
    
    signed = app_call_txn.sign(admin["private_key"])
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print(f"Minted {amount/1_000_000} cUSD to {recipient_address[:8]}...")

def main():
    print("=" * 60)
    print("COMPLETE LOCALNET TEST FOR cUSD")
    print("=" * 60)
    
    # Check connection
    try:
        status = algod_client.status()
        print(f"\nConnected to LocalNet (round {status.get('last-round', 0)})")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Step 1: Get funded account and create test accounts
    print("\n1. SETTING UP ACCOUNTS")
    dispenser = get_funded_account()
    if not dispenser:
        print("Error: No funded account found")
        sys.exit(1)
    
    admin = create_account("Admin")
    user1 = create_account("User1")
    user2 = create_account("User2")
    
    # Fund accounts
    fund_account(dispenser, admin["address"], 100_000_000)
    fund_account(dispenser, user1["address"], 10_000_000)
    fund_account(dispenser, user2["address"], 10_000_000)
    print("Accounts funded")
    
    # Step 2: Create assets
    print("\n2. CREATING ASSETS")
    # Use maximum possible supply (2^64 - 1) for both assets
    max_supply = 2**64 - 1  # 18,446,744,073,709,551,615
    usdc_id = create_asset(admin, "Test USDC", "USDC", max_supply)
    cusd_id = create_asset(admin, "Confío Dollar", "cUSD", max_supply)
    
    # Step 3: Deploy contract
    print("\n3. DEPLOYING CONTRACT")
    app_id, app_address = deploy_contract(admin)
    
    # Step 4: Update cUSD clawback to app
    print("\n4. UPDATING CLAWBACK")
    update_clawback(admin, cusd_id, app_address)
    
    # Step 5: Setup assets
    print("\n5. SETTING UP ASSETS")
    setup_assets(admin, app_id, app_address, cusd_id, usdc_id)

    # Step 5.5: Opt-in users to the application (for local state)
    print("\n5.5 OPT-IN USERS TO APP")
    for user in [user1, user2]:
        params = algod_client.suggested_params()
        # Beaker router reads ApplicationArgs[0] first; include opt_in selector
        opt_in_selector = Method(
            name="opt_in",
            args=[],
            returns=Returns("void")
        ).get_selector()
        app_opt_in = ApplicationCallTxn(
            sender=user["address"],
            sp=params,
            index=app_id,
            on_complete=OnComplete.OptInOC,
            app_args=[opt_in_selector]
        )
        signed = app_opt_in.sign(user["private_key"])
        txid = algod_client.send_transaction(signed)
        wait_for_confirmation(algod_client, txid, 4)
        print(f"User app opt-in: {user['address'][:8]}...")
    
    # Step 6: Opt-in users to cUSD
    print("\n6. OPT-IN TO cUSD")
    for user in [user1, user2]:
        params = algod_client.suggested_params()
        opt_in_txn = AssetTransferTxn(
            sender=user["address"],
            sp=params,
            receiver=user["address"],
            amt=0,
            index=cusd_id
        )
        signed = opt_in_txn.sign(user["private_key"])
        txid = algod_client.send_transaction(signed)
        wait_for_confirmation(algod_client, txid, 4)
        print(f"User opted in: {user['address'][:8]}...")
    
    # Step 7: Test minting
    print("\n7. TESTING MINT")
    test_mint(admin, app_id, cusd_id, user1["address"], 1000_000_000)  # 1000 cUSD
    
    # Check balance
    account_info = algod_client.account_info(user1["address"])
    for asset in account_info.get("assets", []):
        if asset["asset-id"] == cusd_id:
            balance = asset["amount"] / 1_000_000
            print(f"User1 balance: {balance} cUSD")
            break
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE! 🎉")
    print("=" * 60)
    print(f"\nSummary:")
    print(f"- App ID: {app_id}")
    print(f"- cUSD ID: {cusd_id}")
    print(f"- USDC ID: {usdc_id}")
    print(f"- Successfully minted cUSD to user")
    
    # Save config
    with open("localnet_test_config.py", "w") as f:
        f.write(f"# LocalNet Test Configuration\n")
        f.write(f"APP_ID = {app_id}\n")
        f.write(f'APP_ADDRESS = "{app_address}"\n')
        f.write(f"CUSD_ID = {cusd_id}\n")
        f.write(f"USDC_ID = {usdc_id}\n")
        f.write(f'ADMIN_ADDRESS = "{admin["address"]}"\n')
        f.write(f'USER1_ADDRESS = "{user1["address"]}"\n')
        f.write(f'USER2_ADDRESS = "{user2["address"]}"\n')
    
    print("\nConfiguration saved to: localnet_test_config.py")

if __name__ == "__main__":
    main()
