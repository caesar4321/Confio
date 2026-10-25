// Comprar Bitcoin / oro — paid with the Confío dollar the person holds.
//
// Same grammar as BuyStockScreen: amount → live quote → confirm →
// processing → success. Confío charges no product fee: the only charge is
// cUSD's ordinary 0.9% when dollars leave (shown from feeBps), plus
// PancakeSwap's market cost (pool fees + price impact), shown separately.
//
// The one-time risk disclosure (served by cryptoCapabilities) is confirmed
// before the first purchase; the relay refuses a buy without it.

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StatusBar,
  StyleSheet,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { RouteProp, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useMutation } from '@apollo/client';

import { Text, TextInput } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { SuccessHero } from '../components/common/SuccessHero';
import { ReceiptCard } from '../components/common/ReceiptCard';
import { StockTradeSuccessContent } from '../components/common/StockTradeSuccessContent';
import { StockTradeLoadingOverlay } from '../components/common/StockTradeLoadingOverlay';
import { StockRiskSheet } from '../components/StockRiskSheet';
import { CryptoAssetMark } from '../components/CryptoAssetMark';
import { colors } from '../config/theme';
import { CRYPTO_TRADING_UI_ENABLED } from '../config/features';
import { useCryptoCapabilities, useCryptoHoldings, useCryptoMarket } from '../hooks/useCrypto';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { requestActivityShare } from '../services/communityShare';
import { createSponsoredRequestId } from '../services/sponsored7702';
import { isOutcomeUnknown } from '../services/evmWallet';
import {
  ACKNOWLEDGE_CRYPTO_RISK,
  buyCrypto,
  cryptoErrorCode,
  cryptoTradeError,
  isCryptoAckRequired,
  previewCryptoBuy,
} from '../services/cryptoTrading';
import { marketCostPct } from '../services/cryptoSwapMath';
import { MainStackParamList } from '../types/navigation';
import { useNumberFormat } from '../utils/numberFormatting';
import { parseAmountInput, sanitizeAmountInput, toAmountInput, formatPercent } from '../utils/numberLocale';
import {
  feePctLabel,
  formatUnits,
  formatUsdPrice,
  fundingDollarName,
} from '../utils/cryptoPresentation';

type NavProp = NativeStackNavigationProp<MainStackParamList>;
type BuyRoute = RouteProp<MainStackParamList, 'BuyCrypto'>;

export const MIN_CRYPTO_BUY_USD = 1;

type Phase = 'input' | 'processing' | 'success';

