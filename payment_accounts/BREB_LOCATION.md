# Bre-B location checks (anywhere except Venezuela)

Scope: Bre-B, whichever provider runs it (Infinia today; Cobre's COP account/key
applications later), meaning the local-money Colombia activation/recipient, Bre-B key
display and Infinia/Cobre journey-start location-pass gates, is usable from
anywhere EXCEPT Venezuela. The location check is a requirement step of the application
(and renews a lapsed pass before a key is shown), not an up-front gate. Other rails have
no location check: Venezuelan identity documents are refused there at the start. No VPN intelligence, paid IP
lookup, Didit IP analysis, background tracking, or change to general Confío access.
The existing Cloudflare-first `security.geo.country_for_request` resolver is
reused (including its existing free fallback). VE and unknown countries cannot
apply. This is a presence check, not proof of residence or a 5% exposure measure.

The server's local-money list supplies `cobre_co_breb_receive` only when the
Cobre flag, this gate and the Cobre eligibility policy permit it; until then
Bre-B is Infinia's `co_breb` / `co_breb_receive`, behind the same gate.
Listing never depends on the IP. Android and iOS use separate request-bound native verifiers. The signed
server challenge selects the verifier; the client cannot downgrade an Android
challenge by submitting an Apple envelope or vice versa.

Android requests precise foreground location, rejects mock reports, locations
older than two minutes, and accuracy worse than 100 m. A native module hashes a
server-issued challenge with the exact location JSON into a Standard Play
Integrity `requestHash`. Android reuses the prepared provider, never a token or
verdict. Failed providers are discarded for the next user attempt; there is no
Classic fallback. Verification grants a 15-minute account-scoped pass. Gated
operations check their current IP even while the pass remains valid. An explicit
expired/missing-pass refusal prompts fresh verification in the client, followed
by one retry of the refused operation. Timeouts and other financial failures
are never retried by this mechanism. The server decodes through Google and checks requestHash,
timestamp, package, production signing certificate and MEETS_DEVICE_INTEGRITY.
Firebase's global App Check bypass does not bypass this gate. The signed
challenge belongs to the active Confío account and expires in three minutes;
Redis atomically reserves it BEFORE calling Google, preventing simultaneous
decodes and repeated quota spending even when a decode fails. Request a new
challenge for a retry. Android discards a stalled provider preparation on
timeout. The UI's recent-pass cache is scoped to user/account context; it does
not replace the server's pass or current-IP checks. Every verification (passed or refused) is stored in
`BrebLocationCheck` as compliance evidence: account, time, platform, result and
the refusing check, IP and IP country, and the reading (coordinates, accuracy,
reading time). A pass is granted only once its record is stored. Integrity
tokens are never persisted, and nothing is tracked in the background; ensure upstream GraphQL request-body logging is disabled/redacted.

Both lower-level Cobre account provisioning and Bre-B key creation require a
short-lived in-process permit from the verifier. Existing generic mutations
therefore cannot bypass the application. Account/keys remain provider-idempotent.
This does not block incoming employer payments or existing account read access.

## Deployment requirements (not enabled automatically)

- `BREB_LOCATION_ENABLED=True` (independent of `COBRE_PAYMENT_ACCOUNTS_ENABLED`).
  While it is off or the attestation below is missing, the gate is unavailable
  and every Colombian (Bre-B) operation is refused: Infinia's included. Enable
  it together with the deploy that ships this gate.
- iOS: `BREB_IOS_APP_ATTEST_ENABLED=True` and `BREB_IOS_APP_ID` (Team ID prefix +
  bundle ID, production App Attest entitlement).
- `BREB_PLAY_CLOUD_PROJECT_NUMBER`: positive numeric ID of the Cloud project
  linked to this app in Play Console (not its text project ID). Returned by the
  challenge API as public configuration. Do not guess which Firebase project
  is linked. Missing configuration keeps the gate unavailable.
- Shared Redis default cache (`USE_REDIS_CACHE=True`); local-memory cache is
  intentionally insufficient for replay protection.
- `BREB_PLAY_CERTIFICATE_DIGESTS`: comma-separated base64url SHA-256 certificate
  digests for the production Play App Signing certificate, not upload/debug keys.
- Google Application Default Credentials with access to decode Play Integrity
  tokens for `com.Confio.Confio`; enable/link the API in the Play Console/Cloud
  project. Use existing secret deployment mechanisms; do not commit credentials.
- Deploy origin protection so only Cloudflare/trusted ingress can supply
  `CF-IPCountry`. A directly reachable origin accepting arbitrary CF headers
  undermines the shared IP gate.
