# Claude Code Instructions for Confío Project

## Project Context

**Always refer to `README.md` first** before making any changes or suggestions. The README contains:

- Project overview and purpose (LATAM Web3 wallet for stablecoins)
- Complete tech stack (React Native, Django, GraphQL, Sui blockchain)
- Project structure and architecture
- Authentication system with multi-account support
- Development setup instructions
- Security considerations and soft-delete system

## Key Project Information

### Architecture
- **Frontend**: React Native (no Expo) for mobile app
- **Backend**: Django + GraphQL API
- **Blockchain**: Sui blockchain with Move smart contracts
- **Authentication**: Firebase Auth + zkLogin for non-custodial wallets

### Important Directories
- `/apps/` - React Native mobile application
- `/config/` - Django project configuration  
- `/p2p_exchange/` - P2P exchange functionality
- `/contracts/` - Sui Move smart contracts
- `/users/` - User authentication and management

### Current Focus Areas
- P2P exchange system for crypto-to-fiat trading
- Country-specific payment methods (especially for Venezuela)
- Multi-account system (personal/business accounts)
- Payment method validation and filtering

### Development Guidelines
1. **Always check README.md** for project structure and conventions
2. **Follow existing patterns** in the codebase
3. **Use existing GraphQL schema** patterns for new endpoints
4. **Maintain security** with soft-delete system
5. **Consider Latin American context** for financial features
6. **Test with Venezuelan payment methods** as primary use case

### Development Environment
- **Python Virtual Environment**: Always use `myvenv/bin/python` for Python commands
- **Django Commands**: Use `myvenv/bin/python manage.py [command]`
- **Package Installation**: Use `myvenv/bin/pip install [package]`

### Security Notes
- Never store private keys or sensitive data
- Use soft-delete for all critical models
- Maintain audit trails for financial operations
- Follow multi-account isolation principles

## Current Session Context

We've been working on:
- Fixing payment method display issues in the P2P exchange system
- Removing "Efectivo" (cash) from Venezuelan payment methods due to hyperinflation
- Improving admin interface to show country codes and filter payment methods
- Ensuring GraphQL queries work correctly with country-specific payment methods

Always reference the project structure and conventions described in README.md when making changes.