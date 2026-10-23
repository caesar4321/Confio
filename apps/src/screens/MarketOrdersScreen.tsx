import React, { useCallback, useRef, useState } from 'react';
import { useNumberLocale } from '../contexts/NumberLocaleProvider';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useQuery } from '@apollo/client';
import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import { GET_MY_MARKET_ORDERS, orderStatusLabel } from '../services/comprar';
import { formatUsd } from '../utils/comprarFormat';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ComprarFrame, KitButton, ProductThumb, StatusPill } from '../components/comprar/kit';

const PAGE_SIZE = 20;

/** Mis compras / Mis ventas. Sales show only paid orders (never drafts). */
export const MarketOrdersScreen = () => {
  useNumberLocale(); // amounts follow the user's number format, live
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
  const insets = useSafeAreaInsets();
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
    <ComprarFrame title={role === 'buyer' ? 'Mis compras' : 'Mis ventas'}>
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
        contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: 16 + insets.bottom }}
        initialNumToRender={PAGE_SIZE}
        maxToRenderPerBatch={10}
        windowSize={21}
        onEndReachedThreshold={0.5}
        onEndReached={() => { void loadMore(); }}
        refreshControl={<RefreshControl refreshing={networkStatus === 4} onRefresh={() => { setHasMore(true); void refetch(); }} />}
        ListEmptyComponent={loading ? <ActivityIndicator style={{ marginTop: 40 }} color={colors.primaryDark} /> : (
          <View style={styles.emptyBox}>
            <View style={styles.emptyIcon}>
              <Icon name={role === 'buyer' ? 'shopping-bag' : 'inbox'} size={26} color={colors.primaryDeep} />
            </View>
            <Text style={styles.emptyTitle}>{role === 'buyer' ? 'Aún no compraste nada' : 'Aún no tienes ventas'}</Text>
            <Text style={styles.empty}>
              {role === 'buyer'
                ? 'Tus pedidos aparecerán aquí, con su estado hasta que lleguen.'
                : 'Cuando alguien compre en tu tienda, el pedido aparecerá aquí.'}
            </Text>
            {role === 'buyer' ? (
              <KitButton label="Explorar productos" variant="secondary"
                onPress={() => navigation.navigate('BottomTabs', { screen: 'Comprar' })} />
            ) : null}
          </View>
        )}
        renderItem={({ item }: any) => (
          <Pressable style={({ pressed }) => [styles.row, pressed && { opacity: 0.85 }]}
            onPress={() => navigation.navigate('MarketOrder', { orderId: item.id })}>
            <ProductThumb uri={item.productPhotoUrl} size={60} />
            <View style={{ flex: 1, gap: 4 }}>
              <View style={styles.rowTop}>
                <Text style={styles.title} numberOfLines={1}>{item.productTitle}</Text>
                <Text style={styles.amount}>{formatUsd(item.amountUsd)}</Text>
              </View>
              <Text style={styles.meta} numberOfLines={1}>
                {item.quantity > 1 ? `${item.quantity} unidades · ` : ''}
                {role === 'buyer' ? item.store?.name : item.buyerDisplayName}
                {item.createdAt ? ` · ${new Date(item.createdAt).toLocaleDateString('es-BO', { day: 'numeric', month: 'short' })}` : ''}
              </Text>
              <StatusPill status={item.status} label={orderStatusLabel(item.status, item.role)} />
            </View>
          </Pressable>
        )}
      />
    </ComprarFrame>
  );
};

export default MarketOrdersScreen;

const styles = StyleSheet.create({
  tabs: { flexDirection: 'row', margin: 16, marginBottom: 0, backgroundColor: colors.neutralDark, borderRadius: 999, padding: 3 },
  tab: { flex: 1, alignItems: 'center', paddingVertical: 8, borderRadius: 999 },
  tabOn: { backgroundColor: colors.white },
  tabText: { fontSize: 14, fontWeight: '600', color: colors.text.secondary },
  tabTextOn: { color: colors.textFlat },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: colors.white, borderRadius: 16, padding: 12, borderWidth: 1, borderColor: colors.borderLight },
  rowTop: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { flex: 1, fontSize: 15, fontWeight: '600', color: colors.textFlat },
  amount: { fontSize: 15, fontWeight: '700', color: colors.textFlat },
  meta: { fontSize: 13, color: colors.text.secondary },
  emptyBox: { alignItems: 'center', gap: 10, paddingHorizontal: 24, marginTop: 48 },
  emptyIcon: { width: 56, height: 56, borderRadius: 28, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center' },
  emptyTitle: { fontSize: 17, fontWeight: '700', color: colors.textFlat },
  empty: { textAlign: 'center', color: colors.text.secondary, lineHeight: 20 },
});
