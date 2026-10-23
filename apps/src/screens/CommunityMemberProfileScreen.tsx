import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Pressable, RefreshControl, StyleSheet, View } from 'react-native';
import { useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { memberBlockVersion, notifyMemberBlocked } from '../services/communityEvents';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import { useApolloClient, useMutation, useQuery } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { EmptyState } from '../components/EmptyState';
import { DiscoverItem, DiscoverPostCard } from '../components/DiscoverFeed';
import { CommunityMemberPortfolio, CommunityPortfolioSection } from '../components/CommunityPortfolioSection';
import { InvestorProfile, InvestorProfileHeader } from '../components/InvestorProfileHeader';
import { InvestorReturnsCard } from '../components/InvestorReturnsCard';
import { InvestorLockCard, isLocked } from '../components/InvestorLockCard';
import { InvestorBioEditor } from '../components/InvestorBioEditor';
import { isSchemaMismatch } from '../utils/graphqlSchemaMismatch';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import {
  BLOCK_COMMUNITY_MEMBER,
  FOLLOW_COMMUNITY_MEMBER,
  REACT_TO_MESSAGE_CONTENT,
  SET_COMMUNITY_FOLLOW_NOTIFY,
  SET_COMMUNITY_PORTFOLIO_HIDDEN,
  SET_COMMUNITY_PORTFOLIO_HIDDEN_WITH_ERROR,
  UNFOLLOW_COMMUNITY_MEMBER,
} from '../apollo/mutations';
import {
  GET_COMMUNITY_COMMENT_COUNTS,
  GET_COMMUNITY_MEMBER_PORTFOLIO,
  GET_COMMUNITY_MEMBER_CRYPTO_USD,
  GET_COMMUNITY_MEMBER_POSTS,
  GET_COMMUNITY_MEMBER_PROFILE,
  GET_INVESTOR_PROFILE,
  GET_LEAGUE_BADGES,
  GET_MY_TEAM,
} from '../apollo/queries';
import { championLabel } from '../utils/teams';
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

/**
 * Perfil inversor: who the member is (cover, photo, bio, people in common),
 * follow them, how their investments did (Rentabilidad) and what they hold,
 * and what they posted. Portfolios are reciprocal: a viewer whose own
 * profile is hidden or unverified sees a lock instead (server-enforced).
 */
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
  // The asset profile is its own query: an older server rejects the unknown
  // field, and any failure just leaves the section out.
  const [portfolio, setPortfolio] = useState<CommunityMemberPortfolio | null>(null);
  const currentUserId = useRef(userId);
  useEffect(() => {
    if (currentUserId.current === userId) return;
    currentUserId.current = userId;
    setUpdated(null);
    setItems([]);
    setHasMore(false);
    setPostsLoading(true);
    setPortfolio(null);
    setInvestor(null);
  }, [userId]);

  const [setPortfolioHidden] = useMutation(SET_COMMUNITY_PORTFOLIO_HIDDEN);
  const [setPortfolioHiddenWithError] = useMutation(SET_COMMUNITY_PORTFOLIO_HIDDEN_WITH_ERROR);
  const [hiddenBusy, setHiddenBusy] = useState(false);

  // Campeón del mes badges (Liga): their own query, an older server has none.
  const [badges, setBadges] = useState<string[]>([]);
  useEffect(() => {
    let live = true;
    setBadges([]);
    client.query({ query: GET_LEAGUE_BADGES, variables: { userId }, fetchPolicy: 'network-only' })
      .then(({ data }) => { if (live) setBadges(data?.leagueBadges ?? []); })
      .catch(() => {});
    return () => { live = false; };
  }, [client, userId]);

  // The investor header (bio, cover, access): its own query too.
  const [investor, setInvestor] = useState<InvestorProfile | null>(null);
  const [bioOpen, setBioOpen] = useState(false);
  const [returnsRefresh, setReturnsRefresh] = useState(0);
  const [publishBusy, setPublishBusy] = useState(false);
  const investorGeneration = useRef(0);
  const loadInvestor = useCallback(async () => {
    investorGeneration.current += 1;
    const requested = investorGeneration.current;
    const forUser = userId;
    try {
      const { data } = await client.query({
        query: GET_INVESTOR_PROFILE,
        variables: { userId: forUser },
        fetchPolicy: 'network-only',
        // Never share an in-flight read: one started before publishing
        // would hand back the old "locked" access.
        context: { queryDeduplication: false },
      });
      if (!mounted.current || investorGeneration.current !== requested || currentUserId.current !== forUser) return;
      const next = data?.investorProfile as InvestorProfile | null | undefined;
      setInvestor(next && String(next.userId) === forUser ? next : null);
    } catch {
      if (mounted.current && investorGeneration.current === requested && currentUserId.current === forUser) {
        setInvestor(null);
      }
    }
  }, [client, userId]);

  useEffect(() => {
    void loadInvestor();
  }, [loadInvestor]);

  /** The hide switch, with the server's reason when it refuses (an older server: no reason). */
  const writeHidden = async (hidden: boolean): Promise<{ success: boolean; hidden: boolean; error?: string | null } | null> => {
    try {
      const { data } = await setPortfolioHiddenWithError({ variables: { hidden } });
      return data?.setCommunityPortfolioHidden ?? null;
    } catch (e: any) {
      if (!isSchemaMismatch(e)) throw e;
      const { data } = await setPortfolioHidden({ variables: { hidden } });
      return data?.setCommunityPortfolioHidden ?? null;
    }
  };
  const portfolioGeneration = useRef(0);
  const loadPortfolio = useCallback(async () => {
    portfolioGeneration.current += 1;
    const requested = portfolioGeneration.current;
    const forUser = userId;
    try {
      const { data } = await client.query({
        query: GET_COMMUNITY_MEMBER_PORTFOLIO,
        variables: { userId: forUser },
        fetchPolicy: 'network-only',
        // Never share an in-flight read: one started before a hide-switch
        // change would hand its stale "hidden" value to this load.
        context: { queryDeduplication: false },
      });
      if (!mounted.current || portfolioGeneration.current !== requested || currentUserId.current !== forUser) return;
      const next = data?.communityMemberPortfolio as CommunityMemberPortfolio | null | undefined;
      setPortfolio(next && String(next.userId) === forUser ? next : null);
      if (next && String(next.userId) === forUser) {
        // Bitcoin & gold: a separate read, merged in when (and if) it lands.
        client.query({
          query: GET_COMMUNITY_MEMBER_CRYPTO_USD,
          variables: { userId: forUser },
          fetchPolicy: 'network-only',
        }).then(({ data: cryptoData }) => {
          if (!mounted.current || portfolioGeneration.current !== requested || currentUserId.current !== forUser) return;
          const cryptoUsd = cryptoData?.communityMemberCryptoUsd ?? null;
          setPortfolio((current) => (current && String(current.userId) === forUser ? { ...current, cryptoUsd } : current));
        }).catch(() => {});
      }
    } catch {
      if (mounted.current && portfolioGeneration.current === requested && currentUserId.current === forUser) {
        setPortfolio(null);
      }
    }
  }, [client, userId]);

  useEffect(() => {
    void loadPortfolio();
  }, [loadPortfolio]);

  const toggleHidden = async (nextHidden: boolean, teamConfirmed = false) => {
    if (!portfolio || !portfolio.isSelf || hiddenBusy) return;
    // Teams are made of public portfolios: hiding yours takes you out of yours.
    if (nextHidden && !teamConfirmed) {
      // undefined = unknown (failed lookup): warn anyway; an older server has no teams.
      const team = await client.query({ query: GET_MY_TEAM, fetchPolicy: 'network-only' })
        .then(({ data }) => (data?.myTeam ?? null) as { name: string } | null)
        .catch((e) => (isSchemaMismatch(e) ? null : undefined));
      if (team !== null) {
        Alert.alert('Saldrás de tu equipo', team
          ? `Si ocultas tu portafolio, saldrás de ${team.name} y dejarás de ver la Liga.`
          : 'Si ocultas tu portafolio y estás en un equipo, saldrás de él y dejarás de ver la Liga.', [
          { text: 'Cancelar', style: 'cancel' },
          { text: 'Ocultar y salir', style: 'destructive', onPress: () => { void toggleHidden(true, true); } },
        ]);
        return;
      }
    }
    const forUser = userId;
    const previous = portfolio.hidden;
    // A refresh landing meanwhile must not undo the optimistic value.
    portfolioGeneration.current += 1;
    setPortfolio((current) => (current && String(current.userId) === forUser ? { ...current, hidden: nextHidden } : current));
    setHiddenBusy(true);
    const rollback = () => {
      if (!mounted.current || currentUserId.current !== forUser) return;
      setPortfolio((current) => (current && String(current.userId) === forUser ? { ...current, hidden: previous } : current));
    };
    try {
      const result = await writeHidden(nextHidden);
      if (!result?.success) {
        rollback();
        Alert.alert('No pudimos guardar el cambio', result?.error || 'Inténtalo de nuevo en un momento.');
        return;
      }
      // A refresh started before the server confirmed may have read the old
      // value: drop it, the confirmed answer wins.
      portfolioGeneration.current += 1;
      if (mounted.current && currentUserId.current === forUser) {
        setPortfolio((current) =>
          current && String(current.userId) === forUser ? { ...current, hidden: Boolean(result.hidden) } : current,
        );
        void loadInvestor();
      }
    } catch {
      rollback();
      Alert.alert('No pudimos guardar el cambio', 'Revisa tu conexión e inténtalo de nuevo.');
    } finally {
      if (mounted.current) setHiddenBusy(false);
    }
  };

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
      void loadPortfolio();
      void loadInvestor();
      setReturnsRefresh((value) => value + 1);
    }, [refetchProfile, loadFirstPage, loadPortfolio, loadInvestor]),
  );

  // Back from verifying (or publishing elsewhere) while locked out: ask again,
  // the viewer's own state is what the lock depends on.
  const viewerLocked = useRef(false);
  viewerLocked.current = investor?.access === 'viewer_hidden' || investor?.access === 'viewer_unverified';
  const firstFocus = useRef(true);
  useFocusEffect(
    useCallback(() => {
      if (firstFocus.current) {
        firstFocus.current = false;
        return;
      }
      if (!viewerLocked.current) return;
      setReturnsRefresh((value) => value + 1);
      void loadInvestor();
      void loadPortfolio();
    }, [loadInvestor, loadPortfolio]),
  );

  const handleRefresh = async () => {
    setRefreshing(true);
    setUpdated(null);
    setExtrasRefresh((value) => value + 1);
    setReturnsRefresh((value) => value + 1);
    await Promise.all([refetchProfile().catch(() => {}), loadFirstPage(), loadPortfolio(), loadInvestor()]);
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

  // The viewer's own profile is hidden: publish it right from the lock.
  const publishOwn = async () => {
    if (publishBusy) return;
    const forUser = userId;
    setPublishBusy(true);
    try {
      const result = await writeHidden(false);
      if (!result?.success) {
        Alert.alert('No pudimos hacer público tu perfil', result?.error || 'Inténtalo de nuevo en un momento.');
        return;
      }
      // Moved on to another member meanwhile: their loads are not ours to restart.
      if (!mounted.current || currentUserId.current !== forUser) return;
      setReturnsRefresh((value) => value + 1);
      await Promise.all([loadInvestor(), loadPortfolio()]);
    } catch {
      Alert.alert('No pudimos hacer público tu perfil', 'Revisa tu conexión e inténtalo de nuevo.');
    } finally {
      if (mounted.current) setPublishBusy(false);
    }
  };

  const openMore = () => {
    if (!profile || profile.isSelf) return;
    Alert.alert(profile.username, undefined, [
      { text: `Bloquear a ${profile.username}`, style: 'destructive', onPress: confirmBlock },
      { text: 'Cancelar', style: 'cancel' },
    ]);
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
              void loadPortfolio();
            }}
          />
        )}
      </View>
    );
  }

  const visiblePortfolio = portfolio && String(portfolio.userId) === userId ? portfolio : null;

  const access = investor?.access ?? null;
  const locked = isLocked(access);

  const profileHeader = (
    <View>
      <InvestorProfileHeader
        member={profile}
        investor={investor}
        followBusy={followBusy || blocking}
        notifyBusy={notifyBusy}
        onToggleFollow={() => { void toggleFollow(); }}
        onToggleNotify={() => { void toggleNotify(); }}
        onMore={openMore}
        onEditBio={() => setBioOpen(true)}
        onOpenMutual={(id) => navigation.push('CommunityMemberProfile', { userId: id })}
        onMessage={() => navigation.navigate('DirectChat', { userId, username: profile.username })}
        onTip={() => navigation.navigate('SendTip', { userId, username: profile.username })}
        refreshKey={returnsRefresh}
      />
      {badges.length > 0 ? (
        <Pressable style={styles.leagueBadges} onPress={() => navigation.navigate('BottomTabs', { screen: 'Invest', params: { segment: 'liga', at: Date.now() } } as never)} accessibilityRole="button">
          {badges.map((month) => (
            <View key={month} style={styles.leagueBadge}>
              <Text style={styles.leagueBadgeText}>🏆 {championLabel(month)}</Text>
            </View>
          ))}
        </Pressable>
      ) : null}
      {locked && access ? (
        <InvestorLockCard
          access={access}
          busy={publishBusy}
          onPublish={() => { void publishOwn(); }}
          onVerify={() => navigation.navigate('Verification' as never)}
        />
      ) : investor ? (
        <InvestorReturnsCard key={`returns-${userId}`} userId={userId} refreshKey={returnsRefresh} />
      ) : null}
      {visiblePortfolio && !locked ? (
        <CommunityPortfolioSection
          key={`portfolio-${visiblePortfolio.userId}`}
          portfolio={visiblePortfolio}
          onToggleHidden={visiblePortfolio.isSelf ? (value) => void toggleHidden(value) : undefined}
          hiddenBusy={hiddenBusy}
        />
      ) : null}
      <Text style={styles.sectionTitle}>Publicaciones</Text>
    </View>
  );

  return (
    <View style={styles.container}>
      {header}
      {investor?.isSelf ? (
        <InvestorBioEditor
          visible={bioOpen}
          initial={investor.bio}
          onClose={() => setBioOpen(false)}
          onSaved={(bio) => {
            const editedFor = investor.userId;
            if (!mounted.current) return;
            setBioOpen(false);
            // Only onto the profile that was edited, never another member shown since.
            setInvestor((current) => (current && current.userId === editedFor ? { ...current, bio } : current));
          }}
        />
      ) : null}
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
  leagueBadges: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, paddingHorizontal: 16, paddingVertical: 8 },
  leagueBadge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12, backgroundColor: colors.warning.background },
  leagueBadgeText: { fontSize: 12, fontWeight: '600', color: colors.warning.text },
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
