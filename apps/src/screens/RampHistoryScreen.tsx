import React, { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  SafeAreaView,
  StatusBar,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { RouteProp, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import moment from 'moment';
import 'moment/locale/es';

import { GET_CURRENT_ACCOUNT_TRANSACTIONS } from '../apollo/queries';
import { useAccount } from '../contexts/AccountContext';
import { MainStackParamList } from '../types/navigation';
import { RampHero } from '../components/ramps/RampHero';
import { colors } from '../config/theme';

moment.locale('es');

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'RampHistory'>;
type RouteProps = RouteProp<MainStackParamList, 'RampHistory'>;
type RampFilter = 'all' | 'on_ramp' | 'off_ramp';

type ListRow =
  | { kind: 'section'; label: string; key: string }
  | { kind: 'item'; data: any; key: string };

/* ─── helpers ─── */

const getStatusTone = (status?: string | null): 'success' | 'info' | 'warning' | 'error' | 'neutral' => {
  switch ((status || '').toUpperCase()) {
    case 'COMPLETED':
    case 'DELIVERED':
    case 'CONFIRMED':
      return 'success';
    case 'FAILED':
    case 'REJECTED':
    case 'EXPIRED':
      return 'error';
    case 'PROCESSING':
    case 'SUBMITTED':
      return 'info';
    case 'AML_REVIEW':
    case 'PENDING':
      return 'warning';
    default:
      return 'neutral';
  }
};

const getStatusLabel = (status?: string | null): string => {
  switch ((status || '').toUpperCase()) {
    case 'COMPLETED':
    case 'DELIVERED':
    case 'CONFIRMED':
      return 'Completado';
    case 'FAILED':
      return 'Fallido';
    case 'REJECTED':
      return 'Rechazado';
    case 'EXPIRED':
      return 'Expirado';
    case 'AML_REVIEW':
      return 'En revisión';
    case 'PROCESSING':
      return 'En proceso';
    case 'SUBMITTED':
      return 'Enviado';
    case 'PENDING':
      return 'Pendiente';
    default:
      return status || 'Sin estado';
  }
};

const getDetailStatus = (status?: string | null): 'completed' | 'pending' | 'failed' => {
  switch ((status || '').toUpperCase()) {
    case 'COMPLETED':
    case 'DELIVERED':
    case 'CONFIRMED':
      return 'completed';
    case 'FAILED':
    case 'REJECTED':
    case 'EXPIRED':
      return 'failed';
    default:
      return 'pending';
  }
};

const formatDate = (dateString?: string | null): string => {
  if (!dateString) return '';
  const date = moment.utc(dateString).local();
  const now = moment();
  if (date.isSame(now, 'day')) return `Hoy · ${date.format('HH:mm')}`;
  if (date.isSame(now.clone().subtract(1, 'day'), 'day')) return `Ayer · ${date.format('HH:mm')}`;
  return date.format('D [de] MMM · HH:mm');
};

const getSectionLabel = (dateString?: string | null): string => {
  if (!dateString) return 'Sin fecha';
  const date = moment.utc(dateString).local();
  const now = moment();
  if (date.isSame(now, 'day')) return 'Hoy';
  if (date.isSame(now.clone().subtract(1, 'day'), 'day')) return 'Ayer';
  if (date.isSame(now, 'week')) return date.format('dddd'); // e.g. "martes"
  if (date.isSame(now, 'year')) return date.format('D [de] MMMM');
  return date.format('D [de] MMMM, YYYY');
};

const getSectionKey = (dateString?: string | null): string => {
  if (!dateString) return 'none';
  return moment.utc(dateString).local().format('YYYY-MM-DD');
};

const getCurrencyLabel = (tokenType?: string | null): string => {
  const normalized = String(tokenType || '').trim().toUpperCase();
  if (normalized === 'CUSD') return 'cUSD';
  if (normalized === 'USDC POLYGON' || normalized === 'USDC SOLANA' || normalized === 'USDC-A') return 'cUSD';
  return tokenType || 'cUSD';
};

const formatAmount = (raw: string | number, currency?: string): string => {
  const num = parseFloat(String(raw).replace(/[+-]/g, ''));
  if (isNaN(num)) return String(raw);
  const isCrypto = !currency || ['CUSD', 'USDC', 'ALGO', 'cUSD'].includes(currency.toUpperCase());
  if (isCrypto) {
    return num.toLocaleString('es-VE', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  }
  return num.toLocaleString('es-VE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const formatPrimaryRampAmount = (item: any, isOffRamp: boolean): { amount: string; currency: string } => {
  const fiatAmount = String(item.rampFiatAmount || '').trim();
  const fiatCurrency = String(item.rampFiatCurrency || '').trim();
  if (!isOffRamp && fiatAmount && fiatCurrency && fiatAmount !== '0') {
    return { amount: formatAmount(fiatAmount, fiatCurrency), currency: fiatCurrency };
  }
  const rawAmount = String(item.displayAmount || item.amount || '').trim();
  if (!rawAmount || rawAmount === '--') return { amount: '--', currency: isOffRamp ? 'cUSD' : getCurrencyLabel(item.tokenType) };
  const currency = isOffRamp ? 'cUSD' : getCurrencyLabel(item.tokenType);
  return { amount: formatAmount(rawAmount, currency), currency };
};

/* ─── component ─── */

export const RampHistoryScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const route = useRoute<RouteProps>();
  const { activeAccount } = useAccount();
  const [selectedFilter, setSelectedFilter] = useState<RampFilter>(route.params?.initialFilter || 'all');

  const tokenTypes = useMemo(() => {
    if (!activeAccount) return ['CUSD', 'USDC', 'ALGO'];
    if (activeAccount.type === 'business') return ['CUSD', 'USDC', 'ALGO'];
    return activeAccount.isEmployee ? ['CUSD'] : ['CUSD', 'USDC', 'ALGO'];
  }, [activeAccount]);

  const { data, loading, refetch } = useQuery(GET_CURRENT_ACCOUNT_TRANSACTIONS, {
    variables: { limit: 100, offset: 0, tokenTypes },
    skip: !activeAccount,
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
  });

  const rampTransactions = useMemo(() => {
    const transactions = data?.currentAccountTransactions || [];
    return transactions
      .filter((tx: any) => (tx.transactionType || '').toLowerCase() === 'ramp')
      .filter((tx: any) => {
        const rampDirection = (tx.rampDirection || '').toLowerCase();
        if (selectedFilter === 'on_ramp') return rampDirection === 'on_ramp';
        if (selectedFilter === 'off_ramp') return rampDirection === 'off_ramp';
        return true;
      });
  }, [data?.currentAccountTransactions, selectedFilter]);

  /* Build grouped list rows */
  const listRows = useMemo((): ListRow[] => {
    const rows: ListRow[] = [];
    let lastSection = '';
    for (const item of rampTransactions) {
      const sectionKey = getSectionKey(item.createdAt);
      if (sectionKey !== lastSection) {
        rows.push({ kind: 'section', label: getSectionLabel(item.createdAt), key: `section-${sectionKey}` });
        lastSection = sectionKey;
      }
      rows.push({ kind: 'item', data: item, key: item.id });
    }
    return rows;
  }, [rampTransactions]);

  /* Per-filter counts for badge */
  const counts = useMemo(() => {
    const transactions = data?.currentAccountTransactions || [];
    const ramps = transactions.filter((tx: any) => (tx.transactionType || '').toLowerCase() === 'ramp');
    return {
      all: ramps.length,
      on_ramp: ramps.filter((tx: any) => (tx.rampDirection || '').toLowerCase() === 'on_ramp').length,
      off_ramp: ramps.filter((tx: any) => (tx.rampDirection || '').toLowerCase() === 'off_ramp').length,
    };
  }, [data?.currentAccountTransactions]);

  const title = selectedFilter === 'on_ramp'
    ? 'Historial de recargas'
    : selectedFilter === 'off_ramp'
      ? 'Historial de retiros'
      : 'Recargas y retiros';
  const subtitle = selectedFilter === 'on_ramp'
    ? 'Consulta el estado y el monto final de tus compras de saldo.'
    : selectedFilter === 'off_ramp'
      ? 'Consulta el estado y el monto final de tus retiros.'
      : 'Todas tus operaciones de rampa en un solo lugar.';

  const renderFilterChip = (filter: RampFilter, label: string) => {
    const selected = selectedFilter === filter;
    const count = counts[filter];
    return (
      <TouchableOpacity
        key={filter}
        style={[styles.filterChip, selected && styles.filterChipSelected]}
        onPress={() => setSelectedFilter(filter)}
        activeOpacity={0.8}
      >
        <Text style={[styles.filterChipText, selected && styles.filterChipTextSelected]}>{label}</Text>
        {count > 0 && (
          <View style={[styles.filterBadge, selected && styles.filterBadgeSelected]}>
            <Text style={[styles.filterBadgeText, selected && styles.filterBadgeTextSelected]}>{count}</Text>
          </View>
        )}
      </TouchableOpacity>
    );
  };

  const renderRow = ({ item: row }: { item: ListRow }) => {
    if (row.kind === 'section') {
      return (
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionLabel}>{row.label}</Text>
          <View style={styles.sectionLine} />
        </View>
      );
    }

    const item = row.data;
    const isOffRamp = (item.rampDirection || '').toLowerCase() === 'off_ramp';
    const statusTone = getStatusTone(item.rampStatus || item.status);
    const providerLabel = item.rampProvider || item.displayCounterparty || 'Proveedor';
    const titleText = isOffRamp ? 'Retiro' : 'Recarga';
    const primaryAmount = formatPrimaryRampAmount(item, isOffRamp);

    const statusColors = {
      success: { bg: colors.primaryLight, text: colors.primaryDark },
      info: { bg: '#dbeafe', text: '#1d4ed8' },
      warning: { bg: colors.warningLight, text: colors.warning.text },
      error: { bg: colors.dangerLight, text: colors.danger },
      neutral: { bg: '#f3f4f6', text: colors.textSecondary },
    }[statusTone];

    return (
      <TouchableOpacity
        style={styles.itemCard}
        onPress={() => {
          navigation.navigate('TransactionDetail', {
            transactionType: 'ramp',
            transactionData: {
              ...item,
              type: 'ramp',
              amount: primaryAmount.amount,
              currency: primaryAmount.currency,
              formattedTitle: `${titleText} con ${providerLabel}`,
              from: isOffRamp ? 'Tu cuenta' : providerLabel,
              to: isOffRamp ? providerLabel : 'Tu cuenta',
              status: getDetailStatus(item.rampStatus || item.status),
              rampStatus: item.rampStatus || item.status,
              date: item.createdAt,
              time: moment.utc(item.createdAt).local().format('HH:mm'),
            },
          });
        }}
        activeOpacity={0.75}
      >
        {/* Left icon */}
        <View style={[styles.itemIconWrap, isOffRamp ? styles.itemIconWrapOff : styles.itemIconWrapOn]}>
          <Icon
            name={isOffRamp ? 'arrow-up-right' : 'arrow-down-left'}
            size={18}
            color={isOffRamp ? colors.offRampIcon : colors.primaryDark}
          />
        </View>

        {/* Centre copy */}
        <View style={styles.itemCopy}>
          <Text style={styles.itemTitle}>{titleText}</Text>
          <Text style={styles.itemSubtitle} numberOfLines={1}>{providerLabel}</Text>
          <Text style={styles.itemDate}>{formatDate(item.createdAt)}</Text>
        </View>

        {/* Right: amount + status */}
        <View style={styles.itemRight}>
          <Text style={[styles.itemAmount, isOffRamp ? styles.itemAmountNegative : styles.itemAmountPositive]}>
            {isOffRamp ? '−' : '+'}{primaryAmount.amount}
          </Text>
          <Text style={styles.itemCurrency}>{primaryAmount.currency}</Text>
          <View style={[styles.statusPill, { backgroundColor: statusColors.bg }]}>
            <Text style={[styles.statusPillText, { color: statusColors.text }]}>
              {getStatusLabel(item.rampStatus || item.status)}
            </Text>
          </View>
        </View>
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primaryDark} />
      <FlatList
        data={listRows}
        keyExtractor={(row) => row.key}
        style={styles.list}
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
        initialNumToRender={20}
        maxToRenderPerBatch={10}
        windowSize={21}
        refreshControl={
          <RefreshControl
            refreshing={loading}
            onRefresh={() => void refetch()}
            tintColor={colors.primary}
            colors={[colors.primaryDark]}
          />
        }
        ListHeaderComponent={(
          <>
            <RampHero
              eyebrow="Historial"
              title={title}
              subtitle={subtitle}
              onBack={() => navigation.goBack()}
              fromColor={colors.primaryDark}
              toColor={colors.primary}
            />
            <View style={styles.filtersRow}>
              {renderFilterChip('all', 'Todo')}
              {renderFilterChip('on_ramp', 'Recargas')}
              {renderFilterChip('off_ramp', 'Retiros')}
            </View>
          </>
        )}
        ListEmptyComponent={(
          <View style={styles.emptyWrap}>
            {loading ? (
              <ActivityIndicator color={colors.primaryDark} size="large" />
            ) : (
              <>
                <View style={styles.emptyIconCircle}>
                  <Icon name="clock" size={28} color={colors.primaryDark} />
                </View>
                <Text style={styles.emptyTitle}>Sin operaciones aún</Text>
                <Text style={styles.emptyText}>
                  Cuando completes una recarga o un retiro, aparecerá aquí.
                </Text>
              </>
            )}
          </View>
        )}
        renderItem={renderRow}
      />
    </SafeAreaView>
  );
};

export default RampHistoryScreen;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.primaryDark,
  },
  list: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    paddingBottom: 56,
  },

  /* ── Filters ── */
  filtersRow: {
    flexDirection: 'row',
    gap: 8,
    paddingHorizontal: 22,
    marginBottom: 20,
  },
  filterChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: 999,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  filterChipSelected: {
    backgroundColor: colors.primaryLight,
    borderColor: '#a7f3d0',
  },
  filterChipText: {
    fontSize: 13,
    fontWeight: '700',
    color: colors.textSecondary,
  },
  filterChipTextSelected: {
    color: colors.primaryDark,
  },
  filterBadge: {
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: '#e5e7eb',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 4,
  },
  filterBadgeSelected: {
    backgroundColor: '#6ee7b7',
  },
  filterBadgeText: {
    fontSize: 10,
    fontWeight: '800',
    color: colors.textSecondary,
  },
  filterBadgeTextSelected: {
    color: colors.primaryDark,
  },

  /* ── Section headers ── */
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 22,
    marginBottom: 10,
    marginTop: 4,
  },
  sectionLabel: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    color: colors.textSecondary,
  },
  sectionLine: {
    flex: 1,
    height: 1,
    backgroundColor: '#e5e7eb',
  },

  /* ── Item card ── */
  itemCard: {
    marginHorizontal: 22,
    marginBottom: 10,
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderRadius: 20,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: '#e8f5ee',
    shadowColor: '#10b981',
    shadowOpacity: 0.07,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  itemIconWrap: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  itemIconWrapOn: {
    backgroundColor: colors.primaryLight,
  },
  itemIconWrapOff: {
    backgroundColor: colors.offRampLight,
  },
  itemCopy: {
    flex: 1,
    gap: 2,
  },
  itemTitle: {
    fontSize: 15,
    fontWeight: '800',
    color: colors.textFlat,
  },
  itemSubtitle: {
    fontSize: 12,
    color: colors.textSecondary,
    fontWeight: '500',
  },
  itemDate: {
    fontSize: 11,
    color: colors.textSecondary,
    marginTop: 2,
  },
  itemRight: {
    alignItems: 'flex-end',
    gap: 4,
  },
  itemAmount: {
    fontSize: 17,
    fontWeight: '800',
    letterSpacing: -0.3,
  },
  itemCurrency: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.textSecondary,
    marginTop: -2,
  },
  itemAmountPositive: {
    color: colors.primaryDark,
  },
  itemAmountNegative: {
    color: colors.textFlat,
  },

  /* ── Status pill ── */
  statusPill: {
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  statusPillText: {
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 0.1,
  },

  /* ── Empty state ── */
  emptyWrap: {
    marginHorizontal: 22,
    marginTop: 24,
    padding: 36,
    borderRadius: 24,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: '#e8f5ee',
    alignItems: 'center',
    gap: 12,
  },
  emptyIconCircle: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 4,
  },
  emptyTitle: {
    fontSize: 17,
    fontWeight: '800',
    color: colors.textFlat,
    textAlign: 'center',
  },
  emptyText: {
    fontSize: 14,
    lineHeight: 21,
    color: colors.textSecondary,
    textAlign: 'center',
    maxWidth: '85%',
  },
});
