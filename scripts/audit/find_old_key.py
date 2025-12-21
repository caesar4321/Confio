
import boto3
import sys
from algosdk import account, mnemonic

def find_key():
    target_address = "PRDLU7ZJRFB2ZMFJHQW3J5G3NEGN6HHV47CVKNHDAGF5P7MJAMHR37R72E"
    region_name = 'eu-central-2'
    
    print(f"Searching for key matching address: {target_address}")
    
    ssm = boto3.client('ssm', region_name=region_name)
    
    paginator = ssm.get_paginator('get_parameters_by_path')
    page_iterator = paginator.paginate(
        Path='/confio/algorand/',
        Recursive=True,
        WithDecryption=True
    )
    
    for page in page_iterator:
        for param in page['Parameters']:
            name = param['Name']
            if name.endswith('/private-key'):
                # Format is /confio/algorand/{alias}/private-key
                try:
                    parts = name.split('/')
                    # parts: ['', 'confio', 'algorand', 'alias', 'private-key']
                    if len(parts) >= 5:
                        alias = parts[3]
                        
                        private_key = param['Value']
                        address = account.address_from_private_key(private_key)
                        
                        if address == target_address:
                            print(f"MATCH FOUND!")
                            print(f"Alias: {alias}")
                            print(f"SSM Path: {name}")
                            return alias
                        
                        # Optimization: Check if alias looks like user ID 2696
                        if '2696' in alias:
                             print(f"Potential Alias Match (User ID): {alias} -> Address {address}")

                except Exception as e:
                    print(f"Error checking {name}: {e}")

    print("No matching key found in SSM path /confio/algorand/")
    return None

if __name__ == "__main__":
    find_key()
