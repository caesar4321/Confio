import React, { useMemo, useState, useCallback } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, FlatList, RefreshControl, ScrollView, Platform, StatusBar } from 'react-native';
import { Header } from '../navigation/Header';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';
import { GET_PAYROLL_RUNS } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';
import { APP_LAYOUT } from '../config/layout';

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
      return { bg: colors.primaryLight, fg: colors.primaryDark, label: 'Completada', icon: 'check-circle' };
    case 'prepared':
    case 'ready':
      return { bg: '#E0E7FF', fg: '#4F46E5', label: 'Lista', icon: 'clock' };
    case 'submitted':
      return { bg: '#DBEAFE', fg: colors.accent, label: 'Procesando', icon: 'loader' };
    case 'pending':
      return { bg: colors.warningLight, fg: colors.warning.icon, label: 'Pendiente', icon: 'alert-circle' };
    case 'failed':
    case 'cancelled':
      return { bg: '#FEE2E2', fg: colors.error.icon, label: 'Fallida', icon: 'x-circle' };
    default:
      return { bg: colors.neutralDark, fg: colors.text.secondary, label: status || '—', icon: 'help-circle' };
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
        onPress={() => navigation.navigate('PayrollRunDetail', { run: item })}
        activeOpacity={0.7}
      >
        <View style={styles.cardHeader}>
          <View style={[styles.iconBadge, { backgroundColor: badge.bg }]}>
            <Icon name={badge.icon as any} size={20} color={badge.fg} />
          </View>
          <View style={{ flex: 1, marginLeft: 12 }}>
            <Text style={styles.runTitle}>Corrida #{item.runId || item.id?.slice(0, 6)}</Text>
            <Text style={styles.runDate}>
              <Icon name="calendar" size={12} color={colors.text.light} /> {formatDate(displayDate)}
            </Text>
          </View>
          <View style={[styles.statusBadge, { backgroundColor: badge.bg }]}>
            <Text style={[styles.statusText, { color: badge.fg }]}>{badge.label}</Text>
          </View>
        </View>

        <View style={styles.divider} />

        <View style={styles.statsGrid}>
          <View style={styles.statItem}>
            <Icon name="users" size={16} color={colors.text.secondary} />
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
            <Icon name="dollar-sign" size={16} color={colors.text.secondary} />
            <Text style={styles.statLabel}>Total</Text>
            <Text style={styles.statValue}>{formatCurrency(item.totalAmount)}</Text>
            <Text style={styles.statSubtext}>cUSD</Text>
          </View>
        </View>

        <View style={styles.cardFooter}>
          <Icon name="file-text" size={14} color={colors.primaryDark} />
          <Text style={styles.footerText}>Toca para ver detalle y descargar PDF</Text>
          <Icon name="chevron-right" size={16} color={colors.text.light} />
        </View>
      </TouchableOpacity>
    );
  }, [navigation]);

  return (
    <View style={styles.safeArea}>
      <View style={styles.container}>
        <Header
          navigation={navigation as any}
          title="Corridas de Nómina"
          subtitle="Historial de pagos programados"
          backgroundColor={colors.white}
          showBackButton
        />

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
              <Icon name="briefcase" size={20} color={colors.primaryDark} />
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
              <Icon name="trending-up" size={20} color={colors.primaryDark} />
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
              tintColor={colors.primaryDark}
              colors={[colors.primaryDark]}
            />
          }
          ListEmptyComponent={
            <View style={styles.empty}>
              <View style={styles.emptyIcon}>
                <Icon name="inbox" size={48} color={colors.text.light} />
              </View>
              <Text style={styles.emptyTitle}>No hay corridas</Text>
              <Text style={styles.emptySubtitle}>
                Las corridas de nómina que ejecutes aparecerán aquí.
              </Text>
            </View>
          }
        />
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.neutral
  },
  container: {
    flex: 1,
    backgroundColor: colors.neutral
  },
  filtersWrapper: {
    backgroundColor: colors.white,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.neutralDark,
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
    borderColor: colors.border,
    backgroundColor: colors.white,
  },
  filterChipSelected: {
    borderColor: colors.primaryDark,
    backgroundColor: colors.primaryLight
  },
  filterText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.secondary
  },
  filterTextSelected: {
    color: colors.primaryDark
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
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 16,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: '#000',
    shadowOpacity: 0.05,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
  statCardValue: {
    fontSize: 28,
    fontWeight: '700',
    color: colors.text.primary,
    marginTop: 8,
  },
  statCardLabel: {
    fontSize: 13,
    color: colors.text.secondary,
    marginTop: 4,
  },
  statCardSubtext: {
    fontSize: 11,
    color: colors.text.light,
    marginTop: 2,
  },
  totalPaidCard: {
    backgroundColor: colors.primarySoft,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.primaryLight,
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
    color: colors.primaryDark,
  },
  totalPaidValue: {
    fontSize: 32,
    fontWeight: '700',
    color: colors.primaryDark,
    marginBottom: 4,
  },
  totalPaidSubtext: {
    fontSize: 12,
    color: colors.primaryDark,
  },
  listContent: {
    padding: 16,
    paddingTop: 8,
  },
  card: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.border,
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
    color: colors.text.primary,
    marginBottom: 4,
  },
  runDate: {
    fontSize: 13,
    color: colors.text.secondary,
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
    backgroundColor: colors.neutralDark,
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
    backgroundColor: colors.border,
  },
  statLabel: {
    fontSize: 12,
    color: colors.text.secondary,
    marginTop: 4,
  },
  statValue: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text.primary,
  },
  statSubtext: {
    fontSize: 11,
    color: colors.text.light,
  },
  cardFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 16,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: colors.neutralDark,
  },
  footerText: {
    flex: 1,
    fontSize: 12,
    color: colors.primaryDark,
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
    backgroundColor: colors.neutralDark,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text.primary,
    marginBottom: 8,
  },
  emptySubtitle: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 20,
  },
});

export default PayrollRunsHistoryScreen;
