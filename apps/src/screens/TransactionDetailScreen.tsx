import React, { useState, useEffect } from 'react';
import { 
  View, 
  Text, 
  StyleSheet, 
  TouchableOpacity, 
  ScrollView, 
  Platform, 
  Modal, 
  Alert,
  Linking,
  StatusBar,
  Image,
  Clipboard,
  ActivityIndicator
} from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { MainStackParamList } from '../types/navigation';
import Icon from 'react-native-vector-icons/Feather';
import USDCLogo from '../assets/png/USDC.png';
import cUSDLogo from '../assets/png/cUSD.png';
import moment from 'moment';
import 'moment/locale/es';
import { useQuery } from '@apollo/client';
import { GET_SEND_TRANSACTION_BY_ID } from '../apollo/queries';

type TransactionDetailScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;
type TransactionDetailScreenRouteProp = RouteProp<MainStackParamList, 'TransactionDetail'>;

// Color palette from the original design
const colors = {
  primary: '#34d399', // emerald-400
  primaryText: '#34d399',
  primaryLight: '#d1fae5', // emerald-100
  primaryDark: '#10b981', // emerald-500
  secondary: '#8b5cf6', // violet-500
  secondaryText: '#8b5cf6',
  accent: '#3b82f6', // blue-500
  accentText: '#3b82f6',
  neutral: '#f9fafb', // gray-50
  neutralDark: '#f3f4f6', // gray-100
  dark: '#111827', // gray-900
};

