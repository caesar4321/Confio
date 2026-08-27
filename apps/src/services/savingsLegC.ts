// Savings leg C — the final mint, resumable on foreground.
//
// A conversion (Ahorrar) reaches DEST_ARRIVED once its USDT lands at the
// user's own bsc_address on BNB (the server's chain scanner verifies this
// independently — a lying client can't fake it). Leg C is then a pure vault
// call the user signs: subscribeAndMint the arrived USDT → cUSD+ → COMPLETED.
//
// Same "retry every foreground" spirit as the USDC→cUSD auto-swap: if the
// app closed mid-flow, the next foreground finishes the mint. Idempotent —
// once a row is COMPLETED it drops out of the in-flight set, and the vault
// call is a no-op if the USDT was already consumed.

import { gql } from '@apollo/client';
import { subscribeUsdtToSavings } from './cusdPlusVault';

const IN_FLIGHT = gql`
  query CusdPlusConversionsInFlight {
    cusdPlusConversionsInFlight {
      conversionId
      status
      quotedReceiveUsd
      userBscAddress
    }
  }
`;

// Courtesy-skip source: the server enforces the mint geo-gate (phone + IP)
// on both relay rails regardless — this just avoids pointless signed
// attempts (and their error noise) for users the gate will refuse.
const ELIGIBILITY = gql`
  query SavingsMintEligibility {
    cusdPlusSummary {
      savingsEnabled
      sweepableUsdtWei
    }
  }
`;

const ADVANCE = gql`
  mutation AdvanceCusdPlusConversion($conversionId: ID!, $newStatus: String!, $txRef: String) {
    advanceCusdPlusConversion(conversionId: $conversionId, newStatus: $newStatus, txRef: $txRef) {
      success
      errors
    }
  }
`;

// BSC USDT is 18 decimals.
const usdToWei = (usd: number): bigint =>
  BigInt(Math.round(usd * 1e6)) * 10n ** 12n;

let running = false;
// Set when a caller arrives mid-run (a deposit landing during a pass). The
// finally block below drains it exactly once, so N arrivals during one run
// cost one extra pass, not N.
let rerunRequested = false;

// "Is a mint in flight" is MODULE state, not per-screen state. Several
// surfaces mount the resume (Home and the savings account), and `running`
// means only the first caller does the work — so a per-caller callback would
// light the spinner on whichever screen happened to win the race, which may
// not be the one the user is looking at. Every subscriber sees the same flag.
type MintingListener = (minting: boolean) => void;
const mintingListeners = new Set<MintingListener>();
let mintingNow = false;

const setMinting = (value: boolean): void => {
  mintingNow = value;
  mintingListeners.forEach(fn => fn(value));
};

/** Subscribe to mint-in-flight changes; fires immediately with current state. */
export const subscribeSavingsMinting = (fn: MintingListener): (() => void) => {
  mintingListeners.add(fn);
  fn(mintingNow);
  return () => { mintingListeners.delete(fn); };
};

/**
 * Finish any conversion whose bridge USDT has arrived (DEST_ARRIVED) by
 * minting cUSD+. Safe to call on every foreground; self-guards against
 * concurrent runs. Requires the vault address (from server config).
 */
