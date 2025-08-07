import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  RefreshControl,
  ActivityIndicator,
  Animated,
  Dimensions,
} from 'react-native';
import { useNavigation, useFocusEffect, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import Icon from 'react-native-vector-icons/Feather';
import { useAuth } from '../contexts/AuthContext';
import { useAccount } from '../contexts/AccountContext';
import { ProfileMenu } from '../components/ProfileMenu';
import { useQuery } from '@apollo/client';
import { GET_ACCOUNT_BALANCE } from '../apollo/queries';

const { width: screenWidth } = Dimensions.get('window');

type HomeScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

interface QuickAction {
  id: string;
  label: string;
  icon: string;
  color: string;
  onPress: () => void;
}

interface RecentTransaction {
  id: string;
  type: 'sent' | 'received' | 'payment' | 'exchange';
  amount: string;
  currency: string;
  counterparty: string;
  timestamp: string;
}

export const HomeScreenEnhanced = () => {
  const navigation = useNavigation<HomeScreenNavigationProp>();
  const route = useRoute<any>();
  const { userProfile } = useAuth();
  const { activeAccount, accounts, refreshAccounts } = useAccount();
  const [refreshing, setRefreshing] = useState(false);
  const [showLocalCurrency, setShowLocalCurrency] = useState(false);
  const fadeAnim = useCallback(() => new Animated.Value(0), []);
  
  // Fetch real balances - use no-cache to ensure we always get the correct account balance
  const { data: cUSDBalance, refetch: refetchCUSD } = useQuery(GET_ACCOUNT_BALANCE, {
    variables: { tokenType: 'cUSD' },
    fetchPolicy: 'no-cache', // Completely bypass cache to ensure correct account context
  });
  
  const { data: confioBalance, refetch: refetchConfio } = useQuery(GET_ACCOUNT_BALANCE, {
    variables: { tokenType: 'CONFIO' },
    fetchPolicy: 'no-cache', // Completely bypass cache to ensure correct account context
  });

  // Refetch balances when active account changes
  useEffect(() => {
    if (activeAccount) {
      refetchCUSD();
      refetchConfio();
    }
  }, [activeAccount?.id, activeAccount?.type, activeAccount?.index, refetchCUSD, refetchConfio]);

  // Handle navigation params for auto-navigation after conversion
  useEffect(() => {
    const shouldNavigateToAccount = route.params?.shouldNavigateToAccount;
    const refreshTimestamp = route.params?.refreshTimestamp;
    
    if (refreshTimestamp) {
      // Refresh balances when coming back from conversion
      refetchCUSD();
      refetchConfio();
    }
    
    if (shouldNavigateToAccount && cUSDBalance && confioBalance) {
      // Clear the params to prevent re-navigation
      navigation.setParams({ shouldNavigateToAccount: undefined, refreshTimestamp: undefined });
      
      // Navigate to the requested account detail
      if (shouldNavigateToAccount === 'cusd') {
        navigation.navigate('AccountDetail', {
          accountType: 'cusd',
          accountName: 'Confío Dollar',
          accountSymbol: '$cUSD',
          accountBalance: cUSDBalance?.accountBalance || '0',
          accountAddress: activeAccount?.aptosAddress || '',
        });
      } else if (shouldNavigateToAccount === 'confio') {
        navigation.navigate('AccountDetail', {
          accountType: 'confio',
          accountName: 'Confío',
          accountSymbol: '$CONFIO',
          accountBalance: confioBalance?.accountBalance || '0',
          accountAddress: activeAccount?.aptosAddress || '',
        });
      }
    }
  }, [route.params, cUSDBalance, confioBalance, navigation, activeAccount]);

  // Calculate total portfolio value
  const calculateTotalValue = () => {
    const cusd = parseFloat(cUSDBalance?.accountBalance || '0');
    const confio = parseFloat(confioBalance?.accountBalance || '0');
    const confioRate = 0.1; // Mock rate - replace with real exchange rate
    return cusd + (confio * confioRate);
  };

  const totalValue = calculateTotalValue();
  const localRate = 35.5; // Mock VES rate
  const localValue = totalValue * localRate;

  // Pull to refresh handler
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await Promise.all([
        refreshAccounts(),
        refetchCUSD(),
        refetchConfio(),
      ]);
    } catch (error) {
      console.error('Error refreshing:', error);
    } finally {
      setRefreshing(false);
    }
  }, [refreshAccounts, refetchCUSD, refetchConfio]);

  // Quick actions
  const quickActions: QuickAction[] = [
    {
      id: 'send',
      label: 'Enviar',
      icon: 'send',
      color: '#10b981',
      onPress: () => navigation.navigate('BottomTabs', { screen: 'Contacts' }),
    },
    {
      id: 'receive',
      label: 'Recibir',
      icon: 'download',
      color: '#3b82f6',
      onPress: () => navigation.navigate('ConfioAddress'),
    },
    {
      id: 'exchange',
      label: 'Intercambiar',
      icon: 'refresh-cw',
      color: '#8b5cf6',
      onPress: () => navigation.navigate('BottomTabs', { screen: 'Exchange' }),
    },
    {
      id: 'pay',
      label: 'Pagar',
      icon: 'shopping-bag',
      color: '#f59e0b',
      onPress: () => navigation.navigate('BottomTabs', { screen: 'Scan' }),
    },
  ];

  // Mock recent transactions - replace with real data
  const recentTransactions: RecentTransaction[] = [
    {
      id: '1',
      type: 'sent',
      amount: '-50.00',
      currency: 'cUSD',
      counterparty: 'Maria Garcia',
      timestamp: 'Hace 2 horas',
    },
    {
      id: '2',
      type: 'received',
      amount: '+125.50',
      currency: 'cUSD',
      counterparty: 'Juan Perez',
      timestamp: 'Ayer',
    },
    {
      id: '3',
      type: 'payment',
      amount: '-15.00',
      currency: 'cUSD',
      counterparty: 'Café Central',
      timestamp: 'Hace 2 días',
    },
  ];

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
            colors={['#10b981']}
          />
        }
        showsVerticalScrollIndicator={false}
      >
        {/* Enhanced Balance Card */}
        <View style={styles.balanceCard}>
          <View style={styles.balanceHeader}>
            <Text style={styles.balanceLabel}>Valor total del portafolio</Text>
            <TouchableOpacity
              style={styles.currencyToggle}
              onPress={() => setShowLocalCurrency(!showLocalCurrency)}
            >
              <Text style={styles.currencyToggleText}>
                {showLocalCurrency ? 'USD' : 'VES'}
              </Text>
              <Icon name="chevron-down" size={12} color="#fff" />
            </TouchableOpacity>
          </View>
          
          <Animated.View style={styles.balanceAmount}>
            <Text style={styles.currencySymbol}>
              {showLocalCurrency ? 'Bs.' : '$'}
            </Text>
            <Text style={styles.amount}>
              {showLocalCurrency 
                ? localValue.toLocaleString('es-VE', { minimumFractionDigits: 2 })
                : totalValue.toLocaleString('en-US', { minimumFractionDigits: 2 })
              }
            </Text>
          </Animated.View>
          
          <View style={styles.balanceChange}>
            <Icon name="trending-up" size={14} color="#10b981" />
            <Text style={styles.changeText}>+2.5% hoy</Text>
          </View>
        </View>

        {/* Quick Actions */}
        <View style={styles.quickActions}>
          {quickActions.map((action) => (
            <TouchableOpacity
              key={action.id}
              style={styles.actionButton}
              onPress={action.onPress}
              activeOpacity={0.7}
            >
              <View style={[styles.actionIcon, { backgroundColor: action.color }]}>
                <Icon name={action.icon} size={22} color="#fff" />
              </View>
              <Text style={styles.actionLabel}>{action.label}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* Wallet Cards */}
        <View style={styles.walletsSection}>
          <Text style={styles.sectionTitle}>Mis Billeteras</Text>
          
          <TouchableOpacity
            style={styles.walletCard}
            onPress={() => navigation.navigate('AccountDetail', {
              accountType: 'cusd',
              accountName: 'Confío Dollar',
              accountSymbol: '$cUSD',
              accountBalance: cUSDBalance?.accountBalance || '0',
              accountAddress: activeAccount?.aptosAddress || '',
            })}
            activeOpacity={0.7}
          >
            <View style={styles.walletInfo}>
              <View style={styles.walletIcon}>
                <Text style={styles.walletIconText}>$</Text>
              </View>
              <View style={styles.walletDetails}>
                <Text style={styles.walletName}>Confío Dollar</Text>
                <Text style={styles.walletSymbol}>cUSD</Text>
              </View>
            </View>
            <View style={styles.walletBalance}>
              <Text style={styles.walletAmount}>
                ${cUSDBalance?.accountBalance || '0'}
              </Text>
              <Icon name="chevron-right" size={20} color="#9ca3af" />
            </View>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.walletCard}
            onPress={() => navigation.navigate('AccountDetail', {
              accountType: 'confio',
              accountName: 'Confío',
              accountSymbol: '$CONFIO',
              accountBalance: confioBalance?.accountBalance || '0',
              accountAddress: activeAccount?.aptosAddress || '',
            })}
            activeOpacity={0.7}
          >
            <View style={styles.walletInfo}>
              <View style={[styles.walletIcon, { backgroundColor: '#8b5cf6' }]}>
                <Text style={styles.walletIconText}>C</Text>
              </View>
              <View style={styles.walletDetails}>
                <Text style={styles.walletName}>Confío</Text>
                <Text style={styles.walletSymbol}>CONFIO</Text>
              </View>
            </View>
            <View style={styles.walletBalance}>
              <Text style={styles.walletAmount}>
                {confioBalance?.accountBalance || '0'}
              </Text>
              <Icon name="chevron-right" size={20} color="#9ca3af" />
            </View>
          </TouchableOpacity>
        </View>

        {/* Recent Activity */}
        <View style={styles.recentSection}>
          <View style={styles.recentHeader}>
            <Text style={styles.sectionTitle}>Actividad Reciente</Text>
            <TouchableOpacity>
              <Text style={styles.viewAllText}>Ver todo</Text>
            </TouchableOpacity>
          </View>
          
          {recentTransactions.map((tx) => (
            <TouchableOpacity
              key={tx.id}
              style={styles.transactionItem}
              activeOpacity={0.7}
            >
              <View style={styles.transactionIcon}>
                <Icon
                  name={tx.type === 'sent' ? 'arrow-up-right' : 
                        tx.type === 'received' ? 'arrow-down-left' :
                        tx.type === 'payment' ? 'shopping-bag' : 'refresh-cw'}
                  size={20}
                  color={tx.amount.startsWith('-') ? '#ef4444' : '#10b981'}
                />
              </View>
              <View style={styles.transactionDetails}>
                <Text style={styles.transactionName}>{tx.counterparty}</Text>
                <Text style={styles.transactionTime}>{tx.timestamp}</Text>
              </View>
              <Text style={[
                styles.transactionAmount,
                { color: tx.amount.startsWith('-') ? '#ef4444' : '#10b981' }
              ]}>
                {tx.amount} {tx.currency}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      </ScrollView>
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
  balanceCard: {
    backgroundColor: '#10b981',
    paddingTop: 20,
    paddingBottom: 30,
    paddingHorizontal: 20,
    borderBottomLeftRadius: 32,
    borderBottomRightRadius: 32,
  },
  balanceHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  balanceLabel: {
    fontSize: 16,
    color: 'rgba(255,255,255,0.9)',
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
  balanceAmount: {
    flexDirection: 'row',
    alignItems: 'baseline',
    marginBottom: 8,
  },
  currencySymbol: {
    fontSize: 24,
    color: '#fff',
    marginRight: 4,
  },
  amount: {
    fontSize: 40,
    fontWeight: 'bold',
    color: '#fff',
  },
  balanceChange: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  changeText: {
    color: 'rgba(255,255,255,0.9)',
    fontSize: 14,
    marginLeft: 4,
  },
  quickActions: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    paddingHorizontal: 20,
    paddingVertical: 20,
    marginTop: -15,
    backgroundColor: '#fff',
    marginHorizontal: 20,
    borderRadius: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 3,
  },
  actionButton: {
    alignItems: 'center',
  },
  actionIcon: {
    width: 50,
    height: 50,
    borderRadius: 25,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 8,
  },
  actionLabel: {
    fontSize: 13,
    color: '#374151',
    fontWeight: '500',
  },
  walletsSection: {
    paddingHorizontal: 20,
    marginTop: 24,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#111827',
    marginBottom: 16,
  },
  walletCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.03,
    shadowRadius: 4,
    elevation: 2,
  },
  walletInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  walletIcon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#10b981',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  walletIconText: {
    color: '#fff',
    fontSize: 20,
    fontWeight: 'bold',
  },
  walletDetails: {
    justifyContent: 'center',
  },
  walletName: {
    fontSize: 16,
    fontWeight: '600',
    color: '#111827',
  },
  walletSymbol: {
    fontSize: 14,
    color: '#6b7280',
    marginTop: 2,
  },
  walletBalance: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  walletAmount: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#111827',
    marginRight: 8,
  },
  recentSection: {
    paddingHorizontal: 20,
    marginTop: 24,
  },
  recentHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  viewAllText: {
    fontSize: 14,
    color: '#10b981',
    fontWeight: '600',
  },
  transactionItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    padding: 16,
    borderRadius: 12,
    marginBottom: 8,
  },
  transactionIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#f3f4f6',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  transactionDetails: {
    flex: 1,
  },
  transactionName: {
    fontSize: 16,
    fontWeight: '500',
    color: '#111827',
  },
  transactionTime: {
    fontSize: 14,
    color: '#6b7280',
    marginTop: 2,
  },
  transactionAmount: {
    fontSize: 16,
    fontWeight: '600',
  },
});