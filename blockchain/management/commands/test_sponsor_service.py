"""
Test the sponsor service functionality
"""
import asyncio
import json
from decimal import Decimal
from django.core.management.base import BaseCommand
from blockchain.sponsor_service import SponsorService, test_sponsor_service
from blockchain.transaction_manager import TransactionManager
from users.models import User, Account
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Test sponsor service and sponsored transactions'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--check-health',
            action='store_true',
            help='Check sponsor account health'
        )
        parser.add_argument(
            '--estimate',
            type=str,
            help='Estimate gas for transaction type (send, pay, trade)'
        )
        parser.add_argument(
            '--test-send',
            action='store_true',
            help='Test a sponsored send transaction'
        )
        parser.add_argument(
            '--email',
            type=str,
            help='User email for test transactions'
        )
        parser.add_argument(
            '--amount',
            type=Decimal,
            default=Decimal('1'),
            help='Amount for test transaction'
        )
        parser.add_argument(
            '--token',
            type=str,
            default='CUSD',
            help='Token type (CUSD, CONFIO)'
        )
    
    def handle(self, *args, **options):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            if options['check_health']:
                self.check_health(loop)
            
            elif options['estimate']:
                self.estimate_cost(loop, options['estimate'])
            
            elif options['test_send'] and options['email']:
                self.test_send(
                    loop,
                    options['email'],
                    options['amount'],
                    options['token']
                )
            
            else:
                # Run full test suite
                self.stdout.write(self.style.SUCCESS('\n=== Running Full Sponsor Service Test ===\n'))
                loop.run_until_complete(test_sponsor_service())
                
        finally:
            loop.close()
    
    def check_health(self, loop):
        """Check sponsor account health"""
        self.stdout.write(self.style.SUCCESS('\n🏥 Checking Sponsor Health...'))
        
        health = loop.run_until_complete(SponsorService.check_sponsor_health())
        
        # Display health status
        if health['healthy']:
            self.stdout.write(self.style.SUCCESS(f"\n✅ Sponsor is HEALTHY"))
        elif health.get('warning'):
            self.stdout.write(self.style.WARNING(f"\n⚠️  Sponsor has WARNINGS"))
        else:
            self.stdout.write(self.style.ERROR(f"\n❌ Sponsor is UNHEALTHY"))
        
        self.stdout.write(f"\n💰 Balance: {health.get('balance_formatted', 'Unknown')}")
        self.stdout.write(f"🔢 Estimated transactions: {health.get('estimated_transactions', 0)}")
        
        # Show recommendations
        if health.get('recommendations'):
            self.stdout.write(f"\n📋 Recommendations:")
            for rec in health['recommendations']:
                self.stdout.write(f"   - {rec}")
        
        # Show stats
        if health.get('stats'):
            stats = health['stats']
            self.stdout.write(f"\n📊 Statistics:")
            self.stdout.write(f"   Total sponsored: {stats.get('total_sponsored', 0)}")
            self.stdout.write(f"   Gas spent: {stats.get('total_gas_spent', 0) / 1e9:.4f} SUI")
            self.stdout.write(f"   Failed: {stats.get('failed_transactions', 0)}")
    
    def estimate_cost(self, loop, tx_type):
        """Estimate sponsorship cost"""
        self.stdout.write(self.style.SUCCESS(f'\n💸 Estimating cost for {tx_type} transaction...'))
        
        estimate = loop.run_until_complete(
            SponsorService.estimate_sponsorship_cost(
                tx_type,
                {'coin_count': 5}  # Assume 5 coins
            )
        )
        
        self.stdout.write(f"\n📊 Estimate for {tx_type}:")
        self.stdout.write(f"   Gas needed: {estimate['estimated_gas_sui']} SUI")
        self.stdout.write(f"   Sponsor available: {'✅' if estimate['sponsor_available'] else '❌'}")
        self.stdout.write(f"   Can afford: {'✅' if estimate['can_afford'] else '❌'}")
    
    def test_send(self, loop, email, amount, token):
        """Test a sponsored send transaction"""
        self.stdout.write(
            self.style.SUCCESS(
                f'\n🚀 Testing sponsored send: {amount} {token} from {email}'
            )
        )
        
        try:
            # Get user and account
            user = User.objects.get(email=email)
            account = user.accounts.filter(is_active=True).first()
            
            if not account:
                self.stdout.write(self.style.ERROR('No active account found'))
                return
            
            # Create a test recipient address
            test_recipient = "0x" + "0" * 64  # Mock address
            
            self.stdout.write(f"\n📤 Sending from: {account.algorand_address[:16]}...")
            self.stdout.write(f"📥 Sending to: {test_recipient[:16]}...")
            
            # Execute sponsored transaction
            result = loop.run_until_complete(
                TransactionManager.send_tokens(
                    account,
                    test_recipient,
                    amount,
                    token.upper(),
                    None  # No signature for test
                )
            )
            
            if result['success']:
                self.stdout.write(self.style.SUCCESS(f"\n✅ Transaction successful!"))
                self.stdout.write(f"   Digest: {result.get('digest')}")
                self.stdout.write(f"   Gas saved: {result.get('gas_saved', 0)} SUI")
                self.stdout.write(f"   Sponsored by: {result.get('sponsor', 'Unknown')[:16]}...")
            else:
                self.stdout.write(self.style.ERROR(f"\n❌ Transaction failed:"))
                self.stdout.write(f"   Error: {result.get('error')}")
                if result.get('details'):
                    self.stdout.write(f"   Details: {json.dumps(result['details'], indent=2)}")
            
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User {email} not found'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
            logger.exception("Test send failed")