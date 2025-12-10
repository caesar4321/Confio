# Security Review: Keyless Self-Custody Implementation

## Executive Summary

**Architecture:** Keyless Self-Custody with Server-Assisted Deterministic Recovery (2-of-2).
**Verdict:** The system implements a **robust permissionless wallet** suitable for the target LATAM demographic. It provides high resistance to both server compromise and database leaks due to the non-discoverability of user components.

## Risk Assessment

### 1. Server-Assisted Key Derivation (Privileged Access Risk)
The wallet generation relies on two inputs:
- **User Share**: Derived from the OAuth identity (`sub`, `iss`, `aud` in `firebase_id_token`).
- **Server Share**: A high-entropy 32-byte pepper stored in the server database.

**Risk**: An attacker with full Remote Code Execution (RCE) *during* a user's active login session could theoretically intercept the User Share and combine it with the stored Server Share.
**Mitigation**:
- Server memory is volatile; User Shares are never persisted.
- The server does not sign transactions.
- Requires active, sophisticated compromise of the running application, not just a static data breach.

### 2. Database Leak Scenarios (Negligible Risk)
A static database leak exposes the "Server Share" (Peppers) and User Emails.
**Analysis**:
- **Apple**: The OAuth `sub` is **App-Scoped** (unique to Team ID + Bundle ID). There is no mechanism for an attacker to derive or lookup an Apple `sub` from an email address.
- **Google**: While account-scoped, Google **does not provide APIs** to resolve an email address to a `sub` ("Subject ID"). The `sub` is only revealed upon successful user authentication.
**Conclusion**: An attacker possessing the database (Peppers + Emails) **cannot** reconstruct user keys because they cannot obtain the required `sub` input via OSINT or APIs. The system is secure against static data breaches.

### 3. Immutable Security Parameters (Architectural Constraint)
The `DerivationPepper` is non-rotating to ensure deterministic address generation.
**Constraint**: Key rotation involves fund transfer to a new address.
**Operational Requirement**: Strict access controls around the `WalletPepper` table remain a best practice for defense-in-depth.

### 4. Information Disclosure via Logging (Remediated)
**Finding**: The React Native application logs the full Google Sign-In response object to the device console.
- **Location**: `apps/src/services/authService.ts`.
- **Status**: **Remediated**. Console logs have been updated to redact sensitive token information.
- **Recommendation**: Ensure future logging statements sanitize PII.

## Security Classification

| Feature | Classification |
| :--- | :--- |
| **Custody** | **Non-Custodial** (Server cannot sign, keys not persisted) |
| **Trust Model** | **Permissionless / Semi-Trusted** (Server assistance required for recovery, but cannot act alone) |
| **Data Breach Resilience** | **High** (Database leak does not compromise funds due to undiscoverable User Share) |
| **Recovery** | **Identity-Based** (Zero-knowledge of seed phrases required) |

## Recommendations

1.  **Remediation**: Remove sensitive `console.log` statements in `authService.ts` immediately.
2.  **Log Hardening**: Ensure `firebase_id_token` and decoded claims (especially `sub`) are *never* logged to application logs to prevent inadvertent persistence of the User Share.
3.  **Access Control**: Isolate the database credentials used by the web application.
4.  **Transparency**: Communicate clearly that wallet security relies on the integrity of the Google/Apple account, which users are already accustomed to protecting.
