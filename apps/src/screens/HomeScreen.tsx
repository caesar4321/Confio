import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Pressable,
  Platform,
  Alert,
  ScrollView,
  Image,
  RefreshControl,
  Animated,
  Dimensions,
  Vibration,
  AppState,
  AppStateStatus
} from 'react-native';
import ConvertModal from '../components/ConvertModal';
import { Gradient } from '../components/common/Gradient';
import { AuthService } from '../services/authService';
import { useNavigation, useFocusEffect, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useAuth } from '../contexts/AuthContext';
import { waitForAuthReady } from '../contexts/AuthContext';
import { useHeader } from '../contexts/HeaderContext';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import Icon from 'react-native-vector-icons/Feather';
import FAIcon from 'react-native-vector-icons/FontAwesome';
import InviteClaimBanner from '../components/InviteClaimBanner';
import * as Keychain from 'react-native-keychain';
import { getApiUrl } from '../config/env';
import { jwtDecode } from 'jwt-decode';
import { RootStackParamList, MainStackParamList } from '../types/navigation';
import { ProfileMenu } from '../components/ProfileMenu';
import { useAccount } from '../contexts/AccountContext';
import { useAtomicAccountSwitch } from '../hooks/useAtomicAccountSwitch';
import { PushNotificationService } from '../services/pushNotificationService';
import { AccountSwitchOverlay } from '../components/AccountSwitchOverlay';
import { getCountryByIso } from '../utils/countries';
import { WalletCardSkeleton } from '../components/SkeletonLoader';
import { gql, useQuery, useMutation, useApolloClient } from '@apollo/client';
import { GET_PRESALE_STATUS, GET_MY_BALANCES, GET_USER_ACCOUNTS, GET_ACTIVE_PRESALE, GET_ALL_PRESALE_PHASES, CHECK_REFERRAL_STATUS } from '../apollo/queries';
import { REFRESH_ACCOUNT_BALANCE, SET_REFERRER } from '../apollo/mutations';
import { useCountry } from '../contexts/CountryContext';
import algorandService from '../services/algorandService';
import { useCurrency } from '../hooks/useCurrency';
import { useSelectedCountryRate } from '../hooks/useExchangeRate';
import { inviteSendService } from '../services/inviteSendService';
import { GET_PENDING_PAYROLL_ITEMS } from '../apollo/queries';
import { LoadingOverlay } from '../components/LoadingOverlay';
import { ReferralInputModal } from '../components/ReferralInputModal';
import { ReferralSuccessModal } from '../components/ReferralSuccessModal';
import AutoSwapModal from '../components/AutoSwapModal';
import { useAutoSwap } from '../hooks/useAutoSwap';
import { deepLinkHandler } from '../utils/deepLinkHandler';
import { TextInput } from 'react-native';

const AUTH_KEYCHAIN_SERVICE = 'com.confio.auth';
const AUTH_KEYCHAIN_USERNAME = 'auth_tokens';
const PREFERENCES_KEYCHAIN_SERVICE = 'com.confio.preferences';
const BALANCE_VISIBILITY_KEY = 'balance_visibility';
const INVITE_TS_SERVICE = 'com.confio.preferences.invite';
const INVITE_TS_KEY = 'invite_banner_last_ts';

const formatPhoneNumber = (phoneNumber?: string, phoneCountry?: string): string => {
  if (!phoneNumber) return '';

  // If we have a country code, format it
  if (phoneCountry) {
    const country = getCountryByIso(phoneCountry);
    if (country) {
      const countryCode = country[1]; // country[1] is the phone code (e.g., '+54')
      return `${countryCode} ${phoneNumber}`;
    }
  }

  return phoneNumber;
};

interface CustomJwtPayload {
  user_id: number;
  username: string;
  exp: number;
  origIat: number;
  auth_token_version: number;
  type: 'access' | 'refresh';
}

interface Account {
  id: string;
  name: string;
  type: 'personal' | 'business';
  phone?: string;
  category?: string;
  avatar: string;
  isEmployee?: boolean;
  employeeRole?: 'cashier' | 'manager' | 'admin';
  employeePermissions?: {
    acceptPayments: boolean;
    viewTransactions: boolean;
    viewBalance: boolean;
    sendFunds: boolean;
    manageEmployees: boolean;
    viewBusinessAddress: boolean;
    viewAnalytics: boolean;
    manageP2p?: boolean;
  };
}

type HomeScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

interface QuickAction {
  id: string;
  label: string;
  icon: string;
  color: string;
  route: () => void;
}