export const TransactionDetailScreen = () => {
  const navigation = useNavigation<TransactionDetailScreenNavigationProp>();
  const route = useRoute<TransactionDetailScreenRouteProp>();
  const insets = useSafeAreaInsets();
  const [copied, setCopied] = useState('');
  const [showBlockchainDetails, setShowBlockchainDetails] = useState(false);

  // Get transaction type from route params
  const { transactionType, transactionData: rawTransactionData } = route.params;
  
  // Parse transactionData if it's a string (GraphQL JSONField returns as string)
  let transactionData = rawTransactionData;
  if (typeof rawTransactionData === 'string') {
    try {
      transactionData = JSON.parse(rawTransactionData);
    } catch (e) {
      console.error('[TransactionDetailScreen] Failed to parse transaction data:', e);
      transactionData = null;
    }
  }
  
  // Fetch transaction data if we only have an ID and minimal data
  // Check if we have the essential fields for display
  const hasCompleteData = transactionData?.amount && transactionData?.from && transactionData?.to;
  const needsFetch = (transactionData?.id || transactionData?.transaction_id) && !hasCompleteData;
  const transactionId = transactionData?.id || transactionData?.transaction_id;
  
  console.log('[TransactionDetailScreen] Data parsing:', {
    rawDataType: typeof rawTransactionData,
    parsedDataType: typeof transactionData,
    isParsed: typeof rawTransactionData === 'string' && typeof transactionData === 'object'
  });
  
  console.log('[TransactionDetailScreen] Fetch check:', {
    needsFetch,
    transactionId,
    hasAmount: !!transactionData?.amount,
    dataKeys: transactionData ? Object.keys(transactionData) : []
  });
  
  const { data: fetchedData, loading: fetchLoading, error: fetchError } = useQuery(
    GET_SEND_TRANSACTION_BY_ID,
    {
      variables: { id: transactionId },
      skip: !needsFetch || !transactionId,
    }
  );

  // Check if this is a USDC transaction
  const isUSDCTransaction = transactionData && ['deposit', 'withdrawal', 'conversion'].includes(transactionData.type);

  // Sample transaction data - in real app, this would come from props or API
  const transactions = {
    received: {
      type: 'received',
      from: 'María González',
      fromAddress: '0x1a2b3c4d...7890abcd',
      amount: '+125.50',
      currency: 'cUSD',
      date: '2025-06-10',
      time: '14:30',
      status: 'completed',
      hash: '0xabc123def456789012345678901234567890abcdef',
      blockNumber: '2,847,392',
      gasUsed: '21,000',
      gasFee: '0.001',
      confirmations: 127,
      note: 'Pago por almuerzo - Gracias! 🍕',
      avatar: 'M'
    },
    sent: {
      type: 'sent',
      to: 'Carlos Remolina',
      toAddress: '0x9876543a...bcdef123',
      amount: '-89.25',
      currency: 'cUSD',
      date: '2025-06-09',
      time: '16:45',
      status: 'completed',
      hash: '0xdef456abc123789012345678901234567890fedcba',
      blockNumber: '2,846,891',
      gasUsed: '21,000',
      gasFee: '0.001',
      confirmations: 234,
      note: 'Pago servicios freelance',
      avatar: 'C'
    },
    exchange: {
      type: 'exchange',
      from: 'USDC',
      to: 'cUSD',
      amount: '+500.00',
      currency: 'cUSD',
      date: '2025-06-08',
      time: '10:15',
      status: 'completed',
      hash: '0xghi789abc456012345678901234567890abcdefgh',
      blockNumber: '2,846,123',
      gasUsed: '45,000',
      gasFee: '0.002',
      confirmations: 456,
      exchangeRate: '1 USDC = 1 cUSD',
      avatar: null
    },
    payment: {
      type: 'payment',
      to: 'Supermercado Central',
      toAddress: '0x5555666a...7777888b',
      amount: '-32.75',
      currency: 'cUSD',
      date: '2025-06-07',
      time: '18:45',
      status: 'completed',
      hash: '0xjkl012mno345678901234567890abcdef123456789',
      blockNumber: '2,845,567',
      gasUsed: '21,000',
      gasFee: '0.001',
      confirmations: 789,
      location: 'Av. Libertador, Caracas',
      merchantId: 'SUP001',
      avatar: 'S'
    }
  };

  // Log what data we received
  console.log('[TransactionDetailScreen] Route params:', {
    transactionType,
    hasTransactionData: !!transactionData,
    transactionDataKeys: transactionData ? Object.keys(transactionData) : [],
    transactionData: transactionData,
    needsFetch,
    fetchedData: fetchedData?.sendTransaction,
    fetchError: fetchError?.message
  });
  
  // Transform fetched data to match the expected format
  let txData = transactionData;
  if (fetchedData?.sendTransaction && needsFetch) {
    const tx = fetchedData.sendTransaction;
    const isSent = tx.senderUser?.id === tx.recipientUser?.id; // This needs proper user context
    
    console.log('[TransactionDetailScreen] Transforming fetched data:', {
      tx,
      isSent,
      amount: tx.amount,
      tokenType: tx.tokenType,
    });
    
    txData = {
      ...transactionData,
      type: isSent ? 'sent' : 'received',
      from: tx.senderDisplayName || tx.senderUser?.firstName || 'Usuario',
      fromAddress: tx.senderAddress,
      to: tx.recipientDisplayName || tx.recipientUser?.firstName || 'Usuario',
      toAddress: tx.recipientAddress,
      amount: isSent ? `-${tx.amount}` : `+${tx.amount}`,
      currency: tx.tokenType,
      date: moment(tx.createdAt).format('YYYY-MM-DD'),
      time: moment(tx.createdAt).format('HH:mm'),
      status: tx.status?.toLowerCase() || 'completed',
      hash: tx.transactionHash || '',
      note: tx.memo || '',
      avatar: (isSent ? tx.recipientDisplayName : tx.senderDisplayName)?.[0] || 'U',
      isInvitedFriend: !!tx.invitationExpiresAt,
      transaction_type: 'send',
    };
  }
  
  // If transactionData exists and has content, use it directly
  const currentTx = (transactionData && Object.keys(transactionData).length > 1) 
    ? transactionData 
    : (txData || transactions[transactionType]);
  
  console.log('[TransactionDetailScreen] currentTx selection:', {
    hasTransactionData: !!(transactionData && Object.keys(transactionData).length > 1),
    hasTxData: !!txData,
    usingFallback: !!(transactions[transactionType])
  });
  console.log('[TransactionDetailScreen] currentTx:', currentTx);
  console.log('[TransactionDetailScreen] currentTx details:', {
    amount: currentTx?.amount,
    currency: currentTx?.currency,
    status: currentTx?.status,
    type: currentTx?.type,
    from: currentTx?.from,
    to: currentTx?.to,
    keys: currentTx ? Object.keys(currentTx) : []
  });
  
  // Show loading state while fetching
  if (fetchLoading) {
    return (
      <View style={[styles.container, styles.centerContent]}>
        <ActivityIndicator size="large" color={colors.accent} />
        <Text style={styles.loadingText}>Cargando transacción...</Text>
      </View>
    );
  }
  
  // If no transaction data is available, show an error state
  if (!currentTx) {
    return (
      <View style={styles.container}>
        <Text style={styles.errorText}>No se pudo cargar la información de la transacción</Text>
      </View>
    );
  }
  
  const isInvitedFriend = currentTx?.isInvitedFriend || false;

  const handleCopy = (text: string, type: string) => {
    Clipboard.setString(text);
    Alert.alert('Copiado', 'Dirección copiada al portapapeles');
    setCopied(type);
    setTimeout(() => setCopied(''), 2000);
  };

  const getTransactionIcon = (type: string) => {
    switch(type) {
      case 'received':
        return <Icon name="arrow-down" size={24} color="#10b981" />;
      case 'sent':
        return <Icon name="arrow-up" size={24} color="#ef4444" />;
      case 'exchange':
      case 'conversion':
        return <Icon name="refresh-cw" size={24} color="#3b82f6" />;
      case 'payment':
        return <Icon name="shopping-bag" size={24} color="#8b5cf6" />;
      case 'deposit':
        return <Icon name="arrow-down-circle" size={24} color="#10b981" />;
      case 'withdrawal':
        return <Icon name="arrow-up-circle" size={24} color="#ef4444" />;
      default:
        return <Icon name="arrow-up" size={24} color="#6b7280" />;
    }
  };

  const getTransactionTitle = (tx: any) => {
    switch(tx.type) {
      case 'received':
        return `Recibido de ${tx.from}`;
      case 'sent':
        return `Enviado a ${tx.to}`;
      case 'exchange':
        return `Intercambio ${tx.from} → ${tx.to}`;
      case 'conversion':
        return tx.formattedTitle || `Conversión ${tx.currency || 'USDC'} → ${tx.secondaryCurrency || 'cUSD'}`;
      case 'payment':
        // Check if it's a received payment (positive amount) or sent payment (negative amount)
        return tx.amount.startsWith('+') 
          ? `Pago recibido de ${tx.from}`
          : `Pago a ${tx.to}`;
      case 'deposit':
        return tx.formattedTitle || `Depósito ${tx.currency}`;
      case 'withdrawal':
        return tx.formattedTitle || `Retiro ${tx.currency}`;
      default:
        return 'Transacción';
    }
  };

  const getStatusColor = (status: string) => {
    switch(status?.toLowerCase()) {
      case 'completed':
        return { text: '#059669', bg: '#d1fae5' };
      case 'pending':
      case 'processing':
        return { text: '#d97706', bg: '#fef3c7' };
      case 'failed':
        return { text: '#dc2626', bg: '#fee2e2' };
      default:
        return { text: '#6b7280', bg: '#f3f4f6' };
    }
  };

  const statusColors = getStatusColor(currentTx.status);

  // Create styles with dynamic values
  const styles = StyleSheet.create({
    container: {
      flex: 1,
      backgroundColor: colors.neutral,
    },
    centerContent: {
      justifyContent: 'center',
      alignItems: 'center',
    },
    loadingText: {
      marginTop: 16,
      fontSize: 16,
      color: colors.dark,
    },
    errorText: {
      fontSize: 16,
      color: colors.dark,
      textAlign: 'center',
      marginTop: 50,
      paddingHorizontal: 20,
    },
    scrollView: {
      flex: 1,
    },
    header: {
      backgroundColor: colors.primary,
      paddingTop: insets.top + 8,
      paddingBottom: 32,
      paddingHorizontal: 20,
    },
    headerTop: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: 24,
    },
    headerButton: {
      padding: 8,
    },
    headerTitle: {
      fontSize: 18,
      fontWeight: 'bold',
      color: '#fff',
    },
    transactionSummary: {
      alignItems: 'center',
    },
    iconContainer: {
      width: 64,
      height: 64,
      backgroundColor: '#fff',
      borderRadius: 32,
      justifyContent: 'center',
      alignItems: 'center',
      marginBottom: 16,
    },
    amountText: {
      fontSize: 32,
      fontWeight: 'bold',
      color: '#fff',
      marginBottom: 8,
    },
    negativeAmount: {
      color: '#fecaca', // red-200
    },
    transactionTitle: {
      fontSize: 18,
      fontWeight: '600',
      color: '#fff',
      marginBottom: 12,
      textAlign: 'center',
    },
    statusBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: 12,
      paddingVertical: 6,
      borderRadius: 20,
    },
    statusIcon: {
      marginRight: 4,
    },
    statusText: {
      fontSize: 14,
      fontWeight: '500',
    },
    content: {
      marginTop: -16,
      paddingHorizontal: 16,
      paddingBottom: 24,
    },
    card: {
      backgroundColor: '#fff',
      borderRadius: 16,
      padding: 24,
      marginBottom: 16,
      ...Platform.select({
        ios: {
          shadowColor: '#000',
          shadowOffset: { width: 0, height: 2 },
          shadowOpacity: 0.06,
          shadowRadius: 4,
        },
        android: {
          elevation: 2,
        },
      }),
    },
    cardContent: {
      gap: 16,
    },
    cardTitle: {
      fontSize: 18,
      fontWeight: 'bold',
      color: colors.dark,
      marginBottom: 16,
    },
    participantInfo: {
      flexDirection: 'row',
      alignItems: 'center',
    },
    avatarContainer: {
      width: 48,
      height: 48,
      backgroundColor: colors.neutralDark,
      borderRadius: 24,
      justifyContent: 'center',
      alignItems: 'center',
      marginRight: 16,
    },
    avatarText: {
      fontSize: 18,
      fontWeight: 'bold',
      color: '#6b7280',
    },
    participantDetails: {
      flex: 1,
    },
    participantName: {
      fontSize: 16,
      fontWeight: 'bold',
      color: colors.dark,
      marginBottom: 4,
    },
    addressContainer: {
      flexDirection: 'row',
      alignItems: 'center',
    },
    addressText: {
      fontSize: 14,
      color: '#6b7280',
      marginRight: 8,
      flex: 1,
    },
    copyButton: {
      padding: 4,
    },
    exchangeInfo: {
      alignItems: 'center',
      backgroundColor: '#eff6ff',
      padding: 16,
      borderRadius: 12,
    },
    exchangeIcons: {
      flexDirection: 'row',
      alignItems: 'center',
      marginBottom: 8,
    },
    exchangeIcon: {
      width: 32,
      height: 32,
      borderRadius: 16,
      justifyContent: 'center',
      alignItems: 'center',
    },
    exchangeIconText: {
      color: '#fff',
      fontWeight: 'bold',
      fontSize: 14,
    },
    exchangeArrow: {
      marginHorizontal: 8,
    },
    exchangeRate: {
      fontSize: 14,
      color: '#1d4ed8',
      fontWeight: '500',
    },
    infoRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
    },
    infoIcon: {
      marginRight: 12,
      marginTop: 2,
    },
    infoContent: {
      flex: 1,
    },
    infoTitle: {
      fontSize: 16,
      fontWeight: '500',
      color: colors.dark,
      marginBottom: 2,
    },
    infoSubtitle: {
      fontSize: 14,
      color: '#6b7280',
    },
    noteContainer: {
      backgroundColor: colors.neutral,
      padding: 16,
      borderRadius: 12,
    },
    noteHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      marginBottom: 8,
    },
    noteTitle: {
      fontSize: 14,
      fontWeight: '500',
      color: '#374151',
    },
    noteText: {
      fontSize: 14,
      color: '#6b7280',
      lineHeight: 20,
    },
    summaryContainer: {
      gap: 16,
    },
    feeBreakdown: {
      backgroundColor: colors.neutral,
      padding: 16,
      borderRadius: 12,
      gap: 12,
    },
    feeRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
    },
    feeLabel: {
      fontSize: 14,
      color: '#6B7280',
      flex: 1,
    },
    feeAmount: {
      fontSize: 18,
      fontWeight: 'bold',
      color: colors.dark,
    },
    freeFee: {
      flexDirection: 'row',
      alignItems: 'center',
    },
    freeFeeText: {
      fontSize: 14,
      color: '#10b981',
      fontWeight: '500',
      marginRight: 4,
    },
    freeFeeSubtext: {
      fontSize: 12,
      color: '#6b7280',
    },
    divider: {
      height: 1,
      backgroundColor: '#e5e7eb',
      marginVertical: 4,
    },
    totalLabel: {
      fontSize: 14,
      fontWeight: '500',
      color: colors.dark,
    },
    totalAmount: {
      fontSize: 18,
      fontWeight: 'bold',
      color: colors.dark,
    },
    summaryRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
    },
    summaryLabel: {
      fontSize: 14,
      color: '#6b7280',
    },
    summaryValue: {
      fontSize: 14,
      fontWeight: '500',
      color: colors.dark,
    },
    statusContainer: {
      flexDirection: 'row',
      alignItems: 'center',
    },
    statusValue: {
      fontSize: 14,
      fontWeight: '500',
      color: '#10b981',
      marginLeft: 4,
    },
    valuePropositionOuter: {
      backgroundColor: '#A7F3D0', // emerald-200
      borderRadius: 16,
      padding: 16,
      marginBottom: 20,
      marginHorizontal: 0,
    },
    valueRow: {
      flexDirection: 'row',
      alignItems: 'center',
      marginBottom: 6,
    },
    valueIcon: {
      marginRight: 8,
    },
    valueTitle: {
      fontWeight: 'bold',
      fontSize: 16,
      color: '#059669',
    },
    valueDescription: {
      fontSize: 14,
      color: '#059669',
      marginBottom: 12,
    },
    valueHighlightBox: {
      backgroundColor: '#D1FAE5', // emerald-100
      borderRadius: 12,
      padding: 14,
    },
    valueHighlightText: {
      fontSize: 14,
      color: '#065F46',
      lineHeight: 20,
    },
    bold: {
      fontWeight: 'bold',
    },
    blockchainButton: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: colors.neutralDark,
      paddingVertical: 12,
      borderRadius: 12,
    },
    blockchainIcon: {
      marginRight: 8,
    },
    blockchainButtonText: {
      fontSize: 14,
      fontWeight: '500',
      color: '#6b7280',
    },
    actionsContainer: {
      gap: 12,
    },
    primaryAction: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: colors.primary,
      paddingVertical: 16,
      borderRadius: 12,
    },
    primaryActionText: {
      fontSize: 16,
      fontWeight: '500',
      color: '#fff',
    },
    secondaryAction: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: colors.neutralDark,
      paddingVertical: 16,
      borderRadius: 12,
    },
    secondaryActionText: {
      fontSize: 16,
      fontWeight: '500',
      color: '#6b7280',
    },
    actionIcon: {
      marginRight: 8,
    },
    modalOverlay: {
      flex: 1,
      backgroundColor: 'rgba(0, 0, 0, 0.5)',
      justifyContent: 'center',
      alignItems: 'center',
      padding: 20,
    },
    modalContent: {
      backgroundColor: '#fff',
      borderRadius: 20,
      width: '100%',
      maxWidth: 400,
      maxHeight: '80%',
    },
    modalHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: 24,
      borderBottomWidth: 1,
      borderBottomColor: '#e5e7eb',
    },
    modalTitle: {
      fontSize: 20,
      fontWeight: 'bold',
      color: colors.dark,
    },
    modalBody: {
      padding: 24,
    },
    modalSection: {
      marginBottom: 20,
    },
    modalSectionTitle: {
      fontSize: 14,
      fontWeight: '500',
      color: '#374151',
      marginBottom: 8,
    },
    hashContainer: {
      backgroundColor: colors.neutral,
      padding: 12,
      borderRadius: 8,
      flexDirection: 'row',
      alignItems: 'center',
    },
    hashText: {
      fontSize: 12,
      color: '#6b7280',
      fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
      flex: 1,
    },
    technicalRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingVertical: 8,
    },
    technicalLabel: {
      fontSize: 14,
      color: '#6b7280',
    },
    technicalValue: {
      fontSize: 14,
      fontWeight: '500',
      color: colors.dark,
    },
    explorerButton: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: colors.accent,
      paddingVertical: 16,
      borderRadius: 12,
      marginTop: 16,
    },
    explorerIcon: {
      marginRight: 8,
    },
    explorerButtonText: {
      fontSize: 14,
      fontWeight: '500',
      color: '#fff',
    },
    infoNote: {
      backgroundColor: '#eff6ff',
      padding: 12,
      borderRadius: 8,
      marginTop: 16,
    },
    infoNoteText: {
      fontSize: 12,
      color: '#1d4ed8',
      lineHeight: 16,
    },
    feeValueFree: {
      color: colors.primary,
      fontWeight: 'bold',
      marginRight: 4,
    },
    feeValueNote: {
      color: '#6B7280',
      fontSize: 14,
    },
    invitationNotice: {
      flexDirection: 'row',
      alignItems: 'center',
      marginTop: 12,
      backgroundColor: '#ef4444',
      paddingHorizontal: 16,
      paddingVertical: 8,
      borderRadius: 20,
    },
    invitationText: {
      color: '#fff',
      fontSize: 14,
      fontWeight: '500',
    },
    invitationCard: {
      backgroundColor: '#fef2f2',
      borderColor: '#ef4444',
      borderWidth: 2,
    },
    invitationHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      marginBottom: 12,
    },
    invitationCardTitle: {
      fontSize: 18,
      fontWeight: 'bold',
      color: colors.secondary,
      marginLeft: 12,
    },
    invitationCardText: {
      fontSize: 16,
      color: '#1f2937',
      marginBottom: 16,
      lineHeight: 24,
    },
    invitationInfoBox: {
      backgroundColor: '#fff',
      borderRadius: 12,
      padding: 16,
      borderWidth: 1,
      borderColor: colors.secondary + '20',
    },
    invitationInfoTitle: {
      fontSize: 14,
      fontWeight: '600',
      color: colors.secondary,
      marginBottom: 12,
    },
    invitationInfoRow: {
      flexDirection: 'row',
      alignItems: 'center',
      marginBottom: 8,
    },
    invitationInfoText: {
      fontSize: 14,
      color: '#4b5563',
      flex: 1,
    },
    shareButton: {
      backgroundColor: '#25D366', // WhatsApp green
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      paddingVertical: 14,
      paddingHorizontal: 20,
      borderRadius: 12,
      marginTop: 16,
    },
    shareButtonText: {
      color: '#fff',
      fontSize: 16,
      fontWeight: '600',
    },
  });

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      
      {/* Entire screen scrollable */}
      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerTop}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerButton}>
              <Icon name="arrow-left" size={24} color="#fff" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Detalle de Transacción</Text>
            <TouchableOpacity style={styles.headerButton}>
              <Icon name="share" size={24} color="#fff" />
            </TouchableOpacity>
          </View>
          
          <View style={styles.transactionSummary}>
            <View style={styles.iconContainer}>
              {getTransactionIcon(currentTx.type)}
            </View>
            
            <Text style={[
              styles.amountText,
              (currentTx.type === 'sent' || currentTx.type === 'payment' || currentTx.type === 'withdrawal') && styles.negativeAmount
            ]}>
              {currentTx.type === 'deposit' ? '+' : currentTx.type === 'withdrawal' ? '-' : ''}{currentTx.amount || '0.00'} {currentTx.currency || 'cUSD'}
            </Text>
            
            <Text style={styles.transactionTitle}>
              {getTransactionTitle(currentTx)}
            </Text>
            
            <View style={[styles.statusBadge, { backgroundColor: statusColors.bg }]}>
              {(currentTx.status?.toLowerCase() === 'completed' || currentTx.status?.toLowerCase() === 'confirmed') && (
                <Icon name="check-circle" size={16} color={statusColors.text} style={styles.statusIcon} />
              )}
              {currentTx.status?.toLowerCase() === 'pending' && (
                <Icon name="clock" size={16} color={statusColors.text} style={styles.statusIcon} />
              )}
              {currentTx.status?.toLowerCase() === 'processing' && (
                <Icon name="loader" size={16} color={statusColors.text} style={styles.statusIcon} />
              )}
              {currentTx.status?.toLowerCase() === 'failed' && (
                <Icon name="x-circle" size={16} color={statusColors.text} style={styles.statusIcon} />
              )}
              <Text style={[styles.statusText, { color: statusColors.text }]}>
                {currentTx.status?.toLowerCase() === 'completed' ? 'Completado' :
                 currentTx.status?.toLowerCase() === 'confirmed' ? 'Completado' :
                 currentTx.status?.toLowerCase() === 'pending' ? 'Pendiente' :
                 currentTx.status?.toLowerCase() === 'processing' ? 'Procesando' :
                 currentTx.status?.toLowerCase() === 'failed' ? 'Fallido' : 'Desconocido'}
              </Text>
            </View>
            
            {isInvitedFriend && currentTx.type === 'sent' && (
              <View style={styles.invitationNotice}>
                <Icon name="alert-triangle" size={16} color="#fff" style={{ marginRight: 6 }} />
                <Text style={styles.invitationText}>Tu amigo tiene 7 días para reclamar</Text>
              </View>
            )}
          </View>
        </View>

        {/* Content */}
        <View style={styles.content}>
          {/* Main Transaction Info */}
          <View style={styles.card}>
            <View style={styles.cardContent}>
              {/* Participant Info */}
              {currentTx.type === 'deposit' && (
                <View style={styles.participantInfo}>
                  <View style={styles.avatarContainer}>
                    <Icon name="arrow-down-circle" size={24} color={colors.primary} />
                  </View>
                  <View style={styles.participantDetails}>
                    <Text style={styles.participantName}>Depósito desde wallet externa</Text>
                    <View style={styles.addressContainer}>
                      <Text style={styles.addressText}>{currentTx.sourceAddress || currentTx.fromAddress}</Text>
                      <TouchableOpacity 
                        onPress={() => handleCopy(currentTx.sourceAddress || currentTx.fromAddress, 'from')}
                        style={styles.copyButton}
                      >
                        {copied === 'from' ? (
                          <Icon name="check" size={16} color={colors.accent} />
                        ) : (
                          <Icon name="copy" size={16} color={colors.accent} />
                        )}
                      </TouchableOpacity>
                    </View>
                  </View>
                </View>
              )}

              {currentTx.type === 'withdrawal' && (
                <View style={styles.participantInfo}>
                  <View style={styles.avatarContainer}>
                    <Icon name="arrow-up-circle" size={24} color="#ef4444" />
                  </View>
                  <View style={styles.participantDetails}>
                    <Text style={styles.participantName}>Retiro hacia wallet externa</Text>
                    <View style={styles.addressContainer}>
                      <Text style={styles.addressText}>{currentTx.destinationAddress || currentTx.toAddress}</Text>
                      <TouchableOpacity 
                        onPress={() => handleCopy(currentTx.destinationAddress || currentTx.toAddress, 'to')}
                        style={styles.copyButton}
                      >
                        {copied === 'to' ? (
                          <Icon name="check" size={16} color={colors.accent} />
                        ) : (
                          <Icon name="copy" size={16} color={colors.accent} />
                        )}
                      </TouchableOpacity>
                    </View>
                  </View>
                </View>
              )}

              {currentTx.type === 'conversion' && (
                <View style={styles.exchangeInfo}>
                  <View style={styles.exchangeIcons}>
                    <View style={[styles.exchangeIcon, { backgroundColor: '#fff' }]}>
                      {(currentTx.currency || '').trim().toUpperCase() === 'USDC' ? (
                        <Image source={USDCLogo} style={{ width: 24, height: 24, resizeMode: 'contain' }} />
                      ) : (
                        <Image source={cUSDLogo} style={{ width: 24, height: 24, resizeMode: 'contain' }} />
                      )}
                    </View>
                    <Icon name="arrow-right" size={16} color="#6b7280" style={styles.exchangeArrow} />
                    <View style={[styles.exchangeIcon, { backgroundColor: '#fff' }]}>
                      {(currentTx.secondaryCurrency || '').trim().toUpperCase() === 'USDC' ? (
                        <Image source={USDCLogo} style={{ width: 24, height: 24, resizeMode: 'contain' }} />
                      ) : (
                        <Image source={cUSDLogo} style={{ width: 24, height: 24, resizeMode: 'contain' }} />
                      )}
                    </View>
                  </View>
                  {currentTx.exchangeRate && (
                    <Text style={styles.exchangeRate}>
                      Tasa: {
                        // Format exchange rate for conversions
                        (() => {
                          const rate = currentTx.exchangeRate;
                          const isOneToOne = parseFloat(rate) === 1 || rate === '1' || rate === '1.000000';
                          
                          // For USDC conversions with 1:1 rate
                          if (((currentTx.currency || '').toUpperCase() === 'USDC' || (currentTx.secondaryCurrency || '').toUpperCase() === 'USDC') && isOneToOne) {
                            return `1 ${currentTx.currency} = 1 ${currentTx.secondaryCurrency}`;
                          }
                          
                          // If rate already contains '=', use as is
                          if (rate && rate.includes('=')) {
                            return rate;
                          }
                          
                          // Format rate without decimals if it's a whole number
                          const formattedRate = isOneToOne ? '1' : rate;
                          return `1 ${currentTx.currency} = ${formattedRate} ${currentTx.secondaryCurrency}`;
                        })()
                      }
                    </Text>
                  )}
                </View>
              )}

              {currentTx.type === 'received' && (
                <View style={styles.participantInfo}>
                  <View style={styles.avatarContainer}>
                    <Text style={styles.avatarText}>{currentTx.avatar}</Text>
                  </View>
                  <View style={styles.participantDetails}>
                    <Text style={styles.participantName}>{currentTx.from}</Text>
                    <View style={styles.addressContainer}>
                      <Text style={styles.addressText}>{currentTx.fromAddress}</Text>
                      <TouchableOpacity 
                        onPress={() => handleCopy(currentTx.fromAddress, 'from')}
                        style={styles.copyButton}
                      >
                        {copied === 'from' ? (
                          <Icon name="check" size={16} color={colors.accent} />
                        ) : (
                          <Icon name="copy" size={16} color={colors.accent} />
                        )}
                      </TouchableOpacity>
                    </View>
                  </View>
                </View>
              )}

              {currentTx.type === 'sent' && (
                <View style={styles.participantInfo}>
                  <View style={styles.avatarContainer}>
                    <Text style={styles.avatarText}>{currentTx.avatar}</Text>
                  </View>
                  <View style={styles.participantDetails}>
                    <Text style={styles.participantName}>{currentTx.to}</Text>
                    <View style={styles.addressContainer}>
                      <Text style={styles.addressText}>{currentTx.toAddress}</Text>
                      <TouchableOpacity 
                        onPress={() => handleCopy(currentTx.toAddress, 'to')}
                        style={styles.copyButton}
                      >
                        {copied === 'to' ? (
                          <Icon name="check" size={16} color={colors.accent} />
                        ) : (
                          <Icon name="copy" size={16} color={colors.accent} />
                        )}
                      </TouchableOpacity>
                    </View>
                  </View>
                </View>
              )}
              
              {currentTx.type === 'payment' && (
                <View style={styles.participantInfo}>
                  <View style={styles.avatarContainer}>
                    <Text style={styles.avatarText}>
                      {currentTx.amount?.startsWith('+') 
                        ? (currentTx.from ? currentTx.from.charAt(0) : 'U')
                        : (currentTx.to ? currentTx.to.charAt(0) : 'U')
                      }
                    </Text>
                  </View>
                  <View style={styles.participantDetails}>
                    <Text style={styles.participantName}>
                      {currentTx.amount?.startsWith('+') ? currentTx.from : currentTx.to}
                    </Text>
                    <View style={styles.addressContainer}>
                      <Text style={styles.addressText}>
                        {currentTx.amount?.startsWith('+') ? currentTx.fromAddress : currentTx.toAddress}
                      </Text>
                      <TouchableOpacity 
                        onPress={() => handleCopy(
                          currentTx.amount?.startsWith('+') ? currentTx.fromAddress : currentTx.toAddress, 
                          currentTx.amount?.startsWith('+') ? 'from' : 'to'
                        )}
                        style={styles.copyButton}
                      >
                        {copied === (currentTx.amount?.startsWith('+') ? 'from' : 'to') ? (
                          <Icon name="check" size={16} color={colors.accent} />
                        ) : (
                          <Icon name="copy" size={16} color={colors.accent} />
                        )}
                      </TouchableOpacity>
                    </View>
                  </View>
                </View>
              )}

              {currentTx.type === 'exchange' && (
                <View style={styles.exchangeInfo}>
                  <View style={styles.exchangeIcons}>
                    <View style={[styles.exchangeIcon, { backgroundColor: '#fff' }]}>
                      <Image source={USDCLogo} style={{ width: 24, height: 24, resizeMode: 'contain' }} />
                    </View>
                    <Icon name="arrow-down" size={16} color="#6b7280" style={styles.exchangeArrow} />
                    <View style={[styles.exchangeIcon, { backgroundColor: '#fff' }]}>
                      <Image source={cUSDLogo} style={{ width: 24, height: 24, resizeMode: 'contain' }} />
                    </View>
                  </View>
                  <Text style={styles.exchangeRate}>Tasa: {currentTx.exchangeRate}</Text>
                </View>
              )}

              {/* Date & Time */}
              <View style={styles.infoRow}>
                <Icon name="clock" size={20} color="#9ca3af" style={styles.infoIcon} />
                <View style={styles.infoContent}>
                  <Text style={styles.infoTitle}>
                    {currentTx.date && currentTx.time 
                      ? `${moment(currentTx.date).format('DD/MM/YYYY')} • ${currentTx.time}`
                      : currentTx.createdAt 
                        ? `${moment(currentTx.createdAt).format('DD/MM/YYYY')} • ${moment(currentTx.createdAt).format('HH:mm')}`
                        : 'Fecha no disponible'
                    }
                  </Text>
                  <Text style={styles.infoSubtitle}>
                    {currentTx.timestamp 
                      ? moment(currentTx.timestamp).locale('es').fromNow()
                      : currentTx.createdAt
                        ? moment(currentTx.createdAt).locale('es').fromNow()
                        : currentTx.date 
                          ? moment(currentTx.date, 'YYYY-MM-DD').locale('es').fromNow()
                          : ''}
                  </Text>
                </View>
              </View>

              {/* Location for payments - only show when user is paying a business */}
              {currentTx.type === 'payment' && currentTx.amount?.startsWith('-') && currentTx.location && (
                <View style={styles.infoRow}>
                  <Icon name="map-pin" size={20} color="#9ca3af" style={styles.infoIcon} />
                  <View style={styles.infoContent}>
                    <Text style={styles.infoTitle}>{currentTx.location}</Text>
                    <Text style={styles.infoSubtitle}>ID: {currentTx.merchantId}</Text>
                  </View>
                </View>
              )}

              {/* Note */}
              {currentTx.note && (
                <View style={styles.noteContainer}>
                  <View style={styles.noteHeader}>
                    <Icon name="file-text" size={20} color="#9ca3af" style={styles.infoIcon} />
                    <Text style={styles.noteTitle}>Nota</Text>
                  </View>
                  <Text style={styles.noteText}>{currentTx.note}</Text>
                </View>
              )}
            </View>
          </View>

          {/* Transaction Summary */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Resumen de Operación</Text>
            
            <View style={styles.summaryContainer}>
              {/* Amount and Fee Breakdown */}
              <View style={styles.feeBreakdown}>
                <View style={styles.feeRow}>
                  <Text style={styles.feeLabel}>
                    {currentTx.type === 'received' ? 'Monto recibido' : 
                     currentTx.type === 'exchange' ? 'Monto intercambiado' : 'Monto enviado'}
                  </Text>
                  <Text style={styles.feeAmount}>
                    {currentTx.amount ? Math.abs(parseFloat(currentTx.amount.replace(/[+-]/g, ''))).toFixed(2) : '0.00'} {currentTx.currency || 'cUSD'}
                  </Text>
                </View>
                
                <View style={styles.feeRow}>
                  <Text style={styles.feeLabel}>Comisión de red</Text>
                  <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                    <Text style={styles.feeValueFree}>Gratis</Text>
                    <Text style={styles.feeValueNote}>• Cubierto por Confío</Text>
                  </View>
                </View>
                
                {(currentTx.type === 'sent' || currentTx.type === 'payment') && (
                  <>
                    <View style={styles.divider} />
                    <View style={styles.feeRow}>
                      <Text style={styles.totalLabel}>Total debitado</Text>
                      <Text style={styles.totalAmount}>
                        {currentTx.amount || '0.00'} {currentTx.currency || 'cUSD'}
                      </Text>
                    </View>
                  </>
                )}
              </View>

              {/* Transaction ID */}
              <View style={styles.summaryRow}>
                <Text style={styles.summaryLabel}>ID de Operación</Text>
                <Text style={styles.summaryValue}>#{currentTx.hash?.slice(-8).toUpperCase() || 'N/A'}</Text>
              </View>

              {/* Status */}
              <View style={styles.summaryRow}>
                <Text style={styles.summaryLabel}>Estado</Text>
                <View style={styles.statusContainer}>
                  <Icon name="check-circle" size={16} color="#10b981" style={styles.statusIcon} />
                  <Text style={styles.statusValue}>Procesado exitosamente</Text>
                </View>
              </View>

              {/* Processing Time */}
              <View style={styles.summaryRow}>
                <Text style={styles.summaryLabel}>Tiempo de procesamiento</Text>
                <Text style={styles.summaryValue}>Instantáneo</Text>
              </View>
            </View>
          </View>

          {/* Invitation Info Card for non-Confío friends */}
          {isInvitedFriend && currentTx.type === 'sent' && (
            <View style={[styles.card, styles.invitationCard]}>
              <View style={styles.invitationHeader}>
                <Icon name="alert-circle" size={24} color="#ef4444" />
                <Text style={[styles.invitationCardTitle, { color: '#ef4444' }]}>¡Acción Requerida!</Text>
              </View>
              
              <Text style={[styles.invitationCardText, { fontWeight: 'bold', color: '#dc2626' }]}>
                ⏰ Tu amigo tiene solo 7 días para reclamar el dinero o se perderá
              </Text>
              
              <View style={[styles.invitationInfoBox, { backgroundColor: '#fef2f2', borderColor: '#ef4444' }]}>
                <Text style={[styles.invitationInfoTitle, { color: '#dc2626' }]}>¡Avísale ahora mismo!</Text>
                <View style={styles.invitationInfoRow}>
                  <Text style={styles.invitationInfoText}>1. Envíale un mensaje con el link de invitación</Text>
                </View>
                <View style={styles.invitationInfoRow}>
                  <Text style={styles.invitationInfoText}>2. Ayúdale a crear su cuenta en Confío</Text>
                </View>
                <View style={styles.invitationInfoRow}>
                  <Text style={styles.invitationInfoText}>3. Una vez registrado, recibirá el dinero al instante</Text>
                </View>
              </View>
              
              <TouchableOpacity style={styles.shareButton} onPress={() => {
                Alert.alert(
                  'Compartir invitación',
                  `Comparte este mensaje:\n\n¡Hola! Te envié ${currentTx.amount || '0.00'} ${currentTx.currency || 'cUSD'} por Confío. Tienes 7 días para reclamarlo. Descarga la app aquí: [link]`
                );
              }}>
                <Icon name="share-2" size={20} color="#fff" style={{ marginRight: 8 }} />
                <Text style={styles.shareButtonText}>Compartir invitación por WhatsApp</Text>
              </TouchableOpacity>
            </View>
          )}

          {/* Confío Value Proposition */}
          {(currentTx.type === 'received' || currentTx.type === 'sent') && (
            <View style={styles.card}>
              <Text style={styles.cardTitle}>¿Por qué elegir Confío?</Text>
              <View style={styles.valuePropositionOuter}>
                <View style={styles.valueRow}>
                  <Icon name="check-circle" size={20} color={colors.primary} style={styles.valueIcon} />
                  <Text style={styles.valueTitle}>Transferencias 100% gratuitas</Text>
                </View>
                <Text style={styles.valueDescription}>
                  {currentTx.type === 'received' 
                    ? 'Recibiste este dinero sin pagar comisiones'
                    : 'Enviaste este dinero sin pagar comisiones'
                  }
                </Text>
                <View style={styles.valueHighlightBox}>
                  <Text style={styles.valueHighlightText}>
                    💡 <Text style={styles.bold}>Confío: 0% comisión</Text>{'\n'}
                    vs. remesadoras tradicionales <Text style={styles.bold}>(5%-20%)</Text>{'\n'}
                    Apoyamos a los venezolanos 🇻🇪 con transferencias gratuitas
                  </Text>
                </View>
              </View>
            </View>
          )}

          {/* Blockchain Details Button */}
          <View style={styles.card}>
            <TouchableOpacity 
              onPress={() => setShowBlockchainDetails(true)}
              style={styles.blockchainButton}
            >
              <Icon name="external-link" size={16} color="#6b7280" style={styles.blockchainIcon} />
              <Text style={styles.blockchainButtonText}>Ver detalles técnicos</Text>
            </TouchableOpacity>
          </View>

          {/* Actions */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Acciones</Text>
            
            <View style={styles.actionsContainer}>
              {(currentTx.type === 'received' || currentTx.type === 'sent') && (
                <TouchableOpacity 
                  style={styles.primaryAction}
                  onPress={() => {
                    // Navigate to SendToFriend screen
                    const friendName = currentTx.type === 'received' ? currentTx.from : currentTx.to;
                    const friendPhone = currentTx.type === 'received' ? currentTx.fromPhone : currentTx.toPhone;
                    
                    // Debug logging to understand the data
                    console.log('[TransactionDetail] Navigation data:', {
                      transactionType: currentTx.type,
                      friendName,
                      friendPhone,
                      isInvitedFriend: currentTx.isInvitedFriend
                    });
                    
                    // For navigation, we need to determine if this is a Confío user
                    // If it's an invited friend (non-Confío user), we shouldn't navigate
                    // Note: isInvitedFriend means they are NOT on Confío (invitation transaction)
                    if (currentTx.isInvitedFriend) {
                      // This is a non-Confío friend, navigate differently
                      Alert.alert(
                        'Usuario no está en Confío',
                        'Este amigo aún no se ha unido a Confío. Debes esperar a que se registre para poder enviarle dinero nuevamente.',
                        [{ text: 'OK' }]
                      );
                    } else {
                      // This is a Confío user - we just need their phone number
                      // The server will look up their current active Sui address
                      const friendData = {
                        name: friendName || 'Amigo',
                        avatar: currentTx.avatar || friendName?.charAt(0) || 'A',
                        isOnConfio: true,
                        phone: friendPhone || '',
                        // No userId here, but server can look up by phone
                      };
                      
                      console.log('[TransactionDetail] Navigating to SendToFriend with data:', friendData);
                      
                      navigation.navigate('SendToFriend', {
                        friend: friendData,
                        tokenType: currentTx.currency.toLowerCase() === 'cusd' ? 'cusd' : 'confio'
                      });
                    }
                  }}
                >
                  <Icon name="user" size={16} color="#fff" style={styles.actionIcon} />
                  <Text style={styles.primaryActionText}>
                    {currentTx.type === 'received' ? `Enviar a ${currentTx.from}` : `Enviar de nuevo a ${currentTx.to}`}
                  </Text>
                </TouchableOpacity>
              )}
            </View>
          </View>
        </View>
      </ScrollView>
    </View>
  );
};