import React, { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Platform, ScrollView, TextInput, Image, Modal } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import USDCLogo from '../assets/png/USDC.png';
import cUSDLogo from '../assets/png/cUSD.png';

const colors = {
  primary: '#34D399', // emerald-400
  primaryText: '#34D399',
  primaryLight: '#D1FAE5', // emerald-100
  primaryDark: '#10B981', // emerald-500
  secondary: '#8B5CF6', // violet-500
  secondaryText: '#8B5CF6',
  accent: '#3B82F6', // blue-500
  accentText: '#3B82F6',
  neutral: '#F9FAFB', // gray-50
  neutralDark: '#F3F4F6', // gray-100
  dark: '#111827', // gray-900
  warning: {
    background: '#FEF2F2', // red-50
    border: '#FEE2E2', // red-200
    text: '#991B1B', // red-800
    icon: '#DC2626', // red-600
  },
  success: {
    background: '#ECFDF5', // green-50
    border: '#D1FAE5', // green-200
    text: '#065F46', // green-800
    icon: '#059669', // green-600
  },
};

const USDCManageScreen = () => {
  const navigation = useNavigation();
  const insets = useSafeAreaInsets();
  const [exchangeDirection, setExchangeDirection] = useState('usdc-to-cusd');
  const [exchangeAmount, setExchangeAmount] = useState('');
  const [withdrawalAddress, setWithdrawalAddress] = useState('');
  const [showWithdrawSection, setShowWithdrawSection] = useState(false);
  
  const availableUSDC = "458.22";
  const availableCUSD = "2,850.35";
  const minCashOut = "10.00";
  const minWithdraw = "5.00";

  const isUSDCToCUSD = exchangeDirection === 'usdc-to-cusd';
  const maxAmount = isUSDCToCUSD ? availableUSDC : availableCUSD;
  const networkFee = 0.02;
  const withdrawalFee = isUSDCToCUSD ? 0 : 0.50;
  const totalFees = networkFee + withdrawalFee;

  const handleMaxAmount = () => {
    if (isUSDCToCUSD) {
      setExchangeAmount(availableUSDC);
    } else {
      setExchangeAmount(availableCUSD.replace(',', ''));
    }
  };

  const calculateReceiveAmount = () => {
    if (!exchangeAmount) return '0.00';
    const amount = parseFloat(exchangeAmount);
    return (amount - totalFees).toFixed(2);
  };

  const [amount, setAmount] = useState('');
  const [showConfirm, setShowConfirm] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const [showError, setShowError] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const handleExchange = () => {
    if (!amount || parseFloat(amount) <= 0) {
      setErrorMessage('Por favor ingresa un monto válido');
      setShowError(true);
      return;
    }
    setShowConfirm(true);
  };

  const handleConfirm = () => {
    // TODO: Implement actual exchange logic
    setShowConfirm(false);
    setShowSuccess(true);
    setTimeout(() => {
      setShowSuccess(false);
      setAmount('');
    }, 2000);
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.neutral,
  },
  header: {
      paddingTop: insets.top + 8,
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
  toggleContainer: {
    paddingHorizontal: 16,
    marginTop: -16,
    marginBottom: 16,
  },
  toggleWrapper: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 4,
    flexDirection: 'row',
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
  toggleButton: {
    flex: 1,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  toggleButtonActive: {
    backgroundColor: colors.primary,
  },
  toggleButtonText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#6B7280',
  },
  toggleButtonTextActive: {
    color: '#ffffff',
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
  balanceHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  logoCircle: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.accent,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  logoFull: {
    width: 40,
    height: 40,
    resizeMode: 'contain',
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
      flex: 1,
  },
  feeValue: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  feeValueFree: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.primary,
      marginRight: 4,
    },
    feeValueNote: {
      color: '#6B7280',
      fontSize: 14,
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
  feeTotalValueGreen: {
    color: colors.primary,
  },
  feeTotalValueBlue: {
    color: colors.accent,
  },
  confirmButton: {
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  confirmButtonGreen: {
    backgroundColor: colors.primary,
  },
  confirmButtonBlue: {
    backgroundColor: colors.accent,
  },
  confirmButtonDisabled: {
    opacity: 0.5,
  },
  confirmButtonText: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#ffffff',
  },
  warningCard: {
    backgroundColor: colors.warning.background,
    borderWidth: 1,
    borderColor: colors.warning.border,
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    flexDirection: 'row',
  },
  warningIcon: {
    marginRight: 12,
    marginTop: 2,
  },
  warningContent: {
    flex: 1,
  },
  warningTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.warning.text,
    marginBottom: 8,
  },
  warningList: {
    gap: 4,
  },
  warningText: {
    fontSize: 14,
    color: colors.warning.text,
  },
  rateCard: {
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
  rateHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  rateIcon: {
    marginRight: 8,
  },
  rateLabel: {
    flex: 1,
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  rateValue: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  rateDescription: {
    fontSize: 14,
    color: '#6B7280',
  },
  currencyInput: {
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  currencyInputGray: {
    backgroundColor: colors.neutralDark,
  },
  currencyInputGreen: {
    backgroundColor: colors.primaryLight,
  },
  currencyHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  currencyLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  currencyAvailable: {
    fontSize: 14,
    color: '#6B7280',
  },
  exchangeArrow: {
    alignItems: 'center',
    marginVertical: 8,
  },
  receiveAmount: {
    flex: 1,
    fontSize: 24,
    fontWeight: 'bold',
  },
  receiveAmountGreen: {
    color: colors.primary,
  },
  receiveAmountGray: {
    color: '#1F2937',
  },
  infoCard: {
      backgroundColor: '#A7F3D0',
    borderRadius: 16,
      padding: 16,
      marginBottom: 20,
      marginHorizontal: 0,
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
  infoTitle: {
    fontWeight: 'bold',
      fontSize: 16,
      color: '#059669',
      marginBottom: 6,
  },
  benefitsList: {
    gap: 16,
  },
  benefitItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
      marginBottom: 8,
  },
  benefitIcon: {
    marginRight: 12,
    marginTop: 2,
  },
  benefitContent: {
    flex: 1,
  },
  benefitTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
    marginBottom: 4,
  },
  benefitDescription: {
    fontSize: 14,
    color: '#6B7280',
  },
  infoDescription: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 16,
  },
  p2pButton: {
    backgroundColor: colors.secondary,
    paddingVertical: 8,
    paddingHorizontal: 16,
    borderRadius: 8,
    alignSelf: 'flex-start',
  },
  p2pButtonText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#ffffff',
  },
  modalOverlay: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
  },
  modalContent: {
    backgroundColor: '#ffffff',
    padding: 24,
    borderRadius: 16,
    width: '80%',
    alignItems: 'center',
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 16,
  },
  modalText: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 24,
  },
  modalActions: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    width: '100%',
  },
  modalButton: {
    padding: 12,
    borderRadius: 8,
    backgroundColor: colors.accent,
  },
  modalButtonCancel: {
    backgroundColor: colors.warning.background,
  },
  modalButtonConfirm: {
    backgroundColor: colors.primary,
  },
  modalButtonText: {
    fontSize: 14,
    fontWeight: 'bold',
    color: '#ffffff',
  },
  modalButtonTextConfirm: {
    color: '#ffffff',
  },
  successIcon: {
    backgroundColor: colors.primary,
    borderRadius: 16,
    padding: 16,
    marginBottom: 16,
  },
  errorIcon: {
    backgroundColor: colors.warning.background,
  },
});

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={[styles.header, { backgroundColor: showWithdrawSection ? colors.secondary : (isUSDCToCUSD ? colors.primary : colors.accent) }]}>
        <View style={styles.headerContent}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="arrow-left" size={24} color="#ffffff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Gestionar USDC</Text>
          <View style={styles.placeholder} />
        </View>
        
        <View style={styles.headerInfo}>
          <View style={styles.logoContainer}>
            <Image source={USDCLogo} style={styles.logo} />
          </View>
          <Text style={styles.headerSubtitle}>
            {showWithdrawSection ? 'Retirar USDC' : (isUSDCToCUSD ? 'USDC → cUSD' : 'cUSD → USDC')}
          </Text>
          <Text style={styles.headerDescription}>
            {showWithdrawSection 
              ? 'Envía USDC a tu wallet externo'
              : (isUSDCToCUSD 
                ? 'Convierte USDC a cUSD para usar en Confío'
                : 'Convierte cUSD a USDC para retirar'
              )
            }
          </Text>
        </View>
      </View>

      {/* Toggle Switch */}
      <View style={styles.toggleContainer}>
        <View style={styles.toggleWrapper}>
          <TouchableOpacity 
            onPress={() => {
              setExchangeDirection('usdc-to-cusd');
              setShowWithdrawSection(false);
            }}
            style={[
              styles.toggleButton,
              isUSDCToCUSD && !showWithdrawSection && styles.toggleButtonActive,
              isUSDCToCUSD && !showWithdrawSection && { backgroundColor: colors.primary }
            ]}
          >
            <Text style={[
              styles.toggleButtonText,
              isUSDCToCUSD && !showWithdrawSection && styles.toggleButtonTextActive
            ]}>USDC → cUSD</Text>
          </TouchableOpacity>
          
          <TouchableOpacity 
            onPress={() => {
              setExchangeDirection('cusd-to-usdc');
              setShowWithdrawSection(false);
            }}
            style={[
              styles.toggleButton,
              !isUSDCToCUSD && !showWithdrawSection && styles.toggleButtonActive,
              !isUSDCToCUSD && !showWithdrawSection && { backgroundColor: colors.accent }
            ]}
          >
            <Text style={[
              styles.toggleButtonText,
              !isUSDCToCUSD && !showWithdrawSection && styles.toggleButtonTextActive
            ]}>cUSD → USDC</Text>
          </TouchableOpacity>
          
          <TouchableOpacity 
            onPress={() => setShowWithdrawSection(true)}
            style={[
              styles.toggleButton,
              showWithdrawSection && styles.toggleButtonActive,
              showWithdrawSection && { backgroundColor: colors.secondary }
            ]}
          >
            <Text style={[
              styles.toggleButtonText,
              showWithdrawSection && styles.toggleButtonTextActive
            ]}>Retirar USDC</Text>
          </TouchableOpacity>
        </View>
      </View>

      <ScrollView style={styles.content} contentContainerStyle={styles.contentContainer}>
        {showWithdrawSection ? (
          <>
            {/* USDC Balance */}
            <View style={styles.balanceCard}>
              <View style={styles.balanceHeader}>
                <View style={styles.logoCircle}>
                  <Image source={USDCLogo} style={styles.logoFull} />
                </View>
                <Text style={styles.balanceLabel}>Saldo USDC disponible</Text>
                <Text style={styles.balanceAmount}>${availableUSDC}</Text>
              </View>
              <Text style={styles.balanceMin}>Mínimo para retirar: ${minWithdraw}</Text>
            </View>

            {/* Withdrawal Form */}
            <View style={styles.formCard}>
              <Text style={styles.formTitle}>Retirar USDC a wallet externo</Text>
              
              {/* Amount Input */}
              <View style={styles.inputContainer}>
                <Text style={styles.inputLabel}>Cantidad a retirar</Text>
                <View style={styles.amountContainer}>
                  <TextInput
                    style={[styles.amountField, { flex: 1 }]}
                    value={exchangeAmount}
                    onChangeText={setExchangeAmount}
                    placeholder="0.00"
                    keyboardType="numeric"
                  />
                  <View style={styles.currencyBadge}>
                    <Image source={USDCLogo} style={styles.currencyBadgeLogo} />
                    <Text style={styles.currencyBadgeText}>USDC</Text>
                  </View>
                </View>
                <View style={styles.quickAmounts}>
                  <TouchableOpacity 
                    onPress={() => setExchangeAmount('50.00')}
                    style={styles.quickAmountButton}
                  >
                    <Text style={styles.quickAmountText}>$50</Text>
                  </TouchableOpacity>
                  <TouchableOpacity 
                    onPress={() => setExchangeAmount('100.00')}
                    style={styles.quickAmountButton}
                  >
                    <Text style={styles.quickAmountText}>$100</Text>
                  </TouchableOpacity>
                  <TouchableOpacity 
                    onPress={() => setExchangeAmount(availableUSDC)}
                    style={styles.quickAmountButton}
                  >
                    <Text style={styles.quickAmountText}>Todo</Text>
                  </TouchableOpacity>
                </View>
              </View>

              {/* Withdrawal Address */}
              <View style={styles.inputContainer}>
                <Text style={styles.inputLabel}>Dirección de destino</Text>
                <View style={styles.addressInput}>
                  <TextInput
                    value={withdrawalAddress}
                    onChangeText={setWithdrawalAddress}
                    placeholder="0x... (dirección USDC en red Sui)"
                    style={styles.addressInputField}
                  />
                  <TouchableOpacity style={styles.walletButton}>
                    <Icon name="credit-card" size={20} color={colors.accent} />
                  </TouchableOpacity>
                </View>
                <Text style={styles.inputHelper}>
                  Solo direcciones USDC válidas en red Sui
                </Text>
              </View>
              
              {/* Fee Breakdown */}
              <View style={styles.feeBreakdown}>
                <View style={styles.feeRow}>
                  <Text style={styles.feeLabel}>Comisión de red</Text>
                  <Text style={styles.feeValue}>~$0.02</Text>
                </View>
                <View style={styles.feeRow}>
                  <Text style={styles.feeLabel}>Comisión de retiro</Text>
                  <Text style={styles.feeValue}>$0.25</Text>
                </View>
                <View style={styles.feeRow}>
                  <Text style={styles.feeLabel}>Tiempo estimado</Text>
                  <View style={styles.timeContainer}>
                    <Icon name="clock" size={12} color={colors.accent} style={styles.timeIcon} />
                    <Text style={styles.timeText}>3-5 segundos</Text>
                  </View>
                </View>
                <View style={styles.feeDivider} />
                <View style={styles.feeRow}>
                  <Text style={styles.feeTotalLabel}>Total a recibir</Text>
                  <Text style={styles.feeTotalValue}>
                    {exchangeAmount ? (parseFloat(exchangeAmount) - 0.27).toFixed(2) : '0.00'} USDC
                  </Text>
                </View>
              </View>
              
              <TouchableOpacity 
                style={[
                  styles.confirmButton,
                  (!exchangeAmount || !withdrawalAddress || parseFloat(exchangeAmount) < parseFloat(minWithdraw)) && styles.confirmButtonDisabled
                ]}
                disabled={!exchangeAmount || !withdrawalAddress || parseFloat(exchangeAmount) < parseFloat(minWithdraw)}
              >
                <Text style={styles.confirmButtonText}>Confirmar Retiro</Text>
              </TouchableOpacity>
            </View>
          </>
        ) : (
          <>
            {/* Exchange Rate Info */}
            <View style={styles.rateCard}>
              <View style={styles.rateHeader}>
                <Icon 
                  name="info" 
                  size={16} 
                  color={isUSDCToCUSD ? colors.primary : colors.accent} 
                  style={styles.rateIcon} 
                />
                <Text style={styles.rateLabel}>Tasa de cambio</Text>
                <Text style={styles.rateValue}>1:1</Text>
              </View>
              <Text style={styles.rateDescription}>
                1 {isUSDCToCUSD ? 'USDC = 1.00 cUSD' : 'cUSD = 1.00 USDC'} 
                {!isUSDCToCUSD && ` • Mínimo: $${minCashOut}`}
              </Text>
            </View>

            {/* Exchange Form */}
            <View style={styles.formCard}>
              {/* From Currency */}
              <View style={[
                styles.currencyInput,
                isUSDCToCUSD ? styles.currencyInputGray : styles.currencyInputGreen
              ]}>
                <View style={styles.currencyHeader}>
                  <Text style={styles.currencyLabel}>Desde</Text>
                  <Text style={styles.currencyAvailable}>
                    Disponible: ${maxAmount} {isUSDCToCUSD ? 'USDC' : 'cUSD'}
                  </Text>
                </View>
                <View style={styles.amountContainer}>
                  <TextInput
                    style={[styles.amountField, { flex: 1 }]}
                    value={exchangeAmount}
                    onChangeText={setExchangeAmount}
                    placeholder="0.00"
                    keyboardType="numeric"
                  />
                  <View style={styles.currencyBadge}>
                    <Image source={USDCLogo} style={styles.currencyBadgeLogo} />
                    <Text style={styles.currencyBadgeText}>USDC</Text>
                  </View>
                </View>
                <View style={styles.quickAmounts}>
                  <TouchableOpacity 
                    onPress={() => setExchangeAmount('100.00')}
                    style={styles.quickAmountButton}
                  >
                    <Text style={styles.quickAmountText}>$100</Text>
                  </TouchableOpacity>
                  <TouchableOpacity 
                    onPress={() => setExchangeAmount('500.00')}
                    style={styles.quickAmountButton}
                  >
                    <Text style={styles.quickAmountText}>$500</Text>
                  </TouchableOpacity>
                  <TouchableOpacity 
                    onPress={handleMaxAmount}
                    style={styles.quickAmountButton}
                  >
                    <Text style={styles.quickAmountText}>Máximo</Text>
                  </TouchableOpacity>
                </View>
              </View>

              <View style={styles.exchangeArrow}>
                <Icon name="arrow-down" size={20} color={colors.accent} />
              </View>

              {/* To Currency */}
              <View style={[
                styles.currencyInput,
                isUSDCToCUSD ? styles.currencyInputGreen : styles.currencyInputGray
              ]}>
                <View style={styles.currencyHeader}>
                  <Text style={styles.currencyLabel}>A</Text>
                  <Text style={styles.currencyAvailable}>Recibirás</Text>
                </View>
                <View style={styles.amountContainer}>
                  <Text style={[
                    styles.receiveAmount,
                    isUSDCToCUSD ? styles.receiveAmountGreen : styles.receiveAmountGray
                  ]}>
                    {calculateReceiveAmount()}
                  </Text>
                  <View style={styles.currencyBadge}>
                    <Image 
                      source={isUSDCToCUSD ? cUSDLogo : USDCLogo} 
                      style={styles.currencyBadgeLogo} 
                    />
                    <Text style={styles.currencyBadgeText}>
                      {isUSDCToCUSD ? 'cUSD' : 'USDC'}
                    </Text>
                  </View>
                </View>
              </View>

              {/* Withdrawal Address for cUSD -> USDC */}
              {!isUSDCToCUSD && (
                <View style={styles.inputContainer}>
                  <Text style={styles.inputLabel}>Dirección de retiro (wallet externo)</Text>
                  <View style={styles.addressInput}>
                    <TextInput
                      value={withdrawalAddress}
                      onChangeText={setWithdrawalAddress}
                      placeholder="0x... (dirección USDC en red Sui)"
                      style={styles.addressInputField}
                    />
                    <TouchableOpacity style={styles.walletButton}>
                      <Icon name="credit-card" size={20} color={colors.accent} />
                    </TouchableOpacity>
                  </View>
                  <Text style={styles.inputHelper}>
                    Solo direcciones USDC válidas en red Sui
                  </Text>
                </View>
              )}
              
              {/* Fee Breakdown */}
              <View style={styles.feeBreakdown}>
                <View style={styles.feeRow}>
                  <Text style={styles.feeLabel}>Comisión de red</Text>
                  <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                    <Text style={styles.feeValueFree}>Gratis</Text>
                    <Text style={styles.feeValueNote}>• Cubierto por Confío</Text>
                  </View>
                </View>
                {!isUSDCToCUSD && (
                  <View style={styles.feeRow}>
                    <Text style={styles.feeLabel}>Comisión de retiro</Text>
                    <Text style={styles.feeValue}>${withdrawalFee.toFixed(2)}</Text>
                  </View>
                )}
                <View style={styles.feeRow}>
                  <Text style={styles.feeLabel}>Comisión de intercambio</Text>
                  <Text style={styles.feeValueFree}>Gratis</Text>
                </View>
                <View style={styles.feeRow}>
                  <Text style={styles.feeLabel}>Tiempo estimado</Text>
                  <View style={styles.timeContainer}>
                    <Icon name="clock" size={12} color={colors.accent} style={styles.timeIcon} />
                    <Text style={styles.timeText}>
                      3-5 segundos
                    </Text>
                  </View>
                </View>
                <View style={styles.feeDivider} />
                <View style={styles.feeRow}>
                  <Text style={styles.feeTotalLabel}>Total a recibir</Text>
                  <Text style={[
                    styles.feeTotalValue,
                    isUSDCToCUSD ? styles.feeTotalValueGreen : styles.feeTotalValueBlue
                  ]}>
                    {calculateReceiveAmount()} {isUSDCToCUSD ? 'cUSD' : 'USDC'}
                  </Text>
                </View>
              </View>
              
              <TouchableOpacity 
                style={[
                  styles.confirmButton,
                  isUSDCToCUSD ? styles.confirmButtonGreen : styles.confirmButtonBlue,
                  (!exchangeAmount || 
                   parseFloat(exchangeAmount) <= 0 || 
                   (!isUSDCToCUSD && !withdrawalAddress) ||
                   (!isUSDCToCUSD && parseFloat(exchangeAmount) < parseFloat(minCashOut))) && 
                  styles.confirmButtonDisabled
                ]}
                disabled={
                  !exchangeAmount || 
                  parseFloat(exchangeAmount) <= 0 || 
                  (!isUSDCToCUSD && !withdrawalAddress) ||
                  (!isUSDCToCUSD && parseFloat(exchangeAmount) < parseFloat(minCashOut))
                }
              >
                <Text style={styles.confirmButtonText}>
                  Confirmar {isUSDCToCUSD ? 'Intercambio' : 'Retiro'}
                </Text>
              </TouchableOpacity>
            </View>

            {/* Benefits/Info Section */}
            <View style={styles.infoCard}>
              <Text style={styles.infoTitle}>
                {isUSDCToCUSD ? '¿Por qué usar cUSD?' : '¿Necesitas bolívares?'}
              </Text>
              
              {isUSDCToCUSD ? (
                <View style={styles.benefitsList}>
                  <View style={styles.benefitItem}>
                    <Icon name="check-circle" size={20} color={colors.primary} style={styles.benefitIcon} />
                    <View style={styles.benefitContent}>
                      <Text style={styles.benefitTitle}>Pagos instantáneos</Text>
                      <Text style={styles.benefitDescription}>Envía dinero a contactos al instante</Text>
                    </View>
                  </View>
                  <View style={styles.benefitItem}>
                    <Icon name="shield" size={20} color={colors.primary} style={styles.benefitIcon} />
                    <View style={styles.benefitContent}>
                      <Text style={styles.benefitTitle}>Comisiones mínimas</Text>
                      <Text style={styles.benefitDescription}>Transacciones desde $0.001</Text>
                    </View>
                  </View>
                </View>
              ) : (
                <View>
                  <Text style={styles.infoDescription}>
                    Considera usar el Intercambio P2P para cambiar cUSD directamente por bolívares con otros usuarios.
                  </Text>
                  <TouchableOpacity style={styles.p2pButton}>
                    <Text style={styles.p2pButtonText}>Ir a Intercambio P2P</Text>
                  </TouchableOpacity>
                </View>
              )}
            </View>
          </>
        )}
      </ScrollView>

      <Modal
        visible={showConfirm}
        transparent
        animationType="fade"
        onRequestClose={() => setShowConfirm(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>Confirmar Intercambio</Text>
            <Text style={styles.modalText}>
              ¿Estás seguro que deseas intercambiar {amount} cUSD por USDC?
            </Text>
            <View style={styles.modalActions}>
              <TouchableOpacity 
                style={[styles.modalButton, styles.modalButtonCancel]}
                onPress={() => setShowConfirm(false)}
              >
                <Text style={styles.modalButtonText}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity 
                style={[styles.modalButton, styles.modalButtonConfirm]}
                onPress={handleConfirm}
              >
                <Text style={[styles.modalButtonText, styles.modalButtonTextConfirm]}>
                  Confirmar
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      <Modal
        visible={showSuccess}
        transparent
        animationType="fade"
        onRequestClose={() => setShowSuccess(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.successIcon}>
              <Icon name="check" size={32} color="#ffffff" />
            </View>
            <Text style={styles.modalTitle}>¡Intercambio Exitoso!</Text>
            <Text style={styles.modalText}>
              Tu intercambio de {amount} cUSD a USDC se ha completado correctamente.
            </Text>
          </View>
        </View>
      </Modal>

      <Modal
        visible={showError}
        transparent
        animationType="fade"
        onRequestClose={() => setShowError(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={[styles.successIcon, styles.errorIcon]}>
              <Icon name="alert-circle" size={32} color="#ffffff" />
            </View>
            <Text style={styles.modalTitle}>Error</Text>
            <Text style={styles.modalText}>{errorMessage}</Text>
            <TouchableOpacity 
              style={[styles.modalButton, styles.modalButtonConfirm]}
              onPress={() => setShowError(false)}
            >
              <Text style={[styles.modalButtonText, styles.modalButtonTextConfirm]}>
                Entendido
              </Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </View>
  );
};

export default USDCManageScreen; 