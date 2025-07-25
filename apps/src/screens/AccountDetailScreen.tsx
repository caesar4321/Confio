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
import { GET_SEND_TRANSACTIONS_BY_ACCOUNT, GET_PAYMENT_TRANSACTIONS_BY_ACCOUNT } from '../apollo/queries';
import { TransactionItemSkeleton } from '../components/SkeletonLoader';
import moment from 'moment';
import 'moment/locale/es';

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

type AccountDetailScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;
type AccountDetailScreenRouteProp = RouteProp<MainStackParamList, 'AccountDetail'>;

interface Transaction {
  type: 'received' | 'sent' | 'exchange' | 'payment';
  from?: string;
  to?: string;
  amount: string;
  currency: string;
  date: string;
  time: string;
  status: string;
  hash: string;
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
  const [showBalance, setShowBalance] = useState(true);
  const [showExchangeModal, setShowExchangeModal] = useState(false);
  const [exchangeAmount, setExchangeAmount] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [transactionLimit, setTransactionLimit] = useState(10);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasReachedEnd, setHasReachedEnd] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  
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
    exchangeRate: "1 USDC = 1.00 cUSD",
    description: route.params.accountType === 'cusd' 
      ? "Moneda estable respaldada por dólares americanos"
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

  // Animation entrance
  useEffect(() => {
    Animated.timing(fadeAnim, {
      toValue: 1,
      duration: 400,
      useNativeDriver: true,
    }).start();
  }, [fadeAnim]);
  
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
      ]);
      setTransactionLimit(10);
      setHasReachedEnd(false);
    } catch (error) {
      console.error('Error refreshing transactions:', error);
    } finally {
      setRefreshing(false);
    }
  }, [refetchSend, refetchPayment]);

  // Transform real transactions into the format expected by the UI
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

  const transactions = formatTransactions();
  
  // Filter transactions based on search query
  const filteredTransactions = useMemo(() => {
    if (!searchQuery) return transactions;
    
    const query = searchQuery.toLowerCase();
    return transactions.filter(tx => {
      const title = getTransactionTitle(tx).toLowerCase();
      const amount = tx.amount.toLowerCase();
      return title.includes(query) || amount.includes(query);
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

  const TransactionItem = ({ transaction, onPress }: { transaction: Transaction; onPress: () => void }) => {
    return (
      <TouchableOpacity style={styles.transactionItem} onPress={onPress}>
        <View style={styles.transactionIconContainer}>
          {getTransactionIcon(transaction)}
        </View>
        <View style={styles.transactionInfo}>
          <Text style={styles.transactionTitle}>{getTransactionTitle(transaction)}</Text>
          <Text style={styles.transactionDate}>{transaction.date} • {transaction.time}</Text>
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
                  <View style={[styles.currencyIcon, { backgroundColor: colors.accent }]}>
                    <Text style={styles.currencyIconText}>U</Text>
                  </View>
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
                <Text style={styles.exchangeInputLabel}>Tasa: 1 USDC = 1.00 cUSD</Text>
              </View>
              <View style={styles.exchangeInput}>
                <Text style={styles.exchangeInputText}>
                  {exchangeAmount || '0.00'}
                </Text>
                <View style={styles.currencyBadge}>
                  <View style={[styles.currencyIcon, { backgroundColor: colors.primary }]}>
                    <Text style={styles.currencyIconText}>C</Text>
                  </View>
                  <Text style={styles.currencyText}>cUSD</Text>
                </View>
              </View>
            </View>
          </View>

          <View style={styles.feeContainer}>
            <View style={styles.feeRow}>
              <Text style={styles.feeLabel}>Comisión de red</Text>
              <Text style={styles.feeValue}>$0.02</Text>
            </View>
            <View style={styles.feeRow}>
              <Text style={styles.feeLabel}>Comisión de plataforma</Text>
              <Text style={styles.feeValue}>Gratis</Text>
            </View>
            <View style={styles.feeDivider} />
            <View style={styles.feeRow}>
              <Text style={styles.feeTotalLabel}>Total a recibir</Text>
              <Text style={styles.feeTotalValue}>
                {exchangeAmount ? formatNumber(parseFloat(exchangeAmount) - 0.02) : formatNumber(0)} cUSD
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

  const onRefresh = async () => {
    setRefreshing(true);
    setTransactionLimit(10); // Reset to initial limit
    setHasReachedEnd(false); // Reset end flag
    try {
      await Promise.all([
        refetchSend(),
        refetchPayment()
      ]);
    } catch (error) {
      console.error('Error refreshing transactions:', error);
    } finally {
      setRefreshing(false);
    }
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
            <TouchableOpacity onPress={() => setShowBalance(!showBalance)}>
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
              <View style={[styles.actionIcon, { backgroundColor: colors.primary }]}>
                <Icon name="send" size={20} color="#ffffff" />
              </View>
              <Text style={styles.actionButtonText}>Enviar</Text>
            </TouchableOpacity>

            <TouchableOpacity 
              style={styles.actionButton}
              onPress={() => {
                // @ts-ignore - Navigation type mismatch, but should work at runtime
                navigation.navigate('USDCDeposit', { 
                  tokenType: route.params.accountType === 'cusd' ? 'cusd' : 'confio' 
                });
              }}
            >
              <View style={[styles.actionIcon, { backgroundColor: colors.primary }]}>
                <Icon name="download" size={20} color="#ffffff" />
              </View>
              <Text style={styles.actionButtonText}>Recibir</Text>
            </TouchableOpacity>

            <TouchableOpacity 
              style={styles.actionButton}
              onPress={() => {
                // @ts-ignore - Navigation type mismatch, but should work at runtime
                navigation.navigate('BottomTabs', { screen: 'Scan' });
              }}
            >
              <View style={[styles.actionIcon, { backgroundColor: colors.secondary }]}>
                <Icon name="shopping-bag" size={20} color="#ffffff" />
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
              <View style={[styles.actionIcon, { backgroundColor: colors.accent }]}>
                <Icon name="refresh-cw" size={20} color="#ffffff" />
              </View>
              <Text style={styles.actionButtonText}>Intercambio</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* USDC Balance Section - Only show for cUSD account */}
        {route.params.accountType === 'cusd' && usdcAccount && (
          <View style={styles.usdcSection}>
            <View style={styles.usdcCard}>
              <View style={styles.usdcHeader}>
                <View style={styles.usdcInfo}>
                  <Image source={USDCLogo} style={styles.usdcLogo} />
                  <View style={styles.usdcTextContainer}>
                    <Text style={styles.usdcName}>{usdcAccount.name}</Text>
                    <Text style={styles.usdcDescription} numberOfLines={2}>
                      {usdcAccount.description}
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

              <View style={styles.usdcActions}>
                <TouchableOpacity 
                  style={styles.usdcActionButton}
                  onPress={() => navigation.navigate('USDCDeposit', { tokenType: 'usdc' })}
                >
                  <Text style={styles.usdcActionButtonText}>Depositar USDC</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.usdcActionButton, { backgroundColor: colors.accent }]}
                  onPress={() => navigation.navigate('USDCManage')}
                >
                  <Text style={[styles.usdcActionButtonText, { color: '#ffffff' }]}>
                    Gestionar
                  </Text>
                </TouchableOpacity>
              </View>
            </View>
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
            {(sendLoading || paymentLoading) ? (
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
                        onPress={() => {
                          const params = {
                            transactionType: transaction.type,
                            transactionData: {
                              type: transaction.type,
                              from: transaction.from,
                              to: transaction.to,
                              amount: transaction.amount,
                              currency: transaction.currency,
                              date: transaction.date,
                              time: transaction.time,
                              status: transaction.status,
                              hash: transaction.hash,
                              // Add additional fields that TransactionDetailScreen expects
                              fromAddress: transaction.from ? '0x1a2b3c4d...7890abcd' : undefined,
                              toAddress: transaction.to ? '0x9876543a...bcdef123' : undefined,
                              blockNumber: '2,847,392',
                              gasUsed: '21,000',
                              gasFee: '0.001',
                              confirmations: 127,
                              note: transaction.type === 'received' ? 'Pago por almuerzo - Gracias! 🍕' : 
                                    transaction.type === 'sent' ? 'Pago servicios freelance' : undefined,
                              avatar: transaction.from ? transaction.from.charAt(0) : 
                                     transaction.to ? transaction.to.charAt(0) : undefined,
                              location: transaction.type === 'payment' ? 'Av. Libertador, Caracas' : undefined,
                              merchantId: transaction.type === 'payment' ? 'SUP001' : undefined,
                              exchangeRate: transaction.type === 'exchange' ? '1 USDC = 1.00 cUSD' : undefined
                            }
                          };
                          // @ts-ignore - Navigation type mismatch, but works at runtime
                          navigation.navigate('TransactionDetail', params);
                        }} 
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
  usdcCard: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 16,
    borderLeftWidth: 4,
    borderLeftColor: colors.accent,
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
  usdcLogo: {
    width: 40,
    height: 40,
    borderRadius: 20,
    marginRight: 12,
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
    fontSize: 12,
    color: '#6b7280',
    flexWrap: 'wrap',
  },
  usdcBalance: {
    alignItems: 'flex-end',
  },
  usdcBalanceText: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  usdcSymbol: {
    fontSize: 12,
    color: '#6b7280',
  },
  usdcAddressContainer: {
    marginBottom: 12,
  },
  usdcAddressLabel: {
    fontSize: 12,
    color: '#6b7280',
    marginBottom: 4,
  },
  usdcAddressRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  usdcAddressText: {
    fontSize: 12,
    color: '#6b7280',
    marginRight: 4,
  },
  usdcActions: {
    flexDirection: 'row',
    gap: 8,
  },
  usdcActionButton: {
    flex: 1,
    backgroundColor: colors.neutralDark,
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  usdcActionButtonText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1f2937',
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
    gap: 8,
  },
  filterButton: {
    padding: 8,
    backgroundColor: '#ffffff',
    borderRadius: 8,
  },
  transactionsList: {
    gap: 8,
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
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 16,
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
}); 