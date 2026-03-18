import React, { useState, useEffect, useMemo } from 'react';
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
  GET_BANKS,
  GET_P2P_PAYMENT_METHODS,
  GET_USER_BANK_ACCOUNTS,
  CREATE_BANK_INFO,
  UPDATE_BANK_INFO
} from '../apollo/queries';
import { SafeAreaView } from 'react-native-safe-area-context';
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

const KOYWE_SUPPORTED_COUNTRY_CODES = ['AR', 'BO', 'BR', 'CL', 'CO', 'MX', 'PE'];
const FIRST_NAME_ONLY_METHOD_CODES = new Set(['QRI-AR', 'QRI', 'QRI-BO', 'SIP-QR', 'QRI-PE', 'LIGO']);
const SAVABLE_PAYMENT_METHOD_CODES = new Set([
  'WIREAR',
  'QRI-BO',
  'SULPAYMENTS',
  'WIRECL',
  'NEQUI',
  'BANCOLOMBIA',
  'WIREMX',
  'STP',
  'WIREPE',
  'QRI-PE',
  'RECAUDO-PE',
]);

const PERU_BANK_CODE_ALIASES: Record<string, string> = {
  BCP: 'CREDITO',
  'BANCO DE CREDITO DEL PERU': 'CREDITO',
  'BANCO DE CRÉDITO DEL PERÚ': 'CREDITO',
  CREDITO: 'CREDITO',
  BBVA: 'BBVA',
  'BBVA PERU': 'BBVA',
  'BBVA PERÚ': 'BBVA',
  SCOTIABANK: 'SCOTIA',
  'SCOTIABANK PERU': 'SCOTIA',
  'SCOTIABANK PERÚ': 'SCOTIA',
  INTERBANK: 'INTERBANK',
  'BANCO DE LA NACION': 'NACION',
  'BANCO DE LA NACIÓN': 'NACION',
  NACION: 'NACION',
  LIGO: 'LIGO',
};

const KOYWE_BANK_PICKER_ALLOWLIST: Record<string, Set<string>> = {
  PE: new Set(['bcp', 'bbva_peru', 'scotiabank_peru', 'interbank', 'banco_nacion_peru', 'citibank_peru']),
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
    isActive?: boolean;
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
        identificationFormat?: string;
      };
    };
  };
  accountHolderName: string;
  accountNumber?: string;
  phoneNumber?: string;
  email?: string;
  username?: string;
  providerMetadata?: Record<string, string>;
  accountType?: string;
  identificationNumber?: string;
  isDefault: boolean;
}

interface ProviderFieldConfig {
  key: string;
  label: string;
  placeholder: string;
  required?: boolean;
  keyboardType?: 'default' | 'numeric' | 'email-address' | 'phone-pad';
  helpText?: string;
}

interface FieldConfig {
  label: string;
  placeholder: string;
  show: boolean;
  required: boolean;
  keyboardType?: 'default' | 'numeric' | 'email-address' | 'phone-pad';
}

const normalizeProviderMetadata = (value: unknown): Record<string, string> => {
  if (!value) return {};
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      return typeof parsed === 'object' && parsed ? parsed as Record<string, string> : {};
    } catch {
      return {};
    }
  }
  return typeof value === 'object' ? value as Record<string, string> : {};
};

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
  code?: string;
  name: string;
  shortName?: string;
  country: {
    id: string;
    code: string;
    name: string;
    flagEmoji: string;
    requiresIdentification?: boolean;
    identificationName?: string;
    identificationFormat?: string;
  };
  supportsChecking?: boolean;
  supportsSavings?: boolean;
  supportsPayroll?: boolean;
  accountTypeChoices?: string[];
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
    shortName?: string;
    country: {
      id: string;
      code: string;
      name: string;
      flagEmoji: string;
      requiresIdentification: boolean;
      identificationName: string;
      identificationFormat?: string;
    };
  };
  isActive?: boolean;
}

interface AddBankInfoModalProps {
  isVisible: boolean;
  onClose: () => void;
  onSuccess: () => void;
  accountId: string | null;
  editingBankInfo: PaymentMethodAccount | null;
  initialCountryCode?: string | null;
  allowedCountryCodes?: string[] | null;
  allowedPaymentMethodIds?: string[] | null;
  initialPaymentMethodId?: string | null;
  lockCountry?: boolean;
  lockPaymentMethod?: boolean;
  mode?: 'general' | 'off_ramp' | 'on_ramp';
}

