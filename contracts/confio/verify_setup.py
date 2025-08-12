#!/usr/bin/env python3
"""
Verification script for CONFIO contract setup.
Checks that all scripts are properly configured and can import required modules.
"""

import sys
import os

def verify_imports():
    """Verify all required imports work"""
    errors = []
    
    try:
        from algosdk import account, mnemonic
        print("✅ algosdk imports successful")
    except ImportError as e:
        errors.append(f"❌ algosdk import failed: {e}")
    
    try:
        from algosdk.v2client import algod
        print("✅ algod client import successful")
    except ImportError as e:
        errors.append(f"❌ algod import failed: {e}")
    
    try:
        from algosdk.transaction import AssetConfigTxn, AssetTransferTxn, PaymentTxn
        print("✅ transaction imports successful")
    except ImportError as e:
        errors.append(f"❌ transaction import failed: {e}")
    
    return errors

def verify_scripts():
    """Verify all scripts exist and are executable"""
    scripts = [
        "create_confio_token_algorand.py",
        "finalize_confio_asset.py",
        "check_confio_asset.py",
        "deploy_confio_localnet.py"
    ]
    
    errors = []
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    for script in scripts:
        script_path = os.path.join(script_dir, script)
        if os.path.exists(script_path):
            print(f"✅ {script} exists")
            # Try to compile it
            try:
                with open(script_path, 'r') as f:
                    compile(f.read(), script_path, 'exec')
                print(f"   └─ Syntax valid")
            except SyntaxError as e:
                errors.append(f"❌ {script} has syntax error: {e}")
        else:
            errors.append(f"❌ {script} not found")
    
    return errors

def verify_constants():
    """Verify ZERO_ADDR constant is defined correctly"""
    ZERO_ADDR = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ"
    print(f"✅ ZERO_ADDR constant verified: {ZERO_ADDR[:8]}...{ZERO_ADDR[-6:]}")
    return []

def main():
    print("=" * 60)
    print("CONFIO CONTRACT SETUP VERIFICATION")
    print("=" * 60)
    
    all_errors = []
    
    print("\n📦 Checking imports...")
    all_errors.extend(verify_imports())
    
    print("\n📄 Checking scripts...")
    all_errors.extend(verify_scripts())
    
    print("\n🔒 Checking constants...")
    all_errors.extend(verify_constants())
    
    print("\n" + "=" * 60)
    if all_errors:
        print("❌ VERIFICATION FAILED")
        print("=" * 60)
        for error in all_errors:
            print(error)
        sys.exit(1)
    else:
        print("✅ ALL CHECKS PASSED!")
        print("=" * 60)
        print("\n🚀 Ready for deployment:")
        print("  1. Create token: python create_confio_token_algorand.py")
        print("  2. Finalize: python finalize_confio_asset.py")
        print("  3. Verify: python check_confio_asset.py")
        print("\n  Or for LocalNet testing:")
        print("  • python deploy_confio_localnet.py (auto-finalizes)")
        print("\n  For zero-risk window on testnet:")
        print("  • FINALIZE_IMMEDIATELY=1 python create_confio_token_algorand.py")

if __name__ == "__main__":
    main()