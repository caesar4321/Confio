import React, { useMemo, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { NetworkStatus, useMutation, useQuery } from '@apollo/client';

import { DiscoverFeed, DiscoverItem } from '../components/DiscoverFeed';
import { REACT_TO_MESSAGE_CONTENT } from '../apollo/mutations';
import { GET_DISCOVER_FEED } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';

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
  canReact?: boolean | null;
};

export const DiscoverScreen = () => {
  const navigation = useNavigation<Navigation>();
  const [reactToMessageContent] = useMutation(REACT_TO_MESSAGE_CONTENT);
  const [isFetchingMore, setIsFetchingMore] = useState(false);

  const { data, loading, refetch, fetchMore, networkStatus } = useQuery(GET_DISCOVER_FEED, {
    variables: { offset: 0, limit: PAGE_SIZE },
    fetchPolicy: 'network-only',
    notifyOnNetworkStatusChange: true,
  });

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
      canReact: item.canReact ?? true,
    }));
  }, [data]);

  const hasMore = Boolean(data?.discoverFeed?.hasMore);
  const isRefreshing = networkStatus === NetworkStatus.refetch;

  const handleRefresh = async () => {
    await refetch({ offset: 0, limit: PAGE_SIZE });
  };

  const handleLoadMore = async () => {
    if (isFetchingMore || !hasMore) {
      return;
    }
    setIsFetchingMore(true);
    try {
      await fetchMore({
        variables: {
          offset: items.length,
          limit: PAGE_SIZE,
        },
        updateQuery: (previousResult, { fetchMoreResult }) => {
          if (!fetchMoreResult?.discoverFeed) {
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
    await reactToMessageContent({
      variables: {
        contentItemId: String(itemId),
        emoji,
      },
      refetchQueries: [{ query: GET_DISCOVER_FEED, variables: { offset: 0, limit: items.length || PAGE_SIZE } }],
    });
  };

  if (loading && items.length === 0) {
    return (
      <View style={styles.stateWrap}>
        <ActivityIndicator size="small" color="#34d399" />
        <Text style={styles.stateText}>Cargando Descubrir...</Text>
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
    backgroundColor: '#F4F6F8',
  },
  stateWrap: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
    paddingVertical: 48,
    backgroundColor: '#F4F6F8',
  },
  stateText: {
    marginTop: 8,
    fontSize: 13,
    lineHeight: 19,
    color: '#6B7280',
    textAlign: 'center',
  },
});
