import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  ScrollView,
  Platform,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import { Header } from '../navigation/Header';
import { useAccount } from '../contexts/AccountContext';
import { useMutation, useQuery } from '@apollo/client';
import { CREATE_USDC_WITHDRAWAL, GET_UNIFIED_USDC_TRANSACTIONS } from '../apollo/mutations';
import { GET_ACCOUNT_BALANCE } from '../apollo/queries';

const colors = {
  primary: '#34D399',
  secondary: '#8B5CF6',
  accent: '#3B82F6',
  background: '#F9FAFB',
  text: {
    primary: '#1F2937',
    secondary: '#6B7280',
  },
  error: '#EF4444',
  warning: {
    background: '#FEF3C7',
    border: '#FDE68A',
    text: '#92400E',
    icon: '#D97706',
  },
};

export const USDCWithdrawScreen = () => {
  const navigation = useNavigation();
  const { activeAccount } = useAccount();
  
  const [withdrawAmount, setWithdrawAmount] = useState('');
  const [recipientAddress, setRecipientAddress] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  
  // Fetch USDC balance
  const { data: balanceData, loading: balanceLoading } = useQuery(GET_ACCOUNT_BALANCE, {
    variables: { tokenType: 'USDC' },
    fetchPolicy: 'network-only',
  });
  
  const usdcBalance = balanceData?.accountBalance ? parseFloat(balanceData.accountBalance) : 0;
  const networkFee = 0; // Network fee is covered by Confío
  
  // Create withdrawal mutation
  const [createWithdrawal] = useMutation(CREATE_USDC_WITHDRAWAL, {
    onCompleted: (data) => {
      console.log('Withdrawal mutation completed:', data);
      if (data.createUsdcWithdrawal.success) {
        // Clear form
        setWithdrawAmount('');
        setRecipientAddress('');
        
        Alert.alert(
          'Retiro Iniciado',
          `Se está procesando el retiro de ${withdrawAmount} USDC a tu wallet.\n\nID de transacción: ${data.createUsdcWithdrawal.withdrawal.withdrawalId}`,
          [
            {
              text: 'Ver historial',
              onPress: () => {
                navigation.navigate('USDCHistory');
              },
            },
            {
              text: 'OK',
              onPress: () => navigation.goBack(),
            },
          ]
        );
      } else {
        Alert.alert('Error', data.createUsdcWithdrawal.errors?.join('\n') || 'No se pudo procesar el retiro');
      }
    },
    onError: (error) => {
      console.error('Mutation error:', error);
      Alert.alert('Error', error.message || 'No se pudo procesar el retiro');
    },
  });
  
  const handleWithdraw = async () => {
    if (!withdrawAmount || parseFloat(withdrawAmount) <= 0) {
      Alert.alert('Error', 'Por favor ingresa una cantidad válida');
      return;
    }
    
    if (!recipientAddress || recipientAddress.length < 42) {
      Alert.alert('Error', 'Por favor ingresa una dirección de Sui válida');
      return;
    }
    
    const amount = parseFloat(withdrawAmount);
    if (amount > usdcBalance) {
      Alert.alert('Error', 'Saldo insuficiente');
      return;
    }
    
    // Minimum withdrawal amount
    if (amount < 1) {
      Alert.alert('Error', 'El monto mínimo de retiro es 1 USDC');
      return;
    }
    
    // Validate Sui address format (basic validation)
    if (!recipientAddress.startsWith('0x') || recipientAddress.length < 66) {
      Alert.alert('Error', 'La dirección de Sui debe comenzar con 0x y tener 66 caracteres');
      return;
    }
    
    setIsProcessing(true);
    
    try {
      console.log('Creating withdrawal with:', {
        amount: withdrawAmount,
        destinationAddress: recipientAddress,
        serviceFee: '0',
      });
      
      await createWithdrawal({
        variables: {
          input: {
            amount: withdrawAmount,
            destinationAddress: recipientAddress,
            serviceFee: '0', // No service fee for now
          },
        },
      });
    } catch (error) {
      console.error('Withdrawal error:', error);
      Alert.alert('Error', 'No se pudo procesar el retiro. Por favor intenta de nuevo.');
    } finally {
      setIsProcessing(false);
    }
  };
  
  const totalToReceive = withdrawAmount ? parseFloat(withdrawAmount) : 0;

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation}
        title="Retirar USDC"
        backgroundColor={colors.accent}
        isLight={true}
        showBackButton={true}
      />
      
      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        {/* Balance Card */}
        <View style={styles.balanceCard}>
          <Text style={styles.balanceLabel}>Saldo disponible</Text>
          {balanceLoading ? (
            <ActivityIndicator size="small" color={colors.accent} style={{ marginVertical: 8 }} />
          ) : (
            <Text style={styles.balanceAmount}>{usdcBalance.toFixed(2)} USDC</Text>
          )}
          <Text style={styles.balanceNote}>En la red Sui</Text>
        </View>
        
        {/* Warning */}
        <View style={styles.warningContainer}>
          <Icon name="alert-triangle" size={20} color={colors.warning.icon} />
          <View style={styles.warningContent}>
            <Text style={styles.warningTitle}>Importante</Text>
            <Text style={styles.warningText}>
              Los retiros se procesan en la red Sui. Asegúrate de usar una dirección de Sui válida.
            </Text>
          </View>
        </View>
        
        {/* Withdrawal Form */}
        <View style={styles.formContainer}>
          <View style={styles.inputGroup}>
            <Text style={styles.inputLabel}>Cantidad a retirar</Text>
            <View style={styles.amountInputContainer}>
              <TextInput
                style={styles.amountInput}
                value={withdrawAmount}
                onChangeText={setWithdrawAmount}
                placeholder="0.00"
                keyboardType="decimal-pad"
                placeholderTextColor="#9CA3AF"
              />
              <TouchableOpacity
                style={styles.maxButton}
                onPress={() => setWithdrawAmount(usdcBalance.toFixed(2))}
                disabled={balanceLoading || usdcBalance === 0}
              >
                <Text style={styles.maxButtonText}>MAX</Text>
              </TouchableOpacity>
              <Text style={styles.currencyText}>USDC</Text>
            </View>
          </View>
          
          <View style={styles.inputGroup}>
            <Text style={styles.inputLabel}>Dirección de destino</Text>
            <TextInput
              style={styles.addressInput}
              value={recipientAddress}
              onChangeText={setRecipientAddress}
              placeholder="0x..."
              placeholderTextColor="#9CA3AF"
              autoCapitalize="none"
              autoCorrect={false}
            />
            <Text style={styles.inputHint}>Ingresa tu dirección de Sui wallet</Text>
          </View>
          
          {/* Minimum amount notice */}
          {withdrawAmount && parseFloat(withdrawAmount) > 0 && parseFloat(withdrawAmount) < 1 && (
            <View style={styles.errorContainer}>
              <Icon name="alert-circle" size={16} color={colors.error} />
              <Text style={styles.errorText}>El monto mínimo de retiro es 1 USDC</Text>
            </View>
          )}
          
          {/* Fee Summary */}
          <View style={styles.feeSummary}>
            <View style={styles.feeRow}>
              <Text style={styles.feeLabel}>Cantidad</Text>
              <Text style={styles.feeValue}>
                {withdrawAmount || '0'} USDC
              </Text>
            </View>
            <View style={styles.feeRow}>
              <Text style={styles.feeLabel}>Comisión de red</Text>
              <View style={styles.feeValueContainer}>
                <Text style={[styles.feeValue, { color: colors.primary }]}>Gratis</Text>
                <Text style={styles.feeValueNote}>• Cubierto por Confío</Text>
              </View>
            </View>
            <View style={styles.feeDivider} />
            <View style={styles.feeRow}>
              <Text style={styles.feeTotalLabel}>Total a recibir</Text>
              <Text style={styles.feeTotalValue}>
                {totalToReceive.toFixed(2)} USDC
              </Text>
            </View>
          </View>
          
          {/* Withdraw Button */}
          <TouchableOpacity
            style={[
              styles.withdrawButton,
              (!withdrawAmount || !recipientAddress || isProcessing) && styles.withdrawButtonDisabled
            ]}
            onPress={handleWithdraw}
            disabled={!withdrawAmount || !recipientAddress || isProcessing || balanceLoading}
          >
            {isProcessing ? (
              <ActivityIndicator color="#FFFFFF" />
            ) : (
              <>
                <Icon name="arrow-up-circle" size={20} color="#FFFFFF" />
                <Text style={styles.withdrawButtonText}>Retirar USDC</Text>
              </>
            )}
          </TouchableOpacity>
          
          {/* Info */}
          <View style={styles.infoContainer}>
            <Icon name="info" size={16} color={colors.text.secondary} />
            <Text style={styles.infoText}>
              Los retiros se procesan inmediatamente. Monto mínimo: 1 USDC. El tiempo de confirmación depende de la congestión de la red Sui.
            </Text>
          </View>
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
  content: {
    flex: 1,
  },
  balanceCard: {
    backgroundColor: '#FFFFFF',
    marginHorizontal: 16,
    marginTop: 16,
    padding: 20,
    borderRadius: 16,
    alignItems: 'center',
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
    fontSize: 14,
    color: colors.text.secondary,
    marginBottom: 4,
  },
  balanceAmount: {
    fontSize: 28,
    fontWeight: 'bold',
    color: colors.text.primary,
    marginBottom: 4,
  },
  balanceNote: {
    fontSize: 12,
    color: colors.text.secondary,
  },
  warningContainer: {
    backgroundColor: colors.warning.background,
    borderWidth: 1,
    borderColor: colors.warning.border,
    borderRadius: 12,
    padding: 16,
    marginHorizontal: 16,
    marginTop: 16,
    flexDirection: 'row',
  },
  warningContent: {
    flex: 1,
    marginLeft: 12,
  },
  warningTitle: {
    fontSize: 14,
    fontWeight: 'bold',
    color: colors.warning.text,
    marginBottom: 4,
  },
  warningText: {
    fontSize: 13,
    color: colors.warning.text,
    lineHeight: 18,
  },
  formContainer: {
    padding: 16,
  },
  inputGroup: {
    marginBottom: 20,
  },
  inputLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: 8,
  },
  amountInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    paddingHorizontal: 16,
    height: 56,
  },
  amountInput: {
    flex: 1,
    fontSize: 18,
    fontWeight: '600',
    color: colors.text.primary,
  },
  maxButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: colors.accent,
    borderRadius: 6,
    marginRight: 12,
  },
  maxButtonText: {
    color: '#FFFFFF',
    fontSize: 12,
    fontWeight: '600',
  },
  currencyText: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.secondary,
  },
  addressInput: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    paddingHorizontal: 16,
    height: 56,
    fontSize: 16,
    color: colors.text.primary,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  inputHint: {
    fontSize: 12,
    color: colors.text.secondary,
    marginTop: 6,
  },
  feeSummary: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 16,
    marginBottom: 24,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.05,
        shadowRadius: 4,
      },
      android: {
        elevation: 1,
      },
    }),
  },
  feeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  feeLabel: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  feeValue: {
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
  feeDivider: {
    height: 1,
    backgroundColor: '#E5E7EB',
    marginBottom: 12,
  },
  feeTotalLabel: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text.primary,
  },
  feeTotalValue: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.accent,
  },
  withdrawButton: {
    backgroundColor: colors.accent,
    borderRadius: 12,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 16,
    marginBottom: 16,
  },
  withdrawButtonDisabled: {
    backgroundColor: '#9CA3AF',
  },
  withdrawButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
    marginLeft: 8,
  },
  infoContainer: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: '#F3F4F6',
    borderRadius: 8,
    padding: 12,
  },
  infoText: {
    flex: 1,
    fontSize: 12,
    color: colors.text.secondary,
    lineHeight: 16,
    marginLeft: 8,
  },
  errorContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#FEE2E2',
    borderRadius: 8,
    padding: 12,
    marginBottom: 16,
  },
  errorText: {
    flex: 1,
    fontSize: 12,
    color: colors.error,
    marginLeft: 8,
  },
});