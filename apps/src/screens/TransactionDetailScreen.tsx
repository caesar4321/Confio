import React, { useState, useEffect, useMemo } from 'react';
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
  ActivityIndicator,
  Share,
} from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { MainStackParamList } from '../types/navigation';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import USDCLogo from '../assets/png/USDC.png';
import cUSDLogo from '../assets/png/cUSD.png';
import WhatsAppLogo from '../assets/svg/WhatsApp.svg';
import moment from 'moment';
import 'moment/locale/es';
import { useQuery } from '@apollo/client';
import { contactService } from '../services/contactService';
import { GET_SEND_TRANSACTION_BY_ID, GET_PAYMENT_TRANSACTION_BY_ID, CHECK_USERS_BY_PHONES } from '../apollo/queries';
import { useContactNameSync } from '../hooks/useContactName';
import { getPreferredDisplayName, getPreferredSecondaryLine } from '../utils/contactDisplay';
import { SHARE_LINKS } from '../config/shareLinks';
import { useAuth } from '../contexts/AuthContext';
import { getSupportCopy } from '../utils/supportMessaging';
import { colors } from '../config/theme';
import { SkeletonLoader, TransactionItemSkeleton } from '../components/SkeletonLoader';
import { InlineBanner } from '../components/common/InlineBanner';
import { ReceiptCard, ReceiptItem } from '../components/common/ReceiptCard';
import { StatusTierBadge } from '../components/StatusTierBadge';
import { buildInviteLink, buildSendAndInviteShareMessage } from '../utils/inviteLinks';
import { technicalFontFamily } from '../utils/fontFamily';
import { inviteSendService } from '../services/inviteSendService';

type TransactionDetailScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;
type TransactionDetailScreenRouteProp = RouteProp<MainStackParamList, 'TransactionDetail'>;

// Color palette from the original design
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

const addPositiveSign = (value: unknown): string | undefined => {
  if (value === undefined || value === null) return undefined;
  const normalized = String(value).trim();
  if (!normalized) return undefined;
  return normalized.startsWith('+') || normalized.startsWith('-') ? normalized : `+${normalized}`;
};

const addNegativeSign = (value: unknown): string | undefined => {
  if (value === undefined || value === null) return undefined;
  const normalized = String(value).trim();
  if (!normalized) return undefined;
  if (normalized.startsWith('-')) return normalized;
  if (normalized.startsWith('+')) return `-${normalized.slice(1)}`;
  return `-${normalized}`;
};

const normalizePhoneLookupKey = (value?: string | null): string => {
  if (!value) return '';
  const trimmed = value.trim();
  if (!trimmed) return '';
  const hasPlus = trimmed.startsWith('+');
  const digits = trimmed.replace(/\D/g, '');
  return hasPlus ? `+${digits}` : digits;
};

const normalizeRampDirection = (value: unknown, amount?: unknown, title?: unknown): 'on_ramp' | 'off_ramp' | '' => {
  const normalized = String(value || '').trim().toLowerCase();
  if (normalized === 'on_ramp' || normalized === 'off_ramp') return normalized;

  const amountText = String(amount || '').trim();
  if (amountText.startsWith('-')) return 'off_ramp';
  if (amountText.startsWith('+')) return 'on_ramp';

  const titleText = String(title || '').trim().toLowerCase();
  if (titleText.includes('retiro')) return 'off_ramp';
  if (titleText.includes('recarga')) return 'on_ramp';

  return '';
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
    // 0.9% fee charged to the merchant (keep high precision; display may round)
    return parseFloat((amt * 0.009).toFixed(6));
  } catch {
    return 0;
  }
};

// Resolve internalId from explicit fields only.
// Prioritizes UUIDs but falls back to other IDs if no UUID is found to avoid showing "N/A".
const resolveInternalId = (tx?: any, fallback?: any): string | undefined => {
  const candidates = [
    tx?.internalId,
    tx?.internal_id,
    fallback?.internalId,
    fallback?.internal_id,
    // Only use id as fallback, NOT transactionId (which could be blockchain hash)
    tx?.id,
    fallback?.id,
  ];

  let firstValidNonUuid: string | undefined;

  for (const candidate of candidates) {
    if (candidate === undefined || candidate === null) continue;
    const val = typeof candidate === 'string' ? candidate.trim() : String(candidate).trim();
    if (!val || val.toUpperCase() === '#PENDING') continue;

    // Require UUID-like shape: must be long and contain a letter or hyphen
    if (val.length >= 32 && /[A-Fa-f-]/.test(val)) return val;

    // Capture first valid non-UUID as fallback (e.g. legacy integer ID)
    if (!firstValidNonUuid) firstValidNonUuid = val;
  }

  return firstValidNonUuid;
};

const deriveStatusFromNotificationType = (notificationType: string | undefined): string | undefined => {
  switch ((notificationType || '').toUpperCase()) {
    case 'RAMP_FAILED':
      return 'failed';
    case 'RAMP_PENDING':
    case 'RAMP_PROCESSING':
      return 'pending';
    case 'RAMP_COMPLETED':
      return 'completed';
    case 'CONVERSION_FAILED':
    case 'USDC_DEPOSIT_FAILED':
    case 'USDC_WITHDRAWAL_FAILED':
      return 'failed';
    case 'CONVERSION_COMPLETED':
    case 'USDC_DEPOSIT_COMPLETED':
    case 'USDC_WITHDRAWAL_COMPLETED':
      return 'completed';
    case 'USDC_DEPOSIT_PENDING':
      return 'pending';
    default:
      return undefined;
  }
};

const normalizeStatusForDisplay = (status: string | undefined): string => {
  const normalized = (status || '').toString().trim().toLowerCase();
  if (!normalized) return 'pending';
  if (normalized === 'confirmed') return 'completed';
  if (normalized === 'submitted') return 'pending';
  return normalized;
};

