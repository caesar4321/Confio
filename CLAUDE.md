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
7. **FlatList Implementation Rule**: When implementing a FlatList in React Native, ALWAYS include proper pagination mechanisms to ensure all items load. FlatList has built-in virtualization that may not render all items without proper configuration.
8. **Use react-native-svg instead of react-native-linear-gradient**: For all gradient needs, use react-native-svg which is already installed. All gradient effects (linear, radial, etc.) can be achieved with SVG.
9. **Use react-native-keychain instead of AsyncStorage**: For secure storage needs, use the existing react-native-keychain implementation. Do not add AsyncStorage as a dependency.
10. **JWT Context for All Operations**: Never pass account IDs as parameters - all account context must come from JWT tokens. Use `get_jwt_business_context_with_validation()` for business operations.
11. **Permission Validation**: All mutations must validate required permissions. Owners bypass checks, other roles use negative-check system.
12. **GraphQL Field Types**: Use proper GraphQL object types for complex fields, not JSONString.

### Development Environment
- **Python Virtual Environment**: Always use `myvenv/bin/python` for Python commands
- **Django Commands**: Use `myvenv/bin/python manage.py [command]`
- **Package Installation**: Use `myvenv/bin/pip install [package]`
- **Common Commands**:
  ```bash
  # Run development server with WebSocket support
  make runserver
  
  # Run migrations
  myvenv/bin/python manage.py migrate
  
  # Create new migrations
  myvenv/bin/python manage.py makemigrations
  
  # Access Django shell
  myvenv/bin/python manage.py shell
  ```

### Security Notes
- Never store private keys or sensitive data
- Use soft-delete for all critical models
- Maintain audit trails for financial operations
- Follow multi-account isolation principles
- ALL account context must come from JWT tokens, never from client parameters
- Business access always verified through user_id → BusinessEmployee.filter(business_id=x)
- Permissions use negative-check: only explicitly allowed actions permitted
- Both UI and API must enforce permissions (dual enforcement)

## Current Session Context

We've been working on:
- Fixing payment method display issues in the P2P exchange system
- Removing "Efectivo" (cash) from Venezuelan payment methods due to hyperinflation
- Improving admin interface to show country codes and filter payment methods
- Ensuring GraphQL queries work correctly with country-specific payment methods
- Fixed FlatList implementation in AddBankInfoModal to properly handle large lists with pagination
- **Major Security Overhaul**: Replaced client-controlled account parameters with JWT-based context
- **Permission System**: Implemented role-based access control with negative-check validation
- **UI Permission Blocks**: Added feature hiding for employees based on permissions (balance, P2P, payments)

### Recent Fixes
- **FlatList in AddBankInfoModal**: Converted ScrollView to FlatList for payment method and country pickers to handle large lists properly. Added pagination settings: initialNumToRender=20, maxToRenderPerBatch=10, windowSize=21, and getItemLayout for optimal performance.
- **JWT Security Overhaul (July 2025)**: Replaced all client-controlled account parameters with JWT-embedded context to prevent account spoofing and unauthorized access.
- **Business Account Data Isolation**: Fixed critical issue where all business accounts showed same balance/transactions by properly using JWT business_id instead of account.business.id.
- **Employee Permission System**: Implemented comprehensive role-based permissions with both UI blocking (hiding features) and API validation (blocking operations).
- **GraphQL Field Types**: Fixed "Field 'employeePermissions' must not have a selection" error by creating proper EmployeePermissionsType GraphQL object instead of JSONString.
- **Account Lookup Logic**: Fixed "Active account not found" errors for employees by changing user.accounts.filter() to Account.objects.filter() for business account lookups.

Always reference the project structure and conventions described in README.md when making changes.