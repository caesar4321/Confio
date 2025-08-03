#!/usr/bin/env python3
"""
Deploy a fresh instance of cUSD contract for testing
This will create new PauseState and FreezeRegistry objects
"""

import subprocess
import json
import re
import sys
import os

def deploy_cusd():
    """Deploy a fresh cUSD contract and capture the created objects"""
    
    print("Deploying fresh cUSD contract for testing...")
    print("="*60)
    
    # Change to the cUSD contract directory
    cusd_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'contracts', 'cusd')
    os.chdir(cusd_dir)
    print(f"Working directory: {os.getcwd()}")
    
    # Build the contract first
    print("\n1. Building cUSD contract...")
    build_cmd = ["sui", "move", "build"]
    
    try:
        result = subprocess.run(build_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Build failed: {result.stderr}")
            return False
        print("Build successful!")
    except Exception as e:
        print(f"Build error: {e}")
        return False
    
    # Deploy the contract
    print("\n2. Publishing cUSD contract...")
    publish_cmd = ["sui", "client", "publish", "--gas-budget", "100000000"]
    
    try:
        result = subprocess.run(publish_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Publish failed: {result.stderr}")
            return False
        
        output = result.stdout
        print("Publish successful!")
        
        # Parse the output to find important information
        print("\n3. Parsing deployment results...")
        
        # Find the package ID
        package_match = re.search(r'Published Objects:.*?PackageID: (0x[a-f0-9]+)', output, re.DOTALL)
        if package_match:
            package_id = package_match.group(1)
            print(f"\nPackage ID: {package_id}")
        else:
            print("Could not find package ID in output")
            print("Output:", output)
            return False
        
        # Find created objects
        created_objects = []
        
        # Look for shared objects in the output
        # Pattern: Object ID: <id> ... Owner: Shared
        object_pattern = re.compile(r'Object ID: (0x[a-f0-9]+).*?Owner: Shared', re.DOTALL)
        
        for match in object_pattern.finditer(output):
            object_id = match.group(1)
            created_objects.append(object_id)
        
        if created_objects:
            print(f"\nFound {len(created_objects)} shared objects:")
            for obj in created_objects:
                print(f"  - {obj}")
        else:
            # Alternative parsing method
            print("\nTrying alternative parsing for created objects...")
            
            # Look for "Created Objects" section
            created_section = re.search(r'Created Objects:(.*?)(?=\n\n|\Z)', output, re.DOTALL)
            if created_section:
                object_lines = created_section.group(1).strip().split('\n')
                for line in object_lines:
                    if 'Owner: Shared' in line:
                        # Extract object ID from the line
                        obj_match = re.search(r'(0x[a-f0-9]+)', line)
                        if obj_match:
                            created_objects.append(obj_match.group(1))
        
        # Find transaction digest
        tx_match = re.search(r'Transaction Digest: (\w+)', output)
        if tx_match:
            tx_digest = tx_match.group(1)
            print(f"\nTransaction Digest: {tx_digest}")
            
            # We can query this transaction to get more details
            print("\nQuerying transaction for created objects...")
            query_cmd = ["sui", "client", "tx-block", tx_digest, "--json"]
            
            try:
                query_result = subprocess.run(query_cmd, capture_output=True, text=True)
                if query_result.returncode == 0:
                    tx_data = json.loads(query_result.stdout)
                    
                    # Look for created objects in effects
                    if 'effects' in tx_data and 'created' in tx_data['effects']:
                        print("\nCreated objects from transaction:")
                        pause_state_id = None
                        freeze_registry_id = None
                        
                        for obj in tx_data['effects']['created']:
                            obj_type = obj.get('objectType', '')
                            obj_id = obj.get('objectId', '')
                            owner = obj.get('owner', {})
                            
                            print(f"  - ID: {obj_id}")
                            print(f"    Type: {obj_type}")
                            print(f"    Owner: {owner}")
                            
                            # Check if this is PauseState or FreezeRegistry
                            if 'PauseState' in obj_type and owner == 'Shared':
                                pause_state_id = obj_id
                            elif 'FreezeRegistry' in obj_type and owner == 'Shared':
                                freeze_registry_id = obj_id
                        
                        if pause_state_id and freeze_registry_id:
                            print("\n" + "="*60)
                            print("SUCCESS! Found required shared objects:")
                            print("="*60)
                            print(f"Package ID: {package_id}")
                            print(f"PauseState ID: {pause_state_id}")
                            print(f"FreezeRegistry ID: {freeze_registry_id}")
                            print("\nUpdate your configuration with these values!")
                            
                            # Update the mint script
                            update_mint_script(pause_state_id, freeze_registry_id)
                            
                            # Save to a config file
                            save_deployment_info(package_id, pause_state_id, freeze_registry_id, tx_digest)
                            
                            return True
            except Exception as e:
                print(f"Error querying transaction: {e}")
        
        print("\nDeployment completed but could not automatically find shared objects.")
        print("Please check the transaction on Sui Explorer:")
        print(f"https://suiexplorer.com/txblock/{tx_digest}?network=testnet")
        
    except Exception as e:
        print(f"Deployment error: {e}")
        return False
    
    return False

def update_mint_script(pause_state_id, freeze_registry_id):
    """Update the mint script with the new object IDs"""
    
    mint_script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'mint_cusd.py')
    
    try:
        with open(mint_script_path, 'r') as f:
            content = f.read()
        
        # Replace the placeholder IDs
        content = re.sub(r'PAUSE_STATE_ID = "0x\?+?"', f'PAUSE_STATE_ID = "{pause_state_id}"', content)
        content = re.sub(r'FREEZE_REGISTRY_ID = "0x\?+?"', f'FREEZE_REGISTRY_ID = "{freeze_registry_id}"', content)
        
        with open(mint_script_path, 'w') as f:
            f.write(content)
        
        print(f"\nUpdated mint script with new object IDs")
        
    except Exception as e:
        print(f"\nError updating mint script: {e}")

def save_deployment_info(package_id, pause_state_id, freeze_registry_id, tx_digest):
    """Save deployment information to a file"""
    
    deployment_info = {
        "network": "testnet",
        "package_id": package_id,
        "pause_state_id": pause_state_id,
        "freeze_registry_id": freeze_registry_id,
        "deployment_tx": tx_digest,
        "timestamp": subprocess.run(["date"], capture_output=True, text=True).stdout.strip()
    }
    
    deployment_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cusd_deployment.json')
    
    try:
        with open(deployment_file, 'w') as f:
            json.dump(deployment_info, f, indent=2)
        
        print(f"\nSaved deployment info to: {deployment_file}")
    except Exception as e:
        print(f"\nError saving deployment info: {e}")

if __name__ == "__main__":
    success = deploy_cusd()
    
    if not success:
        print("\n" + "="*60)
        print("DEPLOYMENT INCOMPLETE")
        print("="*60)
        print("\nPlease check the output above for errors.")
        print("You may need to manually find the shared objects from the deployment transaction.")
        sys.exit(1)