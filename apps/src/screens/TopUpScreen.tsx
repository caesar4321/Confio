import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Linking,
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
import { useAuth } from '../contexts/AuthContext';
import { useCountry } from '../contexts/CountryContext';
import {
  GET_ME,
  GET_RAMP_AVAILABILITY,
  GET_RAMP_QUOTE,
  GET_MY_KYC_STATUS,
  GET_MY_PERSONAL_KYC_STATUS,
} from '../apollo/queries';
import { getPaymentMethodIcon } from '../utils/paymentMethodIcons';
import { getCountryByIso } from '../utils/countries';
import { Gradient } from '../components/common/Gradient';
import { CREATE_RAMP_ORDER } from '../apollo/mutations';
import { biometricAuthService } from '../services/biometricAuthService';
import LegacyGuardarianTopUpScreen from './LegacyGuardarianTopUpScreen';

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

const StepBadge = ({ number }: { number: number }) => (
  <View style={styles.stepBadge}>
    <Text style={styles.stepBadgeText}>{number}</Text>
  </View>
);

const TopUpScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { userProfile } = useAuth() as any;
  const { selectedCountry, userCountry } = useCountry();

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
  const parsedAmount = Number((amount || '').replace(',', '.'));
  const quoteEnabled = Number.isFinite(parsedAmount) && parsedAmount > 0 && !!availability?.countryCode;

  const { data: quoteData, loading: quoteLoading } = useQuery(GET_RAMP_QUOTE, {
    variables: {
      direction: 'ON_RAMP',
      amount: String(parsedAmount || ''),
      countryCode: availability?.countryCode,
      fiatCurrency,
    },
    skip: !isKoyweMapped || !quoteEnabled,
    fetchPolicy: 'cache-and-network',
  });

  const quote = quoteData?.rampQuote;
  const quoteHeadline = quote ? `Recibes aprox. ${formatMoney(quote.amountOut, 'cUSD')}` : '';
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
  }, [
    kycData?.myKycStatus?.status,
    meData?.me?.isIdentityVerified,
    meData?.me?.verificationStatus,
    personalKycData?.myPersonalKycStatus?.status,
  ]);

  const selectedMethod = useMemo(
    () => methods.find((method) => method.code === selectedMethodCode) || methods[0] || null,
    [methods, selectedMethodCode],
  );
  const selectedMethodMin = Number(selectedMethod?.onRampMinAmount || 0);
  const selectedMethodMax = Number(selectedMethod?.onRampMaxAmount || 0);
  const isBelowTopUpMin = quoteEnabled && selectedMethodMin > 0 && parsedAmount < selectedMethodMin;
  const isAboveTopUpMax = quoteEnabled && selectedMethodMax > 0 && parsedAmount > selectedMethodMax;
  const topUpAmountError = isBelowTopUpMin
    ? `El mínimo por operación es ${formatMoney(String(selectedMethodMin), fiatCurrency)}.`
    : isAboveTopUpMax
      ? `El máximo por operación es ${formatMoney(String(selectedMethodMax), fiatCurrency)}.`
      : null;

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
    if (!selectedMethod) {
      Alert.alert('Selecciona un método', 'Elige un medio de pago disponible para continuar.');
      return;
    }
    if (!quoteEnabled || !quote) {
      Alert.alert('Monto inválido', 'Ingresa un monto válido para ver la cotización.');
      return;
    }
    if (topUpAmountError) {
      Alert.alert('Monto fuera de rango', topUpAmountError);
      return;
    }
    if (!isVerified) {
      openVerificationPrompt();
      return;
    }
    setStep('review');
  };

  const requestCriticalAuth = async () => {
    const authMessage = parsedAmount > 0
      ? `Autoriza la compra de ${parsedAmount.toFixed(2)} cUSD`
      : 'Autoriza esta compra';

    let authenticated = await biometricAuthService.authenticate(authMessage, true, true);
    if (authenticated) {
      return true;
    }

    const lockout = biometricAuthService.isLockout();
    if (lockout) {
      Alert.alert(
        'Biometría bloqueada',
        'Desbloquea tu dispositivo con passcode y vuelve a intentar.',
        [{ text: 'OK', style: 'default' }],
      );
      return false;
    }

    const shouldRetry = await new Promise<boolean>((resolve) => {
      Alert.alert(
        'Autenticación requerida',
        'Debes autenticarte para confirmar esta compra.',
        [
          { text: 'Cancelar', style: 'cancel', onPress: () => resolve(false) },
          { text: 'Reintentar', onPress: () => resolve(true) },
        ],
      );
    });

    if (!shouldRetry) {
      return false;
    }

    authenticated = await biometricAuthService.authenticate(authMessage, true, true);
    if (!authenticated) {
      Alert.alert('No autenticado', 'No pudimos validar tu identidad. Intenta de nuevo en unos segundos.');
      return false;
    }

    return true;
  };

  const handleConfirm = async () => {
    if (!selectedMethod || !quote) {
      return;
    }
    const authenticated = await requestCriticalAuth();
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
        if (!result?.success) {
          Alert.alert('No se pudo crear la orden', result?.error || 'Inténtalo nuevamente.');
          return;
        }

        Alert.alert(
          'Orden creada',
          `Orden ${result.orderId}\n\nPagarás con ${selectedMethod.displayName}.\nRecibirías aproximadamente ${formatMoney(result.amountOut, 'cUSD')}.`,
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
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroFrom} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.heroWrapper}>
          <Gradient fromColor={colors.heroFrom} toColor={colors.heroTo} style={styles.heroGradient}>
            <View style={styles.heroPadding}>
              <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
                <Icon name="arrow-left" size={20} color={colors.surface} />
              </TouchableOpacity>
              <Text style={styles.eyebrow}>Ingresar saldo</Text>
              <Text style={styles.title}>Compra Confío Dollar</Text>
              <Text style={styles.subtitle}>Elige tu medio de pago, revisa la cotización y confirma cuando estés listo.</Text>
            </View>
          </Gradient>
        </View>

        <View style={styles.noticeCard}>
          <View style={styles.noticeIconWrap}>
            <Icon name="globe" size={16} color={colors.accent} />
          </View>
          <View style={styles.noticeCopy}>
            <Text style={styles.noticeTitle}>{countryFlag ? `${countryFlag} ` : ''}Según tu país</Text>
            <Text style={styles.noticeText}>Te mostramos los medios de pago disponibles para {availability?.countryName || countryCode}.</Text>
          </View>
        </View>

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
            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <View style={styles.sectionHeaderLeft}>
                  <StepBadge number={1} />
                  <Text style={styles.sectionTitle}>Monto</Text>
                </View>
                <Text style={styles.sectionMeta}>{countryFlag ? `${countryFlag} ` : ''}{availability.countryName} · {fiatCurrency}</Text>
              </View>
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
                    Mínimo: {selectedMethodMin > 0 ? formatMoney(String(selectedMethodMin), fiatCurrency) : '--'} · Máximo por operación: {selectedMethodMax > 0 ? formatMoney(String(selectedMethodMax), fiatCurrency) : '--'}
                  </Text>
                ) : null}
                {topUpAmountError ? <Text style={styles.errorText}>{topUpAmountError}</Text> : null}
              </View>
            </View>

            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <View style={styles.sectionHeaderLeft}>
                  <StepBadge number={2} />
                  <Text style={styles.sectionTitle}>Medio de pago</Text>
                </View>
              </View>
              <Text style={styles.sectionHint}>Selecciona cómo quieres pagar.</Text>
              <View style={styles.methodsGrid}>{methods.map(renderMethodCard)}</View>
            </View>

            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <View style={styles.sectionHeaderLeft}>
                  <StepBadge number={3} />
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
                      <Text style={styles.quoteLabel}>Pagas</Text>
                      <Text style={styles.quoteValue}>{formatMoney(quote.amountIn, fiatCurrency)}</Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>Recibes aprox.</Text>
                      <Text style={styles.quoteValue}>{formatMoney(quote.amountOut, 'cUSD')}</Text>
                    </View>
                    <View style={styles.quoteRow}>
                      <Text style={styles.quoteLabel}>{'Comisión del\nprocesador de pagos'}</Text>
                      <Text style={styles.quoteValue}>
                        {formatMoney(String(Number(quote.feeAmount || 0) + Number(quote.networkFeeAmount || 0)), quote.feeCurrency)}
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

            {step === 'review' ? (
              <View style={styles.reviewCard}>
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
                <TouchableOpacity
                  style={[styles.primaryButton, isSubmittingOrder && styles.primaryButtonDisabled]}
                  onPress={handleConfirm}
                  activeOpacity={0.8}
                  disabled={isSubmittingOrder}
                >
                  {isSubmittingOrder ? <ActivityIndicator color={colors.surface} /> : <Text style={styles.primaryButtonText}>Confirmar compra</Text>}
                </TouchableOpacity>
                <TouchableOpacity style={styles.ghostButton} onPress={() => setStep('form')} activeOpacity={0.7}>
                  <Text style={styles.ghostButtonText}>Volver a editar</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <TouchableOpacity style={[styles.primaryButton, topUpAmountError && styles.primaryButtonDisabled]} onPress={handleContinue} activeOpacity={0.8} disabled={Boolean(topUpAmountError)}>
                <Icon name={isVerified ? 'chevron-right' : 'shield'} size={18} color={colors.surface} style={styles.primaryButtonIcon} />
                <Text style={styles.primaryButtonText}>{isVerified ? 'Continuar' : 'Continuar y verificar'}</Text>
              </TouchableOpacity>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
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
  noticeCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: colors.accentLight,
    borderRadius: 16,
    padding: 16,
    marginHorizontal: 22,
    marginBottom: 20,
    gap: 12,
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
  sectionTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  sectionMeta: {
    fontSize: 13,
    color: colors.textMuted,
    fontWeight: '600',
  },
  sectionHint: {
    fontSize: 13,
    color: colors.textMuted,
    marginBottom: 12,
  },
  stepBadge: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepBadgeText: {
    fontSize: 13,
    fontWeight: '800',
    color: colors.primaryDark,
  },
  amountCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 20,
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
  },
  methodCardSelected: {
    borderColor: colors.primary,
    backgroundColor: '#f8fffb',
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
  },
  quoteHeadline: {
    fontSize: 22,
    fontWeight: '800',
    color: colors.textPrimary,
    marginBottom: 8,
  },
  quoteRate: {
    fontSize: 14,
    color: colors.textMuted,
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
  },
  reviewTitle: {
    fontSize: 18,
    fontWeight: '800',
    color: colors.textPrimary,
    marginBottom: 14,
  },
  reviewRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginBottom: 12,
  },
  reviewLabel: {
    flex: 1,
    fontSize: 14,
    color: colors.textMuted,
  },
  reviewValue: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  reviewValueHighlight: {
    fontSize: 15,
    fontWeight: '800',
    color: colors.primaryDark,
  },
  primaryButton: {
    marginTop: 12,
    marginHorizontal: 22,
    backgroundColor: colors.primary,
    borderRadius: 16,
    paddingVertical: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryButtonDisabled: {
    opacity: 0.7,
  },
  primaryButtonIcon: {
    marginRight: 8,
  },
  primaryButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.surface,
  },
  ghostButton: {
    marginTop: 12,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
  },
  ghostButtonText: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.primary,
  },
});

export default TopUpScreen;
