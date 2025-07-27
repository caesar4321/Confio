import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  Platform,
  RefreshControl,
  ActivityIndicator,
  Vibration,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useQuery } from '@apollo/client';
import { GET_CONVERSIONS, GET_UNIFIED_USDC_TRANSACTIONS } from '../apollo/mutations';
import Icon from 'react-native-vector-icons/Feather';
import { Header } from '../navigation/Header';
import moment from 'moment';
import 'moment/locale/es';

moment.locale('es');

const colors = {
  primary: '#34D399',
  secondary: '#8B5CF6',
  accent: '#3B82F6',
  background: '#F9FAFB',
  mint: '#10b981', // mint color for free fees
  text: {
    primary: '#1F2937',
    secondary: '#6B7280',
  },
};

interface USDCTransactionRecord {
  transactionId: string;
  transactionType: 'deposit' | 'withdrawal' | 'conversion';
  actorType: 'user' | 'business';
  actorDisplayName: string;
  actorUser?: {
    id: string;
    username: string;
    firstName: string;
    lastName: string;
  };
  actorBusiness?: {
    id: string;
    name: string;
  };
  amount: string;
  currency: string;
  secondaryAmount?: string;
  secondaryCurrency?: string;
  exchangeRate?: string;
  networkFee: string;
  serviceFee: string;
  sourceAddress: string;
  destinationAddress: string;
  network: string;
  status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED';
  errorMessage?: string;
  createdAt: string;
  updatedAt: string;
  completedAt?: string;
  formattedTitle: string;
  iconName: string;
  iconColor: string;
}

const ITEMS_PER_PAGE = 20;

