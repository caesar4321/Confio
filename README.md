# Confío: LATAM's Open Wallet for the Dollar Economy

**Confío** is an open-source Web3 wallet and transaction platform designed for Latin America.  
It enables users to **send, receive, and hold stablecoins** (cUSD (Confío Dollar)) on the **Algorand blockchain**, with zero gas fees and no crypto complexity.

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
*   **Accessible**:
    *   **WhatsApp-like Experience**: Send money to any phone contact directly.
    *   **Fiat On/Off Ramps**: Buy/Sell USDC with local payment methods and can convert it to cUSD.
*   **Business Ready**: Dedicated business accounts with employee roles (Owner, Cashier, Manager) and payroll features.

---

## 🔒 Security Architecture

Confío utilizes a **Keyless Self-Custody** model with **Server-Assisted Deterministic Recovery**.

*   **Non-Custodial**: We never store your private keys. You own your funds.
*   **2-of-2 Security**: Your key is derived from your OAuth login + a server security token. Neither Google/Apple nor Confío can access your wallet alone.
*   **Multisig Protection**: Critical smart contracts are governed by a 3-of-5 multisig setup for maximum safety.

> 📚 **Deep Dive**: [Account & Authentication Details](docs/security/ACCOUNT_AND_AUTH_DETAILS.md)

---

## 🧱 Tech Stack Overview

*   **Mobile App**: React Native (iOS/Android)
*   **Backend**: Django + GraphQL (Python)
*   **Blockchain**: Algorand (PyTeal/TEAL Smart Contracts)
*   **Infrastructure**: AWS (Zurich, SW) & Cloudflare

> 📂 **File Structure**: [View Project Structure](docs/PROJECT_STRUCTURE.md)

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
*   🔗 **Telegram**: [t.me/confio4world](https://t.me/confio4world)
*   📱 **TikTok**: [@julianmoonluna](https://tiktok.com/@julianmoonluna)

---

## 📜 License

MIT License — build freely, fork proudly, remix for your country.

## 🙏 Credits

Confío is led by Julian Moon, a Korean builder based in Latin America, inspired by the dream of trustworthy, borderless financial inclusion for everyone.
