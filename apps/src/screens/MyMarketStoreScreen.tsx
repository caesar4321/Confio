import React, { useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Image, Pressable, StyleSheet, Switch, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { useMutation, useQuery } from '@apollo/client';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, TextInput } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import {
  DELETE_MARKET_PRODUCT, GET_MY_MARKET_STORE, OPEN_MARKET_STORE, SET_MARKET_PRODUCT_PAUSED,
  UPDATE_MARKET_STORE, comprarError,
} from '../services/comprar';
import { useComprarLocation } from '../hooks/useComprarLocation';
import { ComprarLocationModal } from '../components/comprar/ComprarLocationModal';
import { formatLocalPrice } from '../utils/comprarFormat';
import { explainLocateOutcome } from '../utils/comprarLocate';

const PRODUCT_STATUS: Record<string, string> = {
  pending_review: 'En revisión', active: 'Publicado', rejected: 'Rechazado', paused: 'Pausado',
};

/**
 * Mi tienda for the active account, personal or business (a business needs
 * the edit-business-info permission). No KYB. Fee: 8% of each sale, only
 * when you sell.
 */
export const MyMarketStoreScreen = () => {
  const navigation = useNavigation<any>();
  const { data, loading, refetch } = useQuery(GET_MY_MARKET_STORE, { fetchPolicy: 'cache-and-network' });
  useFocusEffect(React.useCallback(() => { void refetch(); }, [refetch]));
  const store = data?.myMarketStore;
  const products = data?.myMarketStoreProducts || [];
  const [openStore, { loading: opening }] = useMutation(OPEN_MARKET_STORE);
  const [updateStore] = useMutation(UPDATE_MARKET_STORE);
  const [setPaused] = useMutation(SET_MARKET_PRODUCT_PAUSED);
  const [deleteProduct] = useMutation(DELETE_MARKET_PRODUCT);
  const { location, home, choose, relocate } = useComprarLocation();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [shipsOutside, setShipsOutside] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const header = (title: string) => (
    <Header navigation={navigation} isHomeScreen={false} title={title} backgroundColor="#fff"
      showBackButton isLight={false} unreadNotifications={0} currentAccountAvatar="U" />
  );

  if (loading && !data) {
    return <SafeAreaView style={styles.screen} edges={['top']}>{header('Mi tienda')}<ActivityIndicator style={{ marginTop: 48 }} color={colors.primaryDark} /></SafeAreaView>;
  }

  if (!store) {
    const submit = async () => {
      setError(null);
      const res = await openStore({ variables: {
        name: name.trim(), description: description.trim(), countryCode: location?.countryCode,
        city: location?.city, shipsOutsideCity: shipsOutside,
      } });
      const r = res.data?.openMarketStore;
      if (!r?.success) {
        if (r?.error === 'identity_required') {
          Alert.alert('Verifica tu identidad', 'Para vender en Comprar necesitas verificar tu identidad.', [
            { text: 'Ahora no', style: 'cancel' },
            { text: 'Verificar', onPress: () => navigation.navigate('Verification') },
          ]);
          return;
        }
        setError(comprarError(r?.error));
        return;
      }
      await refetch();
    };
    return (
      <SafeAreaView style={styles.screen} edges={['top']}>
        {header('Abrir mi tienda')}
        <View style={styles.content}>
          <Text style={styles.lead}>Vende tus productos a compradores verificados. Sin mensualidades: pagas 8% solo cuando vendes.</Text>
          <TextInput style={styles.input} placeholder="Nombre de tu tienda" placeholderTextColor={colors.text.light}
            value={name} onChangeText={setName} />
          <TextInput style={[styles.input, { minHeight: 80 }]} multiline placeholder="¿Qué vendes? (opcional)"
            placeholderTextColor={colors.text.light} value={description} onChangeText={setDescription} />
          <Pressable style={styles.input} onPress={() => setPickerOpen(true)}>
            <Text style={{ color: location?.city ? colors.text.primary : colors.text.light }}>
              {location?.city ? `Ciudad: ${location.city}` : 'Elige tu ciudad'}
            </Text>
          </Pressable>
          <View style={styles.switchRow}>
            <Text style={styles.switchText}>También envío a otras ciudades (el comprador paga más)</Text>
            <Switch value={shipsOutside} onValueChange={setShipsOutside} />
          </View>
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <Pressable style={[styles.primary, (!name.trim() || !location?.city || opening) && styles.disabled]}
            disabled={!name.trim() || !location?.city || opening} onPress={() => { void submit(); }}>
            {opening ? <ActivityIndicator color={colors.white} /> : <Text style={styles.primaryText}>Abrir tienda</Text>}
          </Pressable>
        </View>
        <ComprarLocationModal visible={pickerOpen} countryCode={location?.countryCode || 'BO'} city={location?.city || ''}
          homeCountryCode={home?.countryCode} homeCity={home?.city}
          onClose={() => setPickerOpen(false)} onSelect={choose}
          onUseGps={async () => { explainLocateOutcome(await relocate(), () => setPickerOpen(true)); }} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      {header('Mi tienda')}
      <FlatList
        data={products}
        keyExtractor={(p: any) => String(p.id)}
        contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: 100 }}
        initialNumToRender={20}
        maxToRenderPerBatch={10}
        windowSize={21}
        ListHeaderComponent={
          <View style={{ gap: 10, marginBottom: 6 }}>
            <View style={styles.storeCard}>
              <Text style={styles.storeName}>{store.name}</Text>
              <Text style={styles.muted}>{store.city} · {store.completedOrders} ventas{store.ratingCount ? ` · ★ ${Number(store.avgRating).toFixed(1)}` : ''}</Text>
              {store.status === 'suspended' ? (
                <Text style={styles.error}>Tu tienda está suspendida. Escríbenos desde el asistente.</Text>
              ) : (
                <View style={styles.switchRow}>
                  <Text style={styles.switchText}>Tienda abierta</Text>
                  <Switch value={store.status === 'active'} onValueChange={async (open) => {
                    await updateStore({ variables: { paused: !open } });
                    await refetch();
                  }} />
                </View>
              )}
            </View>
            <Pressable style={styles.salesLink} onPress={() => navigation.navigate('MarketOrders', { role: 'merchant' })}>
              <Icon name="inbox" size={18} color={colors.primaryDark} />
              <Text style={styles.salesText}>Mis ventas</Text>
              <Icon name="chevron-right" size={18} color={colors.text.light} />
            </Pressable>
            <Text style={styles.sectionTitle}>Productos</Text>
          </View>
        }
        ListEmptyComponent={<Text style={styles.muted}>Aún no publicaste productos.</Text>}
        renderItem={({ item }: any) => (
          <Pressable style={styles.row} onPress={() => navigation.navigate('MarketProductEdit', { productId: String(item.id) })}>
            {item.photoUrls?.[0] ? <Image source={{ uri: item.photoUrls[0] }} style={styles.thumb} />
              : <View style={[styles.thumb, styles.thumbEmpty]}><Icon name="image" size={18} color={colors.text.light} /></View>}
            <View style={{ flex: 1 }}>
              <Text style={styles.title} numberOfLines={1}>{item.title}</Text>
              <Text style={styles.muted}>{formatLocalPrice(item.priceLocal, item.currencyCode)} · stock {item.stock}</Text>
              <Text style={[styles.muted, item.status === 'rejected' && styles.rejected]}>
                {PRODUCT_STATUS[item.status] || item.status}
                {item.status === 'rejected' && item.rejectionReason ? ` — ${item.rejectionReason}` : ''}
              </Text>
            </View>
            {(item.status === 'active' || item.status === 'paused') && (
              <Pressable hitSlop={8} onPress={async () => {
                await setPaused({ variables: { productId: item.id, paused: item.status === 'active' } });
                await refetch();
              }} accessibilityLabel={item.status === 'active' ? 'Pausar' : 'Publicar'}>
                <Icon name={item.status === 'active' ? 'pause-circle' : 'play-circle'} size={22} color={colors.text.secondary} />
              </Pressable>
            )}
            <Pressable hitSlop={8} onPress={() => Alert.alert('Eliminar producto', '¿Seguro?', [
              { text: 'Cancelar', style: 'cancel' },
              { text: 'Eliminar', style: 'destructive', onPress: async () => {
                await deleteProduct({ variables: { productId: item.id } });
                await refetch();
              } },
            ])} accessibilityLabel="Eliminar">
              <Icon name="trash-2" size={20} color={colors.text.light} />
            </Pressable>
          </Pressable>
        )}
      />
      <Pressable style={styles.fab} onPress={() => navigation.navigate('MarketProductEdit', {})}>
        <Icon name="plus" size={20} color={colors.white} />
        <Text style={styles.fabText}>Agregar producto</Text>
      </Pressable>
    </SafeAreaView>
  );
};

