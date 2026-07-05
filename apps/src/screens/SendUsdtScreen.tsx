// Enviar USDT (BEP-20) — the savings exit for crypto-native users, in the
// SendWithAddress house grammar (compact instrument header, balance card,
// auto-convert banner, amount + currency badge, quick amounts, paste/scan
// address row with live validation, fee row, footer button).
//
// Auto-converts from cUSD+ in ONE transaction: the vault's
// redeemToUsdt(shares, minOut, to) pays USDT to ANY address directly — no
// intermediate balance, no bridge. Confío fee: NONE (Julian, 2026-07-05).
// Amounts display in USD only (decision A: share math stays invisible).
// Execution wires at vault deploy — handleSend is a stub until then.

import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  ScrollView,
  Image,
} from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
import { InlineBanner } from '../components/common/InlineBanner';
import { AddressScannerModal } from '../components/AddressScannerModal';
import { useAhorrosPortfolio } from '../hooks/useAhorrosPortfolio';
import USDTLogo from '../assets/png/USDT.png';

const USDT_COLOR = '#26A17B'; // Tether brand teal (nominative use)
const MIN_SEND_USD = 1;
const QUICK_AMOUNTS = ['10.00', '50.00', '100.00'];

export const SendUsdtScreen = () => {
  const navigation = useNavigation();
  const { savings } = useAhorrosPortfolio();

  const [amount, setAmount] = useState('');
  const [destination, setDestination] = useState('');
  const [showScanner, setShowScanner] = useState(false);
  const [showError, setShowError] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const amountNum = useMemo(() => {
    const v = parseFloat((amount || '0').replace(',', '.'));
    return Number.isFinite(v) ? v : 0;
  }, [amount]);

  const available = savings.balanceUsd;
  const isValidAddress = /^0x[0-9a-fA-F]{40}$/.test(destination.trim());

  const formatFixedFloor = (value: number, decimals = 2) => {
    const m = Math.pow(10, decimals);
    const floored = Math.floor(value * m) / m;
    return floored.toLocaleString('es-ES', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  };

  const handlePaste = async () => {
    try {
      const text = await Clipboard.getString();
      if (text) setDestination(text.trim());
    } catch {}
  };

  const handleMax = () => {
    const floored = Math.floor(available * 100) / 100;
    if (floored > 0) setAmount(String(floored));
  };

  const handleSend = () => {
    if (!amountNum || amountNum < MIN_SEND_USD) {
      setErrorMessage(`El mínimo para enviar es $${MIN_SEND_USD}.`);
      setShowError(true);
      return;
    }
    if (!isValidAddress) {
      setErrorMessage(
        destination.startsWith('0x')
          ? 'La dirección BEP-20 debe tener 40 caracteres hexadecimales después de 0x.'
          : 'Formato inválido. Usa una dirección BNB Smart Chain (empieza con 0x).',
      );
      setShowError(true);
      return;
    }
    if (amountNum > available) {
      setErrorMessage('Saldo insuficiente en tu ahorro.');
      setShowError(true);
      return;
    }
    // TODO(cusd+ vault deploy): shares = usd / pPlus (eth_call) →
    // vault.redeemToUsdt(shares, minUsdtOut, destination) signed by
    // evmWallet, gas-dusted → Movimientos entry. One transaction, no fee.
  };

  return (
    <View style={styles.container}>
      {/* Compact instrument header — house send-screen grammar */}
      <SafeAreaView edges={['top']} style={{ backgroundColor: USDT_COLOR }}>
        <View style={[styles.header, { backgroundColor: USDT_COLOR }]}>
          <TouchableOpacity
            onPress={() => navigation.goBack()}
            style={styles.backButton}
            accessibilityRole="button"
            accessibilityLabel="Volver"
          >
            <Icon name="arrow-left" size={24} color={colors.white} />
          </TouchableOpacity>
          <View style={styles.headerCenter}>
            <Image source={USDTLogo} style={styles.headerLogo} />
            <Text style={styles.headerTitle}>Enviar USDT</Text>
          </View>
          <View style={styles.placeholder} />
        </View>
      </SafeAreaView>

      <ScrollView style={styles.content} contentContainerStyle={styles.contentContainer}>
        {/* Available Balance */}
        <View style={styles.balanceCard}>
          <Text style={styles.balanceLabel}>Saldo disponible</Text>
          <Text style={styles.balanceAmount}>
            ${formatFixedFloor(available, 2)} en tu ahorro
          </Text>
          <Text style={styles.balanceMin}>Mínimo para enviar: ${MIN_SEND_USD}.00</Text>
        </View>

        {/* Auto-convert banner — the USDC screen's grammar, savings edition */}
        <InlineBanner
          variant="info"
          message="Tu saldo se muestra en tu ahorro (Confío Dollar+). Al enviar, se convierte automáticamente a USDT y se envía por la red BNB Smart Chain (BEP-20)."
          style={{ marginHorizontal: 16, marginTop: 16 }}
        />

        {showError && (
          <InlineBanner
            message={errorMessage}
            variant="error"
            onDismiss={() => setShowError(false)}
            style={{ marginHorizontal: 16, marginTop: 16 }}
          />
        )}

        {/* Send Form */}
        <View style={styles.formCard}>
          {/* Amount */}
          <View style={styles.inputContainer}>
            <Text style={styles.inputLabel}>Cantidad a enviar</Text>
            <View style={styles.amountContainer}>
              <TextInput
                style={[styles.amountField, { flex: 1 }]}
                value={amount}
                onChangeText={setAmount}
                placeholder="0.00"
                keyboardType="numeric"
              />
              <View style={styles.currencyBadge}>
                <Image source={USDTLogo} style={styles.currencyBadgeLogo} />
                <Text style={styles.currencyBadgeText}>USDT</Text>
              </View>
            </View>
          </View>

          {/* Quick amounts */}
          <View style={styles.quickAmounts}>
            {QUICK_AMOUNTS.map((val) => (
              <TouchableOpacity
                key={val}
                style={styles.quickAmountButton}
                onPress={() => setAmount(val)}
                accessibilityRole="button"
                accessibilityLabel={`Enviar ${val}`}
              >
                <Text style={styles.quickAmountText}>{val}</Text>
              </TouchableOpacity>
            ))}
            <TouchableOpacity
              style={styles.quickAmountButton}
              onPress={handleMax}
              accessibilityRole="button"
              accessibilityLabel="Enviar el máximo disponible"
            >
              <Text style={[styles.quickAmountText, styles.maxText]}>MAX</Text>
            </TouchableOpacity>
          </View>

          {/* Address */}
          <View style={styles.inputContainer}>
            <Text style={styles.inputLabel}>Dirección BNB Smart Chain (BEP-20)</Text>
            <View style={styles.addressRow}>
              <TextInput
                style={styles.addressField}
                value={destination}
                onChangeText={setDestination}
                placeholder="0x…"
                placeholderTextColor={colors.text.light}
                autoCapitalize="none"
                autoCorrect={false}
              />
              <TouchableOpacity
                style={styles.pasteButton}
                onPress={handlePaste}
                accessibilityRole="button"
                accessibilityLabel="Pegar dirección del portapapeles"
              >
                <Icon name="clipboard" size={15} color={colors.primaryDark} />
                <Text style={styles.pasteButtonText}>Pegar</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.scanButton}
                onPress={() => setShowScanner(true)}
                accessibilityRole="button"
                accessibilityLabel="Escanear código QR de la dirección"
              >
                <Icon name="camera" size={18} color={colors.primaryDark} />
              </TouchableOpacity>
            </View>
            {destination.length === 0 ? (
              <Text style={styles.addressHelp}>
                Pega o escanea la dirección BEP-20 del destinatario (0x + 40 caracteres). Si
                envías a un exchange, usa su dirección de depósito BEP-20.
              </Text>
            ) : isValidAddress ? (
              <View style={styles.addressValidRow}>
                <Icon name="check-circle" size={13} color={colors.success} />
                <Text style={styles.addressValidText}>Dirección válida</Text>
              </View>
            ) : (
              <Text style={styles.addressHelp}>
                {destination.length}/42 caracteres · empieza con 0x
              </Text>
            )}
          </View>

          {/* Fee */}
          <View style={styles.feeInfo}>
            <Text style={styles.feeLabel}>Comisión de Confío</Text>
            <View style={styles.feeAmountContainer}>
              <Text style={styles.feeAmount}>Gratis</Text>
              <Text style={styles.sponsoredBadge}>Red cubierta por Confío</Text>
            </View>
          </View>
        </View>
      </ScrollView>

      {/* Send Button */}
      <View style={[styles.footer, { paddingBottom: 20 }]}>
        <Button
          title={amountNum > available ? 'Saldo insuficiente' : 'Enviar'}
          onPress={handleSend}
          disabled={!amount || !destination || amountNum > available}
          accessibilityLabel="Enviar"
          icon={<Icon name="send" size={20} color="#ffffff" />}
          style={{ backgroundColor: USDT_COLOR }}
        />
      </View>

      <AddressScannerModal
        visible={showScanner}
        onClose={() => setShowScanner(false)}
        onScanned={(addr) => {
          setDestination(addr.trim());
          setShowScanner(false);
        }}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 14,
  },
  backButton: { padding: 6, width: 40, alignItems: 'center' },
  headerCenter: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  headerLogo: { width: 24, height: 24, borderRadius: 12 },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: colors.white },
  placeholder: { width: 40 },

  content: { flex: 1 },
  contentContainer: { paddingBottom: 24 },

  balanceCard: {
    backgroundColor: '#fff',
    borderRadius: 14,
    padding: 16,
    marginHorizontal: 16,
    marginTop: 16,
    alignItems: 'center',
  },
  balanceLabel: { fontSize: 13, color: colors.text.secondary },
  balanceAmount: { fontSize: 24, fontWeight: '700', color: colors.text.primary, marginTop: 4 },
  balanceMin: { fontSize: 12, color: colors.text.light, marginTop: 4 },

  formCard: {
    backgroundColor: '#fff',
    borderRadius: 14,
    padding: 16,
    marginHorizontal: 16,
    marginTop: 16,
  },
  inputContainer: { marginBottom: 14 },
  inputLabel: { fontSize: 13, fontWeight: '600', color: colors.text.secondary, marginBottom: 8 },
  amountContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.neutral,
    borderRadius: 12,
    paddingHorizontal: 12,
  },
  amountField: { fontSize: 22, fontWeight: '700', color: colors.text.primary, paddingVertical: 12 },
  currencyBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#fff',
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  currencyBadgeLogo: { width: 18, height: 18, borderRadius: 9 },
  currencyBadgeText: { fontSize: 13, fontWeight: '700', color: colors.text.primary },

  quickAmounts: { flexDirection: 'row', gap: 8, marginBottom: 14 },
  quickAmountButton: {
    flex: 1,
    backgroundColor: colors.neutral,
    borderRadius: 10,
    paddingVertical: 9,
    alignItems: 'center',
  },
  quickAmountText: { fontSize: 13, fontWeight: '600', color: colors.text.primary },
  maxText: { color: colors.primaryDark, fontWeight: '800' },

  addressRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  addressField: {
    flex: 1,
    backgroundColor: colors.neutral,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 12,
    fontSize: 13,
    color: colors.text.primary,
    fontFamily: 'monospace' as any,
  },
  pasteButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    borderWidth: 1.5,
    borderColor: colors.primaryDark,
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 10,
  },
  pasteButtonText: { fontSize: 13, fontWeight: '700', color: colors.primaryDark },
  scanButton: {
    borderWidth: 1.5,
    borderColor: colors.primaryDark,
    borderRadius: 10,
    padding: 10,
  },
  addressHelp: { fontSize: 12, color: colors.text.light, marginTop: 8, lineHeight: 17 },
  addressValidRow: { flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 8 },
  addressValidText: { fontSize: 12, fontWeight: '600', color: colors.success },

  feeInfo: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: colors.neutral,
    paddingTop: 12,
  },
  feeLabel: { fontSize: 13, color: colors.text.secondary },
  feeAmountContainer: { alignItems: 'flex-end' },
  feeAmount: { fontSize: 14, fontWeight: '700', color: colors.success },
  sponsoredBadge: { fontSize: 11, color: colors.text.light, marginTop: 1 },

  footer: { paddingHorizontal: 16, paddingTop: 8, backgroundColor: colors.neutral },
});
