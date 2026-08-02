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
} from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import Icon from 'react-native-vector-icons/Feather';
import MCIcon from 'react-native-vector-icons/MaterialCommunityIcons';
import { isRampBlockedCountry } from '../config/env';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RouteProp } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';
import { Header } from '../navigation/Header';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import { InlineBanner } from '../components/common/InlineBanner';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { formatUsdDeltaAbs } from '../utils/savingsFormat';
import { EmptyState } from '../components/EmptyState';
import cUSDLogo from '../assets/png/cUSD.png';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';
import OndoLogo from '../assets/png/Ondo.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import USDCLogo from '../assets/png/USDC.png';
import { useNumberFormat } from '../utils/numberFormatting';
import { useQuery, useMutation } from '@apollo/client';
import { GET_UNIFIED_TRANSACTIONS, GET_CURRENT_ACCOUNT_TRANSACTIONS, GET_PRESALE_STATUS, GET_ACCOUNT_BALANCE, GET_MY_BALANCES, CHECK_USERS_BY_PHONES } from '../apollo/queries';
import { REFRESH_ACCOUNT_BALANCE, SET_REFERRER } from '../apollo/mutations';
// import { CONVERT_USDC_TO_CUSD, CONVERT_CUSD_TO_USDC } from '../apollo/mutations'; // Removed - handled in USDCConversion screen
import { TransactionItemSkeleton } from '../components/SkeletonLoader';
import moment from 'moment';
import 'moment/locale/es';
import 'moment/locale/es';
import { useAccount } from '../contexts/AccountContext';
import * as Keychain from 'react-native-keychain';
import { useContactNameSync } from '../hooks/useContactName';
import { TransactionFilterModal, TransactionFilters } from '../components/TransactionFilterModal';
import { useAuth } from '../contexts/AuthContext';
import { deepLinkHandler } from '../utils/deepLinkHandler';
import { useAutoSwap } from '../hooks/useAutoSwap';
import AutoSwapModal from '../components/AutoSwapModal';
import { useSavingsResume } from '../hooks/useSavingsResume';
import { colors } from '../config/theme';
import { getTierMeta } from '../components/StatusTierBadge';
import { formatTokenLabel, conversionPair, isConversionIncoming } from '../utils/tokenDisplay';

// Color palette
// Keychain constants for storing balance visibility
const PREFERENCES_KEYCHAIN_SERVICE = 'com.confio.preferences';
const ACCOUNT_BALANCE_VISIBILITY_PREFIX = 'account_balance_visibility_';

type AccountDetailScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;
type AccountDetailScreenRouteProp = RouteProp<MainStackParamList, 'AccountDetail'>;

interface Transaction {
  id?: string;
  type: 'received' | 'sent' | 'exchange' | 'payment' | 'conversion' | 'reward' | 'presale' | 'payroll' | 'ramp' | 'humanitarian';
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
  invitationId?: string;
  idempotencyKey?: string;
  invitationClaimed?: boolean;
  invitationReverted?: boolean;
  invitationExpiresAt?: string;
  senderAddress?: string;
  recipientAddress?: string;
  description?: string;
  conversionType?: string;
  conversionFromToken?: string;
  conversionToToken?: string;
  isExternalDeposit?: boolean;
  senderType?: string;
  secondaryCurrency?: string;
  // Enhanced fields
  senderDisplayName?: string;
  counterpartyDisplayName?: string;
  senderUser?: any;
  recipientUser?: any;
  senderStatusTier?: string | null;
  senderIsReferralVerified?: boolean;
  recipientStatusTier?: string | null;
  recipientIsReferralVerified?: boolean;
  payerStatusTier?: string | null;
  payerIsReferralVerified?: boolean;
  merchantStatusTier?: string | null;
  merchantIsReferralVerified?: boolean;
  internalId?: string;
  senderName?: string;
  recipientName?: string;
  p2pTradeId?: string;
  isRewardPayout?: boolean;
  toUsername?: string;
  payrollRunId?: string;
  runId?: string;
  transactionHash?: string;
  rampDirection?: string;
  rampProvider?: string;
}

// Set Spanish locale for moment
moment.locale('es');

const { width: screenWidth } = Dimensions.get('window');

interface TransactionSection {
  title: string;
  data: Transaction[];
}

const normalizePhoneLookupKey = (value?: string | null): string => {
  if (!value) return '';
  const trimmed = value.trim();
  if (!trimmed) return '';
  const hasPlus = trimmed.startsWith('+');
  const digits = trimmed.replace(/\D/g, '');
  return hasPlus ? `+${digits}` : digits;
};

