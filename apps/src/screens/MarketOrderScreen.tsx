import React, { useEffect, useState } from 'react';
import { useNumberLocale } from '../contexts/NumberLocaleProvider';
import { ActivityIndicator, Alert, Linking, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useMutation, useQuery } from '@apollo/client';
import { Text, TextInput } from '../components/common/AppText';
import { colors } from '../config/theme';
import {
  CheckoutStage, GET_MARKET_ORDER, RATE_MARKET_ORDER, SET_MARKET_ORDER_TRACKING, comprarError, orderStatusLabel,
  runMarketAction,
} from '../services/comprar';
import { formatLocalPrice, formatReference, formatUsd } from '../utils/comprarFormat';
import { SuccessHero } from '../components/common/SuccessHero';
import { ProcessingHero } from '../components/common/ProcessingHero';
import {
  ComprarFrame, KitButton, KitCard, KitRow, OrderProgress, ProductThumb, StatusPill, kitText,
} from '../components/comprar/kit';

type Action = 'ship' | 'confirm' | 'dispute' | 'refund' | 'reclaim';
type Copy = { label: string; confirm: string; busy: string; variant: 'primary' | 'secondary' | 'danger' | 'ghost'; icon?: string };

/**
 * What each action is called depends on where the order is. A buyer who just
 * paid is waiting for the store: "Lo recibí" is not their next step (it stays
 * available, quietly, for a hand-delivered order), and a problem at that point
 * is usually "I want to cancel".
 */
const actionCopy = (action: Action, status: string): Copy => {
  const waiting = status === 'funded';
  switch (action) {
    case 'ship':
      return { label: 'Marcar como enviado', icon: 'truck', variant: 'primary', busy: 'Marcando como enviado…',
        confirm: '¿Ya entregaste el pedido a Yango (o al repartidor)?' };
    case 'confirm':
      return waiting
        ? { label: 'Ya lo recibí', variant: 'ghost', busy: 'Confirmando…',
          confirm: 'La tienda aún no lo marcó como enviado. Confirma solo si ya tienes el pedido en tus manos: la tienda recibe el pago.' }
        : { label: 'Lo recibí', icon: 'check', variant: 'primary', busy: 'Confirmando…',
          confirm: 'Al confirmar, la tienda recibe el pago. ¿Recibiste tu pedido?' };
    case 'dispute':
      return { label: waiting ? 'Cancelar o reportar un problema' : 'Tengo un problema', variant: waiting ? 'ghost' : 'secondary',
        icon: waiting ? undefined : 'alert-circle', busy: 'Enviando tu reclamo…', confirm: '' };
    case 'refund':
      return { label: 'Reembolsar al comprador', variant: 'ghost', busy: 'Devolviendo el pago…',
        confirm: 'Devolverás el pago completo al comprador. ¿Continuar?' };
    case 'reclaim':
    default:
      return { label: 'Recuperar mi pago', icon: 'rotate-ccw', variant: 'primary', busy: 'Recuperando tu pago…',
        confirm: 'La tienda no marcó el pedido como enviado a tiempo. ¿Recuperar tu pago?' };
  }
};

