import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  StatusBar,
  SafeAreaView,
  Alert,
  Animated,
  Modal,
  TextInput,
  KeyboardAvoidingView,
  Platform,
  Keyboard,
  TouchableWithoutFeedback,
  PermissionsAndroid,
  Image,
  ActivityIndicator,
  Linking,
  Dimensions,
} from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { MainStackParamList } from '../types/navigation';
import { getPaymentMethodIcon } from '../utils/paymentMethodIcons';
import { useQuery } from '@apollo/client';
import { GET_P2P_TRADE } from '../apollo/queries';
import { p2pSponsoredService } from '../services/p2pSponsoredService';
import { disputeEvidenceService } from '../services/disputeEvidenceService';
import { CameraRoll } from '@react-native-camera-roll/camera-roll';
import LoadingOverlay from '../components/LoadingOverlay';
import { formatLocalDateTime } from '../utils/dateUtils';
import { useAuth } from '../contexts/AuthContext';
import { useAccount } from '../contexts/AccountContext';
import { apolloClient } from '../apollo/client';
import { GET_DISPUTE_EVIDENCE_CODE } from '../apollo/mutations';


type ActiveTradeRouteProp = RouteProp<MainStackParamList, 'ActiveTrade'>;
type ActiveTradeNavigationProp = NativeStackNavigationProp<MainStackParamList, 'ActiveTrade'>;

const MODAL_MAX_HEIGHT = Math.floor(Dimensions.get('window').height * 0.85);
const SCROLL_MAX_HEIGHT = Math.min(Math.floor(Dimensions.get('window').height * 0.6), 420);

interface ActiveTrade {
  id: string;
  trader: {
    name: string;
    isOnline: boolean;
    verified: boolean;
    lastSeen: string;
    responseTime: string;
  };
  amount: string;
  crypto: string;
  totalBs: string;
  countryCode: string;
  currencyCode: string;
  paymentMethod: string;
  rate: string;
  step: number;
  timeRemaining: number;
  tradeType: 'buy' | 'sell';
  status?: string;
  hasRating?: boolean;
  createdAt?: string;
  completedAt?: string;
}


