// A top-up order in the conversation: how to pay it (the QR, the bank
// details or the bank's own page) and how it is going, right under the form
// that created it. The same instructions as the full screen
// (utils/rampInstructions), read again every few seconds.
import React, { useMemo, useRef, useState } from 'react';
import { Image, Linking, Pressable, StyleSheet, View } from 'react-native';
import { useQuery } from '@apollo/client';
import Clipboard from '@react-native-clipboard/clipboard';
import Icon from 'react-native-vector-icons/Feather';
import QRCode from 'react-native-qrcode-svg';
import { GET_RAMP_ORDER_STATUS } from '../apollo/queries';
import { Text } from '../components/common/AppText';
import { USD_UNIT, formatRampMoney } from '../utils/rampFormat';
import { buildRampInstructionView } from '../utils/rampInstructions';

const EMERALD = '#047857';
const INK = '#111827';
const MUTED = '#4B5563';
// As the full screen: a longer payload is not drawn as a QR here.
const QR_MAX_BYTES = 2048;

// An order is watched for this long; after it the full screen has the rest.
const WATCH_MS = 30 * 60 * 1000;
const SAME_HOLDER = 'Paga desde una cuenta o billetera a tu mismo nombre. Los pagos de terceros pueden no acreditarse.';

export type TopUpOrder = {
  orderId: string;
  countryCode?: string;
  paymentMethodCode: string;
  paymentMethodDisplay?: string;
  /** What the person pays, in their currency, as they wrote it. */
  amountIn?: string;
  amountOut?: string;
  fiatCurrency?: string;
  assetUnit?: string;
  nextActionUrl?: string;
  paymentDetails?: unknown;
};

const details = (value: unknown): Record<string, unknown> => {
  if (!value) return {};
  if (typeof value === 'string') {
    try {
      return JSON.parse(value) || {};
    } catch (_e) {
      return {};
    }
  }
  return value as Record<string, unknown>;
};

// The provider's own words for an order, as the server sorts them (ramps/koywe_sync.py).
const DONE = new Set(['DELIVERED', 'CRYPTO_DELIVERED', 'FIAT_DELIVERED']);
const ENDED = new Set(['REJECTED', 'FAILED', 'CANCELLED', 'REFUNDED', 'REFUND_STARTED', 'REFUND_IN_PROGRESS',
  'REFUND_DELIVERED', 'INVALID_WITHDRAWALS_DETAILS', 'EXPIRED']);

/** How it is going, in the person's words. `pay`: the instructions to pay still apply. */
export function topUpOrderStatus(code: string): { label: string; tone: 'wait' | 'good' | 'bad'; pay: boolean } {
  if (DONE.has(code)) return { label: 'Recarga completada', tone: 'good', pay: false };
  // An order nobody paid ends here too: said as it is, not as a refusal.
  if (ENDED.has(code)) return { label: 'Esta recarga no se completó', tone: 'bad', pay: false };
  if (!code || code === 'WAITING') return { label: 'Esperando tu pago', tone: 'wait', pay: true };
  return { label: 'Procesando tu recarga', tone: 'wait', pay: false };
}

