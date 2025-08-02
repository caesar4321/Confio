# Blockchain Polling - Simplified Architecture

## Single Codebase, Multiple Processes Approach

Based on Confío's current scale, we'll use a single Django codebase with separate processes for web and polling.

## Architecture

```
┌─────────────────────┐
│   QuickNode Sui     │
│   gRPC Endpoint     │
└──────────┬──────────┘
           │
           │ Subscribe/Stream
           ▼
┌─────────────────────┐         ┌─────────────────────┐
│  Django Project     │         │    Shared DB        │
│                     │ ◄─────► │  - Users            │
│  Process 1: Web     │         │  - Sui Addresses    │
│  - GraphQL API      │         │  - Transactions     │
│  - User Interface   │         │  - Raw Events       │
│                     │         └─────────────────────┘
│  Process 2: Poller  │                   ▲
│  - gRPC Streaming   │                   │
│  - Event Processing │                   │
│  - Celery Tasks     │         ┌─────────┴───────────┐
└─────────────────────┘ ◄─────► │    Redis Cache      │
                                │  - Celery Queue     │
                                │  - Address Cache    │
                                └─────────────────────┘
```

## Implementation

### 1. Django Management Command (`blockchain/management/commands/poll_blockchain.py`)

```python
from django.core.management.base import BaseCommand
from django.conf import settings
import grpc
import asyncio
from blockchain.tasks import process_transaction

class Command(BaseCommand):
    help = 'Poll Sui blockchain for transactions'
    
    def handle(self, *args, **options):
        self.stdout.write('Starting blockchain polling...')
        asyncio.run(self.poll_blockchain())
    
    async def poll_blockchain(self):
        # Connect to QuickNode
        channel = grpc.aio.secure_channel(
            settings.QUICKNODE_GRPC_ENDPOINT,
            grpc.ssl_channel_credentials()
        )
        
        # Subscribe to transactions
        stub = SuiApiStub(channel)
        
        # Stream transactions
        async for tx in self.stream_transactions(stub):
            # Quick check if relevant
            if self.is_relevant_transaction(tx):
                # Queue for processing
                process_transaction.delay(tx.to_dict())
    
    def is_relevant_transaction(self, tx):
        """Check if transaction involves our contracts or users"""
        # Check contract addresses
        if tx.module in settings.MONITORED_CONTRACTS:
            return True
        
        # Check user addresses (cached)
        sender = tx.sender
        recipients = self.extract_recipients(tx)
        
        user_addresses = cache.get('user_addresses', set())
        if sender in user_addresses or any(r in user_addresses for r in recipients):
            return True
        
        return False
```

### 2. Celery Tasks (`blockchain/tasks.py`)

```python
from celery import shared_task
from django.core.cache import cache
from users.models import Account
from transactions.models import Transaction, RawBlockchainEvent
import logging

logger = logging.getLogger(__name__)

@shared_task
def process_transaction(tx_data):
    """Process a blockchain transaction"""
    try:
        # Save raw event
        raw_event = RawBlockchainEvent.objects.create(
            tx_hash=tx_data['digest'],
            sender=tx_data['sender'],
            module=tx_data['module'],
            function=tx_data['function'],
            raw_data=tx_data,
            block_time=tx_data['timestamp_ms']
        )
        
        # Determine transaction type
        if tx_data['module'] == settings.CUSD_ADDRESS:
            handle_cusd_transaction.delay(raw_event.id)
        elif tx_data['module'] == settings.PAY_ADDRESS:
            handle_payment_transaction.delay(raw_event.id)
        elif tx_data['module'] == settings.P2P_TRADE_ADDRESS:
            handle_p2p_trade.delay(raw_event.id)
            
    except Exception as e:
        logger.error(f"Failed to process transaction: {e}")
        raise

@shared_task
def handle_cusd_transaction(raw_event_id):
    """Process cUSD transfer with notifications"""
    raw_event = RawBlockchainEvent.objects.get(id=raw_event_id)
    tx_data = raw_event.raw_data
    
    # Find users
    sender_account = Account.objects.filter(
        sui_address=tx_data['sender']
    ).first()
    
    recipient_account = Account.objects.filter(
        sui_address=tx_data['recipients'][0]
    ).first()
    
    # Only process if at least one party is a Confío user
    if not (sender_account or recipient_account):
        return
    
    # Create transaction record
    transaction = Transaction.objects.create(
        tx_hash=tx_data['digest'],
        type='transfer',
        sender_account=sender_account,
        recipient_account=recipient_account,
        amount=tx_data['amount'],
        token='CUSD',
        status='completed',
        raw_event=raw_event
    )
    
    # Send notification
    if recipient_account:
        send_push_notification.delay(
            recipient_account.user_id,
            f"Recibiste {format_amount(tx_data['amount'])} cUSD",
            transaction.id
        )

@shared_task(bind=True, max_retries=3)
def update_user_address_cache(self):
    """Periodically update cached user addresses"""
    try:
        addresses = set(
            Account.objects.filter(
                is_active=True,
                sui_address__isnull=False
            ).values_list('sui_address', flat=True)
        )
        
        cache.set('user_addresses', addresses, timeout=300)  # 5 minutes
        logger.info(f"Updated {len(addresses)} user addresses in cache")
        
    except Exception as e:
        logger.error(f"Failed to update address cache: {e}")
        self.retry(countdown=60)
```

