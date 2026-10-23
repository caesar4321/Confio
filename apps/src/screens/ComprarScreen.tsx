import React, { useCallback, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator, FlatList, Image, Pressable, RefreshControl, ScrollView, StyleSheet, View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useMutation, useQuery } from '@apollo/client';
import { Text, TextInput } from '../components/common/AppText';
import { colors } from '../config/theme';
import { MainStackParamList } from '../types/navigation';
import { useComprarLocation } from '../hooks/useComprarLocation';
import { ComprarLocationModal } from '../components/comprar/ComprarLocationModal';
import { GET_MARKETPLACE_HOME, GET_MARKETPLACE_PRODUCTS, SUBMIT_MARKETPLACE_INTEREST } from '../services/comprar';
import { ComprarInterestSheet } from '../components/comprar/ComprarInterestSheet';
import { AnalyticsService } from '../services/analyticsService';
import { formatLocalPrice } from '../utils/comprarFormat';
import { explainLocateOutcome } from '../utils/comprarLocate';

type Nav = NativeStackNavigationProp<MainStackParamList>;
const PAGE_SIZE = 20;

/**
 * Comprar — buy from verified sellers. Browsing defaults to the phone's city
 * and can move to any country/city. A city that is not live shows the fake
 * door: an intent probe, never a deposit or a list of nothing.
 */
