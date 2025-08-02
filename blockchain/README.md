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

## Scaling

1. **Current (< 10K users)**: Single process
2. **Growth (10K-100K)**: Dedicated Celery workers
3. **Scale (100K+)**: Separate polling instance

## Testing

```bash
python manage.py test blockchain
```