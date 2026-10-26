import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Pressable, RefreshControl, StyleSheet, TextInput, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import { useApolloClient, useMutation } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { BylineAvatar } from '../components/PostByline';
import { EmptyState } from '../components/EmptyState';
import { InvestorAccess, InvestorLockCard, isLocked } from '../components/InvestorLockCard';
import { TeamBadge } from '../components/TeamBadge';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import {
  CANCEL_TEAM_JOIN_REQUEST,
  COPY_PLAY,
  DECIDE_TEAM_JOIN_REQUEST,
  EXPEL_TEAM_MEMBER,
  FOLLOW_TEAM,
  JOIN_TEAM,
  JOIN_TEAM_WITH_INVITE,
  LEAVE_TEAM,
  SET_COMMUNITY_PORTFOLIO_HIDDEN_WITH_ERROR,
  SET_TEAM_GOAL,
  TRANSFER_TEAM_CAPTAIN,
} from '../apollo/mutations';
import {
  GET_TEAM,
  GET_TEAM_PNL,
  GET_TEAM_INVITE,
  GET_TEAM_JOIN_REQUESTS,
  GET_TEAM_MEMBERS,
  GET_TEAM_PLAYS,
  GET_TEAM_POSITIONS,
} from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';
import { chatTime } from '../utils/directMessages';
import { formatPctSigned, formatUsd } from '../utils/portfolioFormat';
import { TEAM_MAX_MEMBERS, Team, championLabel, goalLabel, tickerOfSymbol } from '../utils/teams';

type Navigation = NativeStackNavigationProp<MainStackParamList>;
type RouteProps = NativeStackScreenProps<MainStackParamList, 'Team'>['route'];
type Tab = 'members' | 'positions' | 'plays' | 'goal' | 'requests';

type Member = { userId: string; username: string; avatarUrl?: string | null; role: string; returnPct?: string | null };
type Position = { symbol: string; asset: string; ticker: string; name: string; holders: number };
type Play = {
  id: string; userId: string; username: string; avatarUrl?: string | null; side: string; symbol: string;
  asset: string; ticker: string; name: string; at: string; copyable: boolean;
};
type JoinRequest = { id: string; userId: string; username: string; avatarUrl?: string | null; createdAt: string };
type Row = { key: string; member?: Member; position?: Position; play?: Play; request?: JoinRequest };

const QUERY_OF: Record<Exclude<Tab, 'goal'>, any> = {
  members: GET_TEAM_MEMBERS,
  positions: GET_TEAM_POSITIONS,
  plays: GET_TEAM_PLAYS,
  requests: GET_TEAM_JOIN_REQUESTS,
};

/**
 * A team: who is in it, what they hold and buy (counts and names, never
 * amounts), the team's goal, and copy play. Joining needs a public,
 * verified profile (reciprocity); the server decides and says why not.
 */
