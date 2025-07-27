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
import { GET_CONVERSIONS } from '../apollo/mutations';
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

interface ConversionRecord {
  id: string;
  conversionId: string;
  conversionType: 'usdc_to_cusd' | 'cusd_to_usdc';
  fromAmount: string;
  toAmount: string;
  exchangeRate: string;
  feeAmount: string;
  fromToken: string;
  toToken: string;
  status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED';
  createdAt: string;
  completedAt?: string;
  actorType: 'user' | 'business';
  actorDisplayName: string;
  actorUser?: {
    id: string;
    username: string;
    email: string;
  };
  actorBusiness?: {
    id: string;
    name: string;
  };
}

export const USDCHistoryScreen = () => {
  const navigation = useNavigation();
  const [refreshing, setRefreshing] = useState(false);
  
  // Fetch conversion history from GraphQL
  const { data, loading, refetch } = useQuery(GET_CONVERSIONS, {
    variables: { limit: 50 },
    fetchPolicy: 'cache-and-network',
  });
  
  const conversions: ConversionRecord[] = data?.conversions || [];
  
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    if (Platform.OS === 'ios') {
      Vibration.vibrate(10);
    }
    
    try {
      await refetch();
    } catch (error) {
      console.error('Error refreshing conversions:', error);
    } finally {
      setRefreshing(false);
    }
  }, [refetch]);

  const getIcon = (type: string) => {
    return type === 'usdc_to_cusd' ? 'arrow-down-circle' : 'arrow-up-circle';
  };

  const getIconColor = (type: string) => {
    return type === 'usdc_to_cusd' ? colors.primary : colors.accent;
  };

  const getTitle = (record: ConversionRecord) => {
    return record.conversionType === 'usdc_to_cusd' 
      ? `USDC → cUSD`
      : `cUSD → USDC`;
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

  const renderItem = ({ item }: { item: ConversionRecord }) => (
    <TouchableOpacity style={styles.historyItem}>
      <View style={styles.itemHeader}>
        <View style={[styles.iconContainer, { backgroundColor: getIconColor(item.conversionType) + '20' }]}>
          <Icon name={getIcon(item.conversionType)} size={24} color={getIconColor(item.conversionType)} />
        </View>
        <View style={styles.itemInfo}>
          <Text style={styles.itemTitle}>{getTitle(item)}</Text>
          <Text style={styles.itemDate}>{formatDate(item.createdAt)}</Text>
        </View>
        <View style={styles.amountContainer}>
          <Text style={styles.fromAmount}>-{item.fromAmount} {item.fromToken}</Text>
          <Text style={styles.toAmount}>+{item.toAmount} {item.toToken}</Text>
        </View>
      </View>
      
      <View style={styles.itemDetails}>
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Tasa</Text>
          <Text style={styles.detailValue}>1 {item.fromToken} = {item.exchangeRate} {item.toToken}</Text>
        </View>
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Comisión</Text>
          {item.feeAmount === '0' || item.feeAmount === '0.000000' ? (
            <View style={styles.feeContainer}>
              <Text style={[styles.detailValue, { color: colors.mint }]}>Gratis</Text>
              <Text style={styles.feeNote}>• Cubierto por Confío</Text>
            </View>
          ) : (
            <Text style={styles.detailValue}>{item.feeAmount} {item.fromToken}</Text>
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
      <Text style={styles.emptyTitle}>Sin conversiones aún</Text>
      <Text style={styles.emptyText}>
        Tu historial de conversiones entre USDC y cUSD aparecerá aquí
      </Text>
    </View>
  );

  if (loading && conversions.length === 0) {
    return (
      <View style={styles.container}>
        <Header
          navigation={navigation}
          title="Historial de Conversiones"
          backgroundColor={colors.accent}
          isLight={true}
          showBackButton={true}
        />
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={styles.loadingText}>Cargando conversiones...</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation}
        title="Historial de Conversiones"
        backgroundColor={colors.accent}
        isLight={true}
        showBackButton={true}
      />
      
      <FlatList
        data={conversions}
        renderItem={renderItem}
        keyExtractor={item => item.id}
        contentContainerStyle={styles.listContent}
        ListEmptyComponent={EmptyState}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.primary}
            colors={[colors.primary]}
          />
        }
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
});