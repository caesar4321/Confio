import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Platform, ScrollView, Clipboard, Image, ActivityIndicator } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import QRCode from 'react-native-qrcode-svg';
import USDCLogo from '../assets/png/USDC.png';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import { useAccount } from '../contexts/AccountContext';
import { gql, useMutation, useQuery } from '@apollo/client';
import algorandService from '../services/algorandService';

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

const colors = {
  primary: '#34D399', // emerald-400
  secondary: '#8B5CF6', // violet-500
  accent: '#3B82F6', // blue-500
  background: '#F9FAFB', // gray-50
  text: {
    primary: '#1F2937', // gray-800
    secondary: '#6B7280', // gray-500
  },
  warning: {
    background: '#FEF3C7', // yellow-50
    border: '#FDE68A', // yellow-200
    text: '#92400E', // yellow-800
    icon: '#D97706', // yellow-600
  },
};

type TokenType = 'usdc' | 'cusd' | 'confio';

interface RouteParams {
  tokenType?: TokenType;
}

interface TokenConfig {
  name: string;
  fullName: string;
  logo: any;
  color: string;
  description: string;
  subtitle: string;
  warning: string;
  instructions: Array<{
    step: string;
    title: string;
    description: string;
  }>;
}

// Token configuration
const tokenConfig: Record<TokenType, TokenConfig> = {
  usdc: {
    name: 'USDC',
    fullName: 'USD Coin',
    logo: USDCLogo,
    color: colors.accent,
    description: 'Recibe USDC desde cualquier wallet',
    subtitle: 'Envía USDC desde tu wallet externo a esta dirección',
            warning: 'Solo envía USDC en la red Algorand. Otras monedas o redes resultarán en pérdida permanente de fondos.',
    instructions: [
      {
        step: '1',
        title: 'Abre tu wallet externo',
        description: 'Algorand Wallet, Pera Wallet, Binance, etc.'
      },
      {
        step: '2',
        title: 'Selecciona enviar USDC',
        description: 'Asegúrate de estar en la red Algorand'
      },
      {
        step: '3',
        title: 'Pega la dirección de arriba',
        description: 'O escanea el código QR'
      },
      {
        step: '4',
        title: 'Confirma la transacción',
        description: 'El USDC aparecerá en 1-3 minutos'
      }
    ]
  },
  cusd: {
    name: 'cUSD',
    fullName: 'Confío Dollar',
    logo: cUSDLogo,
    color: colors.primary,
    description: 'Recibe cUSD desde cualquier wallet',
    subtitle: 'Envía cUSD desde tu wallet externo a esta dirección',
            warning: 'Solo envía cUSD en la red Algorand. Otras monedas o redes resultarán en pérdida permanente de fondos.',
    instructions: [
      {
        step: '1',
        title: 'Abre tu wallet externo',
        description: 'Algorand Wallet, Pera Wallet, Binance, etc.'
      },
      {
        step: '2',
        title: 'Selecciona enviar cUSD',
        description: 'Asegúrate de estar en la red Algorand'
      },
      {
        step: '3',
        title: 'Pega la dirección de arriba',
        description: 'O escanea el código QR'
      },
      {
        step: '4',
        title: 'Confirma la transacción',
        description: 'El cUSD aparecerá en 1-3 minutos'
      }
    ]
  },
  confio: {
    name: 'CONFIO',
            fullName: 'Confío',
    logo: CONFIOLogo,
    color: colors.secondary,
    description: 'Recibe CONFIO desde cualquier wallet',
    subtitle: 'Envía CONFIO desde tu wallet externo a esta dirección',
            warning: 'Solo envía CONFIO en la red Algorand. Otras monedas o redes resultarán en pérdida permanente de fondos.',
    instructions: [
      {
        step: '1',
        title: 'Abre tu wallet externo',
        description: 'Algorand Wallet, Pera Wallet, Binance, etc.'
      },
      {
        step: '2',
        title: 'Selecciona enviar CONFIO',
        description: 'Asegúrate de estar en la red Algorand'
      },
      {
        step: '3',
        title: 'Pega la dirección de arriba',
        description: 'O escanea el código QR'
      },
      {
        step: '4',
        title: 'Confirma la transacción',
        description: 'El CONFIO aparecerá en 1-3 minutos'
      }
    ]
  }
};

