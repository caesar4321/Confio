# Blockchain Integration Module

Simple blockchain polling for Confío using shared Django infrastructure.

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

- **Single Codebase**: Shares models with main app
- **Celery Tasks**: Async processing of transactions
- **Redis Cache**: User address lookups
- **Same Database**: No sync issues

## Key Components

### Management Command
- `poll_blockchain`: Long-running gRPC stream

### Celery Tasks
- `process_transaction`: Initial processing
- `handle_cusd_transaction`: cUSD transfers
- `handle_payment_transaction`: Pay contract
- `update_user_address_cache`: Address sync

### Models
- `RawBlockchainEvent`: Audit trail
- Uses existing `Transaction` model

## Monitoring

```bash
# Check polling status
python manage.py check_polling_health

# View recent transactions
python manage.py list_recent_blockchain_events

# Cache status
python manage.py show_address_cache_stats
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