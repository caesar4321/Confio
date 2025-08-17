import React, { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Platform, ScrollView, TextInput, Image, ActivityIndicator } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import { useQuery } from '@apollo/client';
import { GET_ACCOUNT_BALANCE } from '../apollo/queries';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useNumberFormat } from '../utils/numberFormatting';

const colors = {
  primary: '#34D399', // emerald-400
  secondary: '#8B5CF6', // violet-500
  accent: '#3B82F6', // blue-500
  background: '#F9FAFB', // gray-50
  neutralDark: '#F3F4F6', // gray-100
  text: {
    primary: '#1F2937', // gray-800
    secondary: '#6B7280', // gray-500
  },
  warning: {
    background: '#FEF3C7', // yellow-50
    border: '#FDE68A', // yellow-200
    text: '#92400E', // yellow-800
    icon: '#D97706', // yellow-600
  },
};

type TokenType = 'cusd' | 'confio';

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
};

export const SendWithAddressScreen = () => {
  const navigation = useNavigation();
  const route = useRoute();
  const insets = useSafeAreaInsets();
  const { formatNumber } = useNumberFormat();
  const tokenType: TokenType = (route.params as any)?.tokenType || 'cusd';
  const prefilledAddress = (route.params as any)?.prefilledAddress || '';
  const config = tokenConfig[tokenType];

  const [amount, setAmount] = useState('');
  const [destination, setDestination] = useState(prefilledAddress);
  const [showSuccess, setShowSuccess] = useState(false);
  const [showError, setShowError] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);

  // Get real balance from GraphQL
  const { data: balanceData, loading: balanceLoading } = useQuery(GET_ACCOUNT_BALANCE, {
    variables: { tokenType: tokenType.toUpperCase() },
    fetchPolicy: 'cache-and-network',
  });

  // Get real balance or fallback to 0
  const availableBalance = React.useMemo(() => {
    const balance = parseFloat(balanceData?.accountBalance || '0');
    return balance;
  }, [balanceData]);

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

  const handleSend = async () => {
    console.log('SendWithAddressScreen: handleSend called');
    
    // Prevent double-clicks/rapid button presses
    if (isProcessing) {
      console.log('SendWithAddressScreen: Already processing, ignoring duplicate click');
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
    
    setIsProcessing(true);
    
    try {
      console.log('SendWithAddressScreen: Navigating to TransactionProcessing');
      
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
          tokenType: tokenType.toUpperCase(), // Add token type for blockchain transaction
        }
      });
    } catch (error) {
      console.error('SendWithAddressScreen: Error navigating to processing screen:', error);
      setErrorMessage('Error al procesar la transacción. Inténtalo de nuevo.');
      setShowError(true);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <View style={styles.container}>
      <ScrollView style={styles.content} contentContainerStyle={styles.contentContainer}>
        {/* Header */}
        <View style={[styles.header, { backgroundColor: config.color, paddingTop: insets.top + 8 }]}> 
          <View style={styles.headerContent}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
              <Icon name="arrow-left" size={24} color="#ffffff" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Enviar {config.name}</Text>
            <View style={styles.placeholder} />
          </View>
          <View style={styles.headerInfo}>
            <View style={styles.logoContainer}>
              <Image source={config.logo} style={styles.logo} />
            </View>
            <Text style={styles.headerSubtitle}>{config.fullName}</Text>
            <Text style={styles.headerDescription}>{config.description}</Text>
          </View>
        </View>

        {/* Available Balance */}
        <View style={styles.balanceCard}>
          <Text style={styles.balanceLabel}>Saldo disponible</Text>
          {balanceLoading ? (
            <ActivityIndicator size="small" color={config.color} style={{ marginVertical: 8 }} />
          ) : (
            <Text style={styles.balanceAmount}>
              {formatFixedFloor(availableBalance, 2)} {config.name}
            </Text>
          )}
          <Text style={styles.balanceMin}>Mínimo para enviar: {config.minSend} {config.name}</Text>
        </View>

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
              >
                <Text style={styles.quickAmountText}>{val}</Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* Address Input */}
          <View style={styles.inputContainer}>
            <Text style={styles.inputLabel}>Dirección Algorand</Text>
            <TextInput
              style={styles.addressField}
              value={destination}
              onChangeText={setDestination}
              placeholder="0x..."
              autoCapitalize="none"
              autoCorrect={false}
            />
            <Text style={styles.addressHelp}>
              Ingresa la dirección Algorand del destinatario (58 caracteres)
            </Text>
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
      <View style={[styles.footer, { paddingBottom: insets.bottom + 20 }]}>
        <TouchableOpacity
          style={[
            styles.sendButton,
            { backgroundColor: config.color },
            (isProcessing || !amount || !destination || parseFloat(amount || '0') > availableBalance) && 
            styles.sendButtonDisabled
          ]}
          onPress={handleSend}
          disabled={isProcessing || !amount || !destination || parseFloat(amount || '0') > availableBalance}
        >
          {isProcessing ? (
            <ActivityIndicator color="white" />
          ) : (
            <>
              <Icon name="send" size={20} color="#ffffff" style={{ marginRight: 8 }} />
              <Text style={styles.sendButtonText}>
                {parseFloat(amount || '0') > availableBalance ? 'Saldo insuficiente' : 'Enviar'}
              </Text>
            </>
          )}
        </TouchableOpacity>
      </View>

      {/* Success Modal */}
      {showSuccess && (
        <View style={styles.overlay}>
          <View style={styles.modal}>
            <View style={[styles.iconContainer, { backgroundColor: config.color + '20' }]}>
              <Icon name="check-circle" size={48} color={config.color} />
            </View>
            <Text style={styles.modalTitle}>¡Enviado!</Text>
            <Text style={styles.modalMessage}>
              Se enviaron {amount} {config.name} exitosamente
            </Text>
            <TouchableOpacity
              style={[styles.modalButton, { backgroundColor: config.color }]}
              onPress={() => navigation.navigate('Home' as any)}
            >
              <Text style={styles.modalButtonText}>Listo</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}

      {/* Error Modal */}
      {showError && (
        <View style={styles.overlay}>
          <View style={styles.modal}>
            <View style={[styles.iconContainer, { backgroundColor: '#FEE2E2' }]}>
              <Icon name="alert-circle" size={48} color="#EF4444" />
            </View>
            <Text style={styles.modalTitle}>Error</Text>
            <Text style={styles.modalMessage}>{errorMessage}</Text>
            <TouchableOpacity
              style={[styles.modalButton, { backgroundColor: '#EF4444' }]}
              onPress={() => setShowError(false)}
            >
              <Text style={styles.modalButtonText}>Cerrar</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}
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
    paddingBottom: 32,
    borderBottomLeftRadius: 24,
    borderBottomRightRadius: 24,
  },
  headerContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    marginBottom: 24,
  },
  backButton: {
    padding: 8,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#ffffff',
  },
  placeholder: {
    width: 40,
  },
  headerInfo: {
    alignItems: 'center',
  },
  logoContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: 'rgba(255, 255, 255, 0.2)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 12,
  },
  logo: {
    width: 48,
    height: 48,
  },
  headerSubtitle: {
    fontSize: 20,
    fontWeight: '600',
    color: '#ffffff',
    marginBottom: 4,
  },
  headerDescription: {
    fontSize: 14,
    color: 'rgba(255, 255, 255, 0.8)',
  },
  balanceCard: {
    backgroundColor: '#ffffff',
    marginHorizontal: 16,
    marginTop: -16,
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
  addressField: {
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 16,
    fontSize: 14,
    color: colors.text.primary,
  },
  addressHelp: {
    fontSize: 12,
    color: colors.text.secondary,
    marginTop: 6,
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
    color: colors.primary,
    marginRight: 8,
  },
  sponsoredBadge: {
    fontSize: 12,
    color: colors.primary,
    backgroundColor: colors.primary + '20',
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
  sendButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 16,
    borderRadius: 12,
  },
  sendButtonDisabled: {
    opacity: 0.5,
  },
  sendButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#ffffff',
  },
  overlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modal: {
    backgroundColor: '#ffffff',
    borderRadius: 20,
    padding: 32,
    width: '85%',
    alignItems: 'center',
  },
  iconContainer: {
    width: 80,
    height: 80,
    borderRadius: 40,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 20,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: 8,
  },
  modalMessage: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    marginBottom: 24,
  },
  modalButton: {
    paddingHorizontal: 32,
    paddingVertical: 12,
    borderRadius: 8,
  },
  modalButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#ffffff',
  },
});
