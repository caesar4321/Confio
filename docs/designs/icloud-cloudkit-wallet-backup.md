# iOS wallet backup in CloudKit

Status: draft under /plan-eng-review. Nothing built.
Target of review: this document. Base commit: aea9ddbeb.

## Problem

The iOS master secret has one cloud copy: a `synchronizable` Keychain item
(`apps/src/services/credentialStorage.ts:61`). The app cannot tell whether that
item ever left the device, yet every iOS user is reported as backed up:

- `apps/src/contexts/AuthContext.tsx:927` reports `icloud` after every login.
- `apps/src/services/authService.ts:2354` reports it again for Apple sign-in.
- `apps/src/services/secureDeterministicWallet.ts:2947` reports it from the secret path.
- `apps/src/hooks/useBackupEnforcement.tsx:304` skips backup enforcement on iOS.

So with iCloud Keychain off, a lost or replaced phone means a lost wallet, and
no data on the server can say how many people are in that position.

## Goal

Every iOS user with iCloud available gets a second copy that the app has proven
exists by reading it back from Apple's servers, with no prompt and no password.
The server learns who has that proof for their current wallet, the first real
measure of this exposure.

## Design

### Storage

- CloudKit **private database**, default zone, new container
  (`iCloud.com.Confio.Confio`, matching bundle id `com.Confio.Confio`).
- One record per wallet, record type `WalletBackup`, one field `payload` (String).
- `payload` is the same body Drive stores: `encryptBackupV2(secret, APP_BACKUP_KEY)`.
  This is the deliberate light wrap. The protection is the person's Apple
  account. User copy must never call this backup "cifrada".
- `payload` is a plain field. It is **not** in `encryptedValues` and not a
  `CKAsset`. Apple documents that encrypted fields depend on key material in
  iCloud Keychain, and that assets are protected under Advanced Data Protection.
  Using either would recreate the dependency this feature exists to remove.

### Record naming

`recordName = "wallet-" + sha256(normalized server anchor address)`.

A wallet is written once under each anchor it has (BSC, Algorand). This gives:

- No query, so no indexed field in the schema. Restore fetches by exact name.
- One iCloud account can hold several wallets without collisions.
- A record is only ever inserted, never updated. If the insert hits an existing
  record, read it and compare. Same secret: done. Different secret: keep it,
  report a failure, change nothing. This is the overwrite that cost user 2785
  their key on Drive (`secureDeterministicWallet.ts:3280`).

The address is hashed so the record name carries no chain address.

### Write path

```
app foreground, signed in, iOS
  └─ ensureCloudKitBackup()              new, apps/src/services/cloudKitBackup.ts
       ├─ stored marker valid for this wallet + iCloud user?
       │     yes, acknowledged ── stop
       │     yes, not acknowledged ── report only
       ├─ read local secret; record names derive from it, so a stale key only
       │  adds an inert record. The server refuses proof that misses any
       │  registered primary address.
       ├─ accountStatus != available ── report state, stop
       ├─ insert record
       ├─ fetch record from server (not from the write result)
       ├─ decrypt payload, compare bytes to the local secret ── differ ─ failure
       ├─ write local "stored" marker (non-synchronizable)
       └─ report proof to server, retry until acknowledged
```

It runs outside `getOrCreateMasterSecret`. The fast path there returns early
(`secureDeterministicWallet.ts:2907`), and skipping an upload inside that path
while reporting success is what caused the July Drive lockout.

The marker holds the wallet hash and a hash of the CloudKit `userRecordID`, so
changing iCloud account triggers a new upload.

Failures retry on a later foreground with backoff. They never block the user.

### Restore path

Restore lives in sign-in reconciliation, not in `getOrCreateMasterSecret`.
`reconcileSignInWallet` runs first (`authService.ts:2071`), and an Apple account
with a registered wallet and no local key is rejected there
(`signInWalletReconciliation.ts:305`), so a later hook would never run.

```
reconcileSignInWallet, candidate has no match (iOS only)
  fetch wallet-<hash> for the personal/0 anchors
    found      → candidate from payload → existing matchesAll() over every owned account
    not found  → today's path, unchanged
    read error → remember "unknown", keep trying remaining sources
  Drive (Google users), as today
  a source validated against the anchors → sign in
  nothing validated and "unknown" set → typed retry error
        no generation, no createMissingSignInWalletCandidate, no replacement
```

