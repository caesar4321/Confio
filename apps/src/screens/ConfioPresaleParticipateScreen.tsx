import React, { useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Image, TextInput, Alert, ActivityIndicator, Platform } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Buffer } from 'buffer';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { formatNumber } from '../utils/numberFormatting';
import { useCountry } from '../contexts/CountryContext';
import CONFIOLogo from '../assets/png/CONFIO.png';
import { useQuery } from '@apollo/client';
import { GET_ACTIVE_PRESALE, GET_MY_BALANCES } from '../apollo/queries';
import { PresaleWsSession } from '../services/presaleWs';
import { LoadingOverlay } from '../components/LoadingOverlay';
import algorandService from '../services/algorandService';
import { biometricAuthService } from '../services/biometricAuthService';

const colors = {
  primary: '#34d399',
  primaryLight: '#d1fae5',
  primaryDark: '#10b981',
  secondary: '#8b5cf6',
  secondaryLight: '#e9d5ff',
  accent: '#3b82f6',
  neutral: '#f9fafb',
  neutralDark: '#f3f4f6',
  dark: '#111827',
  violet: '#8b5cf6',
  violetLight: '#ddd6fe',
};

type ConfioPresaleParticipateScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

export const ConfioPresaleParticipateScreen = () => {
  const navigation = useNavigation<ConfioPresaleParticipateScreenNavigationProp>();
  const { selectedCountry } = useCountry();

  const [amount, setAmount] = useState('');

  // Use the app's selected country for formatting
  const countryCode = selectedCountry?.[2] || 'VE';
  const formatWithLocale = (num: number, options = {}) =>
    formatNumber(num, countryCode, { minimumFractionDigits: 2, maximumFractionDigits: 2, ...options });

  // Fetch presale data
  const { data, loading, error, refetch } = useQuery(GET_ACTIVE_PRESALE, {
    fetchPolicy: 'cache-and-network',
  });
  const { data: balancesData, loading: balancesLoading } = useQuery(GET_MY_BALANCES, {
    fetchPolicy: 'cache-and-network',
  });

  const [busy, setBusy] = useState(false);

  // Get presale data from query
  const presale = data?.activePresalePhase;
  const presalePrice = presale ? parseFloat(presale.pricePerToken) : 0.25;
  const uiMinPurchase = 10;
  const serverMin = presale ? parseFloat(presale.minPurchase) : uiMinPurchase;
  const minAmount = serverMin || uiMinPurchase;
  const maxAmount = presale ? parseFloat(presale.maxPurchase) : 1000;
  const availableCusd = React.useMemo(
    () => parseFloat(balancesData?.myBalances?.cusd || '0'),
    [balancesData?.myBalances?.cusd]
  );

  const presaleData = {
    raised: presale ? parseFloat(presale.totalRaised) : 0,
    goal: presale ? parseFloat(presale.goalAmount) : 1000000,
    participants: presale?.totalParticipants || 0,
  };

  const percentComplete = Math.min((presaleData.raised / presaleData.goal) * 100, 100);
  const hasExceededGoal = presaleData.raised > presaleData.goal;

  const calculateTokens = (cUsdAmount: number) => {
    return cUsdAmount / presalePrice;
  };

  const parsedAmount = parseFloat(amount) || 0;
  const tokensReceived = calculateTokens(parsedAmount);
  const isValidAmount = parsedAmount >= minAmount && parsedAmount <= maxAmount;
  const exceedsBalance = !balancesLoading && parsedAmount > availableCusd;

  // Ensure user is opted into the presale app (explicit opt-in on enter and before swap)
  // Throws an error if the server returns an error message (e.g., backup check failure)
  const ensureOptedIn = async (session?: any): Promise<boolean> => {
    const s = session || new PresaleWsSession();
    if (!session) await s.open();
    const pack = await s.optinPrepare();

    // Check for server-side error in response
    if (pack && !pack.transactions && pack.error) {
      throw new Error(pack.error);
    }

    const txns = Array.isArray(pack?.transactions) ? pack.transactions : [];
    if (txns.length === 0) return true; // already opted in
    const user = txns.find((t: any) => t?.index === 1 && !t?.signed);
    if (!user) return true; // nothing to sign
    const userTxnBytes = Buffer.from(user.transaction, 'base64');
    const signed = await algorandService.signTransactionBytes(userTxnBytes);
    const userSignedB64 = Buffer.from(signed).toString('base64');
    await s.optinSubmit(userSignedB64, pack.sponsor_transactions || []);
    return true;
  };

  const [initializing, setInitializing] = React.useState(true);
  const [loadingMessage, setLoadingMessage] = React.useState('');
  React.useEffect(() => {
    (async () => {
      try {
        setLoadingMessage('Preparando preventa...');
        const s = new PresaleWsSession();
        await s.open();
        await ensureOptedIn(s);
      } catch (e: any) {
        console.log('[Presale] initial opt-in error', e);
        // Show the error message from server (e.g., backup check failure)
        const errorMessage = e?.message || 'Error al preparar la preventa';
        Alert.alert(
          'No disponible',
          errorMessage,
          [{ text: 'OK', onPress: () => navigation.goBack() }]
        );
        return; // Don't complete initialization
      } finally {
        setInitializing(false);
        setLoadingMessage('');
      }
    })();
  }, []);

  const executeSwap = async () => {
    try {
      const bioOk = await biometricAuthService.authenticate(
        'Autoriza esta compra de preventa (operación crítica)',
        false,
        false
      );
      if (!bioOk) {
        Alert.alert('Se requiere biometría', Platform.OS === 'ios' ? 'Confirma con Face ID o Touch ID para continuar.' : 'Confirma con tu huella digital para continuar.', [{ text: 'OK' }]);
        return;
      }

      setBusy(true);
      const session = new PresaleWsSession();
      await session.open();

      // 0) Ensure presale app opt-in explicitly before preparing
      await ensureOptedIn(session);

      // 1) Prepare purchase
      let pack: any;
      try {
        pack = await session.preparePurchase(amount);
      } catch (e: any) {
        // If the server requires opt-in, perform it silently, then retry
        if (String(e?.message || '').includes('requires_presale_app_optin')) {
          await ensureOptedIn(session);
          // Retry purchase prepare after opt-in
          pack = await session.preparePurchase(amount);
        } else {
          throw e;
        }
      }

      // 2) Sign user purchase txn (index 1)
      const txns = Array.isArray(pack?.transactions) ? pack.transactions : [];
      const sponsorTxns = (pack?.sponsor_transactions || []).slice();
      const userToSign = txns.find((t: any) => t?.index === 1 && (t?.needs_signature || !t?.signed));
      if (!userToSign) throw new Error('purchase_missing_user_txn');
      const userBytes = Buffer.from(userToSign.transaction, 'base64');
      const signedUser = await algorandService.signTransactionBytes(userBytes);
      const signedUserB64 = Buffer.from(signedUser).toString('base64');

      // 3) Submit group
      const purchaseId = pack?.purchase_id || pack?.purchaseId;
      if (!purchaseId) throw new Error('purchase_id_missing');
      try {
        await session.submitPurchase(purchaseId, signedUserB64, sponsorTxns);
      } catch (e: any) {
        // If server requires opt-in at submit, auto opt-in and retry silently
        if (String(e?.message || '').includes('requires_presale_app_optin')) {
          // Ensure opt-in
          await ensureOptedIn(session);
          // Rebuild group and resubmit
          const retryPack = await session.preparePurchase(amount);
          const retryTxns = Array.isArray(retryPack?.transactions) ? retryPack.transactions : [];
          const retrySponsorTxns = (retryPack?.sponsor_transactions || []).slice();
          const retryUserToSign = retryTxns.find((t: any) => t?.index === 1 && (t?.needs_signature || !t?.signed));
          if (!retryUserToSign) throw new Error('purchase_missing_user_txn');
          const retryUserBytes = Buffer.from(retryUserToSign.transaction, 'base64');
          const retrySignedUser = await algorandService.signTransactionBytes(retryUserBytes);
          const retrySignedUserB64 = Buffer.from(retrySignedUser).toString('base64');
          const retryPurchaseId = retryPack?.purchase_id || retryPack?.purchaseId;
          await session.submitPurchase(retryPurchaseId, retrySignedUserB64, retrySponsorTxns);
        } else {
          throw e;
        }
      }

      setBusy(false);
      // Show success message (simplified)
      Alert.alert(
        'Compra exitosa',
        'Tu compra fue exitosa.',
        [{ text: 'Ok', onPress: () => navigation.navigate('BottomTabs', { screen: 'Home' }) }]
      );
      setAmount('');
      refetch();
    } catch (e: any) {
      console.log('[Presale] swap error', e);
      setBusy(false);
      // For opt-in race, we handled silently above. Only show other errors.
      if (!String(e?.message || '').includes('requires_presale_app_optin')) {
        Alert.alert('Error', e?.message || 'No se pudo procesar el intercambio');
      }
    }
  };

  const handleSwap = async () => {
    const iso = selectedCountry?.[2];
    if (iso === 'US') {
      Alert.alert('Restricción', 'Lo sentimos, los residentes de Estados Unidos no pueden participar en la preventa.');
      return;
    }
    if (iso === 'KR') {
      Alert.alert('Restricción', 'Lo sentimos, los ciudadanos/residentes de Corea del Sur no pueden participar en la preventa.');
      return;
    }

    if (!isValidAmount) {
      Alert.alert('Error', `Monto debe estar entre ${minAmount} y ${formatWithLocale(maxAmount)} cUSD`);
      return;
    }
    if (exceedsBalance) {
      Alert.alert('Saldo insuficiente', 'No tienes suficiente cUSD para esta compra.');
      return;
    }

    Alert.alert(
      'Confirmar conversión',
      `¿Convertir ${amount} cUSD a ${formatWithLocale(tokensReceived, { minimumFractionDigits: 2 })} $CONFIO?`,
      [
        {
          text: 'Cancelar',
          style: 'cancel',
        },
        {
          text: 'Confirmar',
          onPress: () => executeSwap(),
        },
      ]
    );
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Convertir a $CONFIO</Text>
          <View style={styles.headerSpacer} />
        </View>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.secondary} />
          <Text style={styles.loadingText}>Cargando datos de preventa...</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (error || !presale) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Convertir a $CONFIO</Text>
          <View style={styles.headerSpacer} />
        </View>
        <View style={styles.errorContainer}>
          <Icon name="alert-circle" size={48} color={colors.secondary} />
          <Text style={styles.errorText}>No hay preventa activa en este momento</Text>
          <TouchableOpacity style={styles.retryButton} onPress={() => refetch()}>
            <Text style={styles.retryButtonText}>Reintentar</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <LoadingOverlay visible={initializing || busy} message={loadingMessage || (busy ? 'Procesando intercambio...' : 'Preparando preventa...')} />
      {busy && (
        <View style={styles.overlay}>
          <ActivityIndicator size="large" color="#fff" />
        </View>
      )}
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="arrow-left" size={24} color="#fff" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Convertir a $CONFIO</Text>
        <View style={styles.headerSpacer} />
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Hero Section */}
        <View style={styles.heroSection}>
          <View style={styles.tokenIcon}>
            <Image
              source={CONFIOLogo}
              style={styles.tokenImage}
              resizeMode="contain"
            />
          </View>
          <Text style={styles.heroTitle}>Preventa Fase {presale?.phaseNumber || 1}</Text>
          <Text style={styles.heroSubtitle}>
            {presale?.name || 'Raíces Fuertes'} - {presale?.phaseNumber === 1 ? 'Donde todo comienza 🌱' : presale?.description || ''}
          </Text>

          <View style={styles.priceBadge}>
            <Text style={styles.priceText}>{presalePrice.toFixed(2)} cUSD por $CONFIO</Text>
          </View>
        </View>

        {/* Current Status */}
        <View style={styles.statusSection}>
          <View style={styles.statusCard}>
            <Text style={styles.statusTitle}>
              {hasExceededGoal ? '¡Meta Superada! 🎉' : `¡Fase ${presale?.phaseNumber || 1} Activa!`}
            </Text>
            <Text style={styles.statusDescription}>
              {hasExceededGoal
                ? `La comunidad ha superado todas las expectativas. La Fase ${presale?.phaseNumber || 1} continúa disponible por tiempo limitado.`
                : `¡La Fase ${presale?.phaseNumber || 1} está activa! Puedes convertir cUSD a $CONFIO al precio más bajo de la historia. Oferta limitada mientras tengamos monedas disponibles.`
              }
            </Text>
            <View style={styles.progressContainer}>
              <Text style={styles.progressLabel}>Recaudado en Fase {presale?.phaseNumber || 1}</Text>
              <Text style={[styles.progressAmount, hasExceededGoal && styles.progressAmountExceeded]}>
                {formatWithLocale(presaleData.raised, { minimumFractionDigits: 0, maximumFractionDigits: 0 })} cUSD
              </Text>

              {hasExceededGoal ? (
                <View style={styles.exceededContainer}>
                  <Text style={styles.progressGoal}>
                    Meta original: {formatWithLocale(presaleData.goal, { minimumFractionDigits: 0, maximumFractionDigits: 0 })} cUSD
                  </Text>
                  <View style={styles.exceededBadge}>
                    <Icon name="trending-up" size={14} color="#fff" />
                    <Text style={styles.exceededText}>
                      {Math.round(((presaleData.raised - presaleData.goal) / presaleData.goal) * 100)}% sobre la meta
                    </Text>
                  </View>
                </View>
              ) : (
                <Text style={styles.progressGoal}>
                  Meta: {formatWithLocale(presaleData.goal, { minimumFractionDigits: 0, maximumFractionDigits: 0 })} cUSD
                </Text>
              )}

              <View style={styles.progressBarContainer}>
                <View style={styles.progressBar}>
                  <View style={[
                    styles.progressFill,
                    { width: `${percentComplete}%` },
                    hasExceededGoal && styles.progressFillExceeded
                  ]} />
                </View>
                <Text style={[styles.progressPercentage, hasExceededGoal && styles.progressPercentageExceeded]}>
                  {hasExceededGoal ? '¡Meta alcanzada!' : `${Math.round(percentComplete)}% completado`}
                </Text>
              </View>

              <View style={styles.participantStats}>
                <Icon name="users" size={14} color={hasExceededGoal ? colors.secondary : colors.primary} />
                <Text style={styles.participantText}>
                  <Text style={[styles.participantCount, hasExceededGoal && styles.participantCountExceeded]}>
                    {formatWithLocale(presaleData.participants, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                  </Text> personas ya participaron
                </Text>
              </View>
            </View>
          </View>
        </View>

        {/* Swap Interface */}
        <View style={styles.swapSection}>
          <Text style={styles.sectionTitle}>Convertir cUSD a $CONFIO</Text>

          <View style={styles.swapCard}>
            <View style={styles.inputContainer}>
              <Text style={styles.inputLabel}>Cantidad de cUSD</Text>
              <View style={styles.inputWrapper}>
                <TextInput
                  style={styles.textInput}
                  value={amount}
                  onChangeText={setAmount}
                  placeholder="Ej: 100"
                  keyboardType="numeric"
                  placeholderTextColor="#9CA3AF"
                />
                <Text style={styles.inputSuffix}>cUSD</Text>
              </View>
              <Text style={styles.inputHelper}>
                Saldo: {formatWithLocale(availableCusd)} cUSD • Mínimo: {minAmount} cUSD • Máximo: {formatWithLocale(maxAmount)} cUSD
              </Text>
            </View>

            {parsedAmount > 0 && (
              <View style={styles.resultContainer}>
                <View style={styles.resultRow}>
                  <Text style={styles.resultLabel}>Recibirás:</Text>
                  <Text style={styles.resultValue}>
                    {formatWithLocale(tokensReceived, { minimumFractionDigits: 2 })} $CONFIO
                  </Text>
                </View>
                <View style={styles.resultRow}>
                  <Text style={styles.resultLabel}>Precio por moneda:</Text>
                  <Text style={styles.resultValue}>{presalePrice.toFixed(2)} cUSD</Text>
                </View>
                {!isValidAmount && (
                  <Text style={styles.errorText}>
                    Monto debe estar entre {minAmount} y {formatWithLocale(maxAmount)} cUSD
                  </Text>
                )}
                {exceedsBalance && (
                  <Text style={styles.errorText}>
                    Saldo insuficiente: tienes {formatWithLocale(availableCusd)} cUSD.
                  </Text>
                )}
              </View>
            )}
          </View>
        </View>

        {/* Swap Execution */}
        <View style={styles.swapSection}>
          <TouchableOpacity
            style={[
              styles.swapButton,
              (!isValidAmount || parsedAmount === 0 || exceedsBalance) && styles.swapButtonDisabled
            ]}
            onPress={handleSwap}
            disabled={!isValidAmount || parsedAmount === 0 || exceedsBalance || busy}
          >
            {busy ? null : (
              <>
                <Icon name="refresh-cw" size={20} color="#fff" />
                <Text style={styles.swapButtonText}>Convertir Ahora</Text>
              </>
            )}
          </TouchableOpacity>

          <View style={styles.lockingNotice}>
            <Icon name="lock" size={16} color="#f59e0b" />
            <Text style={styles.lockingText}>
              <Text style={styles.lockingBold}>Importante:</Text> Las monedas $CONFIO permanecerán bloqueadas hasta que Confío alcance adopción masiva.
              Esto protege el valor y asegura que construyamos juntos el futuro financiero de Latinoamérica.
            </Text>
          </View>

          <View style={styles.riskDisclosure}>
            <Icon name="alert-triangle" size={14} color="#ef4444" />
            <Text style={styles.riskText}>
              <Text style={styles.riskBold}>Inversión de alto riesgo:</Text> Como cualquier negocio nuevo,
              el éxito no está garantizado. Participa con responsabilidad.
            </Text>
          </View>
        </View>

        {/* Benefits */}
        <View style={styles.benefitsSection}>
          <Text style={styles.sectionTitle}>Beneficios de Participar</Text>

          <View style={styles.benefitsList}>
            <View style={styles.benefitItem}>
              <Icon name="star" size={20} color={colors.secondary} />
              <Text style={styles.benefitText}>
                <Text style={styles.benefitBold}>Precio más bajo:</Text> {presalePrice.toFixed(2)} cUSD por moneda vs precios futuros más altos
              </Text>
            </View>

            <View style={styles.benefitItem}>
              <Icon name="users" size={20} color={colors.secondary} />
              <Text style={styles.benefitText}>
                <Text style={styles.benefitBold}>Comunidad fundadora:</Text> Serás parte de la base que construye el futuro
              </Text>
            </View>

            <View style={styles.benefitItem}>
              <Icon name="shield" size={20} color={colors.secondary} />
              <Text style={styles.benefitText}>
                <Text style={styles.benefitBold}>Transparencia total:</Text> Fundador comprometido, sin estafas ni sorpresas
              </Text>
            </View>

            <View style={styles.benefitItem}>
              <Icon name="zap" size={20} color={colors.secondary} />
              <Text style={styles.benefitText}>
                <Text style={styles.benefitBold}>Acceso prioritario:</Text> Serás de los primeros cuando lancemos nuevas funciones
              </Text>
            </View>
          </View>
        </View>

        <View style={styles.bottomPadding} />
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  header: {
    backgroundColor: colors.secondary,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: 12,
    paddingBottom: 20,
    paddingHorizontal: 20,
  },
  backButton: {
    padding: 8,
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#fff',
  },
  headerSpacer: {
    width: 40,
  },
  overlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.35)',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 20,
  },
  scrollView: {
    flex: 1,
  },
  heroSection: {
    alignItems: 'center',
    paddingVertical: 32,
    paddingHorizontal: 20,
    backgroundColor: colors.violetLight,
  },
  tokenIcon: {
    width: 80,
    height: 80,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  tokenImage: {
    width: 80,
    height: 80,
  },
  heroTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 8,
    textAlign: 'center',
  },
  heroSubtitle: {
    fontSize: 16,
    color: '#6B7280',
    textAlign: 'center',
    marginBottom: 16,
    lineHeight: 24,
  },
  priceBadge: {
    backgroundColor: colors.secondary,
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 25,
  },
  priceText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  priceComparison: {
    marginTop: 20,
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 16,
    width: '100%',
    borderWidth: 2,
    borderColor: colors.primary,
  },
  priceComparisonTitle: {
    fontSize: 14,
    fontWeight: 'bold',
    color: colors.dark,
    textAlign: 'center',
    marginBottom: 12,
  },
  priceComparisonRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  priceComparisonItem: {
    flex: 1,
    alignItems: 'center',
  },
  priceComparisonLabel: {
    fontSize: 12,
    color: '#6B7280',
    marginBottom: 4,
  },
  priceComparisonValue: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.dark,
  },
  priceComparisonValueHighlight: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.primary,
  },
  priceComparisonSubtext: {
    fontSize: 11,
    color: '#6B7280',
  },
  priceComparisonNote: {
    fontSize: 12,
    color: colors.primary,
    textAlign: 'center',
    marginTop: 12,
    fontWeight: '600',
  },
  statusSection: {
    paddingHorizontal: 20,
    paddingVertical: 24,
  },
  statusCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 20,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  statusTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 12,
  },
  statusDescription: {
    fontSize: 14,
    color: '#6B7280',
    lineHeight: 22,
    marginBottom: 20,
  },
  progressContainer: {
    alignItems: 'center',
  },
  progressLabel: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 4,
  },
  progressAmount: {
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.primary,
    marginBottom: 2,
  },
  progressGoal: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 16,
  },
  progressBarContainer: {
    width: '100%',
    alignItems: 'center',
  },
  progressBar: {
    width: '100%',
    height: 12,
    backgroundColor: '#E5E7EB',
    borderRadius: 6,
    marginBottom: 8,
    overflow: 'hidden',
  },
  progressFill: {
    height: 12,
    backgroundColor: colors.primary,
    borderRadius: 6,
  },
  progressPercentage: {
    fontSize: 12,
    color: colors.primary,
    fontWeight: '600',
  },
  participantStats: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 12,
  },
  participantText: {
    fontSize: 13,
    color: '#6B7280',
  },
  participantCount: {
    fontWeight: 'bold',
    color: colors.primary,
  },
  progressAmountExceeded: {
    color: colors.secondary,
  },
  exceededContainer: {
    alignItems: 'center',
    gap: 8,
    marginBottom: 16,
  },
  exceededBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.secondary,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    gap: 6,
  },
  exceededText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: 'bold',
  },
  progressFillExceeded: {
    backgroundColor: colors.secondary,
  },
  progressPercentageExceeded: {
    color: colors.secondary,
  },
  participantCountExceeded: {
    color: colors.secondary,
  },
  swapSection: {
    paddingHorizontal: 20,
    paddingBottom: 24,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 20,
    textAlign: 'center',
  },
  swapCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 20,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  inputContainer: {
    marginBottom: 20,
  },
  inputLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.dark,
    marginBottom: 8,
  },
  inputWrapper: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 12,
    paddingHorizontal: 16,
    backgroundColor: '#fff',
  },
  textInput: {
    flex: 1,
    paddingVertical: 16,
    fontSize: 16,
    color: colors.dark,
  },
  inputSuffix: {
    fontSize: 16,
    color: '#6B7280',
    fontWeight: '600',
    marginLeft: 8,
  },
  inputHelper: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 4,
  },
  resultContainer: {
    backgroundColor: colors.violetLight,
    borderRadius: 12,
    padding: 16,
  },
  resultRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  resultLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  resultValue: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.secondary,
  },
  errorText: {
    fontSize: 12,
    color: '#ef4444',
    marginTop: 8,
    textAlign: 'center',
  },
  swapButton: {
    flexDirection: 'row',
    backgroundColor: colors.primary,
    paddingHorizontal: 32,
    paddingVertical: 18,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginBottom: 16,
    shadowColor: colors.primary,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 5,
  },
  swapButtonDisabled: {
    backgroundColor: '#D1D5DB',
    shadowOpacity: 0,
    elevation: 0,
  },
  swapButtonText: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#fff',
  },
  lockingNotice: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: '#fef3c7',
    borderColor: '#f59e0b',
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    marginHorizontal: 20,
    gap: 12,
  },
  lockingText: {
    flex: 1,
    fontSize: 13,
    color: '#92400e',
    lineHeight: 18,
  },
  lockingBold: {
    fontWeight: 'bold',
    color: '#78350f',
  },
  riskDisclosure: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: '#fef2f2',
    borderColor: '#ef4444',
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginHorizontal: 20,
    marginTop: 12,
    gap: 8,
  },
  riskText: {
    flex: 1,
    fontSize: 12,
    color: '#7f1d1d',
    lineHeight: 16,
  },
  riskBold: {
    fontWeight: 'bold',
    color: '#991b1b',
  },
  benefitsSection: {
    paddingHorizontal: 20,
    paddingBottom: 24,
  },
  benefitsList: {
    gap: 16,
  },
  benefitItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  benefitText: {
    flex: 1,
    fontSize: 14,
    color: '#6B7280',
    lineHeight: 20,
  },
  benefitBold: {
    fontWeight: 'bold',
    color: colors.dark,
  },
  bottomPadding: {
    height: 40,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  loadingText: {
    marginTop: 16,
    fontSize: 16,
    color: '#6B7280',
  },
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  errorText: {
    marginTop: 16,
    fontSize: 16,
    color: '#6B7280',
    textAlign: 'center',
    marginBottom: 24,
  },
  retryButton: {
    backgroundColor: colors.secondary,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 20,
  },
  retryButtonText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
});
