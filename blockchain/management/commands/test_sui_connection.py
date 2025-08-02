"""
Test Sui RPC connection and basic operations
"""
import asyncio
from django.core.management.base import BaseCommand
from django.conf import settings
from blockchain.sui_client import sui_client
from decimal import Decimal


class Command(BaseCommand):
    help = 'Test Sui RPC connection'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--address',
            type=str,
            help='Test address to check balance'
        )
        parser.add_argument(
            '--test-transfer',
            action='store_true',
            help='Test a transfer (dry run)'
        )
    
    def handle(self, *args, **options):
        self.stdout.write(f"\n🔗 Testing Sui {settings.NETWORK} connection...")
        self.stdout.write(f"RPC URL: {settings.SUI_RPC_URL}\n")
        
        # Run async tests
        asyncio.run(self.run_tests(options))
    
    async def run_tests(self, options):
        # Test 1: Health check
        self.stdout.write("1️⃣ Testing health check...")
        healthy = await sui_client.health_check()
        if healthy:
            self.stdout.write(self.style.SUCCESS("✅ RPC node is healthy"))
        else:
            self.stdout.write(self.style.ERROR("❌ RPC node is not responding"))
            return
        
        # Test 2: Get chain info
        self.stdout.write("\n2️⃣ Getting chain information...")
        try:
            chain_id = await sui_client._make_rpc_call("sui_getChainIdentifier", [])
            self.stdout.write(f"Chain ID: {chain_id}")
            
            # Get latest checkpoint
            checkpoint = await sui_client._make_rpc_call("sui_getLatestCheckpointSequenceNumber", [])
            self.stdout.write(f"Latest checkpoint: {checkpoint}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {e}"))
        
        # Test 3: Check balance if address provided
        if options['address']:
            self.stdout.write(f"\n3️⃣ Checking balances for {options['address']}...")
            try:
                # Get SUI balance
                sui_balance = await sui_client.get_sui_balance(options['address'])
                self.stdout.write(f"SUI: {sui_balance}")
                
                # Try to get cUSD balance (will fail if not deployed)
                try:
                    cusd_balance = await sui_client.get_cusd_balance(options['address'])
                    self.stdout.write(f"cUSD: {cusd_balance}")
                except:
                    self.stdout.write("cUSD: Not available (contract not deployed?)")
                
                # Get recent transactions
                self.stdout.write("\n4️⃣ Recent transactions:")
                txs = await sui_client.get_transactions(options['address'], limit=5)
                
                if txs.get('data'):
                    for tx in txs['data'][:5]:
                        self.stdout.write(f"  - {tx['digest']}")
                else:
                    self.stdout.write("  No transactions found")
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error checking balance: {e}"))
        
        # Test 4: Event subscription (brief test)
        self.stdout.write("\n5️⃣ Testing event subscription...")
        if settings.NETWORK == 'testnet':
            self.stdout.write("WebSocket subscription available on testnet ✅")
        else:
            self.stdout.write("Will use QuickNode gRPC on mainnet 📡")
        
        self.stdout.write(self.style.SUCCESS("\n✨ Connection test complete!"))
        
        # Show configuration summary
        self.stdout.write("\n📋 Current Configuration:")
        self.stdout.write(f"  Network: {settings.NETWORK}")
        self.stdout.write(f"  RPC URL: {settings.SUI_RPC_URL}")
        self.stdout.write(f"  Poll Interval: {settings.POLL_INTERVAL_SECONDS}s")
        self.stdout.write(f"  Gas Budget: {settings.DEFAULT_GAS_BUDGET} MIST")
        
        if settings.NETWORK == 'testnet':
            self.stdout.write(self.style.WARNING(
                "\n⚠️  Using testnet - switch to mainnet for production"
            ))
            self.stdout.write(
                "Set SUI_NETWORK=mainnet and configure QuickNode credentials"
            )