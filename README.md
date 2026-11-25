# Confío

**The personal assistant that pays in Latin America.**

[Website](https://confio.lat) · [Whitepaper](docs/whitepaper/README.md) · [Tokenomics](docs/tokenomics/README.md) · [BNB Smart Chain deployments](contracts/cusd_plus/DEPLOYMENT.md)

Personal AI assistants that act for people are arriving: they search, remind, contact businesses and build carts. In Latin America the errand stops at the payment, because everyday money moves on national rails (Pix, SPEI, Pago Móvil, bank QR, Bre-B) that card-based agent checkouts do not reach.

Confío IA runs the errand and finishes it by paying: the store, the merchant or the person, on that country's own rail, from a dollar balance only the user controls. Every payment needs the user's exact confirmation or stays within limits they signed on-chain. Confío is fully open source and non-custodial.

*La confianza ya existe. Falta un sistema que la merezca.* — Trust already exists. What’s missing is a system that deserves it. · *Confío en vos.*

## What Confío IA does

| Job | How it works |
| --- | --- |
| **Buy at online stores** | A shopping agent searches one or several stores in a cloud browser, builds the cart, shows the real total with shipping, and pays the store on its rail: SPEI in Mexico, Pix in Brazil, Pago Móvil in Venezuela. In Bolivia it places the order and the user pays the store's QR. |
| **Pay people, QR codes and merchants** | The assistant prepares a send or a local-rail payment as a card in the chat. Code, not the model, asks the amount and checks the payee; the user confirms and signs on their own phone. |
| **Shop locally** | Comprar, an in-app marketplace with escrow-held payments and buyer protection, piloting in Bolivia. |
| **Top up and withdraw** | The chat opens the top-up or withdrawal form with the country's live provider limits. |
| **Invest** | Stocks (Ondo Global Markets), gold and bitcoin as priced cards in the chat. |
| **Automate with Cuenta inteligente** | A per-user smart account where the assistant executes within caps the owner signed once: store purchases, hands-off trades within a weekly cap, scheduled payments and payouts, automatic investing, and a named beneficiary. |

Linking the user's own WhatsApp, Gmail and calendar, so the assistant can say what needs attention and draft replies, is rolling out with new app builds.

## Why an assistant can be trusted to pay

### The rules are in code and on-chain, not in the model

The model proposes; code decides. Amounts are asked by code and answered in writing, payees are validated before a card exists, and nothing moves without the user's signature or an on-chain rule they signed. Cuenta inteligente accounts are immutable clones whose caps are constants: a leaky-bucket weekly trade cap where buys and sells both count, price bands against Chainlink feeds, owner alerts on every hands-off action, and a Safe-held kill switch (`tradePaused`).

### User-controlled money

Wallet keys are generated on the user's device, not held by Confío. Encrypted recovery material lives in the user's own Google or Apple cloud account, so familiar sign-in and device recovery work without making Confío the custodian.

### Local rails, not a generic global checkout

Confío integrates each country's bank, QR and instant-payment methods, with live provider switches deciding what the assistant offers in each country, plus international access for diaspora corridors.

### Crypto stays behind the interface

Network fees are sponsored. Multi-step actions are EIP-7702 signed batches with explicit, bounded authorization. Users see dollar amounts and familiar actions, never gas, allowances or addresses.

### Distribution through trust

Confío grows through a founder-led Spanish-language channel and a long public relationship with the region it serves, competing on trust and local fit rather than subsidies.

### Public by default

The mobile app, backend, smart contracts and core documentation are open source. Deployed contracts are source-verified, and control boundaries and risks are documented publicly.

## The dollar balance underneath

| Component | Role |
| --- | --- |
| **USDT on BNB Smart Chain** | External funding, liquidity and exit asset; incoming USDT is converted to the user's Confío dollar automatically |
| **cUSD** | Universal payment dollar backed 1:1 by USDT, and the single 0.9% entry/exit fee perimeter |
| **cUSD+** | USDY-backed accumulating dollar for Ondo-eligible users; moving between cUSD and cUSD+ is free; yield is variable and not guaranteed |
| **Cuenta inteligente** | Per-user immutable smart account (factory per generation, owner-signed `migrate()` to v2) where the assistant executes within signed caps |
| **Payment, payroll, invite, purchase and Comprar contracts** | Local-rail and merchant settlement, payroll, invitation escrow, account-paid store purchases (`ConfioPurchaseSpender`) and marketplace escrow |
| **Stock and swap routers** | Ondo Stocks bought from and sold back into the dollar balance; gold and bitcoin swaps; no router fee, the uniform 0.9% applies |
| **$CONFIO** | Fixed-supply community and ecosystem token; it does not back cUSD, cUSD+ or any user balance |
| **Sponsored transaction layer** | User-authorized EIP-7702 batches with network fees paid by Confío |

## Verified BNB Smart Chain contracts

Upgradeable contracts are owned by the 3-of-5 Safe [`0xF29A4187…b623`](https://bscscan.com/address/0xF29A418744E793973BF4eEc676F8a30B2793b623).

| Contract | Address |
| --- | --- |
| cUSD vault (UUPS proxy) | [`0x6101cC37…8d543F`](https://bscscan.com/address/0x6101cC370635cF2c7f2725EaB010aC407A8d543F#code) |
| cUSD+ vault | [`0x3C29417e…63Ed1`](https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code) |
| Ondo Stocks router (UUPS proxy) | [`0x40c8e134…29c3`](https://bscscan.com/address/0x40c8e134BCAf44EEf9e7D184846F36c9862329c3#code) |
| Gold and bitcoin swap router (proxy) | [`0xA7C27684…bF712`](https://bscscan.com/address/0xA7C27684aB38eC369cB1F4474f279ea503dbF712#code) |
| Cuenta inteligente factory (UUPS proxy) | [`0x339094A1…f953`](https://bscscan.com/address/0x339094A17605B842e0b2fc01441204E67020f953#code) |
| Cuenta inteligente account v2 | [`0x0b3DAf40…cdF7`](https://bscscan.com/address/0x0b3DAf407AF2cF5bC7a1475bF44bD3952533cdF7#code) |
| Cuenta inteligente account v1 | [`0x8a20a0B3…e44A`](https://bscscan.com/address/0x8a20a0B3d2C0c6BED8BeB00bB6Bc7AE3c7ace44A#code) |
| Cuenta inteligente fee collector | [`0x1AE0ACB8…39CD`](https://bscscan.com/address/0x1AE0ACB82bAb9F506188c49305953CB655A539CD#code) |
| Purchase spender | [`0xD0ea8Ec3…32Ca`](https://bscscan.com/address/0xD0ea8Ec3a6F3AD49f13a18Ce801C9594311A32Ca#code) |
| Comprar escrow (UUPS proxy) | [`0x2DFDC1fB…99Fd`](https://bscscan.com/address/0x2DFDC1fB809322c12f54beFE8CC98E0d103a99Fd#code) |
| Sponsored-batch delegate | [`0xC06BD197…bc00`](https://bscscan.com/address/0xC06BD197b34a587026615C6AEd21301F5E99bc00#code) |
| Emergency-exit heartbeat (proxy) | [`0xAE49E3AD…20FF`](https://bscscan.com/address/0xAE49E3AD57531974CD2AEc2633b03770fF4a20FF#code) |
| $CONFIO token | [`0xF5765933…06101`](https://bscscan.com/token/0xF5765933764562A51e179F6AF2b19b7a3d506101) |
| $CONFIO presale vault | [`0xB13Cda84…F18b4`](https://bscscan.com/address/0xB13Cda84348609c534aD1eFA9D4D39a62b2F18b4#code) |
| $CONFIO reward vault | [`0x3E022ADD…6AA49`](https://bscscan.com/address/0x3E022ADD4b3ae8618e431D83004e2aeb5F76AA49#code) |
| $CONFIO vesting vault | [`0x873A6818…6D75a`](https://bscscan.com/address/0x873A68182A384DD84385C7B610Df5D2A3746D75a#code) |
| Invitation escrow | [`0xe6c49CcE…8AcDb59`](https://bscscan.com/address/0xe6c49CcEb57b86dfE2F597053f8f475F18AcDb59#code) |
| Merchant payments | [`0x942BF5F3…5B830bA`](https://bscscan.com/address/0x942BF5F3C9079Ab29492324B9F1E501Db5B830bA#code) |
| Payroll vault | [`0x851e1a56…692027`](https://bscscan.com/address/0x851e1a56De5c0ADBB75e904B2E7325e132692027#code) |

See the [deployment record](contracts/cusd_plus/DEPLOYMENT.md) and the [Cuenta inteligente v2 deployment](docs/deploy/hands-off-v2-deploy.md) for implementation addresses, migrations, superseded deployments and transaction references.

## Repository map

| Path | Contents |
| --- | --- |
| [`apps/`](apps/) | React Native application for iOS and Android |
| [`config/`](config/) and backend packages | Django, GraphQL, authentication, payments, compliance, notifications, and operations |
| [`assistant/`](assistant/) | Confío IA: the chat engine, payment and trade proposals, and the code-side confirmations |
| [`agent_tasks/`](agent_tasks/) | The shopping agent: cloud-browser store purchases and local-rail checkout |
| [`smart_account/`](smart_account/) | Cuenta inteligente server side: rules, hands-off relays, reconciliation, notifications |
| [`contracts/smart_account/`](contracts/smart_account/) | Cuenta inteligente accounts, factory and purchase spender (Foundry) |
| [`contracts/cusd_plus/`](contracts/cusd_plus/) | Dollar vaults, routers, payments, payroll, Comprar escrow and $CONFIO contracts, Foundry tests, deployment scripts, and BSC records |
| [`web/`](web/) | Public website and web product surfaces |
| [`workers/`](workers/) | Background and scheduled workloads |
| [`docs/`](docs/) | Product, security, legal, infrastructure, and operating documentation |

The repository still contains Algorand code and documentation used by the earlier product architecture and its migration. Those directories remain for historical verification and migration support; they are not the current settlement architecture described above.

## Documentation

- **Whitepaper:** [English — authoritative original](docs/whitepaper/README.md) · [Español](docs/whitepaper/README.es.md) · [한국어](docs/whitepaper/README.ko.md)
- **$CONFIO tokenomics:** [English — authoritative original](docs/tokenomics/README.md) · [Español](docs/tokenomics/README.es.md) · [한국어](docs/tokenomics/README.ko.md)
- **Security:** [Account and authentication architecture](docs/security/ACCOUNT_AND_AUTH_DETAILS.md)
- **Sign-in and phone recovery:** [Current wallet reconciliation and verified phone relinking](docs/signin-wallet-reconciliation.md) · [EC2 rollout](docs/deploy-ec2-ubuntu-systemd.md)
- **Institutional collections (pilot):** [Plan](docs/payments/RECURRING_PAYMENT_PLATFORM_PLAN.md) · [API contract](docs/payments/openapi-v1.yaml) · [Sandbox and operations](docs/payments/BILLING_OPERATIONS_RUNBOOK.md)
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