export const TransactionDetailScreen = () => {
  const navigation = useNavigation<TransactionDetailScreenNavigationProp>();
  const route = useRoute<TransactionDetailScreenRouteProp>();
  const insets = useSafeAreaInsets();
  const [copied, setCopied] = useState('');
  const [banner, setBanner] = useState<{ message: string; variant: 'error' | 'success' } | null>(null);
  const dismissBanner = React.useCallback(() => setBanner(null), []);
  const [showBlockchainDetails, setShowBlockchainDetails] = useState(false);
  const [reclaimingInvite, setReclaimingInvite] = useState(false);
  const [reclaimedInviteTxid, setReclaimedInviteTxid] = useState('');
  // Measured hero size: explicit Svg dimensions force a gradient repaint
  // whenever the header's height changes (see AccountDetailScreen).
  const [fieldSize, setFieldSize] = useState({ width: 0, height: 0 });
  const { userProfile } = useAuth();
  const supportCopy = getSupportCopy(userProfile?.phoneCountry);
  const styles = StyleSheet.create({
    container: {
      flex: 1,
      backgroundColor: colors.primary,
    },
    errorText: {
      fontSize: 16,
      color: colors.danger,
      textAlign: 'center',
      padding: 20,
    },
    scrollView: {
      flex: 1,
    },
    header: {
      backgroundColor: colors.primary,
      overflow: 'hidden',
    },
    headerInner: {
      paddingHorizontal: 20,
      paddingBottom: 30,
    },
    headerTitle: {
      fontSize: 20,
      fontWeight: '600',
      color: colors.white,
    },
    amountText: {
      fontSize: 36,
      fontWeight: 'bold',
      color: colors.white,
      marginBottom: 4,
    },
    content: {
      flex: 1,
      backgroundColor: colors.white,
      borderTopLeftRadius: 24,
      borderTopRightRadius: 24,
      paddingTop: 24,
      paddingHorizontal: 20,
      paddingBottom: 20,
      gap: 16,
    },
    addressContainer: {
      flexDirection: 'row',
      alignItems: 'center',
    },
    addressText: {
      fontSize: 14,
      color: colors.text.secondary,
    },
    card: {
      backgroundColor: colors.white,
      borderRadius: 16,
      borderWidth: 1,
      borderColor: colors.border,
      padding: 16,
    },
    sectionLabel: {
      fontSize: 13,
      fontWeight: '600',
      color: colors.text.secondary,
      textTransform: 'uppercase',
      letterSpacing: 0.5,
      marginBottom: 10,
    },
    receiptCard: {
      backgroundColor: colors.white,
    },
    supportFootnote: {
      fontSize: 12,
      color: colors.text.secondary,
      textAlign: 'center',
      lineHeight: 18,
      paddingHorizontal: 12,
    },
    actionRowsCard: {
      backgroundColor: colors.white,
      borderRadius: 16,
      borderWidth: 1,
      borderColor: colors.border,
      paddingHorizontal: 16,
    },
    actionRow: {
      flexDirection: 'row',
      alignItems: 'center',
      paddingVertical: 14,
      gap: 12,
    },
    actionRowIcon: {
      width: 36,
      height: 36,
      borderRadius: 10,
      alignItems: 'center',
      justifyContent: 'center',
    },
    actionRowLabel: {
      flex: 1,
      fontSize: 15,
      fontWeight: '500',
      color: colors.text.primary,
    },
    rowDivider: {
      height: StyleSheet.hairlineWidth,
      backgroundColor: colors.border,
    },
    noteText: {
      fontSize: 16,
      color: '#065f46',
      fontStyle: 'italic',
      lineHeight: 22,
    },
    // Missing card styles
    statusIcon: {
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
      color: colors.white,
    },
    participantDetails: {
      flex: 1,
    },
    participantName: {
      fontSize: 16,
      fontWeight: '600',
      color: colors.dark,
    },
    participantNameRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      alignItems: 'center',
      marginBottom: 4,
    },
    participantLastWordBadgeGroup: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
    },
    participantInlineVerifiedBadge: {
      width: 16,
      height: 16,
      borderRadius: 8,
      backgroundColor: colors.accent,
      alignItems: 'center',
      justifyContent: 'center',
    },
    transactionTitle: {
      fontSize: 16,
      color: colors.white,
      textAlign: 'center',
      marginTop: 8,
      marginBottom: 12, // Restored margin to fix spacing issues
    },
    technicalRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingVertical: 8,
    },
    technicalLabel: {
      fontSize: 14,
      color: colors.text.secondary,
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
      color: colors.white,
    },
    // Pending invitation is a warning, not an error — amber pill.
    invitationNotice: {
      flexDirection: 'row',
      alignItems: 'center',
      marginTop: 12,
      backgroundColor: colors.offRampIcon,
      paddingHorizontal: 16,
      paddingVertical: 8,
      borderRadius: 20,
    },
    invitationText: {
      color: colors.white,
      fontSize: 14,
      fontWeight: '500',
    },
    invitationCard: {
      backgroundColor: colors.warning.background,
      borderColor: colors.warning.border,
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
      color: colors.secondary,
      marginLeft: 12,
    },
    invitationCardText: {
      fontSize: 16,
      color: colors.text.primary,
      marginBottom: 16,
      lineHeight: 24,
    },
    invitationInfoBox: {
      backgroundColor: colors.white,
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
      color: colors.text.secondary,
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
      color: colors.white,
      fontSize: 16,
      fontWeight: '600',
    },
    reclaimCard: {
      backgroundColor: '#f0fdf4',
      borderColor: colors.primary,
      borderWidth: 1,
    },
    reclaimButton: {
      backgroundColor: colors.primary,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      paddingVertical: 14,
      paddingHorizontal: 20,
      borderRadius: 12,
      marginTop: 16,
    },
    reclaimButtonDisabled: {
      opacity: 0.6,
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
      width: 72,
      height: 72,
      backgroundColor: colors.white,
      borderRadius: 24,
      justifyContent: 'center',
      alignItems: 'center',
      marginBottom: 16,
    },


    statusBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: 12,
      paddingVertical: 6,
      borderRadius: 20,
    },

    statusText: {
      fontSize: 14,
      fontWeight: '500',
    },
    cardContent: {
      gap: 16,
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
      color: colors.text.secondary,
    },



    noteContainer: {
      backgroundColor: colors.neutral,
      padding: 16,
      borderRadius: 12,
      marginTop: 24,
    },
    noteHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      marginBottom: 8,
    },
    noteTitle: {
      fontSize: 14,
      fontWeight: '600',
      color: colors.dark,
      marginLeft: 8,
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
      color: colors.white,
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
      backgroundColor: colors.white,
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
      borderBottomColor: colors.border,
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
      color: colors.text.primary,
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
      transactionData = null;
    }
  }

  // Fetch transaction data if we lack phoneKey-style phones (to mirror AccountDetail behavior)
  // Basic completeness for UI
  const hasCompleteData = Boolean(transactionData?.amount && transactionData?.from && transactionData?.to);
  // Phone presence by direction
  const specifiedType = (transactionType || transactionData?.transaction_type || '').toString().toLowerCase();
  const isPayroll = specifiedType === 'payroll' ||
    (transactionData?.payrollRunId && transactionData.payrollRunId !== '') ||
    (transactionData?.type === 'payroll');
  const routeTypeLower = specifiedType;
  const hasRecipientPhone = Boolean(
    (transactionData as any)?.toPhone || (transactionData as any)?.recipient_phone || (transactionData as any)?.recipientPhone
  );
  const hasSenderPhone = Boolean(
    (transactionData as any)?.fromPhone || (transactionData as any)?.sender_phone || (transactionData as any)?.senderPhone
  );
  const lacksPhonesForSend = routeTypeLower === 'sent' ? !hasRecipientPhone : (routeTypeLower === 'received' ? !hasSenderPhone : false);
  // Decide fetch: if send-type and we don't have phoneKey-style phones OR we lack a valid internalId
  const currentInternalId = transactionData?.internalId || transactionData?.internal_id;
  const hasValidInternalId = Boolean(currentInternalId) &&
    currentInternalId !== '#PENDING' &&
    currentInternalId.length >= 32 &&
    /[A-Fa-f-]/.test(currentInternalId);
  const routeInvitationExpiresAt = (transactionData as any)?.invitationExpiresAt || (transactionData as any)?.invitation_expires_at;
  const routeLooksLikeInvite = Boolean(
    (transactionData as any)?.isInvitation ||
    (transactionData as any)?.is_invitation ||
    (transactionData as any)?.isInvitedFriend ||
    (transactionData as any)?.is_invited_friend ||
    routeInvitationExpiresAt
  );
  const routeHasInvitationId = Boolean(
    (transactionData as any)?.invitationId ||
    (transactionData as any)?.invitation_id ||
    (transactionData as any)?.idempotencyKey ||
    (transactionData as any)?.idempotency_key
  );
  const routeInviteNeedsId = routeLooksLikeInvite
    && Boolean(routeInvitationExpiresAt)
    && moment(routeInvitationExpiresAt).isBefore(moment())
    && !routeHasInvitationId;
  const needsFetch = Boolean(
    (transactionData?.id || transactionData?.transaction_id) &&
    (lacksPhonesForSend || !hasValidInternalId || routeInviteNeedsId)
  );
  const transactionId = transactionData?.id || transactionData?.transaction_id;



  // Determine transaction kind to select proper fetch behavior
  const typeLower = (transactionType || transactionData?.transaction_type || '').toString().toLowerCase();
  const isUSDCTransaction = typeLower === 'deposit' || typeLower === 'withdrawal' || typeLower === 'conversion' ||
    (transactionData && ['deposit', 'withdrawal', 'conversion'].includes((transactionData.type || transactionData.transaction_type || '').toString().toLowerCase()));
  const isSendTransaction = ['send', 'sent', 'received', 'payroll'].includes(typeLower);
  const isPaymentTransaction = typeLower === 'payment';

  const { data: payData, loading: payLoading, error: payError } = useQuery(
    GET_PAYMENT_TRANSACTION_BY_ID,
    {
      variables: { id: transactionId },
      // Only fetch for payment type
      skip: !needsFetch || !transactionId || !isPaymentTransaction,
      fetchPolicy: 'cache-and-network',
    }
  );

  const { data: sendData, loading: sendLoading, error: sendError } = useQuery(
    GET_SEND_TRANSACTION_BY_ID,
    {
      variables: { id: transactionId },
      // Fetch for Send types (skip if payment)
      skip: !needsFetch || !transactionId || isUSDCTransaction || (!isSendTransaction && !isPaymentTransaction) || isPaymentTransaction,
      fetchPolicy: 'cache-and-network',
    }
  );

  const fetchedData = isPaymentTransaction
    ? { sendTransaction: payData?.paymentTransaction }
    : { sendTransaction: sendData?.sendTransaction };

  const fetchLoading = isPaymentTransaction ? payLoading : sendLoading;
  const fetchError = isPaymentTransaction ? payError : sendError;



  // No secondary friend query here to avoid backend filter issues

  // Sample transaction data - in real app, this would come from props or API
  const transactions: any = {
  };

  // Log what data we received

  // Transform fetched data to match the expected format
  // We'll build txData from the most reliable source in order:
  // 1) Server-fetched details (when available)
  // 2) Normalized notification payload (camelCased + mapped fields)
  // 3) Raw notification payload (last resort)
  let txData: any = undefined;

  // Case A: Standard Send/Payment Transaction
  if (fetchedData?.sendTransaction && needsFetch && (isSendTransaction || isPaymentTransaction)) {
    const rawTx = fetchedData.sendTransaction;
    // Normalize Payment fields to generic Send fields for consistency
    const tx = {
      ...rawTx,
      senderUser: rawTx.senderUser || rawTx.payerUser,
      recipientUser: rawTx.recipientUser || rawTx.merchantAccountUser,
      senderDisplayName: rawTx.senderDisplayName || rawTx.payerDisplayName,
      recipientDisplayName: rawTx.recipientDisplayName || rawTx.merchantDisplayName,
      senderBusiness: rawTx.senderBusiness || rawTx.payerBusiness,
      recipientBusiness: rawTx.recipientBusiness || rawTx.merchantBusiness,
    };
    // Resolve direction primarily from route params; fallback to simple heuristic
    const routeTypeRaw = (route.params?.transactionType || transactionData?.transaction_type || '').toString().toLowerCase();

    let resolvedType = 'received';
    if (['payment', 'payroll', 'deposit', 'withdrawal', 'conversion'].includes(routeTypeRaw)) {
      resolvedType = routeTypeRaw;
    } else if (routeTypeRaw === 'sent' || routeTypeRaw === 'send') {
      resolvedType = 'sent';
    } else {
      resolvedType = 'received';
    }


    // Determine invitation flags accurately: only when there is an invitation context
    const inviteFromRoute = Boolean((transactionData as any)?.is_invited_friend || (transactionData as any)?.isInvitedFriend);
    const isInvite = Boolean(tx.invitationExpiresAt) || inviteFromRoute;
    const claimedFromRoute = Boolean((transactionData as any)?.invitationClaimed || (transactionData as any)?.invitation_claimed);
    const revertedFromRoute = Boolean((transactionData as any)?.invitationReverted || (transactionData as any)?.invitation_reverted);

    txData = {
      ...(transactionData || {}),
      type: resolvedType,
      from: tx.senderDisplayName || tx.senderUser?.firstName || (transactionData as any)?.senderName || (tx.senderAddress ? `Externo (${tx.senderAddress.slice(0, 4)}...${tx.senderAddress.slice(-4)})` : 'Usuario'),
      fromAddress: tx.senderAddress,
      to: tx.recipientDisplayName || tx.recipientUser?.firstName || (transactionData as any)?.recipientName || 'Usuario',
      toAddress: tx.recipientAddress,
      amount: resolvedType === 'sent' ? `-${tx.amount}` : `+${tx.amount}`,
      currency: tx.tokenType === 'CUSD' ? 'cUSD' : tx.tokenType,
      date: moment.utc(tx.createdAt).local().format('YYYY-MM-DD'),
      time: moment.utc(tx.createdAt).local().format('HH:mm'),
      status: tx.status?.toLowerCase() || 'completed',
      hash: tx.transactionHash || '',
      note: tx.memo || '',
      avatar: (resolvedType === 'sent' ? tx.recipientDisplayName : tx.senderDisplayName)?.[0] || 'U',
      isInvitedFriend: isInvite,
      invitationId: tx.idempotencyKey || (transactionData as any)?.invitationId || (transactionData as any)?.invitation_id,
      idempotencyKey: tx.idempotencyKey,
      invitationExpiresAt: tx.invitationExpiresAt,
      invitationClaimed: isInvite ? (tx.invitationClaimed || claimedFromRoute) : false,
      invitationReverted: isInvite ? (tx.invitationReverted || revertedFromRoute) : false,
      transaction_type: 'send',
      internalId: tx.internalId || (transactionData as any)?.internalId || (transactionData as any)?.internal_id,
      // Add phone keys from fetched data (prefer user.phoneKey over legacy fields)
      sender_phone: (tx.senderUser as any)?.phoneKey || (tx.senderPhone || undefined),
      recipient_phone: (tx.recipientUser as any)?.phoneKey || (tx.recipientPhone || undefined),
      senderPhone: (tx.senderUser as any)?.phoneKey || (tx.senderPhone || undefined),
      recipientPhone: (tx.recipientUser as any)?.phoneKey || (tx.recipientPhone || undefined),
      // Explicitly preserve business data
      payerBusiness: tx.payerBusiness || tx.senderBusiness,
      merchantBusiness: tx.merchantBusiness || tx.recipientBusiness,
      payerDisplayName: tx.payerDisplayName,
      merchantDisplayName: tx.merchantDisplayName,
      senderBusiness: tx.senderBusiness,
      recipientBusiness: tx.recipientBusiness,
      // Tier badge data from counterparty users
      senderStatusTier: tx.senderUser?.statusTier || (transactionData as any)?.senderStatusTier,
      senderIsReferralVerified: tx.senderUser?.isReferralVerified ?? (transactionData as any)?.senderIsReferralVerified,
      recipientStatusTier: tx.recipientUser?.statusTier || (transactionData as any)?.recipientStatusTier,
      recipientIsReferralVerified: tx.recipientUser?.isReferralVerified ?? (transactionData as any)?.recipientIsReferralVerified,
      // Payment-specific
      payerStatusTier: (tx as any).payerUser?.statusTier || (transactionData as any)?.payerStatusTier,
      payerIsReferralVerified: (tx as any).payerUser?.isReferralVerified ?? (transactionData as any)?.payerIsReferralVerified,
      merchantStatusTier: (tx as any).merchantAccountUser?.statusTier || (transactionData as any)?.merchantStatusTier,
      merchantIsReferralVerified: (tx as any).merchantAccountUser?.isReferralVerified ?? (transactionData as any)?.merchantIsReferralVerified,
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
      rampDirection: transactionData.ramp_direction || transactionData.rampDirection || transactionData.direction,
      rampStatus: transactionData.ramp_status || transactionData.rampStatus,
      rampFiatAmount: transactionData.ramp_fiat_amount || transactionData.rampFiatAmount,
      rampFiatCurrency: transactionData.ramp_fiat_currency || transactionData.rampFiatCurrency,
      walletAmount: transactionData.wallet_amount || transactionData.walletAmount,
      walletCurrency: transactionData.wallet_currency || transactionData.walletCurrency,
      createdAt: transactionData.created_at || transactionData.createdAt || transactionData.timestamp,
      transactionType: transactionData.transaction_type || transactionData.transactionType,
      tokenType: transactionData.token_type || transactionData.tokenType || transactionData.currency,
      transactionId: transactionData.transaction_id || transactionData.transactionId || transactionData.id,
      internalId: transactionData.internal_id || transactionData.internalId,
      recipientName: transactionData.recipient_name || transactionData.recipientName,
      recipientPhone: transactionData.recipient_phone || transactionData.recipientPhone,
      recipientAddress: transactionData.recipient_address || transactionData.recipientAddress,
      is_external_address: transactionData.is_external_address,
      is_invited_friend: transactionData.is_invited_friend,
      isInvitedFriend: transactionData.is_invited_friend || transactionData.isInvitedFriend,
      invitationId: (transactionData as any).invitationId || (transactionData as any).invitation_id || (transactionData as any).idempotencyKey,
      idempotencyKey: (transactionData as any).idempotencyKey || (transactionData as any).idempotency_key,
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
      // Override 'to' and 'from' if they contain truncated addresses
      to: (transactionData.to && transactionData.to.includes('...') && transactionData.to.startsWith('0x'))
        ? '' : transactionData.to,
      from: (transactionData.from && transactionData.from.includes('...') && transactionData.from.startsWith('0x'))
        ? '' : transactionData.from,
      // For conversions (will override currency below based on direction)
      currency: transactionData.from_token || transactionData.token_type || transactionData.currency || 'USDC',
      secondaryCurrency: transactionData.to_token || 'cUSD',
      // Explicitly preserve business data in normalization
      payerBusiness: transactionData.payerBusiness || transactionData.senderBusiness,
      merchantBusiness: transactionData.merchantBusiness || transactionData.recipientBusiness,
      payerDisplayName: transactionData.payerDisplayName,
      merchantDisplayName: transactionData.merchantDisplayName,
      senderBusiness: transactionData.senderBusiness,
      recipientBusiness: transactionData.recipientBusiness,
      senderStatusTier: transactionData.senderStatusTier ?? transactionData.senderUser?.statusTier ?? null,
      senderIsReferralVerified: transactionData.senderIsReferralVerified ?? transactionData.senderUser?.isReferralVerified ?? false,
      recipientStatusTier: transactionData.recipientStatusTier ?? transactionData.recipientUser?.statusTier ?? null,
      recipientIsReferralVerified: transactionData.recipientIsReferralVerified ?? transactionData.recipientUser?.isReferralVerified ?? false,
      payerStatusTier: transactionData.payerStatusTier ?? transactionData.senderStatusTier ?? transactionData.senderUser?.statusTier ?? null,
      payerIsReferralVerified: transactionData.payerIsReferralVerified ?? transactionData.senderIsReferralVerified ?? transactionData.senderUser?.isReferralVerified ?? false,
      merchantStatusTier: transactionData.merchantStatusTier ?? transactionData.recipientStatusTier ?? transactionData.recipientUser?.statusTier ?? null,
      merchantIsReferralVerified: transactionData.merchantIsReferralVerified ?? transactionData.recipientIsReferralVerified ?? transactionData.recipientUser?.isReferralVerified ?? false,
      // For conversions: cUSD -> USDC should be negative (money out), USDC -> cUSD should be positive (money in)
      // For withdrawals: always negative (money out)
      amount: transactionData.conversion_type === 'cusd_to_usdc'
        ? `-${transactionData.from_amount || transactionData.amount || '0'}`
        : transactionData.conversion_type === 'usdc_to_cusd'
          ? `+${transactionData.to_amount || transactionData.amount || '0'}`
          : type === 'withdrawal'
            ? `-${transactionData.amount || '0'}`.replace('--', '-') // Ensure single negative sign
            : transactionData.amount || transactionData.from_amount || transactionData.to_amount,
      status:
        transactionData.status ||
        deriveStatusFromNotificationType(transactionData.notification_type || transactionData.notificationType) ||
        'pending',
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

    // Override conversion currency to match displayed amount
    if (transactionData.conversion_type === 'usdc_to_cusd') {
      normalizedTransactionData.currency = 'cUSD';
    } else if (transactionData.conversion_type === 'cusd_to_usdc') {
      normalizedTransactionData.currency = 'USDC';
    }

    // For ramp detail screens, prefer direction-aware display data over provider rail labels.
    if (type === 'ramp') {
      const rampDirection = normalizeRampDirection(
        normalizedTransactionData.rampDirection,
        normalizedTransactionData.amount,
        normalizedTransactionData.formattedTitle || normalizedTransactionData.title,
      );
      const rampFiatAmount = addPositiveSign(normalizedTransactionData.rampFiatAmount);
      const walletAmount = addPositiveSign(normalizedTransactionData.walletAmount || normalizedTransactionData.amount);
      const currentCurrency = String(normalizedTransactionData.currency || normalizedTransactionData.tokenType || '').trim().toUpperCase();

      if (rampDirection === 'on_ramp') {
        if (rampFiatAmount) {
          normalizedTransactionData.amount = rampFiatAmount;
        }
        if (normalizedTransactionData.rampFiatCurrency) {
          normalizedTransactionData.currency = normalizedTransactionData.rampFiatCurrency;
        }
      } else if (rampDirection === 'off_ramp') {
        const signedWalletAmount = addNegativeSign(normalizedTransactionData.walletAmount || normalizedTransactionData.amount);
        if (signedWalletAmount) {
          normalizedTransactionData.amount = signedWalletAmount;
        }
        normalizedTransactionData.currency = 'cUSD';
      } else if (currentCurrency === 'USDC POLYGON' || currentCurrency === 'USDC SOLANA' || currentCurrency === 'USDC-A') {
        normalizedTransactionData.currency = 'cUSD';
      }
    }

    // Fallback timestamp if missing
    if (!normalizedTransactionData.createdAt && !normalizedTransactionData.timestamp) {
      const now = Date.now();
      (normalizedTransactionData as any).timestamp = now;
      (normalizedTransactionData as any).date = moment(now).format('YYYY-MM-DD');
      (normalizedTransactionData as any).time = moment(now).format('HH:mm');
    }

    // Provide from/to fallback names from sender/recipient_name
    // Prefer senderName/recipientName over generic "Usuario" or undefined
    if ((!normalizedTransactionData.from || normalizedTransactionData.from === 'Usuario') && normalizedTransactionData.senderName) {
      (normalizedTransactionData as any).from = normalizedTransactionData.senderName;
    } else if ((!normalizedTransactionData.from || normalizedTransactionData.from === 'Usuario') && normalizedTransactionData.senderAddress) {
      // Fallback to sender addresses for external wallets
      const addr = normalizedTransactionData.senderAddress;
      (normalizedTransactionData as any).from = `Externo (${addr.slice(0, 4)}...${addr.slice(-4)})`;
    }

    if ((!normalizedTransactionData.to || normalizedTransactionData.to === 'Usuario') && normalizedTransactionData.recipientName) {
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

  // Debug timezone conversion
  if (currentTx?.createdAt) {
    const deviceOffset = new Date().getTimezoneOffset();
  }

  // Get contact names for display - check all possible phone fields
  // MUST be called before any early returns to follow React hooks rules
  const senderPhone = currentTx?.sender_phone || currentTx?.senderPhone || currentTx?.fromPhone || (transactionData as any)?.sender_phone || (transactionData as any)?.fromPhone;
  const recipientPhone = currentTx?.recipient_phone || currentTx?.recipientPhone || currentTx?.toPhone || (transactionData as any)?.recipient_phone || (transactionData as any)?.toPhone || (transactionData as any)?.counterpartyPhone;

  // Detect external wallet counterparties to label them as "Billetera externa"
  const isExternalSender = ((currentTx?.type === 'received' || currentTx?.type === 'deposit') && (
    currentTx?.is_external_address || currentTx?.sourceAddress || (currentTx?.fromAddress && !senderPhone)
  )) as boolean;
  const isExternalRecipient = ((currentTx?.type === 'send' || currentTx?.type === 'sent' || currentTx?.type === 'withdrawal') && (
    currentTx?.is_external_address || currentTx?.destinationAddress || ((currentTx?.toAddress || currentTx?.recipient_address) && !recipientPhone)
  )) as boolean;

  // Don't use truncated addresses as fallback names
  const senderFallbackName = isExternalSender
    ? 'Billetera externa'
    : (currentTx?.from || currentTx?.senderName || currentTx?.sender_name);
  const recipientFallbackName = (() => {
    const name = currentTx?.to || currentTx?.recipientName || currentTx?.recipient_name;
    // If it's a truncated address, don't use it as a name
    if (name && name.includes('...') && name.startsWith('0x')) {
      return '';
    }
    return isExternalRecipient ? 'Billetera externa' : name;
  })();

  const senderContactInfo = useContactNameSync(senderPhone, senderFallbackName);
  // Only use contact sync if we have a phone number or a valid name
  const shouldUseContactSync = (recipientPhone && recipientPhone.trim() !== '') || (recipientFallbackName && !recipientFallbackName.startsWith('0x'));

  // Derive phone from local contact by name when phone isn't present or didn't match a contact
  // Try derive by Algorand address first (more reliable than name)
  const toAlgAddress = currentTx?.toAddress || currentTx?.recipient_address;
  const recipientContactByAddress = (!recipientPhone && toAlgAddress)
    ? (contactService.getContactByAlgorandAddressSync
      ? contactService.getContactByAlgorandAddressSync(toAlgAddress)
      : null)
    : null;
  const derivedRecipientPhoneFromAddress = recipientContactByAddress?.normalizedPhones?.[0] || recipientContactByAddress?.phoneNumbers?.[0] || null;

  const recipientContactByName = (!recipientPhone && recipientFallbackName)
    ? (contactService.getContactByNameFuzzy
      ? contactService.getContactByNameFuzzy(recipientFallbackName)
      : contactService.getContactByNameSync(recipientFallbackName))
    : null;
  const derivedRecipientPhoneFromName = recipientContactByName?.normalizedPhones?.[0] || recipientContactByName?.phoneNumbers?.[0] || null;
  const resolvedRecipientPhone = (recipientPhone && recipientPhone.trim() !== '')
    ? recipientPhone
    : (derivedRecipientPhoneFromAddress || derivedRecipientPhoneFromName || undefined);

  const badgeLookupPhones = useMemo(() => {
    const phones = [senderPhone, resolvedRecipientPhone]
      .filter((phone): phone is string => typeof phone === 'string' && phone.trim().length > 0);
    return Array.from(new Set(phones));
  }, [senderPhone, resolvedRecipientPhone]);

  const { data: badgeLookupData } = useQuery(CHECK_USERS_BY_PHONES, {
    skip: badgeLookupPhones.length === 0,
    fetchPolicy: 'cache-first',
  });

  const badgeByPhone = useMemo(() => {
    const map = new Map<string, { statusTier?: string | null; isReferralVerified?: boolean }>();
    (badgeLookupData?.checkUsersByPhones || []).forEach((userInfo: any) => {
      const rawPhone = typeof userInfo?.phoneNumber === 'string' ? userInfo.phoneNumber.trim() : '';
      const normalizedPhone = normalizePhoneLookupKey(rawPhone);
      const badgeInfo = {
        statusTier: userInfo.statusTier || null,
        isReferralVerified: userInfo.isReferralVerified || false,
      };
      if (rawPhone) map.set(rawPhone, badgeInfo);
      if (normalizedPhone) map.set(normalizedPhone, badgeInfo);
    });
    return map;
  }, [badgeLookupData]);

  const senderBadgeInfo = badgeByPhone.get(senderPhone || '') || badgeByPhone.get(normalizePhoneLookupKey(senderPhone));
  const recipientBadgeInfo = badgeByPhone.get(resolvedRecipientPhone || '') || badgeByPhone.get(normalizePhoneLookupKey(resolvedRecipientPhone));
  const resolvedSenderStatusTier = currentTx?.senderStatusTier ?? senderBadgeInfo?.statusTier ?? null;
  const resolvedSenderIsReferralVerified = currentTx?.senderIsReferralVerified ?? senderBadgeInfo?.isReferralVerified ?? false;
  const resolvedRecipientStatusTier = currentTx?.recipientStatusTier ?? recipientBadgeInfo?.statusTier ?? null;
  const resolvedRecipientIsReferralVerified = currentTx?.recipientIsReferralVerified ?? recipientBadgeInfo?.isReferralVerified ?? false;
  const resolvedPayerStatusTier = currentTx?.payerStatusTier ?? resolvedSenderStatusTier;
  const resolvedPayerIsReferralVerified = currentTx?.payerIsReferralVerified ?? resolvedSenderIsReferralVerified;
  const resolvedMerchantStatusTier = currentTx?.merchantStatusTier ?? resolvedRecipientStatusTier;
  const resolvedMerchantIsReferralVerified = currentTx?.merchantIsReferralVerified ?? resolvedRecipientIsReferralVerified;

  // Always call hook unconditionally to respect Rules of Hooks
  const recipientContactResult = useContactNameSync(resolvedRecipientPhone, recipientFallbackName);
  const recipientContactInfo = shouldUseContactSync
    ? recipientContactResult
    : { displayName: '', isFromContacts: false };



  // Show loading state while fetching
  if (fetchLoading) {
    return (
      <View style={[styles.container, { paddingTop: 48 }]}>
        <SkeletonLoader width={48} height={48} borderRadius={24} style={{ alignSelf: 'center', marginBottom: 16 }} />
        <SkeletonLoader width={180} height={28} style={{ alignSelf: 'center', marginBottom: 8 }} />
        <SkeletonLoader width={120} height={16} style={{ alignSelf: 'center', marginBottom: 24 }} />
        <TransactionItemSkeleton />
        <TransactionItemSkeleton />
        <TransactionItemSkeleton />
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

  const isInvitedFriend = currentTx?.isInvitedFriend || currentTx?.is_invited_friend || currentTx?.isInvitation || currentTx?.is_invitation || false;
  const isExternalAddress = currentTx?.is_external_address || false;
  const invitationClaimed = currentTx?.invitationClaimed || currentTx?.invitation_claimed || false;
  const invitationReverted = currentTx?.invitationReverted || currentTx?.invitation_reverted || Boolean(reclaimedInviteTxid);
  const invitationExpiresAt = currentTx?.invitationExpiresAt || currentTx?.invitation_expires_at;
  const isInvitationExpired = invitationExpiresAt ? moment(invitationExpiresAt).isBefore(moment()) : false;
  const currentInvitationId = (currentTx as any).invitationId
    || (currentTx as any).invitation_id
    || (currentTx as any).idempotencyKey
    || (currentTx as any).idempotency_key
    || (transactionData as any)?.invitationId
    || (transactionData as any)?.invitation_id
    || (transactionData as any)?.idempotencyKey
    || (transactionData as any)?.idempotency_key
    || '';
  const showInvitationWarning = isInvitedFriend
    && !isExternalAddress
    && (currentTx?.type === 'send' || currentTx?.type === 'sent')
    && !invitationClaimed
    && !invitationReverted
    && !isInvitationExpired;
  const showInvitationReclaim = isInvitedFriend
    && !isExternalAddress
    && (currentTx?.type === 'send' || currentTx?.type === 'sent')
    && !invitationClaimed
    && !invitationReverted
    && isInvitationExpired
    && Boolean(currentInvitationId);

  const handleReclaimInvite = async () => {
    if (!currentInvitationId || reclaimingInvite) return;
    setReclaimingInvite(true);
    try {
      const result = await inviteSendService.reclaimInvite(currentInvitationId);
      if (!result.success) {
        Alert.alert('No se pudo devolver', result.error || 'Inténtalo nuevamente.');
        return;
      }
      setReclaimedInviteTxid(result.txid || '');
      Alert.alert('Fondos devueltos', 'La invitación expirada fue devuelta a tu balance.');
    } catch (e: any) {
      Alert.alert('No se pudo devolver', e?.message || 'Inténtalo nuevamente.');
    } finally {
      setReclaimingInvite(false);
    }
  };

  // Debug invitation status

  // Debug phone numbers

  // Use contact names if available
  // Prefer phone contact name over any server-provided display values, UNLESS it is a business payment
  let preferredFrom = getPreferredDisplayName(senderPhone, senderContactInfo.displayName);
  let preferredTo = getPreferredDisplayName(recipientPhone, recipientContactInfo.displayName);

  // Business Name Override
  // If valid business info exists, prioritize that over contact matching regardless of type
  // (Because type might be 'received'/'sent' but still be a business transaction)
  if (currentTx?.payerBusiness?.name) {
    preferredFrom = { name: currentTx.payerBusiness.name, fromContacts: false };
  } else if (currentTx?.payerDisplayName && (currentTx.type === 'payment' || currentTx.payerBusiness)) {
    preferredFrom = { name: currentTx.payerDisplayName, fromContacts: false };
  }

  if (currentTx?.merchantBusiness?.name) {
    preferredTo = { name: currentTx.merchantBusiness.name, fromContacts: false };
  } else if (currentTx?.merchantDisplayName && (currentTx.type === 'payment' || currentTx.merchantBusiness)) {
    preferredTo = { name: currentTx.merchantDisplayName, fromContacts: false };
  }

  const displayFromName = preferredFrom.name;
  let displayToName = preferredTo.name;
  if (!recipientContactInfo.isFromContacts) {
    if (recipientContactByAddress?.name) displayToName = recipientContactByAddress.name;
    else if (recipientContactByName?.name) displayToName = recipientContactByName.name;
  }

  // As a last-resort enhancement for notifications where phones may be missing
  // prefer the user's local contact name by exact name match when no phone match exists.
  try {
    if (!preferredTo.fromContacts) {
      const nameHint = (currentTx?.to || currentTx?.recipientName || currentTx?.recipient_name || '').toString().trim();
      if (nameHint) {
        const byName = contactService.getContactByNameSync(nameHint);
        if (byName && byName.name) {
          displayToName = byName.name;
        }
      }
    }
  } catch { }


  const resolveConversionTokens = (tx?: any) => {
    const typeHint =
      tx?.conversion_type ||
      tx?.conversionType ||
      normalizedTransactionData?.conversion_type ||
      normalizedTransactionData?.conversionType ||
      transactionData?.conversion_type ||
      transactionData?.conversionType;
    const fallbackFrom =
      typeHint === 'usdc_to_cusd' ? 'USDC' :
        typeHint === 'cusd_to_usdc' ? 'cUSD' :
          undefined;
    const fallbackTo =
      typeHint === 'usdc_to_cusd' ? 'cUSD' :
        typeHint === 'cusd_to_usdc' ? 'USDC' :
          undefined;
    const fromToken =
      tx?.conversionFromCurrency ||
      tx?.conversion_from_currency ||
      tx?.conversionFromToken ||
      tx?.from_token ||
      tx?.fromToken ||
      fallbackFrom ||
      tx?.currency;
    const toToken =
      tx?.conversionToCurrency ||
      tx?.conversion_to_currency ||
      tx?.conversionToToken ||
      tx?.to_token ||
      tx?.toToken ||
      fallbackTo ||
      tx?.secondaryCurrency ||
      fallbackFrom ||
      tx?.currency;
    return { from: fromToken, to: toToken };
  };

  const { from: conversionFromCurrency, to: conversionToCurrency } = resolveConversionTokens(currentTx);
  const conversionFromCurrencyLabel = ((conversionFromCurrency ?? currentTx?.currency) || '').toString().trim();
  const conversionToCurrencyLabel = ((conversionToCurrency ?? currentTx?.secondaryCurrency) || '').toString().trim();

  const handleCopy = (text: string, type: string) => {
    Clipboard.setString(text);
    // The inline "copied" checkmark next to the address is the feedback; no dialog needed.
    setCopied(type);
    setTimeout(() => setCopied(''), 2000);
  };

  const getTransactionIcon = (type: string) => {
    switch (type) {
      case 'received':
        return <Icon name="arrow-down" size={24} color={colors.primaryDark} />;
      case 'sent':
        return <Icon name="arrow-up" size={24} color={colors.text.primary} />;
      case 'exchange':
      case 'conversion':
        return <Icon name="refresh-cw" size={24} color={colors.accent} />;
      case 'payment':
        return <Icon name="shopping-bag" size={24} color={colors.secondary} />;
      case 'ramp':
        return <Icon name="repeat" size={24} color="#0EA5E9" />;
      case 'payroll':
        return <Icon name="briefcase" size={24} color={colors.primaryDark} />;
      case 'humanitarian':
        return <Icon name="heart" size={24} color="#E11D48" />;
      case 'deposit':
        return <Icon name="arrow-down-circle" size={24} color={colors.primaryDark} />;
      case 'withdrawal':
        return <Icon name="arrow-up-circle" size={24} color={colors.danger} />;
      default:
        return <Icon name="arrow-up" size={24} color={colors.text.secondary} />;
    }
  };

  const getTransactionTitle = (tx: any) => {

    switch (tx.type) {
      case 'received':
        return `Recibido de ${displayFromName}`;
      // Both 'send' and 'sent' are handled for compatibility
      // Backend now uses 'send' for consistency with other types (payment, deposit, etc.)
      // but 'sent' might exist in older data
      case 'send':
      case 'sent':

        if (displayToName) {
          return `Enviado a ${displayToName}`;
        } else if (tx.is_invited_friend && tx.recipient_phone) {
          return 'Enviado a amigo invitado';
        } else if (tx.is_external_address || (tx.toAddress && !tx.recipient_phone) || (tx.recipient_address && !tx.recipient_phone)) {
          return 'Enviado a billetera externa';
        }
        return 'Enviado';
      case 'exchange':
        return `Intercambio ${tx.from} → ${tx.to}`;
      case 'conversion': {
        const tokens = resolveConversionTokens(tx);
        return tx.formattedTitle || `Conversión ${tokens.from || tx.currency || 'USDC'} → ${tokens.to || tx.secondaryCurrency || 'cUSD'}`;
      }
      case 'payment':
        // Check if it's a received payment (positive amount) or sent payment (negative amount)
        return tx.amount.startsWith('+')
          ? `Pago recibido de ${displayFromName}`
          : `Pago a ${displayToName}`;
      case 'ramp': {
        const rampDirection = normalizeRampDirection(
          tx.rampDirection || tx.ramp_direction || tx.direction,
          tx.amount,
          tx.formattedTitle || tx.title,
        );
        return tx.formattedTitle || (rampDirection === 'off_ramp' ? 'Retiro' : 'Recarga');
      }
      case 'payroll':
        return tx.amount.startsWith('+')
          ? `Nómina recibida de ${displayFromName}`
          : `Pago de nómina a ${displayToName}`;
      case 'humanitarian':
        return tx.amount.startsWith('+')
          ? 'Ayuda humanitaria recibida'
          : 'Donación humanitaria';
      case 'deposit':
        return tx.formattedTitle || `Depósito ${tx.currency}`;
      case 'withdrawal':
        return tx.formattedTitle || `Retiro ${tx.currency}`;
      default:
        return 'Transacción';
    }
  };

  const getStatusColor = (status: string) => {
    switch (normalizeStatusForDisplay(status)) {
      case 'completed':
        return { text: colors.primaryDark, bg: '#d1fae5' };
      case 'pending':
        return { text: '#d97706', bg: '#fef3c7' };
      case 'processing':
        return { text: '#1d4ed8', bg: '#dbeafe' };
      case 'aml_review':
        return { text: '#92400e', bg: '#fde68a' };
      case 'failed':
        return { text: colors.error.icon, bg: '#fee2e2' };
      default:
        return { text: colors.text.secondary, bg: colors.neutralDark };
    }
  };

  const effectiveStatus = (currentTx.type || '').toLowerCase() === 'ramp' && currentTx.rampStatus
    ? currentTx.rampStatus.toLowerCase()
    : currentTx.status;
  const statusColors = getStatusColor(effectiveStatus);
  const normalizedStatus = normalizeStatusForDisplay(effectiveStatus);

  const headerPaddingTop = Math.max(insets.top, 12);
  const resolvedInternalId = resolveInternalId(currentTx, transactionData);
  const operationIdDisplay = resolvedInternalId
    ? resolvedInternalId.slice(0, 8).toUpperCase()
    : 'N/A';

  // One formatted date string for the receipt (same source priority the old
  // date/time card row used).
  const dateTimeDisplay = (() => {
    if (currentTx.createdAt) {
      const date = typeof currentTx.createdAt === 'string'
        ? (currentTx.createdAt.includes('T') ? new Date(currentTx.createdAt) : moment(currentTx.createdAt).toDate())
        : new Date(currentTx.createdAt as any);
      return `${moment(date).format('DD/MM/YYYY')} • ${moment(date).format('HH:mm')}`;
    }
    if (currentTx.date && currentTx.time) {
      return `${moment(currentTx.date, 'YYYY-MM-DD').format('DD/MM/YYYY')} • ${currentTx.time}`;
    }
    if (currentTx.date) {
      return moment(currentTx.date, 'YYYY-MM-DD').format('DD/MM/YYYY');
    }
    return 'No disponible';
  })();

  // Operation summary as shared ReceiptCard rows — the same receipt grammar
  // as the success screens. Status appears only when it says something the
  // hero badge doesn't already (confirming, ramp progress, failure).
  const receiptItems = (() => {
    const items: ReceiptItem[] = [];
    const currency = currentTx.currency || 'cUSD';
    const isPaymentDebit = currentTx.type === 'payment' && !!currentTx.amount?.startsWith('-');

    const amountLabel = currentTx.type === 'payment'
      ? (isPaymentDebit ? 'Monto pagado' : 'Monto cobrado')
      : (currentTx.type === 'exchange' || currentTx.type === 'conversion')
        ? 'Monto intercambiado'
        : currentTx.type === 'received'
          ? 'Monto recibido'
          : 'Monto enviado';
    items.push({ label: amountLabel, value: `${formatAmount(currentTx.amount)} ${currency}` });
    items.push({ label: 'Comisión de red', value: 'Gratis · cubre Confío', color: colors.primaryDark });

    if (currentTx.type === 'payment' && !isPaymentDebit) {
      const fee = computeConfioFee(currentTx.amount);
      if (fee > 0) {
        items.push({
          label: 'Comisión Confío (0.9%)',
          value: `- ${(fee < 0.01 && fee > 0) ? '< 0.01' : fee.toFixed(2)} ${currency}`,
        });
      }
    }

    if (currentTx.type === 'send' || currentTx.type === 'sent' || currentTx.type === 'payment') {
      const raw = currentTx.amount;
      const sign = typeof raw === 'string' && raw.startsWith('-') ? '-' : (typeof raw === 'string' && raw.startsWith('+') ? '+' : '');
      const grossAbs = typeof raw === 'string' ? parseFloat(raw.replace(/[+-]/g, '')) : (Number(raw) || 0);
      let totalLabel = currentTx.type === 'sent' ? 'Total enviado' : 'Total recibido';
      let totalAbs = grossAbs;
      if (currentTx.type === 'payment') {
        totalLabel = isPaymentDebit ? 'Total pagado' : 'Total recibido';
        if (!isPaymentDebit) totalAbs = Math.max(0, grossAbs - computeConfioFee(raw));
      }
      items.push({
        label: totalLabel,
        value: `${sign}${totalAbs.toFixed(2)} ${currency}`,
        color: colors.text.primary,
      });
    }

    items.push({ label: 'Fecha', value: dateTimeDisplay });
    items.push({ label: 'ID de operación', value: `#${operationIdDisplay}` });

    if ((currentTx.type || '').toLowerCase() === 'ramp') {
      const rs = ((currentTx.rampStatus || currentTx.status) || '').toString().toUpperCase();
      if (rs === 'PROCESSING') {
        items.push({ label: 'Estado', value: 'En proceso', color: colors.accent, icon: 'loader' });
      } else if (rs === 'PENDING') {
        items.push({ label: 'Estado', value: 'Pendiente', color: colors.offRampIcon, icon: 'clock' });
      } else if (rs === 'FAILED' || rs === 'REJECTED') {
        items.push({ label: 'Estado', value: 'Fallido', color: colors.danger, icon: 'x-circle' });
      }
      items.push({ label: 'Tiempo estimado', value: 'Hasta 1 hora' });
    } else {
      const statusLc = (currentTx.status || '').toString().toLowerCase();
      if (statusLc === 'submitted' || statusLc === 'pending' || statusLc === 'pending_blockchain') {
        items.push({ label: 'Estado', value: 'Confirmando…', color: colors.offRampIcon, icon: 'clock' });
      } else if (statusLc === 'failed') {
        items.push({ label: 'Estado', value: 'Fallido', color: colors.danger, icon: 'x-circle' });
      }
    }

    return items;
  })();

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />

      {/* Entire screen scrollable */}
      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {banner && (
          <InlineBanner
            message={banner.message}
            variant={banner.variant}
            onDismiss={dismissBanner}
            style={{ marginHorizontal: 16, marginTop: 8 }}
          />
        )}
        {/* Header — brand field: vertical emerald gradient + cropped coin
            ring, same grammar as Home/Profile/AccountDetail. Padding lives on
            headerInner (Yoga insets absolute children by parent padding). */}
        <View
          style={styles.header}
          onLayout={(e) => {
            const { width, height } = e.nativeEvent.layout;
            setFieldSize((prev) =>
              prev.width === width && prev.height === height ? prev : { width, height }
            );
          }}
        >
          <Svg
            key={`txField-${fieldSize.width}x${fieldSize.height}`}
            width={fieldSize.width || '100%'}
            height={fieldSize.height || '100%'}
            style={StyleSheet.absoluteFill}
          >
            <Defs>
              <SvgLinearGradient id="txDetailField" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={colors.primary} />
                <Stop offset="1" stopColor={colors.primaryDark} />
              </SvgLinearGradient>
            </Defs>
            <Rect width="100%" height="100%" fill="url(#txDetailField)" />
            <Circle cx="105%" cy="22%" r="90" stroke={colors.white} strokeWidth="22" strokeOpacity="0.10" fill="none" />
          </Svg>
          <View style={[styles.headerInner, { paddingTop: headerPaddingTop }]}>
          <View style={styles.headerTop}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerButton} accessibilityRole="button" accessibilityLabel="Volver">
              <Icon name="arrow-left" size={24} color={colors.white} />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Detalle de Transacción</Text>
            <TouchableOpacity
              style={styles.headerButton}
              accessibilityRole="button"
              accessibilityLabel="Ver comprobante"
              onPress={() => {
                navigation.navigate('TransactionReceipt', {
                  transaction: {
                    ...currentTx,
                    // Explicitly pass name fields for ALL types to prevent 'Usuario'/'Comercio' fallback
                    senderName: currentTx.payerDisplayName || currentTx.senderDisplayName || currentTx.senderName || currentTx.from || currentTx.sender_name || (currentTx.type === 'payroll' ? (currentTx.businessName || 'Empresa') : undefined),
                    recipientName: currentTx.merchantDisplayName || currentTx.recipientDisplayName || currentTx.recipientName || currentTx.to || currentTx.recipient_name || (currentTx.type === 'payroll' ? (currentTx.employeeName || 'Empleado') : undefined),
                    businessName: currentTx.businessName || currentTx.sender_name || 'Empresa',
                    employeeName: currentTx.employeeName || currentTx.recipient_name,

                    // Payment specific rich data
                    payerBusiness: currentTx.payerBusiness,
                    payerDisplayName: currentTx.payerDisplayName,
                    merchantBusiness: currentTx.merchantBusiness,
                    merchantDisplayName: currentTx.merchantDisplayName,

                    // Internal ID for verification QR code (User Request)
                    verificationId: resolvedInternalId || (currentTx as any).itemId || currentTx.id,
                    // Keep original hash logic for display
                    transactionHash: currentTx.transactionId || currentTx.transactionHash,
                  },
                  type: currentTx.type === 'payroll' ? 'payroll' : (currentTx.type === 'payment' ? 'payment' : 'transfer')
                });
              }}
            >
              <Icon name="share" size={24} color={colors.white} />
            </TouchableOpacity>
          </View>

          <View style={styles.transactionSummary}>
            <View style={styles.iconContainer}>
              {getTransactionIcon(currentTx.type)}
            </View>

            {(() => {
              const raw = currentTx.amount as any;
              const isNeg = typeof raw === 'string' ? raw.startsWith('-') : Number(raw) < 0;
              const sign = isNeg ? '-' : (typeof raw === 'string' && raw.startsWith('+') ? '+' : '');
              const abs = formatAmount(raw);
              // Amount stays white either direction — the sign carries the
              // direction; tinting outgoing pink read as an alert.
              return (
                <Text style={styles.amountText}>
                  {sign ? `${sign} ` : ''}{abs} {currentTx.currency || 'cUSD'}
                </Text>
              );
            })()}

            <Text style={styles.transactionTitle}>
              {(() => {
                const title = getTransactionTitle(currentTx);
                return title;
              })()}
            </Text>

            <View style={[styles.statusBadge, { backgroundColor: statusColors.bg }]}>
              {normalizedStatus === 'completed' && (
                <Icon name="check-circle" size={16} color={statusColors.text} style={styles.statusIcon} />
              )}
              {normalizedStatus === 'pending' && (
                <Icon name="clock" size={16} color={statusColors.text} style={styles.statusIcon} />
              )}
              {normalizedStatus === 'processing' && (
                <Icon name="loader" size={16} color={statusColors.text} style={styles.statusIcon} />
              )}
              {normalizedStatus === 'aml_review' && (
                <Icon name="alert-triangle" size={16} color={statusColors.text} style={styles.statusIcon} />
              )}
              {normalizedStatus === 'failed' && (
                <Icon name="x-circle" size={16} color={statusColors.text} style={styles.statusIcon} />
              )}
              <Text style={[styles.statusText, { color: statusColors.text }]}>
                {normalizedStatus === 'completed' ? 'Completado' :
                  normalizedStatus === 'pending' ? 'Pendiente' :
                    normalizedStatus === 'processing' ? 'Procesando' :
                      normalizedStatus === 'aml_review' ? 'En revisión' :
                        normalizedStatus === 'failed' ? 'Fallido' : 'Desconocido'}
              </Text>
            </View>

            {showInvitationWarning && (
              <View style={styles.invitationNotice}>
                <Icon name="alert-triangle" size={16} color={colors.white} style={{ marginRight: 6 }} />
                <Text style={styles.invitationText}>Tu amigo tiene 7 días para reclamar</Text>
              </View>
            )}
            {!showInvitationWarning && isInvitedFriend && invitationClaimed && (currentTx.type === 'send' || currentTx.type === 'sent') && (
              <View style={[styles.invitationNotice, { backgroundColor: colors.primaryDark }]}>
                <Icon name="check-circle" size={16} color={colors.white} style={{ marginRight: 6 }} />
                <Text style={styles.invitationText}>Invitación reclamada</Text>
              </View>
            )}
          </View>
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
                        accessibilityRole="button"
                        accessibilityLabel="Copiar dirección de origen"
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
                    <Icon name="arrow-up-circle" size={24} color={colors.danger} />
                  </View>
                  <View style={styles.participantDetails}>
                    <Text style={styles.participantName}>Retiro hacia wallet externa</Text>
                    <View style={styles.addressContainer}>
                      <Text style={styles.addressText}>{currentTx.destinationAddress || currentTx.toAddress}</Text>
                      <TouchableOpacity
                        onPress={() => handleCopy(currentTx.destinationAddress || currentTx.toAddress, 'to')}
                        style={styles.copyButton}
                        accessibilityRole="button"
                        accessibilityLabel="Copiar dirección de destino"
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
                    <View style={[styles.exchangeIcon, { backgroundColor: colors.white }]}>
                      {conversionFromCurrencyLabel.toUpperCase() === 'USDC' ? (
                        <Image source={USDCLogo} style={{ width: 24, height: 24, resizeMode: 'contain' }} />
                      ) : (
                        <Image source={cUSDLogo} style={{ width: 24, height: 24, resizeMode: 'contain' }} />
                      )}
                    </View>
                    <Icon name="arrow-right" size={16} color={colors.text.secondary} style={styles.exchangeArrow} />
                    <View style={[styles.exchangeIcon, { backgroundColor: colors.white }]}>
                      {conversionToCurrencyLabel.toUpperCase() === 'USDC' ? (
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
                          if ((conversionFromCurrencyLabel.toUpperCase() === 'USDC' || conversionToCurrencyLabel.toUpperCase() === 'USDC') && isOneToOne) {
                            return `1 ${conversionFromCurrencyLabel || currentTx.currency} = 1 ${conversionToCurrencyLabel || currentTx.secondaryCurrency}`;
                          }

                          // If rate already contains '=', use as is
                          if (rate && rate.includes('=')) {
                            return rate;
                          }

                          // Format rate without decimals if it's a whole number
                          const formattedRate = isOneToOne ? '1' : rate;
                          return `1 ${conversionFromCurrencyLabel || currentTx.currency} = ${formattedRate} ${conversionToCurrencyLabel || currentTx.secondaryCurrency}`;
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
                    <View style={styles.participantNameRow}>
                      {(() => {
                        const name = displayFromName;
                        if (!resolvedSenderIsReferralVerified) {
                          return <Text style={styles.participantName}>{name}</Text>;
                        }
                        const words = name.trim().split(' ').filter(Boolean);
                        return words.map((word, i) => {
                          const isLast = i === words.length - 1;
                          if (!isLast) {
                            return <Text key={i} style={styles.participantName}>{word}{' '}</Text>;
                          }
                          return (
                            <View key={i} style={styles.participantLastWordBadgeGroup}>
                              <Text style={styles.participantName}>{word}</Text>
                              <View style={styles.participantInlineVerifiedBadge}>
                                <Icon name="check" size={11} color={colors.white} />
                              </View>
                            </View>
                          );
                        });
                      })()}
                    </View>
                    {resolvedSenderStatusTier && resolvedSenderStatusTier !== 'member' && (
                      <StatusTierBadge tier={resolvedSenderStatusTier} variant="compact" style={{ marginTop: 4, alignSelf: 'flex-start' }} />
                    )}
                    <View style={styles.addressContainer}>
                      <Text style={styles.addressText}>
                        {getPreferredSecondaryLine({ phone: senderPhone, address: currentTx.fromAddress, isExternal: !!currentTx.is_external_address })}
                      </Text>
                      <TouchableOpacity
                        onPress={() => handleCopy(
                          senderPhone ? formatPhoneNumber(senderPhone) : currentTx.fromAddress,
                          'from'
                        )}
                        style={styles.copyButton}
                        accessibilityRole="button"
                        accessibilityLabel="Copiar datos del remitente"
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

              {(currentTx.type === 'send' || currentTx.type === 'sent' || currentTx.type === 'payroll') && (
                <View style={styles.participantInfo}>
                  <View style={styles.avatarContainer}>
                    <Text style={styles.avatarText}>
                      {currentTx.avatar || (currentTx.is_external_address ? '0' : 'U')}
                    </Text>
                  </View>
                  <View style={styles.participantDetails}>
                    <View style={styles.participantNameRow}>
                      {(() => {
                        const name = (() => {
                          if (displayToName) return displayToName;
                          if (currentTx.is_invited_friend && currentTx.recipient_phone) {
                            return `Invitación enviada${currentTx.recipient_display_name ? ` a ${currentTx.recipient_display_name}` : ''}`;
                          }
                          if (currentTx.is_external_address || (currentTx.toAddress && !currentTx.recipient_phone && !displayToName)) {
                            return 'Billetera externa';
                          }
                          const fallbackName = currentTx.to || currentTx.recipient_name || 'Desconocido';
                          if (fallbackName.includes('...') && fallbackName.startsWith('0x')) {
                            return 'Billetera externa';
                          }
                          return fallbackName || 'Desconocido';
                        })();
                        if (!resolvedRecipientIsReferralVerified) {
                          return <Text style={styles.participantName}>{name}</Text>;
                        }
                        const words = name.trim().split(' ').filter(Boolean);
                        return words.map((word, i) => {
                          const isLast = i === words.length - 1;
                          if (!isLast) {
                            return <Text key={i} style={styles.participantName}>{word}{' '}</Text>;
                          }
                          return (
                            <View key={i} style={styles.participantLastWordBadgeGroup}>
                              <Text style={styles.participantName}>{word}</Text>
                              <View style={styles.participantInlineVerifiedBadge}>
                                <Icon name="check" size={11} color={colors.white} />
                              </View>
                            </View>
                          );
                        });
                      })()}
                    </View>
                    {resolvedRecipientStatusTier && resolvedRecipientStatusTier !== 'member' && (
                      <StatusTierBadge tier={resolvedRecipientStatusTier} variant="compact" style={{ marginTop: 4, alignSelf: 'flex-start' }} />
                    )}
                    <View style={styles.addressContainer}>
                      <Text style={styles.addressText}>
                        {(() => {
                          const phoneVal = resolvedRecipientPhone || currentTx.recipient_phone || derivedRecipientPhoneFromName;
                          const forcePhone = !!phoneVal || !!preferredTo.fromContacts;
                          const isExternalHeuristic = !!(currentTx.is_external_address || (currentTx.toAddress && !currentTx.recipient_phone));
                          return getPreferredSecondaryLine({
                            phone: phoneVal,
                            address: currentTx.toAddress || currentTx.recipient_address,
                            isExternal: forcePhone ? false : isExternalHeuristic,
                          });
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
                        accessibilityRole="button"
                        accessibilityLabel="Copiar datos del destinatario"
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
                    <View style={styles.participantNameRow}>
                      {(() => {
                        const isIncoming = currentTx.amount?.startsWith('+');
                        const name = isIncoming ? displayFromName : displayToName;
                        const verified = isIncoming ? resolvedPayerIsReferralVerified : resolvedMerchantIsReferralVerified;
                        if (!verified) {
                          return <Text style={styles.participantName}>{name}</Text>;
                        }
                        const words = name.trim().split(' ').filter(Boolean);
                        return words.map((word, i) => {
                          const isLast = i === words.length - 1;
                          if (!isLast) {
                            return <Text key={i} style={styles.participantName}>{word}{' '}</Text>;
                          }
                          return (
                            <View key={i} style={styles.participantLastWordBadgeGroup}>
                              <Text style={styles.participantName}>{word}</Text>
                              <View style={styles.participantInlineVerifiedBadge}>
                                <Icon name="check" size={11} color={colors.white} />
                              </View>
                            </View>
                          );
                        });
                      })()}
                    </View>
                    {(() => {
                      const isIncoming = currentTx.amount?.startsWith('+');
                      const tier = isIncoming ? resolvedPayerStatusTier : resolvedMerchantStatusTier;
                      return tier && tier !== 'member' ? (
                        <StatusTierBadge tier={tier} variant="compact" style={{ marginTop: 4, alignSelf: 'flex-start' }} />
                      ) : null;
                    })()}
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
                    <View style={[styles.exchangeIcon, { backgroundColor: colors.white }]}>
                      <Image source={USDCLogo} style={{ width: 24, height: 24, resizeMode: 'contain' }} />
                    </View>
                    <Icon name="arrow-down" size={16} color={colors.text.secondary} style={styles.exchangeArrow} />
                    <View style={[styles.exchangeIcon, { backgroundColor: colors.white }]}>
                      <Image source={cUSDLogo} style={{ width: 24, height: 24, resizeMode: 'contain' }} />
                    </View>
                  </View>
                  <Text style={styles.exchangeRate}>Tasa: {currentTx.exchangeRate}</Text>
                </View>
              )}

              {/* Location for payments - only show when user is paying a business */}
              {currentTx.type === 'payment' && currentTx.amount?.startsWith('-') && currentTx.location && (
                <View style={styles.infoRow}>
                  <Icon name="map-pin" size={20} color={colors.text.light} style={styles.infoIcon} />
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
                    <Icon name="file-text" size={20} color={colors.text.light} style={styles.infoIcon} />
                    <Text style={styles.noteTitle}>Nota</Text>
                  </View>
                  <Text style={styles.noteText}>{currentTx.note}</Text>
                </View>
              )}
            </View>
          </View>

          {/* Operation summary — shared receipt grammar */}
          <View>
            <Text style={styles.sectionLabel}>Resumen de operación</Text>
            <ReceiptCard items={receiptItems} style={styles.receiptCard} />
          </View>

          {/* Invitation Info Card for non-Confío friends */}
          {showInvitationWarning && (
            <View style={[styles.card, styles.invitationCard]}>
              <View style={styles.invitationHeader}>
                <Icon name="alert-circle" size={24} color={colors.warning.icon} />
                <Text style={[styles.invitationCardTitle, { color: colors.warning.text }]}>¡Acción requerida!</Text>
              </View>

              <Text style={[styles.invitationCardText, { fontWeight: 'bold', color: colors.warning.text }]}>
                Tu amigo tiene solo 7 días para reclamar el dinero o se perderá
              </Text>

              <View style={[styles.invitationInfoBox, { backgroundColor: colors.white, borderColor: colors.warning.border }]}>
                <Text style={[styles.invitationInfoTitle, { color: colors.warning.text }]}>Avísale ahora mismo</Text>
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
                    const phoneRaw = recipientPhone || currentTx.recipient_phone;
                    const cleanPhone = phoneRaw ? String(phoneRaw).replace(/[^\d]/g, '') : '';
                    const amount = formatAmount(currentTx.amount);
                    const currency = currentTx.currency || 'cUSD';
                    const invitationId = (currentTx as any).invitationId
                      || (currentTx as any).invitation_id
                      || (currentTx as any).idempotencyKey
                      || (transactionData as any)?.invitationId
                      || (transactionData as any)?.invitation_id
                      || (transactionData as any)?.idempotencyKey
                      || '';

                    const inviteLink = buildInviteLink({
                      username: userProfile?.username,
                      source: 'whatsapp',
                      invitationId,
                    });

                    const message = buildSendAndInviteShareMessage({ amount, currency, inviteLink });
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
                      } catch (_) { }
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
                    try {
                      const invitationId = (currentTx as any).invitationId
                        || (currentTx as any).invitation_id
                        || (currentTx as any).idempotencyKey
                        || (transactionData as any)?.invitationId
                        || (transactionData as any)?.invitation_id
                        || (transactionData as any)?.idempotencyKey
                        || '';
                      const inviteLink = buildInviteLink({
                        username: userProfile?.username,
                        source: 'whatsapp',
                        invitationId,
                      });
                      const fallbackMessage = buildSendAndInviteShareMessage({
                        amount: formatAmount(currentTx.amount),
                        currency: currentTx.currency || 'cUSD',
                        inviteLink,
                      });
                      await Share.share({ message: fallbackMessage });
                    } catch (_) { }
                    setBanner({ variant: 'error', message: 'No se pudo abrir WhatsApp.' });
                  }
                }}
              >
                <WhatsAppLogo width={20} height={20} style={{ marginRight: 8 }} />
                <Text style={styles.shareButtonText}>Compartir invitación por WhatsApp</Text>
              </TouchableOpacity>
            </View>
          )}

          {showInvitationReclaim && (
            <View style={[styles.card, styles.reclaimCard]}>
              <View style={styles.invitationHeader}>
                <Icon name="rotate-ccw" size={24} color={colors.primary} />
                <Text style={[styles.invitationCardTitle, { color: colors.primary }]}>Invitación expirada</Text>
              </View>

              <Text style={styles.invitationCardText}>
                Tu amigo no reclamó estos fondos dentro de los 7 días. Puedes devolverlos a tu balance.
              </Text>

              <TouchableOpacity
                style={[styles.reclaimButton, reclaimingInvite && styles.reclaimButtonDisabled]}
                disabled={reclaimingInvite}
                onPress={handleReclaimInvite}
              >
                {reclaimingInvite ? (
                  <ActivityIndicator size="small" color={colors.white} style={{ marginRight: 8 }} />
                ) : (
                  <Icon name="corner-down-left" size={18} color={colors.white} style={{ marginRight: 8 }} />
                )}
                <Text style={styles.shareButtonText}>
                  {reclaimingInvite ? 'Devolviendo...' : 'Devolver fondos'}
                </Text>
              </TouchableOpacity>
            </View>
          )}

          {/* Supportive footnote — no fee marketing, just the mission line */}
          {(currentTx.type === 'received' || currentTx.type === 'send' || currentTx.type === 'sent' || currentTx.type === 'payroll') && (
            <Text style={styles.supportFootnote}>{supportCopy.transferLine}</Text>
          )}
          {currentTx.type === 'payment' && (
            <Text style={styles.supportFootnote}>{supportCopy.merchantLine}</Text>
          )}

          {/* Actions — primary CTA + utility rows in one card */}
          {(currentTx.type === 'received' || currentTx.type === 'send' || currentTx.type === 'sent' || currentTx.type === 'payroll') && (
                <TouchableOpacity
                  style={styles.primaryAction}
                  onPress={() => {
                    // Navigate to SendToFriend screen
                    const friendName = currentTx.type === 'received' ? displayFromName : displayToName;
                    const friendPhone = currentTx.type === 'received' ? senderPhone : recipientPhone;

                    // Debug logging to understand the data

                    // For navigation, we need to determine if this is a Confío user
                    // If it's an invited friend (non-Confío user), we shouldn't navigate
                    // Note: isInvitedFriend means they are NOT on Confío (invitation transaction)
                    if (currentTx.isInvitedFriend || currentTx.is_invited_friend) {
                      // This is a non-Confío friend, navigate differently
                      Alert.alert(
                        'Usuario no está en Confío',
                        'Este amigo aún no se ha unido a Confío. Debes esperar a que se registre para poder enviarle dinero nuevamente.',
                        [{ text: 'Entendido' }]
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


                      navigation.navigate('SendToFriend', {
                        friend: friendData,
                        tokenType: currentTx.currency.toLowerCase() === 'cusd' ? 'cusd' : 'confio'
                      });
                    }
                  }}
                >
                  <Icon name="user" size={16} color={colors.white} style={styles.actionIcon} />
                  <Text style={styles.primaryActionText}>
                    {currentTx.type === 'received' ? `Enviar a ${displayFromName}` : `Enviar de nuevo a ${displayToName}`}
                  </Text>
                </TouchableOpacity>
              )}

          <View style={styles.actionRowsCard}>
            {(currentTx.type === 'send' || currentTx.type === 'sent' || currentTx.type === 'received' || currentTx.type === 'payment') && (
            <>
              <TouchableOpacity
                onPress={() => {
                  navigation.navigate('TransactionReceipt', {
                    transaction: {
                      ...currentTx,
                      ...transactionData,
                      // Explicitly pass name fields for ALL types
                      senderName: currentTx.payerDisplayName || currentTx.senderDisplayName || currentTx.senderName || currentTx.from || currentTx.sender_name,
                      recipientName: currentTx.merchantDisplayName || currentTx.recipientDisplayName || currentTx.recipientName || currentTx.to || currentTx.recipient_name,
                      businessName: currentTx.businessName || currentTx.sender_name || 'Empresa',

                      // Payment specific rich data
                      payerBusiness: currentTx.payerBusiness || transactionData?.payerBusiness,
                      payerDisplayName: currentTx.payerDisplayName || transactionData?.payerDisplayName,
                      merchantBusiness: currentTx.merchantBusiness || transactionData?.merchantBusiness,
                      merchantDisplayName: currentTx.merchantDisplayName || transactionData?.merchantDisplayName,

                      // Internal ID for verification QR code (User Request)
                      verificationId: resolvedInternalId || (currentTx as any).itemId || currentTx.id,
                      // Keep original hash logic for display
                      transactionHash: currentTx.transactionId || transactionData?.transactionId || currentTx.transactionHash,
                    },
                    type: currentTx.type === 'payment' ? 'payment' : 'transfer'
                  });
                }}
                style={styles.actionRow}
                accessibilityRole="button"
                accessibilityLabel="Ver comprobante oficial"
              >
                <View style={[styles.actionRowIcon, { backgroundColor: colors.primarySoft }]}>
                  <Icon name="file-text" size={18} color={colors.primaryDark} />
                </View>
                <Text style={styles.actionRowLabel}>Ver comprobante oficial</Text>
                <Icon name="chevron-right" size={18} color={colors.text.light} />
              </TouchableOpacity>
              <View style={styles.rowDivider} />
            </>
          )}
            <TouchableOpacity
              onPress={() => setShowBlockchainDetails(true)}
              style={styles.actionRow}
              accessibilityRole="button"
              accessibilityLabel="Ver detalles técnicos"
            >
              <View style={[styles.actionRowIcon, { backgroundColor: colors.neutralDark }]}>
                <Icon name="code" size={18} color={colors.text.secondary} />
              </View>
              <Text style={styles.actionRowLabel}>Ver detalles técnicos</Text>
              <Icon name="chevron-right" size={18} color={colors.text.light} />
            </TouchableOpacity>
          </View>
        </View>
      </ScrollView>

      {/* Technical Details Modal */}
      <Modal
        visible={showBlockchainDetails}
        transparent
        animationType="fade"
        onRequestClose={() => setShowBlockchainDetails(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Detalles técnicos</Text>
              <TouchableOpacity onPress={() => setShowBlockchainDetails(false)} style={styles.headerButton} accessibilityRole="button" accessibilityLabel="Cerrar">
                <Icon name="x" size={20} color={colors.dark} />
              </TouchableOpacity>
            </View>
            <ScrollView style={styles.modalBody}>
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
                      const h = (currentTx.transactionHash || currentTx.hash || '').toString();
                      if (!h) return 'N/D';
                      return h.replace(/(.{10}).+(.{6})/, '$1…$2');
                    })()}
                  </Text>
                </View>
                {(currentTx.fromAddress || currentTx.sender_address) && (
                  <View style={styles.technicalRow}>
                    <Text style={styles.technicalLabel}>De</Text>
                    <Text style={styles.technicalValue} numberOfLines={1}>
                      {(currentTx.fromAddress || currentTx.sender_address || '').toString()
                        .replace(/(.{10}).+(.{6})/, '$1…$2')}
                    </Text>
                  </View>
                )}
                {(currentTx.toAddress || currentTx.recipient_address) && (
                  <View style={styles.technicalRow}>
                    <Text style={styles.technicalLabel}>Para</Text>
                    <Text style={styles.technicalValue} numberOfLines={1}>
                      {(currentTx.toAddress || currentTx.recipient_address || '').toString()
                        .replace(/(.{10}).+(.{6})/, '$1…$2')}
                    </Text>
                  </View>
                )}
                <View style={styles.technicalRow}>
                  <Text style={styles.technicalLabel}>Monto</Text>
                  <Text style={styles.technicalValue}>{formatAmount(currentTx.amount)} {currentTx.currency || 'cUSD'}</Text>
                </View>
              </View>

              <TouchableOpacity
                style={[styles.explorerButton, { backgroundColor: colors.secondary }]}
                onPress={async () => {
                  try {
                    const txid = (currentTx.transactionHash || currentTx.hash || '').toString();
                    if (!txid) {
                      Alert.alert('Sin hash', 'Aún no hay hash de transacción disponible.');
                      return;
                    }
                    const base = __DEV__ ? 'https://testnet.explorer.perawallet.app' : 'https://explorer.perawallet.app';
                    const url = `${base}/tx/${encodeURIComponent(txid)}`;
                    await Linking.openURL(url);
                  } catch (e) {
                    Alert.alert('Error', 'No se pudo abrir Pera Explorer.');
                  }
                }}
              >
                <Icon name="external-link" size={16} color={colors.white} style={styles.explorerIcon} />
                <Text style={styles.explorerButtonText}>Abrir en Pera Explorer</Text>
              </TouchableOpacity>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </View>
  );
};
