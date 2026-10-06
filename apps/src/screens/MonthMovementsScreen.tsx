// The movements behind one number of "Tu mes" (design 3A/3B, eng D2 2nd pass).
//
// One screen, several filters (income | spending | category | uncategorized |
// counterparty | own_money), all from monthMovements, so a list always adds up
// to the total it was opened from. "Sin categoría" groups by counterparty with
// inline chips: one tap labels that counterparty (rule: past + future) and the
// group leaves the list. In other lists, tapping a spending row edits it and
// asks "¿Solo este pago o todos …?".
import React, { useCallback, useMemo, useRef, useState } from 'react';
import { Alert, FlatList, StyleSheet, TouchableOpacity, View } from 'react-native';
import { useMutation, useQuery } from '@apollo/client';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import { Header } from '../navigation/Header';
import { Text } from '../components/common/AppText';
import { ChipGrid } from '../components/CategoryChips';
import { colors } from '../config/theme';
import type { MainStackParamList } from '../types/navigation';
import {
  CATEGORIZE_MOVEMENT, GET_MONTH_MOVEMENTS, type CategoryKey, type MonthMovement,
} from '../apollo/monthSummary';
import { categoryLabel, deviceTimezone, formatUsd, MASK, monthName } from '../utils/monthSummary';

type Route = RouteProp<MainStackParamList, 'MonthMovements'>;

const SPENDING_KINDS = new Set(['merchant', 'p2p_send', 'payroll_out', 'donation']);
const KIND_LABEL: Record<string, string> = {
  top_up: 'Recarga', withdrawal: 'Retiro', savings_in: 'Guardaste', savings_out: 'Retiraste del ahorro',
  investment_in: 'Compra de acciones', investment_out: 'Venta de acciones', payroll_in: 'Sueldo',
  payroll_out: 'Nómina', sale: 'Venta', bonus: 'Bono',
};

type Group = { key: string; name: string; count: number; total: number; firstId: string };

function shortDate(iso: string) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : `${d.getDate()} ${monthName(d.getMonth() + 1).slice(0, 3)}`;
}

