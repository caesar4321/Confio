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

export const applyReviewLink = async (
  client: ApolloClient<any>,
  link: ReviewLink,
  // AuthContext's refreshProfile: its profile is React state, not an Apollo query.
  refreshProfile?: () => Promise<unknown>,
) => {
  try {
    const { data } = await client.mutate({ mutation: APPLY_REVIEW_ACCESS, variables: link });
    const result = data?.applyReviewAccess;
    if (result?.success) {
      // Country-dependent screens read GET_ME and railCountries.
      await client.refetchQueries({ include: 'active' });
      if (refreshProfile) await refreshProfile();
      Alert.alert('Modo revisión', `Tu cuenta muestra ahora la experiencia de ${result.country}.`);
    } else {
      Alert.alert('Modo revisión', result?.error || 'No pudimos aplicar el enlace.');
    }
  } catch {
    Alert.alert('Modo revisión', 'No pudimos aplicar el enlace. Intenta nuevamente.');
  }
};
