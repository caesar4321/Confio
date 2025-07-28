import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  TextInput,
  Alert,
  ActivityIndicator,
  Modal,
  Platform,
  FlatList,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useQuery, useMutation, useApolloClient } from '@apollo/client';
import { 
  GET_COUNTRIES, 
  GET_P2P_PAYMENT_METHODS,
  GET_USER_BANK_ACCOUNTS,
  CREATE_BANK_INFO,
  UPDATE_BANK_INFO
} from '../apollo/queries';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { getPaymentMethodIcon } from '../utils/paymentMethodIcons';

// Colors matching app design
const colors = {
  primary: '#34d399',
  primaryLight: '#d1fae5',
  primaryDark: '#10b981',
  secondary: '#8b5cf6',
  accent: '#3b82f6',
  background: '#f9fafb',
  neutralDark: '#f3f4f6',
  text: {
    primary: '#1f2937',
    secondary: '#6b7280',
    light: '#9ca3af',
  },
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
};

interface PaymentMethodAccount {
  id: string;
  account: {
    id: string;
    accountId: string;
    displayName: string;
    accountType: string;
  };
  paymentMethod: {
    id: string;
    name: string;
    displayName: string;
    providerType: string;
    requiresPhone: boolean;
    requiresEmail: boolean;
    requiresAccountNumber: boolean;
    icon: string;
    bank?: {
      id: string;
      name: string;
      shortName?: string;
      country: {
        id: string;
        code: string;
        name: string;
        flagEmoji: string;
        requiresIdentification: boolean;
        identificationName: string;
      };
    };
  };
  accountHolderName: string;
  accountNumber?: string;
  phoneNumber?: string;
  email?: string;
  username?: string;
  accountType?: string;
  identificationNumber?: string;
  isDefault: boolean;
}

interface Country {
  id: string;
  code: string;
  name: string;
  flagEmoji: string;
  requiresIdentification: boolean;
  identificationName: string;
  identificationFormat?: string;
}

interface Bank {
  id: string;
  code: string;
  name: string;
  shortName?: string;
  country: {
    id: string;
    code: string;
    name: string;
    flagEmoji: string;
  };
  supportsChecking: boolean;
  supportsSavings: boolean;
  supportsPayroll: boolean;
  accountTypeChoices: string[];
}

interface P2PPaymentMethod {
  id: string;
  name: string;
  displayName: string;
  providerType: string;
  icon: string;
  requiresPhone: boolean;
  requiresEmail: boolean;
  requiresAccountNumber: boolean;
  bank?: {
    id: string;
    name: string;
    country: {
      id: string;
      code: string;
      name: string;
      flagEmoji: string;
      requiresIdentification: boolean;
      identificationName: string;
    };
  };
  isActive: boolean;
}

interface AddBankInfoModalProps {
  isVisible: boolean;
  onClose: () => void;
  onSuccess: () => void;
  accountId: string | null;
  editingBankInfo: PaymentMethodAccount | null;
}

