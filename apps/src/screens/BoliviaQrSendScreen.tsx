import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, SafeAreaView, ScrollView, StatusBar, StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { gql, useApolloClient, useQuery } from '@apollo/client';
import { useIsFocused, useNavigation } from '@react-navigation/native';

import { Text, TextInput } from '../components/common/AppText';
import { colors } from '../config/theme';
import { PaymentQrScannerModal } from '../components/PaymentQrScannerModal';
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
import {
  BOLIVIA_QR_ACTIVE_SEND,
  BOLIVIA_QR_SEND_ORDER,
  BOLIVIA_QR_SEND_QUOTE,
  BoliviaQrSendOrder,
  BoliviaQrSendQuote,
  CANCEL_BOLIVIA_QR_SEND,
  CREATE_BOLIVIA_QR_SEND,
  REPORT_BOLIVIA_QR_SEND_FUNDING,
  START_BOLIVIA_QR_SEND_FUNDING,
  sendCopy,
} from '../services/boliviaQr';

// The Retiro funding path redeems from these; served, never hardcoded.
const SEND_FUNDING_PARAMS = gql`
  query BoliviaQrSendFundingParams {
    cusdPlusConvertParams { vaultAddress cusdAddress }
  }
`;

const POLL_MS = 10_000;
const GENERIC = 'No pudimos conectar. Intenta de nuevo en unos segundos.';
const UNKNOWN_SEND = 'No pudimos confirmar si tus dólares salieron. No pagues de nuevo: revisa el estado en unos minutos.';

