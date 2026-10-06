import type { ContentPollData } from '../components/ContentPoll';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { NetworkStatus, useApolloClient, useMutation, useQuery } from '@apollo/client';

import { DISCOVER_SECTIONS, DiscoverFeed, DiscoverItem, DiscoverSectionKey } from '../components/DiscoverFeed';
import { OfferCardSkeleton } from '../components/SkeletonLoader';
import { REACT_TO_MESSAGE_CONTENT } from '../apollo/mutations';
import {
  GET_COMMUNITY_COMMENT_COUNTS,
  GET_DISCOVER_FEED,
  GET_DISCOVER_FEED_CARDS,
  GET_DISCOVER_FEED_SECTIONED,
} from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';
import { isSchemaMismatch } from '../utils/graphqlSchemaMismatch';
import { useCommunityEntryState } from '../hooks/useCommunityComposeEntry';
import { memberBlockVersion } from '../services/communityEvents';
import { CommunityComposePrompt } from '../components/CommunityComposePrompt';

const PAGE_SIZE = 10;

type Navigation = NativeStackNavigationProp<MainStackParamList>;

type DiscoverFeedDto = {
  id: string;
  type: 'product' | 'video' | 'news';
  tag: string;
  tagColor: string;
  title: string;
  body: string;
  time: string;
  thumbnail: boolean;
  platformLinks?: Array<{ platform: 'TikTok' | 'Instagram' | 'YouTube'; url: string }> | null;
  imageUrl?: string | null;
  reactionSummary?: Array<{ emoji: string; count: number }> | null;
  viewerReaction?: string | null;
  poll?: ContentPollData | null;
  canReact?: boolean | null;
  sourceName?: string | null;
  isOfficial?: boolean | null;
  sourceAvatarUrl?: string | null;
  sourceAvatarEmoji?: string | null;
};

// A server with the earlier publisher-type sections rejects our keys this way:
// an older server, not an outage.
const OLD_SECTIONS_SERVER = /Unknown Discover section/i;

// Newest first. A server that rejects a document's shape (it predates a field
// or a section key) steps the screen down one rung; the legacy feed has no
// sections, so no chips.
const FEED_TIERS = [
  { document: GET_DISCOVER_FEED_CARDS, sectioned: true },
  { document: GET_DISCOVER_FEED_SECTIONED, sectioned: true },
  { document: GET_DISCOVER_FEED, sectioned: false },
] as const;
const LAST_TIER = FEED_TIERS.length - 1;

