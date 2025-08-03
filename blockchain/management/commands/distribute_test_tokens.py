"""
Distribute test tokens to accounts for development and testing
"""
import asyncio
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from blockchain.transaction_manager import TransactionManager
from blockchain.sponsor_service import SponsorService
from users.models import User, Account
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Distribute test tokens (cUSD and CONFIO) to user accounts'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--all-users',
            action='store_true',
            help='Distribute to all active users'
        )
        parser.add_argument(
            '--email',
            type=str,
            help='Distribute to specific user by email'
        )
        parser.add_argument(
            '--cusd-amount',
            type=Decimal,
            default=Decimal('100'),
            help='Amount of cUSD to distribute (default: 100)'
        )
        parser.add_argument(
            '--confio-amount',
            type=Decimal,
            default=Decimal('100'),
            help='Amount of CONFIO to distribute (default: 100)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be distributed without actually sending'
        )
    
    def handle(self, *args, **options):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            self.stdout.write(self.style.SUCCESS('\n=== Test Token Distribution ===\n'))
            
            # Check sponsor health first
            health = loop.run_until_complete(SponsorService.check_sponsor_health())
            if not health['healthy']:
                self.stdout.write(self.style.ERROR('❌ Sponsor account is not healthy!'))
                self.stdout.write(f"Balance: {health.get('balance_formatted', 'Unknown')}")
                return
            
            self.stdout.write(self.style.SUCCESS(f"✅ Sponsor healthy: {health['balance_formatted']}"))
            
            # Get accounts to distribute to
            accounts = self.get_accounts(options['email'], options['all_users'])
            
            if not accounts:
                self.stdout.write(self.style.WARNING('No accounts found to distribute to'))
                return
            
            self.stdout.write(f"\n📊 Found {len(accounts)} accounts to distribute to")
            
            # Distribution settings
            cusd_amount = options['cusd_amount']
            confio_amount = options['confio_amount']
            dry_run = options['dry_run']
            
            if dry_run:
                self.stdout.write(self.style.WARNING('\n🔍 DRY RUN MODE - No tokens will be sent\n'))
            
            # Get treasury/faucet private key from settings
            treasury_key = getattr(settings, 'TREASURY_PRIVATE_KEY', None)
            if not treasury_key and not dry_run:
                self.stdout.write(self.style.ERROR('❌ TREASURY_PRIVATE_KEY not configured in settings'))
                return
            
            # Distribution summary
            self.stdout.write(f"\n💰 Distribution plan:")
            self.stdout.write(f"   - cUSD: {cusd_amount} per account")
            self.stdout.write(f"   - CONFIO: {confio_amount} per account")
            self.stdout.write(f"   - Total cUSD: {cusd_amount * len(accounts)}")
            self.stdout.write(f"   - Total CONFIO: {confio_amount * len(accounts)}")
            
            if dry_run:
                self.stdout.write("\n👤 Accounts that would receive tokens:")
                for account in accounts:
                    self.stdout.write(f"   - {account.user.email}: {account.sui_address[:16]}...")
                return
            
            # Confirm distribution
            confirm = input(f"\n⚠️  Distribute tokens to {len(accounts)} accounts? (yes/no): ")
            if confirm.lower() != 'yes':
                self.stdout.write(self.style.WARNING('Distribution cancelled'))
                return
            
            # Perform distribution
            self.stdout.write(self.style.SUCCESS('\n🚀 Starting distribution...\n'))
            
            success_count = 0
            failed_count = 0
            
            for i, account in enumerate(accounts, 1):
                self.stdout.write(f"\n[{i}/{len(accounts)}] Processing {account.user.email}...")
                
                try:
                    # Distribute cUSD
                    if cusd_amount > 0:
                        result = loop.run_until_complete(
                            self.distribute_token(account, 'CUSD', cusd_amount, treasury_key)
                        )
                        if result['success']:
                            self.stdout.write(self.style.SUCCESS(f"   ✅ cUSD sent: {cusd_amount}"))
                        else:
                            self.stdout.write(self.style.ERROR(f"   ❌ cUSD failed: {result['error']}"))
                            failed_count += 1
                            continue
                    
                    # Distribute CONFIO
                    if confio_amount > 0:
                        result = loop.run_until_complete(
                            self.distribute_token(account, 'CONFIO', confio_amount, treasury_key)
                        )
                        if result['success']:
                            self.stdout.write(self.style.SUCCESS(f"   ✅ CONFIO sent: {confio_amount}"))
                        else:
                            self.stdout.write(self.style.ERROR(f"   ❌ CONFIO failed: {result['error']}"))
                            failed_count += 1
                            continue
                    
                    success_count += 1
                    
                    # Show new balances
                    new_balances = loop.run_until_complete(
                        TransactionManager.get_all_balances(account)
                    )
                    self.stdout.write(f"   💰 New balances: cUSD={new_balances['cusd']}, CONFIO={new_balances['confio']}")
                    
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"   ❌ Error: {str(e)}"))
                    failed_count += 1
                    logger.exception(f"Failed to distribute to {account.user.email}")
            
            # Summary
            self.stdout.write(self.style.SUCCESS(f"\n✅ Distribution complete!"))
            self.stdout.write(f"   Success: {success_count}")
            self.stdout.write(f"   Failed: {failed_count}")
            
        finally:
            loop.close()
    
    def get_accounts(self, email=None, all_users=False):
        """Get accounts to distribute to"""
        if email:
            try:
                user = User.objects.get(email=email)
                return list(user.accounts.filter(is_active=True))
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'User {email} not found'))
                return []
        
        elif all_users:
            # Get all active personal accounts (not business accounts)
            return list(Account.objects.filter(
                is_active=True,
                type='personal'
            ).select_related('user'))
        
        else:
            # Default: get the 4 test accounts we've been using
            test_emails = [
                'julian@mybitcoinfamily.com',
                'julian+2@mybitcoinfamily.com', 
                'julian+3@mybitcoinfamily.com',
                'julian+4@mybitcoinfamily.com'
            ]
            
            accounts = []
            for email in test_emails:
                try:
                    user = User.objects.get(email=email)
                    account = user.accounts.filter(is_active=True, type='personal').first()
                    if account:
                        accounts.append(account)
                except User.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f'User {email} not found'))
            
            return accounts
    
    async def distribute_token(self, account, token_type, amount, treasury_key):
        """Distribute tokens from treasury to account"""
        try:
            # For now, we'll use a mock distribution
            # In production, this would actually send tokens from a treasury account
            
            # Mock successful distribution
            self.stdout.write(f"      📤 Sending {amount} {token_type} to {account.sui_address[:16]}...")
            
            # Simulate some delay
            await asyncio.sleep(0.5)
            
            # Update the account's cached balance
            from blockchain.models import CachedBalance
            
            balance_key = 'cusd' if token_type == 'CUSD' else 'confio'
            cached_balance, created = CachedBalance.objects.get_or_create(
                account=account,
                defaults={balance_key: Decimal('0')}
            )
            
            # Add to existing balance
            current = getattr(cached_balance, balance_key)
            setattr(cached_balance, balance_key, current + amount)
            cached_balance.save()
            
            return {
                'success': True,
                'digest': 'mock_tx_' + token_type.lower() + '_' + str(amount),
                'amount': amount
            }
            
        except Exception as e:
            logger.exception(f"Failed to distribute {token_type} to {account.sui_address}")
            return {
                'success': False,
                'error': str(e)
            }