export const BuyCryptoScreen = () => {
  const navigation = useNavigation<NavProp>();
  const route = useRoute<BuyRoute>();
  const { formatNumber } = useNumberFormat();
  const { capabilities, refetch: refetchCaps } = useCryptoCapabilities();
  const enabled = Boolean(capabilities?.enabled);
  const { bySymbol } = useCryptoMarket(enabled);
  const asset = bySymbol(route.params.symbol);
  const { savings, cusdBalanceUsd, refetch: refetchPortfolio } = useSavingsPortfolio();
  // Shares Apollo's cache with Detail, Sell and Home: refetched after a buy.
  const { refetch: refetchHoldings } = useCryptoHoldings(false, 0);
  const [acknowledgeRisk] = useMutation(ACKNOWLEDGE_CRYPTO_RISK);

  const funding = capabilities?.fundingDollar ?? 'cusd';
  const balance = funding === 'cusd_plus' ? savings.balanceUsd : cusdBalanceUsd;
  // A thin pool's per-order cap binds the input (none of the launch assets has one).
  const cap = asset?.maxOrderUsd != null ? Math.min(balance, asset.maxOrderUsd) : balance;
  const feeBps = capabilities?.feeBps ?? null;

  const [raw, setRaw] = useState('');
  const [spendAll, setSpendAll] = useState(false);
  const [phase, setPhase] = useState<Phase>('input');
  const [preview, setPreview] = useState<{ tokenOut: bigint; poolFeeBps: number | null; impactBps: number | null } | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [tradeError, setTradeError] = useState<string | null>(null);
  const [settledUnits, setSettledUnits] = useState<bigint>(0n);
  // The receipt shows what was signed, frozen at settlement.
  const [settledFee, setSettledFee] = useState<{ usd: number; bps: number } | null>(null);
  // A fresh quote moved past what was shown: re-quote and make the person
  // confirm the new amount (never retry against the stale preview).
  const [quoteNonce, setQuoteNonce] = useState(0);
  const [priceMoved, setPriceMoved] = useState<string | null>(null);
  const [riskSheet, setRiskSheet] = useState(false);
  const riskAcknowledged = useRef(false);
  const confirmInFlight = useRef(false);
  const requestIdRef = useRef<string | null>(null);
  const onConfirmRef = useRef<() => Promise<void>>(async () => undefined);
  // Each sheet opening is a flow: a confirmation that lands after the person
  // dismissed it or changed the amount never buys anything (BuyStockScreen).
  const riskFlow = useRef(0);
  const riskTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    riskFlow.current += 1;
    if (riskTimer.current) clearTimeout(riskTimer.current);
  }, []);
  const openRiskSheet = (delayMs = 0) => {
    riskFlow.current += 1;
    const flow = riskFlow.current;
    if (riskTimer.current) clearTimeout(riskTimer.current);
    if (delayMs <= 0) {
      setRiskSheet(true);
      return;
    }
    riskTimer.current = setTimeout(() => {
      if (flow === riskFlow.current) setRiskSheet(true);
    }, delayMs);
  };

  const changeAmount = (value: string, isMax = false) => {
    requestIdRef.current = null;
    riskFlow.current += 1;
    setPriceMoved(null);
    setSpendAll(isMax && cap === balance && balance > 0);
    setRaw((prev) => (isMax ? value : sanitizeAmountInput(value, 2, undefined, prev)));
  };

  const amount = useMemo(() => {
    const v = parseAmountInput(raw);
    return Number.isFinite(v) ? v : 0;
  }, [raw]);

  useEffect(() => {
    let cancelled = false;
    setTradeError(null);
    setPreview(null);
    setQuoteLoading(false);
    if (!asset || feeBps == null || !capabilities?.buyEnabled || amount < MIN_CRYPTO_BUY_USD || amount > cap) return;
    setQuoteLoading(true);
    const timer = setTimeout(() => {
      previewCryptoBuy({ symbol: asset.symbol, grossAmountUsd: amount, feeBps })
        .then((q) => {
          if (!cancelled) {
            setPreview({ tokenOut: BigInt(q.expectedOut), poolFeeBps: q.poolFeeBps, impactBps: q.priceImpactBps });
          }
        })
        .catch((e) => { if (!cancelled) setTradeError(cryptoTradeError(e, 'buy')); })
        .finally(() => { if (!cancelled) setQuoteLoading(false); });
    }, 350);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [amount, asset, cap, capabilities?.buyEnabled, feeBps, quoteNonce]);

  const fmtUsd = (v: number) =>
    `$${formatNumber(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  // Deep-link defense: the server gates stay authoritative.
  if (!CRYPTO_TRADING_UI_ENABLED || !capabilities?.tradingEnabled || !capabilities.buyEnabled || !asset) {
    return (
      <View style={[styles.container, styles.center]}>
        <Text style={styles.unavailable}>
          {capabilities?.blockedMessage
            || (asset ? 'Muy pronto podrás comprar desde aquí.' : 'Activo no disponible')}
        </Text>
        <TouchableOpacity onPress={() => navigation.goBack()} style={{ marginTop: 16 }}>
          <Text style={styles.back}>Volver</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const fundingName = fundingDollarName(funding);
  const feeUsd = feeBps != null ? amount * (feeBps / 10_000) : 0;
  const costPct = preview ? marketCostPct(preview.poolFeeBps, preview.impactBps) : null;
  const overBalance = amount > balance;
  const overCap = !overBalance && amount > cap;
  const belowMin = amount > 0 && amount < MIN_CRYPTO_BUY_USD;
  const canConfirm = amount >= MIN_CRYPTO_BUY_USD && !overBalance && !overCap
    && !quoteLoading && preview !== null && feeBps != null;

  const onConfirm = async () => {
    if (!canConfirm || confirmInFlight.current) return;
    if (capabilities.ackRequired && !riskAcknowledged.current) {
      openRiskSheet();
      return;
    }
    confirmInFlight.current = true;
    setTradeError(null);
    setPhase('processing');
    try {
      const requestId = requestIdRef.current || createSponsoredRequestId();
      requestIdRef.current = requestId;
      const result = await buyCrypto({
        asset,
        grossAmountUsd: amount,
        spendAll,
        expectedFeeBps: feeBps,
        expectedFunding: funding,
        previewTokenOut: preview?.tokenOut,
        requestId,
      });
      setSettledUnits(result.tokenOutUnits);
      setSettledFee({ usd: Number(result.feeWei) / 1e18, bps: result.feeBps });
      setPhase('success');
      requestActivityShare({ group: 'crypto', reference: result.txHash });
      void refetchPortfolio().catch(() => undefined);
      void refetchHoldings().catch(() => undefined);
    } catch (e) {
      if (!isOutcomeUnknown(e)) requestIdRef.current = null;
      if (isCryptoAckRequired(e)) {
        riskAcknowledged.current = false;
        setPhase('input');
        void refetchCaps().catch(() => undefined);
        openRiskSheet(400);
        return;
      }
      const code = cryptoErrorCode(e);
      // A changed fee or funding dollar re-prices the trade: show it first.
      if (code === 'FEE_CHANGED' || code === 'FUNDING_CHANGED') void refetchCaps().catch(() => undefined);
      setPhase('input');
      if (code === 'PRICE_MOVED' || code === 'bad_crypto_floor') {
        setPriceMoved(cryptoTradeError(e, 'buy'));
        setQuoteNonce((n) => n + 1);
        return;
      }
      setTradeError(cryptoTradeError(e, 'buy'));
    } finally {
      confirmInFlight.current = false;
    }
  };
  onConfirmRef.current = onConfirm;

  if (phase === 'success') {
    const units = formatUnits(settledUnits, asset.decimals);
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
        <SafeAreaView edges={['top']} style={{ backgroundColor: colors.heroField }} />
        <StockTradeSuccessContent>
          <SuccessHero
            title={`Ya tienes ${asset.ticker}`}
            amount={`≈ ${units} ${asset.ticker}`}
            hint="Queda en tu cuenta. Puedes venderlo cuando quieras, a cualquier hora."
            icon={<CryptoAssetMark ticker={asset.ticker} category={asset.category} size={72} />}
          />
          <ReceiptCard
            style={{ marginTop: 4 }}
            items={[
              { label: `Pagaste con ${fundingName}`, value: fmtUsd(amount) },
              ...(settledFee
                ? [{ label: 'Comisión de Confío', value: `${fmtUsd(settledFee.usd)} (${feePctLabel(settledFee.bps)}%)` }]
                : []),
              { label: 'Recibiste', value: `≈ ${units} ${asset.ticker}`, color: colors.primaryDark },
              { label: 'Fecha', value: `${new Date().toLocaleDateString('es-ES')} · ${new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}` },
              { label: 'Estado', value: 'Completado', color: colors.success, icon: 'check-circle' },
            ]}
          />
          <TouchableOpacity style={styles.successCta} onPress={() => navigation.goBack()} activeOpacity={0.85}>
            <Text style={styles.successCtaText}>Ver mi posición</Text>
          </TouchableOpacity>
        </StockTradeSuccessContent>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
      <Header
        navigation={navigation as any}
        title={`Comprar ${asset.ticker}`}
        titleAccessory={<CryptoAssetMark ticker={asset.ticker} category={asset.category} size={26} />}
        backgroundColor={colors.heroField}
        isLight
        showBackButton
        onBackPress={() => { if (phase !== 'processing') navigation.goBack(); }}
      />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
          <View style={styles.amountCard}>
            <Text style={styles.amountLabel}>¿Cuánto quieres comprar?</Text>
            <View style={styles.amountRow}>
              <Text style={styles.amountCurrency}>$</Text>
              <TextInput
                style={styles.amountInput}
                value={raw}
                onChangeText={(value) => changeAmount(value)}
                keyboardType="decimal-pad"
                placeholder="0.00"
                placeholderTextColor={colors.text.light}
                editable={phase === 'input'}
                autoFocus
                testID="crypto-buy-amount"
              />
            </View>
            <View style={styles.balanceRow}>
              <Text style={[styles.balanceText, overBalance && styles.balanceTextError]}>
                Disponible: {fmtUsd(balance)}
              </Text>
              <TouchableOpacity
                onPress={() => changeAmount(cap > 0 ? toAmountInput(Math.floor(cap * 100) / 100) : '', true)}
                disabled={phase !== 'input' || cap <= 0}
              >
                <Text style={styles.maxBtn}>MAX</Text>
              </TouchableOpacity>
            </View>
          </View>

          <View style={styles.fundingSource}>
            <Icon name="dollar-sign" size={18} color={colors.primaryDark} />
            <View style={{ flex: 1 }}>
              <Text style={styles.fundingTitle}>Pagas con · {fundingName}</Text>
              <Text style={styles.fundingSub}>{fmtUsd(balance)} disponibles</Text>
            </View>
            <Icon name="check-circle" size={16} color={colors.primaryDark} />
          </View>

          {amount > 0 && !belowMin && !overBalance && !overCap && (
            <View style={styles.quoteCard}>
              <View style={styles.quoteRow}>
                <Text style={styles.quoteLabel}>Precio actual</Text>
                <Text style={styles.quoteValue}>{formatUsdPrice(asset.priceUsd)}</Text>
              </View>
              {feeBps != null && (
                <View style={styles.quoteRow}>
                  <Text style={styles.quoteLabel}>Comisión de Confío {feePctLabel(feeBps)}%</Text>
                  <Text style={styles.quoteValue}>{fmtUsd(feeUsd)}</Text>
                </View>
              )}
              {costPct != null && (
                <View style={styles.quoteRow}>
                  <Text style={styles.quoteLabel}>Costo de mercado</Text>
                  <Text style={styles.quoteValue}>~{formatPercent(costPct, 2)}%</Text>
                </View>
              )}
              <View style={styles.quoteDivider} />
              <View style={styles.quoteRow}>
                <Text style={styles.quoteLabelStrong}>Recibes</Text>
                <Text style={styles.quoteValueStrong}>
                  {quoteLoading || !preview
                    ? '…'
                    : `≈ ${formatUnits(preview.tokenOut, asset.decimals)} ${asset.ticker}`}
                </Text>
              </View>
            </View>
          )}

          {belowMin && <Text style={styles.hintError}>El monto mínimo es {fmtUsd(MIN_CRYPTO_BUY_USD)}.</Text>}
          {overBalance && <Text style={styles.hintError}>Tu saldo en {fundingName} es {fmtUsd(balance)}.</Text>}
          {overCap && <Text style={styles.hintError}>El máximo por compra de {asset.ticker} es {fmtUsd(cap)}.</Text>}
          {priceMoved && <Text style={styles.hintError} testID="crypto-price-moved">{priceMoved}</Text>}
          {tradeError && <Text style={styles.hintError}>{tradeError}</Text>}

          <View style={{ flex: 1 }} />

          <TouchableOpacity
            style={[styles.confirmBtn, (!canConfirm || phase === 'processing') && styles.confirmBtnDisabled]}
            onPress={onConfirm}
            disabled={!canConfirm || phase === 'processing'}
            activeOpacity={0.85}
            testID="crypto-buy-confirm"
          >
            {phase === 'processing' ? (
              <>
                <ActivityIndicator color="#fff" size="small" />
                <Text style={styles.confirmBtnText}>Comprando…</Text>
              </>
            ) : (
              <Text style={styles.confirmBtnText}>
                {amount > 0 && canConfirm ? `Comprar ${fmtUsd(amount)}` : 'Comprar'}
              </Text>
            )}
          </TouchableOpacity>
          <Text style={styles.confirmFootnote}>
            Se actualizará la cotización al confirmar; si el precio se mueve más de{' '}
            {formatPercent((capabilities.maxSlippageBps ?? 100) / 100, 2)}%, no se ejecutará.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
      <StockRiskSheet
        visible={riskSheet}
        title={capabilities.disclosureTitle}
        points={capabilities.disclosurePoints ?? []}
        version={capabilities.ackVersion ?? null}
        onRefresh={refetchCaps}
        acknowledge={async (version) => {
          const { data } = await acknowledgeRisk({ variables: { version } });
          return data?.acknowledgeCryptoRisk;
        }}
        onClose={() => {
          riskFlow.current += 1;
          setRiskSheet(false);
        }}
        beginAccept={() => riskFlow.current}
        onAccepted={(flow) => {
          riskAcknowledged.current = true;
          void refetchCaps().catch(() => undefined);
          if (flow === undefined || flow !== riskFlow.current) return;
          setRiskSheet(false);
          if (riskTimer.current) clearTimeout(riskTimer.current);
          riskTimer.current = setTimeout(() => {
            if (flow === riskFlow.current) void onConfirmRef.current();
          }, 400);
        }}
      />
      <StockTradeLoadingOverlay visible={phase === 'processing'} side="buy" ticker={asset.ticker} />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  center: { justifyContent: 'center', alignItems: 'center' },
  unavailable: { color: colors.text.secondary, textAlign: 'center', paddingHorizontal: 32 },
  back: { color: colors.primaryDark, fontWeight: '600' },
  scrollContent: { padding: 16, paddingBottom: 32, flexGrow: 1 },
  amountCard: { backgroundColor: '#fff', borderRadius: 16, padding: 20, marginBottom: 14 },
  amountLabel: { fontSize: 14, color: colors.text.secondary },
  amountRow: { flexDirection: 'row', alignItems: 'center', marginTop: 10 },
  amountCurrency: { fontSize: 34, fontWeight: '700', color: colors.text.primary, marginRight: 4 },
  amountInput: { flex: 1, fontSize: 40, fontWeight: 'bold', color: colors.text.primary, padding: 0 },
  balanceRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 10 },
  balanceText: { fontSize: 13, color: colors.text.secondary },
  balanceTextError: { color: '#DC2626' },
  maxBtn: { fontSize: 13, fontWeight: '800', color: colors.primaryDark },
  fundingSource: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  fundingTitle: { fontSize: 13, fontWeight: '700', color: colors.text.primary },
  fundingSub: { fontSize: 12, color: colors.text.secondary, marginTop: 1 },
  quoteCard: { backgroundColor: '#fff', borderRadius: 16, padding: 16, marginBottom: 14 },
  quoteRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 },
  quoteLabel: { fontSize: 13, color: colors.text.secondary },
  quoteValue: { fontSize: 13, fontWeight: '600', color: colors.text.primary },
  quoteDivider: { height: 1, backgroundColor: colors.surfaceMuted, marginVertical: 8 },
  quoteLabelStrong: { fontSize: 14, fontWeight: '700', color: colors.text.primary },
  quoteValueStrong: { fontSize: 16, fontWeight: '800', color: colors.primaryDark },
  hintError: { fontSize: 13, color: '#DC2626', marginBottom: 14, marginLeft: 4 },
  confirmBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    backgroundColor: colors.primary,
    borderRadius: 14,
    paddingVertical: 16,
  },
  confirmBtnDisabled: { opacity: 0.5 },
  confirmBtnText: { color: '#fff', fontSize: 16, fontWeight: '700' },
  confirmFootnote: { fontSize: 11, color: colors.text.light, textAlign: 'center', marginTop: 10, lineHeight: 15 },
  successCta: { backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 15, paddingHorizontal: 40, marginTop: 32 },
  successCtaText: { color: '#fff', fontSize: 16, fontWeight: '700' },
});
