// Read server settlement state with bounded polling. Receipts can also retrieve
// the authoritative creation time when a success/notification payload omitted it.
import { useEffect, useState } from 'react';
import { transactionTimestamp } from '../utils/transactionRoutes';

const TERMINAL = ['CONFIRMED', 'COMPLETED', 'PAID', 'FAILED', 'REVERTED', 'CANCELLED'];
const terminal = (status?: string) => !!status && TERMINAL.includes(status.toUpperCase());
const POLL_MS = 2000;
const MAX_MS = 90_000;
export type SettlementKind = 'send' | 'payment';
const QUERIES = {
  send: {query: `query SendSettlementStatus($id: ID!) { sendTransaction(id: $id) { id status createdAt } }`, field: 'sendTransaction'},
  payment: {query: `query PaymentSettlementStatus($id: ID!) { paymentTransaction(id: $id) { id status createdAt } }`, field: 'paymentTransaction'},
};

function useSettlement(
  kind: SettlementKind,
  id: string | undefined,
  initialStatus: string | undefined,
  initialCreatedAt: string | undefined,
  fetchMissingDate: boolean,
) {
  const key = `${kind}:${id || ''}`;
  const [snapshot, setSnapshot] = useState({key, status: initialStatus, createdAt: initialCreatedAt});
  useEffect(() => {
    setSnapshot({key, status: initialStatus, createdAt: initialCreatedAt});
    if (!id || (terminal(initialStatus) && !(fetchMissingDate && !initialCreatedAt))) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const giveUpAt = Date.now() + MAX_MS;
    const tick = async () => {
      if (cancelled) return;
      try {
        const { gql } = await import('@apollo/client');
        const { apolloClient } = await import('../apollo/client');
        const spec = QUERIES[kind];
        const { data } = await apolloClient.query({query: gql`${spec.query}`, variables: {id}, fetchPolicy: 'network-only'});
        if (cancelled) return;
        const transaction = data?.[spec.field];
        if (transaction) {
          const createdAt = transactionTimestamp(transaction.createdAt);
          setSnapshot(previous => ({key, status: transaction.status || previous.status, createdAt: createdAt || previous.createdAt}));
          if (terminal(transaction.status)) return;
        }
      } catch {
        // Keep the last known state; unavailable metadata is never invented.
      }
      if (!cancelled && Date.now() < giveUpAt) timer = setTimeout(tick, POLL_MS);
    };
    if (fetchMissingDate && !initialCreatedAt) void tick();
    else timer = setTimeout(tick, POLL_MS);
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [key, kind, id, initialStatus, initialCreatedAt, fetchMissingDate]);
  return snapshot.key === key ? snapshot : {key, status: initialStatus, createdAt: initialCreatedAt};
}

export const useSettlementStatus = (kind: SettlementKind, id: string | undefined, initialStatus: string | undefined) =>
  useSettlement(kind, id, initialStatus, undefined, false).status;

export const useSettlementDetails = (kind: SettlementKind, id: string | undefined, initialStatus: string | undefined, createdAt: string | undefined) =>
  useSettlement(kind, id, initialStatus, createdAt, true);
