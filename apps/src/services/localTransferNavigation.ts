/** Bank money waiting for Confío Face (payment_accounts/payin_hold.py). */
export const PENDING_INCOMING_URL = 'confio://pending-incoming';

type LocalRoute =
  | {screen: 'LocalTransferStatus'; params: {journeyId: string}}
  | {screen: 'PendingIncoming'; params: undefined};

/** Only an explicit local-transfer identity may open this receipt. */
export function localTransferRoute(value: unknown): LocalRoute | null {
  if (typeof value !== 'string') return null;
  if (value === PENDING_INCOMING_URL) return {screen: 'PendingIncoming', params: undefined};
  const id = value.replace(/^confio:\/\/local-transfer\//, '');
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) return null;
  return {screen: 'LocalTransferStatus', params: {journeyId: id}};
}
