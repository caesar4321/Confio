import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  StatusBar,
  SafeAreaView,
  TextInput,
  Alert,
  Modal,
} from 'react-native';
import { useNavigation, useRoute, RouteProp, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useMutation, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { MainStackParamList } from '../types/navigation';
import { CREATE_P2P_TRADE, GET_USER_BANK_ACCOUNTS, GET_MY_P2P_TRADES } from '../apollo/queries';
import { useCurrency } from '../hooks/useCurrency';
import { useAccount } from '../contexts/AccountContext';
import { getPaymentMethodIcon } from '../utils/paymentMethodIcons';

type TradeConfirmRouteProp = RouteProp<MainStackParamList, 'TradeConfirm'>;
type TradeConfirmNavigationProp = NativeStackNavigationProp<MainStackParamList, 'TradeConfirm'>;

export const TradeConfirmScreen: React.FC = () => {
  const navigation = useNavigation<TradeConfirmNavigationProp>();
  const route = useRoute<TradeConfirmRouteProp>();
  const { offer, crypto, tradeType } = route.params;
  
  // Currency formatting
  const { formatAmount } = useCurrency();
  
  // Account context
  const { activeAccount } = useAccount();
  
  // GraphQL queries and mutations
  const [createP2PTrade, { loading: createTradeLoading }] = useMutation(CREATE_P2P_TRADE, {
    refetchQueries: [
      {
        query: GET_MY_P2P_TRADES,
        variables: {}
      }
    ],
    // Don't wait for refetch to complete before navigating
    awaitRefetchQueries: false,
    // Optimistically update the cache
    update: (cache, { data }) => {
      if (data?.createP2pTrade?.success && data?.createP2pTrade?.trade) {
        // The refetchQueries will handle updating the trades list
        // We could also manually update the cache here if needed for instant updates
      }
    }
  });
  // Query user bank accounts for payment method validation
  const { 
    data: userBankAccountsData,
    refetch: refetchBankAccounts 
  } = useQuery(GET_USER_BANK_ACCOUNTS, {
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true
  });
  
  const [amount, setAmount] = useState('');
  const [selectedPaymentMethod, setSelectedPaymentMethod] = useState(offer.paymentMethods[0] || null);
  const [showPaymentModal, setShowPaymentModal] = useState(false);
  
  // Refetch bank accounts when screen comes into focus
  useFocusEffect(
    React.useCallback(() => {
      if (refetchBankAccounts && activeAccount?.id) {
        console.log('[TradeConfirmScreen] Screen focused, refetching bank accounts');
        refetchBankAccounts();
      }
    }, [refetchBankAccounts, activeAccount?.id])
  );
  
  // Auto-select first configured payment method when data loads
  React.useEffect(() => {
    if (userBankAccountsData?.userBankAccounts && offer.paymentMethods.length > 0) {
      // Check if current selection is configured
      if (selectedPaymentMethod && !isPaymentMethodConfigured(selectedPaymentMethod)) {
        // Find first configured payment method
        const firstConfigured = offer.paymentMethods.find(method => isPaymentMethodConfigured(method));
        if (firstConfigured) {
          setSelectedPaymentMethod(firstConfigured);
        }
      }
    }
  }, [userBankAccountsData, offer.paymentMethods]);
  
  // Check if user has configured a specific payment method
  const isPaymentMethodConfigured = (paymentMethod: any) => {
    if (!userBankAccountsData?.userBankAccounts) return false;
    
    return userBankAccountsData.userBankAccounts.some((account: any) => {
      // Check if user has this payment method configured
      if (account.paymentMethod?.id === paymentMethod.id) {
        // Additional validation for required fields
        if (paymentMethod.requiresPhone && !account.phoneNumber) return false;
        if (paymentMethod.requiresEmail && !account.email) return false;
        if (paymentMethod.requiresAccountNumber && !account.accountNumber) return false;
        return true;
      }
      // Legacy check for bank payment methods
      else if (paymentMethod.providerType === 'BANK' && account.bank?.id === paymentMethod.bank?.id) {
        return true;
      }
      return false;
    });
  };

  const handleBack = () => {
    navigation.goBack();
  };

  const handleConfirmTrade = async () => {
    if (!amount || !selectedPaymentMethod) {
      Alert.alert('Error', 'Por favor completa todos los campos');
      return;
    }
    
    const cryptoAmount = parseFloat(amount);
    if (isNaN(cryptoAmount) || cryptoAmount <= 0) {
      Alert.alert('Error', 'Por favor ingresa un monto válido');
      return;
    }
    
    // Check if user has configured the selected payment method
    if (!isPaymentMethodConfigured(selectedPaymentMethod)) {
      Alert.alert(
        'Método de pago no configurado',
        `No tienes configurado ${selectedPaymentMethod.displayName || selectedPaymentMethod.name}. ¿Deseas configurarlo ahora?`,
        [
          { text: 'Cancelar', style: 'cancel' },
          { 
            text: 'Configurar', 
            onPress: () => navigation.navigate('BankInfo'),
            style: 'default' 
          }
        ]
      );
      return;
    }
    
    try {
      // Create the trade in the database
      const { data } = await createP2PTrade({
        variables: {
          input: {
            offerId: offer.id,
            cryptoAmount: cryptoAmount,
            paymentMethodId: selectedPaymentMethod.id,
          },
        },
      });

      if (data?.createP2pTrade?.success) {
        const createdTrade = data.createP2pTrade.trade;
        
        // Navigate to TradeChatScreen with the actual trade data
        navigation.navigate('TradeChat', { 
          offer: offer,
          crypto: crypto,
          amount: amount,
          tradeType: tradeType,
          tradeId: createdTrade.id, // Pass the actual trade ID
          selectedPaymentMethodId: selectedPaymentMethod.id, // Pass the selected payment method ID
          tradeCountryCode: createdTrade.countryCode, // Pass trade's country code
          tradeCurrencyCode: createdTrade.currencyCode, // Pass trade's currency code
        });
      } else {
        const errorMessage = data?.createP2pTrade?.errors?.join(', ') || 'Error desconocido';
        Alert.alert('Error', errorMessage);
      }
    } catch (error) {
      console.error('Error creating trade:', error);
      Alert.alert('Error', 'Ocurrió un error al crear el intercambio. Por favor intenta de nuevo.');
    }
  };

  const handlePaymentMethodSelect = (method: any) => {
    setSelectedPaymentMethod(method);
    setShowPaymentModal(false);
  };

  const calculateTotal = () => {
    const numAmount = parseFloat(amount) || 0;
    const rate = parseFloat(offer.rate) || 0;
    return formatAmount.withCode(numAmount * rate);
  };

  const getPaymentMethodDescription = (method: any) => {
    if (!method) return 'Método de pago';
    const name = method.displayName || method.name || '';
    if (name.includes('Efectivo')) return 'Pago en efectivo';
    if (name.includes('Pago Móvil')) return 'Pago móvil';
    return 'Transferencia bancaria';
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="dark-content" backgroundColor="#fff" />
      
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity onPress={handleBack} style={styles.backButton}>
          <Icon name="arrow-left" size={24} color="#374151" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Confirmar Intercambio</Text>
        <View style={styles.placeholder} />
      </View>

      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        {/* Trade Summary */}
        <View style={styles.summaryCard}>
          <Text style={styles.summaryTitle}>Resumen del intercambio</Text>
          
          <View style={styles.summaryContent}>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Vas a comprar</Text>
              <View style={styles.amountInputContainer}>
                <TextInput
                  style={styles.amountInput}
                  value={amount}
                  onChangeText={setAmount}
                  keyboardType="numeric"
                  placeholder="0.00"
                  placeholderTextColor="#9CA3AF"
                />
                <Text style={styles.cryptoLabel}>{crypto}</Text>
              </View>
            </View>
            
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Pagarás</Text>
              <Text style={styles.totalAmount}>{calculateTotal()}</Text>
            </View>
            
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Tasa</Text>
              <Text style={styles.summaryValue}>{offer.rate} / {crypto}</Text>
            </View>
            
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Comerciante</Text>
              <View style={styles.traderInfo}>
                <Text style={styles.traderName}>{offer.name}</Text>
                {offer.verified && <Icon name="shield" size={16} color={colors.accent} style={styles.verifiedIcon} />}
              </View>
            </View>
          </View>
          
          {/* Warning */}
          <View style={styles.warningBox}>
            <Icon name="alert-triangle" size={20} color="#D97706" style={styles.warningIcon} />
            <View style={styles.warningContent}>
              <Text style={styles.warningTitle}>Importante</Text>
              <Text style={styles.warningText}>
                Solo procede si tienes los fondos listos para el pago inmediato. 
                Tienes 15 minutos para completar el pago.
              </Text>
            </View>
          </View>
        </View>
        
        {/* Payment Method Selection */}
        <View style={styles.paymentCard}>
          <Text style={styles.paymentTitle}>Método de pago seleccionado</Text>
          
          <View style={styles.paymentSelector}>
            <TouchableOpacity 
              style={styles.paymentDropdown}
              onPress={() => setShowPaymentModal(true)}
            >
              <Text style={styles.paymentDropdownText}>
                {selectedPaymentMethod?.displayName || selectedPaymentMethod?.name || 'Seleccionar método'}
              </Text>
              <Icon name="chevron-down" size={20} color="#6B7280" />
            </TouchableOpacity>
          </View>
          
          <View style={styles.paymentMethodContainer}>
            <View style={styles.paymentMethodIcon}>
              <Icon 
                name={getPaymentMethodIcon(selectedPaymentMethod?.icon, selectedPaymentMethod?.providerType, selectedPaymentMethod?.displayName || selectedPaymentMethod?.name)} 
                size={20} 
                color="#fff" 
              />
            </View>
            <View style={styles.paymentMethodInfo}>
              <View style={styles.paymentMethodHeader}>
                <Text style={styles.paymentMethodName}>
                  {selectedPaymentMethod?.displayName || selectedPaymentMethod?.name || 'Método de pago'}
                </Text>
                {selectedPaymentMethod?.bank?.country?.flagEmoji && (
                  <Text style={styles.countryFlag}>{selectedPaymentMethod.bank.country.flagEmoji}</Text>
                )}
              </View>
              <Text style={styles.paymentMethodDescription}>
                {getPaymentMethodDescription(selectedPaymentMethod)}
                {selectedPaymentMethod?.bank?.country?.name && ` • ${selectedPaymentMethod.bank.country.name}`}
              </Text>
            </View>
          </View>
        </View>
      </ScrollView>

      {/* Action Button */}
      <View style={styles.bottomButtonContainer}>
        <TouchableOpacity 
          style={[styles.confirmButton, createTradeLoading && styles.confirmButtonDisabled]} 
          onPress={handleConfirmTrade}
          disabled={createTradeLoading}
        >
          <Text style={styles.confirmButtonText}>
            {createTradeLoading ? 'Creando intercambio...' : 'Confirmar y Comenzar'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Payment Method Modal */}
      <Modal
        visible={showPaymentModal}
        transparent={true}
        animationType="fade"
        onRequestClose={() => setShowPaymentModal(false)}
      >
        <View style={styles.modalOverlay}>
          <TouchableOpacity 
            style={styles.modalBackdrop}
            activeOpacity={1}
            onPress={() => setShowPaymentModal(false)}
          />
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Seleccionar método de pago</Text>
              <TouchableOpacity onPress={() => setShowPaymentModal(false)}>
                <Icon name="x" size={24} color="#6B7280" />
              </TouchableOpacity>
            </View>
            <ScrollView style={styles.modalBody} showsVerticalScrollIndicator={false}>
              {offer.paymentMethods.map((method, index) => {
                const isConfigured = isPaymentMethodConfigured(method);
                return (
                  <TouchableOpacity
                    key={method.id || index}
                    style={[styles.paymentOption, !isConfigured && styles.paymentOptionDisabled]}
                    onPress={() => {
                      if (isConfigured) {
                        handlePaymentMethodSelect(method);
                      } else {
                        Alert.alert(
                          'Método de pago no configurado',
                          `Necesitas configurar ${method.displayName || method.name} antes de poder usarlo.`,
                          [
                            { text: 'Cancelar', style: 'cancel' },
                            { 
                              text: 'Configurar ahora', 
                              onPress: () => {
                                setShowPaymentModal(false);
                                navigation.navigate('BankInfo');
                              },
                              style: 'default' 
                            }
                          ]
                        );
                      }
                    }}
                  >
                    <View style={[styles.paymentOptionIcon, !isConfigured && styles.paymentOptionIconDisabled]}>
                      <Icon 
                        name={getPaymentMethodIcon(method.icon, method.providerType, method.displayName || method.name)} 
                        size={16} 
                        color={isConfigured ? "#fff" : "#9CA3AF"} 
                      />
                    </View>
                    <View style={styles.paymentOptionInfo}>
                      <View style={styles.paymentOptionHeader}>
                        <Text style={[styles.paymentOptionText, !isConfigured && styles.paymentOptionTextDisabled]}>
                          {method.displayName || method.name}
                        </Text>
                        {method.bank?.country?.flagEmoji && (
                          <Text style={styles.countryFlagSmall}>{method.bank.country.flagEmoji}</Text>
                        )}
                        {!isConfigured && (
                          <View style={styles.notConfiguredBadge}>
                            <Text style={styles.notConfiguredText}>No configurado</Text>
                          </View>
                        )}
                      </View>
                      <Text style={[styles.paymentOptionDescription, !isConfigured && styles.paymentOptionDescriptionDisabled]}>
                        {isConfigured ? getPaymentMethodDescription(method) : 'Toca para configurar este método de pago'}
                        {method.bank?.country?.name && ` • ${method.bank.country.name}`}
                      </Text>
                    </View>
                    {selectedPaymentMethod?.id === method.id && isConfigured && (
                      <Icon name="check" size={20} color={colors.primary} />
                    )}
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 16,
    backgroundColor: '#fff',
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 1,
    },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  backButton: {
    padding: 4,
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  placeholder: {
    width: 32,
  },
  content: {
    flex: 1,
    padding: 16,
  },
  summaryCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 1,
    },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  summaryTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 16,
  },
  summaryContent: {
    marginBottom: 24,
  },
  summaryRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  summaryLabel: {
    fontSize: 16,
    color: '#6B7280',
  },
  amountInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  amountInput: {
    width: 96,
    textAlign: 'right',
    fontSize: 18,
    fontWeight: 'bold',
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 8,
    paddingHorizontal: 8,
    paddingVertical: 4,
    marginRight: 8,
  },
  cryptoLabel: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  totalAmount: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.primary,
  },
  summaryValue: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  traderInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  traderName: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
    marginRight: 8,
  },
  verifiedIcon: {
    marginLeft: 4,
  },
  warningBox: {
    backgroundColor: '#FEF3C7',
    borderRadius: 8,
    padding: 12,
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  warningIcon: {
    marginRight: 8,
    marginTop: 2,
  },
  warningContent: {
    flex: 1,
  },
  warningTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#92400E',
    marginBottom: 4,
  },
  warningText: {
    fontSize: 14,
    color: '#92400E',
    lineHeight: 20,
  },
  paymentCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 1,
    },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  paymentTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 12,
  },
  paymentSelector: {
    marginBottom: 12,
  },
  paymentDropdown: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 12,
    marginBottom: 12,
  },
  paymentDropdownText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  paymentMethodContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F9FAFB',
    borderRadius: 8,
    padding: 12,
  },
  paymentMethodIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.accent,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  paymentMethodIconText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
  },
  paymentMethodInfo: {
    flex: 1,
  },
  paymentMethodHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 2,
  },
  paymentMethodName: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
    marginRight: 8,
  },
  paymentMethodDescription: {
    fontSize: 14,
    color: '#6B7280',
  },
  countryFlag: {
    fontSize: 18,
  },
  countryFlagSmall: {
    fontSize: 16,
    marginLeft: 4,
  },
  bottomButtonContainer: {
    backgroundColor: '#fff',
    padding: 16,
    borderTopWidth: 1,
    borderTopColor: '#E5E7EB',
  },
  confirmButton: {
    backgroundColor: colors.primary,
    paddingVertical: 12,
    borderRadius: 12,
    alignItems: 'center',
  },
  confirmButtonDisabled: {
    backgroundColor: '#9CA3AF',
  },
  confirmButtonText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
  },
  modalOverlay: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalBackdrop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
  },
  modalContent: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    width: '85%',
    maxHeight: '70%',
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 4,
    },
    shadowOpacity: 0.25,
    shadowRadius: 8,
    elevation: 8,
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 16,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  modalBody: {
    maxHeight: 300,
  },
  paymentOption: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#F3F4F6',
  },
  paymentOptionDisabled: {
    opacity: 0.6,
  },
  paymentOptionIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.accent,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  paymentOptionIconDisabled: {
    backgroundColor: '#E5E7EB',
  },
  paymentOptionIconText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
  },
  paymentOptionInfo: {
    flex: 1,
  },
  paymentOptionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 2,
  },
  paymentOptionText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  paymentOptionTextDisabled: {
    color: '#9CA3AF',
  },
  paymentOptionDescription: {
    fontSize: 14,
    color: '#6B7280',
  },
  paymentOptionDescriptionDisabled: {
    color: '#D1D5DB',
  },
  notConfiguredBadge: {
    backgroundColor: '#FEF3C7',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
    marginLeft: 8,
  },
  notConfiguredText: {
    fontSize: 11,
    fontWeight: '600',
    color: '#92400E',
  },
}); 