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

## 🧱 Tech Stack

| Layer         | Stack                         |
|---------------|-------------------------------|
| Frontend      | React Native (no Expo)        |
| Auth          | Firebase Authentication       |
| Blockchain    | [Sui](https://sui.io)         |
| Smart Contracts | Move language               |
| Backend API   | Django + GraphQL              |
| CI/CD         | Cloudflare Pages              |

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
│   │   ├── config/        # Application configuration
│   │   ├── contexts/      # React contexts (Auth, etc.)
│   │   ├── hooks/         # Custom React hooks
│   │   ├── screens/       # Screen components
│   │   │   ├── AuthScreen.tsx        # Authentication screen
│   │   │   ├── PhoneVerificationScreen.tsx  # Phone verification
│   │   │   └── HomeScreen.tsx        # Main app screen
│   │   ├── services/      # API and business logic services
│   │   │   ├── authService.ts    # Authentication service
│   │   │   └── ...        # Other services
│   │   ├── types/         # TypeScript type definitions
│   │   ├── utils/         # Utility functions
│   │   │   ├── countries.ts  # Country codes mapping [name, code, iso, flag]
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

## 🚀 Development Setup

### Web Application (React + Django)

1. **Install Dependencies**
   ```bash
   # Install Python dependencies
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

3. **Run Django Development Server**
   ```bash
   python manage.py runserver
   ```
   The server will:
   - Serve the React app at the root URL
   - Handle static files using Whitenoise
   - Provide GraphQL API endpoints

4. **Development Workflow**
   - For React development: `yarn start` (runs on port 3000)
   - For Django development: `python manage.py runserver` (runs on port 8000)
   - After making React changes, run `yarn build` to update the Django-served version

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
>     - `SECRET_KEY`: Django secret key for cryptographic signing (e.g., 'django-insecure-&(hehrlb0sqdkf8awe$55l!k9k)u_6a-5wn1ro))s(prkri2_t')
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