const fmtDate = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString('es-BO', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';

export const MarketOrderScreen = () => {
  useNumberLocale(); // amounts follow the user's number format, live
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const orderId = route.params?.orderId as string;
  const justPaid = Boolean(route.params?.justPaid);
  const { data, loading, refetch, startPolling, stopPolling } = useQuery(GET_MARKET_ORDER, {
    variables: { id: orderId },
    fetchPolicy: 'cache-and-network',
  });
  const order = data?.marketOrder;
  const [busy, setBusy] = useState<Action | null>(null);
  const [stage, setStage] = useState<CheckoutStage | null>(null);
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

  const run = async (action: Action) => {
    setError(null);
    setBusy(action);
    setStage('paying');
    try {
      await runMarketAction(orderId, action as any, {
        ...(action === 'dispute' ? { disputeReason: disputeReason.trim() } : {}),
        onStage: setStage,
      });
      setDisputeOpen(false);
      await refetch();
    } catch (e: any) {
      setError(comprarError(e?.message));
    } finally {
      setBusy(null);
      setStage(null);
    }
  };

  const ask = (action: Action) => {
    if (action === 'dispute') {
      setDisputeOpen(true);
      return;
    }
    const copy = actionCopy(action, order?.status);
    Alert.alert(copy.label, copy.confirm, [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Sí', onPress: () => { void run(action); } },
    ]);
  };

  if (!order) {
    return (
      <ComprarFrame title="Pedido">
        {loading ? <ActivityIndicator style={{ marginTop: 48 }} color={colors.primaryDark} />
          : <Text style={[kitText.muted, { textAlign: 'center', marginTop: 48 }]}>No encontramos el pedido.</Text>}
      </ComprarFrame>
    );
  }

  const merchant = order.role === 'merchant';
  const status = order.status as string;
  const statusLine: Record<string, string> = {
    depositing: 'Estamos confirmando tu pago en la red. Tarda unos segundos.',
    funded: merchant
      ? `Prepara el pedido y márcalo como enviado antes del ${fmtDate(order.shipBy)}.`
      : `La tienda tiene hasta el ${fmtDate(order.shipBy)} para enviarlo. Si no, recuperas tu pago.`,
    shipped: merchant
      ? `Si el comprador no confirma, recibes el pago el ${fmtDate(order.releaseAt)}.`
      : `Confirma cuando lo recibas. Si no hay reclamos, la tienda recibe el pago el ${fmtDate(order.releaseAt)}.`,
    disputed: 'Confío está revisando el caso. Te avisaremos la decisión.',
    released: merchant ? 'El pago ya está en tu cuenta.' : 'Pedido completado. ¡Gracias por comprar!',
    refunded: merchant ? 'El pago fue devuelto al comprador.' : 'Te devolvimos el pago.',
  };
  const actions = ((order.availableActions || []) as string[])
    .filter((a) => a !== 'deposit' && !(a === 'dispute' && disputeOpen)) as Action[];
  const strong = actions.filter((a) => actionCopy(a, status).variant !== 'ghost');
  const quiet = actions.filter((a) => actionCopy(a, status).variant === 'ghost');
  const showHero = justPaid && !merchant && (status === 'depositing' || status === 'funded');
  const blocking = busy !== null && stage === 'paying' ? actionCopy(busy, status).busy : null;
  const waitingForStore = !merchant && status === 'funded';

  return (
    <ComprarFrame title="Pedido" background={showHero ? colors.white : colors.neutral} blocking={blocking}>
      <ScrollView contentContainerStyle={styles.content}>
        {showHero ? (
          status === 'depositing' ? (
            <ProcessingHero title="Confirmando tu pago…" amount={formatUsd(order.amountUsd)}
              hint={`En ${order.store?.name ?? 'la tienda'}`} />
          ) : (
            <SuccessHero title="¡Compra realizada!" amount={formatUsd(order.amountUsd)}
              hint={`En ${order.store?.name ?? 'la tienda'}`} />
          )
        ) : null}

        <KitCard>
          <View style={styles.statusHead}>
            <StatusPill status={status} label={orderStatusLabel(status, order.role)} />
            {settling ? <ActivityIndicator size="small" color={colors.primaryDark} /> : null}
          </View>
          <OrderProgress status={status} />
          {statusLine[status] ? <Text style={kitText.body}>{statusLine[status]}</Text> : null}
        </KitCard>

        {waitingForStore ? (
          <KitCard icon="list" title="Qué sigue">
            <Step n={1} text={`${order.store?.name ?? 'La tienda'} prepara tu pedido.`} />
            <Step n={2} text="Te avisamos cuando salga, con el seguimiento del envío." />
            <Step n={3} text={order.deliveryOutsideCity
              ? 'Recibes el pedido y confirmas en la app que llegó bien.'
              : 'Pagas el envío al repartidor al recibir y confirmas en la app que llegó bien.'} />
          </KitCard>
        ) : null}

        <KitCard>
          <View style={styles.productRow}>
            <ProductThumb uri={order.productPhotoUrl} size={56} />
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.title} numberOfLines={2}>{order.quantity} × {order.productTitle}</Text>
              <Text style={kitText.muted} numberOfLines={1}>
                {merchant ? `Cliente: ${order.buyerDisplayName}` : order.store?.name}
              </Text>
            </View>
          </View>
          <View style={styles.divider} />
          <KitRow label={merchant ? 'Venta' : 'Pagaste'} value={formatUsd(order.amountUsd)} strong={!merchant} />
          {formatReference(order.referenceLocal) ? (
            <Text style={[kitText.muted, styles.right]}>{formatReference(order.referenceLocal)} al cambio de hoy</Text>
          ) : null}
          {merchant && order.feeUsd ? (
            <>
              <KitRow label="Comisión Comprar" muted value={`−${formatUsd(order.feeUsd)}`} />
              <KitRow label="Recibes" strong value={formatUsd(order.merchantNetUsd)} />
            </>
          ) : null}
        </KitCard>

        <KitCard icon="truck" title="Entrega">
          <InfoLine icon="map-pin" text={order.deliveryAddress}
            sub={`${order.deliveryCity}${order.deliveryNote ? ` · ${order.deliveryNote}` : ''}`} />
          <Pressable onPress={() => { void Linking.openURL(`tel:${order.deliveryPhone}`); }}>
            <InfoLine icon="phone" text={order.deliveryPhone} link />
          </Pressable>
          <InfoLine icon="dollar-sign" text={order.deliveryOutsideCity
            ? 'Envío a otra ciudad: lo coordina la tienda.'
            : order.deliveryEstimateLocal
              ? `Envío ~${formatLocalPrice(order.deliveryEstimateLocal, order.deliveryCurrency || '')}, se paga al repartidor.`
              : 'Envío a coordinar con la tienda; se paga al repartidor.'} />
          {merchant && ['funded', 'shipped', 'disputed'].includes(status) ? (
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
            <InfoLine icon="navigation" text={`Seguimiento: ${order.trackingReference}`} />
          ) : null}
        </KitCard>

        {disputeOpen ? (
          <KitCard icon="alert-circle" title={waitingForStore ? '¿Quieres cancelar o algo salió mal?' : '¿Qué pasó?'}>
            <Text style={kitText.muted}>
              Confío revisa el caso con la tienda y, si corresponde, te devuelve el pago.
            </Text>
            <TextInput style={[styles.input, styles.textArea]} multiline
              placeholder={waitingForStore ? 'Cuéntanos por qué quieres cancelar' : 'Cuéntanos el problema con el pedido'}
              placeholderTextColor={colors.text.light} value={disputeReason} onChangeText={setDisputeReason} />
            <KitButton label="Enviar" variant="danger" disabled={busy !== null || disputeReason.trim().length < 10}
              loading={busy === 'dispute'} onPress={() => { void run('dispute'); }} />
            <KitButton label="Volver" variant="ghost" onPress={() => setDisputeOpen(false)} />
          </KitCard>
        ) : null}

        {status === 'released' && !merchant && !order.rating ? (
          <KitCard icon="star" title="Califica a la tienda">
            <View style={styles.stars}>
              {[1, 2, 3, 4, 5].map((n) => (
                <Pressable key={n} onPress={() => setRating(n)} accessibilityLabel={`${n} estrellas`} hitSlop={6}>
                  <Icon name="star" size={32} color={n <= rating ? '#F59E0B' : '#D1D5DB'} />
                </Pressable>
              ))}
            </View>
            <KitButton label="Enviar calificación" disabled={rating === 0} onPress={async () => {
              const res = await rate({ variables: { orderId, rating } });
              if (!res.data?.rateMarketOrder?.success) setError(comprarError(res.data?.rateMarketOrder?.error));
              await refetch();
            }} />
          </KitCard>
        ) : null}

        {status === 'draft' && !merchant ? (
          <KitButton label="Completar pago" icon="lock"
            onPress={() => navigation.replace('MarketCheckout', { productId: String(order.productId), resumeOrderId: order.id })} />
        ) : null}
        {error ? <Text style={kitText.error}>{error}</Text> : null}
        <View style={styles.actions}>
          {strong.map((a) => {
            const copy = actionCopy(a, status);
            return <KitButton key={a} testID={`order-action-${a}`} label={copy.label} icon={copy.icon} variant={copy.variant}
              disabled={busy !== null} loading={busy === a} onPress={() => ask(a)} />;
          })}
          {showHero ? (
            <KitButton label="Seguir comprando" variant="secondary" icon="shopping-bag"
              onPress={() => navigation.navigate('BottomTabs', { screen: 'Comprar' })} />
          ) : null}
          {quiet.map((a) => (
            <KitButton key={a} testID={`order-action-${a}`} label={actionCopy(a, status).label} variant="ghost"
              disabled={busy !== null} onPress={() => ask(a)} />
          ))}
        </View>
      </ScrollView>
    </ComprarFrame>
  );
};

