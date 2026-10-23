import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Linking, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useMutation, useQuery } from '@apollo/client';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, TextInput } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import {
  GET_MARKET_ORDER, RATE_MARKET_ORDER, SET_MARKET_ORDER_TRACKING, comprarError, orderStatusLabel,
  runMarketAction,
} from '../services/comprar';
import { formatLocalPrice, formatUsd } from '../utils/comprarFormat';

const ACTION_COPY: Record<string, { label: string; confirm: string; primary?: boolean; danger?: boolean }> = {
  ship: { label: 'Marcar como enviado', confirm: '¿Ya entregaste el pedido a Yango (o al repartidor)?', primary: true },
  confirm: { label: 'Lo recibí', confirm: 'Al confirmar, la tienda recibe el pago. ¿Recibiste tu pedido?', primary: true },
  dispute: { label: 'Tengo un problema', confirm: '' },
  refund: { label: 'Reembolsar al comprador', confirm: 'Devolverás el pago completo al comprador. ¿Continuar?', danger: true },
  reclaim: { label: 'Recuperar mi pago', confirm: 'La tienda no marcó el pedido como enviado a tiempo. ¿Recuperar tu pago?', primary: true },
};

const fmtDate = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString('es-BO', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';

export const MarketOrderScreen = () => {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const orderId = route.params?.orderId as string;
  const { data, loading, refetch, startPolling, stopPolling } = useQuery(GET_MARKET_ORDER, {
    variables: { id: orderId },
    fetchPolicy: 'cache-and-network',
  });
  const order = data?.marketOrder;
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [disputeOpen, setDisputeOpen] = useState(false);
  const [disputeReason, setDisputeReason] = useState('');
  const [tracking, setTracking] = useState('');
  const [rating, setRating] = useState(0);
  const [setTrackingRef] = useMutation(SET_MARKET_ORDER_TRACKING);
  const [rate] = useMutation(RATE_MARKET_ORDER);

  // While the chain settles an action (or a just-paid deposit), keep reading.
  const settling = Boolean(order?.pendingAction) || order?.status === 'depositing';
  useEffect(() => {
    if (settling) startPolling(4000);
    else stopPolling();
    return () => stopPolling();
  }, [settling, startPolling, stopPolling]);
  useEffect(() => {
    if (order?.trackingReference) setTracking(order.trackingReference);
  }, [order?.trackingReference]);

  const run = async (action: string) => {
    setError(null);
    setBusy(action);
    try {
      await runMarketAction(orderId, action as any,
        action === 'dispute' ? { disputeReason: disputeReason.trim() } : {});
      setDisputeOpen(false);
      await refetch();
    } catch (e: any) {
      setError(comprarError(e?.message));
    } finally {
      setBusy(null);
    }
  };

  const ask = (action: string) => {
    if (action === 'dispute') {
      setDisputeOpen(true);
      return;
    }
    Alert.alert(ACTION_COPY[action].label, ACTION_COPY[action].confirm, [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Sí', onPress: () => { void run(action); } },
    ]);
  };

  if (!order) {
    return (
      <SafeAreaView style={styles.screen} edges={['top']}>
        <Header navigation={navigation} isHomeScreen={false} title="Pedido" backgroundColor="#fff"
          showBackButton isLight={false} unreadNotifications={0} currentAccountAvatar="U" />
        {loading ? <ActivityIndicator style={{ marginTop: 48 }} color={colors.primaryDark} />
          : <Text style={styles.muted}>No encontramos el pedido.</Text>}
      </SafeAreaView>
    );
  }

  const merchant = order.role === 'merchant';
  const statusLine: Record<string, string> = {
    depositing: 'Estamos confirmando tu pago en la red…',
    funded: merchant
      ? `Prepara el pedido y márcalo como enviado antes del ${fmtDate(order.shipBy)}.`
      : `La tienda tiene hasta el ${fmtDate(order.shipBy)} para enviarlo. Si no, recuperas tu pago.`,
    shipped: merchant
      ? `Si el comprador no confirma, recibes el pago el ${fmtDate(order.releaseAt)}.`
      : `Confirma cuando lo recibas. Si no hay reclamos, la tienda recibe el pago el ${fmtDate(order.releaseAt)}.`,
    disputed: 'Confío está revisando el caso. Te avisaremos la decisión.',
    released: merchant ? 'El pago ya está en tu cuenta.' : 'Pedido completado.',
    refunded: merchant ? 'El pago fue devuelto al comprador.' : 'Te devolvimos el pago.',
  };

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <Header navigation={navigation} isHomeScreen={false} title="Pedido" backgroundColor="#fff"
        showBackButton isLight={false} unreadNotifications={0} currentAccountAvatar="U" />
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.card}>
          <Text style={styles.status}>{orderStatusLabel(order.status, order.role)}</Text>
          {statusLine[order.status] ? <Text style={styles.body}>{statusLine[order.status]}</Text> : null}
          {settling ? (
            <View style={styles.settling}>
              <ActivityIndicator size="small" color={colors.primaryDark} />
              <Text style={styles.muted}>Actualizando…</Text>
            </View>
          ) : null}
        </View>

        <View style={styles.card}>
          <Text style={styles.title}>{order.quantity} × {order.productTitle}</Text>
          <Text style={styles.muted}>{merchant ? `Cliente: ${order.buyerDisplayName}` : order.store?.name}</Text>
          <View style={styles.line}>
            <Text style={styles.label}>Total</Text>
            <Text style={styles.value}>{formatLocalPrice(order.subtotalLocal, order.currencyCode)} · {formatUsd(order.amountUsd)}</Text>
          </View>
          {merchant && order.feeUsd ? (
            <>
              <View style={styles.line}>
                <Text style={styles.muted}>Comisión Comprar</Text>
                <Text style={styles.muted}>−{formatUsd(order.feeUsd)}</Text>
              </View>
              <View style={styles.line}>
                <Text style={styles.label}>Recibes</Text>
                <Text style={styles.value}>{formatUsd(order.merchantNetUsd)}</Text>
              </View>
            </>
          ) : null}
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Entrega</Text>
          <Text style={styles.body}>{order.deliveryAddress}</Text>
          <Text style={styles.muted}>{order.deliveryCity}{order.deliveryNote ? ` · ${order.deliveryNote}` : ''}</Text>
          <Pressable onPress={() => { void Linking.openURL(`tel:${order.deliveryPhone}`); }}>
            <Text style={styles.link}>{order.deliveryPhone}</Text>
          </Pressable>
          <Text style={styles.muted}>
            {order.deliveryOutsideCity
              ? 'Envío a otra ciudad: lo coordina la tienda.'
              : order.deliveryEstimateLocal
                ? `Envío ~${formatLocalPrice(order.deliveryEstimateLocal, order.currencyCode)}, se paga al repartidor.`
                : 'Envío a coordinar con la tienda; se paga al repartidor.'}
          </Text>
          {merchant && ['funded', 'shipped', 'disputed'].includes(order.status) ? (
            <View style={styles.trackingRow}>
              <TextInput style={styles.input} placeholder="N.º o link de seguimiento de Yango"
                placeholderTextColor={colors.text.light} value={tracking} onChangeText={setTracking} />
              <Pressable style={styles.smallButton} onPress={async () => {
                await setTrackingRef({ variables: { orderId, trackingReference: tracking } });
                await refetch();
              }}>
                <Text style={styles.smallButtonText}>Guardar</Text>
              </Pressable>
            </View>
          ) : order.trackingReference ? (
            <Text style={styles.body}>Seguimiento: {order.trackingReference}</Text>
          ) : null}
        </View>

        {disputeOpen ? (
          <View style={styles.card}>
            <Text style={styles.sectionTitle}>¿Qué pasó?</Text>
            <TextInput style={[styles.input, { minHeight: 80 }]} multiline placeholder="Cuéntanos el problema con el pedido"
              placeholderTextColor={colors.text.light} value={disputeReason} onChangeText={setDisputeReason} />
            <Pressable style={[styles.actionButton, styles.danger]} disabled={busy !== null}
              onPress={() => { void run('dispute'); }}>
              {busy === 'dispute' ? <ActivityIndicator color={colors.white} /> : <Text style={styles.actionText}>Enviar reclamo</Text>}
            </Pressable>
          </View>
        ) : null}

        {order.status === 'released' && order.role === 'buyer' && !order.rating ? (
          <View style={styles.card}>
            <Text style={styles.sectionTitle}>Califica a la tienda</Text>
            <View style={styles.stars}>
              {[1, 2, 3, 4, 5].map((n) => (
                <Pressable key={n} onPress={() => setRating(n)} accessibilityLabel={`${n} estrellas`}>
                  <Icon name="star" size={28} color={n <= rating ? '#F59E0B' : '#D1D5DB'} />
                </Pressable>
              ))}
            </View>
            <Pressable style={[styles.actionButton, rating === 0 && styles.disabled]} disabled={rating === 0}
              onPress={async () => {
                const res = await rate({ variables: { orderId, rating } });
                if (!res.data?.rateMarketOrder?.success) setError(comprarError(res.data?.rateMarketOrder?.error));
                await refetch();
              }}>
              <Text style={styles.actionText}>Enviar calificación</Text>
            </Pressable>
          </View>
        ) : null}

        {order.status === 'draft' && order.role === 'buyer' ? (
          <Pressable style={styles.actionButton}
            onPress={() => navigation.replace('MarketCheckout', {
              productId: String(order.productId), resumeOrderId: order.id,
            })}>
            <Text style={styles.actionText}>Completar pago</Text>
          </Pressable>
        ) : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <View style={{ gap: 10 }}>
          {(order.availableActions || []).filter((a: string) => a !== 'deposit' && !(a === 'dispute' && disputeOpen)).map((a: string) => (
            <Pressable key={a} disabled={busy !== null}
              style={[styles.actionButton, ACTION_COPY[a]?.danger && styles.danger,
                !ACTION_COPY[a]?.primary && !ACTION_COPY[a]?.danger && styles.secondary]}
              onPress={() => ask(a)}>
              {busy === a ? <ActivityIndicator color={colors.white} /> : (
                <Text style={[styles.actionText, !ACTION_COPY[a]?.primary && !ACTION_COPY[a]?.danger && styles.secondaryText]}>
                  {ACTION_COPY[a]?.label || a}
                </Text>
              )}
            </Pressable>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

export default MarketOrderScreen;

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.neutral },
  content: { padding: 16, gap: 12, paddingBottom: 40 },
  card: { backgroundColor: colors.white, borderRadius: 14, padding: 14, gap: 8 },
  status: { fontSize: 18, fontWeight: '700', color: colors.textFlat },
  sectionTitle: { fontSize: 15, fontWeight: '700', color: colors.textFlat },
  title: { fontSize: 16, fontWeight: '600', color: colors.textFlat },
  body: { fontSize: 14, color: colors.text.primary, lineHeight: 20 },
  muted: { fontSize: 13, color: colors.text.secondary },
  label: { fontSize: 14, color: colors.text.primary },
  value: { fontSize: 14, fontWeight: '600', color: colors.textFlat },
  line: { flexDirection: 'row', justifyContent: 'space-between' },
  link: { fontSize: 14, color: colors.accent, fontWeight: '600' },
  settling: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  trackingRow: { flexDirection: 'row', gap: 8, alignItems: 'center' },
  input: { flex: 1, borderWidth: 1, borderColor: '#E5E7EB', borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, color: colors.text.primary },
  smallButton: { paddingHorizontal: 12, paddingVertical: 10, borderRadius: 10, backgroundColor: colors.textFlat },
  smallButtonText: { color: colors.white, fontWeight: '600' },
  stars: { flexDirection: 'row', gap: 8 },
  actionButton: { backgroundColor: colors.primaryDark, borderRadius: 14, paddingVertical: 14, alignItems: 'center' },
  secondary: { backgroundColor: colors.white, borderWidth: 1, borderColor: '#E5E7EB' },
  secondaryText: { color: colors.text.primary },
  danger: { backgroundColor: colors.error.icon },
  disabled: { backgroundColor: '#D1D5DB' },
  actionText: { color: colors.white, fontWeight: '700', fontSize: 15 },
  error: { color: colors.error.text, textAlign: 'center' },
});
