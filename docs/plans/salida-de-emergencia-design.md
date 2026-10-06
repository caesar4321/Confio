# Salida de emergencia — server-independent full exit (design)

**Status**: approved 2026-07-22 (Julian + Claude + Codex/ChatGPT debate, three rounds)
**Amended**: 2026-08-03 — raw key export rejected outright; this design is no
longer one half of a pair (§ «Rejected: raw key export»)
**Owner track**: self-custody survivability ("what if Confío disappears?" — Peru)
**Siblings**: Emergency Recovery Kit (post-app-deletion — separate track)
**Rejected sibling**: Exportar claves — cancelled 2026-08-03, never built (see
«Rejected: raw key export» below). Salida de emergencia is now the *only*
survivability path, not the mass-market half of a pair.

## Phase 3: on-chain heartbeat is the only trigger (2026-10-05) — SUPERSEDES

Decided by Julian on 2026-10-05. **This section overrides every timing
matrix, route and principle below.** The older sections stay for history.

**Why.** Users cannot reach their keys (Drive appDataFolder and the team
keychain are readable only by Confío's signed app), so a ban plus the relay
refusing to sign is a real freeze, and Emergency Exit was the only way around
it. A provider fraud report (money mules, 2026-09) needs that
freeze to hold until a local authority acts. The narrative is "if Confío
fails, your money doesn't die with it", not "Confío can never stop you".

**The rule.** Emergency Exit is available to every user only once
`ConfioHeartbeat` has had no beat for 14 days (`silenceRequired`). Nothing
else opens it:

- no ban route, no Confío Face, no device attestation for the exit;
- no normal-state exit or cooloff of any length;
- no client-judged outage (Confío domain probes, the Cloudflare outage
  Worker, the phone's local 72h rule).

**Enforced on-chain, atomically.** The exit is one self-signed BSC
transaction to the user's own EOA through `ConfioBatchDelegate.execute`, and
its first call is `ConfioHeartbeat.assertSilent()`. While Confío beats, the
whole batch reverts on-chain, whatever RPC, DNS or server state the phone
saw. A beat that lands before the exit reverts it too. Users whose EOA is
not yet delegated include the 7702 authorization in the same (type-4)
transaction.

**Contract** (`contracts/cusd_plus/ConfioHeartbeat.sol`, tests
`test/ConfioHeartbeat.t.sol`): UUPS proxy owned by the BSC Safe, same
pattern as the vaults, upgradeable on purpose (fixing it too early is the
bigger risk). `beater` (KMS signer) posts `beat()`; the owner can rotate the
beater and change `silenceRequired` within [1 day, 365 days] — the change is
retroactive, so beat right before lowering it; a fresh deploy counts as a
beat; renounce disabled; an uninitialized address (the bare implementation)
fails closed (`NotInitialized`). Two Claude audit rounds, the second clean.
Deploy only with `script/DeployConfioHeartbeat.s.sol` (proxy + initialize in
one transaction, so initialize cannot be front-run).

**Fail-open guard in the app.** The delegate treats any successful call as a
pass, and a codeless address always succeeds. So the app bundles the PROXY
address and refuses to call the exit open unless that address has code,
`beater()` is non-zero and `silenceRequired()` is non-zero
(`emergencyExit/heartbeat.ts`). The owner is deliberately NOT pinned: a Safe
rotation would otherwise close every shipped build's exit for good. The gate
primitive (`gatedTx.ts`) re-checks all of this itself before every send.

**Banned users.** BlockedAccountScreen is where a banned user's app always
opens, and after Confío dies nothing can clear their ban flag. So that screen
reads the heartbeat and shows the exit entry ONLY when the chain says it is
open; while Confío beats, the ban keeps the funds frozen.

**As built (2026-10-05, uncommitted):**
- App: `heartbeat.ts` (read state from public RPCs), `gatedTx.ts` (every
  exit send = `execute([assertSilent(), leg])` to the user's own address;
  type-4 with a self-sponsored authorization when not delegated; a status-1
  receipt without `BatchExecuted` is never a success), `bscExit.ts` (pre-flight
  `assertExitOpen`, every leg gated, a closed-gate revert stops the exit with
  no fallback), `evmWallet.ts` (`encodeExecuteCalldata`,
  `signSetCodeTransaction` — byte-identical to eth_abi/eth_account), the
  screen (closed: signal card, how it works, how to prepare; open: the
  4-step wizard), BlockedAccountScreen (no exit button; funds stay frozen).
- Backend: `cusd_plus/heartbeat.py` — `post_confio_heartbeat` daily 14:40 UTC
  (health gate: DB + RPC; signer must equal on-chain `beater()`; success
  requires a `Beat` log from the heartbeat contract) and
  `check_confio_heartbeat` hourly (CRITICAL log when the chain shows no beat
  for 26h; ERROR when the beater's BNB is low). Settings
  `CONFIO_HEARTBEAT_*`; empty address = both no-op.
- Removed: server ban route (`security/emergency_exit.py`, views, URLs),
  `workers/outage-status`, reachability/outage/Face/Algorand exit modules.

**Open items.**
- Alerts page the team Telegram group (where Confio Brain lives) through a
  dedicated bot, never Brain's own user session (a second Telethon client
  kills its listener): `config/ops_alerts.py` from the Celery monitor (stale
  hourly + "recovered", low beater BNB, chain unreadable, beat failed after
  every retry) and an outside watchdog, `.github/workflows/heartbeat-watchdog.yml`
  + `scripts/ops/heartbeat_watchdog.py`, hourly from GitHub so a dead
  backend still pages. Setup: create the bot, add it to the group, store
  `prod/ops-alert-telegram` = {"bot_token","chat_id"} in Secrets Manager,
  and the repo secrets OPS_ALERT_TELEGRAM_BOT_TOKEN / _CHAT_ID + repo
  variable CONFIO_HEARTBEAT_ADDRESS. GitHub disables scheduled workflows in
  public repos after 60 days without activity.
- Old app builds keep their old exit logic. With the server ban route gone,
  a banned user on an old build gets no immediate exit; but the old client's
  local waiting-period route (72h, then a second 72h when Face cannot run)
  still opens without the server — and with the outage Worker gone, an old
  build that cannot reach Confío falls back to its local 72h outage rule.
  That residual lasts until those builds are gone; only the new gated exit is
  enforced on-chain.

**Algorand.** Removed from the exit (option a). An Algorand group cannot
read the BSC heartbeat and Algorand gets no new work; Algorand balances move
only through the app's normal flows.

**Work list.**

1. Contract: audit, deploy the proxy, record it in `DEPLOYMENT.md`. Bundle
   the proxy address in the app (`bscExit.ts`, alongside the vault address).
2. Heartbeat job: Celery beat task signing `beat()` with the KMS beater,
   daily. Alert after ~24h without a beat on chain — a silent failure for 14
   days opens every exit, frozen accounts included.
3. App: `bscExit.ts` sends the whole exit as one `execute` batch with
   `assertSilent()` first (today it is a sequence of separate transactions);
   the screen reads `opensAt()` / `isSilent()` from chain to show state;
   remove `algorandExit.ts` from the pipeline.
4. Delete: `workers/outage-status`, `outageStatus.ts`,
   `outageStatusConfig.ts`, the Confío probes and outage state machine in
   `reachability.ts`, `emergencyFace.ts`, the ban route
   (`security/emergency_exit.py`, `security/emergency_views.py`, its URLs and
   tests), and BlockedAccountScreen's «Retirar mi dinero» entry.
   BlockedAccountScreen keeps the support contact only.
5. Copy: no "sin pedir permiso a Confío". The claim is that the app lets you
   move your money to another wallet if Confío stops operating, after 14
   days.
6. Disaster drill on BSC testnet/fork: stop beats, warp/wait past
   `silenceRequired`, run the full exit, and confirm it reverts after a late
   beat.

## What this is

A mass-market escape hatch in each account's **Seguridad** tab: move the
account's entire balance to an external wallet, without exposing keys, and
— in the failure modes that matter — **without any Confío server**. This is
the feature that makes "Confío no puede aprobar, rechazar ni bloquear esta
operación" literally true at the code level.

The answer to survivability is *transfer*, not *keys*.

## Non-negotiable principles

1. **Existence is never server-gated.** A server that fakes health checks
   while refusing sends must not be able to hide this feature. The menu
   entry always exists; server state only modulates prominence.
2. **The server can never delay, shorten, extend, or cancel an exit.**
   All timing judgments are client-local. Faking server death only
   *accelerates* the exit (outage = immediate), so the server gains
   nothing by lying in either direction.
3. **Zero GraphQL in the Direct path.** Compose → sign → broadcast goes
   straight to chain nodes (multiple independent hardcoded RPCs, plus a
   user-entered RPC as last resort). Token addresses, ASA ids, ABIs, and
   network params ship in the app bundle.

## Timing matrix (client-judged)

| Client-observed state | Prominence | Wait |
|---|---|---|
| Explicit ban response from server | Seguridad top | **immediate** |
| Confío unreachable ≥24h (with retries) ∧ chain nodes reachable | Home + Seguridad, strong | **immediate** |
| Normal (server healthy) | Seguridad, low-key | **24h local cooloff** |
| No internet at all | menu exists, execution disabled ("conéctate para continuar") | n/a |

Rationale for the 24h cooloff: in normal state a scammer's only gain over
the existing send screens is one-tap-everything convenience; legit users
in normal state have normal sends, so the cooloff costs them nothing. The
worst a manipulated server can inflict is a 24h delay. A ban or real
outage — the actual emergencies — are immediate: any delay there would be
a de-facto fund freeze and would contradict the narrative.

The cooloff/outage windows are measured against **chain block
timestamps**, not the device clock: a scammer can walk a victim through
Settings → Date, but nobody can walk them through forging a BSC block.
(Older drafts cited Exportar claves as sharing this clock source — that
feature was rejected; the clock rationale stands on its own.)

## Execution modes (same screen, same verification, different engine)

- **Sponsored mode** (server alive — ban case): fee-free, standard
  sponsor-group flows.
- **Direct mode** (server dead): user pays gas. The screen shows, per
  chain: the account's own address + QR, the exact asset needed («ALGO
  para comisiones», «BNB para comisiones»), estimated required amount and
  current shortfall — so a gas-poor user can top themselves up from any
  exchange.

## Transfer pipeline (resumable, per-chain checkpoints)

1. **Destination proof**: connect/paste destination per chain; verify
   control via nonce signature where the destination wallet supports it;
   hard chain-mismatch validation (never let an Algorand address receive a
   BSC instruction or vice versa); reject sending to the account's own
   addresses; Algorand ASA opt-in check with clear warning.
2. **Social-engineering gate**: "¿Alguien te pidió enviar tu dinero a esta
   dirección?" checklist (alone / no call / no screen share / nobody asked
   — financiera, staff, family). Abort on any yes.
   **No capture-abort on this screen (decision 2026-07-22)**: nothing
   secret renders here, and a voice-guided scam needs no screen view, so
   aborting on capture only ever punishes legitimate users (casting,
   accessibility, recording) at the worst possible moment. Instead:
   Android sets FLAG_SECURE (remote-support viewers — the AnyDesk scam
   pattern — see black, passively, with zero abort false-positives); iOS
   shows a non-blocking warning banner when `isCaptured` is true. Hard
   capture BLOCKING was originally deferred to the Exportar claves screen,
   "where actual secrets render". With that feature rejected, **no screen
   in the app renders raw key material**, so hard capture-blocking has no
   remaining home — and needs none. Warn, never abort.