- Release the native builds and validate on physical Play-installed Android
  and TestFlight/App Store iOS devices before enabling the respective gates.

## iOS request-bound App Attest

Firebase App Check is unchanged. Bre-B uses a separate DCAppAttestService key
and verifies the full attestation chain against the bundled Apple App Attest
root from https://www.apple.com/certificateauthority/Apple_App_Attestation_Root_CA.pem.
Registration binds the attestation nonce to the challenge plus exact location
JSON. It checks the production AAGUID, RP/App ID hash, zero counter, credential
ID, certificate public-key hash, and COSE key. Subsequent assertions bind that
same payload; a database row lock protects the increasing counter. Keys are
unique and owned by a user, never reassigned on registration. Revoked keys fail
assertion verification. Malformed or development attestation fails closed.

Core Location requires iOS 15+, full accuracy, a fresh reading within 100 m,
and source information without software simulation or accessory production.
No background permission is requested. Missing source information fails closed.
Existing keys are reused. After a failed/unacknowledged registration the server
reports whether the key was registered; unregistered keys rotate rather than
trying to attest an already-attested key with a different challenge.

Apply migration `0016_brebappattestkey` before enabling. Set
`BREB_IOS_APP_ID` to the exact App ID prefix + `.com.Confio.Confio` from the
production entitlement (do not infer the prefix from Firebase). Confirm the
production App Attest entitlement in the signed provisioning profile, then set
`BREB_IOS_APP_ATTEST_ENABLED=True` with the common Cobre/location flags.
Android project-number/certificate settings are not required for the iOS path.
Development/debug attestations and Firebase debug tokens are never accepted.

Signed authenticator extensions, when present, must identify TestFlight/App
Store distribution and a nonempty build version. Legacy authenticators without
those optional extensions still require production AAGUID and Apple chain
verification. No minimum-build policy is imposed. The Apple receipt is stored
as opaque data, not trusted as a fraud score; independent receipt assessment
and Apple's fraud-metric API are not implemented or used for admission.

Release checklist: first registration, normal assertion, replay, changed
coordinates, reinstall/invalid key, lost response, account switch, denied or
reduced location permission, simulated location, and unavailable App Attest.
The simulator cannot demonstrate successful App Attest. Full workspace build
and real Apple attestation remain required even when synthetic crypto tests
and standalone Swift type checking pass. No production settings are changed
by this implementation.

## Quota monitoring and rollout

Standard does not remove Google's default 10,000/day shared server-decryption
quota. `breb_integrity_decode_attempt` logs feature-local UTC counts, with
`breb_integrity_quota_threshold` warnings at 8,000/9,500/10,000 and
`breb_integrity_quota_exhausted` on HTTP 429. Counters live in shared Redis for
two days. These are diagnostic attempts, not authoritative quota usage: other
features, Google retries, and Google's quota window can differ. No GPS/token
payload enters these logs. Network/quota failures deny verification with a
temporary-unavailability message; no location pass is issued by that attempt.

Before enabling, configure project-wide Google Cloud quota alerts (e.g. 80% and
95%) and route the application warnings into the existing alert destination.
Neither cloud alerts nor a quota increase have been created by this change.
Request increased generation AND decryption quotas in the Play Integrity
quota form linked at https://developer.android.com/google/play/integrity/setup.
Size the request for peak daily verifications plus all other consumers and
failure headroom. Deploy backend and the new Android build together; Classic
tokens deliberately fail the Standard requestHash check. Keep the gate off
until release-device, provider-expiry and exhausted-quota tests pass.

The server uses the pinned `timezonefinder==8.2.0` offline dataset. Bre-B is
refused only in Venezuela: the reading and twelve perimeter samples at reported
accuracy plus a 50 m policy buffer must all resolve outside `America/Caracas`
(Venezuela's only zone, used by no other country). A reading that straddles the
border asks for another attempt. Sampling does not establish that every point
inside the disk is outside Venezuela, and 50 m is not a measured guarantee of map
accuracy. Cobre eligibility v2 (migration 0017) blocks only residence in Venezuela.
Regression tests: Bogotá, Cúcuta, Villa del Rosario, Cartagena, Quito and Madrid
pass; Caracas, San Antonio del Táchira and Ureña are refused. Check these before upgrading: timezone datasets can merge
equivalent zones, so a timezone ID is not generally a country identifier.
No coordinates are sent to a reverse-geocoding provider. Passing integrity is not certification
of GPS truth and cannot exclude remote-control or sophisticated spoofing.
