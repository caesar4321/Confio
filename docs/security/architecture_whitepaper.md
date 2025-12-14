# Confío Security Architecture V2: Enhanced Keyless Self-Custody

## 1. Executive Summary

Confío operates on a **Non-Custodial, Mobile-First** security model. 

In the **V2 Architecture (Current)**, we moved from deterministic key generation to **Randomly Generated Master Secrets** backed up securely to the user's personal cloud storage (Google Drive / iCloud). This ensures true device independence ("Roaming"), resilience against OAuth claim instability, and complete user sovereignty over their assets.

## 2. Wallet Architecture (V2)

### 2.1. Master Secret Generation
- **Method**: Unpredictable Randomness (via `react-native-get-random-values` / `tweetnacl`).
- **Secret**: 32-byte high-entropy Master Secret.
- **Derivation Path**: Chain-specific derivation using the native SDK (Ethereum: BIP-44, Algorand: Ed25519 direct derivation).

### 2.2. Hybrid Storage Strategy
To support seamless roaming between iOS and Android while maintaining high security, we use a hybrid storage approach:

1.  **Local Hardware Storage (Hot Wallet)**
    *   **iOS**: iCloud Keychain (`react-native-keychain`).
    *   **Android**: Encrypted SharedPreferences / BlockStore.
    *   **Security**: Protects the active key for signing daily transactions.

2.  **Cloud Backup (Encrypted Backup / Recovery)**
    *   **Android**: **Google Drive AppData Folder** (Hidden from user view).
    *   **iOS**: **iCloud Keychain** (Synced via Apple ID) + **Google Drive Fallback**.
    *   **Encryption**: The Master Secret is **AES-Encrypted** with a static application key before being uploaded to Google Drive.
        *   *Note*: This encryption is intended as obfuscation against casual access and accidental exposure. It does not provide protection against a fully compromised client environment (RCE), which is an accepted trade-off to preserve usability (no backup password).
    *   **Scope**: Uses `https://www.googleapis.com/auth/drive.appdata` to isolate data from other apps.
    *   **Token Isolation**: The Google Drive OAuth Access Token is retained strictly within the mobile client memory and is **never** sent to the application server.

### 2.3. Cross-Platform Roaming
A unique feature of Confío V2 is **optional cross-platform roaming**, enabled through explicit user-consented cloud backup.

*Note: Cross-platform restoration requires explicit user action. Automatic synchronization between Apple iCloud and Google Drive is not assumed.*

1.  **Android -> iOS**: When logging in on iOS, the user can restore a wallet if they previously enabled Google Drive backup on Android.
2.  **iOS -> Android**: Keys generated on iOS are strictly in iCloud by default. To roam to Android, the user must explicit enable "Respaldo en la Nube" (Google Drive Backup) in the iOS app settings, secured by biometrics.

## 3. Legacy Architecture (V1) & Migration

*Ref: `architecture_whitepaper_v1_legacy.md`*

### 3.1. V1 Design (Deprecated)
The V1 system generated keys deterministically combining:
*   **User Share**: OAuth `sub` claim (Google/Apple ID).
*   **Server Share**: A database-stored high-entropy "pepper".
*   **Weakness**: Relied on server uptime for the pepper and consistent OAuth claim formats. Lack of portability between providers.

### 3.2. Migration Process
When a V1 user logs in to the V2 app:
1.  **Detection**: App detects `legacy` wallet existence.
2.  **Generation**: App generates a NEW V2 (Random) Master Secret.
3.  **Sweep**: App constructs a transaction to send ALL assets from V1 Address -> V2 Address.
4.  **Finalize**: User footprint is now fully V2.

## 4. Authentication & Access Control

### 4.1. Identity Providers
*   **Google Sign-In**: Primary identity provider.
*   **Apple Sign-In**: iOS alternative.
*   **JWT**: We use Firebase Authentication to verify identity, then issue a custom **Confío JWT** for API access.

### 4.2. API Security
*   **Token**: Short-lived (15 min) Access Token.
*   **Refresh**: Secure HttpOnly cookie refresh token flow.
*   **Context**: The JWT embeds the specific `account_id` (Personal vs Business) to prevent IDOR at the gateway level.

### 4.3. Biometric Layer
*   **Implementation**: `react-native-keychain` + `LocalAuthentication`.
*   **Strategy**: **Application-Level Enforcement**.
    *   **Storage (iOS)**: Keys stored with `kSecAttrAccessibleAfterFirstUnlock` to allow background signing (e.g. while receiving notifications) without prompting the user every time.
    *   **Authorization**: Sensitive actions (Backup toggle, etc.) trigger an explicit `LocalAuthentication` prompt via the App logic.
*   **Usage**: Required for:
    *   Enabling/Disabling Cloud Backup.
    *   High-value transactions (configurable).

## 5. Threat Model & Mitigations

| Threat | Risk Level | Mitigation |
| :--- | :--- | :--- |
| **Server Database Leak** | Low | V2 Private Keys are **never** stored on the server. An attacker with the database gets 0 user funds. |
| **Google Drive Compromise** | Medium | The backup file in Drive is AES-Encrypted with a separate application key. Raw JSON access is insufficient to steal funds without the app/encryption logic. |
| **Lost Device** | Medium | User can restore wallet on a new device by logging into their Cloud Account (Google/Apple). Biometrics prevent thief from accessing wallet on the lost device. |
| **Simulated Biometrics** | Low | We use hardware-backed Keystore/Keychain which requires cryptographic proof of biometric auth, not just a UI flag. |
| **Malicious Update** | High | Standard supply chain risk. Mitigated by App Store reviews and code signing. |

### 5.1. Residual Risks & Limitations
*   **Encrypted Backup Weakness**: The "Encrypted Backup" uses a static application key (`APP_BACKUP_KEY`) for obfuscation.
    *   **Risk**: If a user's Google/Apple Account is compromised **AND** the attacker extracts the key from the app binary, the backup can be decrypted.
    *   **Dependence**: Security of the backup ultimately relies on the User's Cloud Account security (Strong Password + 2FA).
*   **Rooted/Jailbroken Devices**: On devices where the user has granted root access, OS-level protections (Keychain/BlockStore) can be bypassed by malicious apps. We assume a standard, non-rooted security environment.

## 6. Smart Contract Security

*   **Platform**: Algorand Virtual Machine (AVM / TEAL).
*   **Admin Control**: Critical contracts (USDC, Rewards) are managed by a **Multi-Signature Account (3-of-5)**.
*   **Assets**:
    *   **USDC**: Standard Circle USDC (ASA).
    *   **cUSD**: Confío Dollar (ASA). 1:1 backed by USDC.
    *   **CONFIO**: Utility/Reward Token (ASA).
*   **Permissions**: Contracts utilize `LogicSig` (Stateless Smart Contracts) for delegated signing and `Application` (Stateful) for logic.

## 7. Operational Security

*   **Logs**: No PII or Key material in logs.
*   **Infrastructure**: AWS (EC2/RDS) inside VPC.
*   **Secrets**: AWS Secrets Manager / Parameter Store.
