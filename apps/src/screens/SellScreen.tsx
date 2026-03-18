import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Modal,
  Platform,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  useWindowDimensions,
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
  GET_RAMP_AVAILABILITY,
  GET_MY_KYC_STATUS,
  GET_MY_PERSONAL_KYC_STATUS,
  GET_USER_BANK_ACCOUNTS,
} from '../apollo/queries';
import { getPaymentMethodIcon } from '../utils/paymentMethodIcons';
import { getCountryByIso } from '../utils/countries';
import { getFriendlyRampError } from '../utils/rampErrors';
import { requestRampCriticalAuth } from '../utils/rampFlow';
import { formatRampMoney, formatRampRate, useRampQuoteFlow, validateRampContinue } from '../hooks/useRampQuoteFlow';
import { RampActionBar } from '../components/ramps/RampActionBar';
import { RampHero } from '../components/ramps/RampHero';
import { RampReveal } from '../components/ramps/RampReveal';
import { RampStepHeader } from '../components/ramps/RampStepHeader';
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

export const SellScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { width } = useWindowDimensions();
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
  } = useQuery(GET_RAMP_AVAILABILITY, {
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

  const availability = availabilityData?.rampAvailability;
  const methods: RampMethod[] = availability?.offRampMethods || [];
  const derivedCountryTuple = useMemo(() => getCountryByIso(countryCode), [countryCode]);
  const fiatCurrency = availability?.fiatCurrency || 'USD';
  const countryFlag = derivedCountryTuple ? (derivedCountryTuple as readonly string[])[3] || '' : '';
  const isKoyweMapped = isKoyweCountry && !!availability?.offRampEnabled && methods.length > 0;
  const selectedMethod = useMemo(
    () => methods.find((method) => method.code === selectedMethodCode) || methods[0] || null,
    [methods, selectedMethodCode],
  );
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
  const {
    parsedAmount,
    amountReady,
    quote,
    quoteLoading,
    quoteError,
  } = useRampQuoteFlow({
    direction: 'OFF_RAMP',
    amount,
    countryCode: availability?.countryCode,
    fiatCurrency,
    paymentMethodCode: selectedMethod?.code,
    enabled: isKoyweMapped,
  });
  const quoteHeadline = quote ? `Recibes aprox. ${formatRampMoney(quote.amountOut, fiatCurrency)}` : '';
  const quoteRateLine = quote ? `1 cUSD = ${formatRampRate(quote.exchangeRate, fiatCurrency)}` : '';
  const isCompact = width < 380;
  const isBelowSellMin = amountReady && selectedMethodMin > 0 && parsedAmount < selectedMethodMin;
  const isAboveSellMax = amountReady && effectiveSellMax > 0 && parsedAmount > effectiveSellMax;
  const sellAmountError = isBelowSellMin
    ? `El mínimo por operación es ${formatRampMoney(String(selectedMethodMin), 'cUSD')}.`
    : isAboveSellMax
      ? availableCusdBalance > 0 && effectiveSellMax === availableCusdBalance && selectedMethodMax >= availableCusdBalance
        ? `Tu saldo disponible es ${formatRampMoney(String(availableCusdBalance), 'cUSD')}.`
        : `El máximo permitido es ${formatRampMoney(String(effectiveSellMax), 'cUSD')}.`
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
    const continueError = validateRampContinue({
      hasSelectedMethod: !!selectedMethod,
      amountReady,
      quoteLoading,
      quoteError,
      quote,
      amountError: sellAmountError,
    });
    if (continueError) {
      const title =
        continueError === 'Selecciona un método' ? 'Selecciona un método'
          : continueError === 'Monto inválido' ? 'Monto inválido'
            : continueError === 'Cotización en proceso' ? 'Cotización en proceso'
              : continueError === 'Cotización no disponible' ? 'Cotización no disponible'
                : continueError.includes('mínimo') || continueError.includes('máximo') || continueError.includes('saldo disponible') ? 'Monto fuera de rango'
                  : 'No pudimos cotizar';
      Alert.alert(title, continueError);
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

  const handleConfirm = async () => {
    if (!selectedMethod || !selectedSavedMethod || !quote) {
      return;
    }
    const authenticated = await requestRampCriticalAuth({
      amount: parsedAmount,
      assetLabel: 'cUSD',
      actionLabel: 'retiro',
    });
    if (!authenticated) {
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
        if (!result?.success || !result?.orderId) {
          Alert.alert('No se pudo crear la orden', getFriendlyRampError(result?.error));
          return;
        }
        navigation.replace('RampInstructions', {
          direction: 'OFF_RAMP',
          orderId: result.orderId,
          countryCode: availability?.countryCode,
          paymentMethodCode: selectedMethod.code,
          paymentMethodDisplay: result.paymentMethodDisplay || selectedMethod.displayName,
          amountOut: result.amountOut || undefined,
          fiatCurrency,
          destinationSummary: selectedSavedMethod?.summaryText || undefined,
          nextActionUrl: result.nextActionUrl || undefined,
          paymentDetails: result.paymentDetails,
        });
      })
      .catch((error) => {
        Alert.alert('No se pudo crear la orden', getFriendlyRampError(error?.message));
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
        <RampReveal delay={0}>
        <RampHero
          eyebrow="Retirar saldo"
          title="Vende tus Confío Dollar"
          subtitle="Elige cómo quieres recibir tu dinero, revisa el estimado y confirma al final."
          onBack={() => navigation.goBack()}
          compact={isCompact}
          fromColor={colors.heroFrom}
          toColor={colors.heroTo}
        />
        </RampReveal>

        {/* ─── Info banner ─── */}
        <RampReveal delay={60}>
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
        </RampReveal>

        {availabilityLoading ? (
          <View style={styles.loadingCard}>
            <ActivityIndicator color={colors.primary} size="small" />
            <Text style={styles.loadingText}>Cargando retiros para {countryFlag ? `${countryFlag} ` : ''}{countryCode}...</Text>
          </View>
        ) : (
          <>
            {/* ─── Step 1: Amount ─── */}
            <RampReveal delay={110}>
            <View style={styles.section}>
              <RampStepHeader
                number={1}
                title="Monto"
                meta={`${countryFlag ? `${countryFlag} ` : ''}${availability.countryName} · ${fiatCurrency}`}
                accentColor={colors.primaryDark}
                accentBackground={colors.primaryLight}
                titleColor={colors.dark}
                metaColor={colors.textMuted}
              />
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
                  Saldo disponible: {balancesLoading ? 'Cargando...' : formatRampMoney(String(availableCusdBalance), 'cUSD')}
                </Text>
                <Text style={styles.limitText}>
                  Mínimo: {selectedMethodMin > 0 ? formatRampMoney(String(selectedMethodMin), 'cUSD') : '--'} · Máximo por operación: {effectiveSellMax > 0 ? formatRampMoney(String(effectiveSellMax), 'cUSD') : '--'}
                </Text>
                {sellAmountError ? <Text style={styles.errorText}>{sellAmountError}</Text> : null}
              </View>
            </View>
            </RampReveal>

            {/* ─── Step 2: Receive method ─── */}
            <RampReveal delay={150}>
            <View style={styles.section}>
              <RampStepHeader
                number={2}
                title="Cómo recibirás el dinero"
                accentColor={colors.primaryDark}
                accentBackground={colors.primaryLight}
                titleColor={colors.dark}
              />
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
            </RampReveal>

            {/* ─── Step 3: Bank details ─── */}
            <RampReveal delay={190}>
            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <View style={styles.sectionHeaderContent}>
                  <RampStepHeader
                    number={3}
                    title="Datos de cobro"
                    accentColor={colors.primaryDark}
                    accentBackground={colors.primaryLight}
                    titleColor={colors.dark}
                  />
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
            </RampReveal>

            {/* ─── Step 4: Quote summary ─── */}
            <RampReveal delay={230}>
            <View style={styles.section}>
              <RampStepHeader
                number={4}
                title="Resumen"
                accentColor={colors.primaryDark}
                accentBackground={colors.primaryLight}
                titleColor={colors.dark}
              />
              <View style={styles.quoteCard}>
                {quoteLoading ? (
                  <ActivityIndicator color={colors.primary} />
                ) : quoteError ? (
                  <View style={styles.emptyQuote}>
                    <Icon name="alert-circle" size={20} color={colors.textLight} />
                    <Text style={styles.emptyText}>{quoteError.message || 'No pudimos obtener la cotización de Koywe.'}</Text>
                  </View>
                ) : quote ? (
                  <>
                    <Text style={styles.quoteEyebrow}>Estimado de retiro</Text>
                    <Text style={[styles.quoteHeadline, isCompact && styles.quoteHeadlineCompact]}>{quoteHeadline}</Text>
                    <Text style={styles.quoteRate}>{quoteRateLine}</Text>
                    <View style={styles.quoteDivider} />
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>Envías</Text>
                      <Text style={styles.quoteValue}>{formatRampMoney(quote.amountIn, 'cUSD')}</Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>Recibes aprox.</Text>
                      <Text style={styles.quoteValue}>{formatRampMoney(quote.amountOut, fiatCurrency)}</Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>{'Comisión del\nprocesador de pagos'}</Text>
                      <Text style={styles.quoteValue}>{formatRampMoney(String(Number(quote.feeAmount || 0) + Number(quote.networkFeeAmount || 0)), quote.feeCurrency)}</Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>Comisión de Confío</Text>
                      <Text style={[styles.quoteValue, { color: colors.primary }]}>
                        {formatRampMoney(0, quote.feeCurrency || fiatCurrency)}
                      </Text>
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
            </RampReveal>

            {/* ─── Action buttons ─── */}
            {step === 'review' ? (
              <RampReveal delay={270}>
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
                <RampActionBar
                  primaryLabel="Confirmar retiro"
                  onPrimaryPress={handleConfirm}
                  primaryLoading={isSubmittingOrder}
                  secondaryLabel="Editar retiro"
                  onSecondaryPress={() => setStep('form')}
                />
              </View>
              </RampReveal>
            ) : (
              <RampReveal delay={270}>
              <RampActionBar
                primaryLabel={isVerified ? 'Continuar' : 'Continuar y verificar'}
                onPrimaryPress={handleContinue}
                primaryDisabled={Boolean(sellAmountError) || balancesLoading || quoteLoading}
                primaryIconName={isVerified ? 'chevron-right' : 'shield'}
              />
              </RampReveal>
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
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: 12,
    gap: 12,
  },
  sectionHeaderContent: {
    flex: 1,
  },
  /* ── Input card ── */
  inputCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 20,
    borderWidth: 1,
    borderColor: '#d1fae5',
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
    borderWidth: 1,
    borderColor: '#eef2f7',
    shadowColor: '#111827',
    shadowOpacity: 0.05,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  methodCardSelected: {
    backgroundColor: colors.primaryUltraLight,
    borderColor: '#a7f3d0',
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
    borderWidth: 1,
    borderColor: '#eef2f7',
    shadowColor: '#111827',
    shadowOpacity: 0.05,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  savedCardSelected: {
    backgroundColor: colors.primaryUltraLight,
    borderColor: '#a7f3d0',
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
    borderWidth: 1,
    borderColor: '#d1fae5',
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
    lineHeight: 34,
  },
  quoteHeadlineCompact: {
    fontSize: 24,
    lineHeight: 30,
  },
  quoteEyebrow: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    color: colors.primaryDark,
  },
  quoteRate: {
    color: colors.textMuted,
    fontSize: 14,
    lineHeight: 20,
  },
  quoteDivider: {
    height: 1,
    backgroundColor: colors.border,
    marginVertical: 4,
  },
  quoteRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 18,
    paddingVertical: 4,
  },
  quoteLabel: {
    color: colors.textMuted,
    fontSize: 14,
    lineHeight: 20,
    flex: 1,
  },
  quoteValue: {
    color: colors.dark,
    fontWeight: '700',
    fontSize: 14,
    lineHeight: 20,
    flex: 1,
    textAlign: 'right',
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
    alignItems: 'flex-start',
    gap: 10,
    paddingVertical: 6,
  },
  reviewLabel: {
    flex: 0.95,
    color: colors.textMuted,
    fontSize: 14,
    lineHeight: 20,
  },
  reviewValue: {
    flex: 1.15,
    color: colors.dark,
    fontWeight: '600',
    fontSize: 14,
    lineHeight: 20,
    textAlign: 'right',
  },
  reviewValueHighlight: {
    flex: 1.15,
    color: colors.primary,
    fontWeight: '800',
    fontSize: 16,
    lineHeight: 22,
    textAlign: 'right',
  },
});
