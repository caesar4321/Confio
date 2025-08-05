# Confío: LATAM's Open Wallet for the Dollar Economy

**Confío** is an open-source Web3 wallet and transaction platform designed for Latin America.  
It enables users to **send, receive, and hold stablecoins** (like USDC or cUSD) on the **Aptos blockchain**, with zero gas fees and no crypto complexity.

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
- 🪙 Interact directly with Aptos-based smart contracts
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
| Blockchain      | [Aptos](https://aptosfoundation.org) |
| Smart Contracts | Move language                 |
| Backend API     | Django + GraphQL              |
| Real-time       | Django Channels + WebSocket   |
| Cache/Sessions  | Redis                         |
| Database        | PostgreSQL                    |
| ASGI Server     | Daphne                        |
| CI/CD           | Cloudflare Pages              |
| Link Shortener  | Cloudflare Workers + KV       |

## 🔒 What Confío Is Not

- ❌ Not a custodial wallet — we never store user funds or signing keys
- ❌ No backend "tricks" — money logic lives entirely on-chain
- ❌ No crypto knowledge required — users sign in with Google or Apple
- ❌ No server-side keyless proofs — all signing happens on the client

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

├── blockchain/        # Aptos blockchain integration
│   ├── models.py      # Blockchain event and balance models
│   ├── aptos_balance_service.py # Hybrid balance caching system
│   ├── aptos_sponsor_service.py # Gas sponsorship service
│   ├── aptos_transaction_manager.py # Transaction management with Aptos SDK
│   ├── aptos_keyless_service.py # Keyless authentication service
│   ├── tasks.py       # Celery tasks for blockchain polling
│   ├── management/    # Management commands (poll_blockchain, test_aptos_connection)
│   ├── migrations/    # Database migrations
│   └── README.md      # Blockchain integration documentation

├── payments/          # Payment processing system
│   ├── models.py      # Payment transaction models
│   ├── schema.py      # Payment GraphQL schema
│   └── management/    # Payment management commands

├── send/              # Send transaction system (two-phase flow)
│   ├── models.py      # Send transaction models
│   ├── schema.py      # Send GraphQL schema with prepare/execute mutations
│   └── validators.py  # Transaction validation

├── security/          # Security and fraud prevention system
│   ├── models.py      # Security models (IPAddress, UserSession, DeviceFingerprint, etc.)
│   ├── middleware.py  # Security middleware for tracking IPs and sessions
│   ├── utils.py       # Security utilities (device fingerprinting, risk assessment)
│   ├── admin.py       # Enhanced admin interface for security monitoring
│   └── migrations/    # Database migrations for security models

├── prover/            # Keyless authentication initialization and coordination
│   ├── models.py      # Empty - keyless proofs remain client-side
│   ├── schema.py      # GraphQL schema for keyless initialization
│   ├── admin.py       # Empty - no server-side proof storage
│   └── migrations/    # Database migrations

├── prover-service/    # Standalone service for proof generation and verification
│   ├── index.js      # Main entry point for the prover service
│   ├── prover.js     # Core proof generation and verification logic
│   ├── utils.js      # Utility functions for proof operations
│   ├── tests/        # Test cases for the prover service
│   └── package.json  # Node.js dependencies and scripts
│       ├── Dependencies:
│       │   ├── @aptos-labs/ts-sdk: Aptos SDK functionality
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
│   │   │   ├── authService.ts    # Authentication service with keyless signing
│   │   │   ├── enhancedAuthService.ts # Enhanced auth with device fingerprinting
│   │   │   └── ...        # Other services
│   │   ├── types/         # TypeScript type definitions
│   │   ├── utils/         # Utility functions
│   │   │   ├── accountManager.ts # Multi-account storage and management
│   │   │   ├── countries.ts  # Country codes mapping [name, code, iso, flag]
│   │   │   ├── aptosKeyless.ts   # Keyless authentication utilities with multi-account pepper generation
│   │   │   └── ...        # Other utility functions
│   │   └── ...            # Other source files
│   ├── scripts/           # Build and development scripts
│   ├── .env               # Environment variables (⚠️ Add to .gitignore)
│   ├── babel.config.js    # Babel configuration
│   ├── firebase.json      # Firebase configuration
│   ├── metro.config.js    # Metro bundler configuration
│   └── package.json       # Node.js dependencies

├── contracts/    # Aptos Move smart contracts
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

3. **Keyless Authentication Integration (Client-Side)**
   - Zero-knowledge proof authentication using Aptos keyless
   - All proofs and ephemeral keys remain client-side
   - Server only stores the resulting Aptos address
   - Two-phase transaction flow:
     - Server prepares transaction → returns unsigned bytes
     - Client signs with keyless → sends signature back
     - Server executes with dual signatures (user + sponsor)

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

#### Pepper Formula
The multi-account system uses deterministic pepper generation:
```
pepper = SHA256(issuer | subject | audience | account_type | business_id (if applied) | account_index)
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
- **Existing users**: Continue using their current pepper (equivalent to `personal_0`)
- **Account switching**: Each account type/index combination generates a unique Aptos address
- **Employee accounts**: Access business through JWT with embedded business_id
- **Business owners**: Also receive business_id in JWT for consistent security model

#### Security Model
1. **Deterministic**: Same OAuth identity + account context = same Aptos address
2. **Isolated**: Each account has its own private key and Aptos address
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
- JWT token, Aptos address, and keyless private values getting out of sync

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
- Automatically uses active account context for pepper generation
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
- KeylessProof
- TelegramVerification

Instead of permanently deleting records, a `deleted_at` timestamp is set. This ensures:
- **No index reuse**: Deleted accounts/businesses/users cannot be recreated with the same index, preventing Aptos address collisions and key reuse.
- **Prevents collision of eliminated and newly created accounts**: If an account is deleted, its index is never reused, so a new account cannot be created with the same index and thus cannot generate the same Aptos address. This eliminates the risk of a new user accidentally or maliciously taking over the Aptos address of a previously deleted account.
- **Auditability**: All actions are traceable for compliance and security audits.
- **Data integrity**: Financial and identity records are never truly lost, only flagged as deleted.

### Device Fingerprinting

Confío implements comprehensive device fingerprinting for fraud prevention and risk assessment:

#### Data Collection
- **Device Hardware**: Model, brand, manufacturer, memory
- **Network**: IP address, ISP, country, timezone
- **Software**: OS version, app version, Firebase installation ID
- **Behavioral**: Session patterns, login frequency, feature usage

#### Risk Assessment
- **Registration Risk**: New device + new user = higher scrutiny
- **Login Risk**: New device + existing user = require additional verification
- **Transaction Risk**: High-value transactions from new devices = enhanced monitoring
- **Geolocation Risk**: Login from new country = additional verification

#### Privacy Protection
- **Hash-based Storage**: Personal identifiers are hashed before storage
- **Aggregated Analytics**: Individual fingerprints are not used for tracking
- **Legal Compliance**: Full GDPR/CCPA compliance with data retention policies
- **User Control**: Users can view and delete their device data

#### Security Benefits
- **Account Takeover Prevention**: Detect unauthorized access attempts
- **Fraud Detection**: Identify suspicious patterns across devices
- **Risk-based Authentication**: Adjust security requirements based on risk score
- **Compliance**: Meet regulatory requirements for transaction monitoring

## 🌐 Deployment Architecture

Confío uses a hybrid deployment approach optimized for Latin American users:

### Backend Infrastructure
- **Primary Region**: US East (N. Virginia) for low latency to LATAM
- **Database**: PostgreSQL with read replicas
- **Cache**: Redis cluster for session management
- **CDN**: CloudFlare for static assets and DDoS protection
- **Load Balancer**: AWS Application Load Balancer with SSL termination

### Mobile App Distribution
- **iOS**: TestFlight for closed beta, App Store for production
- **Android**: Internal testing tracks, Google Play Store for production
- **Deep Linking**: Universal Links (iOS) and App Links (Android)
- **Analytics**: Firebase Analytics with custom events

### Web Application
- **Hosting**: Cloudflare Pages for static hosting
- **API**: Django backend with GraphQL endpoint
- **WebSocket**: Django Channels for real-time features
- **SSL**: Full SSL encryption with HSTS headers

### Blockchain Integration
- **Network**: Aptos Testnet for development, Mainnet for production
- **RPC**: Multiple RPC endpoints for redundancy
- **Sponsored Transactions**: Dedicated sponsor account for gas payments
- **Transaction Monitoring**: Real-time blockchain event polling

### Security & Monitoring
- **WAF**: Cloudflare Web Application Firewall
- **DDoS Protection**: Cloudflare with custom rules for LATAM traffic
- **Monitoring**: DataDog for application and infrastructure monitoring
- **Logging**: Structured logging with log aggregation
- **Alerts**: PagerDuty integration for critical issues

### Disaster Recovery
- **Database Backups**: Daily automated backups with point-in-time recovery
- **Code Backups**: Git repositories with multiple remotes
- **Configuration**: Infrastructure as Code with Terraform
- **Failover**: Multi-region deployment capability for critical services

## 🔧 Development Setup

### Prerequisites
- Python 3.9+
- Node.js 18+
- PostgreSQL 13+
- Redis 6+
- Docker (optional, for containerized services)

### Backend Setup

1. **Clone the repository**
```bash
git clone https://github.com/confio/confio.git
cd confio
```

2. **Create virtual environment**
```bash
python -m venv myvenv
source myvenv/bin/activate  # On Windows: myvenv\Scripts\activate
```

3. **Install Python dependencies**
```bash
pip install -r requirements.txt
```

4. **Environment configuration**
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. **Database setup**
```bash
python manage.py migrate
python manage.py createsuperuser
```

6. **Start services**
```bash
# Django development server
python manage.py runserver

# Celery worker (separate terminal)
celery -A config worker -l info

# Celery beat (separate terminal)
celery -A config beat -l info
```

### Frontend Setup

#### Web Application
```bash
cd web
npm install
npm start  # Development server
npm run build  # Production build
```

#### React Native Application
```bash
cd apps
npm install

# iOS (macOS only)
cd ios && pod install && cd ..
npx react-native run-ios

# Android
npx react-native run-android
```

### Blockchain Setup

1. **Install Aptos CLI**
```bash
curl -fsSL "https://aptos.dev/scripts/install_cli.py" | python3
```

2. **Deploy contracts (development)**
```bash
cd contracts/cusd
aptos move publish --profile testnet

cd ../confio
aptos move publish --profile testnet
```

3. **Configure environment**
```bash
# Add contract addresses to .env
APTOS_CUSD_ADDRESS=0x...
APTOS_CONFIO_ADDRESS=0x...
```

### Testing

#### Backend Tests
```bash
python manage.py test
```

#### Frontend Tests
```bash
# Web
cd web && npm test

# React Native
cd apps && npm test
```

#### Smart Contract Tests
```bash
cd contracts/cusd && aptos move test
cd contracts/confio && aptos move test
```

## 📊 Performance & Scalability

### Current Metrics
- **Response Time**: <200ms API response time (95th percentile)
- **Throughput**: 1,000+ requests/second capacity
- **Uptime**: 99.9% availability target
- **Transaction Speed**: <5 seconds for sponsored transactions

### Optimization Strategies
- **Database**: Query optimization, connection pooling, read replicas
- **Caching**: Redis for session data, query results, and computed values
- **CDN**: Static asset caching with geographic distribution
- **Async Processing**: Celery for background tasks and blockchain polling

### Monitoring & Alerting
- **Application Monitoring**: Request/response times, error rates
- **Infrastructure Monitoring**: CPU, memory, disk usage
- **Business Metrics**: Transaction volume, user activity, conversion rates
- **Custom Alerts**: Failed transactions, high error rates, performance degradation

## 🔒 Security Considerations

### Data Protection
- **Encryption at Rest**: Database encryption for sensitive data
- **Encryption in Transit**: TLS 1.3 for all communications
- **Key Management**: AWS KMS for encryption key management
- **PII Handling**: Hash-based storage for personal identifiers

### Access Control
- **Authentication**: Multi-factor authentication for admin accounts
- **Authorization**: Role-based access control (RBAC)
- **API Security**: Rate limiting, input validation, SQL injection prevention
- **Network Security**: VPC isolation, security groups, NACLs

### Compliance
- **GDPR**: Data minimization, right to be forgotten, consent management
- **CCPA**: Data transparency, opt-out mechanisms
- **Financial Regulations**: AML/KYC compliance where required
- **Security Audits**: Regular penetration testing and code reviews

## 🌍 Localization & Internationalization

### Language Support
- **Primary**: Spanish (Latin America)
- **Secondary**: English (US)
- **Planned**: Portuguese (Brazil), Italian (Argentina)

### Regional Considerations
- **Currency Display**: Local currency formatting
- **Payment Methods**: Country-specific payment options
- **Legal Compliance**: Regional financial regulations
- **Cultural Adaptation**: Messaging and UX adapted for LATAM culture

### Technical Implementation
- **i18n Framework**: React i18next for frontend
- **Backend Localization**: Django internationalization
- **Database Design**: Multi-language support for user-generated content
- **Asset Management**: Localized images and media

## 🚀 Roadmap

### Q1 2025
- [ ] Complete Aptos mainnet migration
- [ ] Launch business accounts with employee management
- [ ] Implement advanced P2P trading features
- [ ] Add Brazilian market support

### Q2 2025
- [ ] Multi-language support (Portuguese, Italian)
- [ ] Advanced analytics and reporting
- [ ] Integration with traditional banking
- [ ] Mobile SDK for third-party integrations

### Q3 2025
- [ ] Cross-chain interoperability
- [ ] Merchant payment gateway
- [ ] Advanced DeFi integrations
- [ ] Enterprise-grade compliance tools

### Q4 2025
- [ ] Expansion to additional LATAM countries
- [ ] Institutional investor features
- [ ] Advanced risk management
- [ ] White-label solution for banks

## 🤝 Contributing

Confío is open source and welcomes contributions from the community.

### How to Contribute

1. **Fork the repository** and create a feature branch
2. **Make your changes** with appropriate tests
3. **Submit a pull request** with a clear description
4. **Code review** process with maintainers
5. **Merge** after approval and testing

### Contribution Areas
- **Frontend Development**: React Native, React, TypeScript
- **Backend Development**: Python, Django, GraphQL
- **Smart Contracts**: Move language, Aptos blockchain
- **DevOps**: AWS, Docker, CI/CD pipelines
- **Design**: UI/UX, mobile app design
- **Documentation**: Technical writing, tutorials
- **Testing**: Automated testing, quality assurance
- **Localization**: Translation, cultural adaptation

### Development Guidelines
- **Code Style**: Follow project style guides and linting rules
- **Testing**: Write tests for new features and bug fixes
- **Documentation**: Update documentation for significant changes
- **Security**: Follow secure coding practices
- **Performance**: Consider performance impact of changes

### Community
- **Discord**: Join our developer community
- **GitHub Discussions**: Ask questions and share ideas
- **Issues**: Report bugs and request features
- **Wiki**: Contribute to project documentation

## 📞 Support & Community

### For Users
- **App Support**: In-app help center and contact form
- **Telegram**: [@FansDeJulian](https://t.me/FansDeJulian) for community support
- **Website**: [confio.lat](https://confio.lat) for official information
- **Social Media**: Follow @JulianMoonLuna on TikTok for updates

### For Developers
- **GitHub Issues**: Report bugs and request features
- **Documentation**: Comprehensive guides in the repository
- **Community**: Join our developer Discord server
- **Office Hours**: Monthly community calls with the core team

### Business Inquiries
- **Partnerships**: Email partnerships@confio.lat
- **Enterprise**: Email enterprise@confio.lat
- **Press**: Email press@confio.lat
- **General**: Email hello@confio.lat

## 📄 Legal & Compliance

### Privacy Policy
Our privacy policy is available at [confio.lat/privacy](https://confio.lat/privacy) and covers:
- Data collection and usage
- Third-party integrations
- User rights and controls
- Regional compliance requirements

### Terms of Service
Our terms of service are available at [confio.lat/terms](https://confio.lat/terms) and cover:
- User responsibilities
- Service availability
- Limitation of liability
- Dispute resolution

### Licenses
- **Code**: MIT License - see [LICENSE](LICENSE) file
- **Trademarks**: Confío trademarks are owned by Confío Inc.
- **Content**: Documentation under Creative Commons Attribution
- **Dependencies**: Various open source licenses - see package files

---

**Built with ❤️ for Latin America by [Julian Moon](https://github.com/caesar4321) and the Confío community.**