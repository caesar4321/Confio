// Abrir una posición — margin, leverage, and what it means before it costs
// anything: the exposure, what a ±5% move does to the margin, where it
// liquidates, and every cost. "Revisar" asks the server for the exact quote
// (Relay, the exit, the first-time account charge); "Confirmar" signs it.
//
// The one-time risk disclosure (served by perpsCapabilities) is confirmed
// before the first open; the relay refuses an open without it.

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StatusBar,
  StyleSheet,
  useWindowDimensions,
  View,
} from 'react-native';
import { confirmImpact } from '../components/futures/confirmImpact';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { RouteProp, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';

import { Text, TextInput } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { SuccessHero } from '../components/common/SuccessHero';
import { ReceiptCard } from '../components/common/ReceiptCard';
import { StockTradeSuccessContent } from '../components/common/StockTradeSuccessContent';
import { StockRiskSheet } from '../components/StockRiskSheet';
import { LeverageSlider } from '../components/futures/LeverageSlider';
import { PerpMarketMark } from '../components/futures/PerpMarketMark';
import { FuturesProgress } from '../components/futures/FuturesProgress';
import { colors } from '../config/theme';
import { usePerpsCapabilities, usePerpsMarkets, usePerpsPositions } from '../hooks/usePerps';
import { useLiveMid } from '../hooks/useLiveMids';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { requestActivityShare } from '../services/communityShare';
import {
  OrderType,
  PerpPosition,
  PerpsStep,
  ReviewedOpen,
  Side,
  acknowledgePerpsRisk,
  afterExitFee,
  cancelQuote,
  confirmOpen,
  estimateLiquidationPx,
  perpsErrorCopy,
  quoteOpen,
} from '../services/perps';
import { MainStackParamList } from '../types/navigation';
import { parseAmountInput, sanitizeAmountInput, toAmountInput } from '../utils/numberLocale';
import {
  SIDE_COLORS,
  formatPctSigned,
  formatPerpPrice,
  formatUsd,
  leverageColor,
  sideLabel,
} from '../utils/perpsPresentation';

type Nav = NativeStackNavigationProp<MainStackParamList>;
type R = RouteProp<MainStackParamList, 'FuturesOrder'>;
type Phase = 'input' | 'quoting' | 'review' | 'processing' | 'success';

const QUICK = [10, 25, 50, 100];
// Price chips, as a move from the reference price (the limit, or the market).
const LIMIT_STEPS = [1, 2, 5];
const TP_STEPS = [5, 10, 25];
const SL_STEPS = [2, 5, 10];

/** Hyperliquid prices carry 5 significant figures. */
const roundPx = (px: number) => (px > 0 ? Number(px.toPrecision(5)) : 0);
const pxInput = (px: number) => toAmountInput(roundPx(px), 8);
const parsePx = (raw: string) => {
  const v = parseAmountInput(raw);
  return Number.isFinite(v) && v > 0 ? v : null;
};
// Relay's cost is roughly fixed per crossing; the review shows the exact one.
const BRIDGE_ESTIMATE_USD = 0.05;

export const FuturesOrderScreen = () => {
  const navigation = useNavigation<Nav>();
  const route = useRoute<R>();
  const { capabilities, refetch: refetchCaps } = usePerpsCapabilities();
  const { byCoin } = usePerpsMarkets(Boolean(capabilities?.enabled));
  const market = byCoin(route.params.coin);
  const { positions } = usePerpsPositions(true);
  const { savings, cusdBalanceUsd, refetch: refetchBalances } = useSavingsPortfolio();

  const [side, setSide] = useState<Side>(route.params.side);
  const [raw, setRaw] = useState('');
  const [orderType, setOrderType] = useState<OrderType>('market');
  const [limitRaw, setLimitRaw] = useState('');
  const [protect, setProtect] = useState(false);
  const [tpRaw, setTpRaw] = useState('');
  const [slRaw, setSlRaw] = useState('');
  const [leverage, setLeverage] = useState(2);
  const [phase, setPhase] = useState<Phase>('input');
  const [quote, setQuote] = useState<any>(null);
  const [step, setStep] = useState<PerpsStep | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [riskSheet, setRiskSheet] = useState(false);
  const [opened, setOpened] = useState<PerpPosition | null>(null);
  const riskFlow = useRef(0);
  // Accepted here: the capabilities query may still say otherwise until it refetches.
  const [acked, setAcked] = useState(false);
  const ackRequired = Boolean(capabilities?.ackRequired) && !acked;
  const quoting = useRef(false);
  // What to continue once the risk sheet is accepted (quote or confirm).
  const afterAck = useRef<(() => void) | null>(null);
  // The quote on screen and not yet signed: freed if the member leaves.
  const unsigned = useRef<string | null>(null);

  useEffect(() => {
    if (market && leverage > market.maxLeverage) setLeverage(market.maxLeverage);
  }, [market, leverage]);
  // Leaving with an unsigned quote frees it (a new one would replace it anyway).
  // Unmount only: confirming must never cancel the quote being signed.
  useEffect(() => () => { if (unsigned.current) void cancelQuote(unsigned.current); }, []);

  const fundingDollar = capabilities?.fundingDollar ?? 'cusd';
  const balance = fundingDollar === 'cusd_plus' ? savings.balanceUsd : cusdBalanceUsd;
  const fundingName = fundingDollar === 'cusd_plus' ? 'Confío Dollar+' : 'Confío Dollar';
  const feeBps = capabilities?.feeBps ?? 90;
  const margin = useMemo(() => {
    const v = parseAmountInput(raw);
    return Number.isFinite(v) ? v : 0;
  }, [raw]);
  // A new Hyperliquid account needs more (its activation is paid from it); unknown counts as new.
  const minMargin = capabilities?.newAccount === false
    ? capabilities?.minMarginUsd ?? 10
    : capabilities?.firstMinMarginUsd ?? 12;
  const busy = (positions ?? []).find((p) => ['wait_bridge', 'retry_bridge', 'open_order', 'finish_margin']
    .includes(p.nextAction));

  // Live estimate before the quote: exit fee, a typical Relay cost.
  const credited = Math.max(0, afterExitFee(margin, feeBps) - BRIDGE_ESTIMATE_USD);
  const notional = credited * leverage;
  // Live from Hyperliquid while choosing (estimates and price chips follow it).
  const liveMid = useLiveMid(route.params.coin);
  const markPx = liveMid ?? market?.markPx ?? null;
  const limitPx = orderType === 'limit' ? parsePx(limitRaw) : null;
  // Where the position starts: the member's limit, or the market now.
  const entryPx = orderType === 'limit' ? limitPx : markPx;
  const liq = entryPx ? estimateLiquidationPx(entryPx, notional, credited, side, market?.maxLeverage ?? 1) : null;
  const liqDistance = entryPx && liq != null ? Math.abs(liq - entryPx) / entryPx : null;
  const dir = side === 'long' ? 1 : -1;
  // A limit that would fill at once is a market order with a price cap: said, not refused.
  const limitFillsNow = limitPx != null && markPx != null && (side === 'long' ? limitPx >= markPx : limitPx <= markPx);
  const limitTooFar = limitPx != null && markPx != null && Math.abs(limitPx - markPx) / markPx > 0.5;
  const tpPx = protect ? parsePx(tpRaw) : null;
  const slPx = protect ? parsePx(slRaw) : null;
  // Take-profit beyond the entry in the trade's direction, stop-loss the other way.
  const tpWrong = tpPx != null && entryPx != null && (tpPx - entryPx) * dir <= 0;
  const slWrong = slPx != null && entryPx != null && (slPx - entryPx) * dir >= 0;
  const slPastLiq = slPx != null && liq != null && !slWrong && (slPx - liq) * dir <= 0;
  // What the member's margin does at each level (never more than the margin is lost).
  const resultAt = (px: number | null) => (px && entryPx
    ? Math.max(-credited, notional * ((px - entryPx) / entryPx) * dir) : null);
  const priceInvalid = (orderType === 'limit' && (limitPx == null || limitTooFar))
    || (protect && (tpWrong || slWrong || (tpPx == null && slPx == null)));
  const move = notional * 0.05;
  const takerFee = notional * (market?.takerFeeRate ?? 0.00045);
  const tooSmall = margin > 0 && margin < minMargin;
  const overBalance = margin > balance + 0.001;
  const notionalTooSmall = margin >= minMargin && notional < 12;
  const canReview = Boolean(market) && Boolean(capabilities?.openEnabled) && margin >= minMargin
    && !overBalance && !notionalTooSmall && !busy && phase === 'input' && !priceInvalid;

  const setAmount = (value: string, exact = false) => {
    setError(null);
    setRaw((prev) => (exact ? value : sanitizeAmountInput(value, 2, undefined, prev)));
  };

  const askRisk = (then: () => void) => {
    riskFlow.current += 1;
    afterAck.current = then;
    setRiskSheet(true);
  };

  const review = async (accepted = false) => {
    if (!market || quoting.current) return;
    // First trade: the disclosure comes before any quote (the server asks for it).
    if (ackRequired && !accepted) { askRisk(() => { void review(true); }); return; }
    quoting.current = true;
    setError(null);
    setPhase('quoting'); // inputs freeze: the review is exactly what was quoted
    const reviewed: ReviewedOpen = {
      coin: market.coin, side, leverage, marginUsd: margin.toFixed(2), dollar: fundingDollar, notionalUsd: null,
      orderType, limitPx: orderType === 'limit' ? roundPx(limitPx ?? 0) : null,
      takeProfitPx: tpPx ? roundPx(tpPx) : null, stopLossPx: slPx ? roundPx(slPx) : null,
    };
    try {
      const q = await quoteOpen(reviewed);
      unsigned.current = q?.positionId ?? null;
      reviewed.notionalUsd = Number(q?.costs?.notionalUsd) || null; // the exposure the review shows
      // The quote must be for exactly what the member typed (what gets signed is bounded by it).
      if (Math.abs(Number(q?.costs?.marginUsd) - Number(reviewed.marginUsd)) > 0.005) {
        if (q?.positionId) void cancelQuote(q.positionId);
        unsigned.current = null;
        throw Object.assign(new Error('unsafe_plan'), { code: 'unsafe_plan' });
      }
      setQuote({ ...q, reviewed });
      setPhase('review');
    } catch (e) {
      setError(perpsErrorCopy(e));
      setPhase('input');
    } finally {
      quoting.current = false;
    }
  };

  const confirming = useRef(false);
  const confirm = async (accepted = false) => {
    // One confirmation at a time: a second tap before the sheet closes is ignored.
    if (!quote || confirming.current) return;
    if (ackRequired && !accepted) { askRisk(() => { void confirm(true); }); return; }
    confirming.current = true;
    unsigned.current = null;
    setPhase('processing');
    setStep('exit');
    try {
      const result = await confirmOpen(quote, setStep, quote.reviewed, confirmImpact);
      setOpened(result.position);
      setPhase('success');
      void refetchBalances?.();
      if (result.txHash) {
        setTimeout(() => requestActivityShare({ group: 'perps', reference: result.txHash }), 900);
      }
    } catch (e) {
      const code = (e as { code?: string })?.code;
      setError(perpsErrorCopy(e));
      // The money may already be on its way: the position screen continues it.
      if (code === 'timeout' || code === 'refunded' || code === 'order_not_filled' || code === 'impact_declined'
          || code === 'hyperliquid_unavailable' || code === 'hyperliquid_rejected'
          || code === 'bad_trigger_side' || code === 'limit_too_far' || code === 'impact_too_high') {
        navigation.replace('FuturesPosition', { positionId: quote.positionId });
        return;
      }
      setPhase('input');
      setQuote(null);
    } finally {
      confirming.current = false;
    }
  };

  if (!market) {
    return (
      <View style={[styles.container, styles.center]}>
        <Text style={styles.muted}>{capabilities?.blockedMessage || 'Este mercado no está disponible.'}</Text>
      </View>
    );
  }

  const sideColors = SIDE_COLORS[side];

  if (phase === 'success' && opened && opened.nextAction === 'wait_fill') {
    const waitPx = opened.restingPx ?? opened.limitPx ?? null;
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
        <SafeAreaView edges={['top']} style={{ backgroundColor: colors.heroField }} />
        <StockTradeSuccessContent>
          <SuccessHero
            title="Tu orden está esperando"
            amount={`${market.ticker} · ${sideLabel(side)} ${leverage}x`}
            amountColor={sideColors.text}
            hint={`Se abre si ${market.ticker} llega a ${formatPerpPrice(waitPx)}. Te avisamos cuando se ejecute; puedes cancelarla cuando quieras.`}
            icon={<PerpMarketMark ticker={market.ticker} size={72} leverage={leverage} badgeColor={sideColors.solid} />}
          />
          <ReceiptCard
            style={{ marginTop: 4 }}
            items={[
              { label: `Salió de tu ${fundingName}`, value: formatUsd(Number(quote?.reviewed?.marginUsd ?? margin)) },
              { label: 'Precio de entrada', value: formatPerpPrice(waitPx) },
              ...(opened.plannedTakeProfitPx ? [{ label: 'Tomar ganancia', value: formatPerpPrice(opened.plannedTakeProfitPx), color: '#047857' }] : []),
              ...(opened.plannedStopLossPx ? [{ label: 'Limitar pérdida', value: formatPerpPrice(opened.plannedStopLossPx), color: '#B91C1C' }] : []),
              { label: 'Estado', value: 'Esperando precio', color: '#B45309', icon: 'clock' },
            ]}
          />
          <Pressable style={styles.successCta} onPress={() => navigation.replace('FuturesPosition', { positionId: opened.id })}>
            <Text style={styles.successCtaText}>Ver mi orden</Text>
          </Pressable>
        </StockTradeSuccessContent>
      </View>
    );
  }

  if (phase === 'success' && opened) {
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
        <SafeAreaView edges={['top']} style={{ backgroundColor: colors.heroField }} />
        <StockTradeSuccessContent>
          <SuccessHero
            title="Tu posición está abierta"
            amount={`${market.ticker} · ${sideLabel(side)} ${leverage}x`}
            amountColor={sideColors.text}
            hint={`Ganas si ${market.ticker} ${side === 'long' ? 'sube' : 'baja'}. Puedes cerrarla cuando quieras, a cualquier hora.`}
            icon={<PerpMarketMark ticker={market.ticker} size={72} leverage={leverage} badgeColor={sideColors.solid} />}
          />
          <ReceiptCard
            style={{ marginTop: 4 }}
            items={[
              { label: `Salió de tu ${fundingName}`, value: formatUsd(Number(quote?.reviewed?.marginUsd ?? margin)) },
              { label: 'Precio de entrada', value: formatPerpPrice(opened.entryPx) },
              { label: 'Tamaño', value: `${opened.size ?? '—'} ${market.ticker}` },
              { label: 'Liquidación aprox.', value: formatPerpPrice(opened.liquidationPx), color: '#B91C1C' },
              { label: 'Estado', value: 'Abierta', color: colors.success, icon: 'check-circle' },
            ]}
          />
          <Pressable style={styles.successCta} onPress={() => navigation.replace('FuturesPosition', { positionId: opened.id })}>
            <Text style={styles.successCtaText}>Ver mi posición</Text>
          </Pressable>
        </StockTradeSuccessContent>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
      <Header
        navigation={navigation as any}
        title={`${side === 'long' ? 'Largo' : 'Corto'} en ${market.ticker}`}
        titleAccessory={<PerpMarketMark ticker={market.ticker} size={26} />}
        backgroundColor={colors.heroField}
        isLight
        showBackButton
        onBackPress={() => { if (phase !== 'processing') navigation.goBack(); }}
      />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <View style={styles.segment}>
            {(['long', 'short'] as Side[]).map((s) => (
              <Pressable key={s} onPress={() => setSide(s)} disabled={phase !== 'input'}
                style={[styles.segmentBtn, side === s && { backgroundColor: SIDE_COLORS[s].solid }]}
                accessibilityRole="tab" accessibilityState={{ selected: side === s }}>
                <Icon name={s === 'long' ? 'arrow-up-right' : 'arrow-down-right'} size={16}
                  color={side === s ? '#FFFFFF' : SIDE_COLORS[s].text} />
                <Text style={[styles.segmentText, { color: side === s ? '#FFFFFF' : SIDE_COLORS[s].text }]}>
                  {s === 'long' ? 'Largo · sube' : 'Corto · baja'}
                </Text>
              </Pressable>
            ))}
          </View>

          {busy && (
            <Pressable style={styles.banner} onPress={() => navigation.navigate('FuturesPosition', { positionId: busy.id })}>
              <Icon name="clock" size={16} color="#92400E" />
              <Text style={styles.bannerText}>
                Termina primero tu operación en {busy.ticker}: su dinero está en camino. Toca para verla.
              </Text>
            </Pressable>
          )}

          <View style={styles.card}>
            <Text style={styles.label}>Cómo entrar</Text>
            <View style={styles.typeRow}>
              {([['market', 'Ahora', 'zap'], ['limit', 'A mi precio', 'target']] as const).map(([t, label, icon]) => (
                <Pressable key={t} onPress={() => { setOrderType(t); setError(null); if (t === 'limit' && !limitRaw && markPx) setLimitRaw(pxInput(markPx)); }}
                  disabled={phase !== 'input'} testID={`perps-type-${t}`}
                  style={[styles.typeBtn, orderType === t && styles.typeBtnOn]}
                  accessibilityRole="tab" accessibilityState={{ selected: orderType === t }}>
                  <Icon name={icon} size={15} color={orderType === t ? colors.primaryDark : colors.text.secondary} />
                  <Text style={[styles.typeText, orderType === t && styles.typeTextOn]}>{label}</Text>
                </Pressable>
              ))}
            </View>
            {orderType === 'market' ? (
              <Text style={styles.typeHint}>
                Al mejor precio del momento{markPx ? `, cerca de ${formatPerpPrice(markPx)}` : ''}.
              </Text>
            ) : (
              <>
                <View style={styles.pxRow}>
                  <Text style={styles.pxCurrency}>$</Text>
                  <TextInput
                    style={styles.pxInput}
                    value={limitRaw}
                    onChangeText={(v) => { setError(null); setLimitRaw((prev) => sanitizeAmountInput(v, 8, undefined, prev)); }}
                    keyboardType="decimal-pad"
                    placeholder={markPx ? pxInput(markPx) : '0.00'}
                    placeholderTextColor={colors.text.light}
                    editable={phase === 'input'}
                    testID="perps-limit"
                  />
                  {markPx ? <Text style={styles.pxMark}>Ahora {formatPerpPrice(markPx)}</Text> : null}
                </View>
                <View style={styles.quickRow}>
                  {markPx ? LIMIT_STEPS.map((pct) => (
                    <Pressable key={pct} style={styles.quick} disabled={phase !== 'input'}
                      onPress={() => setLimitRaw(pxInput(markPx * (1 - dir * pct / 100)))}>
                      <Text style={styles.quickText}>{side === 'long' ? '−' : '+'}{pct}%</Text>
                    </Pressable>
                  )) : null}
                </View>
                <Text style={[styles.typeHint, limitTooFar && styles.error]}>
                  {limitTooFar
                    ? 'Ese precio está demasiado lejos del mercado.'
                    : limitFillsNow
                      ? `Ese precio ya está disponible: se abre al instante, sin pasar de ${formatPerpPrice(limitPx)}.`
                      : limitPx
                        ? `Se abre solo si ${market.ticker} ${side === 'long' ? 'baja' : 'sube'} a ${formatPerpPrice(limitPx)}. Mientras espera, tu margen queda en tu cuenta de Hyperliquid y puedes cancelar cuando quieras.`
                        : 'Elige el precio al que quieres entrar.'}
                </Text>
              </>
            )}
          </View>

          <View style={styles.card}>
            <Text style={styles.label}>Margen</Text>
            <View style={styles.amountRow}>
              <Text style={styles.currency}>$</Text>
              <TextInput
                style={styles.amountInput}
                value={raw}
                onChangeText={(v) => setAmount(v)}
                keyboardType="decimal-pad"
                placeholder="0.00"
                placeholderTextColor={colors.text.light}
                editable={phase === 'input'}
                testID="perps-margin"
              />
            </View>
            <View style={styles.quickRow}>
              {QUICK.filter((q) => q <= Math.max(balance, minMargin)).map((q) => (
                <Pressable key={q} style={styles.quick} onPress={() => setAmount(toAmountInput(q), true)}
                  disabled={phase !== 'input'}>
                  <Text style={styles.quickText}>${q}</Text>
                </Pressable>
              ))}
              <Pressable style={styles.quick} onPress={() => setAmount(toAmountInput(Math.floor(balance * 100) / 100), true)}
                disabled={balance <= 0 || phase !== 'input'}>
                <Text style={[styles.quickText, { color: colors.primaryDark }]}>Todo</Text>
              </Pressable>
            </View>
            <Text style={[styles.balance, overBalance && styles.error]}>
              Disponible en {fundingName}: {formatUsd(balance)}
            </Text>
            {tooSmall && <Text style={styles.error}>El margen mínimo es {formatUsd(minMargin)}.</Text>}
            {notionalTooSmall && (
              <Text style={styles.error}>Hyperliquid pide posiciones de al menos $10: sube el apalancamiento o el margen.</Text>
            )}
          </View>

          <View style={styles.card}>
            <Text style={styles.label}>Apalancamiento</Text>
            <LeverageSlider value={leverage} max={market.maxLeverage} onChange={setLeverage} disabled={phase !== 'input'} />
          </View>

          <View style={[styles.card, styles.exposure]}>
            <View style={styles.expRow}>
              <View>
                <Text style={styles.expLabel}>Tu posición</Text>
                <Text style={styles.expValue}>{formatUsd(notional)}</Text>
                <Text style={styles.expSub}>{margin > 0 ? `${formatUsd(credited)} de margen × ${leverage}` : 'Elige tu margen'}</Text>
              </View>
              <View style={styles.liqBox}>
                <Text style={styles.expLabel}>Se liquida en</Text>
                <Text style={[styles.liqValue, { color: leverageColor(leverage, market.maxLeverage) }]}>
                  {margin > 0 ? formatPerpPrice(liq) : '—'}
                </Text>
                {liqDistance != null && margin > 0 ? (
                  <Text style={styles.expSub}>si {side === 'long' ? 'baja' : 'sube'} {formatPctSigned(liqDistance * 100).replace(/^[+−]/, '')}</Text>
                ) : null}
              </View>
            </View>
            {margin > 0 && (
              <View style={styles.scenarios}>
                <Scenario up={side === 'long'} label={`Si ${market.ticker} sube 5%`} value={side === 'long' ? move : -Math.min(move, credited)} />
                <Scenario up={side !== 'long'} label={`Si ${market.ticker} baja 5%`} value={side === 'long' ? -Math.min(move, credited) : move} />
              </View>
            )}
          </View>

          <View style={styles.card}>
            <Pressable style={styles.protectHead} onPress={() => { setProtect((v) => !v); setError(null); }}
              disabled={phase !== 'input'} accessibilityRole="switch" accessibilityState={{ checked: protect }}
              testID="perps-protect">
              <View style={[styles.protectIcon, protect && styles.protectIconOn]}>
                <Icon name="shield" size={16} color={protect ? '#FFFFFF' : colors.primaryDark} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.protectTitle}>Proteger al abrir</Text>
                <Text style={styles.protectSub}>
                  {protect ? 'Se activan cuando tu orden se ejecuta.' : 'Cierra solo con ganancia o limita la pérdida.'}
                </Text>
              </View>
              <View style={[styles.toggle, protect && styles.toggleOn]}>
                <View style={[styles.knob, protect && styles.knobOn]} />
              </View>
            </Pressable>
            {protect && (
              <>
                <TriggerField
                  label="Tomar ganancia" icon="trending-up" tone="#047857" value={tpRaw} editable={phase === 'input'}
                  onChange={(v) => { setError(null); setTpRaw((prev) => sanitizeAmountInput(v, 8, undefined, prev)); }}
                  steps={TP_STEPS} sign={dir} reference={entryPx} onStep={(px) => setTpRaw(pxInput(px))}
                  result={resultAt(tpPx)} testID="perps-tp"
                  error={tpWrong ? `Debe estar ${side === 'long' ? 'por encima' : 'por debajo'} de tu entrada.` : null}
                />
                <TriggerField
                  label="Limitar pérdida" icon="shield-off" tone="#B91C1C" value={slRaw} editable={phase === 'input'}
                  onChange={(v) => { setError(null); setSlRaw((prev) => sanitizeAmountInput(v, 8, undefined, prev)); }}
                  steps={SL_STEPS} sign={-dir} reference={entryPx} onStep={(px) => setSlRaw(pxInput(px))}
                  result={resultAt(slPx)} testID="perps-sl"
                  error={slWrong ? `Debe estar ${side === 'long' ? 'por debajo' : 'por encima'} de tu entrada.`
                    : slPastLiq ? 'Tu posición se liquidaría antes de llegar a este precio.' : null}
                />
                {tpPx == null && slPx == null && (
                  <Text style={styles.typeHint}>Elige al menos uno de los dos niveles.</Text>
                )}
              </>
            )}
          </View>

          <View style={styles.card}>
            <Text style={styles.label}>Costos</Text>
            <Row label={`Comisión de Confío Dollar (${(feeBps / 100).toFixed(1).replace('.', ',')}%) al salir`} value={formatUsd(margin * feeBps / 10_000)} />
            <Row label="Transferencia a Hyperliquid" value={`~${formatUsd(BRIDGE_ESTIMATE_USD)}`} />
            <Row label="Comisión de Hyperliquid al abrir" value={`~${formatUsd(takerFee)}`} />
            <Text style={styles.costNote}>
              Al cerrar se repiten la comisión de Hyperliquid, la transferencia y el 0,9% al entrar a tus dólares.
              {capabilities?.newAccountChargeUsd ? ` La primera vez, Hyperliquid cobra ${formatUsd(capabilities.newAccountChargeUsd)} por activar tu cuenta.` : ''}
            </Text>
          </View>

          {error && <Text style={[styles.error, { marginHorizontal: 4, marginBottom: 12 }]}>{error}</Text>}

          <Pressable style={[styles.primary, !canReview && styles.disabled, { backgroundColor: sideColors.solid }]}
            onPress={() => { void review(); }} disabled={!canReview} testID="perps-review">
            {phase === 'quoting'
              ? <ActivityIndicator color="#FFFFFF" />
              : <Text style={styles.primaryText}>Revisar {side === 'long' ? 'largo' : 'corto'}</Text>}
          </Pressable>
          <Text style={styles.footnote}>
            {orderType === 'limit'
              ? 'Tu orden espera en Hyperliquid hasta que el precio llegue. Puedes cancelarla y traer tu dinero cuando quieras.'
              : `La orden se ejecuta en Hyperliquid al mejor precio del momento, con un límite de ${((capabilities?.slippageBps ?? 50) / 100).toFixed(1).replace('.', ',')}%.`}
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>

      <ReviewSheet
        visible={phase === 'review' && Boolean(quote)}
        quote={quote}
        ticker={market.ticker}
        side={quote?.reviewed?.side ?? side}
        leverage={quote?.reviewed?.leverage ?? leverage}
        markPx={markPx}
        maxLeverage={market.maxLeverage}
        fundingName={fundingName}
        onCancel={() => {
          if (quote?.positionId) void cancelQuote(quote.positionId);
          unsigned.current = null;
          setQuote(null);
          setPhase('input');
        }}
        onConfirm={() => { void confirm(); }}
      />
      <FuturesProgress visible={phase === 'processing'} kind="open" current={step}
        title={`Abriendo ${sideLabel(side).toLowerCase()} en ${market.ticker}`} />
      {capabilities && (
        <StockRiskSheet
          visible={riskSheet}
          title={capabilities.disclosureTitle}
          points={capabilities.disclosurePoints ?? []}
          version={capabilities.ackVersion ?? null}
          onRefresh={refetchCaps}
          acknowledge={async (version) => acknowledgePerpsRisk(version) as any}
          onClose={() => { riskFlow.current += 1; afterAck.current = null; setRiskSheet(false); }}
          beginAccept={() => riskFlow.current}
          onAccepted={(flow) => {
            void refetchCaps().catch(() => undefined);
            if (flow === undefined || flow !== riskFlow.current) return;
            setRiskSheet(false);
            setTimeout(() => {
              if (flow === riskFlow.current) {
                setAcked(true); // the server knows; the next read agrees
                const next = afterAck.current;
                afterAck.current = null;
                next?.();
              }
            }, 400);
          }}
        />
      )}
    </View>
  );
};

