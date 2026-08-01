// Enviar por BNB Smart Chain — THE address-send screen for every BSC token
// (route param `token`), in the SendWithAddress house grammar (compact
// instrument header, balance card, amount + currency badge, quick amounts,
// paste/scan address row with live validation, fee row, footer button).
// The route keeps its historical name (SendUsdt) from the Phase-1.5
// USDT-only exit.
//
//   usdt (default)  dollar-value send, the Algorand USDC-send pattern
//                   (USDC shows/spends the cUSD balance, converting at
//                   send): the balance ALWAYS reflects the cUSD+ position
//                   — send/bsc_flow.py redeems shares to USDT atomically
//                   when wallet USDT doesn't cover. Rail off → Phase-1.5
//                   raw-wallet-USDT transfer (sponsored-first, self-signed
//                   fallback — the exit that must never break); savings-
//                   funded amounts refuse honestly until the rail is on.
//   cusd_plus       the Confío Dollar TOKEN itself (shape D): recipient
//                   gets cUSD+ at any address, no redemption. Rail-gated.
//   confio          BEP-20 CONFIO (shape E); amount is a token count, not
//                   USD. Rail-gated.
//
// Server-authoritative on the rail: the client only signs the batch the
// server stored. Confío fee: NONE (Julian, 2026-07-05).

import React, { useEffect, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  ScrollView,
  Image,
  Alert,
} from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
import { InlineBanner } from '../components/common/InlineBanner';
import { AddressScannerModal } from '../components/AddressScannerModal';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import USDTLogo from '../assets/png/USDT.png';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import { isAddressForNetwork, wrongNetworkMessage } from '../utils/addressNetwork';

type BscToken = 'usdt' | 'cusd_plus' | 'confio';

const MIN_SEND = 1; // $1 for the dollar tokens, 1 CONFIO for CONFIO
const QUICK_AMOUNTS = ['10.00', '50.00', '100.00'];

const TOKEN_CONFIG: Record<BscToken, {
  name: string;
  logo: any;
  color: string;
  isUsd: boolean; // amounts and balances render as dollars
  railOnly: boolean; // needs the server send rail (no legacy fallback)
  networkBanner: string;
}> = {
  usdt: {
    name: 'USDT',
    logo: USDTLogo,
    color: '#26A17B', // Tether brand teal (nominative use)
    isUsd: true,
    railOnly: false,
    networkBanner:
      'Se envía como USDT por la red BNB Smart Chain (BEP-20). ' +
      'Asegúrate de que el destinatario acepte esa red.',
  },
  cusd_plus: {
    name: 'cUSD+',
    logo: cUSDPlusLogo,
    color: colors.primary,
    isUsd: true,
    railOnly: true,
    networkBanner:
      'Se envía como cUSD+ (BEP-20) por la red BNB Smart Chain. El ' +
      'destinatario recibe el token tal cual — si envías a un exchange, ' +
      'usa USDT en su lugar.',
  },
  confio: {
    name: 'CONFIO',
    logo: CONFIOLogo,
    color: colors.secondary,
    isUsd: false,
    railOnly: true,
    networkBanner:
      'Se envía como CONFIO (BEP-20) por la red BNB Smart Chain. ' +
      'Asegúrate de que el destinatario acepte ese token.',
  },
};

