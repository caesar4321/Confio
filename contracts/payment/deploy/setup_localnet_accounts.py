#!/usr/bin/env python3
"""
Setup LocalNet accounts for testing the cUSD contract
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import PaymentTxn, wait_for_confirmation
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN

# Initialize Algod client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

def create_account(name):
    """Create a new Algorand account"""
    private_key, address = account.generate_account()
    passphrase = mnemonic.from_private_key(private_key)
    
    print(f"\n{name} Account:")
    print(f"Address: {address}")
    print(f"Private Key: {private_key}")
    print(f"Mnemonic: {passphrase}")
    
    return {
        "address": address,
        "private_key": private_key,
        "mnemonic": passphrase
    }

def get_dispenser_account():
    """Get the LocalNet dispenser account for funding"""
    # Get the mnemonic for the second funded account (4M ALGO)
    import subprocess
    result = subprocess.run(
        ["algokit", "goal", "account", "export", "-a", "DGTVIK4MNQGNZWIQHSSIWV56UPTOELAF3UOASW42M5NOWIJ3YECZ6IKKQU"],
        capture_output=True,
        text=True
    )
    
    # Extract mnemonic from output
    if result.returncode == 0:
        # The output format is: Exported key for account XXX: "mnemonic words"
        output = result.stdout.strip()
        mnemonic_start = output.find('"') + 1
        mnemonic_end = output.rfind('"')
        dispenser_mnemonic = output[mnemonic_start:mnemonic_end]
    else:
        # Fallback to a known funded account mnemonic
        dispenser_mnemonic = "flash verify february syrup dwarf west length awful drip trial faith spell tray cluster lecture flag recipe install filter custom decorate flip citizen able local"
    
    dispenser_private_key = mnemonic.to_private_key(dispenser_mnemonic)
    dispenser_address = account.address_from_private_key(dispenser_private_key)
    
    return {
        "address": dispenser_address,
        "private_key": dispenser_private_key,
        "mnemonic": dispenser_mnemonic
    }

def fund_account(algod_client, sender, recipient_address, amount_microalgos):
    """Fund an account with ALGO"""
    params = algod_client.suggested_params()
    
    # Create payment transaction
    txn = PaymentTxn(
        sender=sender["address"],
        sp=params,
        receiver=recipient_address,
        amt=amount_microalgos
    )
    
    # Sign transaction
    signed_txn = txn.sign(sender["private_key"])
    
    # Send transaction
    txid = algod_client.send_transaction(signed_txn)
    print(f"Funding transaction sent: {txid}")
    
    # Wait for confirmation
    confirmed_txn = wait_for_confirmation(algod_client, txid, 4)
    print(f"Transaction confirmed in round: {confirmed_txn['confirmed-round']}")
    
    return txid

def check_balance(algod_client, address):
    """Check account balance"""
    account_info = algod_client.account_info(address)
    balance = account_info["amount"] / 1_000_000  # Convert to ALGO
    print(f"Balance for {address[:8]}...: {balance:.6f} ALGO")
    return balance

def main():
    print("=" * 60)
    print("Setting up LocalNet Accounts for cUSD Testing")
    print("=" * 60)
    
    # Check connection
    try:
        status = algod_client.status()
        print(f"\nConnected to LocalNet:")
        print(f"  Last round: {status.get('last-round', 0)}")
        if 'genesis-id' in status:
            print(f"  Genesis ID: {status['genesis-id']}")
    except Exception as e:
        print(f"Error connecting to LocalNet: {e}")
        print("Make sure LocalNet is running: algokit localnet start")
        sys.exit(1)
    
    # Get dispenser account
    print("\n" + "=" * 60)
    print("DISPENSER ACCOUNT (LocalNet funding source)")
    print("=" * 60)
    dispenser = get_dispenser_account()
    print(f"Address: {dispenser['address']}")
    dispenser_balance = check_balance(algod_client, dispenser["address"])
    
    if dispenser_balance < 1000:
        print("Warning: Dispenser balance is low!")
    
    # Create test accounts
    print("\n" + "=" * 60)
    print("CREATING TEST ACCOUNTS")
    print("=" * 60)
    
    accounts = {
        "admin": create_account("Admin/Reserve"),
        "user1": create_account("User 1"),
        "user2": create_account("User 2")
    }
    
    # Fund accounts
    print("\n" + "=" * 60)
    print("FUNDING ACCOUNTS")
    print("=" * 60)
    
    funding_amounts = {
        "admin": 100_000_000,  # 100 ALGO for admin/reserve
        "user1": 10_000_000,   # 10 ALGO for user1
        "user2": 10_000_000    # 10 ALGO for user2
    }
    
    for name, account_data in accounts.items():
        print(f"\nFunding {name} with {funding_amounts[name]/1_000_000} ALGO...")
        try:
            fund_account(
                algod_client,
                dispenser,
                account_data["address"],
                funding_amounts[name]
            )
            check_balance(algod_client, account_data["address"])
        except Exception as e:
            print(f"Error funding {name}: {e}")
    
    # Save account information to file
    print("\n" + "=" * 60)
    print("SAVING ACCOUNT INFORMATION")
    print("=" * 60)
    
    config_content = f"""# LocalNet Test Accounts Configuration
# Generated by setup_localnet_accounts.py

# Admin/Reserve Account (for contract deployment and cUSD reserve)
ADMIN_ADDRESS = "{accounts['admin']['address']}"
ADMIN_PRIVATE_KEY = "{accounts['admin']['private_key']}"
ADMIN_MNEMONIC = "{accounts['admin']['mnemonic']}"

# User Test Accounts
USER1_ADDRESS = "{accounts['user1']['address']}"
USER1_PRIVATE_KEY = "{accounts['user1']['private_key']}"
USER1_MNEMONIC = "{accounts['user1']['mnemonic']}"

USER2_ADDRESS = "{accounts['user2']['address']}"
USER2_PRIVATE_KEY = "{accounts['user2']['private_key']}"
USER2_MNEMONIC = "{accounts['user2']['mnemonic']}"

# Dispenser Account (LocalNet funding source)
DISPENSER_ADDRESS = "{dispenser['address']}"
DISPENSER_PRIVATE_KEY = "{dispenser['private_key']}"
DISPENSER_MNEMONIC = "{dispenser['mnemonic']}"
"""
    
    with open("localnet_accounts.py", "w") as f:
        f.write(config_content)
    
    print("Account configuration saved to: localnet_accounts.py")
    
    print("\n" + "=" * 60)
    print("SETUP COMPLETE!")
    print("=" * 60)
    print("\nYou can now use these accounts to:")
    print("1. Deploy the cUSD contract (use Admin account)")
    print("2. Create cUSD ASA (use Admin as reserve)")
    print("3. Test minting and transfers (User1, User2)")
    print("\nNext steps:")
    print("1. Run: ALGORAND_NETWORK=localnet myvenv/bin/python create_cusd_asa.py")
    print("2. Run: ALGORAND_NETWORK=localnet myvenv/bin/python deploy_cusd_contract.py")
    print("3. Run: ALGORAND_NETWORK=localnet myvenv/bin/python test_cusd_operations.py")

if __name__ == "__main__":
    main()