3. **User assets — redeem-to-base-asset FIRST, raw transfer as fallback.**
   "Permissionless" is not "accessible": an external Pera user cannot
   compose the `[cUSD axfer, app call]` burn group, and a MetaMask user
   cannot call `redeemToUsdt` without a dapp page. Handing users raw
   confio-issued tokens strands them with assets no external tool can
   redeem. So the default exit converts to universally-supported base
   assets before sending:
   - cUSD → `burn_for_collateral` (non-sponsored form, verified
     permissionless, 1:1 on-chain USDC reserves) → send **USDC-Algorand**
   - cUSD+ → `redeemToUsdt` (verified permissionless; only raw-USDY
     redeem is owner-gated) → send **USDT-BSC**
   - USDC/USDT already held, and CONFIO (no backing), transfer as-is.
   - Ondo Stocks → transfer each held stock token as-is to the external BSC
     wallet. The canonical BSC token-address allowlist is generated into the
     mobile bundle from `cusd_plus/gm_tokens.json`. Generation is append-only:
     contracts shipped by an earlier release remain allowed even if Ondo later
     delists a stock or rotates its contract. Emergency Exit never trusts
     symbols, wallet token lists, explorer metadata, Confío, or Ondo APIs at
     runtime. Balances are read through Multicall3 in 250-token chunks and
     positive balances are sent in individually checkpointed transactions.
     Newly listed stocks require an app release before Emergency Exit recognizes
     them; this release lag is an explicit tradeoff for a small, deterministic,
     server-independent trust surface.
   Fallback = raw token transfer, only when the redeem leg is dead
   (cUSD: contract paused; cUSD+: Ondo IM down / PP offboarded), with an
   explicit "this token needs a redemption tool outside Confío" warning.
   The symmetric dependency disclosure: cUSD redemption is self-contained
   on-chain; cUSD+ redemption additionally depends on the Ondo IM/PP
   relationship surviving.
