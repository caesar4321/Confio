import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Linking,
  Modal,
  Platform,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useMutation, useQuery } from '@apollo/client';

import { MainStackParamList } from '../types/navigation';
import { useAccount } from '../contexts/AccountContext';
import { useAuth } from '../contexts/AuthContext';
import { useCountry } from '../contexts/CountryContext';
import { AddBankInfoModal } from '../components/AddBankInfoModal';
import {
  GET_ME,
  GET_MY_BALANCES,
  GET_MOCK_RAMP_AVAILABILITY,
  GET_MOCK_RAMP_QUOTE,
  GET_MY_KYC_STATUS,
  GET_MY_PERSONAL_KYC_STATUS,
  GET_USER_BANK_ACCOUNTS,
} from '../apollo/queries';
import { getPaymentMethodIcon } from '../utils/paymentMethodIcons';
import { getCountryByIso } from '../utils/countries';
import { Gradient } from '../components/common/Gradient';
import { CREATE_RAMP_ORDER } from '../apollo/mutations';
import { SellScreen as LegacyGuardarianSellScreen } from './LegacyGuardarianSellScreen';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'Sell'>;

type RampMethod = {
  paymentMethodId?: string | null;
  code: string;
  displayName: string;
  description: string;
  providerType: string;
  icon?: string | null;
  requiresPhone: boolean;
  requiresEmail: boolean;
  requiresAccountNumber: boolean;
  requiresIdentification: boolean;
  supportsOnRamp: boolean;
  supportsOffRamp: boolean;
  fiatCurrency: string;
  onRampMinAmount?: string | null;
  onRampMaxAmount?: string | null;
  offRampMinAmount?: string | null;
  offRampMaxAmount?: string | null;
};

type SavedBankInfo = {
  id: string;
  accountHolderName: string;
  summaryText: string;
  paymentMethod?: {
    id: string;
    displayName: string;
  };
  isDefault: boolean;
};

/* ─── Polished fintech palette (sell variant) ─── */
const colors = {
  dark: '#111827',
  textPrimary: '#1f2937',
  textMuted: '#6b7280',
  textLight: '#9ca3af',
  border: '#e5e7eb',
  background: '#f0fdf4',
  surface: '#ffffff',
  surfaceAlt: '#f3f4f6',
  primary: '#059669',
  primaryDark: '#047857',
  primaryMid: '#10b981',
  primaryLight: '#d1fae5',
  primaryUltraLight: '#ecfdf5',
  accent: '#3b82f6',
  accentLight: '#dbeafe',
  warning: '#f59e0b',
  warningLight: '#fef3c7',
  success: '#15803d',
  danger: '#b91c1c',
  dangerLight: '#fee2e2',
  heroFrom: '#047857',
  heroTo: '#34d399',
};

const formatMoney = (value?: string | null, code?: string | null) => {
  const parsed = Number(value || 0);
  if (!Number.isFinite(parsed)) {
    return '--';
  }
  return `${parsed.toLocaleString('es-AR', {
    minimumFractionDigits: parsed >= 100 ? 0 : 2,
    maximumFractionDigits: 2,
  })} ${code || ''}`.trim();
};
/* ─── Friendly currency names ─── */
const currencyNames: Record<string, string> = {
  COP: 'pesos colombianos',
  ARS: 'pesos argentinos',
  PEN: 'soles peruanos',
  CLP: 'pesos chilenos',
  MXN: 'pesos mexicanos',
  BRL: 'reales brasileños',
  UYU: 'pesos uruguayos',
  BOB: 'bolivianos',
  PYG: 'guaraníes',
  VES: 'bolívares',
  USD: 'dólares',
  EUR: 'euros',
};
const friendlyCurrency = (code: string) => currencyNames[code] || code;
const KOYWE_SUPPORTED_COUNTRIES = new Set(['AR', 'BO', 'BR', 'CL', 'CO', 'MX', 'PE', 'US']);

/* ─── Clean server display strings ─── */
const cleanDisplay = (text?: string | null): string => {
  if (!text) return '';
  return text.replace(/->/g, ' ').replace(/\u2192/g, ' ').replace(/\s{2,}/g, ' ').trim();
};

const formatRate = (value?: string | null, code?: string | null) => {
  const parsed = Number(value || 0);
  if (!Number.isFinite(parsed)) {
    return '--';
  }
  return `${parsed.toLocaleString('es-AR', {
    minimumFractionDigits: parsed >= 100 ? 2 : 4,
    maximumFractionDigits: 4,
  })} ${code || ''}`.trim();
};

