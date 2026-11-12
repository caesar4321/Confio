# Spec: Phone-less signup and WhatsApp link send

Status: APPROVED 2026-10-29 (Codex quality gate 7/10, gaps from both passes addressed)
Repo: caesar4321/Confio · Branch: main
Type: Epic (7 child issues)

## Context

Signup currently requires a verified phone number: SMS through Twilio Verify, or Telegram Gateway. The phone was added so people could send money to the numbers in their address book. In practice almost nobody sends by phone number. Every new signup still pays for an OTP whether or not the person ever moves money. In October 2026 that was 1,239 SMS (66% to +591 Bolivia) at about $0.30 each.

This epic removes the phone from signup and replaces "send to a phone number" with a mechanism that needs no OTP:

1. The **country** a user belongs to comes from where they actually connect from (IP residence), not from their phone prefix.
2. The **first send to a contact** goes as a one-time link, delivered through the sender's own WhatsApp to that contact's chat. The link pays out of the existing invite escrow.
3. Once the contact claims the link and the sender confirms the account, later sends to that contact go **direct**, with no limit beyond the normal send rules.

Everyone affected:
- New users sign up with Google or Apple only.
- Senders pick from their full address book, as today.
- App Review gets a deep link to switch between country experiences on one Apple ID.
- Admin and analytics read a residence country.

## Current State (verified 2026-10-29)

### Signup gate
- `apps/src/contexts/AuthContext.tsx:1163` routes any session whose `me` lacks `phoneNumber && phoneCountry` to `PhoneVerification`. The same rule applies after login at `:911-916` and on profile refresh at `:369`.
- `apps/src/screens/PhoneVerificationScreen.tsx` (995 lines) offers Telegram or SMS (`sms_verification/twilio_verify.py`, `telegram_verification/schema.py`).
- `apps/src/screens/EditProfileScreen.tsx:163` lets users change the number.
- Old builds decide this gate on the client, so only a minimum-version bump stops them from sending SMS. The minimum-version field is `security/models.py:727` (`minimum_version`, set by hand in admin).

### Country
- `users.User.phone_country` (ISO-2) is the de facto country of the user.
  - Server: 73 non-test files and 229 occurrences read it (excluding migrations and `scripts/`). `scripts/` has 10 more files.
  - App: 40 files read `phoneCountry` from GraphQL.
- Regulatory gates go through `security/geo.py` `GeoPolicy`. `phone_eligible()` and `evaluate()` check `phone_country_of(user)` and then the request IP. There are 26 call sites across 12 files (assistant, cusd_plus eligibility/crypto/perps, presale).
- `security/geo.py:169` `residence_country_for(user)` already returns the majority non-VPN IP country (ISO-3) over the last 90 days.
- Didit picks its workflow by phone country: `security/didit.py:704` `_workflow_id_for_account`, using the `DIDIT_WORKFLOW_IDS_BY_PHONE_COUNTRY` map in `config/settings.py:255`.
- Koywe derives its rail country from the phone country: `ramps/schema.py:2758` `_get_user_phone_country_alpha3`. It needs a document from that country: `security/identity_status.py:53` `phone_country_identity`.
- Bolivia QR decides "is Bolivian" by `phone_country == 'BO'`: `ramps/bolivia_qr.py:80`.

### Phone country vs IP residence (prod, 2026-10-29)

Run over 10,164 active real users with a phone country, using `residence_country_for` (90 days):

| | Users | Share |
|---|---|---|
| Residence known, same as phone country | 1,208 | 98.8% of known |
| Residence known, different | 15 | 1.2% of known |
| No residence in the last 90 days | 8,941 | 88% of all |

- 9,968 of the 10,164 users (98%) have at least one IP row, going back to 2025-09-04. Most simply were not active in the last 90 days.
- The country distribution therefore barely moves where residence is known. The real gap is users without recent activity, and they keep their phone country (see Backfill).

### Contact discovery
- `apps/src/services/contactService.ts:292` `checkConfioUsers` sends the whole address book to the server, 50 numbers at a time.
- The server matches them against `phone_key` in `users/schema.py:2219` `resolve_check_users_by_phones`. Nothing is stored server-side.
- An upload-consent screen guards this (`contactService.ts:262`).

### Invite escrow (reused)
- `contracts/cusd_plus/ConfioInviteEscrow.sol` is deployed on BSC (0xeFF0Af29…D0d6).
- `createInvitation(inviteId, token, amount)` is called by the inviter.
- `claimInvitation(...)` is called by the SPONSOR only and converts between cUSD and Dollar+ by recipient eligibility.
- `reclaimInvitation(inviteId)` is called by the inviter only, after `RECLAIM_PERIOD = 7 days`, and is never pausable.
- Invites are keyed by `(inviter, inviteId)`.
- Backend: `send/models.py:272` `PhoneInvite` (phone_key, invitation_id, inviter_user, inviter_address, status). Prepare, submit and reclaim live in `blockchain/invite_send_mutations.py`. Today's claim is `ClaimInviteForPhone`, which requires an OTP-verified phone.

### App Review
- Reviewers sign in with their own Apple ID, then type a configured reviewer phone number with a fixed code. No SMS is sent.
- `users/review_numbers.py`: the Argentina number is geo-exempt; the US and UK numbers show the blocks.
- With no phone screen, this has no place to live.

