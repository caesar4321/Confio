# Security Review V2: Keyless Self-Custody & Cloud Backup

## 1. Executive Summary

**Architecture:** V2 Random Wallet with Cloud Backup (Google Drive/iCloud).
**Custody Model:** Strict Non-Custodial (Server has 0 knowledge of keys).
**Verdict:** The V2 system significantly improves upon V1 by removing the server from the key derivation loop completely. Security now relies entirely on the user's device security (Biometrics) and their cloud provider account (Google/Apple).

## 2. Threat Model & Risks

### 2.1. Cloud Account Compromise (Primary Risk)
In the V2 model, the user's Master Secret is backed up to Google Drive (AppData folder) or iCloud.
*   **Risk**: If an attacker gains full access to the user's Google Account, they can download the backup file.
*   **Mitigation**:
    *   **File Encryption**: The backup file is AES-256 encrypted before upload.
    *   **Weakness**: The encryption key is embedded in the application source code. A sophisticated attacker who reverse-engineers the app AND compromises the Google Account can decrypt the wallet.
    *   **Context**: This encryption is intended as obfuscation against casual access and accidental exposure, not as a substitute for a user-held encryption password. It does not provide protection against a fully compromised client environment, which is an accepted trade-off to preserve usability.
    *   **Defense in Depth**: Users are encouraged to use 2FA on their Google Accounts. Furthermore, Firebase Authentication tokens do not grant access to Google Drive APIs and are never used for key storage or recovery. Only the specific Google OAuth Access Token (requested explicitly) can access the Drive AppData folder. **Crucially, this Access Token is consumed exclusively on the client device and is NEVER transmitted to the Confío backend servers.**

### 2.2. Local Device Compromise (Theft)
*   **Risk**: User's phone is stolen while unlocked.
*   **Defense**:
    *   **Biometric Gate**: Critical actions (backup export, secret reveal, large transfers) require Biometric Authentication.
    *   **Secure Storage**: Keys are stored in Hardware-backed Keystore/Keychain.
    *   **Result**: Even with the phone, the attacker cannot extract the private key without the user's fingerprint/face.

### 2.3. Server Compromise
*   **Risk**: Attacker gains full control of Confío servers (EC2, RDS).
*   **Impact**:
    *   **Funds**: **Zero Access**. The server stores no keys, no peppers (for V2), and no backup files.
    *   **Data**: Attacker can see transaction history and user contacts.
    *   **Service**: Attacker can disrupt service (DoS).

## 3. Implementation Security

### 3.1. Master Secret Handling
*   **Generation**: Uses `react-native-get-random-values` (CSPRNG).
*   **Lifecycle**:
    1.  Generated in memory.
    2.  Written to Secure Storage (Keychain).
    3.  Encrypted & Uploaded to Drive.
    4.  Wiped from memory.

### 3.2. Biometric Integration
*   **Library**: `react-native-keychain`.
*   **Config**:
    *   **iOS**: `kSecAccessControlUserPresence`. Keys are bound to the device passcode/biometrics.
    *   **Android**: `BiometricPrompt`.
*   **Edge Case**: "Passcode Fallback". On iOS, we allow passcode fallback if biometrics fail, to prevent lockout. On Android, we enforce strong biometrics where available.

### 3.3. Google Drive Scope
*   **Minimization**: We request `drive.appdata` scope.
*   **Effect**: The app can ONLY access files it created in the hidden App Data folder. It cannot read the user's documents, photos, or other app data.
*   **Privacy**: High.

## 4. Recommendations

1.  **Monitor Supply Chain**: Ensure `react-native-keychain` and google sign-in libraries are kept up to date to avoid native vulnerability exploits.
2.  **Biometric Hardening**: Consider implementing "Strict Mode" where we detect if new biometrics were enrolled (Android `KeyPermanentlyInvalidatedException`) and force a specific re-auth flow, though this risks user lockout.
3.  **App Key Obfuscation**: While not a silver bullet, using ProGuard/R8 (Android) and symbol stripping (iOS) makes extracting the backup encryption key slightly harder for script kiddies.

## 5. Security Classification

| Feature | Status | Notes |
| :--- | :--- | :--- |
| **Server Access** | **Zero Knowledge** | Server cannot sign or see keys. |
| **User Access** | **Full Control** | User owns the keys via Device + Cloud Account. |
| **Recovery** | **Cloud-Based** | Relies on Google/Apple account access. |
| **Platform Lock-in** | **Mitigated** | Cross-platform migration supported via manual roaming. |
