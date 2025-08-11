#!/usr/bin/env python3
"""
Build script for Confío Algorand smart contracts
Compiles all PyTeal contracts to TEAL and generates ABI files
Website: https://confio.lat
"""

import os
import sys
import subprocess
from pathlib import Path

# Contract files to build
CONTRACTS = [
    "cusd.py",
    "p2p_trade.py", 
    "invite_send.py",
    "payment.py"
]

def build_contract(contract_file):
    """Build a single contract"""
    contract_name = contract_file.replace(".py", "")
    print(f"\n📦 Building {contract_name}...")
    
    try:
        # Run the contract file to generate TEAL and ABI
        result = subprocess.run(
            [sys.executable, contract_file],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Check if output files were created
        approval_file = f"{contract_name}_approval.teal"
        clear_file = f"{contract_name}_clear.teal"
        abi_file = f"{contract_name}.json"
        
        files_created = []
        if os.path.exists(approval_file):
            files_created.append(approval_file)
        if os.path.exists(clear_file):
            files_created.append(clear_file)
        if os.path.exists(abi_file):
            files_created.append(abi_file)
        
        if files_created:
            print(f"✅ {contract_name} built successfully!")
            print(f"   Generated files: {', '.join(files_created)}")
            if result.stdout:
                print(f"   {result.stdout.strip()}")
        else:
            print(f"⚠️  {contract_name} build completed but no output files found")
            
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to build {contract_name}")
        print(f"   Error: {e.stderr if e.stderr else 'Unknown error'}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error building {contract_name}: {e}")
        return False

def main():
    """Build all contracts"""
    print("🚀 Confío Algorand Smart Contracts Build Script")
    print("=" * 50)
    
    # Change to contracts directory
    contracts_dir = Path(__file__).parent
    os.chdir(contracts_dir)
    
    # Check if required packages are installed
    try:
        import pyteal
        import beaker
        print("✅ PyTeal and Beaker packages found")
    except ImportError as e:
        print("❌ Required packages not found. Please install:")
        print("   pip install pyteal beaker-pyteal")
        sys.exit(1)
    
    # Build each contract
    success_count = 0
    failed_contracts = []
    
    for contract in CONTRACTS:
        if os.path.exists(contract):
            if build_contract(contract):
                success_count += 1
            else:
                failed_contracts.append(contract)
        else:
            print(f"⚠️  Contract file {contract} not found, skipping...")
            failed_contracts.append(contract)
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Build Summary:")
    print(f"   ✅ Successfully built: {success_count}/{len(CONTRACTS)} contracts")
    
    if failed_contracts:
        print(f"   ❌ Failed contracts: {', '.join(failed_contracts)}")
        sys.exit(1)
    else:
        print("   🎉 All contracts built successfully!")
        print(f"\n🌐 Website: https://confio.lat")
        print("\n📝 Note: Contracts are ready but not deployed.")
        print("   To deploy, use the Algorand SDK with the generated TEAL files.")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())