/* ─── Step badge component ─── */
const StepBadge = ({ number }: { number: number }) => (
  <View style={styles.stepBadge}>
    <Text style={styles.stepBadgeText}>{number}</Text>
  </View>
);

export const SellScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { activeAccount } = useAccount();
  const { userProfile } = useAuth() as any;
  const { selectedCountry, userCountry } = useCountry();

  const [amount, setAmount] = useState('');
  const [selectedMethodCode, setSelectedMethodCode] = useState<string | null>(null);
  const [selectedSavedMethodId, setSelectedSavedMethodId] = useState<string | null>(null);
  const [showAddMethodModal, setShowAddMethodModal] = useState(false);
  const [step, setStep] = useState<'form' | 'review'>('form');
  const [isSubmittingOrder, setIsSubmittingOrder] = useState(false);

  const countryCode = useMemo(() => {
    const selectedIso = selectedCountry?.[2];
    const userIso = userCountry?.[2];
    return userProfile?.phoneCountry || selectedIso || userIso || 'AR';
  }, [selectedCountry, userCountry, userProfile?.phoneCountry]);

  const isKoyweCountry = KOYWE_SUPPORTED_COUNTRIES.has(countryCode);

  const { data: meData } = useQuery(GET_ME);
  const { data: balancesData, loading: balancesLoading } = useQuery(GET_MY_BALANCES, {
    fetchPolicy: 'cache-and-network',
  });
  const { data: kycData } = useQuery(GET_MY_KYC_STATUS);
  const { data: personalKycData } = useQuery(GET_MY_PERSONAL_KYC_STATUS);
  const {
    data: availabilityData,
    loading: availabilityLoading,
    refetch: refetchAvailability,
  } = useQuery(GET_MOCK_RAMP_AVAILABILITY, {
    variables: { countryCode },
    fetchPolicy: 'cache-and-network',
    skip: !isKoyweCountry,
  });
  const {
    data: bankAccountsData,
    loading: bankAccountsLoading,
    refetch: refetchBankAccounts,
  } = useQuery(GET_USER_BANK_ACCOUNTS, {
    fetchPolicy: 'cache-and-network',
  });

  const availability = availabilityData?.mockRampAvailability;
  const methods: RampMethod[] = availability?.offRampMethods || [];
  const derivedCountryTuple = useMemo(() => getCountryByIso(countryCode), [countryCode]);
  const fiatCurrency = availability?.fiatCurrency || 'USD';
  const countryFlag = derivedCountryTuple ? (derivedCountryTuple as readonly string[])[3] || '' : '';
  const isKoyweMapped = isKoyweCountry && !!availability?.offRampEnabled && methods.length > 0;
  const parsedAmount = Number((amount || '').replace(',', '.'));
  const quoteEnabled = Number.isFinite(parsedAmount) && parsedAmount > 0 && !!availability?.countryCode;

  const { data: quoteData, loading: quoteLoading } = useQuery(GET_MOCK_RAMP_QUOTE, {
    variables: {
      direction: 'OFF_RAMP',
      amount: String(parsedAmount || ''),
      countryCode: availability?.countryCode,
      fiatCurrency,
    },
    skip: !isKoyweMapped || !quoteEnabled,
    fetchPolicy: 'cache-and-network',
  });

  const quote = quoteData?.mockRampQuote;
  const quoteHeadline = quote ? `Recibes aprox. ${formatMoney(quote.amountOut, fiatCurrency)}` : '';
  const quoteRateLine = quote ? `1 cUSD = ${formatRate(quote.exchangeRate, fiatCurrency)}` : '';
  const [createRampOrder] = useMutation(CREATE_RAMP_ORDER);
  const isVerified = useMemo(() => {
    const candidates = [
      personalKycData?.myPersonalKycStatus?.status,
      kycData?.myKycStatus?.status,
      meData?.me?.verificationStatus,
    ]
      .filter(Boolean)
      .map((status: string) => status.toLowerCase());
    return candidates.includes('verified') || meData?.me?.isIdentityVerified;
  }, [kycData?.myKycStatus?.status, meData?.me?.isIdentityVerified, meData?.me?.verificationStatus, personalKycData?.myPersonalKycStatus?.status]);

  const savedMethods: SavedBankInfo[] = useMemo(() => {
    const accounts = bankAccountsData?.userBankAccounts || [];
    return accounts.filter((account: SavedBankInfo) =>
      methods.some((method) => method.paymentMethodId && account.paymentMethod?.id === method.paymentMethodId),
    );
  }, [bankAccountsData?.userBankAccounts, methods]);

  const selectedMethod = useMemo(
    () => methods.find((method) => method.code === selectedMethodCode) || methods[0] || null,
    [methods, selectedMethodCode],
  );
  const availableCusdBalance = useMemo(() => Number(balancesData?.myBalances?.cusd || 0), [balancesData?.myBalances?.cusd]);
  const selectedMethodMin = Number(selectedMethod?.offRampMinAmount || 0);
  const selectedMethodMax = Number(selectedMethod?.offRampMaxAmount || 0);
  const effectiveSellMax = useMemo(() => {
    if (selectedMethodMax > 0 && availableCusdBalance > 0) {
      return Math.min(selectedMethodMax, availableCusdBalance);
    }
    if (selectedMethodMax > 0) return selectedMethodMax;
    return availableCusdBalance;
  }, [availableCusdBalance, selectedMethodMax]);
  const isBelowSellMin = quoteEnabled && selectedMethodMin > 0 && parsedAmount < selectedMethodMin;
  const isAboveSellMax = quoteEnabled && effectiveSellMax > 0 && parsedAmount > effectiveSellMax;
  const sellAmountError = isBelowSellMin
    ? `El mínimo por operación es ${formatMoney(String(selectedMethodMin), 'cUSD')}.`
    : isAboveSellMax
      ? availableCusdBalance > 0 && effectiveSellMax === availableCusdBalance && selectedMethodMax >= availableCusdBalance
        ? `Tu saldo disponible es ${formatMoney(String(availableCusdBalance), 'cUSD')}.`
        : `El máximo permitido es ${formatMoney(String(effectiveSellMax), 'cUSD')}.`
      : null;

  const compatibleSavedMethods = useMemo(() => {
    if (!selectedMethod?.paymentMethodId) {
      return [];
    }
    return savedMethods.filter((account) => account.paymentMethod?.id === selectedMethod.paymentMethodId);
  }, [savedMethods, selectedMethod?.paymentMethodId]);

  const selectedSavedMethod = useMemo(
    () =>
      compatibleSavedMethods.find((account) => account.id === selectedSavedMethodId) ||
      compatibleSavedMethods.find((account) => account.isDefault) ||
      compatibleSavedMethods[0] ||
      null,
    [compatibleSavedMethods, selectedSavedMethodId],
  );

  useEffect(() => {
    if (!selectedMethodCode && methods.length > 0) {
      setSelectedMethodCode(methods[0].code);
    }
  }, [methods, selectedMethodCode]);

  useEffect(() => {
    if (selectedSavedMethod?.id) {
      setSelectedSavedMethodId(selectedSavedMethod.id);
    } else {
      setSelectedSavedMethodId(null);
    }
  }, [selectedMethod?.paymentMethodId]);

  const promptVerification = () => {
    Alert.alert(
      'Verificación requerida',
      'Antes de confirmar tu retiro, necesitamos validar tu identidad.',
      [
        { text: 'Ahora no', style: 'cancel' },
        { text: 'Ir a Didit', onPress: () => navigation.navigate('Verification') },
      ],
    );
  };

  const handleContinue = () => {
    if (!selectedMethod) {
      Alert.alert('Selecciona un método', 'Elige cómo quieres recibir tu dinero.');
      return;
    }
    if (!quoteEnabled || !quote) {
      Alert.alert('Monto inválido', 'Ingresa cuánto quieres retirar.');
      return;
    }
    if (sellAmountError) {
      Alert.alert('Monto fuera de rango', sellAmountError);
      return;
    }
    if (!selectedSavedMethod) {
      Alert.alert('Faltan datos', 'Antes de continuar necesitas guardar la cuenta o billetera donde vas a recibir el dinero.');
      return;
    }
    if (!isVerified) {
      promptVerification();
      return;
    }
    setStep('review');
  };

  const handleConfirm = () => {
    if (!selectedMethod || !selectedSavedMethod || !quote) {
      return;
    }

    setIsSubmittingOrder(true);
    createRampOrder({
      variables: {
        direction: 'OFF_RAMP',
        amount: String(parsedAmount),
        countryCode: availability?.countryCode,
        fiatCurrency,
        paymentMethodCode: selectedMethod.code,
        bankInfoId: selectedSavedMethod.id,
      },
    })
      .then(({ data }) => {
        const result = data?.createRampOrder;
        if (!result?.success) {
          Alert.alert('No se pudo crear la orden', result?.error || 'Inténtalo nuevamente.');
          return;
        }

        Alert.alert(
          'Orden creada',
          `Orden ${result.orderId}\n\nCobro por ${selectedMethod.displayName} hacia ${selectedSavedMethod.summaryText}.\nRecibirías aproximadamente ${formatMoney(result.amountOut, fiatCurrency)}.`,
          result.nextActionUrl
            ? [
                { text: 'Más tarde', style: 'cancel' },
                { text: 'Abrir proveedor', onPress: () => Linking.openURL(result.nextActionUrl) },
              ]
            : [{ text: 'OK', onPress: () => setStep('form') }],
        );
      })
      .catch((error) => {
        Alert.alert('No se pudo crear la orden', error?.message || 'Inténtalo nuevamente.');
      })
      .finally(() => {
        setIsSubmittingOrder(false);
      });
  };

  if (!isKoyweCountry) {
    return <LegacyGuardarianSellScreen />;
  }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroFrom} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {/* ─── Hero with gradient ─── */}
        <View style={styles.heroWrapper}>
          <Gradient fromColor={colors.heroFrom} toColor={colors.heroTo} style={styles.heroGradient}>
            <View style={styles.heroPadding}>
              <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
                <Icon name="arrow-left" size={20} color={colors.surface} />
              </TouchableOpacity>
              <Text style={styles.eyebrow}>Retirar saldo</Text>
              <Text style={styles.title}>Vende tus Confío Dollar</Text>
              <Text style={styles.subtitle}>Elige cómo quieres recibir tu dinero, revisa el estimado y confirma al final.</Text>
            </View>
          </Gradient>
        </View>

        {/* ─── Info banner ─── */}
        <View style={styles.bannerCard}>
          <View style={styles.bannerIconWrap}>
            <Icon name="shield" size={16} color={colors.accent} />
          </View>
          <View style={styles.bannerCopy}>
            <Text style={styles.bannerTitle}>{countryFlag ? `${countryFlag} ` : ''}Datos de cobro</Text>
            <Text style={styles.bannerText}>
              Puedes guardar tu cuenta o billetera para no volver a cargarla en próximos retiros.
            </Text>
          </View>
        </View>

        {availabilityLoading ? (
          <View style={styles.loadingCard}>
            <ActivityIndicator color={colors.primary} size="small" />
            <Text style={styles.loadingText}>Cargando retiros para {countryFlag ? `${countryFlag} ` : ''}{countryCode}...</Text>
          </View>
        ) : (
          <>
            {/* ─── Step 1: Amount ─── */}
            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <View style={styles.sectionHeaderLeft}>
                  <StepBadge number={1} />
                  <Text style={styles.sectionTitle}>Monto</Text>
                </View>
                <Text style={styles.sectionMeta}>{countryFlag ? `${countryFlag} ` : ''}{availability.countryName} · {fiatCurrency}</Text>
              </View>
              <View style={styles.inputCard}>
                <Text style={styles.inputLabel}>Monto a retirar en cUSD</Text>
                <View style={styles.amountInputRow}>
                  <TextInput
                    style={styles.amountInput}
                    value={amount}
                    onChangeText={(value) => {
                      setAmount(value);
                      setStep('form');
                    }}
                    keyboardType="decimal-pad"
                    placeholder="0"
                    placeholderTextColor={colors.textLight}
                  />
                  <Text style={styles.currencySuffix}>cUSD</Text>
                  <TouchableOpacity
                    style={[styles.maxPill, (!effectiveSellMax || balancesLoading) && styles.maxPillDisabled]}
                    onPress={() => {
                      if (effectiveSellMax > 0) {
                        setAmount(String(Number(effectiveSellMax.toFixed(2))));
                        setStep('form');
                      }
                    }}
                    disabled={!effectiveSellMax || balancesLoading}
                  >
                    <Text style={styles.maxPillText}>Max</Text>
                  </TouchableOpacity>
                </View>
                <Text style={styles.helperText}>Verás cuánto recibirías y el tipo de cambio estimado antes de confirmar.</Text>
                <Text style={styles.limitText}>
                  Saldo disponible: {balancesLoading ? 'Cargando...' : formatMoney(String(availableCusdBalance), 'cUSD')}
                </Text>
                <Text style={styles.limitText}>
                  Mínimo: {selectedMethodMin > 0 ? formatMoney(String(selectedMethodMin), 'cUSD') : '--'} · Máximo por operación: {effectiveSellMax > 0 ? formatMoney(String(effectiveSellMax), 'cUSD') : '--'}
                </Text>
                {sellAmountError ? <Text style={styles.errorText}>{sellAmountError}</Text> : null}
              </View>
            </View>

            {/* ─── Step 2: Receive method ─── */}
            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <View style={styles.sectionHeaderLeft}>
                  <StepBadge number={2} />
                  <Text style={styles.sectionTitle}>Cómo recibirás el dinero</Text>
                </View>
              </View>
              <View style={styles.methodList}>
                {methods.map((method) => {
                  const selected = selectedMethod?.code === method.code;
                  return (
                    <TouchableOpacity
                      key={method.code}
                      style={[styles.methodCard, selected && styles.methodCardSelected]}
                      onPress={() => setSelectedMethodCode(method.code)}
                      activeOpacity={0.7}
                    >
                      <View style={[styles.methodIcon, selected && styles.methodIconSelected]}>
                        <Icon name={getPaymentMethodIcon(method.icon, method.providerType, method.displayName)} size={18} color={selected ? colors.surface : colors.primary} />
                      </View>
                      <View style={styles.methodCopy}>
                        <Text style={[styles.methodTitle, selected && styles.methodTitleSelected]}>{method.displayName}</Text>
                        <Text style={[styles.methodText, selected && styles.methodTextSelected]}>{method.description}</Text>
                      </View>
                      <View style={[styles.radioOuter, selected && styles.radioOuterSelected]}>
                        {selected && <View style={styles.radioInner} />}
                      </View>
                    </TouchableOpacity>
                  );
                })}
              </View>
            </View>

            {/* ─── Step 3: Bank details ─── */}
            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <View style={styles.sectionHeaderLeft}>
                  <StepBadge number={3} />
                  <Text style={styles.sectionTitle}>Datos de cobro</Text>
                </View>
                <TouchableOpacity style={styles.addButton} onPress={() => setShowAddMethodModal(true)}>
                  <Icon name="plus-circle" size={16} color={colors.accent} />
                  <Text style={styles.addButtonText}>Agregar</Text>
                </TouchableOpacity>
              </View>
              {bankAccountsLoading ? (
                <ActivityIndicator color={colors.primary} />
              ) : compatibleSavedMethods.length === 0 ? (
                <View style={styles.emptyCard}>
                  <Icon name="inbox" size={22} color={colors.textLight} />
                  <Text style={styles.emptyTitle}>Todavía no guardaste datos para {selectedMethod?.displayName}</Text>
                  <Text style={styles.emptyText}>Agrega tu cuenta o billetera antes de confirmar el retiro.</Text>
                </View>
              ) : (
                compatibleSavedMethods.map((account) => {
                  const selected = selectedSavedMethod?.id === account.id;
                  return (
                    <TouchableOpacity
                      key={account.id}
                      style={[styles.savedCard, selected && styles.savedCardSelected]}
                      onPress={() => setSelectedSavedMethodId(account.id)}
                      activeOpacity={0.7}
                    >
                      <View style={styles.savedCopy}>
                        <Text style={styles.savedTitle}>{account.accountHolderName}</Text>
                        <Text style={styles.savedText}>{account.summaryText}</Text>
                      </View>
                      <View style={[styles.radioOuter, selected && styles.radioOuterSelected]}>
                        {selected && <View style={styles.radioInner} />}
                      </View>
                    </TouchableOpacity>
                  );
                })
              )}
            </View>

            {/* ─── Step 4: Quote summary ─── */}
            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <View style={styles.sectionHeaderLeft}>
                  <StepBadge number={4} />
                  <Text style={styles.sectionTitle}>Resumen</Text>
                </View>
              </View>
              <View style={styles.quoteCard}>
                {quoteLoading ? (
                  <ActivityIndicator color={colors.primary} />
                ) : quote ? (
                  <>
                    <Text style={styles.quoteHeadline}>{quoteHeadline}</Text>
                    <Text style={styles.quoteRate}>{quoteRateLine}</Text>
                    <View style={styles.quoteDivider} />
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>Envías</Text>
                      <Text style={styles.quoteValue}>{formatMoney(quote.amountIn, 'cUSD')}</Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>Recibes aprox.</Text>
                      <Text style={styles.quoteValue}>{formatMoney(quote.amountOut, fiatCurrency)}</Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>{'Comisión del\nprocesador de pagos'}</Text>
                      <Text style={styles.quoteValue}>{formatMoney(String(Number(quote.feeAmount || 0) + Number(quote.networkFeeAmount || 0)), quote.feeCurrency)}</Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>Comisión de Confío</Text>
                      <Text style={[styles.quoteValue, { color: colors.primary }]}>0 {quote.feeCurrency || fiatCurrency}</Text>
                    </View>
                    <View style={styles.disclaimerPill}>
                      <Icon name="info" size={12} color={colors.accent} />
                      <Text style={styles.quoteNote}>La cotización puede cambiar antes de confirmar.</Text>
                    </View>
                  </>
                ) : (
                  <View style={styles.emptyQuote}>
                    <Icon name="bar-chart-2" size={20} color={colors.textLight} />
                    <Text style={styles.emptyText}>Ingresa el monto para ver el retiro estimado.</Text>
                  </View>
                )}
              </View>
            </View>

            {/* ─── Action buttons ─── */}
            {step === 'review' ? (
              <View style={styles.reviewCard}>
                <View style={styles.reviewAccent} />
                <Text style={styles.reviewTitle}>Revisión final</Text>
                <View style={styles.reviewRow}>
                  <Icon name="credit-card" size={16} color={colors.textMuted} />
                  <Text style={styles.reviewLabel}>Forma de cobro</Text>
                  <Text style={styles.reviewValue}>{selectedMethod?.displayName}</Text>
                </View>
                <View style={styles.reviewRow}>
                  <Icon name="briefcase" size={16} color={colors.textMuted} />
                  <Text style={styles.reviewLabel}>Destino</Text>
                  <Text style={styles.reviewValue}>{selectedSavedMethod?.summaryText}</Text>
                </View>
                <View style={styles.reviewRow}>
                  <Icon name="dollar-sign" size={16} color={colors.textMuted} />
                  <Text style={styles.reviewLabel}>Recibirías</Text>
                  <Text style={styles.reviewValueHighlight}>{quoteHeadline}</Text>
                </View>
                <TouchableOpacity
                  style={[styles.primaryButton, isSubmittingOrder && styles.primaryButtonDisabled]}
                  onPress={handleConfirm}
                  activeOpacity={0.8}
                  disabled={isSubmittingOrder}
                >
                  {isSubmittingOrder ? <ActivityIndicator color={colors.surface} /> : <Text style={styles.primaryButtonText}>Confirmar retiro</Text>}
                </TouchableOpacity>
                <TouchableOpacity style={styles.ghostButton} onPress={() => setStep('form')} activeOpacity={0.7}>
                  <Text style={styles.ghostButtonText}>Editar retiro</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <TouchableOpacity style={[styles.primaryButton, (sellAmountError || balancesLoading) && styles.primaryButtonDisabled]} onPress={handleContinue} activeOpacity={0.8} disabled={Boolean(sellAmountError) || balancesLoading}>
                <Icon name={isVerified ? 'chevron-right' : 'shield'} size={18} color={colors.surface} style={{ marginRight: 8 }} />
                <Text style={styles.primaryButtonText}>{isVerified ? 'Continuar' : 'Continuar y verificar'}</Text>
              </TouchableOpacity>
            )}
          </>
        )}
      </ScrollView>

      <Modal
        visible={showAddMethodModal}
        animationType="slide"
        presentationStyle={Platform.OS === 'ios' ? 'pageSheet' : 'fullScreen'}
        onRequestClose={() => setShowAddMethodModal(false)}
      >
        <AddBankInfoModal
          isVisible={showAddMethodModal}
          onClose={() => setShowAddMethodModal(false)}
          onSuccess={() => {
            setShowAddMethodModal(false);
            refetchBankAccounts();
            refetchAvailability({ countryCode });
          }}
          accountId={activeAccount?.id || null}
          editingBankInfo={null}
          initialCountryCode={countryCode}
          allowedCountryCodes={[countryCode]}
          allowedPaymentMethodIds={methods.map((method) => method.paymentMethodId).filter(Boolean) as string[]}
          initialPaymentMethodId={selectedMethod?.paymentMethodId || null}
          lockCountry={true}
          mode="off_ramp"
        />
      </Modal>
    </SafeAreaView>
  );
};

