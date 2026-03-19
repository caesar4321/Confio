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
  GET_KOYWE_BANK_INFO,
  GET_RAMP_PAYMENT_METHODS,
  GET_USER_BANK_ACCOUNTS,
  CREATE_BANK_INFO,
  UPDATE_BANK_INFO
} from '../apollo/queries';
import { SafeAreaView } from 'react-native-safe-area-context';
import { getPaymentMethodIcon } from '../utils/paymentMethodIcons';
import Svg, { Defs, LinearGradient, Stop, Rect, Circle } from 'react-native-svg';

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
  'WIRECO',
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

const COUNTRY_ALPHA2_TO_ALPHA3: Record<string, string> = {
  AR: 'ARG', BO: 'BOL', BR: 'BRA', CL: 'CHL', CO: 'COL', MX: 'MEX', PE: 'PER',
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
    country?: Country;
  };
  rampPaymentMethod?: RampPaymentMethod | null;
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
  minLength?: number;
  maxLength?: number;
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

const normalizeAccountType = (value: unknown): string => {
  const raw = String(value || '').trim().toLowerCase();
  if (!raw) return '';

  const normalized = raw
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[-\s]+/g, '_')
    .replace(/^cuenta_/, '')
    .replace(/^de_/, '');

  const mapping: Record<string, string> = {
    ahorro: 'savings',
    ahorros: 'savings',
    savings: 'savings',
    corriente: 'checking',
    checking: 'checking',
    nomina: 'payroll',
    payroll: 'payroll',
    interbancaria: 'interbanking',
    interbanking: 'interbanking',
  };

  return mapping[normalized] || normalized;
};

