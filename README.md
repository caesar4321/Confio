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
| Backend Relay | Python (Django)               |
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
│   │   ├── public/        # Static public files
│   │   ├── src/           # React source code
│   │   │   ├── Components/    # React components
│   │   │   ├── images/        # Image assets
│   │   │   ├── styles/        # CSS styles
│   │   │   ├── types/         # TypeScript type definitions
│   │   │   ├── App.css        # Main application styles
│   │   │   ├── App.js         # Main application component
│   │   │   └── index.js       # Application entry point
│   │   ├── build/           # Production build output
│   │   ├── static/          # Static assets
│   │   ├── templates/       # HTML templates
│   │   ├── .eslintrc.json   # ESLint configuration
│   │   ├── .prettierrc       # Prettier configuration
│   │   ├── nginx.conf         # Nginx configuration
│   │   ├── package.json       # Node.js dependencies
│   │   ├── tsconfig.json      # TypeScript configuration
│   │   └── yarn.lock          # Yarn lock file
│   ├── manage.py          # Django management script
│   ├── requirements.txt   # Python dependencies
│   └── celery.py       

├── config/            # Django project configuration
│   ├── settings/      # Environment-specific settings
│   │   ├── base.py   # Base settings
│   │   ├── dev.py    # Development settings
│   │   └── prod.py   # Production settings
│   ├── urls.py        # URL routing
│   ├── wsgi.py        # WSGI configuration
│   └── asgi.py        # ASGI configuration
├── credentials/       # Encrypted credentials (git-crypt)
├── prover/            # Server-side proof verification
│   ├── models.py      # Database models
│   ├── views.py       # API endpoints
│   ├── serializers.py # Data serialization
│   └── tests/         # Test cases
├── users/             # User authentication and management
│   ├── models.py      # User models
│   ├── views.py       # User endpoints
│   ├── serializers.py # User data serialization
│   └── tests/         # User tests
├── web/               # Web application frontend
│   ├── static/        # Static assets
│   ├── templates/     # HTML templates
│   └── views.py       # Web views
├── manage.py          # Django management script
├── requirements.txt   # Python dependencies
└── celery.py   

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
│   │   ├── graphql/       # GraphQL schema and type definitions
│   │   ├── hooks/         # Custom React hooks
│   │   ├── screens/       # Screen components
│   │   ├── services/      # API and business logic services
│   │   ├── types/         # TypeScript type definitions
│   │   └── utils/         # Utility functions
│   ├── prover/            # React Native module for client-side proof generation
│   ├── scripts/           # Build and development scripts
│   ├── .env               # Environment variables (⚠️ Add to .gitignore)
│   ├── babel.config.js    # Babel configuration
│   ├── firebase.json      # Firebase configuration
│   ├── metro.config.js    # Metro bundler configuration
│   └── package.json       # Node.js dependencies
├── contracts/    # Sui Move smart contracts (cUSD, escrow, etc.)
└── README.md
```

⚠️ **Important**: The following files and directories should be added to `.gitignore` for security:

> - `.env` files (⚠️ **Critical Development Files**):
>   - Root `.env` (⚠️ **Location**: `/Confio/.env`): Django settings
>     - `SECRET_KEY`: Django secret key for cryptographic signing
>     - `DEBUG`: Django debug mode (True/False)
>     - `ALLOWED_HOSTS`: Comma-separated list of allowed hostnames
>     - `DATABASE_URL`: PostgreSQL database connection URL
>     - `REDIS_URL`: Redis connection URL for caching
>     - `EMAIL_HOST`: SMTP server host
>     - `EMAIL_PORT`: SMTP server port
>     - `EMAIL_HOST_USER`: SMTP username
>     - `EMAIL_HOST_PASSWORD`: SMTP password
>     - `EMAIL_USE_TLS`: Use TLS for email (True/False)
>     - `DEFAULT_FROM_EMAIL`: Default sender email address
>     - `SUI_NODE_URL`: Sui blockchain node URL
>     - `SUI_FAUCET_URL`: Sui faucet URL for testnet
>     - `SUI_GAS_BUDGET`: Gas budget for transactions
>     - `SUI_PACKAGE_ID`: Sui package ID for smart contracts
>     - `SUI_ADMIN_ADDRESS`: Admin wallet address
>     - `SUI_ADMIN_PRIVATE_KEY`: Admin wallet private key
>     - `FIREBASE_PROJECT_ID`: Firebase project ID
>     - `FIREBASE_PRIVATE_KEY`: Firebase private key
>     - `FIREBASE_CLIENT_EMAIL`: Firebase client email
>     - `FIREBASE_DATABASE_URL`: Firebase Realtime Database URL
>     - `CLOUDINARY_CLOUD_NAME`: Cloudinary cloud name
>     - `CLOUDINARY_API_KEY`: Cloudinary API key
>     - `CLOUDINARY_API_SECRET`: Cloudinary API secret
>     - `SENTRY_DSN`: Sentry error tracking DSN
>     - `LOG_LEVEL`: Application log level
>     - `CORS_ALLOWED_ORIGINS`: Comma-separated list of allowed CORS origins
>     - `CSRF_TRUSTED_ORIGINS`: Comma-separated list of trusted CSRF origins
>     - `SECURE_SSL_REDIRECT`: Redirect to HTTPS (True/False)
>     - `SESSION_COOKIE_SECURE`: Secure session cookies (True/False)
>     - `CSRF_COOKIE_SECURE`: Secure CSRF cookies (True/False)
>     - `SECURE_HSTS_SECONDS`: HSTS header duration
>     - `SECURE_HSTS_INCLUDE_SUBDOMAINS`: Include subdomains in HSTS (True/False)
>     - `SECURE_HSTS_PRELOAD`: Enable HSTS preload (True/False)
>     - `SECURE_PROXY_SSL_HEADER`: Proxy SSL header configuration
>     - `USE_X_FORWARDED_HOST`: Use X-Forwarded-Host header (True/False)
>     - `USE_X_FORWARDED_PORT`: Use X-Forwarded-Port header (True/False)
>     - `GOOGLE_OAUTH_CLIENT_ID`: Google OAuth client ID for web application
>     - `GOOGLE_OAUTH_CLIENT_SECRET`: Google OAuth client secret for web application
>     - `GOOGLE_OAUTH_REDIRECT_URI`: Google OAuth redirect URI for web application
>   - `apps/.env` (⚠️ **Location**: `/Confio/apps/.env`): React Native app settings
>     - `API_URL`: Backend API URL
>     - `FIREBASE_CONFIG`: Firebase configuration JSON
>     - `SUI_NODE_URL`: Sui blockchain node URL
>     - `SUI_FAUCET_URL`: Sui faucet URL for testnet
>     - `SUI_GAS_BUDGET`: Gas budget for transactions
>     - `SUI_PACKAGE_ID`: Sui package ID for smart contracts
>     - `SENTRY_DSN`: Sentry error tracking DSN
>     - `LOG_LEVEL`: Application log level
>     - `ENVIRONMENT`: App environment (development/production)
>     - `VERSION`: App version number
>     - `BUILD_NUMBER`: App build number
>     - `APP_NAME`: App display name
>     - `APP_IDENTIFIER`: App bundle identifier
>     - `APP_SCHEME`: App URL scheme
>     - `DEEP_LINK_PREFIX`: Deep link URL prefix
>     - `APPLE_APP_ID`: Apple App Store ID
>     - `GOOGLE_PLAY_APP_ID`: Google Play Store ID
>     - `GOOGLE_OAUTH_CLIENT_ID_IOS`: Google OAuth client ID for iOS app
>     - `GOOGLE_OAUTH_CLIENT_ID_ANDROID`: Google OAuth client ID for Android app
>     - `GOOGLE_OAUTH_REVERSED_CLIENT_ID`: Google OAuth reversed client ID for iOS
>     - `GOOGLE_OAUTH_WEB_CLIENT_ID`: Google OAuth web client ID for server verification
>   - `apps/android/.env` (⚠️ **Location**: `/Confio/apps/android/.env`): Android-specific settings
>     - `KEYSTORE_PASSWORD`: Keystore password
>     - `KEY_ALIAS`: Key alias
>     - `KEY_PASSWORD`: Key password
>     - `KEYSTORE_PATH`: Keystore file path
>     - `ANDROID_SDK_PATH`: Android SDK path
>     - `ANDROID_NDK_PATH`: Android NDK path
>     - `ANDROID_HOME`: Android home directory
>     - `JAVA_HOME`: Java home directory
>     - `GRADLE_USER_HOME`: Gradle user home directory
>     - `GRADLE_OPTS`: Gradle options
>     - `ANDROID_DEBUG_KEYSTORE`: Debug keystore path
>     - `ANDROID_DEBUG_KEY_ALIAS`: Debug key alias
>     - `ANDROID_DEBUG_KEY_PASSWORD`: Debug key password
>     - `ANDROID_DEBUG_STORE_PASSWORD`: Debug store password
>     - `GOOGLE_OAUTH_CLIENT_ID`: Google OAuth client ID for Android app
>     - `GOOGLE_OAUTH_CLIENT_SECRET`: Google OAuth client secret for Android app
>   - `apps/ios/.env` (⚠️ **Location**: `/Confio/apps/ios/.env`): iOS-specific settings
>     - `APPLE_TEAM_ID`: Apple Developer Team ID
>     - `APPLE_DEVELOPER_TEAM`: Apple Developer Team name
>     - `APPLE_PROVISIONING_PROFILE`: Provisioning profile name
>     - `APPLE_CODE_SIGN_IDENTITY`: Code signing identity
>     - `APPLE_DISTRIBUTION_CERTIFICATE`: Distribution certificate name
>     - `APPLE_DEVELOPMENT_CERTIFICATE`: Development certificate name
>     - `APPLE_KEYCHAIN_PASSWORD`: Keychain password
>     - `APPLE_KEYCHAIN_PATH`: Keychain path
>     - `APPLE_KEYCHAIN_NAME`: Keychain name
>     - `APPLE_KEYCHAIN_CREATE`: Create keychain (True/False)
>     - `APPLE_KEYCHAIN_DEFAULT`: Default keychain (True/False)
>     - `APPLE_KEYCHAIN_UNLOCK`: Unlock keychain (True/False)
>     - `APPLE_KEYCHAIN_TIMEOUT`: Keychain timeout
>     - `APPLE_KEYCHAIN_LOCK_TIMEOUT`: Keychain lock timeout
>     - `APPLE_KEYCHAIN_LOCK_AFTER_USE`: Lock keychain after use (True/False)
>     - `APPLE_KEYCHAIN_LOCK_WHEN_SLEEPING`: Lock keychain when sleeping (True/False)
>     - `GOOGLE_OAUTH_CLIENT_ID`: Google OAuth client ID for iOS app
>     - `GOOGLE_OAUTH_CLIENT_SECRET`: Google OAuth client secret for iOS app
>     - `GOOGLE_OAUTH_REVERSED_CLIENT_ID`: Google OAuth reversed client ID
> - Firebase Configuration Files (⚠️ **Critical Development Files**):
>   - `google-services.json` (⚠️ **Location**: `/Confio/apps/android/app/google-services.json`): Android Firebase config
>   - `GoogleService-Info.plist` (⚠️ **Location**: `/Confio/apps/ios/Confio/GoogleService-Info.plist`): iOS Firebase config
> - `confio.tar.gz` (deployment archive)
> - `apps/android/gradle.properties` (contains keystore and signing configurations)
> - Any other files containing sensitive information or credentials