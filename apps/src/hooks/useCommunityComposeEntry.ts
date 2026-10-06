import { useQuery } from '@apollo/client';

import { GET_COMMUNITY_POSTING_STATUS } from '../apollo/queries';
import { isSchemaMismatch } from '../utils/graphqlSchemaMismatch';

/**
 * Whether to offer "post to Comunidad" here. Only a server that predates
 * Comunidad (it rejects the field) or the kill switch hides the entry points;
 * any other hiccup keeps them, since the composer re-checks and explains
 * (e.g. how to get verified). Shared by the Descubrir header pencil and the
 * feed's prompt card, which read the same cached query.
 */
export function useCommunityComposeEntry(enabled: boolean = true): boolean {
  return useCommunityEntryState(enabled).canCompose;
}

/**
 * `supported`: the server has Comunidad (so "Mis publicaciones" and the
 * blocked list stay reachable even while posting is paused); `canCompose`:
 * offer the composer too.
 */
export function useCommunityEntryState(enabled: boolean = true): { supported: boolean; canCompose: boolean } {
  const { data, error } = useQuery(GET_COMMUNITY_POSTING_STATUS, {
    skip: !enabled,
    fetchPolicy: 'cache-and-network',
  });
  const status = data?.communityPostingStatus;
  if (!enabled || isSchemaMismatch(error)) return { supported: false, canCompose: false };
  if (!status && !error) return { supported: false, canCompose: false }; // not answered yet
  return { supported: true, canCompose: status?.blockCode !== 'disabled' };
}
