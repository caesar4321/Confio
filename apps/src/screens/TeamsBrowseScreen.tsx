import React, { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useApolloClient } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { EmptyState } from '../components/EmptyState';
import { TeamBadge } from '../components/TeamBadge';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { GET_TEAMS_LOOKING } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';
import { formatPctSigned } from '../utils/portfolioFormat';
import { TEAM_MAX_MEMBERS, Team } from '../utils/teams';

type Navigation = NativeStackNavigationProp<MainStackParamList>;

const PAGE = 20;

/** Teams looking for members (your country first), and creating one. */
export const TeamsBrowseScreen = () => {
  const navigation = useNavigation<Navigation>();
  const client = useApolloClient();
  const [items, setItems] = useState<Team[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const generation = useRef(0);
  // No next page while a first-page load is in flight: its offset would be stale.
  const firstPending = useRef(false);

  const load = useCallback(async () => {
    generation.current += 1;
    const requested = generation.current;
    firstPending.current = true;
    try {
      const { data } = await client.query({
        query: GET_TEAMS_LOOKING,
        variables: { offset: 0, limit: PAGE },
        fetchPolicy: 'network-only',
      });
      if (generation.current !== requested) return;
      const page: Team[] = data?.teamsLooking ?? [];
      setItems(page);
      setHasMore(page.length === PAGE);
      setFailed(false);
    } catch {
      if (generation.current === requested) setFailed(true);
    } finally {
      if (generation.current === requested) firstPending.current = false;
    }
  }, [client]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  const loadMore = async () => {
    if (!hasMore || loadingMore || firstPending.current || !items) return;
    const requested = generation.current;
    setLoadingMore(true);
    try {
      const { data } = await client.query({
        query: GET_TEAMS_LOOKING,
        variables: { offset: items.length, limit: PAGE },
        fetchPolicy: 'network-only',
      });
      if (generation.current !== requested) return;
      const page: Team[] = data?.teamsLooking ?? [];
      setItems((current) => {
        const seen = new Set((current ?? []).map((t) => t.id));
        return [...(current ?? []), ...page.filter((t) => !seen.has(t.id))];
      });
      setHasMore(page.length === PAGE);
    } catch {
      // Reaching the end again retries.
    } finally {
      setLoadingMore(false);
    }
  };

  const renderItem = ({ item }: { item: Team }) => {
    const pct = formatPctSigned(item.returnPct);
    return (
      <Pressable onPress={() => navigation.navigate('Team', { teamId: item.id })}
        style={({ pressed }) => [styles.row, pressed && styles.pressed]} accessibilityRole="button">
        <TeamBadge emoji={item.emoji} color={item.color} size={44} />
        <View style={styles.rowBody}>
          <Text style={styles.name} numberOfLines={1}>{item.name}</Text>
          <Text style={styles.meta} numberOfLines={1}>
            {item.memberCount}/{TEAM_MAX_MEMBERS} miembros · {item.joinMode === 'approval' ? 'Con aprobación' : 'Abierto'}
            {pct ? ` · ${pct} en 7 días` : ''}
          </Text>
        </View>
        <Icon name="chevron-right" size={18} color={colors.textSecondary} />
      </Pressable>
    );
  };

  return (
    <View style={styles.container}>
      <Header title="Equipos" navigation={navigation as any} onBackPress={() => navigation.goBack()}
        backgroundColor={colors.background} isLight={false} />
      <FlatList
        data={items ?? []}
        keyExtractor={(t) => t.id}
        renderItem={renderItem}
        contentContainerStyle={styles.list}
        initialNumToRender={15}
        maxToRenderPerBatch={15}
        windowSize={11}
        onEndReachedThreshold={0.4}
        onEndReached={() => { void loadMore(); }}
        ListHeaderComponent={
          <View style={styles.headerBox}>
            <Pressable style={styles.create} onPress={() => navigation.navigate('TeamEdit')} accessibilityRole="button">
              <Icon name="plus" size={18} color={colors.white} />
              <Text style={styles.createText}>Crear equipo</Text>
            </Pressable>
            <Text style={styles.section}>Equipos buscando miembros</Text>
          </View>
        }
        ListFooterComponent={loadingMore ? <ActivityIndicator style={styles.loading} color={colors.primary} /> : null}
        refreshControl={
          <RefreshControl refreshing={refreshing} tintColor={colors.primary}
            onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />
        }
        ListEmptyComponent={failed ? (
          <EmptyState icon="wifi-off" title="No pudimos cargar los equipos" actionLabel="Reintentar" onAction={() => { void load(); }} />
        ) : items === null ? (
          <ActivityIndicator style={styles.loading} color={colors.primary} />
        ) : (
          <EmptyState icon="users" title="Aún no hay equipos con cupo" subtitle="Crea el tuyo e invita a otros inversores." />
        )}
      />
    </View>
  );
};

export default TeamsBrowseScreen;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  list: { paddingBottom: 32, flexGrow: 1 },
  loading: { marginTop: 32 },
  headerBox: { padding: 16, gap: 14 },
  create: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, paddingVertical: 12, borderRadius: 24, backgroundColor: colors.primaryDark },
  createText: { fontSize: 15, fontWeight: '700', color: colors.white },
  section: { fontSize: 13, fontWeight: '700', color: colors.textSecondary, textTransform: 'uppercase' },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.background, borderBottomWidth: 1, borderBottomColor: colors.borderLight,
  },
  pressed: { opacity: 0.7 },
  rowBody: { flex: 1 },
  name: { fontSize: 15, fontWeight: '600', color: colors.dark },
  meta: { marginTop: 2, fontSize: 12, color: colors.textSecondary },
});
