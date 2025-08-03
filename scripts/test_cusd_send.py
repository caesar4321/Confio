#!/usr/bin/env python3
"""
Test sending cUSD through the blockchain system
"""

import os
import sys
import django
import asyncio
from asgiref.sync import sync_to_async

# Setup Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import Account
from blockchain.models import Balance
from blockchain.transaction_manager import TransactionManager
from decimal import Decimal

@sync_to_async
def get_test_accounts():
    """Get test accounts synchronously"""
    # Find accounts with cUSD balance
    accounts_with_balance = []
    for account in Account.objects.filter(
        deleted_at__isnull=True,
        sui_address__isnull=False
    ).exclude(sui_address='').select_related('user'):
        balance = Balance.objects.filter(
            account=account,
            token='CUSD'
        ).first()
        if balance and balance.amount >= 10:
            accounts_with_balance.append((account, balance))
            if len(accounts_with_balance) >= 2:
                break
    return accounts_with_balance

@sync_to_async
def get_balance(account, token):
    """Get balance synchronously"""
    balance = Balance.objects.filter(
        account=account,
        token=token
    ).first()
    return balance

@sync_to_async
def update_balance(balance, new_amount):
    """Update balance synchronously"""
    balance.amount = new_amount
    balance.save()
    return balance

@sync_to_async
def create_balance(account, token, amount):
    """Create balance synchronously"""
    return Balance.objects.create(
        account=account,
        token=token,
        amount=amount
    )

async def test_cusd_send():
    """Test sending cUSD between accounts"""
    
    # Get two accounts with cUSD balance
    account_data = await get_test_accounts()
    
    if len(account_data) < 2:
        print("Not enough accounts with sufficient cUSD balance")
        return
    
    sender, sender_balance = account_data[0]
    recipient, _ = account_data[1]
    
    print(f"Test cUSD Send")
    print(f"==============")
    print(f"Sender: {sender.account_id} ({sender.user.username})")
    print(f"  Sui Address: {sender.sui_address}")
    print(f"  cUSD Balance: {sender_balance.amount}")
    print(f"\nRecipient: {recipient.account_id} ({recipient.user.username})")
    print(f"  Sui Address: {recipient.sui_address}")
    
    # Get recipient's initial balance
    recipient_balance = await get_balance(recipient, 'CUSD')
    initial_recipient_balance = recipient_balance.amount if recipient_balance else 0
    print(f"  Initial cUSD Balance: {initial_recipient_balance}")
    
    # Amount to send
    amount = Decimal('5.0')
    print(f"\nSending {amount} cUSD...")
    
    try:
        # Use TransactionManager to send tokens
        result = await TransactionManager.send_tokens(
            sender,
            recipient.sui_address,
            amount,
            'CUSD'
        )
        
        if result['success']:
            print(f"\n✅ Transaction successful!")
            print(f"Transaction digest: {result.get('digest', 'N/A')}")
            
            # Check if sponsored
            if result.get('sponsored'):
                print(f"Gas sponsored by: {result.get('sponsor', 'N/A')}")
                print(f"Gas saved: {result.get('gas_saved', 0)} SUI")
            
            # Check for warnings
            if result.get('warning'):
                print(f"⚠️  Warning: {result['warning']}")
            
            # Update database balances
            sender_balance.amount -= amount
            await update_balance(sender_balance, sender_balance.amount)
            print(f"\nSender new balance: {sender_balance.amount}")
            
            if recipient_balance:
                recipient_balance.amount += amount
                await update_balance(recipient_balance, recipient_balance.amount)
            else:
                recipient_balance = await create_balance(recipient, 'CUSD', amount)
            print(f"Recipient new balance: {recipient_balance.amount}")
            
        else:
            print(f"\n❌ Transaction failed!")
            print(f"Error: {result.get('error', 'Unknown error')}")
            if result.get('details'):
                print(f"Details: {result['details']}")
                
    except Exception as e:
        print(f"\n❌ Exception occurred: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Run the async function
    asyncio.run(test_cusd_send())