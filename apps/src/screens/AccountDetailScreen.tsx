import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  TextInput,
  Modal,
  Platform,
  Image,
  RefreshControl,
  FlatList,
  SectionList,
  Animated,
  ActivityIndicator,
  Dimensions,
  Vibration,
  Pressable,
  Alert,
  Linking,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RouteProp } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';
import { Header } from '../navigation/Header';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import USDCLogo from '../assets/png/USDC.png';
import { useNumberFormat } from '../utils/numberFormatting';
import { useQuery } from '@apollo/client';
import { GET_SEND_TRANSACTIONS_BY_ACCOUNT, GET_PAYMENT_TRANSACTIONS_BY_ACCOUNT, GET_UNIFIED_TRANSACTIONS } from '../apollo/queries';
import { TransactionItemSkeleton } from '../components/SkeletonLoader';
import moment from 'moment';
import 'moment/locale/es';
import { useAccount } from '../contexts/AccountContext';
import * as Keychain from 'react-native-keychain';
import { useContactNameSync } from '../hooks/useContactName';

// Color palette
const colors = {
  primary: '#34D399', // emerald-400
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
  text: {
    primary: '#1F2937', // gray-800
    secondary: '#6B7280', // gray-500
  },
};

// Keychain constants for storing balance visibility
const PREFERENCES_KEYCHAIN_SERVICE = 'com.confio.preferences';
const ACCOUNT_BALANCE_VISIBILITY_PREFIX = 'account_balance_visibility_';

type AccountDetailScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;
type AccountDetailScreenRouteProp = RouteProp<MainStackParamList, 'AccountDetail'>;

interface Transaction {
  type: 'received' | 'sent' | 'exchange' | 'payment';
  from?: string;
  to?: string;
  fromPhone?: string;
  toPhone?: string;
  amount: string;
  currency: string;
  date: string;
  time: string;
  status: string;
  hash: string;
  isInvitation?: boolean;
  invitationClaimed?: boolean;
  invitationReverted?: boolean;
  invitationExpiresAt?: string;
  senderAddress?: string;
  recipientAddress?: string;
}

// Set Spanish locale for moment
moment.locale('es');

const { width: screenWidth } = Dimensions.get('window');

interface TransactionSection {
  title: string;
  data: Transaction[];
}

