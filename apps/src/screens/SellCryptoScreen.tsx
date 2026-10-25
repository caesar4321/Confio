// Vender Bitcoin / oro — proceeds return to the Confío dollar the person
// holds (cUSD+ if Ondo-eligible, otherwise cUSD), through cUSD's ordinary
// 0.9% entry fee. Selling is never gated by country.
//
// A cUSD+ sale netting under US$1.000001 is refused by the relay (Ondo's
// mint floor): the screen says so before confirming and offers to receive
// the sale in Confío Dollar instead, which is always open.
//
// Everything a sale needs comes from the holding (cryptoHoldings), never
// from the discovery catalog: a holder whose country was blocked (no
// cryptoMarket) or whose token was delisted can always sell.

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

import { Text, TextInput } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { SuccessHero } from '../components/common/SuccessHero';
import { ReceiptCard } from '../components/common/ReceiptCard';
import { StockTradeSuccessContent } from '../components/common/StockTradeSuccessContent';
import { StockTradeLoadingOverlay } from '../components/common/StockTradeLoadingOverlay';
import { CryptoAssetMark } from '../components/CryptoAssetMark';
import { colors } from '../config/theme';
import { CRYPTO_TRADING_UI_ENABLED } from '../config/features';
import { useCryptoCapabilities, useCryptoHoldings } from '../hooks/useCrypto';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { requestActivityShare } from '../services/communityShare';
import { createSponsoredRequestId } from '../services/sponsored7702';
import { isOutcomeUnknown } from '../services/evmWallet';
import {
  cryptoErrorCode,
  cryptoTradeError,
  previewCryptoSell,
  SAVINGS_MINT_TOO_SMALL_MESSAGE,
  sellCrypto,
  unitsForUsd,
} from '../services/cryptoTrading';
import { DOLLAR, DOLLAR_PLUS, marketCostPct, sellFloors } from '../services/cryptoSwapMath';
import { MainStackParamList } from '../types/navigation';
import { useNumberFormat } from '../utils/numberFormatting';
import { formatPercent, parseAmountInput, sanitizeAmountInput, toAmountInput } from '../utils/numberLocale';
import { feePctLabel, formatUnits, fundingDollarName } from '../utils/cryptoPresentation';

type NavProp = NativeStackNavigationProp<MainStackParamList>;
type SellRoute = RouteProp<MainStackParamList, 'SellCrypto'>;

type Phase = 'input' | 'processing' | 'success';

