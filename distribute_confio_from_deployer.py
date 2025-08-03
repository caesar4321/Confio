#!/usr/bin/env python3
"""
Distribute CONFIO tokens from deployer address to the 4 accounts
Current active address has 999.99M CONFIO tokens that need to be distributed
"""
import os
import sys
import subprocess

# Add the project directory to sys.path
sys.path.insert(0, '/Users/julian/Confio')

def run_command(cmd):
    """Run a command and return the result"""
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return None
    print(f"Success: {result.stdout}")
    return result.stdout

def distribute_confio():
    """Distribute 1000 CONFIO to each of the 4 accounts"""
    
    # Target accounts (same as before)
    accounts = [
        ('Julian Personal', '0x79bb06b52bc5bddad6d4bb8a99e91b5644baad67d9c25006d44d1c1b6bd6a6e9'),
        ('Julian Business', '0x04b06df35ddfa55c5e62c9f1a1cd2c6da36efa1b8c0e80cecd9c6c3e9b7b5b85'),
        ('Wonju Personal', '0x8bc5e5e68c2ecb1c7ae1bb64c92af2c7e1b0f1e4c87a1a42ea982a24c11e0d33'),
        ('Wonju Business', '0xa4d5c8e24f86c4c80c0b4c1e37f9b8f0e1a2a8a8f0d8b6b3c3c2e0f8a1a4a8a8')
    ]
    
    # Amount to send (1000 CONFIO = 1000 * 10^6 = 1000000000)
    amount = 1000000000
    
    # CONFIO coin object ID from the deployer account
    confio_coin_id = "0x51ca5d2afe1ff7210945f604a9a3b015593a6bc2df4fff029e8b956f484c057b"
    
    print("Starting CONFIO distribution...")
    print(f"Amount per account: {amount} units (1000 CONFIO)")
    print(f"Using CONFIO coin: {confio_coin_id}")
    
    for i, (name, address) in enumerate(accounts):
        print(f"\n--- Sending 1000 CONFIO to {name} ({i+1}/4) ---")
        
        if i == 0:
            # First transfer: split from the main coin
            cmd = f"sui client split-coin --coin-id {confio_coin_id} --amounts {amount} --gas-budget 10000000"
            result = run_command(cmd)
            if not result:
                print(f"❌ Failed to split CONFIO coin")
                return False
            
            # Extract the new coin ID from the split result
            # The new coin will be created and we need to transfer it
            # For now, let's use pay with specific amounts
            cmd = f"sui client pay --input-coins {confio_coin_id} --recipients {address} --amounts {amount} --gas-budget 10000000"
        else:
            # Subsequent transfers: use the updated coin after previous splits
            cmd = f"sui client pay --input-coins {confio_coin_id} --recipients {address} --amounts {amount} --gas-budget 10000000"
        
        result = run_command(cmd)
        if result:
            print(f"✅ Successfully sent 1000 CONFIO to {name}")
        else:
            print(f"❌ Failed to send CONFIO to {name}")
            return False
    
    print("\n🎉 CONFIO distribution complete!")
    
    # Check remaining balance
    print("\n--- Checking remaining balance ---")
    remaining_cmd = "sui client balance --coin-type 0x2c5f46d4dda1ca49ed4b2c223bd1137b0f8f005a7f6012eb8bc09bf3a858cd56::confio::CONFIO"
    run_command(remaining_cmd)
    
    return True

if __name__ == "__main__":
    success = distribute_confio()
    sys.exit(0 if success else 1)