export const TeamScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProps>();
  const { teamId, inviteToken } = route.params;
  // Arrived through a friend's invite: who sent it, and whether it skips approval.
  const [invite, setInvite] = useState<{ inviterUsername: string; skipsApproval: boolean } | null>(null);
  const client = useApolloClient();
  const [team, setTeam] = useState<Team | null | undefined>(undefined);
  const [tab, setTab] = useState<Tab>('members');
  const [rows, setRows] = useState<Row[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const tabRef = useRef<Tab>('members');
  tabRef.current = tab;

  const [joinTeam] = useMutation(JOIN_TEAM);
  const [joinWithInvite] = useMutation(JOIN_TEAM_WITH_INVITE);
  useEffect(() => {
    if (!inviteToken) return;
    let live = true;
    client.query({ query: GET_TEAM_INVITE, variables: { token: inviteToken }, fetchPolicy: 'network-only' })
      .then(({ data }) => {
        const found = data?.teamInvite;
        if (live && found && String(found.teamId) === String(teamId)) {
          setInvite({ inviterUsername: found.inviterUsername, skipsApproval: Boolean(found.skipsApproval) });
        }
      })
      .catch(() => {});
    return () => { live = false; };
  }, [client, inviteToken, teamId]);
  const [leaveTeam] = useMutation(LEAVE_TEAM);
  const [cancelRequest] = useMutation(CANCEL_TEAM_JOIN_REQUEST);
  const [decideRequest] = useMutation(DECIDE_TEAM_JOIN_REQUEST);
  const [expelMember] = useMutation(EXPEL_TEAM_MEMBER);
  const [transferCaptain] = useMutation(TRANSFER_TEAM_CAPTAIN);
  const [followTeam] = useMutation(FOLLOW_TEAM);
  const [copyPlay] = useMutation(COPY_PLAY);
  const [publish, { loading: publishing }] = useMutation(SET_COMMUNITY_PORTFOLIO_HIDDEN_WITH_ERROR);

  const loadTab = useCallback(async (which: Tab, requested: number) => {
    if (which === 'goal') {
      setRows([]);
      return;
    }
    try {
      const { data } = await client.query({
        query: QUERY_OF[which],
        variables: which === 'members' ? { teamId, range: '7d' } : { teamId },
        fetchPolicy: 'network-only',
      });
      if (generation.current !== requested) return;
      const next: Row[] =
        which === 'members' ? (data?.teamMembers ?? []).map((m: Member) => ({ key: `m${m.userId}`, member: m }))
        : which === 'positions' ? (data?.teamPositions ?? []).map((p: Position) => ({ key: `p${p.symbol}`, position: p }))
        : which === 'plays' ? (data?.teamPlays ?? []).map((p: Play) => ({ key: `j${p.id}`, play: p }))
        : (data?.teamJoinRequests ?? []).map((r: JoinRequest) => ({ key: `r${r.id}`, request: r }));
      setRows(next);
    } catch {
      if (generation.current === requested) setRows([]);
    }
  }, [client, teamId]);

  const load = useCallback(async (which: Tab) => {
    generation.current += 1;
    const requested = generation.current;
    try {
      const { data } = await client.query({ query: GET_TEAM, variables: { teamId, range: '7d' }, fetchPolicy: 'network-only' });
      if (generation.current !== requested) return;
      const next = (data?.team ?? null) as Team | null;
      setTeam(next);
      if (next && !isLocked(next.access as InvestorAccess)) {
        // Dollars per member: their own read (an older server lacks the field).
        client.query({ query: GET_TEAM_PNL, variables: { teamId, range: '7d' }, fetchPolicy: 'network-only' })
          .then((r) => {
            if (generation.current !== requested) return;
            const pnl = r.data?.team?.returnPnlUsd ?? null;
            setTeam((t) => (t ? { ...t, returnPnlUsd: pnl } : t));
          })
          .catch(() => {});
      }
      setFailed(false);
      if (!next || isLocked(next.access as InvestorAccess)) {
        setRows([]);
        return;
      }
      // A tab this viewer can no longer use (left the team, not captain).
      const usable = (which === 'goal' && !next.isMember) || (which === 'requests' && !next.isCaptain) ? 'members' : which;
      if (usable !== which) setTab(usable);
      await loadTab(usable, requested);
    } catch {
      if (generation.current === requested) setFailed(true);
    }
  }, [client, teamId, loadTab]);

  useFocusEffect(
    useCallback(() => {
      // The tab selected now (tab switches load their own rows).
      void load(tabRef.current);
    }, [load]),
  );

  const switchTab = (next: Tab) => {
    if (next === tab) return;
    setTab(next);
    setRows(null);
    generation.current += 1;
    void loadTab(next, generation.current);
  };

  /** Runs a team mutation; shows the server's message when it refuses. */
  const act = async (run: () => Promise<any>, title: string): Promise<any | null> => {
    if (busy) return null;
    setBusy(true);
    try {
      const result = await run();
      if (!result?.success) {
        Alert.alert(title, result?.error || 'Inténtalo de nuevo en un momento.');
        return null;
      }
      return result;
    } catch {
      Alert.alert(title, 'Revisa tu conexión e inténtalo de nuevo.');
      return null;
    } finally {
      setBusy(false);
      void load(tabRef.current);
    }
  };

  const publishOwn = async () => {
    try {
      const { data } = await publish({ variables: { hidden: false } });
      const result = data?.setCommunityPortfolioHidden;
      if (!result?.success) {
        Alert.alert('No pudimos hacer público tu perfil', result?.error || 'Inténtalo de nuevo en un momento.');
        return;
      }
      void load(tabRef.current);
    } catch {
      Alert.alert('No pudimos hacer público tu perfil', 'Revisa tu conexión e inténtalo de nuevo.');
    }
  };

  const join = async () => {
    const result = await act(async () => (invite && inviteToken
      ? (await joinWithInvite({ variables: { teamId, inviteToken } })).data?.joinTeamWithInvite
      : (await joinTeam({ variables: { teamId } })).data?.joinTeam), 'No pudimos unirte');
    if (result?.outcome === 'requested') {
      Alert.alert('Solicitud enviada', 'El capitán decide quién entra. Te avisaremos.');
    }
  };

  const leave = () => {
    if (!team) return;
    Alert.alert(
      '¿Salir del equipo?',
      team.isCaptain && team.memberCount > 1
        ? 'Otro miembro será el capitán. Podrás unirte a otro equipo en 7 días.'
        : 'Podrás unirte a otro equipo en 7 días.',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Salir', style: 'destructive',
          onPress: () => { void act(async () => (await leaveTeam()).data?.leaveTeam, 'No pudimos sacarte del equipo'); },
        },
      ],
    );
  };

  const manageMember = (member: Member) => {
    if (!team?.isCaptain || member.userId === team.captainId) {
      navigation.navigate('CommunityMemberProfile', { userId: member.userId });
      return;
    }
    Alert.alert(member.username, undefined, [
      { text: 'Ver perfil', onPress: () => navigation.navigate('CommunityMemberProfile', { userId: member.userId }) },
      {
        text: 'Hacer capitán',
        onPress: () => Alert.alert(`¿Hacer capitán a ${member.username}?`, 'Dejarás de ser el capitán.', [
          { text: 'Cancelar', style: 'cancel' },
          {
            text: 'Confirmar',
            onPress: () => { void act(async () => (await transferCaptain({ variables: { teamId, userId: member.userId } })).data?.transferTeamCaptain, 'No pudimos cambiar el capitán'); },
          },
        ]),
      },
      {
        text: 'Sacar del equipo', style: 'destructive',
        onPress: () => { void act(async () => (await expelMember({ variables: { teamId, userId: member.userId } })).data?.expelTeamMember, 'No pudimos sacarlo del equipo'); },
      },
      { text: 'Cancelar', style: 'cancel' },
    ]);
  };

  const copy = async (play: Play) => {
    if (busy) return;
    setBusy(true);
    try {
      const { data } = await copyPlay({ variables: { playId: play.id } });
      const result = data?.copyPlay;
      if (!result?.success || !result.play) {
        Alert.alert('No se puede copiar', result?.error || 'Esta jugada ya no se puede copiar.');
        return;
      }
      const { symbol, asset, disclosure } = result.play;
      // The copier picks their own amount on the normal buy screen.
      Alert.alert('Copiar jugada', `${disclosure}\n\nTú eliges el monto. Aplican las comisiones normales.`, [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Continuar',
          onPress: () => (asset === 'stock'
            ? navigation.navigate('BuyStock', { ticker: tickerOfSymbol(symbol) })
            : navigation.navigate('BuyCrypto', { symbol })),
        },
      ]);
    } catch {
      Alert.alert('No se puede copiar', 'Revisa tu conexión e inténtalo de nuevo.');
    } finally {
      setBusy(false);
    }
  };

  const renderItem = ({ item }: { item: Row }) => {
    if (item.member) {
      const m = item.member;
      const pct = formatPctSigned(m.returnPct);
      return (
        <Pressable onPress={() => manageMember(m)} style={({ pressed }) => [styles.row, pressed && styles.pressed]} accessibilityRole="button">
          <BylineAvatar name={m.username} avatarUrl={m.avatarUrl} size={40} />
          <View style={styles.rowBody}>
            <Text style={styles.name} numberOfLines={1}>{m.username}</Text>
            {m.role === 'captain' ? <Text style={styles.meta}>Capitán</Text> : null}
          </View>
          {pct ? <Text style={[styles.pct, m.returnPct?.startsWith('-') ? styles.down : styles.up]}>{pct}</Text> : null}
        </Pressable>
      );
    }
    if (item.position) {
      const p = item.position;
      return (
        <View style={styles.row}>
          <View style={styles.ticker}><Text style={styles.tickerText}>{p.ticker.slice(0, 5)}</Text></View>
          <View style={styles.rowBody}>
            <Text style={styles.name} numberOfLines={1}>{p.name}</Text>
            <Text style={styles.meta}>{p.holders} {p.holders === 1 ? 'miembro la tiene' : 'miembros la tienen'}</Text>
          </View>
        </View>
      );
    }
    if (item.play) {
      const p = item.play;
      return (
        <View style={styles.row}>
          <BylineAvatar name={p.username} avatarUrl={p.avatarUrl} size={40} />
          <View style={styles.rowBody}>
            <Text style={styles.name} numberOfLines={1}>
              {p.username} {p.asset === 'perp' ? (p.side === 'buy' ? 'abrió' : 'cerró') : p.side === 'buy' ? 'compró' : 'vendió'} {p.ticker}
            </Text>
            <Text style={styles.meta}>{p.name} · {chatTime(p.at)}</Text>
          </View>
          {p.copyable ? (
            <Pressable onPress={() => { void copy(p); }} style={styles.copy} accessibilityRole="button" disabled={busy}>
              <Icon name="copy" size={14} color={colors.primaryDark} />
              <Text style={styles.copyText}>Copiar</Text>
            </Pressable>
          ) : null}
        </View>
      );
    }
    if (item.request) {
      const r = item.request;
      const decide = (approve: boolean) => {
        void act(async () => (await decideRequest({ variables: { requestId: r.id, approve } })).data?.decideTeamJoinRequest,
          'No pudimos responder la solicitud');
      };
      return (
        <View style={styles.row}>
          <Pressable onPress={() => navigation.navigate('CommunityMemberProfile', { userId: r.userId })}>
            <BylineAvatar name={r.username} avatarUrl={r.avatarUrl} size={40} />
          </Pressable>
          <View style={styles.rowBody}>
            <Text style={styles.name} numberOfLines={1}>{r.username}</Text>
            <Text style={styles.meta}>{chatTime(r.createdAt)}</Text>
          </View>
          <Pressable onPress={() => decide(false)} style={styles.decline} disabled={busy} accessibilityRole="button">
            <Text style={styles.declineText}>Rechazar</Text>
          </Pressable>
          <Pressable onPress={() => decide(true)} style={styles.accept} disabled={busy} accessibilityRole="button">
            <Text style={styles.acceptText}>Aceptar</Text>
          </Pressable>
        </View>
      );
    }
    return null;
  };

  if (team === undefined || team === null) {
    return (
      <View style={styles.container}>
        <Header title="Equipo" navigation={navigation as any} onBackPress={() => navigation.goBack()}
          backgroundColor={colors.background} isLight={false} />
        {team === null ? (
          <EmptyState icon="users" title="Este equipo ya no está disponible" />
        ) : failed ? (
          <EmptyState icon="wifi-off" title="No pudimos cargar el equipo" actionLabel="Reintentar" onAction={() => { void load(tab); }} />
        ) : (
          <ActivityIndicator style={styles.loading} color={colors.primary} />
        )}
      </View>
    );
  }

  const locked = isLocked(team.access as InvestorAccess);
  const tabs: { key: Tab; label: string }[] = [
    { key: 'members', label: 'Miembros' },
    { key: 'positions', label: 'Posiciones' },
    { key: 'plays', label: 'Jugadas' },
    ...(team.isMember ? [{ key: 'goal' as Tab, label: 'Meta' }] : []),
    ...(team.isCaptain ? [{ key: 'requests' as Tab, label: `Solicitudes${team.pendingRequests ? ` (${team.pendingRequests})` : ''}` }] : []),
  ];
  const pct = formatPctSigned(team.returnPct);
  const pnl = formatUsd(team.returnPnlUsd, { signed: true, usMark: true });

  const header = (
    <View>
      <View style={styles.hero}>
        <TeamBadge emoji={team.emoji} color={team.color} size={72} />
        <Text style={styles.title}>{team.name}</Text>
        {team.description ? <Text style={styles.description}>{team.description}</Text> : null}
        <Text style={styles.heroMeta}>
          {team.memberCount}/{TEAM_MAX_MEMBERS} miembros · {team.joinMode === 'approval' ? 'Con aprobación' : 'Abierto'}
        </Text>
        {!locked && (team.leagueRank || pct) ? (
          <Text style={styles.stat}>
            {team.leagueRank ? `#${team.leagueRank} en la Liga · ` : ''}
            {pnl ? `${pnl} por miembro${pct ? ` (${pct})` : ''} en 7 días` : pct ? `${pct} en 7 días` : ''}
          </Text>
        ) : null}
        {team.championMonths.length > 0 ? (
          <View style={styles.badges}>
            {team.championMonths.map((month) => (
              <View key={month} style={styles.champion}><Text style={styles.championText}>🏆 {championLabel(month)}</Text></View>
            ))}
          </View>
        ) : null}
        <View style={styles.actions}>
          {team.isMember ? (
            <>
              <Pressable style={styles.primary} accessibilityRole="button"
                onPress={() => navigation.navigate('TeamInvite', { teamId, teamName: team.name })}>
                <Text style={styles.primaryText}>Invitar</Text>
              </Pressable>
              {team.isCaptain ? (
                <Pressable style={styles.secondary} onPress={() => navigation.navigate('TeamEdit', { teamId })} accessibilityRole="button">
                  <Text style={styles.secondaryText}>Editar</Text>
                </Pressable>
              ) : null}
              <Pressable style={styles.secondary} onPress={leave} disabled={busy} accessibilityRole="button">
                <Text style={styles.secondaryText}>Salir</Text>
              </Pressable>
            </>
          ) : (
            <>
              {team.joinRequest === 'pending' ? (
                <Pressable style={styles.secondary} disabled={busy} accessibilityRole="button"
                  onPress={() => { void act(async () => (await cancelRequest({ variables: { teamId } })).data?.cancelTeamJoinRequest, 'No pudimos cancelar'); }}>
                  <Text style={styles.secondaryText}>Solicitud enviada · Cancelar</Text>
                </Pressable>
              ) : (
                <Pressable style={[styles.primary, (busy || Boolean(team.joinBlock)) && styles.disabled]}
                  disabled={busy || Boolean(team.joinBlock)} onPress={() => { void join(); }} accessibilityRole="button">
                  <Text style={styles.primaryText}>
                    {team.joinMode === 'approval' && !invite?.skipsApproval ? 'Pedir unirme' : 'Unirme'}
                  </Text>
                </Pressable>
              )}
              <Pressable style={styles.secondary} disabled={busy} accessibilityRole="button"
                onPress={() => { void act(async () => (await followTeam({ variables: { teamId, follow: !team.isFollowing } })).data?.followTeam, 'No pudimos guardar el cambio'); }}>
                <Text style={styles.secondaryText}>{team.isFollowing ? 'Siguiendo' : 'Seguir'}</Text>
              </Pressable>
            </>
          )}
        </View>
        {invite && !team.isMember ? (
          <Text style={styles.invited}>@{invite.inviterUsername} te invitó a este equipo.</Text>
        ) : null}
        {!team.isMember && team.joinBlockMessage && team.joinRequest !== 'pending' ? (
          <Text style={styles.blockMessage}>{team.joinBlockMessage}</Text>
        ) : null}
      </View>
      {locked ? (
        <View style={styles.lock}>
          <InvestorLockCard access={team.access as InvestorAccess}
            busy={publishing}
            onPublish={() => { void publishOwn(); }}
            onVerify={() => navigation.navigate('Verification' as never)} />
        </View>
      ) : (
        <View style={styles.tabs} accessibilityRole="tablist">
          {tabs.map(({ key, label }) => {
            const selected = key === tab;
            return (
              <Pressable key={key} onPress={() => switchTab(key)} style={[styles.tab, selected && styles.tabSelected]}
                accessibilityRole="tab" accessibilityState={{ selected }}>
                <Text style={[styles.tabText, selected && styles.tabTextSelected]}>{label}</Text>
              </Pressable>
            );
          })}
        </View>
      )}
      {!locked && tab === 'goal' ? <GoalCard team={team} onSaved={() => { void load(tabRef.current); }} /> : null}
      {!locked && tab === 'plays' ? (
        <Text style={styles.note}>Copiar una jugada no es una recomendación. Tú decides cuánto invertir.</Text>
      ) : null}
    </View>
  );

  return (
    <View style={styles.container}>
      <Header title="Equipo" navigation={navigation as any} onBackPress={() => navigation.goBack()}
        backgroundColor={colors.background} isLight={false} />
      <FlatList
        data={locked || tab === 'goal' ? [] : rows ?? []}
        keyExtractor={(r) => r.key}
        renderItem={renderItem}
        contentContainerStyle={styles.list}
        initialNumToRender={20}
        maxToRenderPerBatch={10}
        windowSize={11}
        ListHeaderComponent={header}
        refreshControl={
          <RefreshControl refreshing={refreshing} tintColor={colors.primary}
            onRefresh={async () => { setRefreshing(true); await load(tab); setRefreshing(false); }} />
        }
        ListEmptyComponent={locked || tab === 'goal' ? null : rows === null ? (
          <ActivityIndicator style={styles.loading} color={colors.primary} />
        ) : (
          <Text style={styles.empty}>
            {tab === 'positions' ? 'Aún no hay posiciones para mostrar.'
              : tab === 'plays' ? 'Aún no hay jugadas recientes.'
              : tab === 'requests' ? 'No hay solicitudes pendientes.'
              : 'No hay miembros para mostrar.'}
          </Text>
        )}
      />
    </View>
  );
};

