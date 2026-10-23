import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FlatList, Pressable, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useIsFocused, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useApolloClient } from '@apollo/client';

import { Text } from './common/AppText';
import { BylineAvatar } from './PostByline';
import { TeamBadge } from './TeamBadge';
import { colors } from '../config/theme';
import { GET_LEAGUE_TABLE, GET_TEAMS_LOOKING } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';
import { formatPctSigned } from '../utils/portfolioFormat';
import { LeagueRow, TEAM_MIN_RANKED, Team, rankMark } from '../utils/teams';

type Navigation = NativeStackNavigationProp<MainStackParamList>;

type TeamCard =
  | { kind: 'ranked'; key: string; row: LeagueRow }
  | { kind: 'forming'; key: string; team: Team }
  | { kind: 'create'; key: string };

const TOP = 10;

/**
 * The league at the top of Comunidad, Fomo style: a horizontal row of
 * teams (ranked by % return, then the ones still forming, then Crear
 * a team) and one of investors. "Ver todo" opens the whole league. Each row
 * is its own read: an older server, or a failure, only hides that row.
 */
export function LeagueStrips() {
  const navigation = useNavigation<Navigation>();
  const client = useApolloClient();
  const isFocused = useIsFocused();
  const [teams, setTeams] = useState<TeamCard[] | null>(null);
  const [investors, setInvestors] = useState<LeagueRow[] | null>(null);
  // Why the rows are a teaser: 'viewer_unverified' or 'viewer_hidden' (null when open).
  const [lockedBy, setLockedBy] = useState<string | null>(null);
  const generation = useRef(0);

  const load = useCallback(async () => {
    generation.current += 1;
    const requested = generation.current;
    const [teamTable, investorTable, looking] = await Promise.all([
      client.query({ query: GET_LEAGUE_TABLE, variables: { kind: 'teams', range: 'month', offset: 0, limit: TOP }, fetchPolicy: 'network-only' })
        .then((r) => r.data?.leagueTable ?? null).catch(() => null),
      client.query({ query: GET_LEAGUE_TABLE, variables: { kind: 'investors', range: 'month', offset: 0, limit: TOP }, fetchPolicy: 'network-only' })
        .then((r) => r.data?.leagueTable ?? null).catch(() => null),
      client.query({ query: GET_TEAMS_LOOKING, variables: { offset: 0, limit: TOP }, fetchPolicy: 'network-only' })
        .then((r) => (r.data?.teamsLooking ?? null) as Team[] | null).catch(() => null),
    ]);
    if (generation.current !== requested) return;
    if (teamTable === null) {
      // No league on this server (or it failed): no league rows at all.
      setTeams(null);
      setInvestors(null);
      return;
    }
    const open = teamTable.access === 'open';
    setLockedBy(open ? null : String(teamTable.access));
    const ranked: TeamCard[] = (teamTable.rows ?? []).map((row: LeagueRow) => ({ kind: 'ranked', key: `r${row.rank}`, row }));
    const rankedIds = new Set((teamTable.rows ?? []).map((row: LeagueRow) => row.team?.id));
    // Still forming: not in the ranking yet (fewer than 5 members with history).
    const forming: TeamCard[] = open
      ? (looking ?? []).filter((t) => !rankedIds.has(t.id)).map((team) => ({ kind: 'forming', key: `f${team.id}`, team }))
      : [];
    setTeams([...ranked, ...forming, ...(open ? [{ kind: 'create', key: 'create' } as TeamCard] : [])]);
    setInvestors(investorTable ? investorTable.rows ?? [] : null);
  }, [client]);

  useEffect(() => {
    if (isFocused) void load();
  }, [isFocused, load]);

  if (teams === null) return null;

  const openLeague = (kind: 'teams' | 'investors') => navigation.navigate('League', { kind });

  const renderTeam = ({ item }: { item: TeamCard }) => {
    if (item.kind === 'create') {
      return (
        <Pressable style={styles.card} onPress={() => navigation.navigate('TeamEdit')} accessibilityRole="button">
          <View style={styles.plus}><Icon name="plus" size={20} color={colors.primaryDark} /></View>
          <Text style={styles.cardName}>Crear equipo</Text>
          <Text style={styles.cardMeta}>Invita a tus amigos</Text>
        </Pressable>
      );
    }
    if (item.kind === 'forming') {
      const { team } = item;
      const missing = Math.max(TEAM_MIN_RANKED - team.memberCount, 0);
      return (
        <Pressable style={styles.card} onPress={() => navigation.navigate('Team', { teamId: team.id })} accessibilityRole="button">
          <TeamBadge emoji={team.emoji} color={team.color} size={44} />
          <Text style={styles.cardName} numberOfLines={1}>{team.name}</Text>
          <Text style={styles.cardMeta}>{missing > 0 ? `Faltan ${missing} para clasificar` : 'Buscando miembros'}</Text>
        </Pressable>
      );
    }
    const { row } = item;
    const team = row.team;
    if (!team) return null;
    const pct = formatPctSigned(row.pct);
    return (
      <Pressable style={styles.card} onPress={() => navigation.navigate('Team', { teamId: team.id })} accessibilityRole="button">
        <Text style={styles.rank}>{rankMark(row.rank)}</Text>
        <TeamBadge emoji={team.emoji} color={team.color} size={44} />
        <Text style={styles.cardName} numberOfLines={1}>{team.name}</Text>
        <Text style={[styles.pct, row.pct.startsWith('-') ? styles.down : styles.up]}>{pct}</Text>
      </Pressable>
    );
  };

  const renderInvestor = ({ item }: { item: LeagueRow }) => {
    if (!item.userId) return null;
    const userId = item.userId;
    const pct = formatPctSigned(item.pct);
    return (
      <Pressable style={styles.card} onPress={() => navigation.navigate('CommunityMemberProfile', { userId })} accessibilityRole="button">
        <Text style={styles.rank}>{rankMark(item.rank)}</Text>
        <BylineAvatar name={item.username ?? ''} avatarUrl={item.avatarUrl} size={44} />
        <Text style={styles.cardName} numberOfLines={1}>{item.username}</Text>
        <Text style={[styles.pct, item.pct.startsWith('-') ? styles.down : styles.up]}>{pct}</Text>
      </Pressable>
    );
  };

  const strip = (title: string, kind: 'teams' | 'investors', body: React.ReactNode) => (
    <View style={styles.strip}>
      <View style={styles.head}>
        <Text style={styles.title}>{title}</Text>
        <Pressable onPress={() => openLeague(kind)} hitSlop={8} accessibilityRole="button">
          <Text style={styles.link}>Ver todo</Text>
        </Pressable>
      </View>
      {body}
    </View>
  );

  return (
    <View style={styles.container}>
      {strip('Liga del mes · Equipos', 'teams', (
        <FlatList
          horizontal
          data={teams}
          keyExtractor={(c) => c.key}
          renderItem={renderTeam}
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.row}
          initialNumToRender={6}
          maxToRenderPerBatch={6}
          windowSize={5}
        />
      ))}
      {investors && investors.length > 0 ? strip('Liga del mes · Inversores', 'investors', (
        <FlatList
          horizontal
          data={investors}
          keyExtractor={(r) => `i${r.rank}`}
          renderItem={renderInvestor}
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.row}
          initialNumToRender={6}
          maxToRenderPerBatch={6}
          windowSize={5}
        />
      )) : null}
      {lockedBy ? (
        <Pressable
          style={styles.lockNote}
          onPress={() => (lockedBy === 'viewer_unverified' ? navigation.navigate('Verification' as never) : openLeague('teams'))}
          accessibilityRole="button"
        >
          <Icon name="lock" size={14} color={colors.primaryDark} />
          <Text style={styles.lockText}>
            {lockedBy === 'viewer_unverified'
              ? 'Verifica tu identidad para ver la rentabilidad de otros inversores, toda la Liga y unirte a un equipo.'
              : 'Ocultaste tu perfil de inversor: hazlo público para ver toda la Liga y unirte a un equipo.'}
          </Text>
          <Text style={styles.lockAction}>{lockedBy === 'viewer_unverified' ? 'Verificar' : 'Ver'}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { marginBottom: 8 },
  strip: { marginBottom: 14 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 },
  title: { fontSize: 15, fontWeight: '700', color: colors.dark },
  link: { fontSize: 14, fontWeight: '600', color: colors.primaryDark },
  row: { gap: 10, paddingRight: 16 },
  card: {
    width: 112, alignItems: 'center', gap: 5, paddingVertical: 12, paddingHorizontal: 8, borderRadius: 14,
    backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border,
  },
  rank: { fontSize: 13, fontWeight: '700', color: colors.dark },
  plus: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.primaryLight },
  cardName: { fontSize: 13, fontWeight: '600', color: colors.dark, textAlign: 'center' },
  cardMeta: { fontSize: 11, color: colors.textSecondary, textAlign: 'center' },
  pct: { fontSize: 14, fontWeight: '700' },
  up: { color: colors.flowIn.textSmall },
  down: { color: colors.error.icon },
  lockNote: { flexDirection: 'row', alignItems: 'center', gap: 8, padding: 12, borderRadius: 12, backgroundColor: colors.neutralDark },
  lockText: { flex: 1, fontSize: 12, color: colors.dark },
  lockAction: { fontSize: 13, fontWeight: '700', color: colors.primaryDark },
});
