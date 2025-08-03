#!/usr/bin/env python3
"""
Find cUSD shared objects (PauseState and FreezeRegistry)
These are created during contract deployment and are needed for minting
"""

import subprocess
import json
import sys

# Configuration
CUSD_PACKAGE_ID = "0x551a39bd96679261aaf731e880b88fa528b66ee2ef6f0da677bdf0762b907bcf"

def find_shared_objects():
    """
    Find shared objects created by the cUSD package.
    
    This searches for objects with the specific types:
    - {CUSD_PACKAGE_ID}::cusd::PauseState
    - {CUSD_PACKAGE_ID}::cusd::FreezeRegistry
    """
    
    print(f"Searching for cUSD shared objects from package: {CUSD_PACKAGE_ID}")
    
    # First, let's try to get the package publish transaction
    # This would contain the created objects
    
    # Try to find objects by type using the Sui explorer API or RPC
    # For now, we'll use a manual approach
    
    print("\nSearching for PauseState and FreezeRegistry objects...")
    print("These are shared objects created during contract deployment.")
    print("\nTo find them manually:")
    print("1. Check the transaction that deployed the cUSD package")
    print("2. Look for 'Created Objects' in the transaction effects")
    print("3. Find objects with types ending in '::cusd::PauseState' and '::cusd::FreezeRegistry'")
    print("\nAlternatively, use the Sui Explorer:")
    print(f"https://suiexplorer.com/object/{CUSD_PACKAGE_ID}?network=testnet")
    print("Then check the 'Created Objects' tab or the deployment transaction.")
    
    # Try to get some recent objects to see if we can find them
    print("\nAttempting to query for objects...")
    
    # This is a placeholder - in production, you'd use the Sui SDK or RPC
    # to query for objects by type
    
    return None, None

def update_mint_script(pause_state_id, freeze_registry_id):
    """Update the mint script with the found object IDs"""
    
    if not pause_state_id or not freeze_registry_id:
        print("\nCould not find the required objects automatically.")
        print("Please find them manually and update the mint script.")
        return
    
    print(f"\nFound objects:")
    print(f"PauseState: {pause_state_id}")
    print(f"FreezeRegistry: {freeze_registry_id}")
    
    # Update the mint script
    mint_script_path = "scripts/mint_cusd.py"
    
    try:
        with open(mint_script_path, 'r') as f:
            content = f.read()
        
        # Replace the placeholder IDs
        content = content.replace('PAUSE_STATE_ID = "0x???"', f'PAUSE_STATE_ID = "{pause_state_id}"')
        content = content.replace('FREEZE_REGISTRY_ID = "0x???"', f'FREEZE_REGISTRY_ID = "{freeze_registry_id}"')
        
        with open(mint_script_path, 'w') as f:
            f.write(content)
        
        print(f"\nUpdated {mint_script_path} with the object IDs")
        
    except Exception as e:
        print(f"\nError updating mint script: {e}")

if __name__ == "__main__":
    pause_state, freeze_registry = find_shared_objects()
    
    if pause_state and freeze_registry:
        update_mint_script(pause_state, freeze_registry)
    else:
        print("\n" + "="*60)
        print("MANUAL STEPS REQUIRED:")
        print("="*60)
        print("\n1. Visit the Sui Explorer link above")
        print("2. Find the deployment transaction")
        print("3. Look for created objects with these types:")
        print(f"   - {CUSD_PACKAGE_ID}::cusd::PauseState")
        print(f"   - {CUSD_PACKAGE_ID}::cusd::FreezeRegistry")
        print("4. Update scripts/mint_cusd.py with the object IDs")
        print("\nExample object IDs look like:")
        print("   0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef")