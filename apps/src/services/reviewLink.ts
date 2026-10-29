import * as Keychain from 'react-native-keychain';
import { Alert } from 'react-native';
import { gql, ApolloClient } from '@apollo/client';

/**
 * The store-review deep link: confio://review?country=AR&k=<token>
 * (users/review_access.py). It moves the reviewer's own account to that
 * country for 14 days. A link opened while signed out is kept in the
 * keychain and applied right after sign-in.
 */
const SERVICE = 'com.confio.pending_review_link';

export const APPLY_REVIEW_ACCESS = gql`
  mutation ApplyReviewAccess($country: String!, $token: String!) {
    applyReviewAccess(country: $country, token: $token) {
      success
      error
      country
    }
  }
`;

export type ReviewLink = { country: string; token: string };

export const parseReviewLink = (url: URL): ReviewLink | null => {
  const isReview = (url.protocol === 'confio:' && url.host === 'review')
    || url.pathname.split('/').filter(Boolean)[0] === 'review';
  if (!isReview) return null;
  const country = (url.searchParams.get('country') || '').trim().toUpperCase();
  const token = (url.searchParams.get('k') || '').trim();
  return country && token ? { country, token } : null;
};

let applier: ((link: ReviewLink) => Promise<void>) | null = null;

/** AuthContext registers this while signed in; null while signed out. */
export const setReviewLinkApplier = (fn: typeof applier) => {
  applier = fn;
};

export const receiveReviewLink = async (link: ReviewLink) => {
  if (applier) {
    await applier(link);
    return;
  }
  await Keychain.setGenericPassword('review', JSON.stringify(link), { service: SERVICE });
};

export const takePendingReviewLink = async (): Promise<ReviewLink | null> => {
  try {
    const stored = await Keychain.getGenericPassword({ service: SERVICE });
    if (!stored) return null;
    await Keychain.resetGenericPassword({ service: SERVICE });
    const link = JSON.parse(stored.password);
    return link?.country && link?.token ? link : null;
  } catch {
    return null;
  }
};

const SWITCH_DEADLINE_MS = 20_000;
const COUNTRY_NAMES: Record<string, string> = { AR: 'Argentina', US: 'Estados Unidos', GB: 'Reino Unido' };

export const applyReviewLink = async (
  client: ApolloClient<any>,
  link: ReviewLink,
  // AuthContext's refreshProfile: its profile is React state, not an Apollo query.
  refreshProfile?: () => Promise<unknown>,
  // Shows (label) and hides (null) AuthContext's switching overlay.
  setBusy?: (label: string | null) => void,
) => {
  const name = COUNTRY_NAMES[link.country] || link.country;
  setBusy?.(`Cambiando a ${name}…`);
  let message: string;
  try {
    // A request that never answers must not leave the overlay up: after the
    // deadline, say so; opening the link again is safe (it renews the grant).
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error('timeout')), SWITCH_DEADLINE_MS);
    });
    const { data } = await Promise.race([
      client.mutate({ mutation: APPLY_REVIEW_ACCESS, variables: link }),
      deadline,
    ]).finally(() => clearTimeout(timer));
    const result = data?.applyReviewAccess;
    if (result?.success) {
      // The account switch's two halves (hooks/useAtomicAccountSwitch.ts):
      // empty the cache so no screen, open or not, shows the old country's
      // answers, then refetch the open ones. Refetching alone left every
      // screen not on display rendering the old country until it reloaded.
      try {
        await client.clearStore();
      } catch {
        // Refetching below still corrects what is on screen.
      }
      // clearStore() cancels in-flight queries on a later tick: refetching at
      // once could join one of them and put the old country back.
      await new Promise(resolve => setTimeout(resolve, 300));
      // ...and one of them may have answered before it was cancelled: clear
      // what it wrote, now that nothing old is left in flight.
      try {
        await client.clearStore();
      } catch {
        // As above.
      }
      // Every refetch settles before the overlay goes: one failure must not
      // announce the switch while the rest are still loading.
      await Promise.allSettled(client.refetchQueries({ include: 'active' }).results);
      if (refreshProfile) await refreshProfile().catch(() => {});
      message = `Tu cuenta muestra ahora la experiencia de ${COUNTRY_NAMES[result.country] || result.country}.`;
    } else {
      message = result?.error || 'No pudimos aplicar el enlace.';
    }
  } catch (error: any) {
    message = error?.message === 'timeout'
      ? 'No pudimos confirmar el cambio. Abre el enlace otra vez.'
      : 'No pudimos aplicar el enlace. Intenta nuevamente.';
  } finally {
    setBusy?.(null);
  }
  Alert.alert('Modo revisión', message);
};
