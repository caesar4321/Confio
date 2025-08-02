# Blockchain Polling Service Architecture

## Overview

The Confío blockchain polling service is a dedicated Django application that monitors Sui blockchain transactions and syncs relevant data with the main application server.

## Architecture Decision: Separate Services

We use **two separate Django instances** for clear separation of concerns:

1. **Main App Server** - Handles user requests, business logic, notifications
2. **Polling Service** - Monitors blockchain, filters transactions, syncs data

## System Architecture

```
┌─────────────────────┐
│   QuickNode Sui     │
│   gRPC Endpoint     │
└──────────┬──────────┘
           │
           │ Subscribe/Poll
           ▼
┌─────────────────────┐         ┌─────────────────────┐
│  Polling Service    │ ◄─────► │    Redis Cache      │
│  (Django Instance)  │         │  - User addresses   │
│                     │         │  - Processed TXs    │
│  - Transaction      │         │  - Rate limits     │
│    filtering        │         └─────────────────────┘
│  - Deduplication    │                   ▲
│  - Raw data storage │                   │
└──────────┬──────────┘                   │
           │                              │
           │ RabbitMQ/SQS                 │
           │ Transaction Events           │
           ▼                              │
┌─────────────────────┐                   │
│   Main App Server   │ ◄─────────────────┘
│  (Django Instance)  │
│                     │
│  - User context     │
│  - Notifications    │
│  - Business logic   │
│  - GraphQL API      │
└─────────────────────┘
```

## Polling Service Components

### 1. Transaction Monitor (`polling_service/monitors/sui_monitor.py`)

```python
import asyncio
from typing import Set, Dict, Any
from django.core.cache import cache
from quicknode import SuiGRPCClient
import logging

logger = logging.getLogger(__name__)

class SuiTransactionMonitor:
    def __init__(self):
        self.client = SuiGRPCClient(
            endpoint=settings.QUICKNODE_GRPC_ENDPOINT,
            api_key=settings.QUICKNODE_API_KEY
        )
        self.monitored_modules = {
            settings.CUSD_MODULE_ADDRESS,
            settings.CONFIO_MODULE_ADDRESS,
            settings.USDC_MODULE_ADDRESS,
            settings.PAY_MODULE_ADDRESS,
            settings.P2P_TRADE_MODULE_ADDRESS,
            settings.INVITE_SEND_MODULE_ADDRESS
        }
    
    async def start_monitoring(self):
        """Main monitoring loop"""
        while True:
            try:
                await self.poll_transactions()
                await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)
            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(settings.ERROR_RETRY_SECONDS)
    
    async def poll_transactions(self):
        """Poll for new transactions"""
        # Get latest checkpoint
        latest_checkpoint = await self.get_latest_checkpoint()
        last_processed = cache.get('last_processed_checkpoint', 0)
        
        if latest_checkpoint <= last_processed:
            return
        
        # Process transactions in batches
        for checkpoint in range(last_processed + 1, latest_checkpoint + 1):
            transactions = await self.get_checkpoint_transactions(checkpoint)
            await self.process_transactions(transactions)
            cache.set('last_processed_checkpoint', checkpoint, timeout=None)
    
    async def process_transactions(self, transactions: List[Dict]):
        """Filter and process relevant transactions"""
        user_addresses = await self.get_cached_user_addresses()
        
        for tx in transactions:
            if self.is_relevant_transaction(tx, user_addresses):
                await self.handle_transaction(tx)
    
    def is_relevant_transaction(self, tx: Dict, user_addresses: Set[str]) -> bool:
        """Check if transaction is relevant to Confío"""
        # Check if it involves our contracts
        for module in tx.get('modules', []):
            if module in self.monitored_modules:
                # Check if sender or recipient is a Confío user
                sender = tx.get('sender')
                recipients = self.extract_recipients(tx)
                
                if sender in user_addresses or any(r in user_addresses for r in recipients):
                    return True
        
        return False
    
    async def handle_transaction(self, tx: Dict):
        """Process and forward relevant transaction"""
        # Deduplicate
        tx_hash = tx['digest']
        if cache.get(f'processed_tx:{tx_hash}'):
            return
        
        # Store raw transaction
        raw_tx = RawTransaction.objects.create(
            tx_hash=tx_hash,
            checkpoint=tx['checkpoint'],
            sender=tx['sender'],
            module=tx['module'],
            function=tx['function'],
            raw_data=tx,
            timestamp=tx['timestamp_ms']
        )
        
        # Send to main app via message queue
        await self.send_to_main_app(raw_tx)
        
        # Mark as processed
        cache.set(f'processed_tx:{tx_hash}', True, timeout=86400)  # 24h
```

### 2. User Address Sync (`polling_service/sync/address_sync.py`)