4. **No close-out / cleanup mode — removed by decision 2026-07-22.**
   Algorand MBR is *sponsor* money, so a close-out is the exact farming
   primitive the subsidy policy flags; shipping it as UI would hand
   sponsor ALGO to every exit AND permanently flag legitimate returning
   users (same derived address, close-out in history) as farmers.
   Account closure is invisible to users — only assets matter to them.
5. **No native sweeps either (decision 2026-07-22).** Normal accounts
   hold ~zero spendable native balance (auto-convert cleans mis-deposits;
   the sponsor funds exact shortfalls), so a sweep would only ever move a
   Direct-mode gas top-up's leftover cents — and those are MORE useful
   left behind: the account stays alive, and stray future deposits to the
   old address (old QRs, saved payment contacts) can be moved later using
   that leftover gas. Net: the exit moves user assets ONLY, zero native
   ALGO/BNB, on both chains.
6. Per-chain success recorded independently; failed legs retry
   individually; "transfer complete" only when every started leg
   completed. Never a single all-or-nothing status screen.

Biometric at flow start AND immediately before each chain's signing.

## Copy requirements

- Standing description (always visible):
  «Si Confío no está disponible, puedes mover tus fondos directamente
  desde la blockchain. Confío no puede aprobar, rechazar ni bloquear esta
  operación.»
