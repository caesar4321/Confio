import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Modal,
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
import { useAuth } from '../contexts/AuthContext';
import { useCountry } from '../contexts/CountryContext';
import {
  GET_ME,
  GET_RAMP_AVAILABILITY,
  GET_MY_RAMP_ADDRESS,
  GET_MY_KYC_STATUS,
  GET_MY_PERSONAL_KYC_STATUS,
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
import LegacyGuardarianTopUpScreen from './LegacyGuardarianTopUpScreen';
import { useBackupEnforcement } from '../hooks/useBackupEnforcement';
import { colors } from '../config/theme';
import { isKoyweRoutingEnabledForCountry } from '../config/env';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'TopUp'>;

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
const TopUpScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { width } = useWindowDimensions();
  const { userProfile } = useAuth() as any;
  const { selectedCountry, userCountry } = useCountry();
  const { checkBackupEnforcement, BackupEnforcementModal } = useBackupEnforcement();

  const [amount, setAmount] = useState('');
  const [selectedMethodCode, setSelectedMethodCode] = useState<string | null>(null);
  const [step, setStep] = useState<'form' | 'review'>('form');
  const [isSubmittingOrder, setIsSubmittingOrder] = useState(false);
  const [amountFocused, setAmountFocused] = useState(false);
  const [showAuthEmailModal, setShowAuthEmailModal] = useState(false);
  const [authEmailInput, setAuthEmailInput] = useState('');
  const [authEmailError, setAuthEmailError] = useState<string | null>(null);

  const countryCode = useMemo(() => {
    const selectedIso = selectedCountry?.[2];
    const userIso = userCountry?.[2];
    return userProfile?.phoneCountry || selectedIso || userIso || 'AR';
  }, [selectedCountry, userCountry, userProfile?.phoneCountry]);

  const isKoyweCountry = isKoyweRoutingEnabledForCountry(countryCode);

  const { data: meData } = useQuery(GET_ME);
  const { data: kycData } = useQuery(GET_MY_KYC_STATUS);
  const { data: personalKycData } = useQuery(GET_MY_PERSONAL_KYC_STATUS);
  const { data: rampAddressData, loading: rampAddressLoading } = useQuery(GET_MY_RAMP_ADDRESS, {
    fetchPolicy: 'cache-and-network',
    skip: !isKoyweCountry,
  });
  const { data: availabilityData, loading: availabilityLoading } = useQuery(GET_RAMP_AVAILABILITY, {
    variables: { countryCode },
    fetchPolicy: 'cache-and-network',
    skip: !isKoyweCountry,
  });

  const availability = availabilityData?.rampAvailability;
  const methods: RampMethod[] = availability?.onRampMethods || [];
  const derivedCountryTuple = useMemo(() => getCountryByIso(countryCode), [countryCode]);
  const fiatCurrency = availability?.fiatCurrency || 'USD';
  const countryFlag = derivedCountryTuple ? (derivedCountryTuple as readonly string[])[3] || '' : '';
  const isKoyweMapped = isKoyweCountry && !!availability?.onRampEnabled && methods.length > 0;
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
  }, [
    kycData?.myKycStatus?.status,
    meData?.me?.isIdentityVerified,
    meData?.me?.verificationStatus,
    personalKycData?.myPersonalKycStatus?.status,
  ]);
  const hasCompleteRampAddress = Boolean(rampAddressData?.myRampAddress?.isComplete);
  const selectedMethodMin = Number(selectedMethod?.onRampMinAmount || 0);
  const selectedMethodMax = Number(selectedMethod?.onRampMaxAmount || 0);
  const {
    parsedAmount,
    amountReady,
    quote,
    quoteLoading,
    quoteError,
    amountError: topUpAmountError,
  } = useRampQuoteFlow({
    direction: 'ON_RAMP',
    amount,
    countryCode: availability?.countryCode,
    fiatCurrency,
    paymentMethodCode: selectedMethod?.code,
    enabled: isKoyweMapped,
    minAmount: selectedMethodMin,
    maxAmount: selectedMethodMax,
  });
  const quoteHeadline = quote ? `Recibes aprox. ${formatRampMoney(quote.amountOut, 'cUSD')}` : '';
  const quoteRateLine = quote ? `1 cUSD = ${formatRampRate(quote.exchangeRate, fiatCurrency)}` : '';
  const isCompact = width < 380;
  const accountEmail = String(meData?.me?.email || userProfile?.email || '').trim();
  const normalizedSelectedMethodCode = String(selectedMethod?.code || '').trim().toUpperCase();
  const isAppleRelayEmail = /@privaterelay\.appleid\.com$/i.test(accountEmail);
  const requiresRealEmailForPse = countryCode === 'CO' && ['PSE', 'NEQUI', 'BANCOLOMBIA'].includes(normalizedSelectedMethodCode) && isAppleRelayEmail;

  useEffect(() => {
    if (!selectedMethodCode && methods.length > 0) {
      setSelectedMethodCode(methods[0].code);
    }
  }, [methods, selectedMethodCode]);

  useEffect(() => {
    if (!showAuthEmailModal) {
      return;
    }
    if (!authEmailInput.trim() && accountEmail && !isAppleRelayEmail) {
      setAuthEmailInput(accountEmail);
    }
  }, [accountEmail, authEmailInput, isAppleRelayEmail, showAuthEmailModal]);

  const isValidEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());

  const submitRampOrder = async (authEmailOverride?: string | null) => {
    if (!selectedMethod || !quote) {
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
    createRampOrder({
      variables: {
        direction: 'ON_RAMP',
        amount: String(parsedAmount),
        countryCode: availability?.countryCode,
        fiatCurrency,
        paymentMethodCode: selectedMethod.code,
        authEmail: authEmailOverride || undefined,
      },
    })
      .then(({ data }) => {
        const result = data?.createRampOrder;
        if (!result?.success || !result?.orderId) {
          Alert.alert('No se pudo crear la orden', getFriendlyRampError(result?.error));
          return;
        }
        navigation.replace('RampInstructions', {
          direction: 'ON_RAMP',
          orderId: result.orderId,
          countryCode: availability?.countryCode,
          paymentMethodCode: selectedMethod.code,
          paymentMethodDisplay: result.paymentMethodDisplay || selectedMethod.displayName,
          amountOut: result.amountOut || undefined,
          fiatCurrency,
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

  const openVerificationPrompt = () => {
    Alert.alert(
      'Verificación requerida',
      'Antes de confirmar tu compra, necesitamos validar tu identidad.',
      [
        { text: 'Ahora no', style: 'cancel' },
        { text: 'Verificar ahora', onPress: () => navigation.navigate('Verification') },
      ],
    );
  };

  const handleContinue = () => {
    void (async () => {
      const backupAllowed = await checkBackupEnforcement('deposit');
      if (!backupAllowed) {
        return;
      }

      const continueError = validateRampContinue({
        hasSelectedMethod: !!selectedMethod,
        amountReady,
        quoteLoading,
        quoteError,
        quote,
        amountError: topUpAmountError,
      });
      if (continueError) {
        const title =
          continueError === 'Selecciona un método' ? 'Selecciona un método'
            : continueError === 'Monto inválido' ? 'Monto inválido'
              : continueError === 'Cotización en proceso' ? 'Cotización en proceso'
                : continueError === 'Cotización no disponible' ? 'Cotización no disponible'
                  : continueError.includes('mínimo') || continueError.includes('máximo') ? 'Monto fuera de rango'
                    : 'No pudimos cotizar';
        Alert.alert(title, continueError);
        return;
      }
      if (!isVerified) {
        openVerificationPrompt();
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
    })();
  };

  const handleConfirm = async () => {
    if (!selectedMethod || !quote) {
      return;
    }
    if (requiresRealEmailForPse) {
      setAuthEmailError(null);
      setAuthEmailInput('');
      setShowAuthEmailModal(true);
      return;
    }
    const authenticated = await requestRampCriticalAuth({
      amount: parsedAmount,
      assetLabel: 'cUSD',
      actionLabel: 'compra',
    });
    if (!authenticated) {
      return;
    }
    await submitRampOrder();
  };

  if (!isKoyweCountry) {
    return <LegacyGuardarianTopUpScreen />;
  }

  const renderMethodCard = (method: RampMethod) => {
    const selected = selectedMethod?.code === method.code;
    return (
      <TouchableOpacity
        key={method.code}
        style={[styles.methodCard, selected && styles.methodCardSelected]}
        onPress={() => setSelectedMethodCode(method.code)}
        activeOpacity={0.7}
      >
        <View style={[styles.methodIconWrap, selected && styles.methodIconWrapSelected]}>
          <Icon
            name={getPaymentMethodIcon(method.icon, method.providerType, method.displayName)}
            size={18}
            color={selected ? colors.surface : colors.primary}
          />
        </View>
        <View style={styles.methodCopy}>
          <Text style={[styles.methodTitle, selected && styles.methodTitleSelected]}>{method.displayName}</Text>
          <Text style={[styles.methodDescription, selected && styles.methodDescriptionSelected]}>{method.description}</Text>
        </View>
        <View style={[styles.radioOuter, selected && styles.radioOuterSelected]}>
          {selected
            ? <Icon name="check" size={13} color="#ffffff" />
            : null}
        </View>
      </TouchableOpacity>
    );
  };

  return (
    <>
      <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor="#10b981" />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <RampReveal delay={0}>
        <RampHero
          eyebrow="Ingresar saldo"
          title="Compra Confío Dollar"
          subtitle="Elige tu medio de pago, revisa la cotización y confirma cuando estés listo."
          onBack={() => navigation.goBack()}
          compact={isCompact}
          fromColor={colors.primaryDark}
          toColor={colors.primary}
        />
        </RampReveal>

        <RampReveal delay={60}>
        <View style={styles.noticeCard}>
          <View style={styles.noticeIconWrap}>
            <Icon name="globe" size={16} color={colors.primary} />
          </View>
          <View style={styles.noticeCopy}>
            <Text style={styles.noticeTitle}>{countryFlag ? `${countryFlag} ` : ''}Según tu país</Text>
            <Text style={styles.noticeText}>Te mostramos los medios de pago disponibles para {availability?.countryName || countryCode}.</Text>
          </View>
          <TouchableOpacity
            style={styles.historyPill}
            onPress={() => navigation.navigate('RampHistory', { initialFilter: 'on_ramp' })}
            activeOpacity={0.8}
          >
            <Icon name="clock" size={14} color={colors.primary} />
            <Text style={styles.historyPillText}>Ver recargas</Text>
          </TouchableOpacity>
        </View>
        </RampReveal>

        {availabilityLoading ? (
          <View style={styles.loadingCard}>
            <ActivityIndicator color={colors.primary} size="small" />
            <Text style={styles.loadingText}>Cargando opciones para {countryFlag ? `${countryFlag} ` : ''}{countryCode}...</Text>
          </View>
        ) : !isKoyweMapped ? (
          <View style={styles.loadingCard}>
            <Text style={styles.loadingText}>Todavía no encontramos medios disponibles para este país.</Text>
          </View>
        ) : (
          <>
            <RampReveal delay={110}>
            <View style={styles.section}>
              <RampStepHeader
                number={1}
                title="Monto"
                meta={`${countryFlag ? `${countryFlag} ` : ''}${availability.countryName} · ${fiatCurrency}`}
                accentColor={colors.primaryDark}
                accentBackground={colors.primaryLight}
                titleColor={colors.textFlat}
                metaColor={colors.textSecondary}
              />
              <View style={styles.amountCard}>
                <Text style={styles.inputLabel}>Monto estimado en {friendlyCurrency(fiatCurrency)}</Text>
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
                    <Text style={styles.currencyBadgeText}>{fiatCurrency}</Text>
                  </View>
                </View>
                <Text style={styles.helperText}>Verás cuánto recibirías y el tipo de cambio estimado antes de confirmar.</Text>
                {selectedMethodMin > 0 || selectedMethodMax > 0 ? (
                  <Text style={styles.limitText}>
                    Mínimo: {selectedMethodMin > 0 ? formatRampMoney(String(selectedMethodMin), fiatCurrency) : '--'} · Máximo por operación: {selectedMethodMax > 0 ? formatRampMoney(String(selectedMethodMax), fiatCurrency) : '--'}
                  </Text>
                ) : null}
                {topUpAmountError ? <Text style={styles.errorText}>{topUpAmountError}</Text> : null}
              </View>
            </View>
            </RampReveal>

            <RampReveal delay={150}>
            <View style={styles.section}>
              <RampStepHeader
                number={2}
                title="Medio de pago"
                accentColor={colors.primaryDark}
                accentBackground={colors.primaryLight}
                titleColor={colors.textFlat}
              />
              <Text style={styles.sectionHint}>Selecciona cómo quieres pagar.</Text>
              <View style={styles.methodsGrid}>{methods.map(renderMethodCard)}</View>
            </View>
            </RampReveal>

            <RampReveal delay={190}>
            <View style={styles.section}>
              <RampStepHeader
                number={3}
                title="Resumen"
                accentColor={colors.primaryDark}
                accentBackground={colors.primaryLight}
                titleColor={colors.textFlat}
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
                    <Text style={styles.quoteEyebrow}>Estimado de ingreso</Text>
                    <Text style={[styles.quoteHeadline, isCompact && styles.quoteHeadlineCompact]}>{quoteHeadline}</Text>
                    <Text style={styles.quoteRate}>{quoteRateLine}</Text>
                    <View style={styles.quoteDivider} />
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>Pagas</Text>
                      <Text style={styles.quoteValue}>{formatRampMoney(quote.amountIn, fiatCurrency)}</Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>Recibes aprox.</Text>
                      <Text style={styles.quoteValue}>{formatRampMoney(quote.amountOut, 'cUSD')}</Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>Tipo de cambio</Text>
                      <Text style={styles.quoteValue}>{`${formatRampRate(quote.exchangeRate)} ${fiatCurrency}/cUSD`}</Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>{'Comisión del\nprocesador de pagos'}</Text>
                      <Text style={styles.quoteValue}>
                        {formatRampMoney(String(Number(quote.feeAmount || 0) + Number(quote.networkFeeAmount || 0)), quote.feeCurrency)}
                      </Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>Comisión de Confío</Text>
                      <View style={styles.gratisBadge}>
                        <Text style={styles.gratisBadgeText}>Gratis</Text>
                      </View>
                    </View>
                  </>
                ) : (
                  <View style={styles.emptyQuote}>
                    <Icon name="bar-chart-2" size={20} color={colors.textSecondary} />
                    <Text style={styles.emptyText}>Ingresa un monto para ver el resumen estimado.</Text>
                  </View>
                )}
              </View>
            </View>
            </RampReveal>

            {step === 'review' ? (
              <RampReveal delay={230}>
              <View style={styles.reviewCard}>
                <Text style={styles.reviewTitle}>Revisión final</Text>
                <View style={styles.reviewRow}>
                  <Icon name="credit-card" size={16} color={colors.textSecondary} />
                  <Text style={styles.reviewLabel}>Medio de pago</Text>
                  <Text style={styles.reviewValue}>{selectedMethod?.displayName}</Text>
                </View>
                <View style={styles.reviewRow}>
                  <Icon name="dollar-sign" size={16} color={colors.textSecondary} />
                  <Text style={styles.reviewLabel}>Recibirías</Text>
                  <Text style={styles.reviewValueHighlight}>{quoteHeadline}</Text>
                </View>
                <RampActionBar
                  primaryLabel="Confirmar compra"
                  onPrimaryPress={handleConfirm}
                  primaryLoading={isSubmittingOrder}
                  secondaryLabel="Volver a editar"
                  onSecondaryPress={() => setStep('form')}
                />
              </View>
              </RampReveal>
            
            ) : (
              <RampReveal delay={230}>
              <RampActionBar
                primaryLabel={isVerified ? 'Continuar' : 'Continuar y verificar'}
                onPrimaryPress={handleContinue}
                primaryDisabled={Boolean(topUpAmountError) || quoteLoading}
                primaryIconName={isVerified ? 'chevron-right' : 'shield'}
              />
              </RampReveal>
            )}
          </>
        )}
      </ScrollView>
      </SafeAreaView>
      <Modal
        visible={showAuthEmailModal}
        transparent
        animationType="fade"
        onRequestClose={() => setShowAuthEmailModal(false)}
        statusBarTranslucent
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <View style={styles.modalIconWrap}>
              <Icon name="mail" size={22} color={colors.primary} />
            </View>
            <Text style={styles.modalTitle}>Email para continuar con PSE</Text>
            <Text style={styles.modalText}>
              Tu cuenta usa un correo privado de Apple y el codigo de verificacion de PSE no llega ahi.
              Ingresa un email real donde si puedas recibir el codigo para esta operacion en Colombia.
            </Text>
            <TextInput
              value={authEmailInput}
              onChangeText={(value) => {
                setAuthEmailInput(value);
                if (authEmailError) {
                  setAuthEmailError(null);
                }
              }}
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
              placeholder="tuemail@dominio.com"
              placeholderTextColor={colors.textSecondary}
              style={[styles.modalInput, authEmailError && styles.modalInputError]}
            />
            {authEmailError ? <Text style={styles.modalErrorText}>{authEmailError}</Text> : null}
            <Text style={styles.modalFootnote}>Solo lo usaremos para recibir el codigo de esta operacion.</Text>
            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.modalSecondaryButton}
                onPress={() => {
                  setShowAuthEmailModal(false);
                  setAuthEmailError(null);
                }}
                activeOpacity={0.8}
              >
                <Text style={styles.modalSecondaryButtonText}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.modalPrimaryButton}
                activeOpacity={0.85}
                onPress={async () => {
                  const normalizedEmail = authEmailInput.trim().toLowerCase();
                  if (!normalizedEmail) {
                    setAuthEmailError('Ingresa un email para recibir el codigo.');
                    return;
                  }
                  if (!isValidEmail(normalizedEmail)) {
                    setAuthEmailError('Ingresa un email valido.');
                    return;
                  }
                  if (/[@]privaterelay\.appleid\.com$/i.test(normalizedEmail)) {
                    setAuthEmailError('Usa un email real, no un Apple private relay.');
                    return;
                  }
                  setShowAuthEmailModal(false);
                  const authenticated = await requestRampCriticalAuth({
                    amount: parsedAmount,
                    assetLabel: 'cUSD',
                    actionLabel: 'compra',
                  });
                  if (!authenticated) {
                    return;
                  }
                  await submitRampOrder(normalizedEmail);
                }}
              >
                <Text style={styles.modalPrimaryButtonText}>Continuar</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
      <BackupEnforcementModal />
    </>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    paddingBottom: 60,
  },
  noticeCard: {
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
  noticeIconWrap: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: 'rgba(5,150,105,0.12)',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 2,
  },
  noticeCopy: {
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
  noticeTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.primaryDark,
    marginBottom: 4,
  },
  noticeText: {
    fontSize: 13,
    lineHeight: 19,
    color: colors.textFlat,
  },
  loadingCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 28,
    marginHorizontal: 22,
    alignItems: 'center',
    gap: 12,
  },
  loadingText: {
    color: colors.textSecondary,
    fontSize: 14,
    textAlign: 'center',
  },
  section: {
    marginBottom: 24,
    paddingHorizontal: 22,
  },
  sectionHint: {
    fontSize: 13,
    color: colors.textSecondary,
    marginBottom: 12,
  },
  amountCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 20,
    borderWidth: 1,
    borderColor: '#ecfdf5',
    shadowColor: '#111827',
    shadowOpacity: 0.06,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
    elevation: 2,
  },
  inputLabel: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.textFlat,
    marginBottom: 14,
  },
  amountInputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#f9fafb',
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderWidth: 1.5,
    borderColor: colors.border,
  },
  amountInputRowFocused: {
    borderColor: colors.primary,
    backgroundColor: '#f0fdf4',
  },
  amountInput: {
    flex: 1,
    fontSize: 28,
    fontWeight: '700',
    color: colors.textFlat,
    padding: 0,
  },
  currencyBadge: {
    backgroundColor: colors.primaryLight,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 5,
    marginLeft: 12,
  },
  currencyBadgeText: {
    fontSize: 13,
    fontWeight: '800',
    color: colors.primaryDark,
    letterSpacing: 0.4,
  },
  helperText: {
    marginTop: 12,
    fontSize: 13,
    lineHeight: 18,
    color: colors.textSecondary,
  },
  limitText: {
    marginTop: 10,
    fontSize: 12,
    lineHeight: 18,
    color: colors.textSecondary,
  },
  errorText: {
    marginTop: 8,
    fontSize: 12,
    lineHeight: 18,
    color: '#b91c1c',
    fontWeight: '600',
  },
  methodsGrid: {
    gap: 12,
  },
  methodCard: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 16,
    borderWidth: 1.5,
    borderColor: colors.border,
    flexDirection: 'row',
    alignItems: 'center',
    shadowColor: '#111827',
    shadowOpacity: 0.04,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 1,
  },
  methodCardSelected: {
    borderColor: colors.primaryDark,
    borderWidth: 2,
    backgroundColor: colors.primaryDark,
    shadowColor: colors.primaryDark,
    shadowOpacity: 0.22,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 6 },
    elevation: 4,
  },
  methodIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 14,
  },
  methodIconWrapSelected: {
    backgroundColor: 'rgba(255,255,255,0.2)',
  },
  methodCopy: {
    flex: 1,
  },
  methodTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.textFlat,
    marginBottom: 4,
  },
  methodTitleSelected: {
    color: '#ffffff',
  },
  methodDescription: {
    fontSize: 13,
    color: colors.textSecondary,
    lineHeight: 18,
  },
  methodDescriptionSelected: {
    color: 'rgba(255,255,255,0.75)',
  },
  radioOuter: {
    width: 24,
    height: 24,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 12,
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
  quoteCard: {
    backgroundColor: '#f0fdf8',
    borderRadius: 20,
    padding: 20,
    borderWidth: 1.5,
    borderColor: '#6ee7b7',
    shadowColor: '#10B981',
    shadowOpacity: 0.14,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 8 },
    elevation: 4,
  },
  quoteEyebrow: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    color: colors.primaryDark,
    marginBottom: 10,
  },
  quoteHeadline: {
    fontSize: 34,
    fontWeight: '800',
    color: colors.primaryDark,
    marginBottom: 4,
    lineHeight: 40,
  },
  quoteHeadlineCompact: {
    fontSize: 28,
    lineHeight: 34,
  },
  quoteRate: {
    fontSize: 13,
    color: colors.textSecondary,
    lineHeight: 20,
    marginBottom: 4,
  },
  quoteDivider: {
    height: 1,
    backgroundColor: colors.border,
    marginVertical: 16,
  },
  quoteRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
    gap: 16,
  },
  quoteLabel: {
    flex: 1,
    fontSize: 13,
    color: colors.textSecondary,
    lineHeight: 18,
  },
  quoteValue: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.textFlat,
    textAlign: 'right',
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
    justifyContent: 'center',
    paddingVertical: 16,
  },
  emptyText: {
    marginTop: 10,
    fontSize: 13,
    lineHeight: 18,
    color: colors.textSecondary,
    textAlign: 'center',
  },
  reviewCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 20,
    marginHorizontal: 22,
    borderWidth: 1,
    borderColor: '#d1fae5',
    borderLeftWidth: 5,
    borderLeftColor: colors.primary,
    shadowColor: colors.primary,
    shadowOpacity: 0.12,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 },
    elevation: 4,
  },
  reviewTitle: {
    fontSize: 18,
    fontWeight: '800',
    color: colors.textFlat,
    marginBottom: 14,
  },
  reviewRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    marginBottom: 12,
    paddingVertical: 4,
  },
  reviewLabel: {
    flex: 0.95,
    fontSize: 14,
    color: colors.textSecondary,
    lineHeight: 20,
  },
  reviewValue: {
    flex: 1.15,
    fontSize: 14,
    fontWeight: '700',
    color: colors.textFlat,
    lineHeight: 20,
    textAlign: 'right',
  },
  reviewValueHighlight: {
    flex: 1.15,
    fontSize: 16,
    fontWeight: '800',
    color: colors.primaryDark,
    lineHeight: 22,
    textAlign: 'right',
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(15, 23, 42, 0.48)',
    justifyContent: 'center',
    paddingHorizontal: 20,
  },
  modalCard: {
    backgroundColor: colors.surface,
    borderRadius: 24,
    padding: 22,
    borderWidth: 1,
    borderColor: '#d1fae5',
    shadowColor: '#000000',
    shadowOpacity: 0.16,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 12 },
    elevation: 10,
  },
  modalIconWrap: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 14,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '800',
    color: colors.textFlat,
    marginBottom: 8,
  },
  modalText: {
    fontSize: 14,
    lineHeight: 21,
    color: colors.textSecondary,
    marginBottom: 16,
  },
  modalInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 13,
    fontSize: 15,
    color: colors.textFlat,
    backgroundColor: '#f8fafc',
  },
  modalInputError: {
    borderColor: colors.error.border,
  },
  modalErrorText: {
    marginTop: 8,
    fontSize: 13,
    color: colors.error.text,
  },
  modalFootnote: {
    marginTop: 10,
    fontSize: 12,
    lineHeight: 18,
    color: colors.textSecondary,
  },
  modalActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 12,
    marginTop: 20,
  },
  modalSecondaryButton: {
    minWidth: 96,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#eef2f7',
  },
  modalSecondaryButtonText: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.textSecondary,
  },
  modalPrimaryButton: {
    minWidth: 112,
    paddingHorizontal: 18,
    paddingVertical: 12,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primary,
  },
  modalPrimaryButtonText: {
    fontSize: 14,
    fontWeight: '800',
    color: '#ffffff',
  },
});

export default TopUpScreen;
