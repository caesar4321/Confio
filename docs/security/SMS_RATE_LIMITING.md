# SMS Rate Limiting & DDoS Mitigation

## Overview
To protect the platform and Twilio budget from SMS flooding/DDoS attacks, we have implemented strict server-side rate limiting on the SMS verification endpoint (`InitiateSMSVerification`).

## Implementation Details
The rate limiting is implemented in `sms_verification/schema.py` using Django's cache framework (Redis).

### Limits
1.  **Cooldown (60 seconds)**
    *   **Scope:** Per Phone Number
    *   **Effect:** Prevents the same phone number from requesting an SMS more than once every 60 seconds.
    *   **Message:** "Por favor espera un minuto antes de intentar nuevamente."

2.  **User Limit (5 per hour)**
    *   **Scope:** Per Authenticated User ID
    *   **Effect:** Prevents a single compromised user account from draining credits.
    *   **Message:** "Has excedido el límite de intentos por hora."

3.  **IP Limit (20 per hour)**
    *   **Scope:** Per Client IP Address (extracted securely from the *last* IP in `HTTP_X_FORWARDED_FOR`)
    *   **Effect:** Prevents a single IP (e.g., bot script) from flooding multiple numbers.
    *   **Message:** "Demasiados intentos desde esta dirección IP."

4.  **Phone Number Limit (3 per hour)**
    *   **Scope:** Per Phone Number
    *   **Effect:** Prevents a single number from being spammed even if the attacker switches users or IPs (though unlikely without bypassing auth).
    *   **Message:** "Demasiados intentos para este número. Intenta más tarde."

5.  **App Check Token Fingerprint Limit (5 per hour)**
    *   **Scope:** Per `X-Firebase-AppCheck` JWT Token (via SHA-256 hash).
    *   **Effect:** Explicitly prevents bot farms from extracting a mathematically valid App Check Token from a physical device and systematically spraying SMS requests using completely rotated user accounts, proxy IPs, and target phone numbers.
    *   **Message:** "Demasiados intentos desde este dispositivo. Intenta más tarde."

6.  **Device Hardware ID Fingerprint Limit (5 per hour)**
    *   **Scope:** Per `deviceId` extracted from the React Native `deviceFingerprint` provided during `Web3AuthLogin`.
    *   **Effect:** Prevents an attacker using a single valid physical device from continuously requesting new App Check tokens up to the 10,000/day Play Integrity limit. Because the frontend device ID is static across multiple user logins, an attacker automating Android hardware is still restricted to 5 SMS per device per hour.
    *   **Message:** "Límites de seguridad de dispositivo excedidos. Intenta más tarde."

### Bypass/Exemptions
*   **Review Numbers:** Specific test numbers configured in environment variables (e.g., Apple Reviewer numbers) bypass the external API call entirely, so they do not consume credits, but they are still subject to local logic validation.

## Maintenance
*   **Cache Keys:**
    *   `sms_limit:cooldown:{phone_number}`
    *   `sms_limit:user:{user_id}`
    *   `sms_limit:ip:{ip_address}`
    *   `sms_limit:phone:{phone_number}`
    *   `sms_limit:token:{token_hash}`
    *   `sms_limit:device:{device_id}`
*   **Logs:** Warning logs are generated when the IP, Token, or Device limits are hit (`SMS Rate limit exceeded for IP/Token/Device ID ...`).

## Additional Security Measures

### 1. IP Blocking
*   **Mechanism:** Middleware (`SecurityMiddleware`) checks every request against the `IPAddress` table.
*   **Enforcement:** If `is_blocked=True`, the request is immediately rejected with `403 Forbidden`.
*   **Management:** IPs can be blocked via the admin panel or automated scripts (`scripts/ban_attacker.py`).

### 2. Firebase App Check Enforcement (Anti-Bot)
To prevent automated scripts from bypassing the user limits (by creating fresh Firebase accounts continuously) and IP limits (by rotating proxies), we strictly enforce device attestation.

*   **Mechanism:** The `InitiateSMSVerification` endpoint requires a valid `X-Firebase-AppCheck` header (verified via Play Integrity/App Attest).
*   **Trigger:** Executed **before** any rate limiting or Twilio API calls to instantly drop scripted requests.
*   **Enforcement:** Missing or mathematically invalid tokens are rejected with an error asking the user to update their app or try again later.

### 3. Twilio Carrier Lookup (VoIP/Landline Blocking)
To prevent bot farms from using cheap virtual numbers or landlines, we validate the line type before sending an SMS.

*   **API:** Twilio Lookups v2 (`line_type_intelligence`).
*   **Trigger:** Executed **after** rate limiting checks (to save API costs).
*   **Allowed Types:** `mobile`, `fixedVoip` (case-by-case), or `null` (if API fails, we fail open).
*   **Blocked Types:**
    *   `landline`
    *   `voip`
    *   `nonFixedVoip`
*   **Error Message:** "Solo se permiten números móviles. No se admiten líneas fijas o VoIP."

### 4. Geographic Blocking (High-Risk Countries)
We have disabled SMS traffic to specific high-risk countries in Asia and Africa that are not relevant to our LATAM diaspora user base but are frequent sources of SMS pumping fraud.

*   **Asia:**
    *   Afghanistan (+93)
    *   Myanmar (+95)
*   **Africa:**
    *   Cote d'Ivoire (+225)
    *   Somalia (+252)
    *   Tanzania (+255)
    *   Zimbabwe (+263)

These blocks are configured directly in the Twilio Console (Messaging > Settings > Geo permissions).
