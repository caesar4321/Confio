import React, { useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Image, Pressable, StyleSheet, Switch, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { useMutation, useQuery } from '@apollo/client';
import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import {
  DELETE_MARKET_PRODUCT, GET_MY_MARKET_STORE, OPEN_MARKET_STORE, SET_MARKET_PRODUCT_PAUSED,
  UPDATE_MARKET_STORE, comprarError,
} from '../services/comprar';
import { useComprarLocation } from '../hooks/useComprarLocation';
import { ComprarLocationModal } from '../components/comprar/ComprarLocationModal';
import { formatUsd } from '../utils/comprarFormat';
import { explainLocateOutcome } from '../utils/comprarLocate';
import { OpenStoreForm } from '../components/comprar/OpenStoreForm';
import { useAccount } from '../contexts/AccountContext';
import { ComprarFrame, KitCard } from '../components/comprar/kit';

const PRODUCT_STATUS: Record<string, string> = {
  pending_review: 'En revisión', active: 'Publicado', rejected: 'Rechazado', paused: 'Pausado',
};
const STATUS_STYLE: Record<string, { backgroundColor: string; color: string }> = {
  pending_review: { backgroundColor: colors.warning.background, color: colors.warning.text },
  active: { backgroundColor: colors.primaryLight, color: colors.primaryDeep },
  rejected: { backgroundColor: colors.error.background, color: colors.error.text },
  paused: { backgroundColor: colors.neutralDark, color: colors.text.secondary },
};

/**
 * Mi tienda for the active account, personal or business (a business needs
 * the edit-business-info permission). No KYB. The fee comes from the server
 * (marketplaceFeeBps), never from copy.
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
  const [error, setError] = useState<string | null>(null);
  // Locked from the tap until the new store has loaded (the mutation alone
  // finishes before the refetch, which would briefly re-enable the button).
  const [submitting, setSubmitting] = useState(false);
  const { activeAccount } = useAccount();
  const accountLabel = (activeAccount?.type || 'personal').toLowerCase() === 'business'
    ? `la cuenta de ${activeAccount?.business?.name || 'tu negocio'}`
    : 'tu cuenta personal';

  if (loading && !data) {
    return <ComprarFrame title="Mi tienda"><ActivityIndicator style={{ marginTop: 48 }} color={colors.primaryDark} /></ComprarFrame>;
  }

  if (!store) {
    const submit = async (values: { name: string; description: string; shipsOutsideCity: boolean }) => {
      if (submitting) return;
      setError(null);
      setSubmitting(true);
      let res;
      try {
        res = await openStore({ variables: {
          ...values, countryCode: location?.countryCode, city: location?.city,
        } });
      } catch {
        setSubmitting(false);
        setError(comprarError());
        return;
      }
      const r = res.data?.openMarketStore;
      if (!r?.success) {
        setSubmitting(false);
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
      try {
        await refetch();
      } finally {
        setSubmitting(false);
      }
    };
    return (
      <View style={styles.screen}>
        <OpenStoreForm
          feeBps={data?.marketplaceFeeBps}
          city={location?.city || ''}
          accountLabel={accountLabel}
          submitting={submitting || opening}
          error={error}
          onBack={() => navigation.goBack()}
          onPickCity={() => setPickerOpen(true)}
          onSubmit={(values) => { void submit(values); }}
        />
        <ComprarLocationModal visible={pickerOpen} countryCode={location?.countryCode || 'BO'} city={location?.city || ''}
          homeCountryCode={home?.countryCode} homeCity={home?.city}
          onClose={() => setPickerOpen(false)} onSelect={choose}
          onUseGps={async () => { explainLocateOutcome(await relocate(), () => setPickerOpen(true)); }} />
      </View>
    );
  }

  return (
    <ComprarFrame title="Mi tienda">
      <FlatList
        data={products}
        keyExtractor={(p: any) => String(p.id)}
        contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: 100 }}
        initialNumToRender={20}
        maxToRenderPerBatch={10}
        windowSize={21}
        ListHeaderComponent={
          <View style={{ gap: 10, marginBottom: 6 }}>
            <KitCard>
              <View style={styles.storeHead}>
                <View style={styles.avatar}>
                  <Text style={styles.initial}>{(store.name || '?').trim().charAt(0).toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={styles.storeName} numberOfLines={1}>{store.name}</Text>
                  <Text style={styles.muted}>{store.city} · {store.completedOrders} ventas{store.ratingCount ? ` · ★ ${Number(store.avgRating).toFixed(1)}` : ''}</Text>
                </View>
              </View>
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
            </KitCard>
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
              <Text style={styles.muted}>{formatUsd(item.priceUsd)} · stock {item.stock}</Text>
              <View style={[styles.statusPill, STATUS_STYLE[item.status] || STATUS_STYLE.paused]}>
                <Text style={[styles.statusText, { color: (STATUS_STYLE[item.status] || STATUS_STYLE.paused).color }]}>
                  {PRODUCT_STATUS[item.status] || item.status}
                </Text>
              </View>
              {item.status === 'rejected' && item.rejectionReason ? (
                <Text style={[styles.muted, styles.rejected]} numberOfLines={2}>{item.rejectionReason}</Text>
              ) : null}
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
    </ComprarFrame>
  );
};

export default MyMarketStoreScreen;

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.neutral },
  switchRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  switchText: { flex: 1, fontSize: 14, color: colors.text.primary },
  error: { color: colors.error.text, fontSize: 14 },
  storeHead: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  avatar: { width: 48, height: 48, borderRadius: 24, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center' },
  initial: { fontSize: 20, fontWeight: '700', color: colors.primaryDeep },
  storeName: { fontSize: 18, fontWeight: '700', color: colors.textFlat },
  statusPill: { alignSelf: 'flex-start', borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2, marginTop: 2 },
  statusText: { fontSize: 11, fontWeight: '700' },
  muted: { fontSize: 13, color: colors.text.secondary },
  rejected: { color: colors.error.text },
  salesLink: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: colors.white, borderRadius: 16, padding: 16, borderWidth: 1, borderColor: colors.borderLight },
  salesText: { flex: 1, fontSize: 15, fontWeight: '600', color: colors.textFlat },
  sectionTitle: { fontSize: 15, fontWeight: '700', color: colors.textFlat, marginTop: 6 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: colors.white, borderRadius: 16, padding: 12, borderWidth: 1, borderColor: colors.borderLight },
  thumb: { width: 56, height: 56, borderRadius: 12, backgroundColor: colors.neutralDark },
  thumbEmpty: { alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 15, fontWeight: '600', color: colors.textFlat },
  fab: { position: 'absolute', right: 16, bottom: 28, flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: colors.primaryDark, borderRadius: 999, paddingHorizontal: 18, paddingVertical: 14 },
  fabText: { color: colors.white, fontWeight: '700' },
});