const DepositScreen = () => {
  const navigation = useNavigation();
  const route = useRoute();
  const insets = useSafeAreaInsets();
  const [copied, setCopied] = useState(false);
  const [isOptedIn, setIsOptedIn] = useState<boolean | null>(null);
  const [checkingOptIn, setCheckingOptIn] = useState(true);
  const [optingIn, setOptingIn] = useState(false);
  const { activeAccount } = useAccount();
  
  // Get token type from route params, default to 'usdc' for backward compatibility
  const tokenType: TokenType = (route.params as RouteParams)?.tokenType || 'usdc';
  const config = tokenConfig[tokenType];
  
  // Use the real Algorand address from the active account
  const depositAddress = activeAccount?.algorandAddress || "";

  // GraphQL mutation for opt-in
  const [optInToAsset] = useMutation(OPT_IN_TO_USDC, {
    onError: (error) => {
      console.error('[DepositScreen] Mutation error:', error);
      setOptingIn(false);
    }
  });
  
  // Query to check opt-in status
  const { data: optInData, loading: loadingOptIns, refetch: refetchOptIns } = useQuery(CHECK_ASSET_OPT_INS, {
    fetchPolicy: 'network-only',
  });

  // Check if user is opted in to USDC
  useEffect(() => {
    if (optInData?.checkAssetOptIns) {
      const { assetDetails } = optInData.checkAssetOptIns;
      
      // Check if USDC is in the opted-in assets
      // The backend will include USDC in assetDetails if opted in
      const hasUSDC = assetDetails && Object.values(assetDetails).some((asset: any) => 
        asset.symbol === 'USDC'
      );
      
      setIsOptedIn(hasUSDC);
      setCheckingOptIn(false);
    } else if (!loadingOptIns) {
      setCheckingOptIn(false);
    }
  }, [optInData, loadingOptIns, tokenType]);

  const handleOptIn = async () => {
    try {
      setOptingIn(true);
      console.log('[DepositScreen] Starting USDC opt-in...');
      
      // Request USDC opt-in from backend
      console.log('[DepositScreen] Calling optInToAsset mutation...');
      const { data, errors } = await optInToAsset({
        variables: { assetType: 'USDC' }
      });
      
      if (errors) {
        console.error('[DepositScreen] GraphQL errors:', errors);
        return;
      }
      
      console.log('[DepositScreen] Opt-in mutation response:', data);
      
      if (data?.optInToAssetByType?.alreadyOptedIn) {
        // Already opted in
        console.log('[DepositScreen] User already opted in to USDC');
        setIsOptedIn(true);
        await refetchOptIns();
        return;
      }
      
      if (data?.optInToAssetByType?.success && data.optInToAssetByType.requiresUserSignature) {
        // Need to sign the transaction
        console.log('[DepositScreen] Got transactions to sign');
        const userTxn = data.optInToAssetByType.userTransaction;
        const sponsorTxn = data.optInToAssetByType.sponsorTransaction;
        
        console.log('[DepositScreen] User transaction:', userTxn ? 'present' : 'missing');
        console.log('[DepositScreen] Sponsor transaction:', sponsorTxn ? 'present' : 'missing');
        
        // Sign and submit the transaction
        console.log('[DepositScreen] Signing and submitting transaction...');
        const txId = await algorandService.signAndSubmitSponsoredTransaction(
          userTxn,
          sponsorTxn
        );
        
        console.log('[DepositScreen] Transaction result:', txId);
        
        if (txId) {
          // Successfully opted in
          console.log('[DepositScreen] Successfully opted in to USDC:', txId);
          await refetchOptIns();
          setIsOptedIn(true);
        } else {
          console.error('[DepositScreen] Failed to submit opt-in transaction');
        }
      } else {
        console.error('[DepositScreen] Failed to generate opt-in transaction:', data?.optInToAssetByType?.error);
      }
    } catch (error) {
      console.error('[DepositScreen] Error during USDC opt-in:', error);
    } finally {
      setOptingIn(false);
    }
  };

  const handleCopy = async () => {
    await Clipboard.setString(depositAddress);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

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
      paddingTop: insets.top + 8,
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
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: '#ffffff',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
    padding: 8,
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
    padding: 24,
    marginHorizontal: 16,
    marginBottom: 16,
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
  addressTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.text.primary,
    marginBottom: 16,
  },
  qrContainer: {
    alignItems: 'center',
    marginBottom: 24,
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
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  copyButton: {
    padding: 8,
    marginLeft: 8,
  },
  copiedButton: {
    backgroundColor: colors.primary + '20',
    borderRadius: 8,
  },
  shareButton: {
    backgroundColor: colors.accent,
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
  },
  shareButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '500',
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
      {/* Header */}
      <View style={[styles.header, { backgroundColor: config.color }]}>
        <View style={styles.headerContent}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="arrow-left" size={24} color="#ffffff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Depositar {config.name}</Text>
          <View style={styles.placeholder} />
        </View>
        
        <View style={styles.headerInfo}>
          <View style={styles.logoContainer}>
            <Image source={config.logo} style={styles.logo} />
          </View>
          <Text style={styles.headerSubtitle}>{config.description}</Text>
          <Text style={styles.headerDescription}>{config.subtitle}</Text>
        </View>
      </View>

      <ScrollView style={styles.content} contentContainerStyle={styles.contentContainer}>
        {/* Show loading state while checking opt-in status for USDC */}
        {tokenType === 'usdc' && checkingOptIn ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={config.color} />
            <Text style={styles.loadingText}>Verificando configuración...</Text>
          </View>
        ) : tokenType === 'usdc' && isOptedIn === false ? (
          /* Show opt-in prompt for USDC if not opted in */
          <View style={styles.optInContainer}>
            <View style={[styles.optInIcon, { backgroundColor: config.color + '20' }]}>
              <Icon name="unlock" size={40} color={config.color} />
            </View>
            <Text style={styles.optInTitle}>Activa tu dirección USDC</Text>
            <Text style={styles.optInDescription}>
              Para recibir USDC, primero necesitas activar tu dirección en la red Algorand. 
              Este es un proceso único y gratuito que habilita tu wallet para recibir USDC.
            </Text>
            <TouchableOpacity 
              style={[styles.optInButton, { backgroundColor: config.color }]}
              onPress={handleOptIn}
              disabled={optingIn}
            >
              {optingIn ? (
                <ActivityIndicator size="small" color="#ffffff" />
              ) : (
                <>
                  <Icon name="check-circle" size={20} color="#ffffff" />
                  <Text style={styles.optInButtonText}>Activar USDC</Text>
                </>
              )}
            </TouchableOpacity>
          </View>
        ) : (
          <>
            {/* Warning Section */}
            <View style={styles.warningContainer}>
              <Icon name="alert-triangle" size={20} color={colors.warning.icon} style={styles.warningIcon} />
              <View style={styles.warningContent}>
                <Text style={styles.warningTitle}>¡Importante!</Text>
                <Text style={styles.warningText}>
                  {config.warning}
                </Text>
              </View>
            </View>

            {/* Address Section */}
            <View style={styles.addressCard}>
          <Text style={styles.addressTitle}>Tu dirección {config.name}</Text>
          
          {/* QR Code */}
          <View style={styles.qrContainer}>
            <QRCode
              value={depositAddress}
              size={192}
              backgroundColor="white"
              color="black"
            />
          </View>
          
          {/* Address */}
          <View style={styles.addressContainer}>
            <Text style={styles.addressLabel}>Dirección de depósito:</Text>
            <View style={styles.addressRow}>
              <Text style={styles.addressText}>{depositAddress}</Text>
              <TouchableOpacity 
                onPress={handleCopy}
                style={[styles.copyButton, copied && styles.copiedButton]}
              >
                <Icon 
                  name={copied ? "check" : "copy"} 
                  size={16} 
                  color={copied ? colors.primary : colors.text.secondary} 
                />
              </TouchableOpacity>
            </View>
          </View>
          
          <TouchableOpacity style={[styles.shareButton, { backgroundColor: config.color }]}>
            <Text style={styles.shareButtonText}>Compartir dirección</Text>
          </TouchableOpacity>
        </View>

            {/* Instructions */}
            <View style={styles.instructionsCard}>
              <Text style={styles.instructionsTitle}>Pasos para depositar</Text>
              
              {config.instructions.map((instruction, index) => (
                <View key={index} style={styles.instructionStep}>
                  <View style={[styles.stepNumber, { backgroundColor: config.color }]}>
                    <Text style={styles.stepNumberText}>{instruction.step}</Text>
                  </View>
                  <View style={styles.stepContent}>
                    <Text style={styles.stepTitle}>{instruction.title}</Text>
                    <Text style={styles.stepDescription}>{instruction.description}</Text>
                  </View>
                </View>
              ))}
            </View>
          </>
        )}
      </ScrollView>
    </View>
  );
};

export default DepositScreen; 