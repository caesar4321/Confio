// Retirar de Confío Dollar+ — reverse convert flow (cUSD+ → cUSD).
//
// Mirror of ConvertAhorroScreen: amount → live quote (pass-through cost) →
// confirm → processing → success. The destination here is always the user's
// cUSD balance; the "a mi banco" path (direct off-ramp from the savings
// chain) is a separate flow gated on the ramp destination work.
//
// Wiring points (stubbed until the BSC backend lands):
// - getQuote(): Django quote endpoint for the reverse leg (IM redeem +
//   bridge back), remote-config threshold, partial-fill max.
// - onConfirm(): biometric sign + atomic tx + resumable state machine.

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
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { SuccessHero } from '../components/common/SuccessHero';
import { useNumberFormat } from '../utils/numberFormatting';
import { useAhorrosPortfolio } from '../hooks/useAhorrosPortfolio';

type NavProp = NativeStackNavigationProp<MainStackParamList>;

const MIN_AMOUNT_USD = 1;

// TODO(cusd+): backend quote endpoint for the reverse conversion leg.
const getQuote = (amountUsd: number) => ({
  costPct: 0.7,
  costUsd: amountUsd * 0.007,
  receiveUsd: amountUsd * 0.993,
  paused: false,
});

type Phase = 'input' | 'processing' | 'success';

export const RetirarAhorroScreen = () => {
  const navigation = useNavigation<NavProp>();
  const { formatNumber } = useNumberFormat();
  const { savings } = useAhorrosPortfolio();
  const available = savings.balanceUsd;

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

  const onConfirm = () => {
    // TODO(cusd+): biometric confirm → atomic reverse tx → state machine.
    setPhase('processing');
    setTimeout(() => setPhase('success'), 1600);
  };

  if (phase === 'success') {
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
        <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }} />
        <View style={styles.successWrap}>
          <SuccessHero
            title="Listo — está en tu cUSD"
            amount={fmtUsd(quote.receiveUsd)}
            hint="Disponible al instante para enviar, pagar o retirar a tu banco. El resto de tu ahorro sigue creciendo."
          />
          <TouchableOpacity
            style={styles.successCta}
            onPress={() => navigation.goBack()}
            activeOpacity={0.85}
          >
            <Text style={styles.successCtaText}>Volver a mi ahorro</Text>
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
          <Text style={styles.headerTitle}>Retirar de mi ahorro</Text>
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
            <Text style={styles.amountLabel}>¿Cuánto quieres retirar a cUSD?</Text>
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
                En tu ahorro: {fmtUsd(available)}
              </Text>
              <TouchableOpacity
                onPress={() => setRaw(available > 0 ? String(available) : '')}
                disabled={phase !== 'input' || available <= 0}
              >
                <Text style={styles.maxBtn}>MAX</Text>
              </TouchableOpacity>
            </View>
          </View>

          {amount > 0 && !belowMin && !overBalance && (
            quote.paused ? (
              <View style={styles.pausedCard}>
                <Icon name="pause-circle" size={18} color="#B45309" />
                <View style={{ flex: 1 }}>
                  <Text style={styles.pausedTitle}>Pausado por condiciones de mercado</Text>
                  <Text style={styles.pausedBody}>
                    El costo de conversión está alto en este momento. Lo reintentaremos
                    automáticamente — tu ahorro sigue creciendo mientras tanto.
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
                  <Text style={styles.quoteLabelStrong}>Recibirás en cUSD</Text>
                  <Text style={styles.quoteValueStrong}>≈ {fmtUsd(quote.receiveUsd)}</Text>
                </View>
              </View>
            )
          )}

          {belowMin && (
            <Text style={styles.hintError}>El monto mínimo es {fmtUsd(MIN_AMOUNT_USD)}.</Text>
          )}
          {overBalance && (
            <Text style={styles.hintError}>
              Tu ahorro disponible es {fmtUsd(available)}.
            </Text>
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
                <Text style={styles.confirmBtnText}>Retirando…</Text>
              </>
            ) : (
              <Text style={styles.confirmBtnText}>
                {amount > 0 && canConfirm ? `Retirar ${fmtUsd(amount)}` : 'Retirar'}
              </Text>
            )}
          </TouchableOpacity>
          <Text style={styles.confirmFootnote}>
            Sin plazos ni penalidades. Lo que no retires sigue generando rendimiento.
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
