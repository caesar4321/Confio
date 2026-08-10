import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
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
  Vibration,
  AppState,
  AppStateStatus,
} from 'react-native';
import ConvertModal from '../components/ConvertModal';
import { AuthService } from '../services/authService';
import { useNavigation, useFocusEffect, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useAuth, useAuthReady } from '../contexts/AuthContext';
import { useHeader } from '../contexts/HeaderContext';
import cUSDLogo from '../assets/png/cUSD.png';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import Icon from 'react-native-vector-icons/Feather';
import MCIcon from 'react-native-vector-icons/MaterialCommunityIcons';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import { colors } from '../config/theme';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';
import InviteClaimBanner from '../components/InviteClaimBanner';
import { HomeStatsSection } from '../components/HomeStatsSection';
import * as Keychain from 'react-native-keychain';
import { RootStackParamList, MainStackParamList } from '../types/navigation';
import { ProfileMenu } from '../components/ProfileMenu';
import { useAccount } from '../contexts/AccountContext';
import { useAtomicAccountSwitch } from '../hooks/useAtomicAccountSwitch';
import { PushNotificationService } from '../services/pushNotificationService';
import { AccountSwitchOverlay } from '../components/AccountSwitchOverlay';
import { getCountryByIso } from '../utils/countries';
import { WalletCardSkeleton } from '../components/SkeletonLoader';
import { useQuery, useMutation } from '@apollo/client';
import {
  GET_PRESALE_STATUS,
  GET_MY_BALANCES,
  GET_MY_CONFIO_BREAKDOWN,
  GET_ACTIVE_PRESALE,
  GET_ALL_PRESALE_PHASES,
  CHECK_REFERRAL_STATUS,
  GET_ACTIVE_HUMANITARIAN_CAMPAIGNS,
} from '../apollo/queries';
import { REFRESH_ACCOUNT_BALANCE, SET_REFERRER } from '../apollo/mutations';
import { HumanitarianHomeBanner } from '../components/HumanitarianHomeBanner';
import { RouteSheet, RouteOption } from '../components/RouteSheet';
import { useSavingsPortfolio } from '../hooks/useSavingsPortfolio';
import { useRampCountry } from '../hooks/useRampCountry';
import { useCurrency } from '../hooks/useCurrency';
import { useSelectedCountryRate } from '../hooks/useExchangeRate';
import { inviteSendService } from '../services/inviteSendService';
import { GET_PENDING_PAYROLL_ITEMS } from '../apollo/queries';
import { LoadingOverlay } from '../components/LoadingOverlay';
import { ReferralInputModal } from '../components/ReferralInputModal';
import { ReferralSuccessModal } from '../components/ReferralSuccessModal';
import AutoSwapModal from '../components/AutoSwapModal';
import { useAutoSwap } from '../hooks/useAutoSwap';
import { useBnbAutoConvert } from '../hooks/useBnbAutoConvert';
import { useSavingsResume } from '../hooks/useSavingsResume';
import { deepLinkHandler } from '../utils/deepLinkHandler';
import { describeTypes, logBreadcrumb, recordCrashError } from '../services/crashLog';
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
  const isAuthReady = useAuthReady();
  const { currency, formatAmount, exchangeRate } = useCurrency();
  const { rate: marketRate, loading: rateLoading } = useSelectedCountryRate();
  const [algorandAddress, setAlgorandAddress] = React.useState<string>('');
  // Show local currency by default if not in US and rate is available
  const [showLocalCurrency, setShowLocalCurrency] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [statsRefreshNonce, setStatsRefreshNonce] = useState(0);
  const [showBalance, setShowBalance] = useState(true);
  // Invite receipt banner removed; self-claim card state
  const [showInviteClaimCard, setShowInviteClaimCard] = useState(false);
  const [claimingInvite, setClaimingInvite] = useState(false);
  const [claimInviteMessage, setClaimInviteMessage] = useState<string | null>(null);
  const [claimInviteError, setClaimInviteError] = useState<string | null>(null);
  const [inviteReceiptId, setInviteReceiptId] = useState<string | undefined>(undefined);
  const autoClaimedInviteIds = useRef<Set<string>>(new Set());

  const [showReferralInput, setShowReferralInput] = useState(false);


  // New UX State
  // const [showConvertModal, setShowConvertModal] = useState(false); // Removed for auto-swap

  const fadeAnim = useRef(new Animated.Value(0)).current;
  const scaleAnim = useRef(new Animated.Value(1)).current; // Start at 1 to avoid scale-induced layout shift
  const balanceAnim = useRef(new Animated.Value(0)).current;
  const entranceAnimRef = useRef<Animated.CompositeAnimation | null>(null);
  const balanceTransitionRef = useRef<Animated.CompositeAnimation | null>(null);
  const fadeTranslateY20 = useMemo(
    () =>
      fadeAnim.interpolate({
        inputRange: [0, 1],
        outputRange: [20, 0],
      }),
    [fadeAnim]
  );
  const fadeTranslateY30 = useMemo(
    () =>
      fadeAnim.interpolate({
        inputRange: [0, 1],
        outputRange: [30, 0],
      }),
    [fadeAnim]
  );
  const fadeTranslateY40 = useMemo(
    () =>
      fadeAnim.interpolate({
        inputRange: [0, 1],
        outputRange: [40, 0],
      }),
    [fadeAnim]
  );

  // Use account context
  const {
    activeAccount,
    accounts,
    refreshAccounts,
  } = useAccount();

  // Use atomic account switching
  const {
    switchAccount: atomicSwitchAccount,
    state: switchState,
    isAccountSwitchInProgress
  } = useAtomicAccountSwitch();

  // Fetch all balances in a single call to avoid flicker.
  // Skip until auth is fully ready (JWT refreshed + synced to correct account context)
  // to prevent fetching with a stale/wrong-context token.
  const { data: myBalancesData, loading: myBalancesLoading, error: myBalancesError, refetch: refetchMyBalances } = useQuery(GET_MY_BALANCES, {
    fetchPolicy: 'network-only',
    nextFetchPolicy: 'network-only',
    notifyOnNetworkStatusChange: true,
    skip: !isAuthReady,
  });
  // $CONFIO by unlock event. Isolated from GET_MY_BALANCES on purpose: that
  // query feeds every row on this screen and must not fail over a field an
  // older server doesn't know.
  const { data: confioBreakdownData } = useQuery(GET_MY_CONFIO_BREAKDOWN, {
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
    skip: !isAuthReady,
  });
  const [refreshAccountBalance] = useMutation(REFRESH_ACCOUNT_BALANCE);
  // Ahorros e Inversiones portfolio total for the wallet-row entry (stubbed
  // until the cUSD+/stocks backend lands; single wiring point in the hook).
  const savingsPortfolio = useSavingsPortfolio();
  // Reached through a ref so focus/pull-to-refresh can refresh the BSC
  // dollar row without either callback taking a dependency on it. Null
  // until auth is ready — refetch would bypass the hook's own gate.
  const refetchSavingsPortfolioRef = useRef<(() => Promise<unknown>) | null>(null);
  refetchSavingsPortfolioRef.current = isAuthReady ? savingsPortfolio.refetch : null;
  const [checkReferralStatus, { data: referralStatusData }] = useMutation(CHECK_REFERRAL_STATUS);
  const [setReferrerMutation] = useMutation(SET_REFERRER);

  // BSC mirror of the auto-swap: sweep mis-deposited BNB → USDT (silent,
  // server-gated; no-op until CUSD_PLUS_BNB_AUTOCONVERT_ENABLED flips on).
  useBnbAutoConvert(isAuthenticated);

  // Finish any cUSD+ mint whose USDT already arrived. Home carries it for the
  // same reason it carries the USDC→cUSD auto-swap: this is where users land,
  // and a deposit shouldn't wait for them to open the savings account.
  // The polled raw-USDT balance is the arrival trigger: mount and
  // re-foreground only fire when the user arrives, so a deposit landing while
  // they were already sitting here used to wait for them to open the savings
  // account before anything swept it.
  const { mintingSavings } = useSavingsResume(
    isAuthenticated,
    savingsPortfolio.usdtBalanceUsd,
  );

  // Use the auto-swap hook for both ALGO and USDC detection
  const { swapModalAsset, walletRecoveryRequired, dismissWalletRecovery } = useAutoSwap({
    isAuthenticated,
    myBalancesLoading,
    usdcBalanceStr: (myBalancesData as any)?.myBalances?.usdc || '0',
    algoBalanceStr: (myBalancesData as any)?.myBalances?.algo || '0',
    refreshAccountBalance,
    activeAccount
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
  const { data: humanitarianCampaignData } = useQuery(GET_ACTIVE_HUMANITARIAN_CAMPAIGNS, {
    fetchPolicy: 'cache-and-network',
  });
  const pendingPayrollCount = (isBusinessAccount || isPersonalAccount || isEmployeeDelegate)
    ? (pendingPayrollData?.pendingPayrollItems?.length || 0)
    : 0;
  const activeHumanitarianCampaign = humanitarianCampaignData?.activeHumanitarianCampaigns?.[0];
  const isPresaleClaimsUnlocked = presaleStatusData?.isPresaleClaimsUnlocked === true;
  const [presaleDismissed, setPresaleDismissed] = useState(false);
  const showPayrollCard = (isBusinessAccount || isEmployeeDelegate || isPersonalAccount) && pendingPayrollCount > 0;

  // F-005: single promo slot. Only the highest-priority pending item renders on Home,
  // instead of stacking every banner between the balance and the quick actions.
  // Priority: user's unclaimed money > payroll needing signatures > unclaimed presale tokens > campaigns.
  const homePromo: 'inviteClaim' | 'payroll' | 'presaleClaim' | 'humanitarian' | null =
    showInviteClaimCard ? 'inviteClaim'
      : showPayrollCard ? 'payroll'
        : (isPresaleClaimsUnlocked && !presaleDismissed) ? 'presaleClaim'
          : activeHumanitarianCampaign ? 'humanitarian'
            : null;

  // Hunting ReadableNativeArray.getString crash: confirm we reach Home mount,
  // and timestamp it relative to any subsequent crash in Crashlytics.
  useEffect(() => {
    logBreadcrumb('HomeScreen.mount');
    return () => {
      logBreadcrumb('HomeScreen.unmount');
    };
  }, []);

  // Refetch when the active account changes (skip initial mount — useQuery
  // already fetches). EVERY account-scoped query on this screen, not just
  // cUSD: the BSC dollar row, its Confío Dollar / Confío Dollar+ name (a
  // per-USER eligibility flag that still arrives inside this per-account
  // payload) and the payroll card are all read under the JWT's account, so
  // refetching one of the six left the rest showing the account the user
  // just left. Belt to the account-switch machinery's braces — this also
  // covers switch paths that don't go through useAtomicAccountSwitch.
  const prevAccountIdRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    const currentId = activeAccount?.id;
    if (currentId && prevAccountIdRef.current !== undefined && prevAccountIdRef.current !== currentId) {
      refetchMyBalances();
      refetchPendingPayroll();
      refetchSavingsPortfolioRef.current?.().catch(() => {});
    }
    prevAccountIdRef.current = currentId;
  }, [activeAccount?.id, refetchMyBalances, refetchPendingPayroll]);

  // Re-foreground refresh. Home never remounts and never loses focus while
  // the app is backgrounded, so without this the screen shows whatever it
  // read before the phone went in a pocket — including a stale
  // Confío Dollar / Confío Dollar+ name after a server-side eligibility
  // change. The portfolio's 60s poll gets there eventually; a user coming
  // back to the app should not have to wait for it.
  const appStateRef = useRef(AppState.currentState);
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (appStateRef.current.match(/inactive|background/) && next === 'active') {
        refetchMyBalances();
        refetchSavingsPortfolioRef.current?.().catch(() => {});
      }
      appStateRef.current = next;
    });
    return () => sub.remove();
  }, [refetchMyBalances]);

  // Force refresh balances when navigating BACK to this screen (not on initial mount)
  const isMountedRef = useRef(false);
  useFocusEffect(
    useCallback(() => {
      logBreadcrumb(`HomeScreen.focus | firstFocus=${!isMountedRef.current}`);
      if (!isMountedRef.current) {
        // Skip the very first focus — useQuery's network-only already fires on mount
        isMountedRef.current = true;
        return;
      }
      refetchMyBalances();
      refetchPendingPayroll();
      // The BSC dollar row lives in its own query (JWT-scoped, 60s poll).
      // Home never remounts, so without this the slot keeps whatever it
      // read a minute ago while the legacy cUSD row updates instantly —
      // coming back from a deposit/receive, the money looks missing.
      refetchSavingsPortfolioRef.current?.().catch(() => {});
    }, [refetchMyBalances, refetchPendingPayroll])
  );

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
          // Submit to backend
          const attributionData = link.metadata ? {
            ...link.metadata,
            referral_code: link.payload,
            attach_method: 'deferred_link',
          } : undefined;
          const { data, errors } = await setReferrerMutation({
            variables: {
              referrerIdentifier: link.payload,
              attributionData: attributionData ? JSON.stringify(attributionData) : undefined,
            }
          });


          // Handle GraphQL errors
          if (errors && errors.length > 0) {
            const errorMessage = errors[0].message;
            const friendly = formatReferralErrorMessage(errorMessage);

            // 1. Rate Limits: KEEP link, SHOW alert
            const isRateLimit = /rate limit/i.test(errorMessage) || /demasiadas veces/i.test(friendly);
            if (isRateLimit) {
              Alert.alert('Aviso', friendly, [{ text: 'Entendido' }]);
              return;
            }

            // 2. Suspicious/Abuse: CLEAR link, SILENCE alert (to avoid loop)
            const isSuspicious = /suspicious/i.test(errorMessage) || /unusual/i.test(friendly) || /inusual/i.test(friendly);
            if (isSuspicious) {
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
              await deepLinkHandler.clearDeferredLink();
              Alert.alert('Aviso', friendly, [{ text: 'Entendido' }]);
              return;
            }

            // 4. Unknown/Network Errors: KEEP link, SHOW alert (user might retry)
            Alert.alert('Aviso', friendly, [{ text: 'Entendido' }]);
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

            // Check if already registered/claimed or suspicious - clear silently without showing alert
            const shouldSuppressError =
              data?.setReferrer?.message?.includes('already') ||
              data?.setReferrer?.message?.includes('Ya registraste') ||
              data?.setReferrer?.error?.includes('already') ||
              data?.setReferrer?.error?.includes('Ya registraste') ||
              /suspicious/i.test(data?.setReferrer?.error || '') ||
              /suspicious/i.test(data?.setReferrer?.message || '');


            if (shouldSuppressError) {
              // Clear the deferred link silently - user already has a referrer or flagged as suspicious
              try {
                await deepLinkHandler.clearDeferredLink();
              } catch (clearErr) {
              }
            } else {
              // Show alert for other errors with explicit button object
            }
          }
        }
      } catch (err: any) {
        // Try to extract a meaningful error message
        const errorMessage = err?.graphQLErrors?.[0]?.message || err?.message;
        if (errorMessage) {
          const friendly = String(formatReferralErrorMessage(errorMessage) || 'Error desconocido');
          Alert.alert('Error', friendly, [{ text: 'Entendido', onPress: () => { } }]);
        } else {
          Alert.alert('Error', 'Error de conexión. Intenta de nuevo.', [{ text: 'Entendido', onPress: () => { } }]);
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
    // Preferred: the live BSC curve price (server-cached ~60s). The curve
    // moves with every purchase, unlike the static phase price below.
    const rawCurve = presaleStatusData?.confioCurrentPrice;
    const curvePrice = rawCurve ? parseFloat(rawCurve) : NaN;
    if (Number.isFinite(curvePrice) && curvePrice > 0) {
      return curvePrice;
    }

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
  }, [presaleStatusData, activePresaleData, allPresalePhasesData]);

  const confioLocked = React.useMemo(() =>
    parseFloat(myBalancesData?.myBalances?.confioLocked || myBalancesData?.myBalances?.confioPresaleLocked || '0'),
    [myBalancesData?.myBalances?.confioLocked, myBalancesData?.myBalances?.confioPresaleLocked]
  );

  // What the user OWNS: available + presale + earned bonuses. Bonuses still
  // waiting on a deposit are excluded — the home number is my money, and this
  // row used to count CONFIO that had not been earned yet, which also inflated
  // the portfolio headline below.
  //
  // NULL when the breakdown hasn't answered, and there is deliberately NO
  // fallback to confioLive + confioLocked: myBalances.confioLocked still
  // includes the unearned pending rewards on purpose (older builds depend on
  // it), so falling back would silently put ~101K CONFIO of money nobody
  // earned back into this row and into the portfolio headline. An unknown
  // balance renders as "—"; a wrong one gets spent against. Apollo's cache
  // keeps the last good read, so this only shows before the first success.
  const confioTotal = React.useMemo<number | null>(() => {
    const b = confioBreakdownData?.myConfioBreakdown;
    if (!b) return null;
    const num = (v: string | null | undefined) => {
      const parsed = parseFloat(v ?? '0');
      return isFinite(parsed) ? parsed : 0;
    };
    return num(b.available) + num(b.presaleLocked) + num(b.earnedBonuses);
  }, [confioBreakdownData]);

  // Unknown contributes nothing to the portfolio total. Understating is the
  // safe direction: it can't make someone think they have money they don't.
  const confioUsdValue = React.useMemo(() => (confioTotal ?? 0) * confioPriceUsd, [confioTotal, confioPriceUsd]);



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

  // Calculate portfolio value including CONFIO marked to current presale
  // price plus the cUSD+ savings position AND raw wallet USDT (Mercado Pago
  // model: the spendable AND yielding dollars are one headline number, and
  // money must never vanish between USDT landing and the silent mint —
  // for geo-ineligible users the raw USDT IS their dollar). Stocks stay
  // out — the home number must never have a red day; Acciones live in
  // their own row.
  const totalUSDValue = React.useMemo(
    () =>
      cUSDBalance + usdcBalance + confioUsdValue +
      savingsPortfolio.savings.balanceUsd + savingsPortfolio.usdtBalanceUsd,
    [cUSDBalance, usdcBalance, confioUsdValue,
     savingsPortfolio.savings.balanceUsd, savingsPortfolio.usdtBalanceUsd]
  );

  // Use real exchange rate from API only - no fallbacks
  const localExchangeRate = marketRate || 1;
  const totalLocalValue = totalUSDValue * localExchangeRate;

  // Don't show local currency option if exchange rate is not available
  const canShowLocalCurrency = marketRate !== null && marketRate !== 1 && currency.code !== 'USD';

  // Track initialization state — wait for essential data before showing content
  const [isInitialized, setIsInitialized] = useState(false);
  // Only show loading during the initial pass; do not toggle back after first render
  const isLoading = !isInitialized;

  // Gate initialization on activeAccount + first balance data to prevent layout shake
  const initializedRef = useRef(false);
  useEffect(() => {
    if (initializedRef.current) return;
    if (activeAccount && !myBalancesLoading && myBalancesData) {
      initializedRef.current = true;
      setIsInitialized(true);
    }
  }, [activeAccount, myBalancesLoading, myBalancesData]);

  useEffect(() => {
    if (myBalancesError) {    }
  }, [myBalancesError]);

  // Auto-Swap logic has been refactored into the useAutoSwap hook

  // No more mock accounts - we fetch from server

  // Convert stored accounts to the format expected by ProfileMenu
  // For personal accounts, format phone number with country code
  const accountMenuItems = React.useMemo(() => (
    accounts.map(acc => {
      if (acc.type === 'personal' && userProfile) {
        return {
          ...acc,
          phone: formatPhoneNumber(userProfile.phoneNumber, userProfile.phoneCountry),
        };
      }
      return acc;
    })
  ), [accounts, userProfile]);

  // Display accounts — useAccountManager already handles placeholders, no need
  // for a separate bootstrap effect that causes extra re-renders.
  const displayAccounts = React.useMemo(() => {
    if (accountMenuItems.length > 0) {
      return accountMenuItems;
    }

    // Fallback: derive from profile data (rare, only if useAccountManager is still loading)
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
  }, [accountMenuItems, profileData?.businessProfile, userProfile]);

  // Save balance visibility preference to Keychain
  const saveBalanceVisibility = async (isVisible: boolean) => {
    const server = String(PREFERENCES_KEYCHAIN_SERVICE);
    const username = String(BALANCE_VISIBILITY_KEY);
    const password = String(isVisible);
    logBreadcrumb(
      `Home.saveBalanceVisibility | ${describeTypes({ server, username, password })}`
    );
    try {
      await Keychain.setInternetCredentials(server, username, password);
    } catch (error) {
      recordCrashError(error);
    }
  };

  // Load balance visibility preference from Keychain
  const loadBalanceVisibility = async () => {
    const server = String(PREFERENCES_KEYCHAIN_SERVICE);
    logBreadcrumb(`Home.loadBalanceVisibility | ${describeTypes({ server })}`);
    try {
      const credentials = await Keychain.getInternetCredentials(server);
      if (credentials && credentials.username === BALANCE_VISIBILITY_KEY) {
        setShowBalance(credentials.password === 'true');
      }
    } catch (error) {
      // No saved preference, default to showing balance
      recordCrashError(error);
    }
  };

  // Load last shown invite timestamp
  const loadLastInviteTimestamp = async (): Promise<number | null> => {
    const server = String(INVITE_TS_SERVICE);
    logBreadcrumb(`Home.loadLastInviteTimestamp | ${describeTypes({ server })}`);
    try {
      const creds = await Keychain.getInternetCredentials(server);
      if (creds && creds.username === INVITE_TS_KEY && creds.password) {
        const ts = parseInt(creds.password, 10);
        return isNaN(ts) ? null : ts;
      }
    } catch (error) {
      recordCrashError(error);
    }
    return null;
  };

  // Save last shown invite timestamp
  const saveLastInviteTimestamp = async (ts: number) => {
    const server = String(INVITE_TS_SERVICE);
    const username = String(INVITE_TS_KEY);
    const password = String(ts);
    logBreadcrumb(
      `Home.saveLastInviteTimestamp | ${describeTypes({ server, username, password })}`
    );
    try {
      await Keychain.setInternetCredentials(server, username, password);
    } catch (e) {
      recordCrashError(e);
    }
  };

  // Toggle balance visibility and save preference
  const toggleBalanceVisibility = () => {
    const newVisibility = !showBalance;
    setShowBalance(newVisibility);
    saveBalanceVisibility(newVisibility);
  };

  const currentAccount = React.useMemo(() => {
    if (activeAccount) {
      return {
        ...activeAccount,
        phone: activeAccount.type === 'personal' && userProfile
          ? formatPhoneNumber(userProfile.phoneNumber, userProfile.phoneCountry)
          : activeAccount.phone,
      };
    }

    return displayAccounts.length > 0 ? displayAccounts[0] : null;
  }, [activeAccount, displayAccounts, userProfile]);

  const canViewBalance = !activeAccount?.isEmployee || !!activeAccount?.employeePermissions?.viewBalance;
  const displayedPortfolioBalance = canViewBalance
    ? showBalance
      ? (showLocalCurrency
        ? formatAmount.plain(floorToDecimals(totalLocalValue, 2))
        : formatFixedFloor(totalUSDValue, 2))
      : '••••••'
    : '••••••';


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
      await Promise.all([
        refetchMyBalances(),
        // Pull-to-refresh has to move the BSC dollar row too, otherwise the
        // gesture visibly does nothing for the balance most users came to
        // check. (Server-side read cache is 30s, so this is as fresh as the
        // server will serve.)
        refetchSavingsPortfolioRef.current?.() ?? Promise.resolve(),
      ]);
      setStatsRefreshNonce((nonce) => nonce + 1);
    } catch (error) {
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

  // Recargar/Retirar run through ramp providers (Koywe/Guardarian). Where
  // neither operates (VE, NI, PA, CU, ...), the shared hook blocks up front
  // and points to the Efectivo directory instead of failing deep inside the
  // provider flow. It lives in the hook so every entry point gets the guard —
  // this check used to be local to Home, which is how the referral CTAs
  // walked blocked-country users straight into the ramp screen.
  const { navigateToRampOrEfectivo } = useRampCountry();

  // World pickers: Recargar/Retirar route money between the two settlement
  // worlds — spend (cUSD · Algorand) vs grow (cUSD+ · savings chain). Two
  // doors teach the split; more doors teach confusion. Employees skip these
  // (savings is a personal-account feature).
  const [rechargeSheetVisible, setRechargeSheetVisible] = useState(false);
  const [withdrawSheetVisible, setWithdrawSheetVisible] = useState(false);

  // cUSD phase-out (cusdDepositsPaused, server-flipped): the promoted door
  // for EVERYONE is the USDT-BSC rail. Eligibility only decides what the
  // delivered USDT becomes (silent mint to cUSD+ vs raw "Confío Dollar"),
  // so the copy varies but the destination doesn't.
  const savingsRechargeOption: RouteOption = {
    icon: 'trending-up',
    title: savingsPortfolio.savings.enabled
      ? 'Para ahorrar e invertir'
      : 'Recargar dólares',
    subtitle: savingsPortfolio.savings.enabled
      ? 'Gana rendimiento mientras decides · cUSD+'
      : 'Se acreditan en tu Confío Dollar',
    onPress: () => {
      // USDT-BSC rail: Koywe delivers USDT to the user's own address. Goes
      // through the shared helper so the blocked-country check (VE/NI/PA/CU)
      // applies here too — this row used to navigate straight past it.
      navigateToRampOrEfectivo('TopUp', { destination: 'cusd_plus' });
    },
  };
  const cusdRechargeOption: RouteOption = {
    icon: 'dollar-sign',
    // While paused this door exists to UNBLOCK A DRAIN, not to sell cUSD:
    // an off-ramp has a per-method minimum, so a leftover balance below it
    // is stranded unless the user can top it back up to the threshold.
    title: savingsPortfolio.savings.cusdDepositsPaused
      ? 'Al antiguo Confío Dollar'
      : 'Para usar día a día',
    subtitle: savingsPortfolio.savings.cusdDepositsPaused
      ? 'Completa el mínimo para poder retirarlo · cUSD'
      : 'Enviar, pagar y comprar CONFIO · cUSD',
    onPress: () => navigateToRampOrEfectivo('TopUp'),
  };
  // The BSC rail is offered whether or not the user is Ondo-eligible: an
  // ineligible user's top-up lands as plain Confío Dollar (USDT) instead of
  // minting yield, which is exactly what savingsRechargeOption's subtitle
  // already promises.
  //
  // The cUSD door follows the SAME rule as the legacy wallet row below
  // (`!paused || cUSDBalance > 0`): hidden from people with nothing to
  // drain, kept for holders — otherwise a balance under the off-ramp
  // minimum can never be withdrawn at all.
  const showLegacyCusdDoor =
    !savingsPortfolio.savings.cusdDepositsPaused || cUSDBalance > 0;
  const rechargeOptions: RouteOption[] = showLegacyCusdDoor
    ? [savingsRechargeOption, cusdRechargeOption]
    : [savingsRechargeOption];
  // A one-option sheet is pure friction: go straight to the flow. Read via
  // a ref because the quickActions useMemo (narrow deps) would otherwise
  // capture a stale options array.
  const rechargeOptionsRef = React.useRef(rechargeOptions);
  rechargeOptionsRef.current = rechargeOptions;
  const openRechargeFlow = React.useCallback(() => {
    const opts = rechargeOptionsRef.current;
    if (opts.length === 1) {
      opts[0].onPress();
      return;
    }
    setRechargeSheetVisible(true);
  }, []);

  // What the BSC withdrawal rail can actually move in ONE operation: BOTH
  // legs. The funding batch redeems the shortfall out of the vault and pays
  // from the combined balance in a single transaction, and the server's
  // sufficiency check authorizes on raw + position too — so max() understated
  // a split balance and sent users to a door that looked too small to use
  // (audit 2026-08-03 [P2] #13). SUM, matching the sell screens.
  const bscWithdrawableUsd =
    savingsPortfolio.savings.balanceUsd + savingsPortfolio.usdtBalanceUsd;

  // Both options land in the user's bank — the differentiator is where the
  // money sits NOW, so subtitles show live balances instead of destinations.
  // The legacy cUSD row is OMITTED (not merely disabled) once drained, so a
  // user with no cUSD sees a single door and skips the sheet entirely —
  // same rule as the recharge sheet and the legacy wallet row.
  const withdrawOptions: RouteOption[] = [
    ...(showLegacyCusdDoor
      ? [{
        icon: 'dollar-sign',
        title: 'Desde mi cUSD',
        subtitle: `$${formatFixedFloor(cUSDBalance, 2)} disponibles`,
        disabled: cUSDBalance <= 0,
        onPress: () => navigateToRampOrEfectivo('Sell'),
      } as RouteOption]
      : []),
    {
      icon: 'trending-up',
      title: 'Desde mis ahorros',
      // Vault position OR raw USDT — the rail now exits either leg, which is
      // the only way an Ondo-ineligible user (who never mints shares) can
      // reach a bank. Stocks stay excluded: they can't exit through here, so
      // totalUsd would overstate what's withdrawable.
      subtitle: bscWithdrawableUsd > 0
          ? `$${formatFixedFloor(bscWithdrawableUsd, 2)} en ${savingsPortfolio.savings.enabled ? 'Confío Dollar+' : 'Confío Dollar'}`
          : 'Aún no tienes ahorros',
      disabled: bscWithdrawableUsd <= 0,
      onPress: () => {
        // Savings sells ride Guardarian everywhere (SellScreen routes on
        // `destination`, not on the country), so the only gate left is the
        // one that applies to every ramp: countries where NO provider
        // operates go to the Efectivo directory instead.
        navigateToRampOrEfectivo('Sell', { destination: 'cusd_plus' });
      },
    },
  ];
  // Same one-option rule as Recargar: a sheet that only ever offers one door
  // is pure friction. Ref for the same reason — quickActionsData's useMemo
  // has narrow deps and would otherwise capture a stale options array.
  const withdrawOptionsRef = React.useRef(withdrawOptions);
  withdrawOptionsRef.current = withdrawOptions;
  const openWithdrawFlow = React.useCallback(() => {
    const opts = withdrawOptionsRef.current;
    // Skip the sheet only when exactly one door is actually USABLE. Unlike
    // the recharge options, a withdraw row can be disabled (nothing to
    // withdraw from that leg), and onPress() would happily fire anyway —
    // dropping the user into an empty Sell screen.
    const usable = opts.filter((o) => !o.disabled);
    if (usable.length === 1) {
      usable[0].onPress();
      return;
    }
    setWithdrawSheetVisible(true);
  }, []);

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
          color: colors.primary,
          route: () => navigation.navigate('BottomTabs', { screen: 'Contacts' }),
        },
        {
          id: 'pay',
          label: 'Pagar',
          icon: 'shopping-bag',
          color: colors.secondary,
          route: () => {
            const isBusinessAccount = activeAccount?.type?.toLowerCase() === 'business';
            navigation.navigate('BottomTabs', {
              screen: isBusinessAccount ? 'Charge' : 'Scan'
            } as any);
          },
        },
        {
          id: 'efectivo',
          label: 'Efectivo',
          icon: 'cash',
          color: colors.primaryDark,
          route: () => navigation.navigate('Financieras'),
        },
      ].filter(action => {
        switch (action.id) {
          case 'send':
            return permissions.sendFunds === true;
          // 'receive' removed
          case 'pay':
            return permissions.sendFunds === true;
          // Recargar/Retirar are deliberately absent from the list above:
          // moving business money to or from a BANK is the owner's alone.
          // They were previously gated on manageP2p and sendFunds, which
          // are operational permissions and grant no banking authority —
          // any employee who could pay a supplier could also drain the
          // account to a bank. CreateRampOrder now refuses employees
          // server-side too (_employee_ramp_denial).
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
        color: colors.primary,
        route: () => navigation.navigate('BottomTabs', { screen: 'Contacts' }),
      },
      {
        id: 'pay',
        label: 'Pagar',
        icon: 'shopping-bag',
        color: colors.secondary,
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
        color: colors.accent,
        route: openRechargeFlow,
      },
      {
        id: 'withdraw',
        label: 'Retirar',
        icon: 'bank',
        color: colors.offRampIcon,
        route: () => openWithdrawFlow(),
      },
      {
        id: 'efectivo',
        label: 'Efectivo',
        icon: 'cash',
        color: colors.primaryDark,
        route: () => navigation.navigate('Financieras'),
      }
    ];
    // Both flows are useCallback([]) and read their options through refs, so
    // they're referentially stable and can't go stale here.
  }, [activeAccount, navigation, openRechargeFlow, openWithdrawFlow]);

  // Entrance animation - only run after initialization
  React.useEffect(() => {
    if (isInitialized) {
      // No delay needed — skeleton overlay handles the transition
      entranceAnimRef.current?.stop();
      entranceAnimRef.current = Animated.timing(fadeAnim, {
        toValue: 1,
        duration: 250,
        useNativeDriver: true,
      });
      entranceAnimRef.current.start();
    }
    return () => {
      entranceAnimRef.current?.stop();
    };
  }, [fadeAnim, isInitialized]);

  // Balance animation when value changes
  React.useEffect(() => {
    balanceTransitionRef.current?.stop();
    balanceTransitionRef.current = Animated.timing(balanceAnim, {
      toValue: showLocalCurrency ? 1 : 0,
      duration: 300,
      useNativeDriver: true,
    });
    balanceTransitionRef.current.start();
    return () => {
      balanceTransitionRef.current?.stop();
    };
  }, [showLocalCurrency, balanceAnim]);

  React.useEffect(() => {
    return () => {
      entranceAnimRef.current?.stop();
      balanceTransitionRef.current?.stop();
      fadeAnim.stopAnimation();
      balanceAnim.stopAnimation();
      scaleAnim.stopAnimation();
    };
  }, [balanceAnim, fadeAnim, scaleAnim]);

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
          const untriedInvites = pendingInvites.filter(invite => !autoClaimedInviteIds.current.has(invite.invitationId));
          if (untriedInvites.length > 0 && !claimingInvite) {
            untriedInvites.forEach(invite => autoClaimedInviteIds.current.add(invite.invitationId));
            void handleClaimInvite();
          }
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
  }, [userProfile?.phoneNumber, userProfile?.phoneCountry, claimingInvite, handleClaimInvite]);





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
      // Initialization is now gated by activeAccount + balances arriving (above)

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
    if (currentAccount) {
      setCurrentAccountAvatar(currentAccount.avatar);
    }
  }, [currentAccount, setCurrentAccountAvatar]);

  // FIX: Refresh Algorand address when active account changes (critical for post-migration update)
  useEffect(() => {
    let mounted = true;
    const { DeviceEventEmitter } = require('react-native');

    const fetchAddress = async () => {
      const authService = AuthService.getInstance();
      try {
        const address = await authService.getAlgorandAddress();
        if (mounted) {
          setAlgorandAddress(address);
        }
      } catch (e) {
      }
    };

    fetchAddress();

    // Listen for direct address updates (e.g. from migration)
    const subscription = DeviceEventEmitter.addListener('ALGORAND_ADDRESS_UPDATED', (newAddress: string) => {
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

  // Memoized navigation handlers for better performance
  const navigateToCUSDAccount = useCallback(() => {
    navigation.navigate('AccountDetail', {
      accountType: 'cusd',
      accountName: savingsPortfolio.savings.cusdDepositsPaused
        ? 'Antiguo Confío Dollar'
        : 'Confío Dollar',
      accountSymbol: '$cUSD',
      accountBalance: cUSDBalance.toFixed(2),
      // Fix: Use local state algorandAddress if available, fall back to context
      accountAddress: algorandAddress || activeAccount?.algorandAddress || ''
    });
  }, [navigation, cUSDBalance, activeAccount?.algorandAddress, algorandAddress,
      savingsPortfolio.savings.cusdDepositsPaused]);

  const navigateToConfioAccount = useCallback(() => {
    navigation.navigate('AccountDetail', {
      accountType: 'confio',
      accountName: 'Confío',
      accountSymbol: '$CONFIO',
      // Route param is only a first-paint hint; the detail screen reads the
      // breakdown itself. Empty when unknown rather than a guessed number.
      accountBalance: confioTotal !== null ? confioTotal.toFixed(2) : '',
      // Fix: Use local state algorandAddress if available, fall back to context
      accountAddress: algorandAddress || activeAccount?.algorandAddress || ''
    });
  }, [navigation, confioTotal, activeAccount?.algorandAddress, algorandAddress]);

  // Use refs for unstable dependencies so handleAccountSwitch identity is stable
  const atomicSwitchAccountRef = useRef(atomicSwitchAccount);
  atomicSwitchAccountRef.current = atomicSwitchAccount;
  const refetchMyBalancesRef = useRef(refetchMyBalances);
  refetchMyBalancesRef.current = refetchMyBalances;

  const handleAccountSwitch = useCallback(async (accountId: string): Promise<boolean> => {
    try {

      // Close the profile menu immediately to provide feedback
      profileMenu.closeProfileMenu();

      // All accounts are now real accounts from the server

      // Use atomic account switching (via ref to avoid dep instability)
      const success = await atomicSwitchAccountRef.current(accountId);

      if (success) {
        // Refresh balances after successful switch
        await refetchMyBalancesRef.current();
        return true;
      } else {
        return false;
      }
    } catch (error) {
      Alert.alert(
        'Error',
        'No se pudo cambiar la cuenta. Por favor intenta nuevamente.',
        [{ text: 'Entendido', onPress: () => { } }]
      );
      return false;
    }
  }, [profileMenu.closeProfileMenu]);

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


        // Only process if we have BOTH a pending switch AND navigation
        if (pendingSwitch && pendingNavigation && handleAccountSwitch) {

          // Clear the pending switch to prevent duplicate processing
          PushNotificationService.clearPendingAccountSwitch();
          PushNotificationService.clearPendingNavigation();

          // Store the navigation function before clearing
          const navigationToExecute = pendingNavigation;

          // Execute the account switch
          handleAccountSwitch(pendingSwitch).then(success => {
            if (success) {
              // Execute navigation after a short delay
              setTimeout(() => {
                navigationToExecute();
              }, 500);
            }
          }).catch(() => {});
        }
      }, 100); // Small delay to ensure screen is ready

      return () => clearTimeout(timer);
    }, [handleAccountSwitch])
  );

  return (
    <View style={styles.container}>
      {/* Skeleton overlay — rendered on top while loading, then removed */}
      {isLoading && (
        <View style={[StyleSheet.absoluteFillObject, { zIndex: 1, backgroundColor: colors.neutral }]} pointerEvents="none">
          <View style={styles.balanceCard}>
            <View style={styles.balanceCardInner}>
              <View style={styles.portfolioHeader}>
                <View style={styles.portfolioTitleContainer}>
                  <Text style={styles.portfolioLabel}>Mi Saldo Total</Text>
                  <Text style={styles.portfolioSubLabel}>En Dólares</Text>
                </View>
              </View>
              <View style={styles.balanceContainer}>
                <Text style={styles.currencySymbol}>$</Text>
                <Text style={styles.balanceAmount}>••••••</Text>
              </View>
            </View>
          </View>
          <View style={styles.walletsSection}>
            <Text style={styles.walletsTitle}>Mis Billeteras</Text>
            <WalletCardSkeleton />
            <WalletCardSkeleton />
          </View>
        </View>
      )}
      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.white}
            colors={[colors.primary]}
          />
        }
        showsVerticalScrollIndicator={false}
      >
        {/* Enhanced Balance Card Section — brand field: same gradient + coin
            ring family as Auth/splash/Biometric. Vertical gradient so the top
            edge is exactly colors.primary and meets the flat nav header with
            no seam. Padding lives on the inner view, never on the SVG's
            parent (Yoga insets absolute children by the parent's padding). */}
        <Animated.View
          style={[
            styles.balanceCard,
            {
              opacity: fadeAnim,
              transform: [{ scale: scaleAnim }],
            }
          ]}
        >
          <BrandFieldBackground id="homeField" ringCx="102%" ringCy="46%" ringR={80} ringWidth={20} />
          <View style={styles.balanceCardInner}>
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
                  hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                  accessibilityRole="button"
                  accessibilityLabel={showBalance ? 'Ocultar saldo' : 'Mostrar saldo'}
                >
                  <Icon name={showBalance ? 'eye' : 'eye-off'} size={18} color={colors.white} />
                </TouchableOpacity>
              )}
              {canShowLocalCurrency && (
                <TouchableOpacity
                  style={styles.currencyToggle}
                  onPress={() => setShowLocalCurrency(!showLocalCurrency)}
                  activeOpacity={0.7}
                  hitSlop={{ top: 8, bottom: 8, left: 4, right: 4 }}
                  accessibilityRole="button"
                  accessibilityLabel={showLocalCurrency ? 'Mostrar en dólares' : `Mostrar en ${currency.name}`}
                >
                  <Text style={styles.currencyToggleText}>
                    {showLocalCurrency ? currency.code : 'USD'}
                  </Text>
                  <Icon name="chevron-down" size={14} color={colors.white} />
                </TouchableOpacity>
              )}
            </View>
          </View>

          <Animated.View
          style={[
            styles.balanceContainer,
            {
              opacity: 1,
            }
          ]}
          >
            <Text style={styles.currencySymbol}>
              {showLocalCurrency ? currency.symbol : '$'}
            </Text>
                    <Text style={styles.balanceAmount}>
              {displayedPortfolioBalance}
            </Text>
          </Animated.View>
          </View>
        </Animated.View>


        {homePromo === 'inviteClaim' && (
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
              <Icon name="arrow-right" size={16} color={colors.white} />
            </TouchableOpacity>
          </View>
        )}

        {/* Payroll quick action */}
        {homePromo === 'payroll' && (
          <TouchableOpacity
            style={[styles.payrollCard, { marginHorizontal: 16, marginBottom: 12 }]}
            onPress={() => navigation.navigate('PayrollPending')}
            activeOpacity={0.9}
          >
            <View style={styles.payrollIconWrap}>
              <Icon name="briefcase" size={20} color={colors.white} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.payrollTitle}>Pagos de nómina</Text>
              <Text style={styles.payrollSubtitle}>
                {pendingPayrollCount > 0
                  ? `Tienes ${pendingPayrollCount} pagos para firmar`
                  : 'Revisa y ejecuta tus pagos de nómina'}
              </Text>
            </View>
            <Icon name="chevron-right" size={18} color={colors.text.light} />
          </TouchableOpacity>
        )}

        {homePromo === 'humanitarian' && activeHumanitarianCampaign && (
          <HumanitarianHomeBanner
            campaign={activeHumanitarianCampaign}
            onPress={() => navigation.navigate('HumanitarianAid', { slug: activeHumanitarianCampaign.slug })}
            style={{ marginHorizontal: 16, marginBottom: 12 }}
          />
        )}

        {/* CONFIO Presale Banner - claims unlocked */}
        {homePromo === 'presaleClaim' && (
          <Animated.View
            style={[
              styles.presaleBanner,
              {
                opacity: fadeAnim,
                transform: [
                  {
                    translateY: fadeTranslateY20
                  }
                ],
              }
            ]}
          >
            <View style={styles.presaleBannerContent}>
              <View style={styles.presaleBannerLeft}>
                <View style={[styles.presaleBadge, { backgroundColor: colors.primaryDark }]}>
                  <Text style={styles.presaleBadgeText}>RECLAMO</Text>
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
                  <Text style={[styles.presaleDetailsLink, { color: colors.primaryDark }]}>Ir a reclamar</Text>
                </TouchableOpacity>
              </View>
              <View style={styles.presaleBannerRight}>
                <TouchableOpacity onPress={() => setPresaleDismissed(true)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} style={{ position: 'absolute', top: -6, right: -6 }}>
                  <Icon name="x" size={18} color={colors.primaryDark} />
                </TouchableOpacity>
                <TouchableOpacity onPress={() => navigation.navigate('ConfioPresale')} activeOpacity={0.9} style={{ alignItems: 'center' }}>
                  <Image source={CONFIOLogo} style={styles.presaleBannerLogo} />
                  <Icon name="chevron-right" size={20} color={colors.primaryDark} />
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
                  translateY: fadeTranslateY30
                }
              ],
            }
          ]}
        >
          {/* Show employee welcome message if limited actions available */}
          {activeAccount?.isEmployee && quickActions.length <= 1 ? (
            <View style={styles.employeeWelcomeContainer}>
              <View style={styles.employeeWelcomeIcon}>
                <Icon name="briefcase" size={32} color={colors.secondaryDark} />
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
                <View
                  style={[
                    styles.actionIcon,
                    { backgroundColor: action.color },
                  ]}
                >
                  {/* @ts-ignore */}
                  {action.icon === 'bank' || action.icon === 'cash' ? (
                    <MCIcon name={action.icon} size={action.icon === 'cash' ? 22 : 20} color={colors.white} />
                  ) : (
                    <Icon name={action.icon} size={22} color={colors.white} />
                  )}
                </View>
                <Text style={styles.actionLabel}>{action.label}</Text>
              </TouchableOpacity>
            ))
          )}
        </Animated.View>

        {/* Crecimiento Confío stats */}
        <HomeStatsSection
          refreshNonce={statsRefreshNonce}
          showStocks={savingsPortfolio.stocks.enabled}
        />

        {/* Wallets Section */}
        <View style={styles.walletsSection}>
          <Text style={styles.walletsTitle}>Mis Billeteras</Text>

          {/* Both queries feed rows here, so wait for both: a $0.00 dollar
              row that fills in a beat later reads as "my money is gone". */}
          {(myBalancesLoading || savingsPortfolio.loading) ? (
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
                    translateY: fadeTranslateY40
                  }
                ]
              }}
            >
              {/* Primary dollar row (IA inversion, 2026-07-30: cUSD phases
                  out, ALL deposits land as USDT-BSC). Eligible users see
                  "Confío Dollar+" (vault + landed-not-yet-minted USDT);
                  geo-ineligible users see plain "Confío Dollar" — same money
                  minus the yield, USDT never marketed by name. ONE calm
                  entry, deliberately NO day-change here; stocks now live in
                  their own row. Principle: home shows calm balances. */}
              {/* Row rule (Julian, 07-31): "Confío Dollar+" and the new
                  "Confío Dollar" are the SAME slot — eligibility picks
                  which one appears, exactly one always shows. Neither
                  cares about the legacy row below, which is an
                  independent overlay driven only by cUSD-Algorand
                  balance. */}
              {/* Shown to employees too. Balance VISIBILITY is a permission
                  (viewBalance) and it hides the NUMBER — it does not remove
                  the wallet from the account. Hiding the whole card here was
                  the outlier: the legacy row below, and every other balance
                  surface, mask the figure and keep the row. */}
              <Pressable
                  style={({ pressed }) => [
                    styles.walletCard,
                    pressed && { opacity: 0.7 }
                  ]}
                  onPress={() => navigation.navigate('AccountDetail', {
                    accountType: 'cusd_plus',
                    // Same rule as the row title: an ineligible user must not
                    // land on a screen headed "Confío Dollar+".
                    accountName: savingsPortfolio.savings.enabled
                      ? 'Confío Dollar+' : 'Confío Dollar',
                    accountSymbol: '$cUSD+',
                    // Live figures come from the portfolio inside the screen;
                    // this is only the first paint.
                    accountBalance: '0.00',
                  })}
                >
                  <View style={styles.walletCardContent}>
                    <View style={[styles.walletLogoContainer, { backgroundColor: colors.white }]}>
                      <Image source={cUSDPlusLogo} style={styles.walletLogo} />
                    </View>
                    <View style={styles.walletInfo}>
                      <Text style={styles.walletName}>
                        {/* ELIGIBILITY ALONE names the row (Julian, 08-02).
                            It used to also say "Confío Dollar+" whenever a
                            vault balance existed — "someone who cannot mint
                            can still be holding cUSD+" — but that made the
                            name a property of the balance instead of the
                            product: a blocked user kept the + title over a
                            "Dólar digital" subtitle, and it never changed
                            back, not even across a restart. An ineligible
                            user reads "Confío Dollar / Dólar digital",
                            always. The BALANCE below still includes the
                            vault position — what you hold is untouched, only
                            what we call it changed. */}
                        {savingsPortfolio.savings.enabled ? 'Confío Dollar+' : 'Confío Dollar'}
                      </Text>
                      <Text style={styles.walletSymbol}>
                        {/* Ticker in the subtitle like every other row
                            (CONFIO / cUSD). Ineligible variant stays
                            ticker-less: that money is raw USDT, not
                            cUSD+ — no dishonest badge. */}
                        {savingsPortfolio.savings.enabled ? 'cUSD+ · Ahorro que rinde' : 'Dólar digital'}
                      </Text>
                    </View>
                    <View style={styles.walletBalanceContainer}>
                      <Text style={styles.walletBalanceText}>
                        {/* Eligible: vault + landed-not-yet-minted USDT.
                            Ineligible: the row IS the USDT balance — a
                            mere wallet, nothing vault-flavored. */}
                        {/* Same rule as the legacy row: an employee without
                            viewBalance sees the wallet, not the figure. */}
                        {/* ALWAYS include the vault balance. Dropping it when
                            savings is disabled meant an ineligible holder saw
                            $0.00 over real cUSD+ — money the portfolio total
                            below was counting all along. Eligibility gates
                            MINTING, never what you already hold. */}
                        {(canViewBalance && showBalance)
                          ? `$${formatFixedFloor(
                              savingsPortfolio.savings.balanceUsd + savingsPortfolio.usdtBalanceUsd,
                              2,
                            )}`
                          : '••••'}
                      </Text>
                      <Icon name="chevron-right" size={20} color={colors.text.light} />
                    </View>
                  </View>
                </Pressable>

              {/* Legacy cUSD — demoted row. While deposits are paused the
                  row exists only to drain (send/pay/retirar), so hide it
                  entirely once the balance reaches zero. */}
              {(!savingsPortfolio.savings.cusdDepositsPaused || cUSDBalance > 0) && (
                <Pressable
                  style={({ pressed }) => [
                    styles.walletCard,
                    pressed && { opacity: 0.7 }
                  ]}
                  onPress={navigateToCUSDAccount}
                >
                  <View style={styles.walletCardContent}>
                    <View style={[styles.walletLogoContainer, { backgroundColor: colors.white }]}>
                      <Image source={cUSDLogo} style={styles.walletLogo} />
                    </View>
                    <View style={styles.walletInfo}>
                      {/* Legacy lives in the NAME (prefix), not the
                          subtitle — the subtitle keeps what you can DO. */}
                      <Text style={styles.walletName}>
                        {savingsPortfolio.savings.cusdDepositsPaused
                          ? 'Antiguo Confío Dollar'
                          : 'Confío Dollar'}
                      </Text>
                      <Text style={styles.walletSymbol}>
                        {savingsPortfolio.savings.cusdDepositsPaused
                          ? 'Solo retiros y pagos'
                          : 'cUSD'}
                      </Text>
                    </View>
                    <View style={styles.walletBalanceContainer}>
                      <Text style={styles.walletBalanceText}>
                        {/* Hide balance for employees without viewBalance permission */}
                        {(activeAccount?.isEmployee && !activeAccount?.employeePermissions?.viewBalance)
                          ? '••••'
                          : showBalance ? `$${formatFixedFloor(cUSDBalance, 2)}` : '••••'}
                      </Text>
                      <Icon name="chevron-right" size={20} color={colors.text.light} />
                    </View>
                  </View>
                </Pressable>
              )}

              {/* CONFIO Wallet */}
              <Pressable
                style={({ pressed }) => [
                  styles.walletCard,
                  pressed && { opacity: 0.7 }
                ]}
                onPress={navigateToConfioAccount}
              >
                <View style={styles.walletCardContent}>
                  <View style={[styles.walletLogoContainer, { backgroundColor: colors.secondary }]}>
                    <Image source={CONFIOLogo} style={styles.walletLogo} />
                  </View>
                  <View style={styles.walletInfo}>
                    <Text style={styles.walletName}>Confío</Text>
                    <Text style={styles.walletSymbol}>CONFIO</Text>
                  </View>
                  <View style={styles.walletBalanceContainer}>
                    <Text style={styles.walletBalanceText}>
                      {/* Hide balance for employees without viewBalance permission.
                          "—" when the breakdown hasn't answered: unknown, not zero,
                          and never the pending-inclusive legacy number. */}
                      {(activeAccount?.isEmployee && !activeAccount?.employeePermissions?.viewBalance)
                        ? '••••'
                        : !showBalance ? '••••'
                        : confioTotal === null ? '—'
                        : formatFixedFloor(confioTotal, 2)}
                    </Text>
                    <Icon name="chevron-right" size={20} color={colors.text.light} />
                  </View>
                </View>
              </Pressable>

              {/* Acciones de EE.UU. — investments get their own row (split
                  from the old combined Ahorros hub): stocks have red days
                  and belong visually apart from the payment dollar. Shown
                  for stocks-enabled users and anyone still holding. */}
              {/* Issuer eligibility is authoritative: cached holdings must
                  never resurrect the U.S. stocks surface for a blocked geo. */}
              {savingsPortfolio.stocks.enabled && (
                <Pressable
                  style={({ pressed }) => [
                    styles.walletCard,
                    pressed && { opacity: 0.7 }
                  ]}
                  onPress={() => navigation.navigate('StocksList')}
                >
                  <View style={styles.walletCardContent}>
                    <View style={[styles.walletLogoContainer, { backgroundColor: colors.white }]}>
                      <Image source={cUSDPlusLogo} style={styles.walletLogo} />
                    </View>
                    <View style={styles.walletInfo}>
                      <Text style={styles.walletName}>Acciones de EE.UU.</Text>
                      <Text style={styles.walletSymbol}>Inversiones · Ondo</Text>
                    </View>
                    <View style={styles.walletBalanceContainer}>
                      <Text style={styles.walletBalanceText}>
                        {(canViewBalance && showBalance)
                          ? `$${formatFixedFloor(savingsPortfolio.stocks.totalUsd, 2)}`
                          : '••••'}
                      </Text>
                      <Icon name="chevron-right" size={20} color={colors.text.light} />
                    </View>
                  </View>
                </Pressable>
              )}
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

      <RouteSheet
        visible={rechargeSheetVisible}
        title="¿Para qué es esta recarga?"
        options={rechargeOptions}
        onClose={() => setRechargeSheetVisible(false)}
      />
      <RouteSheet
        visible={withdrawSheetVisible}
        title="¿Desde dónde quieres retirar?"
        options={withdrawOptions}
        onClose={() => setWithdrawSheetVisible(false)}
      />

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

      {/* The Algorand auto-swaps take priority: they carry the
          wallet-recovery mode. The savings mint reuses the same spinner. */}
      <AutoSwapModal
        visible={swapModalAsset !== null || walletRecoveryRequired || mintingSavings}
        assetType={swapModalAsset ?? (mintingSavings ? 'USDT' : null)}
        mode={walletRecoveryRequired ? 'wallet_recovery_required' : 'processing'}
        onClose={dismissWalletRecovery}
      />

    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.neutral,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: 100,
  },
  // Enhanced balance card styles. backgroundColor stays as the flat fallback
  // (skeleton overlay reuses this style without the SVG); overflow hidden
  // clips the gradient/ring to the rounded corners.
  balanceCard: {
    backgroundColor: colors.primary,
    borderBottomLeftRadius: 32,
    borderBottomRightRadius: 32,
    overflow: 'hidden',
  },
  balanceCardInner: {
    paddingTop: 20,
    paddingBottom: 30,
    paddingHorizontal: 20,
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
    color: colors.white,
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
    color: colors.white,
    marginRight: 6,
    fontWeight: '500',
  },
  balanceAmount: {
    fontSize: 42,
    fontWeight: 'bold',
    color: colors.white,
    letterSpacing: -1,
  },
  // Quick actions styles
  quickActionsCard: {
    flexDirection: 'row',
    justifyContent: 'space-evenly',
    paddingVertical: 24,
    paddingHorizontal: 16,
    backgroundColor: colors.white,
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
    width: 48,
    height: 48,
    borderRadius: 24,
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
    color: colors.text.primary,
    fontWeight: '600',
  },
  // Wallets section styles
  walletsSection: {
    paddingHorizontal: 20,
    marginTop: 16,
  },
  walletsTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.text.primary,
    marginBottom: 16,
  },
  walletCard: {
    backgroundColor: colors.white,
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
    backgroundColor: colors.primaryDark,
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
    color: colors.primary, // Brand green
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
    color: colors.text.primary,
  },
  walletSymbol: {
    fontSize: 14,
    color: colors.text.secondary,
    marginTop: 2,
  },
  walletBalanceContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  walletBalanceText: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text.primary,
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
    backgroundColor: colors.primary,
    marginBottom: 8,
  },
  inviteClaimBadgeText: {
    color: colors.white,
    fontWeight: 'bold',
    fontSize: 12,
    letterSpacing: 0.3,
  },
  inviteClaimTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.text.primary,
    marginBottom: 4,
  },
  inviteClaimSubtitle: {
    fontSize: 13,
    color: colors.text.secondary,
    lineHeight: 18,
  },
  inviteClaimButton: {
    marginTop: 12,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: colors.primary,
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 12,
    shadowColor: colors.primary,
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.2,
    shadowRadius: 4,
    elevation: 3,
  },
  inviteClaimButtonText: {
    color: colors.white,
    fontWeight: 'bold',
    fontSize: 14,
    letterSpacing: 0.3,
  },
  inviteClaimError: {
    color: colors.error.icon,
    marginTop: 8,
    fontSize: 13,
    textAlign: 'center',
  },
  inviteClaimSuccess: {
    color: colors.primaryDark,
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
    borderColor: colors.border,
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
    backgroundColor: colors.secondary,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  payrollTitle: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  payrollSubtitle: { fontSize: 13, color: colors.text.secondary, marginTop: 2 },
  // Loading state
  loadingText: {
    color: colors.white,
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
    color: colors.text.primary,
    marginBottom: 8,
    textAlign: 'center',
  },
  employeeWelcomeText: {
    fontSize: 14,
    color: colors.text.secondary,
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
    backgroundColor: colors.neutral,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    shadowColor: colors.secondary,
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
    backgroundColor: colors.secondary,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    alignSelf: 'flex-start',
    marginBottom: 8,
  },
  presaleBadgeText: {
    color: colors.white,
    fontSize: 12,
    fontWeight: 'bold',
  },
  presaleBannerTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.text.primary,
    marginBottom: 4,
  },
  presaleBannerSubtitle: {
    fontSize: 13,
    color: colors.text.secondary,
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
    color: colors.secondary,
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
