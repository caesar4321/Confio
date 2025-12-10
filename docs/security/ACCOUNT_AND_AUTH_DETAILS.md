# Account, Authentication & Security Details

This document provides a deep dive into Confío's account system, authentication flows, and security architecture.

## 1. Authentication Flow

Confío uses a "Keyless Self-Custody" model.

### 1.1. Login Process
1.  **Social Sign-In**: Users sign in via Google or Apple. Firebase Authentication handles the OAuth flow and token exchange.
2.  **Phone Verification**: Required for enhanced security in LATAM; utilizes a Telegram-based verification system.
3.  **Key Derivation**:
    *   **User Share**: Derived from the OAuth identity (specifically the stable `sub` claim).
    *   **Server Share**: A high-entropy "pepper" stored on the server.
    *   **Result**: The client combines these locally to derive the private key. **The server never sees the private key.**

## 2. Multi-Account System

Confío supports multiple accounts per user (Personal and Business).

### 2.1. Account ID Format
*   **Personal**: `personal_{index}` (e.g., `personal_0`)
*   **Business**: `business_{businessId}_{index}` (e.g., `business_123_0`)

### 2.2. Salt Formula (Deterministic Wallet)
The wallet address is generated using a deterministic salt locked at 32 bytes (SHA-256):

```
salt = SHA256(issuer | subject | audience | account_type | business_id (if applied) | account_index)
```

**CRITICAL**: This format is chemically locked. Changing it would change all user addresses.

### 2.3. JWT Integration
Account context is embedded directly in the JWT access token to ensure security and prevent IDOR attacks.

**Payload Structure:**
```json
{
  "user_id": "123",
  "account_type": "business",
  "account_index": 0,
  "business_id": "456",
  "type": "access"
}
```

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
*   All operations verify access via `User -> BusinessEmployee`.
*   Owners are identified by `role='owner'` in the relation table, not just by account ownership.
*   The frontend adapts the UI (hiding balances/tabs) based on these permissions.

## 4. Atomic Account Switching

To prevent race conditions where the UI might show one account while the backend token is for another, the app uses **Atomic Account Switching**.

1.  **Pause**: Stop all network requests.
2.  **Switch**: Update Keychain & fetch new JWT with new context.
3.  **Clear**: Wipe local cache (Apollo).
4.  **Resume**: Restart requests with new identity.

## 5. Security Architecture Highlights

*   **Non-Custodial**: Keys exist only in client memory.
*   **Soft Delete**: Deleted accounts/businesses consume their index forever. This prevents address reuse collisions (e.g., if `business_2` is deleted, the next is `business_3`, securing the old address).
*   **Hardware Storage**: Sensitive tokens are stored using `react-native-keychain` with hardware-backed encryption.
