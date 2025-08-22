import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  ScrollView,
  Platform,
  Alert,
  Modal,
  FlatList,
  SafeAreaView,
  StatusBar,
} from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Feather';
import { useMutation, useQuery } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { CREATE_P2P_OFFER, UPDATE_P2P_OFFER, GET_P2P_PAYMENT_METHODS, GET_USER_BANK_ACCOUNTS } from '../apollo/queries';
import { countries, Country } from '../utils/countries';
import { useCountrySelection } from '../hooks/useCountrySelection';
import { useCurrency } from '../hooks/useCurrency';
import { useAccount } from '../contexts/AccountContext';
import { getPaymentMethodIcon } from '../utils/paymentMethodIcons';
import { useNumberFormat } from '../utils/numberFormatting';

// Colors from the design
const colors = {
  primary: '#34d399', // emerald-400
  primaryText: '#34d399',
  primaryLight: '#d1fae5', // emerald-100
  primaryDark: '#10b981', // emerald-500
  secondary: '#8b5cf6', // violet-500
  secondaryText: '#8b5cf6',
  accent: '#3b82f6', // blue-500
  accentText: '#3b82f6',
  neutral: '#f9fafb', // gray-50
  neutralDark: '#f3f4f6', // gray-100
  dark: '#111827', // gray-900
};

type PaymentMethod = {
  id: string;
  name: string;
  displayName: string;
  icon: string;
  isActive: boolean;
};

