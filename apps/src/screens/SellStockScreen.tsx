// Vender acción — sell flow; proceeds land in cUSD+ and keep earning.
//
// Mirror of BuyStockScreen. The exit message matters as much as the entry:
// selling is not "cashing out of Confío" — the money returns to the sweep
// account and resumes earning Treasury yield immediately. Copy says so.
//
// Wiring points (stubbed until the GM backend proxy lands):
// - getSellQuote(): RFQ/attestation soft quote for the sell side.
// - onConfirm(): binding attestation → on-chain settle into the cUSD+ vault.

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
type SellRoute = RouteProp<MainStackParamList, 'SellStock'>;

const MIN_AMOUNT_USD = 1;

// TODO(gm): RFQ/attestation soft quote (sell side) via backend proxy.
const getSellQuote = (amountUsd: number) => {
  // STUB, NOT PRICING — real cost = Ondo GM fee (schedule unknown until
  // onboarding) + Confío markup (server-config). The split is an open
  // pricing decision; do not anchor on 0.3%.
  const costPct = 0.3;
  const costUsd = amountUsd * (costPct / 100);
  return {
    costPct,
    costUsd,
    receiveUsd: amountUsd - costUsd,
    paused: false,
  };
};

type Phase = 'input' | 'processing' | 'success';

export const SellStockScreen = () => {
  const navigation = useNavigation<NavProp>();
  const route = useRoute<SellRoute>();
  const { formatNumber } = useNumberFormat();
  const { byTicker, tradabilityFor } = useGmMarket();
  const { stocks } = useAhorrosPortfolio();

  const stock = byTicker(route.params.ticker);
  const position = stocks.positions.find((p) => p.ticker === route.params.ticker);
  const available = position?.valueUsd ?? 0;

  const [raw, setRaw] = useState('');
  const [phase, setPhase] = useState<Phase>('input');

  const amount = useMemo(() => {
    const v = parseFloat(raw.replace(',', '.'));
    return Number.isFinite(v) ? v : 0;
  }, [raw]);

  const quote = useMemo(() => getSellQuote(amount), [amount]);

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
          <View style={styles.successIcon}>
            <Icon name="check" size={40} color="#fff" />
          </View>
          <Text style={styles.successTitle}>Vendido</Text>
          <Text style={styles.successAmount}>{fmtUsd(quote.receiveUsd)}</Text>
          <Text style={styles.successHint}>
            Ya está en tu ahorro (cUSD+) y sigue generando rendimiento desde ahora mismo.
          </Text>
          <TouchableOpacity
            style={styles.successCta}
            onPress={() => navigation.goBack()}
            activeOpacity={0.85}
          >
            <Text style={styles.successCtaText}>Ver mi ahorro</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        <View style={styles.header}>
          <TouchableOpacity
            onPress={() => navigation.goBack()}
            style={styles.headerIconBtn}
            disabled={phase === 'processing'}
          >
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <TickerLogo ticker={stock.ticker} color={stock.color} logoUrl={stock.logoUrl} size={26} />
            <Text style={styles.headerTitle}>Vender {stock.ticker}</Text>
          </View>
          <View style={styles.headerIconBtn} />
        </View>
      </SafeAreaView>

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
                Tu posición: {fmtUsd(available)}
              </Text>
              <TouchableOpacity
                onPress={() => setRaw(available > 0 ? String(available) : '')}
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
            Lo que recibas vuelve a tu ahorro y sigue generando rendimiento.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },

  header: {
    backgroundColor: colors.primary,
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: '#fff' },

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

  successWrap: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
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