/* ─── Styles ─── */
const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    paddingBottom: 60,
  },

  /* ── Hero ── */
  heroWrapper: {
    borderBottomLeftRadius: 28,
    borderBottomRightRadius: 28,
    overflow: 'hidden',
    marginBottom: 20,
  },
  heroGradient: {
    borderBottomLeftRadius: 28,
    borderBottomRightRadius: 28,
  },
  heroPadding: {
    paddingHorizontal: 24,
    paddingTop: Platform.OS === 'android' ? (StatusBar.currentHeight || 24) + 12 : 16,
    paddingBottom: 28,
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.18)',
    marginBottom: 16,
  },
  eyebrow: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1,
    textTransform: 'uppercase',
    color: 'rgba(255,255,255,0.75)',
    marginBottom: 6,
  },
  title: {
    fontSize: 26,
    fontWeight: '800',
    color: '#ffffff',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 14,
    lineHeight: 21,
    color: 'rgba(255,255,255,0.8)',
  },

  /* ── Banner card ── */
  bannerCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: colors.accentLight,
    borderRadius: 16,
    padding: 16,
    marginHorizontal: 22,
    marginBottom: 20,
    gap: 12,
    shadowColor: '#3b82f6',
    shadowOpacity: 0.08,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  bannerIconWrap: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: 'rgba(59,130,246,0.12)',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 2,
  },
  bannerCopy: {
    flex: 1,
  },
  bannerTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.accent,
    marginBottom: 4,
  },
  bannerText: {
    fontSize: 13,
    lineHeight: 19,
    color: colors.textPrimary,
  },

  /* ── Loading ── */
  loadingCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 28,
    marginHorizontal: 22,
    alignItems: 'center',
    gap: 12,
    shadowColor: '#111827',
    shadowOpacity: 0.06,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  loadingText: {
    color: colors.textMuted,
    fontSize: 14,
  },

  /* ── Fallback (Guardarian) ── */
  fallbackCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 20,
    marginHorizontal: 22,
    gap: 14,
    shadowColor: '#111827',
    shadowOpacity: 0.06,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
    elevation: 3,
  },
  providerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  providerBadge: {
    backgroundColor: colors.primaryUltraLight,
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: 999,
  },
  providerBadgeText: {
    color: colors.primary,
    fontWeight: '700',
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  providerHint: {
    color: colors.textMuted,
    fontWeight: '600',
    fontSize: 13,
  },
  fallbackTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.dark,
  },
  fallbackText: {
    color: colors.textMuted,
    lineHeight: 20,
    fontSize: 14,
  },

  /* ── Step sections ── */
  section: {
    marginBottom: 24,
    paddingHorizontal: 22,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  sectionHeaderLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  stepBadge: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepBadgeText: {
    color: '#ffffff',
    fontSize: 13,
    fontWeight: '800',
  },
  sectionTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: colors.dark,
  },
  sectionMeta: {
    color: colors.textMuted,
    fontSize: 13,
  },

  /* ── Input card ── */
  inputCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 20,
    shadowColor: '#111827',
    shadowOpacity: 0.06,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
    elevation: 3,
  },
  inputLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textMuted,
    marginBottom: 8,
  },
  amountInputRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  amountInput: {
    flex: 1,
    fontSize: 32,
    fontWeight: '700',
    color: colors.dark,
    paddingVertical: 4,
  },
  currencySuffix: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.textLight,
    marginLeft: 8,
  },
  maxPill: {
    marginLeft: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: colors.primaryLight,
  },
  maxPillDisabled: {
    opacity: 0.45,
  },
  maxPillText: {
    fontSize: 12,
    fontWeight: '800',
    color: colors.primaryDark,
  },
  helperText: {
    color: colors.textMuted,
    lineHeight: 18,
    marginTop: 10,
    fontSize: 13,
  },
  limitText: {
    color: colors.textMuted,
    lineHeight: 18,
    marginTop: 8,
    fontSize: 12,
  },
  errorText: {
    color: colors.danger,
    lineHeight: 18,
    marginTop: 8,
    fontSize: 12,
    fontWeight: '600',
  },

  /* ── Method cards ── */
  methodList: {
    gap: 10,
  },
  methodCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    shadowColor: '#111827',
    shadowOpacity: 0.05,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  methodCardSelected: {
    backgroundColor: colors.primaryUltraLight,
    shadowColor: colors.primary,
    shadowOpacity: 0.12,
  },
  methodCopy: {
    flex: 1,
    gap: 2,
  },
  methodIcon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.primaryUltraLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  methodIconSelected: {
    backgroundColor: colors.primary,
  },
  methodTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.dark,
  },
  methodTitleSelected: {
    color: colors.primaryDark,
  },
  methodText: {
    color: colors.textMuted,
    lineHeight: 18,
    fontSize: 13,
  },
  methodTextSelected: {
    color: colors.textMuted,
  },

  /* ── Radio button ── */
  radioOuter: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 2,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  radioOuterSelected: {
    borderColor: colors.primary,
  },
  radioInner: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.primary,
  },

  /* ── Add button ── */
  addButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  addButtonText: {
    color: colors.accent,
    fontWeight: '700',
    fontSize: 14,
  },

  /* ── Empty state ── */
  emptyCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 20,
    gap: 8,
    alignItems: 'center',
    shadowColor: '#111827',
    shadowOpacity: 0.04,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 1,
  },
  emptyTitle: {
    fontWeight: '700',
    color: colors.dark,
    textAlign: 'center',
  },
  emptyText: {
    color: colors.textMuted,
    lineHeight: 18,
    textAlign: 'center',
    fontSize: 13,
  },

  /* ── Saved method cards ── */
  savedCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 14,
    marginTop: 8,
    shadowColor: '#111827',
    shadowOpacity: 0.05,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  savedCardSelected: {
    backgroundColor: colors.primaryUltraLight,
    shadowColor: colors.primary,
    shadowOpacity: 0.12,
  },
  savedCopy: {
    flex: 1,
    gap: 4,
  },
  savedTitle: {
    fontWeight: '700',
    color: colors.dark,
  },
  savedText: {
    color: colors.textMuted,
    fontSize: 13,
  },

  /* ── Quote card ── */
  quoteCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 20,
    gap: 10,
    shadowColor: '#111827',
    shadowOpacity: 0.06,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
    elevation: 3,
  },
  quoteHeadline: {
    fontSize: 28,
    fontWeight: '800',
    color: colors.dark,
  },
  quoteRate: {
    color: colors.textMuted,
    fontSize: 14,
  },
  quoteDivider: {
    height: 1,
    backgroundColor: colors.border,
    marginVertical: 4,
  },
  quoteRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 4,
  },
  quoteLabel: {
    color: colors.textMuted,
    fontSize: 14,
  },
  quoteValue: {
    color: colors.dark,
    fontWeight: '700',
    fontSize: 14,
  },
  disclaimerPill: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.accentLight,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    gap: 8,
    marginTop: 4,
  },
  quoteNote: {
    color: colors.accent,
    lineHeight: 18,
    fontSize: 12,
    flex: 1,
  },
  emptyQuote: {
    alignItems: 'center',
    gap: 8,
    paddingVertical: 8,
  },

  /* ── Review card ── */
  reviewCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 20,
    marginHorizontal: 22,
    gap: 14,
    shadowColor: '#111827',
    shadowOpacity: 0.08,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
    elevation: 3,
    overflow: 'hidden',
  },
  reviewAccent: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    height: 4,
    backgroundColor: colors.primary,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
  },
  reviewTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.dark,
    marginTop: 4,
  },
  reviewRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 6,
  },
  reviewLabel: {
    flex: 1,
    color: colors.textMuted,
    fontSize: 14,
  },
  reviewValue: {
    color: colors.dark,
    fontWeight: '600',
    fontSize: 14,
  },
  reviewValueHighlight: {
    color: colors.primary,
    fontWeight: '800',
    fontSize: 16,
  },

  /* ── Buttons ── */
  primaryButton: {
    backgroundColor: colors.primary,
    borderRadius: 16,
    paddingVertical: 16,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    marginHorizontal: 22,
    shadowColor: colors.primary,
    shadowOpacity: 0.3,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 4,
  },
  primaryButtonDisabled: {
    opacity: 0.65,
  },
  primaryButtonText: {
    color: colors.surface,
    fontWeight: '700',
    fontSize: 16,
  },
  ghostButton: {
    borderRadius: 16,
    paddingVertical: 14,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1.5,
    borderColor: colors.border,
  },
  ghostButtonText: {
    color: colors.textPrimary,
    fontWeight: '700',
    fontSize: 15,
  },
});
