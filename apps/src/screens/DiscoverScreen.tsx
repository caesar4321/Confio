import type { ContentPollData } from '../components/ContentPoll';
import React, { useCallback, useMemo, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { colors } from '../config/theme';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { NetworkStatus, useMutation, useQuery } from '@apollo/client';

import { DISCOVER_SECTIONS, DiscoverFeed, DiscoverItem, DiscoverSectionKey } from '../components/DiscoverFeed';
import { OfferCardSkeleton } from '../components/SkeletonLoader';
import { REACT_TO_MESSAGE_CONTENT } from '../apollo/mutations';
import { GET_DISCOVER_FEED, GET_DISCOVER_FEED_SECTIONED } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';
import { isSchemaMismatch } from '../utils/graphqlSchemaMismatch';

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
};

// A server with the earlier publisher-type sections rejects our keys this way:
// an older server, not an outage.
const OLD_SECTIONS_SERVER = /Unknown Discover section/i;

export const DiscoverScreen = () => {
  const navigation = useNavigation<Navigation>();
  const [reactToMessageContent] = useMutation(REACT_TO_MESSAGE_CONTENT);
  const [isFetchingMore, setIsFetchingMore] = useState(false);
  // Oficial first: Descubrir keeps its "news you can trust" footing, and the
  // mixed and community feeds are one tap away.
  const [section, setSection] = useState<DiscoverSectionKey>('official');

  const sectioned = useQuery(GET_DISCOVER_FEED_SECTIONED, {
    variables: { offset: 0, limit: PAGE_SIZE, section },
    fetchPolicy: 'network-only',
    notifyOnNetworkStatusChange: true,
  });
  const legacyServer = isSchemaMismatch(sectioned.error, OLD_SECTIONS_SERVER);
  const legacy = useQuery(GET_DISCOVER_FEED, {
    variables: { offset: 0, limit: PAGE_SIZE },
    fetchPolicy: 'network-only',
    notifyOnNetworkStatusChange: true,
    skip: !legacyServer,
  });
  const feedDocument = legacyServer ? GET_DISCOVER_FEED : GET_DISCOVER_FEED_SECTIONED;
  const feedVariables = legacyServer ? {} : { section };
  const { data, refetch, fetchMore, networkStatus } = legacyServer ? legacy : sectioned;
  const loading = legacyServer ? legacy.loading : sectioned.loading;
  const feedError = legacyServer ? legacy.error : sectioned.error;

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
    }));
  }, [data]);

  // "Couldn't load" must never read as "nothing here". Apollo keeps the last
  // good data when a refresh fails, so key off the error, not missing data.
  const loadFailed = !loading && Boolean(feedError) && items.length === 0;

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
  useFocusEffect(
    useCallback(() => {
      if (!focusedOnce.current) {
        focusedOnce.current = true;
        return;
      }
      if (loadedCount.current > PAGE_SIZE || paginating.current) return;
      focusRefreshing.current = true;
      feedGeneration.current += 1;
      refetch({ offset: 0, limit: PAGE_SIZE })
        .catch(() => {})
        .finally(() => { focusRefreshing.current = false; });
    }, [refetch]),
  );

  const hasMore = Boolean(data?.discoverFeed?.hasMore);
  const isRefreshing = networkStatus === NetworkStatus.refetch;

  const handleRefresh = async () => {
    feedGeneration.current += 1;
    await refetch({ offset: 0, limit: PAGE_SIZE });
  };

  const handleLoadMore = async () => {
    // Never alongside a refresh: whichever lands last replaces the list.
    if (isFetchingMore || isRefreshing || focusRefreshing.current || !hasMore) {
      return;
    }
    const requestedGeneration = feedGeneration.current;
    setIsFetchingMore(true);
    try {
      await fetchMore({
        variables: {
          offset: items.length,
          limit: PAGE_SIZE,
        },
        updateQuery: (previousResult, { fetchMoreResult }) => {
          if (!fetchMoreResult?.discoverFeed || feedGeneration.current !== requestedGeneration) {
            return previousResult;
          }

          return {
            discoverFeed: {
              __typename: fetchMoreResult.discoverFeed.__typename,
              hasMore: fetchMoreResult.discoverFeed.hasMore,
              items: [
                ...(previousResult?.discoverFeed?.items || []),
                ...fetchMoreResult.discoverFeed.items,
              ],
            },
          };
        },
      });
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
  const waitingForItems = loading && items.length === 0;
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
});