export const AccountDetailScreen = () => {
  const navigation = useNavigation<AccountDetailScreenNavigationProp>();
  const route = useRoute<AccountDetailScreenRouteProp>();
  const { formatNumber, formatCurrency } = useNumberFormat();
  const { activeAccount } = useAccount();
  const [showBalance, setShowBalance] = useState(true);
  const [showExchangeModal, setShowExchangeModal] = useState(false);
  const [exchangeAmount, setExchangeAmount] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [transactionLimit, setTransactionLimit] = useState(10);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasReachedEnd, setHasReachedEnd] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [showHelpModal, setShowHelpModal] = useState(false);
  const [showMoreOptionsModal, setShowMoreOptionsModal] = useState(false);
  
  // Save balance visibility preference for this account type
  const saveBalanceVisibility = async (isVisible: boolean) => {
    try {
      // Use account type in the service name for proper isolation
      const service = `${PREFERENCES_KEYCHAIN_SERVICE}.${route.params.accountType}`;
      await Keychain.setInternetCredentials(
        service,
        'balance_visibility',
        isVisible.toString()
      );
    } catch (error) {
      console.error('Error saving balance visibility preference:', error);
    }
  };

  // Load balance visibility preference for this account type
  const loadBalanceVisibility = async () => {
    try {
      // Use account type in the service name for proper isolation
      const service = `${PREFERENCES_KEYCHAIN_SERVICE}.${route.params.accountType}`;
      const result = await Keychain.getInternetCredentials(service);
      
      if (result && result.password) {
        setShowBalance(result.password === 'true');
      }
    } catch (error) {
      // No saved preference, default to showing balance
      console.log('No saved balance visibility preference for account:', route.params.accountType);
    }
  };

  // Toggle balance visibility and save preference
  const toggleBalanceVisibility = () => {
    const newVisibility = !showBalance;
    setShowBalance(newVisibility);
    saveBalanceVisibility(newVisibility);
  };
  
  // Animation values
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const searchAnim = useRef(new Animated.Value(0)).current;

  // Account data from navigation params
  const accountAddress = route.params.accountAddress || '';
  const account = {
    name: route.params.accountName,
    symbol: route.params.accountSymbol,
    balance: route.params.accountBalance,
    balanceHidden: "•••••••",
    color: route.params.accountType === 'cusd' ? colors.primary : colors.secondary,
    textColor: route.params.accountType === 'cusd' ? colors.primaryText : colors.secondaryText,
    address: accountAddress,
    addressShort: accountAddress ? `${accountAddress.slice(0, 6)}...${accountAddress.slice(-6)}` : '',
    exchangeRate: "1 USDC = 1 cUSD",
    description: route.params.accountType === 'cusd' 
      ? "Moneda estable respaldada 1:1 por dólares estadounidenses (USD)"
              : "Moneda de gobernanza de Confío"
  };

  // USDC balance data (shown only for cUSD account)
  const usdcAccount = route.params.accountType === 'cusd' ? {
    name: "USD Coin",
    symbol: "USDC",
    balance: "458.22",
    balanceHidden: "•••••••",
    description: "Para usuarios avanzados - depósito directo vía Sui Blockchain"
  } : null;

  // Get real transaction data from GraphQL
  const { data: sendTransactionsData, loading: sendLoading, refetch: refetchSend, fetchMore: fetchMoreSend } = useQuery(GET_SEND_TRANSACTIONS_BY_ACCOUNT, {
    variables: {
      accountType: 'personal', // Use 'personal' to match backend account_type field
      accountIndex: 0, // Default account index
      limit: transactionLimit
    }
  });

  const { data: paymentTransactionsData, loading: paymentLoading, refetch: refetchPayment, fetchMore: fetchMorePayment } = useQuery(GET_PAYMENT_TRANSACTIONS_BY_ACCOUNT, {
    variables: {
      accountType: 'personal', // Use 'personal' to match backend account_type field
      accountIndex: 0, // Default account index
      limit: transactionLimit
    }
  });

  // NEW: Unified transactions query (replaces the two above)
  const { data: unifiedTransactionsData, loading: unifiedLoading, refetch: refetchUnified } = useQuery(GET_UNIFIED_TRANSACTIONS, {
    variables: { 
      accountType: 'personal',
      accountIndex: 0,
      limit: transactionLimit,
      offset: 0,
      tokenTypes: route.params.accountType === 'cusd' ? ['cUSD', 'CUSD'] : ['CONFIO']
    },
    skip: false // Enable unified transactions
  });

  // Animation entrance
  useEffect(() => {
    Animated.timing(fadeAnim, {
      toValue: 1,
      duration: 400,
      useNativeDriver: true,
    }).start();
  }, [fadeAnim]);
  
  // Load balance visibility preference on mount
  useEffect(() => {
    loadBalanceVisibility();
  }, [route.params.accountType]);
  
  // Search animation
  useEffect(() => {
    Animated.timing(searchAnim, {
      toValue: showSearch ? 1 : 0,
      duration: 300,
      useNativeDriver: true,
    }).start();
  }, [showSearch, searchAnim]);
  
  // Pull to refresh handler
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    if (Platform.OS === 'ios') {
      Vibration.vibrate(10);
    }
    
    try {
      await Promise.all([
        refetchSend(),
        refetchPayment(),
        refetchUnified(),
      ]);
      setTransactionLimit(10);
      setHasReachedEnd(false);
    } catch (error) {
      console.error('Error refreshing transactions:', error);
    } finally {
      setRefreshing(false);
    }
  }, [refetchSend, refetchPayment, refetchUnified]);

  // NEW: Transform unified transactions into the format expected by the UI
  const formatUnifiedTransactions = () => {
    const allTransactions: Transaction[] = [];

    if (unifiedTransactionsData?.unifiedTransactions) {
      unifiedTransactionsData.unifiedTransactions.forEach((tx: any) => {
        // Determine transaction type based on both transactionType and direction
        let type: 'sent' | 'received' | 'payment' = 'sent';
        if (tx.transactionType.toLowerCase() === 'payment') {
          type = 'payment';
        } else {
          type = tx.direction === 'sent' ? 'sent' : 'received';
        }
        
        // Fix invitation detection: if we have a counterpartyUser, it's not an invitation
        let isActualInvitation = tx.isInvitation || false;
        if (isActualInvitation && tx.counterpartyUser && tx.counterpartyUser.id) {
          // If there's a counterparty user, this is not really an invitation
          console.log('[AccountDetail] Correcting invitation flag - counterparty user exists:', tx.counterpartyUser.id);
          isActualInvitation = false;
        }
        
        // Debug logging
        console.log('[AccountDetail] Transaction:', {
          id: tx.id,
          type: type,
          direction: tx.direction,
          displayCounterparty: tx.displayCounterparty,
          senderPhone: tx.senderPhone,
          counterpartyPhone: tx.counterpartyPhone,
          isInvitation: tx.isInvitation,
          isActualInvitation: isActualInvitation,
          senderAddress: tx.senderAddress,
          counterpartyAddress: tx.counterpartyAddress,
          counterpartyUser: tx.counterpartyUser
        });
        
        // For proper contact name lookup, we need to pass the phone numbers
        // The displayCounterparty is the DB name, but we want local contact names
        allTransactions.push({
          type,
          from: tx.direction === 'received' ? tx.displayCounterparty : undefined,
          to: tx.direction === 'sent' ? tx.displayCounterparty : undefined,
          fromPhone: tx.direction === 'received' ? tx.senderPhone : undefined,
          toPhone: tx.direction === 'sent' ? tx.counterpartyPhone : undefined,
          amount: tx.displayAmount,
          currency: tx.tokenType === 'CUSD' ? 'cUSD' : tx.tokenType,
          date: tx.createdAt, // Keep full timestamp for proper sorting
          time: new Date(tx.createdAt).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }),
          status: tx.status.toLowerCase() === 'confirmed' ? 'completed' : 'pending',
          hash: tx.transactionHash || 'pending',
          isInvitation: isActualInvitation,
          invitationClaimed: tx.invitationClaimed || false,
          invitationReverted: tx.invitationReverted || false,
          invitationExpiresAt: tx.invitationExpiresAt,
          senderAddress: tx.senderAddress,
          recipientAddress: tx.counterpartyAddress // Note: unified view uses counterpartyAddress
        });
      });
    }
    
    // Don't sort here - rely on server ordering which is more accurate
    return allTransactions;
  };

  // LEGACY: Transform real transactions into the format expected by the UI (backup)
  const formatTransactions = () => {
    const allTransactions: Transaction[] = [];
    // Handle both cUSD and CUSD variations
    const currentTokenTypes = route.params.accountType === 'cusd' ? ['cUSD', 'CUSD'] : ['CONFIO'];

    // Add send transactions - filter by token type
    if (sendTransactionsData?.sendTransactionsByAccount) {
      sendTransactionsData.sendTransactionsByAccount
        .filter((tx: any) => currentTokenTypes.includes(tx.tokenType))
        .forEach((tx: any) => {
          const currentUserIsSender = tx.senderAddress === account.address;
          
          allTransactions.push({
            type: currentUserIsSender ? 'sent' : 'received',
            from: currentUserIsSender ? undefined : (tx.senderDisplayName || ''),
            to: currentUserIsSender ? (tx.recipientDisplayName || '') : undefined,
            amount: currentUserIsSender ? `-${tx.amount}` : `+${tx.amount}`,
            currency: tx.tokenType === 'CUSD' ? 'cUSD' : tx.tokenType,
            date: new Date(tx.createdAt).toISOString().split('T')[0],
            time: new Date(tx.createdAt).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }),
            status: tx.status.toLowerCase() === 'confirmed' ? 'completed' : 'pending',
            hash: tx.transactionHash || 'pending'
          });
        });
    }

    // Add payment transactions - filter by token type
    if (paymentTransactionsData?.paymentTransactionsByAccount) {
      paymentTransactionsData.paymentTransactionsByAccount
        .filter((tx: any) => currentTokenTypes.includes(tx.tokenType))
        .forEach((tx: any) => {
          const currentUserIsPayer = tx.payerAddress === account.address;
          const currentUserIsMerchant = tx.merchantAddress === account.address;
          
          allTransactions.push({
            type: 'payment',
            from: currentUserIsMerchant ? (tx.payerDisplayName || '') : undefined,
            to: currentUserIsPayer ? (tx.merchantDisplayName || '') : undefined,
            amount: currentUserIsPayer ? `-${tx.amount}` : `+${tx.amount}`,
            currency: tx.tokenType === 'CUSD' ? 'cUSD' : tx.tokenType,
            date: new Date(tx.createdAt).toISOString().split('T')[0],
            time: new Date(tx.createdAt).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }),
            status: tx.status.toLowerCase() === 'confirmed' ? 'completed' : 'pending',
            hash: tx.transactionHash || 'pending'
          });
        });
    }

    // Sort by date (newest first)
    return allTransactions.sort((a, b) => new Date(b.date + ' ' + b.time).getTime() - new Date(a.date + ' ' + a.time).getTime());
  };

  // Helper functions for transaction display
  const getTransactionTitle = (transaction: Transaction) => {
    switch(transaction.type) {
      case 'received':
        return `Recibido de ${transaction.from}`;
      case 'sent':
        return `Enviado a ${transaction.to}`;
      case 'exchange':
        return `Intercambio ${transaction.from} → ${transaction.to}`;
      case 'payment':
        // If amount is positive, it's a payment received
        return transaction.amount.startsWith('+') 
          ? `Pago recibido de ${transaction.from}` 
          : `Pago a ${transaction.to}`;
      default:
        return 'Transacción';
    }
  };

  const getTransactionIcon = (transaction: Transaction) => {
    switch(transaction.type) {
      case 'received':
        return <Icon name="arrow-down" size={20} color="#10B981" />;
      case 'sent':
        return <Icon name="arrow-up" size={20} color="#EF4444" />;
      case 'exchange':
        return <Icon name="refresh-cw" size={20} color="#3B82F6" />;
      case 'payment':
        return <Icon name="shopping-bag" size={20} color="#8B5CF6" />;
      default:
        return <Icon name="arrow-up" size={20} color="#6B7280" />;
    }
  };

  // Use unified transactions if available, fallback to legacy format
  const transactions = unifiedTransactionsData ? formatUnifiedTransactions() : formatTransactions();
  
  // Filter transactions based on search query
  const filteredTransactions = useMemo(() => {
    if (!searchQuery) return transactions;
    
    const query = searchQuery.toLowerCase();
    return transactions.filter(tx => {
      const title = getTransactionTitle(tx).toLowerCase();
      const amount = tx.amount.toLowerCase();
      const currency = tx.currency.toLowerCase();
      const hash = tx.hash.toLowerCase();
      const date = moment(tx.date).format('DD/MM/YYYY').toLowerCase();
      const fromPhone = (tx.fromPhone || '').toLowerCase();
      const toPhone = (tx.toPhone || '').toLowerCase();
      
      return title.includes(query) || 
             amount.includes(query) ||
             currency.includes(query) ||
             hash.includes(query) ||
             date.includes(query) ||
             fromPhone.includes(query) ||
             toPhone.includes(query);
    });
  }, [transactions, searchQuery]);
  
  // Group transactions by date
  const groupedTransactions = useMemo((): TransactionSection[] => {
    const groups: { [key: string]: Transaction[] } = {};
    
    filteredTransactions.forEach(tx => {
      const date = moment(tx.date);
      let groupKey: string;
      let groupTitle: string;
      
      if (date.isSame(moment(), 'day')) {
        groupKey = 'today';
        groupTitle = 'Hoy';
      } else if (date.isSame(moment().subtract(1, 'day'), 'day')) {
        groupKey = 'yesterday';
        groupTitle = 'Ayer';
      } else if (date.isSame(moment(), 'week')) {
        groupKey = 'this_week';
        groupTitle = 'Esta semana';
      } else if (date.isSame(moment(), 'month')) {
        groupKey = date.format('YYYY-MM-DD');
        groupTitle = date.format('D [de] MMMM');
      } else {
        groupKey = date.format('YYYY-MM');
        groupTitle = date.format('MMMM YYYY');
      }
      
      if (!groups[groupKey]) {
        groups[groupKey] = [];
      }
      groups[groupKey].push(tx);
    });
    
    // Convert to sections array and sort by date
    return Object.entries(groups)
      .sort(([keyA], [keyB]) => {
        if (keyA === 'today') return -1;
        if (keyB === 'today') return 1;
        if (keyA === 'yesterday') return -1;
        if (keyB === 'yesterday') return 1;
        if (keyA === 'this_week') return -1;
        if (keyB === 'this_week') return 1;
        return keyB.localeCompare(keyA);
      })
      .map(([key, txs]) => ({
        title: key === 'today' ? 'Hoy' :
               key === 'yesterday' ? 'Ayer' :
               key === 'this_week' ? 'Esta semana' :
               moment(txs[0].date).format(key.includes('-') ? 'D [de] MMMM' : 'MMMM YYYY'),
        data: txs,
      }));
  }, [filteredTransactions]);
  
  // Check if we've reached the end after loading more
  React.useEffect(() => {
    if (loadingMore) return;
    
    // If we have transactions and the count is less than the limit,
    // it means we've loaded all available transactions
    const currentTokenTypes = route.params.accountType === 'cusd' ? ['cUSD', 'CUSD'] : ['CONFIO'];
    
    const sendTransactions = (sendTransactionsData?.sendTransactionsByAccount || [])
      .filter((tx: any) => currentTokenTypes.includes(tx.tokenType));
    const paymentTransactions = (paymentTransactionsData?.paymentTransactionsByAccount || [])
      .filter((tx: any) => currentTokenTypes.includes(tx.tokenType));
    
    const totalFilteredCount = sendTransactions.length + paymentTransactions.length;
    
    // If we have fewer filtered transactions than the limit, we've reached the end
    if (totalFilteredCount > 0 && totalFilteredCount < transactionLimit) {
      setHasReachedEnd(true);
    }
  }, [sendTransactionsData, paymentTransactionsData, transactionLimit, loadingMore, route.params.accountType]);

  const TransactionItem = ({ transaction }: { transaction: Transaction }) => {
    // Format the date properly
    const formattedDate = moment(transaction.date).format('DD/MM/YYYY');
    const formattedTime = transaction.time;
    
    // Get contact name for sender or recipient
    const phoneToCheck = transaction.type === 'received' ? transaction.fromPhone : transaction.toPhone;
    const fallbackName = transaction.type === 'received' ? transaction.from : transaction.to;
    const contactInfo = useContactNameSync(phoneToCheck, fallbackName);
    
    // Create enhanced transaction title with contact name
    const getEnhancedTransactionTitle = () => {
      let baseTitle = '';
      switch(transaction.type) {
        case 'received':
          baseTitle = `Recibido de ${contactInfo.displayName}`;
          break;
        case 'sent':
          baseTitle = `Enviado a ${contactInfo.displayName}`;
          break;
        case 'exchange':
          baseTitle = `Intercambio ${transaction.from} → ${transaction.to}`;
          break;
        case 'payment':
          if (transaction.amount.startsWith('+')) {
            baseTitle = `Pago recibido de ${contactInfo.displayName}`;
          } else {
            baseTitle = `Pago a ${contactInfo.displayName}`;
          }
          break;
        default:
          baseTitle = 'Transacción';
      }
      return baseTitle;
    };
    
    const navigation = useNavigation();
    
    const handlePress = () => {
      const params = {
        transactionType: transaction.type,
        transactionData: {
          type: transaction.type,
          from: transaction.type === 'received' || (transaction.type === 'payment' && transaction.amount.startsWith('+')) 
            ? contactInfo.displayName 
            : transaction.from,
          to: transaction.type === 'sent' || (transaction.type === 'payment' && transaction.amount.startsWith('-')) 
            ? contactInfo.displayName 
            : transaction.to,
          amount: transaction.amount,
          currency: transaction.currency,
          date: moment(transaction.date).format('DD/MM/YYYY'),
          time: transaction.time,
          timestamp: transaction.date,
          status: transaction.status,
          hash: transaction.hash,
          fromAddress: transaction.type === 'received' ? transaction.senderAddress : undefined,
          toAddress: transaction.type === 'sent' ? transaction.recipientAddress : undefined,
          fromPhone: transaction.fromPhone,
          toPhone: transaction.toPhone,
          note: transaction.type === 'received' ? 'Pago por almuerzo - Gracias! 🍕' : 
                transaction.type === 'sent' ? 'Pago servicios freelance' : undefined,
          avatar: transaction.from ? transaction.from.charAt(0) : 
                 transaction.to ? transaction.to.charAt(0) : undefined,
          location: transaction.type === 'payment' ? 'Av. Libertador, Caracas' : undefined,
          merchantId: transaction.type === 'payment' ? 'SUP001' : undefined,
          exchangeRate: transaction.type === 'exchange' ? '1 USDC = 1 cUSD' : undefined,
          isInvitedFriend: transaction.isInvitation || false // true means friend is NOT on Confío
        }
      };
      // @ts-ignore - Navigation type mismatch, but works at runtime
      navigation.navigate('TransactionDetail', params);
    };
    
    return (
      <TouchableOpacity style={[styles.transactionItem, transaction.isInvitation && styles.invitedTransactionItem]} onPress={handlePress}>
        <View style={styles.transactionIconContainer}>
          {getTransactionIcon(transaction)}
        </View>
        <View style={styles.transactionInfo}>
          <Text style={styles.transactionTitle}>{getEnhancedTransactionTitle()}</Text>
          <View style={styles.transactionSubtitleContainer}>
            <Text style={styles.transactionDate}>{formattedDate} • {formattedTime}</Text>
            {contactInfo.isFromContacts && contactInfo.originalName && (
              <Text style={styles.originalName}> • {contactInfo.originalName}</Text>
            )}
          </View>
          {transaction.isInvitation && transaction.type === 'sent' && (
            <Text style={styles.invitationNote}>
              {transaction.invitationClaimed ? '✅ Invitación reclamada' :
               transaction.invitationReverted ? '❌ Expiró - Fondos devueltos' :
               '⚠️ Tu amigo tiene 7 días para reclamar • Avísale ya'}
            </Text>
          )}
        </View>
        <View style={styles.transactionAmount}>
          <Text style={[
            styles.transactionAmountText,
            transaction.amount.startsWith('-') ? styles.negativeAmount : styles.positiveAmount
          ]}>
            {transaction.amount} {transaction.currency}
          </Text>
          <View style={styles.transactionStatus}>
            <Text style={styles.statusText}>Completado</Text>
            <View style={styles.statusDot} />
          </View>
        </View>
      </TouchableOpacity>
    );
  };

  const ExchangeModal = () => (
    <Modal
      visible={showExchangeModal}
      transparent
      animationType="fade"
      onRequestClose={() => setShowExchangeModal(false)}
    >
      <View style={styles.modalOverlay}>
        <View style={styles.modalContent}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Intercambiar USDC</Text>
            <TouchableOpacity onPress={() => setShowExchangeModal(false)}>
              <Icon name="arrow-left" size={24} color="#6b7280" />
            </TouchableOpacity>
          </View>

          <View style={styles.exchangeContainer}>
            <View style={styles.exchangeInputContainer}>
              <View style={styles.exchangeInputHeader}>
                <Text style={styles.exchangeInputLabel}>Desde</Text>
                <Text style={styles.exchangeInputLabel}>Disponible: {usdcAccount?.balance} USDC</Text>
              </View>
              <View style={styles.exchangeInput}>
                <TextInput
                  value={exchangeAmount}
                  onChangeText={setExchangeAmount}
                  placeholder="0.00"
                  keyboardType="decimal-pad"
                  style={styles.exchangeInputText}
                />
                <View style={styles.currencyBadge}>
                  <Image source={USDCLogo} style={styles.currencyLogo} />
                  <Text style={styles.currencyText}>USDC</Text>
                </View>
              </View>
            </View>

            <View style={styles.exchangeArrow}>
              <Icon name="arrow-down" size={20} color="#6b7280" />
            </View>

            <View style={styles.exchangeInputContainer}>
              <View style={styles.exchangeInputHeader}>
                <Text style={styles.exchangeInputLabel}>A</Text>
                <Text style={styles.exchangeInputLabel}>Tasa: 1 USDC = 1 cUSD</Text>
              </View>
              <View style={styles.exchangeInput}>
                <Text style={styles.exchangeInputText}>
                  {exchangeAmount || '0.00'}
                </Text>
                <View style={styles.currencyBadge}>
                  <Image source={cUSDLogo} style={styles.currencyLogo} />
                  <Text style={styles.currencyText}>cUSD</Text>
                </View>
              </View>
            </View>
          </View>

          <View style={styles.feeContainer}>
            <View style={styles.feeRow}>
              <Text style={styles.feeLabel}>Comisión de red</Text>
              <View style={styles.feeValueContainer}>
                <Text style={styles.feeValueFree}>Gratis</Text>
                <Text style={styles.feeValueNote}>• Cubierto por Confío</Text>
              </View>
            </View>
            <View style={styles.feeRow}>
              <Text style={styles.feeLabel}>Comisión de plataforma</Text>
              <Text style={styles.feeValue}>$0.00</Text>
            </View>
            <View style={styles.feeDivider} />
            <View style={styles.feeRow}>
              <Text style={styles.feeTotalLabel}>Total a recibir</Text>
              <Text style={styles.feeTotalValue}>
                {exchangeAmount || '0.00'} cUSD
              </Text>
            </View>
          </View>

          <TouchableOpacity
            style={[
              styles.exchangeButton,
              !exchangeAmount && styles.exchangeButtonDisabled
            ]}
            disabled={!exchangeAmount}
          >
            <Text style={styles.exchangeButtonText}>Confirmar Intercambio</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );

  const handleSend = () => {
    // @ts-ignore - Navigation type mismatch, but should work at runtime
    navigation.navigate('BottomTabs', { screen: 'Contacts' });
  };

  const loadMoreTransactions = async () => {
    if (loadingMore || hasReachedEnd) return;
    
    setLoadingMore(true);
    const newLimit = transactionLimit + 10;
    
    try {
      // Store the current filtered transaction count
      const prevTransactionCount = transactions.length;
      
      await Promise.all([
        fetchMoreSend({
          variables: { limit: newLimit },
          updateQuery: (prev, { fetchMoreResult }) => {
            if (!fetchMoreResult) return prev;
            return fetchMoreResult;
          }
        }),
        fetchMorePayment({
          variables: { limit: newLimit },
          updateQuery: (prev, { fetchMoreResult }) => {
            if (!fetchMoreResult) return prev;
            return fetchMoreResult;
          }
        })
      ]);
      
      // Update the limit to trigger re-render
      setTransactionLimit(newLimit);
      
      // We'll check if we got new transactions after the component re-renders
      // by comparing the transaction count in a useEffect
    } catch (error) {
      console.error('Error loading more transactions:', error);
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation}
        title={account.name}
        backgroundColor={account.color}
        isLight={true}
        showBackButton={true}
      />

      <ScrollView 
        style={styles.scrollView}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={account.color}
            colors={[account.color]}
          />
        }
      >
        {/* Balance Section */}
        <View style={[styles.balanceSection, { backgroundColor: account.color }]}>
          <View style={styles.balanceIconContainer}>
            <Image 
              source={route.params.accountType === 'cusd' ? cUSDLogo : CONFIOLogo} 
              style={styles.balanceLogo} 
            />
          </View>

          <View style={styles.balanceRow}>
            <Text style={styles.balanceText}>
              {showBalance ? `$${account.balance}` : account.balanceHidden}
            </Text>
            <TouchableOpacity onPress={toggleBalanceVisibility}>
              <Icon
                name={showBalance ? 'eye' : 'eye-off'}
                size={20}
                color="#ffffff"
                style={styles.eyeIcon}
              />
            </TouchableOpacity>
          </View>

          <Text style={styles.balanceDescription}>{account.description}</Text>
          <View style={styles.addressContainer}>
            <Text style={styles.addressText}>{account.addressShort}</Text>
            <TouchableOpacity>
              <Icon name="copy" size={16} color="#ffffff" style={styles.copyIcon} />
            </TouchableOpacity>
          </View>
        </View>

        {/* Action Buttons */}
        <View style={styles.actionButtonsContainer}>
          <View style={styles.actionButtons}>
            <TouchableOpacity 
              style={styles.actionButton}
              onPress={handleSend}
            >
              <View style={{
                width: 52,
                height: 52,
                borderRadius: 26,
                backgroundColor: colors.primary,
                justifyContent: 'center',
                alignItems: 'center',
                marginBottom: 8,
              }}>
                <Icon name="send" size={22} color="#ffffff" />
              </View>
              <Text style={styles.actionButtonText}>Enviar</Text>
            </TouchableOpacity>

            <TouchableOpacity 
              style={styles.actionButton}
              onPress={() => {
                // Navigate to USDCDeposit screen with proper token type
                navigation.navigate('USDCDeposit', { 
                  tokenType: route.params.accountType === 'cusd' ? 'cusd' : 'confio' 
                });
              }}
            >
              <View style={{
                width: 52,
                height: 52,
                borderRadius: 26,
                backgroundColor: colors.primary,
                justifyContent: 'center',
                alignItems: 'center',
                marginBottom: 8,
              }}>
                <Icon name="download" size={22} color="#ffffff" />
              </View>
              <Text style={styles.actionButtonText}>Recibir</Text>
            </TouchableOpacity>

            <TouchableOpacity 
              style={styles.actionButton}
              onPress={() => {
                // @ts-ignore - Navigation type mismatch, but should work at runtime
                const isBusinessAccount = activeAccount?.type?.toLowerCase() === 'business';
                navigation.navigate('BottomTabs', { 
                  screen: isBusinessAccount ? 'Charge' : 'Scan' 
                });
              }}
            >
              <View style={{
                width: 52,
                height: 52,
                borderRadius: 26,
                backgroundColor: colors.secondary,
                justifyContent: 'center',
                alignItems: 'center',
                marginBottom: 8,
              }}>
                <Icon name="shopping-bag" size={22} color="#ffffff" />
              </View>
              <Text style={styles.actionButtonText}>Pagar</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.actionButton}
              onPress={() => {
                // @ts-ignore - Navigation type mismatch, but should work at runtime
                navigation.navigate('BottomTabs', { screen: 'Exchange' });
              }}
            >
              <View style={{
                width: 52,
                height: 52,
                borderRadius: 26,
                backgroundColor: colors.accent,
                justifyContent: 'center',
                alignItems: 'center',
                marginBottom: 8,
              }}>
                <Icon name="refresh-cw" size={22} color="#ffffff" />
              </View>
              <Text style={styles.actionButtonText}>Intercambio</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* USDC Balance Section - Only show for cUSD account */}
        {route.params.accountType === 'cusd' && usdcAccount && (
          <View style={styles.usdcSection}>
            <View style={styles.sectionHeaderContainer}>
              <Text style={styles.sectionTitle}>Gestión Avanzada</Text>
              <TouchableOpacity style={styles.helpButton} onPress={() => setShowHelpModal(true)}>
                <Icon name="help-circle" size={18} color="#6b7280" />
              </TouchableOpacity>
            </View>
            
            <View style={styles.usdcCard}>
              <View style={styles.usdcHeader}>
                <View style={styles.usdcInfo}>
                  <View style={styles.usdcLogoContainer}>
                    <Image source={USDCLogo} style={styles.usdcLogo} />
                    <View style={styles.usdcBadge}>
                      <Text style={styles.usdcBadgeText}>Sui</Text>
                    </View>
                  </View>
                  <View style={styles.usdcTextContainer}>
                    <Text style={styles.usdcName}>{usdcAccount.name}</Text>
                    <Text style={styles.usdcDescription}>
                      Intercambia entre USDC y cUSD
                    </Text>
                  </View>
                </View>
                <View style={styles.usdcBalance}>
                  <Text style={styles.usdcBalanceText}>
                    {showBalance ? usdcAccount.balance : usdcAccount.balanceHidden}
                  </Text>
                  <Text style={styles.usdcSymbol}>{usdcAccount.symbol}</Text>
                </View>
              </View>

              <View style={styles.exchangeRateInfo}>
                <Icon name="info" size={14} color="#3b82f6" />
                <Text style={styles.exchangeRateText}>
                  1 USDC = 1 cUSD • Sin comisión
                </Text>
              </View>

              <View style={styles.usdcActions}>
                <TouchableOpacity 
                  style={styles.usdcActionButton}
                  onPress={() => navigation.navigate('USDCDeposit', { tokenType: 'usdc' })}
                >
                  <Icon name="download" size={16} color="#3b82f6" style={styles.actionIcon} />
                  <View style={styles.actionTextContainer}>
                    <Text style={styles.usdcActionButtonText}>Depositar</Text>
                    <Text style={styles.usdcActionSubtext}>Recibe desde Sui</Text>
                  </View>
                </TouchableOpacity>
                
                <TouchableOpacity
                  style={[styles.usdcActionButton, styles.usdcSecondaryButton]}
                  onPress={() => setShowExchangeModal(true)}
                >
                  <Icon name="refresh-cw" size={16} color="#fff" style={styles.actionIcon} />
                  <View style={styles.actionTextContainer}>
                    <Text style={[styles.usdcActionButtonText, { color: '#ffffff' }]}>
                      Convertir
                    </Text>
                    <Text style={[styles.usdcActionSubtext, { color: 'rgba(255,255,255,0.8)' }]}>
                      A cUSD
                    </Text>
                  </View>
                </TouchableOpacity>
                
                <TouchableOpacity
                  style={styles.usdcMoreButton}
                  onPress={() => setShowMoreOptionsModal(true)}
                >
                  <Icon name="more-horizontal" size={20} color="#6b7280" />
                </TouchableOpacity>
              </View>
            </View>
            
            <Text style={styles.usdcDisclaimer}>
              Para usuarios avanzados • Requiere conocimiento de wallets Sui
            </Text>
          </View>
        )}

        {/* Enhanced Transactions Section */}
        <Animated.View 
          style={[
            styles.transactionsSection,
            {
              opacity: fadeAnim,
              transform: [
                {
                  translateY: fadeAnim.interpolate({
                    inputRange: [0, 1],
                    outputRange: [20, 0],
                  })
                }
              ]
            }
          ]}
        >
          <View style={styles.transactionsHeader}>
            <Text style={styles.transactionsTitle}>Historial de transacciones</Text>
            <View style={styles.transactionsFilters}>
              <TouchableOpacity 
                style={[styles.filterButton, showSearch && styles.filterButtonActive]}
                onPress={() => setShowSearch(!showSearch)}
              >
                <Icon name="search" size={16} color={showSearch ? account.textColor : "#6b7280"} />
              </TouchableOpacity>
              <TouchableOpacity style={styles.filterButton}>
                <Icon name="filter" size={16} color="#6b7280" />
              </TouchableOpacity>
            </View>
          </View>

          {/* Search Bar */}
          {showSearch && (
            <Animated.View 
              style={[
                styles.searchContainer,
                {
                  opacity: searchAnim,
                  transform: [
                    {
                      translateY: searchAnim.interpolate({
                        inputRange: [0, 1],
                        outputRange: [-10, 0],
                      })
                    }
                  ]
                }
              ]}
            >
              <Icon name="search" size={18} color="#9ca3af" style={styles.searchIcon} />
              <TextInput
                style={styles.searchInput}
                placeholder="Buscar transacciones..."
                placeholderTextColor="#9ca3af"
                value={searchQuery}
                onChangeText={setSearchQuery}
                autoCapitalize="none"
                autoCorrect={false}
              />
              {searchQuery.length > 0 && (
                <TouchableOpacity onPress={() => setSearchQuery('')}>
                  <Icon name="x" size={18} color="#9ca3af" />
                </TouchableOpacity>
              )}
            </Animated.View>
          )}

          <View style={styles.transactionsList}>
            {(sendLoading || paymentLoading || unifiedLoading) ? (
              <>
                <TransactionItemSkeleton />
                <TransactionItemSkeleton />
                <TransactionItemSkeleton />
              </>
            ) : filteredTransactions.length === 0 ? (
              <View style={styles.emptyTransactionsContainer}>
                <Icon name={searchQuery ? "search" : "inbox"} size={48} color="#e5e7eb" />
                <Text style={styles.emptyTransactionsText}>
                  {searchQuery ? "No se encontraron transacciones" : "No hay transacciones aún"}
                </Text>
                <Text style={styles.emptyTransactionsSubtext}>
                  {searchQuery 
                    ? "Intenta con otros términos de búsqueda" 
                    : "Tus transacciones aparecerán aquí cuando realices envíos o pagos"}
                </Text>
                {!searchQuery && (
                  <TouchableOpacity 
                    style={styles.emptyActionButton}
                    onPress={handleSend}
                  >
                    <Icon name="send" size={16} color="#fff" />
                    <Text style={styles.emptyActionButtonText}>Hacer mi primera transacción</Text>
                  </TouchableOpacity>
                )}
              </View>
            ) : (
              <>
                {/* Grouped Transactions */}
                {groupedTransactions.map((section, sectionIndex) => (
                  <View key={sectionIndex}>
                    <Text style={styles.sectionHeader}>{section.title}</Text>
                    {section.data.map((transaction, index) => (
                      <TransactionItem 
                        key={`${sectionIndex}-${index}`} 
                        transaction={transaction} 
                      />
                    ))}
                  </View>
                ))}
              </>
            )}
          </View>

          {filteredTransactions.length > 0 && !hasReachedEnd && !searchQuery && (
            <TouchableOpacity 
              style={styles.viewMoreButton}
              onPress={loadMoreTransactions}
              disabled={loadingMore}
            >
              {loadingMore ? (
                <ActivityIndicator size="small" color={account.color} />
              ) : (
                <Text style={[styles.viewMoreButtonText, { color: account.textColor }]}>
                  Ver más transacciones
                </Text>
              )}
            </TouchableOpacity>
          )}
        </Animated.View>
      </ScrollView>

      <ExchangeModal />
      
      {/* Help Modal */}
      <Modal
        visible={showHelpModal}
        transparent
        animationType="fade"
        onRequestClose={() => setShowHelpModal(false)}
      >
        <View style={styles.modalOverlay}>
          <TouchableOpacity 
            style={styles.modalBackdrop} 
            activeOpacity={1}
            onPress={() => setShowHelpModal(false)}
          />
          <View style={styles.helpModalContent}>
            <View style={styles.helpModalHeader}>
              <Text style={styles.helpModalTitle}>¿Qué es la Gestión Avanzada?</Text>
              <TouchableOpacity onPress={() => setShowHelpModal(false)}>
                <Icon name="x" size={24} color="#6b7280" />
              </TouchableOpacity>
            </View>
            
            <ScrollView 
              style={styles.helpModalBody}
              contentContainerStyle={styles.helpModalScrollContent}
              showsVerticalScrollIndicator={true}
              bounces={true}
            >
              <View style={styles.helpSection}>
                <Icon name="info" size={20} color="#3b82f6" style={styles.helpIcon} />
                <View style={styles.helpTextContainer}>
                  <Text style={styles.helpSectionTitle}>USDC en Sui Network</Text>
                  <Text style={styles.helpSectionText}>
                    USDC es una moneda estable respaldada 1:1 por dólares estadounidenses. 
                    Puedes depositar USDC desde la red Sui y convertirlo a cUSD sin comisiones.
                  </Text>
                </View>
              </View>
              
              <View style={styles.helpSection}>
                <Icon name="shield" size={20} color="#10b981" style={styles.helpIcon} />
                <View style={styles.helpTextContainer}>
                  <Text style={styles.helpSectionTitle}>¿Por qué es seguro?</Text>
                  <Text style={styles.helpSectionText}>
                    • USDC está respaldado por Circle, una empresa regulada{'\n'}
                    • La conversión a cUSD es instantánea y sin pérdidas{'\n'}
                    • Tus fondos siempre están bajo tu control
                  </Text>
                </View>
              </View>
              
              <View style={styles.helpSection}>
                <Icon name="users" size={20} color="#8b5cf6" style={styles.helpIcon} />
                <View style={styles.helpTextContainer}>
                  <Text style={styles.helpSectionTitle}>¿Para quién es?</Text>
                  <Text style={styles.helpSectionText}>
                    Esta función es para usuarios avanzados que ya tienen USDC en wallets 
                    de Sui como Sui Wallet, Binance o exchanges compatibles.
                  </Text>
                </View>
              </View>
              
              <View style={styles.helpSection}>
                <Icon name="zap" size={20} color="#f59e0b" style={styles.helpIcon} />
                <View style={styles.helpTextContainer}>
                  <Text style={styles.helpSectionTitle}>Beneficios</Text>
                  <Text style={styles.helpSectionText}>
                    • Sin comisiones de conversión (cubierto por Confío){'\n'}
                    • Transacciones instantáneas{'\n'}
                    • Mayor liquidez para tus operaciones
                  </Text>
                </View>
              </View>
            </ScrollView>
            
            <TouchableOpacity 
              style={styles.helpModalButton}
              onPress={() => setShowHelpModal(false)}
            >
              <Text style={styles.helpModalButtonText}>Entendido</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
      
      {/* More Options Modal */}
      <Modal
        visible={showMoreOptionsModal}
        transparent
        animationType="slide"
        onRequestClose={() => setShowMoreOptionsModal(false)}
      >
        <TouchableOpacity 
          style={styles.modalOverlay} 
          activeOpacity={1} 
          onPress={() => setShowMoreOptionsModal(false)}
        >
          <View style={styles.moreOptionsModalContent}>
            <View style={styles.moreOptionsHandle} />
            
            <Text style={styles.moreOptionsTitle}>Más opciones</Text>
            
            <TouchableOpacity 
              style={styles.moreOptionsItem}
              onPress={() => {
                setShowMoreOptionsModal(false);
                navigation.navigate('USDCConversion');
              }}
            >
              <Icon name="refresh-cw" size={20} color="#1f2937" />
              <Text style={styles.moreOptionsItemText}>Convertir USDC ↔ cUSD</Text>
            </TouchableOpacity>
            
            <TouchableOpacity 
              style={styles.moreOptionsItem}
              onPress={() => {
                setShowMoreOptionsModal(false);
                navigation.navigate('USDCWithdraw');
              }}
            >
              <Icon name="arrow-up-circle" size={20} color="#1f2937" />
              <Text style={styles.moreOptionsItemText}>Retirar USDC a Sui</Text>
            </TouchableOpacity>
            
            <TouchableOpacity 
              style={styles.moreOptionsItem}
              onPress={() => {
                setShowMoreOptionsModal(false);
                navigation.navigate('USDCHistory');
              }}
            >
              <Icon name="clock" size={20} color="#1f2937" />
              <Text style={styles.moreOptionsItemText}>Historial de conversiones</Text>
            </TouchableOpacity>
            
            <TouchableOpacity 
              style={styles.moreOptionsItem}
              onPress={() => {
                setShowMoreOptionsModal(false);
                Alert.alert(
                  'Tutorial de USDC',
                  'Mira nuestro video tutorial sobre cómo usar USDC en Confío',
                  [
                    {
                      text: 'Cancelar',
                      style: 'cancel',
                    },
                    {
                      text: 'Ver Tutorial',
                      onPress: async () => {
                        // Replace with your actual TikTok video URL
                        const tiktokUrl = 'https://www.tiktok.com/@confioapp/video/YOUR_VIDEO_ID';
                        const canOpen = await Linking.canOpenURL(tiktokUrl);
                        if (canOpen) {
                          await Linking.openURL(tiktokUrl);
                        } else {
                          Alert.alert(
                            'Error',
                            'No se pudo abrir el video tutorial. Por favor, busca @confioapp en TikTok.'
                          );
                        }
                      },
                    },
                  ]
                );
              }}
            >
              <Icon name="play-circle" size={20} color="#1f2937" />
              <Text style={styles.moreOptionsItemText}>Ver tutorial</Text>
            </TouchableOpacity>
            
            <TouchableOpacity 
              style={[styles.moreOptionsItem, styles.moreOptionsCancelItem]}
              onPress={() => setShowMoreOptionsModal(false)}
            >
              <Text style={styles.moreOptionsCancelText}>Cancelar</Text>
            </TouchableOpacity>
          </View>
        </TouchableOpacity>
      </Modal>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.neutralDark,
  },
  scrollView: {
    flex: 1,
  },
  balanceSection: {
    paddingTop: 12,
    paddingBottom: 32,
    paddingHorizontal: 20,
    alignItems: 'center',
  },
  balanceIconContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: '#ffffff',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
    padding: 8,
  },
  balanceLogo: {
    width: '100%',
    height: '100%',
    resizeMode: 'contain',
  },
  balanceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  balanceText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#ffffff',
    marginRight: 8,
  },
  eyeIcon: {
    opacity: 0.8,
  },
  balanceDescription: {
    fontSize: 14,
    color: '#ffffff',
    opacity: 0.8,
    marginBottom: 4,
  },
  addressContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  addressText: {
    fontSize: 12,
    color: '#ffffff',
    opacity: 0.7,
    marginRight: 4,
  },
  copyIcon: {
    opacity: 0.8,
  },
  actionButtonsContainer: {
    marginTop: -16,
    paddingHorizontal: 16,
    marginBottom: 16,
  },
  actionButtons: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
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
  actionButton: {
    alignItems: 'center',
    flex: 1,
    paddingHorizontal: 4,
  },
  actionIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 8,
  },
  actionButtonText: {
    fontSize: 12,
    fontWeight: '500',
    color: '#1f2937',
    textAlign: 'center',
  },
  usdcSection: {
    paddingHorizontal: 16,
    marginBottom: 16,
  },
  sectionHeaderContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  helpButton: {
    padding: 4,
  },
  usdcCard: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.08,
        shadowRadius: 8,
      },
      android: {
        elevation: 3,
      },
    }),
  },
  usdcHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  usdcInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
    marginRight: 12,
  },
  usdcLogoContainer: {
    position: 'relative',
    marginRight: 12,
  },
  usdcLogo: {
    width: 48,
    height: 48,
    borderRadius: 24,
  },
  usdcBadge: {
    position: 'absolute',
    bottom: -2,
    right: -2,
    backgroundColor: '#3b82f6',
    borderRadius: 8,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderWidth: 2,
    borderColor: '#ffffff',
  },
  usdcBadgeText: {
    fontSize: 10,
    fontWeight: 'bold',
    color: '#ffffff',
  },
  usdcTextContainer: {
    flex: 1,
  },
  usdcName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1f2937',
    marginBottom: 2,
  },
  usdcDescription: {
    fontSize: 13,
    color: '#6b7280',
  },
  usdcBalance: {
    alignItems: 'flex-end',
  },
  usdcBalanceText: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  usdcSymbol: {
    fontSize: 12,
    color: '#6b7280',
  },
  exchangeRateInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#eff6ff',
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
    marginBottom: 12,
  },
  exchangeRateText: {
    fontSize: 12,
    color: '#3b82f6',
    marginLeft: 6,
    fontWeight: '500',
  },
  usdcActions: {
    flexDirection: 'row',
  },
  usdcActionButton: {
    flex: 1,
    flexDirection: 'row',
    backgroundColor: '#f3f4f6',
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 8,
  },
  usdcSecondaryButton: {
    backgroundColor: colors.accent,
  },
  usdcMoreButton: {
    backgroundColor: '#f3f4f6',
    width: 44,
    height: 44,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionIcon: {
    marginRight: 6,
  },
  actionTextContainer: {
    alignItems: 'flex-start',
  },
  usdcActionButtonText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#1f2937',
  },
  usdcActionSubtext: {
    fontSize: 11,
    color: '#6b7280',
    marginTop: 1,
  },
  usdcDisclaimer: {
    fontSize: 12,
    color: '#6b7280',
    textAlign: 'center',
    marginTop: 8,
  },
  transactionsSection: {
    paddingHorizontal: 16,
    paddingBottom: 24,
  },
  transactionsHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  transactionsTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  transactionsFilters: {
    flexDirection: 'row',
  },
  filterButton: {
    padding: 8,
    backgroundColor: '#ffffff',
    borderRadius: 8,
    marginLeft: 8,
  },
  transactionsList: {
  },
  transactionItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#ffffff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: '#f3f4f6',
  },
  invitedTransactionItem: {
    backgroundColor: '#fef2f2',
    borderColor: '#ef4444',
  },
  transactionIconContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  transactionInfo: {
    flex: 1,
  },
  transactionTitle: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1f2937',
  },
  transactionDate: {
    fontSize: 12,
    color: '#6b7280',
  },
  transactionSubtitleContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  originalName: {
    color: '#D1D5DB',
    fontSize: 11,
    fontStyle: 'italic',
  },
  invitationNote: {
    fontSize: 12,
    color: '#dc2626',
    marginTop: 2,
    fontWeight: 'bold',
  },
  transactionAmount: {
    alignItems: 'flex-end',
  },
  transactionAmountText: {
    fontSize: 16,
    fontWeight: 'bold',
  },
  positiveAmount: {
    color: '#10b981',
  },
  negativeAmount: {
    color: '#ef4444',
  },
  transactionStatus: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  statusText: {
    fontSize: 12,
    color: '#10b981',
    marginRight: 4,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#10b981',
  },
  viewMoreButton: {
    backgroundColor: '#ffffff',
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 24,
    alignItems: 'center',
    marginTop: 16,
    marginHorizontal: 16,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  viewMoreButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6b7280',
  },
  modalOverlay: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalBackdrop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
  },
  modalContent: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    width: '100%',
    maxWidth: 400,
    padding: 24,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 24,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  exchangeContainer: {
    marginBottom: 24,
  },
  exchangeInputContainer: {
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  exchangeInputHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  exchangeInputLabel: {
    fontSize: 12,
    color: '#6b7280',
  },
  exchangeInput: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  exchangeInputText: {
    flex: 1,
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  currencyBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    marginLeft: 8,
  },
  currencyIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 8,
  },
  currencyIconText: {
    color: '#ffffff',
    fontWeight: 'bold',
    fontSize: 12,
  },
  currencyLogo: {
    width: 32,
    height: 32,
    borderRadius: 16,
    marginRight: 8,
  },
  currencyText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1f2937',
  },
  exchangeArrow: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
    alignSelf: 'center',
    marginBottom: 16,
  },
  feeContainer: {
    marginBottom: 24,
  },
  feeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  feeLabel: {
    fontSize: 12,
    color: '#6b7280',
  },
  feeValue: {
    fontSize: 12,
    fontWeight: '500',
    color: '#1f2937',
  },
  feeValueContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  feeValueFree: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.primary,
    marginRight: 4,
  },
  feeValueNote: {
    fontSize: 11,
    color: '#6b7280',
    marginLeft: 4,
  },
  feeDivider: {
    height: 1,
    backgroundColor: '#e5e7eb',
    marginBottom: 12,
  },
  feeTotalLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1f2937',
  },
  feeTotalValue: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1f2937',
  },
  exchangeButton: {
    backgroundColor: colors.primary,
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  exchangeButtonDisabled: {
    opacity: 0.5,
  },
  exchangeButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  loadingContainer: {
    padding: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  loadingText: {
    fontSize: 14,
    color: '#6b7280',
    textAlign: 'center',
  },
  emptyTransactionsContainer: {
    padding: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptyTransactionsText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1f2937',
    marginTop: 16,
    marginBottom: 8,
    textAlign: 'center',
  },
  emptyTransactionsSubtext: {
    fontSize: 14,
    color: '#6b7280',
    textAlign: 'center',
    lineHeight: 20,
    maxWidth: 280,
  },
  searchContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#ffffff',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  searchIcon: {
    marginRight: 8,
  },
  searchInput: {
    flex: 1,
    fontSize: 14,
    color: '#1f2937',
    padding: 0,
  },
  sectionHeader: {
    fontSize: 13,
    fontWeight: '600',
    color: '#6b7280',
    marginTop: 16,
    marginBottom: 8,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  emptyActionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#34d399',
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 24,
    marginTop: 20,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 3,
  },
  emptyActionButtonText: {
    color: '#ffffff',
    fontSize: 14,
    fontWeight: '600',
    marginLeft: 8,
  },
  filterButtonActive: {
    backgroundColor: '#f3f4f6',
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  // Help Modal Styles
  helpModalContent: {
    backgroundColor: '#ffffff',
    borderRadius: 20,
    maxWidth: 380,
    width: '90%',
    height: '70%', // Fixed height to ensure scrolling works
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.15,
        shadowRadius: 12,
      },
      android: {
        elevation: 8,
      },
    }),
  },
  helpModalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#e5e7eb',
  },
  helpModalTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  helpModalBody: {
    flex: 1,
    marginBottom: 10,
  },
  helpModalScrollContent: {
    padding: 20,
    paddingBottom: 20,
  },
  helpSection: {
    flexDirection: 'row',
    marginBottom: 24,
  },
  helpIcon: {
    marginRight: 12,
    marginTop: 2,
  },
  helpTextContainer: {
    flex: 1,
  },
  helpSectionTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1f2937',
    marginBottom: 4,
  },
  helpSectionText: {
    fontSize: 14,
    color: '#6b7280',
    lineHeight: 20,
  },
  helpModalButton: {
    backgroundColor: colors.primary,
    paddingVertical: 14,
    borderRadius: 12,
    marginHorizontal: 20,
    marginTop: 10,
    marginBottom: 20,
    alignItems: 'center',
  },
  helpModalButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  // More Options Modal Styles
  moreOptionsModalContent: {
    backgroundColor: '#ffffff',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingBottom: Platform.OS === 'ios' ? 34 : 20,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: -4 },
        shadowOpacity: 0.1,
        shadowRadius: 8,
      },
      android: {
        elevation: 8,
      },
    }),
  },
  moreOptionsHandle: {
    width: 40,
    height: 4,
    backgroundColor: '#e5e7eb',
    borderRadius: 2,
    alignSelf: 'center',
    marginTop: 12,
    marginBottom: 20,
  },
  moreOptionsTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1f2937',
    paddingHorizontal: 20,
    marginBottom: 16,
  },
  moreOptionsItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 16,
    paddingHorizontal: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  moreOptionsItemText: {
    fontSize: 16,
    color: '#1f2937',
    marginLeft: 16,
  },
  moreOptionsCancelItem: {
    marginTop: 8,
    borderBottomWidth: 0,
    justifyContent: 'center',
  },
  moreOptionsCancelText: {
    fontSize: 16,
    color: '#6b7280',
    textAlign: 'center',
    fontWeight: '500',
  },
}); 