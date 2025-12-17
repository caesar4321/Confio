import React, { useMemo, useState, useCallback } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, FlatList, RefreshControl, ScrollView, SafeAreaView, Platform, StatusBar } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';
import { GET_PAYROLL_RUNS } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'PayrollRunsHistory'>;

type WindowKey = '1m' | '3m' | '6m' | '12m' | 'all';

const FILTERS: { key: WindowKey; label: string; months?: number }[] = [
  { key: '1m', label: '1 mes', months: 1 },
  { key: '3m', label: '3 meses', months: 3 },
  { key: '6m', label: '6 meses', months: 6 },
  { key: '12m', label: '12 meses', months: 12 },
  { key: 'all', label: 'Todo' },
];

const statusStyles = (status: string) => {
  const key = (status || '').toLowerCase();
  switch (key) {
    case 'completed':
    case 'confirmed':
      return { bg: '#D1FAE5', fg: '#059669', label: 'Completada', icon: 'check-circle' };
    case 'prepared':
    case 'ready':
      return { bg: '#E0E7FF', fg: '#4F46E5', label: 'Lista', icon: 'clock' };
    case 'submitted':
      return { bg: '#DBEAFE', fg: '#2563EB', label: 'Procesando', icon: 'loader' };
    case 'pending':
      return { bg: '#FEF3C7', fg: '#D97706', label: 'Pendiente', icon: 'alert-circle' };
    case 'failed':
    case 'cancelled':
      return { bg: '#FEE2E2', fg: '#DC2626', label: 'Fallida', icon: 'x-circle' };
    default:
      return { bg: '#F3F4F6', fg: '#6B7280', label: status || '—', icon: 'help-circle' };
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
  return d.toLocaleDateString('es', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  });
};

