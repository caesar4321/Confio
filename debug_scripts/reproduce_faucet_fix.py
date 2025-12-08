
import os
import sys
import django
from unittest.mock import MagicMock, patch

# Setup Django environment
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_account_manager import AlgorandAccountManager
from users.models import User, Account

def test_faucet_logic():
    print("Testing Faucet Logic Fix...")
    
    # Mock user and account
    user = User(email='test@example.com', username='testuser')
    user.save = MagicMock()
    
    # Mock Account.objects.get_or_create
    account = Account(user=user, account_type='personal', account_index=0)
    account.algorand_address = "TESTADDRESS123456789012345678901234567890123456789012345678"
    account.save = MagicMock()
    
    with patch('users.models.Account.objects.get_or_create', return_value=(account, False)):
        with patch('blockchain.algorand_account_manager.AlgorandAccountManager._check_opt_ins') as mock_check_opt_ins:
            with patch('blockchain.algorand_account_manager.AlgorandAccountManager._opt_in_to_asset') as mock_opt_in:
                with patch('blockchain.algorand_account_manager.AlgorandAccountManager._send_initial_confio') as mock_send_confio:
                    with patch('blockchain.algorand_client.get_algod_client') as mock_get_client:
                        
                        # Scenario 1: User NOT opted in (New user behavior)
                        print("\nScenario 1: User NOT opted in (New user behavior)")
                        mock_check_opt_ins.return_value = [] # Not opted in
                        # _opt_in_to_asset returns (success, already_opted_in)
                        mock_opt_in.return_value = (True, False) 
                        
                        AlgorandAccountManager.get_or_create_algorand_account(user)
                        
                        if mock_send_confio.called:
                            print("PASS: Initial grant sent for new user.")
                        else:
                            print("FAIL: Initial grant NOT sent for new user.")
                            
                        # Reset mocks
                        mock_send_confio.reset_mock()
                        
                        # Scenario 2: User ALREADY opted in (Existing user/Abuse attempt)
                        print("\nScenario 2: User ALREADY opted in (Existing user/Abuse attempt)")
                        mock_check_opt_ins.return_value = [] # Not opted in locally yet (simulating check)
                        # _opt_in_to_asset returns (success, already_opted_in)
                        mock_opt_in.return_value = (True, True) # Success, but WAS already opted in
                        
                        AlgorandAccountManager.get_or_create_algorand_account(user)
                        
                        if not mock_send_confio.called:
                            print("PASS: Initial grant SKIPPED for already opted-in user.")
                        else:
                            print("FAIL: Initial grant SENT for already opted-in user (Vulnerability exists!).")

if __name__ == "__main__":
    test_faucet_logic()
