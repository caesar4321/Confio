#!/usr/bin/env python3
"""
Script to mint cUSD tokens for testing
This requires the PauseState and FreezeRegistry object IDs
"""

import subprocess
import sys
import os

# Configuration for NEW deployment (deployed fresh on 2025-08-02)
CUSD_PACKAGE_ID = "0x1eaf40cd86c66cf6da72202ee2f11b2922be0270cd5ce248057ed48f106f8233"
TREASURY_CAP_ID = "0x2dba12e8a3c92ce824861814fb9fab482abc175a8952de293f4eb10469b2501b"

# Shared objects from deployment transaction HpnRD5pU5pN1HcQnhHjCWz7cR8iPsTtbaYAyn3i23xp2
PAUSE_STATE_ID = "0xefc39f994141412a66fad49b4594a6c9f81789f14b9406614ddb933e8f441f2c"
FREEZE_REGISTRY_ID = "0xf5fddd7297e650af9d73dc314355fc909efae879f218966baf6b60839cf057aa"

def mint_cusd(amount, recipient):
    """Mint cUSD tokens to a recipient address"""
    
    cmd = [
        "sui", "client", "call",
        "--package", CUSD_PACKAGE_ID,
        "--module", "cusd",
        "--function", "mint_and_transfer",
        "--args", 
        TREASURY_CAP_ID,
        PAUSE_STATE_ID,
        FREEZE_REGISTRY_ID,
        str(amount),  # amount in smallest units (6 decimals)
        recipient,    # deposit_address
        recipient,    # recipient
        "--gas-budget", "10000000"
    ]
    
    print(f"Minting {amount / 1e6} cUSD to {recipient}")
    print(f"Command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print("Success!")
            print(result.stdout)
            return True
        else:
            print("Error:")
            print(result.stderr)
            return False
    except Exception as e:
        print(f"Exception: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python mint_cusd.py <amount_in_cusd> <recipient_address>")
        print("Example: python mint_cusd.py 1000 0xed36f82d851c5b54ebc8b58a71ea6473823e073a01ce8b6a5c04a4bcebaf6aef")
        sys.exit(1)
    
    amount_cusd = float(sys.argv[1])
    amount_units = int(amount_cusd * 1e6)  # Convert to smallest units
    recipient = sys.argv[2]
    
    mint_cusd(amount_units, recipient)