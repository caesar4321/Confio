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

---

## 🧱 Tech Stack

| Layer         | Stack                         |
|---------------|-------------------------------|
| Frontend      | React Native (no Expo)        |
| Auth          | Firebase Authentication       |
| Blockchain    | [Sui](https://sui.io)         |
| Smart Contracts | Move language               |
| Backend API   | Django + GraphQL              |
| CI/CD         | Cloudflare Pages              |

---

## 🔒 What Confío Is Not

- ❌ Not a custodial wallet — we never store user funds
- ❌ No backend "tricks" — money logic lives entirely on-chain
- ❌ No crypto knowledge required — users sign in with Google or Apple

---

## 💬 Join the Community

Confío is more than a wallet — it's a mission to bring financial confidence to Latin America through transparency, crypto, and culture.

Come build the future with us:

🌐 Website: [confio.lat](https://confio.lat)  
🔗 Telegram (Community): [t.me/FansDeJulian](https://t.me/FansDeJulian)  
📱 TikTok (Latinoamérica): [@JulianMoonLuna](https://tiktok.com/@JulianMoonLuna)

---

## 📜 License

MIT License — build freely, fork proudly, remix for your country.

---

## 🙏 Credits

Confío is led by Julian Moon,
a Korean builder based in Latin America, inspired by the dream of a trustworthy, borderless financial inclusion for everyone. 

---

## 🧠 Project Structure

This is a **monolithic repository** containing the full Confío stack:

```bash
/Confio/
├── web/               # React-based web application
│   ├── public/        # Static public files
│   ├── src/           # React source code
│   │   ├── Components/    # React components
│   │   ├── images/        # Image assets
│   │   ├── styles/        # CSS styles
│   │   ├── types/         # TypeScript type definitions
│   │   ├── App.css        # Main application styles
│   │   ├── App.js         # Main application component
│   │   └── index.js       # Application entry point
│   ├── build/           # Production build output
│   ├── static/          # Static assets
│   ├── templates/       # HTML templates
│   ├── .eslintrc.json   # ESLint configuration
│   ├── .prettierrc       # Prettier configuration
│   ├── nginx.conf         # Nginx configuration
│   ├── package.json       # Node.js dependencies
│   ├── tsconfig.json      # TypeScript configuration
│   └── yarn.lock          # Yarn lock file

├── config/            # Django project configuration
│   ├── settings.py    # Django settings
│   ├── urls.py        # URL routing
│   ├── wsgi.py        # WSGI configuration
│   ├── schema.py      # Root GraphQL schema
│   ├── celery.py      # Celery configuration
│   └── views.py       # View functions
├── credentials/       # Encrypted credentials (git-crypt)
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
│   └── tests/         # User tests
├── manage.py          # Django management script
├── requirements.txt   # Python dependencies
└── celery.py         # Celery worker configuration

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
│   │   ├── components/    # Reusable React components
│   │   ├── config/        # Application configuration
│   │   ├── hooks/         # Custom React hooks
│   │   ├── screens/       # Screen components
│   │   ├── services/      # API and business logic services
│   │   ├── types/         # TypeScript type definitions
│   │   └── utils/         # Utility functions
│   ├── scripts/           # Build and development scripts
│   ├── .env               # Environment variables (⚠️ Add to .gitignore)
│   ├── babel.config.js    # Babel configuration
│   ├── firebase.json      # Firebase configuration
│   ├── metro.config.js    # Metro bundler configuration
│   └── package.json       # Node.js dependencies
├── contracts/    # Sui Move smart contracts
│   ├── sources/  # Move source files
│   │   ├── cusd.move              # CUSD stablecoin implementation
│   │   ├── cusd_vault_usdc.move   # USDC vault for CUSD minting/burning
│   │   ├── cusd_vault_treasury.move # Treasury vault for CUSD operations
│   │   └── confio.move            # CONFIO governance token
│   ├── Move.toml # Package configuration
│   └── Move.lock # Dependency lock file
└── README.md
```

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
- **File**: `contracts/sources/cusd.move`
- **Purpose**: Implementation of the $cUSD stablecoin, a gasless stablecoin designed for everyday transactions in Latin America
- **Key Features**:
  - 6 decimal places precision for micro-transactions
  - USD-pegged stablecoin backed by USDC
  - Gasless transactions enabled through sponsored transactions: For minting/burning through treasury vault

### Confío ($CONFIO)
- **File**: `contracts/sources/confio.move`
- **Purpose**: Governance and utility token for the Confío platform
- **Key Features**:
  - Fixed supply of 1 billion tokens
  - 6 decimal places precision
  - UTF-8 support for Spanish characters
  - Custom icon URL
- **Distribution**:
  - Initial supply minted to contract deployer
  - Metadata and treasury cap frozen after initialization