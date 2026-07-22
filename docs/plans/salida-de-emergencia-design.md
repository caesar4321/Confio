# Salida de emergencia — server-independent full exit (design)

**Status**: approved 2026-07-22 (Julian + Claude + Codex/ChatGPT debate, three rounds)
**Owner track**: self-custody survivability ("what if Confío disappears?" — Peru)
**Siblings**: Exportar claves (Advanced, unmarketed — separate spec), Emergency Recovery Kit (post-app-deletion — separate track)

## What this is

A mass-market escape hatch in each account's **Seguridad** tab: move the
account's entire balance to an external wallet, without exposing keys, and
— in the failure modes that matter — **without any Confío server**. This is
the feature that makes "Confío no puede aprobar, rechazar ni bloquear esta
operación" literally true at the code level.

Raw key export (Exportar claves) remains a separate, deliberately
unmarketed Advanced feature. Key theft grants covert, permanent access to
future deposits — qualitatively worse than a visible on-chain transfer —
so the mass-market answer to survivability is *transfer*, not *keys*.

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
timestamps**, not the device clock (same anti-manipulation clock source as
Exportar claves).

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
   — financiera, staff, family). Abort on any yes. Stop if screen capture
   is *detected* (iOS `isCaptured`, Android FLAG_SECURE) — detection-based,
   not claimed-total prevention.
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
