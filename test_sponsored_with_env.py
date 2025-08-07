#!/usr/bin/env python
"""
Test Algorand sponsored transactions with environment variables loaded
"""
import os
import sys
import django
from dotenv import load_dotenv

# Load environment variables from .env.algorand
load_dotenv('/Users/julian/Confio/.env.algorand')

# Setup Django
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

# Now run the test
from test_algorand_sponsored import main
import asyncio

if __name__ == "__main__":
    print("Environment variables loaded:")
    print(f"ALGORAND_SPONSOR_ADDRESS: {os.environ.get('ALGORAND_SPONSOR_ADDRESS')}")
    print(f"ALGORAND_CONFIO_ASSET_ID: {os.environ.get('ALGORAND_CONFIO_ASSET_ID')}")
    print()
    
    asyncio.run(main())