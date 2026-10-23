import React, { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Image, Pressable, RefreshControl, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useQuery } from '@apollo/client';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { GET_MY_MARKET_ORDERS, orderStatusLabel } from '../services/comprar';
import { formatLocalPrice } from '../utils/comprarFormat';

const PAGE_SIZE = 20;

/** Mis compras / Mis ventas. Sales show only paid orders (never drafts). */
export const MarketOrdersScreen = () => {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const [role, setRole] = useState<'buyer' | 'merchant'>(route.params?.role ?? 'buyer');
  const { data, loading, refetch, fetchMore, networkStatus } = useQuery(GET_MY_MARKET_ORDERS, {
    variables: { role, limit: PAGE_SIZE, offset: 0 },
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
  });
  const orders = data?.myMarketOrders || [];
  const [hasMore, setHasMore] = useState(true);
  const busy = useRef(false);

  const loadMore = useCallback(async () => {
    if (busy.current || !hasMore || orders.length < PAGE_SIZE) return;
    busy.current = true;
    try {
      const { data: next } = await fetchMore({
        variables: { role, limit: PAGE_SIZE, offset: orders.length },
        updateQuery: (prev: any, { fetchMoreResult }: any) => ({
          myMarketOrders: [...(prev?.myMarketOrders || []), ...(fetchMoreResult?.myMarketOrders || [])],
        }),
      });
      if ((next?.myMarketOrders || []).length < PAGE_SIZE) setHasMore(false);
    } catch {
      // keep the list
    } finally {
      busy.current = false;
    }
  }, [fetchMore, hasMore, orders.length, role]);

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <Header navigation={navigation} isHomeScreen={false} title={role === 'buyer' ? 'Mis compras' : 'Mis ventas'}
        backgroundColor="#fff" showBackButton isLight={false} unreadNotifications={0} currentAccountAvatar="U" />
      <View style={styles.tabs}>
        {(['buyer', 'merchant'] as const).map((r) => (
          <Pressable key={r} style={[styles.tab, role === r && styles.tabOn]} onPress={() => { setHasMore(true); setRole(r); }}>
            <Text style={[styles.tabText, role === r && styles.tabTextOn]}>{r === 'buyer' ? 'Compras' : 'Ventas'}</Text>
          </Pressable>
        ))}
      </View>
      <FlatList
        data={orders}
        keyExtractor={(o: any) => o.id}
        contentContainerStyle={{ padding: 16, gap: 10 }}
        initialNumToRender={PAGE_SIZE}
        maxToRenderPerBatch={10}
        windowSize={21}
        onEndReachedThreshold={0.5}
        onEndReached={() => { void loadMore(); }}
        refreshControl={<RefreshControl refreshing={networkStatus === 4} onRefresh={() => { setHasMore(true); void refetch(); }} />}
        ListEmptyComponent={loading ? <ActivityIndicator style={{ marginTop: 40 }} color={colors.primaryDark} /> : (
          <Text style={styles.empty}>{role === 'buyer' ? 'Aún no compraste nada.' : 'Aún no tienes ventas.'}</Text>
        )}
        renderItem={({ item }: any) => (
          <Pressable style={styles.row} onPress={() => navigation.navigate('MarketOrder', { orderId: item.id })}>
            {item.productPhotoUrl
              ? <Image source={{ uri: item.productPhotoUrl }} style={styles.thumb} />
              : <View style={[styles.thumb, styles.thumbEmpty]}><Icon name="package" size={18} color={colors.text.light} /></View>}
            <View style={{ flex: 1 }}>
              <Text style={styles.title} numberOfLines={1}>{item.quantity} × {item.productTitle}</Text>
              <Text style={styles.meta} numberOfLines={1}>
                {role === 'buyer' ? item.store?.name : item.buyerDisplayName} · {formatLocalPrice(item.subtotalLocal, item.currencyCode)}
              </Text>
              <Text style={[styles.status, item.availableActions?.length && styles.statusAction]}>
                {orderStatusLabel(item.status, item.role)}
              </Text>
            </View>
            <Icon name="chevron-right" size={18} color={colors.text.light} />
          </Pressable>
        )}
      />
    </SafeAreaView>
  );
};

export default MarketOrdersScreen;

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.neutral },
  tabs: { flexDirection: 'row', margin: 16, marginBottom: 0, backgroundColor: colors.neutralDark, borderRadius: 999, padding: 3 },
  tab: { flex: 1, alignItems: 'center', paddingVertical: 8, borderRadius: 999 },
  tabOn: { backgroundColor: colors.white },
  tabText: { fontSize: 14, fontWeight: '600', color: colors.text.secondary },
  tabTextOn: { color: colors.textFlat },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: colors.white, borderRadius: 14, padding: 12 },
  thumb: { width: 52, height: 52, borderRadius: 10, backgroundColor: colors.neutralDark },
  thumbEmpty: { alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 15, fontWeight: '600', color: colors.textFlat },
  meta: { fontSize: 13, color: colors.text.secondary },
  status: { fontSize: 13, color: colors.text.secondary, marginTop: 2 },
  statusAction: { color: colors.primaryDark, fontWeight: '600' },
  empty: { textAlign: 'center', color: colors.text.secondary, marginTop: 40 },
});
