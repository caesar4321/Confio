import React, { useState } from 'react';
import { useNumberLocale } from '../contexts/NumberLocaleProvider';
import { ActivityIndicator, Dimensions, Image, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useQuery } from '@apollo/client';
import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import { GET_MARKETPLACE_PRODUCT } from '../services/comprar';
import { formatRating, formatReference, formatUsd } from '../utils/comprarFormat';
import { formatDecimal } from '../utils/numberLocale';
import { ComprarFrame, KitButton, KitFooter, TrustNote, kitText } from '../components/comprar/kit';
import { StoreReviews } from '../components/comprar/StoreReviews';

const WIDTH = Dimensions.get('window').width;

export const MarketProductScreen = () => {
  useNumberLocale(); // amounts follow the user's number format, live
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const productId = route.params?.productId as string;
  const { data, loading } = useQuery(GET_MARKETPLACE_PRODUCT, {
    variables: { id: productId },
    fetchPolicy: 'cache-and-network',
  });
  const product = data?.marketplaceProduct;
  const [photo, setPhoto] = useState(0);

  if (!product) {
    return (
      <ComprarFrame title="Producto" background={colors.white}>
        {loading ? <ActivityIndicator style={{ marginTop: 48 }} color={colors.primaryDark} />
          : <Text style={[kitText.muted, styles.missing]}>Este producto ya no está disponible.</Text>}
      </ComprarFrame>
    );
  }

  const photos: (string | null)[] = product.photoUrls?.length ? product.photoUrls : [null];
  const reference = formatReference(product.referenceLocal);
  const store = product.store;
  return (
    <ComprarFrame title="Producto" background={colors.white}>
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
        <View>
          <ScrollView horizontal pagingEnabled showsHorizontalScrollIndicator={false}
            onMomentumScrollEnd={(e) => setPhoto(Math.round(e.nativeEvent.contentOffset.x / WIDTH))}>
            {photos.map((url, i) => (
              url ? <Image key={i} source={{ uri: url }} style={styles.photo} />
                : <View key={i} style={[styles.photo, styles.photoPlaceholder]}><Icon name="image" size={32} color={colors.text.light} /></View>
            ))}
          </ScrollView>
          {photos.length > 1 ? (
            <View style={styles.counter}><Text style={styles.counterText}>{photo + 1}/{photos.length}</Text></View>
          ) : null}
        </View>
        {photos.length > 1 ? (
          <View style={styles.dots}>
            {photos.map((_, i) => <View key={i} style={[styles.dot, i === photo && styles.dotActive]} />)}
          </View>
        ) : null}

        <View style={styles.body}>
          {product.categoryLabel ? <Text style={styles.category}>{product.categoryLabel}</Text> : null}
          <Text style={styles.title}>{product.title}</Text>
          <View style={styles.priceRow}>
            <Text style={styles.price}>{formatUsd(product.priceUsd)}</Text>
            {reference ? <Text style={styles.reference}>{reference}</Text> : null}
          </View>
          <View style={[styles.stockPill, product.stock > 0 ? styles.stockOk : styles.stockOut]}>
            <Text style={[styles.stockText, product.stock > 0 ? styles.stockTextOk : styles.stockTextOut]}>
              {product.stock > 0 ? `${formatDecimal(product.stock, { decimals: 0 })} disponible${product.stock === 1 ? '' : 's'}` : 'Agotado'}
            </Text>
          </View>

          {product.description ? (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Descripción</Text>
              <Text style={kitText.body}>{product.description}</Text>
            </View>
          ) : null}

          <Pressable style={({ pressed }) => [styles.storeCard, pressed && { opacity: 0.85 }]}
            onPress={() => navigation.navigate('MarketStore', { storeId: String(store.id) })}>
            <View style={styles.storeAvatar}>
              <Text style={styles.storeInitial}>{(store.name || '?').trim().charAt(0).toUpperCase()}</Text>
            </View>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.storeName} numberOfLines={1}>{store.name}</Text>
              <Text style={kitText.muted} numberOfLines={1}>
                {store.city} · {formatDecimal(store.completedOrders ?? 0, { decimals: 0 })} {store.completedOrders === 1 ? 'venta' : 'ventas'}
                {store.ratingCount ? ` · ★ ${formatRating(store.avgRating)}` : ''}
              </Text>
              <View style={styles.verified}>
                <Icon name="check-circle" size={13} color={colors.primaryDark} />
                <Text style={styles.verifiedText}>Identidad verificada</Text>
              </View>
            </View>
            <Icon name="chevron-right" size={18} color={colors.text.light} />
          </Pressable>

          <StoreReviews storeId={String(store.id)} avgRating={store.avgRating} ratingCount={store.ratingCount}
            preview={2} onSeeAll={() => navigation.navigate('MarketStore', { storeId: String(store.id) })} />

          <TrustNote>
            Pago protegido: tu dinero queda guardado hasta que recibas tu pedido. Si la tienda no lo envía, lo recuperas.
          </TrustNote>
        </View>
      </ScrollView>
      <KitFooter>
        <View style={styles.footerRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.footerPrice}>{formatUsd(product.priceUsd)}</Text>
            <Text style={kitText.muted} numberOfLines={1}>+ envío al recibir</Text>
          </View>
          <View style={{ flex: 1.3 }}>
            <KitButton label={product.isBuyable ? 'Comprar' : 'No disponible'} disabled={!product.isBuyable}
              onPress={() => navigation.navigate('MarketCheckout', { productId: String(product.id) })} />
          </View>
        </View>
      </KitFooter>
    </ComprarFrame>
  );
};