const Step = ({ n, text }: { n: number; text: string }) => (
  <View style={styles.step}>
    <View style={styles.stepNum}><Text style={styles.stepNumText}>{n}</Text></View>
    <Text style={[kitText.body, { flex: 1 }]}>{text}</Text>
  </View>
);

const InfoLine = ({ icon, text, sub, link }: { icon: string; text: string; sub?: string; link?: boolean }) => (
  <View style={styles.info}>
    <Icon name={icon} size={15} color={colors.text.secondary} style={{ marginTop: 2 }} />
    <View style={{ flex: 1 }}>
      <Text style={link ? kitText.link : kitText.body}>{text}</Text>
      {sub ? <Text style={kitText.muted}>{sub}</Text> : null}
    </View>
  </View>
);

export default MarketOrderScreen;

const styles = StyleSheet.create({
  content: { padding: 16, gap: 12, paddingBottom: 40 },
  statusHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  productRow: { flexDirection: 'row', gap: 12, alignItems: 'center' },
  title: { fontSize: 16, fontWeight: '600', color: colors.textFlat },
  divider: { height: 1, backgroundColor: colors.borderLight },
  right: { textAlign: 'right', marginTop: -6 },
  info: { flexDirection: 'row', gap: 10 },
  step: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  stepNum: { width: 22, height: 22, borderRadius: 11, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center', marginTop: 1 },
  stepNumText: { fontSize: 12, fontWeight: '700', color: colors.primaryDeep },
  trackingRow: { flexDirection: 'row', gap: 8, alignItems: 'center' },
  input: { flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 11, fontSize: 14, color: colors.text.primary },
  textArea: { minHeight: 90, textAlignVertical: 'top', flex: 0 },
  smallButton: { paddingHorizontal: 14, paddingVertical: 11, borderRadius: 12, backgroundColor: colors.textFlat },
  smallButtonText: { color: colors.white, fontWeight: '600' },
  stars: { flexDirection: 'row', gap: 10, justifyContent: 'center' },
  actions: { gap: 10 },
});
