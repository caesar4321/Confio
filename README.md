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

## 🧠 Project Structure

This is a **monolithic repository** containing the full Confío stack:

```bash
/Confío/
├── apps/         # React Native wallet app
├── contracts/    # Sui Move smart contracts (cUSD, escrow, etc.)
├── relay/        # Django backend (tx sponsor, Firebase JWT check, etc.)
└── README.md
```

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
a Korean builder based in Latin America, inspired by the dream of a trustworthy, borderless dollar economy for everyone. 