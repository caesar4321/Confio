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
    *   **Scope:** Per Client IP Address (extracted from `HTTP_X_FORWARDED_FOR`)
    *   **Effect:** Prevents a single IP (e.g., bot script) from flooding multiple numbers.
    *   **Message:** "Demasiados intentos desde esta dirección IP."

4.  **Phone Number Limit (3 per hour)**
    *   **Scope:** Per Phone Number
    *   **Effect:** Prevents a single number from being spammed even if the attacker switches users or IPs (though unlikely without bypassing auth).
    *   **Message:** "Demasiados intentos para este número. Intenta más tarde."

### Bypass/Exemptions
*   **Review Numbers:** Specific test numbers configured in environment variables (e.g., Apple Reviewer numbers) bypass the external API call entirely, so they do not consume credits, but they are still subject to local logic validation.

## Maintenance
*   **Cache Keys:**
    *   `sms_limit:cooldown:{phone_number}`
    *   `sms_limit:user:{user_id}`
    *   `sms_limit:ip:{ip_address}`
    *   `sms_limit:phone:{phone_number}`
*   **Logs:** Warning logs are generated when the IP limit is hit (`SMS Rate limit exceeded for IP ...`).