export default MarketProductScreen;

const styles = StyleSheet.create({
  missing: { textAlign: 'center', marginTop: 48 },
  photo: { width: WIDTH, height: WIDTH, backgroundColor: colors.neutralDark },
  photoPlaceholder: { alignItems: 'center', justifyContent: 'center' },
  counter: { position: 'absolute', right: 12, bottom: 12, backgroundColor: 'rgba(17,24,39,0.6)', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  counterText: { color: colors.white, fontSize: 12, fontWeight: '600' },
  dots: { flexDirection: 'row', justifyContent: 'center', gap: 6, marginTop: 10 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: '#D1D5DB' },
  dotActive: { backgroundColor: colors.textFlat, width: 16 },
  body: { padding: 16, gap: 12 },
  category: { fontSize: 12, fontWeight: '700', color: colors.primaryDeep, textTransform: 'uppercase', letterSpacing: 0.5 },
  title: { fontSize: 22, fontWeight: '700', color: colors.textFlat, marginTop: -4 },
  priceRow: { flexDirection: 'row', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' },
  price: { fontSize: 28, fontWeight: '700', color: colors.textFlat },
  reference: { fontSize: 15, color: colors.text.secondary },
  stockPill: { alignSelf: 'flex-start', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  stockOk: { backgroundColor: colors.primaryLight },
  stockOut: { backgroundColor: colors.neutralDark },
  stockText: { fontSize: 12, fontWeight: '700' },
  stockTextOk: { color: colors.primaryDeep },
  stockTextOut: { color: colors.text.secondary },
  section: { gap: 6, paddingTop: 4 },
  sectionTitle: { fontSize: 15, fontWeight: '700', color: colors.textFlat },
  storeCard: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, borderRadius: 16, borderWidth: 1, borderColor: colors.border },
  storeAvatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center' },
  storeInitial: { fontSize: 18, fontWeight: '700', color: colors.primaryDeep },
  storeName: { fontSize: 15, fontWeight: '700', color: colors.textFlat },
  verified: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 2 },
  verifiedText: { fontSize: 12, fontWeight: '600', color: colors.primaryDeep },
  footerRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  footerPrice: { fontSize: 20, fontWeight: '700', color: colors.textFlat },
});
