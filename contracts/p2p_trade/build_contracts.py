#!/usr/bin/env python3
"""Build P2P Trade Contract"""

import os
import json
from pathlib import Path
from p2p_trade import app

# Build output directory
ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)

def build_p2p_trade():
    """Build the P2P trade contract"""
    print("Building P2P Trade Contract...")
    
    # Build the application spec
    app_spec = app.build()
    
    # Save approval program
    approval_file = ARTIFACTS_DIR / "p2p_trade_approval.teal"
    with open(approval_file, "w") as f:
        f.write(app_spec.approval_program)
    print(f"✓ Approval program saved to {approval_file}")
    
    # Save clear program
    clear_file = ARTIFACTS_DIR / "p2p_trade_clear.teal"
    with open(clear_file, "w") as f:
        f.write(app_spec.clear_program)
    print(f"✓ Clear program saved to {clear_file}")
    
    # Save ABI
    abi_file = ARTIFACTS_DIR / "p2p_trade.json"
    with open(abi_file, "w") as f:
        f.write(app_spec.to_json())
    print(f"✓ ABI saved to {abi_file}")
    
    print(f"\nContract Statistics:")
    print(f"  Approval program size: {len(app_spec.approval_program.encode())} bytes")
    print(f"  Clear program size: {len(app_spec.clear_program.encode())} bytes")
    
    print("\n✅ P2P Trade contract built successfully!")
    
if __name__ == "__main__":
    build_p2p_trade()