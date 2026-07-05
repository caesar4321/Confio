// Enviar USDT (BEP-20) — the savings exit for crypto-native users:
// auto-converts from cUSD+ in ONE transaction. The vault's
// redeemToUsdt(shares, minOut, to) pays USDT to ANY address directly —
// no intermediate balance, no bridge, no saga. Confío fee: NONE
// (Julian, 2026-07-05) — same as the Koywe withdrawal rail.
//
// Amounts display in USD only (decision A: share math stays invisible;
// shares = usd / pPlus computed at signing). Execution wires at vault
// deploy — onConfirm is a stub in the ConvertAhorro pattern until then.

import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  ScrollView,
  StatusBar,
  Image,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { colors } from '../config/theme';
import { useNumberFormat } from '../utils/numberFormatting';
import { useAhorrosPortfolio } from '../hooks/useAhorrosPortfolio';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';

const MIN_AMOUNT_USD = 1;

const isPlausibleEvmAddress = (a: string) => /^0x[0-9a-fA-F]{40}$/.test(a.trim());

export const SendUsdtScreen = () => {
  const navigation = useNavigation();
  const { formatNumber } = useNumberFormat();
  const { savings } = useAhorrosPortfolio();

  const [dest, setDest] = useState('');
  const [raw, setRaw] = useState('');
  const amount = useMemo(() => {
    const v = parseFloat(raw.replace(',', '.'));
    return Number.isFinite(v) ? v : 0;
  }, [raw]);

  const fmtUsd = (v: number) =>
    `$${formatNumber(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const destValid = isPlausibleEvmAddress(dest);
  const overBalance = amount > savings.balanceUsd;
  const belowMin = amount > 0 && amount < MIN_AMOUNT_USD;
  const canConfirm = destValid && amount >= MIN_AMOUNT_USD && !overBalance;

  const onConfirm = () => {
    // TODO(cusd+ vault deploy): shares = usd / pPlus (eth_call) →
    // vault.redeemToUsdt(shares, minUsdtOut, dest) signed by evmWallet,
    // gas-dusted; then Movimientos entry. One transaction, no fee.
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerIconBtn}>
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Enviar USDT</Text>
          <View style={styles.headerIconBtn} />
        </View>
      </SafeAreaView>

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
          {/* Destination */}
          <View style={styles.card}>
            <Text style={styles.label}>Dirección de destino (BEP-20)</Text>
            <TextInput
              style={styles.addressInput}
              value={dest}
              onChangeText={setDest}
              placeholder="0x…"
              placeholderTextColor={colors.text.light}
              autoCapitalize="none"
              autoCorrect={false}
            />
            {dest.length > 0 && !destValid && (
              <Text style={styles.hintError}>Dirección inválida — debe empezar con 0x (42 caracteres).</Text>
            )}
          </View>

          {/* Amount */}
          <View style={styles.card}>
            <Text style={styles.label}>¿Cuánto quieres enviar?</Text>
            <View style={styles.amountRow}>
              <Text style={styles.amountCurrency}>$</Text>
              <TextInput
                style={styles.amountInput}
                value={raw}
                onChangeText={setRaw}
                keyboardType="decimal-pad"
                placeholder="0.00"
                placeholderTextColor={colors.text.light}
              />
              <TouchableOpacity
                onPress={() => setRaw(savings.balanceUsd > 0 ? String(savings.balanceUsd) : '')}
              >
                <Text style={styles.maxBtn}>MAX</Text>
              </TouchableOpacity>
            </View>
            <Text style={[styles.balanceLine, overBalance && styles.hintError]}>
              En tu ahorro: {fmtUsd(savings.balanceUsd)}
            </Text>
          </View>

          {/* Source instrument — payment-method grammar */}
          <View style={styles.fundingSource}>
            <Image source={cUSDPlusLogo} style={styles.fundingLogo} />
            <View style={{ flex: 1 }}>
              <Text style={styles.fundingTitle}>Sale de tu ahorro</Text>
              <Text style={styles.fundingSub}>
                Confío Dollar+ · se convierte a USDT al enviar · sin comisión de Confío
              </Text>
            </View>
          </View>

          {/* Receipt */}
          {amount > 0 && !belowMin && !overBalance && (
            <View style={styles.card}>
              <View style={styles.quoteRow}>
                <Text style={styles.quoteLabelStrong}>Recibirá</Text>
                <Text style={styles.quoteValueStrong}>≈ {fmtUsd(amount)} en USDT</Text>
              </View>
            </View>
          )}
          {belowMin && <Text style={styles.hintError}>El monto mínimo es {fmtUsd(MIN_AMOUNT_USD)}.</Text>}

          {/* THE warning — mirror of the receive screen */}
          <View style={styles.warnCard}>
            <Icon name="alert-triangle" size={18} color="#B45309" />
            <Text style={styles.warnText}>
              El destinatario debe aceptar <Text style={styles.warnStrong}>USDT por la red
              BNB Smart Chain (BEP-20)</Text>. Si envías a un exchange, usa su dirección de
              depósito BEP-20. Una dirección o red equivocada significa pérdida permanente.
            </Text>
          </View>

          <View style={{ flex: 1 }} />

          <TouchableOpacity
            style={[styles.confirmBtn, !canConfirm && styles.confirmBtnDisabled]}
            onPress={onConfirm}
            disabled={!canConfirm}
            activeOpacity={0.85}
          >
            <Text style={styles.confirmBtnText}>
              {amount > 0 && canConfirm ? `Enviar ${fmtUsd(amount)}` : 'Enviar'}
            </Text>
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.primary,
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 16,
  },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: '#fff' },
  scrollContent: { padding: 16, paddingBottom: 32, flexGrow: 1 },

  card: { backgroundColor: '#fff', borderRadius: 14, padding: 16, marginBottom: 12 },
  label: { fontSize: 13, fontWeight: '600', color: colors.text.secondary, marginBottom: 8 },
  addressInput: {
    fontSize: 14,
    color: colors.text.primary,
    fontFamily: 'monospace' as any,
    padding: 0,
  },
  amountRow: { flexDirection: 'row', alignItems: 'center' },
  amountCurrency: { fontSize: 28, fontWeight: '700', color: colors.text.primary, marginRight: 6 },
  amountInput: { flex: 1, fontSize: 28, fontWeight: '700', color: colors.text.primary, padding: 0 },
  maxBtn: { fontSize: 13, fontWeight: '800', color: colors.primaryDark },
  balanceLine: { fontSize: 12, color: colors.text.secondary, marginTop: 8 },

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

  quoteRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  quoteLabelStrong: { fontSize: 14, fontWeight: '700', color: colors.text.primary },
  quoteValueStrong: { fontSize: 14, fontWeight: '700', color: colors.primaryDark },

  warnCard: {
    flexDirection: 'row',
    gap: 10,
    backgroundColor: '#FEF3C7',
    borderRadius: 12,
    padding: 14,
    marginBottom: 16,
  },
  warnText: { flex: 1, fontSize: 13, color: '#92400E', lineHeight: 18 },
  warnStrong: { fontWeight: '800' },

  hintError: { fontSize: 12, color: '#DC2626', marginTop: 6 },

  confirmBtn: {
    backgroundColor: colors.primary,
    borderRadius: 14,
    paddingVertical: 15,
    alignItems: 'center',
  },
  confirmBtnDisabled: { opacity: 0.4 },
  confirmBtnText: { color: '#fff', fontSize: 16, fontWeight: '700' },
});
