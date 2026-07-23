# Project Structure

This is a **monolithic repository** containing the full Confío stack.

```bash
/Confio/
├── DESIGN.md          # Website design system («Radicalmente Normal») — source of truth for web/ visuals
├── web/               # React-based web application (Terms, Privacy, Landing)
│   ├── src/           # React source code (+ Jest tests for landing components)
│   └── public/        # Static files
│
├── apps/              # React Native mobile application (iOS + Android)
│   ├── src/           # TypeScript source
│   │   ├── components/
│   │   ├── screens/
│   │   ├── services/  # API & Blockchain services
│   │   └── hooks/     # Custom React hooks
│   ├── ios/           # Native iOS code
│   └── android/       # Native Android code
│
├── config/            # Django project configuration (Settings, URLs)
├── contracts/         # Algorand and EVM smart contracts
│   ├── cusd/          # cUSD Stablecoin
│   ├── cusd_plus/     # cUSD+ BNB Smart Chain vault and deployment records
│   ├── p2p_trade/     # P2P Exchange Contract
│   ├── payment/       # Payment Processing
│   ├── payroll/       # Payroll System
│   ├── presale/       # Token Presale
│   └── vesting/       # Token Vesting
│
├── workers/           # Cloudflare Workers
│   └── link-shortener # WhatsApp link shortener service
│
# Backend Modules (Django Apps)
├── auth/              # Authentication & JWT
├── users/             # User management
├── blockchain/        # Algorand integration service
├── p2p_exchange/      # P2P Trading platform
├── payments/          # Payment processing
├── payroll/           # Payroll management
├── presale/           # CONFIO Token presale
├── send/              # Two-phase send transaction system
├── security/          # Fraud prevention & IP tracking
├── telegram_verification/ # Phone verification
├── sms_verification/  # SMS verification fallback
├── notifications/     # User notifications
├── conversion/        # Currency conversion service
├── exchange_rates/    # Fiat/Crypto exchange rates
├── achievements/      # User gamification & rewards
├── usdc_transactions/ # USDC specific transaction handling
│
├── docs/              # Public project documentation
│   ├── README.md      # Documentation index
│   ├── whitepaper/
│   │   └── README.md  # Canonical English product and strategy whitepaper
│   ├── analysis/      # Partner and product analysis
│   ├── legal/         # Public legal and market-access policies
│   ├── plans/         # Active implementation plans
│   └── security/      # Security, identity, and access-control references
└── manage.py          # Django entry point
```
