// Ahorrar en Confío Dollar+ — convert flow from the user's cUSD balance.
//
// Flow: amount → live quote preview (pass-through cost, never hidden) →
// confirm → processing → success. Three guard states are designed in, not
// bolted on:
// - insufficient balance / below minimum
// - market-conditions pause (bridge quote above the remote-config threshold;
//   partial-fill handled upstream — see the fill-guard spec)
// - quote refresh while typing
//
// Wiring points (all stubbed until the BSC backend lands):
// - getQuote(): becomes the Django quote endpoint (Allbridge leg + IM mint),
//   remote-config threshold, partial-fill max.
// - onConfirm(): becomes biometric sign + atomic tx submit + state machine
//   (IDLE → QUOTED → SUBMITTED → BRIDGING → DONE, resumable on failure).

import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  StatusBar,
  TextInput,
  Image,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { useNumberFormat } from '../utils/numberFormatting';
import { GET_MY_BALANCES } from '../apollo/queries';
import { useAhorrosPortfolio } from '../hooks/useAhorrosPortfolio';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';

type NavProp = NativeStackNavigationProp<MainStackParamList>;

const MIN_AMOUNT_USD = 1;

// TODO(cusd+): replace with the backend quote endpoint. Returns the effective
// conversion cost for this amount (bridge leg + acquisition), plus whether the
// market-conditions guard is tripped (spread above remote-config threshold).
const getQuote = (amountUsd: number) => ({
  costPct: 0.7,
  costUsd: amountUsd * 0.007,
  receiveUsd: amountUsd * 0.993,
  paused: false,
});

type Phase = 'input' | 'processing' | 'success';

