# Wallet reconciliation during social sign-in

Reconciliation changes all active wallet registrations owned by the user. It does not
transfer funds, claim that old funds migrated, or rewrite existing transactions.

## Recovery and authorization

- Discover the server-owned account inventory during sign-in. A locally recovered
  key matching all registered addresses uses ordinary login. Employee-only access
  does not include a business wallet in the inventory.
- For a Google mismatch, read the single canonical Drive manifest and its backup.
  Do not search historical wallets, upload the conflicting local key, or generate
  a new secret on a missing/unreadable backup. The Drive identity must match login.
- Apple uses the synchronizable Keychain secret, never a new Google authorization.
- Confirmed legacy V1 accounts without master-secret backups retain legacy recovery.
  If local V2 material is genuinely absent and every owned registration is V1,
  first reproduce every deterministic V1 address using the sign-in JWT. Matching
  V1 wallets do not require Google Drive authorization. Corruption is not absence.
- When no canonical manifest exists, the exact old subject-named encrypted backup
  remains readable for compatibility, but only if it matches every registered
  address. It cannot authorize replacement; no history/trash scan is performed.
- For a different recovered wallet, obtain a ten-minute server-signed grant tied
  to fresh, non-revoked Google/Apple authentication, the entire account inventory,
  contexts, old addresses, primary replacement BSC address and nonce. Sign the
  primary challenge plus an account/address-bound challenge for every owned
  context using keys derived from the recovered master secret. Verify Keychain
  persistence before completing the mutation.
- The server validates authentication and ownership, not cloud-storage contents.
  Backup verification occurs client-side; backup-status reporting is not an
  authorization factor.

## Registration transition

The completion mutation locks the owner and all owned Account rows in fixed
order, rejects changed inventories, stale grants, omitted/duplicate proofs and
address ownership conflicts, retains old destinations in RetiredWalletAddress,
and binds every recovered BSC wallet in one transaction. A failure on any account
rolls back every registration and audit insert. It marks each account V2 and clears
its legacy Algorand destination. Old-wallet balances and chain availability do not
gate this transition. No transaction, pending payment, balance or entitlement is
rewritten. Old funds remain at their original addresses and are not made usable
by changing this registration.

The old addresses are audit records, not active receive destinations or extra
spendable balances. Invalidate the registered-address monitor cache after commit.
Legacy balance reads bypass account-level cached holdings when there is no
active Algorand address, so old funds cannot reappear through a cache fallback.
An address owned historically by another account cannot be registered. Recovery
of this account's own historical BSC address can reactivate it without deleting
its audit record. Existing submitted transactions retain their original addresses.

After reconciliation, acknowledge the recovered backup during sign-in rather
than routing to a setup screen. A lost completion response is safe to retry with
the same secret. Storage/access failures never authorize random key generation.
Before replacing the subject-bound secret, invalidate any previous persisted
session. Keep the new JWT request-scoped until reconciliation succeeds. Publish
the verified receive-address cache durably before returning login success.
For Google, a subject/address-bound pending-report receipt lets an interrupted
backup acknowledgment retry without another setup screen. It records only a
public address and is cleared after acknowledgment. A matching local key without
that receipt still follows the normal first-backup requirement.

Legacy address writers serialize their final writes against reconciliation,
reject stale wallet snapshots, and cannot attach Algorand addresses to a migrated
BSC-only account. Generic BSC registration uses a compare-and-set update so an
in-flight background registration cannot restore the previous address.

## Additional accounts and concurrency

The master secret is shared across personal and owned business contexts. The
client derives each wallet using its real account type/index/business ID, and
checks siblings even if the primary wallet matches. No employee-only wallet is
changed. New Account saves take the owner lock so account creation serializes
with reconciliation; application bulk creation must not bypass that boundary.
Lost completion responses are idempotent only when every bound context is already
at its proved target. Inventory changes require a fresh grant.

After commit, clear legacy Algorand signing caches and only the reconciled
contexts' old Algo receiving aliases. Keep master secrets and address-bound
recovery copies. Publish each BSC receiving cache before completing sign-in,
then restore the primary personal wallet as the active signing context.

## Rollout and tests

Deploy the additive backend mutations before distributing the mobile build.
Wallet reconciliation reuses the existing retired-address table and needs no new
wallet migration. This release also includes verified phone relinking: apply
`sms_verification.0003_code_approval` and `telegram_verification.0003_code_approval`
before restarting updated Daphne/Celery processes. Follow the
[EC2 rollout order](deploy-ec2-ubuntu-systemd.md#social-sign-in-and-phone-relinking-release).
Older mobile clients retain their previous behavior until updated.
The new protocol uses inventory-bound version-2 grants (not a client app version).
Version-1 grants are rejected. Single-proof completion is accepted only for a
version-2 inventory containing the sole primary account.
The older empty-wallet reenrollment API also remains sole-primary only: offers
are suppressed for owned siblings, completion rechecks under the owner lock, and
new targets cannot claim historical or soft-deleted registrations of other owners.
The client revokes stale single-wallet offers when inventory discovery sees siblings.

Offline backend tests use real signatures and GraphQL execution with mocked
Firebase/database boundaries, not a live database or production credentials:

```sh
myvenv/bin/python -m unittest tests.test_wallet_reconciliation tests.test_wallet_reenrollment_assessment tests.test_wallet_address_writes
cd apps
./node_modules/.bin/jest --config jest.config.js --watchman=false --runInBand src/services/__tests__/signInWalletReconciliation.test.ts src/services/__tests__/secureDeterministicWallet.backupSync.test.ts src/services/__tests__/walletReenrollmentDecision.test.ts
```

Database regression suites `users.test_wallet_reconciliation_db`,
`users.test_wallet_address_writes_db`, and `users.test_legacy_reenrollment_coexistence`
cover rollback, stale registrations, retired
addresses, all-account rollback, employee exclusion, changed inventories, and
PostgreSQL writers/account creation blocked on locks across reconciliation.
Run them against an isolated test database with external services mocked.

Before release, test
both providers on devices, including interrupted sign-in, missing Keychain,
Drive denial, canonical mismatch, and a lost completion response.

## Verified phone relinking

After SMS/Telegram approves a code, a phone-less user taking an already linked
number receives `relinkConfirmation` with the previous accounts' email/username.
No phone changes until `confirmPhoneRelink(token)` succeeds; cancellation preserves
the original link. A changed previous owner requires a fresh confirmation preview.
Only the phone link moves, not wallets, history or settled invitation claims.
Lost previews can retry the same approved code within its expiry/attempt limit;
lost confirmations can acknowledge the committed link but cannot reclaim it later.
Existing users changing a profile number cannot take another account's number.
Regression suites: `users.test_phone_relinking`, `users.test_phone_relink_confirmation`,
`users.test_phone_preview_recovery`, `users.test_phone_stale_saves`,
`blockchain.test_phone_relink_claim`, and `send.test_phone_relink_claim`.
