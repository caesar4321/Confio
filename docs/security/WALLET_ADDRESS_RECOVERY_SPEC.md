# Wallet address rotation & recovery — spec

Status: **proposed, not implemented**. Written 2026-08-02, revised after three
Codex audit rounds. Statements under "Current behaviour" are verified against the
code at that date and cite what was checked; everything under "Design" is a
proposal awaiting the decisions at the end.

## Why this exists

The server stores a **pointer** — `Account.algorand_address` — to a wallet whose
key only the device holds. Nothing today proves that the device asking to move
that pointer is entitled to move it. The only gate is a balance check
(`get_address_reassignment_blocker`), and a balance check cannot answer that
question.

Two observed failures:

1. **Silent permanent pin (user 4322, 2026-08-02).** A Redmi/MIUI device lost the
   Android Keystore when the user first enrolled a screen lock. The app
   re-derived a new wallet and tried to self-heal by re-registering the pointer.
   The server refused (the old address held 0.1 ALGO of sponsor dust, exactly at
   the threshold). The client never read `success`, so nothing surfaced. The
   account could not deposit until support reconstructed the cause by hand. The
   user recovered only because their Drive backup turned out to be real and a
   re-login restored the original secret.
2. **Post-sweep dead end.** If V1 is swept to V2 and the following address
   registration is refused, nothing reaches that registration again: the backend
   refuses to prepare a migration once `account_info(v1)` returns missing
   ([blockchain/mutations.py:2545](../../blockchain/mutations.py)), and
   `checkNeedsMigration()` reads the same missing V1 as "nothing to do"
   ([apps/src/services/migrationService.ts:172](../../apps/src/services/migrationService.ts)).
   Funds are on V2; the pointer and `is_keyless_migrated` can stay on V1
   indefinitely.

Same root cause: **pointer changes are a side effect of other flows instead of an
operation with its own states, proofs, and failure handling.**

## Current behaviour (verified 2026-08-02)

- `UpdateAccountAlgorandAddress` ([users/schema.py:3323](../../users/schema.py))
  accepts any string as the new address. It binds the account to the JWT context,
  so it cannot target another user's account, but requires no proof of possession
  of either key.
- The only gate is a balance heuristic. `spendable_algo = amount - min-balance`
  understates recoverable value: migration frees MBR by closing opt-ins and
  sweeps with `close_remainder_to`. Third-party ASAs are ignored entirely, and
  `auth-addr` (rekeying) is never inspected.
- `Account.algorand_address` is not unique, so the DB gives no identity binding.
- Phone/user sends resolve the recipient from `Account.algorand_address` at send
  time ([blockchain/mutations.py:1047-1053](../../blockchain/mutations.py)).
  **A wrongly-pointed account captures future inbound payments even when its
  balance is zero.** This is why "zero balance" is not "zero value".
- **Derivation differs by generation, and this drives the whole design.** V1
  derives from OAuth claims plus a server-held pepper, and any authenticated
  account context can request that pepper
  ([users/web3auth_schema.py:1044](../../users/web3auth_schema.py),
  [apps/src/services/secureDeterministicWallet.ts:400](../../apps/src/services/secureDeterministicWallet.ts)).
  V2 derives from a separately persisted random master secret and ignores OAuth
  identity inputs
  ([apps/src/services/secureDeterministicWallet.ts:1794](../../apps/src/services/secureDeterministicWallet.ts)).
- Already fixed (2026-08-02): the guard fails closed when the chain cannot be
  read; `registerAlgorandAddressChecked` reads `success`; addresses are redacted
  in the logs it touches. **Narrow claim:** only callers migrated to that helper
  read the result. `p2pSponsoredService.ts` and `TradeChatScreen.tsx` still
  discard the payload (deprecated P2P flow, deliberately left).