- Outage state: the failure moment is the narrative's proof moment —
  «No podemos conectar con los servidores de Confío. Tu dinero no está en
  nuestros servidores: está en la blockchain y sigue siendo tuyo.»
- Future-deposit warning (critical for business accounts):
  «Esta migración mueve tu saldo actual, pero no redirige pagos futuros.
  Actualiza tu QR y tu dirección de cobro.»
- Marketing (after disaster drill only): «Puedes llevarte tu dinero a otra
  billetera cuando quieras, sin pedir permiso a Confío.» — *tu dinero*,
  not *todo*; never hide the cooloff («…el traslado completo se habilita
  después de 24 horas» when applicable).

## Interaction with subsidy policy

None — by construction. The exit produces zero native outflow on both
chains (no close-outs, no sweeps), so it can never trip the bright-line
farming rule, never false-positives the detector, and never touches
sponsor money. The two policies are fully orthogonal.

## Verified facts this design rests on (checked 2026-07-22)

- cusd.py `burn_for_collateral` / `mint_with_collateral` support
  non-sponsored user-paid forms → Direct mode is contract-supported today.
- CusdPlusVault `redeemToUsdt` is permissionless; only raw-USDY `redeem`
  is owner-gated.
- NOT in this repo: any "BlockedAccountScreen" design or "We cannot
  prevent this transfer" copy (a prior AI discussion cited these; they do
  not exist here — do not cite them).

## Ban work package

CORRECTION 2026-07-22: the backend ban system EXISTS (an earlier claim
here that none existed came from a too-narrow grep). `security.UserBan`
(temporary/permanent/trading/withdrawal types) is enforced by
SecurityMiddleware: EVERY authenticated request from a banned user gets a
plain-text 403 «Your account has been suspended…» before any resolver
runs. Two consequences:

- **Sponsored mode for banned users is impossible** under the current
  middleware — they cannot reach GraphQL at all. Direct mode (user gas)
  is their only path, which the shipped v1 already is. A fee-free ban
  exit would require the backend to exempt specific endpoints.
- The middleware ignores the granular ban types (a withdrawal-only ban
  blocks everything) — backend inconsistency noted for a separate fix.

State of the package:

1. **Banned signal plumbing — SHIPPED**: the Apollo error link matches
   the middleware's exact signature (403 + suspension text; bare 403s
   from proxies don't count) and persists a local flag; any later
   successful GraphQL round-trip clears it (un-ban). The emergency state
   machine reads the flag ⇒ banned = immediate, no cooloff. Safe to
   trust by construction: the signal can only ACCELERATE the exit.
