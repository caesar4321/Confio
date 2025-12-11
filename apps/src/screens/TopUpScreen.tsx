import React, { useMemo, useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  SafeAreaView,
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
import Icon from 'react-native-vector-icons/Feather';
import InAppBrowser from 'react-native-inappbrowser-reborn';
import { Linking } from 'react-native';
import { useNavigation } from '@react-navigation/native';
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
import { GuardarianModal } from '../components/GuardarianModal';

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

  const derivedCurrencyCode = useMemo(() => {
    let localCurrency = 'USD';

    if (userProfile?.phoneCountry) {
      const country = getCountryByIso(userProfile.phoneCountry);
      if (country) localCurrency = getCurrencyForCountry(country);
    } else if (selectedCountry) {
      localCurrency = getCurrencyForCountry(selectedCountry);
    } else if (userCountry) {
      localCurrency = getCurrencyForCountry(userCountry);
    }

    // Check if the currency will be available from Guardarian
    // If fiatOptions is loaded, check against it
    // Otherwise, default to the local currency and let the API load handle it
    return localCurrency;
  }, [selectedCountry, userCountry, userProfile?.phoneCountry]);

  const [amount, setAmount] = useState('');
  const [currencyCode, setCurrencyCode] = useState(derivedCurrencyCode);
  const [loading, setLoading] = useState(false);
  const [fiatOptions, setFiatOptions] = useState<GuardarianFiatCurrency[]>([]);
  const [fiatLoading, setFiatLoading] = useState(false);
  const [fiatError, setFiatError] = useState<string | null>(null);
  const [showCurrencyNotAvailableHint, setShowCurrencyNotAvailableHint] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState('');
  const [showGuardarianModal, setShowGuardarianModal] = useState(false);

  // USDC opt-in mutation
  const [optInToUsdc] = useMutation(OPT_IN_TO_USDC);

  // Animation for loading spinner
  const spinValue = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (loadingMessage) {
      // Start spinning animation when loading
      Animated.loop(
        Animated.timing(spinValue, {
          toValue: 1,
          duration: 2000,
          easing: Easing.linear,
          useNativeDriver: true,
        })
      ).start();
    } else {
      // Reset animation when not loading
      spinValue.setValue(0);
    }
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
        console.warn('Guardarian fiat load failed', err);
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
      console.log('[TopUpScreen] Calling optInToAsset mutation for USDC...');

      const { data, errors } = await optInToUsdc({
        variables: { assetType: 'USDC' }
      });

      if (errors) {
        console.error('[TopUpScreen] GraphQL errors:', errors);
        setLoadingMessage('');
        return false;
      }

      console.log('[TopUpScreen] USDC opt-in mutation response:', data);

      if (data?.optInToAssetByType?.alreadyOptedIn) {
        console.log('[TopUpScreen] User already opted in to USDC');
        setLoadingMessage('');
        return true;
      }

      if (data?.optInToAssetByType?.success && data.optInToAssetByType.requiresUserSignature) {
        const userTxn = data.optInToAssetByType.userTransaction;
        const sponsorTxn = data.optInToAssetByType.sponsorTransaction;

        console.log('[TopUpScreen] Signing and submitting USDC opt-in...');
        const txId = await algorandService.signAndSubmitSponsoredTransaction(
          userTxn,
          sponsorTxn
        );

        if (txId) {
          console.log('[TopUpScreen] Successfully opted in to USDC:', txId);
          setLoadingMessage('');
          return true;
        } else {
          console.error('[TopUpScreen] Failed to submit USDC opt-in transaction');
          setLoadingMessage('');
          return false;
        }
      } else {
        console.error('[TopUpScreen] Failed to generate USDC opt-in transaction:', data?.optInToAssetByType?.error);
        setLoadingMessage('');
        return false;
      }
    } catch (error) {
      console.error('[TopUpScreen] Error during USDC opt-in:', error);
      setLoadingMessage('');
      return false;
    }
  };

  const handleStartTopUp = async () => {

    if (!email || !algorandAddress) {
      Alert.alert('Faltan datos', 'Necesitamos tu correo y dirección de Algorand para continuar.');
      return;
    }

    const parsedAmount = parseAmount(amount);
    if (!amount.trim() || isNaN(parsedAmount) || parsedAmount <= 0) {
      Alert.alert('Monto inválido', 'Ingresa un monto mayor a 0.');
      return;
    }

    // Check and opt-in to USDC before proceeding
    const usdcOptInSuccess = await handleUSDCOptIn();
    if (!usdcOptInSuccess) {
      console.log('[TopUpScreen] USDC opt-in failed, stopping top-up flow');
      return;
    }

    // Show the modal instruction instead of proceeding directly
    setShowGuardarianModal(true);
  };

  const handleProceedToGuardarian = async () => {
    setShowGuardarianModal(false);
    setLoading(true);
    const parsedAmount = parseAmount(amount);

    try {
      const tx = await createGuardarianTransaction({
        amount: parsedAmount,
        fromCurrency: currencyCode || 'USD',
        toCurrency: 'USDC',
        toNetwork: 'ALGO',
        email,
        payoutAddress: algorandAddress,
        customerCountry: userProfile?.phoneCountry,
        externalId: `confio-topup-${Date.now()}`,
      });

      const checkoutUrl = tx.redirect_url;
      if (!checkoutUrl) {
        throw new Error('No recibimos el enlace de pago de Guardarian.');
      }

      // DEBUG: Log the redirect URL to understand its structure
      console.log('=== GUARDARIAN REDIRECT URL ===');
      console.log(checkoutUrl);
      console.log('==============================');

      // Simplify options to minimize conflicts
      const options = {
        // iOS Properties
        dismissButtonStyle: 'done',
        preferredBarTintColor: '#72D9BC',
        preferredControlTintColor: 'white',
        readerMode: false,
        animated: true,
        modalPresentationStyle: 'fullScreen',
        modalTransitionStyle: 'coverVertical',
        modalEnabled: true,
        enableBarCollapsing: false,
        // Android Properties
        showTitle: true,
        toolbarColor: '#72D9BC',
        secondaryToolbarColor: 'white',
        navigationBarColor: 'white',
        navigationBarDividerColor: 'white',
        enableUrlBarHiding: true,
        enableDefaultShare: false,
        forceCloseOnRedirection: false,
        // Specify full options to be safe
        hasBackButton: true,
        browserPackage: undefined,
        showInRecents: false
      };

      try {
        if (await InAppBrowser.isAvailable()) {
          await InAppBrowser.open(checkoutUrl, options);
        } else {
          console.warn('[TopUp] InAppBrowser not available, using Linking');
          await Linking.openURL(checkoutUrl);
        }
      } catch (browserErr: any) {
        console.warn('InAppBrowser open failed, falling back to Linking', browserErr);
        Alert.alert('Aviso', `No pudimos abrir el navegador interno (${browserErr.message || 'Error desconocido'}). Intentaremos abrir el navegador externo.`);
        await Linking.openURL(checkoutUrl);
      }
    } catch (err: any) {
      console.error('Guardarian top-up error', err);
      const errorMessage = translateGuardarianError(err?.message || 'Error desconocido');
      Alert.alert('No se pudo iniciar la recarga', errorMessage);
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity style={styles.backButton} onPress={() => navigation.goBack()}>
          <Icon name="arrow-left" size={22} color="#111827" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Recargar con Guardarian</Text>
      </View>

      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {/* Hero Section */}
        <View style={styles.heroSection}>
          <View style={styles.heroIconContainer}>
            <Icon name="credit-card" size={32} color="#72D9BC" />
          </View>
          <Text style={styles.heroTitle}>Recarga tu cuenta</Text>
          <Text style={styles.heroSubtitle}>
            Compra USDC con tu tarjeta o transferencia bancaria. Rápido, seguro y sin complicaciones.
          </Text>
          <Text style={styles.heroSubtitleSmall}>
            Guardarian es un socio regulado. En algunos países solo está disponible la recarga (no el retiro) por regulación local. Retiros disponibles en EUR {getFlagForCurrency('EUR')} MXN {getFlagForCurrency('MXN')} CLP {getFlagForCurrency('CLP')} COP {getFlagForCurrency('COP')} ARS {getFlagForCurrency('ARS')} BRL {getFlagForCurrency('BRL')}.
          </Text>
        </View>

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
              placeholderTextColor="#9CA3AF"
              keyboardType="decimal-pad"
              value={amount}
              onChangeText={setAmount}
            />
          </View>

          <View style={styles.conversionHint}>
            <Icon name="arrow-down" size={14} color="#72D9BC" />
            <Text style={styles.conversionText}>Recibirás USDC en tu cuenta</Text>
          </View>
        </View>

        {/* Features */}
        <View style={styles.featuresContainer}>
          <View style={styles.featureItem}>
            <View style={styles.featureIconCircle}>
              <Icon name="zap" size={16} color="#72D9BC" />
            </View>
            <Text style={styles.featureText}>Instantáneo</Text>
          </View>
          <View style={styles.featureItem}>
            <View style={styles.featureIconCircle}>
              <Icon name="shield" size={16} color="#72D9BC" />
            </View>
            <Text style={styles.featureText}>Seguro</Text>
          </View>
          <View style={styles.featureItem}>
            <View style={styles.featureIconCircle}>
              <Icon name="credit-card" size={16} color="#72D9BC" />
            </View>
            <Text style={styles.featureText}>Tarjeta o banco</Text>
          </View>
        </View>

        {/* CTA Button */}
        <TouchableOpacity
          style={[styles.ctaButton, (!amount || loading) && styles.ctaButtonDisabled]}
          onPress={handleStartTopUp}
          disabled={!amount || loading}
        >
          {loading ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <>
              <Text style={styles.ctaButtonText}>Continuar con Guardarian</Text>
              <Icon name="arrow-right" size={20} color="#fff" />
            </>
          )}
        </TouchableOpacity>

        {/* Powered by Guardarian */}
        <View style={styles.poweredByContainer}>
          <Text style={styles.poweredByLabel}>En alianza con</Text>
          <View style={styles.guardarianLogoContainer}>
            <GuardarianLogo width={217} height={24} />
          </View>
          <Text style={styles.legalText}>
            Guardance UAB es una empresa registrada en Lituania (código de registro: 306353686), con dirección en Zalgirio St. 90-100, Vilnius, Lituania. Está registrada bajo el número 306353686 por el Centro Estatal de Registros de la República de Lituania como Operador de Intercambio de Moneda Virtual.
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
              <View style={[styles.dot, { backgroundColor: '#72D9BC' }]} />
              <View style={[styles.dot, { backgroundColor: '#72D9BC', opacity: 0.6 }]} />
              <View style={[styles.dot, { backgroundColor: '#72D9BC', opacity: 0.3 }]} />
            </View>
          </View>
        </View>
      </Modal>

      <GuardarianModal
        visible={showGuardarianModal}
        type="buy"
        address={algorandAddress}
        onClose={() => setShowGuardarianModal(false)}
        onContinue={handleProceedToGuardarian}
      />

    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingTop: Platform.OS === 'android' ? (StatusBar.currentHeight || 0) + 12 : 12,
    paddingBottom: 12,
    backgroundColor: '#fff',
    borderBottomWidth: 1,
    borderBottomColor: '#F3F4F6',
  },
  backButton: {
    padding: 8,
    marginRight: 8,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#111827',
  },
  content: {
    paddingHorizontal: 20,
    paddingTop: 24,
    paddingBottom: 32,
  },

  // Hero Section
  heroSection: {
    alignItems: 'center',
    marginBottom: 20,
  },
  heroIconContainer: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: '#D1FAE5',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  heroTitle: {
    fontSize: 28,
    fontWeight: '700',
    color: '#111827',
    marginBottom: 8,
    textAlign: 'center',
  },
  heroSubtitle: {
    fontSize: 15,
    color: '#6B7280',
    textAlign: 'center',
    lineHeight: 22,
    paddingHorizontal: 16,
  },
  heroSubtitleSmall: {
    fontSize: 12,
    color: '#6B7280',
    textAlign: 'center',
    lineHeight: 18,
    paddingHorizontal: 20,
    marginTop: 6,
  },

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
    backgroundColor: '#fff',
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
    color: '#1F2937',
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
    backgroundColor: '#fff',
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
    color: '#1F2937',
    marginBottom: 4,
  },
  noticeText: {
    fontSize: 13,
    color: '#4B5563',
    lineHeight: 18,
  },

  // Amount Input Card
  inputCard: {
    backgroundColor: '#fff',
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
    color: '#111827',
    marginBottom: 16,
  },
  amountInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F9FAFB',
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 16,
    borderWidth: 2,
    borderColor: '#E5E7EB',
  },
  currencySymbol: {
    display: 'none',
  },
  amountInput: {
    flex: 1,
    fontSize: 32,
    fontWeight: '700',
    color: '#111827',
    padding: 0,
  },
  currencyBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
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
    color: '#111827',
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
    color: '#72D9BC',
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
    backgroundColor: '#D1FAE5',
    alignItems: 'center',
    justifyContent: 'center',
  },
  featureText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#6B7280',
  },

  // CTA Button
  ctaButton: {
    backgroundColor: '#72D9BC',
    borderRadius: 16,
    paddingVertical: 18,
    paddingHorizontal: 24,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    shadowColor: '#72D9BC',
    shadowOpacity: 0.3,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  ctaButtonDisabled: {
    backgroundColor: '#D1D5DB',
    shadowOpacity: 0,
  },
  ctaButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: '#fff',
  },

  // Powered by Guardarian
  poweredByContainer: {
    alignItems: 'center',
    marginTop: 24,
    gap: 12,
  },
  poweredByLabel: {
    fontSize: 11,
    color: '#9CA3AF',
    fontWeight: '500',
    textAlign: 'center',
  },
  guardarianLogoContainer: {
    backgroundColor: '#fff',
    paddingHorizontal: 20,
    paddingVertical: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
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
    color: '#9CA3AF',
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
    backgroundColor: '#FFFFFF',
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
    color: '#1F2937',
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
});

export default TopUpScreen;
