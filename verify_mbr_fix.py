import os
import django
from unittest.mock import patch, MagicMock

# Initialize Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

def verify_mbr_fix():
    print("Verifying MBR Duplicate Funding Fix...", flush=True)
    
    from blockchain.algorand_account_manager import AlgorandAccountManager
    from users.models import Account, User
    
    # Mock account
    user = User(username='test_user', email='test@example.com')
    account = Account(user=user, account_type='personal', account_index=0)
    # Simulate an account that needs funding (no address, or low balance if we could check)
    # We will simulate "no address" to trigger the logic flow
    
    # Mock the internal methods to verify calls
    with patch.object(AlgorandAccountManager, '_fund_account') as mock_fund, \
         patch.object(AlgorandAccountManager, '_opt_in_to_asset') as mock_opt_in:
        
        print("Test 1: Calling ensure_account_ready with fund_and_opt_in=False", flush=True)
        # Call with flag=False (what mutations.py does now)
        # Start with NO address
        account.algorand_address = None
        
        # We need to simulate a valid address being provided if we want it to proceed past check
        # Or we rely on existing_address param
        existing_addr = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        
        result = AlgorandAccountManager.ensure_account_ready(
            account, 
            existing_address=existing_addr,
            fund_and_opt_in=False
        )
        
        print(f"Result: {result['algorand_address']}", flush=True)
        
        if mock_fund.called:
            print("FAILURE: _fund_account was called!", flush=True)
        else:
            print("SUCCESS: _fund_account was NOT called.", flush=True)
            
        if mock_opt_in.called:
             print("FAILURE: _opt_in_to_asset was called!", flush=True)
        else:
             print("SUCCESS: _opt_in_to_asset was NOT called.", flush=True)

        print("\nTest 2: Calling ensure_account_ready with default (True)", flush=True)
        # Call with default (what legacy/other paths do)
        result_default = AlgorandAccountManager.ensure_account_ready(
            account, 
            existing_address=existing_addr
        )
        
        if mock_fund.called:
            print("SUCCESS: _fund_account was called (as expected for default).", flush=True)
        else:
            print("FAILURE: _fund_account was NOT called for default!", flush=True)

if __name__ == '__main__':
    verify_mbr_fix()
