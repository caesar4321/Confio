import React, { useState, useRef, useEffect, useMemo, useCallback, memo } from 'react';
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
  Clipboard,
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
import { useQuery, useMutation } from '@apollo/client';
import { GET_UNIFIED_TRANSACTIONS, GET_CURRENT_ACCOUNT_TRANSACTIONS, GET_PRESALE_STATUS, GET_ACCOUNT_BALANCE } from '../apollo/queries';
import { REFRESH_ACCOUNT_BALANCE } from '../apollo/mutations';
// import { CONVERT_USDC_TO_CUSD, CONVERT_CUSD_TO_USDC } from '../apollo/mutations'; // Removed - handled in USDCConversion screen
import { TransactionItemSkeleton } from '../components/SkeletonLoader';
import moment from 'moment';
import 'moment/locale/es';
import { useAccount } from '../contexts/AccountContext';
import * as Keychain from 'react-native-keychain';
import { useContactNameSync } from '../hooks/useContactName';
import { TransactionFilterModal, TransactionFilters } from '../components/TransactionFilterModal';

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
  id?: string;
  type: 'received' | 'sent' | 'exchange' | 'payment' | 'conversion';
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
  description?: string;
  conversionType?: string;
  isExternalDeposit?: boolean;
  senderType?: string;
  secondaryCurrency?: string;
  p2pTradeId?: string;
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
  
  // Helper function to format transaction amounts to 2 decimal places
  const formatTransactionAmount = (amount: string): string => {
    // Remove any sign (+/-) temporarily
    const sign = amount.startsWith('-') ? '-' : amount.startsWith('+') ? '+' : '';
    const numericAmount = amount.replace(/^[+-]/, '');
    
    // Parse and format to 2 decimal places
    const parsedAmount = parseFloat(numericAmount);
    const formattedAmount = parsedAmount.toFixed(2);
    
    // Return with sign
    return sign + formattedAmount;
  };
  
  // Check if employee has permission to view balance
  const canViewBalance = !activeAccount?.isEmployee || activeAccount?.employeePermissions?.viewBalance;
  const [showBalance, setShowBalance] = useState(canViewBalance);
  const [refreshing, setRefreshing] = useState(false);
  const [transactionLimit, setTransactionLimit] = useState(20);
  const [transactionOffset, setTransactionOffset] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasReachedEnd, setHasReachedEnd] = useState(false);
  const [allTransactions, setAllTransactions] = useState<any[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [showHelpModal, setShowHelpModal] = useState(false);
  const [showMoreOptionsModal, setShowMoreOptionsModal] = useState(false);
  const [showFilterModal, setShowFilterModal] = useState(false);
  // const [showExchangeModal, setShowExchangeModal] = useState(false); // Removed - using USDCConversion screen directly
  // const [exchangeAmount, setExchangeAmount] = useState(''); // Removed - handled in USDCConversion screen
  // const [conversionDirection, setConversionDirection] = useState<'usdc_to_cusd' | 'cusd_to_usdc'>('usdc_to_cusd'); // Removed - handled in USDCConversion screen
  // const [isProcessingConversion, setIsProcessingConversion] = useState(false); // Removed - handled in USDCConversion screen
  const [transactionFilters, setTransactionFilters] = useState<TransactionFilters>({
    types: {
      sent: true,
      received: true,
      payment: true,
      exchange: true,
      conversion: true,
    },
    currencies: {
      cUSD: true,
      CONFIO: true,
      ...(activeAccount?.isEmployee ? {} : { USDC: true }),
    },
    status: {
      completed: true,
      pending: true,
    },
    timeRange: 'all',
    amountRange: {
      min: '',
      max: '',
    },
  });
  
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
  const toggleBalanceVisibility = useCallback(() => {
    const newVisibility = !showBalance;
    setShowBalance(newVisibility);
    saveBalanceVisibility(newVisibility);
  }, [showBalance, saveBalanceVisibility]);
  
  // Animation values
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const searchAnim = useRef(new Animated.Value(0)).current;

  // Fetch real-time balance for the account
  const { data: balanceData, refetch: refetchBalance } = useQuery(GET_ACCOUNT_BALANCE, {
    variables: { tokenType: route.params.accountType === 'cusd' ? 'cUSD' : 'CONFIO' },
    fetchPolicy: 'no-cache',
  });
  
  // Use real-time balance if available, otherwise fallback to route params
  const currentBalance = balanceData?.accountBalance || route.params.accountBalance;
  
  // Account data from navigation params
  const accountAddress = route.params.accountAddress || '';
  const account = {
    name: route.params.accountName,
    symbol: route.params.accountSymbol,
    balance: currentBalance,
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
  
  // Debug logging
  console.log('AccountDetailScreen - Account info:', {
    activeAccountType: activeAccount?.type,
    activeAccountIndex: activeAccount?.index,
    activeAccountAddress: activeAccount?.suiAddress,
    paramAddress: accountAddress,
    accountName: account.name,
    routeParams: {
      accountType: route.params.accountType,
      accountName: route.params.accountName
    }
  });

  // Fetch USDC balance for cUSD accounts (not for employees)
  const shouldFetchUSDC = route.params.accountType === 'cusd' && !activeAccount?.isEmployee;
  const { data: usdcBalanceData, loading: usdcLoading, error: usdcError, refetch: refetchUSDC } = useQuery(GET_ACCOUNT_BALANCE, {
    variables: { tokenType: 'USDC' },
    fetchPolicy: 'no-cache',
    skip: !shouldFetchUSDC,
  });

  // Parse USDC balance
  const usdcBalance = React.useMemo(() => 
    parseFloat(usdcBalanceData?.accountBalance || '0'), 
    [usdcBalanceData?.accountBalance]
  );

  // USDC balance data - HIDDEN for employees
  const usdcAccount = shouldFetchUSDC ? {
    name: "USD Coin",
    symbol: "USDC",
    balance: usdcBalance.toFixed(2),
    balanceHidden: "•••••••",
    description: "Para usuarios avanzados - depósito directo vía Sui Blockchain"
  } : null;
  
  // JWT-context-aware transactions query
  const queryVariables = {
    limit: transactionLimit,
    offset: 0, // Always start with offset 0 for initial query
    tokenTypes: route.params.accountType === 'cusd' ? 
      (activeAccount?.isEmployee ? ['cUSD', 'CUSD'] : ['cUSD', 'CUSD', 'USDC']) : 
      ['CONFIO']
  };
  
  console.log('AccountDetailScreen - JWT GraphQL query variables:', queryVariables);
  
  const { data: unifiedTransactionsData, loading: unifiedLoading, error: unifiedError, refetch: refetchUnified, fetchMore } = useQuery(GET_CURRENT_ACCOUNT_TRANSACTIONS, {
    variables: queryVariables,
    skip: false, // Enable unified transactions
    onCompleted: (data) => {
      console.log('AccountDetailScreen - JWT context query completed:', {
        hasData: !!data,
        transactionCount: data?.currentAccountTransactions?.length || 0
      });
    },
    onError: (error) => {
      console.error('AccountDetailScreen - Unified query error:', error);
    }
  });
  
  if (unifiedError) {
    console.error('AccountDetailScreen - Query error details:', unifiedError);
  }
  
  // Check if presale is globally active
  const { data: presaleStatusData } = useQuery(GET_PRESALE_STATUS, {
    fetchPolicy: 'cache-and-network',
  });
  const isPresaleActive = presaleStatusData?.isPresaleActive === true;

  // Refresh balance mutation for force-refreshing from blockchain
  const [refreshBalanceMutation] = useMutation(REFRESH_ACCOUNT_BALANCE);
  
  // Conversion mutations
  // const [convertUsdcToCusd] = useMutation(CONVERT_USDC_TO_CUSD); // Removed - handled in USDCConversion screen
  // const [convertCusdToUsdc] = useMutation(CONVERT_CUSD_TO_USDC); // Removed - handled in USDCConversion screen

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
  
  // Refetch transactions when active account changes
  useEffect(() => {
    if (activeAccount) {
      console.log('AccountDetailScreen - Active account changed, refetching transactions');
      refetchUnified();
    }
  }, [activeAccount?.id, activeAccount?.type, activeAccount?.index]);
  
  // Search animation
  useEffect(() => {
    Animated.timing(searchAnim, {
      toValue: showSearch ? 1 : 0,
      duration: 300,
      useNativeDriver: true,
    }).start();
  }, [showSearch, searchAnim]);
  
  // Listen for refresh trigger from navigation params
  useEffect(() => {
    // @ts-ignore - route params type
    if (route.params?.refreshTimestamp) {
      console.log('AccountDetailScreen - Refresh triggered from navigation');
      onRefresh();
    }
  }, [route.params, onRefresh]);
  
  // Pull to refresh handler
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    if (Platform.OS === 'ios') {
      Vibration.vibrate(10);
    }
    
    try {
      // First force refresh from blockchain
      const { data: refreshData } = await refreshBalanceMutation();
      
      if (refreshData?.refreshAccountBalance?.success) {
        console.log('AccountDetailScreen - Balances refreshed from blockchain:', refreshData.refreshAccountBalance.balances);
      }
      
      // Then refresh balance, USDC (if applicable), and transactions
      const promises = [
        refetchBalance(),
        refetchUnified({
          accountType: activeAccount?.type || 'personal',
          accountIndex: activeAccount?.index || 0,
          limit: 20,
          offset: 0,
          tokenTypes: route.params.accountType === 'cusd' ? 
        (activeAccount?.isEmployee ? ['cUSD', 'CUSD'] : ['cUSD', 'CUSD', 'USDC']) : 
        ['CONFIO']
        })
      ];
      
      // Add USDC refresh if applicable
      if (shouldFetchUSDC) {
        promises.push(refetchUSDC());
      }
      
      const [balanceResult, { data }] = await Promise.all(promises);
      setAllTransactions(data?.currentAccountTransactions || []);
      setTransactionLimit(20);
      setTransactionOffset(0);
      setHasReachedEnd(false);
    } catch (error) {
      console.error('Error refreshing transactions:', error);
    } finally {
      setRefreshing(false);
    }
  }, [refetchUnified, refetchBalance, activeAccount, route.params.accountType]);

  // NEW: Transform unified transactions into the format expected by the UI
  const formatUnifiedTransactions = () => {
    const formattedTransactions: Transaction[] = [];

    if (allTransactions.length > 0) {
      allTransactions.forEach((tx: any) => {
        // Determine transaction type based on both transactionType and direction
        let type: 'sent' | 'received' | 'payment' | 'conversion' | 'exchange' = 'sent';
        if (tx.transactionType.toLowerCase() === 'payment') {
          type = 'payment';
        } else if (tx.transactionType.toLowerCase() === 'conversion') {
          type = 'conversion';
        } else if (tx.transactionType.toLowerCase() === 'exchange') {
          type = 'exchange';
        } else {
          type = tx.direction === 'sent' ? 'sent' : 'received';
        }
        
        // Fix invitation detection: 
        // 1. If we have a counterpartyUser, it's not an invitation
        // 2. If it's marked as invitation but has no phone (external wallet), it's not a real invitation
        let isActualInvitation = tx.isInvitation || false;
        if (isActualInvitation && tx.counterpartyUser && tx.counterpartyUser.id) {
          // If there's a counterparty user, this is not really an invitation
          console.log('[AccountDetail] Correcting invitation flag - counterparty user exists:', tx.counterpartyUser.id);
          isActualInvitation = false;
        }
        // Check if it's an external wallet send (no phone number)
        if (isActualInvitation && tx.direction === 'sent' && !tx.counterpartyPhone) {
          console.log('[AccountDetail] Not an invitation - external wallet send (no phone)');
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
        // Debug payment transaction
        if (type === 'payment') {
          console.log('Unified payment transaction:', {
            id: tx.id,
            type,
            direction: tx.direction,
            displayCounterparty: tx.displayCounterparty,
            shouldSetFrom: (type === 'payment' && tx.direction === 'received'),
            shouldSetTo: (type === 'payment' && tx.direction === 'sent')
          });
        }
        
        // Handle conversion transactions
        const isConversion = type === 'conversion';
        
        // For conversions, prepare default values
        let conversionAmount = tx.amount; // Use raw amount, will be formatted below
        let conversionType: string | undefined;
        
        if (isConversion) {
          console.log('[Conversion Raw Data]', {
            id: tx.id,
            description: tx.description,
            conversionType: tx.conversionType,
            fromAmount: tx.fromAmount,
            toAmount: tx.toAmount,
            fromToken: tx.fromToken,
            toToken: tx.toToken,
            displayAmount: tx.displayAmount,
            tokenType: tx.tokenType
          });
          
          // Parse conversion type from description if server fields not available
          conversionType = tx.conversionType;
          console.log('[Conversion Type Detection]', { 
            txId: tx.id,
            txConversionType: tx.conversionType,
            description: tx.description,
            hasUSDC: tx.description?.includes('USDC'),
            hasCUSD: tx.description?.includes('cUSD'),
            hasArrow: tx.description?.includes('→')
          });
          if (!conversionType && tx.description) {
            // The description format is "Conversión: X USDC → Y cUSD"
            if (tx.description.includes('USDC →') && tx.description.includes('cUSD')) {
              conversionType = 'usdc_to_cusd';
            } else if (tx.description.includes('cUSD →') && tx.description.includes('USDC')) {
              conversionType = 'cusd_to_usdc';
            }
          }
          console.log('[Conversion Type Result]', { txId: tx.id, conversionType });
          
          // For cUSD account view, always show cUSD amount with proper sign
          if (conversionType === 'usdc_to_cusd') {
            // USDC to cUSD: gaining cUSD (+)
            const toAmount = tx.toAmount || (tx.description ? tx.description.match(/→\s*([\d.]+)\s*cUSD/)?.[1] : null);
            console.log('[Conversion USDC->cUSD]', { toAmount, fromAmount: tx.fromAmount, amount: tx.amount });
            const amount = parseFloat(String(toAmount || tx.fromAmount || tx.amount)).toFixed(2);
            conversionAmount = `+${amount}`;
          } else if (conversionType === 'cusd_to_usdc') {
            // cUSD to USDC: losing cUSD (-)
            console.log('[Conversion cUSD->USDC]', { fromAmount: tx.fromAmount, amount: tx.amount });
            const amount = parseFloat(String(tx.fromAmount || tx.amount)).toFixed(2);
            conversionAmount = `-${amount}`;
          } else {
            // Fallback: no conversion type detected, still format properly
            console.log('[Conversion Unknown Type]', { description: tx.description, amount: tx.amount });
            // Try to determine direction from token type
            const amount = parseFloat(String(tx.amount)).toFixed(2);
            if (tx.tokenType === 'USDC') {
              // If showing USDC amount, it's USDC to cUSD (gaining cUSD)
              conversionAmount = `+${amount}`;
            } else {
              // If showing cUSD amount, it's cUSD to USDC (losing cUSD)
              conversionAmount = `-${amount}`;
            }
          }
        }
        
        // Check if this is an external deposit
        const isExternalDeposit = type === 'received' && tx.senderType?.toLowerCase() === 'external';
        
        // Debug external deposits
        if (type === 'received' && tx.senderType) {
          console.log('[External Deposit Debug]', {
            id: tx.id,
            type,
            senderType: tx.senderType,
            isExternalDeposit,
            displayCounterparty: tx.displayCounterparty,
            senderAddress: tx.senderAddress,
          });
        }
        
        // Format the from field - truncate address if it's an external deposit
        let fromDisplay = undefined;
        let toDisplay = undefined;
        
        if (isConversion) {
          fromDisplay = conversionType === 'usdc_to_cusd' ? 'USDC' : conversionType === 'cusd_to_usdc' ? 'cUSD' : undefined;
          toDisplay = conversionType === 'usdc_to_cusd' ? 'cUSD' : conversionType === 'cusd_to_usdc' ? 'USDC' : undefined;
        } else if (type === 'exchange') {
          // For P2P exchanges, from is the seller, to is the buyer
          if (tx.direction === 'sent') {
            // User is seller (sending crypto)
            fromDisplay = 'Tú (vendedor)';
            toDisplay = tx.displayCounterparty || 'Comprador';
          } else {
            // User is buyer (receiving crypto)
            fromDisplay = tx.displayCounterparty || 'Vendedor';
            toDisplay = 'Tú (comprador)';
          }
        } else if ((type === 'payment' && tx.direction === 'received') || (type === 'received')) {
          fromDisplay = tx.displayCounterparty;
          // Truncate external wallet addresses
          if (isExternalDeposit && fromDisplay && fromDisplay.startsWith('0x') && fromDisplay.length > 20) {
            fromDisplay = `${fromDisplay.slice(0, 10)}...${fromDisplay.slice(-6)}`;
          }
        } else if ((type === 'payment' && tx.direction === 'sent') || (type === 'sent')) {
          toDisplay = tx.displayCounterparty;
        }
        
        const finalTransaction = {
          id: tx.id,
          type,
          from: fromDisplay,
          to: toDisplay,
          fromPhone: isConversion ? undefined : (tx.direction === 'received' ? tx.senderPhone : undefined),
          toPhone: isConversion ? undefined : (tx.direction === 'sent' ? tx.counterpartyPhone : undefined),
          amount: isConversion ? conversionAmount : tx.displayAmount,
          currency: isConversion ? (conversionType === 'usdc_to_cusd' ? 'USDC' : conversionType === 'cusd_to_usdc' ? 'cUSD' : undefined) : (tx.tokenType === 'CUSD' ? 'cUSD' : tx.tokenType),
          secondaryCurrency: isConversion ? (conversionType === 'usdc_to_cusd' ? 'cUSD' : conversionType === 'cusd_to_usdc' ? 'USDC' : undefined) : undefined,
          conversionType: conversionType || tx.conversionType,
          date: tx.createdAt, // Keep full timestamp for proper sorting
          time: new Date(tx.createdAt).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }),
          status: tx.status.toLowerCase() === 'confirmed' ? 'completed' : 'pending',
          hash: tx.transactionHash || 'pending',
          isInvitation: isActualInvitation,
          invitationClaimed: tx.invitationClaimed || false,
          invitationReverted: tx.invitationReverted || false,
          invitationExpiresAt: tx.invitationExpiresAt,
          senderAddress: tx.senderAddress,
          recipientAddress: tx.counterpartyAddress, // Note: unified view uses counterpartyAddress
          isExternalDeposit, // Add this flag for the UI to show the "Wallet externa" tag
          senderType: tx.senderType,
          description: isConversion ? tx.description : undefined,
          conversionType: isConversion ? conversionType : undefined,
          p2pTradeId: type === 'exchange' ? tx.p2pTradeId : undefined
        };
        
        // Debug final transaction for external deposits
        if (isExternalDeposit) {
          console.log('[External Deposit Final]', {
            from: finalTransaction.from,
            isExternalDeposit: finalTransaction.isExternalDeposit,
            senderType: finalTransaction.senderType,
          });
        }
        
        // Debug conversion amounts
        if (isConversion) {
          console.log('[Conversion Final]', {
            id: tx.id,
            amount: finalTransaction.amount,
            currency: finalTransaction.currency,
            conversionType: finalTransaction.conversionType,
            description: finalTransaction.description
          });
        }
        
        formattedTransactions.push(finalTransaction);
      });
    }
    
    // Don't sort here - rely on server ordering which is more accurate
    return formattedTransactions;
  };


  // Helper functions for transaction display
  const getTransactionTitle = (transaction: Transaction) => {
    // Debug payment transactions
    if (transaction.type === 'payment') {
      console.log('Getting title for payment transaction:', {
        type: transaction.type,
        from: transaction.from,
        to: transaction.to,
        amount: transaction.amount,
        startsWithPlus: transaction.amount.startsWith('+')
      });
    }
    
    switch(transaction.type) {
      case 'received':
        return `Recibido de ${transaction.from}`;
      case 'sent':
        return `Enviado a ${transaction.to}`;
      case 'exchange':
        return `Intercambio ${transaction.from} → ${transaction.to}`;
      case 'conversion':
        // Use conversionType field first, fallback to description parsing
        if (transaction.conversionType === 'usdc_to_cusd') {
          return 'Conversión USDC a cUSD';
        } else if (transaction.conversionType === 'cusd_to_usdc') {
          return 'Conversión cUSD a USDC';
        } else if (transaction.description) {
          // Fallback: parse from description
          if (transaction.description.includes('USDC →') && transaction.description.includes('cUSD')) {
            return 'Conversión USDC a cUSD';
          } else if (transaction.description.includes('cUSD →') && transaction.description.includes('USDC')) {
            return 'Conversión cUSD a USDC';
          }
        }
        return 'Conversión';
      case 'payment':
        // If amount is positive, it's a payment received
        return transaction.amount.startsWith('+') 
          ? `Pago recibido de ${transaction.from || 'Unknown'}` 
          : `Pago a ${transaction.to || 'Unknown'}`;
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
      case 'conversion':
        return <Icon name="repeat" size={20} color="#34D399" />;
      case 'payment':
        return <Icon name="shopping-bag" size={20} color="#8B5CF6" />;
      default:
        return <Icon name="arrow-up" size={20} color="#6B7280" />;
    }
  };

  // Use unified transactions if available, fallback to legacy format
  const transactions = formatUnifiedTransactions();
  
  // Debug which data source is being used
  console.log('AccountDetailScreen - Transaction source:', {
    usingUnified: !!unifiedTransactionsData,
    unifiedCount: unifiedTransactionsData?.currentAccountTransactions?.length || 0,
    allTransactionsCount: allTransactions.length,
    formattedCount: transactions.length,
    hasReachedEnd,
    loadingMore,
    firstTransaction: transactions[0],
    rawData: unifiedTransactionsData?.currentAccountTransactions?.slice(0, 2)
  });
  
  // Debug the actual transaction object
  if (transactions.length > 0 && transactions[0].type === 'payment') {
    console.log('First payment transaction details:', {
      type: transactions[0].type,
      from: transactions[0].from,
      to: transactions[0].to,
      amount: transactions[0].amount
    });
  }
  
  // Filter transactions based on search query and filters
  const filteredTransactions = useMemo(() => {
    let filtered = transactions;
    
    // Apply search query filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(tx => {
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
    }
    
    // Apply type filters
    filtered = filtered.filter(tx => {
      return transactionFilters.types[tx.type];
    });
    
    // Apply currency filters
    filtered = filtered.filter(tx => {
      const currency = tx.currency === 'cUSD' ? 'cUSD' : tx.currency;
      return transactionFilters.currencies[currency as keyof typeof transactionFilters.currencies] ?? true;
    });
    
    // Apply status filters
    filtered = filtered.filter(tx => {
      return transactionFilters.status[tx.status];
    });
    
    // Apply time range filter
    if (transactionFilters.timeRange !== 'all') {
      const now = moment();
      filtered = filtered.filter(tx => {
        const txDate = moment(tx.date);
        switch (transactionFilters.timeRange) {
          case 'today':
            return txDate.isSame(now, 'day');
          case 'week':
            return txDate.isSame(now, 'week');
          case 'month':
            return txDate.isSame(now, 'month');
          case 'year':
            return txDate.isSame(now, 'year');
          default:
            return true;
        }
      });
    }
    
    // Apply amount range filter
    if (transactionFilters.amountRange.min || transactionFilters.amountRange.max) {
      filtered = filtered.filter(tx => {
        const amount = Math.abs(parseFloat(tx.amount.replace(/[^0-9.-]/g, '')));
        const min = transactionFilters.amountRange.min ? parseFloat(transactionFilters.amountRange.min) : 0;
        const max = transactionFilters.amountRange.max ? parseFloat(transactionFilters.amountRange.max) : Infinity;
        return amount >= min && amount <= max;
      });
    }
    
    return filtered;
  }, [
    transactions, 
    debouncedSearchQuery,
    transactionFilters.types,
    transactionFilters.currencies,
    transactionFilters.status,
    transactionFilters.timeRange,
    transactionFilters.amountRange.min,
    transactionFilters.amountRange.max
  ]);
  
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
  
  // Set initial transactions when data loads
  React.useEffect(() => {
    const currentTransactions = unifiedTransactionsData?.currentAccountTransactions || [];
    
    // Only set initial transactions if we're not loading more (i.e., this is the initial load or refresh)
    if (!loadingMore && currentTransactions.length > 0) {
      console.log('Setting initial transactions:', currentTransactions.length);
      setAllTransactions(currentTransactions);
      
      // If we have fewer transactions than the limit, we've reached the end
      if (currentTransactions.length < transactionLimit) {
        setHasReachedEnd(true);
      } else {
        setHasReachedEnd(false);
      }
    }
  }, [unifiedTransactionsData, transactionLimit, loadingMore]);

  const TransactionItem = memo(({ transaction }: { transaction: Transaction }) => {
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
        case 'conversion':
          // Use short title for conversions based on conversion type
          if (transaction.conversionType === 'usdc_to_cusd') {
            baseTitle = 'Conversión USDC a cUSD';
          } else if (transaction.conversionType === 'cusd_to_usdc') {
            baseTitle = 'Conversión cUSD a USDC';
          } else if (transaction.description) {
            // Fallback: parse from description
            if (transaction.description.includes('USDC →') && transaction.description.includes('cUSD')) {
              baseTitle = 'Conversión USDC a cUSD';
            } else if (transaction.description.includes('cUSD →') && transaction.description.includes('USDC')) {
              baseTitle = 'Conversión cUSD a USDC';
            } else {
              baseTitle = 'Conversión';
            }
          } else {
            baseTitle = 'Conversión';
          }
          break;
        case 'payment':
          if (transaction.amount.startsWith('+')) {
            // For received payments, use the from field directly (already has the payer's name)
            baseTitle = `Pago recibido de ${transaction.from || contactInfo.displayName}`;
          } else {
            // For sent payments, use the to field directly (already has the merchant's name)
            baseTitle = `Pago a ${transaction.to || contactInfo.displayName}`;
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
          from: transaction.type === 'received' 
            ? contactInfo.displayName
            : (transaction.type === 'payment' && transaction.amount.startsWith('+'))
            ? transaction.from
            : transaction.from,
          to: transaction.type === 'sent' 
            ? contactInfo.displayName
            : (transaction.type === 'payment' && transaction.amount.startsWith('-'))
            ? transaction.to
            : transaction.to,
          amount: transaction.amount,
          currency: transaction.currency,
          secondaryCurrency: transaction.secondaryCurrency,
          date: moment(transaction.date).format('YYYY-MM-DD'),
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
          exchangeRate: transaction.type === 'exchange' ? '1 USDC = 1 cUSD' : 
                        transaction.type === 'conversion' ? '1' : undefined,
          conversionType: transaction.conversionType,
          formattedTitle: transaction.type === 'conversion' && transaction.conversionType === 'usdc_to_cusd' ? 'USDC → cUSD' :
                          transaction.type === 'conversion' && transaction.conversionType === 'cusd_to_usdc' ? 'cUSD → USDC' : undefined,
          isInvitedFriend: transaction.isInvitation || false // true means friend is NOT on Confío
        }
      };
      // Navigate to different screens based on transaction type
      if (transaction.type === 'exchange' && transaction.p2pTradeId) {
        // Navigate to ActiveTrade screen for P2P trades
        // @ts-ignore - Navigation type mismatch, but works at runtime
        navigation.navigate('ActiveTrade', { 
          trade: { 
            id: transaction.p2pTradeId 
          } 
        });
      } else {
        // @ts-ignore - Navigation type mismatch, but works at runtime
        navigation.navigate('TransactionDetail', params);
      }
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
          {/* Show external wallet indicator for sends to addresses without phone */}
          {transaction.type === 'sent' && !transaction.toPhone && transaction.recipientAddress && (
            <Text style={styles.externalWalletNote}>
              <Icon name="external-link" size={12} color="#3B82F6" /> Wallet externa
            </Text>
          )}
          {/* Show external wallet indicator for deposits from external wallets */}
          {transaction.isExternalDeposit && (
            <Text style={styles.externalWalletNote}>
              <Icon name="download" size={12} color="#10B981" /> Depósito externo
            </Text>
          )}
        </View>
        <View style={styles.transactionAmount}>
          <Text style={[
            styles.transactionAmountText,
            transaction.amount.startsWith('-') ? styles.negativeAmount : styles.positiveAmount
          ]}>
            {formatTransactionAmount(transaction.amount)} {transaction.currency}
          </Text>
          <View style={styles.transactionStatus}>
            <Text style={styles.statusText}>Completado</Text>
            <View style={styles.statusDot} />
          </View>
        </View>
      </TouchableOpacity>
    );
  });

  // Handlers for exchange modal - removed, now handled in USDCConversion screen
  /*
  const handleConversion = async () => {
    console.log('handleConversion called', { exchangeAmount, conversionDirection });
    
    if (!exchangeAmount || parseFloat(exchangeAmount) <= 0) {
      console.log('Invalid amount, returning');
      return;
    }
    
    setIsProcessingConversion(true);
    
    try {
      console.log('Starting conversion:', { direction: conversionDirection, amount: exchangeAmount });
      console.log('Mutations available:', { convertUsdcToCusd, convertCusdToUsdc });
      
      const mutation = conversionDirection === 'usdc_to_cusd' ? convertUsdcToCusd : convertCusdToUsdc;
      console.log('Selected mutation:', mutation);
      
      let data;
      try {
        const response = await mutation({
          variables: {
            amount: exchangeAmount
          }
        });
        data = response.data;
        console.log('Mutation response:', response);
      } catch (mutationError) {
        console.error('Mutation error:', mutationError);
        throw mutationError;
      }
      
      const result = conversionDirection === 'usdc_to_cusd' 
        ? data?.convertUsdcToCusd 
        : data?.convertCusdToUsdc;
      
      console.log('Conversion result:', result);
      console.log('Conversion data:', data);
      console.log('Full mutation response:', { data, result, errors: result?.errors });
      
      // Check if we even got a result
      if (!result) {
        console.error('No result returned from mutation');
        Alert.alert('Error', 'No se recibió respuesta del servidor');
        return;
      }
      
      if (result?.success) {
        Alert.alert(
          'Conversión exitosa',
          `Has convertido ${exchangeAmount} ${conversionDirection === 'usdc_to_cusd' ? 'USDC' : 'cUSD'} exitosamente.`,
          [
            {
              text: 'OK',
              onPress: () => {
                setShowExchangeModal(false);
                setExchangeAmount('');
                onRefresh(); // Refresh balances
              }
            }
          ]
        );
      } else {
        Alert.alert(
          'Error',
          result?.errors?.[0] || 'No se pudo completar la conversión. Por favor intenta de nuevo.',
          [{ text: 'OK' }]
        );
      }
    } catch (error) {
      console.error('Conversion error:', error);
      Alert.alert(
        'Error',
        'Ocurrió un error al procesar la conversión. Por favor intenta de nuevo.',
        [{ text: 'OK' }]
      );
    } finally {
      setIsProcessingConversion(false);
    }
  };
  
  const toggleConversionDirection = useCallback(() => {
    setConversionDirection(prev => 
      prev === 'usdc_to_cusd' ? 'cusd_to_usdc' : 'usdc_to_cusd'
    );
  }, []);
  */

  const handleSend = useCallback(() => {
    // @ts-ignore - Navigation type mismatch, but should work at runtime
    navigation.navigate('BottomTabs', { screen: 'Contacts' });
  }, [navigation]);
  
  const hasActiveFilters = useCallback(() => {
    const allTypesSelected = Object.values(transactionFilters.types).every(v => v);
    const allCurrenciesSelected = Object.values(transactionFilters.currencies).every(v => v);
    const allStatusSelected = Object.values(transactionFilters.status).every(v => v);
    const noAmountRange = !transactionFilters.amountRange.min && !transactionFilters.amountRange.max;
    const allTimeRange = transactionFilters.timeRange === 'all';

    return !(allTypesSelected && allCurrenciesSelected && allStatusSelected && noAmountRange && allTimeRange);
  }, [transactionFilters]);

  // Exchange Modal removed - now using USDCConversion screen directly
  /*
  const renderExchangeModal = () => {
    return (
      <Modal
        visible={showExchangeModal}
        transparent
        animationType="slide"
        onRequestClose={() => setShowExchangeModal(false)}
      >
        <TouchableOpacity 
          style={styles.modalOverlay} 
          activeOpacity={1}
          onPress={() => setShowExchangeModal(false)}
        >
          <TouchableOpacity 
            activeOpacity={1} 
            style={styles.exchangeModalContent}
            onPress={() => {}} // Prevent keyboard dismissal when tapping modal content
          >
            <View style={styles.exchangeModalHeader}>
              <Text style={styles.exchangeModalTitle}>
                Intercambio {conversionDirection === 'usdc_to_cusd' ? 'USDC → cUSD' : 'cUSD → USDC'}
              </Text>
              <TouchableOpacity onPress={() => setShowExchangeModal(false)}>
                <Icon name="x" size={24} color="#6b7280" />
              </TouchableOpacity>
            </View>
            
            <View style={styles.exchangeModalBody}>
              <View style={styles.exchangeInputSection}>
                <Text style={styles.exchangeLabel}>Cantidad a convertir</Text>
                <View style={styles.exchangeInputContainer}>
                  <TextInput
                    ref={exchangeInputRef}
                    style={styles.exchangeInput}
                    value={exchangeAmount}
                    onChangeText={handleExchangeAmountChange}
                    placeholder="0.00"
                    placeholderTextColor="#9ca3af"
                    keyboardType="numeric"
                    autoFocus={true}
                    returnKeyType="done"
                  />
                  <Text style={styles.exchangeCurrency}>
                    {conversionDirection === 'usdc_to_cusd' ? 'USDC' : 'cUSD'}
                  </Text>
                </View>
                
                <TouchableOpacity 
                  style={styles.exchangeDirectionButton}
                  onPress={toggleConversionDirection}
                >
                  <Icon name="refresh-cw" size={16} color="#3b82f6" />
                  <Text style={styles.exchangeDirectionText}>Cambiar dirección</Text>
                </TouchableOpacity>
              </View>
              
              <View style={styles.exchangeInfo}>
                <View style={styles.exchangeInfoRow}>
                  <Text style={styles.exchangeInfoLabel}>Recibirás</Text>
                  <Text style={styles.exchangeInfoValue}>
                    {exchangeAmount || '0'} {conversionDirection === 'usdc_to_cusd' ? 'cUSD' : 'USDC'}
                  </Text>
                </View>
                <View style={styles.exchangeInfoRow}>
                  <Text style={styles.exchangeInfoLabel}>Tasa de cambio</Text>
                  <Text style={styles.exchangeInfoValue}>1:1</Text>
                </View>
                <View style={styles.exchangeInfoRow}>
                  <Text style={styles.exchangeInfoLabel}>Comisión</Text>
                  <Text style={[styles.exchangeInfoValue, { color: colors.primary }]}>Gratis</Text>
                </View>
              </View>
              
              <TouchableOpacity
                style={[
                  styles.exchangeConfirmButton,
                  (!exchangeAmount || parseFloat(exchangeAmount) <= 0 || isProcessingConversion) && styles.exchangeConfirmButtonDisabled
                ]}
                onPress={() => {
                  console.log('Conversion button pressed');
                  console.log('Button state:', {
                    exchangeAmount,
                    isProcessingConversion,
                    disabled: !exchangeAmount || parseFloat(exchangeAmount) <= 0 || isProcessingConversion
                  });
                  handleConversion();
                }}
                disabled={!exchangeAmount || parseFloat(exchangeAmount) <= 0 || isProcessingConversion}
              >
                {isProcessingConversion ? (
                  <ActivityIndicator size="small" color="#ffffff" />
                ) : (
                  <Text style={styles.exchangeConfirmButtonText}>
                    Convertir {exchangeAmount || '0'} {conversionDirection === 'usdc_to_cusd' ? 'USDC' : 'cUSD'}
                  </Text>
                )}
              </TouchableOpacity>
            </View>
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>
    );
  };
  */

  const loadMoreTransactions = useCallback(async () => {
    if (loadingMore || hasReachedEnd || !fetchMore) {
      console.log('loadMoreTransactions - Skipping:', { loadingMore, hasReachedEnd, hasFetchMore: !!fetchMore });
      return;
    }
    
    console.log('loadMoreTransactions - Current state:', {
      allTransactionsLength: allTransactions.length,
      hasReachedEnd,
      loadingMore
    });
    
    setLoadingMore(true);
    
    try {
      // Calculate new offset
      const newOffset = allTransactions.length;
      
      console.log('loadMoreTransactions - Fetching with offset:', newOffset);
      
      // Fetch more transactions with the new offset
      const { data } = await fetchMore({
        variables: {
          accountType: activeAccount?.type || 'personal',
          accountIndex: activeAccount?.index || 0,
          limit: transactionLimit,
          offset: newOffset,
          tokenTypes: route.params.accountType === 'cusd' ? 
      (activeAccount?.isEmployee ? ['cUSD', 'CUSD'] : ['cUSD', 'CUSD', 'USDC']) : 
      ['CONFIO']
        },
        updateQuery: (prev, { fetchMoreResult }) => {
          console.log('loadMoreTransactions - fetchMoreResult:', {
            hasResult: !!fetchMoreResult,
            newTransactionsCount: fetchMoreResult?.currentAccountTransactions?.length || 0,
            prevCount: prev?.currentAccountTransactions?.length || 0
          });
          
          if (!fetchMoreResult) return prev;
          
          if (fetchMoreResult.currentAccountTransactions.length === 0) {
            setHasReachedEnd(true);
            return prev;
          }
          
          // Append new transactions to allTransactions state
          const newTransactions = fetchMoreResult.currentAccountTransactions;
          
          // Check if we've reached the end
          if (newTransactions.length < transactionLimit) {
            console.log('Reached end - got fewer transactions than limit:', newTransactions.length, '<', transactionLimit);
            setHasReachedEnd(true);
          }
          
          setAllTransactions(prevTxs => {
            console.log('Appending transactions:', prevTxs.length, '+', newTransactions.length);
            return [...prevTxs, ...newTransactions];
          });
          
          // Return updated query result for Apollo cache
          return {
            ...prev,
            currentAccountTransactions: [...(prev.currentAccountTransactions || []), ...newTransactions]
          };
        }
      });
    } catch (error) {
      console.error('Error loading more transactions:', error);
    } finally {
      setLoadingMore(false);
    }
  }, [loadingMore, hasReachedEnd, fetchMore, allTransactions.length, activeAccount, transactionLimit, route.params.accountType]);

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation}
        title={account.name}
        backgroundColor={account.color}
        isLight={true}
        showBackButton={true}
      />

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
            {!canViewBalance ? account.balanceHidden : (showBalance ? `$${account.balance}` : account.balanceHidden)}
          </Text>
          {canViewBalance && (
            <TouchableOpacity onPress={toggleBalanceVisibility}>
              <Icon
                name={showBalance ? 'eye' : 'eye-off'}
                size={20}
                color="#ffffff"
                style={styles.eyeIcon}
              />
            </TouchableOpacity>
          )}
        </View>

        {/* Show locked status for CONFIO tokens - only if balance > 0 */}
        {route.params.accountType === 'confio' && canViewBalance && showBalance && parseFloat(account.balance) > 0 && (
          <View style={styles.lockedStatusContainer}>
            <View style={styles.lockedStatusRow}>
              <Icon name="lock" size={14} color="#fbbf24" />
              <Text style={styles.lockedStatusText}>
                Bloqueado: ${account.balance} $CONFIO
              </Text>
            </View>
            <View style={styles.lockedStatusRow}>
              <Icon name="unlock" size={14} color="#ffffff" style={{ opacity: 0.5 }} />
              <Text style={styles.lockedStatusText}>
                Disponible: $0.00 $CONFIO
              </Text>
            </View>
            <Text style={styles.lockedStatusDescription}>
              Se desbloquearán cuando Confío alcance adopción masiva en toda Latinoamérica
            </Text>
          </View>
        )}

        <Text style={styles.balanceDescription}>{account.description}</Text>
        {/* Hide address for employees without viewBusinessAddress permission */}
        {(!activeAccount?.isEmployee || activeAccount?.employeePermissions?.viewBusinessAddress) && account.address && (
          <View style={styles.addressContainer}>
            <Text style={styles.addressText}>{account.addressShort}</Text>
            <TouchableOpacity onPress={() => {
              if (account.address) {
                Clipboard.setString(account.address);
                Alert.alert('Copiado', 'Dirección copiada al portapapeles');
              }
            }}>
              <Icon name="copy" size={16} color="#ffffff" style={styles.copyIcon} />
            </TouchableOpacity>
          </View>
        )}
      </View>

      {/* Action Buttons */}
      <View style={styles.actionButtonsContainer}>
        {activeAccount?.isEmployee && !activeAccount?.employeePermissions?.sendFunds ? (
          // Employee welcome message
          <View style={styles.employeeMessageContainer}>
            <View style={styles.employeeMessageIcon}>
              <Icon name="briefcase" size={32} color="#7c3aed" />
            </View>
            <Text style={styles.employeeMessageTitle}>
              Eres parte de {activeAccount?.business?.name}
            </Text>
            <Text style={styles.employeeMessageText}>
              Como {activeAccount?.employeeRole === 'cashier' ? 'cajero' : 
                    activeAccount?.employeeRole === 'manager' ? 'gerente' : 
                    activeAccount?.employeeRole === 'admin' ? 'administrador' : 'miembro del equipo'}, {(() => {
                const perms = [];
                if (activeAccount?.employeePermissions?.acceptPayments) perms.push('recibir pagos');
                if (activeAccount?.employeePermissions?.viewTransactions) perms.push('ver el historial de transacciones');
                
                if (perms.length === 0) return 'estás aquí para ayudar al éxito del negocio';
                if (perms.length === 1) return `puedes ${perms[0]} para ayudar a nuestros clientes`;
                return `puedes ${perms.join(' y ')} para contribuir al crecimiento del negocio`;
              })()}.
            </Text>
          </View>
        ) : (
          <View style={styles.actionButtons}>
            {(!activeAccount?.isEmployee || activeAccount?.employeePermissions?.sendFunds) && (
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
            )}

            {(!activeAccount?.isEmployee || activeAccount?.employeePermissions?.acceptPayments) && (
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
            )}

            {(!activeAccount?.isEmployee || activeAccount?.employeePermissions?.acceptPayments) && (
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
            )}

            {!activeAccount?.isEmployee && (
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
            )}
          </View>
        )}
      </View>
      <SectionList
        style={styles.scrollView}
        sections={groupedTransactions}
        keyExtractor={(item, index) => `${item.id || item.transactionHash || index}-${index}`}
        renderItem={({ item }) => <TransactionItem transaction={item} />}
        renderSectionHeader={({ section: { title } }) => (
          <Text style={styles.sectionHeader}>{title}</Text>
        )}
        removeClippedSubviews={true}
        maxToRenderPerBatch={10}
        updateCellsBatchingPeriod={50}
        windowSize={10}
        initialNumToRender={10}
        ListEmptyComponent={() => {
          if (unifiedLoading) {
            return (
              <View style={styles.transactionsList}>
                <TransactionItemSkeleton />
                <TransactionItemSkeleton />
                <TransactionItemSkeleton />
              </View>
            );
          }
          
          return (
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
          );
        }}
        ListFooterComponent={() => {
          if (!unifiedLoading && allTransactions.length >= transactionLimit && !hasReachedEnd) {
            return (
              <TouchableOpacity 
                style={styles.loadMoreButton}
                onPress={loadMoreTransactions}
                disabled={loadingMore}
              >
                {loadingMore ? (
                  <ActivityIndicator size="small" color={colors.primary} />
                ) : (
                  <Text style={[styles.loadMoreText, { color: account.color }]}>
                    Ver más transacciones
                  </Text>
                )}
              </TouchableOpacity>
            );
          }
          return null;
        }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={account.color}
            colors={[account.color]}
          />
        }
        onEndReached={() => {
          if (!loadingMore && !hasReachedEnd && filteredTransactions.length > 0 && !searchQuery) {
            console.log('onEndReached triggered - loading more');
            loadMoreTransactions();
          }
        }}
        onEndReachedThreshold={0.3}
        stickySectionHeadersEnabled={false}
        showsVerticalScrollIndicator={true}
        contentContainerStyle={filteredTransactions.length === 0 ? styles.emptyListContainer : undefined}
        ListHeaderComponent={() => (
          <>
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
                    {!canViewBalance ? usdcAccount.balanceHidden : (showBalance ? usdcAccount.balance : usdcAccount.balanceHidden)}
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
                  onPress={() => {
                    console.log('Convert button pressed - navigating to USDCConversion screen');
                    navigation.navigate('USDCConversion');
                  }}
                >
                  <Icon name="refresh-cw" size={16} color="#fff" style={styles.actionIcon} />
                  <View style={styles.actionTextContainer}>
                    <Text style={[styles.usdcActionButtonText, { color: '#ffffff' }]}>
                      Convertir
                    </Text>
                    <Text style={[styles.usdcActionSubtext, { color: 'rgba(255,255,255,0.8)' }]}>
                      USDC ↔ cUSD
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

            {/* CONFIO Presale Section - Only show for CONFIO accounts and if presale is active */}
            {route.params.accountType === 'confio' && isPresaleActive && (
              <View style={styles.confioPresaleSection}>
                <View style={styles.sectionHeaderContainer}>
                  <Text style={styles.sectionTitle}>🚀 Preventa Exclusiva</Text>
                </View>
                
                <View style={styles.confioPresaleCard}>
                  <View style={styles.confioPresaleHeader}>
                    <View style={styles.confioPresaleInfo}>
                      <Text style={styles.confioPresaleTitle}>Únete a la Preventa de $CONFIO</Text>
                      <Text style={styles.confioPresaleDescription}>
                        Acceso anticipado a las monedas $CONFIO
                      </Text>
                    </View>
                  </View>
                  
                  <TouchableOpacity
                    style={styles.confioPresaleButton}
                    onPress={() => navigation.navigate('ConfioPresale')}
                  >
                    <Icon name="star" size={16} color="#fff" style={styles.actionIcon} />
                    <View style={styles.actionTextContainer}>
                      <Text style={[styles.confioPresaleButtonText, { color: '#ffffff' }]}>
                        Ver Detalles
                      </Text>
                      <Text style={[styles.confioPresaleSubtext, { color: 'rgba(255,255,255,0.8)' }]}>
                        Información completa
                      </Text>
                    </View>
                  </TouchableOpacity>
                </View>
              </View>
            )}

            {/* Enhanced Transactions Section */}
            <View style={styles.transactionsSection}>
              <View style={styles.transactionsHeader}>
                <Text style={styles.transactionsTitle}>Historial de transacciones</Text>
                <View style={styles.transactionsFilters}>
                  <TouchableOpacity 
                    style={[styles.filterButton, showSearch && styles.filterButtonActive]}
                    onPress={() => setShowSearch(!showSearch)}
                  >
                    <Icon name="search" size={16} color={showSearch ? account.textColor : "#6b7280"} />
                  </TouchableOpacity>
                  <TouchableOpacity 
                    style={[
                      styles.filterButton,
                      hasActiveFilters() && styles.filterButtonActive
                    ]}
                    onPress={() => setShowFilterModal(true)}
                  >
                    <Icon 
                      name="filter" 
                      size={16} 
                      color={hasActiveFilters() ? account.textColor : "#6b7280"} 
                    />
                    {hasActiveFilters() && (
                      <View style={[styles.filterDot, { backgroundColor: account.color }]} />
                    )}
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
            </View>
          </>
        )}
      />

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
      
      {/* Transaction Filter Modal */}
      <TransactionFilterModal
        visible={showFilterModal}
        onClose={() => setShowFilterModal(false)}
        onApply={setTransactionFilters}
        currentFilters={transactionFilters}
        theme={{
          primary: account.color,
          secondary: colors.secondary,
        }}
      />
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
    backgroundColor: colors.neutralDark,
  },
  balanceSection: {
    paddingTop: 12,
    paddingBottom: 24,
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
  lockedStatusContainer: {
    backgroundColor: 'rgba(0, 0, 0, 0.2)',
    borderRadius: 12,
    padding: 12,
    marginVertical: 8,
    gap: 6,
  },
  lockedStatusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  lockedStatusText: {
    fontSize: 13,
    color: '#ffffff',
    opacity: 0.9,
  },
  lockedStatusDescription: {
    fontSize: 11,
    color: '#ffffff',
    opacity: 0.7,
    marginTop: 4,
    textAlign: 'center',
    fontStyle: 'italic',
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
  employeeMessageContainer: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 24,
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
  employeeMessageIcon: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: '#f3f4f6',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  employeeMessageTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1f2937',
    textAlign: 'center',
    marginBottom: 8,
  },
  employeeMessageText: {
    fontSize: 14,
    color: '#6b7280',
    textAlign: 'center',
    lineHeight: 20,
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
    marginBottom: 0,
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
    paddingTop: 8,
    paddingBottom: 8,
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
    position: 'relative',
  },
  filterDot: {
    position: 'absolute',
    top: 6,
    right: 6,
    width: 6,
    height: 6,
    borderRadius: 3,
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
  externalWalletNote: {
    fontSize: 12,
    color: '#1E40AF',
    marginTop: 2,
    fontWeight: '500',
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
  exchangeArrowButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
    alignSelf: 'center',
    marginVertical: 16,
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
    marginTop: 8,
    marginBottom: 8,
    marginHorizontal: 16,
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
  // Exchange Modal Styles
  exchangeModalContent: {
    backgroundColor: '#ffffff',
    borderRadius: 20,
    margin: 20,
    maxWidth: 400,
    width: '90%',
    alignSelf: 'center',
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
  exchangeModalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#e5e7eb',
  },
  exchangeModalTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  exchangeModalBody: {
    padding: 20,
  },
  exchangeInputSection: {
    marginBottom: 24,
  },
  exchangeLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: '#6b7280',
    marginBottom: 8,
  },
  exchangeInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#f3f4f6',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
    marginBottom: 12,
  },
  exchangeInput: {
    flex: 1,
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1f2937',
    padding: 0,
  },
  exchangeCurrency: {
    fontSize: 16,
    fontWeight: '600',
    color: '#6b7280',
    marginLeft: 8,
  },
  exchangeDirectionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
  },
  exchangeDirectionText: {
    fontSize: 14,
    color: '#3b82f6',
    marginLeft: 6,
    fontWeight: '500',
  },
  exchangeInfo: {
    backgroundColor: '#f9fafb',
    borderRadius: 12,
    padding: 16,
    marginBottom: 20,
  },
  exchangeInfoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  exchangeInfoLabel: {
    fontSize: 14,
    color: '#6b7280',
  },
  exchangeInfoValue: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1f2937',
  },
  exchangeConfirmButton: {
    backgroundColor: colors.accent,
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  exchangeConfirmButtonDisabled: {
    opacity: 0.5,
  },
  exchangeConfirmButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  emptyListContainer: {
    flex: 1,
    paddingTop: 20,
  },
  loadMoreButton: {
    padding: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  loadMoreText: {
    fontSize: 14,
    fontWeight: '600',
  },
  // CONFIO Presale Section styles - matching USD section format
  confioPresaleSection: {
    paddingHorizontal: 16,
    marginBottom: 0,
  },
  confioPresaleCard: {
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
  confioPresaleHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  confioPresaleInfo: {
    flex: 1,
  },
  confioPresaleTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1f2937',
    marginBottom: 4,
  },
  confioPresaleDescription: {
    fontSize: 13,
    color: '#6b7280',
    lineHeight: 18,
  },
  confioPresaleButton: {
    backgroundColor: '#8b5cf6',
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 12,
    ...Platform.select({
      ios: {
        shadowColor: '#8b5cf6',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.3,
        shadowRadius: 4,
      },
      android: {
        elevation: 4,
      },
    }),
  },
  confioPresaleButtonText: {
    fontSize: 14,
    fontWeight: 'bold',
  },
  confioPresaleSubtext: {
    fontSize: 12,
  },
}); 