export const USDCHistoryScreen = () => {
  const navigation = useNavigation();
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [transactions, setTransactions] = useState<USDCTransactionRecord[]>([]);
  
  // Fetch unified USDC transaction history from GraphQL
  const { data, loading, refetch, fetchMore } = useQuery(GET_UNIFIED_USDC_TRANSACTIONS, {
    variables: { limit: ITEMS_PER_PAGE, offset: 0 },
    fetchPolicy: 'network-only', // Changed to force fresh data
    notifyOnNetworkStatusChange: true,
    onCompleted: (data) => {
      const newTransactions = data?.unifiedUsdcTransactions || [];
      console.log('USDC History loaded:', newTransactions.length, 'transactions');
      console.log('First 5:', newTransactions.slice(0, 5).map(t => ({
        type: t.transactionType,
        title: t.formattedTitle,
        amount: t.amount,
        currency: t.currency
      })));
      setTransactions(newTransactions);
      setHasMore(newTransactions.length === ITEMS_PER_PAGE);
    },
  });
  
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    if (Platform.OS === 'ios') {
      Vibration.vibrate(10);
    }
    
    try {
      const result = await refetch({ limit: ITEMS_PER_PAGE, offset: 0 });
      const newTransactions = result.data?.unifiedUsdcTransactions || [];
      setTransactions(newTransactions);
      setHasMore(newTransactions.length === ITEMS_PER_PAGE);
    } catch (error) {
      console.error('Error refreshing USDC transactions:', error);
    } finally {
      setRefreshing(false);
    }
  }, [refetch]);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore || refreshing) return;
    
    setLoadingMore(true);
    try {
      const result = await fetchMore({
        variables: {
          limit: ITEMS_PER_PAGE,
          offset: transactions.length,
        },
      });
      
      const moreTransactions = result.data?.unifiedUsdcTransactions || [];
      if (moreTransactions.length > 0) {
        setTransactions(prev => [...prev, ...moreTransactions]);
        setHasMore(moreTransactions.length === ITEMS_PER_PAGE);
      } else {
        setHasMore(false);
      }
    } catch (error) {
      console.error('Error loading more transactions:', error);
    } finally {
      setLoadingMore(false);
    }
  }, [fetchMore, transactions.length, loadingMore, hasMore, refreshing]);

  const getIcon = (record: USDCTransactionRecord) => {
    return record.iconName || 'circle';
  };

  const getIconColor = (record: USDCTransactionRecord) => {
    return record.iconColor || colors.text.secondary;
  };

  const getTitle = (record: USDCTransactionRecord) => {
    return record.formattedTitle || record.transactionType;
  };

  const formatDate = (dateString: string) => {
    const date = moment(dateString);
    const now = moment();
    
    if (date.isSame(now, 'day')) {
      return `Hoy, ${date.format('HH:mm')}`;
    } else if (date.isSame(now.clone().subtract(1, 'day'), 'day')) {
      return `Ayer, ${date.format('HH:mm')}`;
    } else if (date.isAfter(now.clone().subtract(6, 'days'))) {
      return date.format('dddd, HH:mm');
    } else {
      return date.format('D [de] MMMM, HH:mm');
    }
  };
  
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'COMPLETED':
        return colors.primary;
      case 'PENDING':
      case 'PROCESSING':
        return '#f59e0b';
      case 'FAILED':
        return '#ef4444';
      default:
        return colors.text.secondary;
    }
  };
  
  const getStatusText = (status: string) => {
    switch (status) {
      case 'COMPLETED':
        return 'Completado';
      case 'PENDING':
        return 'Pendiente';
      case 'PROCESSING':
        return 'Procesando';
      case 'FAILED':
        return 'Fallido';
      default:
        return status;
    }
  };

  const handleTransactionPress = (transaction: USDCTransactionRecord) => {
    // Navigate to detail screen with transaction data
    navigation.navigate('TransactionDetail', {
      transactionType: transaction.transactionType.toLowerCase(),
      transactionData: {
        type: transaction.transactionType.toLowerCase(),
        transactionId: transaction.transactionId,
        amount: transaction.amount,
        currency: transaction.currency,
        secondaryAmount: transaction.secondaryAmount,
        secondaryCurrency: transaction.secondaryCurrency,
        exchangeRate: transaction.exchangeRate,
        networkFee: transaction.networkFee,
        serviceFee: transaction.serviceFee,
        sourceAddress: transaction.sourceAddress,
        destinationAddress: transaction.destinationAddress,
        status: transaction.status,
        errorMessage: transaction.errorMessage,
        createdAt: transaction.createdAt,
        completedAt: transaction.completedAt,
        actorType: transaction.actorType,
        actorDisplayName: transaction.actorDisplayName,
        formattedTitle: transaction.formattedTitle,
        iconName: transaction.iconName,
        iconColor: transaction.iconColor,
        // Add any additional fields needed
        from: transaction.actorDisplayName,
        to: transaction.actorDisplayName,
        fromAddress: transaction.sourceAddress,
        toAddress: transaction.destinationAddress,
        date: moment(transaction.createdAt).format('YYYY-MM-DD'),
        time: moment(transaction.createdAt).format('HH:mm'),
        hash: transaction.transactionId,
        network: transaction.network || 'SUI',
      }
    });
  };

  const renderItem = ({ item }: { item: USDCTransactionRecord }) => (
    <TouchableOpacity style={styles.historyItem} onPress={() => handleTransactionPress(item)}>
      <View style={styles.itemHeader}>
        <View style={[styles.iconContainer, { backgroundColor: getIconColor(item) + '20' }]}>
          <Icon name={getIcon(item)} size={24} color={getIconColor(item)} />
        </View>
        <View style={styles.itemInfo}>
          <Text style={styles.itemTitle}>{getTitle(item)}</Text>
          <Text style={styles.itemDate}>{formatDate(item.createdAt)}</Text>
        </View>
        <View style={styles.amountContainer}>
          {item.transactionType.toLowerCase() === 'conversion' && item.secondaryAmount ? (
            <>
              <Text style={styles.fromAmount}>-{item.amount} {item.currency}</Text>
              <Text style={styles.toAmount}>+{item.secondaryAmount} {item.secondaryCurrency}</Text>
            </>
          ) : item.transactionType.toLowerCase() === 'deposit' ? (
            <Text style={styles.toAmount}>+{item.amount} {item.currency}</Text>
          ) : (
            <Text style={styles.fromAmount}>-{item.amount} {item.currency}</Text>
          )}
        </View>
      </View>
      
      <View style={styles.itemDetails}>
        {item.transactionType.toLowerCase() === 'conversion' && item.exchangeRate && (
          <View style={styles.detailRow}>
            <Text style={styles.detailLabel}>Tasa</Text>
            <Text style={styles.detailValue}>1 {item.currency} = {item.exchangeRate} {item.secondaryCurrency}</Text>
          </View>
        )}
        
        {item.transactionType.toLowerCase() === 'deposit' && item.sourceAddress && (
          <View style={styles.detailRow}>
            <Text style={styles.detailLabel}>Desde</Text>
            <Text style={styles.detailValue}>{item.sourceAddress.substring(0, 10)}...{item.sourceAddress.substring(item.sourceAddress.length - 6)}</Text>
          </View>
        )}
        
        {item.transactionType.toLowerCase() === 'withdrawal' && item.destinationAddress && (
          <View style={styles.detailRow}>
            <Text style={styles.detailLabel}>Hacia</Text>
            <Text style={styles.detailValue}>{item.destinationAddress.substring(0, 10)}...{item.destinationAddress.substring(item.destinationAddress.length - 6)}</Text>
          </View>
        )}
        
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Comisión</Text>
          {(parseFloat(item.serviceFee) + parseFloat(item.networkFee)) === 0 ? (
            <View style={styles.feeContainer}>
              <Text style={[styles.detailValue, { color: colors.mint }]}>Gratis</Text>
              <Text style={styles.feeNote}>• Cubierto por Confío</Text>
            </View>
          ) : (
            <Text style={styles.detailValue}>
              {(parseFloat(item.serviceFee) + parseFloat(item.networkFee)).toFixed(6)} {item.currency}
            </Text>
          )}
        </View>
        
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Estado</Text>
          <View style={styles.statusContainer}>
            <Text style={[styles.statusText, { color: getStatusColor(item.status) }]}>
              {getStatusText(item.status)}
            </Text>
            {item.status === 'COMPLETED' && (
              <View style={[styles.statusDot, { backgroundColor: colors.primary }]} />
            )}
          </View>
        </View>
      </View>
    </TouchableOpacity>
  );

  const EmptyState = () => (
    <View style={styles.emptyContainer}>
      <Icon name="clock" size={48} color="#E5E7EB" />
      <Text style={styles.emptyTitle}>Sin transacciones aún</Text>
      <Text style={styles.emptyText}>
        Tu historial de depósitos, retiros y conversiones de USDC aparecerá aquí
      </Text>
    </View>
  );

  const renderFooter = () => {
    if (!loadingMore) return null;
    
    return (
      <View style={styles.footerLoader}>
        <ActivityIndicator size="small" color={colors.primary} />
        <Text style={styles.footerText}>Cargando más transacciones...</Text>
      </View>
    );
  };

  if (loading && transactions.length === 0) {
    return (
      <View style={styles.container}>
        <Header
          navigation={navigation}
          title="Historial de USDC"
          backgroundColor={colors.accent}
          isLight={true}
          showBackButton={true}
        />
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={styles.loadingText}>Cargando transacciones...</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation}
        title="Historial de USDC"
        backgroundColor={colors.accent}
        isLight={true}
        showBackButton={true}
      />
      
      <FlatList
        data={transactions}
        renderItem={renderItem}
        keyExtractor={item => item.transactionId}
        contentContainerStyle={styles.listContent}
        ListEmptyComponent={EmptyState}
        ListFooterComponent={renderFooter}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        onEndReached={loadMore}
        onEndReachedThreshold={0.5}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.primary}
            colors={[colors.primary]}
          />
        }
        initialNumToRender={10}
        maxToRenderPerBatch={10}
        windowSize={21}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  listContent: {
    paddingVertical: 16,
    paddingHorizontal: 16,
  },
  historyItem: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    padding: 16,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.05,
        shadowRadius: 4,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  itemHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  iconContainer: {
    width: 44,
    height: 44,
    borderRadius: 22,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  itemInfo: {
    flex: 1,
  },
  itemTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: 4,
  },
  itemDate: {
    fontSize: 13,
    color: colors.text.secondary,
  },
  amountContainer: {
    alignItems: 'flex-end',
  },
  fromAmount: {
    fontSize: 14,
    color: colors.text.secondary,
    marginBottom: 2,
  },
  toAmount: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.primary,
  },
  itemDetails: {
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#F3F4F6',
  },
  detailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  detailLabel: {
    fontSize: 13,
    color: colors.text.secondary,
  },
  detailValue: {
    fontSize: 13,
    fontWeight: '500',
    color: colors.text.primary,
  },
  statusContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  statusText: {
    fontSize: 13,
    fontWeight: '500',
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    marginLeft: 6,
  },
  separator: {
    height: 12,
  },
  emptyContainer: {
    alignItems: 'center',
    paddingVertical: 60,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text.primary,
    marginTop: 16,
    marginBottom: 8,
  },
  emptyText: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    paddingHorizontal: 40,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    marginTop: 12,
    fontSize: 14,
    color: colors.text.secondary,
  },
  feeContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  feeNote: {
    fontSize: 12,
    color: colors.text.secondary,
    marginLeft: 4,
  },
  footerLoader: {
    paddingVertical: 20,
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'center',
  },
  footerText: {
    marginLeft: 8,
    fontSize: 14,
    color: colors.text.secondary,
  },
});