## Proposed Change

```
#1 Residence country ─┬─> #2 Didit general workflow
                      ├─> #3 Signup without phone (+ min version, SMS off)
                      ├─> #4 Review deep link
                      └─> #6 Link send ──> #7 Saved recipients & direct send
#5 Remove contact discovery (independent, ships with #3's app release)
```

**Release unit.** Server changes for #1 and #2 ship first, on their own. The app changes for #3, #4, #5, #6 and #7 ship together in ONE app release. Server flags for that release:
- `PHONE_VERIFICATION_ENABLED` defaults to True.
- `LINK_INVITE_ENABLED` defaults to False and is turned on the day the build is approved.

Old builds keep the phone flow and the legacy phone invite until `minimum_version` passes the new build. There is no window in which a build has neither phone sends nor link sends.

**Sequencing rationale.** #1 must land first. Removing the phone gate (#3) before every consumer reads `country` would leave new users with no country, and the regulatory gates would fail closed for everyone new. #4 needs #1 because the review link writes `country`. #6 and #7 need #3's app release, because that is the build that stops creating phone-verified users. #5 rides with #3 because both edit the same send and contacts screens.

### #1 Residence country (server)

**Data model** (`users/models.py`, one migration):

```python
country = models.CharField(max_length=2, blank=True, null=True, db_index=True,
    help_text="ISO-2 residence country (IP majority); see security.geo.country_of")
country_source = models.CharField(max_length=16, blank=True, default='',
    choices=[('residence','residence'), ('legacy_phone','legacy_phone'),
             ('signup_ip','signup_ip'), ('review','review')])
country_updated_at = models.DateTimeField(null=True, blank=True)
```