export const CreateOfferScreen = () => {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const route = useRoute<RouteProp<MainStackParamList, 'CreateOffer'>>();
  
  // Check if we're in edit mode
  const editMode = route.params?.editMode || false;
  const offerId = route.params?.offerId;
  const offerData = route.params?.offerData;
  
  // Use centralized country selection hook
  const { selectedCountry, showCountryModal, selectCountry, openCountryModal, closeCountryModal } = useCountrySelection();
  
  // Use currency system based on selected country
  const { currency, formatAmount, inputFormatting } = useCurrency();
  
  // Use number formatting based on user's locale
  const { formatNumber } = useNumberFormat();
  
  // Get current account context
  const { activeAccount } = useAccount();
  
  // GraphQL queries and mutations
  const { data: paymentMethodsData, loading: paymentMethodsLoading, error: paymentMethodsError } = useQuery(GET_P2P_PAYMENT_METHODS, {
    variables: { 
      countryCode: selectedCountry?.[2]
    },
    skip: !selectedCountry,
    fetchPolicy: 'cache-and-network', // Use cache but also fetch fresh data
    errorPolicy: 'all'
  });
  
  // Fetch user's registered payment methods
  const { data: userBankAccountsData, loading: userBankAccountsLoading } = useQuery(GET_USER_BANK_ACCOUNTS, {
    fetchPolicy: 'cache-and-network'
  });
  
  const [createOffer, { loading: createOfferLoading }] = useMutation(CREATE_P2P_OFFER);
  const [updateOffer, { loading: updateOfferLoading }] = useMutation(UPDATE_P2P_OFFER);
  
  // Apollo will automatically refetch when variables change, no manual refetch needed
  // Removed manual refetch to prevent conflicts with other screens

  // Initialize state with offer data if in edit mode
  const [exchangeType, setExchangeType] = useState<'BUY' | 'SELL'>(
    editMode && offerData ? offerData.exchangeType : 'SELL'
  );
  const [tokenType, setTokenType] = useState<'cUSD' | 'CONFIO'>(
    editMode && offerData ? (offerData.tokenType === 'CUSD' ? 'cUSD' : offerData.tokenType) : 'cUSD'
  );
  const [rate, setRate] = useState(editMode && offerData ? offerData.rate.toString() : '');
  const [minAmount, setMinAmount] = useState(editMode && offerData ? offerData.minAmount.toString() : '');
  const [maxAmount, setMaxAmount] = useState(editMode && offerData ? offerData.maxAmount.toString() : '');
  const [terms, setTerms] = useState(editMode && offerData ? (offerData.terms || '') : '');
  const [selectedPaymentMethods, setSelectedPaymentMethods] = useState<string[]>([]);

  // Get user's registered payment method IDs
  const registeredPaymentMethodIds = new Set(
    userBankAccountsData?.userBankAccounts?.map((account: any) => account.paymentMethod?.id) || []
  );

  // Filter payment methods to only show registered ones
  const allPaymentMethods: PaymentMethod[] = paymentMethodsData?.p2pPaymentMethods || [];
  const registeredPaymentMethods = allPaymentMethods.filter(method => 
    registeredPaymentMethodIds.has(method.id)
  );
  const unregisteredPaymentMethods = allPaymentMethods.filter(method => 
    !registeredPaymentMethodIds.has(method.id)
  );
  
  // Debug payment methods
  React.useEffect(() => {
    if (paymentMethodsData?.p2pPaymentMethods) {
      console.log('[CreateOfferScreen] Available payment methods for', selectedCountry?.[0], ':', 
        paymentMethodsData.p2pPaymentMethods.map((m: any) => ({
          id: m.id,
          name: m.displayName,
          isActive: m.isActive,
          bank: m.bank?.name
        }))
      );
    }
  }, [paymentMethodsData, selectedCountry]);
  
  // Set selected payment methods when in edit mode
  React.useEffect(() => {
    if (editMode && offerData?.paymentMethods && !selectedPaymentMethods.length) {
      const methodIds = offerData.paymentMethods.map((method: any) => method.id);
      setSelectedPaymentMethods(methodIds);
    }
  }, [editMode, offerData]);
  
  // Set country when in edit mode
  React.useEffect(() => {
    if (editMode && offerData?.countryCode) {
      const country = countries.find(c => c[2] === offerData.countryCode);
      if (country) {
        selectCountry(country);
      }
    }
  }, [editMode, offerData?.countryCode, selectCountry]);
  


  const togglePaymentMethod = (methodId: string) => {
    setSelectedPaymentMethods(prev => 
      prev.includes(methodId) 
        ? prev.filter(id => id !== methodId)
        : [...prev, methodId]
    );
  };

  const validateForm = () => {
    if (!rate || parseFloat(rate) <= 0) {
      Alert.alert('Error', 'Por favor ingresa una tasa válida');
      return false;
    }
    if (!minAmount || parseFloat(minAmount) <= 0) {
      Alert.alert('Error', 'Por favor ingresa un monto mínimo válido');
      return false;
    }
    if (!maxAmount || parseFloat(maxAmount) <= 0) {
      Alert.alert('Error', 'Por favor ingresa un monto máximo válido');
      return false;
    }
    if (parseFloat(minAmount) > parseFloat(maxAmount)) {
      Alert.alert('Error', 'El monto mínimo no puede ser mayor al máximo');
      return false;
    }
    if (selectedPaymentMethods.length === 0) {
      Alert.alert('Error', 'Por favor selecciona al menos un método de pago');
      return false;
    }
    // Ensure only registered payment methods are selected
    const selectedRegisteredMethods = selectedPaymentMethods.filter(id => 
      registeredPaymentMethodIds.has(id)
    );
    if (selectedRegisteredMethods.length === 0) {
      Alert.alert('Error', 'Debes seleccionar al menos un método de pago que tengas registrado');
      return false;
    }
    if (selectedRegisteredMethods.length !== selectedPaymentMethods.length) {
      Alert.alert('Error', 'Solo puedes incluir métodos de pago que tengas registrados');
      return false;
    }
    if (!selectedCountry) {
      Alert.alert('Error', 'Por favor selecciona un país de operación');
      return false;
    }
    return true;
  };

  const handleCreateOffer = async () => {
    if (!validateForm()) return;

    try {
      if (editMode) {
        // Update existing offer
        const { data } = await updateOffer({
          variables: {
            offerId: offerId,
            rate: parseFloat(rate),
            minAmount: parseFloat(minAmount),
            maxAmount: parseFloat(maxAmount),
            paymentMethodIds: selectedPaymentMethods,
            terms: terms.trim(),
          },
        });
        
        if (data?.updateP2pOffer?.success) {
          Alert.alert(
            'Éxito',
            'Tu oferta ha sido actualizada exitosamente',
            [
              {
                text: 'Ver Mis Ofertas',
                onPress: () => {
                  // Navigate back to ExchangeScreen and show user's offers
                  navigation.navigate('BottomTabs', { 
                    screen: 'Exchange', 
                    params: { showMyOffers: true, refreshData: true } 
                  });
                },
              },
            ]
          );
        } else {
          const errorMessage = data?.updateP2pOffer?.errors?.join(', ') || 'Error desconocido';
          Alert.alert('Error', errorMessage);
        }
      } else {
        // Create new offer
        const { data } = await createOffer({
          variables: {
            input: {
              exchangeType,
              tokenType,
              rate: parseFloat(rate),
              minAmount: parseFloat(minAmount),
              maxAmount: parseFloat(maxAmount),
              paymentMethodIds: selectedPaymentMethods,
              countryCode: selectedCountry?.[2], // Pass the country code
              terms: terms.trim(),
            },
          },
        });

        if (data?.createP2pOffer?.success) {
          Alert.alert(
            'Éxito',
            'Tu oferta ha sido creada exitosamente',
            [
              {
                text: 'Ver Mis Ofertas',
                onPress: () => {
                  // Navigate back to ExchangeScreen and show user's offers
                  navigation.navigate('BottomTabs', { 
                    screen: 'Exchange', 
                    params: { showMyOffers: true, refreshData: true } 
                  });
                },
              },
              {
                text: 'Continuar',
                onPress: () => {
                  // Navigate back and trigger refresh
                  navigation.navigate('BottomTabs', { 
                    screen: 'Exchange', 
                    params: { refreshData: true } 
                  });
                },
                style: 'cancel'
              },
            ]
          );
        } else {
          const errorMessage = data?.createP2pOffer?.errors?.join(', ') || 'Error desconocido';
          Alert.alert('Error', errorMessage);
        }
      }
    } catch (error) {
      console.error('Error creating/updating offer:', error);
      Alert.alert('Error', `Ocurrió un error al ${editMode ? 'actualizar' : 'crear'} la oferta. Por favor intenta de nuevo.`);
    }
  };
  
  const handleDeleteOffer = async () => {
    Alert.alert(
      'Eliminar Oferta',
      '¿Estás seguro de que deseas eliminar esta oferta? Esta acción no se puede deshacer.',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Eliminar',
          style: 'destructive',
          onPress: async () => {
            try {
              const { data } = await updateOffer({
                variables: {
                  offerId: offerId,
                  status: 'CANCELLED',
                },
              });
              
              if (data?.updateP2pOffer?.success) {
                Alert.alert(
                  'Oferta Eliminada',
                  'Tu oferta ha sido eliminada exitosamente',
                  [
                    {
                      text: 'OK',
                      onPress: () => {
                        navigation.navigate('BottomTabs', { 
                          screen: 'Exchange', 
                          params: { showMyOffers: true, refreshData: true } 
                        });
                      },
                    },
                  ]
                );
              } else {
                Alert.alert('Error', 'No se pudo eliminar la oferta');
              }
            } catch (error) {
              Alert.alert('Error', 'No se pudo eliminar la oferta');
            }
          },
        },
      ]
    );
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="dark-content" backgroundColor="#fff" />
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity 
          style={styles.backButton}
          onPress={() => navigation.goBack()}
        >
          <Icon name="arrow-left" size={24} color="#1F2937" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>{editMode ? 'Editar Oferta' : 'Crear Oferta'}</Text>
        <View style={styles.placeholder} />
      </View>

      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        {/* Exchange Type */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Tipo de operación</Text>
          <View style={[styles.toggleContainer, editMode && styles.disabledContainer]}>
            <TouchableOpacity
              style={[styles.toggleButton, exchangeType === 'BUY' && styles.toggleButtonActive]}
              onPress={() => !editMode && setExchangeType('BUY')}
              disabled={editMode}
            >
              <Text style={[styles.toggleButtonText, exchangeType === 'BUY' && styles.toggleButtonTextActive]}>
                Comprar
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.toggleButton, exchangeType === 'SELL' && styles.toggleButtonActive]}
              onPress={() => !editMode && setExchangeType('SELL')}
              disabled={editMode}
            >
              <Text style={[styles.toggleButtonText, exchangeType === 'SELL' && styles.toggleButtonTextActive]}>
                Vender
              </Text>
            </TouchableOpacity>
          </View>
          <Text style={styles.helpText}>
            {editMode ? 'El tipo de operación no se puede cambiar' :
              (exchangeType === 'BUY' 
                ? 'Quieres comprar monedas digitales (pagarás con bolívares)'
                : 'Quieres vender monedas digitales (recibirás bolívares)')
            }
          </Text>
        </View>

        {/* Country Selection */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>País de operación</Text>
          <TouchableOpacity
            style={[styles.countrySelector, editMode && styles.disabledInput]}
            onPress={() => !editMode && openCountryModal()}
            disabled={editMode}
          >
            <View style={styles.countryDisplay}>
              <Text style={styles.countryFlag}>{selectedCountry?.[3] || '🌍'}</Text>
              <Text style={styles.countryName}>
                {selectedCountry?.[0] || 'Seleccionar país'}
              </Text>
            </View>
            <Icon name="chevron-down" size={20} color={editMode ? "#D1D5DB" : "#6B7280"} />
          </TouchableOpacity>
          <Text style={styles.helpText}>
            {editMode ? 'El país no se puede cambiar' : 'País donde operarás y recibirás pagos locales'}
          </Text>
        </View>

        {/* Token Type */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Moneda digital</Text>
          <View style={[styles.toggleContainer, editMode && styles.disabledContainer]}>
            <TouchableOpacity
              style={[styles.toggleButton, tokenType === 'cUSD' && styles.toggleButtonActive]}
              onPress={() => !editMode && setTokenType('cUSD')}
              disabled={editMode}
            >
              <Text style={[styles.toggleButtonText, tokenType === 'cUSD' && styles.toggleButtonTextActive]}>
                Confío Dollar ($cUSD)
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.toggleButton, tokenType === 'CONFIO' && styles.toggleButtonActive]}
              onPress={() => !editMode && setTokenType('CONFIO')}
              disabled={editMode}
            >
              <Text style={[styles.toggleButtonText, tokenType === 'CONFIO' && styles.toggleButtonTextActive]}>
                Confío ($CONFIO)
              </Text>
            </TouchableOpacity>
          </View>
          <Text style={styles.helpText}>
            {editMode && 'La moneda digital no se puede cambiar'}
          </Text>
        </View>

        {/* Rate */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Tasa de cambio ({currency.code} por {tokenType})</Text>
          <View style={styles.inputContainer}>
            <TextInput
              style={styles.textInput}
              value={rate}
              onChangeText={setRate}
              placeholder={inputFormatting.getPlaceholder(35.50)}
              keyboardType="decimal-pad"
            />
            <Text style={styles.inputSuffix}>{currency.code}</Text>
          </View>
        </View>

        {/* Amount Limits */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Límites por operación</Text>
          <View style={styles.row}>
            <View style={styles.halfInputContainer}>
              <Text style={styles.inputLabel}>Mínimo</Text>
              <View style={styles.inputContainer}>
                <TextInput
                  style={styles.textInput}
                  value={minAmount}
                  onChangeText={setMinAmount}
                  placeholder="100.00"
                  keyboardType="decimal-pad"
                />
                <Text style={styles.inputSuffix}>{tokenType}</Text>
              </View>
            </View>
            <View style={styles.halfInputContainer}>
              <Text style={styles.inputLabel}>Máximo</Text>
              <View style={styles.inputContainer}>
                <TextInput
                  style={styles.textInput}
                  value={maxAmount}
                  onChangeText={setMaxAmount}
                  placeholder="1,000.00"
                  keyboardType="decimal-pad"
                />
                <Text style={styles.inputSuffix}>{tokenType}</Text>
              </View>
            </View>
          </View>
        </View>

        {/* Removed 'Cantidad disponible' — availability checked at escrow enable time */}

        {/* Payment Methods */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Métodos de pago</Text>
          {paymentMethodsLoading || userBankAccountsLoading ? (
            <Text style={styles.helpText}>Cargando métodos de pago...</Text>
          ) : paymentMethodsError ? (
            <Text style={styles.helpText}>Error cargando métodos de pago: {paymentMethodsError.message}</Text>
          ) : allPaymentMethods.length === 0 ? (
            <Text style={styles.helpText}>No hay métodos de pago disponibles</Text>
          ) : (
            <>
              {/* Registered Payment Methods */}
              {registeredPaymentMethods.length > 0 && (
                <>
                  <Text style={styles.subsectionTitle}>Métodos de pago registrados</Text>
                  <View style={styles.paymentMethodsContainer}>
                    {registeredPaymentMethods.map((method) => (
                      <TouchableOpacity
                        key={method.id}
                        style={[
                          styles.paymentMethodItem,
                          selectedPaymentMethods.includes(method.id) && styles.paymentMethodItemSelected
                        ]}
                        onPress={() => togglePaymentMethod(method.id)}
                      >
                        <View style={styles.paymentMethodIcon}>
                          <Icon 
                            name={getPaymentMethodIcon(method.icon, method.providerType, method.displayName)} 
                            size={16} 
                            color="#fff" 
                          />
                        </View>
                        <Text style={styles.paymentMethodName}>{method.displayName}</Text>
                        {selectedPaymentMethods.includes(method.id) && (
                          <Icon name="check" size={20} color={colors.primary} />
                        )}
                      </TouchableOpacity>
                    ))}
                  </View>
                </>
              )}
              
              {/* Unregistered Payment Methods */}
              {unregisteredPaymentMethods.length > 0 && (
                <>
                  <Text style={[styles.subsectionTitle, { marginTop: registeredPaymentMethods.length > 0 ? 16 : 0 }]}>
                    Métodos no registrados
                  </Text>
                  <Text style={styles.helpText}>
                    Para incluir estos métodos en tu oferta, primero debes registrarlos en tu perfil.
                  </Text>
                  <View style={[styles.paymentMethodsContainer, { opacity: 0.5 }]}>
                    {unregisteredPaymentMethods.map((method) => (
                      <TouchableOpacity
                        key={method.id}
                        style={styles.paymentMethodItem}
                        onPress={() => {
                          Alert.alert(
                            'Método no registrado',
                            `Debes registrar ${method.displayName} en tu perfil antes de poder incluirlo en tu oferta.`,
                            [
                              { text: 'Cancelar', style: 'cancel' },
                              {
                                text: 'Ir a Métodos de Pago',
                                onPress: () => navigation.navigate('BankInfo')
                              }
                            ]
                          );
                        }}
                      >
                        <View style={styles.paymentMethodIcon}>
                          <Icon 
                            name={getPaymentMethodIcon(method.icon, method.providerType, method.displayName)} 
                            size={16} 
                            color="#fff" 
                          />
                        </View>
                        <Text style={styles.paymentMethodName}>{method.displayName}</Text>
                        <Icon name="lock" size={16} color="#9CA3AF" />
                      </TouchableOpacity>
                    ))}
                  </View>
                </>
              )}
              
              {/* No registered methods message */}
              {registeredPaymentMethods.length === 0 && (
                <View style={styles.noMethodsContainer}>
                  <Icon name="alert-circle" size={48} color={colors.warning} />
                  <Text style={styles.noMethodsTitle}>No tienes métodos de pago registrados</Text>
                  <Text style={styles.noMethodsText}>
                    Debes registrar al menos un método de pago antes de crear una oferta.
                  </Text>
                  <TouchableOpacity
                    style={styles.registerButton}
                    onPress={() => navigation.navigate('BankInfo')}
                  >
                    <Icon name="credit-card" size={20} color="#fff" />
                    <Text style={styles.registerButtonText}>Registrar Métodos de Pago</Text>
                  </TouchableOpacity>
                </View>
              )}
            </>
          )}
        </View>


        {/* Terms */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Términos y condiciones (opcional)</Text>
          <TextInput
            style={styles.textArea}
            value={terms}
            onChangeText={setTerms}
            placeholder="Describe cualquier requerimiento especial o instrucciones..."
            multiline
            numberOfLines={4}
            textAlignVertical="top"
          />
        </View>

        {/* Create/Update Button */}
        <TouchableOpacity
          style={[styles.createButton, (createOfferLoading || updateOfferLoading) && styles.createButtonDisabled]}
          onPress={handleCreateOffer}
          disabled={createOfferLoading || updateOfferLoading}
        >
          <Text style={styles.createButtonText}>
            {(createOfferLoading || updateOfferLoading) 
              ? (editMode ? 'Actualizando...' : 'Creando...')
              : (editMode ? 'Actualizar Oferta' : 'Crear Oferta')
            }
          </Text>
        </TouchableOpacity>
        
        {/* Delete Button (only in edit mode) */}
        {editMode && (
          <TouchableOpacity
            style={[styles.deleteButton, updateOfferLoading && styles.deleteButtonDisabled]}
            onPress={handleDeleteOffer}
            disabled={updateOfferLoading}
          >
            <Icon name="trash-2" size={20} color="#EF4444" />
            <Text style={styles.deleteButtonText}>Eliminar Oferta</Text>
          </TouchableOpacity>
        )}
      </ScrollView>

      {/* Country Selection Modal */}
      <Modal
        animationType="slide"
        transparent={false}
        visible={showCountryModal}
        onRequestClose={closeCountryModal}
      >
        <View style={styles.modalContainer}>
          <View style={styles.modalHeader}>
            <TouchableOpacity onPress={closeCountryModal}>
              <Icon name="x" size={24} color="#1F2937" />
            </TouchableOpacity>
            <Text style={styles.modalTitle}>Seleccionar País</Text>
            <View style={styles.placeholder} />
          </View>
          <FlatList
            data={countries}
            keyExtractor={(item, index) => `${item[2]}-${index}`}
            renderItem={({ item }) => (
              <TouchableOpacity
                style={[
                  styles.countryItem,
                  selectedCountry?.[2] === item[2] && styles.countryItemSelected
                ]}
                onPress={() => selectCountry(item)}
              >
                <Text style={styles.countryFlag}>{item[3]}</Text>
                <Text style={styles.countryItemName}>{item[0]}</Text>
                <Text style={styles.countryCode}>{item[1]}</Text>
                {selectedCountry?.[2] === item[2] && (
                  <Icon name="check" size={20} color={colors.primary} />
                )}
              </TouchableOpacity>
            )}
            showsVerticalScrollIndicator={false}
          />
        </View>
      </Modal>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  subsectionTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6B7280',
    marginBottom: 8,
  },
  noMethodsContainer: {
    alignItems: 'center',
    paddingVertical: 32,
    paddingHorizontal: 16,
    backgroundColor: '#FEF3C7',
    borderRadius: 12,
  },
  noMethodsTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#92400E',
    marginTop: 12,
    marginBottom: 8,
  },
  noMethodsText: {
    fontSize: 14,
    color: '#92400E',
    textAlign: 'center',
    marginBottom: 16,
  },
  registerButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primary,
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 8,
    gap: 8,
  },
  registerButtonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 14,
  },
  warning: '#f59e0b',
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 16,
    backgroundColor: '#fff',
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
  },
  backButton: {
    padding: 8,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  placeholder: {
    width: 40,
  },
  content: {
    flex: 1,
    padding: 16,
  },
  section: {
    marginBottom: 24,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 12,
  },
  toggleContainer: {
    flexDirection: 'row',
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    padding: 4,
  },
  toggleButton: {
    flex: 1,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 8,
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
    color: '#fff',
  },
  helpText: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 8,
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    paddingHorizontal: 12,
    minHeight: 48,
  },
  textInput: {
    flex: 1,
    fontSize: 16,
    color: '#1F2937',
    paddingVertical: 0,
  },
  inputSuffix: {
    fontSize: 14,
    fontWeight: '500',
    color: '#6B7280',
    marginLeft: 8,
  },
  row: {
    flexDirection: 'row',
    gap: 12,
  },
  halfInputContainer: {
    flex: 1,
  },
  inputLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: '#6B7280',
    marginBottom: 8,
  },
  textArea: {
    backgroundColor: '#fff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    padding: 12,
    fontSize: 16,
    color: '#1F2937',
    minHeight: 100,
    maxHeight: 150,
  },
  paymentMethodsContainer: {
    gap: 8,
  },
  paymentMethodItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.neutral,
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  paymentMethodItemSelected: {
    borderColor: colors.primary,
    backgroundColor: colors.primaryLight,
  },
  paymentMethodIcon: {
    width: 32,
    height: 32,
    borderRadius: 8,
    backgroundColor: colors.accent,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  paymentMethodIconText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 14,
  },
  paymentMethodName: {
    flex: 1,
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  createButton: {
    backgroundColor: colors.primary,
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginBottom: 32,
  },
  createButtonDisabled: {
    backgroundColor: '#9CA3AF',
  },
  createButtonText: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#fff',
  },
  deleteButton: {
    flexDirection: 'row',
    backgroundColor: '#FEE2E2',
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 32,
    gap: 8,
  },
  deleteButtonDisabled: {
    backgroundColor: '#F3F4F6',
  },
  deleteButtonText: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#EF4444',
  },
  disabledContainer: {
    opacity: 0.6,
  },
  disabledInput: {
    backgroundColor: '#F9FAFB',
    opacity: 0.7,
  },
  countrySelector: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#fff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    paddingHorizontal: 12,
    minHeight: 48,
  },
  countryDisplay: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  countryFlag: {
    fontSize: 24,
    marginRight: 12,
  },
  countryName: {
    fontSize: 16,
    color: '#1F2937',
    flex: 1,
  },
  modalContainer: {
    flex: 1,
    backgroundColor: '#fff',
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: Platform.OS === 'ios' ? 50 : 20,
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  countryItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#F3F4F6',
  },
  countryItemSelected: {
    backgroundColor: colors.primaryLight,
  },
  countryItemName: {
    fontSize: 16,
    color: '#1F2937',
    flex: 1,
    marginLeft: 12,
  },
  countryCode: {
    fontSize: 14,
    color: '#6B7280',
    marginRight: 8,
  },
});
