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
import { AddPayoutMethodModal } from '../components/AddPayoutMethodModal';
import {
  GET_ME,
  GET_MY_BALANCES,
  GET_RAMP_AVAILABILITY,
  GET_MY_RAMP_ADDRESS,
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
import { tryFundKoyweOffRampInBackground } from '../services/koyweOffRampService';
import { SellScreen as LegacyGuardarianSellScreen } from './LegacyGuardarianSellScreen';
import { colors } from '../config/theme';
import { isKoyweRoutingEnabledForCountry } from '../config/env';

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

type SavedPayoutMethod = {
  id: string;
  accountHolderName: string;
  summaryText: string;
  paymentMethod?: {
    id: string;
    displayName: string;
  };
  rampPaymentMethod?: {
    id: string;
    displayName: string;
  };
  isDefault: boolean;
};

/* ─── Polished fintech palette (sell variant) ─── */
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
  const [amountFocused, setAmountFocused] = useState(false);

  const countryCode = useMemo(() => {
    const selectedIso = selectedCountry?.[2];
    const userIso = userCountry?.[2];
    return userProfile?.phoneCountry || selectedIso || userIso || 'AR';
  }, [selectedCountry, userCountry, userProfile?.phoneCountry]);

  const isKoyweCountry = isKoyweRoutingEnabledForCountry(countryCode);

  const { data: meData } = useQuery(GET_ME);
  const { data: balancesData, loading: balancesLoading } = useQuery(GET_MY_BALANCES, {
    fetchPolicy: 'cache-and-network',
  });
  const { data: kycData } = useQuery(GET_MY_KYC_STATUS);
  const { data: personalKycData } = useQuery(GET_MY_PERSONAL_KYC_STATUS);
  const { data: rampAddressData, loading: rampAddressLoading } = useQuery(GET_MY_RAMP_ADDRESS, {
    fetchPolicy: 'cache-and-network',
    skip: !isKoyweCountry,
  });
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
  const isBoliviaOffRampUnavailable = isKoyweCountry && availability?.countryCode === 'BO' && !availabilityLoading && methods.length === 0;
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
  const hasCompleteRampAddress = Boolean(rampAddressData?.myRampAddress?.isComplete);

  const savedMethods: SavedPayoutMethod[] = useMemo(() => {
    const accounts = bankAccountsData?.userBankAccounts || [];
    return accounts.filter((account: SavedPayoutMethod) =>
      methods.some((method) => method.paymentMethodId && (account.rampPaymentMethod?.id || account.paymentMethod?.id) === method.paymentMethodId),
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
    return savedMethods.filter((account) => (account.rampPaymentMethod?.id || account.paymentMethod?.id) === selectedMethod.paymentMethodId);
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
    if (rampAddressLoading) {
      Alert.alert('Verificando dirección', 'Espera un momento mientras validamos tu dirección para recargas y retiros.');
      return;
    }
    if (!hasCompleteRampAddress) {
      Alert.alert(
        'Completa tu dirección',
        'Antes de continuar, necesitamos tu dirección para habilitar las recargas y retiros bancarios.',
        [
          { text: 'Ahora no', style: 'cancel' },
          { text: 'Completar', onPress: () => navigation.navigate('RampAddress') },
        ],
      );
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
    if (!hasCompleteRampAddress) {
      Alert.alert(
        'Completa tu dirección',
        'Antes de confirmar, necesitamos tu dirección para habilitar las recargas y retiros bancarios.',
        [
          { text: 'Ahora no', style: 'cancel' },
          { text: 'Completar', onPress: () => navigation.navigate('RampAddress') },
        ],
      );
      return;
    }

    setIsSubmittingOrder(true);
    try {
      const { data } = await createRampOrder({
        variables: {
          direction: 'OFF_RAMP',
          amount: String(parsedAmount),
          countryCode: availability?.countryCode,
          fiatCurrency,
          paymentMethodCode: selectedMethod.code,
          bankInfoId: selectedSavedMethod.id,
        },
      });

      const result = data?.createRampOrder;
      if (!result?.success || !result?.orderId) {
        Alert.alert('No se pudo crear la orden', getFriendlyRampError(result?.error));
        return;
      }

      let autoFundingWarning: string | null = null;
      if (String(result.nextStep || '').toUpperCase() === 'WAIT_FOR_USDC_TRANSFER') {
        const fundingResult = await tryFundKoyweOffRampInBackground({
          amount: parsedAmount,
          paymentDetails: result.paymentDetails,
          providerOrderId: result.orderId,
          activeAccount,
        });

        if (fundingResult.status === 'failed') {
          autoFundingWarning = fundingResult.reason === 'invalid_amount'
            ? 'No pudimos iniciar el envío automático del retiro.'
            : `No pudimos iniciar el envío automático del retiro: ${fundingResult.reason}.`;
        } else if (fundingResult.status === 'skipped') {
          autoFundingWarning = 'No pudimos iniciar el envío automático porque Koywe no devolvió un destino compatible con Algorand.';
        }
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

      if (autoFundingWarning) {
        Alert.alert('Retiro creado', autoFundingWarning);
      }
    } catch (error: any) {
      Alert.alert('No se pudo crear la orden', getFriendlyRampError(error?.message));
    } finally {
      setIsSubmittingOrder(false);
    }
  };

  if (!isKoyweCountry) {
    return <LegacyGuardarianSellScreen />;
  }

  if (isBoliviaOffRampUnavailable) {
    return (
      <SafeAreaView style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor="#10b981" />
        <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
          <RampReveal delay={0}>
            <RampHero
              eyebrow="Retirar saldo"
              title="Retiro en BOB no disponible"
              subtitle="Por ahora en Bolivia solo está habilitada la Recarga. Cuando Koywe habilite retiros en BOB, aparecerán aquí."
              onBack={() => navigation.goBack()}
              compact={isCompact}
              fromColor={colors.primaryDark}
              toColor={colors.primary}
            />
          </RampReveal>

          <RampReveal delay={80}>
            <View style={styles.emptyStateCard}>
              <View style={styles.emptyStateIconWrap}>
                <Icon name="info" size={22} color={colors.primaryDark} />
              </View>
              <Text style={styles.emptyStateTitle}>{countryFlag ? `${countryFlag} ` : ''}Solo Recarga disponible</Text>
              <Text style={styles.emptyStateText}>
                Aún no puedes retirar a bolivianos desde Confío. Si quieres agregar saldo en Bolivia, usa Recarga con QR interoperable.
              </Text>
              <TouchableOpacity style={styles.primaryActionButton} onPress={() => navigation.replace('TopUp')}>
                <Text style={styles.primaryActionButtonText}>Ir a Recarga</Text>
              </TouchableOpacity>
            </View>
          </RampReveal>
        </ScrollView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor="#10b981" />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {/* ─── Hero with gradient ─── */}
        <RampReveal delay={0}>
        <RampHero
          eyebrow="Retirar saldo"
          title="Vende tus Confío Dollar"
          subtitle="Elige cómo quieres recibir tu dinero, revisa el estimado y confirma al final."
          onBack={() => navigation.goBack()}
          compact={isCompact}
          fromColor={colors.primaryDark}
          toColor={colors.primary}
        />
        </RampReveal>

        {/* ─── Info banner ─── */}
        <RampReveal delay={60}>
        <View style={styles.bannerCard}>
          <View style={styles.bannerIconWrap}>
            <Icon name="shield" size={16} color={colors.primary} />
          </View>
          <View style={styles.bannerCopy}>
            <Text style={styles.bannerTitle}>{countryFlag ? `${countryFlag} ` : ''}Datos de cobro</Text>
            <Text style={styles.bannerText}>
              Puedes guardar tu cuenta o billetera para no volver a cargarla en próximos retiros.
            </Text>
          </View>
          <TouchableOpacity
            style={styles.historyPill}
            onPress={() => navigation.navigate('RampHistory', { initialFilter: 'off_ramp' })}
            activeOpacity={0.8}
          >
            <Icon name="clock" size={14} color={colors.primary} />
            <Text style={styles.historyPillText}>Ver retiros</Text>
          </TouchableOpacity>
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
                metaColor={colors.textSecondary}
              />
              <View style={styles.inputCard}>
                <Text style={styles.inputLabel}>Monto a retirar en cUSD</Text>
                <View style={[styles.amountInputRow, amountFocused && styles.amountInputRowFocused]}>
                  <TextInput
                    style={styles.amountInput}
                    value={amount}
                    onChangeText={(value) => {
                      setAmount(value);
                      setStep('form');
                    }}
                    onFocus={() => setAmountFocused(true)}
                    onBlur={() => setAmountFocused(false)}
                    keyboardType="decimal-pad"
                    placeholder="0"
                    placeholderTextColor={colors.textSecondary}
                  />
                  <View style={styles.currencyBadge}>
                    <Text style={styles.currencyBadgeText}>cUSD</Text>
                  </View>
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
                        {selected
                          ? <Icon name="check" size={13} color="#ffffff" />
                          : null}
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
                  <Icon name="plus-circle" size={15} color={colors.primaryDark} />
                  <Text style={styles.addButtonText}>Agregar</Text>
                </TouchableOpacity>
              </View>
              {bankAccountsLoading ? (
                <ActivityIndicator color={colors.primary} />
              ) : compatibleSavedMethods.length === 0 ? (
                <View style={styles.emptyCard}>
                  <Icon name="inbox" size={22} color={colors.textSecondary} />
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
                    <Icon name="alert-circle" size={20} color={colors.textSecondary} />
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
                      <Text style={styles.quoteLabel}>Tipo de cambio</Text>
                      <Text style={styles.quoteValue}>{`${formatRampRate(quote.exchangeRate)} ${fiatCurrency}/cUSD`}</Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>{'Comisión del\nprocesador de pagos'}</Text>
                      <Text style={styles.quoteValue}>{formatRampMoney(String(Number(quote.feeAmount || 0) + Number(quote.networkFeeAmount || 0)), quote.feeCurrency)}</Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>Comisión de Confío</Text>
                      <View style={styles.gratisBadge}>
                        <Text style={styles.gratisBadgeText}>Gratis</Text>
                      </View>
                    </View>
                    <View style={styles.disclaimerPill}>
                      <Icon name="info" size={12} color={colors.primaryDark} />
                      <Text style={styles.quoteNote}>La cotización puede cambiar antes de confirmar.</Text>
                    </View>
                  </>
                ) : (
                  <View style={styles.emptyQuote}>
                    <Icon name="bar-chart-2" size={20} color={colors.textSecondary} />
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
                <Text style={styles.reviewTitle}>Revisión final</Text>
                <View style={styles.reviewRow}>
                  <Icon name="credit-card" size={16} color={colors.textSecondary} />
                  <Text style={styles.reviewLabel}>Forma de cobro</Text>
                  <Text style={styles.reviewValue}>{selectedMethod?.displayName}</Text>
                </View>
                <View style={styles.reviewRow}>
                  <Icon name="briefcase" size={16} color={colors.textSecondary} />
                  <Text style={styles.reviewLabel}>Destino</Text>
                  <Text style={styles.reviewValue}>{selectedSavedMethod?.summaryText}</Text>
                </View>
                <View style={styles.reviewRow}>
                  <Icon name="dollar-sign" size={16} color={colors.textSecondary} />
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
        <AddPayoutMethodModal
          isVisible={showAddMethodModal}
          onClose={() => setShowAddMethodModal(false)}
          onSuccess={() => {
            setShowAddMethodModal(false);
            refetchBankAccounts();
            refetchAvailability({ countryCode });
          }}
          accountId={activeAccount?.id || null}
          editingPayoutMethod={null}
          initialCountryCode={countryCode}
          allowedCountryCodes={[countryCode]}
          allowedPaymentMethodIds={methods.map((method) => method.paymentMethodId).filter(Boolean) as string[]}
          initialPaymentMethodId={selectedMethod?.paymentMethodId || null}
          lockCountry={true}
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
    backgroundColor: '#f0fdf4',
    borderRadius: 16,
    padding: 16,
    marginHorizontal: 22,
    marginBottom: 20,
    gap: 12,
    borderWidth: 1,
    borderColor: '#bbf7d0',
    shadowColor: '#10B981',
    shadowOpacity: 0.08,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  bannerIconWrap: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: 'rgba(5,150,105,0.12)',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 2,
  },
  bannerCopy: {
    flex: 1,
  },
  historyPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    alignSelf: 'center',
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: '#bbf7d0',
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  historyPillText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.primary,
  },
  bannerTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.primaryDark,
    marginBottom: 4,
  },
  bannerText: {
    fontSize: 13,
    lineHeight: 19,
    color: colors.textFlat,
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
    color: colors.textSecondary,
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
    backgroundColor: colors.primaryLight,
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
    color: colors.textSecondary,
    fontWeight: '600',
    fontSize: 13,
  },
  fallbackTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.dark,
  },
  fallbackText: {
    color: colors.textSecondary,
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
    color: colors.textSecondary,
    marginBottom: 8,
  },
  amountInputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: 14,
    borderWidth: 1.5,
    borderColor: 'transparent',
    paddingHorizontal: 2,
    paddingVertical: 2,
    marginHorizontal: -2,
  },
  amountInputRowFocused: {
    borderColor: colors.primary,
    backgroundColor: '#f0fdf4',
    borderRadius: 14,
    paddingHorizontal: 8,
  },
  amountInput: {
    flex: 1,
    fontSize: 32,
    fontWeight: '700',
    color: colors.dark,
    paddingVertical: 4,
  },
  currencyBadge: {
    backgroundColor: colors.primaryLight,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 5,
    marginLeft: 8,
  },
  currencyBadgeText: {
    fontSize: 13,
    fontWeight: '800',
    color: colors.primaryDark,
    letterSpacing: 0.4,
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
    color: colors.textSecondary,
    lineHeight: 18,
    marginTop: 10,
    fontSize: 13,
  },
  limitText: {
    color: colors.textSecondary,
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
    borderWidth: 1.5,
    borderColor: '#eef2f7',
    shadowColor: '#111827',
    shadowOpacity: 0.05,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  methodCardSelected: {
    backgroundColor: colors.primaryDark,
    borderColor: colors.primaryDark,
    borderWidth: 2,
    shadowColor: colors.primaryDark,
    shadowOpacity: 0.22,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 6 },
    elevation: 4,
  },
  methodCopy: {
    flex: 1,
    gap: 2,
  },
  methodIcon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  methodIconSelected: {
    backgroundColor: 'rgba(255,255,255,0.2)',
  },
  methodTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.dark,
  },
  methodTitleSelected: {
    color: '#ffffff',
  },
  methodText: {
    color: colors.textSecondary,
    lineHeight: 18,
    fontSize: 13,
  },
  methodTextSelected: {
    color: 'rgba(255,255,255,0.75)',
  },

  /* ── Radio button ── */
  radioOuter: {
    width: 24,
    height: 24,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  radioOuterSelected: {
    borderColor: 'rgba(255,255,255,0.5)',
    backgroundColor: 'rgba(255,255,255,0.18)',
  },
  radioInner: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#ffffff',
  },

  /* ── Add button ── */
  addButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#ecfdf5',
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: '#a7f3d0',
  },
  addButtonText: {
    color: colors.primaryDark,
    fontWeight: '700',
    fontSize: 13,
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
    color: colors.textSecondary,
    lineHeight: 18,
    textAlign: 'center',
    fontSize: 13,
  },
  emptyStateCard: {
    backgroundColor: colors.surface,
    borderRadius: 22,
    padding: 22,
    marginHorizontal: 22,
    marginTop: 4,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#d1fae5',
    shadowColor: '#111827',
    shadowOpacity: 0.06,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
    elevation: 3,
  },
  emptyStateIconWrap: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 14,
  },
  emptyStateTitle: {
    fontWeight: '800',
    color: colors.dark,
    textAlign: 'center',
    fontSize: 20,
  },
  emptyStateText: {
    color: colors.textSecondary,
    lineHeight: 22,
    textAlign: 'center',
    fontSize: 15,
    marginTop: 10,
  },
  primaryActionButton: {
    marginTop: 18,
    minWidth: 180,
    paddingHorizontal: 18,
    paddingVertical: 14,
    borderRadius: 16,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryActionButtonText: {
    color: colors.surface,
    fontWeight: '800',
    fontSize: 15,
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
    backgroundColor: colors.primaryLight,
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
    color: colors.textSecondary,
    fontSize: 13,
  },

  /* ── Quote card ── */
  quoteCard: {
    backgroundColor: '#f0fdf8',
    borderRadius: 20,
    padding: 20,
    gap: 10,
    borderWidth: 1.5,
    borderColor: '#6ee7b7',
    shadowColor: '#10B981',
    shadowOpacity: 0.14,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 8 },
    elevation: 4,
  },
  quoteHeadline: {
    fontSize: 34,
    fontWeight: '800',
    color: colors.primaryDark,
    lineHeight: 40,
  },
  quoteHeadlineCompact: {
    fontSize: 28,
    lineHeight: 34,
  },
  quoteEyebrow: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    color: colors.primaryDark,
  },
  quoteRate: {
    color: colors.textSecondary,
    fontSize: 13,
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
    color: colors.textSecondary,
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
    backgroundColor: '#ecfdf5',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    gap: 8,
    marginTop: 4,
    borderWidth: 1,
    borderColor: '#a7f3d0',
  },
  quoteNote: {
    color: colors.primaryDark,
    lineHeight: 18,
    fontSize: 12,
    flex: 1,
  },
  gratisBadge: {
    backgroundColor: colors.primaryLight,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  gratisBadgeText: {
    fontSize: 12,
    fontWeight: '800',
    color: colors.primaryDark,
    letterSpacing: 0.3,
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
    borderWidth: 1,
    borderColor: '#d1fae5',
    borderLeftWidth: 5,
    borderLeftColor: colors.primary,
    shadowColor: colors.primary,
    shadowOpacity: 0.12,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
    elevation: 4,
  },
  reviewTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.dark,
  },
  reviewRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    paddingVertical: 6,
  },
  reviewLabel: {
    flex: 0.95,
    color: colors.textSecondary,
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
