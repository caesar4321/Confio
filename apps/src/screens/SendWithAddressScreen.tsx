import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Platform, ScrollView, TextInput, Image, ActivityIndicator } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import { useQuery } from '@apollo/client';
import { GET_ACCOUNT_BALANCE } from '../apollo/queries';
import { apolloClient } from '../apollo/client';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import USDCLogo from '../assets/png/USDC.png';
import { SafeAreaView } from 'react-native-safe-area-context';
import Clipboard from '@react-native-clipboard/clipboard';
import { useNumberFormat } from '../utils/numberFormatting';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
import { InlineBanner } from '../components/common/InlineBanner';
import { AddressScannerModal } from '../components/AddressScannerModal';

type TokenType = 'cusd' | 'confio' | 'usdc';

const tokenConfig = {
  cusd: {
    name: 'cUSD',
    fullName: 'Confío Dollar',
    logo: cUSDLogo,
    color: colors.primary,
    minSend: 1,
    fee: 0,  // Sponsored transactions
    description: 'Envía cUSD a cualquier dirección Algorand',
    quickAmounts: ['10.00', '50.00', '100.00'],
  },
  confio: {
    name: 'CONFIO',
    fullName: 'Confío',
    logo: CONFIOLogo,
    color: colors.secondary,
    minSend: 1,
    fee: 0,  // Sponsored transactions
    description: 'Envía CONFIO a cualquier dirección Algorand',
    quickAmounts: ['10.00', '50.00', '100.00'],
  },
  usdc: {
    name: 'USDC',
    fullName: 'USD Coin',
    logo: USDCLogo,
    color: '#2775CA', // USDC Blue
    minSend: 1,
    fee: 0,  // Sponsored transactions via swap
    description: 'Envía USDC a cualquier dirección Algorand',
    quickAmounts: ['10.00', '50.00', '100.00'],
  },
};

