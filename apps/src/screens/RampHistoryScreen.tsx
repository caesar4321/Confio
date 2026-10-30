import { unifiedDetailRoute } from '../utils/transactionRoutes';
import React, { useCallback, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  SafeAreaView,
  StatusBar,
  StyleSheet,
  TouchableOpacity,
  View,
} from 'react-native';
import { Text } from '../components/common/AppText';
import { RouteProp, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import moment from 'moment';
import 'moment/locale/es';

import { GET_CURRENT_ACCOUNT_TRANSACTIONS } from '../apollo/queries';
import { LOCAL_DEPOSITS_WITHOUT_TRANSFER } from '../services/localMoney';
import { useAccount } from '../contexts/AccountContext';
import { MainStackParamList } from '../types/navigation';
import { RampHero } from '../components/ramps/RampHero';
import { colors } from '../config/theme';
import { formatDecimal } from '../utils/numberLocale';

moment.locale('es');

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'RampHistory'>;
type RouteProps = RouteProp<MainStackParamList, 'RampHistory'>;
type RampFilter = 'all' | 'on_ramp' | 'off_ramp';

type ListRow =
  | { kind: 'section'; label: string; key: string }
  | { kind: 'item'; data: any; key: string };

const PAGE_SIZE = 50;
// Every operation that moves money in or out of Confío: one Historial.
const HISTORY_TYPES = ['ramp', 'local_transfer'];

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
  if (normalized === 'CUSD' || normalized === 'CUSD_BSC') return 'cUSD';
  if (normalized === 'CUSD_PLUS') return 'cUSD+';
  if (normalized === 'USDC POLYGON' || normalized === 'USDC SOLANA' || normalized === 'USDC-A') return 'cUSD';
  return tokenType || 'cUSD';
};

const formatAmount = (raw: string | number, currency?: string): string => {
  const num = parseFloat(String(raw).replace(/[+-]/g, ''));
  if (isNaN(num)) return String(raw);
  const isCrypto = !currency || ['CUSD', 'CUSD+', 'CUSD_BSC', 'CUSD_PLUS', 'USDC', 'USDT', 'ALGO', 'BNB'].includes(currency.toUpperCase());
  if (isCrypto) {
    return formatDecimal(num, { decimals: 4, minDecimals: 2 });
  }
  return formatDecimal(num);
};

const formatPrimaryRampAmount = (item: any, isOffRamp: boolean): { amount: string; currency: string } => {
  const fiatAmount = String(item.rampFiatAmount || '').trim();
  const fiatCurrency = String(item.rampFiatCurrency || '').trim();
  if (!isOffRamp && fiatAmount && fiatCurrency && fiatAmount !== '0') {
    return { amount: formatAmount(fiatAmount, fiatCurrency), currency: fiatCurrency };
  }
  const rawAmount = String(item.displayAmount || item.amount || '').trim();
  if (!rawAmount || rawAmount === '--') return { amount: '--', currency: getCurrencyLabel(item.tokenType) };
  const currency = getCurrencyLabel(item.tokenType);
  return { amount: formatAmount(rawAmount, currency), currency };
};

/** In or out of Confío, whichever rail carried it. */
const directionOf = (tx: any): 'on_ramp' | 'off_ramp' => {
  const kind = (tx.transactionType || '').toLowerCase();
  if (kind === 'local_deposit') return 'on_ramp';
  if (kind === 'local_transfer') return (tx.senderType || '').toLowerCase() === 'external' ? 'on_ramp' : 'off_ramp';
  return (tx.rampDirection || '').toLowerCase() === 'off_ramp' ? 'off_ramp' : 'on_ramp';
};

/** A deposit with no transfer behind it: what happened to that money. */
const depositStatus = (deposit: any): {
  label: string; tone: 'success' | 'info' | 'warning' | 'error' | 'neutral'; credited: boolean;
} => {
  switch (deposit.automaticStatus) {
    case 'returned': return { label: 'Devuelto', tone: 'neutral', credited: false };
    case 'returning': return { label: 'Devolviendo', tone: 'info', credited: false };
    case 'return_failed': return { label: 'En revisión', tone: 'warning', credited: false };
    case 'awaiting_face': return { label: 'Confirma tu Face', tone: 'warning', credited: false };
    default:
      return deposit.held
        ? { label: 'En revisión', tone: 'warning', credited: false }
        : { label: 'En proceso', tone: 'info', credited: false };
  }
};

