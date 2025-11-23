import React, { useMemo, useState, useCallback } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, FlatList, RefreshControl, ScrollView, SafeAreaView } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';
import { GET_PAYROLL_RUNS } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'PayrollRunsHistory'>;

type WindowKey = '12m' | '24m' | '36m' | 'all';

const FILTERS: { key: WindowKey; label: string; months?: number }[] = [
  { key: '12m', label: 'Últimos 12m', months: 12 },
  { key: '24m', label: 'Últimos 24m', months: 24 },
  { key: '36m', label: 'Últimos 36m', months: 36 },
  { key: 'all', label: 'Todo' },
];

const statusStyles = (status: string) => {
  const key = (status || '').toLowerCase();
  switch (key) {
    case 'completed':
    case 'confirmed':
      return { bg: '#ecfdf3', fg: '#166534', label: 'Completado' };
    case 'prepared':
    case 'ready':
      return { bg: '#f3e8ff', fg: '#6b21a8', label: 'Listo' };
    case 'submitted':
      return { bg: '#e0f2fe', fg: '#075985', label: 'Enviado' };
    case 'pending':
      return { bg: '#fff7ed', fg: '#9a3412', label: 'Pendiente' };
    case 'failed':
    case 'cancelled':
      return { bg: '#fef2f2', fg: '#b91c1c', label: 'Fallido' };
    default:
      return { bg: '#e5e7eb', fg: '#374151', label: status || '—' };
  }
};

const monthsAgo = (months: number) => {
  const d = new Date();
  d.setMonth(d.getMonth() - months);
  return d;
};

const formatDate = (iso?: string | null) => {
  if (!iso) return 'Sin fecha';
  const d = new Date(iso);
  return d.toLocaleDateString();
};

const PayrollRunsHistoryScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { data, loading, refetch } = useQuery(GET_PAYROLL_RUNS, {
    fetchPolicy: 'cache-and-network',
  });
  const [windowKey, setWindowKey] = useState<WindowKey>('12m');

  const runs = data?.payrollRuns || [];

  const filteredRuns = useMemo(() => {
    const cut = FILTERS.find((f) => f.key === windowKey)?.months;
    return runs
      .filter((run: any) => {
        if (!cut) return true;
        const when = run.scheduledAt || run.createdAt;
        if (!when) return false;
        return new Date(when) >= monthsAgo(cut);
      })
      .map((run: any) => {
        const items = run.items || [];
        const total = items.reduce((acc: number, it: any) => acc + (Number(it.netAmount) || 0), 0);
        return {
          id: run.id,
          runId: run.runId,
          status: run.status,
          scheduledAt: run.scheduledAt,
          createdAt: run.createdAt,
          tokenType: run.tokenType || 'cUSD',
          itemCount: items.length,
          totalAmount: total,
        };
      })
      .sort((a: any, b: any) => {
        const aDate = new Date(a.scheduledAt || a.createdAt || '').getTime();
        const bDate = new Date(b.scheduledAt || b.createdAt || '').getTime();
        return bDate - aDate;
      });
  }, [runs, windowKey]);

  const totals = useMemo(() => {
    return filteredRuns.reduce(
      (acc, r) => {
        acc.runs += 1;
        acc.items += r.itemCount || 0;
        return acc;
      },
      { runs: 0, items: 0 },
    );
  }, [filteredRuns]);

  const renderItem = useCallback(({ item }: any) => {
    const badge = statusStyles(item.status);
    const displayDate = item.scheduledAt || item.createdAt;
    return (
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <View style={{ flex: 1 }}>
            <Text style={styles.runTitle}>Corrida #{item.runId || item.id?.slice(0, 6)}</Text>
            <Text style={styles.runDate}>{formatDate(displayDate)}</Text>
          </View>
          <View style={[styles.badge, { backgroundColor: badge.bg }]}>
            <Text style={[styles.badgeText, { color: badge.fg }]}>{badge.label}</Text>
          </View>
        </View>
        <View style={styles.metaRow}>
          <View style={styles.metaBlock}>
            <Text style={styles.metaLabel}>Token</Text>
            <Text style={styles.metaValue}>{item.tokenType}</Text>
          </View>
          <View style={styles.metaBlock}>
            <Text style={styles.metaLabel}>Destinatarios</Text>
            <Text style={styles.metaValue}>{item.itemCount}</Text>
          </View>
          <View style={styles.metaBlock}>
            <Text style={styles.metaLabel}>Total neto</Text>
            <Text style={styles.metaValue}>{item.totalAmount.toFixed(2)}</Text>
          </View>
        </View>
      </View>
    );
  }, []);

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="chevron-left" size={24} color="#111827" />
          </TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Corridas de nómina</Text>
            <Text style={styles.subtitle}>Pagos programados y completados por corrida</Text>
          </View>
          <TouchableOpacity onPress={() => refetch()} style={styles.refreshButton}>
            <Icon name="refresh-ccw" size={18} color="#111827" />
          </TouchableOpacity>
        </View>

        <View style={styles.filtersWrapper}>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.filtersContent}
            style={styles.filtersScroll}
          >
            {FILTERS.map((f) => {
              const sel = windowKey === f.key;
              return (
                <TouchableOpacity
                  key={f.key}
                  style={[styles.filterChip, sel && styles.filterChipSelected]}
                  onPress={() => setWindowKey(f.key)}
                >
                  <Text style={[styles.filterText, sel && styles.filterTextSelected]}>{f.label}</Text>
                </TouchableOpacity>
              );
            })}
          </ScrollView>
        </View>

        <View style={styles.summaryRow}>
          <View style={styles.summaryCard}>
            <Text style={styles.summaryLabel}>Corridas</Text>
            <Text style={styles.summaryValue}>{totals.runs}</Text>
          </View>
          <View style={styles.summaryCard}>
            <Text style={styles.summaryLabel}>Destinatarios</Text>
            <Text style={styles.summaryValue}>{totals.items}</Text>
          </View>
        </View>

        <FlatList
          data={filteredRuns}
          keyExtractor={(item: any) => item.id}
          renderItem={renderItem}
          contentContainerStyle={[styles.listContent, filteredRuns.length === 0 && { flex: 1 }]}
          ItemSeparatorComponent={() => <View style={{ height: 10 }} />}
          refreshControl={<RefreshControl refreshing={loading} onRefresh={() => refetch()} />}
          ListEmptyComponent={
            <View style={styles.empty}>
              <Icon name="clipboard" size={32} color="#9ca3af" />
              <Text style={styles.emptyTitle}>Sin historial</Text>
              <Text style={styles.emptySubtitle}>A medida que se ejecuten nóminas, aparecerán aquí.</Text>
            </View>
          }
        />
      </View>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#f9fafb' },
  container: { flex: 1, backgroundColor: '#f9fafb' },
  header: {
    paddingTop: 12,
    paddingBottom: 12,
    paddingHorizontal: 16,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    borderBottomWidth: 1,
    borderBottomColor: '#e5e7eb',
  },
  backButton: { padding: 6, marginRight: 10 },
  title: { fontSize: 18, fontWeight: '700', color: '#111827' },
  subtitle: { fontSize: 12, color: '#6b7280', marginTop: 2 },
  refreshButton: {
    width: 32,
    height: 32,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f3f4f6',
    borderRadius: 10,
  },
  filtersWrapper: {
    backgroundColor: '#f9fafb',
    height: 38,
    justifyContent: 'center',
  },
  filtersScroll: { flexGrow: 0, height: '100%' },
  filtersContent: {
    flexDirection: 'row',
    gap: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
    alignItems: 'center',
  },
  filterChip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    backgroundColor: '#f8fafc',
  },
  filterChipSelected: { borderColor: '#10b981', backgroundColor: '#ecfdf3' },
  filterText: { fontSize: 13, fontWeight: '600', color: '#374151' },
  filterTextSelected: { color: '#065f46' },
  summaryRow: {
    flexDirection: 'row',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: '#f9fafb',
  },
  summaryCard: {
    flex: 1,
    padding: 10,
    backgroundColor: '#fff',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  summaryLabel: { fontSize: 12, color: '#6b7280', marginBottom: 4 },
  summaryValue: { fontSize: 18, fontWeight: '700', color: '#111827' },
  listContent: { padding: 12 },
  card: {
    backgroundColor: '#fff',
    borderRadius: 14,
    padding: 14,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  runTitle: { fontSize: 16, fontWeight: '700', color: '#111827' },
  runDate: { fontSize: 12, color: '#6b7280', marginTop: 2 },
  badge: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 12,
  },
  badgeText: { fontSize: 11, fontWeight: '700' },
  metaRow: {
    flexDirection: 'row',
    gap: 12,
  },
  metaBlock: {
    flex: 1,
    padding: 10,
    borderRadius: 10,
    backgroundColor: '#f9fafb',
  },
  metaLabel: { fontSize: 11, color: '#6b7280', marginBottom: 4 },
  metaValue: { fontSize: 14, fontWeight: '700', color: '#111827' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8 },
  emptyTitle: { fontSize: 15, fontWeight: '700', color: '#111827' },
  emptySubtitle: { fontSize: 13, color: '#6b7280', textAlign: 'center' },
});

export default PayrollRunsHistoryScreen;
