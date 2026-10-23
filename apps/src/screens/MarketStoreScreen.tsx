import React, { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Image, Pressable, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { gql, useQuery } from '@apollo/client';
import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import { GET_MARKETPLACE_PRODUCTS } from '../services/comprar';
import { formatReference, formatUsd } from '../utils/comprarFormat';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ComprarFrame, kitText } from '../components/comprar/kit';

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
  const insets = useSafeAreaInsets();
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
    <ComprarFrame title="Tienda">
      <FlatList
        data={products}
        keyExtractor={(p: any) => String(p.id)}
        numColumns={2}
        columnWrapperStyle={{ gap: 12, paddingHorizontal: 16 }}
        contentContainerStyle={{ paddingBottom: 16 + insets.bottom }}
        initialNumToRender={PAGE_SIZE}
        maxToRenderPerBatch={10}
        windowSize={21}
        onEndReachedThreshold={0.5}
        onEndReached={() => { void loadMore(); }}
        ListHeaderComponent={store ? (
          <View style={styles.header}>
            <View style={styles.headTop}>
              <View style={styles.avatar}>
                <Text style={styles.initial}>{(store.name || '?').trim().charAt(0).toUpperCase()}</Text>
              </View>
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={styles.name} numberOfLines={2}>{store.name}</Text>
                <View style={styles.verified}>
                  <Icon name="check-circle" size={13} color={colors.primaryDark} />
                  <Text style={styles.verifiedText}>Identidad verificada</Text>
                </View>
              </View>
            </View>
            <View style={styles.stats}>
              <Stat value={String(store.completedOrders ?? 0)} label={store.completedOrders === 1 ? 'venta' : 'ventas'} />
              <View style={styles.statDivider} />
              <Stat value={store.ratingCount ? `★ ${Number(store.avgRating).toFixed(1)}` : '—'}
                label={store.ratingCount ? `${store.ratingCount} opiniones` : 'sin opiniones'} />
              <View style={styles.statDivider} />
              <Stat value={store.city} label={store.shipsOutsideCity ? 'y otras ciudades' : 'solo esta ciudad'} />
            </View>
            {store.description ? <Text style={kitText.body}>{store.description}</Text> : null}
            {store.isOpen === false ? (
              <Text style={styles.closed}>La tienda está cerrada por ahora.</Text>
            ) : null}
            <Text style={styles.sectionTitle}>Productos</Text>
          </View>
        ) : null}
        ListEmptyComponent={loading || !store ? <ActivityIndicator style={{ marginTop: 32 }} color={colors.primaryDark} />
          : <Text style={[kitText.muted, styles.empty]}>Esta tienda aún no tiene productos.</Text>}
        renderItem={({ item }: any) => (
          <Pressable style={styles.card} onPress={() => navigation.navigate('MarketProduct', { productId: String(item.id) })}>
            {item.photoUrls?.[0] ? <Image source={{ uri: item.photoUrls[0] }} style={styles.image} />
              : <View style={[styles.image, styles.imageEmpty]}><Icon name="image" size={22} color={colors.text.light} /></View>}
            <View style={{ padding: 10 }}>
              <Text style={styles.title} numberOfLines={2}>{item.title}</Text>
              <Text style={styles.price}>{formatUsd(item.priceUsd)}</Text>
              {formatReference(item.referenceLocal) ? (
                <Text style={styles.reference}>{formatReference(item.referenceLocal)}</Text>
              ) : null}
            </View>
          </Pressable>
        )}
      />
    </ComprarFrame>
  );
};

const Stat = ({ value, label }: { value: string; label: string }) => (
  <View style={styles.stat}>
    <Text style={styles.statValue} numberOfLines={1}>{value}</Text>
    <Text style={styles.statLabel} numberOfLines={1}>{label}</Text>
  </View>
);

export default MarketStoreScreen;

const styles = StyleSheet.create({
  header: { padding: 16, gap: 14 },
  headTop: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  avatar: { width: 60, height: 60, borderRadius: 30, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center' },
  initial: { fontSize: 24, fontWeight: '700', color: colors.primaryDeep },
  name: { fontSize: 22, fontWeight: '700', color: colors.textFlat },
  verified: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  verifiedText: { fontSize: 13, fontWeight: '600', color: colors.primaryDeep },
  stats: { flexDirection: 'row', backgroundColor: colors.white, borderRadius: 16, paddingVertical: 12, borderWidth: 1, borderColor: colors.borderLight },
  stat: { flex: 1, alignItems: 'center', gap: 2, paddingHorizontal: 6 },
  statValue: { fontSize: 15, fontWeight: '700', color: colors.textFlat },
  statLabel: { fontSize: 12, color: colors.text.secondary },
  statDivider: { width: 1, backgroundColor: colors.borderLight },
  closed: { fontSize: 13, color: colors.warning.text },
  sectionTitle: { fontSize: 15, fontWeight: '700', color: colors.textFlat, marginTop: 4 },
  card: { flex: 1, backgroundColor: colors.white, borderRadius: 16, overflow: 'hidden', marginBottom: 12, borderWidth: 1, borderColor: colors.borderLight },
  image: { width: '100%', aspectRatio: 1, backgroundColor: colors.neutralDark },
  imageEmpty: { alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 14, color: colors.text.primary },
  price: { fontSize: 15, fontWeight: '700', color: colors.textFlat, marginTop: 2 },
  reference: { fontSize: 12, color: colors.text.secondary },
  empty: { textAlign: 'center', marginTop: 24 },
});
