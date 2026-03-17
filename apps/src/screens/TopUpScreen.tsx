import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
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

const colors = {
  dark: '#111827',
  textPrimary: '#1f2937',
  textMuted: '#6b7280',
  textLight: '#9ca3af',
  border: '#e5e7eb',
  background: '#f0fdf4',
  surface: '#ffffff',
  primary: '#059669',
  primaryDark: '#047857',
  primaryLight: '#d1fae5',
  accent: '#3b82f6',
  accentLight: '#dbeafe',
  heroFrom: '#059669',
  heroTo: '#34d399',
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
const KOYWE_SUPPORTED_COUNTRIES = new Set(['AR', 'BO', 'BR', 'CL', 'CO', 'MX', 'PE', 'US']);

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

  const countryCode = useMemo(() => {
    const selectedIso = selectedCountry?.[2];
    const userIso = userCountry?.[2];
    return userProfile?.phoneCountry || selectedIso || userIso || 'AR';
  }, [selectedCountry, userCountry, userProfile?.phoneCountry]);

  const isKoyweCountry = KOYWE_SUPPORTED_COUNTRIES.has(countryCode);

  const { data: meData } = useQuery(GET_ME);
  const { data: kycData } = useQuery(GET_MY_KYC_STATUS);
  const { data: personalKycData } = useQuery(GET_MY_PERSONAL_KYC_STATUS);
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

  useEffect(() => {
    if (!selectedMethodCode && methods.length > 0) {
      setSelectedMethodCode(methods[0].code);
    }
  }, [methods, selectedMethodCode]);

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
      setStep('review');
    })();
  };

  const handleConfirm = async () => {
    if (!selectedMethod || !quote) {
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

    setIsSubmittingOrder(true);
    createRampOrder({
      variables: {
        direction: 'ON_RAMP',
        amount: String(parsedAmount),
        countryCode: availability?.countryCode,
        fiatCurrency,
        paymentMethodCode: selectedMethod.code,
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
          {selected && <View style={styles.radioInner} />}
        </View>
      </TouchableOpacity>
    );
  };

  return (
    <>
      <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroFrom} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <RampReveal delay={0}>
        <RampHero
          eyebrow="Ingresar saldo"
          title="Compra Confío Dollar"
          subtitle="Elige tu medio de pago, revisa la cotización y confirma cuando estés listo."
          onBack={() => navigation.goBack()}
          compact={isCompact}
          fromColor={colors.heroFrom}
          toColor={colors.heroTo}
        />
        </RampReveal>

        <RampReveal delay={60}>
        <View style={styles.noticeCard}>
          <View style={styles.noticeIconWrap}>
            <Icon name="globe" size={16} color={colors.accent} />
          </View>
          <View style={styles.noticeCopy}>
            <Text style={styles.noticeTitle}>{countryFlag ? `${countryFlag} ` : ''}Según tu país</Text>
            <Text style={styles.noticeText}>Te mostramos los medios de pago disponibles para {availability?.countryName || countryCode}.</Text>
          </View>
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
                titleColor={colors.textPrimary}
                metaColor={colors.textMuted}
              />
              <View style={styles.amountCard}>
                <Text style={styles.inputLabel}>Monto estimado en {friendlyCurrency(fiatCurrency)}</Text>
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
                  <Text style={styles.currencySuffix}>{fiatCurrency}</Text>
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
                titleColor={colors.textPrimary}
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
                titleColor={colors.textPrimary}
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
                      <Text style={styles.quoteLabel}>{'Comisión del\nprocesador de pagos'}</Text>
                      <Text style={styles.quoteValue}>
                        {formatRampMoney(String(Number(quote.feeAmount || 0) + Number(quote.networkFeeAmount || 0)), quote.feeCurrency)}
                      </Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>Comisión de Confío</Text>
                      <Text style={[styles.quoteValue, { color: colors.primary }]}>0 {quote.feeCurrency || fiatCurrency}</Text>
                    </View>
                  </>
                ) : (
                  <View style={styles.emptyQuote}>
                    <Icon name="bar-chart-2" size={20} color={colors.textLight} />
                    <Text style={styles.emptyText}>Ingresa un monto para ver el resumen estimado.</Text>
                  </View>
                )}
              </View>
            </View>
            </RampReveal>

            {step === 'review' ? (
              <RampReveal delay={230}>
              <View style={styles.reviewCard}>
                <View style={styles.reviewAccent} />
                <Text style={styles.reviewTitle}>Revisión final</Text>
                <View style={styles.reviewRow}>
                  <Icon name="credit-card" size={16} color={colors.textMuted} />
                  <Text style={styles.reviewLabel}>Medio de pago</Text>
                  <Text style={styles.reviewValue}>{selectedMethod?.displayName}</Text>
                </View>
                <View style={styles.reviewRow}>
                  <Icon name="dollar-sign" size={16} color={colors.textMuted} />
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
    backgroundColor: colors.accentLight,
    borderRadius: 16,
    padding: 16,
    marginHorizontal: 22,
    marginBottom: 20,
    gap: 12,
    borderWidth: 1,
    borderColor: '#bfdbfe',
    shadowColor: '#3b82f6',
    shadowOpacity: 0.08,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  noticeIconWrap: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: 'rgba(59,130,246,0.12)',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 2,
  },
  noticeCopy: {
    flex: 1,
  },
  noticeTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.accent,
    marginBottom: 4,
  },
  noticeText: {
    fontSize: 13,
    lineHeight: 19,
    color: colors.textPrimary,
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
    color: colors.textMuted,
    fontSize: 14,
    textAlign: 'center',
  },
  section: {
    marginBottom: 24,
    paddingHorizontal: 22,
  },
  sectionHint: {
    fontSize: 13,
    color: colors.textMuted,
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
    color: colors.textPrimary,
    marginBottom: 14,
  },
  amountInputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#f9fafb',
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderWidth: 1,
    borderColor: colors.border,
  },
  amountInput: {
    flex: 1,
    fontSize: 28,
    fontWeight: '700',
    color: colors.textPrimary,
    padding: 0,
  },
  currencySuffix: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.textMuted,
    marginLeft: 12,
  },
  helperText: {
    marginTop: 12,
    fontSize: 13,
    lineHeight: 18,
    color: colors.textMuted,
  },
  limitText: {
    marginTop: 10,
    fontSize: 12,
    lineHeight: 18,
    color: colors.textMuted,
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
    borderWidth: 1,
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
    borderColor: colors.primary,
    backgroundColor: '#f8fffb',
    shadowColor: colors.primary,
    shadowOpacity: 0.1,
  },
  methodIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 14,
  },
  methodIconWrapSelected: {
    backgroundColor: colors.primary,
  },
  methodCopy: {
    flex: 1,
  },
  methodTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.textPrimary,
    marginBottom: 4,
  },
  methodTitleSelected: {
    color: colors.primaryDark,
  },
  methodDescription: {
    fontSize: 13,
    color: colors.textMuted,
    lineHeight: 18,
  },
  methodDescriptionSelected: {
    color: colors.textPrimary,
  },
  radioOuter: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 12,
  },
  radioOuterSelected: {
    borderColor: colors.primary,
  },
  radioInner: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.primary,
  },
  quoteCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 20,
    borderWidth: 1,
    borderColor: '#d1fae5',
    shadowColor: '#111827',
    shadowOpacity: 0.06,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
    elevation: 2,
  },
  quoteEyebrow: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    color: colors.primaryDark,
    marginBottom: 8,
  },
  quoteHeadline: {
    fontSize: 28,
    fontWeight: '800',
    color: colors.textPrimary,
    marginBottom: 6,
    lineHeight: 34,
  },
  quoteHeadlineCompact: {
    fontSize: 24,
    lineHeight: 30,
  },
  quoteRate: {
    fontSize: 14,
    color: colors.textMuted,
    lineHeight: 20,
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
    color: colors.textMuted,
    lineHeight: 18,
  },
  quoteValue: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.textPrimary,
    textAlign: 'right',
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
    color: colors.textMuted,
    textAlign: 'center',
  },
  reviewCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 20,
    marginHorizontal: 22,
    borderWidth: 1,
    borderColor: '#d1fae5',
    shadowColor: '#111827',
    shadowOpacity: 0.08,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 },
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
  },
  reviewTitle: {
    fontSize: 18,
    fontWeight: '800',
    color: colors.textPrimary,
    marginBottom: 14,
    marginTop: 2,
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
    color: colors.textMuted,
    lineHeight: 20,
  },
  reviewValue: {
    flex: 1.15,
    fontSize: 14,
    fontWeight: '700',
    color: colors.textPrimary,
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
});

export default TopUpScreen;
