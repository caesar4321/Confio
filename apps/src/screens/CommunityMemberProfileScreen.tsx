import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Pressable, RefreshControl, StyleSheet, View } from 'react-native';
import { useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { memberBlockVersion, notifyMemberBlocked } from '../services/communityEvents';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import { useApolloClient, useMutation, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../components/common/AppText';
import { EmptyState } from '../components/EmptyState';
import { BylineAvatar } from '../components/PostByline';
import { DiscoverItem, DiscoverPostCard } from '../components/DiscoverFeed';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import {
  BLOCK_COMMUNITY_MEMBER,
  FOLLOW_COMMUNITY_MEMBER,
  REACT_TO_MESSAGE_CONTENT,
  SET_COMMUNITY_FOLLOW_NOTIFY,
  UNFOLLOW_COMMUNITY_MEMBER,
} from '../apollo/mutations';
import {
  GET_COMMUNITY_COMMENT_COUNTS,
  GET_COMMUNITY_MEMBER_POSTS,
  GET_COMMUNITY_MEMBER_PROFILE,
} from '../apollo/queries';
import { useCommunityPostExtras } from '../hooks/useCommunityPostExtras';
import { DiscoverFeedDto, toDiscoverItem } from '../utils/discoverItem';
import { MainStackParamList } from '../types/navigation';

type Navigation = NativeStackNavigationProp<MainStackParamList>;
type RouteProps = NativeStackScreenProps<MainStackParamList, 'CommunityMemberProfile'>['route'];

export type CommunityMemberProfile = {
  id: string;
  username: string;
  avatarUrl?: string | null;
  followerCount: number;
  followingCount: number;
  isSelf: boolean;
  isFollowing: boolean;
  notify: boolean;
};

type FollowResult = { success: boolean; error?: string | null; profile?: CommunityMemberProfile | null };

// The server's cap for one page.
const PAGE_SIZE = 20;

/** "1 seguidor · 12 siguiendo". */
export const followCountsLabel = (followers: number, following: number) =>
  `${followers} ${followers === 1 ? 'seguidor' : 'seguidores'} · ${following} siguiendo`;

/** A Comunidad member: who they are, follow (and get notified), and what they posted. */
export const CommunityMemberProfileScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProps>();
  const userId = String(route.params.userId);
  const client = useApolloClient();

  const {
    data: profileData,
    loading: profileLoading,
    error: profileError,
    refetch: refetchProfile,
  } = useQuery(GET_COMMUNITY_MEMBER_PROFILE, {
    variables: { userId },
    fetchPolicy: 'network-only',
  });
  // A follow change answers with the fresh profile: show it until the next read.
  const [updated, setUpdated] = useState<CommunityMemberProfile | null>(null);
  const rawFetched = profileData?.communityMemberProfile as CommunityMemberProfile | null | undefined;
  const fetched = rawFetched && rawFetched.id !== userId ? undefined : rawFetched;
  // Keyed by member: the screen can be reused for another member (a
  // notification while this one is open), and a late answer about the
  // previous member must never show under the new one.
  const profile = (updated && updated.id === userId ? updated : null) ?? fetched ?? null;
  const notFound = Boolean(profileData) && fetched === null;

  const [follow] = useMutation(FOLLOW_COMMUNITY_MEMBER);
  const [unfollow] = useMutation(UNFOLLOW_COMMUNITY_MEMBER);
  const [setNotify] = useMutation(SET_COMMUNITY_FOLLOW_NOTIFY);
  const [blockMember, { loading: blocking }] = useMutation(BLOCK_COMMUNITY_MEMBER);
  const [reactToMessageContent] = useMutation(REACT_TO_MESSAGE_CONTENT);
  const [followBusy, setFollowBusy] = useState(false);
  const [notifyBusy, setNotifyBusy] = useState(false);

  // Posts, paged by offset. Every refresh starts a new generation so a late
  // page from the previous list is dropped instead of appended.
  const [items, setItems] = useState<DiscoverItem[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [postsLoading, setPostsLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [extrasRefresh, setExtrasRefresh] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [postsFailed, setPostsFailed] = useState(false);
  const generation = useRef(0);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);
  const currentUserId = useRef(userId);
  useEffect(() => {
    if (currentUserId.current === userId) return;
    currentUserId.current = userId;
    setUpdated(null);
    setItems([]);
    setHasMore(false);
    setPostsLoading(true);
  }, [userId]);

  const fetchPage = useCallback(
    (offset: number) =>
      client.query({
        query: GET_COMMUNITY_MEMBER_POSTS,
        variables: { userId, offset, limit: PAGE_SIZE },
        fetchPolicy: 'network-only',
      }),
    [client, userId],
  );

  const serverOffset = useRef(0);
  const loadFirstPage = useCallback(async () => {
    generation.current += 1;
    const requested = generation.current;
    inFlight.current = true;
    try {
      const { data } = await fetchPage(0);
      if (!mounted.current || generation.current !== requested) return;
      const page = data?.communityMemberPosts;
      serverOffset.current = (page?.items || []).length;
      setItems((page?.items || []).map((item: DiscoverFeedDto) => toDiscoverItem(item)));
      setHasMore(Boolean(page?.hasMore));
      setPostsFailed(false);
    } catch {
      if (mounted.current && generation.current === requested) setPostsFailed(true);
    } finally {
      if (generation.current === requested) inFlight.current = false;
      if (mounted.current) setPostsLoading(false);
    }
  }, [fetchPage]);

  useEffect(() => {
    void loadFirstPage();
  }, [loadFirstPage]);

  const loadMore = async () => {
    if (inFlight.current || !hasMore) return;
    const requested = generation.current;
    inFlight.current = true;
    setLoadingMore(true);
    try {
      // The server's offset counts every row it returned, duplicates
      // included: the de-duplicated list length would re-ask the same page.
      const { data } = await fetchPage(serverOffset.current);
      if (!mounted.current || generation.current !== requested) return;
      const page = data?.communityMemberPosts;
      serverOffset.current += (page?.items || []).length;
      const next: DiscoverItem[] = (page?.items || []).map((item: DiscoverFeedDto) => toDiscoverItem(item));
      setItems((previous) => {
        // A post published meanwhile shifts the offsets: never show one twice.
        const seen = new Set(previous.map((item) => item.id));
        return [...previous, ...next.filter((item) => !seen.has(item.id))];
      });
      setHasMore(Boolean(page?.hasMore));
    } catch {
      // A failed next page keeps the list; reaching the end again retries.
    } finally {
      if (generation.current === requested) inFlight.current = false;
      if (mounted.current) setLoadingMore(false);
    }
  };

  // Back from a post where this member was blocked (or anything else that
  // changed them): re-read, so a blocked member's content does not linger.
  const seenBlockVersion = useRef(memberBlockVersion());
  useFocusEffect(
    useCallback(() => {
      if (seenBlockVersion.current === memberBlockVersion()) return;
      seenBlockVersion.current = memberBlockVersion();
      setUpdated(null);
      setExtrasRefresh((value) => value + 1);
      refetchProfile().catch(() => {});
      void loadFirstPage();
    }, [refetchProfile, loadFirstPage]),
  );

  const handleRefresh = async () => {
    setRefreshing(true);
    setUpdated(null);
    setExtrasRefresh((value) => value + 1);
    await Promise.all([refetchProfile().catch(() => {}), loadFirstPage()]);
    if (mounted.current) setRefreshing(false);
  };

  const ids = useMemo(() => items.map((item) => String(item.id)), [items]);
  const postExtras = useCommunityPostExtras(ids, true, extrasRefresh);
  const { data: countsData } = useQuery(GET_COMMUNITY_COMMENT_COUNTS, {
    variables: { contentItemIds: ids.slice(0, 200) },
    skip: ids.length === 0,
    fetchPolicy: 'cache-and-network',
  });
  const commentCounts = useMemo(() => {
    const counts: Record<number, number> = {};
    for (const entry of countsData?.communityCommentCounts || []) {
      if (entry.count > 0) counts[Number(entry.contentItemId)] = entry.count;
    }
    return counts;
  }, [countsData]);

  const applyFollowResult = (result: FollowResult | undefined, fallback: string) => {
    if (result?.success && result.profile) {
      if (result.profile.id === currentUserId.current) setUpdated(result.profile);
      return;
    }
    Alert.alert('No pudimos completar la acción', result?.error || fallback);
  };

  // Here too, not only on a post: a follower who never posted reaches you
  // only through notifications and this profile.
  const confirmBlock = () => {
    if (!profile || profile.isSelf) return;
    const name = profile.username;
    const blockedId = userId;
    Alert.alert(
      `¿Bloquear a ${name}?`,
      'No verás sus publicaciones ni comentarios, y no podrá ver los tuyos ni mencionarte. Puedes desbloquear cuando quieras desde Mis publicaciones.',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Bloquear',
          style: 'destructive',
          onPress: async () => {
            try {
              const { data: result } = await blockMember({ variables: { userId: blockedId } });
              if (!result?.blockCommunityMember?.success) {
                Alert.alert('No pudimos bloquear', result?.blockCommunityMember?.error || 'Inténtalo de nuevo.');
                return;
              }
              notifyMemberBlocked();
              Alert.alert('Bloqueado', `Ya no verás contenido de ${name}.`);
              if (mounted.current && navigation.canGoBack()) navigation.goBack();
            } catch {
              Alert.alert('No pudimos bloquear', 'Revisa tu conexión e inténtalo de nuevo.');
            }
          },
        },
      ],
    );
  };

  const toggleFollow = async () => {
    if (!profile || followBusy) return;
    setFollowBusy(true);
    try {
      if (profile.isFollowing) {
        const { data } = await unfollow({ variables: { userId } });
        applyFollowResult(data?.unfollowCommunityMember, 'Inténtalo de nuevo en un momento.');
      } else {
        const { data } = await follow({ variables: { userId } });
        applyFollowResult(data?.followCommunityMember, 'Inténtalo de nuevo en un momento.');
      }
    } catch {
      Alert.alert('No pudimos completar la acción', 'Revisa tu conexión e inténtalo de nuevo.');
    } finally {
      if (mounted.current) setFollowBusy(false);
    }
  };

  const toggleNotify = async () => {
    if (!profile || notifyBusy) return;
    setNotifyBusy(true);
    try {
      const { data } = await setNotify({ variables: { userId, notify: !profile.notify } });
      applyFollowResult(data?.setCommunityFollowNotify, 'Inténtalo de nuevo en un momento.');
    } catch {
      Alert.alert('No pudimos completar la acción', 'Revisa tu conexión e inténtalo de nuevo.');
    } finally {
      if (mounted.current) setNotifyBusy(false);
    }
  };

  const handleReact = async (itemId: number, emoji: string) => {
    try {
      const { data } = await reactToMessageContent({
        variables: { contentItemId: String(itemId), emoji },
      });
      const result = data?.reactToMessageContent;
      if (!result?.success || !mounted.current) return;
      setItems((previous) =>
        previous.map((item) =>
          item.id === itemId
            ? {
                ...item,
                viewerReaction: result.viewerReaction ?? null,
                reactionSummary: result.reactionSummary || [],
              }
            : item,
        ),
      );
    } catch {
      // The bar keeps its state; tapping again retries.
    }
  };

  const header = (
    <Header
      title="Perfil"
      navigation={navigation as any}
      onBackPress={() => navigation.goBack()}
      backgroundColor={colors.background}
      isLight={false}
    />
  );

  if (profileLoading && !profile) {
    return (
      <View style={styles.container}>
        {header}
        <ActivityIndicator style={styles.loading} size="small" color={colors.primary} />
      </View>
    );
  }

  if (!profile) {
    return (
      <View style={styles.container}>
        {header}
        {notFound ? (
          <EmptyState
            icon="user-x"
            title="No encontramos a este miembro"
            subtitle="Puede que ya no esté en la comunidad o que todavía no haya publicado nada."
            actionLabel="Volver"
            onAction={() => navigation.goBack()}
          />
        ) : (
          <EmptyState
            icon="wifi-off"
            title="No pudimos cargar el perfil"
            subtitle={profileError ? 'Revisa tu conexión e inténtalo de nuevo.' : undefined}
            actionLabel="Reintentar"
            onAction={() => {
              refetchProfile().catch(() => {});
              void loadFirstPage();
            }}
          />
        )}
      </View>
    );
  }

  const profileHeader = (
    <View style={styles.profileCard}>
      <BylineAvatar name={profile.username} avatarUrl={profile.avatarUrl} size={72} />
      <Text style={styles.username} numberOfLines={1}>
        {profile.username}
      </Text>
      <Text style={styles.counts}>{followCountsLabel(profile.followerCount, profile.followingCount)}</Text>
      {profile.isSelf ? null : (
        <View style={styles.actions}>
          <Pressable
            onPress={() => {
              void toggleFollow();
            }}
            disabled={followBusy}
            style={({ pressed }) => [
              styles.followButton,
              profile.isFollowing ? styles.followingButton : styles.followPrimary,
              (pressed || followBusy) && styles.pressed,
            ]}
            accessibilityRole="button"
            accessibilityState={{ selected: profile.isFollowing, busy: followBusy }}
            accessibilityLabel={profile.isFollowing ? 'Siguiendo. Toca para dejar de seguir.' : 'Seguir'}
          >
            {followBusy ? (
              <ActivityIndicator size="small" color={profile.isFollowing ? colors.dark : colors.white} />
            ) : (
              <>
                {profile.isFollowing ? <Icon name="check" size={16} color={colors.dark} /> : null}
                <Text style={[styles.followText, profile.isFollowing && styles.followingText]}>
                  {profile.isFollowing ? 'Siguiendo' : 'Seguir'}
                </Text>
              </>
            )}
          </Pressable>
          {profile.isFollowing ? (
            <Pressable
              onPress={() => {
                void toggleNotify();
              }}
              disabled={notifyBusy}
              style={({ pressed }) => [styles.bellButton, (pressed || notifyBusy) && styles.pressed]}
              hitSlop={6}
              accessibilityRole="button"
              accessibilityState={{ busy: notifyBusy }}
              accessibilityLabel={profile.notify ? 'Silenciar sus publicaciones' : 'Avisarme de sus publicaciones'}
            >
              <Icon
                name={profile.notify ? 'bell' : 'bell-off'}
                size={18}
                color={profile.notify ? colors.primaryDeep : colors.textSecondary}
              />
            </Pressable>
          ) : null}
        </View>
      )}
      {profile.isSelf ? null : (
        <Pressable
          onPress={confirmBlock}
          disabled={blocking}
          hitSlop={8}
          style={({ pressed }) => [styles.blockLink, (pressed || blocking) && styles.pressed]}
          accessibilityRole="button"
          accessibilityLabel={`Bloquear a ${profile.username}`}
        >
          <Text style={styles.blockText}>Bloquear</Text>
        </Pressable>
      )}
      <Text style={styles.sectionTitle}>Publicaciones</Text>
    </View>
  );

  return (
    <View style={styles.container}>
      {header}
      <FlatList
        data={items}
        keyExtractor={(item) => String(item.id)}
        renderItem={({ item }) => (
          <DiscoverPostCard
            item={item}
            onOpenItem={(post) => navigation.navigate('DiscoverPostDetail', { contentItemId: post.id })}
            onReact={handleReact}
            commentCount={commentCounts[item.id]}
            extras={postExtras[item.id]}
          />
        )}
        ListHeaderComponent={profileHeader}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              void handleRefresh();
            }}
            tintColor={colors.primary}
          />
        }
        initialNumToRender={10}
        maxToRenderPerBatch={10}
        windowSize={11}
        onEndReachedThreshold={0.35}
        onEndReached={() => {
          if (hasMore && !loadingMore) void loadMore();
        }}
        ListEmptyComponent={
          postsLoading ? (
            <ActivityIndicator style={styles.loading} size="small" color={colors.primary} />
          ) : postsFailed ? (
            <EmptyState
              icon="wifi-off"
              title="No pudimos cargar sus publicaciones"
              subtitle="Revisa tu conexión e inténtalo de nuevo."
              actionLabel="Reintentar"
              onAction={() => {
                setPostsLoading(true);
                void loadFirstPage();
              }}
            />
          ) : (
            <EmptyState icon="file-text" title="Aún no hay publicaciones" />
          )
        }
        ListFooterComponent={
          loadingMore ? <ActivityIndicator style={styles.footerLoader} size="small" color={colors.primary} /> : null
        }
      />
    </View>
  );
};

