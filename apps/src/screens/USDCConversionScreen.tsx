import React, { useState, useRef, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  Platform,
  KeyboardAvoidingView,
  ScrollView,
  Alert,
  ActivityIndicator,
  Modal,
  Animated,
  Image,
  Easing,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Feather';
import { Header } from '../navigation/Header';
import { MainStackParamList } from '../types/navigation';
import { useAccount } from '../contexts/AccountContext';
import { useQuery, useMutation, gql } from '@apollo/client';
import { GET_ACCOUNT_BALANCE } from '../apollo/queries';
import { ConvertWsSession } from '../services/convertWs';
import algorandService from '../services/algorandService';
import { secureDeterministicWallet } from '../services/secureDeterministicWallet';
import { oauthStorage } from '../services/oauthStorageService';
import { cusdAppOptInService } from '../services/cusdAppOptInService';
import { biometricAuthService } from '../services/biometricAuthService';

// GraphQL mutation for USDC opt-in (reused from DepositScreen)
const OPT_IN_TO_USDC = gql`
  mutation OptInToAsset($assetType: String!) {
    optInToAssetByType(assetType: $assetType) {
      success
      error
      alreadyOptedIn
      requiresUserSignature
      userTransaction
      sponsorTransaction
      groupId
      assetId
      assetName
    }
  }
`;

// GraphQL query to check current opt-ins
const CHECK_ASSET_OPT_INS = gql`
  query CheckAssetOptIns {
    checkAssetOptIns {
      optedInAssets
      assetDetails
    }
  }
`;

const colors = {
  primary: '#34D399',
  secondary: '#8B5CF6',
  accent: '#3B82F6',
  background: '#F9FAFB',
  mint: '#10b981', // mint color for free fees
  text: {
    primary: '#1F2937',
    secondary: '#6B7280',
  },
};

type NavigationProp = NativeStackNavigationProp<MainStackParamList>;

export const USDCConversionScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { activeAccount } = useAccount();
  const [amount, setAmount] = useState('');
  const [conversionDirection, setConversionDirection] = useState<'usdc_to_cusd' | 'cusd_to_usdc'>('usdc_to_cusd');
  const [isProcessing, setIsProcessing] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState('');
  
  // USDC opt-in mutation
  const [optInToUsdc] = useMutation(OPT_IN_TO_USDC);
  
  // Query to check opt-in status  
  const { refetch: refetchOptIns } = useQuery(CHECK_ASSET_OPT_INS);
  
  // Animation for loading spinner
  const spinValue = useRef(new Animated.Value(0)).current;
  
  useEffect(() => {
    if (loadingMessage) {
      // Start spinning animation when loading
      Animated.loop(
        Animated.timing(spinValue, {
          toValue: 1,
          duration: 2000,
          easing: Easing.linear,
          useNativeDriver: true,
        })
      ).start();
    } else {
      // Reset animation when not loading
      spinValue.setValue(0);
    }
  }, [loadingMessage]);
  
  const spin = spinValue.interpolate({
    inputRange: [0, 1],
    outputRange: ['0deg', '360deg'],
  });

  // Legacy conversion GraphQL mutations removed in favor of WS two-step

  // Fetch real balances from GraphQL
  const { data: cusdBalanceData, loading: cusdLoading, refetch: refetchCusd } = useQuery(GET_ACCOUNT_BALANCE, {
    variables: { tokenType: 'cUSD' },
    pollInterval: 30000, // Poll every 30 seconds
  });
  
  const { data: usdcBalanceData, loading: usdcLoading, refetch: refetchUsdc } = useQuery(GET_ACCOUNT_BALANCE, {
    variables: { tokenType: 'USDC' },
    pollInterval: 30000, // Poll every 30 seconds
  });

  // Parse balances from GraphQL data
  const usdcBalance = parseFloat(usdcBalanceData?.accountBalance || '0');
  const cusdBalance = parseFloat(cusdBalanceData?.accountBalance || '0');
  
  // Loading state for balances
  const balancesLoading = cusdLoading || usdcLoading;

  const sourceBalance = conversionDirection === 'usdc_to_cusd' ? usdcBalance : cusdBalance;
  const sourceCurrency = conversionDirection === 'usdc_to_cusd' ? 'USDC' : 'cUSD';
  const targetCurrency = conversionDirection === 'usdc_to_cusd' ? 'cUSD' : 'USDC';

  const handleAmountChange = (value: string) => {
    // Allow only numbers and decimal point
    const numericValue = value.replace(/[^0-9.]/g, '');
    
    // Prevent multiple decimal points
    const parts = numericValue.split('.');
    if (parts.length > 2) return;
    
    // Limit to 2 decimal places
    if (parts[1] && parts[1].length > 2) return;
    
    setAmount(numericValue);
  };

  const handleMaxAmount = () => {
    setAmount(sourceBalance.toString());
  };

  const switchDirection = () => {
    setConversionDirection(prev => 
      prev === 'usdc_to_cusd' ? 'cusd_to_usdc' : 'usdc_to_cusd'
    );
    setAmount('');
  };

  const validateAmount = () => {
    const numAmount = parseFloat(amount);
    if (isNaN(numAmount) || numAmount <= 0) {
      Alert.alert('Monto inválido', 'Por favor ingresa un monto válido');
      return false;
    }
    if (numAmount > sourceBalance) {
      Alert.alert('Saldo insuficiente', `No tienes suficiente ${sourceCurrency} para esta conversión`);
      return false;
    }
    return true;
  };

  // Removed legacy sign/execute function

  // Helper function to handle USDC asset opt-in (reused from DepositScreen pattern)
  const handleUSDCOptIn = async (): Promise<boolean> => {
    try {
      setLoadingMessage('Configurando acceso a USDC...');
      console.log('[USDCConversionScreen] Calling optInToAsset mutation for USDC...');
      
      const { data, errors } = await optInToUsdc({
        variables: { assetType: 'USDC' }
      });
      
      if (errors) {
        console.error('[USDCConversionScreen] GraphQL errors:', errors);
        return false;
      }
      
      console.log('[USDCConversionScreen] USDC opt-in mutation response:', data);
      
      if (data?.optInToAssetByType?.alreadyOptedIn) {
        console.log('[USDCConversionScreen] User already opted in to USDC');
        await refetchOptIns();
        return true;
      }
      
      if (data?.optInToAssetByType?.success && data.optInToAssetByType.requiresUserSignature) {
        const userTxn = data.optInToAssetByType.userTransaction;
        const sponsorTxn = data.optInToAssetByType.sponsorTransaction;
        
        console.log('[USDCConversionScreen] Signing and submitting USDC opt-in...');
        const txId = await algorandService.signAndSubmitSponsoredTransaction(
          userTxn,
          sponsorTxn
        );
        
        if (txId) {
          console.log('[USDCConversionScreen] Successfully opted in to USDC:', txId);
          await refetchOptIns();
          return true;
        } else {
          console.error('[USDCConversionScreen] Failed to submit USDC opt-in transaction');
          return false;
        }
      } else {
        console.error('[USDCConversionScreen] Failed to generate USDC opt-in transaction:', data?.optInToAssetByType?.error);
        return false;
      }
    } catch (error) {
      console.error('[USDCConversionScreen] Error during USDC opt-in:', error);
      return false;
    }
  };

  const handleConversionSuccess = async () => {
    Alert.alert(
      'Conversión exitosa',
      `Has convertido ${amount} ${sourceCurrency} a ${amount} ${targetCurrency}`,
      [
        {
          text: 'Ver historial',
          onPress: () => {
            // Navigate to USDC History screen
            navigation.navigate('USDCHistory' as never);
          },
        },
        {
          text: 'OK',
          onPress: () => {
            // Clear amount and navigate back
            setAmount('');
            // Navigate back to AccountDetail with refresh
            navigation.navigate('AccountDetail' as never, {
              accountType: 'cusd',
              accountName: 'Confío Dollar',
              accountSymbol: '$cUSD',
              accountBalance: '0', // AccountDetailScreen will fetch real balance
              accountAddress: activeAccount?.algorandAddress || '',
              refreshTimestamp: Date.now()
            } as never);
          },
        },
      ]
    );
  };

  const handleConvert = async () => {
    await handleConvertWS();
  };

  // New WS-based conversion handler (non-blocking two-step)
  const handleConvertWS = async () => {
    if (!validateAmount()) return;

    if (!activeAccount?.algorandAddress) {
      Alert.alert('Cuenta no configurada', 'Tu cuenta necesita estar configurada con Algorand para realizar conversiones. Por favor, contacta soporte.', [{ text: 'OK' }]);
      return;
    }

    const bioOk = await biometricAuthService.authenticate(
      'Autoriza esta conversión (operación crítica)'
    );
    if (!bioOk) {
      Alert.alert('Se requiere biometría', 'Confirma con Face ID / Touch ID o huella para convertir.', [{ text: 'OK' }]);
      return;
    }

    setIsProcessing(true);
    setLoadingMessage('Preparando conversión...');
    console.log('[USDCConversionScreen] Starting conversion (WS):', { amount, conversionDirection, sourceCurrency, targetCurrency });

    try {
      const ws = new ConvertWsSession();
      let pack: any;
      let retryCount = 0;
      const maxRetries = 2; // Allow for both cUSD app opt-in and USDC asset opt-in
      
      while (retryCount <= maxRetries) {
        try {
          pack = await ws.prepare({ direction: conversionDirection, amount: amount });
          break; // Success, exit retry loop
        } catch (e: any) {
          const errorMessage = String(e?.message);
          console.log('[USDCConversionScreen] Conversion prepare error:', errorMessage);
          
          if (errorMessage === 'requires_app_optin') {
            // Handle cUSD app opt-in
            try {
              setLoadingMessage('Autorizando aplicación cUSD...');
              const oauthData = await oauthStorage.getOAuthSubject();
              if (oauthData && oauthData.subject && oauthData.provider) {
                const { GOOGLE_CLIENT_IDS } = await import('../config/env');
                const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
                const iss = oauthData.provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
                const aud = oauthData.provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';
                await secureDeterministicWallet.createOrRestoreWallet(iss, oauthData.subject, aud, oauthData.provider, activeAccount?.type || 'personal', activeAccount?.index || 0, activeAccount?.id?.startsWith('business_') ? (activeAccount.id.split('_')[1] || undefined) : undefined);
              }
              const optInResult = await cusdAppOptInService.handleAppOptIn(activeAccount);
              if (!optInResult.success) {
                setLoadingMessage('');
                Alert.alert('Error', optInResult.error || 'No se pudo completar la configuración inicial');
                return;
              }
              retryCount++;
              setLoadingMessage('Preparando conversión...');
              continue; // Retry the prepare call
            } catch (err) {
              setLoadingMessage('');
              console.error('[USDCConversionScreen] App opt-in error', err);
              Alert.alert('Error', 'No se pudo completar la configuración inicial');
              return;
            }
          } else if (errorMessage.includes('not opted') || errorMessage.includes('USDC') || errorMessage.includes('asset') || errorMessage.includes('Please opt-in to USDC and cUSD assets first')) {
            // Handle USDC asset opt-in - try to auto opt-in gracefully
            try {
              console.log('[USDCConversionScreen] Attempting auto USDC opt-in...');
              const usdcOptInSuccess = await handleUSDCOptIn();
              if (usdcOptInSuccess) {
                retryCount++;
                setLoadingMessage('Preparando conversión...');
                continue; // Retry the prepare call
              } else {
                // USDC opt-in failed, but don't show error - just break out
                console.log('[USDCConversionScreen] USDC opt-in failed, stopping conversion gracefully');
                setLoadingMessage('');
                return;
              }
            } catch (usdcErr) {
              console.error('[USDCConversionScreen] USDC opt-in error', usdcErr);
              setLoadingMessage('');
              return;
            }
          } else {
            // Other errors - show the original error
            setLoadingMessage('');
            Alert.alert('Error', String(e?.message || 'No se pudo preparar la conversión'));
            return;
          }
        }
      }
      
      if (!pack) {
        setLoadingMessage('');
        Alert.alert('Error', 'No se pudo preparar la conversión después de varios intentos');
        return;
      }

      // Ensure wallet is ready for signing
      setLoadingMessage('Preparando wallet...');
      try {
        const oauthData = await oauthStorage.getOAuthSubject();
        if (oauthData && oauthData.subject && oauthData.provider) {
          const { GOOGLE_CLIENT_IDS } = await import('../config/env');
          const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
          const iss = oauthData.provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
          const aud = oauthData.provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';
          await secureDeterministicWallet.createOrRestoreWallet(iss, oauthData.subject, aud, oauthData.provider, activeAccount?.type || 'personal', activeAccount?.index || 0, activeAccount?.id?.startsWith('business_') ? (activeAccount.id.split('_')[1] || undefined) : undefined);
        }
      } catch {}

      // Sign and submit group
      setLoadingMessage('Firmando transacción...');
      const unsignedTxs: string[] = pack?.transactions || [];
      const signedUserTransactions: string[] = [];
      for (const utxB64 of unsignedTxs) {
        const bytes = Uint8Array.from(Buffer.from(utxB64, 'base64'));
        const signed = await algorandService.signTransactionBytes(bytes);
        signedUserTransactions.push(Buffer.from(signed).toString('base64'));
      }
      setLoadingMessage('Enviando conversión...');
      await ws.submit({ conversionId: pack?.conversion_id, signedUserTransactions, sponsorTransactions: pack?.sponsor_transactions || [] });

      setLoadingMessage('');
      await refetchCusd();
      await refetchUsdc();
      await handleConversionSuccess();
    } catch (error: any) {
      console.error('[USDCConversionScreen] Conversion error:', error);
      const errorMessage = String(error?.message || error);
      
      // Handle opt-in related errors gracefully without showing alerts
      if (errorMessage.includes('not opted') || 
          errorMessage.includes('opt-in') || 
          errorMessage.includes('Please opt-in to USDC and cUSD assets first') ||
          errorMessage.includes('requires_app_optin')) {
        console.log('[USDCConversionScreen] Conversion failed due to opt-in issue - handled gracefully');
        // Don't show error alert for opt-in issues - they should be handled automatically
      } else {
        // Show error only for non-opt-in related issues
        Alert.alert('Error', 'No se pudo completar la conversión. Por favor intenta de nuevo.');
      }
    } finally {
      setIsProcessing(false);
      setLoadingMessage('');
    }
  };

  const isValidAmount = amount && parseFloat(amount) > 0 && parseFloat(amount) <= sourceBalance;

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation}
        title="Convertir"
        backgroundColor={colors.accent}
        isLight={true}
        showBackButton={true}
      />
      
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.content}
      >
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Conversion Card */}
          <View style={styles.conversionCard}>
            {/* From Section */}
            <View style={styles.currencySection}>
              <Text style={styles.sectionLabel}>Desde</Text>
              <View style={styles.currencyInfo}>
                <View style={styles.currencyHeader}>
                  <Text style={styles.currencyName}>{sourceCurrency}</Text>
                  {balancesLoading ? (
                    <ActivityIndicator size="small" color={colors.primary} />
                  ) : (
                    <Text style={styles.balanceText}>
                      Saldo: ${sourceBalance.toFixed(2)}
                    </Text>
                  )}
                </View>
                <View style={styles.inputContainer}>
                  <TextInput
                    style={styles.amountInput}
                    value={amount}
                    onChangeText={handleAmountChange}
                    placeholder="0.00"
                    placeholderTextColor="#9CA3AF"
                    keyboardType="decimal-pad"
                    editable={!isProcessing}
                  />
                  <TouchableOpacity
                    style={styles.maxButton}
                    onPress={handleMaxAmount}
                    disabled={isProcessing}
                  >
                    <Text style={styles.maxButtonText}>MAX</Text>
                  </TouchableOpacity>
                </View>
              </View>
            </View>

            {/* Switch Button */}
            <TouchableOpacity
              style={styles.switchButton}
              onPress={switchDirection}
              disabled={isProcessing}
            >
              <Icon name="refresh-cw" size={20} color={colors.accent} />
            </TouchableOpacity>

            {/* To Section */}
            <View style={styles.currencySection}>
              <Text style={styles.sectionLabel}>Hacia</Text>
              <View style={styles.currencyInfo}>
                <View style={styles.currencyHeader}>
                  <Text style={styles.currencyName}>{targetCurrency}</Text>
                  <Text style={styles.balanceText}>
                    Recibirás
                  </Text>
                </View>
                <View style={styles.receiveContainer}>
                  <Text style={styles.receiveAmount}>
                    {amount || '0.00'}
                  </Text>
                  <Text style={styles.receiveCurrency}>{targetCurrency}</Text>
                </View>
              </View>
            </View>
          </View>

          {/* Conversion Info */}
          <View style={styles.infoCard}>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Tasa de conversión</Text>
              <Text style={styles.infoValue}>1 {sourceCurrency} = 1 {targetCurrency}</Text>
            </View>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Comisión de red</Text>
              <View style={styles.feeValueContainer}>
                <Text style={[styles.infoValue, { color: colors.mint }]}>Gratis</Text>
                <Text style={styles.feeValueNote}>• Cubierto por Confío</Text>
              </View>
            </View>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Tiempo estimado</Text>
              <Text style={styles.infoValue}>Instantáneo</Text>
            </View>
          </View>

          {/* Info Text */}
          <View style={styles.infoTextContainer}>
            <Icon name="info" size={16} color={colors.text.secondary} />
            <Text style={styles.infoText}>
              Las conversiones entre USDC y cUSD son instantáneas y sin comisiones
            </Text>
          </View>

          {/* Convert Button */}
          <TouchableOpacity
            style={[
              styles.convertButton,
              (!isValidAmount || isProcessing) && styles.convertButtonDisabled
            ]}
            onPress={handleConvertWS}
            disabled={!isValidAmount || isProcessing}
          >
            {isProcessing ? (
              <View style={styles.buttonContent}>
                <Icon name="loader" size={20} color="#fff" />
                <Text style={styles.convertButtonText}>Procesando...</Text>
              </View>
            ) : (
              <Text style={styles.convertButtonText}>
                Convertir {sourceCurrency} a {targetCurrency}
              </Text>
            )}
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
      
      {/* Loading Modal */}
      <Modal
        visible={!!loadingMessage}
        transparent={true}
        animationType="fade"
        statusBarTranslucent={true}
      >
        <View style={styles.loadingOverlay}>
          <View style={styles.loadingCard}>
            {/* Animated Confío Logo */}
            <Animated.View style={{ transform: [{ rotate: spin }] }}>
              <Image
                source={require('../assets/png/CONFIO.png')}
                style={styles.loadingLogo}
              />
            </Animated.View>
            
            {/* Loading Message */}
            <Text style={styles.loadingText}>{loadingMessage}</Text>
            
            {/* Progress Dots Animation */}
            <View style={styles.dotsContainer}>
              <View style={[styles.dot, { backgroundColor: colors.accent }]} />
              <View style={[styles.dot, { backgroundColor: colors.accent, opacity: 0.6 }]} />
              <View style={[styles.dot, { backgroundColor: colors.accent, opacity: 0.3 }]} />
            </View>
          </View>
        </View>
      </Modal>
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
  scrollContent: {
    padding: 16,
    paddingBottom: 32,
  },
  conversionCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    padding: 20,
    marginBottom: 16,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.05,
        shadowRadius: 8,
      },
      android: {
        elevation: 3,
      },
    }),
  },
  currencySection: {
    marginBottom: 24,
  },
  sectionLabel: {
    fontSize: 13,
    color: colors.text.secondary,
    marginBottom: 12,
    fontWeight: '500',
  },
  currencyInfo: {
    gap: 12,
  },
  currencyHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  currencyName: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text.primary,
  },
  balanceText: {
    fontSize: 13,
    color: colors.text.secondary,
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#F9FAFB',
  },
  amountInput: {
    flex: 1,
    fontSize: 24,
    fontWeight: '600',
    color: colors.text.primary,
  },
  maxButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: colors.accent + '20',
    borderRadius: 8,
  },
  maxButtonText: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.accent,
  },
  switchButton: {
    alignSelf: 'center',
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#F3F4F6',
    justifyContent: 'center',
    alignItems: 'center',
    marginVertical: -22,
    zIndex: 1,
    borderWidth: 4,
    borderColor: '#FFFFFF',
  },
  receiveContainer: {
    flexDirection: 'row',
    alignItems: 'baseline',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 16,
    backgroundColor: '#F9FAFB',
  },
  receiveAmount: {
    fontSize: 24,
    fontWeight: '600',
    color: colors.text.primary,
    marginRight: 8,
  },
  receiveCurrency: {
    fontSize: 16,
    color: colors.text.secondary,
  },
  infoCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    padding: 16,
    marginBottom: 16,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 1 },
        shadowOpacity: 0.03,
        shadowRadius: 4,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 8,
  },
  infoLabel: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  infoValue: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  feeValueContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  feeValueNote: {
    fontSize: 12,
    color: colors.text.secondary,
    marginLeft: 4,
  },
  infoTextContainer: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: colors.accent + '10',
    borderRadius: 12,
    padding: 12,
    marginBottom: 24,
  },
  infoText: {
    flex: 1,
    fontSize: 13,
    color: colors.text.secondary,
    marginLeft: 8,
    lineHeight: 18,
  },
  convertButton: {
    backgroundColor: colors.accent,
    borderRadius: 16,
    paddingVertical: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  convertButtonDisabled: {
    backgroundColor: '#D1D5DB',
  },
  convertButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#FFFFFF',
  },
  buttonContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  // Loading Modal Styles
  loadingOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    padding: 32,
    alignItems: 'center',
    minWidth: 280,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 4,
    },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 10,
  },
  loadingLogo: {
    width: 80,
    height: 80,
    marginBottom: 24,
  },
  loadingText: {
    fontSize: 16,
    color: colors.text,
    marginBottom: 20,
    textAlign: 'center',
    fontWeight: '500',
  },
  dotsContainer: {
    flexDirection: 'row',
    gap: 8,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
});
