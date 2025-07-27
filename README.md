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
│   ├── cusd/     # CUSD stablecoin implementation
│   │   ├── sources/  # Move source files
│   │   │   ├── cusd.move              # CUSD stablecoin implementation
│   │   │   ├── cusd_vault_usdc.move   # USDC vault for CUSD minting/burning
│   │   │   └── cusd_vault_treasury.move # Treasury vault for CUSD operations
│   │   ├── Move.toml # Package configuration
│   │   └── Move.lock # Dependency lock file
│   └── confio/   # CONFIO governance token
│       ├── sources/  # Move source files
│       │   └── confio.move            # CONFIO governance token implementation
│       ├── Move.toml # Package configuration
│       └── Move.lock # Dependency lock file

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

Confío supports multiple accounts per user, allowing separate wallets for personal and business use cases.

#### Account Types
- **Personal Accounts**: Individual wallets for personal transactions
- **Business Accounts**: Dedicated wallets for business operations

#### Salt Formula
The multi-account system uses deterministic salt generation:
```
salt = SHA256(issuer | subject | audience | account_type | account_index)
```

Where:
- `issuer`: JWT issuer (e.g., "https://accounts.google.com")
- `subject`: JWT subject (user's unique ID)
- `audience`: OAuth client ID
- `account_type`: Either "personal" or "business"
- `account_index`: Numeric index (0, 1, 2, etc.)

#### Default Behavior
- **New users**: Automatically get `personal_0` as their default account
- **Existing users**: Continue using their current salt (equivalent to `personal_0`)
- **Account switching**: Each account type/index combination generates a unique Sui address

#### Security Model
1. **Deterministic**: Same OAuth identity + account context = same Sui address
2. **Isolated**: Each account has its own private key and Sui address
3. **Non-custodial**: Private keys are never stored on servers
4. **Stateless**: Server doesn't track active accounts, client manages state

#### Implementation Components

**Account Manager** (`apps/src/utils/accountManager.ts`)
- Manages account storage and retrieval using React Native Keychain
- Handles account creation, switching, and context management

**Auth Service Integration** (`apps/src/services/authService.ts`)
- Automatically uses active account context for salt generation
- Provides account switching and creation methods

**React Hook** (`apps/src/hooks/useAccountManager.ts`)
- Provides easy access to account management in React components
- Handles account state and operations

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
await authService.switchAccount('business_0'); // Business account
```

**Multiple Personal Accounts**
```typescript
const personal2 = await authService.createAccount(
  'personal',
  'Personal Savings',
  'S',
  '+1234567890'
);
await authService.switchAccount('personal_1'); // Savings account
```

### Token Management
1. **Access Token**
   - Short-lived (1 hour) for security
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
- `myP2pTrades(accountId)`: User's trades filtered by account context
- `p2pTradeMessages(tradeId)`: Real-time trade chat messages
- `p2pPaymentMethods(countryCode)`: Country-specific payment methods

#### Mutations
- `createP2POffer`: Create new trading offers
- `createP2PTrade`: Initiate trades with offers
- `updateP2PTradeStatus`: Update trade status (payment sent, confirmed, etc.)
- `sendP2PMessage`: Send messages in trade chat

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
    accountId: "business_0"
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

### Prerequisites

1. **Redis Server** (required for Django Channels)
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

2. **PostgreSQL Database**
   ```bash
   # Create database and user
   make db-setup
   ```

### Web Application (React + Django + Channels)

1. **Install Dependencies**
   ```bash
   # Install Python dependencies (includes Django Channels, Redis, Daphne)
   pip install -r requirements.txt

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
   make migrate
   ```

4. **Setup Unified Payment Method System**
   ```bash
   # Create and apply migrations for user and P2P models
   python manage.py makemigrations users p2p_exchange
   python manage.py migrate
   
   # Populate initial country and bank data
   python manage.py populate_bank_data
   
   # Populate P2P payment methods (banks + fintech solutions)
   python manage.py populate_payment_methods
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
>   - `service-account.json` (⚠️ **Location**: `/Confio/config/service-account.json`): Firebase Admin SDK service account key
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
  - USD-pegged stablecoin backed by USDC
  - Gasless transactions enabled through Sui's native sponsored transaction system
  - Vault system for USDC backing and treasury operations

### Confío ($CONFIO)
- **File**: `contracts/confio/sources/confio.move`
- **Purpose**: Governance and utility token for the Confío platform
- **Key Features**:
  - Fixed supply of 1 billion tokens
  - 6 decimal places precision
  - UTF-8 support for Spanish characters
  - Custom icon URL
- **Distribution**:
  - Initial supply minted to contract deployer
  - Metadata and treasury cap frozen after initialization

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

The Confío app includes a gamified achievement system to encourage user engagement and promote viral growth through social sharing.

### Achievement Types

1. **Primeros Pasos** (First Steps) - Complete registration
2. **Primera Compra** (First Purchase) - Complete first P2P trade
3. **Primer Envío** (First Send) - Send cUSD for the first time
4. **Primera Recepción** (First Receive) - Receive cUSD for the first time
5. **Primer Pago** (First Payment) - Make first merchant payment
6. **Verificado** (Verified) - Complete identity verification
7. **10 Intercambios** (10 Trades) - Complete 10 P2P trades
8. **Embajador** (Ambassador) - Refer 5 new users
9. **Hodler** (Hodler) - Hold cUSD for 30 days
10. **Comerciante** (Merchant) - Accept 10 payments
11. **Viajero** (Traveler) - Send to 3 different countries
12. **Veterano** (Veteran) - Active for 6 months

### Implementation Details

- **Location**: Profile screen (`ProfileScreen.tsx`)
- **Visual Design**: Circular badges with completion status
- **Progress Tracking**: "5/12" style counter
- **Share Indicator**: Blue badge for achievements shared on social media

### Social Sharing Integration

Each achievement can be shared to social media with pre-configured hashtags:
- Latin America: `#RetoConfio #MiPrimerConfioDollar`
- Other regions: `#ConfioChallenge #MyFirstSecureDollar`

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