const toNumber = (value: string) => Number(value.replace(',', '.'));
const money = (value?: string | number | null, digits = 2) =>
  value === null || value === undefined || value === '' ? '—'
    : Number(value).toLocaleString('es-BO', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const formatBs = (value?: string | null) => (value ? `Bs ${money(value)}` : '—');
const formatUsd = (value?: string | number | null) => (value === null || value === undefined || value === '' ? '—' : `$${money(value)}`);
const isOpen = (order: BoliviaQrSendOrder | null) => !!order?.orderId && (order.status === 'PENDING' || order.status === 'PROCESSING');

function stage(order: BoliviaQrSendOrder): number {
  if (order.status === 'COMPLETED') return 4;
  const phase = order.phase || '';
  if (['paying', 'payout_pending', 'payout_review', 'payout_failed', 'settled'].includes(phase)) return 2;
  if (['funded', 'funding_reported'].includes(phase)) return 1;
  return 0;
}

/**
 * Pagar con QR Bolivia. One server order per payment: scan → the server reads
 * the QR (who, bank, amount) → price → Confío Face → the dollars leave in one
 * sponsored batch to the server-vouched target → the processor pays the QR.
 * The order lives on the server, so reopening resumes it.
 */
export default function BoliviaQrSendScreen({ initialQr, onBack }: {
  accountId: string; initialQr?: string; onBack: () => void;
}) {
  const client = useApolloClient();
  const navigation = useNavigation<any>();
  const focused = useIsFocused();
  const alive = useRef(true);
  const busy = useRef(false);
  const generation = useRef(0);
  useEffect(() => () => { alive.current = false; }, []);

  const { savings, cusdBalanceUsd } = useSavingsPortfolio();
  const { activeAccount } = useAccount();
  const personal = activeAccount?.type === 'personal';
  const available = (savings?.balanceUsd || 0) + (cusdBalanceUsd || 0);
  const { data: fundingParams } = useQuery(SEND_FUNDING_PARAMS);
  const vaultAddress: string = fundingParams?.cusdPlusConvertParams?.vaultAddress || '';
  const cusdAddress: string = fundingParams?.cusdPlusConvertParams?.cusdAddress || '';
  const fundingReady = !!cusdAddress;

  const [booting, setBooting] = useState(true);
  const [loading, setLoading] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState('');
  const [order, setOrder] = useState<BoliviaQrSendOrder | null>(null);
  const [qrText, setQrText] = useState(initialQr || '');
  const [scanner, setScanner] = useState(false);
  const [recipientQuote, setRecipientQuote] = useState<BoliviaQrSendQuote | null>(null);
  const [amount, setAmount] = useState('');
  const [amountFocused, setAmountFocused] = useState(false);
  const [quote, setQuote] = useState<BoliviaQrSendQuote | null>(null);
  const [checked, setChecked] = useState(false);

  const recipient = recipientQuote?.recipient || null;
  const fixed = !!recipient?.fixedAmount;
  const bob = fixed ? Number(recipient?.amount || 0) : toNumber(amount);

  const boot = useCallback(async (keepError = false) => {
    setBooting(true);
    if (!keepError) setError('');
    try {
      const active = await client.query({ query: BOLIVIA_QR_ACTIVE_SEND, fetchPolicy: 'network-only' });
      if (alive.current) setOrder(active.data?.boliviaQrActiveSend || null);
    } catch {
      if (alive.current && !keepError) setError(GENERIC);
    } finally {
      if (alive.current) setBooting(false);
    }
  }, [client]);
  useEffect(() => { void boot(); }, [boot]);

  // Read the QR on the server: the recipient never comes from the app.
  const readQr = useCallback(async (payload: string) => {
    const text = payload.trim();
    if (!text) return;
    setQrText(text);
    setRecipientQuote(null); setQuote(null); setAmount(''); setChecked(false); setError('');
    setReading(true);
    try {
      const r = await client.query({ query: BOLIVIA_QR_SEND_QUOTE, variables: { qrText: text }, fetchPolicy: 'network-only' });
      const result: BoliviaQrSendQuote | undefined = r.data?.boliviaQrSendQuote;
      if (!alive.current) return;
      if (!result?.success || !result.recipient) {
        setError(result?.error || 'No pudimos leer ese QR.');
        return;
      }
      setRecipientQuote(result);
      if (result.recipient.fixedAmount && result.usdAmount) setQuote(result);
    } catch {
      if (alive.current) setError(GENERIC);
    } finally {
      if (alive.current) setReading(false);
    }
  }, [client]);

  const handedOff = useRef(false);
  useEffect(() => {
    if (initialQr && !handedOff.current && !booting && !order) {
      handedOff.current = true;
      void readQr(initialQr);
    }
  }, [initialQr, booting, order, readQr]);

  // An open-amount QR is priced for the amount typed.
  useEffect(() => {
    if (fixed) return;
    setQuote(null);
    if (order || !recipientQuote || !(bob > 0)) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const r = await client.query({
          query: BOLIVIA_QR_SEND_QUOTE, variables: { qrText, bobAmount: String(bob) }, fetchPolicy: 'network-only',
        });
        if (!cancelled && alive.current) setQuote(r.data?.boliviaQrSendQuote || null);
      } catch {
        if (!cancelled && alive.current) setQuote(null);
      }
    }, 450);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [amount, bob, client, fixed, order, qrText, recipientQuote]);

  const refreshOrder = useCallback(async (orderId: string) => {
    const issued = generation.current;
    const r = await client.query({ query: BOLIVIA_QR_SEND_ORDER, variables: { orderId }, fetchPolicy: 'network-only' });
    const next: BoliviaQrSendOrder | undefined = r.data?.boliviaQrSendOrder;
    if (next?.success && alive.current && issued === generation.current) setOrder(next);
  }, [client]);

  useEffect(() => {
    if (!focused || !isOpen(order) || !order?.orderId) return;
    const timer = setInterval(() => { void refreshOrder(order.orderId as string).catch(() => {}); }, POLL_MS);
    return () => clearInterval(timer);
  }, [focused, order, refreshOrder]);

  const usd = Number(quote?.usdAmount || 0);
  const quoteMatches = !!quote?.success && !!quote.usdAmount && Number(quote.bobAmount) === Number(bob.toFixed(2));
  const affordable = usd > 0 && usd <= available + 1e-9;

  /** Claim the order's single funding, pay it, tell the server. */
  const fund = async (orderId: string) => {
    if (!personal) {
      setError('Cambia a tu cuenta personal para continuar este pago.');
      return;
    }
    if (!fundingReady) {
      setError(GENERIC);
      return;
    }
    // Pin the signer before the single-use claim: the personal wallet, and
    // only if it is the wallet this order was made for.
    const wallet = await getActiveEvmWallet({ type: 'personal', index: 0 });
    const expected = (order?.orderId === orderId ? order.wallet : null)
      || (await client.query({ query: BOLIVIA_QR_SEND_ORDER, variables: { orderId }, fetchPolicy: 'network-only' }))
        .data?.boliviaQrSendOrder?.wallet;
    if (!expected || wallet.address.toLowerCase() !== String(expected).toLowerCase()) {
      if (alive.current) setError('Este pago pertenece a otra cuenta. No se envió nada.');
      return;
    }
    const start = await client.mutate({
      mutation: START_BOLIVIA_QR_SEND_FUNDING, variables: { orderId }, fetchPolicy: 'no-cache',
    });
    const claimed: BoliviaQrSendOrder | undefined = start.data?.startBoliviaQrSendFunding;
    if (!alive.current) return;
    if (!claimed?.success || !claimed.funding || claimed.funding.network !== 'BSC'
        || !/^0x[0-9a-fA-F]{40}$/.test(claimed.funding.depositAddress)
        || !/^[1-9][0-9]*$/.test(claimed.funding.depositAmountWei)) {
      setError(claimed?.error || GENERIC);
      void refreshOrder(orderId).catch(() => {});
      return;
    }
    setOrder({ ...claimed, funding: null });
    if (claimed.funding.expiresAt && claimed.funding.expiresAt * 1000 < Date.now() + 60_000) {
      if (alive.current) setError('El pago venció antes de firmarlo. No se envió nada; cancélalo y vuelve a intentarlo.');
      return;
    }
    let txHash: string | null = null;
    try {
      // The audited Retiro batch (redeem with fee + exact transfer), signed
      // by the pinned wallet, never to outlive the bridge target.
      const res = await fundUsdtDestination({
        to: claimed.funding.depositAddress,
        amountWei: BigInt(claimed.funding.depositAmountWei),
        grossDebitWei: claimed.funding.grossDebitAmountWei ? BigInt(claimed.funding.grossDebitAmountWei) : null,
        vaultAddress: vaultAddress || null,
        cusdAddress,
        wallet,
        notAfter: claimed.funding.expiresAt ? claimed.funding.expiresAt - 30 : undefined,
      });
      txHash = res.txHash;
    } catch (fundError: any) {
      if (!isOutcomeUnknown(fundError)) {
        if (alive.current) {
          setError(fundError?.name === 'InsufficientWithdrawableError'
            ? 'No tienes saldo suficiente. No se envió nada.'
            : 'No se envió nada. Tu dinero sigue en tu cuenta. Podrás cancelar este pago en unos minutos.');
        }
        return;
      }
      if (alive.current) setError(UNKNOWN_SEND);
    }
    const report = await client.mutate({
      mutation: REPORT_BOLIVIA_QR_SEND_FUNDING, variables: { orderId, txHash }, fetchPolicy: 'no-cache',
    }).catch(() => null);
    const reported: BoliviaQrSendOrder | undefined = report?.data?.reportBoliviaQrSendFunding;
    if (alive.current && reported?.success) setOrder(reported);
  };

  const pay = async () => {
    if (busy.current || !recipient || !quoteMatches || !affordable || !checked) return;
    busy.current = true;
    generation.current += 1;
    setLoading(true);
    setError('');
    let created: string | null = null;
    try {
      const place = () => client.mutate({
        mutation: CREATE_BOLIVIA_QR_SEND,
        // The debit the person approved: the server never charges more.
        variables: { qrText, bobAmount: fixed ? null : String(bob), maxUsdAmount: quote?.usdAmount },
        fetchPolicy: 'no-cache',
      });
      let response;
      try {
        response = await withFaceStepUp('withdrawal', place,
          r => isFaceStepUpRequired(r?.data?.createBoliviaQrSend?.nextStep));
      } catch (faceError) {
        if (faceError instanceof FaceCheckError) return;
        throw faceError;
      }
      const result: BoliviaQrSendOrder | undefined = response?.data?.createBoliviaQrSend;
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
      const r = await client.mutate({ mutation: CANCEL_BOLIVIA_QR_SEND, variables: { orderId: order.orderId }, fetchPolicy: 'no-cache' });
      const result: BoliviaQrSendOrder | undefined = r.data?.cancelBoliviaQrSend;
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
    setOrder(null); setQrText(''); setRecipientQuote(null); setQuote(null); setAmount(''); setChecked(false); setError('');
  };

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
          <RampStepHeader number={1} title="QR a pagar" meta="De cualquier banco o billetera" />
          {recipient ? (
            <View style={styles.inputCard}>
              <View style={local.recipientRow}>
                <View style={local.recipientIcon}><Icon name="user" size={18} color={colors.primaryDark} /></View>
                <View style={local.flex}>
                  <Text style={local.recipientName} numberOfLines={2}>{recipient.holderName}</Text>
                  <Text style={local.recipientMeta} numberOfLines={1}>
                    {[recipient.bankName, recipient.accountLast4 ? `···${recipient.accountLast4}` : ''].filter(Boolean).join('  ·  ')}
                  </Text>
                </View>
              </View>
              <TouchableOpacity accessibilityRole="button" onPress={() => setScanner(true)} disabled={loading}
                style={local.rescan}>
                <Icon name="camera" size={15} color={colors.primaryDark} />
                <Text style={local.rescanText}>Escanear otro QR</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <TouchableOpacity accessibilityRole="button" style={[styles.inputCard, local.scanCard]}
              onPress={() => setScanner(true)} disabled={reading}>
              {reading ? <ActivityIndicator color={colors.primary} /> : (
                <>
                  <View style={local.scanIcon}><Icon name="maximize" size={24} color={colors.primaryDark} /></View>
                  <Text style={local.scanTitle}>Escanear QR</Text>
                  <Text style={local.scanText}>Apunta la cámara al QR que te muestran.</Text>
                </>
              )}
            </TouchableOpacity>
          )}
        </View>
      </RampReveal>

      {recipient ? (
        <RampReveal delay={110}>
          <View style={styles.section}>
            <RampStepHeader number={2} title="Monto" meta={`Disponible ${formatUsd(available)}`} />
            <View style={styles.inputCard}>
              <Text style={styles.inputLabel}>{fixed ? 'El QR cobra' : '¿Cuántos bolivianos vas a pagar?'}</Text>
              {fixed ? (
                <Text style={local.fixedAmount}>{formatBs(recipient.amount)}</Text>
              ) : (
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
              )}
              {usd > available + 1e-9 ? <Text style={styles.errorText}>Supera tu saldo disponible.</Text> : null}
              {quote?.error ? <Text style={styles.errorText}>{quote.error}</Text> : null}
            </View>
            {quote?.success && quote.usdAmount ? (
              <View style={[styles.quoteCard, local.quoteGap]}>
                <Text style={styles.quoteEyebrow}>Sale de tu saldo</Text>
                <Text style={styles.quoteHeadline} adjustsFontSizeToFit numberOfLines={1}>{formatUsd(quote.usdAmount)}</Text>
                {quote.rate ? <Text style={styles.quoteRate}>Tasa Bs {money(quote.rate)} por dólar</Text> : null}
                <View style={styles.quoteDivider} />
                <View style={styles.quoteRow}>
                  <Text style={styles.quoteLabel}>Pagas</Text>
                  <Text style={styles.quoteValue}>{formatBs(quote.bobAmount)}</Text>
                </View>
                {Number(quote.confioFeeUsd) > 0 ? (
                  <View style={styles.quoteRow}>
                    <Text style={styles.quoteLabel}>Comisión de Confío</Text>
                    <Text style={styles.quoteValue}>{formatUsd(quote.confioFeeUsd)}</Text>
                  </View>
                ) : null}
                <View style={styles.disclaimerPill}>
                  <Icon name="info" size={14} color={colors.primaryDark} />
                  <Text style={styles.quoteNote}>Incluye la conversión y el envío. El QR se paga completo.</Text>
                </View>
              </View>
            ) : null}
          </View>
        </RampReveal>
      ) : null}

      {quote?.success && quote.usdAmount ? (
        <RampReveal delay={160}>
          <View style={styles.section}>
            <RampStepHeader number={3} title="Confirma" />
            <TouchableOpacity style={styles.checkboxRow} onPress={() => setChecked(value => !value)}
              accessibilityRole="checkbox" accessibilityState={{ checked }} disabled={loading}>
              <View style={[styles.checkbox, checked && styles.checkboxChecked]}>
                {checked ? <Icon name="check" size={14} color={colors.white} /> : null}
              </View>
              <Text style={styles.checkboxText}>
                Revisé a quién le pago y el monto. Un pago con QR no se puede revertir.
              </Text>
            </TouchableOpacity>
          </View>
        </RampReveal>
      ) : null}
    </>
  );

  const renderOrder = (current: BoliviaQrSendOrder) => {
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
    const at = stage(current);
    const steps = ['Pago creado', 'Dólares enviados', 'Conversión a bolivianos', 'QR pagado'];
    return (
      <RampReveal delay={60}>
        <View style={styles.reviewCard}>
          <Text style={styles.reviewTitle}>{copy.title}</Text>
          {copy.body ? <Text style={styles.helperText}>{copy.body}</Text> : null}
          <View style={local.timeline}>
            {steps.map((label, index) => {
              const done = delivered || index < at;
              const active = !delivered && index === at;
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
            <Text style={styles.reviewLabel}>Para</Text>
            <Text style={styles.reviewValue}>
              {[current.holderName, current.bankName, current.accountLast4 ? `···${current.accountLast4}` : ''].filter(Boolean).join('\n')}
            </Text>
          </View>
          <View style={styles.reviewRow}>
            <Text style={styles.reviewLabel}>Pagas</Text>
            <Text style={styles.reviewValueHighlight}>{formatBs(current.bobAmount)}</Text>
          </View>
          <View style={styles.reviewRow}>
            <Text style={styles.reviewLabel}>De tu saldo</Text>
            <Text style={styles.reviewValue}>{formatUsd(current.usdAmount)}</Text>
          </View>
          {current.bankReference ? (
            <View style={styles.reviewRow}>
              <Text style={styles.reviewLabel}>Referencia</Text>
              <Text style={styles.reviewValue} selectable>{current.bankReference}</Text>
            </View>
          ) : null}
          {!delivered && !current.canFund ? <ActivityIndicator color={colors.primary} accessibilityLabel="Pago en proceso" /> : null}
        </View>
      </RampReveal>
    );
  };

  const actionBar = () => {
    if (booting) return null;
    if (!order) {
      if (!recipient) return null;
      return (
        <RampActionBar primaryLabel="Pagar QR" primaryIconName="send" onPrimaryPress={() => { void pay(); }}
          primaryDisabled={!quoteMatches || !affordable || !checked || !fundingReady} primaryLoading={loading} />
      );
    }
    const cancelProps = order.canCancel ? { secondaryLabel: 'Cancelar pago', onSecondaryPress: () => { void cancel(); } } : {};
    if (order.canFund) {
      return <RampActionBar primaryLabel="Continuar pago" primaryIconName="send" onPrimaryPress={() => { void resume(); }}
        primaryDisabled={!fundingReady} primaryLoading={loading} {...cancelProps} />;
    }
    if (order.status === 'COMPLETED' || order.status === 'FAILED') {
      return <RampActionBar primaryLabel="Pagar otro QR" onPrimaryPress={startOver} secondaryLabel="Volver" onSecondaryPress={onBack} />;
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
          <RampHero eyebrow="Bolivia · QR" eyebrowCountry="BO"
            title={order ? 'Tu pago' : 'Paga con QR'}
            subtitle={order ? 'Te avisamos cuando el QR quede pagado.'
              : 'Paga cualquier QR de bancos y billeteras de Bolivia con tu saldo en dólares.'}
            onBack={onBack} compact={!!order} />
        </RampReveal>
        <RampReveal delay={40}>
          <View style={styles.bannerCard}>
            <View style={styles.bannerIconWrap}>
              <Icon name="clock" size={16} color={colors.primary} />
            </View>
            <View style={styles.bannerCopy}>
              <Text style={styles.bannerTitle}>Pagos con QR</Text>
              <Text style={styles.bannerText}>Tus pagos quedan en tu historial.</Text>
            </View>
            <TouchableOpacity style={styles.historyPill} activeOpacity={0.8} accessibilityRole="button"
              onPress={() => navigation.navigate('RampHistory', { initialFilter: 'off_ramp' })}>
              <Icon name="clock" size={14} color={colors.primary} />
              <Text style={styles.historyPillText}>Ver pagos</Text>
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
      <PaymentQrScannerModal visible={scanner} onClose={() => setScanner(false)}
        onScanned={payload => { void readQr(payload); }} hint="Escanea el QR de cobro" />
    </SafeAreaView>
  );
}

const local = StyleSheet.create({
  flex: { flex: 1 },
  edge: { marginHorizontal: 22, marginTop: 0, marginBottom: 16 },
  quoteGap: { marginTop: 14 },
  timeline: { marginTop: 4 },
  failIcon: { backgroundColor: colors.warning.background },
  scanCard: { alignItems: 'center', paddingVertical: 28, gap: 6 },
  scanIcon: {
    width: 52, height: 52, borderRadius: 16, backgroundColor: colors.primaryLight,
    alignItems: 'center', justifyContent: 'center', marginBottom: 6,
  },
  scanTitle: { fontSize: 17, fontWeight: '700', color: colors.dark },
  scanText: { fontSize: 13, color: colors.textSecondary, textAlign: 'center' },
  recipientRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  recipientIcon: {
    width: 40, height: 40, borderRadius: 12, backgroundColor: colors.primaryLight,
    alignItems: 'center', justifyContent: 'center',
  },
  recipientName: { fontSize: 16, fontWeight: '700', color: colors.dark },
  recipientMeta: { fontSize: 13, color: colors.textSecondary, marginTop: 2 },
  rescan: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 14, alignSelf: 'flex-start' },
  rescanText: { fontSize: 14, fontWeight: '600', color: colors.primaryDark },
  fixedAmount: { fontSize: 28, fontWeight: '800', color: colors.dark, marginTop: 4 },
});