export const SendUsdtScreen = () => {
  const navigation = useNavigation();
  const route = useRoute();
  const token: BscToken = (route.params as any)?.token || 'usdt';
  const config = TOKEN_CONFIG[token];
  const { usdtBalanceUsd, savings, loading: portfolioLoading } = useSavingsPortfolio();

  // CONFIO-BSC balance via its OWN query (cusdPlusSummary.confioBalance is
  // newer than the portfolio query — bundling it there would invalidate
  // the whole money query against a server that doesn't serve it yet).
  // Any failure → 0, never a broken portfolio.
  const [confioBalance, setConfioBalance] = useState(0);
  const [confioLoading, setConfioLoading] = useState(token === 'confio');
  useEffect(() => {
    if (token !== 'confio') return;
    let alive = true;
    (async () => {
      try {
        const { gql } = await import('@apollo/client');
        const { apolloClient } = await import('../apollo/client');
        const { data } = await apolloClient.query({
          query: gql`
            query ConfioBscBalance {
              cusdPlusSummary {
                confioBalance
              }
            }
          `,
          fetchPolicy: 'network-only',
        });
        if (alive) setConfioBalance(data?.cusdPlusSummary?.confioBalance ?? 0);
      } catch {
        // Older server: field not deployed yet — show 0, never break.
      } finally {
        if (alive) setConfioLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [token]);

  const [amount, setAmount] = useState('');
  const [destination, setDestination] = useState('');
  const [showScanner, setShowScanner] = useState(false);
  const [showError, setShowError] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [sending, setSending] = useState(false);

  const amountNum = useMemo(() => {
    const v = parseFloat((amount || '0').replace(',', '.'));
    return Number.isFinite(v) ? v : 0;
  }, [amount]);

  // Full-dollar rail flag (send/bsc_flow.py, server-gated). Defaults to the
  // raw-USDT behavior until the server confirms. Sends ride 7702, so the
  // rail counts as ON only when the sponsored params are also live.
  const [dollarRail, setDollarRail] = useState(false);
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { fetchSponsored7702Params, fetchBscSendEnabled } =
          await import('../services/sponsored7702');
        const [params, sendOn] = await Promise.all([
          fetchSponsored7702Params().catch(() => ({ enabled: false, delegateAddress: null })),
          fetchBscSendEnabled(),
        ]);
        if (alive) setDollarRail(Boolean(sendOn && params.enabled));
      } catch {
        // Any failure keeps the safe raw-USDT behavior.
      }
    })();
    return () => { alive = false; };
  }, []);

  // Per-token balance. USDT mirrors the Algorand USDC-send pattern (a USDC
  // send shows and spends the cUSD balance, converting at send time): the
  // cUSD+ position ALWAYS counts toward what's sendable — the server
  // redeems shares to USDT inside the same sponsored tx. max(), not sum:
  // the server funds a send from a single leg, so the honest one-tx
  // capacity is the larger of the two (same as maxSendable in
  // SendWithAddressScreen's usdc mode).
  const available = token === 'confio'
    ? confioBalance
    : token === 'cusd_plus'
      ? savings.balanceUsd
      : Math.max(savings.balanceUsd, usdtBalanceUsd);
  // Every balance here starts at 0 while its query is in flight, so "0" is
  // ambiguous. Without this the button asserts "Saldo insuficiente" against a
  // balance it hasn't read yet, and MAX silently does nothing.
  const balanceReady = token === 'confio' ? !confioLoading : !portfolioLoading;
  const isValidAddress = isAddressForNetwork(destination, 'bsc');
  // Well-formed, but for the OTHER chain — the mistake that burns funds, so
  // it gets named explicitly wherever an address is entered, pasted or
  // scanned, not folded into a generic "formato inválido".
  const wrongChainMessage = wrongNetworkMessage(destination, 'bsc');

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

  const handleSend = async () => {
    if (!amountNum || amountNum < MIN_SEND) {
      setErrorMessage(config.isUsd
        ? `El mínimo para enviar es $${MIN_SEND}.`
        : `El mínimo para enviar es ${MIN_SEND} ${config.name}.`);
      setShowError(true);
      return;
    }
    if (!isValidAddress) {
      setErrorMessage(
        wrongChainMessage
        || (destination.startsWith('0x')
          ? 'La dirección BEP-20 debe tener 40 caracteres hexadecimales después de 0x.'
          : 'Formato inválido. Usa una dirección BNB Smart Chain (empieza con 0x).'),
      );
      setShowError(true);
      return;
    }
    if (amountNum > available) {
      setErrorMessage('Saldo insuficiente.');
      setShowError(true);
      return;
    }
    if (sending) return;
    setSending(true);
    setShowError(false);
    try {
      if (config.railOnly && !dollarRail) {
        // cUSD+/CONFIO ride the server rail only — no legacy fallback.
        setErrorMessage('Los envíos están en preparación. Inténtalo más tarde.');
        setShowError(true);
        return;
      }
      if (dollarRail) {
        // Server rail: hand the validated intent to the shared processing
        // screen — the same biometric gate, step animation and success
        // screen the contact send and the Algorand rail already use. It
        // owns the wait (prepare → sign → submit → receipt, which is
        // seconds, not instant), so this screen must never sit on an
        // awaited send with no spinner. The server resolves the address
        // (it may belong to a Confío user), picks the call shape and
        // stores the exact batch; we only sign it.
        const minuteTimestamp = Math.floor(Date.now() / 60000);
        const idempotencyKey =
          `sendext_${token}_${destination.trim().slice(-8)}_${amount.replace('.', '')}_${minuteTimestamp}`;
        (navigation as any).replace('TransactionProcessing', {
          transactionData: {
            type: 'sent',
            action: 'Enviando',
            amount: String(amountNum),
            currency: config.name,
            recipient: `${destination.trim().slice(0, 10)}…`,
            recipientAddress: destination.trim(),
            memo: '',
            idempotencyKey,
            bscSend: true,
            // Explicit token shapes only. A `usdt` send names NO token so
            // the server keeps its funding-source choice (and delivers
            // cUSD+ if that address turns out to be a Confío user).
            bscTokenType: token === 'cusd_plus' ? 'CUSD_PLUS'
              : token === 'confio' ? 'CONFIO'
                : undefined,
          },
        });
        return;
      }

      // Legacy path (rail dark) moves RAW WALLET USDT only: a savings-
      // funded amount would be silently clamped down by the live-balance
      // re-read below — honest refusal instead.
      if (amountNum > usdtBalanceUsd) {
        setErrorMessage('Los envíos están en preparación. Inténtalo más tarde.');
        setShowError(true);
        return;
      }

      // Sponsored-first (EIP-7702, user needs zero BNB) with self-signed
      // legacy fallback — all inside transferUsdt. Live balance re-read
      // first so MAX sends the exact on-chain amount without reverting.
      const { installBscServerTransport } = await import('../services/bscServerRpc');
      installBscServerTransport();
      const { getActiveEvmWallet } = await import('../services/secureDeterministicWallet');
      const { selector, encodeAddress, bscEthCall } = await import('../services/evmWallet');
      const { transferUsdt, USDT_BSC } = await import('../services/cusdPlusVault');
      const wallet = await getActiveEvmWallet();
      const balHex = await bscEthCall(
        USDT_BSC,
        selector('balanceOf(address)') + encodeAddress(wallet.address),
      );
      const balWei = BigInt(balHex === '0x' ? '0x0' : balHex);
      // Cent precision from the text input, clamped to the live balance.
      let amountWei = BigInt(Math.round(amountNum * 100)) * 10n ** 16n;
      if (amountWei > balWei) amountWei = balWei;
      if (amountWei <= 0n) {
        throw new Error('Saldo insuficiente.');
      }
      await transferUsdt({ to: destination.trim(), amountWei, wallet });
      Alert.alert(
        'Enviado',
        `Enviaste $${formatFixedFloor(Number(amountWei / 10n ** 16n) / 100, 2)} USDT por la red BNB Smart Chain.`,
        [{ text: 'Listo', onPress: () => navigation.goBack() }],
      );
    } catch (e: any) {
      // Honest, retryable: nothing left the wallet if the relay refused it.
      // Server-rail errors arrive as stable codes; map them to Spanish.
      const { BSC_SEND_ERRORS } = await import('../services/bscSend');
      const msg = e?.message || '';
      setErrorMessage(
        msg === 'Saldo insuficiente.'
          ? 'Saldo insuficiente.'
          : BSC_SEND_ERRORS[msg]
            || 'No se pudo enviar. Revisa tu conexión e inténtalo de nuevo.',
      );
      setShowError(true);
    } finally {
      setSending(false);
    }
  };

  return (
    <View style={styles.container}>
      {/* Compact instrument header — house send-screen grammar */}
      <SafeAreaView edges={['top']} style={{ backgroundColor: config.color }}>
        <View style={[styles.header, { backgroundColor: config.color }]}>
          <TouchableOpacity
            onPress={() => navigation.goBack()}
            style={styles.backButton}
            accessibilityRole="button"
            accessibilityLabel="Volver"
          >
            <Icon name="arrow-left" size={24} color={colors.white} />
          </TouchableOpacity>
          <View style={styles.headerCenter}>
            <Image source={config.logo} style={styles.headerLogo} />
            <Text style={styles.headerTitle}>Enviar {config.name}</Text>
          </View>
          <View style={styles.placeholder} />
        </View>
      </SafeAreaView>

      <ScrollView style={styles.content} contentContainerStyle={styles.contentContainer}>
        {/* Available Balance */}
        <View style={styles.balanceCard}>
          <Text style={styles.balanceLabel}>Saldo disponible</Text>
          <Text style={styles.balanceAmount}>
            {config.isUsd
              ? `$${formatFixedFloor(available, 2)}`
              : `${formatFixedFloor(available, 2)} ${config.name}`}
          </Text>
          <Text style={styles.balanceMin}>
            {config.isUsd
              ? `Mínimo para enviar: $${MIN_SEND}.00`
              : `Mínimo para enviar: ${MIN_SEND} ${config.name}`}
          </Text>
        </View>

        <InlineBanner
          variant="info"
          message={config.networkBanner}
          style={{ marginHorizontal: 16, marginTop: 16 }}
        />
        {token === 'usdt' && savings.balanceUsd > 0 && (
          <InlineBanner
            variant="info"
            message="Tu saldo incluye tu Confío Dollar (cUSD+). Al enviar, se convierte automáticamente a USDT y se envía a la dirección destino."
            style={{ marginHorizontal: 16, marginTop: 10 }}
          />
        )}

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
                <Image source={config.logo} style={styles.currencyBadgeLogo} />
                <Text style={styles.currencyBadgeText}>{config.name}</Text>
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
            ) : wrongChainMessage ? (
              <Text style={[styles.addressHelp, styles.addressWrongChain]}>
                {wrongChainMessage}
              </Text>
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
          title={sending ? 'Enviando…'
            : !balanceReady ? 'Cargando saldo…'
              : amountNum > available ? 'Saldo insuficiente' : 'Enviar'}
          onPress={handleSend}
          // Rail sends leave for the processing screen immediately; the
          // legacy path signs and broadcasts HERE, so the spinner is the
          // only sign the tap registered.
          loading={sending}
          disabled={sending || !balanceReady || !amount || !destination || amountNum > available}
          accessibilityLabel="Enviar"
          icon={<Icon name="send" size={20} color="#ffffff" />}
          style={{ backgroundColor: config.color }}
        />
      </View>

      <AddressScannerModal
        network="bsc"
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
  addressWrongChain: { color: colors.warning.text, fontWeight: '600' },
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
