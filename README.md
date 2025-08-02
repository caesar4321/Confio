# Confío: LATAM's Open Wallet for the Dollar Economy

**Confío** is an open-source Web3 wallet and transaction platform designed for Latin America.  
It enables users to **send, receive, and hold stablecoins** (like USDC or cUSD) on the **Sui blockchain**, with zero gas fees and no crypto complexity.

Built for real people — not just crypto experts.

---

## 🌎 Why Confío?

In countries like Venezuela, Argentina, and beyond, inflation erodes trust in local currencies.  
Confío helps people access stable dollars, send remittances, and pay each other — simply and safely — using blockchain.

> "Confío" means **"I trust"** in Spanish.  
> We open-source everything because **trust must be earned, not assumed**.

---

## 🚀 What Can You Do With Confío?

- 🔐 Log in via Google/Apple using Firebase Auth
- 💸 Send cUSD to any phone contact
- 📲 Receive money through WhatsApp links
- ⚡️ Enjoy gasless (sponsored) transactions
- 🪙 Interact directly with Sui-based smart contracts
- 🏪 P2P Trading: Buy and sell crypto with local payment methods
- 💬 Real-time chat for P2P trades with WebSocket support
- 🏢 Business accounts for commercial operations
- 🏦 Bank information management with country-specific requirements

## 🧱 Tech Stack

