#!/usr/bin/env python3
"""
Build script for Payment Contract
Compiles the payment contract to TEAL and generates ABI
"""

import os
import sys
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from payment import app

def build_payment_contract():
    """Build the payment contract and save artifacts"""
    
    print("Building Payment Contract...")
    
    # Build the application
    app_spec = app.build()
    
    # Get the contract name
    contract_name = "payment"
    
    # Create output directory if it doesn't exist
    output_dir = Path(__file__).parent / "artifacts"
    output_dir.mkdir(exist_ok=True)
    
    # Save approval program
    approval_file = output_dir / f"{contract_name}_approval.teal"
    with open(approval_file, "w") as f:
        f.write(app_spec.approval_program)
    print(f"✓ Approval program saved to {approval_file}")
    
    # Save clear program
    clear_file = output_dir / f"{contract_name}_clear.teal"
    with open(clear_file, "w") as f:
        f.write(app_spec.clear_program)
    print(f"✓ Clear program saved to {clear_file}")
    
    # Save contract ABI
    abi_file = output_dir / f"{contract_name}.json"
    contract_dict = app_spec.export() if app_spec.export() else {}
    with open(abi_file, "w") as f:
        f.write(json.dumps(contract_dict, indent=2))
    print(f"✓ ABI saved to {abi_file}")
    
    # Print contract info
    print(f"\nContract Statistics:")
    print(f"  Approval program size: {len(app_spec.approval_program)} bytes")
    print(f"  Clear program size: {len(app_spec.clear_program)} bytes")
    
    # Print state schema info based on what we know about the contract
    print(f"\nGlobal State Schema:")
    print(f"  Bytes: 3 (admin, fee_recipient, sponsor_address)")
    print(f"  Uints: 11 (statistics and counters)")
    
    print(f"\nLocal State Schema:")
    print(f"  Bytes: 0")
    print(f"  Uints: 0")
    
    print("\n✅ Payment contract built successfully!")
    
    return app_spec

if __name__ == "__main__":
    build_payment_contract()