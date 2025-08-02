"""
Test the hybrid balance caching service
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal
import time

from users.models import User, Account
from blockchain.balance_service import BalanceService


class Command(BaseCommand):
    help = 'Test balance caching service'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--user-email',
            type=str,
            help='User email to test'
        )
        parser.add_argument(
            '--benchmark',
            action='store_true',
            help='Run performance benchmark'
        )
    
    def handle(self, *args, **options):
        if options['user_email']:
            self.test_user_balance(options['user_email'])
        
        if options['benchmark']:
            self.run_benchmark()
    
    def test_user_balance(self, email):
        """Test balance operations for a specific user"""
        try:
            user = User.objects.get(email=email)
            account = user.accounts.filter(is_active=True).first()
            
            if not account:
                self.stdout.write(self.style.ERROR(f"No active account for {email}"))
                return
            
            self.stdout.write(f"\n🧪 Testing balance service for {email}")
            self.stdout.write(f"Sui Address: {account.sui_address}\n")
            
            # Test 1: Get cached balance
            self.stdout.write("1️⃣ Getting cached balance...")
            start = time.time()
            balance = BalanceService.get_balance(account, 'CUSD')
            elapsed = (time.time() - start) * 1000
            
            self.stdout.write(f"   Amount: {balance['amount']} cUSD")
            self.stdout.write(f"   Available: {balance['available']} cUSD")
            self.stdout.write(f"   Pending: {balance['pending']} cUSD")
            self.stdout.write(f"   Last Synced: {balance['last_synced']}")
            self.stdout.write(f"   Is Stale: {balance['is_stale']}")
            self.stdout.write(f"   ⏱️  Time: {elapsed:.2f}ms")
            
            # Test 2: Force refresh
            self.stdout.write("\n2️⃣ Force refreshing from blockchain...")
            start = time.time()
            fresh_balance = BalanceService.get_balance(account, 'CUSD', force_refresh=True)
            elapsed = (time.time() - start) * 1000
            
            self.stdout.write(f"   Fresh Amount: {fresh_balance['amount']} cUSD")
            self.stdout.write(f"   ⏱️  Time: {elapsed:.2f}ms")
            
            # Test 3: Critical verification
            self.stdout.write("\n3️⃣ Critical verification (always blockchain)...")
            start = time.time()
            critical_balance = BalanceService.get_balance(
                account, 'CUSD', verify_critical=True
            )
            elapsed = (time.time() - start) * 1000
            
            self.stdout.write(f"   Verified Amount: {critical_balance['amount']} cUSD")
            self.stdout.write(f"   ⏱️  Time: {elapsed:.2f}ms")
            
            # Test 4: Mark stale and check
            self.stdout.write("\n4️⃣ Testing stale marking...")
            BalanceService.mark_stale(account, 'CUSD')
            stale_balance = BalanceService.get_balance(account, 'CUSD')
            self.stdout.write(f"   After marking stale: {stale_balance['is_stale']}")
            
            # Test 5: All balances
            self.stdout.write("\n5️⃣ Getting all balances...")
            start = time.time()
            all_balances = BalanceService.get_all_balances(account)
            elapsed = (time.time() - start) * 1000
            
            for token, data in all_balances.items():
                self.stdout.write(f"   {token.upper()}: {data['amount']}")
            self.stdout.write(f"   ⏱️  Time: {elapsed:.2f}ms")
            
            self.stdout.write(self.style.SUCCESS("\n✅ Balance service test complete!"))
            
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User {email} not found"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {e}"))
    
    def run_benchmark(self):
        """Benchmark cache vs blockchain performance"""
        self.stdout.write("\n📊 Running performance benchmark...")
        
        # Get a test account
        account = Account.objects.filter(
            is_active=True,
            sui_address__isnull=False
        ).first()
        
        if not account:
            self.stdout.write(self.style.ERROR("No accounts with Sui address found"))
            return
        
        # Benchmark 1: Cached reads
        self.stdout.write("\n1️⃣ Cached balance reads (100 iterations):")
        total_time = 0
        for i in range(100):
            start = time.time()
            BalanceService.get_balance(account, 'CUSD')
            total_time += (time.time() - start) * 1000
        
        avg_cached = total_time / 100
        self.stdout.write(f"   Average time: {avg_cached:.2f}ms")
        self.stdout.write(f"   Total time: {total_time:.2f}ms")
        
        # Benchmark 2: Blockchain reads
        self.stdout.write("\n2️⃣ Blockchain balance reads (5 iterations):")
        total_time = 0
        for i in range(5):
            start = time.time()
            BalanceService.get_balance(account, 'CUSD', verify_critical=True)
            total_time += (time.time() - start) * 1000
            time.sleep(0.5)  # Rate limit
        
        avg_blockchain = total_time / 5
        self.stdout.write(f"   Average time: {avg_blockchain:.2f}ms")
        self.stdout.write(f"   Total time: {total_time:.2f}ms")
        
        # Summary
        self.stdout.write("\n📈 Performance Summary:")
        self.stdout.write(f"   Cache is {avg_blockchain/avg_cached:.1f}x faster")
        self.stdout.write(f"   Cache: ~{avg_cached:.0f}ms per request")
        self.stdout.write(f"   Blockchain: ~{avg_blockchain:.0f}ms per request")
        
        self.stdout.write(self.style.SUCCESS("\n✅ Benchmark complete!"))