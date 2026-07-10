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
      amountUsd
      userBscAddress
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

/**
 * Finish any conversion whose bridge USDT has arrived (DEST_ARRIVED) by
 * minting cUSD+. Safe to call on every foreground; self-guards against
 * concurrent runs. Requires the vault address (from server config).
 */
export const resumeSavingsMints = async (vaultAddress: string): Promise<void> => {
  if (running || !vaultAddress) return;
  running = true;
  try {
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.query({
      query: IN_FLIGHT,
      fetchPolicy: 'network-only',
    });
    const rows = (data?.cusdPlusConversionsInFlight || []).filter(
      (r: any) => r.status === 'DEST_ARRIVED',
    );
    for (const row of rows) {
      try {
        const { mintTx } = await subscribeUsdtToSavings({
          vaultAddress,
          usdtWei: usdToWei(row.amountUsd),
          // Direct mint against Ondo's IM — no order book, so 0 floor is safe.
          minUsdyOut: 0n,
        });
        await apolloClient.mutate({
          mutation: ADVANCE,
          variables: { conversionId: row.conversionId, newStatus: 'COMPLETED', txRef: mintTx },
        });
      } catch (e) {
        // One row failing (e.g. gas not yet dusted) must not block the rest;
        // the next foreground retries. Never throws to the caller.
        console.warn('[savingsLegC] mint resume failed for', row.conversionId, e);
      }
    }
  } catch (e) {
    console.warn('[savingsLegC] resume query failed', e);
  } finally {
    running = false;
  }
};