const formatCurrency = (amount: number) => {
  return new Intl.NumberFormat('es', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
};

const PayrollRunsHistoryScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { data, loading, refetch } = useQuery(GET_PAYROLL_RUNS, {
    fetchPolicy: 'cache-and-network',
  });
  const [windowKey, setWindowKey] = useState<WindowKey>('3m');

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
        const completedItems = items.filter((it: any) =>
          (it.status || '').toLowerCase() === 'completed' ||
          (it.status || '').toLowerCase() === 'confirmed'
        ).length;

        return {
          id: run.id,
          runId: run.runId,
          status: run.status,
          scheduledAt: run.scheduledAt,
          createdAt: run.createdAt,
          tokenType: run.tokenType || 'cUSD',
          itemCount: items.length,
          completedItemCount: completedItems,
          totalAmount: total,
          items,
          business: run.business,
        };
      })
      .sort((a: any, b: any) => {
        const aDate = new Date(a.scheduledAt || a.createdAt || '').getTime();
        const bDate = new Date(b.scheduledAt || b.createdAt || '').getTime();
        return bDate - aDate;
      });
  }, [runs, windowKey]);

  const statistics = useMemo(() => {
    const completed = filteredRuns.filter((r: any) =>
      (r.status || '').toLowerCase() === 'completed' ||
      (r.status || '').toLowerCase() === 'confirmed'
    );

    const totalPaid = completed.reduce((acc: number, r: any) => acc + (r.totalAmount || 0), 0);
    const totalEmployees = filteredRuns.reduce((acc: number, r: any) => acc + (r.itemCount || 0), 0);
    const uniqueEmployees = new Set();

    filteredRuns.forEach((run: any) => {
      (run.items || []).forEach((item: any) => {
        if (item.recipientUser?.id) {
          uniqueEmployees.add(item.recipientUser.id);
        }
      });
    });

    return {
      totalRuns: filteredRuns.length,
      completedRuns: completed.length,
      totalPaid,
      totalPayments: totalEmployees,
      uniqueEmployees: uniqueEmployees.size,
    };
  }, [filteredRuns]);

  const renderItem = useCallback(({ item }: any) => {
    const badge = statusStyles(item.status);
    const displayDate = item.scheduledAt || item.createdAt;
    const isCompleted = (item.status || '').toLowerCase() === 'completed' ||
      (item.status || '').toLowerCase() === 'confirmed';

    return (
      <TouchableOpacity
        style={styles.card}
        onPress={() => navigation.navigate('PayrollRunDetail' as never, { run: item } as never)}
        activeOpacity={0.7}
      >
        <View style={styles.cardHeader}>
          <View style={[styles.iconBadge, { backgroundColor: badge.bg }]}>
            <Icon name={badge.icon as any} size={20} color={badge.fg} />
          </View>
          <View style={{ flex: 1, marginLeft: 12 }}>
            <Text style={styles.runTitle}>Corrida #{item.runId || item.id?.slice(0, 6)}</Text>
            <Text style={styles.runDate}>
              <Icon name="calendar" size={12} color="#9CA3AF" /> {formatDate(displayDate)}
            </Text>
          </View>
          <View style={[styles.statusBadge, { backgroundColor: badge.bg }]}>
            <Text style={[styles.statusText, { color: badge.fg }]}>{badge.label}</Text>
          </View>
        </View>

        <View style={styles.divider} />

        <View style={styles.statsGrid}>
          <View style={styles.statItem}>
            <Icon name="users" size={16} color="#6B7280" />
            <Text style={styles.statLabel}>Empleados</Text>
            <Text style={styles.statValue}>{item.itemCount}</Text>
            {item.completedItemCount < item.itemCount && (
              <Text style={styles.statSubtext}>
                {item.completedItemCount} pagados
              </Text>
            )}
          </View>

          <View style={styles.statDivider} />

          <View style={styles.statItem}>
            <Icon name="dollar-sign" size={16} color="#6B7280" />
            <Text style={styles.statLabel}>Total</Text>
            <Text style={styles.statValue}>{formatCurrency(item.totalAmount)}</Text>
            <Text style={styles.statSubtext}>cUSD</Text>
          </View>
        </View>

        <View style={styles.cardFooter}>
          <Icon name="file-text" size={14} color="#059669" />
          <Text style={styles.footerText}>Toca para ver detalle y descargar PDF</Text>
          <Icon name="chevron-right" size={16} color="#9CA3AF" />
        </View>
      </TouchableOpacity>
    );
  }, [navigation]);

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="arrow-left" size={22} color="#111827" />
          </TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Corridas de Nómina</Text>
            <Text style={styles.subtitle}>Historial de pagos programados</Text>
          </View>
        </View>

        {/* Filters */}
        <View style={styles.filtersWrapper}>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.filtersContent}
          >
            {FILTERS.map((f) => {
              const sel = windowKey === f.key;
              return (
                <TouchableOpacity
                  key={f.key}
                  style={[styles.filterChip, sel && styles.filterChipSelected]}
                  onPress={() => setWindowKey(f.key)}
                  activeOpacity={0.7}
                >
                  <Text style={[styles.filterText, sel && styles.filterTextSelected]}>
                    {f.label}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </ScrollView>
        </View>

        {/* Statistics Cards */}
        <View style={styles.statsContainer}>
          <View style={styles.statsRow}>
            <View style={[styles.statCard, { flex: 1 }]}>
              <Icon name="briefcase" size={20} color="#059669" />
              <Text style={styles.statCardValue}>{statistics.totalRuns}</Text>
              <Text style={styles.statCardLabel}>Corridas</Text>
              {statistics.completedRuns < statistics.totalRuns && (
                <Text style={styles.statCardSubtext}>
                  {statistics.completedRuns} completadas
                </Text>
              )}
            </View>

            <View style={[styles.statCard, { flex: 1 }]}>
              <Icon name="users" size={20} color="#2563EB" />
              <Text style={styles.statCardValue}>{statistics.uniqueEmployees}</Text>
              <Text style={styles.statCardLabel}>Empleados</Text>
              <Text style={styles.statCardSubtext}>únicos</Text>
            </View>
          </View>

          <View style={styles.totalPaidCard}>
            <View style={styles.totalPaidHeader}>
              <Icon name="trending-up" size={20} color="#059669" />
              <Text style={styles.totalPaidLabel}>Total pagado</Text>
            </View>
            <Text style={styles.totalPaidValue}>{formatCurrency(statistics.totalPaid)} cUSD</Text>
            <Text style={styles.totalPaidSubtext}>
              {statistics.totalPayments} pagos • {FILTERS.find(f => f.key === windowKey)?.label}
            </Text>
          </View>
        </View>

        {/* Runs List */}
        <FlatList
          data={filteredRuns}
          keyExtractor={(item: any) => item.id}
          renderItem={renderItem}
          contentContainerStyle={[
            styles.listContent,
            filteredRuns.length === 0 && { flex: 1 }
          ]}
          ItemSeparatorComponent={() => <View style={{ height: 12 }} />}
          refreshControl={
            <RefreshControl
              refreshing={loading}
              onRefresh={() => refetch()}
              tintColor="#059669"
              colors={['#059669']}
            />
          }
          ListEmptyComponent={
            <View style={styles.empty}>
              <View style={styles.emptyIcon}>
                <Icon name="inbox" size={48} color="#9CA3AF" />
              </View>
              <Text style={styles.emptyTitle}>No hay corridas</Text>
              <Text style={styles.emptySubtitle}>
                Las corridas de nómina que ejecutes aparecerán aquí.
              </Text>
            </View>
          }
        />
      </View>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#F9FAFB'
  },
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB'
  },
  header: {
    paddingTop: 12,
    paddingBottom: 16,
    paddingHorizontal: 16,
    marginTop: Platform.OS === 'android' ? (StatusBar.currentHeight || 24) + 10 : 0,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
  },
  backButton: {
    padding: 8,
    marginRight: 8,
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: '#111827'
  },
  subtitle: {
    fontSize: 13,
    color: '#6B7280',
    marginTop: 2
  },
  filtersWrapper: {
    backgroundColor: '#fff',
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#F3F4F6',
  },
  filtersContent: {
    paddingHorizontal: 16,
    gap: 8,
  },
  filterChip: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
    borderWidth: 1.5,
    borderColor: '#E5E7EB',
    backgroundColor: '#fff',
  },
  filterChipSelected: {
    borderColor: '#059669',
    backgroundColor: '#D1FAE5'
  },
  filterText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6B7280'
  },
  filterTextSelected: {
    color: '#059669'
  },
  statsContainer: {
    padding: 16,
    gap: 12,
  },
  statsRow: {
    flexDirection: 'row',
    gap: 12,
  },
  statCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 16,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    shadowColor: '#000',
    shadowOpacity: 0.05,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
  statCardValue: {
    fontSize: 28,
    fontWeight: '700',
    color: '#111827',
    marginTop: 8,
  },
  statCardLabel: {
    fontSize: 13,
    color: '#6B7280',
    marginTop: 4,
  },
  statCardSubtext: {
    fontSize: 11,
    color: '#9CA3AF',
    marginTop: 2,
  },
  totalPaidCard: {
    backgroundColor: '#ECFDF5',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: '#A7F3D0',
  },
  totalPaidHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  totalPaidLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#065F46',
  },
  totalPaidValue: {
    fontSize: 32,
    fontWeight: '700',
    color: '#059669',
    marginBottom: 4,
  },
  totalPaidSubtext: {
    fontSize: 12,
    color: '#059669',
  },
  listContent: {
    padding: 16,
    paddingTop: 8,
  },
  card: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    shadowColor: '#000',
    shadowOpacity: 0.05,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  iconBadge: {
    width: 44,
    height: 44,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  runTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#111827',
    marginBottom: 4,
  },
  runDate: {
    fontSize: 13,
    color: '#6B7280',
    flexDirection: 'row',
    alignItems: 'center',
  },
  statusBadge: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 12,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '700'
  },
  divider: {
    height: 1,
    backgroundColor: '#F3F4F6',
    marginVertical: 16,
  },
  statsGrid: {
    flexDirection: 'row',
    gap: 16,
  },
  statItem: {
    flex: 1,
    alignItems: 'center',
    gap: 4,
  },
  statDivider: {
    width: 1,
    backgroundColor: '#E5E7EB',
  },
  statLabel: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 4,
  },
  statValue: {
    fontSize: 20,
    fontWeight: '700',
    color: '#111827',
  },
  statSubtext: {
    fontSize: 11,
    color: '#9CA3AF',
  },
  cardFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 16,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#F3F4F6',
  },
  footerText: {
    flex: 1,
    fontSize: 12,
    color: '#059669',
    fontWeight: '500',
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 40,
  },
  emptyIcon: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: '#F3F4F6',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#111827',
    marginBottom: 8,
  },
  emptySubtitle: {
    fontSize: 14,
    color: '#6B7280',
    textAlign: 'center',
    lineHeight: 20,
  },
});

export default PayrollRunsHistoryScreen;
