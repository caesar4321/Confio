#!/usr/bin/env python3
import os
import sys
sys.path.append('.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from aptos_sdk.account import Account
from django.conf import settings

# Get sponsor credentials
sponsor_address = settings.APTOS_SPONSOR_ADDRESS
sponsor_private_key = getattr(settings, 'APTOS_SPONSOR_PRIVATE_KEY', None)

print(f'Configured sponsor address: {sponsor_address}')
print(f'Has sponsor private key: {bool(sponsor_private_key)}')

if sponsor_private_key:
    try:
        sponsor_account = Account.load_key(sponsor_private_key)
        derived_address = str(sponsor_account.address())
        print(f'Derived address from private key: {derived_address}')
        print(f'Addresses match: {sponsor_address == derived_address}')
        
        if sponsor_address != derived_address:
            print('ERROR: Sponsor address mismatch!')
            print('This would cause INVALID_SIGNATURE errors')
        else:
            print('SUCCESS: Sponsor address matches private key')
    except Exception as e:
        print(f'Error loading sponsor account: {e}')
else:
    print('No sponsor private key configured')