**Resolution:**
- **Signup:** when the account is created (the web3auth login mutation's user creation), set `country = country_for_request(request.META)` and `country_source='signup_ip'`. If the IP is unknown, leave it null.
- **Daily job:** a Celery task `users.tasks.refresh_residence_countries` runs over users with an `IPDeviceUser.last_seen` in the last 24 h.
  - It computes `residence_country_for(user)` and converts ISO-3 to ISO-2 with a new helper `security.geo.to_iso2`.
  - It writes the value only when it is not None and differs from the stored one, with `country_source='residence'`.
  - It never writes null over a known country.
  - It skips users whose `country_source='review'` while they hold an active `ReviewAccess`.
  - A `review` source with no active `ReviewAccess` (expired, superseded with no successor, or the token cleared) is restored on the next run.
    - If the residence country is known, it is used.
    - Otherwise the latest row's `country_before_review` / `source_before_review` are restored. They may be null if the user had no country before.
    - This restoration is the only case where the job may write null.
  - The job also runs over these users even if they had no IP activity in the last 24 h.
- **Backfill** (management command `backfill_residence_country`, idempotent): for every user with a null `country`, use `residence_country_for` if known (source `residence`), else `phone_country` (source `legacy_phone`), else leave it null.
- **Accessor:** `security.geo.country_of(user) -> str` returns `user.country`, falling back to `phone_country`, stripped and upper-cased. It replaces `phone_country_of`, which is kept as an alias for one release.

**Consumer migration rule.** Every read of `phone_country` that means "where this user is" moves to `country_of(user)` (Python) or the `country` column (queries, admin, analytics). A read that means "the country of this phone number" stays on `phone_country`:
- phone normalization: `users/models.py:259-265`, `users/phone_utils.py`
- `users/phone_linking.py`
- invite and employee phone invites: `blockchain/invite_send*`, `send/schema.py`, `users/graphql_employee.py`, `users/models_employee.py`
- payer phone strings: `payments/schema.py:650`, `ramps/schema.py:2865`, `payment_accounts/compliance.py:152`

The implementer classifies each of the 229 occurrences and lists the classification in the PR description.

**GeoPolicy** (`security/geo.py`):
- The field names `phone_blocked`, `phone_messages`, `allow_missing_phone` and the method `phone_eligible` are kept, so the 12 policy files and their tests did not all change at once. A comment on the dataclass says they now apply to `country_of(user)`. `phone_country_of` is renamed to `country_of` everywhere, including test patch targets.
- Both `phone_eligible` and `evaluate` read `country_of(user)`.
- Per-request IP checks are unchanged.
- `blocked_by` reports `'country'` instead of `'phone'`.

**GraphQL.**
- New field `country` on the user type: the residence country (`country_of`), returned to the account's own viewer only.
- `phoneCountry` keeps its meaning (the phone number's country) and is null for phone-less users. Old builds never break: they force phone verification at signup, so their users always have one.
- The new app moves its about 125 country reads from `phoneCountry` to `country`. It keeps `phoneCountry` only where it formats a phone number (about 27 reads).

**Rail ordering for Recibir/Enviar** (new `ramps/rail_country.py`). `rail_countries(user, device_region=None) -> list[str]` returns ISO-2 countries in this order, without duplicates:
1. `user.preferred_rail_country`: a new nullable CharField(2), written when the user picks a country in the rail list.
2. `country_of(user)`: a QR is paid where you are, so residence outranks documents. A Bolivian resident holding only a Venezuelan ID keeps QR Bolivia.
3. Verified Didit document countries: primary first, then additional documents by `verified_at` descending.
4. `device_region` (sent by the client from the device locale)

`ramps/bolivia_qr.py:80` `is_bolivian` becomes `rail_countries(user)[:1] == ['BO']`. Server-side checks have no device, so they call it without `device_region`.

**Rail-country API:**
- Query `railCountries(deviceRegion: String) -> [String!]!` returns the ordered list. The Recibir/Enviar rail lists render in that order.
- Mutation `setPreferredRailCountry(country: String!) -> {success, error}` is called when the user taps a country in the rail list.
  - The country must be a real ISO-2 country (pycountry); anything else returns `error='País no disponible'`. Rail lists already show only countries with rails, so the stored value only reorders them.
  - The account comes from the JWT.
- A missing Didit document simply contributes nothing to the order. A document from a country with no rail is skipped.

**Koywe.**
- The identity sent is `security.identity_status.rail_identity(user, order_country)`. It is a current document that ties the person to that country (issued there, or naming it as nationality or residence), primary or additional, with national IDs and residence permits ranked before passports.
- `phone_country_identity` and `has_phone_country_identity` are replaced by `rail_identity` and `has_rail_identity`. The `User.has_phone_country_identity` property becomes `has_rail_identity`.
- The app's `phoneCountryVerified` flag keeps its name, but now means `has_rail_identity` for the first rail country.
- The ramp address country is the residence (`_get_user_residence_alpha3`), because the address is where the person lives. It is no longer the phone country.
- When the order's country has no matching document, Koywe's error names that country: "necesitamos tu documento de identidad de {país}".

The rail country reaches Koywe through the `country_code` argument the Koywe quote and order mutations already accept. `ramps/schema.py:2190` stops falling back to `phone_country` and falls back to `rail_countries(user)[0]` instead. Each Koywe mutation validates that the country is in `COUNTRY_METHODS` and that `verified_document_of_country(user, country)` exists. Otherwise it returns the existing "verificá tu identidad" error naming that country.

### #2 Didit general workflow
- `security/didit.py:704`: personal sessions use `settings.DIDIT_GENERAL_WORKFLOW_ID`. The phone-country map (`/confio/secrets/prod/didit-workflow-ids-by-phone-country`) is dropped. Business keeps `DIDIT_BUSINESS_WORKFLOW_ID`.
- **The general workflow is live:** "Confio General KYC + AML", `f1f13336-99ad-48f5-aba8-77c92194d3b4`. It was created and published on 2026-10-29 and is the Didit default. The request body and notes are in `security/workflows/kyc/`, and `config/settings.py` already has `DIDIT_GENERAL_WORKFLOW_ID` defaulting to it.
  - The graph is identical to Argentina's (OCR → liveness → face match → AML with ongoing monitoring, NFC off), at the same price of $0.57.
  - **Documents:** ID, passport and residence permit from 228 countries.
  - The country restriction lives in `workflow_graph.nodes.ocr.config.documents_allowed`. The top-level `documents_allowed` is null on every workflow and says nothing. The per-country workflows each accept only their own country; "Rest of Europe" (`e48b5e69`) accepts 55 European countries.
  - **Open check:** readback shows `is_liveness_enabled: false` despite the graph. Confirm liveness and face match on the first real session's `features` before #3 ships.
- **Passports are accepted at first KYC on purpose.**
  - If they were refused, a passport-only person could never become verified, and so could never reach the additional-document step either.
  - Rail document rules are enforced at the rail. Koywe refuses passports except in Colombia (`ramps/koywe_client.py` `_resolve_document_type`).
  - **TopUp mapping:** when the selected rail country's document is a passport that Koywe will not take, or there is no document for that country at all, TopUp shows: "Para recargar desde {país} necesitamos tu {cédula / documento de residencia} de {país}." Its one action opens the additional-document workflow with `id_country={rail country}` and `document_types=['ID','RP']` (`security/didit.py:807-826`). A raw `KoyweError` is never shown.
- **Keep the additional-document workflow for second documents only:** `ecfcc905` stays exactly as it is.
  - It has no liveness or face match by design. It only binds a second document to a person who already passed liveness (`security/didit.py:807-826`, `_bind_to_person`).
  - Used as a first KYC, it would accept an ID photo with no live face behind it.
- `47378c72` ("Custom KYC") was deleted on 2026-10-29. It had no AML and 0 sessions.
- **Record the workflow on every session:** store the `workflow_id` Didit reports into `IdentityVerification.risk_factors['didit']['workflow_id']`. Today it is not persisted, so which workflow verified a user can only be answered through Didit's API.
- Didit pre-selects the document country from the IP, and the user can change it in Didit's dropdown.
- `security/didit.py:799` stops reading `phone_country`.

### #3 Signup without phone (app + server)

**App:**
- `AuthContext.tsx`: delete `requirePhoneVerification` and its three call sites. After login, always go to `BiometricSetup` (`origin: 'login'`).
- Remove `PhoneVerification` from `AuthNavigator.tsx:24` and `MainNavigator.tsx:398`. Delete `PhoneVerificationScreen.tsx` and the phone-change entry at `EditProfileScreen.tsx:163`.
- `contactService.setDefaultPhoneRegion` moves from `me.phoneCountry` to `me.country`.

**Server:**
- New setting `PHONE_VERIFICATION_ENABLED` (default True). When False, `InitiateSmsVerification` and `InitiateTelegramVerification` return `success=false`, `error='La verificación por teléfono ya no es necesaria. Actualizá Confío.'` and never call Twilio or Telegram.

**Release checklist (one ordered list for the whole epic):**
1. Deploy server #1 and #2. Run `backfill_residence_country`. Verify acceptance criteria 3 and 8.
2. Deploy server #3–#7 with `PHONE_VERIFICATION_ENABLED=True` and `LINK_INVITE_ENABLED=False`. Old builds are unaffected.
3. Submit the app build. Reviewers use the review link from #4.
4. On store approval on both platforms: set `LINK_INVITE_ENABLED=True`.
5. 48 h later, if crash and claim metrics are clean:
   - set `minimum_version` to the new build
   - make legacy `PrepareInviteForPhone` refuse
   - set `PHONE_VERIFICATION_ENABLED=False`

**Rollback before step 5:** set `LINK_INVITE_ENABLED=False`. Old builds still work. **After step 5:** rolling back means first setting `PHONE_VERIFICATION_ENABLED=True` and re-enabling legacy prepare, then lowering `minimum_version`. Lowering the version alone is not enough.

Expected outcome: Twilio Verify sends drop to 0 within 24 h of step 5.

### #4 App Review deep link
- Link: `confio://review?country=AR|US|GB&k=<token>`. Handled in `apps/src/navigation/linking.ts`. If the user is signed out, the link is stashed and applied right after login.
- Mutation `applyReviewAccess(country: String!, token: String!) -> {success, error, country}`. The account always comes from the JWT.
  - **Token:** `settings.REVIEW_LINK_TOKEN` (Parameter Store, 32+ random chars, fixed). Compared with `hmac.compare_digest`. Failed attempts are limited to 5 per user per hour (cache key).
  - **Country:** only AR, US and GB are accepted. AR is geo-exempt; US and GB are not.
  - **Writes:** a new `ReviewAccess(user, country, geo_exempt, country_before_review, source_before_review, created_at, expires_at=created_at+14d, superseded_at=NULL)` row, plus `user.country=country` and `country_source='review'`.
    - `country_before_review` and `source_before_review` copy the user's `country` and `country_source` at the first apply. Later applies copy them from the previous row.
    - Applying again on the same account sets `superseded_at` on the previous row and inserts a new one. Rows are never deleted, so history and the monthly count stay exact. One Apple ID can switch countries this way.
    - **Active** means `superseded_at IS NULL AND expires_at > now() AND settings.REVIEW_LINK_TOKEN != ''`. Clearing the token therefore revokes every grant at once.
  - **Cap:** geo-exempt applications are limited to `REVIEW_LINK_MONTHLY_CAP` (default 10) per calendar month (UTC), counted across all users.
    - The count is `ReviewAccess` rows with `geo_exempt=True` created in the current UTC month, including replaced ones.
    - Count and insert run inside one transaction holding `pg_advisory_xact_lock(hashtext('review_link_cap'))`, so concurrent applies cannot exceed the cap.
    - Past the cap the mutation errors.
  - **Alert:** every successful apply sends `send_ops_alert` with the user id, signup date, country and request IP country.
- `security/geo.py:227` `store_review_exempt` is True for an active geo-exempt `ReviewAccess` (and, for one release, the old reviewer numbers).
- **Money cap.** While an account is geo-exempt only because of `ReviewAccess`, each money-moving operation behind a GeoPolicy is capped at US$20. That covers presale buy, stock buy, perps open, crypto buy and on-ramp order. The cap is enforced by a new `security.geo.enforce_review_cap(user, usd_amount)`, called next to the policy check at each of those mutation call sites. Reviewers see every flow; a leaked link opens nothing of size.

`usd_amount` is the value the user commits in that one operation:

| Operation | `usd_amount` |
|---|---|
| presale, stock or crypto buy | the cUSD/USDT input amount (1 unit = US$1) |
| perps open | the margin the user deposits, not the notional |
| on-ramp order | the USD amount of the quote before fees |

The cap is per operation, not cumulative.
- Register `ReviewAccess` in `config/admin_dashboard.py`.
- After #3 ships, retire the review-number settings (`REVIEW_TEST_PHONE_E164*`, `REVIEW_TEST_GEO_BLOCKED_PHONES_E164*`).

### #5 Remove contact discovery
- Delete `checkConfioUsers`, its callers in `syncContacts`, the upload-consent storage (`contactService.ts:92-290`) and the consent screen copy.
- The address book is still read locally after the contacts permission is granted, and shown in Enviar.
- Retire the server resolver `check_users_by_phones` once `minimum_version` passes the last build that calls it.
- Update the iOS `NSContactsUsageDescription` and Play data-safety copy: contacts stay on the device. Only a number you send to is sent, as part of that send.

### #6 Link send (first send to a contact)

**Picking a contact (Enviar):**
1. The user picks a contact. The app normalizes the number with the default region = `me.country`.
2. It calls `resolveRecipientForPhone(phone: String!) -> {kind: SAVED|LEGACY|NONE, user {id username displayName verifiedName}}`. This sends one number per user action and is never a batch (Apple 5.1.2(iv)).
   - **SAVED:** an active `SavedRecipient` exists for `(sender, phone_key)`. Go to the normal direct send (#7).
   - A `RecipientRevocation` for `(sender, phone_key)` exists, with no newer active `SavedRecipient`: the result is NONE.
   - **LEGACY:** an active, non-reviewer user (`not users.review_numbers.is_shared_reviewer_phone_key(phone_key)`) holds this OTP-verified `phone_key`, and their `last_activity_at` is within 180 days. This counts as already sender-confirmed: go to direct send (#7). An inactive holder is treated as NONE, because carriers recycle numbers.
   - **NONE:** go to the link flow.

**Creating the link:**
- **Limits:** US$10 per link and US$100 per sender per rolling 24 h, server-enforced in prepare.
  - **USD value:** cUSD counts 1:1. Dollar+ shares are valued with the vault's `convertToAssets` at prepare time.
  - **What counts toward the 24 h total:** the sender's link rows created in the last 24 h whose status is `prepared` (younger than 30 min), `pending`, `claiming` or `claimed`.
  - **What does not count:** `failed`, `prepared` rows older than 30 min (never funded), and `reclaimed`.
  - **Atomicity:** the sum and the insert run in one transaction that holds `select_for_update()` on the sender's `User` row, so parallel prepares cannot exceed the total.
  - **Stale prepares:** `submitLinkInvite` refuses a `prepared` row older than 30 min and marks it `failed`. The sender must prepare again, which re-checks the limit.
  - **Self-broadcast:** a sender who broadcasts `createInvitation` themselves (bypassing submit) creates an on-chain invite with no `pending` row and no link. It can never be claimed, because claim needs the backend row and the sponsor. The funds only come back through the sender's own reclaim after 7 days. This is not a way around the limit.
- **Notice** shown before the first link: "Los envíos por link tienen un máximo de US$10 (US$100 por día). Cuando tu contacto lo reciba y confirmes su cuenta, podés enviarle sin límite."
- The app generates an ephemeral secp256k1 keypair and stores the private key in react-native-keychain under `link_invite:<inviteRef>`. The key never goes to the server.
- `inviteId = keccak256(abi.encode(ephemeralAddress))`.
- `prepareLinkInvite(phone: String!, amount: String!, tokenType: String!, claimKeyAddress: String!)`:
  - Creates a `PhoneInvite` row with the new fields `kind='link'`, `claim_key_address`, `public_ref` (uuid4), and `phone_key` = the normalized recipient number. That is the send graph: plaintext, the number the sender chose.
  - Returns the same unsigned `createInvitation` transaction the existing prepare returns.
- `submitLinkInvite` reuses the existing submit path.
  - On confirmation it reads `invitations(invitationKey(inviter, inviteId)).expiresAt` from the escrow, stores it in a new `PhoneInvite.expires_at`, and moves the status `prepared → pending`.
  - The on-chain `expiresAt` is the only authoritative expiry. The UI and the reclaim logic read the stored copy.
- The app then opens `https://wa.me/<E164 digits>?text=<encoded message>`.
- **Message (es):** "{senderName} (@{username}) te envió dinero con Confío. Abrilo en la app: https://confio.lat/r/{public_ref}#{privkeyHex}. Confío nunca te pide códigos ni contraseñas." There is no amount in the URL.

**Claiming:**
- `https://confio.lat/r/*` is a universal link / app link to the route `LinkClaim`.
  - The web fallback page says only "Abrí este enlace en la app Confío" with store buttons. No forms.
  - The Open Graph preview is fixed generic text.
- `linkInvite(publicRef)` returns `{senderUsername, senderVerifiedName?, amount, tokenType, status, expiresAt}`.
- To claim, the app signs the EIP-191 message `Confio link claim\nchain:{chainId}\nescrow:{escrow}\ninvite:{inviteId}\nrecipient:{recipientAddress}` with the ephemeral key.
- `claimLinkInvite(publicRef: String!, signature: String!)`:
  - The recipient address is the caller's personal BSC account from the JWT, never a parameter.
  - The server recovers the signer and checks `== claim_key_address`, `status=='pending'`, not expired, and `caller != inviter_user`.
  - It then sponsor-calls `claimInvitation(inviteId, inviter, recipient, eligible, minOut)` with eligibility from `cusd_plus` (as `ClaimInviteForPhone` does) and sets `claimed_by_user`.
  - **Concurrency:**
    - The mutation takes `select_for_update()` on the `PhoneInvite` row and moves it `pending → claiming`, storing `claiming_user` and `claim_started_at`. Only then does it submit the sponsor transaction.
    - A second caller that finds `claiming` or `claimed` gets `status` back and sends nothing.
    - The signed transaction's hash is stored in `claim_tx_hash` BEFORE broadcast.
    - Mined success: `claiming → claimed`.
    - Mined revert, or an error raised before signing or broadcast: `claiming → pending`, and return the error.
    - A broadcast whose outcome is unknown (timeout, RPC error after send) stays `claiming` and returns `status='claiming'`.
  - **Recovery:** a Celery task `reconcile_claiming_link_invites` runs every 5 minutes over rows in `claiming` for more than 10 minutes.
    - It first reads `invitations(key).settled` from the escrow.
    - Settled with an `InvitationClaimed` event to `claiming_user`'s address → `claimed`.
    - Otherwise it reads the receipt for `claim_tx_hash`:
      - reverted → `pending`
      - still unknown to the node 30 minutes after `claim_started_at` (dropped) → `pending`
      - otherwise → stays `claiming`
    - Escrow `settled` makes a double payout impossible. This task only keeps the database in line with the chain.
  - Idempotent: a second claim of a claimed link returns `status='claimed'` and sends nothing on-chain.

**Getting the link into the app:**
- **Installed app:** the universal link opens `LinkClaim` with the full URL, fragment included (React Navigation `linking.getStateFromPath` keeps the hash).
- **Signed out:** the full URL is kept in react-native-keychain under `pending_link_claim` and opened right after login completes. It is cleared once the claim succeeds or the link is no longer `pending`.
- **App not installed:** the fragment cannot survive an App Store or Play install. The web page `/r/<ref>` does two things:
  1. It shows "Instalá Confío y volvé a tocar este link en WhatsApp".
  2. It offers a "Copiar link" button. The page's own JS copies `location.href`, fragment included, locally; nothing is sent to the server.

  After install, Enviar/Recibir shows "Tengo un link de envío". It reads the clipboard only when the user taps it, and opens `LinkClaim` if the text matches `https://confio.lat/r/<uuid>#<64 hex>`.

**Expiry and reclaim.** `RECLAIM_PERIOD` is 7 days, from the contract. There is no cancel before expiry (accepted trade-off of reusing the contract).
- At expiry, the sender gets a push.
- **Auto-reclaim on app foreground:** the app queries `myExpiredLinkInvites` (rows with status `pending` and `expires_at < now`).
  - For up to 5 per launch, oldest first, it runs the existing `PrepareReclaimInvite` → sign → `SubmitReclaimInvite` (sponsored).
  - Signing uses the same wallet-signing path and biometric policy as a normal send.
  - A failure leaves the row `pending` and is retried on the next launch.
  - Success sets `reclaimed`.
- Activity shows each link's state (pending, claimed, expired or reclaimed) and a manual "Recuperar" button on expired rows.

**Reminder.** While the link is pending, "Recordarle" re-opens the same `wa.me` URL using the stored key. If the key is gone (for example after a reinstall), the button is hidden.

**Retire the legacy flow.**
- Once `minimum_version` passes the new build (release checklist step 5), `PrepareInviteForPhone` (non-link) refuses new invites.
- `ClaimInviteForPhone` keeps working for already-verified legacy phones until the last pending invite has expired and been reclaimed.

### #7 Saved recipients and direct send

**Model** (`send/models.py`):

```python
class SavedRecipient(SoftDeleteModel):
    sender_user = FK(User)
    phone_key = CharField(max_length=32)        # sender's contact number
    recipient_user = FK(User)
    source = CharField(choices=['link_claim', 'legacy_phone'])
    basis_at = DateTimeField()                  # claim time (link) or first direct send (legacy)
    confirmed_at = DateTimeField()
    class Meta:
        constraints = [UniqueConstraint(fields=['sender_user', 'phone_key'],
                       condition=Q(deleted_at__isnull=True), name='uniq_saved_recipient')]
```

```python
class RecipientRevocation(models.Model):
    sender_user = FK(User)
    phone_key = CharField(max_length=32)
    revoked_at = DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [UniqueConstraint(fields=['sender_user', 'phone_key'],
                       name='uniq_recipient_revocation')]
```

Register both in `config/admin_dashboard.py`.

**Flows:**
- **After a claim:** the sender gets a push and an in-app sheet: "@{username} recibió tu envío. ¿Guardar esta cuenta para {contactName}?". "Guardar" calls `saveRecipient(publicRef)`. "No" creates nothing.
  - **Who may save:** only the invite's `inviter_user`, taken from the JWT.
  - **When:** only for a `claimed` invite, within 30 days of `claimed_at`.
  - **Effect:** runs in one transaction holding `select_for_update()` on the sender's `User` row.
    - It compares the invite's `claimed_at` with the active row's `basis_at` (the claim time for `link_claim`, the send time for `legacy_phone`).
    - If the invite's `claimed_at` is older, it returns `error='stale'` and changes nothing.
    - Otherwise it soft-deletes the active row, creates `SavedRecipient(source='link_claim', recipient_user=claimed_by_user, basis_at=claimed_at)`, and deletes any `RecipientRevocation` for the pair.
    - The newest claim, by claim time, always wins whatever order the saves arrive in.
  - Revoke and LEGACY auto-save take the same lock, so the three never interleave.
- **Direct send** (SAVED or LEGACY): the existing send flow, whose confirm screen shows @username plus the verified legal name when the recipient passed KYC. For a LEGACY first send, the server creates `SavedRecipient(source='legacy_phone')` on success.
- **Sender revoke:** "Olvidar esta cuenta" on the contact detail soft-deletes the active row and writes `RecipientRevocation(sender_user, phone_key, revoked_at)`.
  - While a revocation exists, `resolveRecipientForPhone` returns NONE even when a LEGACY holder exists. The next send goes back to the link flow.
  - `saveRecipient` clears it.
- **Legacy owner unlink:** Perfil → "Desvincular mi número" clears `phone_number`, `phone_key` and `phone_country`, and keeps `country`. `UserBan.phone_hash` is stored separately and is unaffected.

## Acceptance Criteria

**Definitions:**
- "Active real user" = `users.analytics.get_real_users_queryset().filter(is_active=True)`.
- "Non-reviewer" = `not users.review_numbers.is_shared_reviewer_phone_key(user.phone_key)`.

**Test command:**

```bash
AWS_PROFILE=Julian CONFIO_ENV=testnet myvenv/bin/python manage.py test users security send blockchain ramps cusd_plus presale --keepdb
```

The only allowed failures are the 13 known `SeededProviderEligibilityTests` errors (per CLAUDE.md). App tests: `cd apps && npx jest`.

**Prerequisite for #2:** done. `f1f13336…` is live and in settings. The remaining check is the liveness readback on the first real session (see #2).

1. A fresh Google/Apple signup on the new build reaches Home without any phone screen. `SMSVerification` and `TelegramVerification` rows for that user stay at 0.
2. After `minimum_version` and `PHONE_VERIFICATION_ENABLED=False`, Twilio Verify reports 0 sends over the next 24 h (Twilio usage page).
3. After backfill, every active real user who had a non-empty `phone_country` has a non-null `country`. The `country` value differs from `phone_country` only where `residence_country_for` returned a different known country (expected about 15 users).
4. The daily job never sets `country` to null and never overwrites `country_source='review'` while an active `ReviewAccess` exists. Once access ends, it restores the residence country, or else `country_before_review` (which may be null).
5. A US-IP user with `country='AR'` and no review access is still refused by the Ondo GeoPolicy through the IP check (`blocked_by='ip'`).
6. `applyReviewAccess` with a wrong token fails, and the 6th failure in an hour is rate-limited. With the right token and AR, `store_review_exempt` is True for 14 days and then False. The 11th geo-exempt apply in a calendar month fails. Each success produces exactly one ops alert.
7. A geo-exempt review account cannot place a presale buy, stock buy, perps open, crypto buy or on-ramp order above US$20.
8. Personal Didit sessions use `DIDIT_GENERAL_WORKFLOW_ID` whatever the user's country.
9. `prepareLinkInvite` refuses amount > 10 and refuses when the sender's 24 h link total would exceed 100.
10. `claimLinkInvite` refuses:
    - a signature from any key other than `claim_key_address`
    - a claim by the inviter
    - an expired link

    A second valid claim returns `claimed` without a new on-chain transaction.
11. No GraphQL operation in the new build sends more than one phone number per request. `check_users_by_phones` has no caller in the new build.
12. Reclaim: 7 days after creation, opening the sender's app reclaims an unclaimed link and the balance returns.
13. `resolveRecipientForPhone` returns LEGACY only for a non-reviewer holder active within 180 days, and SAVED only for a non-deleted `SavedRecipient` of the caller.
14. Two parallel `prepareLinkInvite` calls of $60 each, from a sender at $0 that day: exactly one succeeds. Submitting a `prepared` row older than 30 min fails and the row becomes `failed`.
15. A claim whose broadcast times out stays `claiming`. Reconciliation moves it to `claimed` when the chain shows settled, and to `pending` when the transaction reverted or was dropped for more than 30 min.
16. `saveRecipient` for an older claim, after a newer claim was saved, returns `stale`. After "Olvidar esta cuenta", a LEGACY number resolves to NONE.
17. Re-applying the review link keeps the previous `ReviewAccess` row (`superseded_at` set). The monthly count includes it. Clearing `REVIEW_LINK_TOKEN` makes `store_review_exempt` False for every account immediately.
18. iOS and Android (real devices): tapping a `/r/` link while signed out, then signing in, opens `LinkClaim` with the key intact.
19. Every new test states its card: `protects / fails_when / no_claim`.
20. Existing tests keep passing, except the 13 known `SeededProviderEligibilityTests` errors.

## Testing Plan

| Layer | What | Count |
|---|---|---|
| Unit | `country_of`, `to_iso2`, `rail_countries` ordering (doc priority, preferred, locale) | +8 |
| Unit | daily refresh: no-null-overwrite, review skip, ISO conversion | +4 |
| Unit | GeoPolicy with `country` (blocked, missing, IP override, alias kwargs) | +6 |
| Unit | review link: token, rate limit, cap, expiry, replace-on-reapply, `enforce_review_cap` | +7 |
| Unit | link invite: limits, signature recovery, inviter self-claim, expired, idempotent claim | +8 |
| Unit | `resolveRecipientForPhone` SAVED/LEGACY/NONE incl. inactive and reviewer keys | +5 |
| Integration | prepare → submit → claim → `SavedRecipient` on BSC fork (anvil) with the deployed escrow bytecode | +2 |
| Integration | expired link → reclaim on fork | +1 |
| App (jest) | AuthContext routes to BiometricSetup with no phone; review deep link stash-and-apply | +3 |
| App (jest) | link message text has no amount, has the fixed domain and the safety line | +1 |
| E2E (device) | Android real device: signup → Home; send link to own second number → claim on second device → save → direct send | 1 run |

## Rules for the implementing agent

1. Acceptance criteria are the `protects / fails_when / no_claim` profile of each test: the observable it protects, the wrong result it rejects, and what green does not prove. Never "make the tests pass".
2. Real code and real tests land in the same change. A placeholder, a stub assertion or a test deferred to a follow-up is not done.
3. Any change to a test, validator, CI step, timeout, tolerance, threshold, snapshot or suppression pragma is reported on its own line in your summary with its justification, before any other result.
4. A reported command names the command and its observed result (exit status, counts, the failing line). A command you did not run is not reported, and stderr is never silenced in a command you cite.
5. Your report is a claim until the parent re-executes it: say what you verified, what you reused, and what you could not check.

## Rollback Plan

- **#1:** the `country` column is additive. Revert the code and `country_of` falls back to `phone_country`. The migration can stay.
- **#3:** keep `PHONE_VERIFICATION_ENABLED=True` and leave `minimum_version` alone until #1 is verified in prod. If the new build misbehaves, lower `minimum_version`. Old builds keep working because the SMS path is untouched while the flag is True.
- **#4:** disable by clearing `REVIEW_LINK_TOKEN`; every apply then fails.
- **#6:** setting `LINK_INVITE_ENABLED=False` makes `prepareLinkInvite` refuse. Pending links still claim or reclaim, because the escrow exits are never paused.
- **#7:** additive model. Deleting rows only sends senders back to the link flow.

## Effort Estimate

| Child | Server | App | Tests | Total |
|---|---|---|---|---|
| #1 residence country + 229-occurrence migration | 8h | 0.5h | 3h | ~11.5h |
| #2 Didit general workflow | 1h | 0 | 0.5h | ~1.5h |
| #3 signup without phone | 1h | 3h | 1h | ~5h |
| #4 review deep link + money cap | 4h | 1.5h | 2h | ~7.5h |
| #5 remove contact discovery | 0.5h | 2h | 0.5h | ~3h |
| #6 link send (incl. claim reconciliation, install handoff) | 9h | 11h | 6h | ~26h |
| #7 saved recipients + direct | 3h | 4h | 3h | ~10h |
| Rollout (checklist steps 1-5, two-platform device runs, Didit console) | 3h | 3h | — | ~6h |

The estimate covers code and tests. Store review time and the 48 h soak in step 5 are calendar time on top.

## Files Reference

| File | Change |
|---|---|
| `users/models.py` | `country`, `country_source`, `country_updated_at`, `preferred_rail_country` |
| `users/tasks.py` | `refresh_residence_countries` (daily) |
| `users/management/commands/backfill_residence_country.py` | new |
| `security/geo.py:51,169,227,262-330` | `country_of`, `to_iso2`, GeoPolicy fields, `store_review_exempt`, `enforce_review_cap` |
| `security/identity_status.py:53-62` | rail-country document |
| `security/didit.py:704,799` | general workflow |
| `ramps/schema.py:2190,2758-2830` | rail country instead of phone country |
| `ramps/bolivia_qr.py:80` | `rail_countries` |
| `ramps/rail_country.py` | new |
| `users/schema.py` (`country` field, `check_users_by_phones`) | own-account `country`; retire discovery |
| `sms_verification/schema.py`, `telegram_verification/schema.py` | `PHONE_VERIFICATION_ENABLED` |
| `users/review_access.py` + model + migration | `applyReviewAccess`, `ReviewAccess` |
| `send/models.py:272` | `PhoneInvite.kind`, `claim_key_address`, `public_ref`, `expires_at`, `claiming_user`, `claim_started_at`, `claim_tx_hash`, `claimed_by_user`, `claimed_at`; statuses `prepared/pending/claiming/claimed/failed/reclaimed`; `SavedRecipient`, `RecipientRevocation` |
| `send/tasks.py` | `reconcile_claiming_link_invites` (every 5 min) |
| `blockchain/invite_send_mutations.py` | `prepareLinkInvite`, `claimLinkInvite`, `resolveRecipientForPhone`, `saveRecipient`; refuse non-link prepare |
| `config/views.py` + `templates/` | `/r/<ref>` fallback page, generic OG |
| `config/admin_dashboard.py` | register `ReviewAccess`, `SavedRecipient` |
| 73 server files reading `phone_country` | classify and migrate per #1 rule |
| `apps/src/contexts/AuthContext.tsx:199-205,369,911-916,1163,1233` | remove phone gate |
| `apps/src/navigation/{AuthNavigator,MainNavigator,linking}.tsx` | drop PhoneVerification; add `review`, `r/:ref` |
| `apps/src/screens/PhoneVerificationScreen.tsx` | delete |
| `apps/src/screens/EditProfileScreen.tsx:163` | remove phone change; add "Desvincular mi número" for legacy |
| `apps/src/services/contactService.ts:92-355` | remove discovery and upload consent |
| `apps/src/screens/SendToFriendScreen.tsx` | resolve kind; link flow; limits notice |
| `apps/src/screens/LinkClaimScreen.tsx` | new |
| `apps/ios/Confio/Info.plist`, Android manifest / data safety | contacts copy, associated domain `/r/*` |

## Out of Scope

- Removing the GraphQL `phoneCountry` field. It stays as the phone's country; revisit once `minimum_version` has passed every phone-era build.
- A new escrow contract with cancel-before-expiry or trustless claim.
- Global "who in my contacts is on Confío" discovery, in any form.
- WhatsApp Business API, Telegram bot phone linking, any OTP replacement.
- Device-level multi-account limits. Rewards are already gated by Didit person-level dedupe (`achievements/referral_security.py`).
- Re-baselining historical country dashboards.

## Related

- `contracts/cusd_plus/ConfioInviteEscrow.sol` (reused unchanged)
- `security/identity_reuse.py` (ban and phone-hash holds unaffected)
