import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Modal,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  View,
} from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import Icon from 'react-native-vector-icons/Feather';
import { useApolloClient } from '@apollo/client';
import { useIsFocused, useNavigation } from '@react-navigation/native';

import { Text, TextInput } from '../components/common/AppText';
import { colors } from '../config/theme';
import { FaceCheckError, isFaceStepUpRequired, withFaceStepUp } from '../services/faceStepUp';
import { getSeparators, sanitizeAmountInput } from '../utils/numberLocale';
import {
  CANCEL_VEXPAY_ON_RAMP,
  CONFIRM_VEXPAY_C2P,
  CREATE_VEXPAY_ON_RAMP,
  VEXPAY_ACTIVE_ON_RAMP_ORDER,
  VEXPAY_BANKS,
  VEXPAY_ON_RAMP_ORDER,
  VEXPAY_ON_RAMP_QUOTE,
  VERIFY_VEXPAY_PAGO_MOVIL,
  VexpayMethod,
  VexpayOrder,
  VexpayQuote,
  isOrderRegression,
  isoDaysAgo,
  parseDayMonthYear,
  vexpayProgressCopy,
} from '../services/vexpayOnRamp';

const POLL_MS = 10_000;
const GENERIC = 'No pudimos conectar. Intenta de nuevo en unos segundos.';

type Bank = { code: string; name: string };

const toNumber = (value: string) => Number(value.replace(',', '.'));
const formatBs = (value?: string | null) =>
  value ? `Bs ${Number(value).toLocaleString('es-VE', { maximumFractionDigits: 2 })}` : '—';

/**
 * Recargar con bolívares (Pago Móvil, VEXPay). One server order per top-up:
 * amount → who pays → Confío Face → pay from the bank app and enter the
 * reference (or a C2P payment key) → wait for the dollars. The order lives on
 * the server, so reopening this screen resumes it.
 */
