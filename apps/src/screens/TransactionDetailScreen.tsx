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
  ActivityIndicator,
  Share,
} from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { MainStackParamList } from '../types/navigation';
import Icon from 'react-native-vector-icons/Feather';
import USDCLogo from '../assets/png/USDC.png';
import cUSDLogo from '../assets/png/cUSD.png';
import WhatsAppLogo from '../assets/svg/WhatsApp.svg';
import moment from 'moment';
import 'moment/locale/es';
import { useQuery } from '@apollo/client';
import { GET_SEND_TRANSACTION_BY_ID } from '../apollo/queries';
import { useContactNameSync } from '../hooks/useContactName';
import { SHARE_LINKS } from '../config/shareLinks';

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

// Helper function to format amount with proper decimals
const formatAmount = (amount: string | number | undefined): string => {
  if (!amount) return '0.00';
  const numericAmount = typeof amount === 'string' ? parseFloat(amount.replace(/[+-]/g, '')) : amount;
  return numericAmount.toFixed(2);
};

  // Helper function to format amount with sign
  const formatAmountWithSign = (amount: string | undefined): string => {
  if (!amount) return '0.00';
  const sign = amount.startsWith('-') ? '-' : amount.startsWith('+') ? '+' : '';
  const numericPart = formatAmount(amount);
  return sign + numericPart;
};

// Helper function to format phone numbers for display
const formatPhoneNumber = (phone: string | undefined): string => {
  if (!phone) return '';
  
  // Extract country code and phone number
  // Format: "AS9293993619" where AS = American Samoa, DO = Dominican Republic, etc.
  const countryCodeMatch = phone.match(/^([A-Z]{2})(.+)$/);
  if (!countryCodeMatch) return phone;
  
  const [, countryPrefix, phoneNumber] = countryCodeMatch;
  
  // Map common country prefixes to dialing codes
  const countryDialingCodes: { [key: string]: string } = {
    'US': '1',    // United States
    'AS': '1',    // American Samoa
    'DO': '1',    // Dominican Republic  
    'VE': '58',   // Venezuela
    'CO': '57',   // Colombia
    'MX': '52',   // Mexico
    'AR': '54',   // Argentina
    'PE': '51',   // Peru
    'CL': '56',   // Chile
    'EC': '593',  // Ecuador
    'BR': '55',   // Brazil
    'UY': '598',  // Uruguay
    'PY': '595',  // Paraguay
    'BO': '591',  // Bolivia
    // Add more as needed
  };
  
  const dialingCode = countryDialingCodes[countryPrefix] || '';
  
  // Format based on length and country
  if (dialingCode === '1' && phoneNumber.length === 10) {
    // North American format: +1 (XXX) XXX-XXXX
    return `+${dialingCode} (${phoneNumber.slice(0, 3)}) ${phoneNumber.slice(3, 6)}-${phoneNumber.slice(6)}`;
  } else if (dialingCode) {
    // International format: +XX XXXX XXXXXX (adjust spacing as needed)
    return `+${dialingCode} ${phoneNumber}`;
  }
  
  return phone; // Return as-is if we can't format it
};

// Helper to compute Confío service fee (0.9%) for payment transactions
const computeConfioFee = (amountLike: string | number | undefined): number => {
  try {
    if (amountLike === undefined || amountLike === null) return 0;
    const amt = typeof amountLike === 'string' 
      ? parseFloat(amountLike.replace(/[+-]/g, '')) 
      : Number(amountLike);
    if (!isFinite(amt)) return 0;
    // 0.9% fee charged to the merchant (informational here)
    return parseFloat((amt * 0.009).toFixed(2));
  } catch {
    return 0;
  }
};

