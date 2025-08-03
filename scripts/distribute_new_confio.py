#!/usr/bin/env python3
"""
Script to distribute 1000 CONFIO each from the new corrected contract
Package: 0x2c5f46d4dda1ca49ed4b2c223bd1137b0f8f005a7f6012eb8bc09bf3a858cd56
"""

import subprocess
import sys

# New CONFIO contract with 1B supply and 6 decimals
CONFIO_COIN_ID = "0x51ca5d2afe1ff7210945f604a9a3b015593a6bc2df4fff029e8b956f484c057b"
CONFIO_PACKAGE_ID = "0x2c5f46d4dda1ca49ed4b2c223bd1137b0f8f005a7f6012eb8bc09bf3a858cd56"

# Account addresses
ACCOUNTS = {
    "julian_personal": "0x984e1ced3883fbd8b1867b0b68b92a223cde7a0f7470b71e260adb39ff1d827e",
    "julian_business": "0xda4fb7201e9abb2304c3367939914524842e0a41b61b2c305bd64656f3f25792", 
    "wonju_personal": "0xec536ec9495b8f84332814d2ba9faf3d75cb921dd3d464f5b52133dd841407ee",
    "wonju_business": "0x1cf3e01b4879b386002cdadb2463d1635917cdda550658788dd77750f5f3736f"
}

def split_and_send_confio(recipient, amount_confio):
    """Split CONFIO coin and send to recipient"""
    
    # Convert to smallest units (6 decimals for CONFIO)
    amount_units = int(amount_confio * 1e6)
    
    cmd = [
        "sui", "client", "call",
        "--package", "0x2",  # Sui standard library
        "--module", "pay",
        "--function", "split_and_transfer",
        "--type-args", f"{CONFIO_PACKAGE_ID}::confio::CONFIO",
        "--args", 
        CONFIO_COIN_ID,
        str(amount_units),
        recipient,
        "--gas-budget", "10000000"
    ]
    
    print(f"Sending {amount_confio:,} CONFIO to {recipient}")
    print(f"Command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print("Success!")
            return True
        else:
            print("Error:")
            print(result.stderr)
            return False
    except Exception as e:
        print(f"Exception: {e}")
        return False

if __name__ == "__main__":
    # Send 1000 CONFIO to each account
    amount_per_account = 1000
    
    for name, address in ACCOUNTS.items():
        print(f"\n=== Sending to {name} ===")
        success = split_and_send_confio(address, amount_per_account)
        if not success:
            print(f"Failed to send to {name}")
            break
        print(f"Successfully sent {amount_per_account:,} CONFIO to {name}")
    
    print(f"\nDistribution complete! Each account now has {amount_per_account:,} CONFIO tokens.")