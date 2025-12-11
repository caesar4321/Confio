# Presale Geo-Blocking Policy & Implementation

**Last Updated:** 2025-12-11
**Scope:** Presale ("Preventa") Features only.

## Policy Overview
Users from the following regions are strictly prohibited from participating in the $CONFIO token presale due to regulatory reasons:
1.  **United States (US)** - Residents.
2.  **South Korea (KR)** - Citizens/Residents.

Blocking is implemented at both the **Client Support** (UI/UX) level and the **Server Enforcement** (API/Protocol) level to ensure double hardening.

---

## 1. Server-Side Enforcement (The "Hard" Shield)
The backend rejects requests from restricted users regardless of the client they are using.

*   **Location:** `presale/geo_utils.py`
*   **Logic:** `check_presale_eligibility(user)` checks `user.phone_country`.
    *   If `US` or `KR`, it returns `False`.

### A. Waitlist Blocking
*   **File:** `presale/schema.py`
*   **Endpoint:** `mutation JoinPresaleWaitlist`
*   **Behavior:** If a restricted user attempts to join, the mutation returns `success=False` with a specific error message in Spanish.
    *   *Message (US):* "Lo sentimos, los residentes de Estados Unidos no pueden participar en la preventa."
    *   *Message (KR):* "Lo sentimos, los ciudadanos/residentes de Corea del Sur no pueden participar en la preventa."

### B. Purchase Blocking
*   **File:** `presale/ws_consumers.py`
*   **Endpoint:** WebSocket `PresaleSessionConsumer` -> `_prepare`
*   **Behavior:** When a user initiates a purchase (Prepare Phase):
    1.  Server checks eligibility immediately.
    2.  If restricted, it rejects the prepare request with `{ "success": False, "error": <MESSAGE> }`.
    3.  No transaction group is built, and no on-chain activity occurs.

---

## 2. Client-Side Guardrails (The "Soft" Shield)
The React Native app provides immediate feedback and prevents accidental clicks.

*   **Detection Method:** Uses `selectedCountry` from `CountryContext` (derived from User Profile/Phone).

### A. Waitlist Screen (`ConfioPresaleScreen.tsx`)
*   **"Notificar" Button:**
    *   **Check:** `checkEligibility()` is called `onPress`.
    *   **Behavior:** If restricted, shows a native Alert with the Spanish blocking message and **aborts** the API call.
*   **"Participar" Button (Start Flow):**
    *   **Check:** `checkEligibility()` is called `onPress`.
    *   **Behavior:** If restricted, shows the Alert and **blocks navigation** to the participation screen.

### B. Participation Screen (`ConfioPresaleParticipateScreen.tsx`)
*   **"Convertir Ahora" Button (Execute Swap):**
    *   **Check:** `handleSwap()` checks country code at the start.
    *   **Behavior:** If restricted, shows the Alert and **aborts** the WebSocket connection attempt.

---

## 3. Error Message Propagation (Fail-Safe)
If a user were to bypass the client-side check (e.g., via a modified client), the server-side rejection message (defined in section 1) is propagated back to the client.

*   **Mechanism:** `PresaleWsSession.ts` catches the server's `error` payload and throws it as a JavaScript `Error`.
*   **UI Result:** The app catches this error and displays it in an Alert, ensuring the user sees the reason for the rejection even if the client-side guard failed.
