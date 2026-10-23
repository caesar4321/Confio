import React, { useState } from 'react';
import { ActivityIndicator, Dimensions, Image, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useQuery } from '@apollo/client';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { GET_MARKETPLACE_PRODUCT } from '../services/comprar';
import { formatLocalPrice } from '../utils/comprarFormat';

const WIDTH = Dimensions.get('window').width;

export const MarketProductScreen = () => {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const productId = route.params?.productId as string;
  const { data, loading } = useQuery(GET_MARKETPLACE_PRODUCT, {
    variables: { id: productId },
    fetchPolicy: 'cache-and-network',
  });
  const product = data?.marketplaceProduct;
  const [photo, setPhoto] = useState(0);

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <Header navigation={navigation} isHomeScreen={false} title="Producto" backgroundColor="#fff"
        showBackButton isLight={false} unreadNotifications={0} currentAccountAvatar="U" />
      {!product ? (
        loading ? <ActivityIndicator style={{ marginTop: 48 }} color={colors.primaryDark} />
          : <Text style={styles.missing}>Este producto ya no está disponible.</Text>
      ) : (
        <>
          <ScrollView contentContainerStyle={{ paddingBottom: 120 }}>
            <ScrollView horizontal pagingEnabled showsHorizontalScrollIndicator={false}
              onMomentumScrollEnd={(e) => setPhoto(Math.round(e.nativeEvent.contentOffset.x / WIDTH))}>
              {(product.photoUrls?.length ? product.photoUrls : [null]).map((url: string | null, i: number) => (
                url ? <Image key={i} source={{ uri: url }} style={styles.photo} />
                  : <View key={i} style={[styles.photo, styles.photoPlaceholder]}><Icon name="image" size={32} color={colors.text.light} /></View>
              ))}
            </ScrollView>
            {product.photoUrls?.length > 1 && (
              <View style={styles.dots}>
                {product.photoUrls.map((_: string, i: number) => (
                  <View key={i} style={[styles.dot, i === photo && styles.dotActive]} />
                ))}
              </View>
            )}
            <View style={styles.body}>
              <Text style={styles.title}>{product.title}</Text>
              <Text style={styles.price}>{formatLocalPrice(product.priceLocal, product.currencyCode)}</Text>
              <Text style={styles.stock}>
                {product.stock > 0 ? `${product.stock} disponible${product.stock === 1 ? '' : 's'}` : 'Agotado'}
              </Text>
              {product.description ? <Text style={styles.description}>{product.description}</Text> : null}

              <Pressable style={styles.storeCard}
                onPress={() => navigation.navigate('MarketStore', { storeId: String(product.store.id) })}>
                <View style={styles.storeAvatar}><Icon name="home" size={18} color={colors.primaryDark} /></View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.storeName}>{product.store.name}</Text>
                  <Text style={styles.storeMeta}>
                    {product.store.city} · {product.store.completedOrders} ventas
                    {product.store.ratingCount ? ` · ★ ${Number(product.store.avgRating).toFixed(1)}` : ''}
                  </Text>
                </View>
                <View style={styles.verified}>
                  <Icon name="check-circle" size={14} color={colors.primaryDark} />
                  <Text style={styles.verifiedText}>Verificada</Text>
                </View>
              </Pressable>

              <View style={styles.trust}>
                <Icon name="shield" size={16} color={colors.primaryDark} />
                <Text style={styles.trustText}>
                  Pago protegido: tu dinero queda guardado hasta que recibas tu pedido. Si la tienda no lo envía, lo recuperas.
                </Text>
              </View>
            </View>
          </ScrollView>
          <View style={styles.footer}>
            <Pressable
              style={[styles.buyButton, !product.isBuyable && styles.buyDisabled]}
              disabled={!product.isBuyable}
              onPress={() => navigation.navigate('MarketCheckout', { productId: String(product.id) })}
            >
              <Text style={styles.buyText}>{product.isBuyable ? 'Comprar' : 'No disponible'}</Text>
            </Pressable>
          </View>
        </>
      )}
    </SafeAreaView>
  );
};

export default MarketProductScreen;

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.white },
  missing: { textAlign: 'center', color: colors.text.secondary, marginTop: 48 },
  photo: { width: WIDTH, height: WIDTH, backgroundColor: colors.neutralDark },
  photoPlaceholder: { alignItems: 'center', justifyContent: 'center' },
  dots: { flexDirection: 'row', justifyContent: 'center', gap: 6, marginTop: 8 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: '#D1D5DB' },
  dotActive: { backgroundColor: colors.textFlat },
  body: { padding: 16, gap: 8 },
  title: { fontSize: 20, fontWeight: '600', color: colors.textFlat },
  price: { fontSize: 24, fontWeight: '700', color: colors.textFlat },
  stock: { fontSize: 13, color: colors.text.secondary },
  description: { fontSize: 15, color: colors.text.primary, lineHeight: 22, marginTop: 4 },
  storeCard: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12, borderRadius: 14, borderWidth: 1, borderColor: '#E5E7EB', marginTop: 12 },
  storeAvatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center' },
  storeName: { fontSize: 15, fontWeight: '600', color: colors.textFlat },
  storeMeta: { fontSize: 12, color: colors.text.secondary },
  verified: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  verifiedText: { fontSize: 12, fontWeight: '600', color: colors.primaryDark },
  trust: { flexDirection: 'row', gap: 10, padding: 12, borderRadius: 12, backgroundColor: colors.primaryLight, marginTop: 8 },
  trustText: { flex: 1, fontSize: 13, color: colors.onHeroField, lineHeight: 19 },
  footer: { position: 'absolute', left: 0, right: 0, bottom: 0, padding: 16, paddingBottom: 28, backgroundColor: colors.white, borderTopWidth: 1, borderTopColor: '#F0F0F0' },
  buyButton: { backgroundColor: colors.primaryDark, borderRadius: 14, paddingVertical: 15, alignItems: 'center' },
  buyDisabled: { backgroundColor: '#D1D5DB' },
  buyText: { color: colors.white, fontSize: 16, fontWeight: '700' },
});