function TriggerField({
  label, icon, tone, value, onChange, editable, steps, sign, reference, onStep, result, error, testID,
}: {
  label: string; icon: string; tone: string; value: string; onChange: (v: string) => void; editable: boolean;
  steps: number[]; sign: number; reference: number | null; onStep: (px: number) => void;
  result: number | null; error: string | null; testID: string;
}) {
  return (
    <View style={styles.trigger}>
      <View style={styles.triggerHead}>
        <Icon name={icon} size={14} color={tone} />
        <Text style={[styles.triggerLabel, { color: tone }]}>{label}</Text>
        {result != null && !error ? (
          <Text style={[styles.triggerResult, { color: result >= 0 ? '#047857' : '#B91C1C' }]}>
            {result >= 0 ? '+' : '−'}{formatUsd(Math.abs(result))}
          </Text>
        ) : null}
      </View>
      <View style={styles.pxRow}>
        <Text style={styles.pxCurrency}>$</Text>
        <TextInput style={styles.pxInput} value={value} onChangeText={onChange} keyboardType="decimal-pad"
          placeholder="Precio" placeholderTextColor={colors.text.light} editable={editable} testID={testID} />
      </View>
      {reference ? (
        <View style={styles.quickRow}>
          {steps.map((pct) => (
            <Pressable key={pct} style={styles.quick} disabled={!editable}
              onPress={() => onStep(reference * (1 + sign * pct / 100))}>
              <Text style={styles.quickText}>{sign > 0 ? '+' : '−'}{pct}%</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

function Scenario({ up, label, value }: { up: boolean; label: string; value: number }) {
  const positive = value >= 0;
  return (
    <View style={[styles.scenario, { backgroundColor: positive ? '#ECFDF5' : '#FEF2F2' }]}>
      <Text style={styles.scenarioLabel}>{label}</Text>
      <Text style={[styles.scenarioValue, { color: positive ? '#047857' : '#B91C1C' }]}>
        {positive ? '+' : '−'}{formatUsd(Math.abs(value))}
      </Text>
      <Icon name={up ? 'trending-up' : 'trending-down'} size={14} color={positive ? '#047857' : '#B91C1C'} />
    </View>
  );
}

function Row({ label, value, strong, color }: { label: string; value: string; strong?: boolean; color?: string }) {
  return (
    <View style={styles.row}>
      <Text style={[styles.rowLabel, strong && styles.rowStrong]}>{label}</Text>
      <Text style={[styles.rowValue, strong && styles.rowStrong, color ? { color } : null]}>{value}</Text>
    </View>
  );
}

function ReviewSheet({
  visible, quote, ticker, side, leverage, markPx, maxLeverage, fundingName, onCancel, onConfirm,
}: {
  visible: boolean; quote: any; ticker: string; side: Side; leverage: number; markPx: number | null;
  maxLeverage: number; fundingName: string; onCancel: () => void; onConfirm: () => void;
}) {
  const c = quote?.costs || {};
  const credited = c.creditedUsd ?? 0;
  const r: ReviewedOpen | undefined = quote?.reviewed;
  const limit = r?.orderType === 'limit' ? r.limitPx ?? null : null;
  const entry = limit ?? markPx;
  const liq = entry ? estimateLiquidationPx(entry, credited * leverage, credited, side, maxLeverage) : null;
  const sideColors = SIDE_COLORS[side];
  // Large system fonts outgrow the screen: the review scrolls, the buttons stay.
  const insets = useSafeAreaInsets();
  const { height } = useWindowDimensions();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onCancel}>
      <Pressable style={styles.sheetBackdrop} onPress={onCancel} />
      <View style={[styles.sheet, { maxHeight: height - Math.max(insets.top, 16) - 24 }]}>
        <View style={styles.grabber} />
        <ScrollView style={styles.sheetScroll} bounces={false} showsVerticalScrollIndicator>
        <Text style={styles.sheetTitle}>{sideLabel(side)} {leverage}x en {ticker}</Text>
        <Text style={styles.sheetSub}>Revisa antes de firmar</Text>
        <View style={styles.sheetCard}>
          <Row label={`Sale de tu ${fundingName}`} value={formatUsd(Number(quote?.reviewed?.marginUsd ?? c.marginUsd))} />
          <Row label="Comisión de Confío Dollar" value={`−${formatUsd(c.exitFeeUsd)}`} />
          <Row label="Transferencia a Hyperliquid" value={`−${formatUsd(c.bridgeCostUsd)}`} />
          {c.activationUsd ? <Row label="Activación de tu cuenta (solo la primera vez)" value={`−${formatUsd(c.activationUsd)}`} /> : null}
          <View style={styles.divider} />
          <Row label="Tu margen en Hyperliquid" value={`≈ ${formatUsd(credited)}`} strong />
          <Row label="Tu posición" value={`≈ ${formatUsd(c.notionalUsd)}`} strong color={sideColors.text} />
          <Row label="Comisión de Hyperliquid al abrir" value={`≈ ${formatUsd(c.openFeeUsd)}`} />
          <Row label="Entrada" value={limit ? `A ${formatPerpPrice(limit)}` : 'Al precio del momento'} />
          {r?.takeProfitPx ? <Row label="Tomar ganancia" value={formatPerpPrice(r.takeProfitPx)} color="#047857" /> : null}
          {r?.stopLossPx ? <Row label="Limitar pérdida" value={formatPerpPrice(r.stopLossPx)} color="#B91C1C" /> : null}
          <Row label="Se liquida en (aprox.)" value={formatPerpPrice(liq)} color="#B91C1C" />
        </View>
        <Text style={styles.sheetNote}>
          {limit
            ? `Firmas una sola vez con tu llave. El margen cruza a tu cuenta en Hyperliquid y tu orden espera hasta que ${ticker} llegue a ${formatPerpPrice(limit)}. Puedes cancelarla cuando quieras. Puedes perder todo el margen.`
            : 'Firmas una sola vez con tu llave. El margen cruza a tu cuenta en Hyperliquid y la orden se abre al mejor precio del momento. Puedes perder todo el margen.'}
        </Text>
        </ScrollView>
        <Pressable style={[styles.primary, { backgroundColor: sideColors.solid }]} onPress={onConfirm} testID="perps-confirm">
          <Text style={styles.primaryText}>{limit ? 'Confirmar orden' : 'Confirmar y abrir'}</Text>
        </Pressable>
        <Pressable style={styles.secondary} onPress={onCancel}>
          <Text style={styles.secondaryText}>Cancelar</Text>
        </Pressable>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  // A success screen centers its column: the CTA carries its own width, like the Oro y Bitcoin twin.
  successCta: { backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 15, paddingHorizontal: 40, marginTop: 32 },
  successCtaText: { color: '#FFFFFF', fontSize: 16, fontWeight: '700' },
  container: { flex: 1, backgroundColor: colors.neutral },
  center: { alignItems: 'center', justifyContent: 'center', padding: 32 },
  muted: { color: colors.text.secondary, textAlign: 'center' },
  scroll: { padding: 16, paddingBottom: 32 },
  segment: { flexDirection: 'row', backgroundColor: '#FFFFFF', borderRadius: 16, padding: 4, marginBottom: 14 },
  segmentBtn: { flex: 1, flexDirection: 'row', gap: 6, alignItems: 'center', justifyContent: 'center', borderRadius: 12, minHeight: 44 },
  segmentText: { fontSize: 14, fontWeight: '800' },
  banner: { flexDirection: 'row', gap: 10, alignItems: 'center', backgroundColor: '#FEF3C7', borderRadius: 14, padding: 12, marginBottom: 14 },
  bannerText: { flex: 1, fontSize: 13, color: '#92400E', lineHeight: 18 },
  card: { backgroundColor: '#FFFFFF', borderRadius: 20, padding: 16, marginBottom: 14 },
  label: { fontSize: 13, fontWeight: '800', color: colors.text.secondary, marginBottom: 6 },
  amountRow: { flexDirection: 'row', alignItems: 'center' },
  currency: { fontSize: 32, fontWeight: '700', color: colors.text.primary, marginRight: 4 },
  amountInput: { flex: 1, fontSize: 38, fontWeight: '800', color: colors.text.primary, padding: 0 },
  quickRow: { flexDirection: 'row', gap: 8, marginTop: 12, flexWrap: 'wrap' },
  quick: { paddingHorizontal: 14, minHeight: 36, justifyContent: 'center', borderRadius: 18, backgroundColor: '#F3F4F6' },
  quickText: { fontSize: 13, fontWeight: '700', color: colors.text.primary },
  balance: { fontSize: 13, color: colors.text.secondary, marginTop: 10 },
  error: { fontSize: 13, color: '#DC2626', marginTop: 6, lineHeight: 18 },
  exposure: { backgroundColor: '#0F172A' },
  expRow: { flexDirection: 'row', justifyContent: 'space-between' },
  expLabel: { fontSize: 12, fontWeight: '700', color: '#94A3B8' },
  expValue: { fontSize: 28, fontWeight: '800', color: '#FFFFFF', marginTop: 2 },
  expSub: { fontSize: 12, color: '#CBD5E1', marginTop: 2 },
  liqBox: { alignItems: 'flex-end' },
  liqValue: { fontSize: 20, fontWeight: '800', marginTop: 4 },
  scenarios: { flexDirection: 'row', gap: 8, marginTop: 14 },
  scenario: { flex: 1, borderRadius: 12, padding: 10, gap: 2 },
  scenarioLabel: { fontSize: 11, fontWeight: '600', color: '#374151' },
  scenarioValue: { fontSize: 16, fontWeight: '800' },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 6, gap: 12 },
  rowLabel: { flex: 1, fontSize: 13, color: colors.text.secondary },
  rowValue: { fontSize: 13, fontWeight: '700', color: colors.text.primary },
  rowStrong: { fontSize: 15, fontWeight: '800', color: colors.text.primary },
  costNote: { fontSize: 12, lineHeight: 17, color: colors.text.light, marginTop: 8 },
  primary: { borderRadius: 16, paddingVertical: 16, alignItems: 'center', backgroundColor: colors.primary, marginTop: 4 },
  primaryText: { color: '#FFFFFF', fontSize: 16, fontWeight: '800' },
  disabled: { opacity: 0.45 },
  footnote: { fontSize: 11, color: colors.text.light, textAlign: 'center', marginTop: 10, lineHeight: 15 },
  sheetBackdrop: { flex: 1, backgroundColor: 'rgba(15,23,42,0.45)' },
  sheet: { backgroundColor: '#FFFFFF', borderTopLeftRadius: 26, borderTopRightRadius: 26, padding: 20, paddingBottom: 34 },
  sheetScroll: { flexShrink: 1 },
  grabber: { alignSelf: 'center', width: 40, height: 5, borderRadius: 3, backgroundColor: '#E5E7EB', marginBottom: 14 },
  sheetTitle: { fontSize: 20, fontWeight: '800', color: colors.text.primary },
  sheetSub: { fontSize: 13, color: colors.text.secondary, marginTop: 2, marginBottom: 14 },
  sheetCard: { backgroundColor: colors.neutral, borderRadius: 16, padding: 14 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 6 },
  sheetNote: { fontSize: 12, lineHeight: 17, color: colors.text.secondary, marginVertical: 14 },
  secondary: { alignItems: 'center', paddingVertical: 14 },
  secondaryText: { fontSize: 15, fontWeight: '700', color: colors.text.secondary },
  typeRow: { flexDirection: 'row', gap: 8, backgroundColor: colors.neutral, borderRadius: 14, padding: 4 },
  typeBtn: { flex: 1, flexDirection: 'row', gap: 6, alignItems: 'center', justifyContent: 'center', minHeight: 40, borderRadius: 11 },
  typeBtnOn: { backgroundColor: '#FFFFFF', shadowColor: '#0F172A', shadowOpacity: 0.08, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 2 },
  typeText: { fontSize: 14, fontWeight: '700', color: colors.text.secondary },
  typeTextOn: { color: colors.text.primary },
  typeHint: { fontSize: 12, lineHeight: 17, color: colors.text.secondary, marginTop: 10 },
  pxRow: { flexDirection: 'row', alignItems: 'center', marginTop: 12, borderBottomWidth: 1, borderBottomColor: colors.border, paddingBottom: 6 },
  pxCurrency: { fontSize: 22, fontWeight: '700', color: colors.text.primary, marginRight: 4 },
  pxInput: { flex: 1, fontSize: 24, fontWeight: '800', color: colors.text.primary, padding: 0 },
  pxMark: { fontSize: 12, fontWeight: '600', color: colors.text.light },
  protectHead: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  protectIcon: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', backgroundColor: '#ECFDF5' },
  protectIconOn: { backgroundColor: colors.primaryDark },
  protectTitle: { fontSize: 15, fontWeight: '800', color: colors.text.primary },
  protectSub: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },
  toggle: { width: 44, height: 26, borderRadius: 13, backgroundColor: '#E5E7EB', padding: 3 },
  toggleOn: { backgroundColor: colors.primary },
  knob: { width: 20, height: 20, borderRadius: 10, backgroundColor: '#FFFFFF' },
  knobOn: { transform: [{ translateX: 18 }] },
  trigger: { marginTop: 16 },
  triggerHead: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  triggerLabel: { flex: 1, fontSize: 13, fontWeight: '800' },
  triggerResult: { fontSize: 14, fontWeight: '800' },
});
