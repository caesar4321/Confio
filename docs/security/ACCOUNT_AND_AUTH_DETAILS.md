# Account, Authentication & Security Details (V2)

This document provides a deep dive into Confío's V2 account system, authentication flows, and security architecture.

## 1. Authentication Flow

Confío uses a "Keyless Self-Custody" model (V2).

### 1.1. Login Process
1.  **Social Sign-In**: Users sign in via Google or Apple. Firebase Authentication handles the OAuth flow and token exchange.
2.  **Master Secret Retrieval**:
    *   **iOS**:
        *   **Google Sign-In**:
            1.  **Check Google Drive** (App Data Folder) via OAuth Access Token.
            2.  If found in Drive -> Sync to Keychain.
            3.  If missing, check **iCloud Keychain** (`confio_master_secret`).
        *   **Apple Sign-In**:
            1.  **Check iCloud Keychain** (`confio_master_secret`).
            2.  Drive check is skipped (No Access Token).
            3.  If missing -> Generate **New Random** Secret -> Save to Keychain.
    *   **Android**:
        1.  **Check Google Drive** (App Data Folder).
        2.  If found -> Sync to Local.
        3.  If missing, check **Encrypted BlockStore** / SharedPreferences.
        4.  If found locally -> Sync Up to Drive.
        5.  If not found -> Generate **New Random** Secret -> Save to Local & Drive.
3.  **Session & JWT**:
    *   Once the Master Secret is secured locally, the app proceeds to authenticated API requests using the Firebase ID Token (exchanged for a Confío Session Cookie/JWT).

## 2. Multi-Account System

Confío supports multiple accounts per user (Personal and Business).
In V2, all accounts are derived from the **Single Master Secret**.

### 2.1. Account ID Format
*   **Personal**: `personal_{index}` (Example: `personal_0`)
*   **Business**: `business_{businessId}_{index}` (Example: `business_123_0`)

### 2.2. Address Derivation Formula (V2)
Unlike V1 (Identity-based), V2 uses a **Master Secret** + **HKDF** derivation.

**Inputs:**
*   **IKM (Input Key Material)**: The 32-byte Random Master Secret.
*   **Context String**: `confio_v2_salt_{account_type}_{business_id}_{index}`

**Algorithm:**
```typescript
// 1. Generate Contextual Salt
ValidationSalt = SHA256(context_string)

// 2. HKDF Key Derivation
DerivedSeed = HKDF_SHA256(
    IKM = MasterSecret,
    Salt = ValidationSalt,
    Info = "confio|v2|derived|" + context_string,
    Length = 32 bytes
)

// 3. Ed25519 Keypair
KeyPair = Ed25519.fromSeed(DerivedSeed)
AlgorandAddress = Encode(KeyPair.publicKey)
```

**Security Property:**
*   **Isolation**: Compromising a derived key (e.g., `personal_0`) does not reveal the Master Secret or other accounts (`business_0`).
*   **Determinism**: The same Master Secret always yields the same addresses for the same accounts.

### 2.3. JWT Integration
Account context is embedded directly in the backend JWT access token to ensure security and prevent IDOR attacks.
*   The backend does NOT know the Master Secret.
*   The backend ONLY knows the User ID (Firebase UID) and Account permissions.

## 3. Business Employee System

Business accounts allow multiple employees with role-based access.

### 3.1. Roles & Permissions
A "negative-check" system is used. If a permission is not explicitly granted, it is denied.

| Role | Key Permissions | Limitations |
| :--- | :--- | :--- |
| **Owner** | All | None |
| **Admin** | Most (Payments, View, Manage) | Cannot delete business |
| **Manager** | Operational (Payments, View) | Cannot manage employees or edit info |
| **Cashier** | Payments Only | Cannot view balance or history |

### 3.2. Security Pattern
*   All operations verify access via `User -> BusinessEmployee` relation in Postgres.
*   The crypto wallet signing happens **Client-Side**. The employee's app derives the business wallet address using the Business Owner's Master Secret? **NO.**
*   **Correction**: Business Wallets in V2 for *Employees* are Multi-Sig or Permissioned via Smart Contract?
    *   *Current Implementation*: Employees act on behalf of the business via **API Permissions** (Off-chain ledger) for fiat/internal transfers.
    *   For on-chain operations, the Owner's device signs. Employees do not hold the business private key.

## 4. Atomic Account Switching

To prevent race conditions where the UI might show one account while the backend token is for another, the app uses **Atomic Account Switching**.

1.  **Pause**: Stop all network requests.
2.  **Switch**: Update Keychain & fetch new JWT with new context.
3.  **Clear**: Wipe local cache (Apollo).
4.  **Resume**: Restart requests with new identity.

## 5. Security Architecture Highlights (V2)

### 5.1. Token Isolation
*   **Firebase ID Token**: Sent to Server. Used for API Authentication. **Cannot** access Google Drive.
*   **Google OAuth Access Token**: **NEVER** sent to Server. Used strictly on Client to access Google Drive AppData for wallet backup.

### 5.2. Storage Hierarchy
1.  **RAM (Memory)**: Decrypted Master Secret (Milliseconds duration during signing).
2.  **Secure Hardware (Keychain/Keystore)**: Encrypted Master Secret (At Rest on Device).
3.  **Cloud (Drive/iCloud)**: AES-Encrypted Master Secret (At Rest in Cloud).
4.  **Server**: **Zero Knowledge**. The server stores no keys, no seeds, no backup files.

### 5.3. Conflict Resolution
*   If a user has a V1 Wallet (Legacy) and creates a V2 Wallet, the app detects this and initiates a "Sweep Migration" to move assets to V2.
*   V1 Wallets are deprecated and will eventually be phased out.