- `MarkWalletMigrated` still returns `true` to the UI after three refusals and
  updates local state anyway
  ([apps/src/services/migrationService.ts:526-543](../../apps/src/services/migrationService.ts)).
  The retry loop is real; the state machine is not.

## Invariants

1. A pointer moves only when the **user** authorized this specific destination —
   not merely when someone can sign for it.
2. Local device state is committed only after the server accepts, or is rolled
   back. Never local-first.
3. Every refusal produces a named state the app can show and retry from.
   `needsMigration: false` is not a failure state.
4. "We could not check" is never recorded as "there is nothing there" (done).
5. Losing a key is **recovery**, not rotation: delayed, notified, cancellable,
   and never authorized by a balance threshold.
6. While recovery is pending, the account must not silently accept inbound funds
   into a wallet nobody controls.
7. Funds-on-V2-with-pointer-on-V1 is repairable by the client, not only support.

## Design

### What proof of possession does and does not buy

Signing with the **new** key proves the destination key exists. It does **not**
prove the user chose that destination — an attacker naming their own address can
always sign for it. New-key PoP prevents typos and unusable addresses; it is not
an anti-hijack control. Treating it as one was the central error of the previous
draft.

Signing with the **old** key is the real control, and its strength depends on
generation:

| | Old-key signature proves | Why |
|---|---|---|
| **V2** | Meaningful independent factor | derived from a random master secret held on the device / in the user's Drive; an authenticated session alone cannot reproduce it |
| **V1** | Little or nothing | derived from OAuth claims plus a server pepper that any authenticated context can request — the same session mounting the attack can re-derive the key |

Consequences: self-service rotation is available to **V2 accounts** with both
signatures. **V1 accounts cannot self-serve rotate**; they migrate to V2 first
(the sweep already exists) or go through recovery. Any design that treats an
old-key signature as uniformly strong is wrong on V1.

### Rekeying

A signature from the original address key does not prove control of a rekeyed
account, and the legitimate signer of a rekeyed account cannot produce one.
Rotation must read `auth-addr` and either require the effective authorization
key, require rekey reversal first, or refuse self-service rotation for rekeyed
accounts. Pick one explicitly; silence here is a hole.

### The signed transcript

Both signatures cover **identical canonical bytes** containing every field that
scopes the authorization:

```
confio-address-binding:v1
| operation      rotation | recovery
| user_id
| account_id                (immutable row id, not type+index)
| business_id                (or empty)
| old_address
| new_address
| pointer_version           (monotonic, bumped on every accepted change)
| network / genesis_id
| nonce                     (server-issued)
| expiry                    (server clock)
```

Binding `new_address` is what stops a captured old-key signature from authorizing
a different destination. Nonces are server-side, single-use, scoped to account
and operation, consumed **atomically with the state transition**, and rejected
past expiry by server time. Cancellation tokens are single-use with their own
authorization rule.

### Rotation vs recovery

**Rotation** — old key available, V2 only. Both signatures over the transcript.
Immediate. No balance gate: proving control of both ends is strictly stronger
than any balance heuristic, which is then demoted to an abandonment warning.

**Recovery** — old key lost. The case that actually hit us. Requires strong
reauthentication (fresh OAuth, not a cached session), a cooldown, notification to
every channel we have with one-tap cancel, and archival of the old address on the
account row rather than overwriting it.

**During `recovery_pending`, inbound routing must change.** Sends resolve the
pointer at send time, so leaving the pointer on a lost wallet during a cooldown
means every Confío payment in that window lands somewhere unrecoverable. Block
Confío-mediated inbound sends and deposit-address presentation for the duration,
or warn the sender explicitly. Without this the cooldown converts a recoverable
situation into a stream of losses.

**No zero-balance fast path.** The earlier draft proposed skipping the cooldown
for accounts with no funds. Rejected: a zero-balance account still receives
money, so skipping the delay lets a stolen session capture every future inbound
payment immediately. Zero balance is exactly the population this must protect.

