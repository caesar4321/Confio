import React, { useMemo, useCallback } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, FlatList, RefreshControl, SafeAreaView } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';
import { GET_PAYROLL_RUNS } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';

type RouteProps = RouteProp<MainStackParamList, 'PayrollHistory'>;
type NavigationProps = NativeStackNavigationProp<MainStackParamList, 'PayrollHistory'>;

const statusLabel = (s: string) => {
  const key = (s || '').toLowerCase();
  switch (key) {
    case 'pending': return 'Pendiente';
    case 'prepared': return 'Preparado';
    case 'submitted': return 'Enviado';
    case 'confirmed': return 'Confirmado';
    case 'failed': return 'Fallido';
    case 'cancelled': return 'Cancelado';
    case 'ready': return 'Listo';
    case 'partial': return 'Parcial';
    case 'completed': return 'Completado';
    default: return s || '—';
  }
};

const PayrollHistoryScreen = () => {
  const navigation = useNavigation<NavigationProps>();
  const route = useRoute<RouteProps>();
  const { accountId, displayName, username } = route.params;

  const { data, loading, refetch } = useQuery(GET_PAYROLL_RUNS, {
    fetchPolicy: 'cache-and-network',
  });

  const history = useMemo(() => {
    if (!data?.payrollRuns || !accountId) return [];
    return data.payrollRuns
      .flatMap((run: any) => {
        const matchItems = (run.items || []).filter((it: any) => it.recipientAccount?.id === accountId);
        return matchItems.map((it: any) => ({
          id: it.internalId,
          amount: it.netAmount,
          token: run.tokenType || 'cUSD',
          status: it.status,
          runStatus: run.status,
          when: run.scheduledAt || run.createdAt,
        }));
      })
      .sort((a: any, b: any) => (new Date(b.when || '').getTime() - new Date(a.when || '').getTime()));
  }, [data, accountId]);

  const renderItem = useCallback(({ item }: any) => {
    return (
      <View style={styles.row}>
        <View style={{ flex: 1 }}>
          <Text style={styles.amount}>{item.token || 'cUSD'} {item.amount}</Text>
          <Text style={styles.date}>{new Date(item.when).toLocaleDateString()}</Text>
        </View>
        <View style={styles.badges}>
          <View style={[styles.badge, styles.badgeSecondary]}>
            <Text style={styles.badgeText}>{statusLabel(item.runStatus)}</Text>
          </View>
          <View style={[styles.badge, styles.badgeMuted]}>
            <Text style={styles.badgeText}>{statusLabel(item.status)}</Text>
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
            <Text style={styles.title}>Historial de nómina</Text>
            <Text style={styles.subtitle}>{displayName || username ? `${displayName || ''} @${username || ''}` : ''}</Text>
          </View>
          <View style={{ width: 32 }} />
        </View>

        <FlatList
          data={history}
          keyExtractor={(item) => item.id}
          renderItem={renderItem}
          contentContainerStyle={styles.listContent}
          ItemSeparatorComponent={() => <View style={{ height: 10 }} />}
          ListEmptyComponent={
            <View style={styles.empty}>
              <Icon name="clipboard" size={32} color="#9ca3af" />
              <Text style={styles.emptyText}>Sin pagos para este destinatario.</Text>
            </View>
          }
          refreshControl={
            <RefreshControl refreshing={loading} onRefresh={() => refetch()} />
          }
        />
      </View>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#f8fafc' },
  container: { flex: 1, backgroundColor: '#f8fafc' },
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
  backButton: { marginRight: 12, padding: 6 },
  title: { fontSize: 18, fontWeight: '700', color: '#111827' },
  subtitle: { fontSize: 13, color: '#6b7280', marginTop: 2 },
  listContent: { padding: 16, gap: 12 },
  row: {
    backgroundColor: '#fff',
    borderRadius: 14,
    padding: 14,
    borderWidth: 1,
    borderColor: '#e0e7ff',
    borderLeftWidth: 4,
    borderLeftColor: '#10b981',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    shadowColor: '#0f172a',
    shadowOpacity: 0.05,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 3 },
  },
  amount: { fontSize: 15, fontWeight: '700', color: '#111827' },
  date: { fontSize: 12, color: '#6b7280', marginTop: 2 },
  badges: { flexDirection: 'row', gap: 6 },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 10,
  },
  badgeText: { fontSize: 11, fontWeight: '700', color: '#111827' },
  badgeSecondary: { backgroundColor: '#e0f2fe' },
  badgeMuted: { backgroundColor: '#f8fafc' },
  empty: { alignItems: 'center', padding: 32, gap: 8 },
  emptyText: { fontSize: 14, color: '#6b7280' },
});

export default PayrollHistoryScreen;
