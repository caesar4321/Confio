# Confío Blockchain Polling Service

A dedicated Django service for monitoring Sui blockchain transactions and syncing relevant data with the main Confío application.

## Overview

This service continuously polls the Sui blockchain via QuickNode's gRPC API, filters transactions relevant to Confío users, and forwards them to the main application for processing.

## Key Features

- Real-time transaction monitoring via QuickNode Sui gRPC
- Intelligent filtering based on user addresses and contract interactions
- Deduplication to prevent double processing
- Message queue integration for reliable data delivery
- Automatic retry mechanism for failed transactions
- Redis-based caching for performance

## Architecture

The polling service operates independently from the main app:

```
QuickNode → Polling Service → RabbitMQ → Main App
              ↓                             ↓
           Raw TX DB                  Business Logic
                                      Notifications
```

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set environment variables:
   ```bash
   export QUICKNODE_GRPC_ENDPOINT="your-endpoint"
   export QUICKNODE_API_KEY="your-api-key"
   export REDIS_URL="redis://localhost:6379"
   export RABBITMQ_URL="amqp://guest:guest@localhost:5672/"
   export DATABASE_URL="postgresql://user:pass@localhost/polling_db"
   export MAIN_APP_URL="https://api.confio.lat"
   export INTERNAL_API_KEY="your-internal-key"
   ```

4. Run migrations:
   ```bash
   python manage.py migrate
   ```

5. Start the services:
   ```bash
   # Transaction monitoring
   python manage.py run_polling_service
   
   # Address synchronization
   python manage.py sync_addresses
   ```

## Configuration

### Django Settings

```python
# polling_service/settings.py

# QuickNode Configuration
QUICKNODE_GRPC_ENDPOINT = env('QUICKNODE_GRPC_ENDPOINT')
QUICKNODE_API_KEY = env('QUICKNODE_API_KEY')

# Polling Configuration
POLL_INTERVAL_SECONDS = 2  # How often to check for new transactions
ERROR_RETRY_SECONDS = 10   # Retry interval on errors
BATCH_SIZE = 100          # Transactions per batch

# Contract Addresses
CUSD_MODULE_ADDRESS = '0x...'
CONFIO_MODULE_ADDRESS = '0x...'
USDC_MODULE_ADDRESS = '0x...'
PAY_MODULE_ADDRESS = '0x...'
P2P_TRADE_MODULE_ADDRESS = '0x...'
INVITE_SEND_MODULE_ADDRESS = '0x...'

# Sync Configuration
ADDRESS_SYNC_INTERVAL = 60  # Seconds between address syncs
```

## Transaction Types

The service monitors and categorizes these transaction types:

1. **cUSD Transfers** - Direct token transfers
2. **CONFIO Transfers** - Governance token movements
3. **Payments** - Transactions via Pay contract (0.9% fee)
4. **P2P Trades** - Escrow-based trading activity
5. **Invitations** - Invite Send contract activity
6. **USDC Activity** - For cUSD backing verification

## Monitoring

### Health Check Endpoint

```bash
curl http://localhost:8001/health
```

### Metrics

- Checkpoint lag
- Transactions processed per minute
- Error rate
- Queue depth

### Logs

```bash
tail -f logs/polling.log
```

## Development

### Running Tests

```bash
python manage.py test polling_service
```

### Adding New Transaction Types

1. Add module address to `MONITORED_MODULES`
2. Create handler in `handle_transaction()`
3. Define message format for main app
4. Update main app consumer

### Performance Optimization

- Use checkpoint-based polling instead of individual transactions
- Batch Redis operations
- Implement connection pooling
- Use async/await for I/O operations

## Deployment

### Docker

```bash
docker build -t confio-polling .
docker run -d --name polling --env-file .env confio-polling
```

### AWS ECS

See `deployment/ecs-task-definition.json`

### Kubernetes

See `deployment/k8s/polling-deployment.yaml`

## Troubleshooting

### Common Issues

1. **High checkpoint lag**
   - Increase instance size
   - Optimize database queries
   - Check QuickNode rate limits

2. **Missing transactions**
   - Verify address sync is working
   - Check Redis cache
   - Review filter logic

3. **Memory usage**
   - Reduce batch size
   - Implement pagination
   - Clear old processed transactions

## Security

- Internal API uses bearer token authentication
- Service-to-service communication over private network
- No direct user data exposure
- Transaction validation before processing

## License

MIT - See LICENSE file in repository root