#!/usr/bin/env python3
"""
Script to distribute CONFIO tokens to the 4 main accounts
Since CONFIO TreasuryCap is frozen, we need to split existing coins
"""

import subprocess
import sys

# CONFIO coin object with 1 billion tokens
CONFIO_COIN_ID = "0xdfe466f06eb77807f6947ef90bd6ddce03ba758d18faed0922be17e8bcf20cfd"
CONFIO_PACKAGE_ID = "0xfa39d9b961930750646148de35923d789561a4d47571bd7ff17eda9d6f9ec17c"

# Account addresses
ACCOUNTS = {
    "julian_personal": "0x984e1ced3883fbd8b1867b0b68b92a223cde7a0f7470b71e260adb39ff1d827e",
    "julian_business": "0xda4fb7201e9abb2304c3367939914524842e0a41b61b2c305bd64656f3f25792", 
    "wonju_personal": "0xec536ec9495b8f84332814d2ba9faf3d75cb921dd3d464f5b52133dd841407ee",
    "wonju_business": "0x1cf3e01b4879b386002cdadb2463d1635917cdda550658788dd77750f5f3736f"
}

def split_and_send_confio(recipient, amount_confio):
    """Split CONFIO coin and send to recipient"""
    
    # Convert to smallest units (9 decimals for CONFIO)
    amount_units = int(amount_confio * 1e9)
    
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
    
    print(f"Sending {amount_confio} CONFIO to {recipient}")
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
    # If we have 1 billion smallest units and 9 decimals, that's 1 CONFIO total
    # Send 0.2 CONFIO to each account (200 million smallest units each)
    amount_per_account = 0.2  # 0.2 CONFIO per account
    
    for name, address in ACCOUNTS.items():
        print(f"\n=== Sending to {name} ===")
        success = split_and_send_confio(address, amount_per_account)
        if not success:
            print(f"Failed to send to {name}")
            break
        print(f"Successfully sent {amount_per_account:,} CONFIO to {name}")