### Client state

Replace the `needsMigration` boolean with an explicit union. A generic
"refused" is not enough — a swept wallet needs different reconciliation than a
pre-sweep refusal:

| State | Meaning | UI |
|---|---|---|
| `ok` | pointer and device agree | none |
| `migration_pending` | V1 holds value, sweep needed | migration modal |
| `registration_pending` | swept or derived, pointer not yet accepted; retry on every launch | progress + retry |
| `registration_refused` | server rejected, pre-sweep; retryable | banner with server reason |
| `mark_pending` | pointer moved, `is_keyless_migrated` not yet set | silent retry |
| `recovery_required` | device cannot produce the registered address | recovery entry point |
| `recovery_pending` | cooldown running; inbound restricted | prominent, with cancel |
| `key_missing` | pointer matches, signing key gone | recovery entry point |
| `unverified` | chain unreadable; retry later | soft banner, no destructive action |
| `stale_pointer` | another device rotated; this one is behind | re-sync prompt |
| `no_algorand_pointer` | BSC-only account | none (not an error) |

`MigrationModal` and `useBackupEnforcement` consume the union instead of
inferring success from `needsMigration: false`.

### Post-sweep reconciliation

Server intent row **and** client mirror — not either/or. The client mirror drives
UI and resume; it cannot be authoritative because it dies on reinstall, Keychain
loss, a second device, or account switch, and it may retain a target address
whose key it no longer has.

The intent row must not authorize anything merely by existing. It carries
prepared / submitted / confirmed / registered / marked states, the expected group
or transaction id, old and new addresses, the pointer version it was created
against, and an expiry. Finalization requires validated proof at creation **and**
confirmed on-chain evidence, then an atomic compare-and-set against the current
pointer version. Otherwise a stale, abandoned, or attacker-created intent can
move the pointer later without anyone asking.

### Support path

Today's playbook — clear `Account.algorand_address` and the user's backup fields
so the next login re-registers — stays as break-glass, but becomes an audited
admin action recording who, when, why, and the previous value.

## Also worth folding in

- `MarkWalletMigrated` still fails open on an unreadable chain: both
  implementations ([users/schema.py:5624](../../users/schema.py),
  [users/web3auth_schema.py:1180](../../users/web3auth_schema.py)) read
  `has_material_risk` and ignore `inspection_failed`. One line each.
- The `web3auth_schema` variant can additionally apply `new_address`, which is
  unsafe if schema ordering ever exposes it.
- `DepositScreen` discards `businessOptInService`'s result
  ([apps/src/screens/DepositScreen.tsx:216](../../apps/src/screens/DepositScreen.tsx)),
  so a refused business-address registration is invisible to the user.

## Test plan

- Server: transcript signature verification (valid, wrong key, wrong destination,
  replayed nonce, expired, wrong pointer version); cooldown enforcement and
  cancel; rekeyed-account handling; audit row written; compare-and-set under
  concurrent rotation.
- Inbound policy: a send to an account in `recovery_pending` is blocked or warned,
  not silently routed to the old pointer.
- Client: every union state renders and retries; local state is not written when
  the server refuses; an app killed mid-flow resumes to the same state.
- Recovery: post-sweep refusal reconciles on next launch with no support action.
- Regression: user 4322's exact shape — empty wallet, lost key, V2 account —
  reaches `recovery_required` and completes self-serve.
- Boundary tests use the real SDK exception types, not hand-written stand-ins.

## Decisions needed

1. Cooldown length, and the inbound policy during it: hard block on
   Confío-mediated sends, or warn-and-allow?
2. V1 accounts: force migration to V2 before any rotation, or route them
   straight to recovery?
3. Rekeyed accounts: require the effective key, require reversal, or refuse
   self-service?
4. Does this ship before or after `ALGORAND_ONBOARDING_ENABLED` is turned off?
   That changes how much of it needs an Algorand path at all.