export const AccountDetailScreen = () => {
  const navigation = useNavigation<AccountDetailScreenNavigationProp>();
  const route = useRoute<AccountDetailScreenRouteProp>();
  const { formatNumber, formatCurrency } = useNumberFormat();
  const { activeAccount } = useAccount();
  const { isAuthenticated, isLoading: authLoading, accountContextTick, userProfile } = useAuth();

  // Helpers to avoid overstating balances
  const floorToDecimals = useCallback((value: number, decimals: number) => {
    if (!isFinite(value)) return 0;
    const m = Math.pow(10, decimals);
    return Math.floor(value * m) / m;
  }, []);

  const formatFixedFloor = useCallback((value: number, decimals = 2) => {
    const floored = floorToDecimals(value, decimals);
    return floored.toLocaleString('es-ES', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  }, [floorToDecimals]);

  const formatBalanceDisplay = useCallback((valueStr: string | number) => {
    const v = typeof valueStr === 'string' ? parseFloat(valueStr) : valueStr;
    if (!isFinite(v) || v <= 0) return '0.00';
    if (v < 0.01) return '< 0.01';
    return formatFixedFloor(v, 2);
  }, [formatFixedFloor]);

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
  const [copyBanner, setCopyBanner] = useState(false);
  // Measured size of the balance field. The field's height changes after
  // mount (locked-balance card appears when data loads, eye toggle), and an
  // absoluteFill Svg with percentage sizes doesn't repaint on parent growth —
  // the stale gradient leaves a flat band. Explicit dimensions force redraw.
  const [fieldSize, setFieldSize] = useState({ width: 0, height: 0 });
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
      reward: true,
      presale: true,
      payroll: true,
      ramp: true,
      humanitarian: true,
    },
    // Empty means "no currency filter applied" — the filter below treats an
    // absent key as visible. The selectable set comes from accountTokenTypes
    // (see currencyChips), so the chips can never drift from the tokens this
    // account's history actually queries for.
    currencies: {},
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
  const canQueryTransactions = isAuthenticated && !authLoading;

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

  // Fetch balances in one query to avoid UI flicker (live + presale-locked)
  const isCusd = route.params.accountType === 'cusd';
  // The savings account (Confío Dollar+ / raw USDT on BSC) is a THIRD variant,
  // merged in from the old standalone SavingsScreen so both live in one
  // detail surface with one history, one receipt path and one set of rows.
  const isSavingsAccount = route.params.accountType === 'cusd_plus';
  const isConfio = !isCusd && !isSavingsAccount;
  // Finish any cUSD+ mint whose USDT already arrived. This lived on
  // SavingsScreen and was dropped when that screen merged in here (808b7abc),
  // which left every arrived deposit stuck at DEST_ARRIVED. Scoped to the
  // savings account, as it was before.
  // Which ledger rows belong to this account. Was an inline ternary repeated
  // at five call sites; a third account type made that untenable.
  const accountTokenTypes = React.useMemo(() => {
    if (isSavingsAccount) return ['CUSD_PLUS', 'USDT'];
    if (isCusd) return activeAccount?.isEmployee ? ['CUSD'] : ['CUSD', 'USDC', 'ALGO'];
    return ['CONFIO'];
  }, [isCusd, isSavingsAccount, activeAccount?.isEmployee]);
  // Filter chips = the account's own tokens, in display form. ALGO is dropped:
  // it appears only as an auto-conversion artifact, never as money the user
  // holds, so it is not something to filter a statement by.
  const currencyChips = React.useMemo(
    () => accountTokenTypes.filter(t => t !== 'ALGO').map(t => formatTokenLabel(t)),
    [accountTokenTypes],
  );
  // cUSD phase-out: while deposits are paused (server flag, singleton is
  // already cached by Home) this screen goes retiro-only — no Recargar.
  const { savings: ahorrosSavings, usdtBalanceUsd: ahorrosUsdt } = useSavingsPortfolio();
  // Moved below useSavingsPortfolio so it can take the polled USDT balance as
  // its arrival trigger: mounting fires the sweep when the user OPENS this
  // screen, but a deposit landing while they sit here needs the balance to
  // say so. Unconditional and permanently ordered, so hook order is stable.
  const { mintingSavings } = useSavingsResume(isSavingsAccount, ahorrosUsdt);
  // Savings variant figures. The headline is ONE account number (vault
  // position + raw wallet USDT): money must never look like it vanished
  // between landing on-chain and minting into the vault.
  const savingsIsYield = ahorrosSavings.enabled;
  const savingsAccountTotal = ahorrosSavings.balanceUsd + (ahorrosUsdt || 0);
  // Adaptive precision (2 dp, 3 dp under 1¢) so small savers still see the
  // daily tick; below display resolution the part is omitted entirely —
  // "+$0.00" reads as broken. Savings-only: stocks report in their own row.
  const savingsTickerParts: string[] = [];
  {
    const hoy = formatUsdDeltaAbs(ahorrosSavings.earnedTodayUsd);
    if (hoy) {
      savingsTickerParts.push(
        `Hoy ${ahorrosSavings.earnedTodayUsd >= 0 ? '+' : '\u2212'}${hoy}`);
    }
    const mes = formatUsdDeltaAbs(ahorrosSavings.earnedMonthUsd);
    if (mes && ahorrosSavings.earnedMonthUsd > 0) {
      savingsTickerParts.push(`Este mes +${mes}`);
    }
  }
  const isCusdRetiroOnly = isCusd && ahorrosSavings.cusdDepositsPaused;

  const { data: balancesData, refetch: refetchBalances, loading: balancesLoading } = useQuery(GET_MY_BALANCES, {
    fetchPolicy: 'no-cache',
  });

  // Use real-time balance if available, otherwise fallback to route params
  const confioLive = React.useMemo(() => parseFloat(balancesData?.myBalances?.confio || '0'), [balancesData?.myBalances?.confio]);
  const confioLocked = React.useMemo(() => (isConfio ? parseFloat(balancesData?.myBalances?.confioLocked || balancesData?.myBalances?.confioPresaleLocked || '0') : 0), [balancesData?.myBalances?.confioLocked, balancesData?.myBalances?.confioPresaleLocked, isConfio]);
  const cusdLive = React.useMemo(() => parseFloat(balancesData?.myBalances?.cusd || '0'), [balancesData?.myBalances?.cusd]);

  const currentBalance = React.useMemo(() => {
    // Savings reads its own live portfolio, not a route param: the number
    // moves on its own (yield accrues, deposits mint) so a value captured at
    // navigation time would be stale the moment the screen opened.
    if (isSavingsAccount) return savingsAccountTotal.toFixed(2);
    if (isCusd) {
      const v = cusdLive;
      if (!isFinite(v)) return route.params.accountBalance;
      return v.toFixed(2);
    }
    const v = confioLive + confioLocked;
    if (!isFinite(v)) return route.params.accountBalance;
    return v.toFixed(2);
  }, [isCusd, cusdLive, confioLive, confioLocked, route.params.accountBalance,
      isSavingsAccount, savingsAccountTotal]);

  // Account data from navigation params
  const accountAddress = route.params.accountAddress || '';
  const account = {
    name: route.params.accountName,
    symbol: route.params.accountSymbol,
    balance: currentBalance,
    balanceHidden: "•••••••",
    color: isConfio ? colors.secondary : colors.primary,
    colorDark: isConfio ? colors.secondaryDark : colors.primaryDark,
    textColor: isConfio ? colors.secondaryText : colors.primaryText,
    address: accountAddress,
    addressShort: accountAddress ? `${accountAddress.slice(0, 6)}...${accountAddress.slice(-6)}` : '',
    exchangeRate: "1 USDC = 1 cUSD",
    description: isSavingsAccount
      ? (savingsIsYield
        ? "Tu dinero crece mientras duerme, respaldado por bonos del Tesoro"
        : "Dólares digitales, siempre tuyos")
      : isCusd
        ? "Dólar digital estable respaldado 1:1 por USDC"
        : "Moneda de gobernanza de Confío"
  };

  // Debug logging

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

  const handleRefreshAccountBalance = useCallback(() => {
    refetchBalances();
    if (shouldFetchUSDC) refetchUSDC();
  }, [refetchBalances, shouldFetchUSDC, refetchUSDC]);

  const { swapModalAsset, walletRecoveryRequired, dismissWalletRecovery } = useAutoSwap({
    isAuthenticated,
    myBalancesLoading: balancesLoading,
    usdcBalanceStr: (balancesData as any)?.myBalances?.usdc || '0',
    algoBalanceStr: (balancesData as any)?.myBalances?.algo || '0',
    refreshAccountBalance: handleRefreshAccountBalance,
    activeAccount
  });

  // USDC balance data - HIDDEN for employees
  const usdcAccount = shouldFetchUSDC ? {
    name: "USD Coin",
    symbol: "USDC",
    balance: formatBalanceDisplay(usdcBalance),
    balanceHidden: "•••••••",
    description: "Para usuarios avanzados - depósito directo vía Algorand Blockchain"
  } : null;

  // Pulse the convert CTA when USDC is available so users move it into cUSD
  const convertPulseAnim = useRef(new Animated.Value(1)).current;
  const entranceAnimRef = useRef<Animated.CompositeAnimation | null>(null);
  const searchAnimRef = useRef<Animated.CompositeAnimation | null>(null);
  const searchTranslateY = useMemo(
    () =>
      searchAnim.interpolate({
        inputRange: [0, 1],
        outputRange: [-10, 0],
      }),
    [searchAnim]
  );
  const hasUsdcToConvert = shouldFetchUSDC && usdcBalance > 0.0001;

  useEffect(() => {
    let loop: Animated.CompositeAnimation | null = null;
    if (hasUsdcToConvert) {
      loop = Animated.loop(
        Animated.sequence([
          Animated.timing(convertPulseAnim, {
            toValue: 1.08,
            duration: 650,
            useNativeDriver: true,
          }),
          Animated.timing(convertPulseAnim, {
            toValue: 1,
            duration: 400,
            useNativeDriver: true,
          }),
        ])
      );
      loop.start();
    } else {
      convertPulseAnim.stopAnimation(() => {
        convertPulseAnim.setValue(1);
      });
    }
    return () => {
      loop?.stop();
    };
  }, [hasUsdcToConvert, convertPulseAnim]);

  // JWT-context-aware transactions query
  const queryVariables = {
    limit: transactionLimit,
    offset: 0, // Always start with offset 0 for initial query
    tokenTypes: accountTokenTypes
  };


  const { data: unifiedTransactionsData, loading: unifiedLoading, error: unifiedError, refetch: refetchUnified, fetchMore } = useQuery(GET_CURRENT_ACCOUNT_TRANSACTIONS, {
    variables: queryVariables,
    skip: !canQueryTransactions || !activeAccount, // Wait for auth/account context
    fetchPolicy: 'network-only',
    nextFetchPolicy: 'cache-first',
    notifyOnNetworkStatusChange: true,
    onCompleted: (data) => {
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
  const [setReferrerMutation] = useMutation(SET_REFERRER);

  // Conversion mutations
  // const [convertUsdcToCusd] = useMutation(CONVERT_USDC_TO_CUSD); // Removed - handled in USDCConversion screen
  // const [convertCusdToUsdc] = useMutation(CONVERT_CUSD_TO_USDC); // Removed - handled in USDCConversion screen

  // Animation entrance
  useEffect(() => {
    entranceAnimRef.current?.stop();
    entranceAnimRef.current = Animated.timing(fadeAnim, {
      toValue: 1,
      duration: 400,
      useNativeDriver: true,
    });
    entranceAnimRef.current.start();
    return () => {
      entranceAnimRef.current?.stop();
    };
  }, [fadeAnim]);

  // Load balance visibility preference on mount
  useEffect(() => {
    loadBalanceVisibility();
  }, [route.params.accountType]);

  // Ensure transactions refresh once auth/account context is ready (after app resume/login)
  useEffect(() => {
    if (!canQueryTransactions || !activeAccount) return;

    const tokenTypes = accountTokenTypes;

    setTransactionLimit(20);
    setTransactionOffset(0);
    setHasReachedEnd(false);
    setAllTransactions([]);

    refetchUnified({
      limit: 20,
      offset: 0,
      tokenTypes,
    });
    refetchBalances();
    if (shouldFetchUSDC) {
      refetchUSDC();
    }
  }, [accountContextTick, canQueryTransactions, route.params.accountType, activeAccount?.isEmployee, refetchUnified, refetchBalances, shouldFetchUSDC, refetchUSDC]);

  // Refetch transactions when active account changes
  useEffect(() => {
    if (activeAccount && canQueryTransactions) {
      refetchUnified({
        limit: transactionLimit,
        offset: 0,
        tokenTypes: accountTokenTypes
      });
    }
  }, [activeAccount?.id, activeAccount?.type, activeAccount?.index, canQueryTransactions]);

  // Search animation
  useEffect(() => {
    searchAnimRef.current?.stop();
    searchAnimRef.current = Animated.timing(searchAnim, {
      toValue: showSearch ? 1 : 0,
      duration: 300,
      useNativeDriver: true,
    });
    searchAnimRef.current.start();
    return () => {
      searchAnimRef.current?.stop();
    };
  }, [showSearch, searchAnim]);

  useEffect(() => {
    return () => {
      entranceAnimRef.current?.stop();
      searchAnimRef.current?.stop();
      fadeAnim.stopAnimation();
      searchAnim.stopAnimation();
      convertPulseAnim.stopAnimation();
    };
  }, [convertPulseAnim, fadeAnim, searchAnim]);



  // Pull to refresh handler
  const onRefresh = useCallback(async () => {
    if (!canQueryTransactions) {
      return;
    }

    setRefreshing(true);
    if (Platform.OS === 'ios') {
      Vibration.vibrate(10);
    }

    try {
      // First force refresh from blockchain
      const { data: refreshData } = await refreshBalanceMutation();

      if (refreshData?.refreshAccountBalance?.success) {
      }

      // Then refresh balance, USDC (if applicable), and transactions
      const promises = [
        refetchBalances(),
        refetchUnified({
          accountType: activeAccount?.type || 'personal',
          accountIndex: activeAccount?.index || 0,
          limit: 20,
          offset: 0,
          tokenTypes: accountTokenTypes
        })
      ];
      // Add USDC refresh if applicable
      if (shouldFetchUSDC) {
        promises.push(refetchUSDC());
      }

      const [_, { data }] = await Promise.all(promises);
      setAllTransactions(data?.currentAccountTransactions || []);
      setTransactionLimit(20);
      setTransactionOffset(0);
      setHasReachedEnd(false);
    } catch (error) {
      console.error('Error refreshing transactions:', error);
    } finally {
      setRefreshing(false);
    }

  }, [refetchUnified, refetchBalances, activeAccount, route.params.accountType, canQueryTransactions, shouldFetchUSDC, refetchUSDC]);

  // Listen for refresh trigger from navigation params
  useEffect(() => {
    // @ts-ignore - route params type
    if (route.params?.refreshTimestamp) {
      onRefresh();
    }
  }, [route.params, onRefresh]);

  // NEW: Transform unified transactions into the format expected by the UI
  const formatUnifiedTransactions = () => {
    const formattedTransactions: Transaction[] = [];
    const sourceTransactions = allTransactions.length > 0
      ? allTransactions
      : (unifiedTransactionsData?.currentAccountTransactions || []);

    if (sourceTransactions.length > 0) {
      sourceTransactions.forEach((tx: any) => {
        // Determine transaction type based on both transactionType and direction
        let type: 'sent' | 'received' | 'payment' | 'conversion' | 'exchange' | 'reward' | 'presale' | 'payroll' | 'ramp' | 'humanitarian' = 'sent';
        const normalizedTxType = (tx.transactionType || '').toLowerCase();
        if (normalizedTxType === 'payment') {
          type = 'payment';
        } else if (normalizedTxType === 'conversion') {
          type = 'conversion';
        } else if (normalizedTxType === 'exchange') {
          type = 'exchange';
        } else if (normalizedTxType === 'ramp') {
          type = 'ramp';
        } else if (normalizedTxType === 'reward') {
          type = 'reward';
        } else if (normalizedTxType === 'presale') {
          type = 'presale';
        } else if (normalizedTxType === 'payroll') {
          type = 'payroll';
        } else if (normalizedTxType === 'humanitarian') {
          type = 'humanitarian';
        } else {
          type = tx.direction === 'sent' ? 'sent' : 'received';
        }
        const isReward = type === 'reward';
        const isPresale = type === 'presale';
        const isHumanitarian = type === 'humanitarian';

        // Fix invitation detection: 
        // 1. If we have a counterpartyUser, it's not an invitation
        // 2. If it's marked as invitation but has no phone (external wallet), it's not a real invitation
        let isActualInvitation = tx.isInvitation || false;
        if (isActualInvitation && tx.counterpartyUser && tx.counterpartyUser.id) {
          // If there's a counterparty user, this is not really an invitation
          isActualInvitation = false;
        }
        // Check if it's an external wallet send (no phone number)
        if (isActualInvitation && tx.direction === 'sent' && !tx.counterpartyPhone) {
          isActualInvitation = false;
        }

        // Debug logging

        // For proper contact name lookup, we need to pass the phone numbers
        // The displayCounterparty is the DB name, but we want local contact names
        // Debug payment transaction
        if (type === 'payment') {
        }

        // Handle conversion transactions
        const isConversion = type === 'conversion';

        // For conversions, prepare default values
        let conversionAmount = tx.amount; // Use raw amount, will be formatted below
        let conversionType: string | undefined;
        let conversionFromToken: string | undefined;
        let conversionToToken: string | undefined;

        if (isConversion) {

          // Parse conversion type from description if server fields not available
          conversionType = tx.conversionType;
          if (!conversionType && tx.description) {
            // The description format is "Conversión: X USDC → Y cUSD"
            if (tx.description.includes('USDC →') && tx.description.includes('cUSD')) {
              conversionType = 'usdc_to_cusd';
            } else if (tx.description.includes('cUSD →') && tx.description.includes('USDC')) {
              conversionType = 'cusd_to_usdc';
            }
          }
          // The server names both sides of every pair; the local table is the
          // fallback for rows that predate those fields.
          const pair = conversionPair(conversionType);
          conversionFromToken =
            formatTokenLabel(tx.fromToken || tx.from_token) || pair?.from;
          conversionToToken =
            formatTokenLabel(tx.toToken || tx.to_token) || pair?.to;

          // The card shows the side this account actually holds, signed from
          // its point of view: the token arriving (+) or the token leaving (-).
          if (pair) {
            const incoming = isConversionIncoming(conversionType);
            const raw = incoming
              ? (tx.toAmount || tx.fromAmount || tx.amount)
              : (tx.fromAmount || tx.amount);
            const amount = parseFloat(String(raw)).toFixed(2);
            conversionAmount = `${incoming ? '+' : '-'}${amount}`;
          } else {
            // Unrecognised conversion type: keep the row's own sign rather
            // than guessing a direction from the token, which is how the
            // savings pair used to come out backwards.
            const value = parseFloat(String(tx.amount));
            conversionAmount = `${value < 0 ? '-' : '+'}${Math.abs(value).toFixed(2)}`;
          }
        }

        // Check if this is an external deposit
        const isExternalDeposit = !isReward && type === 'received' && tx.senderType?.toLowerCase() === 'external';
        const rewardDescription = isReward ? (tx.displayDescription || tx.description || 'Recompensa por referidos') : undefined;
        const presaleDescription = isPresale ? (tx.displayDescription || tx.description || 'Compra de preventa $CONFIO') : undefined;

        // Debug external deposits
        if (type === 'received' && tx.senderType) {
        }

        // Format the from field - truncate address if it's an external deposit
        let fromDisplay = undefined;
        let toDisplay = undefined;

        if (isConversion) {
          fromDisplay = conversionFromToken;
          toDisplay = conversionToToken;
        } else if (isReward) {
          fromDisplay = tx.senderDisplayName || tx.displayCounterparty || 'Confío Rewards';
          toDisplay = tx.counterpartyDisplayName || 'Tú';
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
        } else if (type === 'ramp') {
          if ((tx.rampDirection || '').toLowerCase() === 'off_ramp') {
            fromDisplay = 'Tu cuenta';
            toDisplay = tx.rampProvider || tx.counterpartyDisplayName || tx.displayCounterparty || 'Proveedor';
          } else {
            fromDisplay = tx.rampProvider || tx.senderDisplayName || tx.displayCounterparty || 'Proveedor';
            toDisplay = 'Tu cuenta';
          }
        } else if ((type === 'payment' && tx.direction === 'received') || (type === 'received')) {
          fromDisplay = tx.displayCounterparty;
          // Truncate external wallet addresses
          if (isExternalDeposit && fromDisplay && fromDisplay.startsWith('0x') && fromDisplay.length > 20) {
            fromDisplay = `${fromDisplay.slice(0, 10)}...${fromDisplay.slice(-6)}`;
          }
        } else if ((type === 'payment' && tx.direction === 'sent') || (type === 'sent')) {
          toDisplay = tx.displayCounterparty;
        } else if (type === 'payroll') {
          if (tx.direction === 'received') {
            fromDisplay = tx.senderDisplayName || tx.displayCounterparty;
          } else {
            toDisplay = tx.counterpartyDisplayName || tx.displayCounterparty;
          }
        } else if (isHumanitarian) {
          if (tx.direction === 'received') {
            fromDisplay = tx.senderDisplayName || tx.displayCounterparty || 'Confío Ayuda Humanitaria';
          } else {
            toDisplay = tx.counterpartyDisplayName || tx.displayCounterparty || 'Confío Ayuda Humanitaria';
          }
        }

        // Ensure display amount has a sign for proper direction (helps payroll visibility)
        let signedDisplayAmount = tx.displayAmount;
        if (!signedDisplayAmount) {
          const base = tx.amount ?? '0';
          const sign = tx.direction === 'sent' ? '-' : '+';
          signedDisplayAmount = `${sign}${base}`;
        } else if (!(signedDisplayAmount.startsWith('+') || signedDisplayAmount.startsWith('-'))) {
          const sign = tx.direction === 'sent' ? '-' : '+';
          signedDisplayAmount = `${sign}${signedDisplayAmount}`;
        }

        const rampDirection = (tx.rampDirection || '').toLowerCase();
        const rampFiatAmountRaw = tx.rampFiatAmount;
        const rampFiatAmount = rampFiatAmountRaw === undefined || rampFiatAmountRaw === null
          ? ''
          : String(rampFiatAmountRaw).trim();
        const signedRampFiatAmount = rampFiatAmount
          ? ((rampFiatAmount.startsWith('+') || rampFiatAmount.startsWith('-')) ? rampFiatAmount : `+${rampFiatAmount}`)
          : '';

        // Map backend status to UI status labels
        const rawStatus = (tx.status || '').toUpperCase();
        const mappedStatus: 'completed' | 'pending' | 'failed' = (() => {
          switch (rawStatus) {
            case 'CONFIRMED':
              return 'completed';
            case 'FAILED':
              return 'failed';
            case 'SUBMITTED':
            case 'PENDING':
            case 'PROCESSING':
              return 'pending';
            default:
              return 'pending';
          }
        })();

        // Derive phone keys from nested users when available
        const fromPhoneKey = (tx.senderUser && (tx.senderUser as any).phoneKey) || tx.senderPhone || (tx as any).fromPhone;
        const toPhoneKey = (tx.counterpartyUser && (tx.counterpartyUser as any).phoneKey) || tx.counterpartyPhone || (tx as any).toPhone;

        const humanitarianDescription = isHumanitarian
          ? (tx.displayDescription || tx.description || (tx.direction === 'received' ? 'Ayuda humanitaria recibida' : 'Donación humanitaria'))
          : undefined;
        const finalDescription = isConversion
          ? tx.description
          : isReward
            ? rewardDescription
            : isPresale
              ? presaleDescription
              : isHumanitarian
                ? humanitarianDescription
                : tx.description;

        const payrollBusinessName = (() => {
          if (type !== 'payroll') return undefined;
          // For payroll, the business is the sender; use sender display/name as business name
          return (
            tx.senderBusiness?.name ||
            fromDisplay ||
            tx.senderDisplayName ||
            tx.counterpartyDisplayName ||
            tx.displayCounterparty ||
            'Empresa'
          );
        })();

        const finalTransaction = {
          id: tx.id,
          type,
          direction: tx.direction,
          from: fromDisplay,
          to: toDisplay,
          fromPhone: isConversion ? undefined : (tx.direction === 'received' ? fromPhoneKey : undefined),
          toPhone: isConversion ? undefined : (tx.direction === 'sent' ? toPhoneKey : undefined),
          amount: isConversion
            ? conversionAmount
            : type === 'ramp' && rampDirection === 'on_ramp' && signedRampFiatAmount
              ? signedRampFiatAmount
              : signedDisplayAmount,
          // For conversions, show the currency of the amount displayed: the destination token for '+' and source for '-'
          currency: isConversion
            // The denomination of the amount shown above: the token arriving
            // for an inbound conversion, the token leaving for an outbound one.
            ? (isConversionIncoming(conversionType)
              ? conversionToToken
              : conversionFromToken)
            : type === 'ramp'
              ? (
                rampDirection === 'on_ramp'
                  ? (tx.rampFiatCurrency || 'cUSD')
                  : 'cUSD'
              )
            : (() => {
              const normalizedToken = (tx.tokenType || '').toUpperCase();
              const isCusdToken = normalizedToken === 'CUSD' || normalizedToken.includes('CONFIO DOLLAR') || normalizedToken.includes('CUSD ');
              if (type === 'payroll' || type === 'humanitarian' || isCusdToken) {
                return 'cUSD';
              }
              return tx.tokenType || route.params.accountSymbol || '';
            })(),
          secondaryCurrency: isConversion ? conversionToToken : undefined,
          conversionType: isConversion ? (conversionType || tx.conversionType) : undefined,
          conversion_type: isConversion ? (conversionType || tx.conversionType) : undefined,
          conversionFromToken: isConversion ? (conversionFromToken || tx.fromToken || tx.from_token) : undefined,
          conversionToToken: isConversion ? (conversionToToken || tx.toToken || tx.to_token) : undefined,
          conversionFromCurrency: isConversion ? (conversionFromToken || tx.fromToken || tx.from_token) : undefined,
          conversionToCurrency: isConversion ? (conversionToToken || tx.toToken || tx.to_token) : undefined,
          fromToken: isConversion ? (conversionFromToken || tx.fromToken || tx.from_token) : undefined,
          toToken: isConversion ? (conversionToToken || tx.toToken || tx.to_token) : undefined,
          from_token: isConversion ? (conversionFromToken || tx.from_token || tx.fromToken) : undefined,
          to_token: isConversion ? (conversionToToken || tx.to_token || tx.toToken) : undefined,
          date: tx.createdAt, // Keep full timestamp for proper sorting
          time: new Date(tx.createdAt).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }),
          status: mappedStatus,
          hash: tx.transactionHash || 'pending',
          isInvitation: isActualInvitation,
          invitationId: tx.idempotencyKey,
          idempotencyKey: tx.idempotencyKey,
          invitationClaimed: tx.invitationClaimed || false,
          invitationReverted: tx.invitationReverted || false,
          invitationExpiresAt: tx.invitationExpiresAt,
          senderAddress: tx.senderAddress,
          recipientAddress: tx.counterpartyAddress, // Note: unified view uses counterpartyAddress
          isExternalDeposit, // Add this flag for the UI to show the "Wallet externa" tag
          senderType: tx.senderType,
          // Helps UI decide if this was a Confío friend vs external
          hasCounterpartyUser: Boolean(tx.counterpartyUser && tx.counterpartyUser.id),
          description: finalDescription,
          p2pTradeId: type === 'exchange' ? tx.p2pTradeId : undefined,
          isRewardPayout: isReward,
          counterpartyUser: tx.counterpartyUser,
          recipientUser: tx.counterpartyUser,
          senderUser: tx.senderUser,
          counterpartyDisplayName: tx.counterpartyDisplayName,
          senderDisplayName: tx.senderDisplayName,
          businessName: payrollBusinessName,
          internalId: tx.internalId, // Pass internalId to detail screen
          senderBusiness: tx.senderBusiness,
          recipientBusiness: tx.counterpartyBusiness,
          rampDirection: tx.rampDirection,
          rampProvider: tx.rampProvider,
          rampFiatAmount: tx.rampFiatAmount,
          rampFiatCurrency: tx.rampFiatCurrency,
        };

        // Debug final transaction for external deposits
        if (isExternalDeposit) {
        }

        // Debug conversion amounts
        if (isConversion) {
        }

        // Debug payroll final transaction
        if (type === 'payroll') {
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
    }

    switch (transaction.type) {
      case 'received':
        return `Recibido de ${transaction.from}`;
      case 'sent':
        return `Enviado a ${transaction.to}`;
      case 'exchange':
        return `Conversión ${transaction.from} → ${transaction.to}`;
      case 'ramp':
        return transaction.rampDirection === 'off_ramp'
          ? `Retiro${transaction.to ? ` con ${transaction.to}` : ''}`
          : `Recarga${transaction.from ? ` con ${transaction.from}` : ''}`;
      case 'conversion': {
        // Name both sides from the row's own tokens, so a new pair reads
        // correctly without another branch here.
        const pair = conversionPair(transaction.conversionType);
        const from = transaction.conversionFromToken || pair?.from;
        const to = transaction.conversionToToken || pair?.to;
        return from && to ? `Conversión ${from} a ${to}` : 'Conversión';
      }
      case 'payment':
        // If amount is positive, it's a payment received
        return transaction.amount.startsWith('+')
          ? `Pago recibido de ${transaction.from || 'Unknown'}`
          : `Pago a ${transaction.to || 'Unknown'}`;
      case 'reward':
        return transaction.description || 'Recompensa Confío';
      case 'presale':
        return transaction.description || 'Compra preventa $CONFIO';
      case 'payroll':
        return transaction.amount.startsWith('+')
          ? `Nómina recibida de ${transaction.from || 'Empresa'}`
          : `Pago de nómina a ${transaction.to || 'Empleado'}`;
      case 'humanitarian':
        return transaction.amount.startsWith('+')
          ? 'Ayuda humanitaria recibida'
          : 'Donación humanitaria';
      default:
        return 'Transacción';
    }
  };

  // Icon chip per category: colored glyph on a soft tint of the same color,
  // matching the app-wide icon-chip grammar. Sent stays neutral — outgoing
  // money is not an alert.
  const getTransactionVisual = (transaction: Transaction): { icon: string; color: string; bg: string } => {
    switch (transaction.type) {
      case 'received':
        return { icon: 'arrow-down', color: colors.primaryDark, bg: colors.primarySoft };
      case 'sent':
        return { icon: 'arrow-up', color: colors.text.primary, bg: colors.neutralDark };
      case 'exchange':
        return { icon: 'refresh-cw', color: colors.accent, bg: '#EFF6FF' };
      case 'conversion':
        return { icon: 'repeat', color: colors.primaryDark, bg: colors.primarySoft };
      case 'ramp':
        return { icon: 'repeat', color: '#0EA5E9', bg: '#E0F2FE' };
      case 'payment':
        return { icon: 'shopping-bag', color: colors.secondary, bg: colors.violetLight };
      case 'reward':
        return { icon: 'gift', color: colors.offRampIcon, bg: colors.warningLight };
      case 'presale':
        return { icon: 'lock', color: '#6366F1', bg: '#EEF2FF' };
      case 'payroll':
        return { icon: 'briefcase', color: colors.primaryDark, bg: colors.primarySoft };
      case 'humanitarian':
        return { icon: 'heart', color: '#E11D48', bg: '#FFE4E6' };
      default:
        return { icon: 'arrow-up', color: colors.text.secondary, bg: colors.neutralDark };
    }
  };

  const getTransactionIcon = (transaction: Transaction) => {
    const visual = getTransactionVisual(transaction);
    return <Icon name={visual.icon} size={20} color={visual.color} />;
  };

  // Use unified transactions if available, fallback to legacy format
  const transactions = formatUnifiedTransactions();

  const badgeLookupPhones = useMemo(() => {
    const phones = transactions.flatMap((transaction) => [transaction.fromPhone, transaction.toPhone])
      .filter((phone): phone is string => typeof phone === 'string' && phone.trim().length > 0);
    return Array.from(new Set(phones));
  }, [transactions]);

  const { data: badgeLookupData } = useQuery(CHECK_USERS_BY_PHONES, {
    variables: { phoneNumbers: badgeLookupPhones },
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

  // Debug which data source is being used

  // Debug the actual transaction object
  if (transactions.length > 0 && transactions[0].type === 'payment') {
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
        // Rows display the short form ("4 jul"), so match what the user sees too
        const dateDisplay = moment(tx.date).format('D MMM').toLowerCase();
        const fromPhone = (tx.fromPhone || '').toLowerCase();
        const toPhone = (tx.toPhone || '').toLowerCase();

        return title.includes(query) ||
          amount.includes(query) ||
          currency.includes(query) ||
          hash.includes(query) ||
          date.includes(query) ||
          dateDisplay.includes(query) ||
          fromPhone.includes(query) ||
          toPhone.includes(query);
      });
    }

    // Apply type filters
    filtered = filtered.filter(tx => {
      return transactionFilters.types[tx.type as keyof typeof transactionFilters.types] ?? true;
    });

    // Apply currency filters. Rows carry the raw wire token ('CUSD_PLUS')
    // while the chips are display labels ('cUSD+'), so both sides are
    // normalised — comparing them raw silently matched nothing and made the
    // toggles inert. An unlisted token stays visible rather than vanishing.
    filtered = filtered.filter(tx => {
      const currency = formatTokenLabel(tx.currency);
      return transactionFilters.currencies[currency] ?? true;
    });

    // Apply status filters
    filtered = filtered.filter(tx => {
      return transactionFilters.status[tx.status as keyof typeof transactionFilters.status];
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

    if (loadingMore || !canQueryTransactions) return;

    setAllTransactions(currentTransactions);

    if (!unifiedLoading) {
      setHasReachedEnd(currentTransactions.length < transactionLimit);
    }
  }, [unifiedTransactionsData, transactionLimit, loadingMore, unifiedLoading, canQueryTransactions]);

  const TransactionItem = memo(({ transaction, activeAccount, userProfile }: { transaction: Transaction, activeAccount: any, userProfile: any }) => {
    // Short date — rows sit under Hoy/Ayer/month section headers, so the
    // full DD/MM/YYYY repeats what the header already says.
    const formattedDate = moment(transaction.date).format('D MMM');
    const formattedTime = transaction.time;
    const isRewardTransaction = transaction.type === 'reward' || transaction.isRewardPayout;
    const isPresaleTransaction = transaction.type === 'presale';

    // Determine if counterparty is an external wallet (no phone + address present + no user)
    const isExternalSent = transaction.type === 'sent' && !transaction.toPhone && transaction.recipientAddress && !(transaction as any).hasCounterpartyUser;
    // senderType is the server's own answer about the SENDER, so it settles a
    // received row on its own. The fallback below cannot: hasCounterpartyUser
    // is derived from counterpartyUser, which on a send row is the RECIPIENT —
    // null for a business account — so a business would read "an address, no
    // phone, no user" and call a known Confío sender an external wallet.
    const senderTypeKnown = typeof (transaction as any).senderType === 'string'
      && !!(transaction as any).senderType;
    const isExternalReceived = transaction.type === 'received' && (
      senderTypeKnown
        ? (transaction as any).senderType.toLowerCase() === 'external'
        : (!transaction.fromPhone && transaction.senderAddress && !(transaction as any).hasCounterpartyUser)
    );
    // Get contact name for sender or recipient, falling back to "Billetera externa" for external wallets
    const phoneToCheck = (isRewardTransaction || isPresaleTransaction) ? undefined : (transaction.type === 'received' ? transaction.fromPhone : transaction.toPhone);
    const fallbackName = isRewardTransaction
      ? (transaction.from || 'Confío Rewards')
      : isPresaleTransaction
        ? (transaction.from || 'Confío Preventa')
        : transaction.type === 'received'
          ? (isExternalReceived ? 'Billetera externa' : transaction.from)
          : (isExternalSent ? 'Billetera externa' : transaction.to);
    const contactInfo = useContactNameSync(phoneToCheck, fallbackName);

    // Create enhanced transaction title with contact name
    const getEnhancedTransactionTitle = () => {
      let baseTitle = '';
      switch (transaction.type) {
        case 'received':
          baseTitle = `Recibido de ${contactInfo.displayName}`;
          break;
        case 'sent':
          baseTitle = `Enviado a ${contactInfo.displayName}`;
          break;
        case 'exchange':
          baseTitle = `Conversión ${transaction.from} → ${transaction.to}`;
          break;
        case 'ramp':
          baseTitle = transaction.rampDirection === 'off_ramp'
            ? `Retiro${transaction.to ? ` con ${transaction.to}` : ''}`
            : `Recarga${transaction.from ? ` con ${transaction.from}` : ''}`;
          break;
        case 'conversion': {
          const pair = conversionPair(transaction.conversionType);
          const from = transaction.conversionFromToken || pair?.from;
          const to = transaction.conversionToToken || pair?.to;
          baseTitle = from && to ? `Conversión ${from} a ${to}` : 'Conversión';
          break;
        }
        case 'payment':
          if (transaction.amount.startsWith('+')) {
            // For received payments, use the from field directly (already has the payer's name)
            baseTitle = `Pago recibido de ${transaction.from || contactInfo.displayName}`;
          } else {
            // For sent payments, use the to field directly (already has the merchant's name)
            baseTitle = `Pago a ${transaction.to || contactInfo.displayName}`;
          }
          break;
        case 'reward':
          baseTitle = transaction.description || 'Recompensa por referidos';
          break;
        case 'presale':
          baseTitle = transaction.description || 'Compra preventa $CONFIO';
          break;
        case 'payroll':
          if (transaction.amount.startsWith('+')) {
            baseTitle = `Nómina recibida de ${transaction.from || 'Empresa'}`;
          } else {
            baseTitle = `Pago de nómina a ${transaction.to || 'Empleado'}`;
          }
          break;
        case 'humanitarian':
          baseTitle = transaction.description || (transaction.amount.startsWith('+')
            ? 'Ayuda humanitaria recibida'
            : 'Donación humanitaria');
          break;
        default:
          baseTitle = 'Transacción';
      }
      return baseTitle;
    };

    const navigation = useNavigation();
    const senderBadgeInfo =
      badgeByPhone.get(transaction.fromPhone || '') ||
      badgeByPhone.get(normalizePhoneLookupKey(transaction.fromPhone));
    const recipientBadgeInfo =
      badgeByPhone.get(transaction.toPhone || '') ||
      badgeByPhone.get(normalizePhoneLookupKey(transaction.toPhone));
    const senderStatusTier =
      (transaction as any).senderStatusTier ??
      transaction.senderUser?.statusTier ??
      senderBadgeInfo?.statusTier ??
      null;
    const senderIsReferralVerified =
      (transaction as any).senderIsReferralVerified ??
      transaction.senderUser?.isReferralVerified ??
      senderBadgeInfo?.isReferralVerified ??
      false;
    const recipientStatusTier =
      (transaction as any).recipientStatusTier ??
      transaction.recipientUser?.statusTier ??
      recipientBadgeInfo?.statusTier ??
      null;
    const recipientIsReferralVerified =
      (transaction as any).recipientIsReferralVerified ??
      transaction.recipientUser?.isReferralVerified ??
      recipientBadgeInfo?.isReferralVerified ??
      false;

    const handlePress = () => {
      const params = {
        transactionType: transaction.type,
        transactionData: {
          type: transaction.type,
          internalId: (transaction as any).internalId,
          from: (transaction.type === 'received' || transaction.type === 'reward')
            ? (transaction.from || contactInfo.displayName)
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
          fromAddress: (transaction.type === 'received' || transaction.type === 'reward') ? transaction.senderAddress : undefined,
          toAddress: transaction.type === 'sent' ? transaction.recipientAddress : undefined,
          fromPhone: transaction.fromPhone,
          toPhone: transaction.toPhone,
          note: undefined,
          avatar: transaction.from ? transaction.from.charAt(0) :
            transaction.to ? transaction.to.charAt(0) : undefined,
          location: transaction.type === 'payment' ? 'Av. Libertador, Caracas' : undefined,
          merchantId: transaction.type === 'payment' ? 'SUP001' : undefined,
          exchangeRate: transaction.type === 'exchange' ? '1 USDC = 1 cUSD' :
            transaction.type === 'conversion' ? '1' : undefined,
          conversionType: transaction.conversionType,
          // The detail screen reads snake_case (it also serves notification
          // payloads); without these it fell back to a hardcoded 'USDC'.
          conversion_type: transaction.conversionType,
          conversionFromToken: transaction.conversionFromToken,
          conversionToToken: transaction.conversionToToken,
          from_token: transaction.conversionFromToken,
          to_token: transaction.conversionToToken,
          formattedTitle: transaction.type === 'conversion'
            ? (() => {
              const pair = conversionPair(transaction.conversionType);
              const from = transaction.conversionFromToken || pair?.from;
              const to = transaction.conversionToToken || pair?.to;
              return from && to ? `${from} → ${to}` : undefined;
            })() :
            transaction.type === 'ramp' && transaction.rampDirection === 'off_ramp' ? 'Retiro' :
            transaction.type === 'ramp' ? 'Recarga' :
            transaction.type === 'humanitarian' ? transaction.description :
            undefined,
          isInvitedFriend: transaction.isInvitation || false, // true means friend is NOT on Confío
          invitationId: transaction.invitationId,
          idempotencyKey: transaction.idempotencyKey,
          invitationClaimed: transaction.invitationClaimed || false,
          invitationReverted: transaction.invitationReverted || false,
          invitationExpiresAt: transaction.invitationExpiresAt || undefined,
          // Pass rich name data for Detail Screen resolution
          senderName: transaction.senderDisplayName || (transaction.senderUser?.firstName ? `${transaction.senderUser.firstName} ${transaction.senderUser.lastName || ''}`.trim() : undefined) || transaction.from,
          recipientName: transaction.counterpartyDisplayName || (transaction.recipientUser?.firstName ? `${transaction.recipientUser.firstName} ${transaction.recipientUser.lastName || ''}`.trim() : undefined) || transaction.to,
          senderUser: transaction.senderUser,
          recipientUser: transaction.recipientUser,
          senderDisplayName: transaction.senderDisplayName,
          recipientDisplayName: transaction.counterpartyDisplayName,
          senderBusiness: (transaction as any).senderBusiness,
          recipientBusiness: (transaction as any).recipientBusiness,
          senderStatusTier,
          senderIsReferralVerified,
          recipientStatusTier,
          recipientIsReferralVerified,
          payerBusiness: (transaction as any).senderBusiness, // Alias for payment logic
          merchantBusiness: (transaction as any).recipientBusiness, // Alias for payment logic
          payerStatusTier: (transaction as any).payerStatusTier ?? senderStatusTier,
          payerIsReferralVerified: (transaction as any).payerIsReferralVerified ?? senderIsReferralVerified,
          merchantStatusTier: (transaction as any).merchantStatusTier ?? recipientStatusTier,
          merchantIsReferralVerified: (transaction as any).merchantIsReferralVerified ?? recipientIsReferralVerified,
        }
      };
      // Navigate to different screens based on transaction type
      if (transaction.type === 'exchange' && transaction.p2pTradeId) {
        // Navigate to ActiveTrade screen for P2P trades
        // @ts-ignore - Navigation type mismatch, but works at runtime
        navigation.navigate('ActiveTrade', {
          trade: {
            id: transaction.p2pTradeId,
            internalId: transaction.internalId
          }
        });
      } else if (transaction.type === 'payroll') {
        // Navigate to PayrollReceipt screen for payroll transactions
        // For payroll, employee sees 'received' direction, business sees 'sent'
        const txAny = transaction as any;
        const isEmployeeView = txAny.direction === 'received';

        // Extract counterparty user data (recipient for sent, sender for received)
        const counterpartyUser = txAny.counterpartyUser || txAny.recipientUser || txAny.senderUser;
        const counterpartyFirstName = counterpartyUser?.firstName || txAny.recipientUser?.firstName || txAny.senderUser?.firstName || '';
        const counterpartyLastName = counterpartyUser?.lastName || txAny.recipientUser?.lastName || txAny.senderUser?.lastName || '';
        const counterpartyFullName = `${counterpartyFirstName} ${counterpartyLastName}`.trim();
        const counterpartyUsername = counterpartyUser?.username || txAny.recipientUser?.username || txAny.senderUser?.username || '';
        const counterpartyPhone = counterpartyUser?.phoneKey || txAny.recipientPhone || txAny.counterpartyPhone || txAny.toPhone || '';

        // Employee name on receipt should come from the counterparty (the payee) when available
        const employeeDisplayName = counterpartyFullName
          || txAny.counterpartyDisplayName
          || txAny.displayCounterparty
          || transaction.to
          || txAny.toName
          || txAny.displayToName
          || counterpartyUsername
          || 'Empleado';

        const businessDisplayName = isEmployeeView
          ? (transaction.from || txAny.senderDisplayName || txAny.displayCounterparty || 'Empresa')
          : (activeAccount?.business?.name || userProfile?.businessName || 'Tu Empresa');

        // @ts-ignore - Navigation type mismatch, but works at runtime
        navigation.navigate('TransactionReceipt', {
          transaction: {
            ...transaction,
            verificationId: txAny.internalId || txAny.id, // Use full UUID for QR code if available
            // Ensure necessary fields for receipt
            employeeName: employeeDisplayName,
            employeeUsername: counterpartyUsername,
            businessName: businessDisplayName,
            amount: transaction.amount,
            currency: (transaction as any).tokenType || transaction.currency,
            date: (transaction as any).createdAt || transaction.date,
            status: transaction.status,
            transactionHash: transaction.transactionHash,
            payrollRunId: transaction.payrollRunId
          },
          type: 'payroll'
        });
      } else {
        // @ts-ignore - Navigation type mismatch, but works at runtime
        navigation.navigate('TransactionDetail', params);
      }
    };

    const transactionAccessibilityLabel = `${getEnhancedTransactionTitle()}. ${formatTransactionAmount(transaction.amount)} ${formatTokenLabel(transaction.currency)}. ${formattedDate} ${formattedTime}.`;
    const isCounterpartyTheSender =
      transaction.type === 'received' ||
      (transaction.type === 'payment' && transaction.amount.startsWith('+')) ||
      (transaction.type === 'payroll' && transaction.amount.startsWith('+')) ||
      (transaction.type === 'humanitarian' && transaction.amount.startsWith('+'));
    const titleStatusTier = isCounterpartyTheSender ? senderStatusTier : recipientStatusTier;
    const titleIsReferralVerified = isCounterpartyTheSender ? senderIsReferralVerified : recipientIsReferralVerified;

    return (
      <TouchableOpacity
        style={[
          styles.transactionItem,
          // Invitation states: pending = warning amber, reverted = error red,
          // claimed = a normal card (nothing is wrong anymore).
          transaction.isInvitation && !transaction.invitationClaimed && !transaction.invitationReverted && styles.invitedTransactionItem,
          transaction.isInvitation && transaction.invitationReverted && styles.revertedTransactionItem,
        ]}
        onPress={handlePress}
        accessibilityRole="button"
        accessibilityLabel={transactionAccessibilityLabel}
        accessibilityHint="Abre el detalle de la transacción."
      >
        <View style={[styles.transactionIconContainer, { backgroundColor: getTransactionVisual(transaction).bg }]}>
          {getTransactionIcon(transaction)}
        </View>
        <View style={styles.transactionInfo}>
          <View style={styles.transactionTitleRow}>
            {(() => {
              const title = getEnhancedTransactionTitle().trim();
              const hasBadge = titleIsReferralVerified || (titleStatusTier && titleStatusTier !== 'member');
              if (!hasBadge) {
                return <Text style={styles.transactionTitle}>{title}</Text>;
              }
              const words = title.split(' ').filter(Boolean);
              return words.map((word, i) => {
                const isLast = i === words.length - 1;
                if (!isLast) {
                  return <Text key={i} style={styles.transactionTitle}>{word}{' '}</Text>;
                }
                return (
                  <View key={i} style={styles.lastWordBadgeGroup}>
                    <Text style={styles.transactionTitle}>{word}</Text>
                    {titleIsReferralVerified && (
                      <View style={styles.inlineVerifiedBadge}>
                        <Icon name="check" size={10} color={colors.white} />
                      </View>
                    )}
                    {titleStatusTier && titleStatusTier !== 'member' && (
                      <Text style={styles.inlineTierEmoji}>{getTierMeta(titleStatusTier).emoji}</Text>
                    )}
                  </View>
                );
              });
            })()}
          </View>
          <View style={styles.transactionSubtitleContainer}>
            <Text style={styles.transactionDate}>{formattedDate} • {formattedTime}</Text>
            {contactInfo.isFromContacts && contactInfo.originalName && (
              <Text style={styles.originalName}> • {contactInfo.originalName}</Text>
            )}
          </View>
          {transaction.isInvitation && transaction.type === 'sent' && (
            <Text style={[
              styles.invitationNote,
              transaction.invitationClaimed ? styles.invitationNoteClaimed :
                transaction.invitationReverted ? styles.invitationNoteReverted :
                  styles.invitationNotePending,
            ]}>
              {transaction.invitationClaimed ? '✓ Invitación reclamada' :
                transaction.invitationReverted ? 'Expiró — fondos devueltos' :
                  'Tu amigo tiene 7 días para reclamar • Avísale ya'}
            </Text>
          )}
          {/* Show external wallet indicator for sends to addresses without phone */}
          {transaction.type === 'sent' && !transaction.toPhone && transaction.recipientAddress && !(transaction as any).hasCounterpartyUser && (
            <Text style={styles.externalWalletNote}>
              <Icon name="external-link" size={12} color={colors.accent} /> Wallet externa
            </Text>
          )}
          {/* Show external wallet indicator for deposits from external wallets */}
          {transaction.isExternalDeposit && (
            <Text style={styles.externalWalletNote}>
              <Icon name="download" size={12} color={colors.primaryDark} /> Depósito externo
            </Text>
          )}
          {isRewardTransaction && (
            <Text style={styles.rewardNote}>
              <Icon name="gift" size={12} color={colors.offRampIcon} /> Recompensa por referidos
            </Text>
          )}
          {isPresaleTransaction && (
            <Text style={styles.presaleNote}>
              <Icon name="lock" size={12} color="#6366F1" /> (bloqueado)
            </Text>
          )}
        </View>
        <View style={styles.transactionAmount}>
          <Text style={[
            styles.transactionAmountText,
            transaction.amount.startsWith('-') ? styles.negativeAmount : styles.positiveAmount
          ]}>
            {formatTransactionAmount(transaction.amount)} {formatTokenLabel(transaction.currency)}
          </Text>
          {/* Status only when it carries information — completed is the
              normal case and stays silent. */}
          {transaction.status !== 'completed' && (
            <View style={styles.transactionStatus}>
              {(() => {
                const isFailed = transaction.status === 'failed';
                return (
                  <>
                    <Text style={[styles.statusText, isFailed ? styles.statusTextFailed : styles.statusTextPending]}>
                      {isFailed ? 'Fallido' : 'Pendiente'}
                    </Text>
                    <View style={[styles.statusDot, isFailed ? styles.statusDotFailed : styles.statusDotPending]} />
                  </>
                );
              })()}
            </View>
          )}
        </View>
      </TouchableOpacity>
    );
  });

  // Handlers for exchange modal - removed, now handled in USDCConversion screen
  /*
  const handleConversion = async () => {
    
    if (!exchangeAmount || parseFloat(exchangeAmount) <= 0) {
      return;
    }
    
    setIsProcessingConversion(true);
    
    try {
      
      const mutation = conversionDirection === 'usdc_to_cusd' ? convertUsdcToCusd : convertCusdToUsdc;
      
      let data;
      try {
        const response = await mutation({
          variables: {
            amount: exchangeAmount
          }
        });
        data = response.data;
      } catch (mutationError) {
        console.error('Mutation error:', mutationError);
        throw mutationError;
      }
      
      const result = conversionDirection === 'usdc_to_cusd' 
        ? data?.convertUsdcToCusd 
        : data?.convertCusdToUsdc;
      
      
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
              text: 'Entendido',
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
          [{ text: 'Entendido' }]
        );
      }
    } catch (error) {
      console.error('Conversion error:', error);
      Alert.alert(
        'Error',
        'Ocurrió un error al procesar la conversión. Por favor intenta de nuevo.',
        [{ text: 'Entendido' }]
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

  // Retirar mirrors Home: where no ramp provider operates, point to the
  // Efectivo directory up front instead of failing inside the provider flow.
  const handleRetirar = useCallback(() => {
    if (isRampBlockedCountry(userProfile?.phoneCountry)) {
      Alert.alert(
        'No disponible en tu país',
        'Los retiros con proveedores aún no están disponibles en tu país. En el menú Efectivo encuentras financieras locales verificadas cerca de ti.',
        [
          { text: 'Cancelar', style: 'cancel' },
          { text: 'Ir a Efectivo', onPress: () => (navigation as any).navigate('Financieras') },
        ],
      );
      return;
    }
    (navigation as any).navigate('Sell', isSavingsAccount ? { destination: 'cusd_plus' } : undefined);
  }, [isSavingsAccount, navigation, userProfile?.phoneCountry]);

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
                Conversión {conversionDirection === 'usdc_to_cusd' ? 'USDC → cUSD' : 'cUSD → USDC'}
              </Text>
              <TouchableOpacity
                onPress={() => setShowExchangeModal(false)}
                hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                accessibilityRole="button"
                accessibilityLabel="Cerrar"
              >
                <Icon name="x" size={24} color={colors.text.secondary} />
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
                    placeholderTextColor={colors.text.light}
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
                  <Icon name="refresh-cw" size={16} color={colors.accent} />
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
                  handleConversion();
                }}
                disabled={!exchangeAmount || parseFloat(exchangeAmount) <= 0 || isProcessingConversion}
              >
                {isProcessingConversion ? (
                  <ActivityIndicator size="small" color={colors.white} />
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
      return;
    }
    if (!canQueryTransactions || !activeAccount) {
      return;
    }


    setLoadingMore(true);

    try {
      // Calculate new offset
      const newOffset = allTransactions.length;


      // Fetch more transactions with the new offset
      const { data } = await fetchMore({
        variables: {
          accountType: activeAccount?.type || 'personal',
          accountIndex: activeAccount?.index || 0,
          limit: transactionLimit,
          offset: newOffset,
          tokenTypes: accountTokenTypes
        },
        updateQuery: (prev, { fetchMoreResult }) => {

          if (!fetchMoreResult) return prev;

          if (fetchMoreResult.currentAccountTransactions.length === 0) {
            setHasReachedEnd(true);
            return prev;
          }

          // Append new transactions to allTransactions state
          const newTransactions = fetchMoreResult.currentAccountTransactions;

          // Check if we've reached the end
          if (newTransactions.length < transactionLimit) {
            setHasReachedEnd(true);
          }

          setAllTransactions(prevTxs => {
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
        navigation={navigation as any}
        title={account.name}
        backgroundColor={account.color}
        isLight={true}
        showBackButton={true}
      />

      {/* Balance Section — instrument brand field: same gradient + coin-ring
          grammar as Home/Profile (emerald for cUSD, violet for CONFIO).
          Vertical gradient meets the flat nav header without a seam; padding
          lives on balanceInner (Yoga insets absolute children by padding). */}
      <View
        style={[styles.balanceSection, { backgroundColor: account.color }]}
        onLayout={(e) => {
          const { width, height } = e.nativeEvent.layout;
          setFieldSize((prev) =>
            prev.width === width && prev.height === height ? prev : { width, height }
          );
        }}
      >
        {/* Gradient id is per-account-type: cUSD and CONFIO detail screens can
            be mounted at once in the nav stack, and RNSVG brush ids collide
            across live instances — the last registered gradient wins for both.
            key forces a clean remount whenever the measured size changes. */}
        <Svg
          key={`field-${route.params.accountType}-${fieldSize.width}x${fieldSize.height}`}
          width={fieldSize.width || '100%'}
          height={fieldSize.height || '100%'}
          style={StyleSheet.absoluteFill}
        >
          <Defs>
            <SvgLinearGradient id={`accountField-${route.params.accountType}`} x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor={account.color} />
              <Stop offset="1" stopColor={account.colorDark} />
            </SvgLinearGradient>
          </Defs>
          <Rect width="100%" height="100%" fill={`url(#accountField-${route.params.accountType})`} />
          <Circle cx="105%" cy="20%" r="90" stroke={colors.white} strokeWidth="22" strokeOpacity="0.10" fill="none" />
        </Svg>
        <View style={styles.balanceInner}>
        <View style={styles.balanceIconContainer}>
          <Image
            source={isSavingsAccount ? cUSDPlusLogo : isCusd ? cUSDLogo : CONFIOLogo}
            style={styles.balanceLogo}
          />
        </View>

        <View style={styles.balanceRow}>
          <Text style={styles.balanceText}>
            {!canViewBalance
              ? account.balanceHidden
              : (showBalance
                ? `$${formatBalanceDisplay(account.balance)}`
                : account.balanceHidden)}
          </Text>
          {canViewBalance && (
            <TouchableOpacity onPress={toggleBalanceVisibility} accessibilityRole="button" accessibilityLabel={showBalance ? 'Ocultar saldo' : 'Mostrar saldo'}>
              <Icon
                name={showBalance ? 'eye' : 'eye-off'}
                size={20}
                color={colors.white}
                style={styles.eyeIcon}
              />
            </TouchableOpacity>
          )}
        </View>

        {/* Savings hero extras (merged from SavingsScreen): the rate is the
            reason this account exists, and landed-but-unminted USDT gets
            named so the headline total is never mistaken for a discrepancy.
            Rate is server-derived and live — never hardcoded in copy. */}
        {isSavingsAccount && canViewBalance && showBalance && (
          <>
            {savingsIsYield && ahorrosSavings.netApyPct > 0 && savingsAccountTotal > 0 && (
              <Text style={styles.savingsRateLine}>
                Rindiendo ~{ahorrosSavings.netApyPct.toFixed(1)}% anual
              </Text>
            )}
            {savingsIsYield && savingsTickerParts.length > 0 && (
              <View style={styles.savingsTickerRow}>
                <Icon name="trending-up" size={14} color={colors.white} />
                <Text style={styles.savingsTicker}>{savingsTickerParts.join('  ·  ')}</Text>
              </View>
            )}
            {savingsIsYield && (ahorrosUsdt || 0) > 0 && (
              <Text style={styles.savingsSplitLine}>
                En camino a tu ahorro ${formatBalanceDisplay(String(ahorrosUsdt))}
              </Text>
            )}
            {!savingsIsYield && ahorrosSavings.balanceUsd > 0 && (
              <Text style={styles.savingsSplitLine}>
                Ahorro por retirar ${formatBalanceDisplay(String(ahorrosSavings.balanceUsd))}
              </Text>
            )}
            {savingsAccountTotal <= 0 && (
              <Text style={styles.savingsEmptyHint}>
                {savingsIsYield
                  ? 'Tu dinero puede crecer mientras duerme'
                  : 'Dólares digitales, siempre tuyos'}
              </Text>
            )}
          </>
        )}

        {/* Show locked status for CONFIO tokens - only if balance > 0 */}
        {route.params.accountType === 'confio' && canViewBalance && showBalance && (parseFloat(account.balance) > 0 || confioLocked > 0) && (
          <View style={styles.lockedStatusContainer}>
            <View style={styles.lockedStatusRow}>
              <Icon name="lock" size={14} color="#fbbf24" />
              <Text style={styles.lockedStatusText}>
                Bloqueado: ${formatBalanceDisplay(confioLocked)} $CONFIO
              </Text>
            </View>
            <View style={styles.lockedStatusRow}>
              <Icon name="unlock" size={14} color={colors.white} style={{ opacity: 0.5 }} />
              <Text style={styles.lockedStatusText}>
                Disponible: ${formatBalanceDisplay(confioLive)} $CONFIO
              </Text>
            </View>
            <Text style={styles.lockedStatusDescription}>
              Se desbloquearán cuando Confío alcance adopción masiva en toda Latinoamérica
            </Text>
          </View>
        )}

        <Text style={[styles.balanceDescription, isSavingsAccount && styles.savingsDescriptionSpacing]}>
          {account.description}
        </Text>
        {/* Hide address for employees without viewBusinessAddress permission */}
        {(!activeAccount?.isEmployee || activeAccount?.employeePermissions?.viewBusinessAddress) && account.address && (
          <View style={styles.addressContainer}>
            <Text style={styles.addressText}>{account.addressShort}</Text>
            <TouchableOpacity onPress={() => {
              if (account.address) {
                Clipboard.setString(account.address);
                setCopyBanner(true);
              }
            }} accessibilityRole="button" accessibilityLabel="Copiar dirección">
              <Icon name="copy" size={16} color={colors.white} style={styles.copyIcon} />
            </TouchableOpacity>
          </View>
        )}
        </View>
      </View>

      {copyBanner && (
        <InlineBanner
          message="Dirección copiada al portapapeles"
          variant="success"
          onDismiss={() => setCopyBanner(false)}
          autoHideMs={2000}
          style={{ marginHorizontal: 16, marginTop: 10, marginBottom: 0 }}
        />
      )}

      {/* cUSD phase-out notice — persistent (no onDismiss), calm info tone */}
      {isCusdRetiroOnly && (
        <InlineBanner
          variant="info"
          message="El Antiguo Confío Dollar (cUSD) ya no recibe recargas nuevas. Puedes seguir enviando, pagando y retirando tu saldo — el dinero nuevo ahora crece en Confío Dollar+."
          style={{ marginHorizontal: 16, marginTop: 10, marginBottom: 0 }}
        />
      )}

      {/* Action Buttons */}
      {/* The card tucks under the green header (negative margin); when a banner
          sits in between, drop the overlap so it doesn't cover the banner. */}
      <View style={[styles.actionButtonsContainer, (copyBanner || isCusdRetiroOnly) && styles.actionButtonsContainerBelowBanner]}>
        {activeAccount?.isEmployee && !activeAccount?.employeePermissions?.sendFunds ? (
          // Employee welcome message
          <View style={styles.employeeMessageContainer}>
            <View style={styles.employeeMessageIcon}>
              <Icon name="briefcase" size={32} color={colors.secondaryDark} />
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
                accessibilityRole="button"
                accessibilityLabel="Enviar"
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
                  <Icon name="send" size={22} color={colors.white} />
                </View>
                <Text style={styles.actionButtonText}>Enviar</Text>
              </TouchableOpacity>
            )}

            {/* Algorand receive hides for cUSD once deposits pause (the
                phase-out blocks the deposit UI); CONFIO keeps its receive —
                no BSC alternative exists for it yet. */}
            {(!activeAccount?.isEmployee || activeAccount?.employeePermissions?.acceptPayments) &&
              !isCusdRetiroOnly && (
              <TouchableOpacity
                style={styles.actionButton}
                onPress={() => {
                  // Same verb, per-account destination: the savings account
                  // receives USDT-BSC on its own address, not an Algorand asset.
                  if (isSavingsAccount) {
                    (navigation as any).navigate('ReceiveSavings', { destination: 'cusd_plus' });
                    return;
                  }
                  navigation.navigate('USDCDeposit', {
                    tokenType: isCusd ? 'cusd' : 'confio'
                  });
                }}
                accessibilityRole="button"
                accessibilityLabel="Recibir"
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
                  <Icon name="download" size={22} color={colors.white} />
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
                  (navigation as any).navigate('BottomTabs', {
                    screen: isBusinessAccount ? 'Charge' : 'Scan'
                  });
                }}
                accessibilityRole="button"
                accessibilityLabel="Pagar"
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
                  <Icon name="shopping-bag" size={22} color={colors.white} />
                </View>
                <Text style={styles.actionButtonText}>Pagar</Text>
              </TouchableOpacity>
            )}

            {!activeAccount?.isEmployee && !isCusdRetiroOnly && (
              <TouchableOpacity
                style={styles.actionButton}
                onPress={() => {
                  // "Ahorrar" was never a separate verb — recharging the
                  // savings account IS this button, pointed at the BSC rail.
                  (navigation as any).navigate('TopUp',
                    isSavingsAccount ? { destination: 'cusd_plus' } : undefined);
                }}
                accessibilityRole="button"
                accessibilityLabel="Recargar"
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
                  <Icon name="dollar-sign" size={22} color={colors.white} />
                </View>
                <Text style={styles.actionButtonText}>Recargar</Text>
              </TouchableOpacity>
            )}

            {/* Retirar — the dollar accounts only (CONFIO has no off-ramp).
                Both settle through the same Sell flow; `destination` picks
                the rail. */}
            {(isCusd || isSavingsAccount) && !activeAccount?.isEmployee && (
              <TouchableOpacity
                style={styles.actionButton}
                onPress={handleRetirar}
                accessibilityRole="button"
                accessibilityLabel="Retirar"
              >
                <View style={{
                  width: 52,
                  height: 52,
                  borderRadius: 26,
                  backgroundColor: colors.offRampIcon,
                  justifyContent: 'center',
                  alignItems: 'center',
                  marginBottom: 8,
                }}>
                  <MCIcon name="bank" size={22} color={colors.white} />
                </View>
                <Text style={styles.actionButtonText}>Retirar</Text>
              </TouchableOpacity>
            )}
          </View>
        )}
      </View>
      <SectionList
        style={styles.scrollView}
        sections={groupedTransactions}
        keyExtractor={(item, index) => `${item.id || item.transactionHash || index}-${index}`}
        renderItem={({ item }) => (
          <TransactionItem
            transaction={item}
            activeAccount={activeAccount}
            userProfile={userProfile}
          />
        )}
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
            <EmptyState
              icon={searchQuery ? 'search' : 'inbox'}
              title={searchQuery ? 'No se encontraron transacciones' : 'No hay transacciones aún'}
              subtitle={
                searchQuery
                  ? 'Intenta con otros términos de búsqueda'
                  : 'Tus transacciones aparecerán aquí cuando realices envíos o pagos'
              }
              actionLabel={searchQuery ? undefined : 'Hacer mi primera transacción'}
              onAction={searchQuery ? undefined : handleSend}
            />
          );
        }}
        ListFooterComponent={() => {
          if (!unifiedLoading && allTransactions.length >= transactionLimit && !hasReachedEnd) {
            return (
              <TouchableOpacity
                style={styles.loadMoreButton}
                onPress={loadMoreTransactions}
                disabled={loadingMore}
                accessibilityRole="button"
                accessibilityLabel="Ver más transacciones"
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
            loadMoreTransactions();
          }
        }}
        onEndReachedThreshold={0.3}
        stickySectionHeadersEnabled={false}
        showsVerticalScrollIndicator={true}
        contentContainerStyle={filteredTransactions.length === 0 ? styles.emptyListContainer : undefined}
        ListHeaderComponent={() => (
          <>
            {/* USDC Balance Section (Gestión Avanzada) - commented out: USDC is auto-converted to cUSD */}
            {/* {route.params.accountType === 'cusd' && usdcAccount && (
              <View style={styles.usdcSection}>
                <View style={styles.sectionHeaderContainer}>
                  <Text style={styles.sectionTitle}>Gestión Avanzada</Text>
                  <TouchableOpacity
                    style={styles.helpButton}
                    onPress={() => setShowHelpModal(true)}
                    hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                    accessibilityRole="button"
                    accessibilityLabel="Ayuda sobre USDC"
                  >
                    <Icon name="help-circle" size={18} color={colors.text.secondary} />
                  </TouchableOpacity>
                </View>

                <View style={styles.usdcCard}>
                  <View style={styles.usdcHeader}>
                    <View style={styles.usdcInfo}>
                      <View style={styles.usdcLogoContainer}>
                        <Image source={USDCLogo} style={styles.usdcLogo} />
                        <View style={styles.usdcBadge}>
                          <Text style={styles.usdcBadgeText}>ALGO</Text>
                        </View>
                      </View>
                      <View style={styles.usdcTextContainer}>
                        <Text style={styles.usdcName}>{usdcAccount.name}</Text>
                        <Text style={styles.usdcDescription}>
                          Convierte entre USDC y cUSD
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
                    <Icon name="info" size={14} color={colors.accent} />
                    <Text style={styles.exchangeRateText}>
                      1 USDC = 1 cUSD • Sin comisión
                    </Text>
                  </View>

                  <View style={styles.usdcActions}>
                    <TouchableOpacity
                      style={[styles.usdcActionButton, { backgroundColor: colors.warningLight, borderWidth: 1, borderColor: colors.offRampIcon }]}
                      onPress={() => navigation.navigate('Sell')}
                    >
                      <MCIcon name="bank" size={14} color={colors.warning.text} style={{ marginRight: 8 }} />
                      <View style={styles.actionTextContainer}>
                        <Text style={[styles.usdcActionButtonText, { color: colors.warning.text }]}>Retirar</Text>
                        <Text style={[styles.usdcActionSubtext, { color: '#B45309' }]}>A tu banco</Text>
                      </View>
                    </TouchableOpacity>

                    <Animated.View style={hasUsdcToConvert ? [{ transform: [{ scale: convertPulseAnim }] }] : undefined}>
                      <TouchableOpacity
                        style={[styles.usdcActionButton, styles.usdcSecondaryButton]}
                        onPress={() => {
                          navigation.navigate('USDCConversion');
                        }}
                      >
                        <Icon name="refresh-cw" size={16} color={colors.white} style={{ marginRight: 8 }} />
                        <View style={styles.actionTextContainer}>
                          <Text style={[styles.usdcActionButtonText, { color: colors.white }]}>
                            Convertir
                          </Text>
                          <Text style={[styles.usdcActionSubtext, { color: 'rgba(255,255,255,0.8)' }]}>
                            USDC ↔ cUSD
                          </Text>
                        </View>
                      </TouchableOpacity>
                    </Animated.View>

                    <TouchableOpacity
                      style={styles.usdcMoreButton}
                      onPress={() => setShowMoreOptionsModal(true)}
                      hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                      accessibilityRole="button"
                      accessibilityLabel="Más opciones de USDC"
                    >
                      <Icon name="more-horizontal" size={20} color={colors.text.secondary} />
                    </TouchableOpacity>
                  </View>

                  <Text style={styles.usdcDisclaimer}>
                    Para usuarios avanzados • Requiere conocimiento de billeteras Algorand
                  </Text>
                </View>
              </View>
            )} */}

            {/* CONFIO Presale Section - Only show for CONFIO accounts and if presale is active */}
            {route.params.accountType === 'confio' && isPresaleActive && (
              <View style={styles.confioPresaleSection}>
                <View style={styles.sectionHeaderContainer}>
                  <Text style={styles.sectionTitle}>💎 Sobre la Moneda $CONFIO</Text>
                </View>

                <View style={styles.confioPresaleCard}>
                  <View style={styles.confioPresaleHeader}>
                    <View style={styles.confioPresaleInfo}>
                      <Text style={styles.confioPresaleTitle}>Utilidad, gobernanza y cómo obtenerla</Text>
                      <Text style={styles.confioPresaleDescription}>
                        La moneda de la comunidad Confío: tu voz en las
                        decisiones del proyecto. Gánala invitando amigos o
                        consíguela temprano en la preventa.
                      </Text>
                    </View>
                  </View>

                  <TouchableOpacity
                    style={styles.confioPresaleButton}
                    onPress={() => navigation.navigate('ConfioPresale')}
                  >
                    <Icon name="info" size={16} color={colors.white} style={{ marginRight: 8 }} />
                    <View style={styles.actionTextContainer}>
                      <Text style={[styles.confioPresaleButtonText, { color: colors.white }]}>
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

            {/* Savings education + partnership (merged from SavingsScreen).
                ONE education door rather than inline sections: respaldo,
                tasa, costos and retiros all live in ProtectedSavings. */}
            {isSavingsAccount && (
              <>
                <TouchableOpacity
                  style={styles.howItWorksRow}
                  onPress={() => (navigation as any).navigate('ProtectedSavings')}
                  activeOpacity={0.8}
                  accessibilityRole="button"
                  accessibilityLabel="Cómo funciona tu ahorro"
                >
                  <View style={styles.howItWorksIconWrap}>
                    <Icon name="shield" size={16} color={colors.primaryDark} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.howItWorksTitle}>¿Cómo funciona?</Text>
                    <Text style={styles.howItWorksSub}>
                      {savingsIsYield
                        ? 'Respaldo, rendimiento y costos — sin letra chica'
                        : 'Respaldo verificable y costos — sin letra chica'}
                    </Text>
                  </View>
                  <Icon name="chevron-right" size={18} color={colors.text.light} />
                </TouchableOpacity>

                {/* Partnership: real logo, nominative use. */}
                <View style={styles.partnerRow}>
                  <Text style={styles.partnerText}>En alianza con</Text>
                  <Image source={OndoLogo} style={styles.partnerLogo} />
                  <Text style={styles.partnerBrand}>Ondo Finance</Text>
                </View>
              </>
            )}

            {/* Enhanced Transactions Section */}
            <View style={styles.transactionsSection}>
              <View style={styles.transactionsHeader}>
                <Text style={styles.transactionsTitle}>Historial de transacciones</Text>
                <View style={styles.transactionsFilters}>
                  <TouchableOpacity
                    style={[styles.filterButton, showSearch && styles.filterButtonActive]}
                    onPress={() => setShowSearch(!showSearch)}
                    accessibilityRole="button"
                    accessibilityLabel={showSearch ? 'Ocultar búsqueda' : 'Mostrar búsqueda'}
                  >
                    <Icon name="search" size={16} color={showSearch ? account.textColor : colors.text.secondary} />
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[
                      styles.filterButton,
                      hasActiveFilters() && styles.filterButtonActive
                    ]}
                    onPress={() => setShowFilterModal(true)}
                    accessibilityRole="button"
                    accessibilityLabel="Abrir filtros de transacciones"
                  >
                    <Icon
                      name="filter"
                      size={16}
                      color={hasActiveFilters() ? account.textColor : colors.text.secondary}
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
                          translateY: searchTranslateY
                        }
                      ]
                    }
                  ]}
                >
                  <Icon name="search" size={18} color={colors.text.light} style={styles.searchIcon} />
                  <TextInput
                    style={styles.searchInput}
                    placeholder="Buscar transacciones..."
                    placeholderTextColor={colors.text.light}
                    value={searchQuery}
                    onChangeText={setSearchQuery}
                    autoCapitalize="none"
                    autoCorrect={false}
                  />
                  {searchQuery.length > 0 && (
                    <TouchableOpacity onPress={() => setSearchQuery('')} accessibilityRole="button" accessibilityLabel="Limpiar búsqueda">
                      <Icon name="x" size={18} color={colors.text.light} />
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
              <TouchableOpacity onPress={() => setShowHelpModal(false)} accessibilityRole="button" accessibilityLabel="Cerrar ayuda">
                <Icon name="x" size={24} color={colors.text.secondary} />
              </TouchableOpacity>
            </View>

            <ScrollView
              style={styles.helpModalBody}
              contentContainerStyle={styles.helpModalScrollContent}
              showsVerticalScrollIndicator={true}
              bounces={true}
            >
              <View style={styles.helpSection}>
                <Icon name="info" size={20} color={colors.accent} style={styles.helpIcon} />
                <View style={styles.helpTextContainer}>
                  <Text style={styles.helpSectionTitle}>USDC en red de Algorand</Text>
                  <Text style={styles.helpSectionText}>
                    USDC es una moneda estable respaldada 1:1 por dólares estadounidenses.
                    Puedes depositar USDC desde la red de Algorand y convertirlo a cUSD sin comisiones.
                  </Text>
                </View>
              </View>

              <View style={styles.helpSection}>
                <Icon name="shield" size={20} color={colors.primaryDark} style={styles.helpIcon} />
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
                <Icon name="users" size={20} color={colors.secondary} style={styles.helpIcon} />
                <View style={styles.helpTextContainer}>
                  <Text style={styles.helpSectionTitle}>¿Para quién es?</Text>
                  <Text style={styles.helpSectionText}>
                    Esta función es para usuarios avanzados que ya tienen USDC en wallets
                    de Algorand como Pera Wallet, Binance o exchanges compatibles.
                  </Text>
                </View>
              </View>

              <View style={styles.helpSection}>
                <Icon name="zap" size={20} color={colors.offRampIcon} style={styles.helpIcon} />
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
              accessibilityRole="button"
              accessibilityLabel="Entendido"
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
                navigation.navigate('USDCDeposit', { tokenType: 'usdc' });
              }}
              accessibilityRole="button"
              accessibilityLabel="Depositar USDC"
            >
              <Icon name="download" size={20} color={colors.text.primary} />
              <Text style={styles.moreOptionsItemText}>Depositar USDC</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.moreOptionsItem}
              onPress={() => {
                setShowMoreOptionsModal(false);
                // @ts-ignore
                navigation.navigate('SendWithAddress', { tokenType: 'usdc' });
              }}
              accessibilityRole="button"
              accessibilityLabel="Retirar USDC a Algorand"
            >
              <Icon name="arrow-up-circle" size={20} color={colors.text.primary} />
              <Text style={styles.moreOptionsItemText}>Retirar USDC a Algorand</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.moreOptionsItem}
              onPress={() => {
                setShowMoreOptionsModal(false);
                navigation.navigate('USDCHistory');
              }}
              accessibilityRole="button"
              accessibilityLabel="Ver historial de conversiones"
            >
              <Icon name="clock" size={20} color={colors.text.primary} />
              <Text style={styles.moreOptionsItemText}>Historial de conversiones</Text>
            </TouchableOpacity>



            <TouchableOpacity
              style={[styles.moreOptionsItem, styles.moreOptionsCancelItem]}
              onPress={() => setShowMoreOptionsModal(false)}
              accessibilityRole="button"
              accessibilityLabel="Cerrar más opciones"
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
        availableCurrencies={currencyChips}
        theme={{
          primary: account.color,
          secondary: colors.secondary,
        }}
      />

      {/* The Algorand auto-swaps take priority: they are recovery-capable and
          carry the wallet-recovery mode. The savings mint reuses the same
          spinner so background conversions never move money silently. */}
      <AutoSwapModal
        visible={!!swapModalAsset || walletRecoveryRequired || mintingSavings}
        assetType={swapModalAsset || (mintingSavings ? 'USDT' : 'USDC')}
        mode={walletRecoveryRequired ? 'wallet_recovery_required' : 'processing'}
        onClose={dismissWalletRecovery}
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
    overflow: 'hidden',
  },
  balanceInner: {
    paddingTop: 12,
    paddingBottom: 24,
    paddingHorizontal: 20,
    alignItems: 'center',
  },
  balanceIconContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.white,
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
    color: colors.white,
    marginRight: 8,
  },
  eyeIcon: {
    opacity: 0.8,
  },
  balanceDescription: {
    fontSize: 14,
    color: colors.white,
    opacity: 0.8,
    marginBottom: 4,
  },
  howItWorksRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
  },
  howItWorksIconWrap: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primarySoft,
  },
  howItWorksTitle: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  howItWorksSub: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },
  partnerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    marginBottom: 16,
  },
  partnerText: { fontSize: 12, color: colors.text.secondary },
  partnerLogo: { width: 16, height: 16, resizeMode: 'contain' },
  partnerBrand: { fontSize: 12, fontWeight: '700', color: colors.text.primary },
  savingsActionIcon: {
    width: 52,
    height: 52,
    borderRadius: 26,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 8,
  },
  savingsActionIconOff: { opacity: 0.4 },
  // Mirrors SavingsScreen's hero rhythm verbatim — that screen's calm comes
  // from consistent 6/8pt steps at one type size, not from tighter packing.
  savingsRateLine: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.white,
    opacity: 0.95,
    marginTop: 6,
  },
  savingsSplitLine: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.white,
    opacity: 0.9,
    marginTop: 6,
  },
  savingsTickerRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 8 },
  savingsTicker: { fontSize: 13, color: colors.white, opacity: 0.9 },
  savingsEmptyHint: {
    fontSize: 13,
    color: colors.white,
    opacity: 0.85,
    marginTop: 8,
    textAlign: 'center',
    paddingHorizontal: 24,
  },
  // balanceDescription has no marginTop, so it collides with whatever the
  // savings hero adds above it. Give the savings variant a real gap.
  savingsDescriptionSpacing: { marginTop: 14 },
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
    color: colors.white,
    opacity: 0.9,
  },
  lockedStatusDescription: {
    fontSize: 11,
    color: colors.white,
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
    color: colors.white,
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
  actionButtonsContainerBelowBanner: {
    marginTop: 12,
  },
  employeeMessageContainer: {
    backgroundColor: colors.white,
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
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  employeeMessageTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text.primary,
    textAlign: 'center',
    marginBottom: 8,
  },
  employeeMessageText: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 20,
  },
  actionButtons: {
    backgroundColor: colors.white,
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
    color: colors.text.primary,
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
    color: colors.text.primary,
  },
  helpButton: {
    padding: 4,
  },
  usdcCard: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.border,
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
    backgroundColor: colors.accent,
    borderRadius: 8,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderWidth: 2,
    borderColor: colors.white,
  },
  usdcBadgeText: {
    fontSize: 10,
    fontWeight: 'bold',
    color: colors.white,
  },
  usdcTextContainer: {
    flex: 1,
  },
  usdcName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.text.primary,
    marginBottom: 2,
  },
  usdcDescription: {
    fontSize: 13,
    color: colors.text.secondary,
  },
  usdcBalance: {
    alignItems: 'flex-end',
  },
  usdcBalanceText: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.text.primary,
  },
  usdcSymbol: {
    fontSize: 12,
    color: colors.text.secondary,
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
    color: colors.accent,
    marginLeft: 6,
    fontWeight: '500',
  },
  usdcActions: {
    flexDirection: 'row',
  },
  usdcActionButton: {
    flex: 1,
    flexDirection: 'row',
    backgroundColor: colors.neutralDark,
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
    backgroundColor: colors.neutralDark,
    width: 44,
    height: 44,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionTextContainer: {
    alignItems: 'flex-start',
  },
  usdcActionButtonText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.primary,
  },
  usdcActionSubtext: {
    fontSize: 11,
    color: colors.text.secondary,
    marginTop: 1,
  },
  usdcDisclaimer: {
    fontSize: 12,
    color: colors.text.secondary,
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
    color: colors.text.primary,
  },
  transactionsFilters: {
    flexDirection: 'row',
  },
  filterButton: {
    padding: 8,
    backgroundColor: colors.white,
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
    backgroundColor: colors.white,
    borderRadius: 12,
    padding: 16,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: colors.neutralDark,
  },
  invitedTransactionItem: {
    backgroundColor: colors.warning.background,
    borderColor: colors.warning.border,
  },
  revertedTransactionItem: {
    backgroundColor: colors.error.background,
    borderColor: colors.error.border,
  },
  transactionIconContainer: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  transactionInfo: {
    flex: 1,
  },
  transactionTitleRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  transactionTitle: {
    fontSize: 14,
    lineHeight: 20,
    fontWeight: '500',
    color: colors.text.primary,
  },
  lastWordBadgeGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  inlineVerifiedBadge: {
    width: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: colors.accent,
    justifyContent: 'center',
    alignItems: 'center',
  },
  inlineTierEmoji: {
    fontSize: 11,
  },
  transactionDate: {
    fontSize: 12,
    color: colors.text.secondary,
  },
  transactionSubtitleContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  originalName: {
    color: colors.borderMedium,
    fontSize: 11,
    fontStyle: 'italic',
  },
  invitationNote: {
    fontSize: 12,
    marginTop: 2,
    fontWeight: '600',
  },
  invitationNotePending: {
    color: colors.warning.text,
  },
  invitationNoteClaimed: {
    color: colors.primaryDark,
  },
  invitationNoteReverted: {
    color: colors.error.icon,
  },
  externalWalletNote: {
    fontSize: 12,
    color: '#1E40AF',
    marginTop: 2,
    fontWeight: '500',
  },
  rewardNote: {
    fontSize: 12,
    color: '#B45309',
    marginTop: 2,
    fontWeight: '600',
  },
  presaleNote: {
    fontSize: 12,
    color: '#4F46E5',
    marginTop: 2,
    fontWeight: '600',
  },
  transactionAmount: {
    alignItems: 'flex-end',
  },
  transactionAmountText: {
    fontSize: 16,
    fontWeight: 'bold',
  },
  positiveAmount: {
    color: colors.primaryDark,
  },
  // Outgoing money is normal, not an alert — red stays reserved for failures.
  negativeAmount: {
    color: colors.text.primary,
  },
  transactionStatus: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 2,
  },
  statusText: {
    fontSize: 12,
    marginRight: 4,
  },
  statusTextPending: {
    color: colors.offRampIcon, // amber
  },
  statusTextFailed: {
    color: colors.danger, // red
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  statusDotPending: { backgroundColor: colors.offRampIcon },
  statusDotFailed: { backgroundColor: colors.danger },
  viewMoreButton: {
    backgroundColor: colors.white,
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 24,
    alignItems: 'center',
    marginTop: 16,
    marginHorizontal: 16,
    borderWidth: 1,
    borderColor: colors.border,
  },
  viewMoreButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.secondary,
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
    backgroundColor: colors.white,
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
    color: colors.text.primary,
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
    color: colors.text.secondary,
  },
  exchangeInput: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  exchangeInputText: {
    flex: 1,
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.text.primary,
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
    color: colors.white,
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
    color: colors.text.primary,
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
    color: colors.text.secondary,
  },
  feeValue: {
    fontSize: 12,
    fontWeight: '500',
    color: colors.text.primary,
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
    color: colors.text.secondary,
    marginLeft: 4,
  },
  feeDivider: {
    height: 1,
    backgroundColor: colors.border,
    marginBottom: 12,
  },
  feeTotalLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  feeTotalValue: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
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
    color: colors.white,
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
    color: colors.text.secondary,
    textAlign: 'center',
  },
  searchContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.white,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: colors.border,
  },
  searchIcon: {
    marginRight: 8,
  },
  searchInput: {
    flex: 1,
    fontSize: 14,
    color: colors.text.primary,
    padding: 0,
  },
  sectionHeader: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.secondary,
    marginTop: 8,
    marginBottom: 8,
    marginHorizontal: 16,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  filterButtonActive: {
    backgroundColor: colors.neutralDark,
    borderWidth: 1,
    borderColor: colors.border,
  },
  // Help Modal Styles
  helpModalContent: {
    backgroundColor: colors.white,
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
    borderBottomColor: colors.border,
  },
  helpModalTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.text.primary,
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
    color: colors.text.primary,
    marginBottom: 4,
  },
  helpSectionText: {
    fontSize: 14,
    color: colors.text.secondary,
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
    color: colors.white,
    fontSize: 16,
    fontWeight: '600',
  },
  // More Options Modal Styles
  moreOptionsModalContent: {
    backgroundColor: colors.white,
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
    backgroundColor: colors.border,
    borderRadius: 2,
    alignSelf: 'center',
    marginTop: 12,
    marginBottom: 20,
  },
  moreOptionsTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.text.primary,
    paddingHorizontal: 20,
    marginBottom: 16,
  },
  moreOptionsItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 16,
    paddingHorizontal: 20,
    borderBottomWidth: 1,
    borderBottomColor: colors.neutralDark,
  },
  moreOptionsItemText: {
    fontSize: 16,
    color: colors.text.primary,
    marginLeft: 16,
  },
  moreOptionsCancelItem: {
    marginTop: 8,
    borderBottomWidth: 0,
    justifyContent: 'center',
  },
  moreOptionsCancelText: {
    fontSize: 16,
    color: colors.text.secondary,
    textAlign: 'center',
    fontWeight: '500',
  },
  // Exchange Modal Styles
  exchangeModalContent: {
    backgroundColor: colors.white,
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
    borderBottomColor: colors.border,
  },
  exchangeModalTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.text.primary,
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
    color: colors.text.secondary,
    marginBottom: 8,
  },
  exchangeModalInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
    marginBottom: 12,
  },
  exchangeModalInput: {
    flex: 1,
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.text.primary,
    padding: 0,
  },
  exchangeCurrency: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text.secondary,
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
    color: colors.accent,
    marginLeft: 6,
    fontWeight: '500',
  },
  exchangeInfo: {
    backgroundColor: colors.neutral,
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
    color: colors.text.secondary,
  },
  exchangeInfoValue: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.primary,
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
    color: colors.white,
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
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.border,
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
    color: colors.text.primary,
    marginBottom: 4,
  },
  confioPresaleDescription: {
    fontSize: 13,
    color: colors.text.secondary,
    lineHeight: 18,
  },
  confioPresaleButton: {
    backgroundColor: colors.secondary,
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 12,
    ...Platform.select({
      ios: {
        shadowColor: colors.secondary,
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