export const AddBankInfoModal = ({
  isVisible,
  onClose,
  onSuccess,
  accountId,
  editingBankInfo,
  initialCountryCode = null,
  allowedCountryCodes = null,
  allowedPaymentMethodIds = null,
  initialPaymentMethodId = null,
  lockCountry = false,
  lockPaymentMethod = false,
  mode = 'general',
}: AddBankInfoModalProps) => {
  // Safe area insets not required; use fixed padding where needed
  const isEditing = !!editingBankInfo;
  const apolloClient = useApolloClient();

  // Form state
  const [selectedPaymentMethod, setSelectedPaymentMethod] = useState<P2PPaymentMethod | null>(null);
  const [selectedCountry, setSelectedCountry] = useState<Country | null>(null);
  const [selectedBank, setSelectedBank] = useState<Bank | null>(null);
  const [formData, setFormData] = useState({
    accountHolderName: '',
    accountNumber: '',
    accountType: '',
    identificationNumber: '',
    phoneNumber: '',
    email: '',
    username: '',
    providerMetadata: {} as Record<string, string>,
    isDefault: false,
  });
  const [showPaymentMethodPicker, setShowPaymentMethodPicker] = useState(false);
  const [showCountryPicker, setShowCountryPicker] = useState(false);
  const [showProviderBankPicker, setShowProviderBankPicker] = useState(false);
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
        accountType: editingBankInfo.accountType || '',
        identificationNumber: editingBankInfo.identificationNumber || '',
        phoneNumber: editingBankInfo.phoneNumber || '',
        email: editingBankInfo.email || '',
        username: editingBankInfo.username || '',
        providerMetadata: normalizeProviderMetadata(editingBankInfo.providerMetadata),
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
        accountType: '',
        identificationNumber: '',
        phoneNumber: '',
        email: '',
        username: '',
        providerMetadata: {},
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

  const { data: banksData } = useQuery(GET_BANKS, {
    variables: { countryCode: selectedCountry?.code },
    skip: !isVisible || !selectedCountry,
    fetchPolicy: 'cache-and-network',
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
  const countryBanks: Bank[] = banksData?.banks || [];
  const koyweBankOptions = useMemo(() => {
    const allowedCodes = KOYWE_BANK_PICKER_ALLOWLIST[(selectedCountry?.code || '').toUpperCase()];
    if (!allowedCodes) {
      return countryBanks;
    }
    return countryBanks.filter((bank) => allowedCodes.has((bank.code || '').toLowerCase()));
  }, [countryBanks, selectedCountry?.code]);
  const filteredCountries = useMemo(() => {
    if (!allowedCountryCodes?.length) {
      const supported = new Set(KOYWE_SUPPORTED_COUNTRY_CODES);
      return countries.filter((country) => supported.has(country.code.toUpperCase()));
    }
    const allowed = new Set(allowedCountryCodes.map((code) => code.toUpperCase()));
    return countries.filter((country) => allowed.has(country.code.toUpperCase()));
  }, [allowedCountryCodes, countries]);

  const paymentMethods: P2PPaymentMethod[] = useMemo(() => {
    const methods = (paymentMethodsData?.p2pPaymentMethods || []).filter((method: P2PPaymentMethod) => {
      const code = (method.name || '').replace(/_/g, '-').toUpperCase();
      if (mode === 'general' || mode === 'off_ramp') {
        return SAVABLE_PAYMENT_METHOD_CODES.has(code);
      }
      return true;
    });
    if (!allowedPaymentMethodIds?.length) {
      return methods;
    }
    const allowed = new Set(allowedPaymentMethodIds);
    return methods.filter((method: P2PPaymentMethod) => allowed.has(method.id));
  }, [allowedPaymentMethodIds, paymentMethodsData?.p2pPaymentMethods]);

  useEffect(() => {
    if (!isVisible || editingBankInfo || !initialCountryCode || !filteredCountries.length) {
      return;
    }
    const matchingCountry = filteredCountries.find((country) => country.code === initialCountryCode);
    if (matchingCountry) {
      setSelectedCountry(matchingCountry);
    }
  }, [filteredCountries, editingBankInfo, initialCountryCode, isVisible]);

  useEffect(() => {
    if (!isVisible || editingBankInfo || !initialPaymentMethodId || !paymentMethods.length) {
      return;
    }
    const matchingMethod = paymentMethods.find((method) => method.id === initialPaymentMethodId);
    if (matchingMethod) {
      setSelectedPaymentMethod(matchingMethod);
      if (matchingMethod.bank) {
        setSelectedBank(matchingMethod.bank);
      }
    }
  }, [editingBankInfo, initialPaymentMethodId, isVisible, paymentMethods]);

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

  const methodCode = (selectedPaymentMethod?.name || '').replace(/_/g, '-').toUpperCase();
  const countryCode = selectedCountry?.code?.toUpperCase() || '';
  const isPayoutMode = mode !== 'on_ramp';

  const fieldCopy = useMemo(() => {
    const defaultAccount: FieldConfig = {
      label: selectedPaymentMethod?.providerType === 'bank' ? 'Número de cuenta' : 'Identificador',
      placeholder: selectedPaymentMethod?.providerType === 'bank' ? 'Número de cuenta bancaria' : 'Identificador de cuenta',
      show: Boolean(selectedPaymentMethod?.requiresAccountNumber),
      required: Boolean(selectedPaymentMethod?.requiresAccountNumber),
      keyboardType: 'default' as const,
    };
    const defaultPhone: FieldConfig = {
      label: 'Teléfono',
      placeholder: 'Número de teléfono',
      show: Boolean(selectedPaymentMethod?.requiresPhone),
      required: Boolean(selectedPaymentMethod?.requiresPhone),
      keyboardType: 'phone-pad' as const,
    };
    const defaultEmail: FieldConfig = {
      label: 'Email',
      placeholder: 'Dirección de correo electrónico',
      show: Boolean(selectedPaymentMethod?.requiresEmail),
      required: Boolean(selectedPaymentMethod?.requiresEmail),
      keyboardType: 'email-address' as const,
    };

    if (FIRST_NAME_ONLY_METHOD_CODES.has(methodCode) && !(isPayoutMode && (methodCode === 'QRI-BO' || methodCode === 'QRI-PE'))) {
      return {
        account: { ...defaultAccount, show: false, required: false },
        phone: { ...defaultPhone, show: false, required: false },
        email: { ...defaultEmail, show: false, required: false },
        holderLabel: 'Nombre',
      };
    }

    if (countryCode === 'AR' && methodCode === 'WIREAR') {
      return {
        account: { ...defaultAccount, label: 'CBU o CVU', placeholder: 'Ingresa tu CBU o CVU', show: true, required: true, keyboardType: 'number-pad' as const },
        phone: defaultPhone,
        email: defaultEmail,
        holderLabel: 'Titular de la cuenta',
      };
    }
    if ((countryCode === 'AR' || countryCode === 'CL') && methodCode === 'KHIPU') {
      return {
        account: { ...defaultAccount, show: false, required: false },
        phone: { ...defaultPhone, show: false, required: false },
        email: { ...defaultEmail, show: true, required: true },
        holderLabel: 'Nombre',
      };
    }
    if (countryCode === 'MX' && (methodCode === 'WIREMX' || methodCode === 'STP')) {
      return {
        account: { ...defaultAccount, label: 'CLABE', placeholder: 'Ingresa la CLABE', show: true, required: true, keyboardType: 'numeric' as const },
        phone: defaultPhone,
        email: defaultEmail,
        holderLabel: 'Titular de la cuenta',
      };
    }
    if (countryCode === 'BR' && methodCode === 'SULPAYMENTS') {
      return {
        account: { ...defaultAccount, label: 'Llave PIX o cuenta', placeholder: 'CPF, email, teléfono o llave PIX', show: true, required: true, keyboardType: 'default' as const },
        phone: { ...defaultPhone, label: 'Teléfono PIX', placeholder: 'Número asociado a PIX', show: false, required: false },
        email: defaultEmail,
        holderLabel: 'Titular de la cuenta',
      };
    }
    if (countryCode === 'CO' && methodCode === 'NEQUI') {
      return {
        account: { ...defaultAccount, show: false, required: false },
        phone: { ...defaultPhone, label: 'Número Nequi', placeholder: 'Número de Nequi', show: true, required: true },
        email: defaultEmail,
        holderLabel: 'Titular de la billetera',
      };
    }
    if (countryCode === 'CO' && methodCode === 'PSE') {
      return {
        account: { ...defaultAccount, show: false, required: false },
        phone: { ...defaultPhone, show: true, required: true },
        email: { ...defaultEmail, show: true, required: true },
        holderLabel: 'Nombre completo',
      };
    }
    if (countryCode === 'PE' && methodCode === 'QRI-PE') {
      if (isPayoutMode) {
        return {
          account: { ...defaultAccount, label: 'CCI o número interbancario', placeholder: 'Ingresa el número interbancario de 20 dígitos', show: true, required: true, keyboardType: 'numeric' as const },
          phone: { ...defaultPhone, show: false, required: false },
          email: { ...defaultEmail, show: false, required: false },
          holderLabel: 'Titular de la cuenta',
        };
      }
      return {
        account: { ...defaultAccount, show: false, required: false },
        phone: { ...defaultPhone, label: 'Teléfono de la billetera', placeholder: 'Número asociado a la billetera', show: false, required: false },
        email: { ...defaultEmail, show: false, required: false },
        holderLabel: 'Nombre',
      };
    }
    if (countryCode === 'BO' && methodCode === 'QRI-BO' && isPayoutMode) {
      return {
        account: { ...defaultAccount, show: false, required: false },
        phone: { ...defaultPhone, label: 'Teléfono de la billetera', placeholder: 'Número asociado a la billetera', show: true, required: true },
        email: { ...defaultEmail, show: false, required: false },
        holderLabel: 'Titular de la billetera',
      };
    }
    return {
      account: defaultAccount,
      phone: defaultPhone,
      email: defaultEmail,
      holderLabel: selectedPaymentMethod?.providerType === 'fintech' ? 'Titular de la cuenta o billetera' : 'Titular de la cuenta',
    };
  }, [countryCode, isPayoutMode, methodCode, selectedPaymentMethod?.providerType]);

const showAccountTypeField = useMemo(() => {
  if (!selectedPaymentMethod || selectedPaymentMethod.providerType !== 'bank') {
    return false;
  }
  return true;
}, [countryCode, methodCode, selectedPaymentMethod]);

  const accountTypeRequired = showAccountTypeField;

  const providerFieldConfigs = useMemo<ProviderFieldConfig[]>(() => {
    if (!selectedPaymentMethod) {
      return [];
    }

    if (countryCode === 'CO' && methodCode === 'PSE') {
      return [
        {
          key: 'firstName',
          label: 'Nombre',
          placeholder: 'Ingresa tu nombre',
          required: true,
        },
        {
          key: 'lastName',
          label: 'Apellido',
          placeholder: 'Ingresa tu apellido',
          required: true,
        },
        {
          key: 'documentType',
          label: 'Tipo de documento',
          placeholder: 'CC, CE, NIT, PASSPORT...',
          required: true,
        },
        {
          key: 'documentNumber',
          label: 'Número de documento',
          placeholder: 'Ingresa tu número de documento',
          required: true,
          keyboardType: 'numeric',
        },
      ];
    }

    if (countryCode === 'BR' && (methodCode === 'SULPAYMENTS' || methodCode === 'PIX-QR')) {
      const fields: ProviderFieldConfig[] = [];
      if (isPayoutMode) {
        fields.push({
          key: 'bankName',
          label: 'Institución receptora',
          placeholder: 'Selecciona la institución',
          required: true,
          helpText: 'Selecciona la institución o banco asociado a la llave PIX donde recibirás el retiro.',
        });
      }
      fields.push({
        key: 'pixKeyType',
        label: 'Tipo de llave PIX',
        placeholder: 'CPF, teléfono, email o aleatoria',
        helpText: 'Si tu cuenta usa PIX, guarda el tipo de llave para completar el cobro.',
      });
      return fields;
    }

    if (countryCode === 'CL' && (methodCode === 'WIRECL' || methodCode === 'KHIPU')) {
      return [
        {
          key: 'bankName',
          label: 'Banco receptor',
          placeholder: 'Selecciona el banco',
          required: methodCode === 'WIRECL' && isPayoutMode,
          helpText: methodCode === 'WIRECL' && isPayoutMode ? 'Selecciona el banco donde recibirás el retiro.' : undefined,
        },
        {
          key: 'beneficiaryRut',
          label: 'RUT del titular',
          placeholder: 'Ingresa el RUT del titular',
          helpText: 'Útil para transferencias y validaciones del beneficiario en Chile.',
        },
      ];
    }

    if (countryCode === 'MX' && methodCode === 'WIREMX') {
      return [
        {
          key: 'bankName',
          label: 'Institución receptora',
          placeholder: 'Nombre de la institución',
          helpText: 'Guarda la institución receptora para transferencias SPEI.',
        },
      ];
    }

    if (countryCode === 'PE' && ['WIREPE', 'RECAUDO-PE', 'WIREUSDPE', 'WIREUSDPE-INTERBANK'].includes(methodCode)) {
      return [
        {
          key: 'bankName',
          label: 'Banco receptor',
          placeholder: 'Nombre del banco',
          required: methodCode !== 'RECAUDO-PE',
          helpText: methodCode === 'RECAUDO-PE' ? 'Para Recaudo BCP usaremos BCP por defecto si no aplica otro banco.' : 'Ejemplos: BCP, Interbank, BBVA, Scotiabank.',
        },
        {
          key: 'cci',
          label: 'CCI (opcional)',
          placeholder: 'Código de Cuenta Interbancario',
          keyboardType: 'numeric',
        },
      ];
    }

    if (!isPayoutMode) {
      return [];
    }

    if (countryCode === 'BO' && methodCode === 'QRI-BO') {
      return [
        {
          key: 'walletApp',
          label: 'App o banco del QR',
          placeholder: 'Banco o billetera que recibirá el QR',
          helpText: 'Sirve para identificar la app que el usuario usará con el QR interoperable.',
        },
      ];
    }

    if (countryCode === 'PE' && methodCode === 'QRI-PE') {
      return [
        {
          key: 'walletApp',
          label: 'App de la billetera',
          placeholder: 'Yape, Plin, Ligo u otra',
        },
      ];
    }

    if (countryCode === 'CO' && methodCode === 'PSE') {
      return [
        {
          key: 'bankName',
          label: 'Banco receptor',
          placeholder: 'Nombre del banco',
        },
      ];
    }

    return [];
  }, [countryCode, isPayoutMode, methodCode, selectedPaymentMethod]);

  const validateForm = () => {
    if (!selectedPaymentMethod) {
      Alert.alert('Error', 'Por favor selecciona un método de pago', [{ text: 'OK' }]);
      return false;
    }


    if (!formData.accountHolderName.trim()) {
      Alert.alert('Error', 'Por favor ingresa el nombre del titular', [{ text: 'OK' }]);
      return false;
    }

    // Validate required fields based on payment method
    if (fieldCopy.account.required && !formData.accountNumber.trim()) {
      Alert.alert('Error', 'Por favor ingresa el número de cuenta', [{ text: 'OK' }]);
      return false;
    }

    if (fieldCopy.phone.required && !formData.phoneNumber.trim()) {
      Alert.alert('Error', 'Por favor ingresa el número de teléfono', [{ text: 'OK' }]);
      return false;
    }

    if (fieldCopy.email.required && !formData.email.trim()) {
      Alert.alert('Error', 'Por favor ingresa el email', [{ text: 'OK' }]);
      return false;
    }

    // For bank payments, validate ID requirements
    if (selectedPaymentMethod.bank?.country?.requiresIdentification && !formData.identificationNumber.trim()) {
      Alert.alert('Error', `Por favor ingresa tu ${selectedPaymentMethod.bank.country.identificationName}`, [{ text: 'OK' }]);
      return false;
    }

    for (const field of providerFieldConfigs) {
      const value = formData.providerMetadata[field.key];
      if (field.required && !value?.trim()) {
        Alert.alert('Error', `Por favor completa ${field.label.toLowerCase()}`, [{ text: 'OK' }]);
        return false;
      }
    }

    if (accountTypeRequired && !String(formData.accountType || '').trim()) {
      Alert.alert('Error', 'Por favor selecciona el tipo de cuenta', [{ text: 'OK' }]);
      return false;
    }

    return true;
  };

  const handleSubmit = async () => {
    if (!validateForm()) return;

    setIsSubmitting(true);
    try {
      const enrichedProviderMetadata = { ...formData.providerMetadata };
      if (isPayoutMode && countryCode === 'CO') {
        if (methodCode === 'NEQUI' && !enrichedProviderMetadata.bankCode) {
          enrichedProviderMetadata.bankCode = 'NEQUI';
        }
        if (methodCode === 'BANCOLOMBIA' && !enrichedProviderMetadata.bankCode) {
          enrichedProviderMetadata.bankCode = 'BANCOLOMBIA';
        }
      }
      if (isPayoutMode && countryCode === 'PE') {
        const normalizedBankName = (enrichedProviderMetadata.bankName || '').trim().toUpperCase();
        if (!enrichedProviderMetadata.bankCode && normalizedBankName && PERU_BANK_CODE_ALIASES[normalizedBankName]) {
          enrichedProviderMetadata.bankCode = PERU_BANK_CODE_ALIASES[normalizedBankName];
        }
        if (methodCode === 'QRI-PE' && !enrichedProviderMetadata.bankCode) {
          enrichedProviderMetadata.bankCode = 'LIGO';
        }
        if (methodCode === 'RECAUDO-PE' && !enrichedProviderMetadata.bankCode) {
          enrichedProviderMetadata.bankCode = 'CREDITO';
        }
      }
      if (isPayoutMode && countryCode === 'MX' && methodCode === 'STP' && !enrichedProviderMetadata.bankCode) {
        enrichedProviderMetadata.bankCode = 'STP';
      }
      const variables = {
        paymentMethodId: selectedPaymentMethod!.id,
        accountHolderName:
          methodCode === 'PSE' &&
          formData.providerMetadata.firstName?.trim() &&
          formData.providerMetadata.lastName?.trim()
            ? `${formData.providerMetadata.firstName.trim()} ${formData.providerMetadata.lastName.trim()}`
            : formData.accountHolderName.trim(),
        accountNumber: formData.accountNumber.trim() || null,
        phoneNumber: formData.phoneNumber.trim() || null,
        email: formData.email.trim() || null,
        username: formData.username.trim() || null,
        accountType: showAccountTypeField ? (formData.accountType || null) : null,
        identificationNumber: formData.identificationNumber.trim() || null,
        providerMetadata: Object.keys(enrichedProviderMetadata).length
          ? JSON.stringify(enrichedProviderMetadata)
          : null,
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

          // Method 2: Safer global refresh to avoid in-flight reset invariant
          apolloClient.stop();
          await apolloClient.clearStore();
          apolloClient.reFetchObservableQueries();

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
        Alert.alert('Error', data?.error || 'Error al guardar el método de pago', [{ text: 'OK' }]);
      }
    } catch (error) {
      console.error('Error submitting payment method:', error);
      Alert.alert('Error', 'Error de conexión', [{ text: 'OK' }]);
    } finally {
      setIsSubmitting(false);
    }
  };

  const renderPaymentMethodPicker = () => {
    if (!showPaymentMethodPicker) {
      return null;
    }

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
          setFormData(prev => ({ ...prev, providerMetadata: {}, accountType: '' }));
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
        presentationStyle={Platform.OS === 'ios' ? 'pageSheet' : 'fullScreen'}
        onRequestClose={() => setShowPaymentMethodPicker(false)}
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
    if (!showCountryPicker) {
      return null;
    }

    const renderCountryItem = ({ item: country }: { item: Country }) => (
      <TouchableOpacity
        style={styles.pickerItem}
        onPress={() => {
          setSelectedCountry(country);
          setSelectedBank(null);
          setSelectedPaymentMethod(null); // Reset payment method when country changes
          setFormData(prev => ({ ...prev, providerMetadata: {}, accountType: '' }));
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
        presentationStyle={Platform.OS === 'ios' ? 'pageSheet' : 'fullScreen'}
        onRequestClose={() => setShowCountryPicker(false)}
      >
        <View style={styles.pickerContainer}>
          <View style={styles.pickerHeader}>
            <TouchableOpacity onPress={() => setShowCountryPicker(false)}>
              <Text style={styles.pickerCancel}>Cancelar</Text>
            </TouchableOpacity>
            <Text style={styles.pickerTitle}>Seleccionar País</Text>
            <View style={{ width: 60 }} />
          </View>

          <FlatList
            data={filteredCountries}
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

  const renderProviderBankPicker = () => {
    if (!showProviderBankPicker) {
      return null;
    }

    const renderBankItem = ({ item: bank }: { item: Bank }) => {
      const isSelected =
        formData.providerMetadata.bankCode === bank.code ||
        formData.providerMetadata.bankName === bank.name;

      return (
        <TouchableOpacity
          style={styles.pickerItem}
          onPress={() => {
            setFormData(prev => ({
              ...prev,
              providerMetadata: {
                ...prev.providerMetadata,
                bankName: bank.name,
                bankCode: bank.code || '',
              },
            }));
            setShowProviderBankPicker(false);
          }}
        >
          <View style={{ flex: 1 }}>
            <Text style={styles.pickerItemText}>{bank.name}</Text>
            {bank.shortName ? <Text style={styles.providerTypeSubtext}>{bank.shortName}</Text> : null}
          </View>
          {isSelected ? <Icon name="check" size={20} color={colors.primary} /> : null}
        </TouchableOpacity>
      );
    };

    return (
      <Modal
        visible={showProviderBankPicker}
        animationType="slide"
        presentationStyle={Platform.OS === 'ios' ? 'pageSheet' : 'fullScreen'}
        onRequestClose={() => setShowProviderBankPicker(false)}
      >
        <View style={styles.pickerContainer}>
          <View style={styles.pickerHeader}>
            <TouchableOpacity onPress={() => setShowProviderBankPicker(false)}>
              <Text style={styles.pickerCancel}>Cancelar</Text>
            </TouchableOpacity>
            <Text style={styles.pickerTitle}>Seleccionar Banco</Text>
            <View style={{ width: 60 }} />
          </View>

          <FlatList
            data={koyweBankOptions}
            renderItem={renderBankItem}
            keyExtractor={(item) => item.id}
            style={styles.pickerList}
            contentContainerStyle={styles.pickerListContent}
            showsVerticalScrollIndicator={true}
            initialNumToRender={20}
            maxToRenderPerBatch={10}
            windowSize={21}
            removeClippedSubviews={true}
            updateCellsBatchingPeriod={50}
            getItemLayout={(data, index) => ({
              length: 60,
              offset: 60 * index,
              index,
            })}
          />
        </View>
      </Modal>
    );
  };


  return (
    <SafeAreaView style={styles.container}>
      {/* Header */}
      <View style={[styles.header, { paddingTop: 8 }]}>
        <View style={styles.headerContent}>
          <TouchableOpacity onPress={onClose} style={styles.closeButton}>
            <Icon name="x" size={24} color={colors.text.primary} />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>
            {isEditing ? 'Editar método de pago' : mode === 'off_ramp' ? 'Agregar forma de cobro' : 'Agregar método de pago'}
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
            style={[styles.picker, lockCountry && styles.pickerDisabled]}
            onPress={() => !lockCountry && setShowCountryPicker(true)}
            disabled={countriesLoading || lockCountry}
          >
            <View style={styles.pickerContent}>
              {selectedCountry ? (
                <>
                  <Text style={styles.countryFlag}>{selectedCountry.flagEmoji}</Text>
                  <Text style={styles.pickerText}>{selectedCountry.name}</Text>
                </>
              ) : (
                <Text style={styles.pickerPlaceholder}>
                  {countriesLoading ? 'Cargando países...' : 'Seleccionar país'}
                </Text>
              )}
            </View>
            <Icon name={lockCountry ? 'lock' : 'chevron-down'} size={16} color={colors.text.secondary} />
          </TouchableOpacity>
        </View>

        {/* Payment Method Selection */}
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Método de Pago *</Text>
          <TouchableOpacity
            style={[styles.picker, (!selectedCountry || lockPaymentMethod) && styles.pickerDisabled]}
            onPress={() => selectedCountry && !lockPaymentMethod && setShowPaymentMethodPicker(true)}
            disabled={!selectedCountry || lockPaymentMethod}
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
            <Icon name={lockPaymentMethod ? 'lock' : 'chevron-down'} size={20} color={colors.text.secondary} />
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
          <Text style={styles.label}>{fieldCopy.holderLabel} *</Text>
          <TextInput
            style={styles.textInput}
            value={formData.accountHolderName}
            onChangeText={(value) => setFormData(prev => ({ ...prev, accountHolderName: value }))}
            placeholder={fieldCopy.holderLabel}
            autoCapitalize="words"
          />
        </View>

        {/* Account Number (conditional) */}
        {fieldCopy.account.show && (
          <View style={styles.inputGroup}>
            <Text style={styles.label}>
              {fieldCopy.account.label}{fieldCopy.account.required ? ' *' : ''}
            </Text>
            <TextInput
              style={styles.textInput}
              value={formData.accountNumber}
              onChangeText={(value) => setFormData(prev => ({ ...prev, accountNumber: value }))}
              placeholder={fieldCopy.account.placeholder}
              keyboardType={fieldCopy.account.keyboardType}
            />
          </View>
        )}

        {/* Phone Number (conditional) */}
        {fieldCopy.phone.show && (
          <View style={styles.inputGroup}>
            <Text style={styles.label}>{fieldCopy.phone.label}{fieldCopy.phone.required ? ' *' : ''}</Text>
            <TextInput
              style={styles.textInput}
              value={formData.phoneNumber}
              onChangeText={(value) => setFormData(prev => ({ ...prev, phoneNumber: value }))}
              placeholder={fieldCopy.phone.placeholder}
              keyboardType={fieldCopy.phone.keyboardType}
            />
          </View>
        )}

        {/* Email (conditional) */}
        {fieldCopy.email.show && (
          <View style={styles.inputGroup}>
            <Text style={styles.label}>{fieldCopy.email.label}{fieldCopy.email.required ? ' *' : ''}</Text>
            <TextInput
              style={styles.textInput}
              value={formData.email}
              onChangeText={(value) => setFormData(prev => ({ ...prev, email: value }))}
              placeholder={fieldCopy.email.placeholder}
              keyboardType={fieldCopy.email.keyboardType}
              autoCapitalize="none"
            />
          </View>
        )}

        {/* Username (always optional) */}
        {selectedPaymentMethod && selectedPaymentMethod.providerType === 'fintech' && false && (
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
        {showAccountTypeField && (
          <View style={styles.inputGroup}>
            <Text style={styles.label}>
              Tipo de Cuenta{accountTypeRequired ? ' *' : ''}
            </Text>
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

        {providerFieldConfigs.map((field) => {
          if (field.key === 'bankName') {
            const canUseBankPicker = koyweBankOptions.length > 0;
            return (
              <View style={styles.inputGroup} key={field.key}>
                <Text style={styles.label}>
                  {field.label}{field.required ? ' *' : ''}
                </Text>
                {canUseBankPicker ? (
                  <TouchableOpacity
                    style={styles.picker}
                    onPress={() => setShowProviderBankPicker(true)}
                  >
                    <View style={styles.pickerContent}>
                      {formData.providerMetadata.bankName ? (
                        <Text style={styles.pickerText}>{formData.providerMetadata.bankName}</Text>
                      ) : (
                        <Text style={styles.pickerPlaceholder}>{field.placeholder}</Text>
                      )}
                    </View>
                    <Icon name="chevron-down" size={16} color={colors.text.secondary} />
                  </TouchableOpacity>
                ) : (
                  <TextInput
                    style={styles.textInput}
                    value={formData.providerMetadata[field.key] || ''}
                    onChangeText={(value) =>
                      setFormData(prev => ({
                        ...prev,
                        providerMetadata: {
                          ...prev.providerMetadata,
                          [field.key]: value,
                        },
                      }))
                    }
                    placeholder={field.placeholder}
                    autoCapitalize="words"
                  />
                )}
                {field.helpText ? <Text style={styles.helpText}>{field.helpText}</Text> : null}
              </View>
            );
          }

          return (
            <View style={styles.inputGroup} key={field.key}>
              <Text style={styles.label}>
                {field.label}{field.required ? ' *' : ''}
              </Text>
              <TextInput
                style={styles.textInput}
                value={formData.providerMetadata[field.key] || ''}
                onChangeText={(value) =>
                  setFormData(prev => ({
                    ...prev,
                    providerMetadata: {
                      ...prev.providerMetadata,
                      [field.key]: value,
                    },
                  }))
                }
                placeholder={field.placeholder}
                keyboardType={field.keyboardType || 'default'}
                autoCapitalize="none"
              />
              {field.helpText ? <Text style={styles.helpText}>{field.helpText}</Text> : null}
            </View>
          );
        })}


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
      {renderProviderBankPicker()}
    </SafeAreaView>
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