export const AddBankInfoModal = ({
  isVisible,
  onClose,
  onSuccess,
  accountId,
  editingBankInfo
}: AddBankInfoModalProps) => {
  const insets = useSafeAreaInsets();
  const isEditing = !!editingBankInfo;
  const apolloClient = useApolloClient();

  // Form state
  const [selectedPaymentMethod, setSelectedPaymentMethod] = useState<P2PPaymentMethod | null>(null);
  const [selectedCountry, setSelectedCountry] = useState<Country | null>(null);
  const [selectedBank, setSelectedBank] = useState<Bank | null>(null);
  const [formData, setFormData] = useState({
    accountHolderName: '',
    accountNumber: '',
    accountType: 'ahorro',
    identificationNumber: '',
    phoneNumber: '',
    email: '',
    username: '',
    isDefault: false,
  });
  const [showPaymentMethodPicker, setShowPaymentMethodPicker] = useState(false);
  const [showCountryPicker, setShowCountryPicker] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Initialize form for editing
  useEffect(() => {
    if (editingBankInfo) {
      setSelectedPaymentMethod(editingBankInfo.paymentMethod);
      if (editingBankInfo.paymentMethod.bank) {
        setSelectedCountry(editingBankInfo.paymentMethod.bank.country);
        setSelectedBank(editingBankInfo.paymentMethod.bank);
      }
      setFormData({
        accountHolderName: editingBankInfo.accountHolderName,
        accountNumber: editingBankInfo.accountNumber || '',
        accountType: editingBankInfo.accountType || 'ahorro',
        identificationNumber: editingBankInfo.identificationNumber || '',
        phoneNumber: editingBankInfo.phoneNumber || '',
        email: editingBankInfo.email || '',
        username: editingBankInfo.username || '',
        isDefault: editingBankInfo.isDefault,
      });
    } else {
      // Reset form for new entry
      setSelectedPaymentMethod(null);
      setSelectedCountry(null);
      setSelectedBank(null);
      setFormData({
        accountHolderName: '',
        accountNumber: '',
        accountType: 'ahorro',
        identificationNumber: '',
        phoneNumber: '',
        email: '',
        username: '',
        isDefault: false,
      });
    }
  }, [editingBankInfo, isVisible]);

  // GraphQL queries
  const { 
    data: countriesData, 
    loading: countriesLoading 
  } = useQuery(GET_COUNTRIES, {
    variables: { isActive: true },
    skip: !isVisible
  });

  const { 
    data: paymentMethodsData, 
    loading: paymentMethodsLoading 
  } = useQuery(GET_P2P_PAYMENT_METHODS, {
    variables: { countryCode: selectedCountry?.code },
    skip: !isVisible || !selectedCountry,
    fetchPolicy: 'cache-and-network', // Use same policy as CreateOfferScreen for consistency
    onCompleted: (data) => {
      console.log('[AddBankInfoModal] Payment methods query completed:', {
        countryCode: selectedCountry?.code,
        methodsCount: data?.p2pPaymentMethods?.length,
        methods: data?.p2pPaymentMethods?.slice(0, 5).map((m: any) => ({
          id: m.id,
          name: m.displayName,
          providerType: m.providerType
        }))
      });
    }
  });


  // Mutations with cache update
  const [createBankInfo] = useMutation(CREATE_BANK_INFO, {
    update(cache, { data }) {
      if (data?.createBankInfo?.success) {
        // Evict all getUserBankAccounts queries to force refetch
        cache.evict({ fieldName: 'userBankAccounts' });
        // Also try to evict the root query
        cache.evict({ id: 'ROOT_QUERY', fieldName: 'userBankAccounts' });
        cache.gc();
      }
    }
  });
  
  const [updateBankInfo] = useMutation(UPDATE_BANK_INFO, {
    update(cache, { data }) {
      if (data?.updateBankInfo?.success) {
        // Evict all getUserBankAccounts queries to force refetch
        cache.evict({ fieldName: 'userBankAccounts' });
        // Also try to evict the root query
        cache.evict({ id: 'ROOT_QUERY', fieldName: 'userBankAccounts' });
        cache.gc();
      }
    }
  });

  const countries: Country[] = countriesData?.countries || [];
  const paymentMethods: P2PPaymentMethod[] = paymentMethodsData?.p2pPaymentMethods || [];

  // Debug logging
  console.log('Countries loaded:', countries.length);
  console.log('Selected country:', selectedCountry?.name, selectedCountry?.code);
  console.log('Payment methods count:', paymentMethods.length);
  if (selectedCountry?.code === 'CO') {
    console.log('Colombia payment methods:', paymentMethods.map(pm => pm.displayName));
  }

  const getAccountTypeOptions = () => {
    if (selectedBank && selectedBank.accountTypeChoices && selectedBank.accountTypeChoices.length > 0) {
      return selectedBank.accountTypeChoices.map(type => ({
        value: type,
        label: getAccountTypeLabel(type)
      }));
    }
    
    // Default options
    return [
      { value: 'ahorro', label: 'Cuenta de Ahorros' },
      { value: 'corriente', label: 'Cuenta Corriente' },
      { value: 'nomina', label: 'Cuenta Nómina' },
    ];
  };

  const getAccountTypeLabel = (type: string) => {
    const labels: { [key: string]: string } = {
      'ahorro': 'Cuenta de Ahorros',
      'corriente': 'Cuenta Corriente',
      'nomina': 'Cuenta Nómina',
      'checking': 'Cuenta Corriente',
      'savings': 'Cuenta de Ahorros',
      'payroll': 'Cuenta Nómina',
    };
    return labels[type] || type;
  };

  const validateForm = () => {
    if (!selectedPaymentMethod) {
      Alert.alert('Error', 'Por favor selecciona un método de pago');
      return false;
    }
    
    
    if (!formData.accountHolderName.trim()) {
      Alert.alert('Error', 'Por favor ingresa el nombre del titular');
      return false;
    }
    
    // Validate required fields based on payment method
    if (selectedPaymentMethod.requiresAccountNumber && !formData.accountNumber.trim()) {
      Alert.alert('Error', 'Por favor ingresa el número de cuenta');
      return false;
    }
    
    if (selectedPaymentMethod.requiresPhone && !formData.phoneNumber.trim()) {
      Alert.alert('Error', 'Por favor ingresa el número de teléfono');
      return false;
    }
    
    if (selectedPaymentMethod.requiresEmail && !formData.email.trim()) {
      Alert.alert('Error', 'Por favor ingresa el email');
      return false;
    }
    
    // For bank payments, validate ID requirements
    if (selectedPaymentMethod.bank?.country?.requiresIdentification && !formData.identificationNumber.trim()) {
      Alert.alert('Error', `Por favor ingresa tu ${selectedPaymentMethod.bank.country.identificationName}`);
      return false;
    }
    
    return true;
  };

  const handleSubmit = async () => {
    if (!validateForm()) return;

    setIsSubmitting(true);
    try {

      const variables = {
        paymentMethodId: selectedPaymentMethod!.id,
        accountHolderName: formData.accountHolderName.trim(),
        accountNumber: formData.accountNumber.trim() || null,
        phoneNumber: formData.phoneNumber.trim() || null,
        email: formData.email.trim() || null,
        username: formData.username.trim() || null,
        accountType: formData.accountType || null,
        identificationNumber: formData.identificationNumber.trim() || null,
        isDefault: formData.isDefault,
      };

      let result;
      if (isEditing) {
        result = await updateBankInfo({
          variables: {
            bankInfoId: editingBankInfo!.id,
            ...variables
          },
          refetchQueries: [
            { query: GET_USER_BANK_ACCOUNTS, variables: {} },
            { query: GET_USER_BANK_ACCOUNTS, variables: {} } // Also refetch without filter
          ],
          awaitRefetchQueries: true
        });
      } else {
        result = await createBankInfo({ 
          variables,
          refetchQueries: [
            { query: GET_USER_BANK_ACCOUNTS, variables: {} },
            { query: GET_USER_BANK_ACCOUNTS, variables: {} } // Also refetch without filter
          ],
          awaitRefetchQueries: true
        });
      }

      const data = isEditing ? result.data?.updateBankInfo : result.data?.createBankInfo;

      if (data?.success) {
        // Force refetch all active queries that depend on bank accounts
        try {
          // Method 1: Refetch by query name
          await apolloClient.refetchQueries({
            include: ['GetUserBankAccounts']
          });
          
          // Method 2: Reset the entire store to force all queries to refetch
          // This is more aggressive but ensures all data is fresh
          await apolloClient.resetStore();
          
          console.log('Successfully reset Apollo store and refetched all queries');
        } catch (refetchError) {
          console.error('Error refetching queries:', refetchError);
          // Even if refetch fails, try to clear the cache
          try {
            apolloClient.cache.evict({ fieldName: 'userBankAccounts' });
            apolloClient.cache.gc();
          } catch (cacheError) {
            console.error('Error clearing cache:', cacheError);
          }
        }
        
        Alert.alert(
          'Éxito', 
          isEditing ? 'Método de pago actualizado' : 'Método de pago agregado',
          [{ text: 'OK', onPress: onSuccess }]
        );
      } else {
        Alert.alert('Error', data?.error || 'Error al guardar el método de pago');
      }
    } catch (error) {
      console.error('Error submitting payment method:', error);
      Alert.alert('Error', 'Error de conexión');
    } finally {
      setIsSubmitting(false);
    }
  };

  const renderPaymentMethodPicker = () => {
    // No need to filter by isActive - backend already returns only active methods
    const activePaymentMethods = paymentMethods;
    
    console.log('[AddBankInfoModal] Payment methods to display:', {
      total: paymentMethods.length,
      methods: paymentMethods.slice(0, 5).map(m => m.displayName)
    });
    
    const renderPaymentMethodItem = ({ item: method }: { item: P2PPaymentMethod }) => (
      <TouchableOpacity
        style={styles.pickerItem}
        onPress={() => {
          setSelectedPaymentMethod(method);
          if (method.bank) {
            setSelectedCountry(method.bank.country);
            setSelectedBank(method.bank);
          } else {
            setSelectedBank(null);
          }
          setShowPaymentMethodPicker(false);
        }}
      >
        <Icon name={getPaymentMethodIcon(method.icon, method.providerType, method.displayName)} size={20} color={colors.text.secondary} />
        <View style={{ flex: 1, marginLeft: 12 }}>
          <Text style={styles.pickerItemText}>{method.displayName}</Text>
          <Text style={styles.providerTypeSubtext}>
            {method.providerType === 'bank' ? 'Banco' : 
             method.providerType === 'fintech' ? 'Billetera Digital' : 
             method.providerType}
          </Text>
        </View>
        {selectedPaymentMethod?.id === method.id && (
          <Icon name="check" size={20} color={colors.primary} />
        )}
      </TouchableOpacity>
    );
    
    return (
      <Modal
        visible={showPaymentMethodPicker}
        animationType="slide"
        presentationStyle="pageSheet"
      >
        <View style={styles.pickerContainer}>
          <View style={styles.pickerHeader}>
            <TouchableOpacity onPress={() => setShowPaymentMethodPicker(false)}>
              <Text style={styles.pickerCancel}>Cancelar</Text>
            </TouchableOpacity>
            <Text style={styles.pickerTitle}>Seleccionar Método</Text>
            <View style={{ width: 60 }} />
          </View>
          
          {activePaymentMethods.length > 10 && (
            <View style={styles.scrollHint}>
              <Text style={styles.scrollHintText}>
                {activePaymentMethods.length} métodos disponibles - desliza para ver más
              </Text>
            </View>
          )}
          
          <FlatList
            data={activePaymentMethods}
            renderItem={renderPaymentMethodItem}
            keyExtractor={(item) => item.id}
            style={styles.pickerList}
            contentContainerStyle={styles.pickerListContent}
            showsVerticalScrollIndicator={true}
            // Important FlatList optimizations for large lists
            initialNumToRender={20}
            maxToRenderPerBatch={10}
            windowSize={21}
            removeClippedSubviews={true}
            updateCellsBatchingPeriod={50}
            // Ensure all items are rendered
            getItemLayout={(data, index) => ({
              length: 60, // Approximate height of each item
              offset: 60 * index,
              index,
            })}
          />
        </View>
      </Modal>
    );
  };

  const renderCountryPicker = () => {
    const renderCountryItem = ({ item: country }: { item: Country }) => (
      <TouchableOpacity
        style={styles.pickerItem}
        onPress={() => {
          setSelectedCountry(country);
          setSelectedBank(null);
          setSelectedPaymentMethod(null); // Reset payment method when country changes
          setShowCountryPicker(false);
        }}
      >
        <Text style={styles.countryFlag}>{country.flagEmoji}</Text>
        <Text style={styles.pickerItemText}>{country.name}</Text>
        {selectedCountry?.id === country.id && (
          <Icon name="check" size={20} color={colors.primary} />
        )}
      </TouchableOpacity>
    );
    
    return (
      <Modal
        visible={showCountryPicker}
        animationType="slide"
        presentationStyle="pageSheet"
      >
        <View style={styles.pickerContainer}>
          <View style={styles.pickerHeader}>
            <TouchableOpacity onPress={() => setShowCountryPicker(false)}>
              <Text style={styles.pickerCancel}>Cancelar</Text>
            </TouchableOpacity>
            <Text style={styles.pickerTitle}>Seleccionar País</Text>
            <View style={{ width: 60 }} />
          </View>
          
          {countries.length > 10 && (
            <View style={styles.scrollHint}>
              <Text style={styles.scrollHintText}>
                {countries.length} países disponibles - desliza para ver más
              </Text>
            </View>
          )}
          
          <FlatList
            data={countries}
            renderItem={renderCountryItem}
            keyExtractor={(item) => item.id}
            style={styles.pickerList}
            contentContainerStyle={styles.pickerListContent}
            showsVerticalScrollIndicator={true}
            // Important FlatList optimizations for large lists
            initialNumToRender={20}
            maxToRenderPerBatch={10}
            windowSize={21}
            removeClippedSubviews={true}
            updateCellsBatchingPeriod={50}
            // Ensure all items are rendered
            getItemLayout={(data, index) => ({
              length: 60, // Approximate height of each item
              offset: 60 * index,
              index,
            })}
          />
        </View>
      </Modal>
    );
  };


  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={[styles.header, { paddingTop: insets.top + 8 }]}>
        <View style={styles.headerContent}>
          <TouchableOpacity onPress={onClose} style={styles.closeButton}>
            <Icon name="x" size={24} color={colors.text.primary} />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>
            {isEditing ? 'Editar Método de Pago' : 'Agregar Método de Pago'}
          </Text>
          <TouchableOpacity
            onPress={handleSubmit}
            disabled={isSubmitting}
            style={[styles.saveButton, isSubmitting && styles.saveButtonDisabled]}
          >
            {isSubmitting ? (
              <ActivityIndicator size="small" color="white" />
            ) : (
              <Text style={styles.saveButtonText}>
                {isEditing ? 'Guardar' : 'Crear'}
              </Text>
            )}
          </TouchableOpacity>
        </View>
      </View>

      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        {/* Country Selection */}
        <View style={styles.inputGroup}>
          <Text style={styles.label}>País *</Text>
          <TouchableOpacity
            style={styles.picker}
            onPress={() => setShowCountryPicker(true)}
          >
            <View style={styles.pickerContent}>
              {selectedCountry ? (
                <>
                  <Text style={styles.countryFlag}>{selectedCountry.flagEmoji}</Text>
                  <Text style={styles.pickerText}>{selectedCountry.name}</Text>
                </>
              ) : (
                <Text style={styles.pickerPlaceholder}>Seleccionar país</Text>
              )}
            </View>
            <Icon name="chevron-down" size={20} color={colors.text.secondary} />
          </TouchableOpacity>
        </View>

        {/* Payment Method Selection */}
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Método de Pago *</Text>
          <TouchableOpacity
            style={[styles.picker, !selectedCountry && styles.pickerDisabled]}
            onPress={() => selectedCountry && setShowPaymentMethodPicker(true)}
            disabled={!selectedCountry}
          >
            <View style={styles.pickerContent}>
              {selectedPaymentMethod ? (
                <>
                  <Icon name={getPaymentMethodIcon(selectedPaymentMethod.icon, selectedPaymentMethod.providerType, selectedPaymentMethod.displayName)} size={20} color={colors.text.secondary} />
                  <Text style={[styles.pickerText, { marginLeft: 8 }]}>{selectedPaymentMethod.displayName}</Text>
                </>
              ) : (
                <Text style={styles.pickerPlaceholder}>
                  {selectedCountry ? 'Seleccionar método de pago' : 'Primero selecciona un país'}
                </Text>
              )}
            </View>
            <Icon name="chevron-down" size={20} color={colors.text.secondary} />
          </TouchableOpacity>
        </View>

        {/* Bank Information Display (only show for bank-based payment methods) */}
        {selectedPaymentMethod?.bank && (
          <View style={styles.inputGroup}>
            <Text style={styles.label}>Banco</Text>
            <View style={styles.infoBox}>
              <Icon name="info" size={16} color={colors.text.secondary} />
              <Text style={styles.infoText}>{selectedPaymentMethod.bank.name}</Text>
            </View>
          </View>
        )}

        {/* Account Holder Name */}
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Nombre del Titular *</Text>
          <TextInput
            style={styles.textInput}
            value={formData.accountHolderName}
            onChangeText={(value) => setFormData(prev => ({ ...prev, accountHolderName: value }))}
            placeholder="Nombre completo del titular"
            autoCapitalize="words"
          />
        </View>

        {/* Account Number (conditional) */}
        {selectedPaymentMethod?.requiresAccountNumber && (
          <View style={styles.inputGroup}>
            <Text style={styles.label}>
              {selectedPaymentMethod.providerType === 'bank' ? 'Número de Cuenta *' : 'Número de Cuenta'}
            </Text>
            <TextInput
              style={styles.textInput}
              value={formData.accountNumber}
              onChangeText={(value) => setFormData(prev => ({ ...prev, accountNumber: value }))}
              placeholder={selectedPaymentMethod.providerType === 'bank' ? 'Número de cuenta bancaria' : 'Identificador de cuenta'}
              keyboardType="numeric"
            />
          </View>
        )}

        {/* Phone Number (conditional) */}
        {selectedPaymentMethod?.requiresPhone && (
          <View style={styles.inputGroup}>
            <Text style={styles.label}>Teléfono *</Text>
            <TextInput
              style={styles.textInput}
              value={formData.phoneNumber}
              onChangeText={(value) => setFormData(prev => ({ ...prev, phoneNumber: value }))}
              placeholder="Número de teléfono"
              keyboardType="phone-pad"
            />
          </View>
        )}

        {/* Email (conditional) */}
        {selectedPaymentMethod?.requiresEmail && (
          <View style={styles.inputGroup}>
            <Text style={styles.label}>Email *</Text>
            <TextInput
              style={styles.textInput}
              value={formData.email}
              onChangeText={(value) => setFormData(prev => ({ ...prev, email: value }))}
              placeholder="Dirección de correo electrónico"
              keyboardType="email-address"
              autoCapitalize="none"
            />
          </View>
        )}

        {/* Username (always optional) */}
        {selectedPaymentMethod && selectedPaymentMethod.providerType === 'fintech' && (
          <View style={styles.inputGroup}>
            <Text style={styles.label}>Usuario (Opcional)</Text>
            <TextInput
              style={styles.textInput}
              value={formData.username}
              onChangeText={(value) => setFormData(prev => ({ ...prev, username: value }))}
              placeholder="Nombre de usuario o handle"
              autoCapitalize="none"
            />
          </View>
        )}

        {/* Account Type (only for banks) */}
        {selectedPaymentMethod?.providerType === 'bank' && (
          <View style={styles.inputGroup}>
            <Text style={styles.label}>Tipo de Cuenta *</Text>
            <View style={styles.radioGroup}>
              {getAccountTypeOptions().map((option) => (
                <TouchableOpacity
                  key={option.value}
                  style={styles.radioOption}
                  onPress={() => setFormData(prev => ({ ...prev, accountType: option.value }))}
                >
                  <View style={[
                    styles.radioCircle,
                    formData.accountType === option.value && styles.radioCircleSelected
                  ]}>
                    {formData.accountType === option.value && (
                      <View style={styles.radioInner} />
                    )}
                  </View>
                  <Text style={styles.radioLabel}>{option.label}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        )}

        {/* Identification Number (conditional) */}
        {selectedPaymentMethod?.bank?.country?.requiresIdentification && (
          <View style={styles.inputGroup}>
            <Text style={styles.label}>
              {selectedPaymentMethod.bank.country.identificationName} *
            </Text>
            <TextInput
              style={styles.textInput}
              value={formData.identificationNumber}
              onChangeText={(value) => setFormData(prev => ({ ...prev, identificationNumber: value }))}
              placeholder={`Ingresa tu ${selectedPaymentMethod.bank.country.identificationName}`}
              keyboardType="numeric"
            />
            {selectedPaymentMethod.bank.country.identificationFormat && (
              <Text style={styles.helpText}>
                Formato: {selectedPaymentMethod.bank.country.identificationFormat}
              </Text>
            )}
          </View>
        )}


        {/* Set as Default */}
        <View style={styles.inputGroup}>
          <TouchableOpacity
            style={styles.checkboxRow}
            onPress={() => setFormData(prev => ({ ...prev, isDefault: !prev.isDefault }))}
          >
            <View style={[
              styles.checkbox,
              formData.isDefault && styles.checkboxSelected
            ]}>
              {formData.isDefault && (
                <Icon name="check" size={14} color="white" />
              )}
            </View>
            <Text style={styles.checkboxLabel}>Marcar como método de pago predeterminado</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>

      {/* Pickers */}
      {renderPaymentMethodPicker()}
      {renderCountryPicker()}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    backgroundColor: 'white',
    borderBottomWidth: 1,
    borderBottomColor: colors.neutralDark,
    paddingBottom: 16,
    paddingHorizontal: 16,
  },
  headerContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  closeButton: {
    padding: 4,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.text.primary,
  },
  saveButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 8,
    minWidth: 60,
    alignItems: 'center',
  },
  saveButtonDisabled: {
    opacity: 0.6,
  },
  saveButtonText: {
    color: 'white',
    fontWeight: '600',
    fontSize: 14,
  },
  content: {
    flex: 1,
    paddingHorizontal: 16,
    paddingTop: 16,
  },
  inputGroup: {
    marginBottom: 20,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: 8,
  },
  picker: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: 'white',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.neutralDark,
    paddingHorizontal: 12,
    paddingVertical: 12,
  },
  pickerDisabled: {
    opacity: 0.6,
  },
  pickerContent: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  pickerText: {
    fontSize: 16,
    color: colors.text.primary,
  },
  pickerPlaceholder: {
    fontSize: 16,
    color: colors.text.secondary,
  },
  countryFlag: {
    fontSize: 20,
    marginRight: 8,
  },
  textInput: {
    backgroundColor: 'white',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.neutralDark,
    paddingHorizontal: 12,
    paddingVertical: 12,
    fontSize: 16,
    color: colors.text.primary,
  },
  helpText: {
    fontSize: 12,
    color: colors.text.secondary,
    marginTop: 4,
  },
  radioGroup: {
    gap: 12,
  },
  radioOption: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  radioCircle: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: colors.text.light,
    marginRight: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  radioCircleSelected: {
    borderColor: colors.primary,
  },
  radioInner: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.primary,
  },
  radioLabel: {
    fontSize: 16,
    color: colors.text.primary,
  },
  checkboxRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 2,
    borderColor: colors.text.light,
    marginRight: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkboxSelected: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  checkboxLabel: {
    fontSize: 16,
    color: colors.text.primary,
  },
  pickerContainer: {
    flex: 1,
    backgroundColor: colors.background,
  },
  pickerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: colors.neutralDark,
    backgroundColor: 'white',
  },
  pickerTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.text.primary,
  },
  pickerCancel: {
    fontSize: 16,
    color: colors.primary,
  },
  pickerList: {
    flex: 1,
    maxHeight: '80%', // Ensure it doesn't take full screen
  },
  pickerListContent: {
    paddingBottom: 20, // Add padding at the bottom for better scrolling
  },
  scrollHint: {
    backgroundColor: colors.primary + '15',
    paddingVertical: 8,
    paddingHorizontal: 16,
    alignItems: 'center',
  },
  scrollHintText: {
    fontSize: 13,
    color: colors.primary,
    fontStyle: 'italic',
  },
  pickerItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: 'white',
    borderBottomWidth: 1,
    borderBottomColor: colors.neutralDark,
  },
  pickerItemText: {
    flex: 1,
    fontSize: 16,
    color: colors.text.primary,
  },
  providerTypeText: {
    fontSize: 12,
    color: colors.text.secondary,
    marginRight: 8,
    textTransform: 'capitalize',
  },
  providerTypeSubtext: {
    fontSize: 12,
    color: colors.text.light,
    marginTop: 2,
  },
  infoBox: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primaryLight,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    gap: 8,
  },
  infoText: {
    fontSize: 14,
    color: colors.text.primary,
    flex: 1,
  },
});