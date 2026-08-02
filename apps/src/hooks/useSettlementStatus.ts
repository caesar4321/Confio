// Watch a transaction's SERVER-side settlement status until it's terminal.
//
// Why this exists: the client can hold a receipt long before the chain has
// committed to it. On BSC a block is final only once the validator set has
// voted (BEP-126 fast finality, ~1s), and the Celery confirm task is what
// checks that and flips the row to CONFIRMED. So "Confirmado" is the
// server's word, not ours — the screen starts at "Confirmando…" and upgrades
// when the row says so. (Algorand never needed this: its first block is
// final, so submitted and confirmed were effectively the same instant.)
//
// Polling, not a subscription, on purpose: the send/pay WS sessions close
// after submit, and this needs to survive the screen being re-entered from
// history. Both queries below are long-standing fields, so this cannot break
// against an older server the way a new field would.

import { useEffect, useState } from 'react';

const TERMINAL = ['CONFIRMED', 'FAILED', 'REVERTED'];

/** ~2s cadence for ~90s: settlement normally lands in a few seconds, and a
 *  row still unsettled after 90s is a support case, not a spinner case. */
const POLL_MS = 2000;
const MAX_MS = 90_000;

export type SettlementKind = 'send' | 'payment';

const QUERIES: Record<SettlementKind, { query: string; pick: (d: any) => string | undefined }> = {
  send: {
    query: `query SendSettlementStatus($id: ID!) {
      sendTransaction(id: $id) { id status }
    }`,
    pick: (d) => d?.sendTransaction?.status,
  },
  payment: {
    query: `query PaymentSettlementStatus($id: ID!) {
      paymentTransaction(id: $id) { id status }
    }`,
    pick: (d) => d?.paymentTransaction?.status,
  },
};

/**
 * Returns the latest known status, starting from `initialStatus` and
 * upgrading as the server settles. Stops on a terminal status, on unmount,
 * or after MAX_MS. Never throws: a failed poll just leaves the last known
 * status in place, so a flaky network shows "Confirmando…" rather than an
 * error on a transaction that is fine.
 */
export const useSettlementStatus = (
  kind: SettlementKind,
  id: string | undefined,
  initialStatus: string | undefined,
): string | undefined => {
  const [status, setStatus] = useState(initialStatus);

  useEffect(() => {
    setStatus(initialStatus);
  }, [initialStatus, id]);

  useEffect(() => {
    if (!id) return;
    if (status && TERMINAL.includes(status)) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const giveUpAt = Date.now() + MAX_MS;

    const tick = async () => {
      if (cancelled) return;
      try {
        const { gql } = await import('@apollo/client');
        const { apolloClient } = await import('../apollo/client');
        const spec = QUERIES[kind];
        const { data } = await apolloClient.query({
          query: gql`${spec.query}`,
          variables: { id },
          fetchPolicy: 'network-only', // settlement state must never be cached
        });
        const next = spec.pick(data);
        if (cancelled) return;
        if (next) {
          setStatus(next);
          if (TERMINAL.includes(next)) return; // settled — stop polling
        }
      } catch {
        // Keep the last known status and try again; a poll failure is not a
        // transaction failure.
      }
      if (!cancelled && Date.now() < giveUpAt) {
        timer = setTimeout(tick, POLL_MS);
      }
    };

    timer = setTimeout(tick, POLL_MS);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // `status` is intentionally excluded: including it would tear down and
    // rebuild the loop on every poll that returns the same value.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, id]);

  return status;
};
