"""
Poll Sui blockchain for relevant transactions
"""
import asyncio
import json
from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.cache import cache
from blockchain.sui_client import sui_client
from blockchain.tasks import process_transaction
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Poll Sui blockchain for transactions'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run once instead of continuous polling'
        )
    
    def handle(self, *args, **options):
        self.stdout.write(f"🚀 Starting Sui blockchain polling on {settings.NETWORK}...")
        
        if options['once']:
            asyncio.run(self.poll_once())
        else:
            asyncio.run(self.poll_continuous())
    
    async def poll_continuous(self):
        """Continuous polling loop"""
        self.stdout.write("Running in continuous mode...")
        
        while True:
            try:
                await self.poll_transactions()
                await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                self.stdout.write("\n👋 Stopping poller...")
                break
            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(10)  # Error backoff
    
    async def poll_once(self):
        """Single poll run"""
        self.stdout.write("Running single poll...")
        await self.poll_transactions()
        self.stdout.write("✅ Poll complete")
    
    async def poll_transactions(self):
        """Poll for new transactions"""
        # For testnet, we'll poll recent transactions
        # For mainnet with QuickNode, we'll use their streaming API
        
        if settings.NETWORK == 'testnet':
            await self.poll_testnet_transactions()
        else:
            await self.poll_quicknode_transactions()
    
    async def poll_testnet_transactions(self):
        """Poll testnet using standard RPC"""
        # Get monitored addresses from cache
        user_addresses = cache.get('user_addresses', set())
        all_addresses = user_addresses | set(settings.MONITOR_ADDRESSES)
        
        if not all_addresses:
            logger.info("No addresses to monitor")
            return
        
        # Check transactions for each address
        # (In production, we'd track last seen transaction)
        for address in all_addresses:
            try:
                result = await sui_client.get_transactions(
                    address,
                    limit=10  # Recent transactions
                )
                
                if result.get('data'):
                    for tx in result['data']:
                        await self.process_transaction_data(tx)
                        
            except Exception as e:
                logger.error(f"Error polling address {address}: {e}")
    
    async def poll_quicknode_transactions(self):
        """Poll mainnet using QuickNode gRPC"""
        # This will be implemented when moving to mainnet
        raise NotImplementedError(
            "QuickNode gRPC streaming will be implemented for mainnet"
        )
    
    async def process_transaction_data(self, tx_data):
        """Process a transaction"""
        digest = tx_data['digest']
        
        # Check if already processed
        cache_key = f"processed_tx:{digest}"
        if cache.get(cache_key):
            return
        
        # Get full transaction details
        try:
            full_tx = await sui_client.get_transaction_detail(digest)
            
            # Check if relevant to our contracts
            if self.is_relevant_transaction(full_tx):
                # Queue for processing
                process_transaction.delay(full_tx)
                
                # Mark as processed
                cache.set(cache_key, True, 86400)  # 24 hours
                
                self.stdout.write(f"📥 Queued transaction: {digest}")
                
        except Exception as e:
            logger.error(f"Error processing transaction {digest}: {e}")
    
    def is_relevant_transaction(self, tx):
        """Check if transaction involves our contracts or users"""
        # Check if it's a move call to our contracts
        if tx.get('transaction', {}).get('data', {}).get('messageVersion') == 'v1':
            tx_data = tx['transaction']['data']['transaction']
            
            if tx_data.get('kind') == 'ProgrammableTransaction':
                for command in tx_data.get('transactions', []):
                    if command.get('MoveCall'):
                        package = command['MoveCall'].get('package')
                        if package in [
                            settings.CUSD_PACKAGE_ID,
                            settings.CONFIO_PACKAGE_ID,
                            settings.PAY_PACKAGE_ID,
                            settings.P2P_TRADE_PACKAGE_ID,
                            settings.INVITE_SEND_PACKAGE_ID
                        ]:
                            return True
        
        # Check balance changes for our tokens
        for change in tx.get('balanceChanges', []):
            coin_type = change.get('coinType')
            if any(contract in coin_type for contract in [
                settings.CUSD_PACKAGE_ID,
                settings.CONFIO_PACKAGE_ID
            ]):
                return True
        
        return False