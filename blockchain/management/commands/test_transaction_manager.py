"""
Test the transaction manager with coin preparation
"""
import asyncio
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import User, Account
from blockchain.transaction_manager import TransactionManager
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Test transaction manager coin preparation'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            help='User email to test with'
        )
        parser.add_argument(
            '--token',
            type=str,
            default='CUSD',
            help='Token type (CUSD, CONFIO, USDC)'
        )
        parser.add_argument(
            '--amount',
            type=Decimal,
            default=Decimal('1'),
            help='Amount to prepare for transaction'
        )
        parser.add_argument(
            '--estimate',
            action='store_true',
            help='Only estimate transaction cost'
        )
    
    def handle(self, *args, **options):
        email = options.get('email')
        token = options.get('token').upper()
        amount = options['amount']
        estimate_only = options.get('estimate')
        
        if not email:
            self.stdout.write(self.style.ERROR('Email required'))
            return
        
        try:
            user = User.objects.get(email=email)
            account = user.accounts.filter(is_active=True).first()
            
            if not account:
                self.stdout.write(self.style.ERROR(f'No active account for {email}'))
                return
            
            self.stdout.write(f"\n🔍 Testing transaction manager for {email}")
            self.stdout.write(f"   Account: {account.name} ({account.algorand_address[:16]}...)")
            self.stdout.write(f"   Token: {token}")
            self.stdout.write(f"   Amount: {amount}")
            
            # Run async operations
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                if estimate_only:
                    # Estimate transaction cost
                    estimate = loop.run_until_complete(
                        TransactionManager.estimate_transaction_cost(
                            account,
                            token,
                            amount
                        )
                    )
                    
                    self.stdout.write(f"\n📊 Transaction Estimate:")
                    self.stdout.write(f"   Total coins owned: {estimate['total_coins']}")
                    self.stdout.write(f"   Coins needed: {estimate['coins_needed']}")
                    self.stdout.write(f"   Needs merge: {estimate['needs_merge']}")
                    self.stdout.write(f"\n💸 Gas Estimates:")
                    self.stdout.write(f"   Direct send: {estimate['gas_estimates']['direct']:,} MIST")
                    self.stdout.write(f"   Merge cost: {estimate['gas_estimates']['merge_cost']:,} MIST")
                    self.stdout.write(f"   After merge: {estimate['gas_estimates']['after_merge']:,} MIST")
                    self.stdout.write(f"   Savings: {estimate['gas_estimates']['savings']:,} MIST")
                    self.stdout.write(f"\n✅ Recommendation: {estimate['recommendation']}")
                    
                else:
                    # Prepare coins for transaction
                    prepared = loop.run_until_complete(
                        TransactionManager.prepare_coins(
                            account,
                            token,
                            amount,
                            merge_if_needed=True
                        )
                    )
                    
                    self.stdout.write(f"\n🪙 Coin Preparation Results:")
                    self.stdout.write(f"   Total coins owned: {prepared['total_coins']}")
                    self.stdout.write(f"   Coins selected: {len(prepared['coins'])}")
                    self.stdout.write(f"   Needs merge: {prepared['needs_merge']}")
                    self.stdout.write(f"   Actually merged: {prepared['merged']}")
                    
                    self.stdout.write(f"\n📦 Selected Coins:")
                    total_balance = Decimal('0')
                    for i, coin in enumerate(prepared['coins']):
                        balance = Decimal(coin['balance'])
                        if token == 'CUSD' or token == 'USDC':
                            balance = balance / Decimal(10 ** 6)
                        else:  # CONFIO
                            balance = balance / Decimal(10 ** 9)
                        total_balance += balance
                        
                        self.stdout.write(
                            f"   {i+1}. {coin['objectId'][:16]}... "
                            f"Balance: {balance} {token}"
                        )
                    
                    self.stdout.write(f"\n💰 Total selected: {total_balance} {token}")
                    
                    if prepared['merged']:
                        self.stdout.write(
                            f"\n✅ Coins were merged into primary coin: "
                            f"{prepared['primary_coin']['objectId'][:16]}..."
                        )
                    
            finally:
                loop.close()
                
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User {email} not found'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
            logger.exception("Transaction manager test failed")


# Test with decorator example
@TransactionManager.prepare_transaction('CUSD')
async def example_send_function(account: Account, recipient: str, amount: Decimal):
    """Example function using the decorator"""
    # Access prepared coins
    prepared = account._prepared_coins
    print(f"Using {len(prepared['coins'])} coins for transaction")
    return "tx_hash_example"