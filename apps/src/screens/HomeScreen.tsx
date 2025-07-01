import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Platform, Alert, ScrollView, Image } from 'react-native';
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
import { useAccountManager } from '../hooks/useAccountManager';

const AUTH_KEYCHAIN_SERVICE = 'com.confio.auth';
const AUTH_KEYCHAIN_USERNAME = 'auth_tokens';

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

export const HomeScreen = () => {
  const navigation = useNavigation<HomeScreenNavigationProp>();
  const { setCurrentAccountAvatar, profileMenu } = useHeader();
  const { signOut } = useAuth();
  const [suiAddress, setSuiAddress] = React.useState<string>('');
  const [showLocalCurrency, setShowLocalCurrency] = useState(false);
  
  // Use account manager hook
  const {
    activeAccount,
    accounts,
    isLoading: accountsLoading,
    switchAccount,
    createAccount,
    refreshAccounts,
  } = useAccountManager();
  
  // Only show loading for initial data load, not for account loading
  const isLoading = false; // accountsLoading;
  
  // Debug initial state
  console.log('HomeScreen initial render:', { 
    showProfileMenu: profileMenu.showProfileMenu, 
    activeAccount: activeAccount?.id,
    activeAccountType: activeAccount?.type,
    activeAccountIndex: activeAccount?.index,
    accountsCount: accounts.length,
    accounts: accounts,
    isLoading: accountsLoading
  });
  
  // Fallback to mock accounts if no stored accounts exist
  const mockAccounts: Account[] = [
    { 
      id: "personal", 
      name: "Julian Moon", 
      type: "personal", 
      phone: "+58 412 345 6789",
      avatar: "J"
    },
    { 
      id: "restaurant", 
      name: "El Sabor de Chicha", 
      type: "business", 
      category: "Restaurante",
      avatar: "E"
    },
    { 
      id: "consulting", 
      name: "Novio coreano 🤭", 
      type: "business", 
      category: "Consultoria",
      avatar: "N"
    }
  ];

  // Convert stored accounts to the format expected by ProfileMenu
  const accountMenuItems = accounts.map(acc => ({
    id: acc.id,
    name: acc.name,
    type: acc.type,
    phone: acc.phone,
    category: acc.category,
    avatar: acc.avatar,
  }));

  // Only use stored accounts - no mock accounts
  const displayAccounts = accountMenuItems;

  const currentAccount = activeAccount ? {
    id: activeAccount.id,
    name: activeAccount.name,
    type: activeAccount.type,
    phone: activeAccount.phone,
    category: activeAccount.category,
    avatar: activeAccount.avatar,
  } : (displayAccounts.length > 0 ? displayAccounts[0] : null); // Only use first account if accounts exist
  
  // Debug display accounts
  console.log('HomeScreen - Display accounts:', {
    accountsLength: accounts.length,
    accountMenuItemsLength: accountMenuItems.length,
    displayAccountsLength: displayAccounts.length,
    displayAccounts: displayAccounts,
    usingMockAccounts: accounts.length === 0,
    currentAccountType: currentAccount?.type,
    currentAccountIndex: currentAccount?.id ? currentAccount.id.split('_')[1] : undefined,
    activeAccountId: activeAccount?.id,
    activeAccountType: activeAccount?.type,
    activeAccountIndex: activeAccount?.index
  });

  // Mock balances - replace with real data later
  const mockBalances = {
    cusd: "3,542.75",
    confio: "234.18"
  };

  // Mock exchange rates - replace with real data later
  const mockLocalCurrency = {
    name: "Bolívares",
    rate: 35.5,
    symbol: "Bs."
  };

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

  // Update header when account changes
  useEffect(() => {
    if (currentAccount) {
      setCurrentAccountAvatar(currentAccount.avatar);
    }
  }, [currentAccount, setCurrentAccountAvatar]);

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
      
      // Check if this is a mock account (not stored in our system)
      const isMockAccount = mockAccounts.some(acc => acc.id === accountId);
      
      console.log('HomeScreen - Account type check:', {
        accountId: accountId,
        isMockAccount: isMockAccount,
        mockAccountIds: mockAccounts.map(acc => acc.id),
        storedAccountIds: accounts.map(acc => acc.id)
      });
      
      if (isMockAccount) {
        // For mock accounts, just close the menu (no actual switching)
        console.log('HomeScreen - Mock account selected:', accountId);
        profileMenu.closeProfileMenu();
      } else {
        // For real accounts, perform the actual switch
        console.log('HomeScreen - Real account selected, switching to:', accountId);
        await switchAccount(accountId);
        profileMenu.closeProfileMenu();
      }
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
    <View style={{ flex: 1, backgroundColor: '#F3F4F6' }}>
      {/* Balance Card Section - mint background, rounded bottom border */}
      <View style={{
        backgroundColor: '#34d399',
        paddingTop: 12,
        paddingBottom: 32,
        paddingHorizontal: 20,
        borderBottomLeftRadius: 32,
        borderBottomRightRadius: 32,
      }}>
        <Text style={{ fontSize: 15, color: '#fff', opacity: 0.8 }}>Tu saldo en:</Text>
        <Text style={{ fontSize: 15, color: '#fff', opacity: 0.8, marginBottom: 4 }}>Dólares estadounidenses</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Text style={{ fontSize: 32, fontWeight: 'bold', color: '#fff' }}>${mockBalances.cusd}</Text>
          <TouchableOpacity style={{
            marginLeft: 8,
            backgroundColor: 'rgba(255,255,255,0.2)',
            borderRadius: 16,
            paddingHorizontal: 12,
            paddingVertical: 4,
          }}>
            <Text style={{ color: '#fff', fontSize: 12 }}>Ver en Bs. 5.000.000,00</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Wallets Section - light grey background */}
      <ScrollView style={{ flex: 1, backgroundColor: '#F3F4F6' }} contentContainerStyle={{ paddingHorizontal: 0 }} showsHorizontalScrollIndicator={false}>
        
        <View style={styles.walletsHeader}>
          <Text style={styles.walletsTitle}>Mis Cuentas</Text>
        </View>
        <View style={{ ...styles.walletsContainer, width: '100%' }}>
          <View style={{ ...styles.walletCard, width: '100%' }}>
            <TouchableOpacity 
              style={styles.walletCardContent}
              onPress={() => navigation.navigate('AccountDetail', { 
                accountType: 'cusd',
                accountName: 'Confío Dollar',
                accountSymbol: '$cUSD',
                accountBalance: mockBalances.cusd
              })}
            >
              <View style={styles.walletLogoContainer}>
                <Image source={cUSDLogo} style={styles.walletLogo} />
              </View>
              <View style={styles.walletInfo}>
                <Text style={styles.walletName}>Confío Dollar</Text>
                <Text style={styles.walletSymbol}>$cUSD</Text>
              </View>
              <View style={styles.walletBalance}>
                <Text style={styles.walletBalanceText}>${mockBalances.cusd}</Text>
              </View>
            </TouchableOpacity>
          </View>
          <View style={{ ...styles.walletCard, width: '100%' }}>
            <TouchableOpacity 
              style={styles.walletCardContent}
              onPress={() => navigation.navigate('AccountDetail', { 
                accountType: 'confio',
                accountName: 'Confío',
                accountSymbol: '$CONFIO',
                accountBalance: mockBalances.confio
              })}
            >
              <View style={styles.walletLogoContainer}>
                <Image source={CONFIOLogo} style={styles.walletLogo} />
              </View>
              <View style={styles.walletInfo}>
                <Text style={styles.walletName}>Confío</Text>
                <Text style={styles.walletSymbol}>$CONFIO</Text>
              </View>
              <View style={styles.walletBalance}>
                <Text style={styles.walletBalanceText}>{mockBalances.confio}</Text>
              </View>
            </TouchableOpacity>
          </View>
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
    backgroundColor: '#F3F4F6',
  },
  header: {
    paddingTop: 56,
    paddingBottom: 32,
    paddingHorizontal: 20,
    borderBottomLeftRadius: 32,
    borderBottomRightRadius: 32,
    width: '100%',
  },
  headerInner: {
    paddingTop: 56,
    paddingBottom: 32,
    paddingHorizontal: 20,
  },
  balanceSection: {
    marginTop: 8,
  },
  balanceLabel: {
    fontSize: 15,
    color: '#FFFFFF',
    opacity: 0.8,
  },
  balanceSubLabel: {
    fontSize: 15,
    color: '#FFFFFF',
    opacity: 0.8,
    marginTop: 4,
  },
  balanceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 8,
    width: '100%',
  },
  balanceAmount: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#FFFFFF',
  },
  currencyToggle: {
    marginLeft: 12,
    backgroundColor: 'rgba(255,255,255,0.2)',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    flexShrink: 1,
    maxWidth: 140,
  },
  currencyToggleText: {
    color: '#FFFFFF',
    fontSize: 12,
  },
  content: {
    flex: 1,
  },
  walletsHeader: {
    paddingHorizontal: 20,
    paddingVertical: 16,
  },
  walletsTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  walletsContainer: {
    paddingHorizontal: 12,
  },
  walletCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F8FAFC',
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
  },
  walletLogoContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    marginRight: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  walletLogo: {
    width: 40,
    height: 40,
    borderRadius: 20,
  },
  walletInfo: {
    flex: 1,
  },
  walletName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  walletSymbol: {
    fontSize: 13,
    color: '#64748B',
    marginTop: 2,
  },
  walletBalance: {
    alignItems: 'flex-end',
  },
  walletBalanceText: {
    fontSize: 17,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  loadingText: {
    color: '#fff',
    fontSize: 18,
    textAlign: 'center',
    marginTop: 40,
  },
  walletCardContent: {
    flexDirection: 'row',
    alignItems: 'center',
    width: '100%',
  },
}); 