export const DiscoverScreen = () => {
  const navigation = useNavigation<Navigation>();
  const client = useApolloClient();
  const [reactToMessageContent] = useMutation(REACT_TO_MESSAGE_CONTENT);
  const [isFetchingMore, setIsFetchingMore] = useState(false);
  // Para ti first: everything, with verified sources marked by the Oficial
  // check; the Oficial-only and community feeds are one tap away.
  const [section, setSection] = useState<DiscoverSectionKey>('for_you');

  const [tier, setTier] = useState(0);
  const feedTier = FEED_TIERS[tier];
  const legacyServer = !feedTier.sectioned;
  const feedDocument = feedTier.document;
  const feedVariables = feedTier.sectioned ? { section } : {};
  const { data, refetch, updateQuery, networkStatus, loading, error: feedError } = useQuery(feedDocument, {
    variables: { offset: 0, limit: PAGE_SIZE, ...feedVariables },
    fetchPolicy: 'network-only',
    notifyOnNetworkStatusChange: true,
  });
  // The "¿Qué quieres compartir?" card opens Para ti (where Descubrir lands)
  // and Comunidad; Oficial is Confío's and verified sources only. The header
  // pencil (DiscoverStackHeader) is the always-reachable entry.
  const composeSection = section === 'for_you' || section === 'community';
  const { canCompose, supported: communitySupported } = useCommunityEntryState(!legacyServer);
  const showPrompt = canCompose && composeSection;
  // Mis publicaciones travels with the composer card (Para ti and Comunidad).
  const showMyPosts = communitySupported && composeSection;

  // Stepping down is not a failure: the next rung is already on its way.
  const steppingDown = tier < LAST_TIER && isSchemaMismatch(feedError, OLD_SECTIONS_SERVER);
  useEffect(() => {
    if (steppingDown) setTier((current) => Math.min(current + 1, LAST_TIER));
  }, [steppingDown]);

  const items = useMemo<DiscoverItem[]>(() => {
    return (data?.discoverFeed?.items || []).map((item: DiscoverFeedDto) => ({
      id: Number(item.id),
      type: item.type,
      tag: item.tag,
      tagColor: item.tagColor,
      title: item.title,
      body: item.body,
      time: item.time,
      thumbnail: item.thumbnail,
      platformLinks: item.platformLinks || [],
      imageUrl: item.imageUrl || undefined,
      reactionSummary: item.reactionSummary || [],
      viewerReaction: item.viewerReaction,
      poll: item.poll,
      canReact: item.canReact ?? true,
      sourceName: item.sourceName || undefined,
      isOfficial: Boolean(item.isOfficial),
      sourceAvatarUrl: item.sourceAvatarUrl || null,
      sourceAvatarEmoji: item.sourceAvatarEmoji || null,
    }));
  }, [data]);

  // Comment counts for the cards, asked on their own so a server without
  // Comunidad comments fails only this (the cards just show none).
  const pageIds = useMemo(() => items.map((item) => String(item.id)), [items]);
  const countsSkipped = legacyServer || pageIds.length === 0 || section === 'official';
  const { data: countsData, refetch: refetchCounts } = useQuery(GET_COMMUNITY_COMMENT_COUNTS, {
    // The server counts up to 200 posts in one query.
    variables: { contentItemIds: pageIds.slice(0, 200) },
    skip: countsSkipped,
    fetchPolicy: 'cache-and-network',
  });
  // The same posts can gain or lose comments while you are away: re-count on
  // every return and every pull-to-refresh, not only when the page changes.
  const refreshCounts = useCallback(() => {
    if (!countsSkipped) refetchCounts().catch(() => {});
  }, [countsSkipped, refetchCounts]);
  useFocusEffect(refreshCounts);
  const commentCounts = useMemo(() => {
    const counts: Record<number, number> = {};
    for (const entry of countsData?.communityCommentCounts || []) {
      if (entry.count > 0) counts[Number(entry.contentItemId)] = entry.count;
    }
    return counts;
  }, [countsData]);

  // "Couldn't load" must never read as "nothing here". Apollo keeps the last
  // good data when a refresh fails, so key off the error, not missing data.
  const loadFailed = !loading && !steppingDown && Boolean(feedError) && items.length === 0;

  // Every list replacement (section switch, refresh) starts a new generation.
  // A next page merges only into the generation it was requested from, so a
  // late page from an earlier visit (Oficial → Comunidad → Oficial) is dropped.
  const feedGeneration = useRef(0);
  const selectSection = (next: DiscoverSectionKey) => {
    if (next === section) return;
    feedGeneration.current += 1;
    setSection(next);
  };

  // Descubrir is a tab again, so it stays mounted: re-read the first page on
  // every return (not the first focus — mount already fetched). Only while
  // the user is still on that page: the server caps a response at one page,
  // and Apollo replaces the list, so refreshing deeper would throw away what
  // they scrolled to. Pull-to-refresh covers that case.
  const loadedCount = useRef(0);
  loadedCount.current = items.length;
  // Nor while a next page is loading: a first-page refetch finishing after it
  // would replace the accumulated list.
  const paginating = useRef(false);
  const focusRefreshing = useRef(false);
  paginating.current = isFetchingMore;
  const focusedOnce = useRef(false);
  const seenBlockVersion = useRef(0);
  useFocusEffect(
    useCallback(() => {
      if (!focusedOnce.current) {
        focusedOnce.current = true;
        seenBlockVersion.current = memberBlockVersion();
        return;
      }
      // After blocking someone, re-read from the top even if scrolled deep:
      // their posts must disappear, and the new generation drops any page
      // still in flight for the old list.
      const currentBlockVersion = memberBlockVersion();
      const blockedSince = currentBlockVersion !== seenBlockVersion.current;
      if (!blockedSince && (loadedCount.current > PAGE_SIZE || paginating.current)) return;
      focusRefreshing.current = true;
      feedGeneration.current += 1;
      refetch({ offset: 0, limit: PAGE_SIZE })
        // Marked seen only once the re-read lands: offline, the next focus
        // tries again instead of leaving the blocked member's posts up.
        .then(() => { seenBlockVersion.current = currentBlockVersion; })
        .catch(() => {})
        .finally(() => { focusRefreshing.current = false; });
    }, [refetch]),
  );

  const hasMore = Boolean(data?.discoverFeed?.hasMore);
  const isRefreshing = networkStatus === NetworkStatus.refetch;

  const handleRefresh = async () => {
    feedGeneration.current += 1;
    refreshCounts();
    await refetch({ offset: 0, limit: PAGE_SIZE });
  };

  const handleLoadMore = async () => {
    // Never alongside a refresh or a first-page load (a section switch):
    // whichever lands last replaces the list, and an offset taken from a list
    // that is about to be replaced skips posts.
    if (isFetchingMore || isRefreshing || loading || focusRefreshing.current || !hasMore) {
      return;
    }
    const requestedGeneration = feedGeneration.current;
    setIsFetchingMore(true);
    try {
      // Fetched on its own, not via fetchMore: fetchMore re-reads the active
      // query when it settles even if its page is rejected, which would wipe
      // a newer section's error and show "nothing here" instead of the failure.
      const { data: nextPage } = await client.query({
        query: feedDocument,
        variables: { ...feedVariables, offset: items.length, limit: PAGE_SIZE },
        fetchPolicy: 'network-only',
      });
      if (!nextPage?.discoverFeed || feedGeneration.current !== requestedGeneration) {
        return;
      }
      updateQuery((previousResult: any) => ({
        discoverFeed: {
          __typename: nextPage.discoverFeed.__typename,
          hasMore: nextPage.discoverFeed.hasMore,
          items: [
            ...(previousResult?.discoverFeed?.items || []),
            ...nextPage.discoverFeed.items,
          ],
        },
      }));
    } catch {
      // A failed next page keeps the list; reaching the end again retries.
    } finally {
      setIsFetchingMore(false);
    }
  };

  const handleReact = async (itemId: number, emoji: string) => {
    // The refetch below replaces the list.
    feedGeneration.current += 1;
    await reactToMessageContent({
      variables: {
        contentItemId: String(itemId),
        emoji,
      },
      refetchQueries: [{
        query: feedDocument,
        variables: { ...feedVariables, offset: 0, limit: items.length || PAGE_SIZE },
      }],
    });
  };

  // With chips on screen, a section switch keeps them and spins in the list;
  // the full skeleton is only for the chipless legacy feed.
  const waitingForItems = (loading || steppingDown) && items.length === 0;
  if (waitingForItems && legacyServer) {
    return (
      <View style={{ flex: 1, paddingTop: 12 }}>
        {Array.from({ length: 3 }).map((_, i) => (
          <OfferCardSkeleton key={i} />
        ))}
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <DiscoverFeed
        items={items}
        refreshing={isRefreshing}
        loadingMore={isFetchingMore}
        hasMore={hasMore}
        onRefresh={() => {
          void handleRefresh();
        }}
        onEndReached={() => {
          void handleLoadMore();
        }}
        onReact={handleReact}
        loading={waitingForItems}
        loadFailed={loadFailed}
        onRetry={() => {
          feedGeneration.current += 1;
          refetch({ offset: 0, limit: PAGE_SIZE }).catch(() => {});
        }}
        sections={legacyServer ? [] : DISCOVER_SECTIONS}
        // The legacy feed is unfiltered: its empty state is Para ti's.
        activeSection={legacyServer ? 'for_you' : section}
        onSelectSection={selectSection}
        commentCounts={commentCounts}
        sectionAccessory={showPrompt || showMyPosts ? (
          <>
            {showPrompt ? (
              <CommunityComposePrompt onPress={() => navigation.navigate('CommunityCompose')} />
            ) : null}
            {showMyPosts ? (
              <Pressable
                style={styles.myPosts}
                onPress={() => navigation.navigate('MyCommunityPosts')}
                accessibilityRole="button"
              >
                <Icon name="user" size={14} color={colors.primaryDark} />
                <Text style={styles.myPostsText}>Mis publicaciones</Text>
                <Icon name="chevron-right" size={14} color={colors.primaryDark} />
              </Pressable>
            ) : null}
          </>
        ) : null}
        onOpenItem={(item: DiscoverItem) => {
          navigation.navigate('DiscoverPostDetail', { contentItemId: item.id });
        }}
      />
    </View>
  );
};

export default DiscoverScreen;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.neutral,
  },
  myPosts: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: 6,
    marginBottom: 12,
    paddingVertical: 4,
  },
  myPostsText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.primaryDark,
  },
});
