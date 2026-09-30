/**
 * Incoming Infinia money held until Confío Face (docs/plans/infinia-payin-face-hold.md).
 *
 * A personal account's local-currency pay-in is not converted into the wallet
 * until the account's person confirms with their face; unconfirmed after 24h,
 * it goes back to the payer. One face check releases the whole queue.
 *
 * Isolated operations: an older server without these fields must only make
 * this feature disappear, never break a shared screen query.
 */
import { gql } from '@apollo/client';
import { ensureFaceCheck, FaceCheckPurpose, isFaceStepUpRequired } from './faceStepUp';

export type PendingIncomingState = 'awaiting_face' | 'releasing' | 'returning' | 'review' | 'returned' | 'return_failed';

export interface PendingIncomingPayin {
  id: string;
  state: PendingIncomingState;
  amount: string;
  asset: string;
  country: string;
  payerName: string | null;
  receivedAt: string;
  returnsAt: string;
  returnAmount: string | null;
  returnDeduction: string | null;
  journeyId: string | null;
}

const FIELDS = `
  id
  state
  amount
  asset
  country
  payerName
  receivedAt
  returnsAt
  returnAmount
  returnDeduction
  journeyId
`;

export const PENDING_INCOMING_PAYINS = gql`
  query PendingIncomingPayins {
    pendingIncomingPayins { ${FIELDS} }
  }
`;

const RELEASE = gql`
  mutation ReleasePendingPayins {
    releasePendingPayins {
      success
      error
      nextStep
      released { ${FIELDS} }
    }
  }
`;

const PAYIN_RELEASE: FaceCheckPurpose = 'payin_release';

export const isAwaiting = (p: PendingIncomingPayin) => p.state === 'awaiting_face';
/** Confirmed or returning but not settled yet: a journey has not taken over
 * (the transfer screen shows it from then on) and the return is not final. */
export const isUnresolved = (p: PendingIncomingPayin) =>
  (p.state === 'releasing' && !p.journeyId) || p.state === 'review'
  || p.state === 'returning' || p.state === 'return_failed';

/**
 * `items: null` means "could not load" (network, server error): callers keep
 * what they last showed. An older server without the field yields `[]` —
 * the feature simply isn't there yet.
 */
export const fetchPendingIncoming = async (): Promise<{ items: PendingIncomingPayin[] | null }> => {
  try {
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.query({ query: PENDING_INCOMING_PAYINS, fetchPolicy: 'network-only' });
    return { items: data?.pendingIncomingPayins ?? [] };
  } catch (error: any) {
    const unsupported = /Cannot query field ["']?pendingIncomingPayins/.test(String(error?.message || ''));
    return { items: unsupported ? [] : null };
  }
};

export type ReleaseOutcome =
  | { kind: 'released'; released: PendingIncomingPayin[] }
  | { kind: 'declined' }
  | { kind: 'error'; message: string };

/** Confirm with Confío Face, then release every waiting pay-in. */
export const releasePendingIncoming = async (): Promise<ReleaseOutcome> => {
  const { apolloClient } = await import('../apollo/client');
  const attempt = async () => {
    const { data } = await apolloClient.mutate({ mutation: RELEASE });
    return data?.releasePendingPayins;
  };
  try {
    // Ask for the face first: the queue is always gated, so a round trip that
    // can only answer "face_check" would just delay the camera.
    if (!(await ensureFaceCheck(PAYIN_RELEASE))) return { kind: 'declined' };
    let result = await attempt();
    if (!result?.success && (isFaceStepUpRequired(result?.nextStep) || isFaceStepUpRequired(result?.error))) {
      // The window lapsed between the check and the call: once more.
      if (!(await ensureFaceCheck(PAYIN_RELEASE))) return { kind: 'declined' };
      result = await attempt();
    }
    if (!result?.success) {
      return { kind: 'error', message: result?.error || 'No pudimos recibir tu dinero. Intenta de nuevo.' };
    }
    return { kind: 'released', released: result.released ?? [] };
  } catch {
    return { kind: 'error', message: 'Revisa tu conexión e intenta de nuevo.' };
  }
};

/** "23 h 5 min" / "12 min" / "menos de 1 min" until the server's return time. */
export const timeLeft = (returnsAt: string, now: number = Date.now()): string => {
  const ms = Date.parse(returnsAt) - now;
  if (!Number.isFinite(ms) || ms <= 60_000) return 'menos de 1 min';
  const minutes = Math.floor(ms / 60_000);
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return hours > 0 ? `${hours} h${rest ? ` ${rest} min` : ''}` : `${minutes} min`;
};
