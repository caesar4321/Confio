import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator, Image, SafeAreaView, ScrollView, StatusBar, StyleSheet, TouchableOpacity, View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Share from 'react-native-share';
import ViewShot from 'react-native-view-shot';
import { CameraRoll } from '@react-native-camera-roll/camera-roll';
import { useApolloClient } from '@apollo/client';
import { useIsFocused, useNavigation } from '@react-navigation/native';

import { Text, TextInput } from '../components/common/AppText';
import { colors } from '../config/theme';
import { RampActionBar } from '../components/ramps/RampActionBar';
import { RampHero } from '../components/ramps/RampHero';
import { RampReveal } from '../components/ramps/RampReveal';
import { RampStepHeader } from '../components/ramps/RampStepHeader';
import { rampFlowStyles as styles } from '../components/ramps/rampFlowStyles';
import { FaceCheckError, isFaceStepUpRequired, withFaceStepUp } from '../services/faceStepUp';
import { getSeparators, sanitizeAmountInput } from '../utils/numberLocale';
import {
  BOLIVIA_QR_ACTIVE_RECEIVE,
  BOLIVIA_QR_RECEIVE_ORDER,
  BOLIVIA_QR_RECEIVE_QUOTE,
  BoliviaQrReceiveOrder,
  BoliviaQrReceiveQuote,
  CANCEL_BOLIVIA_QR_RECEIVE,
  CREATE_BOLIVIA_QR_RECEIVE,
  qrImageUri,
  receiveCopy,
} from '../services/boliviaQr';

const POLL_MS = 5_000;
const GENERIC = 'No pudimos conectar. Intenta de nuevo en unos segundos.';

