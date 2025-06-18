import React, { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Platform, ScrollView, TextInput, Image } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';

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
    available: '2,850.35',
    fee: 0.02,
    description: 'Envía cUSD a cualquier dirección Sui',
    quickAmounts: ['10.00', '50.00', '100.00'],
  },
  confio: {
    name: 'CONFIO',
    fullName: 'Confío Token',
    logo: CONFIOLogo,
    color: colors.secondary,
    minSend: 1,
    available: '1,000.00',
    fee: 0.02,
    description: 'Envía CONFIO a cualquier dirección Sui',
    quickAmounts: ['10.00', '50.00', '100.00'],
  },
};

export const SendScreen = () => {
  const navigation = useNavigation();
  const route = useRoute();
  const tokenType: TokenType = (route.params as any)?.tokenType || 'cusd';
  const config = tokenConfig[tokenType];

  const [amount, setAmount] = useState('');
  const [destination, setDestination] = useState('');
  const [showSuccess, setShowSuccess] = useState(false);
  const [showError, setShowError] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const handleQuickAmount = (val: string) => setAmount(val);

  const handleSend = () => {
    if (!amount || parseFloat(amount) < config.minSend) {
      setErrorMessage(`El mínimo para enviar es ${config.minSend} ${config.name}`);
      setShowError(true);
      return;
    }
    if (!destination || !destination.startsWith('0x')) {
      setErrorMessage('Dirección de destino inválida');
      setShowError(true);
      return;
    }
    setShowSuccess(true);
    setTimeout(() => {
      setShowSuccess(false);
      setAmount('');
      setDestination('');
    }, 2000);
  };

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={[styles.header, { backgroundColor: config.color }]}> 
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

      <ScrollView style={styles.content} contentContainerStyle={styles.contentContainer}>
        {/* Available Balance */}
        <View style={styles.balanceCard}>
          <Text style={styles.balanceLabel}>Saldo disponible</Text>
          <Text style={styles.balanceAmount}>{config.available} {config.name}</Text>
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
            <View style={styles.quickAmounts}>
              {config.quickAmounts.map((val) => (
                <TouchableOpacity 
                  key={val}
                  onPress={() => handleQuickAmount(val)}
                  style={styles.quickAmountButton}
                >
                  <Text style={styles.quickAmountText}>${val}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>

          {/* Destination Address */}
          <View style={styles.inputContainer}>
            <Text style={styles.inputLabel}>Dirección de destino</Text>
            <View style={styles.addressInput}>
              <TextInput
                value={destination}
                onChangeText={setDestination}
                placeholder="0x... (dirección en red Sui)"
                style={styles.addressInputField}
              />
              <TouchableOpacity style={styles.walletButton}>
                <Icon name="credit-card" size={20} color={config.color} />
              </TouchableOpacity>
            </View>
            <Text style={styles.inputHelper}>
              Solo direcciones válidas en red Sui
            </Text>
          </View>

          {/* Fee Breakdown */}
          <View style={styles.feeBreakdown}>
            <View style={styles.feeRow}>
              <Text style={styles.feeLabel}>Comisión de red</Text>
              <Text style={styles.feeValue}>~${config.fee.toFixed(2)}</Text>
            </View>
            <View style={styles.feeRow}>
              <Text style={styles.feeLabel}>Tiempo estimado</Text>
              <View style={styles.timeContainer}>
                <Icon name="clock" size={12} color={config.color} style={styles.timeIcon} />
                <Text style={styles.timeText}>1-3 minutos</Text>
              </View>
            </View>
            <View style={styles.feeDivider} />
            <View style={styles.feeRow}>
              <Text style={styles.feeTotalLabel}>Total a enviar</Text>
              <Text style={styles.feeTotalValue}>
                {amount ? (parseFloat(amount) + config.fee).toFixed(2) : '0.00'} {config.name}
              </Text>
            </View>
          </View>

          <TouchableOpacity 
            style={[
              styles.confirmButton,
              (!amount || !destination || parseFloat(amount) < config.minSend) && styles.confirmButtonDisabled
            ]}
            disabled={!amount || !destination || parseFloat(amount) < config.minSend}
            onPress={handleSend}
          >
            <Text style={styles.confirmButtonText}>Confirmar Envío</Text>
          </TouchableOpacity>

          {showSuccess && (
            <View style={styles.successBox}>
              <Icon name="check-circle" size={32} color={config.color} />
              <Text style={styles.successText}>¡Envío realizado!</Text>
            </View>
          )}
          {showError && (
            <View style={styles.errorBox}>
              <Icon name="alert-triangle" size={28} color={colors.warning.icon} />
              <Text style={styles.errorText}>{errorMessage}</Text>
              <TouchableOpacity onPress={() => setShowError(false)}>
                <Text style={styles.errorDismiss}>Cerrar</Text>
              </TouchableOpacity>
            </View>
          )}
        </View>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    paddingTop: 48,
    paddingBottom: 32,
    paddingHorizontal: 16,
  },
  headerContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 24,
  },
  backButton: {
    padding: 8,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: 'bold',
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
    backgroundColor: '#ffffff',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
    padding: 8,
  },
  logo: {
    width: '100%',
    height: '100%',
    resizeMode: 'contain',
  },
  headerSubtitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#ffffff',
    marginBottom: 8,
  },
  headerDescription: {
    fontSize: 14,
    color: '#ffffff',
    opacity: 0.8,
  },
  content: {
    flex: 1,
  },
  contentContainer: {
    padding: 16,
    paddingBottom: 32,
  },
  balanceCard: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 16,
    marginBottom: 16,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.1,
        shadowRadius: 4,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  balanceLabel: {
    flex: 1,
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  balanceAmount: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  balanceMin: {
    fontSize: 14,
    color: '#6B7280',
  },
  formCard: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 24,
    marginBottom: 16,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.1,
        shadowRadius: 4,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  formTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 16,
  },
  inputContainer: {
    marginBottom: 24,
  },
  inputLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: '#374151',
    marginBottom: 8,
  },
  amountContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F0F6FF', // or your blue-50
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 12,
    marginBottom: 8,
  },
  amountField: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1F2937',
    backgroundColor: 'transparent',
    borderWidth: 0,
  },
  currencyBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    marginLeft: 8,
  },
  currencyBadgeLogo: {
    width: 32,
    height: 32,
    resizeMode: 'contain',
    marginRight: 6,
  },
  currencyBadgeText: {
    fontSize: 18,
    fontWeight: '600',
    color: '#2563eb',
  },
  quickAmounts: {
    flexDirection: 'row',
    marginTop: 12,
    gap: 8,
  },
  quickAmountButton: {
    backgroundColor: colors.accent + '20',
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 16,
  },
  quickAmountText: {
    fontSize: 12,
    color: colors.accent,
  },
  addressInput: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  addressInputField: {
    flex: 1,
    fontSize: 14,
    color: '#1F2937',
  },
  walletButton: {
    padding: 4,
  },
  inputHelper: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 4,
  },
  feeBreakdown: {
    marginBottom: 24,
  },
  feeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  feeLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  feeValue: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  timeContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  timeIcon: {
    marginRight: 4,
  },
  timeText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  feeDivider: {
    height: 1,
    backgroundColor: '#E5E7EB',
    marginVertical: 12,
  },
  feeTotalLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1F2937',
  },
  feeTotalValue: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.accent,
  },
  confirmButton: {
    backgroundColor: colors.accent,
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  confirmButtonDisabled: {
    opacity: 0.5,
  },
  confirmButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  successBox: {
    alignItems: 'center',
    marginTop: 16,
    marginBottom: 8,
  },
  successText: {
    color: colors.primary,
    fontSize: 16,
    fontWeight: '600',
    marginTop: 8,
  },
  errorBox: {
    alignItems: 'center',
    marginTop: 16,
    marginBottom: 8,
    backgroundColor: colors.warning.background,
    borderRadius: 8,
    padding: 12,
  },
  errorText: {
    color: colors.warning.text,
    fontSize: 15,
    fontWeight: '500',
    marginTop: 8,
    marginBottom: 4,
    textAlign: 'center',
  },
  errorDismiss: {
    color: colors.warning.icon,
    fontWeight: 'bold',
    marginTop: 8,
    fontSize: 14,
  },
}); 