An outage must not block a recovery another source can complete, and must not
turn into "no backup exists". Without the second rule it could reach
`canReplaceAfterRecoveryFailure` (`authService.ts:2183`) and retire a wallet.

Sibling accounts derive from the one master secret, so a record per personal/0
anchor is enough. `matchesEveryAnchor` only checks personal/0
(`secureDeterministicWallet.ts:691`), which is correct for the upload guard;
restore still passes the full `matchesAll()`.

### Native module

`apps/ios/Confio/ConfioCloudBackup.swift` + `.m`, following `ConfioAudioRoute`.
Methods: `accountStatus`, `insert(recordName, payload)`, `fetch(recordName)`,
`userRecordHash`. Errors keep their CloudKit code. Every call has a timeout.

### Scope of users

All iOS users, whichever provider they signed in with. Line 927 reports `icloud`
for Google users on iPhone as well, and they skip enforcement too. Anchor-keyed
records make the provider irrelevant.

### Server state

CloudKit gets its own fields. Existing `backup_provider` and `backup_verified_at`
stay exactly as they are, including the implicit `icloud` report. That report
must not be tightened: `backup_verified_at` null gates setup
(`users/models.py:350`), so proof-only reporting would trap every iOS user
without iCloud.

New on `User`:

- `cloudkit_backup_verified_at`: set only after a verified read-back.
- `cloudkit_backup_wallet_hash`: the anchor hash that was proven. The mutation
  rejects a hash that does not match the user's current personal/0 anchor, so a
  replaced wallet does not inherit proof, and "proven" only counts while this
  hash equals the current one. Reports use the pinned session token.
- `cloudkit_backup_state`: `proven`, `no_icloud_account`, `icloud_restricted`,
  `failed`. Null means no report reached the server, for any reason.

New mutation `reportCloudKitBackup`, separate from `ReportBackupStatus`, in its
own try/catch so an older server cannot fail a shared request.

The state never gates a user.

Metric: iOS users without observed CloudKit proof, with `no_icloud_account` and
null shown separately. This is not "users with no backup": Keychain may still
sync and Drive may exist. Filter on iOS sessions, not `backup_provider`, because
`google_drive` wins over `icloud` (`users/schema.py:6154`).

## Decision ledger

Approved by the user during review:

- R0: CloudKit proof uses a separate flag, not the `icloud` provider value
  (user message, 2026-10-30). Stored as the fields above rather than a new
  `backup_provider` value, because that field has one value per user and Drive
  would overwrite it.

- R1 structure: original arrangement, about 11 files and 2 new classes
  (D2, user answer, 2026-10-30).

- R2 privacy: plain CloudKit field, readable by Apple, accepted for parity with
  Drive, where `appDataFolder` hides files from the user and other apps but
  Google holds the keys (D3, user answer, 2026-10-30). Security docs must be
  updated with the build.

## NOT in scope

- Changing Android or Drive behaviour.
- Password-based encryption (`backup-key-by-design`).
- Moving a wallet between iOS and Android.
- Deleting CloudKit records when an account is deleted. Same as Drive today,
  old records are inert without a matching anchor. Worth a later look.
- Any Algorand-specific work.

## What already exists

- `encryptBackupV2`, `decryptBackupV2`, `APP_BACKUP_KEY`: reused as is.
- `matchesEveryAnchor`, `secretsEqual`: reused for upload and restore checks.
- `storeAddressBoundMasterSecret`: same address-keyed idea, reused as the model.
- `onCloudSyncResult`: the Drive proof pattern this copies.
- `ConfioAudioRoute`: native module template.

## Required before implementation

**Device probe: core result passed (2026-10-30).** iPhone SE, Development
environment, plain String field, fake payloads only. iCloud Keychain was turned
off by hand on the device; the probe cannot read that setting itself.

| Check | Keychain on | Keychain off |
|---|---|---|
| `accountStatus` | available | available |
| Insert | ok | ok |
| Fetch and compare | match | match |
| After reinstall | record kept | record kept |
| Second insert | CKError 14, value kept | CKError 14, value kept |
| Record from the other run | n/a | readable |

A new container failed with CKError 5 for about 3 minutes, then worked.