const toNumber = (value: string) => Number(value.replace(',', '.'));
const money = (value?: string | number | null, digits = 2) =>
  value === null || value === undefined || value === '' ? '—'
    : Number(value).toLocaleString('es-BO', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const formatBs = (value?: string | null) => (value ? `Bs ${money(value)}` : '—');
const formatUsd = (value?: string | number | null) => (value === null || value === undefined || value === '' ? '—' : `$${money(value)}`);
const isOpen = (order: BoliviaQrReceiveOrder | null) => !!order?.orderId && (order.status === 'PENDING' || order.status === 'PROCESSING');

function remaining(expiresAt?: string | null, now = Date.now()): string {
  const end = expiresAt ? Date.parse(expiresAt) : NaN;
  if (!Number.isFinite(end)) return '';
  const seconds = Math.max(0, Math.floor((end - now) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/**
 * Recibir con QR Bolivia. One server order per QR: amount in bolivianos →
 * Confío Face → the processor's QR (any Bolivian bank app pays it) → the
 * dollars arrive in the person's balance. Nothing is signed here: the money
 * comes to the wallet. The order lives on the server, so reopening resumes it.
 */
export default function BoliviaQrReceiveScreen() {
  const client = useApolloClient();
  const navigation = useNavigation<any>();
  const focused = useIsFocused();
  const alive = useRef(true);
  const busy = useRef(false);
  const generation = useRef(0);
  const shot = useRef<ViewShot>(null);
  useEffect(() => () => { alive.current = false; }, []);

  const [booting, setBooting] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [order, setOrder] = useState<BoliviaQrReceiveOrder | null>(null);
  const [amount, setAmount] = useState('');
  const [amountFocused, setAmountFocused] = useState(false);
  const [quote, setQuote] = useState<BoliviaQrReceiveQuote | null>(null);
  const [now, setNow] = useState(Date.now());

  const boot = useCallback(async (keepError = false) => {
    setBooting(true);
    if (!keepError) setError('');
    try {
      const r = await client.query({ query: BOLIVIA_QR_ACTIVE_RECEIVE, fetchPolicy: 'network-only' });
      if (alive.current) setOrder(r.data?.boliviaQrActiveReceive || null);
    } catch {
      if (alive.current && !keepError) setError(GENERIC);
    } finally {
      if (alive.current) setBooting(false);
    }
  }, [client]);
  useEffect(() => { void boot(); }, [boot]);

  useEffect(() => {
    setQuote(null);
    if (order || !amount || !(toNumber(amount) > 0)) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const r = await client.query({
          query: BOLIVIA_QR_RECEIVE_QUOTE, variables: { bobAmount: String(toNumber(amount)) }, fetchPolicy: 'network-only',
        });
        if (!cancelled && alive.current) setQuote(r.data?.boliviaQrReceiveQuote || null);
      } catch {
        if (!cancelled && alive.current) setQuote(null);
      }
    }, 450);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [amount, client, order]);

  const refreshOrder = useCallback(async (orderId: string) => {
    const issued = generation.current;
    const r = await client.query({ query: BOLIVIA_QR_RECEIVE_ORDER, variables: { orderId }, fetchPolicy: 'network-only' });
    const next: BoliviaQrReceiveOrder | undefined = r.data?.boliviaQrReceiveOrder;
    if (next?.success && alive.current && issued === generation.current) setOrder(next);
  }, [client]);

  useEffect(() => {
    if (!focused || !isOpen(order) || !order?.orderId) return;
    const timer = setInterval(() => { void refreshOrder(order.orderId as string).catch(() => {}); }, POLL_MS);
    return () => clearInterval(timer);
  }, [focused, order, refreshOrder]);

  useEffect(() => {
    if (order?.phase !== 'qr_ready') return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [order?.phase]);

  const amountValue = toNumber(amount);
  const quoteMatches = !!quote?.success && Number(quote.bobAmount) === Number(amountValue.toFixed(2));

  const create = async () => {
    if (busy.current || !quoteMatches) return;
    busy.current = true;
    generation.current += 1;
    setLoading(true);
    setError('');
    try {
      const place = () => client.mutate({
        mutation: CREATE_BOLIVIA_QR_RECEIVE, variables: { bobAmount: String(amountValue) }, fetchPolicy: 'no-cache',
      });
      let response;
      try {
        // Each QR spends its own Confío Face check, like any top-up.
        response = await withFaceStepUp('on_ramp', place,
          r => isFaceStepUpRequired(r?.data?.createBoliviaQrReceive?.nextStep));
      } catch (faceError) {
        if (faceError instanceof FaceCheckError) return;
        throw faceError;
      }
      const result: BoliviaQrReceiveOrder | undefined = response?.data?.createBoliviaQrReceive;
      if (!alive.current) return;
      if (result?.nextStep === 'verification') {
        setError(result.error || '');
        navigation.navigate('Verification');
        return;
      }
      if (!result?.success || !result.orderId) {
        setError(result?.error || GENERIC);
        void boot(true);
        return;
      }
      setOrder(result);
    } catch {
      if (alive.current) {
        setError(GENERIC);
        // A lost answer may still have made a QR: show whatever exists.
        void boot(true);
      }
    } finally {
      busy.current = false;
      generation.current += 1;
      if (alive.current) setLoading(false);
    }
  };

  const cancel = async () => {
    if (busy.current || !order?.orderId) return;
    busy.current = true;
    setLoading(true);
    try {
      const r = await client.mutate({ mutation: CANCEL_BOLIVIA_QR_RECEIVE, variables: { orderId: order.orderId }, fetchPolicy: 'no-cache' });
      const result: BoliviaQrReceiveOrder | undefined = r.data?.cancelBoliviaQrReceive;
      if (!alive.current) return;
      if (result?.success) {
        // Hidden here; it can still be paid until it expires, so we keep watching it.
        setOrder(null); setAmount(''); setQuote(null);
        setNotice('Ocultamos ese QR. Si alguien ya lo tiene, aún puede pagarlo hasta que venza.');
      } else {
        setError(result?.error || GENERIC);
      }
    } catch {
      if (alive.current) setError(GENERIC);
    } finally {
      busy.current = false;
      if (alive.current) setLoading(false);
    }
  };

  const captureQr = async (): Promise<string | null> => {
    try {
      return (await shot.current?.capture?.()) || null;
    } catch {
      return null;
    }
  };

  const shareQr = async () => {
    const uri = await captureQr();
    if (!uri) return;
    try {
      await Share.open({
        title: 'QR para pagarme', url: uri, type: 'image/jpeg',
        message: `Págame ${formatBs(order?.bobAmount)} con este QR desde cualquier banco o billetera de Bolivia.`,
      });
    } catch {
      // closed by the person
    }
  };

  const saveQr = async () => {
    const uri = await captureQr();
    if (!uri) return;
    try {
      await CameraRoll.save(uri, { type: 'photo' });
      setNotice('QR guardado en tu galería.');
    } catch {
      setError('No pudimos guardar la imagen. Revisa el permiso de la galería.');
    }
  };

  const startOver = () => { setOrder(null); setAmount(''); setQuote(null); setError(''); setNotice(''); };

  const banner = (text: string, tone: 'warning' | 'info') => (
    <View style={[tone === 'warning' ? styles.warningCard : local.infoCard, local.edge]} accessibilityRole="alert">
      <Icon name={tone === 'warning' ? 'alert-circle' : 'check-circle'} size={18}
        color={tone === 'warning' ? colors.warning.text : colors.primaryDark} />
      <View style={local.flex}><Text style={tone === 'warning' ? styles.warningText : local.infoText}>{text}</Text></View>
    </View>
  );

  const renderForm = () => (
    <>
      <RampReveal delay={60}>
        <View style={styles.section}>
          <RampStepHeader number={1} title="Monto" meta="Lo que te van a pagar" />
          <View style={styles.inputCard}>
            <Text style={styles.inputLabel}>¿Cuántos bolivianos vas a cobrar?</Text>
            <View style={[styles.amountInputRow, amountFocused && styles.amountInputRowFocused]}>
              <TextInput
                accessibilityLabel="Monto en bolivianos"
                value={amount}
                keyboardType="decimal-pad"
                onChangeText={text => setAmount(prev => sanitizeAmountInput(text, 2, undefined, prev))}
                onFocus={() => setAmountFocused(true)}
                onBlur={() => setAmountFocused(false)}
                placeholder={`0${getSeparators().decimal}00`}
                placeholderTextColor={colors.textTertiary}
                style={styles.amountInput}
                editable={!loading}
              />
              <View style={styles.currencyBadge}><Text style={styles.currencyBadgeText}>BOB</Text></View>
            </View>
            {quote?.error ? <Text style={styles.errorText}>{quote.error}</Text> : null}
          </View>
          {quote?.success ? (
            <View style={[styles.quoteCard, local.quoteGap]}>
              <Text style={styles.quoteEyebrow}>Recibes aprox.</Text>
              <Text style={styles.quoteHeadline} adjustsFontSizeToFit numberOfLines={1}>{formatUsd(quote.usdEstimate)}</Text>
              {quote.rate ? <Text style={styles.quoteRate}>Tasa Bs {money(quote.rate)} por dólar</Text> : null}
              <View style={styles.disclaimerPill}>
                <Icon name="info" size={14} color={colors.primaryDark} />
                <Text style={styles.quoteNote}>Llegan a tu saldo unos minutos después del pago.</Text>
              </View>
            </View>
          ) : null}
        </View>
      </RampReveal>
    </>
  );

  const renderQr = (current: BoliviaQrReceiveOrder) => {
    const uri = qrImageUri(current.qrImage);
    const left = remaining(current.expiresAt, now);
    return (
      <RampReveal delay={60}>
        <ViewShot ref={shot} options={{ format: 'jpg', quality: 0.95 }}>
          <View style={local.qrCard}>
            <Text style={local.qrEyebrow}>PÁGAME CON QR</Text>
            <Text style={local.qrAmount}>{formatBs(current.bobAmount)}</Text>
            {uri ? <Image source={{ uri }} style={local.qrImage} resizeMode="contain" accessibilityLabel="Código QR" />
              : <ActivityIndicator color={colors.primary} />}
            <Text style={local.qrHint}>Desde cualquier banco o billetera de Bolivia</Text>
          </View>
        </ViewShot>
        {left ? <Text style={local.expiry}>{left === '0:00' ? 'El QR venció' : `Vence en ${left}`}</Text> : null}
        <View style={local.qrActions}>
          <TouchableOpacity style={local.qrAction} onPress={() => { void shareQr(); }} accessibilityRole="button">
            <Icon name="share-2" size={18} color={colors.primaryDark} />
            <Text style={local.qrActionText}>Compartir</Text>
          </TouchableOpacity>
          <TouchableOpacity style={local.qrAction} onPress={() => { void saveQr(); }} accessibilityRole="button">
            <Icon name="download" size={18} color={colors.primaryDark} />
            <Text style={local.qrActionText}>Guardar</Text>
          </TouchableOpacity>
        </View>
      </RampReveal>
    );
  };

  const renderOrder = (current: BoliviaQrReceiveOrder) => {
    if (current.phase === 'qr_ready') return renderQr(current);
    const copy = receiveCopy(current);
    const done = current.status === 'COMPLETED';
    const ended = current.status === 'FAILED';
    return (
      <RampReveal delay={60}>
        <View style={ended ? styles.emptyStateCard : styles.reviewCard}>
          {ended ? (
            <View style={[styles.emptyStateIconWrap, local.failIcon]}>
              <Icon name="clock" size={22} color={colors.warning.text} />
            </View>
          ) : null}
          <Text style={ended ? styles.emptyStateTitle : styles.reviewTitle}>{copy.title}</Text>
          <Text style={ended ? styles.emptyStateText : styles.helperText}>{copy.body}</Text>
          {!ended ? (
            <>
              <View style={styles.quoteDivider} />
              <View style={styles.reviewRow}>
                <Text style={styles.reviewLabel}>Te pagaron</Text>
                <Text style={styles.reviewValue}>{formatBs(current.bobAmount)}</Text>
              </View>
              <View style={styles.reviewRow}>
                <Text style={styles.reviewLabel}>{done ? 'Recibiste' : 'Recibes aprox.'}</Text>
                <Text style={styles.reviewValueHighlight}>{formatUsd(current.usdReceived || current.usdEstimate)}</Text>
              </View>
              {!done ? <ActivityIndicator color={colors.primary} accessibilityLabel="Acreditando" /> : null}
            </>
          ) : null}
        </View>
      </RampReveal>
    );
  };

  const actionBar = () => {
    if (booting) return null;
    if (!order) {
      return <RampActionBar primaryLabel="Crear QR" primaryIconName="maximize" onPrimaryPress={() => { void create(); }}
        primaryDisabled={!quoteMatches} primaryLoading={loading} />;
    }
    if (order.phase === 'qr_ready') {
      return <RampActionBar primaryLabel="Listo" onPrimaryPress={() => navigation.goBack()}
        secondaryLabel="Cancelar QR" onSecondaryPress={() => { void cancel(); }} />;
    }
    if (!isOpen(order)) {
      return <RampActionBar primaryLabel="Crear otro QR" onPrimaryPress={startOver}
        secondaryLabel="Volver" onSecondaryPress={() => navigation.goBack()} />;
    }
    return null;
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroFieldDark} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled">
        <RampReveal delay={0}>
          <RampHero eyebrow="Bolivia · QR" eyebrowCountry="BO"
            title={order ? (order.phase === 'qr_ready' ? 'Tu QR' : 'Tu cobro') : 'Cobra con QR'}
            subtitle={order ? 'Te avisamos cuando los dólares lleguen.'
              : 'Crea un QR por el monto que quieras. Te pagan desde cualquier banco y recibes dólares.'}
            onBack={() => navigation.goBack()} compact={!!order}
            onHistory={() => navigation.navigate('RampHistory', { initialFilter: 'on_ramp' })}
            historyLabel="Ver historial de cobros" />
        </RampReveal>
        {error ? banner(error, 'warning') : null}
        {notice && !error ? banner(notice, 'info') : null}
        {booting ? (
          <View style={styles.loadingCard}>
            <ActivityIndicator color={colors.primary} accessibilityLabel="Cargando" />
            <Text style={styles.loadingText}>Cargando…</Text>
          </View>
        ) : order ? renderOrder(order) : renderForm()}
      </ScrollView>
      {actionBar()}
    </SafeAreaView>
  );
}

const local = StyleSheet.create({
  flex: { flex: 1 },
  edge: { marginHorizontal: 22, marginTop: 0, marginBottom: 16 },
  quoteGap: { marginTop: 14 },
  failIcon: { backgroundColor: colors.warning.background },
  infoCard: {
    flexDirection: 'row', gap: 10, alignItems: 'center', padding: 14, borderRadius: 14,
    backgroundColor: colors.primaryLight,
  },
  infoText: { fontSize: 14, color: colors.primaryDeep, lineHeight: 20 },
  qrCard: {
    marginHorizontal: 22, backgroundColor: colors.white, borderRadius: 22, paddingVertical: 24, paddingHorizontal: 20,
    alignItems: 'center', borderWidth: 1, borderColor: colors.border,
  },
  qrEyebrow: { fontSize: 11, fontWeight: '700', letterSpacing: 2, color: colors.primaryDark },
  qrAmount: { fontSize: 30, fontWeight: '800', color: colors.dark, marginTop: 6, marginBottom: 14 },
  qrImage: { width: 240, height: 240 },
  qrHint: { fontSize: 13, color: colors.textSecondary, marginTop: 14, textAlign: 'center' },
  expiry: { textAlign: 'center', fontSize: 14, fontWeight: '600', color: colors.textSecondary, marginTop: 12 },
  qrActions: { flexDirection: 'row', justifyContent: 'center', gap: 12, marginTop: 14 },
  qrAction: {
    flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 18, paddingVertical: 12, borderRadius: 14,
    backgroundColor: colors.primaryLight,
  },
  qrActionText: { fontSize: 15, fontWeight: '700', color: colors.primaryDeep },
});