export function TopUpOrderCard({ order, onOpen }: {
  order: TopUpOrder;
  /** Opens the full instructions screen. */
  onOpen: () => void;
}) {
  // What the server last said for certain. A read that fails says nothing:
  // the card never falls back to "waiting for your payment" over a paid order.
  const known = useRef<{ status: string; paymentDetails?: unknown; nextActionUrl?: string | null } | null>(null);
  const mountedAt = useRef(Date.now());
  const settledNow = !!known.current && !['wait'].includes(topUpOrderStatus(known.current.status).tone);
  const { data } = useQuery(GET_RAMP_ORDER_STATUS, {
    variables: { orderId: order.orderId, countryCode: order.countryCode },
    fetchPolicy: 'cache-and-network',
    // Each read asks the provider: not once it ended, and not for ever.
    pollInterval: settledNow || Date.now() - mountedAt.current > WATCH_MS ? 0 : 10000,
  });
  if (data?.rampOrderStatus?.success) {
    known.current = {
      status: String(data.rampOrderStatus.status || '').toUpperCase(),
      paymentDetails: data.rampOrderStatus.paymentDetails,
      nextActionUrl: data.rampOrderStatus.nextActionUrl,
    };
  }
  const served = known.current;
  const status = topUpOrderStatus(served?.status || '');
  const [copied, setCopied] = useState('');
  const view = useMemo(() => buildRampInstructionView({
    direction: 'ON_RAMP',
    paymentMethodCode: order.paymentMethodCode,
    paymentMethodDisplay: order.paymentMethodDisplay,
    paymentDetails: { ...details(order.paymentDetails), ...details(served?.paymentDetails) },
    nextActionUrl: served?.nextActionUrl || order.nextActionUrl,
  }), [order, served?.paymentDetails, served?.nextActionUrl]);
  const qr = (view.qrValue || '').trim();
  // Bytes, as the full screen counts them (an accent is two).
  const drawQr = !!qr && unescape(encodeURIComponent(qr)).length <= QR_MAX_BYTES;
  const settled = status.tone !== 'wait';
  const showPay = status.pay;
  const amounts = [
    order.amountIn && order.fiatCurrency ? `Pagas ${order.amountIn} ${order.fiatCurrency}` : '',
    order.amountOut ? `Recibes aprox. ${formatRampMoney(order.amountOut, order.assetUnit || USD_UNIT)}` : '',
  ].filter(Boolean);

  return (
    <View style={styles.card}>
      <View style={styles.status} accessible accessibilityLabel={status.label}>
        <Icon name={status.tone === 'good' ? 'check-circle' : status.tone === 'bad' ? 'alert-circle' : 'clock'} size={16}
          color={status.tone === 'bad' ? '#B91C1C' : EMERALD} />
        <Text style={[styles.statusText, status.tone === 'bad' && styles.bad]}>{status.label}</Text>
      </View>
      {amounts.length ? <Text style={styles.amounts}>{amounts.join(' · ')}</Text> : null}
      {!showPay ? null : (
        <>
          <Text style={styles.title}>{view.title}</Text>
          {view.subtitle ? <Text style={styles.subtitle}>{view.subtitle}</Text> : null}
          {view.qrImageUri ? (
            <Image source={{ uri: view.qrImageUri }} style={styles.qrImage} resizeMode="contain" accessibilityLabel="Código QR para pagar" />
          ) : drawQr ? (
            <View style={styles.qr} accessible accessibilityLabel="Código QR para pagar"><QRCode value={qr} size={180} /></View>
          ) : null}
          {view.rows.map((row) => (
            <Pressable
              key={`${row.label}:${row.value}`}
              onPress={() => {
                Clipboard.setString(row.value);
                setCopied(row.label);
              }}
              style={styles.row}
              accessibilityRole="button"
              accessibilityLabel={`${row.label}: ${row.value}. Toca para copiar`}
            >
              <View style={styles.rowText}>
                <Text style={styles.rowLabel}>{row.label}</Text>
                <Text style={styles.rowValue} selectable>{row.value}</Text>
              </View>
              <Icon name={copied === row.label ? 'check' : 'copy'} size={16} color={copied === row.label ? EMERALD : MUTED} />
            </Pressable>
          ))}
          {/* As the full screen: a page to pay on only where the method has one of its own. */}
          {view.actionUrl && view.allowExternalAction ? (
            <Pressable onPress={() => { Linking.openURL(view.actionUrl!).catch(() => {}); }}
              style={({ pressed }) => [styles.pay, pressed && styles.payPressed]}
              accessibilityRole="link" accessibilityLabel={view.actionLabel || 'Ir a pagar'}>
              <Text style={styles.payText}>{view.actionLabel || 'Ir a pagar'}</Text>
            </Pressable>
          ) : null}
          {view.note ? <Text style={styles.note}>{view.note}</Text> : null}
          <Text style={styles.note}>{SAME_HOLDER}</Text>
        </>
      )}
      <Pressable onPress={onOpen} style={styles.second} accessibilityRole="button" accessibilityLabel="Ver en pantalla completa">
        <Text style={styles.secondText}>{settled ? 'Ver la recarga' : 'Ver en pantalla completa'}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 4, marginBottom: 4, maxWidth: 340, padding: 14, borderRadius: 16,
    borderWidth: 1, borderColor: '#A7F3D0', backgroundColor: '#FFFFFF',
  },
  status: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  statusText: { fontSize: 14, fontWeight: '700', color: EMERALD },
  bad: { color: '#B91C1C' },
  amounts: { fontSize: 14, fontWeight: '600', color: INK, marginTop: 8 },
  title: { fontSize: 16, fontWeight: '700', color: INK, marginTop: 10 },
  subtitle: { fontSize: 14, lineHeight: 20, color: MUTED, marginTop: 4 },
  qr: { alignSelf: 'center', marginTop: 14, padding: 10, borderRadius: 12, backgroundColor: '#FFFFFF' },
  qrImage: { alignSelf: 'center', width: 200, height: 200, marginTop: 14 },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 48, marginTop: 8, paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: 12, backgroundColor: '#F3F4F6',
  },
  rowText: { flex: 1 },
  rowLabel: { fontSize: 12, color: MUTED },
  rowValue: { fontSize: 15, fontWeight: '600', color: INK, marginTop: 2 },
  pay: { marginTop: 14, height: 48, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: EMERALD },
  payPressed: { backgroundColor: '#065F46' },
  payText: { fontSize: 16, fontWeight: '700', color: '#FFFFFF' },
  note: { fontSize: 13, lineHeight: 18, color: MUTED, marginTop: 10 },
  second: { marginTop: 6, minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  secondText: { fontSize: 15, fontWeight: '600', color: MUTED },
});