export const TransactionDetailScreen = () => {
  const navigation = useNavigation<TransactionDetailScreenNavigationProp>();
  const route = useRoute<TransactionDetailScreenRouteProp>();
  const insets = useSafeAreaInsets();
  const [copied, setCopied] = useState('');
  const [showBlockchainDetails, setShowBlockchainDetails] = useState(false);

  // Define styles early to avoid undefined errors
  const styles = StyleSheet.create({
    container: {
      flex: 1,
      backgroundColor: colors.primary,
    },
    centerContent: {
      justifyContent: 'center',
      alignItems: 'center',
    },
    loadingText: {
      marginTop: 16,
      fontSize: 16,
      color: colors.accent,
    },
    errorText: {
      fontSize: 16,
      color: '#ef4444',
      textAlign: 'center',
      padding: 20,
    },
    scrollView: {
      flex: 1,
    },
    header: {
      paddingTop: insets.top,
      paddingHorizontal: 20,
      paddingBottom: 30,
      backgroundColor: colors.primary,
    },
    headerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: 24,
    },
    backButton: {
      width: 40,
      height: 40,
      borderRadius: 20,
      backgroundColor: 'rgba(255, 255, 255, 0.2)',
      alignItems: 'center',
      justifyContent: 'center',
    },
    headerTitle: {
      fontSize: 20,
      fontWeight: '600',
      color: '#fff',
    },
    statusContainer: {
      alignItems: 'center',
      marginBottom: 16,
    },
    statusIcon: {
      width: 64,
      height: 64,
      borderRadius: 32,
      backgroundColor: 'rgba(255, 255, 255, 0.2)',
      alignItems: 'center',
      justifyContent: 'center',
      marginBottom: 12,
    },
    statusText: {
      fontSize: 16,
      fontWeight: '500',
      color: '#fff',
      marginBottom: 4,
    },
    amountText: {
      fontSize: 36,
      fontWeight: 'bold',
      color: '#fff',
      marginBottom: 4,
    },
    currencyText: {
      fontSize: 20,
      color: '#fff',
      opacity: 0.8,
    },
    content: {
      flex: 1,
      backgroundColor: '#fff',
      borderTopLeftRadius: 24,
      borderTopRightRadius: 24,
      paddingTop: 24,
      paddingHorizontal: 20,
      paddingBottom: 20,
    },
    avatarSection: {
      alignItems: 'center',
      marginBottom: 24,
    },
    avatar: {
      width: 64,
      height: 64,
      borderRadius: 32,
      backgroundColor: colors.secondary,
      alignItems: 'center',
      justifyContent: 'center',
      marginBottom: 12,
    },
    avatarText: {
      fontSize: 24,
      fontWeight: 'bold',
      color: '#fff',
    },
    receiverName: {
      fontSize: 20,
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
    },
    dateTimeRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 16,
      paddingHorizontal: 4,
    },
    dateTimeItem: {
      flexDirection: 'row',
      alignItems: 'center',
    },
    dateTimeText: {
      fontSize: 14,
      color: '#6b7280',
      marginLeft: 6,
    },
    section: {
      marginBottom: 20,
    },
    sectionHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      marginBottom: 12,
    },
    sectionIcon: {
      marginRight: 8,
    },
    sectionTitle: {
      fontSize: 16,
      fontWeight: '600',
      color: colors.dark,
    },
    card: {
      backgroundColor: colors.neutral,
      borderRadius: 12,
      padding: 16,
    },
    cardTitle: {
      fontSize: 18,
      fontWeight: 'bold',
      color: colors.dark,
      marginBottom: 16,
    },
    row: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 12,
    },
    label: {
      fontSize: 14,
      color: '#6b7280',
    },
    value: {
      fontSize: 14,
      fontWeight: '500',
      color: colors.dark,
    },
    noteCard: {
      backgroundColor: colors.primaryLight,
      borderRadius: 12,
      padding: 16,
    },
    noteText: {
      fontSize: 16,
      color: '#065f46',
      fontStyle: 'italic',
      lineHeight: 22,
    },
    actionButton: {
      flex: 1,
      backgroundColor: colors.primary,
      paddingVertical: 14,
      borderRadius: 12,
      alignItems: 'center',
      marginHorizontal: 6,
    },
    actionButtonText: {
      fontSize: 16,
      fontWeight: '600',
      color: '#fff',
    },
    // Missing card styles
    cardContent: {
      flex: 1,
    },
    summaryContainer: {
      gap: 16,
    },
    feeBreakdown: {
      backgroundColor: '#f9fafb',
      borderRadius: 8,
      padding: 12,
    },
    feeRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 8,
    },
    feeLabel: {
      fontSize: 14,
      color: '#6b7280',
    },
    feeAmount: {
      fontSize: 14,
      fontWeight: '600',
      color: colors.dark,
    },
    feeValueFree: {
      fontSize: 14,
      fontWeight: '600',
      color: '#10b981',
    },
    feeValueNote: {
      fontSize: 12,
      color: '#6b7280',
      marginLeft: 4,
    },
    divider: {
      height: 1,
      backgroundColor: '#e5e7eb',
      marginVertical: 8,
    },
    totalLabel: {
      fontSize: 14,
      fontWeight: '600',
      color: colors.dark,
    },
    totalAmount: {
      fontSize: 16,
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
    statusIcon: {
      marginRight: 4,
    },
    statusValue: {
      fontSize: 14,
      fontWeight: '500',
      color: '#10b981',
    },
    invitationCard: {
      backgroundColor: '#fef2f2',
      borderColor: '#ef4444',
      borderWidth: 1,
    },
    invitationHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      marginBottom: 12,
    },
    invitationCardTitle: {
      fontSize: 18,
      fontWeight: 'bold',
      marginLeft: 8,
    },
    invitationCardText: {
      fontSize: 14,
      color: '#1f2937',
      marginBottom: 12,
      lineHeight: 20,
    },
    invitationInfoBox: {
      borderRadius: 8,
      borderWidth: 1,
      padding: 12,
      marginBottom: 16,
    },
    invitationInfoTitle: {
      fontSize: 14,
      fontWeight: 'bold',
      marginBottom: 8,
    },
    invitationInfoRow: {
      flexDirection: 'row',
      marginBottom: 4,
    },
    invitationInfoText: {
      fontSize: 13,
      color: '#374151',
      lineHeight: 18,
    },
    shareButton: {
      backgroundColor: '#ef4444',
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      paddingVertical: 12,
      borderRadius: 8,
    },
    shareButtonText: {
      color: '#fff',
      fontSize: 14,
      fontWeight: '600',
    },
    valuePropositionOuter: {
      backgroundColor: '#A7F3D0',
      borderRadius: 16,
      padding: 16,
    },
    valueRow: {
      flexDirection: 'row',
      alignItems: 'center',
      marginBottom: 8,
    },
    valueIcon: {
      marginRight: 8,
    },
    valueTitle: {
      fontSize: 16,
      fontWeight: 'bold',
      color: colors.dark,
    },
    valueDescription: {
      fontSize: 14,
      color: '#374151',
      marginBottom: 12,
      lineHeight: 20,
    },
    valueHighlightBox: {
      backgroundColor: '#fff',
      borderRadius: 12,
      padding: 12,
      borderWidth: 1,
      borderColor: '#d1fae5',
    },
    valueHighlightText: {
      fontSize: 13,
      color: '#065f46',
      lineHeight: 20,
    },
    bold: {
      fontWeight: 'bold',
    },
    actionsContainer: {
      gap: 12,
    },
    primaryAction: {
      backgroundColor: colors.primary,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      paddingVertical: 14,
      borderRadius: 12,
    },
    primaryActionText: {
      color: '#fff',
      fontSize: 16,
      fontWeight: '600',
    },
    actionIcon: {
      marginRight: 8,
    },
    secondaryButton: {
      backgroundColor: colors.neutral,
    },
    secondaryButtonText: {
      color: colors.dark,
    },
    buttonRow: {
      flexDirection: 'row',
      marginTop: 24,
      marginHorizontal: -6,
    },
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
    blockchainButtonText: {
      fontSize: 14,
      color: '#374151',
      marginLeft: 8,
    },
    blockchainIcon: {
      marginRight: 4,
    },
    // Missing participant styles
    participantInfo: {
      flexDirection: 'row',
      alignItems: 'center',
      marginBottom: 16,
    },
    avatarContainer: {
      width: 48,
      height: 48,
      borderRadius: 24,
      backgroundColor: colors.secondary,
      alignItems: 'center',
      justifyContent: 'center',
      marginRight: 12,
    },
    avatarText: {
      fontSize: 20,
      fontWeight: 'bold',
      color: '#fff',
    },
    participantDetails: {
      flex: 1,
    },
    participantName: {
      fontSize: 16,
      fontWeight: '600',
      color: colors.dark,
      marginBottom: 4,
    },
    transactionTitle: {
      fontSize: 16,
      color: '#fff',
      textAlign: 'center',
      marginTop: 8,
    },
    negativeAmount: {
      color: '#fee2e2',
    },
    blockchainDetails: {
      marginTop: 16,
    },
    blockchainTitle: {
      fontSize: 14,
      fontWeight: '600',
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
    // Additional styles from duplicate block
    headerTop: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: 24,
    },
    headerButton: {
      padding: 8,
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
    cardContent: {
      gap: 16,
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
    participantDetails: {
      flex: 1,
    },
    participantName: {
      fontSize: 16,
      fontWeight: 'bold',
      color: colors.dark,
      marginBottom: 4,
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
  })

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
    isParsed: typeof rawTransactionData === 'string' && typeof transactionData === 'object',
    transactionData: transactionData,
    recipient_phone: transactionData?.recipient_phone,
    recipient_address: transactionData?.recipient_address,
    toAddress: transactionData?.toAddress,
    is_invited_friend: transactionData?.is_invited_friend,
    is_invited_friend_type: typeof transactionData?.is_invited_friend,
    is_external_address: transactionData?.is_external_address,
    is_external_address_type: typeof transactionData?.is_external_address,
    allKeys: transactionData ? Object.keys(transactionData) : []
  });
  
  console.log('[TransactionDetailScreen] Fetch check:', {
    needsFetch,
    transactionId,
    hasAmount: !!transactionData?.amount,
    dataKeys: transactionData ? Object.keys(transactionData) : []
  });
  
  // Check if this is a USDC transaction first
  const isUSDCTransaction = transactionType === 'deposit' || transactionType === 'withdrawal' || transactionType === 'conversion' ||
    (transactionData && ['deposit', 'withdrawal', 'conversion'].includes(transactionData.type || transactionData.transaction_type));

  const { data: fetchedData, loading: fetchLoading, error: fetchError } = useQuery(
    GET_SEND_TRANSACTION_BY_ID,
    {
      variables: { id: transactionId },
      skip: !needsFetch || !transactionId || isUSDCTransaction, // Skip for USDC transactions
    }
  );

  // No secondary friend query here to avoid backend filter issues

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
    conversion: {
      type: 'conversion',
      from: 'USDC',
      to: 'cUSD',
      amount: '+100.00',
      currency: 'USDC',
      secondaryCurrency: 'cUSD',
      date: '2025-06-08',
      time: '10:15',
      status: 'completed',
      hash: '0xconv123abc456789012345678901234567890def',
      formattedTitle: 'Conversión USDC → cUSD',
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
  // We'll build txData from the most reliable source in order:
  // 1) Server-fetched details (when available)
  // 2) Normalized notification payload (camelCased + mapped fields)
  // 3) Raw notification payload (last resort)
  let txData: any = undefined;
  if (fetchedData?.sendTransaction && needsFetch) {
    const tx = fetchedData.sendTransaction;
    // Resolve direction primarily from route params; fallback to simple heuristic
    const routeTypeRaw = (route.params?.transactionType || transactionData?.transaction_type || '').toString().toLowerCase();
    const resolvedType = routeTypeRaw === 'sent' || routeTypeRaw === 'send'
      ? 'sent'
      : routeTypeRaw === 'received' ? 'received' : 'received';
    
    console.log('[TransactionDetailScreen] Transforming fetched data:', {
      tx,
      resolvedType,
      amount: tx.amount,
      tokenType: tx.tokenType,
    });
    
    txData = {
      ...(transactionData || {}),
      type: resolvedType,
      from: tx.senderDisplayName || tx.senderUser?.firstName || 'Usuario',
      fromAddress: tx.senderAddress,
      to: tx.recipientDisplayName || tx.recipientUser?.firstName || 'Usuario',
      toAddress: tx.recipientAddress,
      amount: resolvedType === 'sent' ? `-${tx.amount}` : `+${tx.amount}`,
      currency: tx.tokenType === 'CUSD' ? 'cUSD' : tx.tokenType,
      date: moment.utc(tx.createdAt).local().format('YYYY-MM-DD'),
      time: moment.utc(tx.createdAt).local().format('HH:mm'),
      status: tx.status?.toLowerCase() || 'completed',
      hash: tx.transactionHash || '',
      note: tx.memo || '',
      avatar: (resolvedType === 'sent' ? tx.recipientDisplayName : tx.senderDisplayName)?.[0] || 'U',
      isInvitedFriend: !!tx.invitationExpiresAt,
      invitationExpiresAt: tx.invitationExpiresAt,
      invitationClaimed: !!(tx.recipientUser && tx.recipientUser.id),
      transaction_type: 'send',
      // Add phone numbers from fetched data
      sender_phone: tx.senderUser?.phoneCountry && tx.senderUser?.phoneNumber ? 
        `${tx.senderUser.phoneCountry}${tx.senderUser.phoneNumber}` : tx.senderPhone,
      recipient_phone: tx.recipientUser?.phoneCountry && tx.recipientUser?.phoneNumber ? 
        `${tx.recipientUser.phoneCountry}${tx.recipientUser.phoneNumber}` : tx.recipientPhone,
      senderPhone: tx.senderUser?.phoneCountry && tx.senderUser?.phoneNumber ? 
        `${tx.senderUser.phoneCountry}${tx.senderUser.phoneNumber}` : tx.senderPhone,
      recipientPhone: tx.recipientUser?.phoneCountry && tx.recipientUser?.phoneNumber ? 
        `${tx.recipientUser.phoneCountry}${tx.recipientUser.phoneNumber}` : tx.recipientPhone,
    };
    // If opened via an invite-received notification, force receiver perspective
    if (transactionData?.notification_type === 'INVITE_RECEIVED') {
      txData.type = 'received';
    }
  }
  
  // If transactionData exists and has content, normalize it
  let normalizedTransactionData = transactionData;
  if (transactionData && Object.keys(transactionData).length > 1) {
    // Handle USDC conversion transactions
    let type = transactionData.transaction_type || transactionData.transactionType || transactionData.type;
    
    // If it has conversion_type, it's a conversion transaction
    if (transactionData.conversion_type) {
      type = 'conversion';
    }
    
    // Normalize field names from notification data (snake_case to camelCase)
    normalizedTransactionData = {
      ...transactionData,
      // Map transaction_type to type for consistency
      type: type,
      createdAt: transactionData.created_at || transactionData.createdAt || transactionData.timestamp,
      transactionType: transactionData.transaction_type || transactionData.transactionType,
      tokenType: transactionData.token_type || transactionData.tokenType || transactionData.currency,
      transactionId: transactionData.transaction_id || transactionData.transactionId || transactionData.id,
      recipientName: transactionData.recipient_name || transactionData.recipientName,
      recipientPhone: transactionData.recipient_phone || transactionData.recipientPhone,
      recipientAddress: transactionData.recipient_address || transactionData.recipientAddress,
      is_external_address: transactionData.is_external_address,
      is_invited_friend: transactionData.is_invited_friend,
      isInvitedFriend: transactionData.is_invited_friend || transactionData.isInvitedFriend,
      invitationClaimed: (transactionData as any).invitationClaimed || (transactionData as any).invitation_claimed,
      invitationReverted: (transactionData as any).invitationReverted || (transactionData as any).invitation_reverted,
      invitationExpiresAt: (transactionData as any).invitationExpiresAt || (transactionData as any).invitation_expires_at,
      recipient_phone: transactionData.recipient_phone || transactionData.recipientPhone,
      recipient_address: transactionData.recipient_address || transactionData.recipientAddress,
      senderName: transactionData.sender_name || transactionData.senderName,
      senderPhone: transactionData.sender_phone || transactionData.senderPhone,
      senderAddress: transactionData.sender_address || transactionData.senderAddress,
      transactionHash: transactionData.transaction_hash || transactionData.transactionHash,
      hash: transactionData.transaction_hash || transactionData.transactionHash || transactionData.hash || transactionData.txid,
      is_invited_friend: transactionData.is_invited_friend,
      is_external_address: transactionData.is_external_address,
      // Override 'to' and 'from' if they contain truncated addresses
      to: (transactionData.to && transactionData.to.includes('...') && transactionData.to.startsWith('0x')) 
        ? '' : transactionData.to,
      from: (transactionData.from && transactionData.from.includes('...') && transactionData.from.startsWith('0x')) 
        ? '' : transactionData.from,
      // For conversions
      currency: transactionData.from_token || transactionData.token_type || transactionData.currency || 'USDC',
      secondaryCurrency: transactionData.to_token || 'cUSD',
      // For conversions: cUSD -> USDC should be negative (money out), USDC -> cUSD should be positive (money in)
      // For withdrawals: always negative (money out)
      amount: transactionData.conversion_type === 'cusd_to_usdc' 
        ? `-${transactionData.from_amount || transactionData.amount || '0'}`
        : transactionData.conversion_type === 'usdc_to_cusd'
        ? `+${transactionData.to_amount || transactionData.amount || '0'}`
        : type === 'withdrawal'
        ? `-${transactionData.amount || '0'}`.replace('--', '-') // Ensure single negative sign
        : transactionData.amount || transactionData.from_amount || transactionData.to_amount,
      status: transactionData.status || 'completed',
      // Format date if timestamp is available
      date: transactionData.timestamp ? moment.utc(transactionData.timestamp).local().format('YYYY-MM-DD') : transactionData.date,
      time: transactionData.timestamp ? moment.utc(transactionData.timestamp).local().format('HH:mm') : transactionData.time,
      // Format conversion title
      formattedTitle: transactionData.conversion_type === 'usdc_to_cusd' ? 'Conversión USDC → cUSD' : 
                      transactionData.conversion_type === 'cusd_to_usdc' ? 'Conversión cUSD → USDC' : null,
      // For withdrawals
      destinationAddress: transactionData.destination_address || transactionData.destinationAddress,
      toAddress: transactionData.destination_address || transactionData.destinationAddress || transactionData.toAddress,
    };

    // If opened via an invite-received notification, force receiver perspective
    if (transactionData?.notification_type === 'INVITE_RECEIVED') {
      normalizedTransactionData.type = 'received';
    }

    // Normalize currency symbol casing and cUSD mapping
    if (typeof normalizedTransactionData.currency === 'string') {
      const cur = (normalizedTransactionData.currency as string).toUpperCase();
      if (cur === 'CUSD') normalizedTransactionData.currency = 'cUSD';
    }

    // Fallback timestamp if missing
    if (!normalizedTransactionData.createdAt && !normalizedTransactionData.timestamp) {
      const now = Date.now();
      (normalizedTransactionData as any).timestamp = now;
      (normalizedTransactionData as any).date = moment(now).format('YYYY-MM-DD');
      (normalizedTransactionData as any).time = moment(now).format('HH:mm');
    }
    
    // Provide from/to fallback names from sender/recipient_name
    if (!normalizedTransactionData.from && normalizedTransactionData.senderName) {
      (normalizedTransactionData as any).from = normalizedTransactionData.senderName;
    }
    if (!normalizedTransactionData.to && normalizedTransactionData.recipientName) {
      (normalizedTransactionData as any).to = normalizedTransactionData.recipientName;
    }
    
    // Provide addresses mapping if missing
    if (!normalizedTransactionData.fromAddress && normalizedTransactionData.senderAddress) {
      (normalizedTransactionData as any).fromAddress = normalizedTransactionData.senderAddress;
    }
    if (!normalizedTransactionData.toAddress && normalizedTransactionData.recipientAddress) {
      (normalizedTransactionData as any).toAddress = normalizedTransactionData.recipientAddress;
    }
  }
  
  // If we couldn't build txData from server, prefer the normalized payload
  if (!txData) {
    if (normalizedTransactionData && Object.keys(normalizedTransactionData).length > 1) {
      txData = normalizedTransactionData;
    } else if (transactionData) {
      txData = transactionData;
    }
  }
  
  // Keep txData as-is; invitationClaimed inferred from recipientUser presence when fetched

  // Prefer server-fetched data when available; otherwise fall back to normalized notification payload
  const currentTx = txData || transactions[transactionType];
  
  console.log('[TransactionDetailScreen] currentTx selection:', {
    hasTransactionData: !!(transactionData && Object.keys(transactionData).length > 1),
    hasTxData: !!txData,
    usingFallback: !!(transactions[transactionType])
  });
  console.log('[TransactionDetailScreen] currentTx:', currentTx);
  console.log('[TransactionDetailScreen] currentTx datetime fields:', {
    date: currentTx?.date,
    time: currentTx?.time,
    createdAt: currentTx?.createdAt,
    created_at: currentTx?.created_at,
    timestamp: currentTx?.timestamp,
  });
  
  // Debug timezone conversion
  if (currentTx?.createdAt) {
    const deviceOffset = new Date().getTimezoneOffset();
    console.log('[TransactionDetailScreen] Timezone debug:', {
      rawCreatedAt: currentTx.createdAt,
      parsedUTC: moment.utc(currentTx.createdAt).format('YYYY-MM-DD HH:mm:ss'),
      convertedLocal: moment.utc(currentTx.createdAt).local().format('YYYY-MM-DD HH:mm:ss'),
      deviceTimezoneOffset: `${deviceOffset} minutes (${-deviceOffset/60} hours)`,
      currentLocalTime: moment().format('YYYY-MM-DD HH:mm:ss'),
      momentLocalTime: moment.utc(currentTx.createdAt).local().format(),
      isUTC: moment.utc(currentTx.createdAt).isUTC(),
      isLocal: moment.utc(currentTx.createdAt).local().isLocal(),
    });
  }
  console.log('[TransactionDetailScreen] currentTx details:', {
    amount: currentTx?.amount,
    currency: currentTx?.currency,
    status: currentTx?.status,
    type: currentTx?.type,
    from: currentTx?.from,
    to: currentTx?.to,
    sender_phone: currentTx?.sender_phone,
    recipient_phone: currentTx?.recipient_phone,
    keys: currentTx ? Object.keys(currentTx) : []
  });
  
  // Get contact names for display - check all possible phone fields
  // MUST be called before any early returns to follow React hooks rules
  const senderPhone = currentTx?.sender_phone || currentTx?.senderPhone || currentTx?.fromPhone || transactionData?.sender_phone;
  const recipientPhone = currentTx?.recipient_phone || currentTx?.recipientPhone || currentTx?.toPhone || transactionData?.recipient_phone;
  
  console.log('[TransactionDetailScreen] Contact lookup:', {
    senderPhone,
    recipientPhone,
    fallbackSenderName: currentTx?.from || currentTx?.senderName,
    fallbackRecipientName: currentTx?.to || currentTx?.recipientName,
  });
  
  // Don't use truncated addresses as fallback names
  const senderFallbackName = currentTx?.from || currentTx?.senderName || currentTx?.sender_name;
  const recipientFallbackName = (() => {
    const name = currentTx?.to || currentTx?.recipientName || currentTx?.recipient_name;
    // If it's a truncated address, don't use it as a name
    if (name && name.includes('...') && name.startsWith('0x')) {
      return '';
    }
    return name;
  })();
  
  const senderContactInfo = useContactNameSync(senderPhone, senderFallbackName);
  // Only use contact sync if we have a phone number or a valid name
  const shouldUseContactSync = recipientPhone || (recipientFallbackName && !recipientFallbackName.startsWith('0x'));
  console.log('[TransactionDetailScreen] Contact sync decision:', {
    recipientPhone,
    recipientFallbackName,
    shouldUseContactSync,
    is_external_address: currentTx?.is_external_address,
    is_invited_friend: currentTx?.is_invited_friend,
    hasRecipientUser: !!currentTx?.recipient_user,
    toField: currentTx?.to,
    recipientAddress: currentTx?.recipient_address
  });
  
  const recipientContactInfo = shouldUseContactSync
    ? useContactNameSync(recipientPhone, recipientFallbackName)
    : { displayName: '', isFromContacts: false };
  
  console.log('[TransactionDetailScreen] Contact info results:', {
    senderContactInfo,
    recipientContactInfo,
    recipientFallbackName,
    recipientPhone,
    displayToName: recipientContactInfo.displayName
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
  
  const isInvitedFriend = currentTx?.isInvitedFriend || currentTx?.is_invited_friend || false;
  const isExternalAddress = currentTx?.is_external_address || false;
  const invitationClaimed = currentTx?.invitationClaimed || currentTx?.invitation_claimed || false;
  const invitationReverted = currentTx?.invitationReverted || currentTx?.invitation_reverted || false;
  const invitationExpiresAt = currentTx?.invitationExpiresAt || currentTx?.invitation_expires_at;
  const isInvitationExpired = invitationExpiresAt ? moment(invitationExpiresAt).isBefore(moment()) : false;
  const showInvitationWarning = isInvitedFriend 
    && !isExternalAddress 
    && (currentTx?.type === 'send' || currentTx?.type === 'sent') 
    && !invitationClaimed 
    && !invitationReverted 
    && !isInvitationExpired;
  
  // Debug invitation status
  console.log('[TransactionDetailScreen] Invitation status:', {
    isInvitedFriend,
    isExternalAddress,
    invitationClaimed,
    invitationReverted,
    invitationExpiresAt,
    isInvitationExpired,
    isInvitedFriend_camelCase: currentTx?.isInvitedFriend,
    is_invited_friend_snake_case: currentTx?.is_invited_friend,
    is_external_address: currentTx?.is_external_address,
    type: currentTx?.type,
    recipient_phone: currentTx?.recipient_phone,
    willShowInvitationCard: showInvitationWarning,
  });
  
  // Debug phone numbers
  console.log('[TransactionDetailScreen] Phone number data:', {
    sender_phone: currentTx?.sender_phone,
    senderPhone: currentTx?.senderPhone,
    recipient_phone: currentTx?.recipient_phone,
    recipientPhone: currentTx?.recipientPhone,
    fromPhone: currentTx?.fromPhone,
    toPhone: currentTx?.toPhone,
    // Also check raw transactionData
    raw_sender_phone: transactionData?.sender_phone,
    raw_recipient_phone: transactionData?.recipient_phone,
    all_keys: currentTx ? Object.keys(currentTx) : [],
  });
  
  // Use contact names if available
  const displayFromName = senderContactInfo.displayName;
  let displayToName = recipientContactInfo.displayName;
  
  console.log('[TransactionDetailScreen] Display names:', {
    displayFromName,
    displayToName,
    recipientContactInfo
  });

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
    console.log('[TransactionDetailScreen] getTransactionTitle called with:', {
      type: tx.type,
      typeEquality: tx.type === 'sent',
      typeofType: typeof tx.type,
      displayToName
    });
    
    switch(tx.type) {
      case 'received':
        return `Recibido de ${displayFromName}`;
      // Both 'send' and 'sent' are handled for compatibility
      // Backend now uses 'send' for consistency with other types (payment, deposit, etc.)
      // but 'sent' might exist in older data
      case 'send':
      case 'sent':
        console.log('[TransactionDetailScreen] Title logic for sent:', {
          displayToName,
          hasDisplayToName: !!displayToName,
          is_invited_friend: tx.is_invited_friend,
          recipient_phone: tx.recipient_phone,
          is_external_address: tx.is_external_address,
          toAddress: tx.toAddress,
          recipient_address: tx.recipient_address
        });
        
        if (displayToName) {
          return `Enviado a ${displayToName}`;
        } else if (tx.is_invited_friend && tx.recipient_phone) {
          return 'Enviado a amigo invitado';
        } else if (tx.is_external_address || (tx.toAddress && !tx.recipient_phone) || (tx.recipient_address && !tx.recipient_phone)) {
          return 'Enviado a dirección externa';
        }
        return 'Enviado';
      case 'exchange':
        return `Intercambio ${tx.from} → ${tx.to}`;
      case 'conversion':
        return tx.formattedTitle || `Conversión ${tx.currency || 'USDC'} → ${tx.secondaryCurrency || 'cUSD'}`;
      case 'payment':
        // Check if it's a received payment (positive amount) or sent payment (negative amount)
        return tx.amount.startsWith('+') 
          ? `Pago recibido de ${displayFromName}`
          : `Pago a ${displayToName}`;
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
              (currentTx.type === 'send' || currentTx.type === 'sent' || currentTx.type === 'payment' || currentTx.type === 'withdrawal' || 
               (currentTx.type === 'conversion' && currentTx.amount?.startsWith('-'))) && styles.negativeAmount
            ]}>
              {formatAmountWithSign(currentTx.amount)} {currentTx.currency || 'cUSD'}
            </Text>
            
            <Text style={styles.transactionTitle}>
              {(() => {
                const title = getTransactionTitle(currentTx);
                console.log('[TransactionDetailScreen] TITLE DISPLAY:', {
                  title,
                  type: currentTx.type,
                  displayToName,
                  to: currentTx.to,
                  is_external_address: currentTx.is_external_address
                });
                return title;
              })()}
            </Text>
            
            <View style={[styles.statusBadge, { backgroundColor: statusColors.bg }]}>
              {(currentTx.status?.toLowerCase() === 'completed' || currentTx.status?.toLowerCase() === 'confirmed') && (
                <Icon name="check-circle" size={16} color={statusColors.text} style={styles.statusIcon} />
              )}
              {(currentTx.status?.toLowerCase() === 'pending' || currentTx.status?.toLowerCase() === 'submitted') && (
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
                 (currentTx.status?.toLowerCase() === 'pending' || currentTx.status?.toLowerCase() === 'submitted') ? 'Pendiente' :
                 currentTx.status?.toLowerCase() === 'processing' ? 'Procesando' :
                 currentTx.status?.toLowerCase() === 'failed' ? 'Fallido' : 'Desconocido'}
              </Text>
            </View>
            
            {showInvitationWarning && (
              <View style={styles.invitationNotice}>
                <Icon name="alert-triangle" size={16} color="#fff" style={{ marginRight: 6 }} />
                <Text style={styles.invitationText}>Tu amigo tiene 7 días para reclamar</Text>
              </View>
            )}
            {!showInvitationWarning && invitationClaimed && (currentTx.type === 'send' || currentTx.type === 'sent') && (
              <View style={[styles.invitationNotice, { backgroundColor: '#10b981' }]}> 
                <Icon name="check-circle" size={16} color="#fff" style={{ marginRight: 6 }} />
                <Text style={styles.invitationText}>Invitación reclamada</Text>
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
                    <Text style={styles.participantName}>{displayFromName}</Text>
                    <View style={styles.addressContainer}>
                      <Text style={styles.addressText}>
                        {senderPhone ? formatPhoneNumber(senderPhone) : currentTx.fromAddress}
                      </Text>
                      <TouchableOpacity 
                        onPress={() => handleCopy(
                          senderPhone ? formatPhoneNumber(senderPhone) : currentTx.fromAddress, 
                          'from'
                        )}
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

              {(currentTx.type === 'send' || currentTx.type === 'sent') && (
                <View style={styles.participantInfo}>
                  <View style={styles.avatarContainer}>
                    <Text style={styles.avatarText}>
                      {currentTx.avatar || (currentTx.is_external_address ? '0' : 'U')}
                    </Text>
                  </View>
                  <View style={styles.participantDetails}>
                    <Text style={styles.participantName}>
                      {(() => {
                        console.log('[TransactionDetailScreen] SENT NAME LOGIC - Full data:', {
                          displayToName,
                          currentTx_keys: Object.keys(currentTx),
                          to: currentTx.to,
                          recipient_name: currentTx.recipient_name,
                          is_external_address: currentTx.is_external_address,
                          is_invited_friend: currentTx.is_invited_friend,
                          recipient_phone: currentTx.recipient_phone,
                          toAddress: currentTx.toAddress,
                          recipient_address: currentTx.recipient_address,
                          recipientAddress: currentTx.recipientAddress,
                          recipientPhone: currentTx.recipientPhone
                        });
                        return null;
                      })()}
                      {(() => {
                        // If we have a display name from contacts or transaction data
                        if (displayToName) return displayToName;
                        
                        // For invited friends (non-Confío users)
                        if (currentTx.is_invited_friend && currentTx.recipient_phone) {
                          return `Invitación enviada${currentTx.recipient_display_name ? ` a ${currentTx.recipient_display_name}` : ''}`;
                        }
                        
                        // For external addresses
                        if (currentTx.is_external_address || (currentTx.toAddress && !currentTx.recipient_phone && !displayToName)) {
                          return 'Dirección externa';
                        }
                        
                        // Fallback - but don't use truncated addresses
                        const fallbackName = currentTx.to || currentTx.recipient_name || 'Desconocido';
                        // If the fallback looks like a truncated address, don't use it
                        if (fallbackName.includes('...') && fallbackName.startsWith('0x')) {
                          return 'Dirección externa';
                        }
                        return fallbackName || `DEBUG FALLBACK ${new Date().getTime()}`;
                      })()}
                    </Text>
                    <View style={styles.addressContainer}>
                      <Text style={styles.addressText}>
                        {(() => {
                          // Direct logging
                          console.log('[TransactionDetailScreen] ADDRESS SECTION:', JSON.stringify({
                            recipientPhone,
                            recipient_phone: currentTx.recipient_phone,
                            toAddress: currentTx.toAddress,
                            recipient_address: currentTx.recipient_address,
                            is_invited_friend: currentTx.is_invited_friend,
                            is_external_address: currentTx.is_external_address,
                          }));
                          
                          // For external addresses - show the full address
                          if (currentTx.is_external_address || (currentTx.toAddress && !currentTx.recipient_phone)) {
                            const fullAddress = currentTx.toAddress || currentTx.recipient_address;
                            if (fullAddress && fullAddress.length > 40) {
                              return `${fullAddress.substring(0, 10)}...${fullAddress.substring(fullAddress.length - 6)}`;
                            }
                            return fullAddress || 'Sin dirección';
                          }
                          
                          // For invited friends - show phone
                          if (currentTx.is_invited_friend && currentTx.recipient_phone) {
                            const phone = recipientPhone || currentTx.recipient_phone;
                            return phone ? formatPhoneNumber(phone) : 'Sin número';
                          }
                          
                          return 'DEBUG: No data';
                        })()}
                      </Text>
                      <TouchableOpacity 
                        onPress={() => handleCopy(
                          recipientPhone || currentTx.recipient_phone 
                            ? formatPhoneNumber(recipientPhone || currentTx.recipient_phone) 
                            : (currentTx.toAddress || currentTx.recipient_address || ''), 
                          'to'
                        )}
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
                      {currentTx.amount?.startsWith('+') ? displayFromName : displayToName}
                    </Text>
                    <View style={styles.addressContainer}>
                      <Text style={styles.addressText}>
                        {/* Hide phone/address for payment transactions to preserve privacy */}
                        {''}
                      </Text>
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
                    {(() => {
                      // Prioritize createdAt if it exists (from notifications)
                      if (currentTx.createdAt) {
                        if (typeof currentTx.createdAt === 'string') {
                          const isoLike = currentTx.createdAt.includes('T');
                          const date = isoLike ? new Date(currentTx.createdAt) : moment(currentTx.createdAt).toDate();
                          return `${moment(date).format('DD/MM/YYYY')} • ${moment(date).format('HH:mm')}`;
                        } else if (typeof currentTx.createdAt === 'number' || currentTx.createdAt instanceof Date) {
                          const date = new Date(currentTx.createdAt as any);
                          return `${moment(date).format('DD/MM/YYYY')} • ${moment(date).format('HH:mm')}`;
                        }
                      } else if (currentTx.date && currentTx.time) {
                        // Already formatted date and time from AccountDetailScreen
                        return `${moment(currentTx.date, 'YYYY-MM-DD').format('DD/MM/YYYY')} • ${currentTx.time}`;
                      }
                      return 'Fecha no disponible';
                    })()}
                  </Text>
                  <Text style={styles.infoSubtitle}>
                    {(() => {
                      // If we have a createdAt timestamp
                      if (currentTx.createdAt) {
                        if (typeof currentTx.createdAt === 'string') {
                          const isoLike = currentTx.createdAt.includes('T');
                          const date = isoLike ? new Date(currentTx.createdAt) : moment(currentTx.createdAt).toDate();
                          return moment(date).locale('es').fromNow();
                        } else if (typeof currentTx.createdAt === 'number' || currentTx.createdAt instanceof Date) {
                          return moment(new Date(currentTx.createdAt as any)).locale('es').fromNow();
                        }
                      }
                      // If we have a generic timestamp field
                      else if (currentTx.timestamp) {
                        if (typeof currentTx.timestamp === 'string') {
                          if (currentTx.timestamp.includes('T')) {
                            const date = new Date(currentTx.timestamp);
                            return moment(date).locale('es').fromNow();
                          }
                          return moment(currentTx.timestamp).locale('es').fromNow();
                        } else if (typeof currentTx.timestamp === 'number' || currentTx.timestamp instanceof Date) {
                          return moment(new Date(currentTx.timestamp as any)).locale('es').fromNow();
                        }
                      }
                      // If we only have date (already formatted), combine with time if available
                      else if (currentTx.date) {
                        const dateTime = currentTx.time 
                          ? moment(`${currentTx.date} ${currentTx.time}`, 'YYYY-MM-DD HH:mm')
                          : moment(currentTx.date, 'YYYY-MM-DD');
                        return dateTime.locale('es').fromNow();
                      }
                      return '';
                    })()}
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
                    {formatAmount(currentTx.amount)} {currentTx.currency || 'cUSD'}
                  </Text>
                </View>
                
                <View style={styles.feeRow}>
                  <Text style={styles.feeLabel}>Comisión de red</Text>
                  <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                    <Text style={styles.feeValueFree}>Gratis</Text>
                    <Text style={styles.feeValueNote}>• Cubierto por Confío</Text>
                  </View>
                </View>

                {currentTx.type === 'payment' && (() => {
                  const fee = computeConfioFee(currentTx.amount);
                  return fee > 0 ? (
                    <View style={styles.feeRow}>
                      <Text style={styles.feeLabel}>Comisión Confío (0.9%)</Text>
                      <Text style={styles.feeAmount}>- {fee.toFixed(2)} {currentTx.currency || 'cUSD'}</Text>
                    </View>
                  ) : null;
                })()}
                
                {(currentTx.type === 'send' || currentTx.type === 'sent' || currentTx.type === 'payment') && (
                  <>
                    <View style={styles.divider} />
                    <View style={styles.feeRow}>
                      <Text style={styles.totalLabel}>Total debitado</Text>
                      <Text style={styles.totalAmount}>
                        {(() => {
                          const raw = currentTx.amount;
                          const sign = typeof raw === 'string' && raw.startsWith('-') ? '-' : (typeof raw === 'string' && raw.startsWith('+') ? '+' : '');
                          const grossAbs = typeof raw === 'string' ? parseFloat(raw.replace(/[+-]/g, '')) : (Number(raw) || 0);
                          const fee = computeConfioFee(raw);
                          const netAbs = Math.max(0, grossAbs - fee);
                          return `${sign}${netAbs.toFixed(2)}`;
                        })()} {currentTx.currency || 'cUSD'}
                      </Text>
                    </View>
                  </>
                )}
              </View>

              {/* Transaction ID */}
              <View style={styles.summaryRow}>
                <Text style={styles.summaryLabel}>ID de Operación</Text>
                <Text style={styles.summaryValue}>
                  #{currentTx.hash?.slice(-8).toUpperCase() || 
                    currentTx.transactionId?.slice(-8).toUpperCase() || 
                    currentTx.transaction_id?.slice(-8).toUpperCase() || 
                    'N/A'}
                </Text>
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
          {showInvitationWarning && (
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
              
              <TouchableOpacity 
                style={styles.shareButton} 
                onPress={async () => {
                  try {
                    console.log('[WhatsApp Share] Starting share process...');
                    const phoneRaw = recipientPhone || currentTx.recipient_phone;
                    const cleanPhone = phoneRaw ? String(phoneRaw).replace(/[^\d]/g, '') : '';
                    const amount = formatAmount(currentTx.amount);
                    const currency = currentTx.currency || 'cUSD';
                    const message = `¡Hola! Te envié ${amount} ${currency} por Confío. 🎉\n\nTienes 7 días para reclamarlo. Descarga la app y crea tu cuenta:\n\n📲 ${SHARE_LINKS.campaigns.beta}\n\n¡Es gratis y en segundos recibes tu dinero!`;
                    const encodedMessage = encodeURIComponent(message);

                    if (Platform.OS === 'android') {
                      // Android: api.whatsapp.com tends to preserve prefilled text more reliably
                      const apiUrl = cleanPhone
                        ? `https://api.whatsapp.com/send?phone=${cleanPhone}&text=${encodedMessage}`
                        : `https://api.whatsapp.com/send?text=${encodedMessage}`;
                      try {
                        await Linking.openURL(apiUrl);
                        return;
                      } catch (e) {
                        console.log('[WhatsApp Share][Android] API URL failed, trying scheme...', e);
                      }

                      // Try whatsapp:// scheme
                      const schemeUrl = cleanPhone
                        ? `whatsapp://send?phone=${cleanPhone}&text=${encodedMessage}`
                        : `whatsapp://send?text=${encodedMessage}`;
                      const canOpenScheme = await Linking.canOpenURL(schemeUrl);
                      if (canOpenScheme) {
                        await Linking.openURL(schemeUrl);
                        return;
                      }

                      // Try Intent (some devices require it)
                      const intentUrl = `intent://send?text=${encodedMessage}#Intent;scheme=whatsapp;package=com.whatsapp;end`;
                      try {
                        await Linking.openURL(intentUrl);
                        return;
                      } catch (e) {
                        console.log('[WhatsApp Share][Android] Intent also failed, trying wa.me...', e);
                      }

                      // Try wa.me
                      const webUrl = cleanPhone
                        ? `https://wa.me/${cleanPhone}?text=${encodedMessage}`
                        : `https://wa.me/?text=${encodedMessage}`;
                      const canOpenWeb = await Linking.canOpenURL(webUrl);
                      if (canOpenWeb) {
                        await Linking.openURL(webUrl);
                        return;
                      }

                      // Last resort: Play Store or share sheet
                      try {
                        await Linking.openURL('market://details?id=com.whatsapp');
                        return;
                      } catch (_) {}
                      await Share.share({ message });
                      return;
                    } else {
                      // iOS path: scheme first
                      const schemeUrl = cleanPhone
                        ? `whatsapp://send?phone=${cleanPhone}&text=${encodedMessage}`
                        : `whatsapp://send?text=${encodedMessage}`;
                      const canOpen = await Linking.canOpenURL(schemeUrl);
                      if (canOpen) {
                        await Linking.openURL(schemeUrl);
                        return;
                      }
                      // Web fallback
                      const webUrl = cleanPhone
                        ? `https://wa.me/${cleanPhone}?text=${encodedMessage}`
                        : `https://wa.me/?text=${encodedMessage}`;
                      const canOpenWeb = await Linking.canOpenURL(webUrl);
                      if (canOpenWeb) {
                        await Linking.openURL(webUrl);
                        return;
                      }
                      await Share.share({ message });
                    }
                  } catch (error) {
                    console.error('[WhatsApp Share] Error:', error);
                    try {
                      await Share.share({ message: `Te envié dinero por Confío. ${SHARE_LINKS.campaigns.beta}` });
                    } catch (_) {}
                    Alert.alert('Error', 'No se pudo abrir WhatsApp.');
                  }
                }}
              >
                <WhatsAppLogo width={20} height={20} style={{ marginRight: 8 }} />
                <Text style={styles.shareButtonText}>Compartir invitación por WhatsApp</Text>
              </TouchableOpacity>
            </View>
          )}

          {/* Confío Value Proposition */}
          {(currentTx.type === 'received' || currentTx.type === 'send' || currentTx.type === 'sent') && (
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
              {(currentTx.type === 'received' || currentTx.type === 'send' || currentTx.type === 'sent') && (
                <TouchableOpacity 
                  style={styles.primaryAction}
                  onPress={() => {
                    // Navigate to SendToFriend screen
                    const friendName = currentTx.type === 'received' ? displayFromName : displayToName;
                    const friendPhone = currentTx.type === 'received' ? senderPhone : recipientPhone;
                    
                    // Debug logging to understand the data
                    console.log('[TransactionDetail] Navigation data:', {
                      transactionType: currentTx.type,
                      friendName,
                      friendPhone,
                      senderPhone,
                      recipientPhone,
                      isInvitedFriend: currentTx.isInvitedFriend || currentTx.is_invited_friend
                    });
                    
                    // For navigation, we need to determine if this is a Confío user
                    // If it's an invited friend (non-Confío user), we shouldn't navigate
                    // Note: isInvitedFriend means they are NOT on Confío (invitation transaction)
                    if (currentTx.isInvitedFriend || currentTx.is_invited_friend) {
                      // This is a non-Confío friend, navigate differently
                      Alert.alert(
                        'Usuario no está en Confío',
                        'Este amigo aún no se ha unido a Confío. Debes esperar a que se registre para poder enviarle dinero nuevamente.',
                        [{ text: 'OK' }]
                      );
                    } else {
                      // This is a Confío user - we just need their phone number
                      // The server will look up their current active Algorand address
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
                    {currentTx.type === 'received' ? `Enviar a ${displayFromName}` : `Enviar de nuevo a ${displayToName}`}
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