Not yet proven: the per-app iCloud switch off, the Production environment, and
restore on a different or erased device with Keychain off.

**Release step.** CloudKit schema must be deployed to Production before the
App Store build ships. TestFlight and App Store builds use Production, so a
missed deploy fails every write while Development builds look fine.

## Premises

| Premise | Receipt | Verdict |
|---|---|---|
| iOS has no second cloud copy for Apple users | no CloudKit code; `Confio.entitlements` has no iCloud key | true |
| `icloud` is reported without proof | `AuthContext.tsx:927` | true |
| A server `backup_verified_at` null gates setup | `users/models.py:350` | true |
| Encrypted CloudKit fields depend on iCloud Keychain | Apple, Encrypting User Data | true |
| Plain CloudKit fields work with Keychain off | device probe, 2026-10-30 | true on one iPhone, Development environment |
| Plain fields are readable by Apple | Apple Platform Security, service keys | true by documentation |

## Failure modes

| Path | Failure | Handling | User sees |
|---|---|---|---|
| Upload | iCloud signed out | state `no_icloud_account` | nothing |
| Upload | Production schema not deployed | state `failed`, metric at zero proofs | nothing; caught by canary check |
| Upload | Read-back differs | no marker, state `failed` | nothing |
| Upload | Report lost | marker unacknowledged, retried | nothing |
| Upload | Existing record holds another secret | keep it, state `failed` | nothing |
| Restore | CloudKit outage, no other source | typed error, nothing generated | retry message |
| Restore | Other iCloud account on the phone | not found, today's path | today's message |
| Server | Wallet replaced after proof | hash mismatch, not counted | nothing |

No critical gaps: every silent path leaves a server state.

## Test plan

Regression contract: sign-in with a working local key makes no CloudKit call and
behaves as today.

- `signInWalletReconciliation`: found and valid restores; found but anchor
  mismatch is refused; not found keeps the RECOVERY-APPLE-KEYCHAIN result; read
  error plus empty Drive refuses generation and replacement; read error plus
  valid Drive succeeds.
- `cloudKitBackup`: read-back mismatch leaves no marker; existing different
  record is untouched; unacknowledged marker reports without uploading; iCloud
  account change uploads again; secret failing the anchors never uploads.
- Server: stale hash rejected; proof not counted after wallet replacement;
  `backup_verified_at` and `backup_provider` unchanged by the mutation.
- Real iPhone, TestFlight build: the device probe plus erase-and-restore.

`[→E2E]` real-device restore. Native Swift has no unit coverage in this repo, so
that probe is the only proof of the module.

## Performance

One insert and one fetch per wallet, once, on foreground off the sign-in path.
Restore adds one fetch only when no local key matches. Calls need a timeout
(about 10 s, estimated) so a slow iCloud cannot stall sign-in.

## Implementation Tasks

- [x] **T0 (P1, human: ~2h / CC: ~30min)** Device probe with Keychain off: passed.
- [ ] **T1 (P1, human: ~2d / CC: ~1h)** Container, entitlements, profile, `ConfioCloudBackup`.
- [ ] **T2 (P1, human: ~2d / CC: ~1h)** `cloudKitBackup.ts`, foreground trigger, acknowledgement retry.
- [ ] **T3 (P1, human: ~2d / CC: ~1h)** Reconciliation restore with the unknown state.
- [ ] **T4 (P1, human: ~1d / CC: ~30min)** User fields, migration, mutation, admin column.
- [ ] **T5 (P1, human: ~1h / CC: ~10min)** Deploy schema to Production, confirm a TestFlight write.
- [ ] **T6 (P2, human: ~2h / CC: ~15min)** Update `docs/security`: backup is readable by Apple, as Drive is by Google.

Sequential implementation, no parallelization opportunity.

## Suppressed findings

None.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | not run | |
| Outside Review | codex, default-on | Independent 2nd opinion | 1 | completed | 6 findings, 1 critical, all applied to this design |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | issues_open | 6 issues, 0 critical gaps remaining |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | not run, no UI in scope | |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | not run | |

- **OUTSIDE COVERAGE:** codex, plan review, completed, 6 findings.
- **VERDICT:** Eng review findings are applied to the design, implementation gated on T0. Eng review required again only if T0 changes the storage choice.

NO UNRESOLVED DECISIONS
