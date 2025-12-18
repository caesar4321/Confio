# Smart Contract Access Control & Hybrid Architecture

## Overview
This document details the access control philosophy governing the Confío Smart Contracts on Algorand. Our architecture adopts a **Hybrid Model** that balances the seamless "Gasless" user experience of Web2 with the resilience and censorship resistance of Web3.

## The Hybrid Model
Most of our contracts allow interactions via two distinct paths:
1.  **Sponsored (Gasless) Path:** The default path where the Confío backend (Sponsor) constructs transaction groups and pays the network fees (ALGO) on behalf of the user. This creates a smooth experience where users don't need to hold ALGO.
2.  **Direct (Trustless) Path:** A fallback path where any user can interact directly with the contract by constructing the transaction themselves and paying the network fees/MBR.

### Why Hybrid?
*   **Resilience:** If the Confío backend goes offline or the Sponsor account runs out of funds, the contracts remain functional. Users are not locked out of their assets; they simply revert to a standard "pay-your-own-fee" model.
*   **Censorship Resistance:** No single entity (including Confío) can prevent a valid transaction from occurring. This preserves the core value proposition of a public blockchain.
*   **Trust:** By allowing direct interaction, we prove that the contract logic is immutable and available to all, fostering trust in the system.

---

## Contract Classifications

### 1. Strictly Restricted Contracts
These contracts contain sensitive business logic or centralized accounting mechanisms where bypassing the backend could break internal state or compliance requirements. They are locked to authorized entities only.

| Contract | Access Requirement | Rationale |
| :--- | :--- | :--- |
| **Payment** (`payment.py`) | Sponsor Only | Ensures payments flow through the verified valid path and fees are correctly tracked/accumulated according to current business logic. |
| **Payroll** (`payroll.py`) | Sponsor, Admin, Business Owner, or Delegate | Protects business funds and ensures payouts adhere to the organization's defined hierarchy and rules. |
| **Vesting** (`confio_vesting_pool.py`) | Admin (Mgmt) / Beneficiary (Claim) | Administrative functions (add/revoke) are locked. Claims are semi-restricted to the specific beneficiary. |

### 2. Hybrid / Open Contracts
These contracts are designed to be public utilities where Confío provides a convenience layer (Sponsorship) but does not enforce a monopoly on execution.

| Contract | Access Paths | Rationale |
| :--- | :--- | :--- |
| **P2P Trade** (`p2p_trade.py`) | **Sponsored:** Backend pays MBR/Fees.<br>**Direct:** User pays MBR/Fees. | Allows decentralized trading even if our frontend is unavailable. Users can always complete or cancel trades they initiated. |
| **Invite & Send** (`invite_send.py`) | **Sponsored:** Backend creates invite.<br>**Direct:** User pays MBR to create. | Ensures invitations can be claimed by their intended recipient (via crypto address) regardless of backend status. |
| **Rewards** (`confio_rewards.py`) | **Sponsored:** Backend triggers claim.<br>**Direct:** User calls `claim`. | Users have a right to their allocated rewards. If the backend fails to trigger the claim, the user can self-claim on-chain. |
| **cUSD** (`cusd.py`) | **Sponsored:** Backend helps mint.<br>**Direct:** User calls `mint`/`burn`. | Maintains the 1:1 peg trustlessly. If a user holds USDC, they can always mint cUSD (and vice versa) without permission. |
| **Presale** (`confio_presale.py`) | **Sponsored:** Backend buys.<br>**Direct:** User calls `buy`. | Ensures the presale is a public event. Users can participate directly via block explorers or scripts. |

> [!IMPORTANT]
> **cUSD Minting Integrity**
> Importantly, **Confío cannot arbitrarily mint cUSD.** All minting requires verifiable USDC backing provided by the caller, even in the Sponsored (gasless) flow. The contract logic enforces a strict 1:1 collaterization check before minting any new tokens.

---

## Technical Implementation Checks
When auditing or developing new features, access control is verified using the `Txn.sender()` and `Global.group_size()` properties.

**Example: Hybrid Check (P2P Trade)**
```python
# Allows Sponsor OR Direct User
If(
    And(
        app.state.sponsor_address.get() != Bytes(""),
        Txn.sender() == app.state.sponsor_address.get()
    ),
    actual_user.store(Txn.accounts[0]), # Sponsor Call
    actual_user.store(Txn.sender())     # Direct Call
)
```

**Example: Strict Check (Payment)**
```python
# Restricted to Sponsor Only
Assert(Txn.sender() == app.state.sponsor_address.get())
```

## Conclusion
The Hybrid Architecture ensures that Confío offers a premium, managed user experience without compromising the fundamental resilience and openness of the underlying blockchain infrastructure.
