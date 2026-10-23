import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Pressable, RefreshControl, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useIsFocused, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useApolloClient, useMutation } from '@apollo/client';

import { Text } from './common/AppText';
import { BylineAvatar } from './PostByline';
import { EmptyState } from './EmptyState';
import { InvestorAccess, InvestorLockCard, isLocked } from './InvestorLockCard';
import { TeamBadge } from './TeamBadge';
import { colors } from '../config/theme';
import { SET_COMMUNITY_PORTFOLIO_HIDDEN_WITH_ERROR } from '../apollo/mutations';
import { GET_LEAGUE_DAYS_TO_RANK, GET_LEAGUE_TABLE, GET_MY_TEAM, GET_TEAMS_LOOKING } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';
import { formatPctSigned } from '../utils/portfolioFormat';
import { LEAGUE_RANGES, LeagueRange, LeagueRow, TEAM_MAX_MEMBERS, TEAM_MIN_RANKED, Team, daysToRankLabel, rankMark } from '../utils/teams';

type Navigation = NativeStackNavigationProp<MainStackParamList>;
export type LeagueKind = 'teams' | 'investors';
type Kind = LeagueKind;

type Props = {
  initialKind?: Kind;
  /** False while hidden (another segment of the Invertir tab): nothing loads. */
  active?: boolean;
};


const PAGE = 30;

/**
 * The league: teams and investors ranked by % return (never by how much
 * they have). Badges only, no money prizes. Reciprocal like portfolios: a
 * hidden or unverified viewer sees the top 3 and how to take part.
 */