const toPayoutAccountType = (value: unknown): string | null => {
  const normalized = normalizeAccountType(value);
  if (!normalized) return null;
  if (normalized === 'savings') return 'ahorro';
  if (normalized === 'checking') return 'corriente';
  if (normalized === 'payroll') return 'nomina';
  return normalized;
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

interface RampFieldSchema {
  accountHolderLabel?: string;
  accountField?: FieldConfig;
  phoneField?: FieldConfig;
  emailField?: FieldConfig;
  showAccountTypeField?: boolean;
  accountTypeRequired?: boolean;
  defaultProviderMetadata?: Record<string, string>;
  providerFields?: ProviderFieldConfig[];
}

interface RampPaymentMethod {
  id: string;
  code?: string;
  name?: string;
  displayName: string;
  providerType: string;
  icon: string;
  requiresPhone: boolean;
  requiresEmail: boolean;
  requiresAccountNumber: boolean;
  requiresIdentification?: boolean;
  supportsOnRamp?: boolean;
  supportsOffRamp?: boolean;
  fieldSchema?: RampFieldSchema;
  country?: Country;
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

interface AddPayoutMethodModalProps {
  isVisible: boolean;
  onClose: () => void;
  onSuccess: () => void;
  accountId: string | null;
  editingPayoutMethod: PaymentMethodAccount | null;
  initialCountryCode?: string | null;
  allowedCountryCodes?: string[] | null;
  allowedPaymentMethodIds?: string[] | null;
  initialPaymentMethodId?: string | null;
  lockCountry?: boolean;
  lockPaymentMethod?: boolean;
}

export const AddPayoutMethodModal = ({
  isVisible,
  onClose,
  onSuccess,
  accountId,
  editingPayoutMethod,
  initialCountryCode = null,
  allowedCountryCodes = null,
  allowedPaymentMethodIds = null,
  initialPaymentMethodId = null,
  lockCountry = false,
  lockPaymentMethod = false,
}: AddPayoutMethodModalProps) => {
  // Safe area insets not required; use fixed padding where needed
  const isEditing = !!editingPayoutMethod;
  const apolloClient = useApolloClient();

  // Form state
  const [selectedPaymentMethod, setSelectedPaymentMethod] = useState<RampPaymentMethod | null>(null);
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

  const resetRailSpecificFields = (
    currentData: {
      accountHolderName: string;
      accountNumber: string;
      accountType: string;
      identificationNumber: string;
      phoneNumber: string;
      email: string;
      username: string;
      providerMetadata: Record<string, string>;
      isDefault: boolean;
    },
    overrides: Partial<{
      accountHolderName: string;
      accountNumber: string;
      accountType: string;
      identificationNumber: string;
      phoneNumber: string;
      email: string;
      username: string;
      providerMetadata: Record<string, string>;
      isDefault: boolean;
    }> = {},
  ) => ({
    accountHolderName: currentData.accountHolderName,
    accountNumber: '',
    accountType: '',
    identificationNumber: '',
    phoneNumber: '',
    email: '',
    username: '',
    providerMetadata: {},
    isDefault: currentData.isDefault,
    ...overrides,
  });

  const parseRampFieldSchema = (paymentMethod?: RampPaymentMethod | null): RampFieldSchema | null => {
    const raw = paymentMethod?.fieldSchema;
    if (!raw) return null;
    if (typeof raw === 'object') return raw as RampFieldSchema;
    try {
      return JSON.parse(raw as unknown as string) as RampFieldSchema;
    } catch {
      return null;
    }
  };

  const getDefaultProviderMetadata = (paymentMethod?: RampPaymentMethod | null): Record<string, string> => {
    const schema = parseRampFieldSchema(paymentMethod);
    return schema?.defaultProviderMetadata || {};
  };

  // Initialize form for editing
  useEffect(() => {
    if (editingPayoutMethod) {
      const resolvedPaymentMethod = editingPayoutMethod.rampPaymentMethod || editingPayoutMethod.paymentMethod;
      setSelectedPaymentMethod(resolvedPaymentMethod);
      if (resolvedPaymentMethod?.bank) {
        setSelectedCountry(resolvedPaymentMethod.bank.country);
        setSelectedBank(resolvedPaymentMethod.bank);
      } else if (resolvedPaymentMethod?.country) {
        setSelectedCountry(resolvedPaymentMethod.country);
      }
      setFormData({
        accountHolderName: editingPayoutMethod.accountHolderName,
        accountNumber: editingPayoutMethod.accountNumber || '',
        accountType: normalizeAccountType(editingPayoutMethod.accountType),
        identificationNumber: editingPayoutMethod.identificationNumber || '',
        phoneNumber: editingPayoutMethod.phoneNumber || '',
        email: editingPayoutMethod.email || '',
        username: editingPayoutMethod.username || '',
        providerMetadata: {
          ...getDefaultProviderMetadata(resolvedPaymentMethod),
          ...normalizeProviderMetadata(editingPayoutMethod.providerMetadata),
        },
        isDefault: editingPayoutMethod.isDefault,
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
  }, [editingPayoutMethod, isVisible]);

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
  } = useQuery(GET_RAMP_PAYMENT_METHODS, {
    variables: {
      countryCode: selectedCountry?.code,
      direction: 'OFF_RAMP',
    },
    skip: !isVisible || !selectedCountry,
    fetchPolicy: 'cache-and-network', // Use same policy as CreateOfferScreen for consistency
    onCompleted: (data) => {
      console.log('[AddPayoutMethodModal] Payment methods query completed:', {
        component: 'AddPayoutMethodModal',
        countryCode: selectedCountry?.code,
        methodsCount: data?.rampPaymentMethods?.length,
        methods: data?.rampPaymentMethods?.slice(0, 5).map((m: any) => ({
          id: m.id,
          name: m.code || m.displayName,
          providerType: m.providerType
        }))
      });
    }
  });

  const alpha3 = COUNTRY_ALPHA2_TO_ALPHA3[(selectedCountry?.code || '').toUpperCase()];
  const { data: koyweBankData } = useQuery(GET_KOYWE_BANK_INFO, {
    variables: { countryCode: alpha3 },
    skip: !isVisible || !alpha3,
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
  const koyweBankOptions: Bank[] = useMemo(() => {
    const raw: { bankCode: string; name: string; institutionName?: string }[] =
      koyweBankData?.koyweBankInfo || [];
    return raw.map((b) => ({
      id: b.bankCode,
      code: b.bankCode,
      name: b.name,
      shortName: b.institutionName || undefined,
      country: { id: '', code: selectedCountry?.code || '', name: '', flagEmoji: '' },
    }));
  }, [koyweBankData, selectedCountry?.code]);
  const filteredCountries = useMemo(() => {
    if (!allowedCountryCodes?.length) {
      const supported = new Set(KOYWE_SUPPORTED_COUNTRY_CODES);
      return countries.filter((country) => supported.has(country.code.toUpperCase()));
    }
    const allowed = new Set(allowedCountryCodes.map((code) => code.toUpperCase()));
    return countries.filter((country) => allowed.has(country.code.toUpperCase()));
  }, [allowedCountryCodes, countries]);

  const paymentMethods: RampPaymentMethod[] = useMemo(() => {
    const methods = (paymentMethodsData?.rampPaymentMethods || []).filter((method: RampPaymentMethod) => {
      const code = (method.code || method.name || '').replace(/_/g, '-').toUpperCase();
      if (!method.supportsOffRamp) {
        return false;
      }
      return SAVABLE_PAYMENT_METHOD_CODES.has(code);
    });
    if (!allowedPaymentMethodIds?.length) {
      return methods;
    }
    const allowed = new Set(allowedPaymentMethodIds);
    return methods.filter((method: RampPaymentMethod) => allowed.has(method.id));
  }, [allowedPaymentMethodIds, paymentMethodsData?.rampPaymentMethods]);

  useEffect(() => {
    if (!isVisible || editingPayoutMethod || !initialCountryCode || !filteredCountries.length) {
      return;
    }
    const matchingCountry = filteredCountries.find((country) => country.code === initialCountryCode);
    if (matchingCountry) {
      setSelectedCountry(matchingCountry);
    }
  }, [filteredCountries, editingPayoutMethod, initialCountryCode, isVisible]);

  useEffect(() => {
    if (!isVisible || editingPayoutMethod || !initialPaymentMethodId || !paymentMethods.length) {
      return;
    }
    const matchingMethod = paymentMethods.find((method) => method.id === initialPaymentMethodId);
    if (matchingMethod) {
      setSelectedPaymentMethod(matchingMethod);
      if (matchingMethod.bank) {
        setSelectedBank(matchingMethod.bank);
      }
      setFormData(prev => ({
        ...prev,
        providerMetadata: {
          ...getDefaultProviderMetadata(matchingMethod),
          ...prev.providerMetadata,
        },
      }));
    }
  }, [editingPayoutMethod, initialPaymentMethodId, isVisible, paymentMethods]);

  const getAccountTypeOptions = () => {
    if (selectedBank && selectedBank.accountTypeChoices && selectedBank.accountTypeChoices.length > 0) {
      return selectedBank.accountTypeChoices.map(type => ({
        value: normalizeAccountType(type),
        label: getAccountTypeLabel(type)
      }));
    }

    // Default canonical options
    return [
      { value: 'savings', label: 'Cuenta de Ahorros' },
      { value: 'checking', label: 'Cuenta Corriente' },
      { value: 'payroll', label: 'Cuenta Nómina' },
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
      'interbanking': 'Cuenta Interbancaria',
    };
    return labels[normalizeAccountType(type)] || type;
  };

  const methodCode = (selectedPaymentMethod?.code || selectedPaymentMethod?.name || '').replace(/_/g, '-').toUpperCase();
  const countryCode = selectedCountry?.code?.toUpperCase() || '';
  const serverFieldSchema = useMemo<RampFieldSchema | null>(() => {
    return parseRampFieldSchema(selectedPaymentMethod);
  }, [selectedPaymentMethod?.fieldSchema]);

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
      show: false,
      required: false,
      keyboardType: 'email-address' as const,
    };

    if (serverFieldSchema) {
      return {
        account: serverFieldSchema.accountField || defaultAccount,
        phone: serverFieldSchema.phoneField || defaultPhone,
        email: serverFieldSchema.emailField || defaultEmail,
        holderLabel: serverFieldSchema.accountHolderLabel || (selectedPaymentMethod?.providerType === 'fintech' ? 'Titular de la cuenta o billetera' : 'Titular de la cuenta'),
      };
    }

    if (FIRST_NAME_ONLY_METHOD_CODES.has(methodCode) && methodCode !== 'QRI-BO' && methodCode !== 'QRI-PE') {
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
      return {
        account: { ...defaultAccount, label: 'CCI o número interbancario', placeholder: 'Ingresa el número interbancario de 20 dígitos', show: true, required: true, keyboardType: 'numeric' as const },
        phone: { ...defaultPhone, show: false, required: false },
        email: { ...defaultEmail, show: false, required: false },
        holderLabel: 'Titular de la cuenta',
      };
    }
    if (countryCode === 'BO' && methodCode === 'QRI-BO') {
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
  }, [countryCode, methodCode, selectedPaymentMethod?.providerType, serverFieldSchema]);

  const payoutEmailField = useMemo(
    () => ({ ...fieldCopy.email, show: false, required: false }),
    [fieldCopy.email],
  );

  const showAccountTypeField = useMemo(() => {
    if (typeof serverFieldSchema?.showAccountTypeField === 'boolean') {
      return serverFieldSchema.showAccountTypeField;
    }
    if (!selectedPaymentMethod || selectedPaymentMethod.providerType !== 'bank') {
      return false;
    }
    return true;
  }, [countryCode, methodCode, selectedPaymentMethod, serverFieldSchema]);

  const accountTypeRequired = typeof serverFieldSchema?.accountTypeRequired === 'boolean'
    ? serverFieldSchema.accountTypeRequired
    : showAccountTypeField;

  const providerFieldConfigs = useMemo<ProviderFieldConfig[]>(() => {
    if (!selectedPaymentMethod) {
      return [];
    }

    if (serverFieldSchema?.providerFields?.length) {
      return serverFieldSchema.providerFields;
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
      return [
        {
          key: 'bankName',
          label: 'Institución receptora',
          placeholder: 'Selecciona la institución',
          required: true,
          helpText: 'Selecciona la institución o banco asociado a la llave PIX donde recibirás el retiro.',
        },
        {
          key: 'pixKeyType',
          label: 'Tipo de llave PIX',
          placeholder: 'CPF, teléfono, email o aleatoria',
          helpText: 'Si tu cuenta usa PIX, guarda el tipo de llave para completar el cobro.',
        },
      ];
    }

    if (countryCode === 'CL' && (methodCode === 'WIRECL' || methodCode === 'KHIPU')) {
      return [
        {
          key: 'bankName',
          label: 'Banco receptor',
          placeholder: 'Selecciona el banco',
          required: methodCode === 'WIRECL',
          helpText: methodCode === 'WIRECL' ? 'Selecciona el banco donde recibirás el retiro.' : undefined,
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
  }, [countryCode, methodCode, selectedPaymentMethod, serverFieldSchema]);

  const validateForm = () => {
    if (!selectedPaymentMethod) {
      Alert.alert('Error', 'Por favor selecciona una forma de cobro', [{ text: 'OK' }]);
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

    const accountNumberValue = String(formData.accountNumber || '').trim();
    if (fieldCopy.account.show && accountNumberValue) {
      if (fieldCopy.account.minLength && accountNumberValue.length < fieldCopy.account.minLength) {
        Alert.alert('Error', `${fieldCopy.account.label} debe tener al menos ${fieldCopy.account.minLength} dígitos`, [{ text: 'OK' }]);
        return false;
      }
      if (fieldCopy.account.maxLength && accountNumberValue.length > fieldCopy.account.maxLength) {
        Alert.alert('Error', `${fieldCopy.account.label} debe tener máximo ${fieldCopy.account.maxLength} dígitos`, [{ text: 'OK' }]);
        return false;
      }
    }

    if (fieldCopy.phone.required && !formData.phoneNumber.trim()) {
      Alert.alert('Error', 'Por favor ingresa el número de teléfono', [{ text: 'OK' }]);
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
      if (countryCode === 'PE') {
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
      if (countryCode === 'MX' && methodCode === 'STP' && !enrichedProviderMetadata.bankCode) {
        enrichedProviderMetadata.bankCode = 'STP';
      }
      const variables = {
        paymentMethodId: null,
        rampPaymentMethodId: selectedPaymentMethod!.id,
        accountHolderName:
          methodCode === 'PSE' &&
          formData.providerMetadata.firstName?.trim() &&
          formData.providerMetadata.lastName?.trim()
            ? `${formData.providerMetadata.firstName.trim()} ${formData.providerMetadata.lastName.trim()}`
            : formData.accountHolderName.trim(),
        accountNumber: formData.accountNumber.trim() || null,
        phoneNumber: formData.phoneNumber.trim() || null,
        email: null,
        username: formData.username.trim() || null,
        accountType: showAccountTypeField ? toPayoutAccountType(formData.accountType) : null,
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
            bankInfoId: editingPayoutMethod!.id,
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
          isEditing ? 'Forma de cobro actualizada' : 'Forma de cobro agregada',
          [{ text: 'OK', onPress: onSuccess }]
        );
      } else {
        Alert.alert('Error', data?.error || 'Error al guardar la forma de cobro', [{ text: 'OK' }]);
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

    const renderPaymentMethodItem = ({ item: method }: { item: RampPaymentMethod }) => (
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
          setFormData(prev => resetRailSpecificFields(prev, {
            accountHolderName: prev.accountHolderName,
            isDefault: prev.isDefault,
            providerMetadata: getDefaultProviderMetadata(method),
          }));
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
        <SafeAreaView style={styles.pickerContainer}>
          <View style={styles.pickerHeader}>
            <TouchableOpacity onPress={() => setShowPaymentMethodPicker(false)}>
              <Text style={styles.pickerCancel}>Cancelar</Text>
            </TouchableOpacity>
            <Text style={styles.pickerTitle}>Forma de cobro</Text>
            <View style={{ width: 70 }} />
          </View>

          <FlatList
            data={activePaymentMethods}
            renderItem={renderPaymentMethodItem}
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
              length: 62,
              offset: 62 * index,
              index,
            })}
          />
        </SafeAreaView>
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
          setFormData(prev => resetRailSpecificFields(prev, {
            accountHolderName: prev.accountHolderName,
            isDefault: prev.isDefault,
          }));
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
        <SafeAreaView style={styles.pickerContainer}>
          <View style={styles.pickerHeader}>
            <TouchableOpacity onPress={() => setShowCountryPicker(false)}>
              <Text style={styles.pickerCancel}>Cancelar</Text>
            </TouchableOpacity>
            <Text style={styles.pickerTitle}>País</Text>
            <View style={{ width: 70 }} />
          </View>

          <FlatList
            data={filteredCountries}
            renderItem={renderCountryItem}
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
              length: 56,
              offset: 56 * index,
              index,
            })}
          />
        </SafeAreaView>
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
        <SafeAreaView style={styles.pickerContainer}>
          <View style={styles.pickerHeader}>
            <TouchableOpacity onPress={() => setShowProviderBankPicker(false)}>
              <Text style={styles.pickerCancel}>Cancelar</Text>
            </TouchableOpacity>
            <Text style={styles.pickerTitle}>Banco receptor</Text>
            <View style={{ width: 70 }} />
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
              length: 62,
              offset: 62 * index,
              index,
            })}
          />
        </SafeAreaView>
      </Modal>
    );
  };


  const [focusedField, setFocusedField] = useState<string | null>(null);

  return (
    <SafeAreaView style={styles.container}>
      {/* Gradient header with curved bottom */}
      <View style={styles.headerWrap}>
        <Svg width="100%" height={70} style={StyleSheet.absoluteFill}>
          <Defs>
            <LinearGradient id="hdrGrad" x1="0" y1="0" x2="1" y2="1">
              <Stop offset="0" stopColor="#34d399" stopOpacity="1" />
              <Stop offset="1" stopColor="#6ee7b7" stopOpacity="1" />
            </LinearGradient>
          </Defs>
          <Rect width="100%" height={70} fill="url(#hdrGrad)" />
          <Circle cx="92%" cy="10" r="60" fill="rgba(255,255,255,0.07)" />
        </Svg>
        <View style={styles.headerContent}>
          <TouchableOpacity onPress={onClose} style={styles.closeButton}>
            <Icon name="x" size={22} color="white" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>
            {isEditing ? 'Editar forma de cobro' : 'Agregar forma de cobro'}
          </Text>
          {/* Save button in header still shown, but primary CTA is at bottom */}
          <View style={{ width: 40 }} />
        </View>
      </View>

      <ScrollView
        style={styles.content}
        contentContainerStyle={styles.contentContainer}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        {/* ── Section: Destino ── */}
        <Text style={styles.sectionHeader}>Destino</Text>
        <View style={styles.card}>
          {/* Country */}
          <View style={styles.fieldInCard}>
            <Text style={styles.label}>País {!lockCountry && '*'}</Text>
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
              <Icon name={lockCountry ? 'lock' : 'chevron-down'} size={16} color={colors.text.light} />
            </TouchableOpacity>
          </View>

          <View style={styles.cardDivider} />

          {/* Payment Method */}
          <View style={styles.fieldInCard}>
            <Text style={styles.label}>Forma de cobro *</Text>
            <TouchableOpacity
              style={[styles.picker, (!selectedCountry || lockPaymentMethod) && styles.pickerDisabled]}
              onPress={() => selectedCountry && !lockPaymentMethod && setShowPaymentMethodPicker(true)}
              disabled={!selectedCountry || lockPaymentMethod}
            >
              <View style={styles.pickerContent}>
                {selectedPaymentMethod ? (
                  <>
                    <Icon name={getPaymentMethodIcon(selectedPaymentMethod.icon, selectedPaymentMethod.providerType, selectedPaymentMethod.displayName)} size={18} color={colors.primary} style={{ marginRight: 8 }} />
                    <Text style={styles.pickerText}>{selectedPaymentMethod.displayName}</Text>
                  </>
                ) : (
                  <Text style={styles.pickerPlaceholder}>
                    {selectedCountry
                      ? (paymentMethodsLoading ? 'Cargando métodos...' : 'Seleccionar forma de cobro')
                      : 'Primero selecciona un país'}
                  </Text>
                )}
              </View>
              <Icon name={lockPaymentMethod ? 'lock' : 'chevron-down'} size={16} color={colors.text.light} />
            </TouchableOpacity>
          </View>

          {/* Bank info display */}
          {selectedPaymentMethod?.bank && (
            <>
              <View style={styles.cardDivider} />
              <View style={styles.fieldInCard}>
                <View style={styles.infoBox}>
                  <Icon name="info" size={14} color={colors.primaryDark} />
                  <Text style={styles.infoText}>{selectedPaymentMethod.bank.name}</Text>
                </View>
              </View>
            </>
          )}
        </View>

        {/* ── Section: Datos del titular ── */}
        <Text style={styles.sectionHeader}>Datos del titular</Text>
        <View style={styles.card}>
          {/* Account Holder Name */}
          <View style={styles.fieldInCard}>
            <Text style={styles.label}>{fieldCopy.holderLabel} *</Text>
            <TextInput
              style={[styles.textInput, focusedField === 'holder' && styles.textInputFocused]}
              value={formData.accountHolderName}
              onChangeText={(value) => setFormData(prev => ({ ...prev, accountHolderName: value }))}
              placeholder={fieldCopy.holderLabel}
              placeholderTextColor={colors.text.light}
              autoCapitalize="words"
              onFocus={() => setFocusedField('holder')}
              onBlur={() => setFocusedField(null)}
            />
          </View>

          {/* Identification Number */}
          {selectedPaymentMethod?.bank?.country?.requiresIdentification && (
            <>
              <View style={styles.cardDivider} />
              <View style={styles.fieldInCard}>
                <Text style={styles.label}>{selectedPaymentMethod.bank.country.identificationName} *</Text>
                <TextInput
                  style={[styles.textInput, focusedField === 'id' && styles.textInputFocused]}
                  value={formData.identificationNumber}
                  onChangeText={(value) => setFormData(prev => ({ ...prev, identificationNumber: value }))}
                  placeholder={`Ingresa tu ${selectedPaymentMethod.bank.country.identificationName}`}
                  placeholderTextColor={colors.text.light}
                  keyboardType="numeric"
                  onFocus={() => setFocusedField('id')}
                  onBlur={() => setFocusedField(null)}
                />
                {selectedPaymentMethod.bank.country.identificationFormat && (
                  <Text style={styles.helpText}>Formato: {selectedPaymentMethod.bank.country.identificationFormat}</Text>
                )}
              </View>
            </>
          )}
        </View>

        {/* ── Section: Datos de la cuenta ── */}
        {(fieldCopy.account.show || fieldCopy.phone.show || payoutEmailField.show || providerFieldConfigs.length > 0) && (
          <>
            <Text style={styles.sectionHeader}>Datos de la cuenta</Text>
            <View style={styles.card}>
              {/* Account Number */}
              {fieldCopy.account.show && (
                <View style={styles.fieldInCard}>
                  <Text style={styles.label}>{fieldCopy.account.label}{fieldCopy.account.required ? ' *' : ''}</Text>
                  <TextInput
                    style={[styles.textInput, focusedField === 'account' && styles.textInputFocused]}
                    value={formData.accountNumber}
                    onChangeText={(value) => setFormData(prev => ({ ...prev, accountNumber: value }))}
                    placeholder={fieldCopy.account.placeholder}
                    placeholderTextColor={colors.text.light}
                    keyboardType={fieldCopy.account.keyboardType}
                    maxLength={fieldCopy.account.maxLength}
                    onFocus={() => setFocusedField('account')}
                    onBlur={() => setFocusedField(null)}
                  />
                </View>
              )}

              {/* Phone */}
              {fieldCopy.phone.show && (
                <>
                  {fieldCopy.account.show && <View style={styles.cardDivider} />}
                  <View style={styles.fieldInCard}>
                    <Text style={styles.label}>{fieldCopy.phone.label}{fieldCopy.phone.required ? ' *' : ''}</Text>
                    <TextInput
                      style={[styles.textInput, focusedField === 'phone' && styles.textInputFocused]}
                      value={formData.phoneNumber}
                      onChangeText={(value) => setFormData(prev => ({ ...prev, phoneNumber: value }))}
                      placeholder={fieldCopy.phone.placeholder}
                      placeholderTextColor={colors.text.light}
                      keyboardType={fieldCopy.phone.keyboardType}
                      onFocus={() => setFocusedField('phone')}
                      onBlur={() => setFocusedField(null)}
                    />
                  </View>
                </>
              )}

              {/* Email */}
              {payoutEmailField.show && (
                <>
                  {(fieldCopy.account.show || fieldCopy.phone.show) && <View style={styles.cardDivider} />}
                  <View style={styles.fieldInCard}>
                    <Text style={styles.label}>{payoutEmailField.label}{payoutEmailField.required ? ' *' : ''}</Text>
                    <TextInput
                      style={[styles.textInput, focusedField === 'email' && styles.textInputFocused]}
                      value={formData.email}
                      onChangeText={(value) => setFormData(prev => ({ ...prev, email: value }))}
                      placeholder={payoutEmailField.placeholder}
                      placeholderTextColor={colors.text.light}
                      keyboardType={payoutEmailField.keyboardType}
                      autoCapitalize="none"
                      onFocus={() => setFocusedField('email')}
                      onBlur={() => setFocusedField(null)}
                    />
                  </View>
                </>
              )}

              {/* Provider fields */}
              {providerFieldConfigs.map((field, idx) => {
                const hasPrev = fieldCopy.account.show || fieldCopy.phone.show || payoutEmailField.show || idx > 0;
                if (field.key === 'bankName') {
                  const canUseBankPicker = koyweBankOptions.length > 0;
                  return (
                    <React.Fragment key={field.key}>
                      {hasPrev && <View style={styles.cardDivider} />}
                      <View style={styles.fieldInCard}>
                        <Text style={styles.label}>{field.label}{field.required ? ' *' : ''}</Text>
                        {canUseBankPicker ? (
                          <TouchableOpacity style={styles.picker} onPress={() => setShowProviderBankPicker(true)}>
                            <View style={styles.pickerContent}>
                              {formData.providerMetadata.bankName ? (
                                <Text style={styles.pickerText}>{formData.providerMetadata.bankName}</Text>
                              ) : (
                                <Text style={styles.pickerPlaceholder}>{field.placeholder}</Text>
                              )}
                            </View>
                            <Icon name="chevron-down" size={16} color={colors.text.light} />
                          </TouchableOpacity>
                        ) : (
                          <TextInput
                            style={[styles.textInput, focusedField === field.key && styles.textInputFocused]}
                            value={formData.providerMetadata[field.key] || ''}
                            onChangeText={(value) => setFormData(prev => ({ ...prev, providerMetadata: { ...prev.providerMetadata, [field.key]: value } }))}
                            placeholder={field.placeholder}
                            placeholderTextColor={colors.text.light}
                            autoCapitalize="words"
                            onFocus={() => setFocusedField(field.key)}
                            onBlur={() => setFocusedField(null)}
                          />
                        )}
                        {field.helpText ? <Text style={styles.helpText}>{field.helpText}</Text> : null}
                      </View>
                    </React.Fragment>
                  );
                }
                return (
                  <React.Fragment key={field.key}>
                    {hasPrev && <View style={styles.cardDivider} />}
                    <View style={styles.fieldInCard}>
                      <Text style={styles.label}>{field.label}{field.required ? ' *' : ''}</Text>
                      <TextInput
                        style={[styles.textInput, focusedField === field.key && styles.textInputFocused]}
                        value={formData.providerMetadata[field.key] || ''}
                        onChangeText={(value) => setFormData(prev => ({ ...prev, providerMetadata: { ...prev.providerMetadata, [field.key]: value } }))}
                        placeholder={field.placeholder}
                        placeholderTextColor={colors.text.light}
                        keyboardType={field.keyboardType || 'default'}
                        autoCapitalize="none"
                        onFocus={() => setFocusedField(field.key)}
                        onBlur={() => setFocusedField(null)}
                      />
                      {field.helpText ? <Text style={styles.helpText}>{field.helpText}</Text> : null}
                    </View>
                  </React.Fragment>
                );
              })}
            </View>
          </>
        )}

        {/* ── Section: Tipo de cuenta ── */}
        {showAccountTypeField && (
          <>
            <Text style={styles.sectionHeader}>Tipo de cuenta{accountTypeRequired ? ' *' : ''}</Text>
            <View style={styles.card}>
              {getAccountTypeOptions().map((option, idx) => (
                <React.Fragment key={option.value}>
                  {idx > 0 && <View style={styles.cardDivider} />}
                  <TouchableOpacity
                    style={styles.radioRow}
                    onPress={() => setFormData(prev => ({ ...prev, accountType: option.value }))}
                  >
                    <View style={[styles.radioCircle, formData.accountType === option.value && styles.radioCircleSelected]}>
                      {formData.accountType === option.value && <View style={styles.radioInner} />}
                    </View>
                    <Text style={styles.radioLabel}>{option.label}</Text>
                  </TouchableOpacity>
                </React.Fragment>
              ))}
            </View>
          </>
        )}

        {/* ── Default checkbox ── */}
        <View style={styles.card}>
          <TouchableOpacity
            style={styles.checkboxRow}
            onPress={() => setFormData(prev => ({ ...prev, isDefault: !prev.isDefault }))}
          >
            <View style={[styles.checkbox, formData.isDefault && styles.checkboxSelected]}>
              {formData.isDefault && <Icon name="check" size={13} color="white" />}
            </View>
            <Text style={styles.checkboxLabel}>Marcar como forma de cobro predeterminada</Text>
          </TouchableOpacity>
        </View>

        {/* Bottom spacing so sticky button doesn't overlap */}
        <View style={{ height: 100 }} />
      </ScrollView>

      {/* ── Sticky save button ── */}
      <View style={styles.stickyFooter}>
        <TouchableOpacity
          onPress={handleSubmit}
          disabled={isSubmitting}
          style={[styles.saveButton, isSubmitting && styles.saveButtonDisabled]}
        >
          {isSubmitting ? (
            <ActivityIndicator size="small" color="white" />
          ) : (
            <Text style={styles.saveButtonText}>
              {isEditing ? 'Guardar cambios' : 'Agregar forma de cobro'}
            </Text>
          )}
        </TouchableOpacity>
      </View>

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

  // ── Header ──
  headerWrap: {
    height: 70,
    overflow: 'hidden',
    borderBottomLeftRadius: 24,
    borderBottomRightRadius: 24,
  },
  headerContent: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: 10,
  },
  closeButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: 'rgba(255,255,255,0.2)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitle: {
    fontSize: 17,
    fontWeight: 'bold',
    color: 'white',
  },

  // ── Scroll content ──
  content: {
    flex: 1,
  },
  contentContainer: {
    paddingHorizontal: 16,
    paddingTop: 20,
  },

  // ── Section headers ──
  sectionHeader: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.text.light,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: 8,
    marginLeft: 4,
  },

  // ── Grouped card ──
  card: {
    backgroundColor: 'white',
    borderRadius: 14,
    marginBottom: 20,
    overflow: 'hidden',
    ...Platform.select({
      ios: {
        shadowColor: '#064e3b',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.06,
        shadowRadius: 6,
      },
      android: { elevation: 2 },
    }),
  },
  fieldInCard: {
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  cardDivider: {
    height: 1,
    backgroundColor: colors.neutralDark,
    marginHorizontal: 14,
  },

  // ── Labels & inputs ──
  label: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.text.secondary,
    marginBottom: 6,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  picker: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.background,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.neutralDark,
    paddingHorizontal: 12,
    paddingVertical: 11,
  },
  pickerDisabled: {
    opacity: 0.5,
  },
  pickerContent: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  pickerText: {
    fontSize: 15,
    color: colors.text.primary,
  },
  pickerPlaceholder: {
    fontSize: 15,
    color: colors.text.light,
  },
  countryFlag: {
    fontSize: 20,
    marginRight: 8,
  },
  textInput: {
    backgroundColor: colors.background,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.neutralDark,
    paddingHorizontal: 12,
    paddingVertical: 11,
    fontSize: 15,
    color: colors.text.primary,
  },
  textInputFocused: {
    borderColor: colors.primary,
    borderWidth: 1.5,
  },
  helpText: {
    fontSize: 12,
    color: colors.text.light,
    marginTop: 5,
    lineHeight: 16,
  },
  infoBox: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primaryLight,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  infoText: {
    fontSize: 14,
    color: colors.primaryDark,
    marginLeft: 8,
    flex: 1,
    fontWeight: '500',
  },

  // ── Radio buttons ──
  radioRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 14,
    paddingVertical: 14,
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
    fontSize: 15,
    color: colors.text.primary,
  },

  // ── Checkbox ──
  checkboxRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 14,
    paddingVertical: 14,
  },
  checkbox: {
    width: 22,
    height: 22,
    borderRadius: 6,
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
    fontSize: 15,
    color: colors.text.primary,
    flex: 1,
    lineHeight: 20,
  },

  // ── Sticky footer ──
  stickyFooter: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: 'white',
    borderTopWidth: 1,
    borderTopColor: colors.neutralDark,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: -2 },
        shadowOpacity: 0.06,
        shadowRadius: 4,
      },
      android: { elevation: 4 },
    }),
  },
  saveButton: {
    backgroundColor: colors.primary,
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 50,
  },
  saveButtonDisabled: {
    opacity: 0.6,
  },
  saveButtonText: {
    color: 'white',
    fontWeight: '700',
    fontSize: 16,
  },

  // ── Picker modals ──
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
    fontSize: 17,
    fontWeight: 'bold',
    color: colors.text.primary,
  },
  pickerCancel: {
    fontSize: 16,
    color: colors.primary,
    fontWeight: '600',
  },
  pickerList: {
    flex: 1,
  },
  pickerListContent: {
    paddingBottom: 32,
  },
  scrollHint: {
    backgroundColor: colors.primary + '15',
    paddingVertical: 8,
    paddingHorizontal: 16,
    alignItems: 'center',
  },
  scrollHintText: {
    fontSize: 13,
    color: colors.primaryDark,
    fontStyle: 'italic',
  },
  pickerItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 14,
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
});