export const resumeSavingsMints = async (vaultAddress: string): Promise<void> => {
  if (!vaultAddress) return;
  // Coalesce, don't drop. A deposit landing WHILE a run is in flight used to
  // be discarded by this guard: the running pass had already read a zero
  // balance and, with no DEST_ARRIVED rows, never re-read it, so the arrival
  // waited for the next foreground or remount. Remember that someone asked
  // and re-run once at the end instead.
  if (running) {
    rerunRequested = true;
    return;
  }
  running = true;
  let announced = false;
  try {
    const { apolloClient } = await import('../apollo/client');
    // Geo-ineligible users keep their arrived USDT raw ("Confío Dollar") —
    // don't mint. Cache-first: the summary is polled by the portfolio hook;
    // an unknown answer falls through to attempting (server still gates).
    let usdtOnHandWei = 0n;
    try {
      const { data: elig } = await apolloClient.query({
        query: ELIGIBILITY,
        // network-only: the balance decides how much to sweep, so a cached
        // figure would mint the wrong amount.
        fetchPolicy: 'network-only',
      });
      if (elig?.cusdPlusSummary?.savingsEnabled === false) return;
      usdtOnHandWei = BigInt(elig?.cusdPlusSummary?.sweepableUsdtWei ?? '0');
    } catch {}
    const { data } = await apolloClient.query({
      query: IN_FLIGHT,
      fetchPolicy: 'network-only',
    });
    const rows = (data?.cusdPlusConversionsInFlight || []).filter(
      (r: any) => r.status === 'DEST_ARRIVED',
    );
    // Announce only once there is real work: the resume runs on every
    // foreground, and flashing a modal on the empty case would be noise.
    if (rows.length) {
      announced = true;
      setMinting(true);
    }
    for (const row of rows) {
      try {
        const { mintTx } = await subscribeUsdtToSavings({
          vaultAddress,
          // Once DEST_ARRIVED, the server replaces this quoted value with
          // the exact six-decimal amount observed in the USDT Transfer log.
          usdtWei: usdToWei(row.quotedReceiveUsd),
          // Direct mint against Ondo's IM — no order book, so 0 floor is safe.
          minUsdyOut: 0n,
        });
        await apolloClient.mutate({
          mutation: ADVANCE,
          variables: { conversionId: row.conversionId, newStatus: 'COMPLETED', txRef: mintTx },
        });
      } catch (e) {
        // One row failing (e.g. sponsor rail briefly down) must not block the rest;
        // the next foreground retries. Never throws to the caller.
        console.warn('[savingsLegC] mint resume failed for', row.conversionId, e);
      }
    }

    // Plain deposits no longer arrive as DEST_ARRIVED rows: the server stopped
    // opening a conversion it could not know was allowed (the mint gate needs
    // a request's IP, which a Celery scanner never has). What's left is the
    // honest signal — raw USDT sitting at the user's own address. Sweep it.
    //
    // AFTER the bridge rows above, and re-read: their USDT is part of this
    // same balance, so sweeping first would mint it twice.
    if (rows.length) {
      try {
        const { data: fresh } = await apolloClient.query({
          query: ELIGIBILITY, fetchPolicy: 'network-only',
        });
        usdtOnHandWei = BigInt(fresh?.cusdPlusSummary?.sweepableUsdtWei ?? '0');
      } catch { usdtOnHandWei = 0n; }
    }
    // sweepableUsdtWei, never a Float or the displayed balance. The exact
    // string avoids rounding $1.000001 down to $1 at the JS boundary. The
    // server reads the
    // chain fresh and subtracts what is already committed — prepared sends,
    // in-flight off-ramps, in-flight sagas — none of which escrow on chain,
    // so this subtraction is the only thing keeping an auto-mint from moving
    // funds out from under them. It reports 0 on any failure, which mints
    // nothing (audit 2026-08-01).
    // Ondo's InstantManager rejects sub-$1 amounts on this side too, so a
    // smaller balance is left alone rather than burned on a reverting mint.
    if (usdtOnHandWei > 0n) {
      if (!announced) { announced = true; setMinting(true); }
      try {
        await subscribeUsdtToSavings({
          vaultAddress,
          usdtWei: usdtOnHandWei,
          minUsdyOut: 0n,
        });
        // No mutation: the RELAY writes the history row, after the gate it
        // actually enforced. The client never asserts a conversion happened.
      } catch (e) {
        // Includes mint_not_available for a blocked IP — the server refuses
        // and the USDT simply stays raw. Next foreground retries.
        console.warn('[savingsLegC] usdt sweep failed', e);
      }
    }
  } catch (e) {
    console.warn('[savingsLegC] resume query failed', e);
  } finally {
    running = false;
    // Always clear, including on the query-failure path above — a modal that
    // outlives its work is worse than no modal.
    if (announced) setMinting(false);
    // Drain a coalesced request. Cleared BEFORE the re-run so the re-run can
    // set it again for anything that arrives during IT; not awaited, so this
    // never recurses on the stack.
    if (rerunRequested) {
      rerunRequested = false;
      void resumeSavingsMints(vaultAddress);
    }
  }
};
