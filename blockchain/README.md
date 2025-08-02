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

## Sui Coin Management Strategy

### Overview

On Sui blockchain, tokens are represented as individual `Coin<T>` objects rather than account balances. This creates unique challenges that we handle transparently for users.

### Key Concepts

#### 1. Coin Fragmentation
- Each payment creates a new coin object
- Users accumulate multiple coin objects over time
- Example: Receiving 5 payments of 1 USDC = 5 separate coin objects

#### 2. Transaction Limits
- Sui limits the number of objects per transaction (typically 512)
- Gas optimization requires careful coin selection
- Large numbers of small coins increase transaction costs

### Current Implementation

#### Balance Display
- **Method**: `suix_getBalance` RPC call
- **Behavior**: Automatically aggregates all coin objects
- **User Experience**: Users see total balance, not individual coins

#### Balance Caching
- Database stores aggregated balances
- Redis caches for performance
- Blockchain verification on-demand

### Coin Management Strategy

#### 1. Automatic Coin Management

```python
# Thresholds
MAX_COINS_PER_TYPE = 10  # Merge if more than this
MIN_COINS_KEEP = 3       # Keep some unmerged for gas/parallel txs
```

#### 2. Smart Coin Selection

When sending tokens:
1. **Exact match**: Use single coin if amount matches
2. **Minimal coins**: Select fewest coins to cover amount
3. **Gas optimization**: Reserve some coins for gas payment

#### 3. Periodic Optimization

Run daily background task to:
- Merge excessive fragmentation
- Maintain optimal coin distribution
- Log statistics for monitoring

#### 4. User Experience

**Transparent to users**:
- Show total balance only
- Handle merging automatically
- No manual coin management needed

### Implementation Phases

#### Phase 1: Basic Send (Current) ✅
- Use individual coins as-is
- Manual splitting when needed
- Basic balance aggregation

#### Phase 2: Smart Selection (Next)
- Implement `CoinManager.select_coins_for_amount()`
- Automatic coin selection for payments
- Better gas efficiency

#### Phase 3: Auto-Merge (Future)
- Background coin optimization
- Automatic merging when fragmented
- Predictive splitting for common amounts

### Technical Implementation

See `coin_management.py` for the `CoinManager` class that handles:
- `get_coin_objects()` - List all coins of a type
- `select_coins_for_amount()` - Smart selection algorithm
- `merge_coins()` - Combine multiple coins
- `prepare_exact_amount()` - Get exact amount needed

### Example Scenarios

#### Scenario 1: User receives many small payments
- **Problem**: 50 coins of 0.1 CUSD each
- **Solution**: Auto-merge into 5 coins of 1 CUSD
- **Result**: Lower transaction costs, better UX

#### Scenario 2: User wants to send exact amount
- **Problem**: Need 5.5 CUSD, have coins of 3, 2, 1, 0.5
- **Solution**: Select 3 + 2 + 1 coins, split 0.5 from change
- **Result**: Exact payment without manual management

### Monitoring and Metrics

Track:
- Average coins per user per token type
- Merge transaction frequency
- Gas costs saved through optimization
- User transaction success rates

### Security Considerations

1. **Signature Management**: Secure handling of zkLogin for merges
2. **Rate Limiting**: Prevent excessive merge operations
3. **Audit Trail**: Log all coin operations
4. **Error Recovery**: Handle partial merge failures