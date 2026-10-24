import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Modal,
  SafeAreaView,
  ScrollView,
  StatusBar,
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
import { RampActionBar } from '../components/ramps/RampActionBar';
import { RampHero } from '../components/ramps/RampHero';
import { RampReveal } from '../components/ramps/RampReveal';
import { RampStepHeader } from '../components/ramps/RampStepHeader';
import { rampFlowStyles as styles } from '../components/ramps/rampFlowStyles';
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
  value ? `Bs ${Number(value).toLocaleString('es-VE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';
const formatUsd = (value?: string | null) =>
  value ? `$${Number(value).toLocaleString('es-VE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';

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
  const [amountFocused, setAmountFocused] = useState(false);
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
    // A quote belongs to one amount: drop it the moment the amount changes.
    setQuote(null);
    if (order || !amount || !(toNumber(amount) > 0)) return;
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
  const quoteMatches = !!quote?.success && Number(quote.usdAmount) === amountValue;
  const payerOk = cedula.trim().length >= 6 && phone.replace(/\D/g, '').length >= 10 && !!bank;

  const create = async () => {
    if (busy.current || !amountOk || !payerOk || !bank || !quoteMatches) return;
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
  const goBack = () => navigation.goBack();
  const refresh = (orderId: string) => { void refreshOrder(orderId).catch(() => setError(GENERIC)); };

  const errorCard = error ? (
    <View style={[styles.warningCard, local.edge]} accessibilityRole="alert">
      <Icon name="alert-circle" size={18} color={colors.warning.text} />
      <View style={local.flex}>
        <Text style={styles.warningText}>{error}</Text>
      </View>
    </View>
  ) : null;

  const detailRow = (label: string, value?: string | null, last = false) => (
    <View style={[local.detailRow, !last && local.detailDivider]}>
      <View style={local.flex}>
        <Text style={local.detailLabel}>{label}</Text>
        <Text style={local.detailValue} selectable>{value || '—'}</Text>
      </View>
      {value ? (
        <TouchableOpacity accessibilityRole="button" accessibilityLabel={`Copiar ${label}`} onPress={() => copy(value)}
          style={local.copyButton} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
          <Icon name="copy" size={16} color={colors.primaryDark} />
        </TouchableOpacity>
      ) : null}
    </View>
  );

  const statusLink = (orderId: string) => (
    <TouchableOpacity style={[styles.historyPill, local.statusLink]} onPress={() => refresh(orderId)} disabled={loading}
      accessibilityRole="button">
      <Icon name="refresh-cw" size={14} color={colors.primary} />
      <Text style={styles.historyPillText}>Consultar estado</Text>
    </TouchableOpacity>
  );

  // ─── Pago Móvil: the transfer details, then the reference ───
  const renderPagoMovil = (current: VexpayOrder) => {
    const account = current.receivingAccount;
    const ves = current.vesAmount ? String(Number(current.vesAmount)) : null;
    const all = account && ves
      ? `Banco: ${account.bankName} (${account.bankCode})\nTeléfono: ${account.phone}\nRIF: ${account.identification}\nMonto: ${ves}`
      : null;
    return (
      <>
        <RampReveal delay={60}>
          <View style={styles.section}>
            <RampStepHeader number={1} title="Haz el Pago Móvil" meta="Desde tu banco" />
            <View style={styles.quoteCard}>
              <Text style={styles.quoteEyebrow}>Envía exactamente</Text>
              <View style={local.headlineRow}>
                <Text style={[styles.quoteHeadline, local.flex]} adjustsFontSizeToFit numberOfLines={1}>
                  {formatBs(current.vesAmount)}
                </Text>
                {ves ? (
                  <TouchableOpacity accessibilityRole="button" accessibilityLabel="Copiar monto" onPress={() => copy(ves)}
                    style={local.copyBubble}>
                    <Icon name="copy" size={18} color={colors.primaryDark} />
                  </TouchableOpacity>
                ) : null}
              </View>
              <Text style={styles.quoteRate}>Recibes aprox. {formatUsd(current.estimatedUsdt)} en tu cuenta Confío.</Text>
              <View style={styles.quoteDivider} />
              {detailRow('Banco', account ? `${account.bankName} (${account.bankCode})` : null)}
              {detailRow('Teléfono', account?.phone)}
              {detailRow('RIF / Cédula', account?.identification, true)}
              {all ? (
                <TouchableOpacity style={styles.smallGhost} onPress={() => copy(all)} accessibilityRole="button">
                  <Icon name="clipboard" size={16} color={colors.successText} />
                  <Text style={styles.smallGhostText}>Copiar todos los datos</Text>
                </TouchableOpacity>
              ) : null}
              <View style={styles.disclaimerPill}>
                <Icon name="users" size={14} color={colors.primaryDark} />
                <Text style={styles.quoteNote}>Puede pagar otra persona. Envía el monto exacto, en un solo pago.</Text>
              </View>
            </View>
          </View>
        </RampReveal>

        <RampReveal delay={110}>
          <View style={styles.section}>
            <RampStepHeader number={2} title="Confirma tu pago" meta="Referencia y fecha" />
            <View style={styles.inputCard}>
              <Text style={styles.inputLabel}>Referencia del Pago Móvil</Text>
              <TextInput
                accessibilityLabel="Referencia del Pago Móvil"
                value={code}
                onChangeText={text => setCode(text.replace(/\D/g, '').slice(0, 32))}
                keyboardType="number-pad"
                placeholder="Al menos los últimos 6 dígitos"
                placeholderTextColor={colors.textTertiary}
                style={[styles.textInput, local.field]}
                editable={!loading}
              />
              <Text style={[styles.inputLabel, local.spaced]}>¿Cuándo hiciste el pago?</Text>
              <View style={styles.chipRow}>
                {([['today', 'Hoy'], ['yesterday', 'Ayer'], ['other', 'Otro día']] as const).map(([id, label]) => (
                  <TouchableOpacity
                    key={id}
                    accessibilityRole="button"
                    accessibilityState={{ selected: paidWhen === id }}
                    onPress={() => setPaidWhen(id)}
                    style={[styles.chip, paidWhen === id && styles.chipSelected]}
                  >
                    <Text style={[styles.chipText, paidWhen === id && styles.chipTextSelected]}>{label}</Text>
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
                  placeholderTextColor={colors.textTertiary}
                  style={[styles.textInput, local.field, local.spaced]}
                  editable={!loading}
                />
              )}
            </View>
          </View>
        </RampReveal>
      </>
    );
  };

  const renderC2p = (current: VexpayOrder) => (
    <RampReveal delay={60}>
      <View style={styles.section}>
        <RampStepHeader number={1} title="Clave de pago" meta={formatBs(current.vesAmount)} />
        <View style={styles.inputCard}>
          <Text style={styles.inputLabel}>
            {current.otpRequested ? 'Tu banco te envió una clave por SMS' : 'Genera la clave de pago (C2P) en la app de tu banco'}
          </Text>
          <View style={styles.amountInputRow}>
            <TextInput
              accessibilityLabel="Clave de pago"
              value={code}
              onChangeText={text => setCode(text.replace(/\D/g, '').slice(0, 8))}
              keyboardType="number-pad"
              placeholder="••••••"
              placeholderTextColor={colors.textTertiary}
              style={[styles.amountInput, local.otp]}
              editable={!loading}
            />
          </View>
          <Text style={styles.helperText}>
            Se debitarán {formatBs(current.vesAmount)} y recibes aprox. {formatUsd(current.estimatedUsdt)}.
          </Text>
        </View>
      </View>
    </RampReveal>
  );

  // ─── After paying: one timeline, whatever the provider's legs ───
  const renderProgress = (current: VexpayOrder) => {
    const progress = vexpayProgressCopy(current);
    const credited = current.status === 'COMPLETED' && !!current.deliveredUsdt;
    if (current.status === 'FAILED') {
      return (
        <RampReveal delay={60}>
          <View style={styles.emptyStateCard}>
            <View style={[styles.emptyStateIconWrap, local.failIcon]}>
              <Icon name={current.statusDetail === 'cancelled_by_user' ? 'x' : 'alert-triangle'} size={22}
                color={colors.warning.text} />
            </View>
            <Text style={styles.emptyStateTitle}>{progress.title}</Text>
            <Text style={styles.emptyStateText}>{progress.body}</Text>
          </View>
        </RampReveal>
      );
    }
    const stage = timelineStage(current);
    const steps = ['Pago en bolívares', 'Conversión a dólares', 'Dólares en tu cuenta'];
    return (
      <RampReveal delay={60}>
        <View style={styles.reviewCard}>
          <Text style={styles.reviewTitle}>{progress.title}</Text>
          {progress.body ? <Text style={styles.helperText}>{progress.body}</Text> : null}
          <View style={local.timeline}>
            {steps.map((label, index) => {
              const done = credited || index < stage;
              const active = !credited && index === stage;
              return (
                <View key={label} style={styles.timelineRow}>
                  <View style={styles.timelineRail}>
                    <View style={[styles.timelineDot, done && styles.timelineDotDone, active && styles.timelineDotActive]}>
                      {done ? <Icon name="check" size={13} color={colors.white} />
                        : active ? <View style={styles.timelineDotInner} /> : null}
                    </View>
                    {index < steps.length - 1 ? <View style={[styles.timelineLine, done && styles.timelineLineDone]} /> : null}
                  </View>
                  <Text style={[styles.timelineLabel, !done && !active && styles.timelineLabelTodo,
                    active && styles.timelineLabelActive]}>{label}</Text>
                </View>
              );
            })}
          </View>
          <View style={styles.quoteDivider} />
          <View style={styles.reviewRow}>
            <Text style={styles.reviewLabel}>Pagaste</Text>
            <Text style={styles.reviewValue}>{formatBs(current.vesAmount)}</Text>
          </View>
          <View style={styles.reviewRow}>
            <Text style={styles.reviewLabel}>{credited ? 'Recibiste' : 'Recibes aprox.'}</Text>
            <Text style={styles.reviewValueHighlight}>{formatUsd(credited ? current.deliveredUsdt : current.estimatedUsdt)}</Text>
          </View>
          {!credited ? <ActivityIndicator color={colors.primary} accessibilityLabel="Recarga en proceso" /> : null}
        </View>
      </RampReveal>
    );
  };

  // ─── Before the order: amount, method, payer ───
  const renderForm = () => (
    <>
      <RampReveal delay={60}>
        <View style={styles.section}>
          <RampStepHeader number={1} title="Monto" meta="En dólares" />
          <View style={styles.inputCard}>
            <Text style={styles.inputLabel}>¿Cuántos dólares quieres recibir?</Text>
            <View style={[styles.amountInputRow, amountFocused && styles.amountInputRowFocused]}>
              <TextInput
                accessibilityLabel="Monto en dólares"
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
              <View style={styles.currencyBadge}><Text style={styles.currencyBadgeText}>USD</Text></View>
            </View>
            {quote?.minUsd && quote?.maxUsd ? (
              <Text style={styles.limitText}>Entre {formatUsd(quote.minUsd)} y {formatUsd(quote.maxUsd)} por recarga.</Text>
            ) : null}
            {quote?.error ? <Text style={styles.errorText}>{quote.error}</Text> : null}
          </View>
          {quote?.success ? (
            <View style={[styles.quoteCard, local.quoteGap]}>
              <Text style={styles.quoteEyebrow}>Pagarás</Text>
              <Text style={styles.quoteHeadline} adjustsFontSizeToFit numberOfLines={1}>{formatBs(quote.vesAmount)}</Text>
              {quote.rate ? <Text style={styles.quoteRate}>Tasa {formatBs(quote.rate)} por dólar</Text> : null}
              <View style={styles.quoteDivider} />
              <View style={styles.quoteRow}>
                <Text style={styles.quoteLabel}>Pagas</Text>
                <Text style={styles.quoteValue}>{formatUsd(quote.usdAmount)}</Text>
              </View>
              {quote.processorFeeUsd ? (
                <View style={styles.quoteRow}>
                  <Text style={styles.quoteLabel}>{'Comisión del\nprocesador de pagos'}</Text>
                  <Text style={styles.quoteValue}>− {formatUsd(quote.processorFeeUsd)}</Text>
                </View>
              ) : null}
              {quote.confioFeeUsd && Number(quote.confioFeeUsd) > 0 ? (
                <View style={styles.quoteRow}>
                  <Text style={styles.quoteLabel}>Comisión de Confío</Text>
                  <Text style={styles.quoteValue}>− {formatUsd(quote.confioFeeUsd)}</Text>
                </View>
              ) : null}
              <View style={styles.quoteFinalDivider} />
              <View style={styles.quoteFinalRow}>
                <Text style={styles.quoteFinalLabel}>Recibes aprox.</Text>
                <Text style={styles.quoteFinalValue}>{formatUsd(quote.estimatedUsdt)}</Text>
              </View>
              <View style={styles.disclaimerPill}>
                <Icon name="info" size={14} color={colors.primaryDark} />
                <Text style={styles.quoteNote}>Estimado: el monto final se fija al convertir tu pago.</Text>
              </View>
            </View>
          ) : null}
        </View>
      </RampReveal>

      <RampReveal delay={110}>
        <View style={styles.section}>
          <RampStepHeader number={2} title="Cómo pagas" />
          <View style={styles.methodList}>
            {METHODS.map(option => {
              const selected = method === option.id;
              return (
                <TouchableOpacity
                  key={option.id}
                  accessibilityRole="radio"
                  accessibilityState={{ selected }}
                  onPress={() => setMethod(option.id)}
                  activeOpacity={0.8}
                  style={[styles.methodCard, selected && styles.methodCardSelected]}
                >
                  <View style={[styles.methodIcon, selected && styles.methodIconSelected]}>
                    <Icon name={option.icon} size={18} color={selected ? colors.white : colors.primaryDark} />
                  </View>
                  <View style={styles.methodCopy}>
                    <Text style={[styles.methodTitle, selected && styles.methodTitleSelected]}>{option.title}</Text>
                    <Text style={[styles.methodText, selected && styles.methodTextSelected]}>{option.text}</Text>
                  </View>
                  <View style={[styles.radioOuter, selected && styles.radioOuterSelected]}>
                    {selected ? <View style={styles.radioInner} /> : null}
                  </View>
                </TouchableOpacity>
              );
            })}
          </View>
        </View>
      </RampReveal>

      <RampReveal delay={160}>
        <View style={styles.section}>
          <RampStepHeader number={3} title="Quién paga" meta="Puede ser otra persona" />
          <View style={styles.inputCard}>
            <Text style={styles.inputLabel}>Cédula</Text>
            <TextInput accessibilityLabel="Cédula" value={cedula} onChangeText={setCedula} autoCapitalize="characters"
              placeholder="V12345678" placeholderTextColor={colors.textTertiary}
              style={[styles.textInput, local.field]} editable={!loading} />
            <Text style={[styles.inputLabel, local.spaced]}>Teléfono del Pago Móvil</Text>
            <TextInput accessibilityLabel="Teléfono del Pago Móvil" value={phone} onChangeText={setPhone}
              keyboardType="phone-pad" placeholder="0414 1234567" placeholderTextColor={colors.textTertiary}
              style={[styles.textInput, local.field]} editable={!loading} />
            <Text style={[styles.inputLabel, local.spaced]}>Banco</Text>
            <TouchableOpacity accessibilityRole="button" accessibilityLabel="Elegir banco" onPress={() => setBankPicker(true)}
              style={[local.field, local.picker]} disabled={loading}>
              <Text style={bank ? local.pickerValue : local.pickerPlaceholder} numberOfLines={1}>
                {bank ? bank.name : 'Elige el banco'}
              </Text>
              <Icon name="chevron-down" size={18} color={colors.textSecondary} />
            </TouchableOpacity>
          </View>
        </View>
      </RampReveal>
    </>
  );

  const actionBar = () => {
    if (booting) return null;
    if (!order) {
      return (
        <RampActionBar primaryLabel="Continuar" primaryIconName="arrow-right" onPrimaryPress={() => { void create(); }}
          primaryDisabled={!amountOk || !payerOk || !quoteMatches} primaryLoading={loading} />
      );
    }
    const pending = order.status === 'PENDING' && order.canConfirm !== false;
    const cancelProps = order.canCancel
      ? { secondaryLabel: 'Cancelar recarga (no pagué)', onSecondaryPress: () => { void cancel(); } }
      : {};
    if (pending && order.method === 'pago_movil') {
      return (
        <RampActionBar primaryLabel="Ya pagué, confirmar" primaryIconName="check" onPrimaryPress={() => { void confirm(); }}
          primaryDisabled={code.length < 4 || paymentDate === null} primaryLoading={loading} {...cancelProps} />
      );
    }
    if (pending && order.method === 'c2p') {
      return (
        <RampActionBar primaryLabel="Pagar" primaryIconName="lock" onPrimaryPress={() => { void confirm(); }}
          primaryDisabled={code.length < 6} primaryLoading={loading} {...cancelProps} />
      );
    }
    const final = (order.status === 'COMPLETED' && !!order.deliveredUsdt) || order.status === 'FAILED';
    return final ? (
      <RampActionBar primaryLabel="Hacer otra recarga" onPrimaryPress={startOver} secondaryLabel="Volver" onSecondaryPress={goBack} />
    ) : null;
  };

  const pendingOrder = order && order.status === 'PENDING' && order.canConfirm !== false;
  const heroTitle = !order ? 'Recarga con bolívares'
    : pendingOrder && order.method === 'pago_movil' ? 'Paga desde tu banco'
      : pendingOrder ? 'Autoriza el pago' : 'Tu recarga';
  const heroSubtitle = !order
    ? 'Paga por Pago Móvil desde cualquier banco venezolano y recibe dólares en tu cuenta.'
    : pendingOrder ? 'Usa estos datos tal cual. No cierres hasta confirmar.'
      : 'Te avisamos cuando tus dólares estén en tu cuenta.';

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroFieldDark} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled">
        <RampReveal delay={0}>
          <RampHero eyebrow="Venezuela · Pago Móvil" eyebrowCountry="VE" title={heroTitle} subtitle={heroSubtitle}
            onBack={goBack} compact={!!order} />
        </RampReveal>
        {errorCard}
        {booting ? (
          <View style={styles.loadingCard}>
            <ActivityIndicator color={colors.primary} accessibilityLabel="Cargando" />
            <Text style={styles.loadingText}>Cargando…</Text>
          </View>
        ) : !order ? renderForm()
          : pendingOrder && order.method === 'pago_movil' ? renderPagoMovil(order)
            : pendingOrder && order.method === 'c2p' ? renderC2p(order)
              : renderProgress(order)}
        {order && !booting && order.orderId && (order.status === 'PENDING' || order.status === 'PROCESSING')
          ? statusLink(order.orderId) : null}
      </ScrollView>
      {actionBar()}

      <Modal visible={bankPicker} animationType="slide" onRequestClose={() => setBankPicker(false)}>
        <SafeAreaView style={styles.container}>
          <View style={local.modalHeader}>
            <Text style={styles.reviewTitle}>Elige el banco</Text>
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
            getItemLayout={(_, index) => ({ length: BANK_ROW, offset: BANK_ROW * index, index })}
            renderItem={({ item }) => {
              const selected = bank?.code === item.code;
              return (
                <TouchableOpacity
                  accessibilityRole="button"
                  style={local.bankRow}
                  onPress={() => { setBank(item); setBankPicker(false); }}
                >
                  <View style={local.flex}>
                    <Text style={local.pickerValue} numberOfLines={1}>{item.name}</Text>
                    <Text style={local.detailLabel}>{item.code}</Text>
                  </View>
                  {selected ? <Icon name="check" size={18} color={colors.primaryDark} /> : null}
                </TouchableOpacity>
              );
            }}
          />
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

const BANK_ROW = 60;

const METHODS: { id: VexpayMethod; icon: string; title: string; text: string }[] = [
  { id: 'pago_movil', icon: 'smartphone', title: 'Pago Móvil', text: 'Pagas desde la app de tu banco y escribes la referencia aquí.' },
  { id: 'c2p', icon: 'key', title: 'Clave de pago (C2P)', text: 'Escribes aquí la clave de tu banco y se debita al instante.' },
];

/** 0 = paying, 1 = converting, 2 = crediting. */
function timelineStage(order: VexpayOrder): number {
  const detail = order.statusDetail || '';
  if (order.status === 'COMPLETED') return 2;
  if (order.status === 'PROCESSING' && (detail.startsWith('onward_') || detail.startsWith('needs_review'))) return 1;
  return 0;
}

const local = StyleSheet.create({
  flex: { flex: 1 },
  edge: { marginHorizontal: 22, marginTop: 0, marginBottom: 16 },
  spaced: { marginTop: 14 },
  field: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 14, backgroundColor: colors.white,
  },
  picker: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 48, gap: 8 },
  pickerValue: { fontSize: 16, fontWeight: '600', color: colors.dark, flexShrink: 1 },
  pickerPlaceholder: { fontSize: 16, color: colors.textTertiary },
  otp: { letterSpacing: 8, textAlign: 'center' },
  quoteGap: { marginTop: 14 },
  headlineRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  copyBubble: {
    width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.primaryLight,
  },
  detailRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 10 },
  detailDivider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  detailLabel: { fontSize: 12, fontWeight: '600', color: colors.textSecondary },
  detailValue: { fontSize: 16, fontWeight: '700', color: colors.dark, marginTop: 2 },
  copyButton: { padding: 6 },
  statusLink: { marginTop: 4 },
  timeline: { marginTop: 4 },
  failIcon: { backgroundColor: colors.warning.background },
  modalHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: 20 },
  bankRow: {
    height: BANK_ROW, paddingHorizontal: 20, flexDirection: 'row', alignItems: 'center', gap: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
});