export const HomeScreen = () => {
  const navigation = useNavigation<HomeScreenNavigationProp>();
  const route = useRoute<any>();
  const { setCurrentAccountAvatar, profileMenu } = useHeader();
  const { signOut, userProfile, isAuthenticated, profileData } = useAuth() as any;
  const { userCountry, selectedCountry } = useCountry();
  const { currency, formatAmount, exchangeRate } = useCurrency();
  const { rate: marketRate, loading: rateLoading } = useSelectedCountryRate();
  const apollo = useApolloClient();
  const [algorandAddress, setAlgorandAddress] = React.useState<string>('');
  // Show local currency by default if not in US and rate is available
  const [showLocalCurrency, setShowLocalCurrency] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [showBalance, setShowBalance] = useState(true);
  // Invite receipt banner removed; self-claim card state
  const [showInviteClaimCard, setShowInviteClaimCard] = useState(false);
  const [claimingInvite, setClaimingInvite] = useState(false);
  const [claimInviteMessage, setClaimInviteMessage] = useState<string | null>(null);
  const [claimInviteError, setClaimInviteError] = useState<string | null>(null);
  const [inviteReceiptId, setInviteReceiptId] = useState<string | undefined>(undefined);

  const [showReferralInput, setShowReferralInput] = useState(false);


  // New UX State
  // const [showConvertModal, setShowConvertModal] = useState(false); // Removed for auto-swap

  const fadeAnim = useRef(new Animated.Value(0)).current;
  const scaleAnim = useRef(new Animated.Value(0.95)).current;
  const balanceAnim = useRef(new Animated.Value(0)).current;

  // Use account context
  const {
    activeAccount,
    accounts,
    isLoading: accountsLoading,
    createAccount,
    refreshAccounts,
    getActiveAccountContext,
    syncWithServer,
  } = useAccount();

  // Use atomic account switching
  const {
    switchAccount: atomicSwitchAccount,
    state: switchState,
    isAccountSwitchInProgress
  } = useAtomicAccountSwitch();

  // Fetch all balances in a single call to avoid flicker
  const { data: myBalancesData, loading: myBalancesLoading, error: myBalancesError, refetch: refetchMyBalances } = useQuery(GET_MY_BALANCES, {
    fetchPolicy: 'network-only',
    nextFetchPolicy: 'network-only',
    notifyOnNetworkStatusChange: true,
  });
  const [refreshAccountBalance] = useMutation(REFRESH_ACCOUNT_BALANCE);
  const [checkReferralStatus, { data: referralStatusData }] = useMutation(CHECK_REFERRAL_STATUS);
  const [setReferrerMutation] = useMutation(SET_REFERRER);

  // Use the auto-swap hook for both ALGO and USDC detection
  const { swapModalAsset } = useAutoSwap({
    isAuthenticated,
    myBalancesLoading,
    usdcBalanceStr: (myBalancesData as any)?.myBalances?.usdc || '0',
    algoBalanceStr: (myBalancesData as any)?.myBalances?.algo || '0',
    refreshAccountBalance
  });

  // Check if presale is globally active / claims unlocked
  const { data: presaleStatusData } = useQuery(GET_PRESALE_STATUS, {
    fetchPolicy: 'cache-and-network',
  });
  const { data: activePresaleData } = useQuery(GET_ACTIVE_PRESALE, {
    fetchPolicy: 'cache-first',
  });
  const { data: allPresalePhasesData } = useQuery(GET_ALL_PRESALE_PHASES, {
    fetchPolicy: 'cache-first',
  });
  const isBusinessAccount = (activeAccount?.type || '').toLowerCase() === 'business';
  const isPersonalAccount = (activeAccount?.type || '').toLowerCase() === 'personal';
  const isEmployeeDelegate = !!activeAccount?.isEmployee;
  const { data: pendingPayrollData, refetch: refetchPendingPayroll } = useQuery(GET_PENDING_PAYROLL_ITEMS, {
    skip: !activeAccount,
    fetchPolicy: 'cache-and-network',
  });
  const pendingPayrollCount = (isBusinessAccount || isPersonalAccount || isEmployeeDelegate)
    ? (pendingPayrollData?.pendingPayrollItems?.length || 0)
    : 0;
  const isPresaleActive = presaleStatusData?.isPresaleActive === true;
  const isPresaleClaimsUnlocked = presaleStatusData?.isPresaleClaimsUnlocked === true;
  const [presaleDismissed, setPresaleDismissed] = useState(false);
  const showPayrollCard = (isBusinessAccount || isEmployeeDelegate || isPersonalAccount) && pendingPayrollCount > 0;

  // Refetch balances when active account changes
  useEffect(() => {
    if (activeAccount) {
      refetchMyBalances();
    }
  }, [activeAccount?.id, activeAccount?.type, activeAccount?.index, refetchMyBalances]);

  // Force refresh balances when navigating to this screen
  useFocusEffect(
    useCallback(() => {
      console.log('HomeScreen focused - refreshing balances and payroll');
      refetchMyBalances();
      refetchPendingPayroll();
      // Also nudge account refresh on focus in case auth just resumed
      try { refreshAccounts(); } catch { }
    }, [refetchMyBalances, refetchPendingPayroll])
  );

  // Extra guard: subscribe to navigation focus event to refetch
  useEffect(() => {
    const unsubscribe = navigation.addListener('focus', () => {
      console.log('HomeScreen navigation focus - refetching balances and payroll');
      refetchMyBalances();
      refetchPendingPayroll();
    });
    return unsubscribe;
  }, [navigation, refetchMyBalances, refetchPendingPayroll]);

  // On initial mount after auth, pull accounts once to avoid blank ProfileMenu
  useEffect(() => {
    if (isAuthenticated) {
      console.log('HomeScreen - Authenticated on mount, refreshing accounts');
      refreshAccounts();
      // Retry once shortly after in case token just switched contexts
      const t = setTimeout(() => {
        console.log('HomeScreen - Retrying accounts refresh');
        refreshAccounts();
      }, 600);
      return () => clearTimeout(t);
    }
  }, [isAuthenticated, refreshAccounts]);

  // State for deferred referral success modal
  const [showDeferredReferralSuccess, setShowDeferredReferralSuccess] = useState(false);

  // Helper function to format error messages (same as ReferralInputModal)
  const formatReferralErrorMessage = (rawMessage: string | undefined): string => {
    if (!rawMessage) {
      return 'Error al registrar referidor';
    }

    if (/rate limit/i.test(rawMessage)) {
      const minutesMatch = rawMessage.match(/(\d+)\s*minutes?/i);
      if (minutesMatch) {
        const minutes = minutesMatch[1];
        return `Has intentado demasiadas veces. Por favor espera ${minutes} minuto${minutes === '1' ? '' : 's'} antes de intentar nuevamente.`;
      }
      return 'Has intentado demasiadas veces. Por favor espera unos minutos antes de intentar nuevamente.';
    }

    if (/suspicious/i.test(rawMessage)) {
      return 'Detectamos actividad inusual. Por favor contacta a soporte.';
    }

    return rawMessage;
  };

  // Check for deferred referral link and register automatically
  useEffect(() => {
    const checkDeferredReferral = async () => {
      if (!isAuthenticated) return;

      try {
        const link = await deepLinkHandler.getDeferredLink();
        if (link && link.type === 'referral') {
          console.log('[HomeScreen] Found deferred referral:', link.payload);

          // Submit to backend
          const { data, errors } = await setReferrerMutation({
            variables: { referrerIdentifier: link.payload }
          });

          console.log('[HomeScreen] Referral submission result:', data);

          // Handle GraphQL errors
          if (errors && errors.length > 0) {
            const errorMessage = errors[0].message;
            const friendly = formatReferralErrorMessage(errorMessage);
            console.log('[HomeScreen] Referral GraphQL error:', friendly);

            // 1. Rate Limits: KEEP link, SHOW alert
            const isRateLimit = /rate limit/i.test(errorMessage) || /demasiadas veces/i.test(friendly);
            if (isRateLimit) {
              Alert.alert('Aviso', friendly, [{ text: 'OK' }]);
              return;
            }

            // 2. Suspicious/Abuse: CLEAR link, SILENCE alert (to avoid loop)
            const isSuspicious = /suspicious/i.test(errorMessage) || /unusual/i.test(friendly) || /inusual/i.test(friendly);
            if (isSuspicious) {
              console.log('[HomeScreen] Suspicious activity detected, silently clearing deferred link');
              await deepLinkHandler.clearDeferredLink();
              return;
            }

            // 3. Logic Errors (Self-referral, Invalid code, Already has referrer): CLEAR link, SHOW alert
            // These are permanent errors, so we must clear the link to stop the loop.
            const isLogicError =
              /own referrer/i.test(errorMessage) || /propio referidor/i.test(friendly) ||
              /not found/i.test(errorMessage) || /no encontrado/i.test(friendly) ||
              /invalid/i.test(errorMessage) || /inválido/i.test(friendly) ||
              /already/i.test(errorMessage) || /ya tienes/i.test(friendly) || /registrado/i.test(friendly);

            if (isLogicError) {
              console.log('[HomeScreen] Permanent logic error, clearing deferred link:', friendly);
              await deepLinkHandler.clearDeferredLink();
              Alert.alert('Aviso', friendly, [{ text: 'OK' }]);
              return;
            }

            // 4. Unknown/Network Errors: KEEP link, SHOW alert (user might retry)
            Alert.alert('Aviso', friendly, [{ text: 'OK' }]);
            return;
          }

          if (data?.setReferrer?.success) {
            // Clear the deferred link after successful submission
            await deepLinkHandler.clearDeferredLink();
            // Refetch balances to show the locked reward
            refetchMyBalances();
            checkReferralStatus();
            // Show success modal
            setShowDeferredReferralSuccess(true);
          } else {
            // Ensure friendly message is a string
            const friendly = String(formatReferralErrorMessage(data?.setReferrer?.error) || 'Error desconocido');
            console.log('[HomeScreen] Referral submission failed:', friendly);

            // Check if already registered/claimed or suspicious - clear silently without showing alert
            const shouldSuppressError =
              data?.setReferrer?.message?.includes('already') ||
              data?.setReferrer?.message?.includes('Ya registraste') ||
              data?.setReferrer?.error?.includes('already') ||
              data?.setReferrer?.error?.includes('Ya registraste') ||
              /suspicious/i.test(data?.setReferrer?.error || '') ||
              /suspicious/i.test(data?.setReferrer?.message || '');

            console.log('[HomeScreen] Should suppress error?', shouldSuppressError);

            if (shouldSuppressError) {
              console.log('[HomeScreen] Suppressing error, attempting to clear link...');
              // Clear the deferred link silently - user already has a referrer or flagged as suspicious
              try {
                await deepLinkHandler.clearDeferredLink();
                console.log('[HomeScreen] Cleared deferred link successfully');
              } catch (clearErr) {
                console.error('[HomeScreen] Failed to clear deferred link:', clearErr);
              }
            } else {
              console.log('[HomeScreen] Not suppressing error, showing alert...');
              // Show alert for other errors with explicit button object
              Alert.alert('Aviso', friendly, [{ text: 'OK', onPress: () => console.log('OK Pressed') }]);
              console.log('[HomeScreen] Alert shown');
            }
          }
        }
      } catch (err: any) {
        console.error('[HomeScreen] Failed to submit deferred referral:', err);

        // Try to extract a meaningful error message
        const errorMessage = err?.graphQLErrors?.[0]?.message || err?.message;
        if (errorMessage) {
          const friendly = String(formatReferralErrorMessage(errorMessage) || 'Error desconocido');
          Alert.alert('Error', friendly, [{ text: 'OK', onPress: () => { } }]);
        } else {
          Alert.alert('Error', 'Error de conexión. Intenta de nuevo.', [{ text: 'OK', onPress: () => { } }]);
        }
      }
    };

    checkDeferredReferral();
  }, [isAuthenticated, setReferrerMutation, refetchMyBalances, checkReferralStatus]);

  // Check referral status on mount to determine if ghost field should show
  useEffect(() => {
    if (isAuthenticated) {
      checkReferralStatus();
    }
  }, [isAuthenticated, checkReferralStatus]);

  // Log any errors and data for debugging


  // Parse balances safely - memoized for performance
  const cUSDBalance = React.useMemo(() =>
    parseFloat(myBalancesData?.myBalances?.cusd || '0'),
    [myBalancesData?.myBalances?.cusd]
  );
  const usdcBalance = React.useMemo(() =>
    parseFloat(myBalancesData?.myBalances?.usdc || '0'),
    [myBalancesData?.myBalances?.usdc]
  );
  const confioLive = React.useMemo(() =>
    parseFloat(myBalancesData?.myBalances?.confio || '0'),
    [myBalancesData?.myBalances?.confio]
  );
  const confioPresaleLocked = React.useMemo(() =>
    parseFloat(myBalancesData?.myBalances?.confioPresaleLocked || '0'),
    [myBalancesData?.myBalances?.confioPresaleLocked]
  );



  const confioPriceUsd = React.useMemo(() => {
    const rawActive = activePresaleData?.activePresalePhase?.pricePerToken;
    const activeStatus = (activePresaleData?.activePresalePhase?.status || '').toLowerCase();
    const activePrice = rawActive ? parseFloat(rawActive) : NaN;

    // Only use active presale data if status is valid
    if (
      Number.isFinite(activePrice) &&
      activePrice > 0 &&
      ['active', 'completed', 'paused', 'coming_soon'].includes(activeStatus)
    ) {
      return activePrice;
    }

    const phases = allPresalePhasesData?.allPresalePhases || [];

    if (phases.length) {
      const sorted = [...phases].sort(
        (a, b) => Number(b?.phaseNumber || 0) - Number(a?.phaseNumber || 0),
      );

      const lastPhase = sorted.find((phase) => {
        const status = (phase?.status || '').toLowerCase();
        return ['active', 'completed', 'paused', 'coming_soon'].includes(status);
      });

      if (lastPhase?.pricePerToken) {
        const parsed = parseFloat(lastPhase.pricePerToken);
        if (Number.isFinite(parsed) && parsed > 0) {
          return parsed;
        }
      }
    }
    return 0.2;
  }, [activePresaleData, allPresalePhasesData]);

  const confioLocked = React.useMemo(() =>
    parseFloat(myBalancesData?.myBalances?.confioLocked || myBalancesData?.myBalances?.confioPresaleLocked || '0'),
    [myBalancesData?.myBalances?.confioLocked, myBalancesData?.myBalances?.confioPresaleLocked]
  );

  const confioTotal = React.useMemo(() => confioLive + confioLocked, [confioLive, confioLocked]);

  const confioUsdValue = React.useMemo(() => confioTotal * confioPriceUsd, [confioTotal, confioPriceUsd]);



  // Display helpers to avoid overstating balances (flooring instead of rounding)
  const floorToDecimals = React.useCallback((value: number, decimals: number) => {
    if (!isFinite(value)) return 0;
    const m = Math.pow(10, decimals);
    return Math.floor(value * m) / m;
  }, []);

  const formatFixedFloor = React.useCallback((value: number, decimals = 2) => {
    const floored = floorToDecimals(value, decimals);
    // Use toLocaleString for grouping but preserve exact decimals
    return floored.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  }, [floorToDecimals]);

  // Calculate portfolio value including CONFIO marked to current presale price
  const totalUSDValue = React.useMemo(
    () => cUSDBalance + usdcBalance + confioUsdValue,
    [cUSDBalance, usdcBalance, confioUsdValue]
  );

  // Use real exchange rate from API only - no fallbacks
  const localExchangeRate = marketRate || 1;
  const totalLocalValue = totalUSDValue * localExchangeRate;

  // Don't show local currency option if exchange rate is not available
  const canShowLocalCurrency = marketRate !== null && marketRate !== 1 && currency.code !== 'USD';

  // Debug exchange rate
  console.log('HomeScreen - Exchange rate:', {
    marketRate,
    rateLoading,
    localExchangeRate,
    totalUSDValue,
    totalLocalValue,
    currency: currency.code,
    currencySymbol: currency.symbol,
    userCountry,
    userCountryISO: userCountry?.[2],
    selectedCountry,
    selectedCountryISO: selectedCountry?.[2],
    showLocalCurrency,
    formattedLocal: formatAmount.plain(totalLocalValue),
    formattedUSD: totalUSDValue.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })
  });

  // Track initialization state (one-time) to avoid flicker
  const [isInitialized, setIsInitialized] = useState(false);
  // Only show loading during the initial pass; do not toggle back after first render
  const isLoading = !isInitialized;

  // Log any errors and data for debugging
  useEffect(() => {
    console.log('Balance query status:', {
      isInitialized,
      loading: myBalancesLoading,
      data: myBalancesData,
      error: myBalancesError?.message,
    });
    if (myBalancesError) {
      console.error('Error fetching balances:', myBalancesError);
    }
  }, [isInitialized, myBalancesLoading, myBalancesData, myBalancesError]);


  // Auto-Swap logic has been refactored into the useAutoSwap hook

  // No more mock accounts - we fetch from server

  // Convert stored accounts to the format expected by ProfileMenu
  // For personal accounts, format phone number with country code
  const accountMenuItems = accounts.map(acc => {
    if (acc.type === 'personal' && userProfile) {
      return {
        ...acc,
        phone: formatPhoneNumber(userProfile.phoneNumber, userProfile.phoneCountry), // Format phone number with country code
      };
    }
    return acc;
  });

  // Bootstrap placeholder accounts if server/state not ready yet
  const [bootstrapAccounts, setBootstrapAccounts] = useState<Account[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (!isAuthenticated) {
          if (!cancelled) setBootstrapAccounts([]);
          return;
        }
        // Only attempt bootstrap when nothing to show
        if (accountMenuItems.length > 0) {
          if (!cancelled) setBootstrapAccounts([]);
          return;
        }
        const ctx = await getActiveAccountContext();
        if (cancelled) return;
        if (ctx.type === 'business' && ctx.businessId) {
          const bp = profileData?.businessProfile;
          const name = bp?.name || 'Negocio';
          const avatar = (name || 'N').charAt(0).toUpperCase();
          setBootstrapAccounts([
            {
              id: `business_${ctx.businessId}_${ctx.index}`,
              name,
              type: 'business',
              avatar,
              category: bp?.category,
            } as Account,
          ]);
        } else {
          const name = userProfile?.firstName || userProfile?.username || 'Personal';
          const avatar = (name || 'P').charAt(0).toUpperCase();
          setBootstrapAccounts([
            {
              id: `personal_${ctx.index}`,
              name,
              type: 'personal',
              avatar,
              phone: userProfile ? formatPhoneNumber(userProfile.phoneNumber, userProfile.phoneCountry) : undefined,
            } as Account,
          ]);
        }
      } catch (e) {
        // As a last resort, show a generic personal placeholder
        setBootstrapAccounts([
          { id: 'personal_0', name: 'Personal', type: 'personal', avatar: 'P' } as Account,
        ]);
      }
    })();
    return () => { cancelled = true; };
  }, [isAuthenticated, accountMenuItems.length, getActiveAccountContext, userProfile?.firstName, userProfile?.username, userProfile?.phoneNumber, userProfile?.phoneCountry, profileData?.businessProfile?.id, profileData?.businessProfile?.name, profileData?.businessProfile?.category]);

  // Only use stored accounts normally; provide safe placeholder on startup/race
  const displayAccounts = accountMenuItems.length > 0
    ? accountMenuItems
    : (bootstrapAccounts.length > 0
      ? bootstrapAccounts
      : (() => {
        const bp = profileData?.businessProfile;
        if (bp && bp.id && bp.name) {
          return [{
            id: `business_${bp.id}_0`,
            name: bp.name,
            type: 'business' as const,
            phone: undefined,
            category: bp.category,
            avatar: (bp.name || 'N').charAt(0).toUpperCase(),
            isEmployee: false,
          }];
        }
        if (userProfile) {
          return [{
            id: 'personal_0',
            name: userProfile.firstName || userProfile.username || 'Personal',
            type: 'personal' as const,
            phone: formatPhoneNumber(userProfile.phoneNumber, userProfile.phoneCountry),
            category: undefined,
            avatar: (userProfile.firstName || userProfile.username || 'P').charAt(0).toUpperCase(),
            isEmployee: false,
          }];
        }
        return [];
      })()
    );

  // Debug display accounts
  console.log('HomeScreen - Display accounts:', {
    accountsLength: accounts.length,
    accountMenuItemsLength: accountMenuItems.length,
    bootstrapAccountsLength: bootstrapAccounts.length,
    displayAccountsLength: displayAccounts.length,
    displayAccounts: displayAccounts.map(acc => ({ id: acc.id, name: acc.name, avatar: acc.avatar, type: acc.type })),
    activeAccountId: activeAccount?.id,
    activeAccountType: activeAccount?.type,
  });

  // One-time hard hydrate of accounts from server right after mount/auth
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (!isAuthenticated) return;
        // Only if we still have just a placeholder or nothing
        if (accounts.length > 1) return;
        // Ensure we only hydrate after a fresh/finalized token is in place
        try { await waitForAuthReady(); } catch { }
        console.log('HomeScreen - Hydrating accounts via GET_USER_ACCOUNTS');
        const result = await apollo.query({
          query: GET_USER_ACCOUNTS,
          fetchPolicy: 'no-cache',
          context: { skipProactiveRefresh: true },
        });
        const list = result?.data?.userAccounts || [];
        console.log('HomeScreen - GET_USER_ACCOUNTS result count:', list.length);
        if (!cancelled && list.length >= 1) {
          try { await syncWithServer(list as any[]); } catch (e) { console.log('HomeScreen - syncWithServer failed', e); }
        } else if (!cancelled && list.length === 0) {
          // Fallback: derive accounts from profileData to populate menu promptly
          const derived: any[] = [];
          if (profileData?.userProfile) {
            derived.push({
              id: 'personal_0',
              accountType: 'personal',
              accountIndex: 0,
              displayName: profileData.userProfile.firstName || profileData.userProfile.username || 'Personal',
              avatarLetter: (profileData.userProfile.firstName || profileData.userProfile.username || 'P').charAt(0).toUpperCase(),
              isEmployee: false,
              employeeRole: null,
              employeePermissions: null,
              business: null,
            });
          }
          if (profileData?.businessProfile?.id && profileData.businessProfile.name) {
            derived.push({
              id: `business_${profileData.businessProfile.id}_0`,
              accountType: 'business',
              accountIndex: 0,
              displayName: profileData.businessProfile.name,
              avatarLetter: (profileData.businessProfile.name || 'N').charAt(0).toUpperCase(),
              isEmployee: false,
              employeeRole: null,
              employeePermissions: null,
              business: {
                id: profileData.businessProfile.id,
                name: profileData.businessProfile.name,
                category: profileData.businessProfile.category,
              }
            });
          }
          if (derived.length > 0) {
            console.log('HomeScreen - Using derived accounts from profileData:', derived.length);
            try { await syncWithServer(derived); } catch (e) { console.log('HomeScreen - derived syncWithServer failed', e); }
          }
        }
      } catch (e) {
        console.warn('HomeScreen - GET_USER_ACCOUNTS hydrate failed:', (e as any)?.message || e);
      }
    })();
    return () => { cancelled = true; };
  }, [isAuthenticated, accounts.length, apollo, syncWithServer, profileData?.userProfile?.firstName, profileData?.userProfile?.username, profileData?.businessProfile?.id, profileData?.businessProfile?.name, profileData?.businessProfile?.category]);

  // Fallback: if accounts are still empty shortly after auth/profile are ready, derive from profileData immediately
  useEffect(() => {
    if (!isAuthenticated) return;
    if (accounts.length > 0) return;
    // Try to populate from profileData without waiting on network
    const derived: any[] = [];
    if (profileData?.userProfile) {
      derived.push({
        id: 'personal_0',
        accountType: 'personal',
        accountIndex: 0,
        displayName: profileData.userProfile.firstName || profileData.userProfile.username || 'Personal',
        avatarLetter: (profileData.userProfile.firstName || profileData.userProfile.username || 'P').charAt(0).toUpperCase(),
        isEmployee: false,
        employeeRole: null,
        employeePermissions: null,
        business: null,
      });
    }
    if (profileData?.businessProfile?.id && profileData.businessProfile.name) {
      derived.push({
        id: `business_${profileData.businessProfile.id}_0`,
        accountType: 'business',
        accountIndex: 0,
        displayName: profileData.businessProfile.name,
        avatarLetter: (profileData.businessProfile.name || 'N').charAt(0).toUpperCase(),
        isEmployee: false,
        employeeRole: null,
        employeePermissions: null,
        business: {
          id: profileData.businessProfile.id,
          name: profileData.businessProfile.name,
          category: profileData.businessProfile.category,
        }
      });
    }
    if (derived.length > 0) {
      (async () => { try { await syncWithServer(derived); } catch { } })();
    }
  }, [isAuthenticated, accounts.length, profileData?.userProfile?.firstName, profileData?.userProfile?.username, profileData?.businessProfile?.id, profileData?.businessProfile?.name, profileData?.businessProfile?.category, syncWithServer]);

  // Save balance visibility preference to Keychain
  const saveBalanceVisibility = async (isVisible: boolean) => {
    try {
      await Keychain.setInternetCredentials(
        PREFERENCES_KEYCHAIN_SERVICE,
        BALANCE_VISIBILITY_KEY,
        isVisible.toString()
      );
    } catch (error) {
      console.error('Error saving balance visibility preference:', error);
    }
  };

  // Load balance visibility preference from Keychain
  const loadBalanceVisibility = async () => {
    try {
      const credentials = await Keychain.getInternetCredentials(PREFERENCES_KEYCHAIN_SERVICE);
      if (credentials && credentials.username === BALANCE_VISIBILITY_KEY) {
        setShowBalance(credentials.password === 'true');
      }
    } catch (error) {
      // No saved preference, default to showing balance
      console.log('No saved balance visibility preference, using default');
    }
  };

  // Load last shown invite timestamp
  const loadLastInviteTimestamp = async (): Promise<number | null> => {
    try {
      const creds = await Keychain.getInternetCredentials(INVITE_TS_SERVICE);
      if (creds && creds.username === INVITE_TS_KEY && creds.password) {
        const ts = parseInt(creds.password, 10);
        return isNaN(ts) ? null : ts;
      }
    } catch { }
    return null;
  };

  // Save last shown invite timestamp
  const saveLastInviteTimestamp = async (ts: number) => {
    try {
      await Keychain.setInternetCredentials(
        INVITE_TS_SERVICE,
        INVITE_TS_KEY,
        ts.toString()
      );
    } catch (e) {
      console.log('Failed to persist invite banner timestamp');
    }
  };

  // Toggle balance visibility and save preference
  const toggleBalanceVisibility = () => {
    const newVisibility = !showBalance;
    setShowBalance(newVisibility);
    saveBalanceVisibility(newVisibility);
  };

  const currentAccount = activeAccount ? {
    ...activeAccount,
    phone: activeAccount.type === 'personal' && userProfile
      ? formatPhoneNumber(userProfile.phoneNumber, userProfile.phoneCountry)
      : activeAccount.phone,
  } : (displayAccounts.length > 0 ? displayAccounts[0] : null); // Only use first account if accounts exist

  // Debug display accounts
  console.log('HomeScreen - Display accounts:', {
    accountsLength: accounts.length,
    accountMenuItemsLength: accountMenuItems.length,
    displayAccountsLength: displayAccounts.length,
    displayAccounts: displayAccounts.map(acc => ({ id: acc.id, name: acc.name, avatar: acc.avatar, type: acc.type })),
    currentAccountType: currentAccount?.type,
    currentAccountName: currentAccount?.name,
    currentAccountAvatar: currentAccount?.avatar,
    currentAccountIndex: currentAccount?.id && currentAccount.id.startsWith('business_')
      ? currentAccount.id.split('_')[2]
      : currentAccount?.id?.split('_')[1],
    activeAccountId: activeAccount?.id,
    activeAccountType: activeAccount?.type,
    activeAccountName: activeAccount?.name,
    activeAccountAvatar: activeAccount?.avatar,
    activeAccountIndex: activeAccount?.index,
    userProfileLoaded: !!userProfile,
    userProfileName: userProfile?.firstName || userProfile?.username
  });


  // Pull to refresh handler
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    // Add haptic feedback
    if (Platform.OS === 'ios') {
      Vibration.vibrate(10);
    }

    try {
      // Force refresh balances from blockchain (bypass cache)
      await Promise.all([
        refreshAccounts(),
        refreshAccountBalance(), // Force blockchain sync
      ]);
      await refetchMyBalances();
    } catch (error) {
      console.error('Error refreshing data:', error);
    } finally {
      setRefreshing(false);
    }
  }, [refreshAccounts, refetchMyBalances]);

  const handleClaimInvite = useCallback(async () => {
    if (claimingInvite) return;
    setClaimInviteError(null);
    setClaimInviteMessage(null);
    setClaimingInvite(true);
    try {
      const authService = AuthService.getInstance();
      const address = await authService.getAlgorandAddress();
      if (!address) {
        setClaimInviteError('No se encontró tu dirección Algorand');
        return;
      }
      // Claim ALL pending invites at once
      const res = await inviteSendService.claimAllPendingInvites(
        userProfile?.phoneNumber,
        userProfile?.phoneCountry,
        address
      );
      if (res.totalClaimed === 0 && res.totalFailed === 0) {
        setClaimInviteError('No se encontraron invitaciones pendientes');
      } else if (res.totalFailed > 0 && res.totalClaimed === 0) {
        setClaimInviteError(res.errors[0] || 'No se pudieron reclamar las invitaciones');
      } else if (res.totalClaimed > 0) {
        const msg = res.totalClaimed === 1
          ? 'Invitación reclamada. Revisa tu billetera.'
          : `${res.totalClaimed} invitaciones reclamadas. Revisa tu billetera.`;
        setClaimInviteMessage(msg);
        setShowInviteClaimCard(false);
      }
    } catch (e: any) {
      setClaimInviteError(e?.message || 'No se pudieron reclamar las invitaciones');
    } finally {
      setClaimingInvite(false);
    }
  }, [claimingInvite, userProfile?.phoneNumber, userProfile?.phoneCountry]);

  // Quick actions configuration - filter based on permissions
  const quickActionsData: QuickAction[] = [
    {
      id: 'send',
      label: 'Enviar',
      icon: 'send',
      color: '#34D399',
      route: () => navigation.navigate('BottomTabs', { screen: 'Contacts' }),
    },
    {
      id: 'receive',
      label: 'Recibir',
      icon: 'download',
      color: '#34D399',
      route: () => navigation.navigate('USDCDeposit', { tokenType: 'cusd' }),
    },
    {
      id: 'pay',
      label: 'Pagar',
      icon: 'shopping-bag',
      color: '#8b5cf6',
      route: () => {
        // For business accounts, navigate to Charge screen instead of Scan
        const isBusinessAccount = activeAccount?.type?.toLowerCase() === 'business';
        navigation.navigate('BottomTabs', {
          screen: isBusinessAccount ? 'Charge' : 'Scan'
        } as any);
      },
    },
    {
      id: 'exchange',
      label: 'Recargar',
      icon: 'dollar-sign',
      color: '#3b82f6',
      route: () => navigation.navigate('TopUp'),
    },
  ];

  // Filter quick actions based on employee permissions
  const quickActions = React.useMemo(() => {
    // If user is an employee, filter actions based on permissions
    if (activeAccount?.isEmployee) {
      const permissions = activeAccount.employeePermissions || {
        acceptPayments: false,
        viewTransactions: false,
        viewBalance: false,
        sendFunds: false,
        manageEmployees: false,
        viewBusinessAddress: false,
        viewAnalytics: false,
        manageP2p: false,
      };

      return [
        {
          id: 'send',
          label: 'Enviar',
          icon: 'send',
          color: '#34D399',
          route: () => navigation.navigate('BottomTabs', { screen: 'Contacts' }),
        },
        {
          id: 'pay',
          label: 'Pagar',
          icon: 'shopping-bag',
          color: '#8b5cf6',
          route: () => {
            const isBusinessAccount = activeAccount?.type?.toLowerCase() === 'business';
            navigation.navigate('BottomTabs', {
              screen: isBusinessAccount ? 'Charge' : 'Scan'
            } as any);
          },
        },
        {
          id: 'exchange',
          label: 'Recargar',
          icon: 'dollar-sign',
          color: '#3b82f6',
          route: () => navigation.navigate('TopUp'),
        },
        {
          id: 'withdraw',
          label: 'Retirar',
          icon: 'bank',
          isFA: true,
          color: '#F59E0B',
          route: () => navigation.navigate('Sell'),
        },
      ].filter(action => {
        switch (action.id) {
          case 'send':
            return permissions.sendFunds === true;
          // 'receive' removed
          case 'pay':
            return permissions.sendFunds === true;
          case 'exchange':
            return (permissions as any).manageP2p === true;
          case 'withdraw':
            // Assuming withdraw requires sendFunds or manageP2p? 
            // Currently Retirar (Sell) lets you send USDC to bank. It involves sending funds.
            return permissions.sendFunds === true;
          default:
            return true;
        }
      });
    }

    // Non-employees get new default actions (No Receive, Add Withdraw)
    return [
      {
        id: 'send',
        label: 'Enviar',
        icon: 'send',
        color: '#34D399',
        route: () => navigation.navigate('BottomTabs', { screen: 'Contacts' }),
      },
      {
        id: 'pay',
        label: 'Pagar',
        icon: 'shopping-bag',
        color: '#8b5cf6',
        route: () => {
          const isBusinessAccount = activeAccount?.type?.toLowerCase() === 'business';
          navigation.navigate('BottomTabs', {
            screen: isBusinessAccount ? 'Charge' : 'Scan'
          } as any);
        },
      },
      {
        id: 'exchange',
        label: 'Recargar',
        icon: 'dollar-sign',
        color: '#3b82f6',
        route: () => navigation.navigate('TopUp'),
      },
      {
        id: 'withdraw',
        label: 'Retirar',
        icon: 'bank',
        isFA: true,
        color: '#F59E0B',
        route: () => navigation.navigate('Sell'),
      }
    ];
  }, [activeAccount, navigation]);

  // Entrance animation - only run after initialization
  React.useEffect(() => {
    if (isInitialized && !isLoading) {
      // Small delay to ensure smooth transition
      setTimeout(() => {
        Animated.parallel([
          Animated.timing(fadeAnim, {
            toValue: 1,
            duration: 600,
            useNativeDriver: true,
          }),
          Animated.spring(scaleAnim, {
            toValue: 1,
            friction: 8,
            tension: 40,
            useNativeDriver: true,
          }),
        ]).start();
      }, 50);
    }
  }, [fadeAnim, scaleAnim, isInitialized, isLoading]);

  // Balance animation when value changes
  React.useEffect(() => {
    Animated.timing(balanceAnim, {
      toValue: showLocalCurrency ? 1 : 0,
      duration: 300,
      useNativeDriver: true,
    }).start();
  }, [showLocalCurrency, balanceAnim]);

  // Reset to USD if exchange rate is not available
  React.useEffect(() => {
    if (!canShowLocalCurrency && showLocalCurrency) {
      setShowLocalCurrency(false);
    }
  }, [canShowLocalCurrency, showLocalCurrency]);

  // Surface self-claim card only when pending invites exist
  React.useEffect(() => {
    let cancelled = false;
    const checkInvite = async () => {
      if (!userProfile?.phoneNumber) {
        setShowInviteClaimCard(false);
        setInviteReceiptId(undefined);
        return;
      }
      try {
        // Check if there are ANY pending invites to claim
        const pendingInvites = await inviteSendService.getAllPendingInvites(userProfile.phoneNumber, userProfile.phoneCountry);
        if (!cancelled) {
          const hasPendingInvites = pendingInvites.length > 0;
          setShowInviteClaimCard(hasPendingInvites);
          // Store the first invitation ID for backwards compatibility (if needed elsewhere)
          setInviteReceiptId(hasPendingInvites ? pendingInvites[0].invitationId : undefined);
          console.log(`[HomeScreen] Pending invites check: ${pendingInvites.length} found`);
        }
      } catch (e) {
        if (!cancelled) {
          setShowInviteClaimCard(false);
          setInviteReceiptId(undefined);
        }
      }
    };
    checkInvite();
    return () => {
      cancelled = true;
    };
  }, [userProfile?.phoneNumber, userProfile?.phoneCountry]);





  // Route hint to surface claim card (e.g., after verification)
  useEffect(() => {
    const anyRoute: any = route as any;
    if (anyRoute?.params?.checkInviteReceipt) {
      setShowInviteClaimCard(true);
      try { (navigation as any).setParams({ checkInviteReceipt: undefined }); } catch { }
    }
  }, [route, navigation]);

  // Combined initialization effect
  React.useEffect(() => {
    let mounted = true;

    const initializeHomeScreen = async () => {
      if (!mounted) return;
      // Mark initialized immediately to avoid long blocking loading screens
      setIsInitialized(true);

      try {
        // Load balance visibility preference first
        await loadBalanceVisibility();

        // Initialize auth service
        const authService = AuthService.getInstance();
        await authService.initialize();

        if (!mounted) return;

        const address = await authService.getAlgorandAddress();
        setAlgorandAddress(address);

      } catch (error) {
        console.error('HomeScreen - Error during initialization:', error);
      } finally {
        // No-op: already marked initialized at start
      }
    };

    initializeHomeScreen();

    return () => {
      mounted = false;
    };
  }, []);

  // Invite receipt banner removed

  // Update header when account changes or user profile updates
  useEffect(() => {
    console.log('HomeScreen - Avatar update effect:', {
      currentAccountAvatar: currentAccount?.avatar,
      currentAccountName: currentAccount?.name,
      currentAccountType: currentAccount?.type,
      userProfileLoaded: !!userProfile,
      userProfileName: userProfile?.firstName || userProfile?.username
    });

    if (currentAccount) {
      setCurrentAccountAvatar(currentAccount.avatar);
    }
  }, [currentAccount, setCurrentAccountAvatar, userProfile]);

  // FIX: Refresh Algorand address when active account changes (critical for post-migration update)
  useEffect(() => {
    let mounted = true;
    const { DeviceEventEmitter } = require('react-native');

    const fetchAddress = async () => {
      const authService = AuthService.getInstance();
      try {
        const address = await authService.getAlgorandAddress();
        if (mounted) {
          console.log('HomeScreen - Refreshed Algorand address:', address);
          setAlgorandAddress(address);
        }
      } catch (e) {
        console.error('HomeScreen - Error refreshing address:', e);
      }
    };

    fetchAddress();

    // Listen for direct address updates (e.g. from migration)
    const subscription = DeviceEventEmitter.addListener('ALGORAND_ADDRESS_UPDATED', (newAddress: string) => {
      console.log('HomeScreen - Received ALGORAND_ADDRESS_UPDATED event:', newAddress);
      if (mounted) {
        setAlgorandAddress(newAddress);
        // FORCE REFETCH OF BALANCES
        // Now that the backend has the new address (via migrationService Update),
        // we must trigger a fresh query to resolve_my_balances to see the funds.
        refetchMyBalances();
        refetchPendingPayroll();
      }
    });

    return () => {
      mounted = false;
      subscription.remove();
    };
  }, [activeAccount?.id, activeAccount?.type, activeAccount?.index]);

  // Debug log when showProfileMenu changes
  useEffect(() => {
    console.log('showProfileMenu changed to:', profileMenu.showProfileMenu);
  }, [profileMenu.showProfileMenu]);

  // Only refresh accounts when coming from specific screens
  const [hasInitialLoad, setHasInitialLoad] = useState(false);

  // Memoized navigation handlers for better performance
  const navigateToCUSDAccount = useCallback(() => {
    navigation.navigate('AccountDetail', {
      accountType: 'cusd',
      accountName: 'Confío Dollar',
      accountSymbol: '$cUSD',
      accountBalance: cUSDBalance.toFixed(2),
      // Fix: Use local state algorandAddress if available, fall back to context
      accountAddress: algorandAddress || activeAccount?.algorandAddress || ''
    });
  }, [navigation, cUSDBalance, activeAccount?.algorandAddress, algorandAddress]);

  const navigateToConfioAccount = useCallback(() => {
    navigation.navigate('AccountDetail', {
      accountType: 'confio',
      accountName: 'Confío',
      accountSymbol: '$CONFIO',
      accountBalance: confioTotal.toFixed(2),
      // Fix: Use local state algorandAddress if available, fall back to context
      accountAddress: algorandAddress || activeAccount?.algorandAddress || ''
    });
  }, [navigation, confioTotal, activeAccount?.algorandAddress, algorandAddress]);

  useFocusEffect(
    React.useCallback(() => {
      // Only refresh if we've done the initial load and are coming back
      if (hasInitialLoad) {
        console.log('HomeScreen - Screen refocused, checking if refresh needed');
        // Only refresh if we're coming from screens that might have changed data
        const currentRoute = navigation.getState()?.routes?.slice(-2, -1)?.[0]?.name;
        if (currentRoute === 'CreateBusiness' || currentRoute === 'EditBusiness' || currentRoute === 'EditProfile') {
          refreshAccounts();
        }
      } else {
        setHasInitialLoad(true);
      }
    }, [hasInitialLoad, refreshAccounts, navigation])
  );

  const handleAccountSwitch = async (accountId: string): Promise<boolean> => {
    try {
      console.log('HomeScreen - handleAccountSwitch called with:', accountId);

      // Close the profile menu immediately to provide feedback
      profileMenu.closeProfileMenu();

      // All accounts are now real accounts from the server
      console.log('HomeScreen - Switching to account:', accountId);

      // Use atomic account switching
      const success = await atomicSwitchAccount(accountId);

      if (success) {
        console.log('HomeScreen - Account switch successful');
        // Refresh balances after successful switch
        await Promise.all([
          refetchMyBalances(),
        ]);
        return true;
      } else {
        console.log('HomeScreen - Account switch failed');
        return false;
      }
    } catch (error) {
      console.error('Error switching account:', error);
      Alert.alert(
        'Error',
        'No se pudo cambiar la cuenta. Por favor intenta nuevamente.',
        [{ text: 'OK', onPress: () => { } }]
      );
      return false;
    }
  };

  const handleCreateBusinessAccount = () => {
    profileMenu.closeProfileMenu();
    // Navigate to business account creation screen
    navigation.navigate('CreateBusiness');
  };

  // Check for pending account switch from push notification when screen gains focus
  useFocusEffect(
    useCallback(() => {
      // Add a small delay to ensure the screen is fully mounted
      const timer = setTimeout(() => {
        const pendingSwitch = PushNotificationService.getPendingAccountSwitch();
        const pendingNavigation = PushNotificationService.getPendingNavigation();

        console.log('HomeScreen - Checking for pending account switch:', {
          pendingSwitch,
          hasPendingNavigation: !!pendingNavigation,
          hasHandleAccountSwitch: !!handleAccountSwitch
        });

        // Only process if we have BOTH a pending switch AND navigation
        if (pendingSwitch && pendingNavigation && handleAccountSwitch) {
          console.log('HomeScreen - Processing pending account switch');

          // Clear the pending switch to prevent duplicate processing
          PushNotificationService.clearPendingAccountSwitch();
          PushNotificationService.clearPendingNavigation();

          // Store the navigation function before clearing
          const navigationToExecute = pendingNavigation;

          // Execute the account switch
          handleAccountSwitch(pendingSwitch).then(success => {
            if (success) {
              console.log('HomeScreen - Account switched successfully');
              // Execute navigation after a short delay
              setTimeout(() => {
                console.log('HomeScreen - Executing deferred navigation');
                navigationToExecute();
              }, 500);
            } else {
              console.error('HomeScreen - Account switch failed');
            }
          }).catch(error => {
            console.error('HomeScreen - Error switching account:', error);
          });
        }
      }, 100); // Small delay to ensure screen is ready

      return () => clearTimeout(timer);
    }, [handleAccountSwitch])
  );

  if (isLoading) {
    return (
      <Gradient
        fromColor="#5AC8A8"
        toColor="#72D9BC"
        style={styles.container}
      >
        <View style={styles.content}>
          <Text style={styles.loadingText}>Cargando...</Text>
        </View>
      </Gradient>
    );
  }

  return (
    <View style={styles.container}>
      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor="#fff"
            colors={['#34d399']}
          />
        }
        showsVerticalScrollIndicator={false}
      >
        {/* Enhanced Balance Card Section */}
        <Animated.View
          style={[
            styles.balanceCard,
            {
              opacity: fadeAnim,
              transform: [{ scale: scaleAnim }],
            }
          ]}
        >
          <View style={styles.portfolioHeader}>
            <View style={styles.portfolioTitleContainer}>
              <Text style={styles.portfolioLabel}>Mi Saldo Total</Text>
              <Text style={styles.portfolioSubLabel}>
                {showLocalCurrency ? `En ${currency.name}` : 'En Dólares'}
              </Text>
            </View>
            <View style={styles.portfolioActions}>
              {/* Only show eye toggle if employee has viewBalance permission or not an employee */}
              {(!activeAccount?.isEmployee || activeAccount?.employeePermissions?.viewBalance) && (
                <TouchableOpacity
                  style={styles.eyeToggle}
                  onPress={toggleBalanceVisibility}
                  activeOpacity={0.7}
                >
                  <Icon name={showBalance ? 'eye' : 'eye-off'} size={18} color="#fff" />
                </TouchableOpacity>
              )}
              {canShowLocalCurrency && (
                <TouchableOpacity
                  style={styles.currencyToggle}
                  onPress={() => setShowLocalCurrency(!showLocalCurrency)}
                  activeOpacity={0.7}
                >
                  <Text style={styles.currencyToggleText}>
                    {showLocalCurrency ? currency.code : 'USD'}
                  </Text>
                  <Icon name="chevron-down" size={14} color="#fff" />
                </TouchableOpacity>
              )}
            </View>
          </View>

          <Animated.View
            style={[
              styles.balanceContainer,
              {
                opacity: balanceAnim.interpolate({
                  inputRange: [0, 1],
                  outputRange: [1, 1],
                }),
              }
            ]}
          >
            <Text style={styles.currencySymbol}>
              {showLocalCurrency ? currency.symbol : '$'}
            </Text>
            <Text style={styles.balanceAmount}>
              {/* Hide balance for employees without viewBalance permission */}
              {(() => {
                console.log('HomeScreen Balance Check:', {
                  isEmployee: activeAccount?.isEmployee,
                  permissions: activeAccount?.employeePermissions,
                  viewBalance: activeAccount?.employeePermissions?.viewBalance
                });
                return (activeAccount?.isEmployee && !activeAccount?.employeePermissions?.viewBalance)
                  ? '••••••'
                  : showBalance
                    ? (showLocalCurrency
                      ? formatAmount.plain(floorToDecimals(totalLocalValue, 2))
                      : formatFixedFloor(totalUSDValue, 2)
                    )
                    : '••••••';
              })()}
            </Text>
          </Animated.View>
        </Animated.View>


        {showInviteClaimCard && (
          <View style={styles.inviteClaimCard}>
            <View style={styles.inviteClaimHeader}>
              <View style={styles.inviteClaimBadge}>
                <Text style={styles.inviteClaimBadgeText}>INVITACIÓN</Text>
              </View>
              <Text style={styles.inviteClaimTitle}>Reclama fondos pendientes</Text>
              <Text style={styles.inviteClaimSubtitle}>
                Completa el reclamo para mover el dinero a tu billetera y empezar a usarlo.
              </Text>
            </View>
            {claimInviteError ? <Text style={styles.inviteClaimError}>{claimInviteError}</Text> : null}
            {claimInviteMessage ? <Text style={styles.inviteClaimSuccess}>{claimInviteMessage}</Text> : null}
            <TouchableOpacity
              style={[styles.inviteClaimButton, claimingInvite && { opacity: 0.7 }]}
              onPress={handleClaimInvite}
              activeOpacity={0.85}
              disabled={claimingInvite}
            >
              <Text style={styles.inviteClaimButtonText}>{claimingInvite ? 'Reclamando...' : 'Reclamar ahora'}</Text>
              <Icon name="arrow-right" size={16} color="#fff" />
            </TouchableOpacity>
          </View>
        )}

        {/* Payroll quick action */}
        {showPayrollCard && (
          <TouchableOpacity
            style={[styles.payrollCard, { marginHorizontal: 16, marginBottom: 12 }]}
            onPress={() => navigation.navigate('PayrollPending' as never)}
            activeOpacity={0.9}
          >
            <View style={styles.payrollIconWrap}>
              <Icon name="briefcase" size={20} color="#fff" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.payrollTitle}>Pagos de nómina</Text>
              <Text style={styles.payrollSubtitle}>
                {pendingPayrollCount > 0
                  ? `Tienes ${pendingPayrollCount} pagos para firmar`
                  : 'Revisa y ejecuta tus pagos de nómina'}
              </Text>
            </View>
            <Icon name="chevron-right" size={18} color="#9CA3AF" />
          </TouchableOpacity>
        )}

        {/* CONFIO Presale Banner - Show claims unlocked (green) or presale active (purple) */}
        {isPresaleClaimsUnlocked && !presaleDismissed && (
          <Animated.View
            style={[
              styles.presaleBanner,
              {
                opacity: fadeAnim,
                transform: [
                  {
                    translateY: fadeAnim.interpolate({
                      inputRange: [0, 1],
                      outputRange: [20, 0],
                    })
                  }
                ],
              }
            ]}
          >
            <View style={styles.presaleBannerContent}>
              <View style={styles.presaleBannerLeft}>
                <View style={[styles.presaleBadge, { backgroundColor: '#10b981' }]}>
                  <Text style={styles.presaleBadgeText}>🔓 RECLAMO</Text>
                </View>
                <Text style={styles.presaleBannerTitle}>¡Reclama tus $CONFIO!</Text>
                <Text style={styles.presaleBannerSubtitle}>
                  Tus monedas ya están disponibles. Reclámalas en segundos.
                </Text>
                <TouchableOpacity
                  onPress={() => {
                    // Use confioPresaleLocked to check if user has anything to claim
                    const canClaim = confioPresaleLocked > 0;
                    if (!canClaim) {
                      Alert.alert(
                        "Aviso",
                        "No tienes tokens disponibles para reclamar o ya fueron reclamados.",
                        [{ text: "OK", onPress: () => { } }]
                      );
                      return;
                    }
                    navigation.navigate('ConfioPresale');
                  }}
                  activeOpacity={0.7}
                  style={{ marginTop: 8 }}
                >
                  <Text style={[styles.presaleDetailsLink, { color: '#10b981' }]}>Ir a reclamar</Text>
                </TouchableOpacity>
              </View>
              <View style={styles.presaleBannerRight}>
                <TouchableOpacity onPress={() => setPresaleDismissed(true)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} style={{ position: 'absolute', top: -6, right: -6 }}>
                  <Icon name="x" size={18} color="#10b981" />
                </TouchableOpacity>
                <TouchableOpacity onPress={() => navigation.navigate('ConfioPresale')} activeOpacity={0.9} style={{ alignItems: 'center' }}>
                  <Image source={CONFIOLogo} style={styles.presaleBannerLogo} />
                  <Icon name="chevron-right" size={20} color="#10b981" />
                </TouchableOpacity>
              </View>
            </View>
          </Animated.View>
        )}
        {isPresaleActive && !isPresaleClaimsUnlocked && !presaleDismissed && (
          <Animated.View
            style={[
              styles.presaleBanner,
              {
                opacity: fadeAnim,
                transform: [
                  {
                    translateY: fadeAnim.interpolate({
                      inputRange: [0, 1],
                      outputRange: [20, 0],
                    })
                  }
                ],
              }
            ]}
          >
            <View style={styles.presaleBannerContent}>
              <View style={styles.presaleBannerLeft}>
                <View style={styles.presaleBadge}>
                  <Text style={styles.presaleBadgeText}>💎 INFORMACIÓN</Text>
                </View>
                <Text style={styles.presaleBannerTitle}>¿Qué es la Moneda $CONFIO?</Text>
                <Text style={styles.presaleBannerSubtitle}>
                  Información sobre su papel en el ecosistema de Confío
                </Text>
                <TouchableOpacity
                  onPress={() => navigation.navigate('ConfioPresale')}
                  activeOpacity={0.7}
                  style={{ marginTop: 8 }}
                >
                  <Text style={styles.presaleDetailsLink}>Ver detalles</Text>
                </TouchableOpacity>
              </View>
              <View style={styles.presaleBannerRight}>
                <TouchableOpacity onPress={() => setPresaleDismissed(true)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} style={{ position: 'absolute', top: -6, right: -6 }}>
                  <Icon name="x" size={18} color="#8b5cf6" />
                </TouchableOpacity>
                <TouchableOpacity onPress={() => navigation.navigate('ConfioPresale')} activeOpacity={0.9} style={{ alignItems: 'center' }}>
                  <Image source={CONFIOLogo} style={styles.presaleBannerLogo} />
                  <Icon name="chevron-right" size={20} color="#8b5cf6" />
                </TouchableOpacity>
              </View>
            </View>
          </Animated.View>
        )}

        {/* Quick Actions */}
        <Animated.View
          style={[
            styles.quickActionsCard,
            {
              opacity: fadeAnim,
              transform: [
                {
                  translateY: fadeAnim.interpolate({
                    inputRange: [0, 1],
                    outputRange: [30, 0],
                  })
                }
              ],
            }
          ]}
        >
          {/* Show employee welcome message if limited actions available */}
          {activeAccount?.isEmployee && quickActions.length <= 1 ? (
            <View style={styles.employeeWelcomeContainer}>
              <View style={styles.employeeWelcomeIcon}>
                <Icon name="briefcase" size={32} color="#7c3aed" />
              </View>
              <Text style={styles.employeeWelcomeTitle}>
                ¡Hola, equipo {activeAccount?.business?.name}!
              </Text>
              <Text style={styles.employeeWelcomeText}>
                Como {activeAccount?.employeeRole === 'cashier' ? 'cajero' :
                  activeAccount?.employeeRole === 'manager' ? 'gerente' :
                    activeAccount?.employeeRole === 'admin' ? 'administrador' : 'parte del equipo'},{' '}
                {activeAccount?.employeePermissions?.acceptPayments
                  ? 'estás listo para recibir pagos y atender a nuestros clientes.'
                  : 'eres una parte importante de nuestro equipo.'}
              </Text>
            </View>
          ) : (
            quickActions.map((action, index) => (
              <TouchableOpacity
                key={action.id}
                style={styles.actionButton}
                onPress={action.route}
                activeOpacity={0.7}
              >
                <Animated.View
                  style={[
                    styles.actionIcon,
                    { backgroundColor: action.color },
                    {
                      transform: [
                        {
                          scale: scaleAnim.interpolate({
                            inputRange: [0.95, 1],
                            outputRange: [0.8, 1],
                          })
                        }
                      ]
                    }
                  ]}
                >
                  {/* @ts-ignore */}
                  {(action as any).isFA ? (
                    <FAIcon name={action.icon} size={20} color="#fff" />
                  ) : (
                    <Icon name={action.icon} size={22} color="#fff" />
                  )}
                </Animated.View>
                <Text style={styles.actionLabel}>{action.label}</Text>
              </TouchableOpacity>
            ))
          )}
        </Animated.View>

        {/* Wallets Section */}
        <View style={styles.walletsSection}>
          <Text style={styles.walletsTitle}>Mis Billeteras</Text>

          {myBalancesLoading ? (
            <>
              <WalletCardSkeleton />
              <WalletCardSkeleton />
            </>
          ) : (
            <Animated.View
              style={{
                opacity: fadeAnim,
                transform: [
                  {
                    translateY: fadeAnim.interpolate({
                      inputRange: [0, 1],
                      outputRange: [40, 0],
                    })
                  }
                ]
              }}
            >
              {/* cUSD Wallet */}
              <Pressable
                style={({ pressed }) => [
                  styles.walletCard,
                  pressed && { opacity: 0.7 }
                ]}
                onPress={navigateToCUSDAccount}
              >
                <View style={styles.walletCardContent}>
                  <View style={[styles.walletLogoContainer, { backgroundColor: '#ffffff' }]}>
                    <Image source={cUSDLogo} style={styles.walletLogo} />
                  </View>
                  <View style={styles.walletInfo}>
                    <Text style={styles.walletName}>Confío Dollar</Text>
                    <Text style={styles.walletSymbol}>cUSD</Text>
                  </View>
                  <View style={styles.walletBalanceContainer}>
                    <Text style={styles.walletBalanceText}>
                      {/* Hide balance for employees without viewBalance permission */}
                      {(activeAccount?.isEmployee && !activeAccount?.employeePermissions?.viewBalance)
                        ? '••••'
                        : showBalance ? `$${formatFixedFloor(cUSDBalance, 2)}` : '••••'}
                    </Text>
                    <Icon name="chevron-right" size={20} color="#9ca3af" />
                  </View>
                </View>
              </Pressable>

              {/* CONFIO Wallet */}
              <Pressable
                style={({ pressed }) => [
                  styles.walletCard,
                  pressed && { opacity: 0.7 }
                ]}
                onPress={navigateToConfioAccount}
              >
                <View style={styles.walletCardContent}>
                  <View style={[styles.walletLogoContainer, { backgroundColor: '#8b5cf6' }]}>
                    <Image source={CONFIOLogo} style={styles.walletLogo} />
                  </View>
                  <View style={styles.walletInfo}>
                    <Text style={styles.walletName}>Confío</Text>
                    <Text style={styles.walletSymbol}>CONFIO</Text>
                  </View>
                  <View style={styles.walletBalanceContainer}>
                    <Text style={styles.walletBalanceText}>
                      {/* Hide balance for employees without viewBalance permission */}
                      {(activeAccount?.isEmployee && !activeAccount?.employeePermissions?.viewBalance)
                        ? '••••'
                        : showBalance ? formatFixedFloor(confioTotal, 2) : '••••'}
                    </Text>
                    <Icon name="chevron-right" size={20} color="#9ca3af" />
                  </View>
                </View>
              </Pressable>
            </Animated.View>
          )}
        </View>

        {/* Ghost Input for Referral */}
        {referralStatusData?.checkReferralStatus?.canSetReferrer !== false && (
          <View style={styles.ghostInputContainer}>
            <TouchableOpacity onPress={() => setShowReferralInput(true)} style={styles.ghostButton}>
              <Text style={styles.ghostButtonText}>¿Tienes un código de invitación?</Text>
            </TouchableOpacity>
          </View>
        )}
      </ScrollView>

      {/* Profile Menu */}
      <ProfileMenu
        visible={profileMenu.showProfileMenu}
        onClose={profileMenu.closeProfileMenu}
        accounts={displayAccounts}
        selectedAccount={activeAccount?.id || displayAccounts[0]?.id || ''}
        onAccountSwitch={handleAccountSwitch}
        onCreateBusinessAccount={handleCreateBusinessAccount}
      />

      {/* Account Switch Overlay */}
      <AccountSwitchOverlay
        visible={switchState.isLoading}
        progress={switchState.progress}
      />

      {/* Referral Input Modal */}
      <ReferralInputModal
        visible={showReferralInput}
        onClose={() => setShowReferralInput(false)}
        onSuccess={() => {
          setShowReferralInput(false);
          // Refresh balances
          setTimeout(() => {
            refetchMyBalances();
          }, 500);
        }}
      />

      <LoadingOverlay
        visible={claimingInvite}
        message="Reclamando tu invitación..."
      />

      <ReferralSuccessModal
        visible={showDeferredReferralSuccess}
        onClose={() => setShowDeferredReferralSuccess(false)}
      />

      <AutoSwapModal
        visible={swapModalAsset !== null}
        assetType={swapModalAsset}
      />

    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f9fafb',
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: 100,
  },
  // Enhanced balance card styles
  balanceCard: {
    backgroundColor: '#34d399',
    paddingTop: 20,
    paddingBottom: 30,
    paddingHorizontal: 20,
    borderBottomLeftRadius: 32,
    borderBottomRightRadius: 32,
  },
  portfolioHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  portfolioTitleContainer: {
    flex: 1,
  },
  portfolioLabel: {
    fontSize: 16,
    color: 'rgba(255,255,255,0.95)',
    fontWeight: '500',
  },
  portfolioSubLabel: {
    fontSize: 12,
    color: 'rgba(255,255,255,0.7)',
    marginTop: 2,
  },
  portfolioActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  eyeToggle: {
    padding: 6,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.15)',
  },
  currencyToggle: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.2)',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
  },
  currencyToggleText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
    marginRight: 4,
  },
  balanceContainer: {
    flexDirection: 'row',
    alignItems: 'baseline',
    marginBottom: 12,
  },
  currencySymbol: {
    fontSize: 24,
    color: '#fff',
    marginRight: 6,
    fontWeight: '500',
  },
  balanceAmount: {
    fontSize: 42,
    fontWeight: 'bold',
    color: '#fff',
    letterSpacing: -1,
  },
  // Quick actions styles
  quickActionsCard: {
    flexDirection: 'row',
    justifyContent: 'space-evenly',
    paddingVertical: 24,
    paddingHorizontal: 16,
    backgroundColor: '#fff',
    marginHorizontal: 20,
    marginTop: -20,
    borderRadius: 20,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 5,
  },
  actionButton: {
    alignItems: 'center',
    flex: 1,
  },
  actionIcon: {
    width: 52,
    height: 52,
    borderRadius: 26,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 8,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 3,
  },
  actionLabel: {
    fontSize: 13,
    color: '#374151',
    fontWeight: '600',
  },
  // Wallets section styles
  walletsSection: {
    paddingHorizontal: 20,
    marginTop: 28,
  },
  walletsTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#111827',
    marginBottom: 16,
  },
  walletCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    marginBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.04,
    shadowRadius: 6,
    elevation: 2,
  },
  walletCardContent: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
  },
  walletLogoContainer: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#10b981',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 16,
  },
  ghostInputContainer: {
    marginHorizontal: 20,
    marginBottom: 20,
  },
  ghostButton: {
    padding: 12,
    alignItems: 'center',
  },
  ghostButtonText: {
    color: '#34d399', // Brand green
    fontWeight: '600',
  },


  walletLogo: {
    width: 44,
    height: 44,
    borderRadius: 22,
  },
  walletInfo: {
    flex: 1,
  },
  walletName: {
    fontSize: 17,
    fontWeight: '600',
    color: '#111827',
  },
  walletSymbol: {
    fontSize: 14,
    color: '#6b7280',
    marginTop: 2,
  },
  walletBalanceContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  walletBalanceText: {
    fontSize: 18,
    fontWeight: '700',
    color: '#111827',
    marginRight: 8,
  },
  inviteClaimCard: {
    marginHorizontal: 20,
    marginTop: 16,
    marginBottom: 8,
    backgroundColor: '#f0fdf4',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#bbf7d0',
    padding: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  inviteClaimHeader: {
    marginBottom: 12,
  },
  inviteClaimBadge: {
    alignSelf: 'flex-start',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    backgroundColor: '#22c55e',
    marginBottom: 8,
  },
  inviteClaimBadgeText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 12,
    letterSpacing: 0.3,
  },
  inviteClaimTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1e293b',
    marginBottom: 4,
  },
  inviteClaimSubtitle: {
    fontSize: 13,
    color: '#64748b',
    lineHeight: 18,
  },
  inviteClaimButton: {
    marginTop: 12,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: '#22c55e',
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 12,
    shadowColor: '#22c55e',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.2,
    shadowRadius: 4,
    elevation: 3,
  },
  inviteClaimButtonText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 14,
    letterSpacing: 0.3,
  },
  inviteClaimError: {
    color: '#dc2626',
    marginTop: 8,
    fontSize: 13,
    textAlign: 'center',
  },
  inviteClaimSuccess: {
    color: '#059669',
    marginTop: 8,
    fontSize: 13,
    textAlign: 'center',
  },
  payrollCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#EEF2FF',
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  payrollIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 14,
    backgroundColor: '#8B5CF6',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  payrollTitle: { fontSize: 15, fontWeight: '700', color: '#111827' },
  payrollSubtitle: { fontSize: 13, color: '#6b7280', marginTop: 2 },
  // Loading state
  loadingText: {
    color: '#fff',
    fontSize: 18,
    textAlign: 'center',
    marginTop: 40,
  },
  // Employee welcome styles
  employeeWelcomeContainer: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 16,
  },
  employeeWelcomeIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: '#f3e8ff',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 12,
  },
  employeeWelcomeTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#111827',
    marginBottom: 8,
    textAlign: 'center',
  },
  employeeWelcomeText: {
    fontSize: 14,
    color: '#6b7280',
    textAlign: 'center',
    paddingHorizontal: 20,
    lineHeight: 20,
  },
  // CONFIO Presale Banner styles
  presaleBanner: {
    marginHorizontal: 20,
    marginTop: 16,
    marginBottom: 8,
  },
  presaleBannerContent: {
    backgroundColor: '#f8fafc',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#e2e8f0',
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    shadowColor: '#8b5cf6',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 8,
    elevation: 3,
  },
  presaleBannerLeft: {
    flex: 1,
    marginRight: 12,
  },
  presaleBadge: {
    backgroundColor: '#8b5cf6',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    alignSelf: 'flex-start',
    marginBottom: 8,
  },
  presaleBadgeText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: 'bold',
  },
  presaleBannerTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1e293b',
    marginBottom: 4,
  },
  presaleBannerSubtitle: {
    fontSize: 13,
    color: '#64748b',
    lineHeight: 18,
  },
  presaleBannerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  presaleBannerLogo: {
    width: 32,
    height: 32,
    borderRadius: 16,
  },
  presaleDetailsLink: {
    color: '#8b5cf6',
    fontWeight: '600',
    fontSize: 13,
  },
  // Legacy styles kept for compatibility
  content: {
    flex: 1,
  },
  header: {
    paddingTop: 56,
    paddingBottom: 32,
    paddingHorizontal: 20,
    borderBottomLeftRadius: 32,
    borderBottomRightRadius: 32,
    width: '100%',
  },
}); 
