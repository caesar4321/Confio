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
import Icon from 'react-native-vector-icons/Feather';
import { gql, useApolloClient, useQuery } from '@apollo/client';
import { useIsFocused, useNavigation } from '@react-navigation/native';

import { Text, TextInput } from '../components/common/AppText';
import { colors } from '../config/theme';
import { RampActionBar } from '../components/ramps/RampActionBar';
import { RampHero } from '../components/ramps/RampHero';
import { RampReveal } from '../components/ramps/RampReveal';
import { RampStepHeader } from '../components/ramps/RampStepHeader';
import { rampFlowStyles as styles } from '../components/ramps/rampFlowStyles';
import { FaceCheckError, isFaceStepUpRequired, withFaceStepUp } from '../services/faceStepUp';
import { fundUsdtDestination } from '../services/cusdPlusVault';
import { getActiveEvmWallet } from '../services/secureDeterministicWallet';
import { isOutcomeUnknown } from '../services/evmWallet';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { useAccount } from '../contexts/AccountContext';
import { getSeparators, sanitizeAmountInput } from '../utils/numberLocale';
import { VE_BANKS } from '../services/vePagoMovilTopUp';
import {
  VeAgendaPicker, VeAgendaSaveToggle, initialVeAgendaSave, saveVeAgendaEntry, veAgendaSaveReady, vePickFields,
} from '../components/agenda/VeAgendaPicker';
import { AgendaEntry } from '../services/agenda';
import {
  CANCEL_VE_SEND,
  CREATE_VE_SEND,
  REPORT_VE_SEND_FUNDING,
  START_VE_SEND_FUNDING,
  VE_ACTIVE_SEND,
  VE_SEND_ORDER,
  VE_SEND_QUOTE,
  VeSendOrder,
  VeSendQuote,
  sendStage,
  sendCopy,
} from '../services/vePagoMovilSend';

// The Retiro funding path redeems from these; served, never hardcoded.
const SEND_FUNDING_PARAMS = gql`
  query VePagoMovilSendFundingParams {
    cusdPlusConvertParams { vaultAddress cusdAddress }
  }
`;

const POLL_MS = 10_000;
const GENERIC = 'No pudimos conectar. Intenta de nuevo en unos segundos.';
const UNKNOWN_SEND = 'No pudimos confirmar si tus dólares salieron. No envíes de nuevo: revisa el estado en unos minutos.';

type Bank = { code: string; name: string };

