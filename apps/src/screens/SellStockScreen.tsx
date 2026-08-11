// Vender acción — sell flow; proceeds land in cUSD+ and keep earning.
//
// Mirror of BuyStockScreen. The exit message matters as much as the entry:
// selling is not "cashing out of Confío" — the money returns to the sweep
// account and resumes earning Treasury yield immediately. Copy says so.
//
// Preview uses Ondo's non-binding soft quote; confirmation requests a fresh
// binding redemption attestation and atomically settles back into cUSD+.

import React, { useEffect, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  StatusBar,
  TextInput,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  Image,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Header } from '../navigation/Header';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { SuccessHero } from '../components/common/SuccessHero';
import { ReceiptCard } from '../components/common/ReceiptCard';
import { StockTradeSuccessContent } from '../components/common/StockTradeSuccessContent';
import { StockTradeLoadingOverlay } from '../components/common/StockTradeLoadingOverlay';
import { useNumberFormat } from '../utils/numberFormatting';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { useGmMarket } from '../hooks/useGmMarket';
import { TickerLogo } from '../components/TickerLogo';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';
import { STOCKS_TRADING_UI_ENABLED } from '../config/features';
import { getSoftStockQuote, sellStockToSavings } from '../services/ondoStocks';

type NavProp = NativeStackNavigationProp<MainStackParamList>;
type SellRoute = RouteProp<MainStackParamList, 'SellStock'>;

const MIN_AMOUNT_USD = 1;

const getSellQuote = (amountUsd: number, ready: boolean, receiveUsd?: number) => {
  const costPct = 0.3;
  const costUsd = amountUsd * (costPct / 100);
  return {
    costPct,
    costUsd,
    receiveUsd: receiveUsd ?? amountUsd - costUsd,
    paused: !ready,
  };
};

type Phase = 'input' | 'processing' | 'success';

