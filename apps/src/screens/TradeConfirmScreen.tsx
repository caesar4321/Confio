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
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useMutation } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { MainStackParamList } from '../types/navigation';
import { CREATE_P2P_TRADE } from '../apollo/queries';
import { useCurrency } from '../hooks/useCurrency';
import { useAccount } from '../contexts/AccountContext';

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
  
  // GraphQL mutation
  const [createP2PTrade, { loading: createTradeLoading }] = useMutation(CREATE_P2P_TRADE);
  
  const [amount, setAmount] = useState('');
  const [selectedPaymentMethod, setSelectedPaymentMethod] = useState(offer.paymentMethods[0] || null);
  const [showPaymentModal, setShowPaymentModal] = useState(false);

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
    
    try {
      // Create the trade in the database
      const { data } = await createP2PTrade({
        variables: {
          input: {
            offerId: offer.id,
            cryptoAmount: cryptoAmount,
            paymentMethodId: selectedPaymentMethod.id,
            accountId: activeAccount?.id, // Pass the current account ID
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
              <Text style={styles.paymentMethodIconText}>
                {(selectedPaymentMethod?.displayName || selectedPaymentMethod?.name || 'M').charAt(0)}
              </Text>
            </View>
            <View style={styles.paymentMethodInfo}>
              <Text style={styles.paymentMethodName}>
                {selectedPaymentMethod?.displayName || selectedPaymentMethod?.name || 'Método de pago'}
              </Text>
              <Text style={styles.paymentMethodDescription}>
                {getPaymentMethodDescription(selectedPaymentMethod)}
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
              {offer.paymentMethods.map((method, index) => (
                <TouchableOpacity
                  key={method.id || index}
                  style={styles.paymentOption}
                  onPress={() => handlePaymentMethodSelect(method)}
                >
                  <View style={styles.paymentOptionIcon}>
                    <Text style={styles.paymentOptionIconText}>
                      {(method.displayName || method.name || 'M').charAt(0)}
                    </Text>
                  </View>
                  <View style={styles.paymentOptionInfo}>
                    <Text style={styles.paymentOptionText}>
                      {method.displayName || method.name}
                    </Text>
                    <Text style={styles.paymentOptionDescription}>
                      {getPaymentMethodDescription(method)}
                    </Text>
                  </View>
                  {selectedPaymentMethod?.id === method.id && (
                    <Icon name="check" size={20} color={colors.primary} />
                  )}
                </TouchableOpacity>
              ))}
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
  paymentMethodName: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
    marginBottom: 2,
  },
  paymentMethodDescription: {
    fontSize: 14,
    color: '#6B7280',
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
  paymentOptionIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.accent,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  paymentOptionIconText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
  },
  paymentOptionInfo: {
    flex: 1,
  },
  paymentOptionText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  paymentOptionDescription: {
    fontSize: 14,
    color: '#6B7280',
  },
}); 