export const ConvertAhorroScreen = () => {
  const navigation = useNavigation<NavProp>();
  const { formatNumber } = useNumberFormat();
  const { savings } = useAhorrosPortfolio();

  const { data: balancesData } = useQuery(GET_MY_BALANCES, {
    fetchPolicy: 'cache-and-network',
  });
  const available = parseFloat(balancesData?.myBalances?.cusd || '0') || 0;

  const [raw, setRaw] = useState('');
  const [phase, setPhase] = useState<Phase>('input');

  const amount = useMemo(() => {
    const v = parseFloat(raw.replace(',', '.'));
    return Number.isFinite(v) ? v : 0;
  }, [raw]);

  const quote = useMemo(() => getQuote(amount), [amount]);

  const fmtUsd = (v: number, digits = 2) =>
    `$${formatNumber(v, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

  const overBalance = amount > available;
  const belowMin = amount > 0 && amount < MIN_AMOUNT_USD;
  const canConfirm = amount >= MIN_AMOUNT_USD && !overBalance && !quote.paused;

  // First-year feel: what does this amount earn per day at the current rate?
  const dailyEstimate = (quote.receiveUsd * savings.netApyPct) / 100 / 365;

  const onConfirm = () => {
    // TODO(cusd+): biometric confirm → build atomic tx → submit → track the
    // BRIDGING state machine. This stub simulates the happy path only.
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
          <Text style={styles.successTitle}>Tu ahorro empezó a crecer</Text>
          <Text style={styles.successAmount}>{fmtUsd(quote.receiveUsd)}</Text>
          <Text style={styles.successHint}>
            Mañana habrás ganado ≈ {fmtUsd(dailyEstimate, dailyEstimate < 0.01 ? 4 : 2)} — y así
            todos los días, sin hacer nada.
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
          <Text style={styles.headerTitle}>Ahorrar en Confío Dollar+</Text>
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
          {/* Amount */}
          <View style={styles.amountCard}>
            <Text style={styles.amountLabel}>¿Cuánto quieres ahorrar?</Text>
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
                Disponible: {fmtUsd(available)} cUSD
              </Text>
              <TouchableOpacity
                onPress={() => setRaw(available > 0 ? String(available) : '')}
                disabled={phase !== 'input' || available <= 0}
              >
                <Text style={styles.maxBtn}>MAX</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* Quote preview — the honest receipt, live while typing */}
          {amount > 0 && !belowMin && !overBalance && (
            quote.paused ? (
              // Not an error: a designed state. The guard skipped this window;
              // it retries automatically (foreground checks).
              <View style={styles.pausedCard}>
                <Icon name="pause-circle" size={18} color="#B45309" />
                <View style={{ flex: 1 }}>
                  <Text style={styles.pausedTitle}>Pausado por condiciones de mercado</Text>
                  <Text style={styles.pausedBody}>
                    El costo de conversión está alto en este momento. Lo reintentaremos
                    automáticamente — no tienes que hacer nada.
                  </Text>
                </View>
              </View>
            ) : (
              <View style={styles.quoteCard}>
                <View style={styles.quoteRow}>
                  <Text style={styles.quoteLabel}>Costo de conversión</Text>
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
                {dailyEstimate > 0 && (
                  <View style={styles.quoteEstimateRow}>
                    <Icon name="trending-up" size={13} color={colors.primaryDark} />
                    <Text style={styles.quoteEstimateText}>
                      Ganarás ≈ {fmtUsd(dailyEstimate, dailyEstimate < 0.01 ? 4 : 2)} al día a la
                      tasa actual (~
                      {formatNumber(savings.netApyPct, { maximumFractionDigits: 1 })}% anual)
                    </Text>
                  </View>
                )}
              </View>
            )
          )}

          {belowMin && (
            <Text style={styles.hintError}>El monto mínimo es {fmtUsd(MIN_AMOUNT_USD)}.</Text>
          )}
          {overBalance && (
            <Text style={styles.hintError}>
              No tienes suficiente cUSD — tu disponible es {fmtUsd(available)}.
            </Text>
          )}

          <View style={{ flex: 1 }} />

          {/* Confirm */}
          <TouchableOpacity
            style={[styles.confirmBtn, (!canConfirm || phase === 'processing') && styles.confirmBtnDisabled]}
            onPress={onConfirm}
            disabled={!canConfirm || phase === 'processing'}
            activeOpacity={0.85}
          >
            {phase === 'processing' ? (
              <>
                <ActivityIndicator color="#fff" size="small" />
                <Text style={styles.confirmBtnText}>Convirtiendo…</Text>
              </>
            ) : (
              <>
                <Image source={cUSDPlusLogo} style={styles.confirmLogo} />
                <Text style={styles.confirmBtnText}>
                  {amount > 0 && canConfirm ? `Ahorrar ${fmtUsd(amount)}` : 'Ahorrar'}
                </Text>
              </>
            )}
          </TouchableOpacity>
          <Text style={styles.confirmFootnote}>
            Verás el resultado al instante. Tu cUSD+ está respaldado por bonos del Tesoro de
            EE.UU. y puedes retirarlo cuando quieras.
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

  quoteCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 16,
    marginBottom: 14,
  },
  quoteRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  quoteLabel: { fontSize: 13, color: colors.text.secondary },
  quoteValue: { fontSize: 13, fontWeight: '600', color: colors.text.primary },
  quoteDivider: { height: 1, backgroundColor: colors.surfaceMuted, marginVertical: 12 },
  quoteLabelStrong: { fontSize: 14, fontWeight: '700', color: colors.text.primary },
  quoteValueStrong: { fontSize: 16, fontWeight: '800', color: colors.primaryDark },
  quoteEstimateRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 12,
    backgroundColor: colors.primaryLight,
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  quoteEstimateText: { flex: 1, fontSize: 12, color: colors.primaryDark, fontWeight: '600' },

  pausedCard: {
    flexDirection: 'row',
    gap: 10,
    backgroundColor: '#FEF3C7',
    borderRadius: 14,
    padding: 14,
    marginBottom: 14,
  },
  pausedTitle: { fontSize: 14, fontWeight: '700', color: '#92400E' },
  pausedBody: { fontSize: 12, color: '#92400E', marginTop: 3, lineHeight: 17 },

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
  confirmLogo: { width: 22, height: 22, borderRadius: 11 },
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
