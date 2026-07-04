// Comprar acción — buy flow funded from cUSD+ (sweep model).
//
// Same grammar as ConvertAhorroScreen: amount → live quote preview →
// confirm → processing → success. The quote line shows token quantity
// (fractional shares) and the pass-through operation cost.
//
// Wiring points (stubbed until the GM backend proxy lands):
// - getStockQuote(): becomes the RFQ/attestation soft-quote endpoint
//   (short duration = tighter spread, long = extended validity, per Ondo).
// - onConfirm(): binding attestation → on-chain settle from the cUSD+ vault.
//
// Empty-funds cross-sell: if cUSD+ can't cover the amount, the error links
// straight into the savings funding flow — investing money always passes
// through the sweep account, never around it.

import React, { useMemo, useState } from 'react';
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
import { useNumberFormat } from '../utils/numberFormatting';
import { useAhorrosPortfolio } from '../hooks/useAhorrosPortfolio';
import { useGmMarket } from '../hooks/useGmMarket';
import { TickerLogo } from '../components/TickerLogo';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';

type NavProp = NativeStackNavigationProp<MainStackParamList>;
type BuyRoute = RouteProp<MainStackParamList, 'BuyStock'>;

const MIN_AMOUNT_USD = 1;

// TODO(gm): RFQ/attestation soft quote via backend proxy.
const getStockQuote = (amountUsd: number, priceUsd: number) => {
  // STUB, NOT PRICING — real cost = Ondo GM fee (schedule unknown until
  // onboarding) + Confío markup (server-config). The split is an open
  // pricing decision; do not anchor on 0.3%.
  const costPct = 0.3;
  const costUsd = amountUsd * (costPct / 100);
  const netUsd = amountUsd - costUsd;
  return {
    costPct,
    costUsd,
    tokensOut: priceUsd > 0 ? netUsd / priceUsd : 0,
    paused: false,
  };
};

type Phase = 'input' | 'processing' | 'success';

export const BuyStockScreen = () => {
  const navigation = useNavigation<NavProp>();
  const route = useRoute<BuyRoute>();
  const { formatNumber } = useNumberFormat();
  const { byTicker, tradabilityFor } = useGmMarket();
  const { savings } = useAhorrosPortfolio();

  const stock = byTicker(route.params.ticker);
  const available = savings.balanceUsd;

  const [raw, setRaw] = useState('');
  const [phase, setPhase] = useState<Phase>('input');

  const amount = useMemo(() => {
    const v = parseFloat(raw.replace(',', '.'));
    return Number.isFinite(v) ? v : 0;
  }, [raw]);

  const quote = useMemo(
    () => getStockQuote(amount, stock?.priceUsd ?? 0),
    [amount, stock],
  );

  const fmtUsd = (v: number, digits = 2) =>
    `$${formatNumber(v, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

  if (!stock) {
    return (
      <View style={[styles.container, { justifyContent: 'center', alignItems: 'center' }]}>
        <Text style={{ color: colors.text.secondary }}>Acción no encontrada</Text>
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

  const onConfirm = () => {
    // TODO(gm): binding attestation + on-chain settle. Happy-path stub.
    setPhase('processing');
    setTimeout(() => setPhase('success'), 1600);
  };

  if (phase === 'success') {
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
        <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }} />
        <View style={styles.successWrap}>
          <TickerLogo ticker={stock.ticker} color={stock.color} logoUrl={stock.logoUrl} size={72} />
          <Text style={styles.successTitle}>Ya tienes {stock.ticker}</Text>
          <Text style={styles.successAmount}>
            ≈ {formatNumber(quote.tokensOut, { maximumFractionDigits: 4 })} {stock.ticker}
          </Text>
          <Text style={styles.successHint}>
            Los dividendos se reinvierten automáticamente en el valor de tu posición. Puedes
            vender cuando quieras.
          </Text>
          <TouchableOpacity
            style={styles.successCta}
            onPress={() => navigation.goBack()}
            activeOpacity={0.85}
          >
            <Text style={styles.successCtaText}>Ver mi posición</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <Header
        navigation={navigation as any}
        title={`Comprar ${stock.ticker}`}
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
            <Text style={styles.amountLabel}>¿Cuánto quieres invertir?</Text>
            <View style={styles.amountRow}>
              <Text style={styles.amountCurrency}>$</Text>
              <TextInput
                style={styles.amountInput}
                value={raw}
                onChangeText={setRaw}
                keyboardType="decimal-pad"
                placeholder="0.00"
                placeholderTextColor={colors.text.light}
                editable={phase === 'input'}
                autoFocus
              />
            </View>
            <View style={styles.balanceRow}>
              <Text style={[styles.balanceText, overBalance && styles.balanceTextError]}>
                Disponible en tu ahorro: {fmtUsd(available)}
              </Text>
              <TouchableOpacity
                onPress={() => setRaw(available > 0 ? String(available) : '')}
                disabled={phase !== 'input' || available <= 0}
              >
                <Text style={styles.maxBtn}>MAX</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* Funding instrument, payment-method style: the sweep model must
              be visible at a glance — you pay with your savings (cUSD+).
              Amounts stay in $ (decision A: never show share counts). */}
          <View style={styles.fundingSource}>
            <Image source={cUSDPlusLogo} style={styles.fundingLogo} />
            <View style={{ flex: 1 }}>
              <Text style={styles.fundingTitle}>Pagas con tu ahorro</Text>
              <Text style={styles.fundingSub}>
                Confío Dollar+ · {fmtUsd(available)} disponibles
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
                <Text style={styles.quoteLabelStrong}>Recibirás</Text>
                <Text style={styles.quoteValueStrong}>
                  ≈ {formatNumber(quote.tokensOut, { maximumFractionDigits: 4 })} {stock.ticker}
                </Text>
              </View>
            </View>
          )}

          {belowMin && (
            <Text style={styles.hintError}>El monto mínimo es {fmtUsd(MIN_AMOUNT_USD)}.</Text>
          )}
          {overBalance && (
            <View style={styles.fundRow}>
              <Text style={styles.hintError}>
                Tu ahorro disponible es {fmtUsd(available)}.
              </Text>
              <TouchableOpacity onPress={() => navigation.navigate('ConvertAhorro')}>
                <Text style={styles.fundLink}>Ahorrar primero →</Text>
              </TouchableOpacity>
            </View>
          )}

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
                <Text style={styles.confirmBtnText}>Comprando…</Text>
              </>
            ) : (
              <Text style={styles.confirmBtnText}>
                {amount > 0 && canConfirm ? `Comprar ${fmtUsd(amount)}` : 'Comprar'}
              </Text>
            )}
          </TouchableOpacity>
          <Text style={styles.confirmFootnote}>
            Verás el precio final antes de confirmar. Las acciones pueden subir o bajar de valor.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
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
  fundRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  fundLink: { fontSize: 13, fontWeight: '800', color: colors.primaryDark, marginBottom: 14 },

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

  successWrap: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  successTitle: { fontSize: 20, fontWeight: '700', color: colors.text.primary, marginTop: 20 },
  successAmount: { fontSize: 34, fontWeight: 'bold', color: colors.primaryDark, marginTop: 10 },
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