export default MyMarketStoreScreen;

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.neutral },
  content: { padding: 16, gap: 12 },
  lead: { fontSize: 15, color: colors.text.primary, lineHeight: 21 },
  input: { backgroundColor: colors.white, borderWidth: 1, borderColor: '#E5E7EB', borderRadius: 12, paddingHorizontal: 12, paddingVertical: 12, fontSize: 15, color: colors.text.primary },
  switchRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  switchText: { flex: 1, fontSize: 14, color: colors.text.primary },
  primary: { backgroundColor: colors.primaryDark, borderRadius: 14, paddingVertical: 15, alignItems: 'center' },
  primaryText: { color: colors.white, fontWeight: '700', fontSize: 16 },
  disabled: { backgroundColor: '#D1D5DB' },
  error: { color: colors.error.text, fontSize: 14 },
  storeCard: { backgroundColor: colors.white, borderRadius: 14, padding: 14, gap: 6 },
  storeName: { fontSize: 18, fontWeight: '700', color: colors.textFlat },
  muted: { fontSize: 13, color: colors.text.secondary },
  rejected: { color: colors.error.text },
  salesLink: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: colors.white, borderRadius: 14, padding: 14 },
  salesText: { flex: 1, fontSize: 15, fontWeight: '600', color: colors.textFlat },
  sectionTitle: { fontSize: 15, fontWeight: '700', color: colors.textFlat, marginTop: 6 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: colors.white, borderRadius: 14, padding: 12 },
  thumb: { width: 52, height: 52, borderRadius: 10, backgroundColor: colors.neutralDark },
  thumbEmpty: { alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 15, fontWeight: '600', color: colors.textFlat },
  fab: { position: 'absolute', right: 16, bottom: 28, flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: colors.primaryDark, borderRadius: 999, paddingHorizontal: 18, paddingVertical: 14 },
  fabText: { color: colors.white, fontWeight: '700' },
});
