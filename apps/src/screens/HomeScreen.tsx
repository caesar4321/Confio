import React, { useState, useEffect, useCallback, useRef } from 'react';
import { 
  View, 
  Text, 
  StyleSheet, 
  TouchableOpacity, 
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
import { useNavigation, useFocusEffect } from '@react-navigation/native';
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
import { getCountryByIso } from '../utils/countries';
import { WalletCardSkeleton } from '../components/SkeletonLoader';
import { useQuery } from '@apollo/client';
import { GET_ACCOUNT_BALANCE } from '../apollo/queries';

const AUTH_KEYCHAIN_SERVICE = 'com.confio.auth';
const AUTH_KEYCHAIN_USERNAME = 'auth_tokens';

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
  const { setCurrentAccountAvatar, profileMenu } = useHeader();
  const { signOut, userProfile } = useAuth();
  const [suiAddress, setSuiAddress] = React.useState<string>('');
  const [showLocalCurrency, setShowLocalCurrency] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  
  // Animation values
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const scaleAnim = useRef(new Animated.Value(0.95)).current;
  const balanceAnim = useRef(new Animated.Value(0)).current;
  
  // Use account context
  const {
    activeAccount,
    accounts,
    isLoading: accountsLoading,
    switchAccount,
    createAccount,
    refreshAccounts,
  } = useAccount();
  
  // Fetch real balances
  const { data: cUSDBalanceData, loading: cUSDLoading, refetch: refetchCUSD } = useQuery(GET_ACCOUNT_BALANCE, {
    variables: { tokenType: 'cUSD' },
    fetchPolicy: 'cache-and-network',
  });
  
  const { data: confioBalanceData, loading: confioLoading, refetch: refetchConfio } = useQuery(GET_ACCOUNT_BALANCE, {
    variables: { tokenType: 'CONFIO' },
    fetchPolicy: 'cache-and-network',
  });
  
  // Parse balances safely
  const cUSDBalance = parseFloat(cUSDBalanceData?.accountBalance || '0');
  const confioBalance = parseFloat(confioBalanceData?.accountBalance || '0');
  
  // Calculate portfolio value - Only include cUSD for now
  // CONFIO value is not determined yet
  const totalUSDValue = cUSDBalance;
  const localExchangeRate = 35.5; // TODO: Fetch real VES rate
  const totalLocalValue = totalUSDValue * localExchangeRate;
  
  // Only show loading for initial data load
  const isLoading = accountsLoading && !accounts.length;
  
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
  
  // Quick actions configuration
  const quickActions: QuickAction[] = [
    {
      id: 'send',
      label: 'Enviar',
      icon: 'send',
      color: '#10b981',
      route: () => navigation.navigate('BottomTabs', { screen: 'Contacts' }),
    },
    {
      id: 'receive',
      label: 'Recibir',
      icon: 'download',
      color: '#10b981',
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

  // Entrance animation
  React.useEffect(() => {
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
  }, [fadeAnim, scaleAnim]);
  
  // Balance animation when value changes
  React.useEffect(() => {
    Animated.timing(balanceAnim, {
      toValue: showLocalCurrency ? 1 : 0,
      duration: 300,
      useNativeDriver: true,
    }).start();
  }, [showLocalCurrency, balanceAnim]);

  React.useEffect(() => {
    console.log('HomeScreen - useEffect triggered for data loading');
    
    const loadData = async () => {
      try {
        console.log('HomeScreen - Starting data load');
        const authService = AuthService.getInstance();
        
        console.log('HomeScreen - Got AuthService instance, calling initialize');
        
        // Ensure AuthService is initialized
        await authService.initialize();
        
        console.log('HomeScreen - AuthService initialized, getting zkLogin address');
        
        const address = await authService.getZkLoginAddress();
        setSuiAddress(address);
        
        console.log('HomeScreen - Data load completed, address:', address);
      } catch (error) {
        console.error('HomeScreen - Error loading data:', error);
      }
    };

    loadData();
  }, []);

  // Add a simple useEffect to test if useEffect is working at all
  React.useEffect(() => {
    console.log('HomeScreen - Component mounted');
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

  // Refresh accounts when screen comes into focus (e.g., after creating a business account)
  useFocusEffect(
    React.useCallback(() => {
      console.log('HomeScreen - Screen focused, refreshing accounts');
      refreshAccounts();
    }, [refreshAccounts])
  );

  const handleAccountSwitch = async (accountId: string) => {
    try {
      console.log('HomeScreen - handleAccountSwitch called with:', accountId);
      
      // All accounts are now real accounts from the server
      console.log('HomeScreen - Switching to account:', accountId);
      await switchAccount(accountId);
      profileMenu.closeProfileMenu();
    } catch (error) {
      console.error('Error switching account:', error);
    }
  };

  const handleCreateBusinessAccount = () => {
    profileMenu.closeProfileMenu();
    // Navigate to business account creation screen
    navigation.navigate('CreateBusiness');
  };



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
                {showLocalCurrency ? 'En Bolívares Venezolanos' : 'En Dólares Estadounidenses'}
              </Text>
            </View>
            <TouchableOpacity 
              style={styles.currencyToggle}
              onPress={() => setShowLocalCurrency(!showLocalCurrency)}
              activeOpacity={0.7}
            >
              <Text style={styles.currencyToggleText}>
                {showLocalCurrency ? 'Bs.' : 'USD'}
              </Text>
              <Icon name="chevron-down" size={14} color="#fff" />
            </TouchableOpacity>
          </View>
          
          <Animated.View 
            style={[
              styles.balanceContainer,
              {
                opacity: balanceAnim.interpolate({
                  inputRange: [0, 1],
                  outputRange: [1, 0.3],
                }),
              }
            ]}
          >
            <Text style={styles.currencySymbol}>
              {showLocalCurrency ? 'Bs.' : '$'}
            </Text>
            <Text style={styles.balanceAmount}>
              {showLocalCurrency 
                ? totalLocalValue.toLocaleString('es-VE', { 
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2 
                  })
                : totalUSDValue.toLocaleString('en-US', { 
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2 
                  })
              }
            </Text>
          </Animated.View>
          
          {/* Portfolio change indicator */}
          <View style={styles.changeContainer}>
            <Icon name="trending-up" size={16} color="#10f981" />
            <Text style={styles.changeText}>+2.5% hoy</Text>
          </View>
        </Animated.View>
        
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
          {quickActions.map((action, index) => (
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
          ))}
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
              <TouchableOpacity 
                style={styles.walletCard}
                onPress={() => navigation.navigate('AccountDetail', { 
                  accountType: 'cusd',
                  accountName: 'Confío Dollar',
                  accountSymbol: '$cUSD',
                  accountBalance: cUSDBalance.toFixed(2),
                  accountAddress: activeAccount?.suiAddress || ''
                })}
                activeOpacity={0.7}
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
                      ${cUSDBalance.toFixed(2)}
                    </Text>
                    <Icon name="chevron-right" size={20} color="#9ca3af" />
                  </View>
                </View>
              </TouchableOpacity>

              {/* CONFIO Wallet */}
              <TouchableOpacity 
                style={styles.walletCard}
                onPress={() => navigation.navigate('AccountDetail', { 
                  accountType: 'confio',
                  accountName: 'Confío',
                  accountSymbol: '$CONFIO',
                  accountBalance: confioBalance.toFixed(2),
                  accountAddress: activeAccount?.suiAddress || ''
                })}
                activeOpacity={0.7}
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
                      {confioBalance.toFixed(2)}
                    </Text>
                    <Icon name="chevron-right" size={20} color="#9ca3af" />
                  </View>
                </View>
              </TouchableOpacity>
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
  changeContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  changeText: {
    color: 'rgba(255,255,255,0.9)',
    fontSize: 14,
    marginLeft: 6,
    fontWeight: '500',
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