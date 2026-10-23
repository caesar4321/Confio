// What's new in Comunidad, for the places that point people at it: the
// Invertir tab badge, the "Comunidad" segment pill and the preview card on
// the Invertir pane. Comunidad lives one segment away inside Invertir, so
// without these signals nobody would ever open it.
//
// "Seen" is per device: the newest PUBLISH time the user has looked at, kept
// in the keychain like the balance-visibility preference (never AsyncStorage).
// Publish time, not id: ids are allocated before moderation, so a post that
// is approved late has an older id but is still new to the reader.

import { gql } from '@apollo/client';
import * as Keychain from 'react-native-keychain';
import { useSyncExternalStore } from 'react';

const SEEN_SERVICE = 'com.confio.community.seen';
const SEEN_KEY = 'last_seen_published_at';
const PEEK_SIZE = 10;

// Its own query (not the shared feed document): an older server that
// rejects a field fails only this, never the feed.
export const GET_COMMUNITY_PEEK = gql`
  query CommunityPeek($limit: Int) {
    discoverFeed(offset: 0, limit: $limit, section: "community") {
      items { id title body time sourceName sourceAvatarUrl sourceAvatarEmoji publishedAt }
    }
  }
`;

export type PeekItem = {
  id: string;
  title: string;
  body: string;
  time: string;
  sourceName?: string | null;
  sourceAvatarUrl?: string | null;
  sourceAvatarEmoji?: string | null;
  publishedAt?: string | null;
};

type State = {
  items: PeekItem[];
  /** Epoch ms of the newest post seen; null = never opened on this device. */
  lastSeenAt: number | null;
  /** Highest post id seen: the fallback for a post without a publish time. */
  lastSeenId: number;
  loaded: boolean;
};

type Seen = { at: number; id: number };

let state: State = { items: [], lastSeenAt: null, lastSeenId: 0, loaded: false };

const publishedMs = (item: PeekItem): number => {
  const t = item.publishedAt ? Date.parse(item.publishedAt) : NaN;
  return Number.isFinite(t) ? t : 0;
};

/** Seen marks only ever move forward (a slow read must not undo a visit). */
const laterOf = (a: number | null, b: number | null): number | null =>
  a === null ? b : b === null ? a : Math.max(a, b);
const listeners = new Set<() => void>();
const emit = (next: Partial<State>) => {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
};

const readSeen = async (): Promise<Seen | null> => {
  try {
    const c = await Keychain.getInternetCredentials(SEEN_SERVICE);
    if (!c || c.username !== SEEN_KEY) return null;
    const parsed = JSON.parse(c.password);
    const at = Number(parsed?.at);
    const id = Number(parsed?.id);
    return Number.isFinite(at) ? { at, id: Number.isFinite(id) ? id : 0 } : null;
  } catch {
    return null;
  }
};

/** New since the last visit: by publish time, or — for a post the server
 *  sent without one — by id. */
const isUnread = (item: PeekItem): boolean => {
  const t = publishedMs(item);
  return t > 0 ? t > (state.lastSeenAt as number) : Number(item.id) > state.lastSeenId;
};

let inFlight: Promise<void> | null = null;

/** Re-read the newest Comunidad posts (cheap: one page of ids and snippets). */
export const refreshCommunityPeek = (): Promise<void> => {
  if (inFlight) return inFlight;
  inFlight = (async () => {
    try {
      const { apolloClient } = await import('../apollo/client');
      const [{ data }, stored] = await Promise.all([
        apolloClient.query({ query: GET_COMMUNITY_PEEK, variables: { limit: PEEK_SIZE }, fetchPolicy: 'network-only' }),
        readSeen(),
      ]);
      // Merge with what this session already marked: a visit that happened
      // while this refresh was in flight wins over the older stored value.
      emit({ items: data?.discoverFeed?.items || [],
             lastSeenAt: laterOf(state.lastSeenAt, stored ? stored.at : null),
             lastSeenId: Math.max(state.lastSeenId, stored ? stored.id : 0),
             loaded: true });
    } catch {
      // A failed peek just shows no badge; the feed itself is unaffected.
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
};

/** The user opened Comunidad: everything currently known is seen. */
export const markCommunitySeen = async (): Promise<void> => {
  const newest = state.items.reduce((max, i) => Math.max(max, publishedMs(i)), state.lastSeenAt || 0);
  const newestId = state.items.reduce((max, i) => Math.max(max, Number(i.id) || 0), state.lastSeenId);
  emit({ lastSeenAt: newest, lastSeenId: newestId });
  try {
    await Keychain.setInternetCredentials(SEEN_SERVICE, SEEN_KEY, JSON.stringify({ at: newest, id: newestId }));
  } catch {
    // Best effort: worst case the badge shows again next launch.
  }
};

export type CommunityPeek = State & {
  /** New posts since the last visit (capped at the peek page). */
  unread: number;
  /** Never opened on this device, and there is something to see. */
  neverOpened: boolean;
};

const snapshot = (): CommunityPeek => {
  const unread = state.lastSeenAt === null
    ? 0
    : state.items.filter(isUnread).length;
  return { ...state, unread, neverOpened: state.loaded && state.lastSeenAt === null && state.items.length > 0 };
};

let cached = snapshot();
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
listeners.add(() => { cached = snapshot(); });

export const useCommunityPeek = (): CommunityPeek =>
  useSyncExternalStore(subscribe, () => cached, () => cached);

/** Short label for a badge: '9+' / '3', or '' for a plain dot. */
export const peekBadge = (peek: CommunityPeek): string | null => {
  if (peek.unread > 0) return peek.unread >= PEEK_SIZE ? '9+' : String(peek.unread);
  if (peek.neverOpened) return '';
  return null;
};
