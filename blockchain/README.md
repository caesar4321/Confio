# Blockchain Integration Module

Django app for Sui blockchain integration with hybrid balance caching for optimal performance.

## Quick Start

1. Install dependencies:
```bash
pip install grpcio grpcio-tools celery redis
```

2. Run migrations:
```bash
python manage.py migrate blockchain
```

3. Start polling:
```bash
# Terminal 1: Celery worker
celery -A config worker -l info

# Terminal 2: Celery beat
celery -A config beat -l info

# Terminal 3: Blockchain poller
python manage.py poll_blockchain
```

## Architecture

### Overview
The blockchain integration uses a **two-part system**:
1. **Polling Process**: Monitors blockchain for relevant transactions
2. **Celery Workers**: Process transactions asynchronously

### How Polling Works

```
Sui Blockchain → poll_blockchain → Celery Queue → process_transaction → Update Cache
       ↑              (detect)         (queue)        (parse & route)      (invalidate)
       |                                                    ↓
   RPC calls                                         handle_*_transaction
                                                     (token-specific logic)
```

The `poll_blockchain` management command:
- Runs as a **separate long-running process**
- Polls blockchain every 2 seconds
- Detects transactions involving your contracts/users
- Queues transactions to Celery for processing
- Does NOT block the web server

### Key Features
- **Hybrid Caching**: Database + Redis caching with blockchain verification
- **Smart Invalidation**: Automatic stale marking after transactions
- **Periodic Reconciliation**: Hourly sync to catch any drift
- **Performance Optimized**: <10ms cached reads vs 100-500ms blockchain queries

## Key Components

### Balance Service (`balance_service.py`)
- **Fast Reads**: Cached balances for UI display
- **Smart Refresh**: Auto-refresh stale or old balances
- **Critical Verification**: Always query blockchain for sensitive operations
- **Pending Tracking**: Track in-flight transaction amounts

### Management Commands
- `poll_blockchain`: Long-running blockchain monitor
- `test_sui_connection`: Test RPC connectivity
- `test_balance_service`: Test hybrid caching system

### Celery Tasks
- `process_transaction`: Initial processing
- `reconcile_all_balances`: Hourly full reconciliation
- `refresh_stale_balances`: 5-minute stale balance refresh
- `mark_transaction_balances_stale`: Invalidate after transactions

### Models
- `RawBlockchainEvent`: Raw blockchain data storage
- `Balance`: Cached token balances with staleness tracking
- `TransactionProcessingLog`: Processing audit trail

## Balance Caching Strategy

### When to Use Cache vs Blockchain

**Use Cache (Fast ~10ms):**
- Home screen balance display
- Transaction history
- Analytics/reporting
- Non-critical UI updates

**Force Blockchain Query (~200ms):**
- Before sending transactions
- During escrow creation
- Large withdrawals
- Conversion operations (USDC ↔ cUSD)

### Example Usage

```python
from blockchain.balance_service import BalanceService

# Fast cached read for display
balance = BalanceService.get_balance(account, 'CUSD')
print(f"Balance: {balance['amount']} cUSD")

# Critical operation - verify with blockchain
balance = BalanceService.get_balance(
    account, 'CUSD', 
    verify_critical=True
)
if balance['amount'] >= withdrawal_amount:
    # Proceed with withdrawal
```

## Monitoring

```bash
# Test balance service
python manage.py test_balance_service --user-email user@example.com

# Run performance benchmark
python manage.py test_balance_service --benchmark

# Check RPC connection
python manage.py test_sui_connection --address 0x123...
```

## Configuration

```python
# settings.py
QUICKNODE_GRPC_ENDPOINT = env('QUICKNODE_GRPC_ENDPOINT')
MONITORED_CONTRACTS = [
    env('CUSD_ADDRESS'),
    env('CONFIO_ADDRESS'),
    env('PAY_ADDRESS'),
    env('P2P_TRADE_ADDRESS'),
]
```

## Production Deployment

### Process Architecture
You need to run **4 separate processes** in production:

```bash
# 1. Django Web Server
gunicorn config.wsgi

# 2. Celery Worker (processes blockchain transactions)
celery -A config worker -l info

# 3. Celery Beat (runs periodic tasks)
celery -A config beat -l info

# 4. Blockchain Poller (monitors blockchain)
python manage.py poll_blockchain
```

### Docker Compose Example
```yaml
version: '3.8'
services:
  web:
    command: gunicorn config.wsgi
    
  celery:
    command: celery -A config worker -l info
    
  celery-beat:
    command: celery -A config beat -l info
    
  blockchain-poller:
    command: python manage.py poll_blockchain
    restart: always  # Important: keep running
```

### Systemd Service Example
```ini
# /etc/systemd/system/confio-poller.service
[Unit]
Description=Confio Blockchain Poller
After=network.target

[Service]
Type=simple
User=confio
WorkingDirectory=/opt/confio
Environment="DJANGO_SETTINGS_MODULE=config.settings"
ExecStart=/opt/confio/venv/bin/python manage.py poll_blockchain
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Important Notes
- The poller is **NOT a Celery task** - it's a standalone process
- It must run continuously to detect transactions
- Use supervisor, systemd, or Docker to ensure it restarts on failure
- Monitor logs for polling errors

## Scaling

1. **Current (< 10K users)**: Single process
2. **Growth (10K-100K)**: Dedicated Celery workers
3. **Scale (100K+)**: Separate polling instance

## Testing

```bash
python manage.py test blockchain
```

## Sui Coin Management

For details on how we handle Sui's coin object model, see the [Sui Coin Management Strategy](../README.md#-sui-coin-management-strategy) in the main README.

Key files:
- `coin_management.py` - CoinManager implementation
- `COIN_STRATEGY.md` - Detailed strategy documentation