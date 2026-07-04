import React, { useState, useEffect, useCallback } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Platform, ScrollView, Image, ActivityIndicator, Share, Linking } from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import { useNavigation, useRoute, useFocusEffect } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import QRCode from 'react-native-qrcode-svg';
import USDCLogo from '../assets/png/USDC.png';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import { useAccount } from '../contexts/AccountContext';
import { gql, useMutation, useQuery } from '@apollo/client';
import algorandService from '../services/algorandService';
import businessOptInService from '../services/businessOptInService';
import { cusdAppOptInService } from '../services/cusdAppOptInService';
import { useBackupEnforcement } from '../hooks/useBackupEnforcement';
import { technicalFontFamily } from '../utils/fontFamily';

// GraphQL mutation for USDC opt-in specifically
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

// GraphQL query to check current opt-ins
const CHECK_ASSET_OPT_INS = gql`
  query CheckAssetOptIns {
    checkAssetOptIns {
      optedInAssets
      assetDetails
    }
  }
`;

// Unified deposit configuration — same address for all tokens
const depositConfig = {
  description: 'Recibe cUSD, USDC o CONFIO en la red de Algorand',
  subtitle: 'Envía fondos desde tu wallet externo a esta dirección',
  warning: '⚠️ Solo acepta cUSD, USDC y CONFIO en la red de Algorand. El depósito de cualquier otro activo resultará en pérdida permanente de fondos.',
  autoConvertNote: 'Los depósitos de USDC se convierten automáticamente a cUSD como respaldo de reserva 1:1.',
  instructions: [
    {
      step: '1',
      title: 'Abre tu wallet externo',
      description: 'Pera Wallet, Defly, Binance, etc.'
    },
    {
      step: '2',
      title: 'Selecciona enviar cUSD, USDC o CONFIO',
      description: 'Asegúrate de estar en la red de Algorand'
    },
    {
      step: '3',
      title: 'Pega la dirección de arriba',
      description: 'O escanea el código QR'
    },
    {
      step: '4',
      title: 'Confirma la transacción',
      description: 'Tu saldo aparecerá en 1-3 minutos'
    }
  ]
};

import { AuthService } from '../services/authService';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
import { Header } from '../navigation/Header';

// ... (imports)