export const ActiveTradeScreen: React.FC = () => {
  const navigation = useNavigation<ActiveTradeNavigationProp>();
  const route = useRoute<ActiveTradeRouteProp>();
  const { trade: routeTrade } = route.params;
  const { userProfile } = useAuth();
  const { activeAccount, accounts } = useAccount();
  
  // All useState hooks must be called unconditionally
  const [activeTradeStep, setActiveTradeStep] = useState(1);
  const [timeRemaining, setTimeRemaining] = useState(900);
  const [spinAnim] = useState(new Animated.Value(0));
  const [showDisputeModal, setShowDisputeModal] = useState(false);
  const [disputeReason, setDisputeReason] = useState('');
  const [isSubmittingDispute, setIsSubmittingDispute] = useState(false);
  const [isUploadingEvidence, setIsUploadingEvidence] = useState(false);
  const [showEvidenceSheet, setShowEvidenceSheet] = useState(false);
  const [showVideoGallery, setShowVideoGallery] = useState(false);
  const [videoItems, setVideoItems] = useState<{ uri: string; thumbUri: string; name?: string; duration?: number }[]>([]);
  const [confioCode, setConfioCode] = useState<string | null>(null);
  const [confioCodeExp, setConfioCodeExp] = useState<string | null>(null);
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);
  
  // Dispute now goes on-chain via prepare/submit using p2pSponsoredService
  
  // Fetch full trade details immediately if we only have an ID
  const { data: tradeDetailsData, loading: tradeDetailsLoading, error: tradeDetailsError, refetch } = useQuery(GET_P2P_TRADE, {
    variables: { id: routeTrade?.id },
    skip: !routeTrade?.id,
    fetchPolicy: 'cache-and-network',
  });
  
  // Use full trade data if available, otherwise use route params
  const fullTradeData = tradeDetailsData?.p2pTrade;
  const currentUserId = userProfile?.id;
  const currentBusinessId = activeAccount?.business?.id;
  
  // Get all my business IDs from all accounts
  const myBusinessIds = accounts
    ?.filter(acc => acc.type === 'business' && acc.business?.id)
    .map(acc => String(acc.business.id)) || [];
  
  // Determine if current user is buyer or seller using strict ID comparisons against the active account context
  const iAmBuyer = fullTradeData ? (
    (fullTradeData.buyerUser?.id && String(fullTradeData.buyerUser.id) === String(currentUserId || '')) ||
    (fullTradeData.buyer?.id && String(fullTradeData.buyer.id) === String(currentUserId || '')) ||
    (currentBusinessId && fullTradeData.buyerBusiness?.id && String(fullTradeData.buyerBusiness.id) === String(currentBusinessId))
  ) : false;
  
  const iAmSeller = fullTradeData ? (
    (fullTradeData.sellerUser?.id && String(fullTradeData.sellerUser.id) === String(currentUserId || '')) ||
    (fullTradeData.seller?.id && String(fullTradeData.seller.id) === String(currentUserId || '')) ||
    (currentBusinessId && fullTradeData.sellerBusiness?.id && String(fullTradeData.sellerBusiness.id) === String(currentBusinessId))
  ) : false;
  
  const trade = fullTradeData ? {
    id: fullTradeData.id,
    step: fullTradeData.step || 1,
    status: fullTradeData.status,
    hasRating: fullTradeData.hasRating || false,
    tradeType: iAmBuyer ? 'buy' : 'sell', // Current user's perspective
    trader: iAmBuyer ? {
      // If I'm buyer, show seller info
      name: fullTradeData.sellerBusiness?.name || 
        fullTradeData.sellerDisplayName || 
        `${fullTradeData.sellerUser?.firstName || ''} ${fullTradeData.sellerUser?.lastName || ''}`.trim() || 
        fullTradeData.sellerUser?.username || 
        `${fullTradeData.seller?.firstName || ''} ${fullTradeData.seller?.lastName || ''}`.trim() || 
        fullTradeData.seller?.username || 'Vendedor',
      isOnline: fullTradeData.sellerStats?.isOnline || false,
      verified: fullTradeData.sellerStats?.isVerified || false,
      lastSeen: fullTradeData.sellerUser?.lastLogin || fullTradeData.seller?.lastLogin || null,
      responseTime: fullTradeData.sellerStats?.avgResponseTime || 'N/A',
      completedTrades: fullTradeData.sellerStats?.completedTrades || 0,
      successRate: fullTradeData.sellerStats?.successRate || 0,
    } : {
      // If I'm seller, show buyer info
      name: fullTradeData.buyerBusiness?.name || 
        fullTradeData.buyerDisplayName || 
        `${fullTradeData.buyerUser?.firstName || ''} ${fullTradeData.buyerUser?.lastName || ''}`.trim() || 
        fullTradeData.buyerUser?.username || 
        `${fullTradeData.buyer?.firstName || ''} ${fullTradeData.buyer?.lastName || ''}`.trim() || 
        fullTradeData.buyer?.username || 'Comprador',
      isOnline: fullTradeData.buyerStats?.isOnline || false,
      verified: fullTradeData.buyerStats?.isVerified || false,
      lastSeen: fullTradeData.buyerUser?.lastLogin || fullTradeData.buyer?.lastLogin || null,
      responseTime: fullTradeData.buyerStats?.avgResponseTime || 'N/A',
      completedTrades: fullTradeData.buyerStats?.completedTrades || 0,
      successRate: fullTradeData.buyerStats?.successRate || 0,
    },
    amount: fullTradeData.cryptoAmount || fullTradeData.amount,
    crypto: fullTradeData.crypto,
    totalBs: fullTradeData.fiatAmount,
    countryCode: fullTradeData.countryCode,
    currencyCode: fullTradeData.currencyCode,
    paymentMethod: fullTradeData.paymentMethod?.displayName || 'N/A',
    rate: fullTradeData.rateUsed || fullTradeData.exchangeRate || fullTradeData.rate || '0',
    timeRemaining: 900, // Default 15 minutes
    createdAt: fullTradeData.createdAt,
    completedAt: fullTradeData.completedAt,
  } : routeTrade;

  // Compute current account's own evidence count safely (GraphQL may return JSON string for evidenceUrls)
  const ownEvidenceCount = (() => {
    try {
      const ec: any = (fullTradeData as any)?.evidenceCount;
      if (typeof ec === 'number') return ec;
      const evs: any = (fullTradeData as any)?.dispute?.evidences;
      if (Array.isArray(evs)) return evs.length;
      const urls: any = (fullTradeData as any)?.dispute?.evidenceUrls;
      if (Array.isArray(urls)) return urls.length;
      if (typeof urls === 'string') {
        const parsed = JSON.parse(urls);
        if (Array.isArray(parsed)) return parsed.length;
      }
    } catch {}
    return 0;
  })();
  
  // Helper function to get step from trade status
  const getStepFromStatus = (status: string) => {
    switch (status) {
      case 'PENDING': return 1;
      case 'PAYMENT_PENDING': return 2;
      case 'PAYMENT_SENT': return 3;
      case 'PAYMENT_CONFIRMED': return 4;
      case 'PAYMENT_RECEIVED': return 4;
      case 'CRYPTO_RELEASED': return 4;
      case 'COMPLETED': return 4;
      case 'CANCELLED': return 1;
      default: return 1;
    }
  };

  // Update activeTradeStep when trade data is loaded
  useEffect(() => {
    if (trade?.status) {
      const step = getStepFromStatus(trade.status);
      setActiveTradeStep(step);
    }
  }, [trade?.status]);
  
  // Initialize and tick countdown from server expiresAt
  useEffect(() => {
    const expiresAtIso = fullTradeData?.expiresAt as string | undefined;
    const nowMs = Date.now();
    if (expiresAtIso) {
      const expMs = new Date(expiresAtIso).getTime();
      if (!isNaN(expMs)) {
        const initial = Math.max(0, Math.floor((expMs - nowMs) / 1000));
        setTimeRemaining(initial);
      }
    }
    const timer = setInterval(() => {
      setTimeRemaining(prev => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [fullTradeData?.expiresAt]);

  // Spinning animation for step 3
  useEffect(() => {
    if (activeTradeStep === 3) {
      const spin = Animated.loop(
        Animated.timing(spinAnim, {
          toValue: 1,
          duration: 1000,
          useNativeDriver: true,
        })
      );
      spin.start();
      return () => spin.stop();
    }
  }, [activeTradeStep, spinAnim]);
  
  // Reduce render-time logging to avoid noise that looks like polling
  useEffect(() => {
    console.log('[ActiveTradeScreen] Trade status changed:', {
      tradeId: routeTrade?.id,
      status: fullTradeData?.status,
      step: fullTradeData?.step,
      isBuyer: iAmBuyer,
      isSeller: iAmSeller,
    });
  }, [routeTrade?.id, fullTradeData?.status, fullTradeData?.step, iAmBuyer, iAmSeller]);
  
  // no-op
  
  // Format crypto token for display
  const formatCrypto = (crypto: string): string => {
    if (crypto === 'CUSD' || crypto === 'cusd') return 'cUSD';
    if (crypto === 'CONFIO' || crypto === 'confio') return 'CONFIO';
    return crypto;
  };
  
  // Show loading state while fetching full trade details
  if (tradeDetailsLoading && !routeTrade?.step) {
    return (
      <SafeAreaView style={styles.container}>
        <StatusBar barStyle="dark-content" backgroundColor="#fff" />
        <View style={styles.header}>
          <View style={styles.headerContent}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
              <Icon name="arrow-left" size={24} color="#374151" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Cargando intercambio...</Text>
          </View>
        </View>
        <View style={styles.content}>
          <View style={styles.stepCard}>
            <View style={styles.loadingCard}>
              <Animated.View style={styles.spinner} />
              <Text style={styles.loadingTitle}>Cargando detalles del intercambio</Text>
              <Text style={styles.loadingSubtitle}>Por favor espera un momento</Text>
            </View>
          </View>
        </View>
      </SafeAreaView>
    );
  }
  
  // Show error if trade data couldn't be loaded
  if (tradeDetailsError || (!trade && !tradeDetailsLoading)) {
    return (
      <SafeAreaView style={styles.container}>
        <StatusBar barStyle="dark-content" backgroundColor="#fff" />
        <View style={styles.header}>
          <View style={styles.headerContent}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
              <Icon name="arrow-left" size={24} color="#374151" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Error</Text>
          </View>
        </View>
        <View style={styles.content}>
          <View style={styles.stepCard}>
            <Text style={styles.stepTitle}>Error al cargar el intercambio</Text>
            <Text style={styles.stepDescription}>
              No se pudieron cargar los datos del intercambio. Por favor, vuelve a intentarlo.
            </Text>
          </View>
        </View>
      </SafeAreaView>
    );
  }

  const formatTime = (seconds: number) => {
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
  };

  const getProgressPercentage = () => {
    const totalTime = 15 * 60; // 15 minutes in seconds
    return ((totalTime - timeRemaining) / totalTime) * 100;
  };

  const handleGoBack = () => {
    // Simply go back to the previous screen
    navigation.goBack();
  };

  const handleDisputeTrade = () => {
    setShowDisputeModal(true);
  };

  const submitDispute = async () => {
    if (!disputeReason || disputeReason.trim().length < 10) {
      Alert.alert('Error', 'Por favor proporciona una descripción detallada del problema (mínimo 10 caracteres).');
      return;
    }

    // Ensure keyboard is closed and show global spinner overlay
    try { Keyboard.dismiss(); } catch {}
    setIsSubmittingDispute(true);
    // Hide the modal so the spinner overlay is clearly visible above the screen
    setShowDisputeModal(false);
    try {
      const res = await p2pSponsoredService.openDispute(trade.id, disputeReason.trim());
      if (res.success) {
        Alert.alert(
          'Disputa iniciada',
          'Tu disputa ha sido registrada. Un administrador revisará el caso pronto.',
          [
            {
              text: 'OK',
              onPress: () => navigation.goBack(),
            },
          ],
        );
      } else {
        Alert.alert('Error', res.error || 'No se pudo iniciar la disputa.');
      }
    } catch (error) {
      console.error('Error initiating dispute:', error);
      Alert.alert('Error', 'Ocurrió un error al iniciar la disputa. Por favor intenta de nuevo.');
    } finally {
      setIsSubmittingDispute(false);
    }
  };

  const requestVideoPermission = async (): Promise<boolean> => {
    if (Platform.OS !== 'android') return true;
    try {
      const sdk = Number(Platform.Version) || 0;
      const perm = (PermissionsAndroid as any).PERMISSIONS?.READ_MEDIA_VIDEO || PermissionsAndroid.PERMISSIONS.READ_EXTERNAL_STORAGE;
      // @ts-ignore
      const has = await PermissionsAndroid.check(perm);
      if (has) return true;
      // @ts-ignore
      const result = await PermissionsAndroid.request(perm, {
        title: 'Acceso a videos',
        message: 'Confío necesita acceso a tus videos para subir la evidencia (grabación de pantalla).',
        buttonPositive: 'Permitir',
        buttonNegative: 'Cancelar',
      });
      // @ts-ignore
      return result === PermissionsAndroid.RESULTS.GRANTED;
    } catch (e) {
      console.error('[Dispute] Video permission error:', e);
      return false;
    }
  };

  const pickScreenRecordingFromGallery = async () => {
    try {
      const allowed = await requestVideoPermission();
      if (!allowed) {
        Alert.alert('Permiso requerido', 'Debes permitir acceso a videos para seleccionar tu grabación de pantalla.');
        return;
      }
      // Close the sheet before opening the gallery modal to avoid stacked transparent modals
      setShowEvidenceSheet(false);
      const vids = await CameraRoll.getPhotos({ first: 60, assetType: 'Videos' });
      if (!vids.edges.length) {
        Alert.alert('Sin videos', 'No se encontraron videos recientes en tu galería. Usa la grabación de pantalla del sistema.');
        return;
      }
      setVideoItems(
        vids.edges.map(e => ({
          uri: e.node.image.uri,
          thumbUri: e.node.image.uri,
          name: (e.node.image as any)?.filename || 'Video',
          duration: (e.node.image as any)?.playableDuration || (e.node as any)?.playableDuration || undefined,
        }))
      );
      setShowVideoGallery(true);
    } catch (e: any) {
      console.error('[Dispute] pick video error:', e?.message || e);
      Alert.alert('Error', 'No se pudo abrir la galería de videos.');
    }
  };

  const handleSelectVideo = async (uri: string, name?: string) => {
    setShowVideoGallery(false);
    setIsUploadingEvidence(true);
    try {
      const lower = (name || uri || '').toLowerCase();
      const contentType = lower.endsWith('.mov') ? 'video/quicktime' : 'video/mp4';
      const res = await disputeEvidenceService.uploadEvidence(String(trade.id), uri, { contentType });
      if (!res.success) throw new Error(res.error || 'Fallo al subir la evidencia');
      Alert.alert('Evidencia subida', 'Tu video fue enviado correctamente para revisión.');
      setShowEvidenceSheet(false);
      try { await refetch(); } catch {}
    } catch (e: any) {
      console.error('[Dispute] upload evidence error:', e?.message || e);
      Alert.alert('Error', e?.message || 'No se pudo subir la evidencia.');
    } finally {
      setIsUploadingEvidence(false);
    }
  };

  const handleAbandonTrade = () => {
    Alert.alert(
      '¿Abandonar intercambio?',
      'Esta acción cancelará el intercambio y no podrás recuperarlo. ¿Estás seguro?',
      [
        {
          text: 'Cancelar',
          style: 'cancel',
        },
        {
          text: 'Abandonar',
          style: 'destructive',
          onPress: () => {
            // Here you would typically call an API to cancel the trade
            Alert.alert('Intercambio cancelado', 'El intercambio ha sido cancelado.');
            navigation.navigate('BottomTabs', { screen: 'Exchange' });
          },
        },
      ]
    );
  };

  const handleOpenChat = () => {
    navigation.navigate('TradeChat', {
      offer: {
        id: trade.id,
        name: trade.trader?.name || 'Comerciante',
        rate: (trade.rate || '0') + ' ' + (trade.currencyCode || 'VES'),
        limit: '1000',
        available: '500',
        paymentMethods: [trade.paymentMethod],
        responseTime: trade.trader?.responseTime || 'N/A',
        completedTrades: trade.trader?.completedTrades || 0,
        successRate: trade.trader?.successRate || 0,
        verified: trade.trader?.verified || false,
        isOnline: trade.trader?.isOnline || false,
        lastSeen: trade.trader?.lastSeen || null,
        countryCode: trade.countryCode,
      },
      crypto: formatCrypto(trade.crypto || 'cUSD') as 'cUSD' | 'CONFIO',
      amount: trade.amount,
      tradeType: trade.tradeType,
      tradeId: trade.id,
      tradeCountryCode: trade.countryCode,
      tradeCurrencyCode: trade.currencyCode,
      initialStep: activeTradeStep, // Pass the current step
      tradeStatus: trade.status, // Pass the current status if available
    });
  };

  const handleRateTrader = () => {
    Alert.alert('Calificación', 'Función de calificación en desarrollo');
  };

  // Progress bar component
  const TradeProgressBar: React.FC<{ currentStep: number; totalSteps: number }> = ({ currentStep, totalSteps }) => (
    <View style={styles.progressBarContainer}>
      {Array.from({ length: totalSteps }, (_, i) => (
        <React.Fragment key={i}>
          <View style={[
            styles.progressStep,
            i + 1 <= currentStep ? styles.progressStepActive : styles.progressStepInactive
          ]}>
            {i + 1 <= currentStep ? (
              <Icon name="check" size={16} color="#ffffff" />
            ) : (
              <Text style={[
                styles.progressStepText,
                i + 1 <= currentStep ? styles.progressStepTextActive : styles.progressStepTextInactive
              ]}>
                {i + 1}
              </Text>
            )}
          </View>
          {i < totalSteps - 1 && (
            <View style={[
              styles.progressLine,
              i + 1 < currentStep ? styles.progressLineActive : styles.progressLineInactive
            ]} />
          )}
        </React.Fragment>
      ))}
    </View>
  );

  // Determine if user is buyer or seller
  const isBuyer = trade.tradeType === 'buy';
  const isSeller = trade.tradeType === 'sell';

  const renderStep1 = () => {
    if (isBuyer) {
      return (
        <View style={styles.stepCard}>
          <Text style={styles.stepTitle}>Realizar Pago</Text>
          <Text style={styles.stepDescription}>
            Transfiere <Text style={styles.boldText}>{trade.totalBs || '0'} {trade.currencyCode || 'VES'}</Text> usando:
          </Text>
          
          <View style={styles.paymentMethodCard}>
            <View style={styles.paymentMethodHeader}>
              <View style={styles.paymentMethodIcon}>
                <Icon 
                  name={getPaymentMethodIcon(null, null, trade.paymentMethod)} 
                  size={18} 
                  color="#fff" 
                />
              </View>
              <View>
                <Text style={styles.paymentMethodName}>{trade.paymentMethod || 'N/A'}</Text>
                <Text style={styles.paymentMethodSubtitle}>Método seleccionado</Text>
              </View>
            </View>
          </View>

          {trade.paymentMethod && typeof trade.paymentMethod === 'string' && trade.paymentMethod.includes('Efectivo') ? (
            <View style={styles.cashInstructionsCard}>
              <Text style={styles.cashInstructionsTitle}>Instrucciones para pago en efectivo</Text>
              <View style={styles.cashInstructionsList}>
                <Text style={styles.cashInstruction}>• Coordina el punto de encuentro con {trade.trader?.name || 'el vendedor'}</Text>
                <Text style={styles.cashInstruction}>• Lleva exactamente: <Text style={styles.boldText}>{trade.totalBs || '0'} {trade.currencyCode || 'VES'}</Text></Text>
                <Text style={styles.cashInstruction}>• Encuentro en lugar público y seguro</Text>
                <Text style={styles.cashInstruction}>• Verifica la identidad del vendedor</Text>
              </View>
            </View>
          ) : (
            <View style={styles.bankDetailsCard}>
              <View style={styles.bankDetailsRow}>
                <Text style={styles.bankDetailsLabel}>Banco:</Text>
                <Text style={styles.bankDetailsValue}>{trade.paymentMethod || 'N/A'}</Text>
              </View>
              <View style={styles.bankDetailsRow}>
                <Text style={styles.bankDetailsLabel}>Titular:</Text>
                <Text style={styles.bankDetailsValue}>{trade.trader?.name || 'el vendedor'} (Nombre completo)</Text>
              </View>
              <View style={styles.bankDetailsRow}>
                <Text style={styles.bankDetailsLabel}>Cédula:</Text>
                <Text style={styles.bankDetailsValue}>V-12.345.678</Text>
              </View>
              <View style={styles.bankDetailsRow}>
                <Text style={styles.bankDetailsLabel}>Cuenta:</Text>
                <Text style={styles.bankDetailsValue}>0102-0000-00000000000</Text>
              </View>
              <View style={styles.bankDetailsRow}>
                <Text style={styles.bankDetailsLabel}>Monto exacto:</Text>
                <Text style={styles.bankDetailsAmount}>{trade.totalBs || '0'} {trade.currencyCode || 'VES'}</Text>
              </View>
            </View>
          )}
          
          <View style={styles.infoCard}>
            <View style={styles.infoContent}>
              <Icon name="info" size={20} color={colors.accent} style={styles.infoIcon} />
              <View>
                <Text style={styles.infoTitle}>¿Ya realizaste el pago?</Text>
                <Text style={styles.infoText}>
                  Usa el chat del intercambio para marcar el pago como completado y comunicarte con el vendedor.
                </Text>
              </View>
            </View>
          </View>
          
          <TouchableOpacity style={styles.primaryButton} onPress={handleOpenChat}>
            <Icon name="message-circle" size={16} color="#fff" style={styles.buttonIcon} />
            <Text style={styles.primaryButtonText}>Ir al chat del intercambio</Text>
          </TouchableOpacity>
        </View>
      );
    } else {
      // Seller view
      return (
        <View style={styles.stepCard}>
          <Text style={styles.stepTitle}>Esperando Pago del Comprador</Text>
          <Text style={styles.stepDescription}>
            {trade.trader?.name || 'El vendedor'} debe transferir <Text style={styles.boldText}>{trade.totalBs || '0'} {trade.currencyCode || 'VES'}</Text> a tu cuenta.
          </Text>
          
          <View style={styles.infoCard}>
            <View style={styles.infoContent}>
              <Icon name="clock" size={20} color={colors.accent} style={styles.infoIcon} />
              <View>
                <Text style={styles.infoTitle}>Tiempo de respuesta esperado</Text>
                <Text style={styles.infoText}>
                  El comprador tiene hasta 15 minutos para completar la transferencia.
                </Text>
              </View>
            </View>
          </View>

          <View style={styles.summaryCard}>
            <Text style={styles.summaryTitle}>Detalles del intercambio</Text>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Vas a enviar:</Text>
              <Text style={styles.summaryValue}>{trade.amount || '0'} {formatCrypto(trade.crypto || 'cUSD')}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Vas a recibir:</Text>
              <Text style={styles.summaryValue}>{trade.totalBs || '0'} {trade.currencyCode || 'VES'}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Tasa de cambio:</Text>
              <Text style={styles.summaryValue}>{trade.rate || '0'} {trade.currencyCode || 'VES'}/{formatCrypto(trade.crypto || 'cUSD')}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Comprador:</Text>
              <Text style={styles.summaryValue}>{trade.trader?.name || 'Comerciante'}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>ID del intercambio:</Text>
              <Text style={[styles.summaryValue, { fontSize: 12 }]}>#{trade.id.slice(-8).toUpperCase()}</Text>
            </View>
          </View>
          
          <TouchableOpacity style={styles.primaryButton} onPress={handleOpenChat}>
            <Icon name="message-circle" size={16} color="#fff" style={styles.buttonIcon} />
            <Text style={styles.primaryButtonText}>Ir al chat del intercambio</Text>
          </TouchableOpacity>
        </View>
      );
    }
  };

  const renderStep2 = () => {
    if (isBuyer) {
      return (
        <View style={styles.stepCard}>
          <Text style={styles.stepTitle}>Confirmar Pago</Text>
          <Text style={styles.stepDescription}>
            Confirma que has completado el pago de <Text style={styles.boldText}>{trade.totalBs || '0'} {trade.currencyCode || 'VES'}</Text>
          </Text>
          
          <View style={styles.infoCard}>
            <View style={styles.infoContent}>
              <Icon name="info" size={20} color={colors.accent} style={styles.infoIcon} />
              <View>
                <Text style={styles.infoTitle}>Verificación del vendedor</Text>
                <Text style={styles.infoText}>
                  {trade.trader?.name || 'El vendedor'} verificará el pago en su cuenta bancaria. 
                  Por favor sé paciente mientras confirma la transacción.
                </Text>
              </View>
            </View>
          </View>
            
          <View style={styles.warningCard}>
            <View style={styles.warningContent}>
              <Icon name="alert-triangle" size={20} color="#D97706" style={styles.warningIcon} />
              <View>
                <Text style={styles.warningTitle}>Solo confirma si ya pagaste</Text>
                <Text style={styles.warningText}>
                  No marques como pagado si no has completado la transferencia. 
                  Esto puede resultar en la suspensión de tu cuenta.
                </Text>
              </View>
            </View>
          </View>
          
          <View style={styles.infoCard}>
            <View style={styles.infoContent}>
              <Icon name="info" size={20} color={colors.accent} style={styles.infoIcon} />
              <View>
                <Text style={styles.infoTitle}>Siguiente paso</Text>
                <Text style={styles.infoText}>
                  Debes confirmar el pago desde el chat del intercambio para mayor seguridad.
                </Text>
              </View>
            </View>
          </View>
          
          <TouchableOpacity style={styles.primaryButton} onPress={handleOpenChat}>
            <Icon name="message-circle" size={16} color="#ffffff" style={styles.buttonIcon} />
            <Text style={styles.primaryButtonText}>Ir al chat del intercambio</Text>
          </TouchableOpacity>
        </View>
      );
    } else {
      // Seller view - they need to confirm they received payment
      return (
        <View style={styles.stepCard}>
          <Text style={styles.stepTitle}>¿Recibiste el Pago?</Text>
          <Text style={styles.stepDescription}>
            Verifica que recibiste <Text style={styles.boldText}>{trade.totalBs || '0'} {trade.currencyCode || 'VES'}</Text> en tu cuenta bancaria.
          </Text>
          
          <View style={styles.warningCard}>
            <View style={styles.warningContent}>
              <Icon name="alert-triangle" size={20} color="#D97706" style={styles.warningIcon} />
              <View>
                <Text style={styles.warningTitle}>Verifica antes de confirmar</Text>
                <Text style={styles.warningText}>
                  Solo confirma si realmente recibiste el pago en tu cuenta. 
                  Una vez confirmado, se liberarán los {formatCrypto(trade.crypto || 'cUSD')} al comprador.
                </Text>
              </View>
            </View>
          </View>

          <View style={styles.infoCard}>
            <View style={styles.infoContent}>
              <Icon name="shield" size={20} color={colors.primary} style={styles.infoIcon} />
              <View>
                <Text style={styles.infoTitle}>Protección del vendedor</Text>
                <Text style={styles.infoText}>
                  Si no recibiste el pago, reporta el problema. Nunca liberes fondos sin haber recibido el pago completo.
                </Text>
              </View>
            </View>
          </View>
          
          <View style={styles.infoCard}>
            <View style={styles.infoContent}>
              <Icon name="info" size={20} color={colors.accent} style={styles.infoIcon} />
              <View>
                <Text style={styles.infoTitle}>Siguiente paso</Text>
                <Text style={styles.infoText}>
                  La liberación de fondos debe realizarse desde el chat del intercambio por seguridad.
                </Text>
              </View>
            </View>
          </View>
          
          <TouchableOpacity style={styles.primaryButton} onPress={handleOpenChat}>
            <Icon name="message-circle" size={16} color="#ffffff" style={styles.buttonIcon} />
            <Text style={styles.primaryButtonText}>Ir al chat del intercambio</Text>
          </TouchableOpacity>
        </View>
      );
    }
  };

  const renderStep3 = () => {
    if (isBuyer) {
      return (
        <View style={styles.stepCard}>
          <Text style={styles.stepTitle}>Esperando Confirmación</Text>
          <Text style={styles.stepDescription}>
            {trade.trader?.name || 'El vendedor'} está verificando tu pago. Esto puede tomar unos minutos.
          </Text>
      
      <View style={styles.loadingCard}>
        <Animated.View 
          style={[
            styles.spinner,
            {
              transform: [{
                rotate: spinAnim.interpolate({
                  inputRange: [0, 1],
                  outputRange: ['0deg', '360deg'],
                })
              }]
            }
          ]}
        />
        <Text style={styles.loadingTitle}>Verificando pago...</Text>
        <Text style={styles.loadingSubtitle}>Tiempo promedio: {trade.trader?.responseTime || 'N/A'}</Text>
      </View>
      
      <View style={styles.summaryCard}>
        <Text style={styles.summaryTitle}>Resumen de la operación</Text>
        <View style={styles.summaryRow}>
          <Text style={styles.summaryLabel}>Cantidad:</Text>
          <Text style={styles.summaryValue}>{trade.amount || '0'} {trade.crypto}</Text>
        </View>
        <View style={styles.summaryRow}>
          <Text style={styles.summaryLabel}>Pagado:</Text>
          <Text style={styles.summaryValue}>{trade.totalBs || '0'} {trade.currencyCode || 'VES'}</Text>
        </View>
        <View style={styles.summaryRow}>
          <Text style={styles.summaryLabel}>Tasa de cambio:</Text>
          <Text style={styles.summaryValue}>{trade.rate || '0'} {trade.currencyCode || 'VES'}/{formatCrypto(trade.crypto || 'cUSD')}</Text>
        </View>
        <View style={styles.summaryRow}>
          <Text style={styles.summaryLabel}>Vendedor:</Text>
          <Text style={styles.summaryValue}>{trade.trader?.name || 'el vendedor'}</Text>
        </View>
        <View style={styles.summaryRow}>
          <Text style={styles.summaryLabel}>ID del intercambio:</Text>
          <Text style={[styles.summaryValue, { fontSize: 12 }]}>#{trade.id.slice(-8).toUpperCase()}</Text>
        </View>
      </View>
      
          <TouchableOpacity style={styles.primaryButton} onPress={handleOpenChat}>
            <Icon name="message-circle" size={16} color="#fff" style={styles.buttonIcon} />
            <Text style={styles.primaryButtonText}>Ir al chat del intercambio</Text>
          </TouchableOpacity>
        </View>
      );
    } else {
      // Seller view - processing the release of funds
      return (
        <View style={styles.stepCard}>
          <Text style={styles.stepTitle}>Liberando Fondos</Text>
          <Text style={styles.stepDescription}>
            Estamos procesando la transferencia de {trade.amount || '0'} {formatCrypto(trade.crypto || 'cUSD')} a {trade.trader?.name || 'el comprador'}.
          </Text>
          
          <View style={styles.loadingCard}>
            <Animated.View 
              style={[
                styles.spinner,
                {
                  transform: [{
                    rotate: spinAnim.interpolate({
                      inputRange: [0, 1],
                      outputRange: ['0deg', '360deg'],
                    })
                  }]
                }
              ]}
            />
            <Text style={styles.loadingTitle}>Procesando transacción...</Text>
            <Text style={styles.loadingSubtitle}>Esto puede tomar unos minutos</Text>
          </View>
          
          <View style={styles.summaryCard}>
            <Text style={styles.summaryTitle}>Resumen de la operación</Text>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Enviando:</Text>
              <Text style={styles.summaryValue}>{trade.amount || '0'} {formatCrypto(trade.crypto || 'cUSD')}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Recibido:</Text>
              <Text style={styles.summaryValue}>{trade.totalBs || '0'} {trade.currencyCode || 'VES'}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Comprador:</Text>
              <Text style={styles.summaryValue}>{trade.trader?.name || 'el comprador'}</Text>
            </View>
          </View>
          
          <TouchableOpacity style={styles.primaryButton} onPress={handleOpenChat}>
            <Icon name="message-circle" size={16} color="#fff" style={styles.buttonIcon} />
            <Text style={styles.primaryButtonText}>Ir al chat del intercambio</Text>
          </TouchableOpacity>
        </View>
      );
    }
  };

  const renderStep4 = () => {
    // Get full trade data from GraphQL query
    const fullTradeData = tradeDetailsData?.p2pTrade;
    
    console.log('[ActiveTradeScreen] renderStep4 - trade data:', {
      tradeId: trade.id,
      status: trade.status,
      hasRating: trade.hasRating,
      step: trade.step,
      willShowRatedUI: (trade.status === 'COMPLETED' || trade.status === 'CRYPTO_RELEASED' || trade.status === 'PAYMENT_CONFIRMED') && trade.hasRating
    });
    
    // If trade is already completed (rated), show different UI
    if ((trade.status === 'COMPLETED' || trade.status === 'CRYPTO_RELEASED' || trade.status === 'PAYMENT_CONFIRMED') && trade.hasRating) {
      return (
        <View style={styles.stepCard}>
          <View style={styles.successHeader}>
            <View style={styles.successIcon}>
              <Icon name="check" size={32} color="#ffffff" />
            </View>
            <Text style={styles.successTitle}>¡Intercambio Completado!</Text>
            <Text style={styles.successDescription}>
              Este intercambio ha sido completado y calificado
            </Text>
          </View>
          
          <View style={styles.transactionDetailsCard}>
            <Text style={styles.transactionDetailsTitle}>Detalles de la transacción</Text>
            <View style={styles.transactionDetailsRow}>
              <Text style={styles.transactionDetailsLabel}>ID del intercambio:</Text>
              <Text style={[styles.transactionDetailsValue, { fontSize: 12 }]}>#{trade.id.slice(-8).toUpperCase()}</Text>
            </View>
            <View style={styles.transactionDetailsRow}>
              <Text style={styles.transactionDetailsLabel}>Fecha de finalización:</Text>
              <Text style={styles.transactionDetailsValue}>{formatLocalDateTime(fullTradeData?.completedAt || trade.completedAt || trade.createdAt || new Date().toISOString())}</Text>
            </View>
            <View style={styles.transactionDetailsRow}>
              <Text style={styles.transactionDetailsLabel}>Cantidad:</Text>
              <Text style={styles.transactionDetailsValue}>{trade.amount || '0'} {formatCrypto(trade.crypto || 'cUSD')}</Text>
            </View>
            <View style={styles.transactionDetailsRow}>
              <Text style={styles.transactionDetailsLabel}>Total pagado:</Text>
              <Text style={styles.transactionDetailsValue}>{trade.totalBs || '0'}{(trade.totalBs && !trade.totalBs.includes(trade.currencyCode || 'VES')) ? ` ${trade.currencyCode || 'VES'}` : ''}</Text>
            </View>
            <View style={styles.transactionDetailsRow}>
              <Text style={styles.transactionDetailsLabel}>Tasa de cambio:</Text>
              <Text style={styles.transactionDetailsValue}>{trade.rate || '0'} {trade.currencyCode || 'VES'}/{formatCrypto(trade.crypto || 'cUSD')}</Text>
            </View>
            <View style={styles.transactionDetailsRow}>
              <Text style={styles.transactionDetailsLabel}>Comerciante:</Text>
              <Text style={styles.transactionDetailsValue}>{trade.trader?.name || 'Comerciante'}</Text>
            </View>
            <View style={styles.transactionDetailsRow}>
              <Text style={styles.transactionDetailsLabel}>Método de pago:</Text>
              <Text style={styles.transactionDetailsValue}>{fullTradeData?.paymentMethod?.displayName || trade.paymentMethod || 'N/A'}</Text>
            </View>
            <View style={styles.transactionDetailsRow}>
              <Text style={styles.transactionDetailsLabel}>Estado:</Text>
              <Text style={[styles.transactionDetailsValue, { color: colors.success }]}>Completado y calificado</Text>
            </View>
          </View>
          
          <View style={styles.successButtons}>
            <TouchableOpacity style={styles.secondaryButton} onPress={handleGoBack}>
              <Text style={styles.secondaryButtonText}>Volver a Intercambios</Text>
            </TouchableOpacity>
          </View>

          {/* Technical details button for completed & rated trade (if hash available) */}
          {(
            <View style={styles.transactionDetailsCard}>
              <TouchableOpacity 
                onPress={() => setShowTechnicalDetails(true)}
                style={styles.blockchainButton}
              >
                <Icon name="external-link" size={16} color="#6b7280" style={styles.blockchainIcon} />
                <Text style={styles.blockchainButtonText}>Ver detalles técnicos</Text>
              </TouchableOpacity>
            </View>
          )}

          {/* Technical Details Modal */}
          <Modal
            visible={showTechnicalDetails}
            transparent
            animationType="fade"
            onRequestClose={() => setShowTechnicalDetails(false)}
          >
            <View style={styles.modalOverlay}>
              <View style={[styles.modalContent, { maxHeight: '85%' }]}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>Detalles técnicos</Text>
                  <TouchableOpacity onPress={() => setShowTechnicalDetails(false)} style={styles.modalCloseButton}>
                    <Icon name="x" size={20} color="#111827" />
                  </TouchableOpacity>
                </View>
                <ScrollView style={styles.modalScroll} contentContainerStyle={styles.modalScrollContent}>
                  <View style={styles.modalSection}>
                    <Text style={styles.modalSectionTitle}>Transacción</Text>
                    <View style={styles.technicalRow}>
                      <Text style={styles.technicalLabel}>Red</Text>
                      <Text style={styles.technicalValue}>{__DEV__ ? 'Testnet' : 'Mainnet'}</Text>
                    </View>
                    <View style={styles.technicalRow}>
                      <Text style={styles.technicalLabel}>Hash</Text>
                      <Text style={styles.technicalValue} numberOfLines={1}>
                        {(() => {
                          const h = (
                            fullTradeData?.escrow?.releaseTransactionHash ||
                            fullTradeData?.escrow?.escrowTransactionHash ||
                            fullTradeData?.cryptoTransactionHash ||
                            ''
                          ).toString();
                          if (!h) return 'N/D';
                          return h.replace(/(.{10}).+(.{6})/, '$1…$2');
                        })()}
                      </Text>
                    </View>
                  </View>

                  <TouchableOpacity
                    style={[styles.explorerButton]}
                    onPress={async () => {
                      try {
                        const txid = (
                          fullTradeData?.escrow?.releaseTransactionHash ||
                          fullTradeData?.escrow?.escrowTransactionHash ||
                          fullTradeData?.cryptoTransactionHash ||
                          ''
                        ).toString();
                        if (!txid) {
                          Alert.alert('Sin hash', 'Aún no hay hash de transacción disponible.');
                          return;
                        }
                        const base = __DEV__ ? 'https://testnet.explorer.perawallet.app' : 'https://explorer.perawallet.app';
                        const url = `${base}/tx/${encodeURIComponent(txid)}/`;
                        const canOpen = await Linking.canOpenURL(url);
                        if (canOpen) await Linking.openURL(url);
                        else Alert.alert('No se puede abrir', 'No se pudo abrir Pera Explorer.');
                      } catch (e) {
                        Alert.alert('Error', 'No se pudo abrir Pera Explorer.');
                      }
                    }}
                  >
                    <Icon name="external-link" size={16} color="#fff" style={styles.explorerIcon} />
                    <Text style={styles.explorerButtonText}>Abrir en Pera Explorer</Text>
                  </TouchableOpacity>
                </ScrollView>
              </View>
            </View>
          </Modal>
        </View>
      );
    }
    
    // If trade is not yet rated, show rating button
    return (
      <View style={styles.stepCard}>
        <View style={styles.successHeader}>
          <View style={styles.successIcon}>
            <Icon name="check" size={32} color="#ffffff" />
          </View>
          <Text style={styles.successTitle}>¡Intercambio Completado!</Text>
          <Text style={styles.successDescription}>
            Has recibido <Text style={styles.boldText}>{trade.amount || '0'} {formatCrypto(trade.crypto || 'cUSD')}</Text> en tu wallet
          </Text>
        </View>
        
        <View style={styles.transactionDetailsCard}>
          <Text style={styles.transactionDetailsTitle}>Detalles de la transacción</Text>
          <View style={styles.transactionDetailsRow}>
            <Text style={styles.transactionDetailsLabel}>ID del intercambio:</Text>
            <Text style={[styles.transactionDetailsValue, { fontSize: 12 }]}>#{trade.id.slice(-8).toUpperCase()}</Text>
          </View>
          <View style={styles.transactionDetailsRow}>
            <Text style={styles.transactionDetailsLabel}>Fecha de finalización:</Text>
            <Text style={styles.transactionDetailsValue}>{formatLocalDateTime(fullTradeData?.completedAt || trade.completedAt || trade.createdAt || new Date().toISOString())}</Text>
          </View>
          <View style={styles.transactionDetailsRow}>
            <Text style={styles.transactionDetailsLabel}>Cantidad:</Text>
            <Text style={styles.transactionDetailsValue}>{trade.amount || '0'} {formatCrypto(trade.crypto || 'cUSD')}</Text>
          </View>
          <View style={styles.transactionDetailsRow}>
            <Text style={styles.transactionDetailsLabel}>Total pagado:</Text>
            <Text style={styles.transactionDetailsValue}>{trade.totalBs || '0'}{(trade.totalBs && !trade.totalBs.includes(trade.currencyCode || 'VES')) ? ` ${trade.currencyCode || 'VES'}` : ''}</Text>
          </View>
          <View style={styles.transactionDetailsRow}>
            <Text style={styles.transactionDetailsLabel}>Tasa de cambio:</Text>
            <Text style={styles.transactionDetailsValue}>{trade.rate || '0'} {trade.currencyCode || 'VES'}/{formatCrypto(trade.crypto || 'cUSD')}</Text>
          </View>
          <View style={styles.transactionDetailsRow}>
            <Text style={styles.transactionDetailsLabel}>Comerciante:</Text>
            <Text style={styles.transactionDetailsValue}>{trade.trader?.name || 'Comerciante'}</Text>
          </View>
          <View style={styles.transactionDetailsRow}>
            <Text style={styles.transactionDetailsLabel}>Método de pago:</Text>
            <Text style={styles.transactionDetailsValue}>{fullTradeData?.paymentMethod?.displayName || trade.paymentMethod || 'N/A'}</Text>
          </View>
        </View>
        
        <View style={styles.successButtons}>
          <TouchableOpacity style={styles.primaryButton} onPress={() => {
            // Check if already rated
            if (trade.hasRating) {
              Alert.alert('Ya calificado', 'Ya has calificado este intercambio.');
              return;
            }
            
            // Determine who is rating whom based on current user's role
            const iAmBuyer = trade.tradeType === 'buy';
            const fullTradeData = tradeDetailsData?.p2pTrade;
            
            // Get counterparty information - handle both personal and business accounts
            let counterpartyName = '';
            let counterpartyInfo = null;
            
            if (iAmBuyer) {
              // I'm the buyer, so I rate the seller
              if (fullTradeData?.sellerBusiness) {
                counterpartyName = fullTradeData.sellerBusiness.name;
                counterpartyInfo = fullTradeData.sellerBusiness;
              } else if (fullTradeData?.sellerUser) {
                counterpartyInfo = fullTradeData.sellerUser;
                counterpartyName = `${counterpartyInfo.firstName || ''} ${counterpartyInfo.lastName || ''}`.trim() || counterpartyInfo.username || 'Vendedor';
              } else if (fullTradeData?.sellerDisplayName) {
                counterpartyName = fullTradeData.sellerDisplayName;
              } else if (fullTradeData?.seller) {
                // Fallback to old field
                counterpartyInfo = fullTradeData.seller;
                counterpartyName = `${counterpartyInfo.firstName || ''} ${counterpartyInfo.lastName || ''}`.trim() || counterpartyInfo.username || 'Vendedor';
              } else {
                counterpartyName = trade.trader?.name || 'Vendedor';
              }
            } else {
              // I'm the seller, so I rate the buyer
              if (fullTradeData?.buyerBusiness) {
                counterpartyName = fullTradeData.buyerBusiness.name;
                counterpartyInfo = fullTradeData.buyerBusiness;
              } else if (fullTradeData?.buyerUser) {
                counterpartyInfo = fullTradeData.buyerUser;
                counterpartyName = `${counterpartyInfo.firstName || ''} ${counterpartyInfo.lastName || ''}`.trim() || counterpartyInfo.username || 'Comprador';
              } else if (fullTradeData?.buyerDisplayName) {
                counterpartyName = fullTradeData.buyerDisplayName;
              } else if (fullTradeData?.buyer) {
                // Fallback to old field
                counterpartyInfo = fullTradeData.buyer;
                counterpartyName = `${counterpartyInfo.firstName || ''} ${counterpartyInfo.lastName || ''}`.trim() || counterpartyInfo.username || 'Comprador';
              } else {
                counterpartyName = trade.trader?.name || 'Comprador';
              }
            }
            
            // Get the correct counterparty stats
            const counterpartyStats = iAmBuyer ? fullTradeData?.sellerStats : fullTradeData?.buyerStats;
            
            console.log('[ActiveTradeScreen] Rating navigation:', {
              iAmBuyer,
              tradeType: trade.tradeType,
              buyerUser: fullTradeData?.buyerUser,
              buyerBusiness: fullTradeData?.buyerBusiness,
              sellerUser: fullTradeData?.sellerUser,
              sellerBusiness: fullTradeData?.sellerBusiness,
              buyerDisplayName: fullTradeData?.buyerDisplayName,
              sellerDisplayName: fullTradeData?.sellerDisplayName,
              counterpartyName,
              counterpartyStats,
              hasRating: trade.hasRating,
            });
            
            navigation.navigate('TraderRating', {
              tradeId: trade.id,
              trader: {
                name: counterpartyName,
                verified: counterpartyStats?.isVerified || trade.trader?.verified || false,
                completedTrades: counterpartyStats?.completedTrades || trade.trader?.completedTrades || 0,
                successRate: counterpartyStats?.successRate || trade.trader?.successRate || 0
              },
              tradeDetails: {
                amount: trade.amount,
                crypto: formatCrypto(trade.crypto || 'cUSD'),
                totalPaid: trade.totalBs,
                method: fullTradeData?.paymentMethod?.displayName || trade.paymentMethod || 'N/A',
                date: formatLocalDateTime(fullTradeData?.completedAt || trade.completedAt || trade.createdAt || new Date().toISOString()),
                // Use real timestamps to avoid negatives
                duration: (() => {
                  const startMs = fullTradeData?.createdAt ? new Date(fullTradeData.createdAt as any).getTime() : Date.now();
                  const endMs = fullTradeData?.completedAt ? new Date(fullTradeData.completedAt as any).getTime() : Date.now();
                  const mins = Math.max(0, Math.round((endMs - startMs) / 60000));
                  return `${mins} minutos`;
                })(),
              }
            });
          }}>
            <Text style={styles.primaryButtonText}>Calificar a {trade.trader?.name || 'Comerciante'}</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.secondaryButton} onPress={handleGoBack}>
            <Text style={styles.secondaryButtonText}>Volver al Inicio</Text>
          </TouchableOpacity>
        </View>

        {/* Technical details button for completed trade (if hash available) */}
        {(
          <View style={styles.transactionDetailsCard}>
            <TouchableOpacity 
              onPress={() => setShowTechnicalDetails(true)}
              style={styles.blockchainButton}
            >
              <Icon name="external-link" size={16} color="#6b7280" style={styles.blockchainIcon} />
              <Text style={styles.blockchainButtonText}>Ver detalles técnicos</Text>
            </TouchableOpacity>
          </View>
        )}

        {/* Technical Details Modal */}
        <Modal
          visible={showTechnicalDetails}
          transparent
          animationType="fade"
          onRequestClose={() => setShowTechnicalDetails(false)}
        >
          <View style={styles.modalOverlay}>
            <View style={styles.modalContent}>
              <View style={styles.modalHeader}>
                <Text style={styles.modalTitle}>Detalles técnicos</Text>
                <TouchableOpacity onPress={() => setShowTechnicalDetails(false)} style={styles.modalCloseButton}>
                  <Icon name="x" size={20} color="#111827" />
                </TouchableOpacity>
              </View>
              <ScrollView
                style={styles.modalScroll}
                contentContainerStyle={styles.modalScrollContent}
                keyboardShouldPersistTaps="handled"
                keyboardDismissMode={Platform.OS === 'ios' ? 'on-drag' : 'interactive'}
                showsVerticalScrollIndicator={true}
                nestedScrollEnabled
                contentInsetAdjustmentBehavior={Platform.OS === 'ios' ? 'always' : 'automatic'}
              >
                  <View style={styles.modalSection}>
                    <Text style={styles.modalSectionTitle}>Transacción</Text>
                    <View style={styles.technicalRow}>
                      <Text style={styles.technicalLabel}>Red</Text>
                      <Text style={styles.technicalValue}>{__DEV__ ? 'Testnet' : 'Mainnet'}</Text>
                    </View>
                    <View style={styles.technicalRow}>
                      <Text style={styles.technicalLabel}>Hash</Text>
                      <Text style={styles.technicalValue} numberOfLines={1}>
                        {(() => {
                          const h = (
                            fullTradeData?.escrow?.releaseTransactionHash ||
                            fullTradeData?.escrow?.escrowTransactionHash ||
                            fullTradeData?.cryptoTransactionHash ||
                            ''
                          ).toString();
                          if (!h) return 'N/D';
                          return h.replace(/(.{10}).+(.{6})/, '$1…$2');
                        })()}
                      </Text>
                    </View>
                  </View>

                <TouchableOpacity
                  style={[styles.explorerButton]}
                  onPress={async () => {
                    try {
                      const txid = (
                        fullTradeData?.escrow?.releaseTransactionHash ||
                        fullTradeData?.escrow?.escrowTransactionHash ||
                        fullTradeData?.cryptoTransactionHash ||
                        ''
                      ).toString();
                      if (!txid) {
                        Alert.alert('Sin hash', 'Aún no hay hash de transacción disponible.');
                        return;
                      }
                      const base = __DEV__ ? 'https://testnet.explorer.perawallet.app' : 'https://explorer.perawallet.app';
                      const url = `${base}/tx/${encodeURIComponent(txid)}/`;
                      const canOpen = await Linking.canOpenURL(url);
                      if (canOpen) await Linking.openURL(url);
                      else Alert.alert('No se puede abrir', 'No se pudo abrir Pera Explorer.');
                    } catch (e) {
                      Alert.alert('Error', 'No se pudo abrir Pera Explorer.');
                    }
                  }}
                >
                  <Icon name="external-link" size={16} color="#fff" style={styles.explorerIcon} />
                  <Text style={styles.explorerButtonText}>Abrir en Pera Explorer</Text>
                </TouchableOpacity>
              </ScrollView>
            </View>
          </View>
        </Modal>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="dark-content" backgroundColor="#fff" />
      
      <View style={styles.header}>
        <View style={styles.headerContent}>
          <TouchableOpacity onPress={handleGoBack} style={styles.backButton}>
            <Icon name="arrow-left" size={24} color="#374151" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>
            {trade.status === 'COMPLETED' ? 'Detalle del Intercambio' : 'Intercambio Activo'}
          </Text>
          <View style={styles.headerSpacer} />
          {trade.status !== 'COMPLETED' && trade.status !== 'CANCELLED' && trade.status !== 'EXPIRED' && trade.status !== 'DISPUTED' && (
            <TouchableOpacity 
              style={styles.menuButton}
              onPress={() => {
                Alert.alert(
                  'Opciones del intercambio',
                  '¿Qué deseas hacer?',
                  [
                    {
                      text: 'Reportar problema',
                      onPress: handleDisputeTrade,
                    },
                    {
                      text: 'Abandonar intercambio',
                      onPress: handleAbandonTrade,
                      style: 'destructive',
                    },
                    {
                      text: 'Cancelar',
                      style: 'cancel',
                    },
                  ],
                );
              }}
            >
              <Icon name="more-vertical" size={20} color="#374151" />
            </TouchableOpacity>
          )}
          {trade.status === 'DISPUTED' && (
            <View style={styles.disputedBadge}>
              <Icon name="alert-triangle" size={14} color="#DC2626" />
              <Text style={styles.disputedBadgeText}>En disputa</Text>
            </View>
          )}
        </View>
        
        {trade.status !== 'DISPUTED' && (
          <TradeProgressBar currentStep={activeTradeStep} totalSteps={4} />
        )}
        
        {trade.status !== 'COMPLETED' && trade.status !== 'DISPUTED' && (
          <View style={styles.timerCard}>
            <View style={styles.timerHeader}>
              <Text style={styles.timerLabel}>Tiempo restante</Text>
              {timeRemaining > 0 ? (
                <Text style={styles.timerValue}>{formatTime(timeRemaining)}</Text>
              ) : (
                <View style={styles.timerPillExpired}>
                  <Text style={[styles.timerValue, styles.timerValueExpired]}>{formatTime(timeRemaining)}</Text>
                </View>
              )}
            </View>
            <View style={styles.timerProgressBar}>
              <View 
                style={[
                  styles.timerProgressFill, 
                  { width: `${Math.max(10, 100 - getProgressPercentage())}%` },
                  timeRemaining <= 0 && styles.timerProgressExpired
                ]} 
              />
            </View>
            <TouchableOpacity 
              style={styles.viewAllTradesHint}
              onPress={() => navigation.navigate('BottomTabs', { screen: 'Exchange' })}
            >
              <Icon name="list" size={12} color="#2563EB" style={styles.hintIcon} />
              <Text style={styles.hintText}>Ver todos mis intercambios</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>
      
      {/* Dispute Banner */}
      {trade.status === 'DISPUTED' && (
        <View style={styles.disputeBanner}>
          <View style={styles.disputeBannerContent}>
            <Icon name="shield" size={24} color="#0F766E" style={styles.disputeBannerIcon} />
            <View style={styles.disputeBannerTextContainer}>
              <Text style={styles.disputeBannerTitle}>🤝 Estamos aquí para ayudarte</Text>
              <Text style={styles.disputeBannerText}>
                Hemos recibido tu solicitud y nuestro equipo especializado está trabajando para resolver 
                este intercambio de manera justa. Tus fondos están completamente seguros durante este proceso.
              </Text>
              {!!(fullTradeData?.hasEvidence || ownEvidenceCount > 0) && (
                <View style={{ marginTop: 8, alignSelf: 'flex-start', backgroundColor: '#D1FAE5', borderColor: '#10B981', borderWidth: 1, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999 }}>
                  <Text style={{ color: '#065F46', fontWeight: '600' }}>
                    ✅ Evidencia enviada ({ownEvidenceCount})
                  </Text>
                </View>
              )}
            </View>
          </View>
          <TouchableOpacity 
            style={styles.disputeChatButton}
            onPress={handleOpenChat}
          >
            <Icon name="message-circle" size={16} color="#0F766E" />
            <Text style={styles.disputeChatButtonText}>💬 Continuar conversación</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.disputeChatButton, { marginTop: 8, backgroundColor: '#DCFCE7', borderColor: '#34D399' }]}
            onPress={async () => {
              try {
                setConfioCode(null); setConfioCodeExp(null);
                const { data } = await apolloClient.mutate({ mutation: GET_DISPUTE_EVIDENCE_CODE, variables: { tradeId: trade.id }, fetchPolicy: 'no-cache' });
                const res = data?.getDisputeEvidenceCode;
                if (res?.success) {
                  setConfioCode(res.confioCode || null);
                  setConfioCodeExp(res.expiresAt || null);
                }
              } catch {}
              setShowEvidenceSheet(true);
            }}
          >
            <Icon name="upload" size={16} color="#065F46" />
            <Text style={[styles.disputeChatButtonText, { color: '#065F46' }]}>⬆️ Subir evidencia (pantalla)</Text>
          </TouchableOpacity>
        </View>
      )}
      
      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        {trade.status === 'DISPUTED' ? (
          <View style={styles.stepCard}>
            <Text style={styles.stepTitle}>✅ Tu caso está en buenas manos</Text>
            <Text style={styles.stepDescription}>
              Un especialista de nuestro equipo está revisando todos los detalles para encontrar la mejor solución. 
              Recibirás una notificación tan pronto como tengamos una resolución.
            </Text>
            <View style={styles.disputeInfoCard}>
              <Text style={styles.disputeInfoTitle}>💡 Mientras tanto, esto es lo que debes saber:</Text>
              <View style={styles.disputeInfoItem}>
                <Text style={styles.disputeInfoBullet}>🛡️</Text>
                <Text style={styles.disputeInfoText}>
                  Tus fondos están completamente seguros y no pueden ser movidos sin tu autorización
                </Text>
              </View>
              <View style={styles.disputeInfoItem}>
                <Text style={styles.disputeInfoBullet}>⏱️</Text>
                <Text style={styles.disputeInfoText}>
                  Nuestro equipo responde en un máximo de 24 horas hábiles
                </Text>
              </View>
              <View style={styles.disputeInfoItem}>
                <Text style={styles.disputeInfoBullet}>💬</Text>
                <Text style={styles.disputeInfoText}>
                  Nuestro equipo de soporte se comunicará contigo a través del chat del intercambio
                </Text>
              </View>
              <View style={styles.disputeInfoItem}>
                <Text style={styles.disputeInfoBullet}>🎯</Text>
                <Text style={styles.disputeInfoText}>
                  Nuestro objetivo es resolver el 95% de las disputas en menos de 48 horas
                </Text>
              </View>
            </View>
          </View>
        ) : (
          <>
            {activeTradeStep === 1 && renderStep1()}
            {activeTradeStep === 2 && renderStep2()}
            {activeTradeStep === 3 && renderStep3()}
            {activeTradeStep === 4 && renderStep4()}
            {activeTradeStep === 5 && renderStep4()}
            {activeTradeStep > 5 && (
              <View style={styles.stepCard}>
                <Text style={styles.stepTitle}>Estado desconocido</Text>
                <Text style={styles.stepDescription}>
                  Step: {activeTradeStep}, Status: {trade.status}
                </Text>
              </View>
            )}
            {!activeTradeStep && (
              <View style={styles.stepCard}>
                <Text style={styles.stepTitle}>Cargando...</Text>
                <Text style={styles.stepDescription}>
                  Por favor espera mientras cargamos los detalles del intercambio.
                </Text>
              </View>
            )}
          </>
        )}
      </ScrollView>

      {/* Dispute Modal */}
      <Modal
        visible={showDisputeModal}
        animationType="slide"
        transparent
        presentationStyle="overFullScreen"
        onRequestClose={() => setShowDisputeModal(false)}
      >
        <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
          <View style={styles.modalOverlay}>
            <KeyboardAvoidingView
              style={styles.kbContainer}
              behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
              keyboardVerticalOffset={Platform.OS === 'ios' ? 64 : 0}
            >
              <View style={styles.modalContent}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>Disputar intercambio</Text>
                  <TouchableOpacity
                    onPress={() => {
                      setShowDisputeModal(false);
                      setDisputeReason('');
                    }}
                    style={styles.modalCloseButton}
                  >
                    <Icon name="x" size={24} color="#6B7280" />
                  </TouchableOpacity>
                </View>

                <ScrollView
                  style={styles.modalScroll}
                  contentContainerStyle={styles.modalScrollContent}
                  keyboardShouldPersistTaps="handled"
                  showsVerticalScrollIndicator={false}
                >
                  <Text style={styles.modalDescription}>
                    Por favor describe detalladamente el problema con este intercambio.
                    Tu reporte será revisado por nuestro equipo de soporte.
                  </Text>

                  <TextInput
                    style={styles.disputeTextInput}
                    placeholder="Describe el problema (mínimo 10 caracteres)..."
                    placeholderTextColor="#9CA3AF"
                    value={disputeReason}
                    onChangeText={setDisputeReason}
                    multiline
                    numberOfLines={6}
                    textAlignVertical="top"
                    returnKeyType="done"
                    onSubmitEditing={Keyboard.dismiss}
                  />
                </ScrollView>

                <View style={styles.modalActions}>
                  <TouchableOpacity
                    style={styles.modalCancelButton}
                    onPress={() => {
                      setShowDisputeModal(false);
                      setDisputeReason('');
                    }}
                    disabled={isSubmittingDispute}
                  >
                    <Text style={styles.modalCancelButtonText}>Cancelar</Text>
                  </TouchableOpacity>

                  <TouchableOpacity
                    style={[
                      styles.modalSubmitButton,
                      (isSubmittingDispute || disputeReason.trim().length < 10) && styles.modalSubmitButtonDisabled,
                    ]}
                    onPress={submitDispute}
                    disabled={isSubmittingDispute || disputeReason.trim().length < 10}
                  >
                    <Text style={styles.modalSubmitButtonText}>
                      {isSubmittingDispute ? 'Enviando...' : 'Enviar disputa'}
                    </Text>
                  </TouchableOpacity>
                </View>
              </View>
            </KeyboardAvoidingView>
          </View>
        </TouchableWithoutFeedback>
      </Modal>
      {/* Global loading overlay for blockchain confirmation */}
      <LoadingOverlay visible={isSubmittingDispute} message="Confirmando disputa en blockchain…" />
      <LoadingOverlay visible={isUploadingEvidence} message="Subiendo evidencia…" />

      {/* Evidence bottom sheet (simple modal) */}
      <Modal
        visible={showEvidenceSheet}
        animationType="slide"
        transparent={Platform.OS !== 'ios'}
        presentationStyle={Platform.OS === 'ios' ? 'overFullScreen' : undefined as any}
        onRequestClose={() => setShowEvidenceSheet(false)}
      >
        {Platform.OS === 'ios' ? (
          <SafeAreaView style={{ flex: 1, backgroundColor: '#00000066' }}>
            <View style={styles.modalOverlay}>
              <View style={styles.modalContent}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>Subir evidencia</Text>
                  <TouchableOpacity onPress={() => setShowEvidenceSheet(false)} style={styles.modalCloseButton}>
                    <Icon name="x" size={24} color="#6B7280" />
                  </TouchableOpacity>
                </View>
                <View style={{ maxHeight: SCROLL_MAX_HEIGHT }}>
                  <ScrollView
                    style={styles.modalScroll}
                    contentContainerStyle={styles.modalScrollContent}
                    keyboardShouldPersistTaps="handled"
                    keyboardDismissMode={'on-drag'}
                    showsVerticalScrollIndicator={true}
                    contentInsetAdjustmentBehavior={'always'}
                    directionalLockEnabled
                    alwaysBounceVertical
                  >
                    <Text style={styles.modalDescription}>
                      Solo se aceptan grabaciones de pantalla del app del banco/fintech (30–45s, máx. 200MB). Sigue esta lista:
                    </Text>
                  {!!confioCode && (
                    <View style={{ backgroundColor: '#ECFDF5', borderWidth: 1, borderColor: '#A7F3D0', borderRadius: 8, padding: 12, marginBottom: 12 }}>
                      <Text style={{ color: '#065F46', fontSize: 14, marginBottom: 4 }}>Código Confío</Text>
                      <Text style={{ color: '#065F46', fontSize: 20, fontWeight: 'bold' }}>{confioCode}</Text>
                      {!!confioCodeExp && (
                        <Text style={{ color: '#065F46', fontSize: 12, marginTop: 4 }}>Vence: {formatLocalDateTime(confioCodeExp)}</Text>
                      )}
                    </View>
                  )}
                  <Text style={styles.stepDescription}>1) Muestra el código de Confío en la pantalla de disputa</Text>
                  <Text style={styles.stepDescription}>2) Abre tu app bancaria y busca la transacción</Text>
                  <Text style={styles.stepDescription}>3) El memo debe incluir el código</Text>
                  <Text style={styles.stepDescription}>4) Haz pull-to-refresh para actualizar</Text>
                  <Text style={styles.stepDescription}>5) Desplázate para mostrar ID/importe/hora</Text>
                  <Text style={styles.stepDescription}>6) Regresa a Confío y sube el video</Text>
                  </ScrollView>
                </View>
                <View style={styles.modalActions}>
                  <TouchableOpacity style={styles.modalSubmitButton} onPress={pickScreenRecordingFromGallery}>
                    <Text style={styles.modalSubmitButtonText}>Seleccionar video de pantalla</Text>
                  </TouchableOpacity>
                </View>
              </View>
            </View>
          </SafeAreaView>
        ) : (
          <View style={[styles.modalOverlay]} pointerEvents="box-none">
            <View style={styles.modalContent}>
                  <View style={styles.modalHeader}>
                    <Text style={styles.modalTitle}>Subir evidencia</Text>
                    <TouchableOpacity onPress={() => setShowEvidenceSheet(false)} style={styles.modalCloseButton}>
                      <Icon name="x" size={24} color="#6B7280" />
                    </TouchableOpacity>
                  </View>
                  <View style={{ maxHeight: SCROLL_MAX_HEIGHT }}>
                    <ScrollView
                      style={styles.modalScroll}
                      contentContainerStyle={styles.modalScrollContent}
                      keyboardShouldPersistTaps="handled"
                      keyboardDismissMode={'interactive'}
                      showsVerticalScrollIndicator={true}
                      nestedScrollEnabled
                      overScrollMode="always"
                      scrollEventThrottle={16}
                      decelerationRate="normal"
                      directionalLockEnabled
                      alwaysBounceVertical
                    >
                      <Text style={styles.modalDescription}>
                        Solo se aceptan grabaciones de pantalla del app del banco/fintech (30–45s, máx. 200MB). Sigue esta lista:
                      </Text>
                      {!!confioCode && (
                        <View style={{ backgroundColor: '#ECFDF5', borderWidth: 1, borderColor: '#A7F3D0', borderRadius: 8, padding: 12, marginBottom: 12 }}>
                          <Text style={{ color: '#065F46', fontSize: 14, marginBottom: 4 }}>Código Confío</Text>
                          <Text style={{ color: '#065F46', fontSize: 20, fontWeight: 'bold' }}>{confioCode}</Text>
                          {!!confioCodeExp && (
                            <Text style={{ color: '#065F46', fontSize: 12, marginTop: 4 }}>Vence: {formatLocalDateTime(confioCodeExp)}</Text>
                          )}
                        </View>
                      )}
                      <Text style={styles.stepDescription}>1) Muestra el código de Confío en la pantalla de disputa</Text>
                      <Text style={styles.stepDescription}>2) Abre tu app bancaria y busca la transacción</Text>
                      <Text style={styles.stepDescription}>3) El memo debe incluir el código</Text>
                      <Text style={styles.stepDescription}>4) Haz pull-to-refresh para actualizar</Text>
                      <Text style={styles.stepDescription}>5) Desplázate para mostrar ID/importe/hora</Text>
                      <Text style={styles.stepDescription}>6) Regresa a Confío y sube el video</Text>
                    </ScrollView>
                  </View>
                  <View style={styles.modalActions}>
                    <TouchableOpacity style={styles.modalSubmitButton} onPress={pickScreenRecordingFromGallery}>
                      <Text style={styles.modalSubmitButtonText}>Seleccionar video de pantalla</Text>
                    </TouchableOpacity>
                  </View>
                </View>
          </View>
        )}
      </Modal>

      {/* Simple video gallery modal */}
      <Modal
        visible={showVideoGallery}
        animationType="slide"
        onRequestClose={() => setShowVideoGallery(false)}
      >
        <SafeAreaView style={{ flex: 1, backgroundColor: '#fff' }}>
          <View style={{ padding: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
            <Text style={{ fontSize: 18, fontWeight: 'bold' }}>Selecciona el video</Text>
            <TouchableOpacity onPress={() => setShowVideoGallery(false)}>
              <Icon name="x" size={24} color="#6B7280" />
            </TouchableOpacity>
          </View>
          <ScrollView contentContainerStyle={{ flexDirection: 'row', flexWrap: 'wrap' }}>
            {videoItems.map((item, idx) => (
              <TouchableOpacity key={idx} onPress={() => handleSelectVideo(item.uri, item.name)} style={{ width: '33.33%', padding: 2 }}>
                <View>
                  <Image source={{ uri: item.thumbUri }} style={{ width: '100%', aspectRatio: 1, backgroundColor: '#eee' }} />
                  <View style={{ position: 'absolute', bottom: 4, right: 4, backgroundColor: 'rgba(0,0,0,0.6)', paddingHorizontal: 6, paddingVertical: 2, borderRadius: 8 }}>
                    <Text style={{ color: '#fff', fontSize: 12 }}>
                      {item.duration ? `${Math.floor(item.duration)}s` : 'Video'}
                    </Text>
                  </View>
                </View>
              </TouchableOpacity>
            ))}
            {videoItems.length === 0 && (
              <View style={{ padding: 24, alignItems: 'center', justifyContent: 'center', width: '100%' }}>
                <ActivityIndicator />
              </View>
            )}
          </ScrollView>
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
  },
  header: {
    backgroundColor: '#fff',
    padding: 16,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 1,
    },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  headerContent: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  backButton: {
    marginRight: 12,
    padding: 4,
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  progressBarContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  progressStep: {
    width: 32,
    height: 32,
    borderRadius: 16,
    justifyContent: 'center',
    alignItems: 'center',
  },
  progressStepActive: {
    backgroundColor: colors.primary,
  },
  progressStepInactive: {
    backgroundColor: '#E5E7EB',
  },
  progressStepText: {
    fontSize: 14,
    fontWeight: '600',
  },
  progressStepTextActive: {
    color: '#ffffff',
  },
  progressStepTextInactive: {
    color: '#6B7280',
  },
  progressLine: {
    flex: 1,
    height: 4,
    marginHorizontal: 8,
  },
  progressLineActive: {
    backgroundColor: colors.primary,
  },
  progressLineInactive: {
    backgroundColor: '#E5E7EB',
  },
  timerCard: {
    backgroundColor: '#DBEAFE',
    padding: 12,
    borderRadius: 8,
    marginBottom: 16,
  },
  timerHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  timerLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1E40AF',
  },
  timerValue: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1E40AF',
  },
  timerValueExpired: {
    color: '#991B1B',
  },
  timerPillExpired: {
    backgroundColor: '#FEE2E2',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 9999,
    borderWidth: 1,
    borderColor: '#FCA5A5',
  },
  timerProgressBar: {
    width: '100%',
    height: 8,
    backgroundColor: '#BFDBFE',
    borderRadius: 4,
  },
  timerProgressFill: {
    height: 8,
    backgroundColor: '#2563EB',
    borderRadius: 4,
  },
  timerProgressExpired: {
    backgroundColor: '#FCA5A5',
  },
  content: {
    flex: 1,
    padding: 16,
  },
  stepCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  stepTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 16,
  },
  stepDescription: {
    fontSize: 16,
    color: '#6B7280',
    marginBottom: 16,
  },
  boldText: {
    fontWeight: 'bold',
  },
  paymentMethodCard: {
    backgroundColor: '#ECFDF5',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
  },
  paymentMethodHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  paymentMethodIcon: {
    width: 40,
    height: 40,
    backgroundColor: colors.primary,
    borderRadius: 20,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  paymentMethodIconText: {
    color: '#ffffff',
    fontSize: 18,
    fontWeight: 'bold',
  },
  paymentMethodName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#065F46',
  },
  paymentMethodSubtitle: {
    fontSize: 14,
    color: '#059669',
  },
  cashInstructionsCard: {
    backgroundColor: '#FEF3C7',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
  },
  cashInstructionsTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#92400E',
    marginBottom: 8,
  },
  cashInstructionsList: {
    gap: 4,
  },
  cashInstruction: {
    fontSize: 14,
    color: '#B45309',
  },
  bankDetailsCard: {
    backgroundColor: '#F9FAFB',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
  },
  bankDetailsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  bankDetailsLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  bankDetailsValue: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  bankDetailsAmount: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  infoCard: {
    backgroundColor: '#DBEAFE',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
  },
  infoContent: {
    flexDirection: 'row',
  },
  infoIcon: {
    marginRight: 8,
    marginTop: 2,
  },
  infoTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1E40AF',
    marginBottom: 4,
  },
  infoText: {
    fontSize: 14,
    color: '#1D4ED8',
    flex: 1,
  },
  warningCard: {
    backgroundColor: '#FEF3C7',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
  },
  warningContent: {
    flexDirection: 'row',
  },
  warningIcon: {
    marginRight: 8,
    marginTop: 2,
  },
  warningTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#92400E',
    marginBottom: 4,
  },
  warningText: {
    fontSize: 14,
    color: '#B45309',
    flex: 1,
  },
  loadingCard: {
    backgroundColor: '#DBEAFE',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
    alignItems: 'center',
  },
  spinner: {
    width: 32,
    height: 32,
    borderWidth: 4,
    borderColor: '#BFDBFE',
    borderTopColor: '#2563EB',
    borderRadius: 16,
    marginBottom: 8,
  },
  loadingTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1E40AF',
    marginBottom: 4,
  },
  loadingSubtitle: {
    fontSize: 14,
    color: '#2563EB',
  },
  summaryCard: {
    backgroundColor: '#F9FAFB',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
  },
  summaryTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 8,
  },
  summaryRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  summaryLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  summaryValue: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  successHeader: {
    alignItems: 'center',
    marginBottom: 24,
  },
  successIcon: {
    width: 64,
    height: 64,
    backgroundColor: '#10B981',
    borderRadius: 32,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  successTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 8,
  },
  successDescription: {
    fontSize: 16,
    color: '#6B7280',
    textAlign: 'center',
  },
  transactionDetailsCard: {
    backgroundColor: '#F9FAFB',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
  },
  transactionDetailsTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 8,
  },
  transactionDetailsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  transactionDetailsLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  transactionDetailsValue: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  successButtons: {
    gap: 12,
    marginTop: 8,
  },
  primaryButton: {
    backgroundColor: colors.primary,
    paddingVertical: 12,
    borderRadius: 12,
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'center',
    marginBottom: 12,
  },
  primaryButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  secondaryButton: {
    backgroundColor: '#F3F4F6',
    paddingVertical: 12,
    borderRadius: 12,
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'center',
  },
  secondaryButtonText: {
    color: '#374151',
    fontSize: 16,
    fontWeight: '600',
  },
  buttonIcon: {
    marginRight: 8,
  },
  viewTradesButton: {
    padding: 4,
  },
  viewAllTradesHint: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 8,
    borderRadius: 8,
    backgroundColor: '#DBEAFE',
  },
  hintIcon: {
    marginRight: 4,
  },
  hintText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#2563EB',
  },
  abandonButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
    backgroundColor: '#FEF2F2',
    borderWidth: 1,
    borderColor: '#EF4444',
  },
  abandonButtonText: {
    color: '#EF4444',
    fontSize: 14,
    fontWeight: '600',
  },
  headerSpacer: {
    flex: 1,
  },
  menuButton: {
    padding: 8,
    marginLeft: 8,
  },
  disputedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#FEE2E2',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#FECACA',
  },
  disputedBadgeText: {
    color: '#DC2626',
    fontSize: 12,
    fontWeight: '600',
    marginLeft: 4,
  },
  disputeBanner: {
    backgroundColor: '#F0FDF9',
    margin: 16,
    marginTop: 0,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: '#10B981',
    overflow: 'hidden',
  },
  disputeBannerContent: {
    flexDirection: 'row',
    padding: 16,
    alignItems: 'flex-start',
  },
  disputeBannerIcon: {
    marginRight: 12,
    marginTop: 2,
  },
  disputeBannerTextContainer: {
    flex: 1,
  },
  disputeBannerTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#0F766E',
    marginBottom: 4,
  },
  disputeBannerText: {
    fontSize: 14,
    color: '#134E4A',
    lineHeight: 20,
  },
  disputeReasonContainer: {
    marginTop: 12,
    padding: 12,
    backgroundColor: '#ECFDF5',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#A7F3D0',
  },
  disputeReasonLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#0F766E',
    marginBottom: 4,
  },
  disputeReasonText: {
    fontSize: 14,
    color: '#134E4A',
    lineHeight: 20,
  },
  disputeChatButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 16,
    backgroundColor: '#ECFDF5',
    borderTopWidth: 1,
    borderTopColor: '#A7F3D0',
  },
  disputeChatButtonText: {
    color: '#0F766E',
    fontSize: 14,
    fontWeight: '600',
    marginLeft: 8,
  },
  disputeInfoCard: {
    marginTop: 16,
    padding: 16,
    backgroundColor: '#F0FDF9',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#A7F3D0',
  },
  disputeInfoTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#0F766E',
    marginBottom: 12,
  },
  disputeInfoItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 12,
  },
  disputeInfoBullet: {
    fontSize: 16,
    marginRight: 8,
    marginTop: 1,
  },
  disputeInfoText: {
    fontSize: 13,
    color: '#134E4A',
    flex: 1,
    lineHeight: 18,
  },
  headerActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  disputeButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
    backgroundColor: '#FEF3C7',
    borderWidth: 1,
    borderColor: '#F59E0B',
  },
  disputeButtonText: {
    color: '#F59E0B',
    fontSize: 14,
    fontWeight: '600',
  },
  disputedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
    backgroundColor: '#FEE2E2',
    gap: 4,
  },
  disputedBadgeText: {
    color: '#DC2626',
    fontSize: 14,
    fontWeight: '600',
  },
  helperText: {
    fontSize: 14,
    color: '#6B7280',
    textAlign: 'center',
    marginTop: 12,
    paddingHorizontal: 24,
    lineHeight: 20,
  },
  // Modal styles
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  kbContainer: {
    width: '100%',
  },
  modalContent: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 20,
    width: '100%',
    maxWidth: 400,
  },
  modalScroll: {
    maxHeight: 300,
  },
  modalScrollContent: {
    paddingBottom: 16,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#111827',
  },
  modalCloseButton: {
    padding: 4,
  },
  modalDescription: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 16,
    lineHeight: 20,
  },
  disputeTextInput: {
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderRadius: 12,
    padding: 12,
    fontSize: 14,
    color: '#111827',
    minHeight: 100,
    marginBottom: 20,
  },
  modalActions: {
    flexDirection: 'row',
    gap: 12,
  },
  modalCancelButton: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: '#F3F4F6',
    alignItems: 'center',
  },
  modalCancelButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#374151',
  },
  modalSubmitButton: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: colors.primary,
    alignItems: 'center',
  },
  modalSubmitButtonDisabled: {
    backgroundColor: '#9CA3AF',
  },
  modalSubmitButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#fff',
  },
  // Technical details styles
  blockchainButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  blockchainIcon: {
    marginRight: 4,
  },
  blockchainButtonText: {
    fontSize: 14,
    color: '#374151',
    marginLeft: 8,
  },
  modalSection: {
    marginBottom: 16,
  },
  modalSectionTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#111827',
    marginBottom: 8,
  },
  technicalRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  technicalLabel: {
    fontSize: 14,
    color: '#6b7280',
  },
  technicalValue: {
    fontSize: 14,
    fontWeight: '500',
    color: '#111827',
    maxWidth: '65%',
  },
  explorerButton: {
    backgroundColor: '#8B5CF6',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 14,
    borderRadius: 12,
    marginTop: 8,
  },
  explorerIcon: {
    marginRight: 8,
  },
  explorerButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
});
