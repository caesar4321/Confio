import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  Platform,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
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
  text: {
    primary: '#1F2937',
    secondary: '#6B7280',
  },
};

interface ConversionRecord {
  id: string;
  type: 'usdc_to_cusd' | 'cusd_to_usdc';
  fromAmount: string;
  toAmount: string;
  rate: string;
  fee: string;
  date: string;
  time: string;
  status: 'completed' | 'pending' | 'failed';
  hash: string;
}

// Mock conversion history data
const mockHistory: ConversionRecord[] = [
  {
    id: '1',
    type: 'usdc_to_cusd',
    fromAmount: '100.00',
    toAmount: '100.00',
    rate: '1 USDC = 1 cUSD',
    fee: '0.00',
    date: '2025-07-24',
    time: '14:30',
    status: 'completed',
    hash: '0xabc123def456...',
  },
  {
    id: '2',
    type: 'cusd_to_usdc',
    fromAmount: '250.00',
    toAmount: '250.00',
    rate: '1 cUSD = 1 USDC',
    fee: '0.00',
    date: '2025-07-23',
    time: '09:15',
    status: 'completed',
    hash: '0xdef789ghi012...',
  },
  {
    id: '3',
    type: 'usdc_to_cusd',
    fromAmount: '500.00',
    toAmount: '500.00',
    rate: '1 USDC = 1 cUSD',
    fee: '0.00',
    date: '2025-07-22',
    time: '16:45',
    status: 'completed',
    hash: '0xghi345jkl678...',
  },
  {
    id: '4',
    type: 'usdc_to_cusd',
    fromAmount: '75.50',
    toAmount: '75.50',
    rate: '1 USDC = 1 cUSD',
    fee: '0.00',
    date: '2025-07-20',
    time: '11:20',
    status: 'completed',
    hash: '0xjkl901mno234...',
  },
];

export const USDCHistoryScreen = () => {
  const navigation = useNavigation();

  const getIcon = (type: string) => {
    return type === 'usdc_to_cusd' ? 'arrow-down-circle' : 'arrow-up-circle';
  };

  const getIconColor = (type: string) => {
    return type === 'usdc_to_cusd' ? colors.primary : colors.accent;
  };

  const getTitle = (record: ConversionRecord) => {
    return record.type === 'usdc_to_cusd' 
      ? `USDC → cUSD`
      : `cUSD → USDC`;
  };

  const formatDate = (date: string) => {
    const momentDate = moment(date);
    if (momentDate.isSame(moment(), 'day')) {
      return 'Hoy';
    } else if (momentDate.isSame(moment().subtract(1, 'day'), 'day')) {
      return 'Ayer';
    } else {
      return momentDate.format('DD [de] MMMM');
    }
  };

  const renderItem = ({ item }: { item: ConversionRecord }) => (
    <TouchableOpacity style={styles.historyItem}>
      <View style={styles.itemHeader}>
        <View style={[styles.iconContainer, { backgroundColor: getIconColor(item.type) + '20' }]}>
          <Icon name={getIcon(item.type)} size={24} color={getIconColor(item.type)} />
        </View>
        <View style={styles.itemInfo}>
          <Text style={styles.itemTitle}>{getTitle(item)}</Text>
          <Text style={styles.itemDate}>{formatDate(item.date)} • {item.time}</Text>
        </View>
        <View style={styles.amountContainer}>
          <Text style={styles.fromAmount}>-{item.fromAmount}</Text>
          <Text style={styles.toAmount}>+{item.toAmount}</Text>
        </View>
      </View>
      
      <View style={styles.itemDetails}>
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Tasa</Text>
          <Text style={styles.detailValue}>{item.rate}</Text>
        </View>
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Comisión</Text>
          <Text style={styles.detailValue}>
            {item.fee === '0.00' ? 'Gratis' : `${item.fee} USDC`}
          </Text>
        </View>
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Estado</Text>
          <View style={styles.statusContainer}>
            <Text style={[styles.statusText, { color: item.status === 'completed' ? colors.primary : colors.text.secondary }]}>
              {item.status === 'completed' ? 'Completado' : 'Pendiente'}
            </Text>
            {item.status === 'completed' && (
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
        data={mockHistory}
        renderItem={renderItem}
        keyExtractor={item => item.id}
        contentContainerStyle={styles.listContent}
        ListEmptyComponent={EmptyState}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
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
});