# Confío

**Dollar finance built for Latin America — user-controlled money, distributed through trust.**

[Website](https://confio.lat) · [Whitepaper](docs/whitepaper/README.md) · [Tokenomics](docs/tokenomics/README.md) · [BNB Smart Chain deployments](contracts/cusd_plus/DEPLOYMENT.md)

Confío is a fully open-source, non-custodial financial application for Latin America. It combines dollar access, savings, transfers, merchant payments, payroll, staged eligible Ondo Stocks access, and the $CONFIO ecosystem token in a familiar mobile experience. The current product system settles on **BNB Smart Chain**, while the application hides gas, approvals, contract calls, and blockchain addresses from everyday users.

*Lo tuyo, tuyo. · Blockchain inside. Simple as PayPal.*

## What Confío does

- **Add and withdraw dollars:** convert local currency or BSC-USDT into Confío dollars and back through one transparent 0.9% entry/exit fee perimeter.
- **Hold cUSD or save with cUSD+:** users in Ondo-ineligible jurisdictions receive the universal, USDT-backed cUSD payment dollar; eligible users receive the USDY-backed, accumulating cUSD+ savings balance. Moving between cUSD and cUSD+ inside Confío is free. Yield is variable and not guaranteed.
- **Send simply:** transfer to contacts without asking users to copy blockchain addresses or hold BNB for gas.
- **Accept payments:** support merchant invoices and QR-centered payment flows with transparent on-chain settlement.
- **Run payroll:** let businesses fund and authorize dollar payouts while recipients remain in control of their wallets.
- **Access Ondo Stocks (staged):** once live trading is activated, eligible users can buy from cUSD+ and return sale proceeds to cUSD+ through a dedicated router with an explicit fixed 0.30% Confío fee on every completed purchase and sale.
- **Participate in the ecosystem:** use the fixed-supply $CONFIO token for presale allocations, rewards, and disclosed ecosystem functions. $CONFIO does not back cUSD, cUSD+, or user dollar balances.

## Why Confío is different

### User-controlled money

Wallet keys are generated on the user's device, not held by Confío. Encrypted recovery material is stored in the user's personal cloud account, supporting familiar Google or Apple sign-in and device recovery without turning Confío into the wallet custodian.

### Crypto complexity stays behind the interface

Normal in-app transactions are sponsored. Confío uses EIP-7702 signed batches for multi-step actions while keeping the user's authorization explicit and bounded. Users interact with dollar amounts and familiar actions rather than gas tokens, allowances, and contract calls.

### Local access, not a generic global interface

Confío integrates country-specific bank, QR, and payment methods for Latin America and international access for diaspora corridors. Product surfaces, eligibility, and payment methods adapt to local operating realities.

### Distribution through trust

Confío is built around a founder-led Spanish-language distribution channel and a long-running public relationship with the region it serves. The product competes on trust, local fit, and direct education rather than feature parity or cashback subsidies alone.

### Public by default

The mobile application, backend, smart contracts, and core documentation are open source. Deployed contracts are source-verified, and material control boundaries and risks are documented publicly.

## Product architecture

| Component | Role |
| --- | --- |
| **USDT on BNB Smart Chain** | External funding, liquidity, and exit asset; the app automatically converts incoming USDT into the appropriate Confío dollar |
| **cUSD** | Universal payment dollar backed 1:1 by USDT, used when USDY exposure is unavailable or unsuitable |
| **cUSD+** | USDY-backed savings wrapper for Ondo-eligible users |
| **Payment, payroll, invite, and presale contracts** | cUSD/cUSD+ settlement, merchant and payroll fees, invitation escrow, and cUSD-funded presale purchases |
| **Ondo Stocks router** | Staged user-authorized purchases from cUSD+ and sales back into cUSD+, with a fixed 0.30% explicit fee |
| **$CONFIO** | Fixed-supply community and ecosystem token, separate from dollar backing |
| **Sponsored transaction layer** | User-authorized EIP-7702 batches with network fees paid by Confío |

The product followed Ondo's production infrastructure onto BNB Smart Chain: USDY, the InstantManager subscription and redemption path, its reference-price oracle, and BSC-USDT liquidity. cUSD is the universal payment layer and cUSD+ is its eligible savings wrapper. Every external USDT conversion into or out of this dollar system pays 0.9%; internal sends and cUSD/cUSD+ conversions cost 0%. Payments, payroll, transfers, and $CONFIO were consolidated onto the same network to avoid bridges and fragmented balances inside the consumer experience.

## Verified BNB Smart Chain contracts

| Contract | Address |
| --- | --- |
| cUSD vault (UUPS proxy) | [`0x6101cC37…8d543F`](https://bscscan.com/address/0x6101cC370635cF2c7f2725EaB010aC407A8d543F#code) |
| cUSD+ vault | [`0x3C29417e…63Ed1`](https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code) |
| Ondo Stocks router (UUPS proxy) | [`0x40c8e134…29c3`](https://bscscan.com/address/0x40c8e134BCAf44EEf9e7D184846F36c9862329c3#code) |
| $CONFIO token | [`0xCcEb3F61…B3fa8`](https://bscscan.com/token/0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8) |
| $CONFIO presale vault | [`0x8c3A1fff…aC0358`](https://bscscan.com/address/0x8c3A1fffcFfE1B07108486Be85C0dC42B4aC0358#code) |
| $CONFIO reward vault | [`0x812b8d86…De730`](https://bscscan.com/address/0x812b8d86952123bED0a33E92a76211cbbACDe730#code) |
| $CONFIO vesting vault | [`0xb873e4db…0bE7A`](https://bscscan.com/address/0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A#code) |
| Invitation escrow | [`0xe6c49CcE…8AcDb59`](https://bscscan.com/address/0xe6c49CcEb57b86dfE2F597053f8f475F18AcDb59#code) |
| Merchant payments | [`0x942BF5F3…5B830bA`](https://bscscan.com/address/0x942BF5F3C9079Ab29492324B9F1E501Db5B830bA#code) |
| Payroll vault | [`0x851e1a56•692027`](https://bscscan.com/address/0x851e1a56De5c0ADBB75e904B2E7325e132692027#code) |
| Sponsored-batch delegate | [`0xC06BD197…bc00`](https://bscscan.com/address/0xC06BD197b34a587026615C6AEd21301F5E99bc00#code) |

See the [deployment record](contracts/cusd_plus/DEPLOYMENT.md) for implementation addresses, migrations, superseded deployments, transaction references, and operational status.

## Repository map

| Path | Contents |
| --- | --- |
| [`apps/`](apps/) | React Native application for iOS and Android |
| [`config/`](config/) and backend packages | Django, GraphQL, authentication, payments, compliance, notifications, and operations |
| [`contracts/cusd_plus/`](contracts/cusd_plus/) | Solidity contracts, Foundry tests, deployment scripts, and BSC records |
| [`web/`](web/) | Public website and web product surfaces |
| [`workers/`](workers/) | Background and scheduled workloads |
| [`docs/`](docs/) | Product, security, legal, infrastructure, and operating documentation |

The repository still contains Algorand code and documentation used by the earlier product architecture and its migration. Those directories remain for historical verification and migration support; they are not the current settlement architecture described above.

## Documentation

- **Whitepaper:** [English — authoritative original](docs/whitepaper/README.md) · [Español](docs/whitepaper/README.es.md) · [한국어](docs/whitepaper/README.ko.md)
- **$CONFIO tokenomics:** [English — authoritative original](docs/tokenomics/README.md) · [Español](docs/tokenomics/README.es.md) · [한국어](docs/tokenomics/README.ko.md)
- **Security:** [Account and authentication architecture](docs/security/ACCOUNT_AND_AUTH_DETAILS.md)
- **Contracts:** [BSC deployment record](contracts/cusd_plus/DEPLOYMENT.md)

The English whitepaper and tokenomics documents are the authoritative originals. Translations are provided for convenience and may lag behind the English versions.

## Development

Confío is a production system with external infrastructure, compliance providers, and encrypted environment configuration. A source checkout can run local components, but end-to-end payment and blockchain flows require the appropriate test credentials and services.

### Backend

```bash
python -m venv myvenv
source myvenv/bin/activate
pip install -r requirements.txt
export CONFIO_ENV=testnet
python manage.py runserver
```

Run backend tests with:

```bash
CONFIO_ENV=testnet python manage.py test
```

### Mobile application

```bash
cd apps
yarn install
CONFIO_ENV=testnet yarn start
```

In a second terminal, run `CONFIO_ENV=testnet yarn ios` or `CONFIO_ENV=testnet yarn android` after completing the native React Native setup for that platform.

### Web application

```bash
cd web
yarn install
yarn start
```

### BSC contracts

The Solidity package uses Foundry and pinned dependencies:

```bash
cd contracts/cusd_plus
npm install
npm run setup:forge-std
forge build
forge test
```

Never broadcast a deployment or administrative transaction without reviewing the current [deployment record](contracts/cusd_plus/DEPLOYMENT.md) and environment safeguards.

## Community

- Website: [confio.lat](https://confio.lat)
- TikTok: [@julianmoonluna](https://www.tiktok.com/@julianmoonluna)
- GitHub: [caesar4321/Confio](https://github.com/caesar4321/Confio)

## License

Confío is released under the [MIT License](LICENSE).

## Disclaimer

This repository and its documentation are provided for informational and software-development purposes. Nothing here is investment, legal, tax, or financial advice, an offer of securities, or a guarantee of yield, liquidity, market value, product availability, or regulatory eligibility. Product access depends on jurisdiction, identity and compliance checks, provider availability, and applicable law.
