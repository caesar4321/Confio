# Confío Documentation

This directory contains the public product, architecture, security, legal, and
operational documentation for the Confío repository.

## Product and strategy

- [English whitepaper](whitepaper/README.md) - Confío’s global product and
  strategy reference.
- [Chain decision note](CHAIN_DECISION_NOTE.md) - Role-based chain selection
  for cUSD, cUSD+, and $CONFIO.
- [Project structure](PROJECT_STRUCTURE.md) - Repository and service map.

## Wallet and blockchain architecture

- [Algorand integration guide](ALGORAND_INTEGRATION_GUIDE.md)
- [Sponsored transactions](ALGORAND_SPONSORED_TRANSACTIONS.md)
- [cUSD contracts](../contracts/cusd/README.md)
- [cUSD+ contracts](../contracts/cusd_plus/README.md)
- [cUSD+ BSC deployment record](../contracts/cusd_plus/DEPLOYMENT.md)
- [Contract access control](security/CONTRACT_ACCESS_CONTROL.md)

## Security and identity

- [Security architecture whitepaper](security/architecture_whitepaper.md)
- [Account and authentication details](security/ACCOUNT_AND_AUTH_DETAILS.md)
- [GraphQL API security](security/GRAPHQL_API_SECURITY.md)
- [Firebase App Check](security/firebase_app_check.md)
- [Referral identity policy](security/REFERRAL_REWARD_IDENTITY_POLICY.md)

## Fiat access and operations

- [Koywe test matrix](KOYWE_TEST_MATRIX.md)
- [Guardarian analysis](analysis/guardarian_analysis.md)
- [Geo-blocking policy](legal/GEO_BLOCKING.md)

## Plans and historical material

- Active implementation plans belong in [`plans/`](plans/).
- Analytical notes belong in [`analysis/`](analysis/).
- Superseded security documents are explicitly named `*_legacy.md`.

The English whitepaper is the canonical public overview. Product-specific
contract and deployment documents remain the authority for implementation
details.