export const SendWithAddressScreen = () => {
  const navigation = useNavigation();
  const route = useRoute();
  // Safe area handled with SafeAreaView
  const { formatNumber } = useNumberFormat();
  const tokenType: TokenType = (route.params as any)?.tokenType || 'cusd';
  const prefilledAddress = (route.params as any)?.prefilledAddress || '';
  const prefilledAmount = (route.params as any)?.prefilledAmount || '';
  const config = tokenConfig[tokenType];

  const [amount, setAmount] = useState(prefilledAmount);
  const [destination, setDestination] = useState(prefilledAddress);
  const [showError, setShowError] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [showScanner, setShowScanner] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const navLock = React.useRef(false);
  const [prepared, setPrepared] = useState<any | null>(null);

  // Balance snapshot + background refresh
  const [balanceSnapshot, setBalanceSnapshot] = useState<string | null>(null);
  const [balanceLoading, setBalanceLoading] = useState<boolean>(false);
  const [cusdBalanceSnapshot, setCusdBalanceSnapshot] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const tok = tokenType.toUpperCase();
    try {
      const cached = apolloClient.readQuery<{ accountBalance: string }>({
        query: GET_ACCOUNT_BALANCE,
        variables: { tokenType: tok }
      });
      if (cached?.accountBalance && mounted) setBalanceSnapshot(cached.accountBalance);

      if (tokenType === 'usdc') {
        const cachedCusd = apolloClient.readQuery<{ accountBalance: string }>({
          query: GET_ACCOUNT_BALANCE,
          variables: { tokenType: 'CUSD' }
        });
        if (cachedCusd?.accountBalance && mounted) setCusdBalanceSnapshot(cachedCusd.accountBalance);
      }
    } catch { }

    setBalanceLoading(true);
    apolloClient.query<{ accountBalance: string }>({
      query: GET_ACCOUNT_BALANCE,
      variables: { tokenType: tok },
      fetchPolicy: 'network-only'
    }).then(res => {
      if (!mounted) return;
      setBalanceSnapshot(res.data?.accountBalance ?? null);
    }).catch(() => { }).finally(() => mounted && setBalanceLoading(false));

    if (tokenType === 'usdc') {
      apolloClient.query<{ accountBalance: string }>({
        query: GET_ACCOUNT_BALANCE,
        variables: { tokenType: 'CUSD' },
        fetchPolicy: 'network-only'
      }).then(res => {
        if (!mounted) return;
        setCusdBalanceSnapshot(res.data?.accountBalance ?? null);
      }).catch(() => { });
    }

    return () => { mounted = false; };
  }, [tokenType]);

  const availableBalance = React.useMemo(() => parseFloat(balanceSnapshot || '0'), [balanceSnapshot]);
  const availableCusdBalance = React.useMemo(() => parseFloat(cusdBalanceSnapshot || '0'), [cusdBalanceSnapshot]);

  // Prevent overstatement: floor display to 2 decimals
  const floorToDecimals = React.useCallback((value: number, decimals: number) => {
    if (!isFinite(value)) return 0;
    const m = Math.pow(10, decimals);
    return Math.floor(value * m) / m;
  }, []);

  const formatFixedFloor = React.useCallback((value: number, decimals = 2) => {
    const floored = floorToDecimals(value, decimals);
    return floored.toLocaleString('es-ES', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  }, [floorToDecimals]);

  const handleQuickAmount = (val: string) => setAmount(val);

  const maxSendable = tokenType === 'usdc'
    ? Math.max(availableBalance, availableCusdBalance)
    : availableBalance;

  const handleMax = () => {
    const floored = floorToDecimals(maxSendable, 2);
    if (floored > 0) setAmount(String(floored));
  };

  const handlePaste = async () => {
    try {
      const text = await Clipboard.getString();
      if (text) setDestination(text.trim());
    } catch { }
  };

  const isValidAddress = destination.length === 58 && /^[A-Z2-7]{58}$/.test(destination);

  // Background preflight via WS when valid Algorand address and amount provided
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        setPrepared(null);
        const amt = parseFloat(String(amount || '0'));
        const isAlgorandAddress = destination.length === 58 && /^[A-Z2-7]{58}$/.test(destination);
        if (!(isFinite(amt) && amt > 0 && isAlgorandAddress)) return;
        const assetType = tokenType.toUpperCase();
        const { prepareSendViaWs } = await import('../services/sendWs');
        const pack = await prepareSendViaWs({
          amount: amt,
          assetType,
          recipientAddress: destination,
        });
        if (!alive) return;
        if (pack && Array.isArray((pack as any).transactions) && (pack as any).transactions.length >= 2) {
          setPrepared({ transactions: (pack as any).transactions });
        }
      } catch (e) {
        // ignore preflight errors; processing screen will fallback
      }
    })();
    return () => { alive = false; };
  }, [amount, destination, tokenType]);

  const handleSend = async () => {

    // Prevent double-clicks/rapid button presses
    if (isProcessing || navLock.current) {
      return;
    }

    if (!amount || parseFloat(amount) < config.minSend) {
      setErrorMessage(`El mínimo para enviar es ${config.minSend} ${config.name}`);
      setShowError(true);
      return;
    }
    if (!destination) {
      setErrorMessage('Dirección de destino inválida');
      setShowError(true);
      return;
    }

    // Check if it's an Algorand address (58 characters, uppercase letters and numbers 2-7)
    const isAlgorandAddress = destination.length === 58 && /^[A-Z2-7]{58}$/.test(destination);

    // Check if it's a Sui address (0x + 64 hex characters) - legacy support
    const isSuiAddress = destination.startsWith('0x') && destination.match(/^0x[0-9a-f]{64}$/); // Legacy Sui support

    if (!isAlgorandAddress && !isSuiAddress) {
      if (destination.startsWith('0x')) {
        // Attempted legacy Sui address
        if (destination.length < 66) {
          setErrorMessage('La dirección Sui (legacy) debe tener 64 caracteres hexadecimales después de 0x');
        } else {
          setErrorMessage('La dirección contiene caracteres inválidos. Use solo 0-9 y a-f');
        }
      } else if (destination.length === 58) {
        // Attempted Algorand address
        setErrorMessage('La dirección Algorand debe contener solo letras mayúsculas y números 2-7');
      } else {
        setErrorMessage('Formato de dirección inválido. Use una dirección Algorand (58 caracteres)');
      }
      setShowError(true);
      return;
    }

    // Determine if we need to swap cUSD to USDC
    let needsCusdSwap = false;
    const amountNumFloat = parseFloat(amount || '0');

    if (tokenType === 'usdc' && availableBalance < amountNumFloat) {
      if (availableCusdBalance >= amountNumFloat) {
        needsCusdSwap = true;
      } else {
        setErrorMessage('Saldo insuficiente en USDC y cUSD');
        setShowError(true);
        return;
      }
    } else if (availableBalance < amountNumFloat) {
      setErrorMessage('Saldo insuficiente');
      setShowError(true);
      return;
    }

    setIsProcessing(true);
    navLock.current = true;

    try {

      // Generate idempotency key to prevent double-spending
      const minuteTimestamp = Math.floor(Date.now() / 60000);
      const recipientSuffix = destination.slice(-8);
      const amountStr = amount.replace('.', '');
      const idempotencyKey = `send_${recipientSuffix}_${amountStr}_${config.name}_${minuteTimestamp}`;

      // Navigate to processing screen with transaction data
      (navigation as any).replace('TransactionProcessing', {
        transactionData: {
          type: 'sent',
          amount: amount,
          currency: config.name,
          recipient: destination.substring(0, 10) + '...',
          action: 'Enviando',
          recipientAddress: destination,
          memo: '', // Empty memo - user can add notes in a future feature
          idempotencyKey: idempotencyKey,
          prepared: prepared,
          tokenType: tokenType.toUpperCase(), // Add token type for blockchain transaction
          needsCusdSwap: needsCusdSwap, // Pass the swap flag to processing screen
        }
      });
    } catch (error) {
      setErrorMessage('Error al procesar la transacción. Inténtalo de nuevo.');
      setShowError(true);
    } finally {
      setTimeout(() => {
        setIsProcessing(false);
        navLock.current = false;
      }, 600);
    }
  };

  return (
    <View style={styles.container}>
      {/* Compact instrument header — this is a task screen; the color and
          logo badge carry the instrument, the form gets the space. */}
      <SafeAreaView edges={['top']} style={{ backgroundColor: config.color }}>
        <View style={[styles.header, { backgroundColor: config.color }]}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton} accessibilityRole="button" accessibilityLabel="Volver">
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
          {balanceSnapshot == null || balanceLoading ? (
            <ActivityIndicator size="small" color={config.color} style={{ marginVertical: 8 }} />
          ) : (
            <Text style={styles.balanceAmount}>
              {tokenType === 'usdc'
                ? `${formatFixedFloor(availableCusdBalance, 2)} cUSD`
                : `${formatFixedFloor(availableBalance, 2)} ${config.name}`}
            </Text>
          )}
          <Text style={styles.balanceMin}>Mínimo para enviar: {config.minSend} {config.name}</Text>
        </View>

        {tokenType === 'usdc' && (
          <InlineBanner
            variant="info"
            message="Tu saldo se muestra en cUSD. Al enviar, tus cUSD se convertirán automáticamente a USDC y se enviarán a la dirección destino."
            style={{ marginHorizontal: 16, marginTop: 16 }}
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
          {/* Amount Input */}
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

          {/* Quick Amount Buttons */}
          <View style={styles.quickAmounts}>
            {config.quickAmounts.map((val) => (
              <TouchableOpacity
                key={val}
                style={styles.quickAmountButton}
                onPress={() => handleQuickAmount(val)}
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

          {/* Address Input */}
          <View style={styles.inputContainer}>
            <Text style={styles.inputLabel}>Dirección Algorand</Text>
            <View style={styles.addressRow}>
              <TextInput
                style={styles.addressField}
                value={destination}
                onChangeText={setDestination}
                placeholder="Dirección de 58 caracteres"
                placeholderTextColor={colors.text.light}
                autoCapitalize="characters"
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
                Pega o escanea la dirección Algorand del destinatario (58 caracteres, A–Z y 2–7)
              </Text>
            ) : isValidAddress ? (
              <View style={styles.addressValidRow}>
                <Icon name="check-circle" size={13} color={colors.success} />
                <Text style={styles.addressValidText}>Dirección válida</Text>
              </View>
            ) : (
              <Text style={styles.addressHelp}>
                {destination.length}/58 caracteres · solo A–Z y 2–7
              </Text>
            )}
          </View>

          {/* Fee Info - Now shows sponsored */}
          <View style={styles.feeInfo}>
            <Text style={styles.feeLabel}>Comisión de red</Text>
            <View style={styles.feeAmountContainer}>
              <Text style={styles.feeAmount}>Gratis</Text>
              <Text style={styles.sponsoredBadge}>Cubierto por Confío</Text>
            </View>
          </View>
        </View>
      </ScrollView>

      {/* Send Button */}
      <View style={[styles.footer, { paddingBottom: 20 }]}>
        <Button
          title={balanceSnapshot == null ? 'Cargando saldo…' : parseFloat(amount || '0') > (tokenType === 'usdc' ? Math.max(availableBalance, availableCusdBalance) : availableBalance) ? 'Saldo insuficiente' : 'Enviar'}
          onPress={handleSend}
          loading={isProcessing}
          disabled={!amount || !destination || parseFloat(amount || '0') > (tokenType === 'usdc' ? Math.max(availableBalance, availableCusdBalance) : availableBalance)}
          accessibilityLabel="Enviar"
          icon={<Icon name="send" size={20} color="#ffffff" />}
          style={{ backgroundColor: config.color }}
        />
      </View>

      <AddressScannerModal
        visible={showScanner}
        onClose={() => setShowScanner(false)}
        onScanned={(address) => setDestination(address)}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    flex: 1,
  },
  contentContainer: {
    paddingBottom: 100,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 14,
  },
  backButton: {
    padding: 8,
  },
  headerCenter: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  headerLogo: {
    width: 24,
    height: 24,
    borderRadius: 12,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.white,
  },
  placeholder: {
    width: 40,
  },
  balanceCard: {
    backgroundColor: colors.background,
    marginHorizontal: 16,
    marginTop: 16,
    borderRadius: 16,
    padding: 20,
    alignItems: 'center',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.1,
        shadowRadius: 8,
      },
      android: {
        elevation: 4,
      },
    }),
  },
  balanceLabel: {
    fontSize: 14,
    color: colors.text.secondary,
    marginBottom: 4,
  },
  balanceAmount: {
    fontSize: 32,
    fontWeight: '700',
    color: colors.text.primary,
    marginBottom: 8,
  },
  balanceMin: {
    fontSize: 12,
    color: colors.text.secondary,
  },
  formCard: {
    backgroundColor: '#ffffff',
    marginHorizontal: 16,
    marginTop: 16,
    borderRadius: 16,
    padding: 20,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.05,
        shadowRadius: 8,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  inputContainer: {
    marginBottom: 20,
  },
  inputLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: 8,
  },
  amountContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    paddingHorizontal: 16,
    height: 56,
  },
  amountField: {
    fontSize: 24,
    fontWeight: '600',
    color: colors.text.primary,
    flex: 1,
  },
  currencyBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#ffffff',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
    marginLeft: 12,
  },
  currencyBadgeLogo: {
    width: 20,
    height: 20,
    marginRight: 6,
  },
  currencyBadgeText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.primary,
  },
  quickAmounts: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 20,
  },
  quickAmountButton: {
    flex: 1,
    backgroundColor: colors.neutralDark,
    paddingVertical: 10,
    marginHorizontal: 4,
    borderRadius: 8,
    alignItems: 'center',
  },
  quickAmountText: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  addressRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  addressField: {
    flex: 1,
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 16,
    fontSize: 14,
    color: colors.text.primary,
  },
  pasteButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: colors.primarySoft,
    paddingHorizontal: 14,
    paddingVertical: 16,
    borderRadius: 12,
  },
  pasteButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  scanButton: {
    backgroundColor: colors.primarySoft,
    paddingHorizontal: 13,
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  addressHelp: {
    fontSize: 12,
    color: colors.text.secondary,
    marginTop: 6,
  },
  addressValidRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    marginTop: 6,
  },
  addressValidText: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.success,
  },
  maxText: {
    color: colors.primaryDark,
    fontWeight: '700',
  },
  feeInfo: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: colors.neutralDark,
  },
  feeLabel: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  feeAmountContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  feeAmount: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.primaryDark,
    marginRight: 8,
  },
  sponsoredBadge: {
    fontSize: 12,
    color: colors.primaryDark,
    backgroundColor: colors.primarySoft,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 12,
  },
  footer: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    backgroundColor: '#ffffff',
    paddingHorizontal: 16,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: colors.neutralDark,
  },
});
