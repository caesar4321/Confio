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
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Feather';
import { useMutation, useQuery } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { CREATE_P2P_OFFER, GET_P2P_PAYMENT_METHODS, GET_ME } from '../apollo/queries';
import { countries, Country, getCountryByPhoneCode } from '../utils/countries';

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
  
  // GraphQL queries and mutations
  const { data: userData } = useQuery(GET_ME);
  const { data: paymentMethodsData, loading: paymentMethodsLoading } = useQuery(GET_P2P_PAYMENT_METHODS);
  const [createOffer, { loading: createOfferLoading }] = useMutation(CREATE_P2P_OFFER);
  
  // Smart country defaulting based on user's phone country
  const getDefaultCountry = (): Country | null => {
    if (userData?.me?.phoneCountry) {
      const countryByPhone = getCountryByPhoneCode(userData.me.phoneCountry);
      if (countryByPhone) return countryByPhone;
    }
    // Fallback to Venezuela if no phone country or not found
    return countries.find(c => c[0] === 'Venezuela') || null;
  };

  const [exchangeType, setExchangeType] = useState<'BUY' | 'SELL'>('SELL');
  const [tokenType, setTokenType] = useState<'cUSD' | 'CONFIO'>('cUSD');
  const [rate, setRate] = useState('');
  const [minAmount, setMinAmount] = useState('');
  const [maxAmount, setMaxAmount] = useState('');
  const [availableAmount, setAvailableAmount] = useState('');
  const [terms, setTerms] = useState('');
  const [responseTime, setResponseTime] = useState('15');
  const [selectedPaymentMethods, setSelectedPaymentMethods] = useState<string[]>([]);
  const [selectedCountry, setSelectedCountry] = useState<Country | null>(getDefaultCountry());
  const [showCountryModal, setShowCountryModal] = useState(false);

  const paymentMethods: PaymentMethod[] = paymentMethodsData?.p2pPaymentMethods || [];

  // Update country when user data loads
  useEffect(() => {
    if (userData?.me?.phoneCountry) {
      const countryByPhone = getCountryByPhoneCode(userData.me.phoneCountry);
      if (countryByPhone && !selectedCountry) {
        setSelectedCountry(countryByPhone);
      }
    }
  }, [userData?.me?.phoneCountry]);

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
    if (!availableAmount || parseFloat(availableAmount) <= 0) {
      Alert.alert('Error', 'Por favor ingresa un monto disponible válido');
      return false;
    }
    if (parseFloat(availableAmount) < parseFloat(minAmount)) {
      Alert.alert('Error', 'El monto disponible no puede ser menor al mínimo');
      return false;
    }
    if (selectedPaymentMethods.length === 0) {
      Alert.alert('Error', 'Por favor selecciona al menos un método de pago');
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
      const { data } = await createOffer({
        variables: {
          input: {
            exchangeType,
            tokenType,
            rate: parseFloat(rate),
            minAmount: parseFloat(minAmount),
            maxAmount: parseFloat(maxAmount),
            availableAmount: parseFloat(availableAmount),
            paymentMethodIds: selectedPaymentMethods,
            terms: terms.trim(),
            responseTimeMinutes: parseInt(responseTime),
          },
        },
      });

      if (data?.createP2pOffer?.success) {
        Alert.alert(
          'Éxito',
          'Tu oferta ha sido creada exitosamente',
          [
            {
              text: 'OK',
              onPress: () => navigation.goBack(),
            },
          ]
        );
      } else {
        const errorMessage = data?.createP2pOffer?.errors?.join(', ') || 'Error desconocido';
        Alert.alert('Error', errorMessage);
      }
    } catch (error) {
      console.error('Error creating offer:', error);
      Alert.alert('Error', 'Ocurrió un error al crear la oferta. Por favor intenta de nuevo.');
    }
  };

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity 
          style={styles.backButton}
          onPress={() => navigation.goBack()}
        >
          <Icon name="arrow-left" size={24} color="#1F2937" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Crear Oferta</Text>
        <View style={styles.placeholder} />
      </View>

      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        {/* Exchange Type */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Tipo de operación</Text>
          <View style={styles.toggleContainer}>
            <TouchableOpacity
              style={[styles.toggleButton, exchangeType === 'BUY' && styles.toggleButtonActive]}
              onPress={() => setExchangeType('BUY')}
            >
              <Text style={[styles.toggleButtonText, exchangeType === 'BUY' && styles.toggleButtonTextActive]}>
                Comprar
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.toggleButton, exchangeType === 'SELL' && styles.toggleButtonActive]}
              onPress={() => setExchangeType('SELL')}
            >
              <Text style={[styles.toggleButtonText, exchangeType === 'SELL' && styles.toggleButtonTextActive]}>
                Vender
              </Text>
            </TouchableOpacity>
          </View>
          <Text style={styles.helpText}>
            {exchangeType === 'BUY' 
              ? 'Quieres comprar criptomonedas (pagarás con bolívares)'
              : 'Quieres vender criptomonedas (recibirás bolívares)'
            }
          </Text>
        </View>

        {/* Country Selection */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>País de operación</Text>
          <TouchableOpacity
            style={styles.countrySelector}
            onPress={() => setShowCountryModal(true)}
          >
            <View style={styles.countryDisplay}>
              <Text style={styles.countryFlag}>{selectedCountry?.[3] || '🌍'}</Text>
              <Text style={styles.countryName}>
                {selectedCountry?.[0] || 'Seleccionar país'}
              </Text>
            </View>
            <Icon name="chevron-down" size={20} color="#6B7280" />
          </TouchableOpacity>
          <Text style={styles.helpText}>
            País donde operarás y recibirás pagos locales
          </Text>
        </View>

        {/* Token Type */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Criptomoneda</Text>
          <View style={styles.toggleContainer}>
            <TouchableOpacity
              style={[styles.toggleButton, tokenType === 'cUSD' && styles.toggleButtonActive]}
              onPress={() => setTokenType('cUSD')}
            >
              <Text style={[styles.toggleButtonText, tokenType === 'cUSD' && styles.toggleButtonTextActive]}>
                Confío Dollar ($cUSD)
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.toggleButton, tokenType === 'CONFIO' && styles.toggleButtonActive]}
              onPress={() => setTokenType('CONFIO')}
            >
              <Text style={[styles.toggleButtonText, tokenType === 'CONFIO' && styles.toggleButtonTextActive]}>
                Confío ($CONFIO)
              </Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Rate */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Tasa de cambio (Bs. por {tokenType})</Text>
          <View style={styles.inputContainer}>
            <TextInput
              style={styles.textInput}
              value={rate}
              onChangeText={setRate}
              placeholder="35.50"
              keyboardType="decimal-pad"
            />
            <Text style={styles.inputSuffix}>Bs.</Text>
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

        {/* Available Amount */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Cantidad disponible</Text>
          <View style={styles.inputContainer}>
            <TextInput
              style={styles.textInput}
              value={availableAmount}
              onChangeText={setAvailableAmount}
              placeholder="5,000.00"
              keyboardType="decimal-pad"
            />
            <Text style={styles.inputSuffix}>{tokenType}</Text>
          </View>
          <Text style={styles.helpText}>
            Cantidad total que tienes disponible para {exchangeType === 'BUY' ? 'comprar' : 'vender'}
          </Text>
        </View>

        {/* Payment Methods */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Métodos de pago</Text>
          {paymentMethodsLoading ? (
            <Text style={styles.helpText}>Cargando métodos de pago...</Text>
          ) : (
            <View style={styles.paymentMethodsContainer}>
              {paymentMethods.map((method) => (
                <TouchableOpacity
                  key={method.id}
                  style={[
                    styles.paymentMethodItem,
                    selectedPaymentMethods.includes(method.id) && styles.paymentMethodItemSelected
                  ]}
                  onPress={() => togglePaymentMethod(method.id)}
                >
                  <View style={styles.paymentMethodIcon}>
                    <Text style={styles.paymentMethodIconText}>
                      {method.displayName.charAt(0)}
                    </Text>
                  </View>
                  <Text style={styles.paymentMethodName}>{method.displayName}</Text>
                  {selectedPaymentMethods.includes(method.id) && (
                    <Icon name="check" size={20} color={colors.primary} />
                  )}
                </TouchableOpacity>
              ))}
            </View>
          )}
        </View>

        {/* Response Time */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Tiempo de respuesta (minutos)</Text>
          <View style={styles.inputContainer}>
            <TextInput
              style={styles.textInput}
              value={responseTime}
              onChangeText={setResponseTime}
              placeholder="15"
              keyboardType="number-pad"
            />
            <Text style={styles.inputSuffix}>min</Text>
          </View>
          <Text style={styles.helpText}>
            Tiempo promedio en que respondes a las solicitudes de intercambio
          </Text>
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

        {/* Create Button */}
        <TouchableOpacity
          style={[styles.createButton, createOfferLoading && styles.createButtonDisabled]}
          onPress={handleCreateOffer}
          disabled={createOfferLoading}
        >
          <Text style={styles.createButtonText}>
            {createOfferLoading ? 'Creando...' : 'Crear Oferta'}
          </Text>
        </TouchableOpacity>
      </ScrollView>

      {/* Country Selection Modal */}
      <Modal
        animationType="slide"
        transparent={false}
        visible={showCountryModal}
        onRequestClose={() => setShowCountryModal(false)}
      >
        <View style={styles.modalContainer}>
          <View style={styles.modalHeader}>
            <TouchableOpacity onPress={() => setShowCountryModal(false)}>
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
                onPress={() => {
                  setSelectedCountry(item);
                  setShowCountryModal(false);
                }}
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
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: Platform.OS === 'ios' ? 50 : 20,
    paddingBottom: 16,
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