export default CommunityMemberProfileScreen;

const styles = StyleSheet.create({
  blockLink: { marginTop: 12, paddingVertical: 4, paddingHorizontal: 8 },
  blockText: { fontSize: 13, color: colors.textSecondary, textDecorationLine: 'underline' },
  container: {
    flex: 1,
    backgroundColor: colors.neutral,
  },
  loading: {
    marginTop: 32,
  },
  list: {
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 28,
    flexGrow: 1,
  },
  profileCard: {
    alignItems: 'center',
    paddingTop: 8,
    paddingBottom: 4,
  },
  username: {
    marginTop: 12,
    fontSize: 20,
    fontWeight: '700',
    color: colors.dark,
    maxWidth: '100%',
  },
  counts: {
    marginTop: 4,
    fontSize: 14,
    color: colors.textSecondary,
  },
  actions: {
    marginTop: 16,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  followButton: {
    minWidth: 132,
    height: 40,
    paddingHorizontal: 20,
    borderRadius: 20,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  followPrimary: {
    backgroundColor: colors.dark,
  },
  followingButton: {
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.borderMedium,
  },
  followText: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.white,
  },
  followingText: {
    color: colors.dark,
  },
  bellButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.borderMedium,
  },
  pressed: {
    opacity: 0.7,
  },
  sectionTitle: {
    alignSelf: 'flex-start',
    marginTop: 24,
    marginBottom: 12,
    fontSize: 15,
    fontWeight: '700',
    color: colors.dark,
  },
  footerLoader: {
    paddingVertical: 8,
  },
});