```python
class UserAddressSync:
    """Syncs user addresses between main app and polling service"""
    
    def __init__(self):
        self.redis_client = get_redis_connection('default')
    
    async def sync_addresses(self):
        """Periodic sync of user addresses from main app"""
        while True:
            try:
                # Fetch from main app API
                response = await self.fetch_user_addresses()
                addresses = response['addresses']
                
                # Update Redis cache
                pipeline = self.redis_client.pipeline()
                pipeline.delete('user_addresses')
                for addr in addresses:
                    pipeline.sadd('user_addresses', addr)
                pipeline.execute()
                
                logger.info(f"Synced {len(addresses)} user addresses")
                
            except Exception as e:
                logger.error(f"Address sync error: {e}")
            
            await asyncio.sleep(settings.ADDRESS_SYNC_INTERVAL)
    
    async def fetch_user_addresses(self) -> Dict:
        """Fetch active addresses from main app"""
        headers = {
            'Authorization': f'Bearer {settings.INTERNAL_API_KEY}',
            'X-Service': 'polling-service'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.MAIN_APP_URL}/internal/active-addresses",
                headers=headers
            ) as response:
                return await response.json()
```

### 3. Message Queue Integration (`polling_service/queue/publisher.py`)

```python
import pika
import json
from django.conf import settings

class TransactionPublisher:
    def __init__(self):
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(settings.RABBITMQ_URL)
        )
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue='sui_transactions', durable=True)
    
    def publish_transaction(self, transaction_data: Dict):
        """Publish transaction to main app"""
        message = {
            'tx_hash': transaction_data['tx_hash'],
            'type': self.determine_transaction_type(transaction_data),
            'sender': transaction_data['sender'],
            'recipients': transaction_data['recipients'],
            'amount': transaction_data['amount'],
            'token': transaction_data['token'],
            'module': transaction_data['module'],
            'function': transaction_data['function'],
            'timestamp': transaction_data['timestamp'],
            'raw_tx_id': transaction_data['id']  # Reference to raw data
        }
        
        self.channel.basic_publish(
            exchange='',
            routing_key='sui_transactions',
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,  # Persistent
                content_type='application/json'
            )
        )
    
    def determine_transaction_type(self, tx_data: Dict) -> str:
        """Determine transaction type for main app processing"""
        module = tx_data['module']
        function = tx_data['function']
        
        if module == settings.CUSD_MODULE_ADDRESS:
            if function == 'transfer':
                return 'cusd_transfer'
            elif function == 'mint':
                return 'cusd_mint'
        elif module == settings.PAY_MODULE_ADDRESS:
            return 'payment'
        elif module == settings.P2P_TRADE_MODULE_ADDRESS:
            return 'p2p_trade'
        elif module == settings.INVITE_SEND_MODULE_ADDRESS:
            return 'invitation'
        
        return 'unknown'
```

### 4. Django Models (`polling_service/models.py`)

```python
from django.db import models
from django.contrib.postgres.fields import JSONField

class RawTransaction(models.Model):
    """Stores raw blockchain transaction data"""
    tx_hash = models.CharField(max_length=66, unique=True, db_index=True)
    checkpoint = models.BigIntegerField(db_index=True)
    sender = models.CharField(max_length=66, db_index=True)
    module = models.CharField(max_length=66, db_index=True)
    function = models.CharField(max_length=100)
    raw_data = JSONField()
    timestamp = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False)
    
    class Meta:
        indexes = [
            models.Index(fields=['checkpoint', 'processed']),
            models.Index(fields=['sender', 'timestamp']),
        ]

class ProcessingError(models.Model):
    """Tracks transactions that failed processing"""
    transaction = models.ForeignKey(RawTransaction, on_delete=models.CASCADE)
    error_type = models.CharField(max_length=50)
    error_message = models.TextField()
    retry_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)
```

## Main App Integration

### 1. Transaction Consumer (`main_app/consumers/transaction_consumer.py`)

```python
class TransactionConsumer:
    """Consumes transactions from polling service"""
    
    def handle_transaction(self, message: Dict):
        """Process transaction with business context"""
        tx_type = message['type']
        
        if tx_type == 'cusd_transfer':
            self.handle_cusd_transfer(message)
        elif tx_type == 'payment':
            self.handle_payment(message)
        elif tx_type == 'p2p_trade':
            self.handle_p2p_trade(message)
        # ... other types
    
    def handle_cusd_transfer(self, tx_data: Dict):
        """Process cUSD transfer with notifications"""
        # Find users
        sender_account = Account.objects.filter(
            sui_address=tx_data['sender']
        ).first()
        
        recipient_account = Account.objects.filter(
            sui_address=tx_data['recipients'][0]
        ).first()
        
        # Create transaction record
        transaction = Transaction.objects.create(
            tx_hash=tx_data['tx_hash'],
            type='transfer',
            sender_account=sender_account,
            recipient_account=recipient_account,
            amount=tx_data['amount'],
            token='CUSD',
            status='completed',
            blockchain_timestamp=tx_data['timestamp']
        )
        
        # Send notification if recipient is Confío user
        if recipient_account:
            self.send_notification(
                recipient_account,
                f"You received {tx_data['amount']} cUSD",
                transaction
            )
```