/** Team goal: aggregate progress only. The captain sets it. */
function GoalCard({ team, onSaved }: { team: Team; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [kind, setKind] = useState<'invested_usd' | 'weekly_investors'>('invested_usd');
  const [target, setTarget] = useState('');
  const [setGoal, { loading }] = useMutation(SET_TEAM_GOAL);
  const goal = team.goal;

  const save = async () => {
    try {
      const { data } = await setGoal({ variables: { teamId: team.id, kind, target: target.trim() } });
      const result = data?.setTeamGoal;
      if (!result?.success) {
        Alert.alert('No pudimos guardar la meta', result?.error || 'Inténtalo de nuevo.');
        return;
      }
      setEditing(false);
      setTarget('');
      onSaved();
    } catch {
      Alert.alert('No pudimos guardar la meta', 'Revisa tu conexión e inténtalo de nuevo.');
    }
  };

  return (
    <View style={styles.goal}>
      {goal ? (
        <>
          <Text style={styles.name}>{goalLabel(goal)}</Text>
          <View style={styles.bar}><View style={[styles.barFill, { width: `${Math.min(100, Math.max(0, goal.percent))}%` }]} /></View>
          <Text style={styles.meta}>
            {goal.reached ? '¡Meta cumplida! 🎉' : `${goal.percent}%`}
            {goal.deadline ? ` · hasta el ${goal.deadline}` : ''}
          </Text>
        </>
      ) : (
        <Text style={styles.meta}>
          {team.isCaptain ? 'Define una meta para tu equipo.' : 'Tu equipo aún no tiene una meta visible.'}
        </Text>
      )}
      <Text style={styles.hint}>
        Nadie pone dinero en común: cada quien invierte en su propia cuenta. Las metas en dólares se muestran en pasos de 10%.
      </Text>
      {team.isCaptain && !editing ? (
        <Pressable style={styles.secondary} onPress={() => setEditing(true)} accessibilityRole="button">
          <Text style={styles.secondaryText}>{goal ? 'Cambiar meta' : 'Definir meta'}</Text>
        </Pressable>
      ) : null}
      {editing ? (
        <View style={styles.goalForm}>
          <View style={styles.kinds}>
            {(['invested_usd', 'weekly_investors'] as const).map((k) => (
              <Pressable key={k} onPress={() => setKind(k)} style={[styles.range, kind === k && styles.rangeSelected]} accessibilityRole="button">
                <Text style={styles.rangeText}>{k === 'invested_usd' ? 'Invertir juntos (US$)' : 'Miembros invirtiendo'}</Text>
              </Pressable>
            ))}
          </View>
          <TextInput
            value={target}
            onChangeText={(v) => setTarget(v.replace(/[^0-9]/g, ''))}
            keyboardType="number-pad"
            placeholder={kind === 'invested_usd' ? 'Ej: 1000 (pasos de 100)' : 'Ej: 5'}
            placeholderTextColor={colors.textSecondary}
            style={styles.input}
            maxLength={8}
          />
          <View style={styles.actions}>
            <Pressable style={styles.secondary} onPress={() => setEditing(false)} accessibilityRole="button">
              <Text style={styles.secondaryText}>Cancelar</Text>
            </Pressable>
            <Pressable style={[styles.primary, (!target || loading) && styles.disabled]} disabled={!target || loading}
              onPress={() => { void save(); }} accessibilityRole="button">
              <Text style={styles.primaryText}>Guardar</Text>
            </Pressable>
          </View>
        </View>
      ) : null}
    </View>
  );
}

export default TeamScreen;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  list: { paddingBottom: 32, flexGrow: 1 },
  loading: { marginTop: 32 },
  hero: { alignItems: 'center', padding: 20, gap: 6, backgroundColor: colors.background },
  title: { marginTop: 6, fontSize: 22, fontWeight: '700', color: colors.dark, textAlign: 'center' },
  description: { fontSize: 14, color: colors.dark, textAlign: 'center' },
  stat: { fontSize: 14, fontWeight: '600', color: colors.flowIn.textSmall },
  badges: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 6 },
  champion: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12, backgroundColor: colors.warning.background },
  championText: { fontSize: 12, fontWeight: '600', color: colors.warning.text },
  actions: { flexDirection: 'row', gap: 10, marginTop: 10, justifyContent: 'center' },
  primary: { paddingHorizontal: 22, paddingVertical: 10, borderRadius: 20, backgroundColor: colors.primaryDark },
  primaryText: { fontSize: 15, fontWeight: '700', color: colors.white },
  secondary: { paddingHorizontal: 18, paddingVertical: 10, borderRadius: 20, borderWidth: 1, borderColor: colors.border, alignSelf: 'center' },
  secondaryText: { fontSize: 15, fontWeight: '600', color: colors.dark },
  disabled: { opacity: 0.5 },
  invited: { marginTop: 6, fontSize: 13, fontWeight: '600', color: colors.primaryDark, textAlign: 'center' },
  blockMessage: { marginTop: 6, fontSize: 13, color: colors.textSecondary, textAlign: 'center' },
  lock: { padding: 16 },
  tabs: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, paddingHorizontal: 16, paddingVertical: 10, backgroundColor: colors.background,
    borderTopWidth: 1, borderTopColor: colors.borderLight },
  tab: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 16, backgroundColor: colors.neutral },
  tabSelected: { backgroundColor: colors.dark },
  tabText: { fontSize: 14, fontWeight: '600', color: colors.textSecondary },
  tabTextSelected: { color: colors.white },
  note: { paddingHorizontal: 16, paddingVertical: 8, fontSize: 12, color: colors.textSecondary },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.background, borderBottomWidth: 1, borderBottomColor: colors.borderLight,
  },
  pressed: { opacity: 0.7 },
  rowBody: { flex: 1 },
  name: { fontSize: 15, fontWeight: '600', color: colors.dark },
  meta: { marginTop: 2, fontSize: 12, color: colors.textSecondary },
  heroMeta: { fontSize: 13, color: colors.textSecondary, textAlign: 'center' },
  pct: { fontSize: 15, fontWeight: '700' },
  up: { color: colors.flowIn.textSmall },
  down: { color: colors.error.icon },
  ticker: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.neutralDark },
  tickerText: { fontSize: 10, fontWeight: '700', color: colors.dark },
  copy: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 14, backgroundColor: colors.primaryLight },
  copyText: { fontSize: 13, fontWeight: '600', color: colors.primaryDark },
  accept: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 14, backgroundColor: colors.primaryDark },
  acceptText: { fontSize: 13, fontWeight: '700', color: colors.white },
  decline: { paddingHorizontal: 10, paddingVertical: 6 },
  declineText: { fontSize: 13, fontWeight: '600', color: colors.textSecondary },
  empty: { padding: 24, fontSize: 14, color: colors.textSecondary, textAlign: 'center' },
  goal: { margin: 16, padding: 16, gap: 8, borderRadius: 14, backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border },
  bar: { height: 10, borderRadius: 5, backgroundColor: colors.neutralDark, overflow: 'hidden' },
  barFill: { height: 10, borderRadius: 5, backgroundColor: colors.primaryDark },
  hint: { fontSize: 12, color: colors.textSecondary },
  goalForm: { gap: 10 },
  kinds: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  range: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 12, borderWidth: 1, borderColor: colors.border },
  rangeSelected: { borderColor: colors.primaryDark, backgroundColor: colors.primaryLight },
  rangeText: { fontSize: 13, fontWeight: '600', color: colors.dark },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 16, color: colors.dark },
});
