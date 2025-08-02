# Confío Smart Contracts

This directory contains all Move smart contracts for the Confío platform on the Sui blockchain.

## Contracts Overview

1. **cUSD** - USD-pegged stablecoin with 1:1 USDC backing
2. **CONFIO** - Governance token with fixed 1B supply
3. **Pay** - Payment processing with 0.9% fee collection
4. **Invite Send** - Send funds to non-users with 7-day reclaim
5. **P2P Trade** - Escrow-based peer-to-peer trading

## Important Documents

- **[PERMISSIONS.md](./PERMISSIONS.md)** - Comprehensive guide to all admin functions and capabilities
- Individual contract READMEs in each subdirectory

## Security Considerations

All contracts have been designed with Latin American use cases in mind:
- Privacy-preserving (no personal data on-chain)
- Support for informal economy participants
- Gasless transactions via sponsorship
- Multi-language support (Spanish characters)

## Deployment

Each contract should be deployed in the following order:
1. cUSD (stablecoin infrastructure)
2. CONFIO (governance token)
3. Pay (payment system)
4. Invite Send (invitation system)
5. P2P Trade (trading platform)

After deployment, admin capabilities should be transferred to appropriate multi-signature wallets as outlined in PERMISSIONS.md.

## Testing

Run tests for all contracts:
```bash
cd contracts/cusd && sui move test
cd contracts/confio && sui move test
cd contracts/pay && sui move test
cd contracts/invite_send && sui move test
cd contracts/p2p_trade && sui move test
```

## Audit Status

- [ ] cUSD - Pending audit
- [ ] CONFIO - Pending audit
- [ ] Pay - Pending audit
- [ ] Invite Send - Pending audit
- [ ] P2P Trade - Pending audit

## License

MIT - See repository root for full license text.