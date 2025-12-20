# Firebase App Check Integration

**Last Updated:** December 20, 2025

## Overview

We have migrated from a custom Play Integrity implementation to **Firebase App Check**. This provides a unified solution for verifying device integrity on both Android and iOS platforms, protecting our API and resources from abuse (bots, rooted devices, emulators).

---

## Architecture

### Client-Side (React Native)

*   **Sdk**: `@react-native-firebase/app-check`
*   **Service**: `apps/src/services/appCheckService.ts`
*   **Providers**:
    *   **Android**: Google Play Integrity
    *   **iOS**: App Attest (Targeting iOS 15.1+)
    *   **Development**: Debug Provider (enabled via `__DEV__` flag)

### Backend-Side (Django)

*   **Sdk**: `firebase-admin`
*   **Service**: `security/integrity_service.py`
*   **Verification**:
    *   The backend validates the App Check token sent by the client.
    *   Tokens are stateless JWTs signed by Firebase.
    *   Verification confirms the request is accompanied by a **valid Firebase App Check attestation** for our app on a genuine device.
    *   **Note**: Token TTL defines maximum validity. Replay protection relies on server-side request context and session scoping (WebSocket).

---

## Implementation Details

### 1. Client Integration

The client initializes App Check on startup and attaches a token to sensitive requests.

**Initialization (`appCheckService.ts`):**
```typescript
await appCheck().initializeAppCheck({
  provider: appCheck().newReactNativeFirebaseAppCheckProvider(),
  isTokenAutoRefreshEnabled: true,
});
```

**Transport:**
*   **GraphQL/HTTP**: Sent in `X-Firebase-AppCheck` header.
*   **WebSockets**: Sent as `&app_check_token=...` query parameter during connection.

### 2. Backend Verification

**Helper: `verify_request_header`**
Located in `security/integrity_service.py`. It extracts the header (or WebSocket context), verifies the token via Firebase Admin SDK, and returns the result (valid/invalid).

**WebSocket Optimization:**
App Check verification is expensive (network call to Firebase public keys, signature verification).
*   For **WebSockets**, we verify **ONCE** during the handshake (`connect` method).
*   The `_DummyRequest` object used in internal mutations is flagged with `_app_check_verified = True` to skip redundant checks during the session.

---

## Enforcement Strategy

We employ a graded enforcement strategy to minimize disruption while securing critical paths.

| Action | Transport | Level | Description |
| :--- | :--- | :--- | :--- |
| **Reward Claim** | GraphQL | **BLOCKING** | Prevents referral abuse. Fails if token is invalid or missing. |
| **Login / Signup** | GraphQL | Warning | Logs verification status; does not block users yet. |
| **Payments** | WebSocket | Warning | Verifies integrity on connection. Logs results. |
| **Withdrawals** | WebSocket | Warning | Verifies integrity on connection. Logs results. |
| **Guardarian** | REST/GQL | Warning | Logs verification status for fiat on/off-ramp. |

*   **Blocking**: Request is rejected immediately if integrity check fails.
*   **Warning**: Request proceeds, but failure is logged for analysis.

---

## Testing & Debugging

### Debug Providers
In development builds (`__DEV__ = true`), the app uses the **Debug Provider**. This allows testing on simulators and emulators which normally fail integrity checks.

### Debug Tokens
To authorize a simulator/device for the Debug Provider, its unique **Debug Token** must be added to the Firebase Console.

1.  Run the app on the simulator/device.
2.  Check the Metro logs (or Xcode/Android Studio logs) for:
    `"Firebase App Check Debug Token: <UUID>"`
3.  Add this token in **Firebase Console > App Check > Apps > Manage debug tokens**.

> **Note**: Recorded tokens for team devices are stored in `.env.testnet` for reference.

### Common Issues
*   **"Unregistered App"**: Ensure the `google-services.json` (Android) or `GoogleService-Info.plist` (iOS) matches the project in Firebase Console.
*   **"Invalid Token"**: The token may have expired (TTL is usually 1 hour) or belongs to a different project. The SDK auto-refreshes, but hardcoded tokens in scripts will expire.
*   **"Missing Header"**: Ensure `client.ts` or `ws_consumers.py` is correctly attaching/extracting the token.