const DepositScreen = () => {
  const navigation = useNavigation();
  const route = useRoute();
  // const insets = useSafeAreaInsets(); // Avoid hook to prevent crashes if provider not ready
  const [copied, setCopied] = useState(false);
  const [hasDepositAccess, setHasDepositAccess] = useState(Platform.OS === 'ios');
  const [checkingBackupAccess, setCheckingBackupAccess] = useState(Platform.OS !== 'ios');
  const [isOptedIn, setIsOptedIn] = useState<boolean | null>(null);
  const [checkingOptIn, setCheckingOptIn] = useState(true);
  const [optingIn, setOptingIn] = useState(false);
  const [needsWalletSetup, setNeedsWalletSetup] = useState(false);
  const [localAddress, setLocalAddress] = useState<string>('');
  const { checkBackupEnforcement, BackupEnforcementModal } = useBackupEnforcement();

  const { activeAccount, refreshAccounts } = useAccount();

  const config = depositConfig;

  // Fetch fresh address from Keychain (AuthService) to ensure we have V2 address post-migration
  useEffect(() => {
    const fetchAddress = async () => {
      try {
        const authService = AuthService.getInstance();
        const address = await authService.getAlgorandAddress();
        if (address) {
          setLocalAddress(address);
        }
      } catch (e) {
      }
    };
    fetchAddress();
  }, [activeAccount?.id]); // Refetch if account changes

  // Use the real Algorand address from Keychain if available, fallback to context
  const depositAddress = localAddress || activeAccount?.algorandAddress || "";

  // GraphQL mutation for opt-in
  const [optInToAsset] = useMutation(OPT_IN_TO_USDC, {
    onError: (error) => {      setOptingIn(false);
    }
  });

  // Query to check opt-in status
  const { data: optInData, loading: loadingOptIns, refetch: refetchOptIns } = useQuery(CHECK_ASSET_OPT_INS, {
    fetchPolicy: 'network-only',
    onError: (err) => {
      // If the opt-in status query fails (e.g., auth race), default to showing the activation CTA      setIsOptedIn(false);
      setNeedsWalletSetup(false);
      setCheckingOptIn(false);
    }
  });

  // Check if user is opted in to USDC and whether additional setup is needed
  useEffect(() => {

    if (optInData?.checkAssetOptIns) {
      const { assetDetails, optedInAssets } = optInData.checkAssetOptIns;


      // Parse assetDetails if it's a string
      let parsedAssetDetails = assetDetails;
      if (typeof assetDetails === 'string') {
        try {
          parsedAssetDetails = JSON.parse(assetDetails);
        } catch (e) {
          parsedAssetDetails = {};
        }
      }

      // Check all required assets for unified deposit
      const values = parsedAssetDetails ? (Object.values(parsedAssetDetails) as any[]) : [];
      const hasUSDC = values.some((asset: any) => asset.symbol === 'USDC');
      const hasCUSD = values.some((asset: any) => asset.symbol === 'cUSD');
      const hasCONFIO = values.some((asset: any) => asset.symbol === 'CONFIO');

      setIsOptedIn(hasUSDC);
      setNeedsWalletSetup(Boolean(hasUSDC && (!hasCUSD || !hasCONFIO)));

      setCheckingOptIn(false);
    } else if (!loadingOptIns) {
      setCheckingOptIn(false);
    }
  }, [optInData, loadingOptIns]);

  // Ensure we always re-check opt-in status when returning to this screen
  useFocusEffect(
    useCallback(() => {
      let isActive = true;

      const enforceBackup = async () => {
        if (Platform.OS === 'ios') {
          setHasDepositAccess(true);
          setCheckingBackupAccess(false);
          return;
        }

        setCheckingBackupAccess(true);
        const allowed = await checkBackupEnforcement('deposit');
        if (!isActive) {
          return;
        }

        setHasDepositAccess(allowed);
        setCheckingBackupAccess(false);

        if (!allowed) {
          navigation.goBack();
        }
      };

      void enforceBackup();

      if (typeof refetchOptIns === 'function') {
        refetchOptIns();
      }
      return () => {
        isActive = false;
      };
    }, [checkBackupEnforcement, navigation, refetchOptIns])
  );

  const handleOptIn = async () => {
    try {
      setOptingIn(true);

      // Step A: Ensure cUSD application opt-in (sponsored) for business accounts
      try {
        const appOptIn = await cusdAppOptInService.handleAppOptIn(activeAccount);
      } catch (e) {
      }

      // Step B: Ensure asset opt-ins for cUSD and CONFIO on business accounts
      try {
        const ok = await businessOptInService.checkAndHandleOptIns((msg) => {
        });
      } catch (e) {
      }

      // Request USDC opt-in from backend
      const { data, errors } = await optInToAsset({
        variables: { assetType: 'USDC' }
      });

      if (errors) {        return;
      }


      if (data?.optInToAssetByType?.alreadyOptedIn) {
        // Already opted in
        setIsOptedIn(true);
        setNeedsWalletSetup(false);
        await refetchOptIns();
        return;
      }

      if (data?.optInToAssetByType?.success && data.optInToAssetByType.requiresUserSignature) {
        // Need to sign the transaction
        const userTxn = data.optInToAssetByType.userTransaction;
        const sponsorTxn = data.optInToAssetByType.sponsorTransaction;


        // Ensure wallet is initialized before signing (Critical for cold starts)


        // Sign and submit the transaction
        const txId = await algorandService.signAndSubmitSponsoredTransaction(
          userTxn,
          sponsorTxn
        );


        if (txId) {
          // Successfully opted in
          await refetchOptIns();
          // Refresh accounts to ensure address is loaded
          await refreshAccounts();
          setIsOptedIn(true);
          setNeedsWalletSetup(false);
        } else {        }
      } else {      }
    } catch (error) {
    } finally {
      setOptingIn(false);
    }
  };

  // No separate CTA; setup runs within handleOptIn when needed

  // No additional setup CTA; keep UI simple for USDC

  const handleCopy = async () => {
    await Clipboard.setString(depositAddress);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleShare = useCallback(async () => {
    if (!depositAddress) {
      return;
    }
    try {
      const message = `Esta es mi dirección Confío:\n${depositAddress}`;
      await Share.share({
        title: 'Dirección Confío',
        message,
      });
    } catch (error) {
    }
  }, [depositAddress]);

  // Move styles inside the component to use insets
  const styles = StyleSheet.create({
    container: {
      flex: 1,
      backgroundColor: colors.background,
    },
    content: {
      flex: 1,
    },
    contentContainer: {
      paddingBottom: 32,
    },
    header: {
      paddingTop: 12,
      paddingBottom: 32,
      paddingHorizontal: 16,
    },
    headerContent: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: 24,
    },
    backButton: {
      padding: 8,
    },
    headerTitle: {
      fontSize: 18,
      fontWeight: 'bold',
      color: '#ffffff',
    },
    placeholder: {
      width: 40,
    },
    headerInfo: {
      alignItems: 'center',
    },
    logoContainer: {
      flexDirection: 'row',
      justifyContent: 'center',
      alignItems: 'center',
      marginBottom: 16,
    },
    logoCircle: {
      width: 48,
      height: 48,
      borderRadius: 24,
      backgroundColor: '#ffffff',
      justifyContent: 'center',
      alignItems: 'center',
      padding: 6,
      borderWidth: 2,
      borderColor: 'rgba(255,255,255,0.6)',
      marginHorizontal: -4,
    },
    logoCircleCenter: {
      width: 56,
      height: 56,
      borderRadius: 28,
      zIndex: 1,
    },
    logo: {
      width: '100%',
      height: '100%',
      resizeMode: 'contain',
    },
    headerSubtitle: {
      fontSize: 20,
      fontWeight: 'bold',
      color: '#ffffff',
      marginBottom: 8,
    },
    headerDescription: {
      fontSize: 14,
      color: '#ffffff',
      opacity: 0.8,
    },
    warningContainer: {
      backgroundColor: colors.warning.background,
      borderWidth: 1,
      borderColor: colors.warning.border,
      borderRadius: 12,
      padding: 16,
      marginHorizontal: 16,
      marginTop: 16,
      marginBottom: 16,
      flexDirection: 'row',
    },
    warningIcon: {
      marginRight: 12,
      marginTop: 2,
    },
    warningContent: {
      flex: 1,
    },
    warningTitle: {
      fontSize: 16,
      fontWeight: 'bold',
      color: colors.warning.text,
      marginBottom: 4,
    },
    warningText: {
      fontSize: 14,
      color: colors.warning.text,
    },
    addressCard: {
      backgroundColor: '#ffffff',
      borderRadius: 16,
      padding: 20,
      marginHorizontal: 16,
      marginBottom: 12,
      alignItems: 'center',
    },
    networkPill: {
      backgroundColor: '#FEF3C7',
      borderRadius: 12,
      paddingHorizontal: 12,
      paddingVertical: 5,
      alignSelf: 'center',
      marginBottom: 12,
    },
    networkPillText: { fontSize: 12, fontWeight: '700', color: '#92400E' },
    explorerLink: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 4,
      marginTop: 12,
    },
    explorerLinkText: { fontSize: 12, color: '#6B7280' },
    addressTitle: {
      fontSize: 16,
      fontWeight: '700',
      color: colors.text.primary,
      marginBottom: 12,
    },
    addressMono: {
      fontSize: 12,
      color: colors.text.secondary,
      textAlign: 'center',
      marginTop: 12,
      paddingHorizontal: 8,
      fontFamily: technicalFontFamily,
    },
    btnRow: { flexDirection: 'row', gap: 10, marginTop: 14 },
    copyBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      backgroundColor: colors.primary,
      borderRadius: 12,
      paddingHorizontal: 18,
      paddingVertical: 11,
    },
    copyBtnText: { color: '#fff', fontSize: 14, fontWeight: '700' },
    shareBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      borderWidth: 1.5,
      borderColor: colors.primaryDark,
      borderRadius: 12,
      paddingHorizontal: 18,
      paddingVertical: 11,
    },
    shareBtnText: { color: colors.primaryDark, fontSize: 14, fontWeight: '700' },
    warnCard: {
      flexDirection: 'row',
      gap: 10,
      backgroundColor: '#FEF3C7',
      borderRadius: 12,
      padding: 14,
      marginHorizontal: 16,
      marginTop: 16,
      marginBottom: 12,
    },
    warnText: { flex: 1, fontSize: 13, color: '#92400E', lineHeight: 18 },
    warnStrong: { fontWeight: '800' },
    becomesCard: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      backgroundColor: '#ffffff',
      borderRadius: 12,
      padding: 14,
      marginHorizontal: 16,
      marginBottom: 12,
    },
    becomesLogo: { width: 30, height: 30, borderRadius: 15 },
    becomesText: { flex: 1, fontSize: 13, color: colors.text.secondary, lineHeight: 18 },
    stepsSectionTitle: {
      fontSize: 16,
      fontWeight: '700',
      color: colors.text.primary,
      marginHorizontal: 16,
      marginBottom: 10,
      marginTop: 4,
    },
    stepCard: {
      flexDirection: 'row',
      gap: 12,
      backgroundColor: '#ffffff',
      borderRadius: 12,
      padding: 14,
      marginHorizontal: 16,
      marginBottom: 8,
    },
    stepNum: {
      width: 26,
      height: 26,
      borderRadius: 13,
      backgroundColor: colors.primaryLight,
      alignItems: 'center',
      justifyContent: 'center',
    },
    stepNumText: { fontSize: 13, fontWeight: '800', color: colors.primaryDark },
    stepCardTitle: { fontSize: 14, fontWeight: '600', color: colors.text.primary },
    stepCardBody: { fontSize: 12, color: colors.text.secondary, marginTop: 2, lineHeight: 17 },
    qrContainer: {
      alignItems: 'center',
    },
    addressContainer: {
      marginBottom: 16,
    },
    addressLabel: {
      fontSize: 14,
      color: colors.text.secondary,
      marginBottom: 8,
    },
    addressRow: {
      flexDirection: 'row',
      alignItems: 'center',
    },
    addressText: {
      flex: 1,
      fontSize: 14,
      color: colors.text.primary,
      fontFamily: technicalFontFamily,
    },
    copyButton: {
      padding: 8,
      marginLeft: 8,
    },
    copiedButton: {
      backgroundColor: colors.primary + '20',
      borderRadius: 8,
    },
    instructionsCard: {
      backgroundColor: '#ffffff',
      borderRadius: 16,
      padding: 24,
      marginHorizontal: 16,
      marginBottom: 32,
      ...Platform.select({
        ios: {
          shadowColor: '#000',
          shadowOffset: { width: 0, height: 2 },
          shadowOpacity: 0.1,
          shadowRadius: 4,
        },
        android: {
          elevation: 2,
        },
      }),
    },
    instructionsTitle: {
      fontSize: 18,
      fontWeight: 'bold',
      color: colors.text.primary,
      marginBottom: 16,
    },
    instructionStep: {
      flexDirection: 'row',
      marginBottom: 16,
    },
    stepNumber: {
      width: 24,
      height: 24,
      borderRadius: 12,
      backgroundColor: colors.accent,
      justifyContent: 'center',
      alignItems: 'center',
      marginRight: 12,
    },
    stepNumberText: {
      color: '#ffffff',
      fontSize: 14,
      fontWeight: 'bold',
    },
    stepContent: {
      flex: 1,
    },
    stepTitle: {
      fontSize: 16,
      fontWeight: '500',
      color: colors.text.primary,
      marginBottom: 4,
    },
    stepDescription: {
      fontSize: 14,
      color: colors.text.secondary,
    },
    optInContainer: {
      backgroundColor: '#ffffff',
      borderRadius: 16,
      padding: 24,
      marginHorizontal: 16,
      marginBottom: 16,
      alignItems: 'center',
      ...Platform.select({
        ios: {
          shadowColor: '#000',
          shadowOffset: { width: 0, height: 2 },
          shadowOpacity: 0.1,
          shadowRadius: 4,
        },
        android: {
          elevation: 2,
        },
      }),
    },
    optInIcon: {
      width: 80,
      height: 80,
      borderRadius: 40,
      backgroundColor: colors.accent + '20',
      justifyContent: 'center',
      alignItems: 'center',
      marginBottom: 16,
    },
    optInTitle: {
      fontSize: 20,
      fontWeight: 'bold',
      color: colors.text.primary,
      marginBottom: 8,
      textAlign: 'center',
    },
    optInDescription: {
      fontSize: 14,
      color: colors.text.secondary,
      textAlign: 'center',
      marginBottom: 24,
      paddingHorizontal: 16,
    },
    optInButton: {
      backgroundColor: colors.accent,
      paddingVertical: 14,
      paddingHorizontal: 32,
      borderRadius: 8,
      flexDirection: 'row',
      alignItems: 'center',
    },
    optInButtonText: {
      color: '#ffffff',
      fontSize: 16,
      fontWeight: '600',
      marginLeft: 8,
    },
    loadingContainer: {
      flex: 1,
      justifyContent: 'center',
      alignItems: 'center',
    },
    loadingText: {
      fontSize: 16,
      color: colors.text.secondary,
      marginTop: 16,
    },
  });

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Depositar"
        backgroundColor={colors.primary}
        isLight
        showBackButton
      />

      <ScrollView style={styles.content} contentContainerStyle={styles.contentContainer}>
        {/* Hero section */}
        <View style={{ backgroundColor: colors.primary, paddingBottom: 32, paddingHorizontal: 16 }}>
          <View style={styles.headerInfo}>
            <View style={styles.logoContainer}>
              <View style={styles.logoCircle}>
                <Image source={cUSDLogo} style={styles.logo} />
              </View>
              <View style={[styles.logoCircle, styles.logoCircleCenter]}>
                <Image source={USDCLogo} style={styles.logo} />
              </View>
              <View style={styles.logoCircle}>
                <Image source={CONFIOLogo} style={styles.logo} />
              </View>
            </View>
            <Text style={styles.headerSubtitle}>{config.description}</Text>
            <Text style={styles.headerDescription}>{config.subtitle}</Text>
          </View>
        </View>
        {/* Show loading state while checking opt-in status */}
        {checkingBackupAccess || !hasDepositAccess ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={colors.primary} />
            <Text style={styles.loadingText}>Verificando respaldo...</Text>
          </View>
        ) : checkingOptIn ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={colors.primary} />
            <Text style={styles.loadingText}>Verificando configuración...</Text>
          </View>
        ) : ((isOptedIn !== true) || needsWalletSetup === true) ? (
          /* Single friendly CTA for USDC opt-in */
          <View style={styles.optInContainer}>
            <View style={[styles.optInIcon, { backgroundColor: colors.primary + '20' }]}>
              <Icon name="unlock" size={40} color={colors.primary} />
            </View>
            <Text style={styles.optInTitle}>Activa tu dirección</Text>
            <Text style={styles.optInDescription}>
              Activa tu dirección para recibir depósitos. Es un paso único y gratis.
            </Text>
            <TouchableOpacity
              style={[styles.optInButton, { backgroundColor: colors.primary }]}
              onPress={handleOptIn}
              disabled={optingIn}
            >
              {optingIn ? (
                <ActivityIndicator size="small" color="#ffffff" />
              ) : (
                <>
                  <Icon name="check-circle" size={20} color="#ffffff" />
                  <Text style={styles.optInButtonText}>Activar dirección</Text>
                </>
              )}
            </TouchableOpacity>
          </View>
        ) : (
          <>
            {/* Warning — ReceiveSavings grammar: borderless amber, inline
                bold on the tokens that matter, no shouting title */}
            <View style={styles.warnCard}>
              <Icon name="alert-triangle" size={18} color="#B45309" />
              <Text style={styles.warnText}>
                Envía únicamente <Text style={styles.warnStrong}>cUSD, USDC o CONFIO</Text>{' '}
                por la red <Text style={styles.warnStrong}>Algorand</Text>. El depósito de
                cualquier otro activo o por otra red resultará en pérdida permanente de
                los fondos.
              </Text>
            </View>

            {/* What it becomes — the becomesCard grammar (BSC sibling shows
                cUSD+; here USDC auto-converts to Confío Dollar 1:1) */}
            <View style={styles.becomesCard}>
              <Image source={cUSDLogo} style={styles.becomesLogo} />
              <Text style={styles.becomesText}>
                Los depósitos de USDC se convierten automáticamente en{' '}
                <Text style={styles.warnStrong}>Confío Dollar (cUSD)</Text> con respaldo
                1:1.
              </Text>
            </View>

            {/* Address Section */}
            <View style={styles.addressCard}>
              <Text style={styles.addressTitle}>Tu dirección de depósito</Text>
              <View style={styles.networkPill}>
                <Text style={styles.networkPillText}>Red: Algorand</Text>
              </View>

              {/* QR Code */}
              <View style={styles.qrContainer}>
                <QRCode
                  value={depositAddress || "loading"}
                  size={192}
                  backgroundColor="white"
                  color="black"
                />
              </View>

              <Text style={styles.addressMono}>{depositAddress}</Text>
              <View style={styles.btnRow}>
                <TouchableOpacity
                  style={styles.copyBtn}
                  onPress={handleCopy}
                  activeOpacity={0.85}
                  accessibilityRole="button"
                  accessibilityLabel="Copiar dirección"
                >
                  <Icon name={copied ? 'check' : 'copy'} size={16} color="#fff" />
                  <Text style={styles.copyBtnText}>{copied ? 'Copiada' : 'Copiar'}</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.shareBtn}
                  onPress={handleShare}
                  activeOpacity={0.85}
                  accessibilityRole="button"
                  accessibilityLabel="Compartir dirección"
                >
                  <Icon name="share-2" size={16} color={colors.primaryDark} />
                  <Text style={styles.shareBtnText}>Compartir</Text>
                </TouchableOpacity>
              </View>
              <TouchableOpacity
                style={styles.explorerLink}
                onPress={() => {
                  const base = __DEV__
                    ? 'https://testnet.explorer.perawallet.app'
                    : 'https://explorer.perawallet.app';
                  Linking.openURL(`${base}/address/${depositAddress}/`);
                }}
              >
                <Text style={styles.explorerLinkText}>Ver en Pera Explorer</Text>
                <Icon name="external-link" size={12} color="#6B7280" />
              </TouchableOpacity>
            </View>

            {/* Instructions — per-step cards, the ReceiveSavings grammar */}
            <Text style={styles.stepsSectionTitle}>Cómo enviar</Text>
            {config.instructions.map((instruction, index) => (
              <View key={index} style={styles.stepCard}>
                <View style={styles.stepNum}>
                  <Text style={styles.stepNumText}>{instruction.step}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.stepCardTitle}>{instruction.title}</Text>
                  <Text style={styles.stepCardBody}>{instruction.description}</Text>
                </View>
              </View>
            ))}
          </>
        )}
      </ScrollView>
      <BackupEnforcementModal />
    </View >
  );
};

export default DepositScreen; 