export function MonthMovementsScreen() {
  const navigation = useNavigation();
  const { params } = useRoute<Route>();
  const masked = Boolean(params.masked);
  const timezone = useMemo(() => deviceTimezone(), []);
  const variables = {
    year: params.year, month: params.month, timezone, filterBy: params.filterBy, value: params.value ?? null,
  };
  const { data, loading, error, refetch } = useQuery<{ monthMovements: MonthMovement[] }>(GET_MONTH_MOVEMENTS, {
    variables, fetchPolicy: 'cache-and-network',
    // refetch() after a save must start a NEW request: reusing a background
    // refresh sent before the save would bring back the pre-save list. A new
    // request also supersedes the old one, whose late answer is then ignored.
    context: { queryDeduplication: false },
  });
  // The summary's category split changes too. Refetch the MOUNTED summary
  // query by name (its own request supersedes any older one of the same
  // query); this also runs if the user already went back mid-save. The
  // summary screen additionally re-reads on every re-focus. 'MonthMovements'
  // also refreshes Tu mes's "Clasifica N pagos" count, even mid-navigation.
  const [categorize] = useMutation(CATEGORIZE_MOVEMENT, { refetchQueries: ['MonthSummary', 'MonthMovements'] });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [failedKey, setFailedKey] = useState<string | null>(null);
  // Optimistic (founder 2026-10-05: "it should be reactive"): a pick shows at
  // once and saves in the background; a failure puts things back and says so.
  //   hidden:    "Sin categoría" groups already labeled (gone from the list)
  //   overrides: row id -> category shown before the server confirms
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const [overrides, setOverrides] = useState<Record<string, CategoryKey | null>>({});
  // Last pick wins: a slower, older answer for the same key never reverts a
  // newer choice.
  const latestPick = useRef(new Map<string, number>());
  const raw = data?.monthMovements ?? [];
  const movements = useMemo(
    () => raw.map((m) => (m.id in overrides ? { ...m, category: overrides[m.id] } : m)),
    [raw, overrides],
  );

  const groups: Group[] = useMemo(() => {
    if (params.filterBy !== 'uncategorized') return [];
    const by = new Map<string, Group>();
    for (const m of movements) {
      const key = m.counterpartyKey || `row:${m.id}`;
      const g = by.get(key) ?? { key, name: m.counterpartyName || 'Sin nombre', count: 0, total: 0, firstId: m.id };
      g.count += 1;
      g.total += Number(m.amountUsd);
      by.set(key, g);
    }
    return [...by.values()].filter((g) => !hidden.has(g.key)).sort((a, b) => b.total - a.total);
  }, [movements, params.filterBy, hidden]);

  const save = useCallback(async (
    movementId: string, category: CategoryKey, applyTo: 'counterparty' | 'movement', failKey: string,
    optimistic: { hideGroup?: string; rowIds?: string[] },
  ) => {
    const seq = (latestPick.current.get(failKey) ?? 0) + 1;
    latestPick.current.set(failKey, seq);
    const before: Record<string, CategoryKey | null> = {};
    for (const id of optimistic.rowIds ?? []) before[id] = raw.find((m) => m.id === id)?.category ?? null;
    // Show the result now.
    setFailedKey((k) => (k === failKey ? null : k));
    setEditingId(null);
    if (optimistic.hideGroup) setHidden((h) => new Set(h).add(optimistic.hideGroup!));
    if (optimistic.rowIds?.length) {
      setOverrides((o) => ({ ...o, ...Object.fromEntries(optimistic.rowIds!.map((id) => [id, category])) }));
    }
    try {
      const res = await categorize({ variables: { movementId, category, applyTo } });
      if (!res.data?.categorizeMovement?.success) throw new Error('failed');
      // refetchQueries brings the server truth; the optimistic view already matches it.
    } catch {
      if (latestPick.current.get(failKey) !== seq) return;    // a newer pick owns this item now
      if (optimistic.hideGroup) {
        setHidden((h) => { const n = new Set(h); n.delete(optimistic.hideGroup!); return n; });
      }
      if (optimistic.rowIds?.length) {
        setOverrides((o) => ({ ...o, ...before }));
        setEditingId(failKey);                 // reopen so "No se guardó" is seen
      }
      setFailedKey(failKey);
    }
  }, [categorize, raw]);

  const editMovement = (m: MonthMovement, category: CategoryKey) => {
    const allRows = raw.filter((x) => x.counterpartyKey && x.counterpartyKey === m.counterpartyKey
      && SPENDING_KINDS.has(x.kind)).map((x) => x.id);
    if (!m.counterpartyKey) {
      save(m.id, category, 'movement', m.id, { rowIds: [m.id] });
      return;
    }
    Alert.alert(
      categoryLabel(category),
      `¿Solo este pago o todos los pagos a ${m.counterpartyName || 'este destinatario'}? "Todos" también cambia los pagos anteriores.`,
      [
        { text: 'Cancelar', style: 'cancel' },
        { text: 'Solo este pago', onPress: () => save(m.id, category, 'movement', m.id, { rowIds: [m.id] }) },
        { text: 'Todos', onPress: () => save(m.id, category, 'counterparty', m.id, { rowIds: allRows }) },
      ],
    );
  };

  // The app's shared screen header (same as Tu mes / Notificaciones).
  const header = (
    <Header navigation={navigation as any} title={params.title} backgroundColor={colors.heroField} isLight showBackButton />
  );

  const empty = loading ? null : error ? (
    <View style={styles.center}>
      <Text style={styles.muted}>No pudimos cargar los movimientos</Text>
      <TouchableOpacity onPress={() => refetch()} style={styles.retry} accessibilityRole="button">
        <Text style={styles.retryText}>Reintentar</Text>
      </TouchableOpacity>
    </View>
  ) : (
    <View style={styles.center}>
      <Text style={styles.muted}>
        {params.filterBy === 'uncategorized' ? 'Todo tiene categoría. ¡Listo!' : 'No hay movimientos.'}
      </Text>
    </View>
  );

  if (params.filterBy === 'uncategorized') {
    return (
      <View style={styles.safe}>
        {header}
        <FlatList
          data={groups}
          keyExtractor={(g) => g.key}
          initialNumToRender={20}
          maxToRenderPerBatch={10}
          windowSize={21}
          contentContainerStyle={styles.list}
          ListEmptyComponent={empty}
          renderItem={({ item }) => (
            <View style={styles.group} testID={`uncategorized-group-${item.key}`}>
              <View style={styles.rowBetween}>
                <Text style={styles.name} numberOfLines={1}>{item.name}</Text>
                <Text style={styles.meta}>
                  {item.count} {item.count === 1 ? 'pago' : 'pagos'} · {masked ? MASK : formatUsd(item.total)}
                </Text>
              </View>
              {/* A group keyed by a real counterparty labels all of them (rule). */}
              <ChipGrid
                selected={null}
                onPick={(c) => save(item.firstId, c, item.key.startsWith('row:') ? 'movement' : 'counterparty', item.key,
                  { hideGroup: item.key })}
              />
              {failedKey === item.key && <Text style={styles.failed}>No se guardó</Text>}
            </View>
          )}
        />
      </View>
    );
  }

  return (
    <View style={styles.safe}>
      {header}
      <FlatList
        data={movements}
        keyExtractor={(m) => m.id}
        initialNumToRender={20}
        maxToRenderPerBatch={10}
        windowSize={21}
        contentContainerStyle={styles.list}
        ListEmptyComponent={empty}
        renderItem={({ item }) => {
          const spending = SPENDING_KINDS.has(item.kind);
          const sign = item.direction === 'received' ? '+' : '';
          return (
            <View style={styles.row}>
              <TouchableOpacity
                disabled={!spending}
                onPress={() => setEditingId(editingId === item.id ? null : item.id)}
                style={styles.rowBetween}
                accessibilityRole={spending ? 'button' : undefined}
                accessibilityHint={spending ? 'Cambiar la categoría' : undefined}
              >
                <View style={styles.rowLeft}>
                  <Text style={styles.name} numberOfLines={1}>
                    {item.counterpartyName || KIND_LABEL[item.kind] || 'Movimiento'}
                  </Text>
                  <Text style={styles.meta}>
                    {shortDate(item.date)}{spending ? ` · ${categoryLabel(item.category)}` : ''}
                  </Text>
                </View>
                <Text style={styles.amount}>{masked ? MASK : `${sign}${formatUsd(item.amountUsd)}`}</Text>
              </TouchableOpacity>
              {editingId === item.id && (
                <>
                  <ChipGrid selected={item.category} onPick={(c) => editMovement(item, c)} />
                  {failedKey === item.id && <Text style={styles.failed}>No se guardó</Text>}
                </>
              )}
            </View>
          );
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.white },
  header: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 20, paddingVertical: 10 },
  title: { flex: 1, fontSize: 20, fontWeight: '700', color: colors.text.primary },
  list: { paddingHorizontal: 20, paddingBottom: 32, flexGrow: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  muted: { fontSize: 15, color: colors.text.secondary, textAlign: 'center' },
  retry: { marginTop: 12, minHeight: 44, justifyContent: 'center', paddingHorizontal: 20 },
  retryText: { fontSize: 15, fontWeight: '700', color: colors.primaryDark },
  group: { paddingVertical: 14, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border, gap: 10 },
  row: { paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border, gap: 10 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', minHeight: 44, gap: 12 },
  rowLeft: { flexShrink: 1 },
  name: { fontSize: 15, color: colors.text.primary },
  meta: { fontSize: 12, color: colors.text.secondary, fontVariant: ['tabular-nums'] },
  amount: { fontSize: 15, fontWeight: '600', color: colors.text.primary, fontVariant: ['tabular-nums'] },
  failed: { fontSize: 12, color: colors.text.secondary },
});