| Layer           | Stack                         |
|-----------------|-------------------------------|
| Frontend        | React Native (no Expo)        |
| Web App         | React + TypeScript            |
| Auth            | Firebase Authentication       |
| Blockchain      | [Sui](https://sui.io)         |
| Smart Contracts | Move language                 |
| Backend API     | Django + GraphQL              |
| Real-time       | Django Channels + WebSocket   |
| Cache/Sessions  | Redis                         |
| Database        | PostgreSQL                    |
| ASGI Server     | Daphne                        |
| CI/CD           | Cloudflare Pages              |
| Link Shortener  | Cloudflare Workers + KV       |

## 🔒 What Confío Is Not

- ❌ Not a custodial wallet — we never store user funds
- ❌ No backend "tricks" — money logic lives entirely on-chain
- ❌ No crypto knowledge required — users sign in with Google or Apple

## 💬 Join the Community

Confío is more than a wallet — it's a mission to bring financial confidence to Latin America through transparency, crypto, and culture.

Come build the future with us:

🌐 Website: [confio.lat](https://confio.lat)  
🔗 Telegram (Community): [t.me/FansDeJulian](https://t.me/FansDeJulian)  
📱 TikTok (Latinoamérica): [@JulianMoonLuna](https://tiktok.com/@JulianMoonLuna)

## 📜 License

MIT License — build freely, fork proudly, remix for your country.

## 🙏 Credits

Confío is led by Julian Moon,
a Korean builder based in Latin America, inspired by the dream of a trustworthy, borderless financial inclusion for everyone. 

## 🧠 Project Structure

This is a **monolithic repository** containing the full Confío stack:

```bash
/Confio/
├── web/               # React-based web application
│   ├── public/        # Static public files
│   │   ├── index.html # Base HTML template
│   │   ├── manifest.json # Web app manifest
│   │   └── images/    # Public images
│   ├── .well-known/   # App verification files
│   │   ├── apple-app-site-association # iOS app verification
│   │   └── assetlinks.json # Android app verification
│   ├── src/           # React source code
│   │   ├── components/    # React components
│   │   ├── pages/        # Page components
│   │   │   ├── TermsPage.js    # Terms of Service page
│   │   │   ├── PrivacyPage.js  # Privacy Policy page
│   │   │   └── DeletionPage.js # Data Deletion page
│   │   ├── styles/       # CSS and SCSS files
│   │   ├── types/        # TypeScript type definitions
│   │   ├── App.css       # Main application styles
│   │   ├── App.js        # Main application component
│   │   └── index.js      # Application entry point
│   ├── build/           # Production build output
│   │   ├── static/       # Compiled static assets
│   │   │   ├── css/      # Compiled CSS files
│   │   │   ├── js/       # Compiled JavaScript files
│   │   │   └── media/    # Compiled media files
│   │   └── index.html    # Production HTML template
│   ├── scripts/         # Build and utility scripts
│   │   └── copy-index.js # Script to sync React build with Django
│   ├── .eslintrc.json   # ESLint configuration
│   ├── .prettierrc      # Prettier configuration
│   ├── nginx.conf       # Nginx configuration
│   ├── package.json     # Node.js dependencies
│   ├── tsconfig.json    # TypeScript configuration
│   └── yarn.lock        # Yarn lock file

├── config/            # Django project configuration
│   ├── settings.py    # Django settings
│   ├── urls.py        # URL routing
│   ├── wsgi.py        # WSGI configuration
│   ├── asgi.py        # ASGI configuration for Django Channels
│   ├── schema.py      # Root GraphQL schema
│   ├── celery.py      # Celery configuration
│   └── views.py       # View functions

├── auth/             # Authentication module
│   ├── models.py     # Auth-related models
│   ├── schema.py     # Auth GraphQL schema
│   ├── jwt.py        # JWT token handling
│   └── middleware.py # Auth middleware

├── telegram_verification/  # Phone verification system
│   ├── models.py     # Verification models
│   ├── schema.py     # Verification GraphQL schema
│   ├── views.py      # Verification endpoints
│   └── country_codes.py # Country codes mapping

├── p2p_exchange/      # P2P trading platform
│   ├── models.py      # P2P trading models (Offers, Trades, Messages, UserStats, Escrow)
│   ├── schema.py      # P2P GraphQL schema and mutations
│   ├── admin.py       # Enhanced admin interface with visual indicators
│   ├── consumers.py   # WebSocket consumers for real-time chat
│   ├── routing.py     # WebSocket URL routing
│   ├── default_payment_methods.py # Country-specific payment methods
│   └── migrations/    # Database migrations for P2P models

├── payments/          # Payment processing system
│   ├── models.py      # Payment transaction models
│   ├── schema.py      # Payment GraphQL schema
│   └── management/    # Payment management commands

├── send/              # Send transaction system
│   ├── models.py      # Send transaction models
│   ├── schema.py      # Send GraphQL schema
│   └── validators.py  # Transaction validation

├── security/          # Security and fraud prevention system
│   ├── models.py      # Security models (IPAddress, UserSession, DeviceFingerprint, etc.)
│   ├── middleware.py  # Security middleware for tracking IPs and sessions
│   ├── utils.py       # Security utilities (device fingerprinting, risk assessment)
│   ├── admin.py       # Enhanced admin interface for security monitoring
│   └── migrations/    # Database migrations for security models

├── prover/            # Server-side proof verification
│   ├── models.py      # Database models for storing proof verification results
│   ├── schema.py      # GraphQL schema and resolvers for proof verification endpoints
│   ├── serializers.py # Data serialization for proof verification
│   └── tests/         # Test cases for proof verification

├── prover-service/    # Standalone service for proof generation and verification
│   ├── index.js      # Main entry point for the prover service
│   ├── prover.js     # Core proof generation and verification logic
│   ├── utils.js      # Utility functions for proof operations
│   ├── tests/        # Test cases for the prover service
│   └── package.json  # Node.js dependencies and scripts
│       ├── Dependencies:
│       │   ├── @mysten/zklogin: zkLogin functionality
│       │   ├── express: Web server
│       │   ├── cors: Cross-Origin Resource Sharing
│       │   └── dotenv: Environment variable management
│       └── Scripts:
│           ├── start: Run the service
│           ├── test: Run tests
│           └── lint: Run the linter

├── users/             # User authentication and management
│   ├── models.py      # User models
│   ├── schema.py      # GraphQL schema and resolvers
│   ├── serializers.py # User data serialization
│   ├── country_codes.py # Country codes mapping [name, code, iso]
│   ├── jwt.py         # JWT token management
│   ├── middleware.py  # User authentication middleware
│   └── tests/         # User tests

├── apps/                    # React Native mobile application
│   ├── android/            # Android-specific native code and configurations
│   │   ├── app/           # Android app module
│   │   ├── google-services.json  # Firebase configuration for Android (⚠️ Add to .gitignore)
│   │   └── ...            # Other Android configurations
│   ├── ios/                # iOS-specific native code and configurations
│   │   ├── Confio/        # iOS app module
│   │   ├── GoogleService-Info.plist  # Firebase configuration for iOS (⚠️ Add to .gitignore)
│   │   └── ...            # Other iOS configurations
│   ├── src/                # React Native source code
│   │   ├── apollo/        # GraphQL client configuration and queries
│   │   ├── assets/        # Static assets (images, fonts, etc.)
│   │   │   └── svg/       # SVG assets (logos, icons)
│   │   ├── components/    # Reusable React components
│   │   ├── screens/       # Main app screens (HomeScreen, ContactsScreen, etc.)
│   │   ├── config/        # Application configuration
│   │   ├── contexts/      # React contexts (Auth, etc.)
│   │   ├── hooks/         # Custom React hooks
│   │   │   └── useAccountManager.ts  # Multi-account management hook
│   │   ├── screens/       # Screen components
│   │   │   ├── AuthScreen.tsx        # Authentication screen
│   │   │   ├── PhoneVerificationScreen.tsx  # Phone verification
│   │   │   ├── HomeScreen.tsx        # Main app screen
│   │   │   └── CreateBusinessScreen.tsx     # Business account creation
│   │   ├── services/      # API and business logic services
│   │   │   ├── authService.ts    # Authentication service with multi-account support
│   │   │   └── ...        # Other services
│   │   ├── types/         # TypeScript type definitions
│   │   ├── utils/         # Utility functions
│   │   │   ├── accountManager.ts # Multi-account storage and management
│   │   │   ├── countries.ts  # Country codes mapping [name, code, iso, flag]
│   │   │   ├── zkLogin.ts   # zkLogin utilities with multi-account salt generation
│   │   │   └── ...        # Other utility functions
│   │   └── ...            # Other source files
│   ├── scripts/           # Build and development scripts
│   ├── .env               # Environment variables (⚠️ Add to .gitignore)
│   ├── babel.config.js    # Babel configuration
│   ├── firebase.json      # Firebase configuration
│   ├── metro.config.js    # Metro bundler configuration
│   └── package.json       # Node.js dependencies

├── contracts/    # Sui Move smart contracts
│   ├── README.md     # Contracts overview and deployment guide
│   ├── PERMISSIONS.md # Comprehensive permissions and multi-sig guide
│   ├── cusd/     # CUSD stablecoin implementation
│   │   ├── sources/  # Move source files
│   │   │   ├── cusd.move              # CUSD stablecoin implementation
│   │   │   ├── cusd_vault_usdc.move   # USDC vault for CUSD minting/burning
│   │   │   └── cusd_vault_treasury.move # Treasury vault for CUSD operations
│   │   ├── Move.toml # Package configuration
│   │   └── Move.lock # Dependency lock file
│   ├── confio/   # CONFIO governance token
│   │   ├── sources/  # Move source files
│   │   │   └── confio.move            # CONFIO governance token implementation
│   │   ├── Move.toml # Package configuration
│   │   └── Move.lock # Dependency lock file
│   ├── pay/      # Payment processing with fee collection
│   │   ├── sources/  # Move source files
│   │   │   └── pay.move               # Payment system with 0.9% fee
│   │   ├── Move.toml # Package configuration
│   │   └── Move.lock # Dependency lock file
│   ├── invite_send/  # Send funds to non-users with invitations
│   │   ├── sources/  # Move source files
│   │   │   └── invite_send.move       # Invitation system with 7-day reclaim
│   │   ├── Move.toml # Package configuration
│   │   └── Move.lock # Dependency lock file
│   └── p2p_trade/    # P2P trading with escrow and dispute resolution
│       ├── sources/  # Move source files
│       │   └── p2p_trade.move         # Escrow-based P2P trading system
│       ├── tests/    # Test files
│       │   └── escrow_security_test.move  # Security test cases
│       ├── README.md # Contract documentation
│       ├── Move.toml # Package configuration
│       └── Move.lock # Dependency lock file

├── workers/           # Cloudflare Workers services
│   └── link-shortener/  # Link shortener for WhatsApp share links
│       ├── src/
│       │   └── index.ts  # Worker code for platform detection and redirects
│       ├── public/
│       │   └── admin.html  # Admin UI for link management
│       ├── wrangler.toml   # Cloudflare Workers configuration
│       ├── tsconfig.json   # TypeScript configuration
│       ├── package.json    # Node.js dependencies
│       ├── README.md       # Link shortener documentation
│       └── DEPLOY.md       # Deployment instructions

├── manage.py          # Django management script
├── requirements.txt   # Python dependencies
└── celery.py         # Celery worker configuration
```

## 🔒 Authentication & Security

### Authentication Flow
1. **Social Sign-In**
   - Sign in with Google or Apple
   - Firebase Authentication handles OAuth flow
   - Secure token exchange with backend

2. **Phone Verification**
   - Required for enhanced security
   - Telegram-based verification system
   - Country code support for LATAM

3. **zkLogin Integration**
   - Zero-knowledge proof authentication
   - Secure key derivation and storage
   - Automatic proof refresh before expiration

### Multi-Account System

Confío supports multiple accounts per user, allowing separate wallets for personal and business use cases with advanced JWT-based context management and role-based access control.

#### Account Types
- **Personal Accounts**: Individual wallets for personal transactions
- **Business Accounts**: Dedicated wallets for business operations with employee management

#### Account ID Format
- **Personal**: `personal_{index}` (e.g., `personal_0`, `personal_1`)
- **Business (All)**: `business_{businessId}_{index}` (e.g., `business_123_0`, `business_456_1`)
  - Both owners and employees use the same format
  - Differentiation between owner/employee is done via BusinessEmployee relation model on server
  - businessId is the actual Business model ID from the database

#### Salt Formula
The multi-account system uses deterministic salt generation:
```
salt = SHA256(issuer | subject | audience | account_type | business_id (if applied) | account_index)
```

Where:
- `issuer`: JWT issuer (e.g., "https://accounts.google.com")
- `subject`: JWT subject (user's unique ID)
- `audience`: OAuth client ID
- `account_type`: Either "personal" or "business"
- `business_id`: Business ID (only included for business accounts)
- `account_index`: Numeric index (0, 1, 2, etc.)

#### JWT Integration

The system includes comprehensive JWT context management for secure account operations:

**JWT Payload Structure**
```json
{
  "user_id": "123",
  "username": "user@example.com",
  "account_type": "business",
  "account_index": 0,
  "business_id": "456",  // Present for ALL business accounts (owner and employee)
  "auth_token_version": 1,
  "exp": 1234567890,
  "type": "access"
}
```

**Account Context in API Requests**
- All GraphQL queries/mutations automatically receive account context from JWT
- Business operations validate access through BusinessEmployee relationships
- No client-controlled parameters for sensitive operations
- Account context determines which wallet address and data to access

#### Business Employee System

Business accounts support multiple employees with role-based permissions:

**Roles**
- **Owner**: Full access to all business operations (bypasses permission checks)
- **Admin**: All operations except deleting the business
- **Manager**: Full operational permissions without employee management
- **Cashier**: Limited to accepting payments and creating invoices

**Permission System (Negative-Check)**
```python
# Permissions are explicitly defined - if not listed, access is denied
ROLE_PERMISSIONS = {
    'owner': {
        # All permissions granted (special case - bypasses checks)
        'accept_payments', 'view_transactions', 'view_balance', 'send_funds',
        'manage_employees', 'view_business_address', 'view_analytics',
        'delete_business', 'edit_business_info', 'manage_bank_accounts',
        'manage_p2p', 'create_invoices', 'manage_invoices', 'export_data'
    },
    'admin': {
        'accept_payments': True, 'view_transactions': True, 'view_balance': True,
        'send_funds': True, 'manage_employees': True, 'view_business_address': True,
        'view_analytics': True, 'edit_business_info': True, 'manage_bank_accounts': True,
        'manage_p2p': True, 'create_invoices': True, 'manage_invoices': True,
        'export_data': True
        # Note: delete_business is False (not granted)
    },
    'manager': {
        'accept_payments': True, 'view_transactions': True, 'view_balance': True,
        'send_funds': True, 'view_business_address': True, 'view_analytics': True,
        'manage_bank_accounts': True, 'manage_p2p': True, 'create_invoices': True,
        'manage_invoices': True, 'export_data': True
        # Note: manage_employees and edit_business_info are False
    },
    'cashier': {
        'accept_payments': True, 'view_transactions': True, 'create_invoices': True
        # Note: All other permissions are False, including:
        # - view_balance (cannot see business balance)
        # - view_business_address (cannot see business address)
        # - send_funds (cannot make payments)
        # - manage_p2p (cannot access P2P trading)
    }
}
```

**Security Pattern**
- All business operations verify access through `user_id → BusinessEmployee.filter(business_id=x)`
- Never directly access through business_id to prevent security vulnerabilities
- JWT context validation happens centrally in `get_jwt_business_context_with_validation()`
- Both UI and API enforce permissions - UI hides features, API blocks operations
- Owners identified by role='owner' in BusinessEmployee, not by account ownership

**UI Permission Enforcement**
The frontend automatically adapts based on employee permissions:

```typescript
// Balance visibility
{activeAccount?.isEmployee && !activeAccount?.employeePermissions?.viewBalance
  ? '••••••'  // Hidden for employees without permission
  : '$1,234.56'
}

// Action buttons
{activeAccount?.isEmployee && quickActions.length <= 1 ? (
  // Show welcome message instead of limited actions
  <EmployeeWelcomeMessage />
) : (
  // Show available action buttons
  <ActionButtons />
)}

// Tab visibility
- Scan tab: Hidden for employees without sendFunds
- Exchange tab: Shows lock message without manageP2p
- Charge>Pagar: Shows lock message without sendFunds

// Address visibility
- Business address hidden for cashiers (no viewBusinessAddress permission)
- Personal addresses always visible to account owner
```

#### Default Behavior
- **New users**: Automatically get `personal_0` as their default account
- **Existing users**: Continue using their current salt (equivalent to `personal_0`)
- **Account switching**: Each account type/index combination generates a unique Sui address
- **Employee accounts**: Access business through JWT with embedded business_id
- **Business owners**: Also receive business_id in JWT for consistent security model

#### Security Model
1. **Deterministic**: Same OAuth identity + account context = same Sui address
2. **Isolated**: Each account has its own private key and Sui address
3. **Non-custodial**: Private keys are never stored on servers
4. **Stateless**: Server doesn't track active accounts, client manages state
5. **Role-based**: Negative-check permission system ensures only explicitly allowed actions
6. **Relationship-based**: All business access verified through BusinessEmployee table
7. **JWT-first**: All account context comes from JWT, never from client parameters

### Atomic Account Switching

The app uses atomic account switching to prevent partial state updates where different parts of the app could be in different account contexts.

#### Problem Solved
- Profile and balance showing Business account, but acting like Personal account
- Offers created by Business account requiring Personal account permissions
- JWT token, Sui address, and zkLogin private values getting out of sync

#### Implementation

The `useAtomicAccountSwitch` hook ensures all account-related state is synchronized:

1. **Validates** the target account exists
2. **Pauses** all Apollo queries to prevent race conditions
3. **Clears** Apollo cache to prevent stale data
4. **Updates** account context in Keychain
5. **Obtains** new JWT token with updated context
6. **Refreshes** profile data
7. **Refreshes** accounts list
8. **Resumes** Apollo queries
9. **Validates** everything is in sync

#### Usage

```typescript
import { useAtomicAccountSwitch } from '../hooks/useAtomicAccountSwitch';
import { AccountSwitchOverlay } from '../components/AccountSwitchOverlay';

function MyComponent() {
  const { 
    switchAccount, 
    state, 
    isAccountSwitchInProgress 
  } = useAtomicAccountSwitch();
  
  const handleAccountSwitch = async (accountId: string) => {
    const success = await switchAccount(accountId);
    if (success) {
      // Account switched successfully
    }
  };
  
  return (
    <>
      {/* Your UI */}
      
      {/* Always include the overlay to block UI during switch */}
      <AccountSwitchOverlay
        visible={state.isLoading}
        progress={state.progress}
      />
    </>
  );
}
```

#### What Gets Synchronized
- Keychain account context
- JWT authentication token  
- Apollo cache (cleared and refetched)
- Profile data (personal or business)
- Active queries
- UI state

#### Important Notes
1. **Always use `useAtomicAccountSwitch`** instead of the raw `switchAccount` from `useAccount`
2. **Always include `AccountSwitchOverlay`** in your component to block UI during switch
3. **Never bypass the atomic switch** - it ensures data consistency
4. **Account context comes from JWT** - never pass accountId to mutations
8. **Permission validation**: Every mutation validates required permissions

#### Implementation Components

**Account Manager** (`apps/src/utils/accountManager.ts`)
- Manages account storage and retrieval using React Native Keychain
- Handles account creation, switching, and context management
- Stores account metadata including business relationships

**Auth Service Integration** (`apps/src/services/authService.ts`)
- Automatically uses active account context for salt generation
- Provides account switching and creation methods
- Manages JWT tokens with embedded account context

**JWT Context** (`users/jwt_context.py`)
- `get_jwt_business_context_with_validation()`: Extracts account context from JWT and validates BusinessEmployee access
  - Pass `required_permission=None` for read-only operations
  - Pass specific permission (e.g., 'send_funds', 'manage_employees') for mutations
- `check_role_permission()`: Implements negative-check permission system

**React Hook** (`apps/src/hooks/useAccountManager.ts`)
- Provides easy access to account management in React components
- Handles account state and operations

## 🔗 Link Shortener (WhatsApp Share Links)

Confío uses a custom Cloudflare Workers-based link shortener for WhatsApp share links during closed-beta (TestFlight). This replaces expensive third-party services with a cost-effective solution.

### Features
- **Short Links**: Generate links like `confio.lat/abc123`
- **Platform Detection**: Automatically detects iOS/Android/Desktop
- **Smart Redirects**:
  - iOS → TestFlight with referral data
  - Android → Play Store with referrer parameter
  - Desktop → Landing page with campaign data
- **Deferred Deep Linking**: Post-install attribution with 48-hour window
- **Analytics**: Track clicks, platforms, and countries
- **Cost-Effective**: Free tier covers most usage (vs $1,200/month Branch.io)

### Implementation

#### Worker Service (`/workers/link-shortener/`)
- **Platform Detection**: User-agent based platform detection
- **API Endpoints**: Create links, get statistics
- **KV Storage**: Stores link data and analytics
- **Admin UI**: Web interface for link management

#### React Native Integration (`/apps/src/utils/deepLinkHandler.ts`)
- **Deep Link Handler**: Processes incoming links
- **Deferred Links**: Stores links for post-login processing
- **Secure Storage**: Uses react-native-keychain for deferred links
- **Navigation**: Routes users to appropriate screens

### Deployment
See `/workers/link-shortener/DEPLOY.md` for detailed deployment instructions. Key steps:
1. Create Cloudflare KV namespaces
2. Configure environment variables
3. Deploy with `wrangler deploy`
4. Set up custom domain routing
5. Configure iOS Universal Links
- Syncs with server-provided account data

#### Usage Examples

**Creating a Business Account**
```typescript
const businessAccount = await authService.createAccount(
  'business',
  'El Sabor de Chicha',
  'E',
  undefined,
  'Restaurante'
);
await authService.switchAccount(businessAccount.id);
```

**Switching Between Accounts**
```typescript
await authService.switchAccount('personal_0'); // Personal account
await authService.switchAccount('business_123_0'); // Business account (ID 123)
```

**Employee Access**
```typescript
// Employee switches to employer's business account
await authService.switchAccount('business_456_0'); // Business ID 456
// JWT automatically includes business_id for permission validation
// Server differentiates owner vs employee via BusinessEmployee relation
```

**GraphQL Query with Permission Check**
```python
# Backend automatically validates access
jwt_context = get_jwt_business_context_with_validation(info, required_permission='view_balance')
if not jwt_context:
    return "0"  # Access denied
```

#### Permission Examples

**Cashier Creating Invoice** ✅
```python
# Cashier has 'accept_payments' permission
jwt_context = get_jwt_business_context_with_validation(info, required_permission='accept_payments')
# Access granted - can create invoice
```

**Cashier Managing Employees** ❌
```python
# Cashier lacks 'manage_employees' permission
jwt_context = get_jwt_business_context_with_validation(info, required_permission='manage_employees')
# Returns None - access denied
```

**Owner Any Operation** ✅
```python
# Owners bypass all permission checks
if employee_record.role == 'owner':
    # Full access granted
```

### Token Management
1. **Access Token**
   - Short-lived (1 hour) for security
   - Contains account context (type, index, business_id)
   - Automatically refreshed using refresh token
   - Stored securely in device Keychain

2. **Refresh Token**
   - Long-lived (1 year) for persistent sessions
   - Used to obtain new access tokens
   - Stored securely in device Keychain

3. **Token Refresh Mechanism**
   - Proactive refresh: Checks token expiration before requests
   - Reactive refresh: Handles expired token errors
   - Request queue management during refresh
   - Automatic retry of failed requests after refresh
   - Secure token storage and cleanup
   - Account context preserved across token refreshes

### Security Features
- 🔒 Secure credential storage using Keychain
- 🔄 Automatic token refresh and rotation
- 🧹 Complete data cleanup on sign out
- 🔐 JWT-based API authentication
- 🛡️ Protection against replay attacks

### Soft Delete System (Security & Audit)

Confío uses a **soft delete** system for all critical models, including:
- User
- Business
- Account
- Transaction
- IdentityVerification
- ZkLoginProof
- TelegramVerification

Instead of permanently deleting records, a `deleted_at` timestamp is set. This ensures:
- **No index reuse**: Deleted accounts/businesses/users cannot be recreated with the same index, preventing Sui address collisions and key reuse.
- **Prevents collision of eliminated and newly created accounts**: If an account is deleted, its index is never reused, so a new account cannot be created with the same index and thus cannot generate the same Sui address. This eliminates the risk of a new user accidentally or maliciously taking over the Sui address of a previously deleted account.
- **Auditability**: All actions are traceable for compliance and security audits.
- **Data integrity**: Financial and identity records are never truly lost, only flagged as deleted.
- **Security**: Prevents accidental or malicious recreation of accounts with the same salt, which would result in the same Sui address and potential fund loss or takeover.

All queries for account creation/index assignment include soft-deleted rows to prevent index reuse. Normal queries (default manager) exclude soft-deleted rows, so deleted items are hidden from the UI and API by default.

#### Example: Why Soft Delete?
If a business account `business_2` is deleted, the next business account will be `business_3`, not `business_2` again. This ensures that the Sui address for `business_2` is never reused, maintaining cryptographic and financial safety.

## 🔒 Recent Security Enhancements

### JWT-Based Account Context (July 2025)
Major security overhaul replacing client-controlled account parameters with JWT-embedded context:

- **Before**: Account ID passed as GraphQL parameters (security risk)
- **After**: Account context embedded in JWT token (secure)
- **Impact**: Prevents account spoofing and unauthorized access
- **Implementation**: All GraphQL resolvers updated to use `get_jwt_business_context_with_validation()`

### Permission System Improvements
- Centralized permission validation in JWT context extraction
- Negative-check system: only explicitly allowed actions permitted
- UI and API dual enforcement: features hidden + operations blocked
- Employee access always validated through BusinessEmployee relation

### Key Security Fixes
- Fixed business accounts showing same data regardless of accessor
- Fixed payment attribution errors in multi-account scenarios
- Removed deprecated header-based context middleware
- Added permission checks to all financial mutations
- Implemented role-based UI feature blocking

## 💸 Transaction Types

Confío supports four main categories of transactions, each with distinct types and flows:

### Send Transactions
Direct transfers between users with different recipient types:

- **👥 Confío Friend** - Send to existing Confío users
  - Recipient has a registered Confío account with their deterministic non-custodial Sui address
  - Instant delivery to their wallet
  - Real-time notifications

- **📧 Non-Confío Friend** - Invite new users via phone number
  - Recipient receives invitation via phone/WhatsApp
  - Funds held in smart contract until claimed
  - When the invitee claims the funds, it's released to the invitee's Sui wallet address
  - 7-day expiration period before reversion

- **🔗 External Wallet** - Direct blockchain transfers
  - Send to any Sui wallet address
  - No invitation or registration required
  - Pure on-chain transaction

**Note**: Businesses cannot receive personal payments with Send feature to maintain clear separation between commercial and personal finances.

### Payment Transactions
Commercial transactions for business operations:

- **Personal → Business** - Consumer payments to merchants
  - Users pay businesses for goods/services
  - QR code and invoice-based payments
  - Receipt generation and tracking
  - 0.9% merchant fee automatically deducted via smart contract
  - Merchant receives 99.1% of payment amount

- **Business → Business** - B2B transactions
  - Inter-business payments and settlements
  - Supply chain and vendor payments
  - Commercial invoicing system
  - 0.9% fee for receiving business

### Exchange Transactions
P2P trading platform for buying/selling crypto with fiat:

- **Any Account Type** - All combinations supported
  - Personal → Personal (P2P)
  - Personal → Business (P2B) 
  - Business → Business (B2B)
  - Business → Personal (B2P)
  - Trade cUSD or CONFIO tokens for fiat currency
  - Local payment methods (bank transfers, mobile money)
  - Smart contract based escrow-protected transactions

### Conversion Transactions  
Currency conversion within the same account:

- **USDC ↔ cUSD** - Convert between stablecoin types
  - Available for both personal and business accounts
  - 1:1 conversion rate (always)
  - Seamless currency switching for user convenience

### Transaction Fees

- **Send**: Free (including Sui network fees - sponsored by Confío)
- **Payment**: 0.9% merchant fee (automatically deducted via smart contract)
- **Exchange**: Free (including Sui network fees - sponsored by Confío)
- **Conversion**: Free (including Sui network fees - sponsored by Confío)

All Sui blockchain network fees are covered by Confío through sponsored transactions, ensuring users never need to hold SUI tokens for gas fees.

## 🏪 P2P Trading Platform

Confío includes a comprehensive peer-to-peer trading platform that allows users to buy and sell cryptocurrency using local payment methods.

### Key Features

- **Multi-Currency Support**: Trade cUSD and CONFIO tokens
- **Local Payment Methods**: Support for country-specific payment methods (bank transfers, digital wallets, cash)
- **Real-time Chat**: WebSocket-powered messaging system for trade coordination
- **Account Context**: Separate trading for personal and business accounts
- **Admin Interface**: Enhanced admin panel with visual indicators for trade management

### Architecture

#### Direct Relationship Model
The P2P platform uses a **direct foreign key architecture** for cleaner semantics:

- **P2POffer**: Links directly to `offer_user` or `offer_business`
- **P2PTrade**: Links directly to `buyer_user`/`buyer_business` and `seller_user`/`seller_business`
- **P2PMessage**: Links directly to `sender_user` or `sender_business`
- **P2PUserStats**: Links directly to `stats_user` or `stats_business`

This eliminates confusing Account indirection and provides:
- ✅ **Clearer semantics**: Direct relationships are self-explanatory
- ✅ **Better performance**: Fewer database joins required
- ✅ **Account context filtering**: Trades filter correctly by user vs business context
- ✅ **Visual admin interface**: 👤 for users, 🏢 for businesses
- ✅ **JWT-based context**: Account context determined by JWT, not client parameters

#### WebSocket Integration
Real-time features powered by Django Channels:

```python
# ASGI Configuration (config/asgi.py)
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
```

#### Hybrid GraphQL + WebSocket Architecture

The P2P chat system uses a **hybrid approach** combining the reliability of GraphQL mutations with the real-time capabilities of WebSocket connections:

**GraphQL Mutations for Sending Messages**
- Reliable message delivery through structured API
- Built-in error handling and validation
- Consistent with the rest of the application architecture
- Automatic retry mechanisms through Apollo Client

**Raw WebSocket for Real-time Updates**
- Immediate message delivery to all connected clients
- Low-latency real-time communication
- Proven compatibility with Django Channels
- Direct channel layer broadcasting

```typescript
// Frontend implementation
const [sendMessage] = useMutation(SEND_P2P_MESSAGE);
const websocket = useRef<WebSocket | null>(null);

// Send via GraphQL mutation
await sendMessage({
  variables: {
    input: { tradeId, content: messageContent, messageType: 'TEXT' }
  }
});

// Receive via WebSocket
websocket.current.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // Handle real-time message updates
};
```

**Benefits of Hybrid Approach:**
- ✅ **Reliable sending**: GraphQL ensures messages are properly stored and validated
- ✅ **Real-time receiving**: WebSocket provides instant updates to all participants
- ✅ **Fallback compatibility**: Works with existing WebSocket infrastructure
- ✅ **Best performance**: Combines strengths of both technologies
- ✅ **Proven stability**: Avoids complex GraphQL subscription protocol issues

#### Payment Methods
Country-specific payment methods defined in `p2p_exchange/default_payment_methods.py`:

- **Venezuela**: Pago Móvil, Zelle, Binance Pay, PayPal
- **Argentina**: Mercado Pago, Transferencia Bancaria, Ualá, Brubank
- **Colombia**: Nequi, Daviplata, Bancolombia, PSE
- **Global**: USDT TRC20, Bitcoin, Ethereum, PayPal

### Database Models

#### P2POffer
```python
class P2POffer(SoftDeleteModel):
    # Direct relationships
    offer_user = models.ForeignKey(User, ...)
    offer_business = models.ForeignKey(Business, ...)
    
    # Trading details
    exchange_type = models.CharField(choices=['BUY', 'SELL'])
    token_type = models.CharField(choices=['cUSD', 'CONFIO'])
    rate = models.DecimalField(...)
    payment_methods = models.ManyToManyField(P2PPaymentMethod)
```

#### P2PTrade
```python
class P2PTrade(SoftDeleteModel):
    # Direct relationships
    buyer_user = models.ForeignKey(User, ...)
    buyer_business = models.ForeignKey(Business, ...)
    seller_user = models.ForeignKey(User, ...)
    seller_business = models.ForeignKey(Business, ...)
    
    # Trade details
    crypto_amount = models.DecimalField(...)
    fiat_amount = models.DecimalField(...)
    status = models.CharField(choices=STATUS_CHOICES)
```

#### P2PMessage
```python
class P2PMessage(SoftDeleteModel):
    trade = models.ForeignKey(P2PTrade, ...)
    
    # Direct relationships
    sender_user = models.ForeignKey(User, ...)
    sender_business = models.ForeignKey(Business, ...)
    
    content = models.TextField()
    message_type = models.CharField(choices=MESSAGE_TYPES)
```

### GraphQL API

The P2P platform exposes a comprehensive GraphQL API:

#### Queries
- `p2pOffers`: List available offers with filtering
- `myP2pTrades`: User's trades filtered by JWT account context (no accountId parameter)
- `p2pTradeMessages(tradeId)`: Real-time trade chat messages
- `p2pPaymentMethods(countryCode)`: Country-specific payment methods

#### Mutations
- `createP2POffer`: Create new trading offers (uses JWT context)
- `createP2PTrade`: Initiate trades with offers (uses JWT context)
- `updateP2PTradeStatus`: Update trade status (validates permissions)
- `sendP2PMessage`: Send messages in trade chat (uses JWT context)

### Usage Examples

#### Creating an Offer
```graphql
mutation CreateOffer {
  createP2pOffer(input: {
    exchangeType: "SELL"
    tokenType: "cUSD"
    rate: 36.50
    minAmount: 10.00
    maxAmount: 1000.00
    availableAmount: 500.00
    paymentMethodIds: ["1", "2"]
    countryCode: "VE"
    accountId: "business_123_0"
  }) {
    success
    offer { id rate availableAmount }
  }
}
```

#### Real-time Trade Messages
```graphql
query TradeMessages($tradeId: ID!) {
  p2pTradeMessages(tradeId: $tradeId) {
    id
    content
    senderType
    senderDisplayName
    createdAt
  }
}
```

## 💱 Exchange Rate System

Confío includes a comprehensive multi-currency exchange rate system that provides real-time market rates for P2P trading across Latin America and global markets.

### Supported Currencies

The system supports **25 currencies** with specialized sources for accurate market rates:

#### **Latin America (10 currencies)**
- **VES** - Venezuela (Bolívar)
- **ARS** - Argentina (Peso) 
- **COP** - Colombia (Peso)
- **PEN** - Peru (Sol)
- **CLP** - Chile (Peso)
- **BOB** - Bolivia (Boliviano)
- **UYU** - Uruguay (Peso)
- **PYG** - Paraguay (Guaraní)
- **BRL** - Brazil (Real)
- **MXN** - Mexico (Peso)

#### **North America & Oceania (3 currencies)**
- **USD** - United States (Dollar) - *base currency*
- **CAD** - Canada (Dollar)
- **AUD** - Australia (Dollar)

#### **Europe (2 currencies)**
- **EUR** - Europe (Euro)
- **GBP** - United Kingdom (Pound)

#### **Asia Pacific (10 currencies)**
- **JPY** - Japan (Yen)
- **CNY** - China (Yuan)
- **KRW** - South Korea (Won)
- **INR** - India (Rupee)
- **SGD** - Singapore (Dollar)
- **THB** - Thailand (Baht)
- **PHP** - Philippines (Peso)
- **MYR** - Malaysia (Ringgit)
- **IDR** - Indonesia (Rupiah)
- **VND** - Vietnam (Dong)

| Region | Count | Sources |
|--------|-------|---------|
| **Latin America** | 10 currencies | Country-specific APIs + global APIs |
| **North America & Oceania** | 3 currencies | Global APIs |
| **Europe** | 2 currencies | Global APIs |
| **Asia Pacific** | 10 currencies | Global APIs |
| **Total** | **25 currencies** | Multiple specialized sources |

### Exchange Rate Sources

#### Global Multi-Currency Sources
- **ExchangeRate-API** (`exchangerate_api`)
  - **Coverage**: 24+ global currencies
  - **Rate Type**: Official exchange rates
  - **Reliability**: ⭐⭐⭐⭐⭐ High
  - **Update Frequency**: Real-time
  - **Status**: ✅ Active

- **Yadio** (`yadio`)
  - **Coverage**: Limited currencies including VES
  - **Rate Type**: Market rates
  - **Reliability**: ⭐⭐⭐⭐ Good
  - **Purpose**: VES backup source
  - **Status**: ✅ Active

- **CurrencyLayer** (`currencylayer`)
  - **Coverage**: Various currencies (limited free tier)
  - **Rate Type**: Official rates
  - **Reliability**: ⭐⭐⭐ Medium
  - **Purpose**: Additional coverage when available
  - **Status**: 🟡 Partial (limited coverage)

#### Argentina-Specific Sources (ARS)
Argentina requires specialized sources due to multiple official rates and significant parallel market ("blue dollar") premium:

- **Bluelytics** (`bluelytics`)
  - **API**: `https://api.bluelytics.com.ar/v2/latest`
  - **Coverage**: ARS official + blue dollar rates
  - **Rate Types**: 
    - `official`: Government rate (~1,283 ARS/USD)
    - `parallel`: Blue dollar rate (~1,305 ARS/USD)
  - **Reliability**: ⭐⭐⭐⭐⭐ Excellent
  - **Purpose**: True parallel market rates for P2P trading
  - **Status**: ✅ Active

- **DolarAPI** (`dolarapi`)
  - **API**: `https://dolarapi.com/v1/dolares`
  - **Coverage**: Multiple ARS rate types
  - **Rate Types**:
    - `oficial`: Official government rate
    - `blue`: Blue dollar (parallel market)
    - `bolsa`: Stock market rate
    - `contadoconliqui`: CCL rate
  - **Reliability**: ⭐⭐⭐⭐⭐ Excellent
  - **Purpose**: Comprehensive Argentine market rates
  - **Status**: ✅ Active

#### Historical Sources (Deprecated)
- **DolarToday** (`dolartoday`) - ❌ **REMOVED**
  - **Issue**: S3 bucket no longer exists (404 error)
  - **Was**: Venezuelan parallel market specialist
  - **Replacement**: Yadio + ExchangeRate-API for VES rates

### Rate Types

The system categorizes rates into different types based on their source and market context:

| Rate Type | Description | Use Case | Countries |
|-----------|-------------|----------|-----------|
| `official` | Government/bank rates | Stable economies | BOB, USD, EUR, etc. |
| `parallel` | Black/blue market rates | P2P trading | ARS (blue dollar), VES |
| `average` | Averaged market rates | Reference rates | ARS (bolsa, CCL) |

### Architecture

#### Backend Components (`exchange_rates/`)
- **Models** (`models.py`): `ExchangeRate`, `RateFetchLog` with soft delete support
- **Services** (`services.py`): Multi-source fetching with error handling and logging
- **Admin** (`admin.py`): Visual admin interface with colored badges and rate comparison
- **Tasks** (`tasks.py`): Celery-based periodic rate fetching
- **Currency Mapping** (`currency_mapping.py`): Country-to-currency mappings

#### Frontend Integration (`apps/src/`)
- **Hooks** (`hooks/useExchangeRate.ts`):
  - `useSelectedCountryRate()`: Dynamic rate based on selected country
  - `useExchangeRate()`: Generic currency pair rates
  - `useCryptoToFiatCalculator()`: Crypto-to-fiat conversion utilities
- **Components** (`components/ExchangeRateDisplay.tsx`): Real-time rate display with currency codes
- **Currency Utilities** (`utils/currencyMapping.ts`): Country-to-currency mapping functions

#### GraphQL API (`exchange_rates/schema.py`)
```graphql
type Query {
  exchangeRateWithFallback(sourceCurrency: String!, targetCurrency: String!): String
  currentExchangeRate(sourceCurrency: String!, targetCurrency: String!, rateType: String!): String
}
```

### Country-Specific Exchange Rate Examples

#### Venezuela (VES)
- **Challenge**: Economic instability, multiple rate tiers
- **Sources**: Yadio (market rates) + ExchangeRate-API (official rates)
- **Current Rate**: ~119 VES/USD
- **Note**: Parallel market rates significantly higher than official rates

#### Argentina (ARS)
- **Challenge**: Multiple official rates, blue dollar premium
- **Sources**: Bluelytics + DolarAPI (specialized Argentine APIs)
- **Rate Examples**:
  - Official: ~1,283 ARS/USD
  - Blue Dollar: ~1,305 ARS/USD (what people actually use)
- **Accuracy**: ⭐⭐⭐⭐⭐ Excellent (true parallel market rates)

#### Bolivia (BOB)
- **Status**: Economically stable, recent inflation
- **Sources**: ExchangeRate-API (official rates sufficient)
- **Current Rate**: ~6.9 BOB/USD
- **Note**: Official rates still reflect market reality

#### Colombia (COP)
- **Status**: Stable currency with official rate accuracy
- **Sources**: ExchangeRate-API
- **Current Rate**: ~4,013 COP/USD
- **Note**: No parallel market premium

### Automatic Updates

The system fetches rates automatically via Celery tasks:

```python
# config/settings.py
CELERY_BEAT_SCHEDULE = {
    'fetch-exchange-rates': {
        'task': 'exchange_rates.tasks.fetch_all_rates',
        'schedule': crontab(minute='*/15'),  # Every 15 minutes
    },
}
```

### Error Handling & Monitoring

- **Comprehensive Logging**: All API calls logged with response times and success/failure status
- **Fallback Logic**: Multiple sources with priority: specialized → general → fallback
- **Rate Fetch Logs**: `RateFetchLog` model tracks all fetching attempts for debugging
- **Admin Interface**: Visual indicators for source reliability and rate freshness

### Usage in P2P Trading

The exchange rate system integrates seamlessly with P2P trading:

1. **Market Rate Display**: Shows current rates like "1,305 ARS/USD mercado" in the UI
2. **Rate Comparison**: P2P offers show percentage difference from market rate
3. **Country-Specific**: Automatically uses appropriate currency based on user's country
4. **Real-time Updates**: Rates update every 15 minutes for accurate pricing

### Development Commands

```bash
# Manual rate fetching
python manage.py fetch_rates

# Check current rates
python manage.py shell -c "from exchange_rates.models import ExchangeRate; print(ExchangeRate.objects.filter(source_currency='ARS').order_by('-fetched_at')[:5])"

# View rate fetch logs
# Admin interface: /admin/exchange_rates/ratefetchlog/
```

This multi-currency system ensures that Confío users across Latin America have access to accurate, real-time exchange rates for fair P2P trading regardless of their local economic conditions.

## 🔐 Security & Fraud Prevention

Confío implements a comprehensive security system to protect users and prevent fraud while maintaining the permissionless nature of blockchain transactions.

### Device Fingerprinting

The security system collects device fingerprints to track and monitor user activity across sessions:

#### Client-Side (React Native)
- **Implementation**: `apps/src/utils/deviceFingerprint.js`
- **Features**:
  - Persistent device ID using React Native Keychain
  - Hardware information collection
  - Behavioral pattern tracking
  - Screen and system information
  - Timezone and locale detection

#### Backend Integration
- **Models**: IPAddress, UserSession, DeviceFingerprint, UserDevice
- **Middleware**: SecurityMiddleware tracks IPs, sessions, and devices
- **Storage**: Device fingerprints stored and analyzed for patterns

### Security Features

#### IP Tracking & Analysis
- Automatic IP geolocation (manual trigger to save API calls)
- VPN/Proxy detection
- IP reputation checking
- Country-based risk assessment

#### Session Management
- Device-based session tracking
- Multi-device support with trust levels
- Session activity monitoring
- Automatic suspicious activity detection

#### Risk Assessment
- Transaction velocity monitoring
- Unusual pattern detection
- Cross-device activity analysis
- Behavioral analytics

### Security Models

```python
# IP Address Tracking
class IPAddress(SoftDeleteModel):
    ip_address = models.GenericIPAddressField(unique=True)
    country_code = models.CharField(max_length=2)
    is_vpn = models.BooleanField(default=False)
    is_blocked = models.BooleanField(default=False)
    risk_score = models.IntegerField(default=0)

# Device Fingerprinting
class DeviceFingerprint(SoftDeleteModel):
    fingerprint_hash = models.CharField(max_length=64)
    device_info = models.JSONField()
    first_seen = models.DateTimeField(auto_now_add=True)
    
# User Device Tracking
class UserDevice(SoftDeleteModel):
    user = models.ForeignKey(User)
    device_name = models.CharField(max_length=255)
    is_trusted = models.BooleanField(default=False)
    total_sessions = models.IntegerField(default=0)
```

### Admin Interface

The security app includes an enhanced admin interface for monitoring:
- Real-time IP tracking with geolocation
- Device fingerprint analysis
- User session monitoring
- Suspicious activity alerts
- Ban management system

### KYC Requirements (Disabled for MVP)

For the blockchain MVP, KYC requirements have been disabled to maintain the permissionless nature of crypto transactions. The check_kyc_required function always returns False, but the infrastructure remains in place for future compliance needs if required.

### Privacy Considerations

- Device fingerprints are hashed before storage
- No personally identifiable information in fingerprints
- Users can clear behavioral data (but not device ID)
- All security data follows soft-delete patterns

### Achievement & Rewards Fraud Prevention

The security system includes comprehensive fraud prevention for the achievements and rewards system:

#### Multi-Account Abuse Prevention
- **Device Fingerprint Tracking**: Links achievements to specific devices
- **Cross-Account Detection**: Identifies users creating multiple accounts from same device
- **Behavioral Analysis**: Detects suspicious patterns in achievement claiming
- **IP-Based Clustering**: Groups related accounts by IP patterns

#### Achievement Security Features

```python
# Achievement claim validation
class UserAchievement(SoftDeleteModel):
    user = models.ForeignKey(User)
    achievement_type = models.ForeignKey(AchievementType)
    device_fingerprint = models.ForeignKey(DeviceFingerprint)
    claim_ip = models.ForeignKey(IPAddress)
    
# Fraud detection signals
- Same device claiming "new user" achievements multiple times
- Rapid achievement claiming from single IP
- Pattern matching for bot-like behavior
- Referral chain analysis for circular referrals
```

#### Referral System Protection
- **Referral Loops**: Detects and prevents circular referral chains
- **Device Validation**: Ensures referrer and referee use different devices
- **Time-Based Analysis**: Flags suspiciously fast referral completions
- **Geographic Validation**: Checks for realistic geographic distribution

#### Automated Fraud Detection

The system automatically flags suspicious activity:

1. **Device Reuse**
   - Multiple "Pionero Beta" claims from same device
   - New user achievements on previously seen devices
   - Pattern: Device → Multiple Accounts → Multiple Rewards

2. **Velocity Checks**
   - Too many achievements in short timeframe
   - Inhuman speeds for completing tasks
   - Bulk account creation patterns

3. **Network Analysis**
   - Cluster detection for fraud rings
   - Social graph analysis for fake referral networks
   - IP subnet analysis for bot farms

#### Admin Tools for Fraud Investigation

```python
# Admin interface provides:
- Device fingerprint timeline view
- Achievement claim heat maps
- Suspicious pattern alerts
- Bulk action tools for fraud response
- Referral network visualization
```

#### Response to Detected Fraud

When fraud is detected, the system can:
- **Soft Block**: Prevent achievement claims without banning
- **Achievement Reversal**: Remove fraudulently obtained rewards
- **Network Ban**: Block entire clusters of related accounts
- **Smart Contract Integration**: On-chain blocking for severe cases

### Example Fraud Scenarios Prevented

1. **The Multi-Account Farmer**
   - User creates 50 accounts to claim "Pionero Beta" achievement
   - System detects: Same device fingerprint across accounts
   - Response: Only first account receives achievement

2. **The Referral Circle**
   - Users A→B→C→A create circular referral chain
   - System detects: Referral loop in network graph
   - Response: Referral rewards blocked for circular chains

3. **The Bot Farm**
   - Automated scripts create hundreds of accounts
   - System detects: Identical behavioral patterns, same IP subnet
   - Response: Entire IP range flagged, achievements blocked

4. **The Device Spoofer**
   - User attempts to fake device fingerprints
   - System detects: Inconsistent hardware info, behavioral anomalies
   - Response: Deep behavioral analysis triggers manual review

### Balancing Security and User Experience

The fraud prevention system is designed to be:
- **Invisible to legitimate users**: Real users never see security checks
- **Forgiving of edge cases**: Shared devices (families) handled gracefully
- **Scalable**: Automated detection reduces manual review needs
- **Privacy-preserving**: No personal data exposed in fraud detection

This comprehensive approach ensures that the achievement system rewards genuine community members while preventing abuse at scale.

## 🌍 Internationalization & Number Formatting

Confío provides a comprehensive number formatting system that automatically adapts to users' regional preferences based on their phone number country code. This ensures familiar number formatting for users across 50+ countries.

### Number Formatting System

The system is implemented in `apps/src/utils/numberFormatting.ts` and provides:

#### Country-Specific Formatting
- **Latin America**: Spanish/Portuguese formatting (1.234,56)
- **United States/UK**: English formatting (1,234.56)
- **Europe**: Mixed formatting based on country
- **Asia**: Country-specific formatting

#### Key Features
- 📱 **Automatic Detection**: Uses user's phone country code to determine formatting
- 🔢 **Consistent Display**: All numbers formatted consistently across the app
- 💱 **Currency Support**: Proper currency symbol placement and formatting
- 📊 **Percentage Formatting**: Locale-aware percentage display
- ⌨️ **Input Formatting**: Real-time formatting while typing in input fields

### Usage Examples

#### Basic Number Formatting
```typescript
import { useNumberFormat } from '../utils/numberFormatting';

const MyComponent = () => {
  const { formatNumber, formatCurrency } = useNumberFormat();
  
  // User from Colombia sees: 1.234,56
  // User from US sees: 1,234.56
  const formatted = formatNumber(1234.56);
  
  // Currency formatting
  // Colombia: COP 1.234,56
  // US: $1,234.56
  const price = formatCurrency(1234.56, 'COP');
};
```

#### Supported Countries
The system supports 50+ countries including:

**Latin America** - Two Different Number Format Systems:

> **Important Note**: Latin America doesn't have a unified number format. Countries influenced by Spanish colonialism typically use the European format (1.234,56), while countries with stronger US influence use the American format (1,234.56). This distinction is crucial for user experience - displaying numbers in the wrong format can confuse users and lead to serious financial errors.

**Spanish/European Format** (period for thousands, comma for decimals):
- 🇦🇷 Argentina: 1.234,56
- 🇧🇴 Bolivia: 1.234,56
- 🇨🇱 Chile: 1.234,56
- 🇨🇴 Colombia: 1.234,56
- 🇵🇾 Paraguay: 1.234,56
- 🇺🇾 Uruguay: 1.234,56
- 🇻🇪 Venezuela: 1.234,56
- 🇧🇷 Brazil: 1.234,56
- 🇪🇨 Ecuador: 1.234,56

**American/English Format** (comma for thousands, period for decimals):
- 🇩🇴 Dominican Republic: 1,234.56
- 🇸🇻 El Salvador: 1,234.56
- 🇬🇹 Guatemala: 1,234.56
- 🇭🇳 Honduras: 1,234.56
- 🇲🇽 Mexico: 1,234.56
- 🇳🇮 Nicaragua: 1,234.56
- 🇵🇦 Panama: 1,234.56
- 🇵🇪 Peru: 1,234.56

**Special Cases**:
- 🇨🇷 Costa Rica: 1 234,56 (space for thousands)
- 🇨🇺 Cuba: 1 234,56 (space for thousands)

**Other Regions**:
- 🇺🇸 United States: 1,234.56
- 🇬🇧 United Kingdom: 1,234.56
- 🇪🇸 Spain: 1.234,56
- 🇫🇷 France: 1 234,56
- 🇩🇪 Germany: 1.234,56
- 🇮🇳 India: 1,23,456.78 (Lakhs system)
- And 30+ more countries

### Implementation Details

#### React Hook
```typescript
const {
  formatNumber,       // Format plain numbers
  formatCurrency,     // Format with currency
  formatNumberForCountry,  // Format for specific country
  getDecimalSeparator,     // Get user's decimal separator
  getThousandsSeparator,   // Get user's thousands separator
  parseLocalizedNumber,    // Parse formatted string to number
  userCountryCode,         // User's detected country
  locale                   // User's locale string
} = useNumberFormat();
```

#### Input Field Formatting
```typescript
import { formatNumberInput } from '../utils/numberFormatting';

// Real-time formatting while user types
const handleAmountChange = (value: string) => {
  const { formatted, raw } = formatNumberInput(value, userCountryCode, {
    decimals: 2
  });
  setDisplayValue(formatted);  // What user sees
  setNumericValue(raw);        // Actual number for calculations
};
```

### Integration Status

The number formatting system is fully integrated in:
- ✅ **TradeChatScreen**: Trade amounts, rates, and percentages
- ✅ **ExchangeScreen**: Crypto/fiat amounts and exchange rates
- ✅ **SendToFriendScreen**: Send amounts
- ✅ **SendWithAddressScreen**: Send amounts
- ✅ **AccountDetailScreen**: Balance and exchange amounts

### Benefits

1. **User Comfort**: Users see numbers in their familiar format
2. **Reduced Errors**: Less confusion about decimal/thousand separators
3. **Professional Appearance**: Consistent, localized formatting
4. **Easy Maintenance**: Centralized formatting logic
5. **Scalability**: Easy to add new countries/locales

This internationalization system ensures that Confío feels native to users across Latin America and beyond, building trust through familiar number formatting.

## 🚀 Development Setup

### Quick Start Commands

The project includes convenient Makefile commands for common operations:

```bash
# Start development server with WebSocket support
make runserver

# Run database migrations
make migrate

# Setup database and user (PostgreSQL)
make db-setup

# Run Django shell
make shell

# Run tests
make test
```

### Prerequisites

1. **Python Virtual Environment**
   ```bash
   # Create virtual environment
   python -m venv myvenv
   
   # Activate virtual environment
   source myvenv/bin/activate  # On macOS/Linux
   # or
   myvenv\Scripts\activate     # On Windows
   ```

2. **Redis Server** (required for Django Channels)
   ```bash
   # macOS
   brew install redis
   brew services start redis
   
   # Ubuntu/Debian
   sudo apt-get install redis-server
   sudo systemctl start redis-server
   
   # Or use Docker
   docker run -d -p 6379:6379 redis:alpine
   ```

3. **PostgreSQL Database**
   ```bash
   # Create database and user
   make db-setup
   ```

### Web Application (React + Django + Channels)

1. **Install Dependencies**
   ```bash
   # Install Python dependencies (includes Django Channels, Redis, Daphne)
   myvenv/bin/pip install -r requirements.txt

   # Install Node.js dependencies
   cd web
   yarn install
   ```

2. **Build React App**
   ```bash
   cd web
   yarn build
   ```
   This will:
   - Build the React application
   - Automatically copy the new `index.html` to Django's templates directory
   - Generate static files with unique hashes for cache busting

3. **Run Database Migrations**
   ```bash
   myvenv/bin/python manage.py migrate
   ```

4. **Setup Unified Payment Method System**
   ```bash
   # Create and apply migrations for user and P2P models
   myvenv/bin/python manage.py makemigrations users p2p_exchange
   myvenv/bin/python manage.py migrate
   
   # Populate initial country and bank data
   myvenv/bin/python manage.py populate_bank_data
   
   # Populate P2P payment methods (banks + fintech solutions)
   myvenv/bin/python manage.py populate_payment_methods
   ```
   This will:
   - Create database tables for Country, Bank, and BankInfo models (now called PaymentMethod)
   - Create P2PPaymentMethod tables with provider types and requirements
   - Populate countries with specific ID requirements (Venezuela requires Cédula, Colombia doesn't)
   - Pre-load major banks for each supported LATAM country (83+ banks)
   - Add fintech solutions (Nequi, Yape, PayPal, Mercado Pago, etc.)
   - Create unified payment method system supporting both banks and fintech
   - Enable flexible recipient fields (phone for Nequi, email for PayPal, etc.)
   
   **Payment Method Breakdown:**
   - **Traditional Banks**: 83 (across Venezuela, Colombia, Argentina, Peru, Mexico, etc.)
   - **Fintech/Digital Wallets**: 13 (Nequi, PayPal, Yape, DaviPlata, Mercado Pago, etc.)
   - **Cash/Physical**: 2 (OXXO Pay, Efectivo)
   - **Total**: 107+ payment methods

5. **Run Django Channels Development Server**
   ```bash
   # Primary option: Django Channels with Daphne (supports WebSockets)
   make runserver
   
   # Alternative options:
   make runserver-wsgi    # Standard Django server (no WebSocket support)
   ```
   The server will:
   - Serve the React app at the root URL
   - Handle static files using Whitenoise
   - Provide GraphQL API endpoints
   - Support WebSocket connections for real-time P2P chat

6. **Development Workflow**
   - For React development: `yarn start` (runs on port 3000)
   - For Django development: `make runserver` (runs on port 8000 with WebSocket support)
   - After making React changes, run `yarn build` to update the Django-served version

### Mobile Application (React Native)

1. **Install Dependencies**
   ```bash
   cd apps
   yarn install
   ```

2. **iOS Setup**
   ```bash
   cd ios
   bundle install
   bundle exec pod install
   cd ..
   ```

3. **Run the App**
   ```bash
   # iOS
   yarn ios
   
   # Android
   yarn android
   ```

4. **Multi-Account Features**
   - Account creation and switching
   - Personal and business account support
   - Deterministic Sui address generation
   - Secure account storage using Keychain

5. **P2P Trading Features**
   - Create and browse trading offers
   - Real-time trade chat with WebSocket connection
   - Account-specific trade filtering
   - Local payment method integration

6. **AccountContext Architecture**
   - **Single source of truth** for account state across the entire app
   - **Eliminates state drift** from multiple hook instances
   - **Provides shared account context** to all components
   - **Enables dynamic tab switching** between personal/business modes
   - **Prevents UI blinks** during account switching and screen focus changes
   
   **Key Components:**
   - `AccountProvider`: Wraps the app and provides shared account state
   - `useAccount()`: Hook for accessing account data and operations
   - **Benefits**: Consistent state, better performance, smoother UX

### Static File Handling

The project uses a combination of Django and Whitenoise for static file serving:

1. **Development**
   - Django's development server serves static files
   - React development server (port 3000) serves files directly

2. **Production**
   - Whitenoise serves static files efficiently
   - Files are compressed and cached
   - No separate web server needed for static files

3. **Build Process**
   - React build generates hashed filenames for cache busting
   - `copy-index.js` script syncs the build with Django templates
   - Static files are collected into Django's static directory

### Known Patches

The project uses `patch-package` to maintain fixes for third-party dependencies. These patches are automatically applied after `yarn install` via the `postinstall` script.

#### Vision Camera Patch
- **File**: `apps/patches/react-native-vision-camera+4.6.4.patch`
- **Purpose**: Fixes CMake configuration for proper linking with react-native-worklets-core
- **Issue**: Vision Camera's CMake configuration needs to be updated to correctly link with the worklets library
- **Solution**: The patch updates the CMake configuration to use the correct build directory for the worklets library

⚠️ **Important**: The following files and directories should be added to `.gitignore` for security:

> - `.env` files (⚠️ **Critical Development Files**):
>   - Root `.env` (⚠️ **Location**: `/Confio/.env`): Django settings
>     - `PRODUCTION_HOSTS`: Comma-separated list of production hostnames
>     - `DEVELOPMENT_HOSTS`: Comma-separated list of development hostnames
>     - `DB_NAME`: PostgreSQL database name
>     - `DB_USER`: PostgreSQL database user
>     - `DB_PASSWORD`: PostgreSQL database password
>     - `DB_HOST`: PostgreSQL database host
>     - `DB_PORT`: PostgreSQL database port
>     - `REDIS_URL`: Redis connection URL (e.g., 'redis://localhost:6379/0')
>     - `SECRET_KEY`: Django secret key for cryptographic signing (e.g., '***REMOVED***')
>     - `PYTHONPATH`: Python path for Django
>     - `DJANGO_SETTINGS_MODULE`: Django settings module path
>   - `apps/.env` (⚠️ **Location**: `/Confio/apps/.env`): React Native app settings
>     - `GOOGLE_WEB_CLIENT_ID`: Google OAuth client ID for web platform
>     - `GOOGLE_IOS_CLIENT_ID`: Google OAuth client ID for iOS platform
>     - `GOOGLE_ANDROID_CLIENT_ID`: Google OAuth client ID for Android platform
>     - `API_URL`: Production backend API URL
>     - `API_URL_DEV`: Development backend API URL
>   - `apps/android/.env` (⚠️ **Location**: `/Confio/apps/android/.env`): Android-specific settings
>     - `KEYSTORE_FILE`: Path to Android keystore file
>     - `KEYSTORE_PASSWORD`: Keystore password
>     - `KEY_ALIAS`: Key alias
>     - `KEY_PASSWORD`: Key password
>   - `apps/ios/.env` (⚠️ **Location**: `/Confio/apps/ios/.env`): iOS-specific settings
>     - (No environment variables currently defined)
> - Firebase Configuration Files (⚠️ **Critical Development Files**):
>   - `google-services.json` (⚠️ **Location**: `/Confio/apps/android/app/google-services.json`): Android Firebase config
>   - `GoogleService-Info.plist` (⚠️ **Location**: `/Confio/apps/ios/Confio/GoogleService-Info.plist`): iOS Firebase config
>   - `firebase-service-account.json` (⚠️ **Location**: `/Confio/config/firebase-service-account.json`): Firebase Admin SDK service account key
>     - Required for server-side Firebase operations (e.g., token verification)
>     - Download from Firebase Console > Project Settings > Service Accounts > Generate New Private Key
> - `confio.tar.gz` (deployment archive)
> - `apps/android/gradle.properties` (contains keystore and signing configurations)
> - Any other files containing sensitive information or credentials

> **Note**: Google OAuth Client IDs are configured in `apps/.env` and accessed through `apps/src/config/env.ts` using `react-native-dotenv`.

## 📜 Smart Contracts

### Confío Dollar ($cUSD)
- **File**: `contracts/cusd/sources/cusd.move`
- **Purpose**: Implementation of the $cUSD stablecoin, a gasless stablecoin designed for everyday transactions in Latin America
- **Key Features**:
  - 6 decimal places precision for micro-transactions
  - USD-pegged stablecoin backed 1:1 by USDC reserves
  - Admin controls for minting, freezing addresses, and pausing system
  - Two-step burn process requiring user confirmation
  - Vault registry for managing multiple reserve addresses
- **Security Features**:
  - Freeze registry to block malicious addresses
  - System pause/unpause for emergency situations
  - Event emission for all critical operations
  - Admin-only functions protected by capability objects

### Confío ($CONFIO)
- **File**: `contracts/confio/sources/confio.move`
- **Purpose**: Governance and utility token for the Confío platform
- **Key Features**:
  - Fixed supply of 1 billion tokens
  - 9 decimal places precision
  - UTF-8 support for Spanish characters (ñ, í)
  - Custom icon URL for wallet display
- **Distribution**:
  - Initial supply minted to contract deployer
  - Treasury cap frozen preventing future minting
  - No burn functionality to maintain fixed supply

### Confío Pay
- **File**: `contracts/pay/sources/pay.move`
- **Purpose**: Payment processing system with automatic fee collection
- **Key Features**:
  - Automatic 0.9% fee deduction on all payments
  - Support for both cUSD and CONFIO tokens
  - Permissionless payments - no registration required
  - Django integration via payment_id tracking
  - Real-time fee collection in shared FeeCollector
- **Fee Distribution**:
  - 0.9% automatically collected as platform fee
  - 99.1% sent directly to recipient
  - Fees accumulate in contract until admin withdrawal
- **Perfect for Latin America**:
  - No barriers for informal economy businesses
  - Any address can receive payments instantly
  - Business validation handled off-chain in Django

### Invite Send
- **File**: `contracts/invite_send/sources/invite_send.move`
- **Purpose**: Send funds to non-Confío users with phone number verification
- **Key Features**:
  - Send cUSD or CONFIO to users who haven't signed up yet
  - 7-day reclaim period if funds remain unclaimed
  - Phone numbers never stored on blockchain (privacy protection)
  - Admin-controlled claims after Django verifies phone match
  - Unique invitation IDs generated by Django (e.g., UUIDs)
- **Security Flow**:
  1. Sender creates invitation with funds and Django-generated ID
  2. Django stores phone number + invitation ID mapping in database
  3. New user signs up with phone number → gets zkLogin Sui address
  4. Django verifies phone match → calls admin claim function
  5. Funds automatically transfer to new user's address
- **Reclaim Feature**:
  - After 7 days, sender can reclaim unclaimed funds
  - Prevents permanent loss of funds if recipient never signs up
  - One-click reclaim by original sender only

### P2P Trade
- **File**: `contracts/p2p_trade/sources/p2p_trade.move`
- **Purpose**: Secure escrow-based peer-to-peer trading system for crypto-to-fiat exchanges
- **Key Features**:
  - Escrow protection: Crypto funds locked until fiat payment confirmed
  - 15-minute trade window with automatic expiry (900 seconds)
  - Self-trading prevention (ESelfTrade error)
  - Admin-mediated dispute resolution system
  - Support for both cUSD and CONFIO tokens
  - Privacy-preserving: No personal information on-chain
- **Trade Flow**:
  1. Seller creates trade offer with crypto amount and fiat details
  2. Buyer accepts trade within 15-minute window
  3. Buyer sends fiat payment off-chain (bank transfer, mobile money, etc.)
  4. Seller confirms receipt, releasing crypto to buyer
  5. Either party can open dispute if issues arise
- **Security Features**:
  - Separate escrow vaults for each token type
  - Atomic fund transfers only on valid state transitions
  - Authorization checks on all critical operations
  - Trade statistics tracking for platform monitoring
- **Perfect for Latin America**:
  - Supports country-specific payment methods
  - No KYC required on-chain (handled by Django)
  - Designed for informal economy participants
  - Dispute resolution for building trust

### Gasless Transactions
- **Implementation**: Handled off-chain through Sui's native sponsored transaction system
- **Components**:
  - App server maintains SUI balance for gas sponsorship
  - Client SDK integrates with Sui's sponsored transaction API
  - Rate limiting and gas budget controls implemented at the application level
- **Benefits**:
  - Zero gas fees for end users
  - Native Sui protocol support
  - Simplified implementation without additional smart contracts

### Smart Contract Security & Permissions

For detailed information about smart contract permissions and multi-signature setup:

- **📋 [contracts/PERMISSIONS.md](contracts/PERMISSIONS.md)** - Comprehensive guide covering:
  - All admin capabilities and their risk levels
  - Multi-signature wallet recommendations
  - Time-lock suggestions for critical operations
  - Migration checklist for production deployment
  - Security best practices

- **📖 [contracts/README.md](contracts/README.md)** - Overview of all smart contracts

**Key Security Features:**
- Critical operations (minting, freezing) require admin capabilities
- Fixed supply for CONFIO token (no inflation risk)
- Escrow protection for P2P trades
- Time-based expiration for invitations and trades
- No personal data stored on-chain

### Country Code Management

The project maintains country code mappings in two locations:

1. **Client-side** (`apps/src/utils/countries.ts`):
   - Format: `[country_name, country_code, iso_code, flag]`
   - Used by the React Native app for phone number input
   - Includes flag emojis for UI display
   - Helper functions:
     - `getCountryByIso(iso)`: Get country by ISO code
     - `getCountryByPhoneCode(code)`: Get country by phone code

2. **Server-side** (`users/country_codes.py`):
   - Format: `[country_name, country_code, iso_code]`
   - Used by Django backend for phone number validation
   - Used in Telegram verification process
   - Ensures consistent country code handling across the application

Both files maintain the same list of countries and codes, with the client version including additional UI elements (flags) and the server version focusing on validation and formatting.

## 🚀 Deployment Guide

This section covers the essential steps for setting up Confío in production or development environments.

### Database Setup & Migrations

#### Initial Setup
```bash
# 1. Create Python virtual environment
python -m venv myvenv
source myvenv/bin/activate  # On Windows: myvenv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Setup PostgreSQL database
# Create database and user (adjust credentials as needed)
createdb confio_db
createuser confio_user --createdb

# 4. Configure environment variables in .env file
DB_NAME=confio_db
DB_USER=confio_user
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
REDIS_URL=redis://localhost:6379/0
```

#### Core System Migrations
```bash
# Apply all initial migrations
python manage.py migrate

# Create admin user (optional)
python manage.py createsuperuser
```

### Unified Payment Method System Setup

**⚠️ Critical Step**: The unified payment method system requires specific migration order and data population.

#### Step 1: Run Migrations
```bash
# Create migrations for both apps
python manage.py makemigrations users p2p_exchange

# Apply migrations
python manage.py migrate
```

#### Step 2: Populate Base Data
```bash
# Populate countries and banks (83+ banks across LATAM)
python manage.py populate_bank_data

# Populate unified P2P payment methods
python manage.py populate_payment_methods
```

#### Step 3: Verify Installation
```bash
# Check payment method counts
python manage.py shell -c "
from p2p_exchange.models import P2PPaymentMethod
print(f'Total payment methods: {P2PPaymentMethod.objects.count()}')
print(f'Banks: {P2PPaymentMethod.objects.filter(provider_type="bank").count()}')
print(f'Fintech: {P2PPaymentMethod.objects.filter(provider_type="fintech").count()}')
"
```

Expected output:
```
Total payment methods: 107
Banks: 83
Fintech: 13
```

### Payment Method System Architecture

The unified system provides:

**🏦 Traditional Banks (83+ supported)**
- Country-specific banks across Venezuela, Colombia, Argentina, Peru, Mexico, Chile, Bolivia, Ecuador
- Bank-specific account types (checking, savings, payroll)
- Country-specific ID requirements (Cédula in Venezuela, optional in Colombia)

**📱 Fintech Solutions (13+ supported)**
- **Mobile Wallets**: Nequi (CO), Yape (PE), DaviPlata (CO), Plin (PE)
- **Global Platforms**: PayPal, Wise (TransferWise)
- **Regional Solutions**: Mercado Pago (AR), Ualá (AR), Zelle (US)
- **Cash Options**: OXXO Pay (MX), Efectivo (Global)

**🔧 Dynamic Field Requirements**
- Phone numbers for mobile wallets (Nequi, Yape)
- Email addresses for global platforms (PayPal, Wise)
- Account numbers for traditional banks
- Usernames for some fintech platforms
- Country-specific validation (ID requirements)

### Frontend Integration

The React Native app automatically supports the unified payment method system:

```typescript
// GraphQL query now includes all payment method types
const { data } = useQuery(GET_P2P_PAYMENT_METHODS, {
  variables: { countryCode: selectedCountry }
});

// Dynamic form fields based on payment method requirements
if (paymentMethod.requiresPhone) {
  // Show phone number field
}
if (paymentMethod.requiresEmail) {
  // Show email field
}
if (paymentMethod.providerType === 'bank') {
  // Show bank-specific fields (account type, ID number)
}
```

### Troubleshooting

#### Missing Database Columns Error
If you see `column p2p_exchange_p2ppaymentmethod.provider_type does not exist`:

```bash
# Check migration status
python manage.py showmigrations p2p_exchange users

# If migrations are missing, create them
python manage.py makemigrations p2p_exchange
python manage.py migrate

# Re-populate payment methods
python manage.py populate_payment_methods --update-existing
```

#### Empty Payment Methods
If GraphQL returns empty payment method lists:

```bash
# Verify data population
python manage.py shell -c "from p2p_exchange.models import P2PPaymentMethod; print(P2PPaymentMethod.objects.count())"

# If count is 0, run population command
python manage.py populate_payment_methods
```

#### GraphQL Schema Errors
If you see field errors like `Cannot query field 'providerType'`:

1. Ensure Django server is restarted after schema changes
2. Check that all migrations are applied
3. Verify P2PPaymentMethod model has all required fields

### Production Considerations

1. **Database Performance**: Consider indexing frequently queried fields:
   ```sql
   CREATE INDEX idx_payment_method_country_active ON p2p_exchange_p2ppaymentmethod(country_code, is_active);
   CREATE INDEX idx_payment_method_provider_type ON p2p_exchange_p2ppaymentmethod(provider_type);
   ```

2. **Security**: Ensure sensitive bank information is properly protected:
   - Use HTTPS for all API endpoints
   - Implement proper access controls for bank info
   - Consider encryption for stored payment details

3. **Monitoring**: Track payment method usage and success rates:
   - Monitor which payment methods are most popular
   - Track conversion rates by payment method type
   - Alert on payment method failures

## 🔧 Common Development Issues & Solutions

### Virtual Environment Issues

**Problem**: `python: command not found` or using wrong Python version
```bash
# Solution: Always use virtual environment
source myvenv/bin/activate  # Activate first
# OR use full path
myvenv/bin/python manage.py runserver
```

**Problem**: `ModuleNotFoundError` when running Django commands
```bash
# Solution: Install dependencies in virtual environment
myvenv/bin/pip install -r requirements.txt
```

### JWT Context Errors

**Problem**: "Active account not found" error
```python
# Wrong: Looking up by user's direct accounts
account = user.accounts.filter(account_type='business').first()

# Correct: Look up through JWT context
jwt_context = get_jwt_business_context_with_validation(info)
account = Account.objects.filter(
    business_id=jwt_context['business_id'],
    account_index=jwt_context['account_index']
).first()
```

**Problem**: Business accounts showing same data
```python
# Wrong: Using account.business.id
business_id = account.business.id

# Correct: Using JWT business_id
jwt_context = get_jwt_business_context_with_validation(info)
business_id = jwt_context['business_id']
```

### GraphQL Field Type Errors

**Problem**: "Field must not have a selection since type 'JSONString' has no subfields"
```python
# Wrong: Using JSONString for complex fields
employee_permissions = graphene.JSONString()

# Correct: Create proper GraphQL object type
class EmployeePermissionsType(graphene.ObjectType):
    viewBalance = graphene.Boolean()
    sendFunds = graphene.Boolean()
    # ... other fields

employee_permissions = graphene.Field(EmployeePermissionsType)
```

### Permission Validation

**Problem**: Mutations not checking permissions
```python
# Wrong: Direct business access
def mutate(self, info, business_id):
    business = Business.objects.get(id=business_id)
    # ... perform operation

# Correct: Validate through JWT context
def mutate(self, info):
    jwt_context = get_jwt_business_context_with_validation(
        info, 
        required_permission='manage_employees'
    )
    if not jwt_context:
        raise GraphQLError("Permission denied")
    business = Business.objects.get(id=jwt_context['business_id'])
```

## 📱 App Verification: `.well-known` Directory & nginx Configuration

To enable iOS and Android app verification (for deep linking and app association), you must:

1. **Copy the `.well-known` directory**
   - The directory `web/.well-known/` contains:
     - `apple-app-site-association` (for iOS Universal Links)
     - `assetlinks.json` (for Android App Links)
   - Copy this directory to the web root served by nginx. If deploying, ensure it is present at the top-level of your public/static files (e.g., `/var/www/html/.well-known/` or your Django static root if using Whitenoise).

2. **nginx Configuration**
   - Add the following block to your `nginx.conf` to serve `.well-known` files with the correct content type:

```nginx
location ^~ /.well-known/ {
    alias /path/to/your/project/web/.well-known/;
    default_type application/json;
    add_header Access-Control-Allow-Origin *;
    try_files $uri =404;
}
```
- Replace `/path/to/your/project/web/.well-known/` with the absolute path to your `.well-known` directory.
- If you use Whitenoise or Django static files, ensure `.well-known` is included in your static collection and not ignored by `.gitignore` or static file settings.

3. **Reload nginx**
   - After updating the config, reload nginx:
     ```bash
     sudo nginx -s reload
     ```

4. **Verify**
   - Visit `https://yourdomain.com/.well-known/apple-app-site-association` and `https://yourdomain.com/.well-known/assetlinks.json` in your browser. You should see the raw JSON, not an HTML error page.

**Note:**
- The `default_type application/json;` ensures the correct content-type for verification files.
- If you use a different static file server, adapt the config accordingly.

## 🏆 Achievements (Logros) System

The Confío app includes a simplified achievement system focused on core user behaviors that drive retention and organic growth.

### MVP Achievements (5 Core Behaviors)

| Achievement | Description | Reward | Icon | Trigger |
|-------------|-------------|---------|------|---------|
| **Pionero Beta** | Únete durante la fase beta | 1 CONFIO | 🚀 | Account creation during beta |
| **Conexión Exitosa** | Te uniste por invitación y completaste tu primera transacción | 4 CONFIO | 🎯 | Enter referrer + first transaction (INVITED user) |
| **Primera Compra P2P** | Completa tu primera compra/venta P2P | 8 CONFIO | 🔄 | First P2P trade completion |
| **Hodler** | Mantén saldo por 30 días | 12 CONFIO | 💎 | Hold balance for 30 consecutive days |
| **10 Intercambios** | Completa 10 transacciones P2P | 20 CONFIO | 📈 | Complete 10 P2P trades |
| **Referido Exitoso** | Invitaste a alguien que completó su primera transacción | 4 CONFIO | 🤝 | Someone you invited completes first transaction (INVITER) |

### Unified Referral System

The referral system supports three types of referrals in a single flow:
1. **Influencer** - TikTok @username
2. **Friend Username** - Confío @username  
3. **Friend Phone** - Phone number with country code

**How it works:**
- New users have 48 hours after signup to enter a referrer
- Both parties receive rewards only after the referred user completes their first transaction
- Clear distinction: "Conexión Exitosa" for invited users, "Referido Exitoso" for inviters

### CONFIO Token Economics

- **Internal rewards token** - Locked until presale/launch to ensure value appreciation
- **Simplified Achievement System**: 6 core achievements focused on user adoption

### Core Achievements (Logros)

1. **Pionero Beta** (1 CONFIO)
   - First 10,000 users only
   - Exclusive future benefits (mystery rewards)
   - Automatic on signup

2. **Primera Transacción** (4 CONFIO)
   - Complete first transaction (send or receive)
   - Core onboarding metric

3. **Conexión con Amigos** (3 CONFIO)
   - Add 3 friends to contacts
   - Network growth incentive

4. **10 Intercambios** (20 CONFIO)
   - Complete 10 P2P trades
   - Highest reward for core app usage

5. **Influencer Destacado** (Variable 10-250 CONFIO)
   - Share app on TikTok
   - Rewards scale with video views (10K views = 10 CONFIO, up to 1M+ = 250 CONFIO)

6. **Hodler 30 días** (12 CONFIO)
   - Maintain balance for 30 days
   - Retention incentive

### Unified Referral System
- Single referral input for any identifier (username, code, phone)
- 48-hour window after signup to set referrer
- Both parties receive rewards on first transaction
- Prevents gaming through one-time-only referral setting

### Implementation Architecture

#### Backend Components
- **Models** (`users/models.py`):
  - `AchievementType`: Defines available achievements
  - `UserAchievement`: Tracks user progress and claims
  - `InfluencerReferral`: Manages TikTok referral tracking
  - `TikTokViralShare`: Tracks viral content performance

#### GraphQL API
```graphql
# Queries
achievementTypes
userAchievements

# Mutations
claimAchievementReward(achievementId: ID!)
setReferrer(referrerIdentifier: String!)
checkReferralStatus
```

#### Frontend Components
- **AchievementsScreen** (`apps/src/screens/AchievementsScreen.tsx`):
  - Displays achievement progress
  - Shows referral box only during 48-hour window
  - Claim rewards functionality
  - Share achievements to social media

- **ReferralInputModal** (`apps/src/components/ReferralInputModal.tsx`):
  - Unified referral input for influencer/friend/phone
  - Country code picker for phone numbers
  - Real-time validation and error messages
  - Auto-detection of referral type

### Anti-Abuse Measures

1. **Phone Verification Required**: Must complete phone verification to claim rewards
2. **Dual Username System**: Both influencer and user TikTok usernames required
3. **Transaction Requirements**: Referral rewards only paid after real transactions
4. **Rate Limiting**: Prevents spam submissions
5. **Manual Review**: High-value achievements flagged for review

### Management Commands

```bash
# Create/update achievement types
python manage.py create_achievement_types

# Clean up duplicate achievements
python manage.py cleanup_achievements

# Reorder achievements by reward value
python manage.py reorder_achievements
```

### Visual Design

- **Achievement Cards**: Clean design with emoji icons, progress bars, and CONFIO rewards
- **Unified Color Scheme**: Teal/mint (#34d399) as primary achievement color
- **Referral Modal**: 
  - Three input types: Influencer, @Username, Phone
  - Country code picker with 244 countries
  - Real-time validation feedback
- **Orange Referral Box**: Prominent call-to-action during 48-hour window

### Key Simplifications from Original Design

1. **Reduced from 30+ to 6 achievements** - Focus on core behaviors only
2. **Removed viral/UGC achievements** - Official content strategy instead
3. **Unified referral flow** - Single entry point for all referral types
4. **Clear achievement distinction** - "Conexión Exitosa" vs "Referido Exitoso"
5. **No monetary values shown** - CONFIO displayed as points, not dollars

## 🚀 CONFIO Token Presale System

Confío includes a comprehensive presale system for the CONFIO utility token, designed with transparency and community participation in mind.

### Token Distribution

- **95% Founder & Team**: Majority control like any successful startup
- **5% Community Presale**: Opportunity for early supporters, not VCs

### Presale Phases

| Phase | Name | Price | Goal | Target | Status |
|-------|------|-------|------|--------|--------|
| **Phase 1** | Raíces Fuertes | 0.25 cUSD | $1M | 🇻🇪🇦🇷🇧🇴 Community base | Active/Coming Soon |
| **Phase 2** | Expansión Regional | 0.50 cUSD | $10M | 🌎 New markets | Upcoming |
| **Phase 3** | Alcance Continental | 1.00 cUSD | TBD | 🌍 Global investors | Future |

### Key Features

1. **Global On/Off Switch**: Master control to enable/disable all presale features
2. **Phase Management**: Activate phases independently with different pricing
3. **Purchase Limits**: Min/max purchase amounts per transaction and per user
4. **Real-time Tracking**: Dashboard shows progress, participants, and funds raised
5. **Token Locking**: All purchased tokens remain locked until mass adoption

### Technical Implementation

#### Django Models (`presale/models.py`)
- **PresaleSettings**: Singleton model for global presale control
- **PresalePhase**: Individual presale phases with pricing and limits
- **PresalePurchase**: Transaction records for token purchases
- **PresaleStats**: Aggregated statistics per phase
- **UserPresaleLimit**: Per-user purchase tracking for limits

#### GraphQL Integration
```graphql
# Check if presale is active (no auth required)
query GetPresaleStatus {
  isPresaleActive
}

# Get active presale phase
query GetActivePresale {
  activePresalePhase {
    phaseNumber
    pricePerToken
    minPurchase
    maxPurchase
    totalRaised
    progressPercentage
  }
}

# Purchase tokens
mutation PurchasePresaleTokens($cusdAmount: String!) {
  purchasePresaleTokens(cusdAmount: $cusdAmount) {
    success
    purchase {
      confioAmount
      transactionHash
    }
  }
}
```

#### UI Components
- **ConfioPresaleScreen**: Main presale information and phases
- **ConfioTokenomicsScreen**: Transparent token distribution explanation
- **ConfioPresaleParticipateScreen**: Token purchase interface
- **Conditional Banners**: Show only when `isPresaleActive === true`

### Admin Management

1. **Enable/Disable Presale**:
   - Navigate to Admin → Presale Settings
   - Toggle "Is presale active" checkbox
   - Save to enable/disable all presale features

2. **Manage Phases**:
   - Admin → Presale Phases
   - Set status: coming_soon, active, completed, paused
   - Configure pricing, limits, and goals

3. **Monitor Progress**:
   - Real-time dashboard in admin panel
   - View purchases, participants, and funds raised
   - Export data for analysis

### Setup Commands

```bash
# Initial presale setup
python manage.py setup_presale

# Update presale data
python manage.py update_presale_data

# Update descriptions
python manage.py update_presale_descriptions
```

### Security & Compliance

1. **Server-side Validation**: All purchase limits enforced on backend
2. **JWT-based Access**: User identity verified through JWT tokens
3. **No Price Predictions**: Avoiding legal issues with growth promises
4. **Clear Lock Terms**: Tokens locked "until mass adoption" (no specific date)
5. **Risk Disclosure**: Clear warnings about investment risks

### User Experience

- **Accessible Language**: Avoiding crypto jargon ("monedas" not "tokens")
- **Country-aware Formatting**: Numbers formatted based on user's country
- **Mobile-first Design**: Optimized for React Native app
- **Progress Visualization**: Real-time progress bars and participant counts
- **Social Proof**: Show number of participants and community growth

## 📱 Social Financial Marketing Strategy: "Sigue al fundador"

### Overview

The "Sigue al fundador" (Follow the founder) section transforms Confío from a simple financial app into a social financial platform by leveraging founder Julian Moon's personal brand (@julianmoonluna) with 240K+ TikTok followers.

### Key Components

#### 1. **Strategic Placement**
- Located in Profile tab between Community and Legal sections
- Features prominent social media buttons (TikTok, Instagram, YouTube)
- Includes emotional tagline: "Un coreano que sueña con una nueva Latinoamérica"

#### 2. **Viral Growth Loop**
```
TikTok (@julianmoonluna) → Confío App → Share Achievements → TikTok
```

#### 3. **Milestone-Based Sharing**

**Registration:**
```
#RetoConfio #MiPrimerConfioDollar #NuevoEnConfio
"¡Me uní a Confío! Mi primer paso hacia un dólar seguro 💪"
```

**First P2P Trade:**
```
#RetoConfio #PrimerDolarSeguro #ConfioP2P
"¡Conseguí mi primer cUSD en Confío! 🔥 #DolarAntiInflacion"
```

**First Send:**
```
#RetoConfio #EnviandoConConfio #DolarSeguro
"Enviando dinero fácil y seguro con Confío ✈️"
```

### Technical Implementation

#### Share Functionality (React Native)
```javascript
const shareMilestone = async (milestone: string) => {
  const hashtags = getHashtagsByRegion(userRegion);
  const message = getMilestoneMessage(milestone);
  
  await Share.share({
    message: `${message}\n\n${hashtags}`,
    url: videoTemplateUrl, // Pre-made template video
  });
};
```

#### Region-Based Hashtags
```javascript
const getHashtagsByRegion = (region: string) => {
  const baseTag = region === 'LATAM' ? '#RetoConfio' : '#ConfioChallenge';
  // ... milestone-specific tags
};
```

### Marketing Benefits

1. **Trust Building**: Personal founder story increases app credibility
2. **Organic Growth**: Users become voluntary brand ambassadors
3. **Cultural Connection**: "Korean dreaming of new Latin America" narrative
4. **Viral Potential**: Achievement sharing creates social proof
5. **Community Building**: Links app users with founder's social following

### Success Metrics

- Achievement share rate
- Social media referral traffic
- Hashtag reach and engagement
- User retention after social sharing
- Viral coefficient (K-factor)

### Future Enhancements

1. **Rewards System**: Offer fee discounts for social sharing
2. **Leaderboards**: Regional achievement rankings
3. **Special Badges**: Exclusive achievements for social sharers
4. **Creator Fund**: Revenue sharing for viral content creators
5. **Live Events**: TikTok lives with app feature launches

### Cultural Adaptation

The strategy adapts to regional preferences:
- **Spanish-speaking LATAM**: Uses "Reto" (challenge) which resonates with all age groups
- **English-speaking regions**: Uses "Challenge" for broader appeal
- **Visual Content**: TikTok-first approach aligns with LATAM's video consumption habits

This social financial approach positions Confío not just as a utility app but as a movement for financial inclusion in Latin America, with Julian's personal story as the emotional anchor.

## 🔐 Security Architecture: KYC/AML Decorators

### Summary of Changes

I've successfully refactored all financial transactions to use decorators for KYC and AML checks:

### 1. Created GraphQL Decorators:

- `@graphql_require_aml()` - Blocks sanctioned/banned users
- `@graphql_require_kyc(operation_type)` - Checks KYC limits (currently always passes for MVP)

### 2. Applied Decorators to All Financial Mutations:

**Send Transactions:**
```python
@graphql_require_aml()
@graphql_require_kyc('send_money')
def mutate(cls, root, info, input):
```

**P2P Trading:**
```python
@graphql_require_aml()
@graphql_require_kyc('p2p_trade')
def mutate(cls, root, info, input):
```

**Payments:**
```python
@graphql_require_aml()
@graphql_require_kyc('accept_payments')  # For CreateInvoice
@graphql_require_kyc('send_money')      # For PayInvoice
```

### 3. Benefits:

- **Clean Architecture** - Security checks happen before any database operations
- **No DB Engagement** - Failed security checks exit early without touching the database
- **Reusable Pattern** - Same decorators can be used for any new financial mutations
- **Simple AML** - Only blocks sanctioned/banned users (no complex amount calculations)
- **Future-Ready KYC** - Structure in place for when you need to implement KYC levels

### 4. How It Works:

1. User makes request
2. `@graphql_require_aml()` checks if user is banned/sanctioned
3. `@graphql_require_kyc()` checks transaction limits (currently always passes)
4. Only if both pass does the mutation code execute
5. No database queries until all checks pass

The system is now much cleaner and follows proper separation of concerns!

## 📱 Push Notifications with Firebase Cloud Messaging

### Overview

Confío uses Firebase Cloud Messaging (FCM) for push notifications, with an efficient batch-sending architecture that minimizes server load and properly handles invalid tokens.

### Key Features

1. **Batch Sending by Default**: All notifications use FCM's multicast API, even single messages
2. **Automatic Token Management**: Invalid tokens are immediately deactivated based on FCM error codes
3. **User Preferences**: Granular control over notification categories
4. **Deep Linking**: Notifications can navigate users to specific screens
5. **Background Handling**: Messages processed even when app is closed

### Backend Configuration

Firebase Admin SDK is already initialized in `config/settings.py` using the service account file at:
```
config/firebase-service-account.json
```

### Architecture

#### Token Management
- FCM tokens stored in `FCMDeviceToken` model with failure tracking
- Tokens automatically deactivated after 5 consecutive failures
- Invalid tokens immediately removed based on FCM error responses:
  - `UnregisteredError` - Device no longer registered
  - `SenderIdMismatchError` - Token belongs to different app
  - `invalid-registration-token` - Invalid token format

#### Batch Processing
```python
# All messages sent via send_batch_notifications()
# Automatically splits into chunks of 500 (FCM limit)
# Handles individual response errors per token
```

### Management Commands

```bash
# Test push notifications
python manage.py test_fcm_batch --user-email user@example.com

# Clean up invalid/stale tokens
python manage.py cleanup_fcm_tokens --days-inactive 90

# View cleanup options
python manage.py cleanup_fcm_tokens --help
```

### Mobile App Integration

The React Native app includes:
- Automatic token registration on app launch
- Secure token storage using react-native-keychain
- Background message handling with Notifee
- Deep link navigation from notifications
- Settings screen for notification preferences

### Notification Categories

Users can control notifications by category:
- **Transactions**: Payments sent/received, conversions
- **P2P Trading**: Trade updates, offers, disputes
- **Security**: Login alerts, security notifications
- **Promotions**: Special offers and rewards
- **Announcements**: Platform updates and news
