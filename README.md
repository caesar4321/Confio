# Confío: LATAM's Open Wallet for the Dollar Economy

**Confío** is an open-source digital-dollar wallet and transaction platform
designed for Latin America. It uses **cUSD on Algorand** for everyday payments
and **cUSD+ on BNB Smart Chain** for USDY-backed dollar savings, with sponsored
network fees and no crypto complexity.

Built for real people — not just crypto experts.

---

## 🌎 Why Confío?

In countries like Venezuela, Argentina, and beyond, inflation erodes trust in local currencies.
Confío helps people access stable dollars, send remittances, and pay each other — simply and safely — using blockchain.

> "Confío" means **"I trust"** in Spanish.
> We open-source everything because **trust must be earned, not assumed**.

---

## 🚀 Key Features

*   **Zero Complexity**: Log in with Google/Apple. No seed phrases to lose.
*   **Gasless**: We sponsor transaction fees. Users just send money.
*   **Stable**: cUSD (Confío Dollar) 1:1 backed by USDC.
*   **Savings**: cUSD+ provides eligible users with variable USDY-backed yield exposure on BNB Smart Chain.
*   **Accessible**:
    *   **WhatsApp-like Experience**: Send money to any phone contact directly.
    *   **Fiat On/Off Ramps**: Buy/Sell USDC with local payment methods and can convert it to cUSD.
*   **Business Ready**: Dedicated business accounts with employee roles (Owner, Cashier, Manager) and payroll features.

---

## 🔒 Security Architecture

Confío utilizes a **Cloud-Native Self-Custody** model.

 *   **Non-Custodial**: We never store your private keys. You own your funds.
 *   **Device-Generated**: Your key is generated on your device and encrypted in your personal cloud (Google Drive / iCloud). Only you have access.
 *   **Governed Contracts**: Critical operations use multi-party approval, including transparent Safe governance for cUSD+.

> 📚 **Deep Dive**: [Account & Authentication Details](docs/security/ACCOUNT_AND_AUTH_DETAILS.md)

---

## 🧱 Tech Stack Overview

*   **Mobile App**: React Native (iOS/Android)
*   **Backend**: Django + GraphQL (Python)
*   **Blockchains**: Algorand (payments) + BNB Smart Chain (cUSD+ savings)
*   **Infrastructure**: AWS (Zurich, SW) & Cloudflare

> 📂 **File Structure**: [View Project Structure](docs/PROJECT_STRUCTURE.md)

---

## 📚 Documentation

*   **[English Whitepaper](docs/whitepaper/README.md)**: Product thesis, multi-chain architecture, business model, operating metrics, risks, and roadmap.
*   **[Documentation Index](docs/README.md)**: Technical, security, legal, product, and operational references.
*   **[Smart Contracts](contracts/README.md)**: Contract packages and product-specific deployment documentation.

---

## 🛠️ Usage & Development

### Environment Setup (`CONFIO_ENV`)

Confío loads settings based on the `CONFIO_ENV` flag.

| Environment | Use Case |
| :--- | :--- |
| `mainnet` | Production (Default) |
| `testnet` | Local Development & QA |

**Local Development Command**:
```bash
# Always set this for local dev!
export CONFIO_ENV=testnet

# Run Backend
python manage.py runserver

# Run Mobile App
cd apps && CONFIO_ENV=testnet yarn ios
```

---

## 💬 Join the Community

Confío is more than a wallet — it's a mission to bring financial confidence to Latin America.

*   🌐 **Website**: [confio.lat](https://confio.lat)
*   📱 **TikTok**: [@julianmoonluna](https://tiktok.com/@julianmoonluna)

---

## 📜 License

MIT License — build freely, fork proudly, remix for your country.

## 🙏 Credits

Confío is led by Julian Moon, a Korean builder based in Latin America, inspired by the dream of trustworthy, borderless financial inclusion for everyone.
