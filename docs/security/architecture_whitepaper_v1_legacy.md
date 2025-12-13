# Confío Security Architecture: Keyless Self-Custody

## Execution Summary

Confío utilizes a **Keyless Self-Custody** model with **Server-Assisted Deterministic Recovery**. 

This architecture is designed to address the specific constraints of the Latin American mass market:
1.  **Zero-Friction Onboarding**: No passwords, seed phrases, or specialized hardware required.
2.  **Device Independence**: Users frequently lose devices, change SIM cards, and share phones. Wallets must be recovering using only a standard OAuth login (Google/Apple).
3.  **Non-Custodial Integrity**: The server never stores user private keys at rest and cannot sign transactions on behalf of users.

## Architectural Definition

**"Keyless Self-Custody with Server-Assisted Deterministic Recovery"**

We define our security model based on the industry standard for "Non-Custodial" services (similar to remote-prover zkLogin implementations or early OAuth-based keyless wallets):

> **A service is Non-Custodial if the server cannot sign transactions on behalf of the user and does not persist the private key.**

### 2-of-2 Component Split

The user's private key is derived deterministically on the client device using two components. Neither component alone can derive the key.

1.  **User Share (OAuth Context)**
    *   **Source**: Authenticated Google/Apple Identity Token.
    *   **Derivation**: `SHA256(Issuer | Subject | Audience | AccountContext)`.
    *   **Privacy**: 
        *   **Apple**: The Subject (`sub`) is App-Scoped and private to the developer team. It acts as a private user identifier.
        *   **Google**: The Subject (`sub`) is only provided upon successful authentication. There is no public API to resolve email addresses to Subject IDs.
    *   **Role**: proves "Who I am" (Identity).

2.  **Server Share (Derivation Pepper)**
    *   **Source**: Confío Secure Server (Database).
    *   **Encryption**: AES-256 (Fernet) encrypted at rest using a master key stored in **AWS SSM Parameter Store**, protected by **AWS KMS**.
    *   **Nature**: High-entropy 32-byte secret, unique per account, non-rotating.
    *   **Role**: Enforces "Authorized Access" and acts as a cryptographic blinder against `sub` discovery.

### Key Derivation Process

```typescript
// Happens ONLY in Client Memory
Seed = HKDF(
    IKM = UserShare (OAuth Claims),
    Salt = ServerShare (Derivation Pepper),
    Info = Context
)
Keypair = Ed25519(Seed)
```

## Security Guarantees & Trade-offs

### 1. Resilience to Database Leaks (High)
A critical feature of this architecture is its resilience to server-side static data breaches.
*   **Leak**: Attacker gains `WalletDerivationPepper` and `Email` from the database.
*   **Requirement**: Attacker needs the `UserShare` (specifically the OAuth `Subject`) to derive the key.
*   **Defense**: The `Subject` is **undetectable via OSINT**.
    *   **Apple**: Impossible to derive `sub` from Email (App-Scoped).
    *   **Google**: No API exists to convert Email to `sub` without user authentication.
*   **Result**: The stolen database information is useless for key derivation without the User Share, which remains protected by the Identity Provider's authentication barrier.

### 2. Non-Custodial Properties
*   **No Private Key Storage**: The Confío server **never** persists the derived private key or seed using disk storage. It exists only momentarily in the client's volatile memory.
*   **No Server-Side Signing**: The server does not possess the logic or capability to sign transactions. All signing happens on the client device (React Native).

### 3. Server-Assisted Recovery (The Trade-off)
To enable "Device-Independent Recovery", we accept a specific trade-off:
*   **Theoretical Reconstruction**: If an attacker gains full Remote Code Execution (RCE) *during* a user's active login, they could intercept the token and pepper to reconstruct the key.
*   **Justification**: This "Active Compromise" risk is significantly lower than the "Passive Data Breach" risk (which we have mitigated) and the "User Error/Loss" risk (which we have eliminated).

## Conclusion

Confío's model properly balances mass-market UX with robust security. By leveraging the **non-discoverability of OAuth Subjects** and combining it with a **Server Pepper**, we achieve a practical "2-of-2" security split where a database breach does *not* result in fund loss, fulfilling the core promise of non-custodial security without the burden of seed phrase management.