const toNumber = (value: string) => Number(value.replace(',', '.'));
const money = (value?: string | number | null, digits = 2) =>
  value === null || value === undefined || value === '' ? '—'
    : Number(value).toLocaleString('es-VE', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const formatBs = (value?: string | null) => (value ? `Bs ${money(value)}` : '—');
const formatUsd = (value?: string | number | null) => (value === null || value === undefined || value === '' ? '—' : `$${money(value)}`);
const isOpen = (order: VeSendOrder | null) => !!order?.orderId && (order.status === 'PENDING' || order.status === 'PROCESSING');

/**
 * Enviar bolívares por Pago Móvil. One server order per send:
 * recipient → amount → Confío Face → the dollars leave in one sponsored
 * batch to the server-vouched deposit address → the provider converts → the server
 * pays the recipient. The order lives on the server, so reopening resumes it.
 */
export default function VePagoMovilSendScreen() {
  const client = useApolloClient();
  const navigation = useNavigation<any>();
  const focused = useIsFocused();
  const alive = useRef(true);
  const busy = useRef(false);
  // Bumped around every mutation: a read issued before it is stale.
  const generation = useRef(0);
  useEffect(() => () => { alive.current = false; }, []);

  const { savings, cusdBalanceUsd } = useSavingsPortfolio();
  // Funding signs with the ACTIVE account's wallet: only the personal one.
  const { activeAccount } = useAccount();
  const personal = activeAccount?.type === 'personal';
  const available = (savings?.balanceUsd || 0) + (cusdBalanceUsd || 0);
  const { data: fundingParams } = useQuery(SEND_FUNDING_PARAMS);
  const vaultAddress: string = fundingParams?.cusdPlusConvertParams?.vaultAddress || '';
  const cusdAddress: string = fundingParams?.cusdPlusConvertParams?.cusdAddress || '';
  // The funding claim is single-use: never spend it before the redeem
  // contracts are known.
  const fundingReady = !!cusdAddress;

  const [booting, setBooting] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [order, setOrder] = useState<VeSendOrder | null>(null);
  const [amount, setAmount] = useState('');
  const [amountFocused, setAmountFocused] = useState(false);
  const [quote, setQuote] = useState<VeSendQuote | null>(null);
  const [cedula, setCedula] = useState('');
  const [phone, setPhone] = useState('');
  const [bank, setBank] = useState<Bank | null>(null);
  const [banks, setBanks] = useState<Bank[]>([]);
  const [bankPicker, setBankPicker] = useState(false);
  const [checked, setChecked] = useState(false);
  const [agendaSave, setAgendaSave] = useState(() => initialVeAgendaSave('third_party'));

  const boot = useCallback(async (keepError = false) => {
    setBooting(true);
    if (!keepError) setError('');
    try {
      const [active, bankList] = await Promise.all([
        client.query({ query: VE_ACTIVE_SEND, fetchPolicy: 'network-only' }),
        client.query({ query: VE_BANKS, fetchPolicy: 'cache-first' }),
      ]);
      if (!alive.current) return;
      setOrder(active.data?.vePagomovilActiveSend || null);
      setBanks(bankList.data?.vePagomovilBanks || []);
    } catch {
      if (alive.current && !keepError) setError(GENERIC);
    } finally {
      if (alive.current) setBooting(false);
    }
  }, [client]);
  useEffect(() => { void boot(); }, [boot]);
  // The bank list can fail on its own (the server answers [] on any provider
  // error): offer a retry instead of an empty picker.
  const reloadBanks = useCallback(async () => {
    try {
      const r = await client.query({ query: VE_BANKS, fetchPolicy: 'network-only' });
      if (alive.current) setBanks(r.data?.vePagomovilBanks || []);
    } catch {
      // the empty state stays, with its retry
    }
  }, [client]);

  useEffect(() => {
    // A quote belongs to one amount: drop it the moment the amount changes.
    setQuote(null);
    if (order || !amount || !(toNumber(amount) > 0)) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const r = await client.query({
          query: VE_SEND_QUOTE, variables: { usdAmount: String(toNumber(amount)) }, fetchPolicy: 'network-only',
        });
        if (!cancelled && alive.current) setQuote(r.data?.vePagomovilSendQuote || null);
      } catch {
        if (!cancelled && alive.current) setQuote(null);
      }
    }, 450);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [amount, client, order]);

  const refreshOrder = useCallback(async (orderId: string) => {
    const issued = generation.current;
    const r = await client.query({ query: VE_SEND_ORDER, variables: { orderId }, fetchPolicy: 'network-only' });
    const next: VeSendOrder | undefined = r.data?.vePagomovilSendOrder;
    if (next?.success && alive.current && issued === generation.current) setOrder(next);
  }, [client]);

  useEffect(() => {
    if (!focused || !isOpen(order) || !order?.orderId) return;
    const timer = setInterval(() => { void refreshOrder(order.orderId as string).catch(() => {}); }, POLL_MS);
    return () => clearInterval(timer);
  }, [focused, order, refreshOrder]);

  const min = Number(quote?.minUsd || 0);
  const max = Number(quote?.maxUsd || 0);
  const amountValue = toNumber(amount);
  const amountOk = amountValue > 0 && (!min || amountValue >= min) && (!max || amountValue <= max)
    && amountValue <= available + 1e-9;
  const quoteMatches = !!quote?.success && Number(quote.usdAmount) === amountValue;
  const recipientOk = cedula.trim().length >= 6 && phone.replace(/\D/g, '').length >= 10 && !!bank
    && veAgendaSaveReady(agendaSave);

  const pickFromAgenda = (entry: AgendaEntry) => {
    const fields = vePickFields(entry);
    setCedula(fields.cedula);
    setPhone(fields.phone);
    setBank(banks.find(item => item.code === fields.bankCode) || null);
    // Already saved: nothing to save again.
    setAgendaSave(initialVeAgendaSave('third_party'));
  };

  /** Claim the order's single funding, pay it, tell the server. */
  const fund = async (orderId: string) => {
    if (!personal) {
      setError('Cambia a tu cuenta personal para continuar este envío.');
      return;
    }
    if (!fundingReady) {
      setError(GENERIC);
      return;
    }
    // Pin the signer before the single-use claim: the personal wallet, and
    // only if it is the wallet this order was made for. An account switch
    // mid-flow can then never debit another wallet.
    const wallet = await getActiveEvmWallet({ type: 'personal', index: 0 });
    const expected = (order?.orderId === orderId ? order.wallet : null)
      || (await client.query({ query: VE_SEND_ORDER, variables: { orderId }, fetchPolicy: 'network-only' }))
        .data?.vePagomovilSendOrder?.wallet;
    if (!expected || wallet.address.toLowerCase() !== String(expected).toLowerCase()) {
      if (alive.current) setError('Este envío pertenece a otra cuenta. No se envió nada.');
      return;
    }
    const start = await client.mutate({
      mutation: START_VE_SEND_FUNDING, variables: { orderId }, fetchPolicy: 'no-cache',
    });
    const claimed: VeSendOrder | undefined = start.data?.startVePagomovilSendFunding;
    if (!alive.current) return;
    if (!claimed?.success || !claimed.funding || claimed.funding.network !== 'BSC'
        || !/^0x[0-9a-fA-F]{40}$/.test(claimed.funding.depositAddress)
        || !/^[1-9][0-9]*$/.test(claimed.funding.depositAmountWei)) {
      setError(claimed?.error || GENERIC);
      void refreshOrder(orderId).catch(() => {});
      return;
    }
    setOrder({ ...claimed, funding: null });
    // A bridge target expires: never sign for one that is about to (e.g. the
    // phone slept after the claim). Nothing is sent; the send can be cancelled.
    if (claimed.funding.expiresAt && claimed.funding.expiresAt * 1000 < Date.now() + 60_000) {
      if (alive.current) setError('El envío venció antes de firmarlo. No se envió nada; cancélalo y vuelve a intentarlo.');
      return;
    }
    let txHash: string | null = null;
    try {
      // The audited Retiro batch (redeem with fee + exact transfer), signed
      // by the pinned wallet.
      const res = await fundUsdtDestination({
        to: claimed.funding.depositAddress,
        amountWei: BigInt(claimed.funding.depositAmountWei),
        grossDebitWei: claimed.funding.grossDebitAmountWei ? BigInt(claimed.funding.grossDebitAmountWei) : null,
        vaultAddress: vaultAddress || null,
        cusdAddress,
        wallet,
        // Never signed to outlive the bridge target.
        notAfter: claimed.funding.expiresAt ? claimed.funding.expiresAt - 30 : undefined,
      });
      txHash = res.txHash;
    } catch (fundError: any) {
      if (!isOutcomeUnknown(fundError)) {
        // Refused before anything was broadcast.
        if (alive.current) {
          setError(fundError?.name === 'InsufficientWithdrawableError'
            ? 'No tienes saldo suficiente. No se envió nada.'
            : 'No se envió nada. Tu dinero sigue en tu cuenta. Podrás cancelar este envío en unos minutos.');
        }
        return;
      }
      // Broadcast, verdict lost: never a failure, the chain decides.
      if (alive.current) setError(UNKNOWN_SEND);
    }
    const report = await client.mutate({
      mutation: REPORT_VE_SEND_FUNDING, variables: { orderId, txHash }, fetchPolicy: 'no-cache',
    }).catch(() => null);
    const reported: VeSendOrder | undefined = report?.data?.reportVePagomovilSendFunding;
    if (alive.current && reported?.success) setOrder(reported);
  };

  const send = async () => {
    if (busy.current || !amountOk || !recipientOk || !checked || !bank || !quoteMatches) return;
    busy.current = true;
    generation.current += 1;
    setLoading(true);
    setError('');
    let created: string | null = null;
    try {
      const place = () => client.mutate({
        mutation: CREATE_VE_SEND,
        variables: { usdAmount: String(amountValue), cedula: cedula.trim(), phone: phone.trim(), bankCode: bank.code },
        fetchPolicy: 'no-cache',
      });
      let response;
      try {
        response = await withFaceStepUp('withdrawal', place,
          r => isFaceStepUpRequired(r?.data?.createVePagomovilSend?.nextStep));
      } catch (faceError) {
        if (faceError instanceof FaceCheckError) return;
        throw faceError;
      }
      const result: VeSendOrder | undefined = response?.data?.createVePagomovilSend;
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
      created = result.orderId;
      setOrder(result);
      void saveVeAgendaEntry(client, agendaSave, { cedula: cedula.trim(), phone: phone.trim(), bankCode: bank.code });
      await fund(result.orderId);
    } catch {
      // Once the order exists, money may be moving: only the status decides.
      if (alive.current) setError(created ? UNKNOWN_SEND : GENERIC);
    } finally {
      busy.current = false;
      generation.current += 1;
      if (alive.current) setLoading(false);
      if (created) void refreshOrder(created).catch(() => {});
    }
  };

  const resume = async () => {
    if (busy.current || !order?.orderId || !order.canFund) return;
    busy.current = true;
    generation.current += 1;
    setLoading(true);
    setError('');
    try {
      await fund(order.orderId);
    } catch {
      if (alive.current) setError(UNKNOWN_SEND);
    } finally {
      busy.current = false;
      generation.current += 1;
      if (alive.current) setLoading(false);
      void refreshOrder(order.orderId).catch(() => {});
    }
  };

  const cancel = async () => {
    if (busy.current || !order?.orderId) return;
    busy.current = true;
    generation.current += 1;
    setLoading(true);
    setError('');
    try {
      const r = await client.mutate({ mutation: CANCEL_VE_SEND, variables: { orderId: order.orderId }, fetchPolicy: 'no-cache' });
      const result: VeSendOrder | undefined = r.data?.cancelVePagomovilSend;
      if (!alive.current) return;
      if (result?.success) setOrder(result);
      else setError(result?.error || GENERIC);
    } catch {
      if (alive.current) setError(GENERIC);
    } finally {
      busy.current = false;
      generation.current += 1;
      if (alive.current) setLoading(false);
      void refreshOrder(order.orderId).catch(() => {});
    }
  };

  const startOver = () => {
    setOrder(null); setAmount(''); setQuote(null); setChecked(false); setError('');
  };
  const goBack = () => navigation.goBack();

  const errorCard = error ? (
    <View style={[styles.warningCard, local.edge]} accessibilityRole="alert">
      <Icon name="alert-circle" size={18} color={colors.warning.text} />
      <View style={local.flex}><Text style={styles.warningText}>{error}</Text></View>
    </View>
  ) : null;

  const renderForm = () => (
    <>
      <RampReveal delay={60}>
        <View style={styles.section}>
          <RampStepHeader number={1} title="Destinatario" meta="Tú u otra persona" />
          <View style={styles.inputCard}>
            <VeAgendaPicker disabled={loading} onPick={pickFromAgenda} />
            <Text style={styles.inputLabel}>Cédula</Text>
            <TextInput accessibilityLabel="Cédula del destinatario" value={cedula} onChangeText={setCedula}
              autoCapitalize="characters" placeholder="V12345678" placeholderTextColor={colors.textTertiary}
              style={[styles.textInput, local.field]} editable={!loading} />
            <Text style={[styles.inputLabel, local.spaced]}>Teléfono del Pago Móvil</Text>
            <TextInput accessibilityLabel="Teléfono del destinatario" value={phone} onChangeText={setPhone}
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
            <VeAgendaSaveToggle value={agendaSave} onChange={setAgendaSave} disabled={loading} />
          </View>
        </View>
      </RampReveal>

      <RampReveal delay={110}>
        <View style={styles.section}>
          <RampStepHeader number={2} title="Monto" meta={`Disponible ${formatUsd(available)}`} />
          <View style={styles.inputCard}>
            <Text style={styles.inputLabel}>¿Cuántos dólares quieres enviar?</Text>
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
            {min && amountValue > 0 && amountValue < min ? (
              <Text style={styles.limitText}>El mínimo es {formatUsd(quote?.minUsd as string)}.</Text>
            ) : null}
            {amountValue > available + 1e-9 ? <Text style={styles.errorText}>Supera tu saldo disponible.</Text> : null}
            {quote?.error ? <Text style={styles.errorText}>{quote.error}</Text> : null}
          </View>
          {quote?.success ? (
            <View style={[styles.quoteCard, local.quoteGap]}>
              <Text style={styles.quoteEyebrow}>Llega aprox.</Text>
              <Text style={styles.quoteHeadline} adjustsFontSizeToFit numberOfLines={1}>{formatBs(quote.estimatedVes)}</Text>
              {quote.rate ? <Text style={styles.quoteRate}>Tasa {formatBs(quote.rate)} por dólar</Text> : null}
              <View style={styles.quoteDivider} />
              <View style={styles.quoteRow}>
                <Text style={styles.quoteLabel}>Envías</Text>
                <Text style={styles.quoteValue}>{formatUsd(quote.usdAmount)}</Text>
              </View>
              {Number(quote.confioFeeUsd) > 0 ? (
                <View style={styles.quoteRow}>
                  <Text style={styles.quoteLabel}>Comisión de Confío</Text>
                  <Text style={styles.quoteValue}>− {formatUsd(quote.confioFeeUsd)}</Text>
                </View>
              ) : null}
              <View style={styles.quoteRow}>
                <Text style={styles.quoteLabel}>{'Comisión del\nprocesador de pagos'}</Text>
                <Text style={styles.quoteValue}>− {formatUsd(quote.processorFeeUsd)}</Text>
              </View>
              <View style={styles.disclaimerPill}>
                <Icon name="info" size={14} color={colors.primaryDark} />
                <Text style={styles.quoteNote}>Estimado: los bolívares finales se fijan al convertir tu envío.</Text>
              </View>
            </View>
          ) : null}
        </View>
      </RampReveal>

      <RampReveal delay={160}>
        <View style={styles.section}>
          <RampStepHeader number={3} title="Confirma" />
          <TouchableOpacity style={styles.checkboxRow} onPress={() => setChecked(value => !value)}
            accessibilityRole="checkbox" accessibilityState={{ checked }} disabled={loading}>
            <View style={[styles.checkbox, checked && styles.checkboxChecked]}>
              {checked ? <Icon name="check" size={14} color={colors.white} /> : null}
            </View>
            <Text style={styles.checkboxText}>
              Revisé la cédula, el teléfono y el banco. Un Pago Móvil enviado no se puede revertir.
            </Text>
          </TouchableOpacity>
        </View>
      </RampReveal>
    </>
  );

  const renderOrder = (current: VeSendOrder) => {
    const copy = sendCopy(current);
    if (current.status === 'FAILED') {
      return (
        <RampReveal delay={60}>
          <View style={styles.emptyStateCard}>
            <View style={[styles.emptyStateIconWrap, local.failIcon]}>
              <Icon name={current.statusDetail === 'cancelled_by_user' ? 'x' : 'alert-triangle'} size={22} color={colors.warning.text} />
            </View>
            <Text style={styles.emptyStateTitle}>{copy.title}</Text>
            <Text style={styles.emptyStateText}>{copy.body}</Text>
          </View>
        </RampReveal>
      );
    }
    const delivered = current.status === 'COMPLETED';
    const stage = sendStage(current);
    const steps = ['Envío creado', 'Dólares enviados', 'Conversión a bolívares', 'Bolívares entregados'];
    const recipient = current.beneficiary;
    return (
      <RampReveal delay={60}>
        <View style={styles.reviewCard}>
          <Text style={styles.reviewTitle}>{copy.title}</Text>
          {copy.body ? <Text style={styles.helperText}>{copy.body}</Text> : null}
          <View style={local.timeline}>
            {steps.map((label, index) => {
              const done = delivered || index < stage;
              const active = !delivered && index === stage;
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
          {recipient ? (
            <View style={styles.reviewRow}>
              <Text style={styles.reviewLabel}>Para</Text>
              <Text style={styles.reviewValue}>{`${recipient.cedula}\n${recipient.phone}\n${recipient.bankName}`}</Text>
            </View>
          ) : null}
          <View style={styles.reviewRow}>
            <Text style={styles.reviewLabel}>Envías</Text>
            <Text style={styles.reviewValue}>{formatUsd(current.usdAmount)}</Text>
          </View>
          <View style={styles.reviewRow}>
            <Text style={styles.reviewLabel}>{current.vesAmount ? 'Llegan' : 'Llegan aprox.'}</Text>
            <Text style={styles.reviewValueHighlight}>{formatBs(current.vesAmount || current.estimatedVes)}</Text>
          </View>
          {current.bankReference ? (
            <View style={styles.reviewRow}>
              <Text style={styles.reviewLabel}>Referencia</Text>
              <Text style={styles.reviewValue} selectable>{current.bankReference}</Text>
            </View>
          ) : null}
          {!delivered && !current.canFund ? <ActivityIndicator color={colors.primary} accessibilityLabel="Envío en proceso" /> : null}
        </View>
      </RampReveal>
    );
  };

  const actionBar = () => {
    if (booting) return null;
    if (!order) {
      return (
        <RampActionBar primaryLabel="Enviar bolívares" primaryIconName="send" onPrimaryPress={() => { void send(); }}
          primaryDisabled={!amountOk || !recipientOk || !checked || !quoteMatches || !fundingReady}
          primaryLoading={loading} />
      );
    }
    const cancelProps = order.canCancel ? { secondaryLabel: 'Cancelar envío', onSecondaryPress: () => { void cancel(); } } : {};
    if (order.canFund) {
      return <RampActionBar primaryLabel="Continuar envío" primaryIconName="send" onPrimaryPress={() => { void resume(); }}
        primaryDisabled={!fundingReady} primaryLoading={loading} {...cancelProps} />;
    }
    if (order.status === 'COMPLETED' || order.status === 'FAILED') {
      return <RampActionBar primaryLabel="Hacer otro envío" onPrimaryPress={startOver} secondaryLabel="Volver" onSecondaryPress={goBack} />;
    }
    return order.canCancel
      ? <RampActionBar primaryLabel="Consultar estado" onPrimaryPress={() => { void refreshOrder(order.orderId as string).catch(() => setError(GENERIC)); }}
          primaryLoading={loading} {...cancelProps} />
      : null;
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroFieldDark} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled">
        <RampReveal delay={0}>
          <RampHero eyebrow="Venezuela · Pago Móvil" eyebrowCountry="VE"
            title={order ? 'Tu envío' : 'Envía bolívares'}
            subtitle={order ? 'Te avisamos cuando los bolívares lleguen.'
              : 'Tus dólares llegan como bolívares a cualquier cuenta con Pago Móvil, tuya o de otra persona.'}
            onBack={goBack} compact={!!order} />
        </RampReveal>
        <RampReveal delay={40}>
          <View style={styles.bannerCard}>
            <View style={styles.bannerIconWrap}>
              <Icon name="send" size={16} color={colors.primary} />
            </View>
            <View style={styles.bannerCopy}>
              <Text style={styles.bannerTitle}>Envíos en bolívares</Text>
              <Text style={styles.bannerText}>Tus envíos por Pago Móvil quedan en tu historial.</Text>
            </View>
            <TouchableOpacity style={styles.historyPill} activeOpacity={0.8} accessibilityRole="button"
              onPress={() => navigation.navigate('RampHistory', { initialFilter: 'off_ramp' })}>
              <Icon name="clock" size={14} color={colors.primary} />
              <Text style={styles.historyPillText}>Ver envíos</Text>
            </TouchableOpacity>
          </View>
        </RampReveal>
        {errorCard}
        {booting ? (
          <View style={styles.loadingCard}>
            <ActivityIndicator color={colors.primary} accessibilityLabel="Cargando" />
            <Text style={styles.loadingText}>Cargando…</Text>
          </View>
        ) : order ? renderOrder(order) : renderForm()}
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
            ListEmptyComponent={(
              <View style={styles.emptyCard}>
                <Text style={styles.emptyTitle}>No pudimos cargar los bancos</Text>
                <Text style={styles.emptyText}>Revisa tu conexión e intenta de nuevo.</Text>
                <TouchableOpacity style={styles.primaryActionButton} accessibilityRole="button"
                  onPress={() => { void reloadBanks(); }}>
                  <Text style={styles.primaryActionButtonText}>Reintentar</Text>
                </TouchableOpacity>
              </View>
            )}
            initialNumToRender={20}
            maxToRenderPerBatch={10}
            windowSize={21}
            getItemLayout={(_, index) => ({ length: BANK_ROW, offset: BANK_ROW * index, index })}
            renderItem={({ item }) => (
              <TouchableOpacity accessibilityRole="button" style={local.bankRow}
                onPress={() => { setBank(item); setBankPicker(false); }}>
                <View style={local.flex}>
                  <Text style={local.pickerValue} numberOfLines={1}>{item.name}</Text>
                  <Text style={local.bankCode}>{item.code}</Text>
                </View>
                {bank?.code === item.code ? <Icon name="check" size={18} color={colors.primaryDark} /> : null}
              </TouchableOpacity>
            )}
          />
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

const BANK_ROW = 60;

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
  bankCode: { fontSize: 12, fontWeight: '600', color: colors.textSecondary },
  quoteGap: { marginTop: 14 },
  timeline: { marginTop: 4 },
  failIcon: { backgroundColor: colors.warning.background },
  modalHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: 20 },
  bankRow: {
    height: BANK_ROW, paddingHorizontal: 20, flexDirection: 'row', alignItems: 'center', gap: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
});