export const SellStockScreen = () => {
  const navigation = useNavigation<NavProp>();
  const route = useRoute<SellRoute>();
  const { formatNumber } = useNumberFormat();
  const { stocks, refetch } = useSavingsPortfolio();
  const { byTicker, tradabilityFor } = useGmMarket(stocks.enabled);

  const stock = byTicker(route.params.ticker);
  const position = stocks.positions.find((p) => p.ticker === route.params.ticker);
  const available = position?.valueUsd ?? 0;

  const [raw, setRaw] = useState('');
  const [sellAll, setSellAll] = useState(false);
  const [phase, setPhase] = useState<Phase>('input');
  const [quoteReady, setQuoteReady] = useState(false);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [tradeError, setTradeError] = useState<string | null>(null);
  const [settledReceiveUsd, setSettledReceiveUsd] = useState(0);
  const [softNetWei, setSoftNetWei] = useState(0n);

  const amount = useMemo(() => {
    const v = parseFloat(raw.replace(',', '.'));
    return Number.isFinite(v) ? v : 0;
  }, [raw]);

  const quote = useMemo(
    () => getSellQuote(amount, quoteReady && !quoteLoading, softNetWei > 0n ? Number(softNetWei) / 1e18 : undefined),
    [amount, quoteReady, quoteLoading, softNetWei],
  );

  useEffect(() => {
    let cancelled = false;
    setTradeError(null);
    setQuoteReady(false);
    setSoftNetWei(0n);
    setQuoteLoading(false);
    if (!stock || !stocks.enabled || !stocks.tradingEnabled || amount < MIN_AMOUNT_USD || amount > available) return;
    setQuoteLoading(true);
    const timer = setTimeout(() => {
      getSoftStockQuote(stock.symbol, 'sell', amount)
        .then((q) => {
          if (!cancelled) {
            const gross = (BigInt(q.tokenAmount) * BigInt(q.price)) / 10n ** 18n;
            setSoftNetWei(gross - (gross * 30n) / 10_000n);
            setQuoteReady(true);
          }
        })
        .catch((e) => {
          if (!cancelled) setTradeError(e instanceof Error ? e.message : 'No pudimos cotizar la venta.');
        })
        .finally(() => { if (!cancelled) setQuoteLoading(false); });
    }, 350);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [amount, available, stock, stocks.enabled, stocks.tradingEnabled]);

  const fmtUsd = (v: number, digits = 2) =>
    `$${formatNumber(v, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

  // Deep-link defense: execution remains unavailable until the server has a
  // deployed, registered router. Selling is not geo-gated once enabled.
  if (!STOCKS_TRADING_UI_ENABLED || !stocks.enabled || !stocks.tradingEnabled || !stock) {
    return (
      <View style={[styles.container, { justifyContent: 'center', alignItems: 'center' }]}>
        <Text style={{ color: colors.text.secondary, textAlign: 'center', paddingHorizontal: 32 }}>
          {stock ? 'Muy pronto podrás vender acciones desde la app.' : 'Acción no encontrada'}
        </Text>
        <TouchableOpacity onPress={() => navigation.goBack()} style={{ marginTop: 16 }}>
          <Text style={{ color: colors.primaryDark, fontWeight: '600' }}>Volver</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const tradability = tradabilityFor(stock);
  const overBalance = amount > available;
  const belowMin = amount > 0 && amount < MIN_AMOUNT_USD;
  const canConfirm =
    amount >= MIN_AMOUNT_USD && !overBalance && !quote.paused && tradability !== 'closed';

  const onConfirm = async () => {
    setTradeError(null);
    setPhase('processing');
    try {
      const result = await sellStockToSavings({
        symbol: stock.symbol,
        grossAmountUsd: amount,
        sellAll,
        minExpectedNetWei: (softNetWei * 99n) / 100n,
      });
      setSettledReceiveUsd(Number(result.expectedNetWei) / 1e18);
      await refetch();
      setPhase('success');
    } catch (e) {
      setTradeError(e instanceof Error ? e.message : 'No pudimos completar la venta.');
      setPhase('input');
    }
  };

  if (phase === 'success') {
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
        <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }} />
        <StockTradeSuccessContent>
          <SuccessHero
            title="Vendido"
            amount={fmtUsd(settledReceiveUsd)}
            hint="Ya está en tu ahorro (cUSD+) y sigue generando rendimiento desde ahora mismo."
          />
          <ReceiptCard
            style={{ marginTop: 4 }}
            items={[
              { label: 'Vendiste', value: fmtUsd(amount) },
              { label: 'Costo de operación', value: `${fmtUsd(quote.costUsd)} (${quote.costPct.toFixed(2)}%)` },
              { label: 'Recibido en tu ahorro', value: fmtUsd(settledReceiveUsd), color: colors.primaryDark },
              { label: 'Fecha', value: `${new Date().toLocaleDateString('es-ES')} · ${new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}` },
              { label: 'Estado', value: 'Completado', color: colors.success, icon: 'check-circle' },
            ]}
          />
          <TouchableOpacity
            style={styles.successCta}
            onPress={() => navigation.goBack()}
            activeOpacity={0.85}
          >
            <Text style={styles.successCtaText}>Ver mi ahorro</Text>
          </TouchableOpacity>
        </StockTradeSuccessContent>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <Header
        navigation={navigation as any}
        title={`Vender ${stock.ticker}`}
        titleAccessory={<TickerLogo ticker={stock.ticker} color={stock.color} logoUrl={stock.logoUrl} size={26} />}
        backgroundColor={colors.primary}
        isLight
        showBackButton
        onBackPress={() => { if (phase !== 'processing') navigation.goBack(); }}
      />

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.amountCard}>
            <Text style={styles.amountLabel}>¿Cuánto quieres vender?</Text>
            <View style={styles.amountRow}>
              <Text style={styles.amountCurrency}>$</Text>
              <TextInput
                style={styles.amountInput}
                value={raw}
                onChangeText={(value) => {
                  setSellAll(false);
                  setRaw(value);
                }}
                keyboardType="decimal-pad"
                placeholder="0.00"
                placeholderTextColor={colors.text.light}
                editable={phase === 'input'}
                autoFocus
              />
            </View>
            <View style={styles.balanceRow}>
              <Text style={[styles.balanceText, overBalance && styles.balanceTextError]}>
                Tu posición: {fmtUsd(available)}
              </Text>
              <TouchableOpacity
                onPress={() => {
                  setSellAll(available > 0);
                  setRaw(available > 0 ? String(available) : '');
                }}
                disabled={phase !== 'input' || available <= 0}
              >
                <Text style={styles.maxBtn}>MAX</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* Destination, payment-method style: proceeds land in the savings
              instrument and keep earning — visible at a glance. */}
          <View style={styles.fundingSource}>
            <Image source={cUSDPlusLogo} style={styles.fundingLogo} />
            <View style={{ flex: 1 }}>
              <Text style={styles.fundingTitle}>Recibes en tu ahorro</Text>
              <Text style={styles.fundingSub}>
                Confío Dollar+ · sigue generando rendimiento
              </Text>
            </View>
            <Icon name="check-circle" size={16} color={colors.primaryDark} />
          </View>

          {tradability === 'reduced' && (
            <View style={styles.sessionHint}>
              <Icon name="moon" size={14} color="#92400E" />
              <Text style={styles.sessionHintText}>
                Sesión extendida: el costo de operación puede ser un poco mayor.
              </Text>
            </View>
          )}

          {amount > 0 && !belowMin && !overBalance && (
            <View style={styles.quoteCard}>
              <View style={styles.quoteRow}>
                <Text style={styles.quoteLabel}>Precio actual</Text>
                <Text style={styles.quoteValue}>{fmtUsd(stock.priceUsd)}</Text>
              </View>
              <View style={styles.quoteRow}>
                <Text style={styles.quoteLabel}>Costo de operación</Text>
                <Text style={styles.quoteValue}>
                  ~{formatNumber(quote.costPct, { maximumFractionDigits: 2 })}% ·{' '}
                  {fmtUsd(quote.costUsd)}
                </Text>
              </View>
              <View style={styles.quoteDivider} />
              <View style={styles.quoteRow}>
                <Text style={styles.quoteLabelStrong}>Recibirás en tu ahorro</Text>
                <Text style={styles.quoteValueStrong}>≈ {fmtUsd(quote.receiveUsd)}</Text>
              </View>
            </View>
          )}

          {belowMin && (
            <Text style={styles.hintError}>El monto mínimo es {fmtUsd(MIN_AMOUNT_USD)}.</Text>
          )}
          {overBalance && (
            <Text style={styles.hintError}>Tu posición es {fmtUsd(available)}.</Text>
          )}
          {tradeError && <Text style={styles.hintError}>{tradeError}</Text>}

          <View style={{ flex: 1 }} />

          <TouchableOpacity
            style={[styles.confirmBtn, (!canConfirm || phase === 'processing') && styles.confirmBtnDisabled]}
            onPress={onConfirm}
            disabled={!canConfirm || phase === 'processing'}
            activeOpacity={0.85}
          >
            {phase === 'processing' ? (
              <>
                <ActivityIndicator color="#fff" size="small" />
                <Text style={styles.confirmBtnText}>Vendiendo…</Text>
              </>
            ) : (
              <Text style={styles.confirmBtnText}>
                {amount > 0 && canConfirm ? `Vender ${fmtUsd(amount)}` : 'Vender'}
              </Text>
            )}
          </TouchableOpacity>
          <Text style={styles.confirmFootnote}>
            La cotización se actualiza al confirmar; lo recibido vuelve a tu ahorro.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
      <StockTradeLoadingOverlay
        visible={phase === 'processing'}
        side="sell"
        ticker={stock.ticker}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },


  scrollContent: { padding: 16, paddingBottom: 32, flexGrow: 1 },

  fundingSource: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  fundingLogo: { width: 30, height: 30, borderRadius: 15 },
  fundingTitle: { fontSize: 13, fontWeight: '700', color: colors.text.primary },
  fundingSub: { fontSize: 12, color: colors.text.secondary, marginTop: 1 },
  amountCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 20,
    marginBottom: 14,
  },
  amountLabel: { fontSize: 14, color: colors.text.secondary },
  amountRow: { flexDirection: 'row', alignItems: 'center', marginTop: 10 },
  amountCurrency: { fontSize: 34, fontWeight: '700', color: colors.text.primary, marginRight: 4 },
  amountInput: {
    flex: 1,
    fontSize: 40,
    fontWeight: 'bold',
    color: colors.text.primary,
    padding: 0,
  },
  balanceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 10,
  },
  balanceText: { fontSize: 13, color: colors.text.secondary },
  balanceTextError: { color: '#DC2626' },
  maxBtn: { fontSize: 13, fontWeight: '800', color: colors.primaryDark },

  sessionHint: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#FEF3C7',
    borderRadius: 12,
    padding: 12,
    marginBottom: 14,
  },
  sessionHintText: { flex: 1, fontSize: 12, color: '#92400E', lineHeight: 17 },

  quoteCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 16,
    marginBottom: 14,
  },
  quoteRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
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
  confirmFootnote: {
    fontSize: 11,
    color: colors.text.light,
    textAlign: 'center',
    marginTop: 10,
    lineHeight: 15,
  },

  successIcon: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 24,
  },
  successTitle: { fontSize: 20, fontWeight: '700', color: colors.text.primary },
  successAmount: { fontSize: 42, fontWeight: 'bold', color: colors.primaryDark, marginTop: 10 },
  successHint: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    marginTop: 14,
    lineHeight: 20,
  },
  successCta: {
    backgroundColor: colors.primary,
    borderRadius: 14,
    paddingVertical: 15,
    paddingHorizontal: 40,
    marginTop: 32,
  },
  successCtaText: { color: '#fff', fontSize: 16, fontWeight: '700' },
});