### 2. Internal API Endpoints (`main_app/internal_api/views.py`)

```python
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required

@csrf_exempt
@require_internal_service_auth
def active_addresses(request):
    """Return all active user Sui addresses for polling service"""
    addresses = list(
        Account.objects.filter(
            is_active=True,
            sui_address__isnull=False
        ).values_list('sui_address', flat=True)
    )
    
    # Include contract addresses that should always be monitored
    addresses.extend([
        settings.FEE_COLLECTOR_ADDRESS,
        settings.ESCROW_VAULT_ADDRESS,
        settings.INVITATION_VAULT_ADDRESS
    ])
    
    return JsonResponse({
        'addresses': addresses,
        'count': len(addresses),
        'timestamp': timezone.now().isoformat()
    })
```

## Deployment Configuration

### 1. Polling Service (`docker-compose.polling.yml`)

```yaml
version: '3.8'

services:
  polling:
    build: .
    command: python manage.py run_polling_service
    environment:
      - DJANGO_SETTINGS_MODULE=polling_service.settings
      - QUICKNODE_GRPC_ENDPOINT=${QUICKNODE_GRPC_ENDPOINT}
      - QUICKNODE_API_KEY=${QUICKNODE_API_KEY}
      - REDIS_URL=${REDIS_URL}
      - RABBITMQ_URL=${RABBITMQ_URL}
      - DATABASE_URL=${POLLING_DB_URL}
    depends_on:
      - redis
      - rabbitmq
      - postgres
    restart: unless-stopped
    
  address_sync:
    build: .
    command: python manage.py sync_addresses
    environment:
      - DJANGO_SETTINGS_MODULE=polling_service.settings
      - MAIN_APP_URL=${MAIN_APP_URL}
      - INTERNAL_API_KEY=${INTERNAL_API_KEY}
    depends_on:
      - redis
    restart: unless-stopped
```

### 2. AWS Infrastructure

```terraform
# Separate EC2 instances
resource "aws_instance" "main_app" {
  instance_type = "t3.large"
  # ... main app configuration
}

resource "aws_instance" "polling_service" {
  instance_type = "t3.medium"
  # ... polling service configuration
}

# Shared infrastructure
resource "aws_elasticache_cluster" "redis" {
  cluster_id = "confio-cache"
  engine = "redis"
  node_type = "cache.t3.micro"
}

resource "aws_mq_broker" "rabbitmq" {
  broker_name = "confio-mq"
  engine_type = "RabbitMQ"
  engine_version = "3.11.20"
  host_instance_type = "mq.t3.micro"
}
```

## Monitoring and Alerting

### Key Metrics to Monitor

1. **Polling Service Health**
   - Checkpoint lag (current vs latest)
   - Transaction processing rate
   - Error rate
   - Memory usage

2. **Data Consistency**
   - Unprocessed transaction count
   - Message queue depth
   - Address sync freshness

3. **Performance**
   - QuickNode API latency
   - Database query time
   - Message publishing latency

### Alert Conditions

```python
# CloudWatch alarms
- Checkpoint lag > 100
- Error rate > 5%
- Unprocessed transactions > 1000
- Address sync failure
- RabbitMQ queue depth > 10000
```

## Security Considerations

1. **Internal API Authentication**
   - Use service-to-service tokens
   - Rotate keys regularly
   - Whitelist IP addresses

2. **Data Validation**
   - Verify transaction signatures
   - Validate addresses format
   - Check amount boundaries

3. **Rate Limiting**
   - QuickNode API limits
   - Database connection pooling
   - Message queue throttling

## Advantages of This Architecture

1. **Reliability**: Main app can continue serving users even if polling fails
2. **Scalability**: Each service scales independently
3. **Maintainability**: Clear separation of concerns
4. **Performance**: No impact on user-facing API response times
5. **Flexibility**: Easy to add more blockchain monitoring
6. **Resilience**: Message queue ensures no transaction is lost

## Implementation Timeline

1. **Week 1**: Set up infrastructure and basic polling
2. **Week 2**: Implement transaction filtering and deduplication
3. **Week 3**: Build message queue integration
4. **Week 4**: Add monitoring and error handling
5. **Week 5**: Testing and optimization
6. **Week 6**: Production deployment