export default function VePagoMovilReceiveScreen() {
  const client = useApolloClient();
  const navigation = useNavigation<any>();
  const focused = useIsFocused();
  const alive = useRef(true);
  const busy = useRef(false);
  // Bumped when a confirmation or cancellation starts: a status read issued
  // before it is stale and must not overwrite what the mutation returns.
  const generation = useRef(0);
  useEffect(() => () => { alive.current = false; }, []);

  const [booting, setBooting] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [order, setOrderState] = useState<VexpayOrder | null>(null);
  // Every write goes through here: an out-of-order response can never move
  // the order backwards (e.g. reopen the payment form after confirming).
  const setOrder = useCallback((next: VexpayOrder | null) => {
    setOrderState(prev => (next && isOrderRegression(prev, next) ? prev : next));
  }, []);

  const [amount, setAmount] = useState('');
  const [quote, setQuote] = useState<VexpayQuote | null>(null);
  const [method, setMethod] = useState<VexpayMethod>('pago_movil');
  const [cedula, setCedula] = useState('');
  const [phone, setPhone] = useState('');
  const [bank, setBank] = useState<Bank | null>(null);
  const [banks, setBanks] = useState<Bank[]>([]);
  const [bankPicker, setBankPicker] = useState(false);
  const [code, setCode] = useState(''); // bank reference or C2P key
  // When the Pago Móvil was made: VEXPay needs the date unless it was today.
  const [paidWhen, setPaidWhen] = useState<'today' | 'yesterday' | 'other'>('today');
  const [paidOn, setPaidOn] = useState(''); // DD/MM/AAAA when 'other'
  const paymentDate = paidWhen === 'today' ? '' : paidWhen === 'yesterday' ? isoDaysAgo(1) : parseDayMonthYear(paidOn);

  // keepError: after a refused creation, look for an existing order without
  // wiping the reason the user must read.
  const boot = useCallback(async (keepError = false) => {
    setBooting(true);
    if (!keepError) setError('');
    try {
      const [active, bankList] = await Promise.all([
        client.query({ query: VEXPAY_ACTIVE_ON_RAMP_ORDER, fetchPolicy: 'network-only' }),
        client.query({ query: VEXPAY_BANKS, fetchPolicy: 'cache-first' }),
      ]);
      if (!alive.current) return;
      setOrder(active.data?.vexpayActiveOnRampOrder || null);
      setBanks(bankList.data?.vexpayBanks || []);
    } catch {
      if (alive.current && !keepError) setError(GENERIC);
    } finally {
      if (alive.current) setBooting(false);
    }
  }, [client, setOrder]);
  useEffect(() => { void boot(); }, [boot]);

  // Live estimate while typing the amount.
  useEffect(() => {
    if (order || !amount || !(toNumber(amount) > 0)) { setQuote(null); return; }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const r = await client.query({
          query: VEXPAY_ON_RAMP_QUOTE, variables: { usdAmount: String(toNumber(amount)) }, fetchPolicy: 'network-only',
        });
        if (!cancelled && alive.current) setQuote(r.data?.vexpayOnRampQuote || null);
      } catch {
        if (!cancelled && alive.current) setQuote(null);
      }
    }, 450);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [amount, client, order]);

  const refreshOrder = useCallback(async (orderId: string) => {
    const issued = generation.current;
    const r = await client.query({ query: VEXPAY_ON_RAMP_ORDER, variables: { orderId }, fetchPolicy: 'network-only' });
    const next: VexpayOrder | undefined = r.data?.vexpayOnRampOrder;
    if (next?.success && alive.current && issued === generation.current) setOrder(next);
  }, [client, setOrder]);

  // Poll every unfinished order: a confirmation whose response was lost, or a
  // payment confirmed elsewhere, still reaches the screen.
  const unfinished = !!order?.orderId && (order.status === 'PENDING' || order.status === 'PROCESSING'
    // Delivered but not yet credited: keep refreshing until the settled amount arrives.
    || (order.status === 'COMPLETED' && !order.deliveredUsdt));
  useEffect(() => {
    if (!focused || !unfinished || !order?.orderId) return;
    const timer = setInterval(() => { void refreshOrder(order.orderId as string).catch(() => {}); }, POLL_MS);
    return () => clearInterval(timer);
  }, [focused, unfinished, order?.orderId, refreshOrder]);

  const min = Number(quote?.minUsd || 0);
  const max = Number(quote?.maxUsd || 0);
  const amountValue = toNumber(amount);
  const amountOk = amountValue > 0 && (!min || amountValue >= min) && (!max || amountValue <= max);
  const payerOk = cedula.trim().length >= 6 && phone.replace(/\D/g, '').length >= 10 && !!bank;

  const create = async () => {
    if (busy.current || !amountOk || !payerOk || !bank) return;
    busy.current = true;
    setLoading(true);
    setError('');
    try {
      const place = () => client.mutate({
        mutation: CREATE_VEXPAY_ON_RAMP,
        variables: { usdAmount: String(amountValue), method, cedula: cedula.trim(), phone: phone.trim(), bankCode: bank.code },
        fetchPolicy: 'no-cache',
      });
      let response;
      try {
        // Each top-up order spends its own Confío Face check, like Recargar.
        response = await withFaceStepUp('on_ramp', place,
          r => isFaceStepUpRequired(r?.data?.createVexpayOnRamp?.nextStep));
      } catch (faceError) {
        if (faceError instanceof FaceCheckError) return;
        throw faceError;
      }
      const result: VexpayOrder | undefined = response?.data?.createVexpayOnRamp;
      if (!alive.current) return;
      if (result?.nextStep === 'verification') {
        setError(result.error || '');
        navigation.navigate('Verification');
        return;
      }
      if (!result?.success || !result.orderId) {
        setError(result?.error || GENERIC);
        // An existing open order is the one to finish.
        void boot(true);
        return;
      }
      setOrder(result);
      setCode('');
    } catch {
      if (alive.current) setError(GENERIC);
    } finally {
      busy.current = false;
      if (alive.current) setLoading(false);
    }
  };

  const confirm = async () => {
    if (busy.current || !order?.orderId || !code.trim()) return;
    busy.current = true;
    generation.current += 1;
    let refreshAfter = false;
    setLoading(true);
    setError('');
    try {
      const isC2p = order.method === 'c2p';
      const r = await client.mutate({
        mutation: isC2p ? CONFIRM_VEXPAY_C2P : VERIFY_VEXPAY_PAGO_MOVIL,
        variables: isC2p
          ? { orderId: order.orderId, otp: code.trim() }
          : { orderId: order.orderId, reference: code.trim(), paymentDate: paymentDate || undefined },
        fetchPolicy: 'no-cache',
      });
      const result: VexpayOrder | undefined = isC2p ? r.data?.confirmVexpayC2p : r.data?.verifyVexpayPagoMovil;
      if (!alive.current) return;
      if (!result?.success) {
        setError(result?.error || GENERIC);
        // The server may have moved the order on (e.g. closed a failed charge).
        refreshAfter = true;
        return;
      }
      setOrder(result);
    } catch {
      // The bank may already have taken the money: never invite a second payment.
      if (alive.current) setError('No pudimos confirmar todavía. No pagues de nuevo; consulta el estado en unos segundos.');
      refreshAfter = true;
    } finally {
      busy.current = false;
      // Reads issued while the mutation ran may predate its effect.
      generation.current += 1;
      if (alive.current) setLoading(false);
      if (refreshAfter && order.orderId) void refreshOrder(order.orderId).catch(() => {});
    }
  };

  const cancel = async () => {
    if (busy.current || !order?.orderId) return;
    busy.current = true;
    generation.current += 1;
    let refreshAfter = false;
    setLoading(true);
    setError('');
    try {
      const r = await client.mutate({ mutation: CANCEL_VEXPAY_ON_RAMP, variables: { orderId: order.orderId }, fetchPolicy: 'no-cache' });
      const result: VexpayOrder | undefined = r.data?.cancelVexpayOnRamp;
      if (!alive.current) return;
      if (!result?.success) {
        setError(result?.error || GENERIC);
        refreshAfter = true;
        return;
      }
      setOrder(result);
    } catch {
      if (alive.current) setError(GENERIC);
    } finally {
      busy.current = false;
      generation.current += 1;
      if (alive.current) setLoading(false);
      if (refreshAfter && order.orderId) void refreshOrder(order.orderId).catch(() => {});
    }
  };

  const startOver = () => {
    setOrder(null); setAmount(''); setQuote(null); setCode(''); setError('');
  };

  const copy = (value: string) => Clipboard.setString(value);

  const button = (title: string, onPress: () => void, disabled = false, secondary = false) => (
    <TouchableOpacity
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={[styles.button, secondary && styles.buttonSecondary, disabled && styles.disabled]}
    >
      <Text style={[styles.buttonText, secondary && styles.buttonTextSecondary]}>{title}</Text>
    </TouchableOpacity>
  );

  const copyRow = (label: string, value?: string | null) => (
    <View style={styles.copyRow}>
      <View style={styles.copyText}>
        <Text style={styles.label}>{label}</Text>
        <Text style={styles.value} selectable>{value || '—'}</Text>
      </View>
      {value ? (
        <TouchableOpacity accessibilityRole="button" accessibilityLabel={`Copiar ${label}`} onPress={() => copy(value)} style={styles.copyButton}>
          <Icon name="copy" size={18} color={colors.primaryDark} />
        </TouchableOpacity>
      ) : null}
    </View>
  );

  const pendingActions = (current: VexpayOrder) => (
    <>
      {button('Consultar estado', () => { void refreshOrder(current.orderId as string).catch(() => setError(GENERIC)); }, loading, true)}
      {current.canCancel && button('Cancelar recarga (no pagué)', () => { void cancel(); }, loading, true)}
    </>
  );

  const renderOrder = (current: VexpayOrder) => {
    // The form shows only while the server accepts a confirmation for it.
    const pending = current.status === 'PENDING' && current.canConfirm !== false;
    if (pending && current.method === 'pago_movil') {
      const account = current.receivingAccount;
      return (
        <View style={styles.card}>
          <Text style={styles.heading}>Haz un Pago Móvil desde tu banco</Text>
          <Text style={styles.note}>Envía exactamente este monto. Puede pagar otra persona.</Text>
          {copyRow('Monto', current.vesAmount ? String(Number(current.vesAmount)) : null)}
          {copyRow('Banco', account ? `${account.bankName} (${account.bankCode})` : null)}
          {copyRow('Teléfono', account?.phone)}
          {copyRow('RIF / Cédula', account?.identification)}
          <Text style={styles.heading}>Referencia del pago</Text>
          <TextInput
            accessibilityLabel="Referencia del Pago Móvil"
            value={code}
            onChangeText={text => setCode(text.replace(/\D/g, '').slice(0, 32))}
            keyboardType="number-pad"
            placeholder="Al menos los últimos 6 dígitos"
            style={styles.input}
            editable={!loading}
          />
          <Text style={styles.heading}>¿Cuándo hiciste el pago?</Text>
          <View style={styles.segment}>
            {([['today', 'Hoy'], ['yesterday', 'Ayer'], ['other', 'Otro día']] as const).map(([id, label]) => (
              <TouchableOpacity
                key={id}
                accessibilityRole="button"
                accessibilityState={{ selected: paidWhen === id }}
                onPress={() => setPaidWhen(id)}
                style={[styles.segmentItem, paidWhen === id && styles.segmentActive]}
              >
                <Text style={[styles.segmentText, paidWhen === id && styles.segmentTextActive]}>{label}</Text>
              </TouchableOpacity>
            ))}
          </View>
          {paidWhen === 'other' && (
            <TextInput
              accessibilityLabel="Fecha del pago"
              value={paidOn}
              onChangeText={setPaidOn}
              keyboardType="numbers-and-punctuation"
              placeholder="DD/MM/AAAA"
              style={styles.input}
              editable={!loading}
            />
          )}
          {button('Ya pagué, confirmar', () => { void confirm(); }, loading || code.length < 4 || paymentDate === null)}
          {pendingActions(current)}
        </View>
      );
    }
    if (pending && current.method === 'c2p') {
      return (
        <View style={styles.card}>
          <Text style={styles.heading}>Escribe tu clave de pago</Text>
          <Text style={styles.note}>
            {current.otpRequested
              ? 'Tu banco te envió una clave por SMS.'
              : 'Genera la clave de pago (C2P) en la app de tu banco.'}{' '}
            Se debitarán {formatBs(current.vesAmount)}.
          </Text>
          <TextInput
            accessibilityLabel="Clave de pago"
            value={code}
            onChangeText={text => setCode(text.replace(/\D/g, '').slice(0, 8))}
            keyboardType="number-pad"
            placeholder="6 a 8 dígitos"
            style={styles.input}
            editable={!loading}
          />
          {button('Pagar', () => { void confirm(); }, loading || code.length < 6)}
          {pendingActions(current)}
        </View>
      );
    }
    const progress = vexpayProgressCopy(current);
    const credited = current.status === 'COMPLETED' && !!current.deliveredUsdt;
    const final = credited || current.status === 'FAILED';
    return (
      <View style={styles.card}>
        <Text style={styles.heading}>{progress.title}</Text>
        {progress.body ? <Text>{progress.body}</Text> : null}
        <Text style={styles.note}>
          {credited
            ? `Recibiste ${current.deliveredUsdt} dólares.`
            : `Recibirás aproximadamente ${current.estimatedUsdt} dólares.`}
        </Text>
        {!final && <ActivityIndicator accessibilityLabel="Recarga en proceso" />}
        {!final && button('Consultar estado', () => { void refreshOrder(current.orderId as string).catch(() => setError(GENERIC)); }, loading, true)}
        {final && button('Hacer otra recarga', startOver)}
        {final && button('Volver', () => navigation.goBack(), false, true)}
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.root}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <TouchableOpacity accessibilityRole="button" accessibilityLabel="Volver" onPress={() => navigation.goBack()}>
          <Icon name="arrow-left" size={24} color={colors.dark} />
        </TouchableOpacity>
        <Text style={styles.title}>Recargar con bolívares</Text>
        <Text style={styles.subtitle}>Paga por Pago Móvil desde cualquier banco y recibe dólares en tu cuenta.</Text>
        {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
        {booting ? <ActivityIndicator accessibilityLabel="Cargando" /> : order ? renderOrder(order) : (
          <>
            <View style={styles.card}>
              <Text style={styles.heading}>¿Cuántos dólares quieres recibir?</Text>
              <TextInput
                accessibilityLabel="Monto en dólares"
                value={amount}
                keyboardType="decimal-pad"
                onChangeText={text => setAmount(prev => sanitizeAmountInput(text, 2, undefined, prev))}
                placeholder={`0${getSeparators().decimal}00`}
                style={[styles.input, styles.amountInput]}
                editable={!loading}
              />
              {quote?.success ? (
                <Text style={styles.note}>
                  Pagarás {formatBs(quote.vesAmount)} · recibirás aprox. {quote.estimatedUsdt} dólares
                  {min || max ? `\nEntre $${quote.minUsd} y $${quote.maxUsd} por recarga.` : ''}
                </Text>
              ) : quote?.error ? <Text style={styles.error}>{quote.error}</Text> : null}
            </View>

            <View style={styles.card}>
              <Text style={styles.heading}>¿Cómo vas a pagar?</Text>
              <View style={styles.segment}>
                {([['pago_movil', 'Pago Móvil'], ['c2p', 'Clave de pago']] as const).map(([id, label]) => (
                  <TouchableOpacity
                    key={id}
                    accessibilityRole="button"
                    accessibilityState={{ selected: method === id }}
                    onPress={() => setMethod(id)}
                    style={[styles.segmentItem, method === id && styles.segmentActive]}
                  >
                    <Text style={[styles.segmentText, method === id && styles.segmentTextActive]}>{label}</Text>
                  </TouchableOpacity>
                ))}
              </View>
              <Text style={styles.note}>
                {method === 'pago_movil'
                  ? 'Envías el Pago Móvil desde la app de tu banco y luego escribes la referencia aquí.'
                  : 'Escribes aquí la clave de pago de tu banco y se debita al instante.'}
              </Text>
            </View>

            <View style={styles.card}>
              <Text style={styles.heading}>¿Quién paga?</Text>
              <Text style={styles.note}>Datos de la cuenta que hace el pago. Puede ser otra persona.</Text>
              <TextInput accessibilityLabel="Cédula" value={cedula} onChangeText={setCedula} autoCapitalize="characters"
                placeholder="Cédula (V12345678)" style={styles.input} editable={!loading} />
              <TextInput accessibilityLabel="Teléfono del Pago Móvil" value={phone} onChangeText={setPhone}
                keyboardType="phone-pad" placeholder="Teléfono (0414 1234567)" style={styles.input} editable={!loading} />
              <TouchableOpacity accessibilityRole="button" onPress={() => setBankPicker(true)} style={styles.input} disabled={loading}>
                <Text style={bank ? styles.value : styles.placeholder}>{bank ? bank.name : 'Banco'}</Text>
              </TouchableOpacity>
            </View>

            {button('Continuar', () => { void create(); }, loading || !amountOk || !payerOk || !quote?.success)}
            {loading && <ActivityIndicator accessibilityLabel="Creando recarga" />}
          </>
        )}
      </ScrollView>

      <Modal visible={bankPicker} animationType="slide" onRequestClose={() => setBankPicker(false)}>
        <SafeAreaView style={styles.root}>
          <View style={styles.modalHeader}>
            <Text style={styles.heading}>Elige el banco</Text>
            <TouchableOpacity accessibilityRole="button" accessibilityLabel="Cerrar" onPress={() => setBankPicker(false)}>
              <Icon name="x" size={24} color={colors.dark} />
            </TouchableOpacity>
          </View>
          <FlatList
            data={banks}
            keyExtractor={item => item.code}
            initialNumToRender={20}
            maxToRenderPerBatch={10}
            windowSize={21}
            getItemLayout={(_, index) => ({ length: 56, offset: 56 * index, index })}
            renderItem={({ item }) => (
              <TouchableOpacity
                accessibilityRole="button"
                style={styles.bankRow}
                onPress={() => { setBank(item); setBankPicker(false); }}
              >
                <Text style={styles.value}>{item.name}</Text>
                <Text style={styles.note}>{item.code}</Text>
              </TouchableOpacity>
            )}
          />
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  content: { padding: 20, gap: 16 },
  title: { fontSize: 24, fontWeight: '700', color: colors.dark },
  subtitle: { fontSize: 15, color: colors.text.secondary },
  card: { padding: 20, gap: 12, backgroundColor: colors.white, borderRadius: 20, borderWidth: 1, borderColor: colors.primaryLight },
  heading: { fontSize: 16, fontWeight: '600', color: colors.dark },
  note: { fontSize: 13, color: colors.text.secondary },
  error: { color: colors.danger },
  label: { fontSize: 12, color: colors.text.secondary },
  value: { fontSize: 16, color: colors.dark },
  placeholder: { fontSize: 16, color: colors.text.secondary },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, padding: 12, fontSize: 16, color: colors.dark },
  amountInput: { fontSize: 24 },
  button: { padding: 15, borderRadius: 12, backgroundColor: colors.primaryDark, alignItems: 'center' },
  buttonSecondary: { backgroundColor: colors.primaryLight },
  buttonText: { fontWeight: '600', color: colors.white },
  buttonTextSecondary: { color: colors.primaryDark },
  disabled: { opacity: 0.45 },
  segment: { flexDirection: 'row', backgroundColor: colors.background, borderRadius: 10, padding: 4 },
  segmentItem: { flex: 1, paddingVertical: 10, borderRadius: 8, alignItems: 'center' },
  segmentActive: { backgroundColor: colors.white },
  segmentText: { color: colors.text.secondary, fontWeight: '600' },
  segmentTextActive: { color: colors.primaryDark },
  copyRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  copyText: { flex: 1 },
  copyButton: { padding: 8 },
  modalHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: 20 },
  bankRow: { height: 56, paddingHorizontal: 20, justifyContent: 'center', borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
});