export function LeagueContent({ initialKind = 'teams', active = true }: Props) {
  const navigation = useNavigation<Navigation>();
  const isFocused = useIsFocused();
  const client = useApolloClient();
  const [kind, setKind] = useState<Kind>(initialKind);
  // Teams with room, for someone without a team (most aren't ranked yet: 5 members first).
  const [looking, setLooking] = useState<Team[]>([]);
  // All time: proven days still needed to rank (the viewer, or the viewer's team).
  const [daysToRank, setDaysToRank] = useState<number | null>(null);
  const [range, setRange] = useState<LeagueRange>('month');
  const [rows, setRows] = useState<LeagueRow[] | null>(null);
  const [access, setAccess] = useState<InvestorAccess | null>(null);
  const [mine, setMine] = useState<{ rank: number; pct: string | null } | null>(null);
  const [myTeam, setMyTeam] = useState<Team | null | undefined>(undefined);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [failed, setFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const generation = useRef(0);
  // No next page while a first-page load is in flight: its offset would be stale.
  const firstPending = useRef(false);
  // Server positions consumed so far: the server drops blocked rows after
  // slicing, so what is shown can be shorter than what was read.
  const consumed = useRef(0);
  const [publish, { loading: publishing }] = useMutation(SET_COMMUNITY_PORTFOLIO_HIDDEN_WITH_ERROR);

  const load = useCallback(async (which: Kind, period: LeagueRange) => {
    generation.current += 1;
    const requested = generation.current;
    firstPending.current = true;
    client.query({ query: GET_MY_TEAM, fetchPolicy: 'network-only' })
      .then(({ data }) => {
        if (generation.current !== requested) return;
        setMyTeam((data?.myTeam ?? null) as Team | null);
      })
      .catch(() => {});
    // Teams still forming (not ranked yet) close the team ranking: teams and the league are one list.
    if (which === 'teams') {
      client.query({ query: GET_TEAMS_LOOKING, variables: { offset: 0, limit: 20 }, fetchPolicy: 'network-only' })
        .then((res) => { if (generation.current === requested) setLooking(res.data?.teamsLooking ?? []); })
        .catch(() => {});
    }
    try {
      const { data } = await client.query({
        query: GET_LEAGUE_TABLE,
        variables: { kind: which, range: period, offset: 0, limit: PAGE },
        fetchPolicy: 'network-only',
      });
      if (generation.current !== requested) return;
      const table = data?.leagueTable;
      setRows(table?.rows ?? []);
      consumed.current = PAGE;
      setHasMore(Boolean(table?.hasMore));
      setAccess((table?.access ?? null) as InvestorAccess | null);
      setMine(table?.myRank ? { rank: table.myRank, pct: table.myPct ?? null } : null);
      setDaysToRank(null);
      if (period === 'all' && !table?.myRank) {
        client.query({ query: GET_LEAGUE_DAYS_TO_RANK, variables: { kind: which }, fetchPolicy: 'network-only' })
          .then((res) => { if (generation.current === requested) setDaysToRank(res.data?.leagueDaysToRank ?? null); })
          .catch(() => {});
      }
      setFailed(false);
    } catch {
      if (generation.current === requested) setFailed(true);
    } finally {
      if (generation.current === requested) firstPending.current = false;
    }
  }, [client]);

  // On screen (tab focused and this segment shown) is when it reads.
  useEffect(() => {
    if (active && isFocused) void load(kind, range);
  }, [active, isFocused, load, kind, range]);

  const loadMore = async () => {
    if (!hasMore || loadingMore || firstPending.current || !rows) return;
    const requested = generation.current;
    setLoadingMore(true);
    try {
      // A page whose rows were all left out (blocks) reads on, a few pages at most.
      for (let attempt = 0; attempt < 5; attempt += 1) {
        const { data } = await client.query({
          query: GET_LEAGUE_TABLE,
          variables: { kind, range, offset: consumed.current, limit: PAGE },
          fetchPolicy: 'network-only',
        });
        if (generation.current !== requested) return;
        const table = data?.leagueTable;
        const page: LeagueRow[] = table?.rows ?? [];
        if (table?.access !== 'open') {
          // Access changed meanwhile (profile hidden elsewhere): the answer replaces everything shown.
          setRows(page);
          setAccess((table?.access ?? null) as InvestorAccess | null);
          setMine(null);
          setHasMore(false);
          return;
        }
        consumed.current += PAGE;
        // Ranks are unique within a table: they key the merge.
        setRows((current) => {
          const seen = new Set((current ?? []).map((r) => r.rank));
          return [...(current ?? []), ...page.filter((r) => !seen.has(r.rank))];
        });
        setHasMore(Boolean(table?.hasMore));
        if (page.length > 0 || !table?.hasMore) return;
      }
    } catch {
      // Reaching the end again retries.
    } finally {
      setLoadingMore(false);
    }
  };

  const switchTo = (nextKind: Kind, nextRange: LeagueRange) => {
    if (nextKind === kind && nextRange === range) return;
    setRows(null);
    setMine(null);
    setKind(nextKind);
    setRange(nextRange);
  };

  const publishOwn = async () => {
    try {
      const { data } = await publish({ variables: { hidden: false } });
      const result = data?.setCommunityPortfolioHidden;
      if (!result?.success) {
        Alert.alert('No pudimos hacer público tu perfil', result?.error || 'Inténtalo de nuevo en un momento.');
        return;
      }
      void load(kind, range);
    } catch {
      Alert.alert('No pudimos hacer público tu perfil', 'Revisa tu conexión e inténtalo de nuevo.');
    }
  };

  const locked = isLocked(access);
  const rankedIds = new Set((rows ?? []).map((r) => r.team?.id).filter(Boolean));

  const renderItem = ({ item }: { item: LeagueRow }) => {
    const pct = formatPctSigned(item.pct);
    const up = !item.pct.startsWith('-');
    const open = () => {
      if (item.team) navigation.navigate('Team', { teamId: item.team.id });
      else if (item.userId) navigation.navigate('CommunityMemberProfile', { userId: item.userId });
    };
    return (
      <Pressable onPress={open} style={({ pressed }) => [styles.row, pressed && styles.pressed]} accessibilityRole="button">
        <Text style={styles.rank}>{rankMark(item.rank)}</Text>
        {item.team ? (
          <TeamBadge emoji={item.team.emoji} color={item.team.color} size={40} />
        ) : (
          <BylineAvatar name={item.username ?? ''} avatarUrl={item.avatarUrl} size={40} />
        )}
        <View style={styles.rowBody}>
          <Text style={styles.name} numberOfLines={1}>{item.team ? item.team.name : item.username}</Text>
          {item.team ? (
            <Text style={styles.meta}>{item.members ?? item.team.memberCount} miembros cuentan</Text>
          ) : null}
        </View>
        <Text style={[styles.pct, up ? styles.up : styles.down]}>{pct}</Text>
      </Pressable>
    );
  };

  const header = (
    <View>
      {/* First thing a locked viewer sees: why, and the one step that opens it. */}
      {locked && access ? (
        <View style={styles.lock}>
          <InvestorLockCard access={access} busy={publishing} onPublish={() => { void publishOwn(); }}
            onVerify={() => navigation.navigate('Verification' as never)} />
        </View>
      ) : null}
      <View style={styles.tabs} accessibilityRole="tablist">
        {(['teams', 'investors'] as Kind[]).map((key) => {
          const selected = key === kind;
          return (
            <Pressable key={key} onPress={() => switchTo(key, range)} style={[styles.tab, selected && styles.tabSelected]}
              accessibilityRole="tab" accessibilityState={{ selected }}>
              <Text style={[styles.tabText, selected && styles.tabTextSelected]}>{key === 'teams' ? 'Equipos' : 'Inversores'}</Text>
            </Pressable>
          );
        })}
      </View>
      {!locked ? (
        <View style={styles.ranges}>
          {LEAGUE_RANGES.map((r) => {
            const selected = r.key === range;
            return (
              <Pressable key={r.key} onPress={() => switchTo(kind, r.key)} style={[styles.range, selected && styles.rangeSelected]}
                accessibilityRole="button" accessibilityState={{ selected }}>
                <Text style={[styles.rangeText, selected && styles.rangeTextSelected]}>{r.label}</Text>
              </Pressable>
            );
          })}
        </View>
      ) : null}
      <Text style={styles.explainer}>
        {kind === 'teams'
          ? 'Gana el equipo con mejor rentabilidad, no el que más invierte. Cuentan los equipos con 5 miembros o más.'
          : 'Gana quien tenga mejor rentabilidad en su portafolio, no quien más invierte.'}
        {range === 'all' ? ' Total suma los días seguidos con historial y clasifica desde 30 días.' : ''}
        {' '}Solo insignias, sin premios en dinero.
      </Text>
      {!locked && kind === 'teams' && myTeam ? (
        <Pressable style={styles.myTeam} onPress={() => navigation.navigate('Team', { teamId: myTeam.id })} accessibilityRole="button">
          <TeamBadge emoji={myTeam.emoji} color={myTeam.color} size={36} />
          <View style={styles.rowBody}>
            <Text style={styles.name} numberOfLines={1}>{myTeam.name}</Text>
            <Text style={styles.meta}>
              {mine
                ? `Tu equipo va ${rankMark(mine.rank)} con ${formatPctSigned(mine.pct)}`
                : daysToRankLabel(range === 'all' ? daysToRank : null, true) ?? 'Tu equipo aún no clasifica en este periodo'}
            </Text>
          </View>
          <Icon name="chevron-right" size={18} color={colors.textSecondary} />
        </Pressable>
      ) : null}
      {!locked && kind === 'investors' ? (
        <View style={styles.myTeam}>
          <View style={styles.rowBody}>
            <Text style={styles.name}>Tu posición</Text>
            <Text style={styles.meta}>
              {mine
                ? `${rankMark(mine.rank)} con ${formatPctSigned(mine.pct)}`
                : daysToRankLabel(range === 'all' ? daysToRank : null) ?? 'Aún no clasificas en este periodo (mínimo $10 invertidos)'}
            </Text>
          </View>
        </View>
      ) : null}
    </View>
  );

  return (
    <View style={styles.container}>
      <FlatList
        data={rows ?? []}
        keyExtractor={(r) => `${kind}-${r.rank}`}
        renderItem={renderItem}
        contentContainerStyle={styles.list}
        initialNumToRender={15}
        maxToRenderPerBatch={15}
        windowSize={11}
        onEndReachedThreshold={0.4}
        onEndReached={() => { void loadMore(); }}
        ListHeaderComponent={header}
        ListFooterComponent={
          <>
            {loadingMore ? <ActivityIndicator style={styles.loading} color={colors.primary} /> : null}
            {!locked && kind === 'teams' && rows !== null && !hasMore ? (
              <View style={styles.forming}>
                <Text style={styles.formingTitle}>Formándose</Text>
                <Text style={styles.formingHint}>Clasifican con {TEAM_MIN_RANKED} miembros. Únete desde la página del equipo.</Text>
                {looking.filter((t) => !rankedIds.has(t.id)).map((team) => {
                  const missing = Math.max(TEAM_MIN_RANKED - team.memberCount, 0);
                  return (
                    <Pressable key={team.id} style={({ pressed }) => [styles.row, pressed && styles.pressed]}
                      onPress={() => navigation.navigate('Team', { teamId: team.id })} accessibilityRole="button">
                      <Text style={styles.rank}>·</Text>
                      <TeamBadge emoji={team.emoji} color={team.color} size={40} />
                      <View style={styles.rowBody}>
                        <Text style={styles.name} numberOfLines={1}>{team.name}</Text>
                        <Text style={styles.meta}>
                          {team.memberCount}/{TEAM_MAX_MEMBERS} miembros{missing > 0 ? ` · faltan ${missing} para clasificar` : ''}
                        </Text>
                      </View>
                      <Icon name="chevron-right" size={18} color={colors.textSecondary} />
                    </Pressable>
                  );
                })}
                {looking.length >= 20 ? (
                  <Pressable style={styles.more} onPress={() => navigation.navigate('TeamsBrowse')} accessibilityRole="button">
                    <Text style={styles.link}>Ver más equipos</Text>
                  </Pressable>
                ) : null}
                <Pressable style={styles.create} onPress={() => navigation.navigate('TeamEdit')} accessibilityRole="button">
                  <Icon name="plus" size={18} color={colors.white} />
                  <Text style={styles.createText}>Crear equipo</Text>
                </Pressable>
              </View>
            ) : null}
          </>
        }
        refreshControl={
          <RefreshControl refreshing={refreshing} tintColor={colors.primary}
            onRefresh={async () => { setRefreshing(true); await load(kind, range); setRefreshing(false); }} />
        }
        ListEmptyComponent={failed ? (
          <EmptyState icon="wifi-off" title="No pudimos cargar la Liga" actionLabel="Reintentar"
            onAction={() => { void load(kind, range); }} />
        ) : rows === null ? (
          <ActivityIndicator style={styles.loading} color={colors.primary} />
        ) : (
          <EmptyState icon="award" title="Aún no hay clasificados"
            subtitle={kind === 'teams' ? 'Los equipos aparecen cuando tienen 5 miembros con historial.' : 'Los inversores aparecen con historial completo del periodo.'} />
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  list: { paddingBottom: 32, flexGrow: 1 },
  loading: { marginTop: 32 },
  tabs: { flexDirection: 'row', gap: 8, paddingHorizontal: 16, paddingTop: 10, backgroundColor: colors.background },
  tab: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 16, backgroundColor: colors.neutral },
  tabSelected: { backgroundColor: colors.dark },
  tabText: { fontSize: 14, fontWeight: '600', color: colors.textSecondary },
  tabTextSelected: { color: colors.white },
  ranges: { flexDirection: 'row', gap: 6, paddingHorizontal: 16, paddingVertical: 10, backgroundColor: colors.background },
  range: { paddingHorizontal: 12, paddingVertical: 5, borderRadius: 12, borderWidth: 1, borderColor: colors.border },
  rangeSelected: { borderColor: colors.primaryDark, backgroundColor: colors.primaryLight },
  rangeText: { fontSize: 13, fontWeight: '600', color: colors.textSecondary },
  rangeTextSelected: { color: colors.dark },
  explainer: { paddingHorizontal: 16, paddingVertical: 10, fontSize: 12, color: colors.textSecondary },
  myTeam: {
    flexDirection: 'row', alignItems: 'center', gap: 12, marginHorizontal: 16, marginBottom: 12, padding: 14,
    borderRadius: 14, backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border,
  },
  plus: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.primaryLight },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.background, borderBottomWidth: 1, borderBottomColor: colors.borderLight,
  },
  pressed: { opacity: 0.7 },
  rank: { width: 28, fontSize: 16, fontWeight: '700', color: colors.dark, textAlign: 'center' },
  rowBody: { flex: 1 },
  name: { fontSize: 15, fontWeight: '600', color: colors.dark },
  meta: { marginTop: 2, fontSize: 12, color: colors.textSecondary },
  pct: { fontSize: 15, fontWeight: '700' },
  up: { color: colors.flowIn.textSmall },
  down: { color: colors.error.icon },
  lock: { padding: 16 },
  forming: { marginTop: 16 },
  formingTitle: { paddingHorizontal: 16, fontSize: 15, fontWeight: '700', color: colors.dark },
  formingHint: { paddingHorizontal: 16, paddingTop: 2, paddingBottom: 8, fontSize: 12, color: colors.textSecondary },
  more: { alignItems: 'center', paddingVertical: 12 },
  create: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, margin: 16, paddingVertical: 12, borderRadius: 24, backgroundColor: colors.primaryDark },
  createText: { fontSize: 15, fontWeight: '700', color: colors.white },
  link: { fontSize: 14, fontWeight: '600', color: colors.primaryDark },
});
