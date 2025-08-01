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
  Vibration
} from 'react-native';
import { Gradient } from '../components/common/Gradient';
import { AuthService } from '../services/authService';
import { useNavigation, useFocusEffect, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useAuth } from '../contexts/AuthContext';
import { useHeader } from '../contexts/HeaderContext';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import Icon from 'react-native-vector-icons/Feather';
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
import { useQuery } from '@apollo/client';
import { GET_ACCOUNT_BALANCE, GET_PRESALE_STATUS } from '../apollo/queries';
import { useCountry } from '../contexts/CountryContext';
import { useCurrency } from '../hooks/useCurrency';
import { useSelectedCountryRate } from '../hooks/useExchangeRate';

const AUTH_KEYCHAIN_SERVICE = 'com.confio.auth';
const AUTH_KEYCHAIN_USERNAME = 'auth_tokens';
const PREFERENCES_KEYCHAIN_SERVICE = 'com.confio.preferences';
const BALANCE_VISIBILITY_KEY = 'balance_visibility';

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
  const { signOut, userProfile } = useAuth();
  const { userCountry, selectedCountry } = useCountry();
  const { currency, formatAmount, exchangeRate } = useCurrency();
  const { rate: marketRate, loading: rateLoading } = useSelectedCountryRate();
  const [suiAddress, setSuiAddress] = React.useState<string>('');
  // Show local currency by default if not in US and rate is available
  const [showLocalCurrency, setShowLocalCurrency] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [showBalance, setShowBalance] = useState(true);
  
  // Animation values
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
  } = useAccount();
  
  // Use atomic account switching
  const { 
    switchAccount: atomicSwitchAccount, 
    state: switchState, 
    isAccountSwitchInProgress 
  } = useAtomicAccountSwitch();
  
  // Fetch real balances - use no-cache to ensure we always get the correct account balance
  const { data: cUSDBalanceData, loading: cUSDLoading, error: cUSDError, refetch: refetchCUSD } = useQuery(GET_ACCOUNT_BALANCE, {
    variables: { tokenType: 'cUSD' },
    fetchPolicy: 'no-cache', // Completely bypass cache to ensure correct account context
  });
  
  const { data: confioBalanceData, loading: confioLoading, error: confioError, refetch: refetchConfio } = useQuery(GET_ACCOUNT_BALANCE, {
    variables: { tokenType: 'CONFIO' },
    fetchPolicy: 'no-cache', // Completely bypass cache to ensure correct account context
  });
  
  // Check if presale is globally active
  const { data: presaleStatusData } = useQuery(GET_PRESALE_STATUS, {
    fetchPolicy: 'cache-and-network',
  });
  const isPresaleActive = presaleStatusData?.isPresaleActive === true;
  
  // Refetch balances when active account changes
  useEffect(() => {
    if (activeAccount) {
      refetchCUSD();
      refetchConfio();
    }
  }, [activeAccount?.id, activeAccount?.type, activeAccount?.index, refetchCUSD, refetchConfio]);

  // Force refresh balances when navigating to this screen
  useFocusEffect(
    useCallback(() => {
      console.log('HomeScreen focused - refreshing balances');
      refetchCUSD();
      refetchConfio();
    }, [refetchCUSD, refetchConfio])
  );
  
  // Log any errors and data for debugging
  useEffect(() => {
    console.log('Balance query status:', {
      isInitialized,
      cUSDLoading,
      confioLoading,
      cUSDData: cUSDBalanceData,
      confioData: confioBalanceData,
      cUSDError: cUSDError?.message,
      confioError: confioError?.message,
    });
    
    if (cUSDError) {
      console.error('Error fetching cUSD balance:', cUSDError);
    }
    if (confioError) {
      console.error('Error fetching CONFIO balance:', confioError);
    }
    if (cUSDBalanceData) {
      console.log('cUSD balance data:', cUSDBalanceData);
    }
    if (confioBalanceData) {
      console.log('CONFIO balance data:', confioBalanceData);
    }
  }, [isInitialized, cUSDLoading, confioLoading, cUSDError, confioError, cUSDBalanceData, confioBalanceData]);
  
  // Parse balances safely - memoized for performance
  const cUSDBalance = React.useMemo(() => 
    parseFloat(cUSDBalanceData?.accountBalance || '0'), 
    [cUSDBalanceData?.accountBalance]
  );
  const confioBalance = React.useMemo(() => 
    parseFloat(confioBalanceData?.accountBalance || '0'), 
    [confioBalanceData?.accountBalance]
  );
  
  // Calculate portfolio value - Only include cUSD for now
  // CONFIO value is not determined yet
  const totalUSDValue = cUSDBalance;
  
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
  
  // Track initialization state
  const [isInitialized, setIsInitialized] = useState(false);
  
  // Only show loading on very first load
  const isLoading = !isInitialized && accountsLoading;
  
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

  // Only use stored accounts - no mock accounts
  const displayAccounts = accountMenuItems;

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
    currentAccountIndex: currentAccount?.id ? currentAccount.id.split('_')[1] : undefined,
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
      await Promise.all([
        refreshAccounts(),
        refetchCUSD(),
        refetchConfio(),
      ]);
    } catch (error) {
      console.error('Error refreshing data:', error);
    } finally {
      setRefreshing(false);
    }
  }, [refreshAccounts, refetchCUSD, refetchConfio]);
  
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
      label: 'Intercambio',
      icon: 'refresh-cw',
      color: '#3b82f6',
      route: () => navigation.navigate('BottomTabs', { screen: 'Exchange' }),
    },
  ];
  
  // Filter quick actions based on employee permissions
  const quickActions = React.useMemo(() => {
    // If user is an employee, filter actions based on permissions
    if (activeAccount?.isEmployee) {
      const permissions = activeAccount.employeePermissions || {};
      
      return quickActionsData.filter(action => {
        switch (action.id) {
          case 'send':
            // Employees can't send funds
            return permissions.sendFunds === true;
          case 'receive':
            // Employees can receive if they can accept payments
            return permissions.acceptPayments === true;
          case 'pay':
            // Employees need sendFunds permission to pay
            return permissions.sendFunds === true;
          case 'exchange':
            // Employees need manageP2p permission
            return permissions.manageP2p === true;
          default:
            return true;
        }
      });
    }
    
    // Non-employees get all actions
    return quickActionsData;
  }, [activeAccount, quickActionsData]);

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

  // Combined initialization effect
  React.useEffect(() => {
    let mounted = true;
    
    const initializeHomeScreen = async () => {
      if (!mounted) return;
      
      try {
        // Load balance visibility preference first
        await loadBalanceVisibility();
        
        // Initialize auth service
        const authService = AuthService.getInstance();
        await authService.initialize();
        
        if (!mounted) return;
        
        const address = await authService.getZkLoginAddress();
        setSuiAddress(address);
        
      } catch (error) {
        console.error('HomeScreen - Error during initialization:', error);
      } finally {
        if (mounted) {
          // Mark as initialized after a small delay to prevent flash
          setTimeout(() => {
            if (mounted) {
              setIsInitialized(true);
            }
          }, 100);
        }
      }
    };

    initializeHomeScreen();
    
    return () => {
      mounted = false;
    };
  }, []);

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
      accountAddress: activeAccount?.suiAddress || ''
    });
  }, [navigation, cUSDBalance, activeAccount?.suiAddress]);

  const navigateToConfioAccount = useCallback(() => {
    navigation.navigate('AccountDetail', { 
      accountType: 'confio',
      accountName: 'Confío',
      accountSymbol: '$CONFIO',
      accountBalance: confioBalance.toFixed(2),
      accountAddress: activeAccount?.suiAddress || ''
    });
  }, [navigation, confioBalance, activeAccount?.suiAddress]);
  
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

  const handleAccountSwitch = async (accountId: string) => {
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
          refetchCUSD(),
          refetchConfio(),
        ]);
      } else {
        console.log('HomeScreen - Account switch failed');
      }
    } catch (error) {
      console.error('Error switching account:', error);
      Alert.alert(
        'Error',
        'No se pudo cambiar la cuenta. Por favor intenta nuevamente.',
        [{ text: 'OK' }]
      );
    }
  };

  const handleCreateBusinessAccount = () => {
    profileMenu.closeProfileMenu();
    // Navigate to business account creation screen
    navigation.navigate('CreateBusiness');
  };

  // Check for pending account switch from push notification
  useFocusEffect(
    useCallback(() => {
      const pendingSwitch = PushNotificationService.getPendingAccountSwitch();
      if (pendingSwitch && handleAccountSwitch) {
        console.log('HomeScreen - Found pending account switch:', pendingSwitch);
        PushNotificationService.clearPendingAccountSwitch();
        
        // Use the existing handleAccountSwitch function with delay
        setTimeout(() => {
          handleAccountSwitch(pendingSwitch);
        }, 1000); // Delay to ensure UI is ready and avoid conflicts
      }
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
                      ? formatAmount.plain(totalLocalValue)
                      : totalUSDValue.toLocaleString('en-US', { 
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2 
                        })
                    )
                  : '••••••';
              })()}
            </Text>
          </Animated.View>
        </Animated.View>
        
        {/* CONFIO Presale Banner - Only show if presale is active */}
        {isPresaleActive && (
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
          <TouchableOpacity 
            style={styles.presaleBannerContent}
            onPress={() => navigation.navigate('ConfioPresale')}
            activeOpacity={0.9}
          >
            <View style={styles.presaleBannerLeft}>
              <View style={styles.presaleBadge}>
                <Text style={styles.presaleBadgeText}>🚀 PREVENTA</Text>
              </View>
              <Text style={styles.presaleBannerTitle}>Únete a la Preventa de $CONFIO</Text>
              <Text style={styles.presaleBannerSubtitle}>
                Sé de los primeros en obtener monedas $CONFIO antes del lanzamiento público
              </Text>
            </View>
            <View style={styles.presaleBannerRight}>
              <Image source={CONFIOLogo} style={styles.presaleBannerLogo} />
              <Icon name="chevron-right" size={20} color="#8b5cf6" />
            </View>
          </TouchableOpacity>
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
                  <Icon name={action.icon} size={22} color="#fff" />
                </Animated.View>
                <Text style={styles.actionLabel}>{action.label}</Text>
              </TouchableOpacity>
            ))
          )}
        </Animated.View>

        {/* Wallets Section */}
        <View style={styles.walletsSection}>
          <Text style={styles.walletsTitle}>Mis Billeteras</Text>
          
          {cUSDLoading || confioLoading ? (
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
                        : showBalance ? `$${cUSDBalance.toFixed(2)}` : '••••'}
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
                        : showBalance ? confioBalance.toFixed(2) : '••••'}
                    </Text>
                    <Icon name="chevron-right" size={20} color="#9ca3af" />
                  </View>
                </View>
              </Pressable>
            </Animated.View>
          )}
        </View>
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