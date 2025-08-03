#!/usr/bin/env python3
"""
Script to mint cUSD tokens from the original package (0x551a...)
This script has the correct object IDs for PauseState and FreezeRegistry
"""

import subprocess
import sys
import os

# Configuration for ORIGINAL cUSD package (0x551a...)
CUSD_PACKAGE_ID = "0x551a39bd96679261aaf731e880b88fa528b66ee2ef6f0da677bdf0762b907bcf"
TREASURY_CAP_ID = "0xadbc39527efb7cfc63a5e9102aba7aa0c20f7957d851630a52f98547bc9ab68c"

# Shared objects found from deployment transaction 3dFHYZxVY7cEiH7xJQ4q4oAC6urQpvDYzVKiN1DstNAK
PAUSE_STATE_ID = "0x55616cc257b5fa731fa561b92c80a3153a6b0c015011c526f73bc7307e97e388"
FREEZE_REGISTRY_ID = "0xb1b2cca965ff21e31db0f61017d0af12032f8f97f385e2aa6e7996d07c99394a"

# AdminCap for unfreezing addresses if needed
ADMIN_CAP_ID = "0x40bff04a420ec25ba15adb93205a860df98fd29ed32be37ba20ef658c51f44a5"

def unfreeze_address(address):
    """Unfreeze an address using AdminCap"""
    cmd = [
        "sui", "client", "call",
        "--package", CUSD_PACKAGE_ID,
        "--module", "cusd",
        "--function", "unfreeze_address",
        "--args", 
        ADMIN_CAP_ID,
        FREEZE_REGISTRY_ID,
        address,
        "--gas-budget", "10000000"
    ]
    
    print(f"Unfreezing address {address}")
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
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python mint_original_cusd.py unfreeze <address>")
        print("  python mint_original_cusd.py mint <amount_in_cusd> <recipient_address>")
        print("Example: python mint_original_cusd.py mint 1000 0xed36f82d851c5b54ebc8b58a71ea6473823e073a01ce8b6a5c04a4bcebaf6aef")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "unfreeze":
        if len(sys.argv) != 3:
            print("Usage: python mint_original_cusd.py unfreeze <address>")
            sys.exit(1)
        address = sys.argv[2]
        unfreeze_address(address)
    
    elif command == "mint":
        if len(sys.argv) != 4:
            print("Usage: python mint_original_cusd.py mint <amount_in_cusd> <recipient_address>")
            sys.exit(1)
        amount_cusd = float(sys.argv[2])
        amount_units = int(amount_cusd * 1e6)  # Convert to smallest units
        recipient = sys.argv[3]
        mint_cusd(amount_units, recipient)
    
    else:
        print("Unknown command. Use 'unfreeze' or 'mint'")
        sys.exit(1)