export const SellCryptoScreen = () => {
  const navigation = useNavigation<NavProp>();
  const route = useRoute<SellRoute>();
  const { formatNumber } = useNumberFormat();
  const { capabilities, refetch: refetchCaps } = useCryptoCapabilities();
  const { holdings, refetch: refetchHoldings } = useCryptoHoldings();
  const { refetch: refetchPortfolio } = useSavingsPortfolio();
  const position = (holdings ?? []).find((h) => h.symbol === route.params.symbol);
  // Kept after a MAX sale empties the position (the refetch drops the row).
  const [lastPosition, setLastPosition] = useState(position);
  useEffect(() => { if (position) setLastPosition(position); }, [position]);
  const asset = position ?? lastPosition;
  const heldUnits = useMemo(() => {
    try {
      return BigInt(position?.units || '0');
    } catch {
      return 0n;
    }
  }, [position?.units]);
  const positionUsd = position?.valueUsd ?? null;

  const funding = capabilities?.fundingDollar ?? 'cusd';
  const feeBps = capabilities?.feeBps ?? null;
  const slipBps = BigInt(capabilities?.maxSlippageBps ?? 100);

  const [raw, setRaw] = useState('');
  const [sellAll, setSellAll] = useState(false);
  // Receive in Confío Dollar instead of Dollar+ (small cUSD+ sales).
  const [intoCusd, setIntoCusd] = useState(false);
  const [phase, setPhase] = useState<Phase>('input');
  const [preview, setPreview] = useState<{ usdtOut: bigint; netWei: bigint; poolFeeBps: number | null; impactBps: number | null } | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [tradeError, setTradeError] = useState<string | null>(null);
  const [settledNetUsd, setSettledNetUsd] = useState(0);
  const [settledUnits, setSettledUnits] = useState(0n);
  // The receipt shows what was signed, frozen at settlement.
  const [settledFee, setSettledFee] = useState<{ usd: number; bps: number } | null>(null);
  const [quoteNonce, setQuoteNonce] = useState(0);
  const [priceMoved, setPriceMoved] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [settledDest, setSettledDest] = useState<string>(fundingDollarName(funding));
  const confirmInFlight = useRef(false);
  const requestIdRef = useRef<string | null>(null);

  const changeAmount = (value: string, isMax = false) => {
    requestIdRef.current = null;
    setPriceMoved(null);
    setSellAll(isMax && heldUnits > 0n);
    setRaw((prev) => (isMax ? value : sanitizeAmountInput(value, 2, undefined, prev)));
  };

  const amount = useMemo(() => {
    const v = parseAmountInput(raw);
    return Number.isFinite(v) ? v : 0;
  }, [raw]);

  const units = sellAll ? heldUnits : unitsForUsd(heldUnits, positionUsd ?? 0, amount);

  useEffect(() => {
    let cancelled = false;
    setTradeError(null);
    setErrorCode(null);
    setPreview(null);
    setQuoteLoading(false);
    if (!asset || feeBps == null || !capabilities?.tradingEnabled || units <= 0n) return;
    setQuoteLoading(true);
    const timer = setTimeout(() => {
      previewCryptoSell({ symbol: asset.symbol, units, feeBps })
        .then((q) => {
          if (!cancelled) {
            setPreview({
              usdtOut: BigInt(q.expectedOut), netWei: q.netWei, poolFeeBps: q.poolFeeBps, impactBps: q.priceImpactBps,
            });
          }
        })
        .catch((e) => { if (!cancelled) setTradeError(cryptoTradeError(e, 'sell')); })
        .finally(() => { if (!cancelled) setQuoteLoading(false); });
    }, 350);
    return () => { cancelled = true; clearTimeout(timer); };
    // `units` is a bigint: compare by value through its string.
  }, [asset?.symbol, feeBps, capabilities?.tradingEnabled, units.toString(), quoteNonce]); // eslint-disable-line react-hooks/exhaustive-deps

  const fmtUsd = (v: number) =>
    `$${formatNumber(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  if (!CRYPTO_TRADING_UI_ENABLED || !capabilities?.tradingEnabled || !asset) {
    return (
      <View style={[styles.container, styles.center]}>
        <Text style={styles.unavailable}>
          {asset ? 'Muy pronto podrás vender desde aquí.' : 'Activo no disponible'}
        </Text>
        <TouchableOpacity onPress={() => navigation.goBack()} style={{ marginTop: 16 }}>
          <Text style={styles.back}>Volver</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const destIsPlus = funding === 'cusd_plus' && !intoCusd;
  const destName = destIsPlus ? 'Confío Dollar+' : 'Confío Dollar';
  // Same check the relay makes, on the preview's own quote.
  const tooSmallForPlus = Boolean(
    destIsPlus && preview && feeBps != null
    && sellFloors({ dollar: DOLLAR_PLUS, quotedUsdtOut: preview.usdtOut, feeBps: BigInt(feeBps), slipBps })
      .savingsMintTooSmall,
  );
  const overBalance = positionUsd != null && !sellAll && amount > positionUsd;
  const netUsd = preview ? Number(preview.netWei) / 1e18 : 0;
  const costPct = preview ? marketCostPct(preview.poolFeeBps, preview.impactBps) : null;
  const canConfirm = units > 0n && !overBalance && !quoteLoading && preview !== null
    && feeBps != null && !tooSmallForPlus;

  const onConfirm = async () => {
    if (!canConfirm || confirmInFlight.current) return;
    confirmInFlight.current = true;
    setTradeError(null);
    setPhase('processing');
    try {
      const requestId = requestIdRef.current || createSponsoredRequestId();
      requestIdRef.current = requestId;
      const result = await sellCrypto({
        asset,
        units,
        sellAll,
        expectedFeeBps: feeBps,
        expectedFunding: funding,
        intoCusd: funding === 'cusd_plus' && intoCusd,
        previewUsdtOut: preview?.usdtOut,
        requestId,
      });
      setSettledNetUsd(Number(result.expectedNetWei) / 1e18);
      setSettledUnits(result.unitsSold);
      setSettledFee({ usd: Number(result.feeWei) / 1e18, bps: result.feeBps });
      setSettledDest(result.dollar === DOLLAR ? 'Confío Dollar' : 'Confío Dollar+');
      setPhase('success');
      requestActivityShare({ group: 'crypto', reference: result.txHash });
      void refetchHoldings().catch(() => undefined);
      void refetchPortfolio().catch(() => undefined);
    } catch (e) {
      if (!isOutcomeUnknown(e)) requestIdRef.current = null;
      const code = cryptoErrorCode(e);
      if (code === 'FEE_CHANGED' || code === 'FUNDING_CHANGED') void refetchCaps().catch(() => undefined);
      setPhase('input');
      if (code === 'PRICE_MOVED' || code === 'bad_crypto_floor') {
        // Re-quote; the person confirms the new amount.
        setPriceMoved(cryptoTradeError(e, 'sell'));
        setQuoteNonce((n) => n + 1);
        return;
      }
      setErrorCode(code);
      setTradeError(cryptoTradeError(e, 'sell'));
    } finally {
      confirmInFlight.current = false;
    }
  };

  if (phase === 'success') {
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.heroField} />
        <SafeAreaView edges={['top']} style={{ backgroundColor: colors.heroField }} />
        <StockTradeSuccessContent>
          <SuccessHero
            title="Vendido"
            amount={`≈ ${fmtUsd(settledNetUsd)}`}
            hint={`Ya está en tu ${settledDest}.`}
          />
          <ReceiptCard
            style={{ marginTop: 4 }}
            items={[
              { label: 'Vendiste', value: `${formatUnits(settledUnits, asset.decimals)} ${asset.ticker}` },
              ...(settledFee
                ? [{ label: 'Comisión de Confío', value: `${fmtUsd(settledFee.usd)} (${feePctLabel(settledFee.bps)}%)` }]
                : []),
              { label: `Recibido en ${settledDest}`, value: `≈ ${fmtUsd(settledNetUsd)}`, color: colors.primaryDark },
              { label: 'Fecha', value: `${new Date().toLocaleDateString('es-ES')} · ${new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}` },
              { label: 'Estado', value: 'Completado', color: colors.success, icon: 'check-circle' },
            ]}
          />
          <TouchableOpacity style={styles.successCta} onPress={() => navigation.goBack()} activeOpacity={0.85}>
            <Text style={styles.successCtaText}>Listo</Text>
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
        title={`Vender ${asset.ticker}`}
        titleAccessory={<CryptoAssetMark ticker={asset.ticker} category={asset.category} size={26} />}
        backgroundColor={colors.heroField}
        isLight
        showBackButton
        onBackPress={() => { if (phase !== 'processing') navigation.goBack(); }}
      />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
          <View style={styles.amountCard}>
            <Text style={styles.amountLabel}>¿Cuánto quieres vender?</Text>
            <View style={styles.amountRow}>
              <Text style={styles.amountCurrency}>$</Text>
              <TextInput
                style={styles.amountInput}
                value={raw}
                onChangeText={(value) => changeAmount(value)}
                keyboardType="decimal-pad"
                placeholder="0.00"
                placeholderTextColor={colors.text.light}
                // Without a price the dollar amount can't map to units: MAX only.
                editable={phase === 'input' && positionUsd != null}
                autoFocus={positionUsd != null}
                testID="crypto-sell-amount"
              />
            </View>
            <View style={styles.balanceRow}>
              <Text style={[styles.balanceText, overBalance && styles.balanceTextError]}>
                Tu posición: {positionUsd != null ? fmtUsd(positionUsd) : '—'} · {formatUnits(heldUnits, asset.decimals)} {asset.ticker}
              </Text>
              <TouchableOpacity
                onPress={() => changeAmount(positionUsd != null ? toAmountInput(positionUsd) : '', true)}
                disabled={phase !== 'input' || heldUnits <= 0n}
              >
                <Text style={styles.maxBtn}>MAX</Text>
              </TouchableOpacity>
            </View>
          </View>

          <View style={styles.fundingSource}>
            <Icon name="dollar-sign" size={18} color={colors.primaryDark} />
            <View style={{ flex: 1 }}>
              <Text style={styles.fundingTitle}>Recibes en · {destName}</Text>
              {funding === 'cusd_plus' && intoCusd ? (
                <TouchableOpacity onPress={() => setIntoCusd(false)}>
                  <Text style={styles.link}>Recibir en Confío Dollar+</Text>
                </TouchableOpacity>
              ) : null}
            </View>
            <Icon name="check-circle" size={16} color={colors.primaryDark} />
          </View>

          {units > 0n && !overBalance && (
            <View style={styles.quoteCard}>
              <View style={styles.quoteRow}>
                <Text style={styles.quoteLabel}>Vendes</Text>
                <Text style={styles.quoteValue}>{formatUnits(units, asset.decimals)} {asset.ticker}</Text>
              </View>
              {costPct != null && (
                <View style={styles.quoteRow}>
                  <Text style={styles.quoteLabel}>Costo de mercado</Text>
                  <Text style={styles.quoteValue}>~{formatPercent(costPct, 2)}%</Text>
                </View>
              )}
              <View style={styles.quoteDivider} />
              <View style={styles.quoteRow}>
                <Text style={styles.quoteLabelStrong}>Recibes</Text>
                <Text style={styles.quoteValueStrong}>{quoteLoading || !preview ? '…' : `≈ ${fmtUsd(netUsd)}`}</Text>
              </View>
            </View>
          )}

          {tooSmallForPlus && (
            <View style={styles.smallSale}>
              <Text style={styles.hintError}>{SAVINGS_MINT_TOO_SMALL_MESSAGE}</Text>
              <TouchableOpacity onPress={() => setIntoCusd(true)} accessibilityRole="button" testID="crypto-sell-into-cusd">
                <Text style={styles.link}>Recibir en Confío Dollar →</Text>
              </TouchableOpacity>
            </View>
          )}
          {priceMoved && <Text style={styles.hintError} testID="crypto-price-moved">{priceMoved}</Text>}
          {overBalance && <Text style={styles.hintError}>Tu posición es {fmtUsd(positionUsd ?? 0)}.</Text>}
          {tradeError && <Text style={styles.hintError}>{tradeError}</Text>}
          {destIsPlus && (errorCode === 'savings_mint_too_small' || errorCode === 'savings_not_available') && (
            <TouchableOpacity onPress={() => { setIntoCusd(true); setTradeError(null); setErrorCode(null); }} accessibilityRole="button">
              <Text style={[styles.link, styles.errorLink]}>Recibir en Confío Dollar →</Text>
            </TouchableOpacity>
          )}

          <View style={{ flex: 1 }} />

          <TouchableOpacity
            style={[styles.confirmBtn, (!canConfirm || phase === 'processing') && styles.confirmBtnDisabled]}
            onPress={onConfirm}
            disabled={!canConfirm || phase === 'processing'}
            activeOpacity={0.85}
            testID="crypto-sell-confirm"
          >
            {phase === 'processing' ? (
              <>
                <ActivityIndicator color="#fff" size="small" />
                <Text style={styles.confirmBtnText}>Vendiendo…</Text>
              </>
            ) : (
              <Text style={styles.confirmBtnText}>{sellAll ? `Vender todo mi ${asset.ticker}` : 'Vender'}</Text>
            )}
          </TouchableOpacity>
          <Text style={styles.confirmFootnote}>
            Se actualizará la cotización al confirmar; si el precio se mueve más de{' '}
            {formatPercent(Number(slipBps) / 100, 2)}%, no se ejecutará.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
      <StockTradeLoadingOverlay visible={phase === 'processing'} side="sell" ticker={asset.ticker} />
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
  balanceRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 10, gap: 8 },
  balanceText: { flex: 1, fontSize: 13, color: colors.text.secondary },
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
  link: { fontSize: 13, fontWeight: '700', color: colors.primaryDark, marginTop: 2 },
  quoteCard: { backgroundColor: '#fff', borderRadius: 16, padding: 16, marginBottom: 14 },
  quoteRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 },
  quoteLabel: { fontSize: 13, color: colors.text.secondary },
  quoteValue: { fontSize: 13, fontWeight: '600', color: colors.text.primary },
  quoteDivider: { height: 1, backgroundColor: colors.surfaceMuted, marginVertical: 8 },
  quoteLabelStrong: { fontSize: 14, fontWeight: '700', color: colors.text.primary },
  quoteValueStrong: { fontSize: 16, fontWeight: '800', color: colors.primaryDark },
  smallSale: { marginBottom: 14 },
  errorLink: { marginLeft: 4, marginBottom: 14 },
  hintError: { fontSize: 13, color: '#DC2626', marginBottom: 8, marginLeft: 4 },
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