### 3. Celery Beat Schedule (`config/celery.py`)

```python
from celery import Celery
from celery.schedules import crontab

app = Celery('confio')

app.conf.beat_schedule = {
    'update-user-addresses': {
        'task': 'blockchain.tasks.update_user_address_cache',
        'schedule': 60.0,  # Every minute
    },
    'cleanup-old-events': {
        'task': 'blockchain.tasks.cleanup_old_events',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
    },
}
```

### 4. Docker Compose (`docker-compose.yml`)

```yaml
version: '3.8'

services:
  web:
    build: .
    command: gunicorn config.wsgi:application --bind 0.0.0.0:8000
    volumes:
      - .:/code
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      - db
      - redis

  poller:
    build: .
    command: python manage.py poll_blockchain
    volumes:
      - .:/code
    env_file:
      - .env
    depends_on:
      - db
      - redis
    restart: unless-stopped

  celery:
    build: .
    command: celery -A config worker -l info
    volumes:
      - .:/code
    env_file:
      - .env
    depends_on:
      - db
      - redis

  celery-beat:
    build: .
    command: celery -A config beat -l info
    volumes:
      - .:/code
    env_file:
      - .env
    depends_on:
      - db
      - redis

  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=confio
      - POSTGRES_USER=confio
      - POSTGRES_PASSWORD=confio
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

### 5. Models (`blockchain/models.py`)

```python
from django.db import models
from django.contrib.postgres.fields import JSONField

class RawBlockchainEvent(models.Model):
    """Stores raw blockchain events for audit trail"""
    tx_hash = models.CharField(max_length=66, unique=True, db_index=True)
    sender = models.CharField(max_length=66, db_index=True)
    module = models.CharField(max_length=66, db_index=True)
    function = models.CharField(max_length=100)
    raw_data = JSONField()
    block_time = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False)
    
    class Meta:
        indexes = [
            models.Index(fields=['sender', 'block_time']),
            models.Index(fields=['module', 'function']),
        ]
```

## Deployment Strategy

### Phase 1: Single EC2 Instance (Current)
```bash
# All processes on one t3.medium instance
docker-compose up -d
```

### Phase 2: Separate Containers (Growth)
```bash
# Web on one instance
docker-compose up -d web

# Poller + Celery on another
docker-compose up -d poller celery celery-beat
```

### Phase 3: Full Separation (Scale)
- Move to ECS/Fargate
- Separate poller to dedicated instance
- Use SQS instead of Redis for queues

## Monitoring

```python
# Add to settings.py
LOGGING = {
    'version': 1,
    'handlers': {
        'blockchain': {
            'class': 'logging.FileHandler',
            'filename': 'logs/blockchain.log',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'blockchain': {
            'handlers': ['blockchain'],
            'level': 'INFO',
        },
    },
}
```

## Cost Comparison

| Setup | Monthly Cost | Complexity |
|-------|--------------|------------|
| Single Instance | ~$50 | Low |
| Separate Processes | ~$80 | Medium |
| Fully Separate | ~$150 | High |

## Migration Path

1. **Now**: Everything on one instance
2. **10K users**: Move poller to separate container
3. **100K users**: Dedicated poller instance
4. **1M users**: Multiple pollers with sharding

This approach gives you the simplicity of a single codebase while maintaining the flexibility to scale components independently as needed.