export const ComprarScreen = () => {
  const navigation = useNavigation<Nav>();
  const { location, home: homeLocation, resolving, choose, relocate } = useComprarLocation();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [category, setCategory] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [submittedSearch, setSubmittedSearch] = useState('');
  const [answered, setAnswered] = useState<string | null>(null);
  const [probeOpen, setProbeOpen] = useState(false);
  const [submitInterest] = useMutation(SUBMIT_MARKETPLACE_INTEREST);

  const countryCode = location?.countryCode || '';
  const city = location?.city || '';
  // Each city's fake door is its own question.
  React.useEffect(() => { setAnswered(null); }, [countryCode, city]);
  const { data: home } = useQuery(GET_MARKETPLACE_HOME, {
    variables: { countryCode, city },
    skip: !countryCode,
    fetchPolicy: 'cache-and-network',
  });
  const cityInfo = home?.marketplaceCity;
  const isLive = Boolean(cityInfo?.isLive);
  const categories = home?.marketplaceCategories || [];

  const variables = useMemo(() => ({
    countryCode, city: city || null, category, search: submittedSearch || null,
    limit: PAGE_SIZE, offset: 0,
  }), [countryCode, city, category, submittedSearch]);
  const { data, loading, error: productsError, refetch, fetchMore, networkStatus } = useQuery(GET_MARKETPLACE_PRODUCTS, {
    variables,
    skip: !countryCode || !isLive,
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
  });
  const products = data?.marketplaceProducts || [];
  const [hasMore, setHasMore] = useState(true);
  const loadingMore = useRef(false);

  const loadMore = useCallback(async () => {
    if (loadingMore.current || !hasMore || loading || products.length < PAGE_SIZE) return;
    loadingMore.current = true;
    try {
      const { data: next } = await fetchMore({
        variables: { ...variables, offset: products.length },
        updateQuery: (prev: any, { fetchMoreResult }: any) => ({
          marketplaceProducts: [...(prev?.marketplaceProducts || []), ...(fetchMoreResult?.marketplaceProducts || [])],
        }),
      });
      if ((next?.marketplaceProducts || []).length < PAGE_SIZE) setHasMore(false);
    } catch {
      // keep the list; reaching the end again retries
    } finally {
      loadingMore.current = false;
    }
  }, [fetchMore, hasMore, loading, products.length, variables]);

  const answerFakeDoor = (wants: boolean) => {
    void AnalyticsService.logEvent('comprar_fake_door', {
      answer: wants ? 'si_avisame' : 'solo_miraba', country: countryCode, city,
    });
    if (wants) {
      // The probe: buy or sell, what, at what price, current sales.
      setProbeOpen(true);
      return;
    }
    setAnswered('no');
    void submitInterest({ variables: { countryCode, city, role: 'browsing' } }).catch(() => {});
  };

  const header = (
    <View>
      <View style={styles.topRow}>
        <Pressable style={styles.locationChip} onPress={() => setPickerOpen(true)}
          accessibilityRole="button" accessibilityLabel="Cambiar ciudad">
          <Icon name="map-pin" size={14} color={colors.primaryDark} />
          <Text style={styles.locationText} numberOfLines={1}>
            {resolving ? 'Buscando tu ciudad…' : city || 'Elige tu ciudad'}
          </Text>
          <Icon name="chevron-down" size={14} color={colors.text.secondary} />
        </Pressable>
        <View style={styles.topActions}>
          <Pressable style={styles.iconButton} onPress={() => navigation.navigate('MarketOrders')}
            accessibilityRole="button" accessibilityLabel="Mis compras">
            <Icon name="shopping-bag" size={18} color={colors.text.primary} />
          </Pressable>
          <Pressable style={styles.iconButton} onPress={() => navigation.navigate('MyMarketStore')}
            accessibilityRole="button" accessibilityLabel="Mi tienda">
            <Icon name="home" size={18} color={colors.text.primary} />
          </Pressable>
        </View>
      </View>
      {isLive && (
        <>
          <View style={styles.searchBox}>
            <Icon name="search" size={16} color={colors.text.light} />
            <TextInput style={styles.searchInput} placeholder="Buscar productos o tiendas"
              placeholderTextColor={colors.text.light} value={search} onChangeText={setSearch}
              returnKeyType="search" onSubmitEditing={() => { setHasMore(true); setSubmittedSearch(search.trim()); }} />
          </View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
            {[{ key: null, label: 'Todo' }, ...categories].map((c: any) => {
              const selected = c.key === category;
              return (
                <Pressable key={c.key || 'all'} onPress={() => { setHasMore(true); setCategory(c.key); }}
                  style={[styles.chip, selected && styles.chipSelected]}>
                  <Text style={[styles.chipText, selected && styles.chipTextSelected]}>{c.label}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
          {cityInfo?.deliveryEstimate ? (
            <Text style={styles.deliveryLine}>
              Envío en {city} ~{formatLocalPrice(cityInfo.deliveryEstimate, cityInfo.currencyCode)}
              {cityInfo.deliveryPartner ? ` con ${cityInfo.deliveryPartner}` : ''}{' · '}se paga al repartidor
            </Text>
          ) : null}
        </>
      )}
    </View>
  );

  const fakeDoor = (
    <View style={styles.fakeDoor}>
      <Icon name="shopping-bag" size={36} color={colors.primaryDark} />
      <Text style={styles.fakeTitle}>Próximamente en {city || 'tu ciudad'}</Text>
      <Text style={styles.fakeBody}>
        Compra productos de vendedores verificados, con tu pago protegido hasta que recibas tu pedido.
      </Text>
      {answered ? (
        <Text style={styles.fakeThanks}>
          {answered === 'yes' ? '¡Listo! Te avisaremos cuando llegue a tu ciudad.'
            : answered === 'yes_quiet' ? '¡Gracias! Tus respuestas nos ayudan a decidir dónde abrir.'
              : 'Gracias por mirar.'}
        </Text>
      ) : (
        <View style={styles.fakeButtons}>
          <Pressable style={styles.primaryButton} onPress={() => answerFakeDoor(true)}>
            <Text style={styles.primaryButtonText}>Sí, avísame</Text>
          </Pressable>
          <Pressable style={styles.secondaryButton} onPress={() => answerFakeDoor(false)}>
            <Text style={styles.secondaryButtonText}>Solo miraba</Text>
          </Pressable>
        </View>
      )}
      <Pressable onPress={() => setPickerOpen(true)} style={styles.exploreLink}>
        <Text style={styles.exploreText}>Explorar otras ciudades</Text>
      </Pressable>
    </View>
  );

  return (
    <View style={styles.screen}>
      {location && !isLive ? (
        <ScrollView contentContainerStyle={{ paddingBottom: 32 }}>
          {header}
          {fakeDoor}
        </ScrollView>
      ) : (
        <FlatList
          data={products}
          keyExtractor={(p: any) => String(p.id)}
          numColumns={2}
          columnWrapperStyle={styles.columns}
          ListHeaderComponent={header}
          contentContainerStyle={{ paddingBottom: 32 }}
          initialNumToRender={PAGE_SIZE}
          maxToRenderPerBatch={10}
          windowSize={21}
          onEndReachedThreshold={0.5}
          onEndReached={() => { void loadMore(); }}
          refreshControl={
            <RefreshControl refreshing={networkStatus === 4} onRefresh={() => { setHasMore(true); void refetch(); }} />
          }
          ListEmptyComponent={
            loading || resolving ? (
              <ActivityIndicator style={{ marginTop: 48 }} color={colors.primaryDark} />
            ) : productsError ? (
              // "Couldn't load" must never read as "nobody sells here".
              <View style={styles.fakeDoor}>
                <Text style={styles.fakeBody}>No pudimos cargar los productos.</Text>
                <Pressable style={styles.secondaryButton} onPress={() => { void refetch(); }}>
                  <Text style={styles.secondaryButtonText}>Reintentar</Text>
                </Pressable>
              </View>
            ) : submittedSearch || category ? (
              <Text style={styles.empty}>No encontramos productos con ese filtro.</Text>
            ) : (
              // Live but nobody has listed yet: stores fill this themselves.
              <View style={styles.fakeDoor}>
                <Icon name="home" size={36} color={colors.primaryDark} />
                <Text style={styles.fakeTitle}>Comprar ya está en {city}</Text>
                <Text style={styles.fakeBody}>
                  Abre tu tienda y sé de los primeros en vender a compradores verificados. Sin mensualidades: pagas 8% solo cuando vendes.
                </Text>
                <Pressable style={styles.primaryButton} onPress={() => navigation.navigate('MyMarketStore')}>
                  <Text style={styles.primaryButtonText}>Abrir mi tienda</Text>
                </Pressable>
                <Text style={styles.fakeBody}>¿Vienes a comprar? Los primeros productos aparecerán aquí muy pronto.</Text>
              </View>
            )
          }
          renderItem={({ item }: any) => (
            <Pressable style={styles.card}
              onPress={() => navigation.navigate('MarketProduct', { productId: String(item.id) })}>
              {item.photoUrls?.[0] ? (
                <Image source={{ uri: item.photoUrls[0] }} style={styles.cardImage} />
              ) : (
                <View style={[styles.cardImage, styles.cardImagePlaceholder]}>
                  <Icon name="image" size={24} color={colors.text.light} />
                </View>
              )}
              <View style={styles.cardBody}>
                <Text style={styles.cardTitle} numberOfLines={2}>{item.title}</Text>
                <Text style={styles.cardPrice}>{formatLocalPrice(item.priceLocal, item.currencyCode)}</Text>
                <Text style={styles.cardStore} numberOfLines={1}>{item.store?.name}</Text>
              </View>
            </Pressable>
          )}
        />
      )}
      <ComprarInterestSheet
        key={`${countryCode}-${city}`}
        visible={probeOpen}
        countryCode={countryCode}
        city={city}
        categories={categories}
        onClose={() => setProbeOpen(false)}
        onDone={(notify) => { setProbeOpen(false); setAnswered(notify ? 'yes' : 'yes_quiet'); }}
      />
      <ComprarLocationModal
        visible={pickerOpen}
        countryCode={countryCode || 'BO'}
        city={city}
        homeCountryCode={homeLocation?.countryCode}
        homeCity={homeLocation?.city}
        onClose={() => setPickerOpen(false)}
        onSelect={(cc, c) => { setHasMore(true); choose(cc, c); }}
        onUseGps={async () => {
          setHasMore(true);
          explainLocateOutcome(await relocate(), () => setPickerOpen(true));
        }}
      />
    </View>
  );
};

export default ComprarScreen;

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.neutral },
  topRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingTop: 12 },
  locationChip: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: colors.white, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 8, borderWidth: 1, borderColor: '#E5E7EB', maxWidth: '60%' },
  locationText: { fontSize: 14, fontWeight: '600', color: colors.text.primary, flexShrink: 1 },
  topActions: { flexDirection: 'row', gap: 8 },
  iconButton: { width: 38, height: 38, borderRadius: 19, backgroundColor: colors.white, borderWidth: 1, borderColor: '#E5E7EB', alignItems: 'center', justifyContent: 'center' },
  searchBox: { flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: 16, marginTop: 12, backgroundColor: colors.white, borderRadius: 12, borderWidth: 1, borderColor: '#E5E7EB', paddingHorizontal: 12 },
  searchInput: { flex: 1, paddingVertical: 10, fontSize: 15, color: colors.text.primary },
  chips: { paddingHorizontal: 16, paddingVertical: 12, gap: 8 },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.white, borderWidth: 1, borderColor: '#E5E7EB' },
  chipSelected: { backgroundColor: colors.textFlat, borderColor: colors.textFlat },
  chipText: { fontSize: 13, fontWeight: '600', color: colors.text.primary },
  chipTextSelected: { color: colors.white },
  deliveryLine: { fontSize: 12, color: colors.text.secondary, paddingHorizontal: 16, paddingBottom: 8 },
  columns: { gap: 12, paddingHorizontal: 16 },
  card: { flex: 1, backgroundColor: colors.white, borderRadius: 14, overflow: 'hidden', marginBottom: 12, borderWidth: 1, borderColor: '#F0F0F0' },
  cardImage: { width: '100%', aspectRatio: 1, backgroundColor: colors.neutralDark },
  cardImagePlaceholder: { alignItems: 'center', justifyContent: 'center' },
  cardBody: { padding: 10, gap: 2 },
  cardTitle: { fontSize: 14, color: colors.text.primary },
  cardPrice: { fontSize: 16, fontWeight: '700', color: colors.textFlat },
  cardStore: { fontSize: 12, color: colors.text.secondary },
  empty: { textAlign: 'center', color: colors.text.secondary, marginTop: 48 },
  fakeDoor: { alignItems: 'center', padding: 24, margin: 16, backgroundColor: colors.white, borderRadius: 16, gap: 10 },
  fakeTitle: { fontSize: 20, fontWeight: '700', color: colors.textFlat, textAlign: 'center' },
  fakeBody: { fontSize: 14, color: colors.text.secondary, textAlign: 'center', lineHeight: 20 },
  fakeButtons: { flexDirection: 'row', gap: 10, marginTop: 6 },
  fakeThanks: { fontSize: 14, fontWeight: '600', color: colors.primaryDark, marginTop: 6 },
  primaryButton: { backgroundColor: colors.primaryDark, borderRadius: 12, paddingHorizontal: 18, paddingVertical: 12 },
  primaryButtonText: { color: colors.white, fontWeight: '700', fontSize: 15 },
  secondaryButton: { borderRadius: 12, paddingHorizontal: 18, paddingVertical: 12, borderWidth: 1, borderColor: '#E5E7EB' },
  secondaryButtonText: { color: colors.text.primary, fontWeight: '600', fontSize: 15 },
  exploreLink: { marginTop: 6 },
  exploreText: { color: colors.primaryDark, fontWeight: '600' },
});
