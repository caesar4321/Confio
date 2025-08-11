# Confío Smart Contracts

This directory contains all smart contracts and blockchain-related code for the Confío platform on Algorand.

## Directory Structure

The contracts are organized into 6 main categories:

### 📦 [`confio/`](./confio)
CONFIO utility/governance token (1B fixed supply)
- Token creation scripts (ASA - Algorand Standard Asset)
- Not backed by any assets (utility token)
- Token distribution utilities
- CONFIO-related tests and configurations

### 💵 [`cusd/`](./cusd)
cUSD stablecoin smart contract (backed by USDC/T-Bills)
- Main cUSD contract (1:1 backed by USDC or T-Bills)
- USDC deposits mint cUSD 1:1
- Admin mints backed by T-Bill reserves
- Test suites for cUSD functionality

### 📨 [`invite_send/`](./invite_send)
Send & Invite functionality
- Inbox router contracts with sponsor support
- Invite pool management
- Send tokens via phone/email to non-users
- 7-day expiry for unclaimed invites

### 💳 [`payment/`](./payment)
Payment routing and processing
- Payment router contracts
- Atomic payment processing
- Batch payment support
- Fee collection mechanisms
- Token distribution scripts

### 🤝 [`p2p_trade/`](./p2p_trade)
P2P trading and escrow system
- P2P vault contracts with sponsor support
- Escrow management
- 15-minute expiry for trades
- Capital-efficient box storage

### 🚀 [`presale/`](./presale)
CONFIO token presale system
- Multi-round presale contract
- Flexible exchange rates (cUSD/CONFIO)
- Lock/unlock mechanism for token distribution
- Full sponsor support for gasless transactions
- Admin controls for rounds and withdrawals

## Key Features

### Sponsor Pattern
All production contracts implement the sponsor pattern where:
- Platform (sponsor) funds all Minimum Balance Requirements (MBR)
- Users only need stablecoins, never ALGO
- 100% MBR recovery through proper box management

### Production Contracts
Production-ready contracts include:
- Sponsor funding for all MBR
- Explicit MBR refunds after box deletion
- Recipient opt-in checks
- Proper order of operations (delete → refund)

## Quick Start

### Deploy All Production Contracts
```bash
cd p2p_trade/deploy
python deploy_production_contracts.py
```

### Create Tokens
```bash
# Create CONFIO token (ASA)
cd confio
python create_confio_token_algorand.py

# Deploy cUSD contract
cd ../cusd
python deploy_cusd.py
```

## Architecture Overview

```
User → Mobile App → GraphQL API → Smart Contracts
                                    ├── cUSD (USDC/T-Bill backed stablecoin)
                                    ├── CONFIO (1B fixed utility token)
                                    ├── P2P Vault (escrow)
                                    ├── Payment Router
                                    └── Inbox Router (invites)
```

### Token Economics
- **CONFIO**: 1,000,000,000 fixed supply utility/governance token (no backing)
- **cUSD**: 1:1 backed stablecoin (USDC deposits or T-Bill reserves)
- **No cross-collateralization**: CONFIO and cUSD are independent

## Security Features

- **Box Storage**: Temporary, recoverable storage for trades/invites
- **Sponsor Pattern**: Platform covers all blockchain fees
- **Opt-in Checks**: Verify recipients can receive tokens
- **Dispute Resolution**: Arbitration for P2P trades
- **Time Limits**: Auto-expiry for trades (15 min) and invites (7 days)

## Testing

Each module contains its own test suite:
```bash
# Test cUSD
cd cusd/tests
python test_simple_mint.py

# Test P2P trades
cd p2p_trade/tests
python test_production_contracts.py
```

## Documentation

- [Sponsor Pattern Guide](./p2p_trade/SPONSOR_PATTERN_GUIDE.md)
- [Escrow Architecture](./p2p_trade/ESCROW_ARCHITECTURE_V2.md)
- [Dispute Resolution](./p2p_trade/DISPUTE_RESOLUTION_GUIDE.md)
- [MBR Recovery](./p2p_trade/MBR_RECOVERY_GUIDE.md)

## Network Configuration

- **LocalNet**: For development and testing
- **TestNet**: For staging (testnet-api.algonode.cloud)
- **MainNet**: For production (mainnet-api.algonode.cloud)

## License

Proprietary - Confío 2024