2. **BlockedAccountScreen — PENDING**: the announcement surface (reason,
   appeal path, «we cannot block your funds») with the exit CTA on it —
   mandatory because a banned user's app UI may be unusable, making
   Perfil → Seguridad unreachable. Includes auth-failure reachability.

## Open items

- Disaster drill before any marketing use: real device, Confío domain
  blocked, full exit both chains including the redeemToUsdt leg.
- RPC endpoint list curation (Algorand: Algonode-class public endpoints;
  BSC: ≥3 independent providers) + health rotation.
- Timelocked direct-redeem path on the vault for the Ondo-dead scenario —
  separate contract-upgrade track, not in this scope.
- Emergency Recovery Kit scope addition: an open-source static page that
  composes the cUSD burn group for external (Pera) holders to sign —
  makes cUSD fully self-redeemable post-mortem for anyone who exited with
  raw tokens. (No kit equivalent can exist for cUSD+ — its dependency is
  contractual, not tooling; that is what the vault timelock track is for.)

## Phase 2: Confío Face, the ban route, the outage Worker (2026-09-29)

Amends the timing matrix above (the 24h figures became 72h in the face
step-up release). Decided by Julian on 2026-09-29.

| Client-observed state | Route | Wait |
|---|---|---|
| Server-confirmed ban, KYC'd (Confío reachable) | **ban route** | Confío Face, then immediate. **No waiting-period fallback.** |
| Server-confirmed ban, no KYC selfie on file | ban route | 72h cooloff (no face to check; a ring's pooling account looks like this, and a banned user cannot re-verify) |
| Normal (Confío reachable) | normal | 72h cooloff, then Confío Face (KYC'd users only) or a second 72h wait |
| `blocked`: Confío unreachable from the phone, up per the Worker | normal | 72h cooloff, then always the second 72h wait: the face check cannot run, and the phone cannot confirm the user's KYC status offline (a stored "no KYC" answer could be stale, which would reopen the faceless-72h shortcut), so users without KYC also wait 144h here |
| Outage confirmed by the Worker (down since T) | outage | immediate once T is 72h old (chain time) |
| Confío and the Worker both unreachable | outage | immediate after 72h of local observation |
| No internet | — | execution disabled |

- **Ban route** (`security/emergency_exit.py`, `emergencyExit/emergencyFace.ts`):
  a banned user cannot use GraphQL, so the route uses plain endpoints
  (`/api/emergency-exit/…`) with no JWT. The account is proved by an
  EIP-191 signature over a one-time challenge with the account's own BSC
  key. The server confirms the ban, so a faked 403 (MITM, a tampered
  proxy) cannot route a healthy account here, and a ban flag while Confío
  is unreachable unlocks nothing. This supersedes principle 2 for banned
  accounts: the immediate route requires a successful face check when a
  KYC reference is available. Without that reference, the waiting-period
  route remains available, as specified in the amended matrix above.
- **Device attestation on the exit only**: every ban-route call and the
  normal route's `startFaceCheck(purpose: emergency_exit)` require a
  Firebase App Check token (Play Integrity / App Attest), so the face
  capture comes from the genuine app, not a script or an injected camera.
- **Outage Worker** (`workers/outage-status`): Cloudflare cron probe of
  Confío every 5 minutes; serves an Ed25519-signed `{checkedAt, lastUpAt,
  downSince}`. The app ships the public key and accepts a statement only
  if `checkedAt` is within 30 minutes of chain time. It closes the "block
  Confío's domain for a faceless 72h exit" shortcut unless the Worker is
  blocked too, and dates a real outage from when the Worker first saw it.
  Until its URL and public key are set in `outageStatusConfig.ts` the app
  keeps the local rule.
- **Confío Face is asked only of users who went through KYC** (an approved
  personal identity verification, `step_up_applies`). A recruited identity
  exists to pass KYC, which opens the fiat ramps and bank payouts, so the
  money enters through a KYC'd account and its first hop out needs the
  holder. Users who never verified keep sending as before. A KYC'd user
  whose stored selfie is missing is asked to verify again, never waved
  through.
- **Sends**: every personal BSC send from a KYC'd user, to a Confío user as
  much as to an external address, needs its own Confío Face approval. An
  unspent withdrawal approval expires after 15 minutes; a deposit or emergency
  exit approval cannot authorize a withdrawal. The server atomically consumes
  the approval immediately before execution, bound to the operation's source,
  destination, asset and amount via its validated calls. Exact retries retain
  that approval; a different operation or changed terms need a new one. Phone
  invites (money escrowed for a phone that is not on Confío
  yet) are sends too and take the same gate. Business senders and the
  server-only activation fee stay exempt.
- **Pay** (`payments/bsc_flow.py`, risk-based so checkout stays one tap):
  paying an unrelated KYB-verified merchant never asks. A KYC'd payer is asked for
  Confío Face only when paying a business they own or work for (soft-deleted
  employee records count) or one that never passed KYB — the two ways a ring
  would pool money through Pay. Business payers stay exempt.
- **Generic sponsorship and legacy relay**: policy-validated external outflows
  receive the same single-use gate. Self-conversions remain exempt. A generic
  request without durable idempotency binds to its exact signed intent (including
  nonce and deadline); it cannot authorize another transfer with a fresh nonce.
  Koywe off-ramp order creation only checks availability: funding is the outgoing
  operation that consumes the approval. Ambiguous broadcast outcomes do not
  release an approval for another operation.
- **Bank payouts and journeys**: a direct payout binds its immutable provider
  instruction; an outgoing Infinia/Cobre journey binds its destination snapshot
  and bridge quote. Approval consumption and instruction creation commit in one
  database transaction, so a rejected Face check cannot leave a runnable payout
  for a worker. Already-authorized journey legs complete under that instruction
  without consuming another approval. Exact retries validate stored terms first.
- **Limits of this control**: this is presence verification, not evidence of a
  legitimate source of funds or customer intent. A cooperating verified holder
  can still approve transactions. Third-party funding remains supported; this
  change does not impose payer-name matching or change non-KYC/business exemptions.
- **Identity recycling hold**: independently of the Face rollout flag, new
  outgoing activity is restricted when a verified personal document matches an
  actively banned account by issuing country, document type and normalized
  number. Additional and soft-deleted verified documents count. Names, IPs and
  device matches alone do not trigger this hold. Checks use live bans, including
  bans created after KYC; expired/lifted bans cease to trigger it.
  `SuspiciousActivity` cases with trigger `identity_reuse_active_ban` record each
  match. To release one after manual review, enter investigation notes and use
  the admin dismissal action, which records the reviewer. A generic duplicate
  identity dismissal does not release it; a new ban or changed ban terms needs
  another review. Business/merchant Face exemptions do not bypass this hold.
  Login, reads, support, incoming funding and the independent emergency exit
  remain available. Already-broadcast transactions cannot be undone by this gate.

### Face release update gate (5.1.5)

- Leave `FACE_STEP_UP_ENABLED=false` until **both** App Store and Google Play
  distribute the Face-capable release. Supported 5.1.5+ clients enforce Face
  even while this switch is off; the switch forces legacy clients to update.
  Headers select rollout policy, never prove successful identity verification.
  Before global enforcement, legacy/missing headers still follow legacy policy.
- App opening uses a separate `app_unlock` Face purpose that cannot authorize
  deposits or outgoing transactions. Each outgoing operation still consumes its
  own approval. Non-KYC users skip additional Face authentication only after a
  successful server eligibility response. Unknown/offline responses do not unlock
  the normal app; a recovery-only route remains available from the lock screen.
- Transaction and online account-action device prompts are replaced by Face.
  Emergency Exit retains local device protection only on the server-independent
  fallback, without a preceding device prompt on online Face routes. Its existing
  eligibility/wait requirements remain; opening recovery does not authorize exit.
  The fallback provisions and verifies its local guard on first use (not during
  login), repairs confirmed permanent invalidation, and rejects concurrent
  attempts. Resume unmounts Main before network checks; account switching waits
  for the automatic check to finish, while recovery remains accessible.
- Deploy the backend and `0016_face_app_unlock` migration before the app.
- Once enabled, transaction GraphQL fields, Guardarian order creation and
  money-moving WebSocket frames require `X-Confio-Platform`, `X-Confio-Version`,
  `X-Confio-Build`, and `X-Confio-Face-Capable: 1`. Missing/malformed metadata
  fails closed with `APP_UPDATE_REQUIRED` and a Spanish update message.
- Defaults: `FACE_MIN_APP_VERSION=5.1.5`, `FACE_MIN_ANDROID_BUILD=157`,
  `FACE_MIN_IOS_BUILD=1`. Build floors apply within the minimum marketing
  version; later iOS releases can reset their build to 1. Confirm these values
  match the uploaded binaries before enabling. No enforcement toggle is
  changed by this code or by publishing an app build.
- The GraphQL gate uses resolved schema field names, so aliases and misleading
  operation names do not bypass it. WebSockets recheck on each financial frame,
  including sockets opened before enablement. Reads, login, support, claim and
  recovery routes are not globally blocked.
- These headers are **untrusted compatibility hints**, never proof of liveness.
  Existing backend Rekognition result grading, KYC/merchant exemptions, and
  single-operation Face-grant claims remain the authorization controls.
- Guardarian deposit orders also check and consume a fresh on-ramp Face
  approval before contacting the provider. Ambiguous provider failures do not
  release it. Sell checkout creation does not consume a withdrawal approval;
  its signed funding transaction enforces that separately. The app retries
  only an explicit Face rejection, once, after a successful Face check.
- Old clients may still cancel expired P2P escrows or open disputes; these
  recovery/support actions are exempt from the financial-frame update gate.

## Rejected: raw key export (Exportar claves)

**Cancelled 2026-08-03 (Julian). Confío does not export keys — at any
tier, marketed or not. Do not re-propose it.**

Recorded here so the idea is not rediscovered as an obvious gap: it is a
considered rejection, not an oversight.

Key theft grants covert, permanent access to every *future* deposit, is
invisible to the victim, and cannot be undone once the secret has been
seen — a strictly larger attack surface than the thing it was meant to
insure against. An emergency transfer is its opposite on every axis:
visible, one-time, on-chain, and bounded by the balance that exists at
that moment. No delay gate, view-session hardening, or scam-warning copy
changes that asymmetry; those measures only reduce the rate at which the
larger vector is exploited. So the feature does not exist, and the design
has no user-reachable path to raw key material.

Two corollaries worth stating, because both have already caused confusion:

- **The 7-day gate belongs to no shipped feature.** It appears in old
  notes as an export delay. It was in fact the emergency-exit sweep
  window, and the shipped values are 24h cooloff + 72h validity
  (`NORMAL_COOLOFF_SECONDS` / `COOLOFF_VALID_SECONDS` in
  `apps/src/services/emergencyExit/reachability.ts`).
- **The Drive backup's app-constant encryption is not an escape hatch
  either — but it stays.** The wallet blob in `appDataFolder` is
  encrypted with a constant compiled into every APK, so whoever obtains
  that file obtains raw key material. Nobody should cite it as a
  post-mortem path: it is not one, and it is not consented.

  Re-keying it to a server-derived wrap key was **considered and
  rejected (2026-08-03)**. The reasoning, so it is not re-proposed: the
  real access control is the `appDataFolder` OAuth-client ACL and the
  iCloud keychain access group, not the cipher. The dominant threat —
  Google account takeover — routes *through the app*, which would
  authenticate to us and be handed the wrap key anyway, so the key
  defends only out-of-band ciphertext disclosure (insider, compelled
  process), and a party who can compel Google can compel Confío. Against
  that narrow gain it would cost a new lockout class (wrap-key store
  loss bricks every Drive-only user — cf. the 2026-07 Keystore-wipe
  incident) and, worse, would convert the server from an *operational*
  dependency into a *cryptographic* one, permanently foreclosing the
  recovery-only boot mode in the kit track. No user-input passphrase
  either: a forgotten password is an unrecoverable lockout, which for
  this user base is worse than the threat it addresses.

  The residual constraint is real and worth stating plainly: at restore
  time there is no local Keystore, no user input, and (in the scenario
  that matters) no server, so the only key material available is what
  ships in the binary. The constant is close to the only option, and the
  ACL is the control. What *is* worth fixing when that code is next
  touched: the construction, not the key —
  `crypto-js AES.encrypt(text, passphrase)` is EVP_BytesToKey/MD5,
  single-iteration, CBC, unauthenticated. AEAD (AES-GCM or
  XChaCha20-Poly1305) over HKDF of the same constant is a free upgrade
  with no trust-model change. Low priority: a corrupted blob already
  fails the derived-address check downstream, so integrity is caught,
  just at the wrong layer.