/* ─── component ─── */

export const RampHistoryScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const route = useRoute<RouteProps>();
  const { activeAccount } = useAccount();
  const [selectedFilter, setSelectedFilter] = useState<RampFilter>(route.params?.initialFilter || 'all');
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);

  const { data, loading, refetch, fetchMore } = useQuery(GET_CURRENT_ACCOUNT_TRANSACTIONS, {
    // This is an operation-history screen, not an asset ledger. Fetch every
    // rail while filtering by operation on the server, before pagination, so
    // Algorand cUSD/USDC/ALGO,
    // BSC cUSD/cUSD+/USDT/BNB, and future ramp assets cannot disappear just
    // because a separate token allowlist has not been updated yet.
    variables: { limit: PAGE_SIZE, offset: 0, transactionTypes: HISTORY_TYPES },
    skip: !activeAccount,
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
  });

  // Deposits that never became a transaction (returned, in review, waiting
  // for Confío Face). An error here only loses these rows.
  const { data: depositsData, error: depositsError, refetch: refetchDeposits } = useQuery(LOCAL_DEPOSITS_WITHOUT_TRANSFER, {
    skip: !activeAccount,
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
  });

  const onRefresh = useCallback(async () => {
    setHasMore(true);
    await refetch({
      limit: PAGE_SIZE,
      offset: 0,
      transactionTypes: HISTORY_TYPES,
    });
    await refetchDeposits().catch(() => {});
  }, [refetch, refetchDeposits]);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore || loading) return;

    const currentTransactions = data?.currentAccountTransactions || [];
    setLoadingMore(true);
    try {
      const result = await fetchMore({
        variables: {
          limit: PAGE_SIZE,
          offset: currentTransactions.length,
          transactionTypes: HISTORY_TYPES,
        },
        updateQuery: (previous, { fetchMoreResult }) => {
          const incoming = fetchMoreResult?.currentAccountTransactions || [];
          if (!incoming.length) return previous;
          const existing = previous?.currentAccountTransactions || [];
          const knownIds = new Set(existing.map((transaction: any) => transaction.id));
          return {
            ...previous,
            currentAccountTransactions: [
              ...existing,
              ...incoming.filter((transaction: any) => !knownIds.has(transaction.id)),
            ],
          };
        },
      });
      const incoming = result.data?.currentAccountTransactions || [];
      setHasMore(incoming.length === PAGE_SIZE);
    } finally {
      setLoadingMore(false);
    }
  }, [data?.currentAccountTransactions, fetchMore, hasMore, loading, loadingMore]);

  const history = useMemo(() => {
    const transactions = (data?.currentAccountTransactions || [])
      .filter((tx: any) => HISTORY_TYPES.includes((tx.transactionType || '').toLowerCase()));
    const deposits = (depositsData?.localDepositsWithoutTransfer || []).map((deposit: any) => ({
      ...deposit, id: `deposit-${deposit.internalId}`, transactionType: 'local_deposit', createdAt: deposit.occurredAt,
    }));
    return [...transactions, ...deposits]
      .sort((a: any, b: any) => moment.utc(b.createdAt).valueOf() - moment.utc(a.createdAt).valueOf());
  }, [data?.currentAccountTransactions, depositsData?.localDepositsWithoutTransfer]);

  const rampTransactions = useMemo(() => history.filter((tx: any) => (
    selectedFilter === 'all' || directionOf(tx) === selectedFilter
  )), [history, selectedFilter]);

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
  const counts = useMemo(() => ({
    all: history.length,
    on_ramp: history.filter((tx: any) => directionOf(tx) === 'on_ramp').length,
    off_ramp: history.filter((tx: any) => directionOf(tx) === 'off_ramp').length,
  }), [history]);

  const title = selectedFilter === 'on_ramp' ? 'Lo que recibiste'
    : selectedFilter === 'off_ramp' ? 'Lo que enviaste' : 'Tu historial';
  const subtitle = 'Recargas, retiros y transferencias locales, con su estado y monto.';

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
    const kind = (item.transactionType || '').toLowerCase();
    const isDeposit = kind === 'local_deposit';
    const isLocal = kind === 'local_transfer';
    const isOffRamp = directionOf(item) === 'off_ramp';
    const depositState = isDeposit ? depositStatus(item) : null;
    const statusTone = depositState?.tone || getStatusTone(item.rampStatus || item.status);
    const statusLabel = depositState?.label || getStatusLabel(item.rampStatus || item.status);
    const providerLabel = isDeposit ? (item.sender?.name || 'Remitente no informado')
      : isLocal ? ((isOffRamp ? item.counterpartyDisplayName : item.senderDisplayName) || item.description || 'Cuenta local')
        : (item.rampProvider || item.displayCounterparty || 'Proveedor');
    const titleText = isDeposit || (isLocal && !isOffRamp) ? 'Ingreso' : isLocal ? 'Envío' : isOffRamp ? 'Retiro' : 'Recarga';
    const primaryAmount = isDeposit
      ? { amount: formatAmount(item.amount, item.asset), currency: item.asset }
      : formatPrimaryRampAmount(item, isOffRamp);
    // Not credited yet, or sent back: never a "+".
    const amountPending = isLocal && item.localTransferPendingAmount;
    const amountSign = depositState?.credited === false ? '' : isOffRamp ? '−' : '+';

    const statusColors = {
      success: { bg: colors.primaryLight, text: colors.primaryDark },
      info: { bg: '#dbeafe', text: '#1d4ed8' },
      warning: { bg: colors.warningLight, text: colors.warning.text },
      error: { bg: colors.dangerLight, text: colors.danger },
      neutral: { bg: colors.neutralDark, text: colors.textSecondary },
    }[statusTone];

    return (
      <TouchableOpacity
        style={styles.itemCard}
        disabled={isDeposit && item.automaticStatus !== 'awaiting_face'}
        onPress={() => {
          if (isDeposit) {
            navigation.navigate('PendingIncoming');
            return;
          }
          if (isLocal) {
            navigation.navigate('LocalTransferStatus', { journeyId: item.localTransferId });
            return;
          }
          navigation.navigate('TransactionDetail', unifiedDetailRoute({
            transactionType: 'ramp',
            transactionData: {
              ...item,
              type: 'ramp',
              walletAmount: item.netAmount || item.amount,
              walletCurrency: item.tokenType,
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
          }));
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
            {amountPending ? 'Pendiente' : `${amountSign}${primaryAmount.amount}`}
          </Text>
          {amountPending ? null : <Text style={styles.itemCurrency}>{primaryAmount.currency}</Text>}
          <View style={[styles.statusPill, { backgroundColor: statusColors.bg }]}>
            <Text style={[styles.statusPillText, { color: statusColors.text }]}>
              {statusLabel}
            </Text>
          </View>
        </View>
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
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
            refreshing={loading && !loadingMore}
            onRefresh={() => void onRefresh()}
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
            />
            <View style={styles.filtersRow}>
              {renderFilterChip('all', 'Todo')}
              {renderFilterChip('on_ramp', 'Recibido')}
              {renderFilterChip('off_ramp', 'Enviado')}
            </View>
            {depositsError ? (
              // A failed request is not "no deposits".
              <TouchableOpacity style={styles.depositsError} onPress={() => { refetchDeposits().catch(() => {}); }}
                accessibilityRole="button">
                <Text style={styles.depositsErrorText}>No pudimos cargar algunos depósitos. Toca para reintentar.</Text>
              </TouchableOpacity>
            ) : null}
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
                  Cuando recibas o envíes dinero desde un banco, aparecerá aquí con su estado.
                </Text>
              </>
            )}
          </View>
        )}
        ListFooterComponent={loadingMore ? (
          <View style={styles.footerLoader}>
            <ActivityIndicator color={colors.primaryDark} />
          </View>
        ) : null}
        onEndReached={() => void loadMore()}
        onEndReachedThreshold={0.4}
        renderItem={renderRow}
      />
    </SafeAreaView>
  );
};

export default RampHistoryScreen;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.heroField,
  },
  list: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    paddingBottom: 56,
  },
  footerLoader: {
    paddingVertical: 20,
  },

  depositsError: { marginHorizontal: 22, marginBottom: 12, paddingVertical: 8 },
  depositsErrorText: { fontSize: 13, color: colors.warning.text },

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
    borderColor: colors.primaryLight,
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
    backgroundColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 4,
  },
  filterBadgeSelected: {
    backgroundColor: colors.primary,
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
    backgroundColor: colors.border,
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
    borderColor: colors.border,
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
    borderColor: colors.border,
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
