import React, { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Image, Pressable, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { gql, useQuery } from '@apollo/client';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { GET_MARKETPLACE_PRODUCTS } from '../services/comprar';
import { formatLocalPrice } from '../utils/comprarFormat';

const GET_STORE = gql`
  query MarketplaceStore($id: ID!) {
    marketplaceStore(id: $id) {
      id name description countryCode city shipsOutsideCity isOpen avgRating ratingCount completedOrders
    }
  }
`;

const PAGE_SIZE = 20;

export const MarketStoreScreen = () => {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const storeId = route.params?.storeId as string;
  const { data: storeData } = useQuery(GET_STORE, { variables: { id: storeId } });
  const store = storeData?.marketplaceStore;
  const variables = { countryCode: store?.countryCode || '', storeId, limit: PAGE_SIZE, offset: 0 };
  const { data, loading, fetchMore } = useQuery(GET_MARKETPLACE_PRODUCTS, { variables, skip: !store });
  const products = data?.marketplaceProducts || [];
  const [hasMore, setHasMore] = useState(true);
  const busy = useRef(false);
  const loadMore = useCallback(async () => {
    if (busy.current || !hasMore || products.length < PAGE_SIZE) return;
    busy.current = true;
    try {
      const { data: next } = await fetchMore({
        variables: { ...variables, offset: products.length },
        updateQuery: (prev: any, { fetchMoreResult }: any) => ({
          marketplaceProducts: [...(prev?.marketplaceProducts || []), ...(fetchMoreResult?.marketplaceProducts || [])],
        }),
      });
      if ((next?.marketplaceProducts || []).length < PAGE_SIZE) setHasMore(false);
    } catch {
      // keep the list
    } finally {
      busy.current = false;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchMore, hasMore, products.length, store?.countryCode, storeId]);

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <Header navigation={navigation} isHomeScreen={false} title={store?.name || 'Tienda'} backgroundColor="#fff"
        showBackButton isLight={false} unreadNotifications={0} currentAccountAvatar="U" />
      <FlatList
        data={products}
        keyExtractor={(p: any) => String(p.id)}
        numColumns={2}
        columnWrapperStyle={{ gap: 12, paddingHorizontal: 16 }}
        initialNumToRender={PAGE_SIZE}
        maxToRenderPerBatch={10}
        windowSize={21}
        onEndReachedThreshold={0.5}
        onEndReached={() => { void loadMore(); }}
        ListHeaderComponent={store ? (
          <View style={styles.header}>
            <Text style={styles.name}>{store.name}</Text>
            <Text style={styles.meta}>
              {store.city} · {store.completedOrders} ventas
              {store.ratingCount ? ` · ★ ${Number(store.avgRating).toFixed(1)} (${store.ratingCount})` : ''}
            </Text>
            <View style={styles.verified}>
              <Icon name="check-circle" size={14} color={colors.primaryDark} />
              <Text style={styles.verifiedText}>Vendedor con identidad verificada</Text>
            </View>
            {store.description ? <Text style={styles.description}>{store.description}</Text> : null}
            <Text style={styles.meta}>
              {store.shipsOutsideCity ? `Entrega en ${store.city} y otras ciudades` : `Entrega solo en ${store.city}`}
            </Text>
          </View>
        ) : null}
        ListEmptyComponent={loading || !store ? <ActivityIndicator style={{ marginTop: 32 }} color={colors.primaryDark} />
          : <Text style={styles.empty}>Esta tienda aún no tiene productos.</Text>}
        renderItem={({ item }: any) => (
          <Pressable style={styles.card} onPress={() => navigation.navigate('MarketProduct', { productId: String(item.id) })}>
            {item.photoUrls?.[0] ? <Image source={{ uri: item.photoUrls[0] }} style={styles.image} />
              : <View style={[styles.image, styles.imageEmpty]}><Icon name="image" size={22} color={colors.text.light} /></View>}
            <View style={{ padding: 10 }}>
              <Text style={styles.title} numberOfLines={2}>{item.title}</Text>
              <Text style={styles.price}>{formatLocalPrice(item.priceLocal, item.currencyCode)}</Text>
            </View>
          </Pressable>
        )}
      />
    </SafeAreaView>
  );
};

export default MarketStoreScreen;

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.neutral },
  header: { padding: 16, gap: 6 },
  name: { fontSize: 22, fontWeight: '700', color: colors.textFlat },
  meta: { fontSize: 13, color: colors.text.secondary },
  verified: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  verifiedText: { fontSize: 13, fontWeight: '600', color: colors.primaryDark },
  description: { fontSize: 14, color: colors.text.primary, lineHeight: 20 },
  card: { flex: 1, backgroundColor: colors.white, borderRadius: 14, overflow: 'hidden', marginBottom: 12 },
  image: { width: '100%', aspectRatio: 1, backgroundColor: colors.neutralDark },
  imageEmpty: { alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 14, color: colors.text.primary },
  price: { fontSize: 15, fontWeight: '700', color: colors.textFlat, marginTop: 2 },
  empty: { textAlign: 'center', color: colors.text.secondary, marginTop: 32 },
});
