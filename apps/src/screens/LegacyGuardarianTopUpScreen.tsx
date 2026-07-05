import React, { useMemo, useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  ActivityIndicator,
  Alert,
  ScrollView,
  Platform,
  Modal,
  Animated,
  Easing,
  Image,
  StatusBar,
} from 'react-native';
import { Header } from '../navigation/Header';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import { colors } from '../config/theme';
import { Linking } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import GuardarianLogo from '../assets/svg/guardarian.svg';
import { useAuth } from '../contexts/AuthContext';
import { useAccount } from '../contexts/AccountContext';
import { useCountry } from '../contexts/CountryContext';
import { getCurrencyForCountry, getCurrencySymbol } from '../utils/currencyMapping';
import { countries, getCountryByIso } from '../utils/countries';
import { createGuardarianTransaction, fetchGuardarianFiatCurrencies, GuardarianFiatCurrency } from '../services/guardarianService';
import { useCurrencyByCode } from '../hooks/useCurrency';
import { getFlagForCurrency } from '../utils/currencyFlags';
import { useMutation, gql } from '@apollo/client';
import algorandService from '../services/algorandService';
import { secureDeterministicWallet } from '../services/secureDeterministicWallet';
import { oauthStorage } from '../services/oauthStorageService';
import { apolloClient } from '../apollo/client';
import PreFlightModal from '../components/PreFlightModal';
import { useBackupEnforcement } from '../hooks/useBackupEnforcement';
import { Button } from '../components/common/Button';


// GraphQL mutation for USDC opt-in
const OPT_IN_TO_USDC = gql`
  mutation OptInToAsset($assetType: String!) {
    optInToAssetByType(assetType: $assetType) {
      success
      error
      alreadyOptedIn
      requiresUserSignature
      userTransaction
      sponsorTransaction
      groupId
      assetId
      assetName
    }
  }
`;

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'TopUp'>;

