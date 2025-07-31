import React, { useState } from 'react';
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
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Feather';
import { Header } from '../navigation/Header';
import { MainStackParamList } from '../types/navigation';
import { useAccount } from '../contexts/AccountContext';
import { useMutation } from '@apollo/client';
import { CONVERT_USDC_TO_CUSD, CONVERT_CUSD_TO_USDC } from '../apollo/mutations';

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

  // GraphQL mutations
  const [convertUsdcToCusd] = useMutation(CONVERT_USDC_TO_CUSD);
  const [convertCusdToUsdc] = useMutation(CONVERT_CUSD_TO_USDC);

  // Mock balances - in real app, fetch from API
  const usdcBalance = 250.00;
  const cusdBalance = 500.00;

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

  const handleConvert = async () => {
    if (!validateAmount()) return;

    setIsProcessing(true);
    console.log('[USDCConversionScreen] Starting conversion:', { amount, conversionDirection, sourceCurrency, targetCurrency });
    
    try {
      // Choose the appropriate mutation based on conversion direction
      const mutation = conversionDirection === 'usdc_to_cusd' ? convertUsdcToCusd : convertCusdToUsdc;
      
      console.log('[USDCConversionScreen] Calling mutation with amount:', amount);
      const { data } = await mutation({
        variables: { amount },
      });
      
      console.log('[USDCConversionScreen] Mutation response:', data);
      
      // Check which mutation was called and get the result
      const mutationResult = conversionDirection === 'usdc_to_cusd' 
        ? data?.convertUsdcToCusd 
        : data?.convertCusdToUsdc;
      
      if (mutationResult?.success) {
        // Show success
        Alert.alert(
          'Conversión exitosa',
          `Has convertido ${amount} ${sourceCurrency} a ${amount} ${targetCurrency}`,
          [
            {
              text: 'Ver historial',
              onPress: () => {
                // Go back to home first to refresh balances
                navigation.navigate('BottomTabs' as never, {
                  screen: 'Home' as never,
                } as never);
                
                // After a short delay, navigate to account detail
                setTimeout(() => {
                  navigation.navigate('AccountDetail' as never, {
                    accountType: 'cusd',
                    accountName: 'Confío Dollar',
                    accountSymbol: '$cUSD',
                    accountBalance: '0', // This will trigger refresh
                    accountAddress: activeAccount?.suiAddress || '',
                    refreshTimestamp: Date.now()
                  } as never);
                }, 500);
              },
            },
            {
              text: 'OK',
              onPress: () => {
                // Simply go back to home
                navigation.navigate('BottomTabs' as never, {
                  screen: 'Home' as never,
                } as never);
              },
            },
          ]
        );
      } else {
        // Show error from mutation
        const errorMessage = mutationResult?.errors?.join(', ') || 'Error desconocido';
        console.error('[USDCConversionScreen] Conversion failed:', errorMessage);
        Alert.alert('Error', `No se pudo completar la conversión: ${errorMessage}`);
      }
    } catch (error) {
      console.error('[USDCConversionScreen] Conversion error:', error);
      Alert.alert('Error', 'No se pudo completar la conversión. Por favor intenta de nuevo.');
    } finally {
      setIsProcessing(false);
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
                  <Text style={styles.balanceText}>
                    Saldo: ${sourceBalance.toFixed(2)}
                  </Text>
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
            onPress={handleConvert}
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
});