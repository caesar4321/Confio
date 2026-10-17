import { useCallback, useEffect, useRef, useState } from 'react';
import { useApolloClient } from '@apollo/client';
import { useFocusEffect } from '@react-navigation/native';

import { GET_COMMUNITY_POST_EXTRAS } from '../apollo/queries';
import type { ActivityShare } from '../components/ActivitySummary';
import { isSchemaMismatch } from '../utils/graphqlSchemaMismatch';

/** What a feed card adds on top of the post: who wrote it and, for activity posts, the verified movement. */
export type CommunityPostExtras = {
  contentItemId: string;
  /** Set for member posts whose author has a profile (a chosen username). */
  authorId?: string | null;
  /** The member's own text on an activity post (the body also holds the headline). */
  note?: string | null;
  activity?: ActivityShare | null;
};

// The server reads at most 50 posts per call.
const CHUNK = 50;

/**
 * Extras for the given posts, fetched on their own query: a server without
 * them rejects only this, and the cards keep rendering from the feed (body,
 * plain byline). Each post is asked once per round; a failed chunk is retried
 * when the list next changes, except on an older server, which is never asked
 * again. A new round (every post asked again) starts when the screen regains
 * focus or `refreshKey` changes: a purchase's live P&L and position move.
 */
export function useCommunityPostExtras(
  ids: Array<string | number>,
  enabled = true,
  refreshKey = 0,
): Record<number, CommunityPostExtras> {
  const client = useApolloClient();
  const [extras, setExtras] = useState<Record<number, CommunityPostExtras>>({});
  const requested = useRef(new Set<string>());
  const unsupported = useRef(false);
  const mounted = useRef(true);
  const [round, setRound] = useState(0);
  const newRound = useCallback(() => {
    requested.current.clear();
    setRound((value) => value + 1);
  }, []);
  const focusedOnce = useRef(false);
  useFocusEffect(
    useCallback(() => {
      if (focusedOnce.current) newRound();
      focusedOnce.current = true;
    }, [newRound]),
  );
  const lastRefreshKey = useRef(refreshKey);
  useEffect(() => {
    if (lastRefreshKey.current === refreshKey) return;
    lastRefreshKey.current = refreshKey;
    newRound();
  }, [refreshKey, newRound]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const key = ids.map(String).join(',');
  useEffect(() => {
    if (!enabled || unsupported.current || !key) return;
    const missing = key.split(',').filter((id) => id && !requested.current.has(id));
    if (!missing.length) return;
    missing.forEach((id) => requested.current.add(id));
    for (let start = 0; start < missing.length; start += CHUNK) {
      const chunk = missing.slice(start, start + CHUNK);
      Promise.resolve()
        .then(() =>
          client.query({
            query: GET_COMMUNITY_POST_EXTRAS,
            variables: { contentItemIds: chunk },
            fetchPolicy: 'network-only',
          }),
        )
        .then((result) => {
          const rows: CommunityPostExtras[] = result?.data?.communityPostExtras || [];
          if (!mounted.current || !rows.length) return;
          setExtras((previous) => {
            const next = { ...previous };
            for (const row of rows) next[Number(row.contentItemId)] = row;
            return next;
          });
        })
        .catch((error) => {
          if (isSchemaMismatch(error)) {
            unsupported.current = true;
            return;
          }
          chunk.forEach((id) => requested.current.delete(id));
        });
    }
  }, [client, enabled, key, round]);

  return extras;
}