const TopUpScreen = () => {

  const navigation = useNavigation<NavigationProp>();
  const { userProfile } = useAuth() as any;
  const { activeAccount } = useAccount();
  const { selectedCountry, userCountry } = useCountry();
  const { checkBackupEnforcement, BackupEnforcementModal } = useBackupEnforcement();

  const derivedCurrencyCode = useMemo(() => {
    let localCurrency = 'USD';

    if (userProfile?.phoneCountry) {
      const country = getCountryByIso(userProfile.phoneCountry);
      if (country) localCurrency = getCurrencyForCountry(country as any);
    } else if (selectedCountry) {
      localCurrency = getCurrencyForCountry(selectedCountry as any);
    } else if (userCountry) {
      localCurrency = getCurrencyForCountry(userCountry as any);
    }

    // Check if the currency will be available from Guardarian
    // If fiatOptions is loaded, check against it
    // Otherwise, default to the local currency and let the API load handle it
    return localCurrency;
  }, [selectedCountry, userCountry, userProfile?.phoneCountry]);

  const [amount, setAmount] = useState('');
  const [currencyCode, setCurrencyCode] = useState<string>('USD');
  const [loading, setLoading] = useState(false);
  const [fiatOptions, setFiatOptions] = useState<GuardarianFiatCurrency[]>([]);
  const [fiatLoading, setFiatLoading] = useState(false);
  const [fiatError, setFiatError] = useState<string | null>(null);
  const [showCurrencyNotAvailableHint, setShowCurrencyNotAvailableHint] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState('');
  const [showPreFlightModal, setShowPreFlightModal] = useState(false);

  // USDC opt-in mutation
  const [optInToUsdc] = useMutation(OPT_IN_TO_USDC);

  // Savings rail: entered from Ahorros with destination 'cusd_plus'. The
  // money buys USDT on BSC and the SERVER injects the account's registered
  // bsc_address (client-supplied payout is refused on this rail) — the same
  // contract as the Koywe savings rail.
  const route = useRoute();
  const isSavingsRail = (route.params as any)?.destination === 'cusd_plus';

  // Animation for loading spinner
  const spinValue = useRef(new Animated.Value(0)).current;
  const spinLoopRef = useRef<Animated.CompositeAnimation | null>(null);

  useEffect(() => {
    if (loadingMessage) {
      // Start spinning animation when loading
      spinLoopRef.current?.stop();
      spinLoopRef.current = Animated.loop(
        Animated.timing(spinValue, {
          toValue: 1,
          duration: 2000,
          easing: Easing.linear,
          useNativeDriver: true,
        })
      );
      spinLoopRef.current.start();
    } else {
      // Reset animation when not loading
      spinLoopRef.current?.stop();
      spinValue.setValue(0);
    }
    return () => {
      spinLoopRef.current?.stop();
      spinValue.stopAnimation();
    };
  }, [loadingMessage]);

  const spin = spinValue.interpolate({
    inputRange: [0, 1],
    outputRange: ['0deg', '360deg'],
  });

  const algorandAddress = activeAccount?.algorandAddress || '';
  const email = userProfile?.email || '';

  const { formatAmount } = useCurrencyByCode(currencyCode || 'USD');

  useEffect(() => {
    // When fiat options load, check if derived currency is available
    if (fiatOptions.length > 0) {
      const availableTickers = fiatOptions.map(f => f.ticker);
      if (availableTickers.includes(derivedCurrencyCode)) {
        setCurrencyCode(derivedCurrencyCode);
        setShowCurrencyNotAvailableHint(false);
      } else {
        // Fallback to USD if local currency not available
        setCurrencyCode('USD');
        setShowCurrencyNotAvailableHint(derivedCurrencyCode !== 'USD');
      }
    } else {
      setCurrencyCode(derivedCurrencyCode);
      setShowCurrencyNotAvailableHint(false);
    }
  }, [derivedCurrencyCode, fiatOptions]);

  useEffect(() => {
    const loadFiats = async () => {
      setFiatLoading(true);
      setFiatError(null);
      try {
        const res = await fetchGuardarianFiatCurrencies();
        setFiatOptions(res || []);
      } catch (err: any) {
        setFiatError('No pudimos cargar todas las monedas. Usa las sugeridas.');
      } finally {
        setFiatLoading(false);
      }
    };
    loadFiats();
  }, []);


  const parseAmount = (value: string) => {
    const normalized = value.replace(/,/g, '.').replace(/[^0-9.]/g, '');
    const parsed = parseFloat(normalized);
    return isFinite(parsed) ? parsed : NaN;
  };

  const translateGuardarianError = (errorMessage: string): string => {
    // Pattern matching for dynamic amount messages
    // e.g., "USD amount must be higher than 19.185 and lower than 29069"
    const amountRangePattern = /(\w+)\s+amount\s+must\s+be\s+higher\s+than\s+([\d.,]+)\s+and\s+lower\s+than\s+([\d.,]+)/i;
    const amountRangeMatch = errorMessage.match(amountRangePattern);
    if (amountRangeMatch) {
      const [, currency, min, max] = amountRangeMatch;
      return `El monto en ${currency} debe ser mayor a ${min} y menor a ${max}.`;
    }

    // Pattern for minimum amount
    // e.g., "Amount must be at least 20"
    const minAmountPattern = /amount\s+must\s+be\s+at\s+least\s+([\d.,]+)/i;
    const minAmountMatch = errorMessage.match(minAmountPattern);
    if (minAmountMatch) {
      const [, min] = minAmountMatch;
      return `El monto mínimo es ${min}.`;
    }

    // Pattern for maximum amount
    // e.g., "Amount must be less than 30000"
    const maxAmountPattern = /amount\s+must\s+be\s+less\s+than\s+([\d.,]+)/i;
    const maxAmountMatch = errorMessage.match(maxAmountPattern);
    if (maxAmountMatch) {
      const [, max] = maxAmountMatch;
      return `El monto máximo es ${max}.`;
    }

    // Common Guardarian error messages translation
    const errorTranslations: { [key: string]: string } = {
      'amount is too low': 'El monto es demasiado bajo. Por favor ingresa un monto mayor.',
      'amount is too high': 'El monto es demasiado alto. Por favor ingresa un monto menor.',
      'invalid amount': 'El monto ingresado no es válido.',
      'currency not supported': 'Esta moneda no está soportada actualmente.',
      'country not supported': 'Lo sentimos, tu país no está soportado en este momento.',
      'invalid email': 'El correo electrónico no es válido.',
      'invalid address': 'La dirección de billetera no es válida.',
      'minimum amount': 'El monto mínimo de recarga no se ha alcanzado.',
      'maximum amount': 'Has excedido el monto máximo permitido.',
      'transaction failed': 'La transacción falló. Por favor intenta nuevamente.',
      'rate limit exceeded': 'Demasiadas solicitudes. Por favor espera unos minutos.',
      'service unavailable': 'El servicio no está disponible temporalmente.',
    };

    const lowerError = errorMessage.toLowerCase();

    // Check for partial matches
    for (const [englishError, spanishError] of Object.entries(errorTranslations)) {
      if (lowerError.includes(englishError.toLowerCase())) {
        return spanishError;
      }
    }

    // Return original if no translation found
    return errorMessage;
  };

  // Helper function to handle USDC asset opt-in
  const handleUSDCOptIn = async (): Promise<boolean> => {
    try {
      setLoadingMessage('Configurando acceso a USDC...');

      const { data, errors } = await optInToUsdc({
        variables: { assetType: 'USDC' }
      });

      if (errors) {        setLoadingMessage('');
        return false;
      }


      if (data?.optInToAssetByType?.alreadyOptedIn) {
        setLoadingMessage('');
        return true;
      }

      if (data?.optInToAssetByType?.success && data.optInToAssetByType.requiresUserSignature) {
        const userTxn = data.optInToAssetByType.userTransaction;
        const sponsorTxn = data.optInToAssetByType.sponsorTransaction;

        const txId = await algorandService.signAndSubmitSponsoredTransaction(
          userTxn,
          sponsorTxn
        );

        if (txId) {
          setLoadingMessage('');
          return true;
        } else {          setLoadingMessage('');
          return false;
        }
      } else {        setLoadingMessage('');
        return false;
      }
    } catch (error) {
      setLoadingMessage('');
      return false;
    }
  };

  const handleStartTopUp = async () => {
    const backupAllowed = await checkBackupEnforcement('deposit');
    if (!backupAllowed) {
      return;
    }

    if (!email || (!isSavingsRail && !algorandAddress)) {
      Alert.alert('Faltan datos', 'Necesitamos tu correo y dirección de Algorand para continuar.');
      return;
    }

    const parsedAmount = parseAmount(amount);
    if (!amount.trim() || isNaN(parsedAmount) || parsedAmount <= 0) {
      Alert.alert('Monto inválido', 'Ingresa un monto mayor a 0.');
      return;
    }
    // Ensure wallet is initialized before opting in (Critical for cold starts)
    // Ensure wallet is initialized before opting in (Critical for cold starts)


    // Check and opt-in to USDC before proceeding (cUSD rail only — the
    // savings rail settles on BSC, no Algorand asset involved)
    if (!isSavingsRail) {
      const usdcOptInSuccess = await handleUSDCOptIn();
      if (!usdcOptInSuccess) {
        return;
      }
    }

    // Show PreFlightModal instead of proceeding directly
    setShowPreFlightModal(true);
  };

  const handleProceedToGuardarian = async () => {
    setShowPreFlightModal(false);
    const walletSafe = await checkBackupEnforcement('deposit');
    if (!walletSafe) {
      return;
    }
    setLoading(true);
    const parsedAmount = parseAmount(amount);

    try {
      const tx = await createGuardarianTransaction({
        amount: parsedAmount,
        fromCurrency: currencyCode || 'USD',
        toCurrency: isSavingsRail ? 'USDT' : 'USDC',
        toNetwork: isSavingsRail ? 'BSC' : 'ALGO',
        email,
        // Savings rail: NO payout address — the server injects the
        // registered bsc_address and refuses a client-supplied one.
        payoutAddress: isSavingsRail ? undefined : algorandAddress,
        customerCountry: userProfile?.phoneCountry,
        externalId: `confio-topup-${Date.now()}`,
      });

      const checkoutUrl = tx.redirect_url;
      if (!checkoutUrl) {
        throw new Error('No recibimos el enlace de pago de Guardarian.');
      }

      // DEBUG: Log the redirect URL to understand its structure

      // Open directly in external browser
      await Linking.openURL(checkoutUrl);

    } catch (err: any) {
      const errorMessage = translateGuardarianError(err?.message || 'Error desconocido');
      Alert.alert('No se pudo iniciar la recarga', errorMessage);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Recargar"
        backgroundColor={colors.primary}
        isLight
        showBackButton
        rightAccessory={(
          <TouchableOpacity
            style={styles.historyButton}
            onPress={() => navigation.navigate('RampHistory', { initialFilter: 'on_ramp' })}
            accessibilityRole="button"
            accessibilityLabel="Ver historial de recargas"
          >
            <Text style={styles.historyButtonText}>Historial</Text>
          </TouchableOpacity>
        )}
      />

      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>

        {/* Emerald brand field under the flat nav header (PayoutMethods
            pattern) — padding on fieldInner per the Yoga absolute-child rule. */}
        <View style={styles.brandField}>
          <Svg style={StyleSheet.absoluteFill}>
            <Defs>
              <SvgLinearGradient id="guardarianTopUpField" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={colors.primary} />
                <Stop offset="1" stopColor={colors.primaryDark} />
              </SvgLinearGradient>
            </Defs>
            <Rect width="100%" height="100%" fill="url(#guardarianTopUpField)" />
            <Circle cx="105%" cy="18%" r="80" stroke={colors.white} strokeWidth="20" strokeOpacity="0.10" fill="none" />
          </Svg>
          <View style={styles.fieldInner}>
            <Text style={styles.fieldEyebrow}>RECARGAR CON GUARDARIAN</Text>
            <Text style={styles.fieldTitle}>{isSavingsRail ? 'Recarga tu ahorro' : 'Recarga tu cuenta'}</Text>
            <Text style={styles.fieldSubtitle}>
              {isSavingsRail
                ? 'Dinero nuevo llega directo a tu ahorro (Confío Dollar+). En el checkout verás USDT — se acredita automáticamente al llegar.'
                : 'Pagas con tarjeta o transferencia y recibes cUSD. En el checkout verás USDC — se convierte automáticamente al llegar.'}
            </Text>
          </View>
        </View>

        <Text style={styles.regulatoryNote}>
          Guardarian es un socio regulado. Lo que esté disponible en tu país aparece aquí.
        </Text>

        {/* Info card */}
        <View style={styles.infoCard}>
          <View style={styles.infoIconContainer}>
            <Icon name="info" size={16} color="#0EA5E9" />
          </View>
          <View style={styles.infoContent}>
            <Text style={styles.infoCardText}>
              {email
                ? `Abriremos Guardarian con tu correo (${email.length > 20 ? email.substring(0, 20) + '...' : email}) y tu billetera pre-configurados.`
                : `Abriremos Guardarian con tu billetera pre-configurada. Deberás ingresar tu correo electrónico.`
              }
            </Text>
          </View>
        </View>

        {/* Info Notice if currency not available */}
        {showCurrencyNotAvailableHint && (
          <View style={styles.noticeCard}>
            <View style={styles.noticeIconContainer}>
              <Icon name="info" size={20} color="#0EA5E9" />
            </View>
            <View style={styles.noticeContent}>
              <Text style={styles.noticeTitle}>Paga en tu moneda local</Text>
              <Text style={styles.noticeText}>
                Tu moneda local ({derivedCurrencyCode}) se convertirá automáticamente a USD. Guardarian acepta tu tarjeta o transferencia en {derivedCurrencyCode}.
              </Text>
            </View>
          </View>
        )}

        {/* Amount Input Card */}
        <View style={styles.inputCard}>
          <Text style={styles.inputLabel}>¿Cuánto quieres recargar?</Text>

          <View style={styles.amountInputContainer}>
            <View style={styles.currencyBadge}>
              <Text style={styles.flagEmoji}>{getFlagForCurrency(currencyCode)}</Text>
              <Text style={styles.currencyCodeText}>{currencyCode}</Text>
            </View>
            <TextInput
              style={styles.amountInput}
              placeholder="0"
              placeholderTextColor={colors.text.light}
              keyboardType="decimal-pad"
              value={amount}
              onChangeText={setAmount}
            />
          </View>

          <View style={styles.conversionHint}>
            <Icon name="arrow-down" size={14} color={colors.primary} />
            <Text style={styles.conversionText}>{isSavingsRail ? 'Llega directo a tu ahorro (Confío Dollar+)' : 'Recibes cUSD en tu cuenta'}</Text>
          </View>
        </View>

        {/* Features */}
        <View style={styles.featuresContainer}>
          <View style={styles.featureItem}>
            <View style={styles.featureIconCircle}>
              <Icon name="zap" size={16} color={colors.primary} />
            </View>
            <Text style={styles.featureText}>Instantáneo</Text>
          </View>
          <View style={styles.featureItem}>
            <View style={styles.featureIconCircle}>
              <Icon name="shield" size={16} color={colors.primary} />
            </View>
            <Text style={styles.featureText}>Seguro</Text>
          </View>
          <View style={styles.featureItem}>
            <View style={styles.featureIconCircle}>
              <Icon name="credit-card" size={16} color={colors.primary} />
            </View>
            <Text style={styles.featureText}>Tarjeta o banco</Text>
          </View>
        </View>

        {/* CTA Button */}
        <Button
          title="Continuar con Guardarian"
          onPress={handleStartTopUp}
          loading={loading}
          disabled={!amount}
          icon={<Icon name="arrow-right" size={20} color={colors.white} />}
          style={!amount
            ? { backgroundColor: colors.borderMedium, borderRadius: 16, paddingHorizontal: 24 }
            : {
                backgroundColor: colors.primary,
                borderRadius: 16,
                paddingHorizontal: 24,
                shadowColor: colors.primary,
                shadowOpacity: 0.3,
                shadowRadius: 12,
                shadowOffset: { width: 0, height: 4 },
                elevation: 4,
              }}
          textStyle={{ fontWeight: '700' }}
        />

        <TouchableOpacity
          style={styles.supportButton}
          onPress={() => Linking.openURL('https://t.me/confio4world')}
        >
          <Icon name="help-circle" size={16} color={colors.text.secondary} />
          <Text style={styles.supportButtonText}>¿Estás perdido? ¡Pide ayuda en soporte!</Text>
        </TouchableOpacity>

        {/* Powered by Guardarian */}
        <View style={styles.poweredByContainer}>

          <Text style={styles.poweredByLabel}>En alianza con</Text>
          <View style={styles.guardarianLogoContainer}>
            <GuardarianLogo width={217} height={24} />
          </View>

          <Text style={styles.legalText}>
            Guardarian es operado por FinSeven CZ s.r.o., una empresa registrada en la República Checa (código de registro: 22304681), con su dirección en Na Čečeličce 425/4, Smíchov, 15000, Praga, República Checa, registrada como Proveedor de Servicios de Activos Virtuales (VASP).
          </Text>
        </View>
      </ScrollView>

      {/* Loading Modal */}
      <Modal
        visible={!!loadingMessage}
        transparent={true}
        animationType="fade"
        statusBarTranslucent={true}
      >
        <View style={styles.loadingOverlay}>
          <View style={styles.loadingCard}>
            {/* Animated Confío Logo */}
            <Animated.View style={{ transform: [{ rotate: spin }] }}>
              <Image
                source={require('../assets/png/CONFIO.png')}
                style={styles.loadingLogo}
              />
            </Animated.View>

            {/* Loading Message */}
            <Text style={styles.loadingText}>{loadingMessage}</Text>

            {/* Progress Dots Animation */}
            <View style={styles.dotsContainer}>
              <View style={[styles.dot, { backgroundColor: colors.primary }]} />
              <View style={[styles.dot, { backgroundColor: colors.primary, opacity: 0.6 }]} />
              <View style={[styles.dot, { backgroundColor: colors.primary, opacity: 0.3 }]} />
            </View>
          </View>
        </View>
      </Modal>

      <PreFlightModal
        visible={showPreFlightModal}
        type="buy"
        onContinue={handleProceedToGuardarian}
        onCancel={() => setShowPreFlightModal(false)}
      />
      <BackupEnforcementModal />
    </View>
  );
};

const styles = StyleSheet.create({
  brandField: {
    backgroundColor: colors.primary,
    overflow: 'hidden',
    marginHorizontal: -20,
    marginTop: -24,
    marginBottom: 4,
  },
  fieldInner: {
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 22,
  },
  fieldEyebrow: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 2,
    color: colors.primaryLight,
    marginBottom: 6,
  },
  fieldTitle: {
    fontSize: 22,
    fontWeight: '800',
    color: colors.white,
  },
  fieldSubtitle: {
    fontSize: 13,
    lineHeight: 19,
    color: 'rgba(255,255,255,0.85)',
    marginTop: 6,
  },
  regulatoryNote: {
    fontSize: 11,
    lineHeight: 16,
    color: colors.text.secondary,
    marginHorizontal: 20,
    marginTop: 12,
    marginBottom: 4,
  },
  container: {
    flex: 1,
    backgroundColor: colors.neutral,
  },
  historyButton: {
    minWidth: 72,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: 'rgba(255,255,255,0.18)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.3)',
    alignItems: 'center',
  },
  historyButtonText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.white,
  },
  content: {
    paddingHorizontal: 20,
    paddingTop: 24,
    paddingBottom: 32,
  },

  // Hero Section

  // Info Card
  infoCard: {
    flexDirection: 'row',
    backgroundColor: '#EFF6FF',
    borderRadius: 12,
    padding: 12,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#DBEAFE',
  },
  infoIconContainer: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: colors.white,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 10,
    marginTop: 2,
  },
  infoContent: {
    flex: 1,
  },
  infoCardText: {
    fontSize: 12,
    color: colors.text.primary,
    lineHeight: 16,
  },

  // Notice Card
  noticeCard: {
    flexDirection: 'row',
    backgroundColor: '#EFF6FF',
    borderRadius: 16,
    padding: 16,
    marginBottom: 24,
    borderWidth: 1,
    borderColor: '#DBEAFE',
  },
  noticeIconContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.white,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  noticeContent: {
    flex: 1,
  },
  noticeTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.text.primary,
    marginBottom: 4,
  },
  noticeText: {
    fontSize: 13,
    color: colors.text.secondary,
    lineHeight: 18,
  },

  // Amount Input Card
  inputCard: {
    backgroundColor: colors.white,
    borderRadius: 20,
    padding: 20,
    marginBottom: 24,
    shadowColor: '#000',
    shadowOpacity: 0.08,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  inputLabel: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: 16,
  },
  amountInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.neutral,
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 16,
    borderWidth: 2,
    borderColor: colors.border,
  },
  currencySymbol: {
    display: 'none',
  },
  amountInput: {
    flex: 1,
    fontSize: 32,
    fontWeight: '700',
    color: colors.text.primary,
    padding: 0,
  },
  currencyBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.white,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 8,
    gap: 6,
    marginRight: 12,
  },
  flagEmoji: {
    fontSize: 20,
  },
  currencyCodeText: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.text.primary,
  },
  conversionHint: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 12,
    gap: 6,
  },
  conversionText: {
    fontSize: 13,
    color: colors.primary,
    fontWeight: '600',
  },

  // Features
  featuresContainer: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginBottom: 32,
  },
  featureItem: {
    alignItems: 'center',
    gap: 8,
  },
  featureIconCircle: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  featureText: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.text.secondary,
  },

  // CTA Button

  // Powered by Guardarian
  poweredByContainer: {
    alignItems: 'center',
    marginTop: 24,
    gap: 12,
  },
  poweredByLabel: {
    fontSize: 11,
    color: colors.text.light,
    fontWeight: '500',
    textAlign: 'center',
  },
  guardarianLogoContainer: {
    backgroundColor: colors.white,
    paddingHorizontal: 20,
    paddingVertical: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: '#000',
    shadowOpacity: 0.04,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
    alignItems: 'center',
    justifyContent: 'center',
    minWidth: 260,
  },
  legalText: {
    fontSize: 9,
    color: colors.text.light,
    textAlign: 'center',
    lineHeight: 13,
    paddingHorizontal: 16,
    marginTop: 4,
  },
  // Loading Modal Styles
  loadingOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingCard: {
    backgroundColor: colors.white,
    borderRadius: 20,
    padding: 32,
    alignItems: 'center',
    minWidth: 280,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 4,
    },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 10,
  },
  loadingLogo: {
    width: 80,
    height: 80,
    marginBottom: 24,
  },
  loadingText: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text.primary,
    textAlign: 'center',
    marginBottom: 16,
  },
  dotsContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  supportButton: {
    marginTop: 24,
    marginBottom: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.neutralDark,
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 20,
    alignSelf: 'center',
    gap: 8,
  },
  supportButtonText: {
    fontSize: 14,
    color: colors.text.secondary,
    fontWeight: '600',
  },
});

export default TopUpScreen;
