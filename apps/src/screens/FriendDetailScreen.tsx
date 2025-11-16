import React, { useState, useEffect, useMemo, useCallback, memo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Platform,
  Image,
  RefreshControl,
  Modal,
  TextInput,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RouteProp } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';
import { Header } from '../navigation/Header';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import { useNumberFormat } from '../utils/numberFormatting';
import { useQuery } from '@apollo/client';
import { GET_UNIFIED_TRANSACTIONS_WITH_FRIEND, GET_ME } from '../apollo/queries';
import { useAccount } from '../contexts/AccountContext';
import { TransactionFilterModal, TransactionFilters } from '../components/TransactionFilterModal';
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

type FriendDetailScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;
type FriendDetailScreenRouteProp = RouteProp<MainStackParamList, 'FriendDetail'>;

interface Transaction {
  id: string;
  type: 'sent' | 'received' | 'payment' | 'exchange' | 'reward';
  from?: string;
  to?: string;
  amount: string;
  currency: string;
  date: string;
  time: string;
  status: 'completed' | 'pending';
  hash: string;
  isInvitation: boolean;
  invitationClaimed: boolean;
  invitationReverted: boolean;
  invitationExpiresAt?: string;
  senderAddress?: string;
  recipientAddress?: string;
  description?: string;
  p2pTradeId?: string;
}

interface Friend {
  id?: string;
  name: string;
  phone?: string;
  avatar: string;
  isOnConfio: boolean;
}

moment.locale('es');

export function FriendDetailScreen() {
  const navigation = useNavigation<FriendDetailScreenNavigationProp>();
  const route = useRoute<FriendDetailScreenRouteProp>();
  const { formatCurrency } = useNumberFormat();
  const { activeAccount } = useAccount();
  
  // Safely extract route params with defaults
  const params = route.params || {};
  const {
    friendId = '',
    friendName = '',
    friendAvatar = '👤',
    friendPhone,
    isOnConfio = false
  } = params;
  
  // Construct friend object from route params
  const friend: Friend = {
    id: friendId,
    name: friendName,
    avatar: friendAvatar,
    phone: friendPhone,
    isOnConfio: isOnConfio
  };
  
  // Early return with error state if essential params are missing
  if (!friendName) {
    return (
      <View style={styles.container}>
        <Header
          navigation={navigation}
          title="Error"
          backgroundColor={colors.primary}
          isLight={true}
          showBackButton={true}
        />
        <View style={styles.errorContainer}>
          <Text style={styles.errorText}>Error: Friend data not found</Text>
        </View>
      </View>
    );
  }

  // State for transaction filtering
  const [searchQuery, setSearchQuery] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [showFilterModal, setShowFilterModal] = useState(false);
  const [transactionFilters, setTransactionFilters] = useState<TransactionFilters>({
    types: {
      sent: true,
      received: true,
      payment: true,
      exchange: true,
      conversion: true,
      reward: true,
    },
    currencies: {
      cUSD: true,
      CONFIO: true,
      USDC: true,
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

  // State management
  const [showTokenSelection, setShowTokenSelection] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [transactionLimit, setTransactionLimit] = useState(20);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasReachedEnd, setHasReachedEnd] = useState(false);

  // Check if this is a device contact (not on Confío)
  const isDeviceContact = !friend.isOnConfio;

  // Get current user data for navigation
  const { data: userData } = useQuery(GET_ME, {
    skip: false,
    fetchPolicy: 'cache-first',
  });

  // Use friend-specific unified transactions query
  const queryVariables = {
    friendUserId: friend.isOnConfio ? friend.id : null,
    friendPhone: friend.phone,
    limit: transactionLimit,
    offset: 0,
  };

  const { 
    data: unifiedTransactionsData, 
    loading: unifiedLoading, 
    error: unifiedError,
    refetch: unifiedRefetch,
    fetchMore,
    networkStatus
  } = useQuery(GET_UNIFIED_TRANSACTIONS_WITH_FRIEND, {
    variables: queryVariables,
    fetchPolicy: 'cache-first',
    notifyOnNetworkStatusChange: true,
    skip: false,
    onCompleted: (data) => {
      console.log('FriendDetailScreen - Friend transactions query completed:', {
        hasData: !!data,
        transactionCount: data?.unifiedTransactionsWithFriend?.length || 0
      });
    },
    onError: (error) => {
      console.error('Unified transactions query error:', error);
    }
  });

  // Get friend transactions directly from the friend-specific query (no client-side filtering needed)
  const friendTransactions = useMemo(() => {
    return unifiedTransactionsData?.unifiedTransactionsWithFriend || [];
  }, [unifiedTransactionsData]);

  // Transform unified transactions into the format expected by the UI
  const formatTransactions = useCallback(() => {
    const allTransactions: Transaction[] = [];

    friendTransactions.forEach((tx: any) => {
      const transactionType = tx.transactionType.toLowerCase();
      
      // Determine transaction direction from current user perspective
      const isCurrentUserSender = tx.direction === 'sent';
      
      const uiCurrency = (tx.tokenType || '').toUpperCase() === 'CUSD' ? 'cUSD' : (tx.tokenType || 'CONFIO');
      allTransactions.push({
        id: tx.id,
        type: transactionType === 'exchange' ? 'exchange' : 
              transactionType === 'payment' ? 'payment' :
              transactionType === 'reward' ? 'reward' :
              isCurrentUserSender ? 'sent' : 'received',
        from: transactionType === 'reward'
          ? (tx.senderDisplayName || 'Confío Rewards')
          : isCurrentUserSender ? undefined : friend.name,
        to: transactionType === 'reward'
          ? (friend.name || 'Tú')
          : isCurrentUserSender ? friend.name : undefined,
        amount: tx.displayAmount || tx.amount,
        currency: uiCurrency,
        date: new Date(tx.createdAt).toISOString().split('T')[0],
        time: new Date(tx.createdAt).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }),
        status: tx.status === 'CONFIRMED' ? 'completed' : 'pending',
        hash: tx.transactionHash || tx.id || 'pending',
        isInvitation: tx.isInvitation || false,
        invitationClaimed: tx.invitationClaimed || false,
        invitationReverted: tx.invitationReverted || false,
        invitationExpiresAt: tx.invitationExpiresAt,
        senderAddress: tx.senderAddress,
        recipientAddress: tx.counterpartyAddress,
        description: tx.description,
        p2pTradeId: tx.p2pTradeId
      });
    });

    // Sort by date (newest first)
    return allTransactions.sort((a, b) => new Date(b.date + ' ' + b.time).getTime() - new Date(a.date + ' ' + a.time).getTime());
  }, [friendTransactions, friend.name]);
  
  const transactions = formatTransactions();
  
  // Filter transactions based on search query and filters
  const filteredTransactions = useMemo(() => {
    let filtered = transactions;
    
    // Safety check for transactionFilters
    if (!transactionFilters) {
      return filtered;
    }
    
    // Apply search query filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(tx => {
        const title = getTransactionTitle(tx).toLowerCase();
        const amount = tx.amount.toLowerCase();
        const currency = tx.currency.toLowerCase();
        const hash = tx.hash.toLowerCase();
        const date = moment(tx.date).format('DD/MM/YYYY').toLowerCase();
        
        return title.includes(query) || 
               amount.includes(query) ||
               currency.includes(query) ||
               hash.includes(query) ||
               date.includes(query);
      });
    }
    
    // Apply type filters
    if (transactionFilters.types) {
      filtered = filtered.filter(tx => {
        return transactionFilters.types[tx.type];
      });
    }
    
    // Apply currency filters
    if (transactionFilters.currencies) {
      filtered = filtered.filter(tx => {
        const currency = tx.currency === 'cUSD' ? 'cUSD' : tx.currency;
        return transactionFilters.currencies[currency as keyof typeof transactionFilters.currencies] ?? true;
      });
    }
    
    // Apply status filters
    if (transactionFilters.status) {
      filtered = filtered.filter(tx => {
        return transactionFilters.status[tx.status];
      });
    }
    
    // Apply time range filter
    if (transactionFilters.timeRange && transactionFilters.timeRange !== 'all') {
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
    if (transactionFilters.amountRange && (transactionFilters.amountRange.min || transactionFilters.amountRange.max)) {
      filtered = filtered.filter(tx => {
        const amount = Math.abs(parseFloat(tx.amount.replace(/[^0-9.-]/g, '')));
        const min = transactionFilters.amountRange.min ? parseFloat(transactionFilters.amountRange.min) : 0;
        const max = transactionFilters.amountRange.max ? parseFloat(transactionFilters.amountRange.max) : Infinity;
        return amount >= min && amount <= max;
      });
    }
    
    return filtered;
  }, [transactions, searchQuery, transactionFilters]);
  
  const hasActiveFilters = useCallback(() => {
    // Safety check for transactionFilters
    if (!transactionFilters) return false;
    
    // Check if any filter is non-default
    const defaultFilters: TransactionFilters = {
      types: { sent: true, received: true, payment: true, exchange: true, conversion: true, reward: true },
      currencies: { cUSD: true, CONFIO: true, USDC: true },
      status: { completed: true, pending: true },
      timeRange: 'all',
      amountRange: { min: '', max: '' }
    };
    
    return JSON.stringify(transactionFilters) !== JSON.stringify(defaultFilters);
  }, [transactionFilters]);

  const getTransactionTitle = useCallback((transaction: Transaction) => {
    switch(transaction.type) {
      case 'received':
        return `Recibido de ${transaction.from}`;
      case 'sent':
        return `Enviado a ${transaction.to}`;
      case 'payment':
        return `Pago a ${transaction.to}`;
      case 'exchange':
        return 'Intercambio P2P';
      case 'reward':
        return transaction.description || 'Recompensa Confío';
      default:
        return 'Transacción';
    }
  }, []);

  const getTransactionIcon = useCallback((transaction: Transaction) => {
    switch(transaction.type) {
      case 'received':
        return <Icon name="arrow-down" size={20} color="#10B981" />;
      case 'sent':
        return <Icon name="arrow-up" size={20} color="#EF4444" />;
      case 'payment':
        return <Icon name="shopping-bag" size={20} color="#8B5CF6" />;
      case 'exchange':
        return <Icon name="repeat" size={20} color="#8B5CF6" />;
      default:
        return <Icon name="arrow-up" size={20} color="#6B7280" />;
    }
  }, []);

  const TransactionItem = memo(({ transaction, onPress }: { transaction: Transaction; onPress: () => void }) => {
    // Only treat as an active invitation if not claimed, not reverted, and not expired
    const isExpired = transaction.invitationExpiresAt ? moment(transaction.invitationExpiresAt).isBefore(moment()) : false;
    const isInvitationTransaction = !!transaction.isInvitation && !transaction.invitationClaimed && !transaction.invitationReverted && !isExpired;
    
    // Debug logging
    if (transaction.type === 'sent') {
      console.log('[FriendDetail] Transaction:', {
        to: transaction.to,
        isInvitation: transaction.isInvitation,
        isInvitationTransaction,
        friendIsOnConfio: friend.isOnConfio
      });
    }
    
    return (
      <TouchableOpacity style={[styles.transactionItem, isInvitationTransaction && styles.invitedTransactionItem]} onPress={onPress}>
        <View style={[styles.transactionIconContainer, isInvitationTransaction && styles.invitedIconContainer]}>
          {getTransactionIcon(transaction)}
        </View>
        <View style={styles.transactionInfo}>
          <Text style={styles.transactionTitle}>{getTransactionTitle(transaction)}</Text>
          <Text style={styles.transactionDate}>{transaction.date} • {transaction.time}</Text>
          {isInvitationTransaction && transaction.type === 'sent' && (
            <Text style={styles.invitedNote}>
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
            <Text style={styles.statusText}>
              {transaction.status === 'completed' ? 'Completado' : 'Pendiente'}
            </Text>
            <View style={[styles.statusDot, { backgroundColor: transaction.status === 'completed' ? '#10b981' : '#f59e0b' }]} />
          </View>
        </View>
      </TouchableOpacity>
    );
  });

  const handleSendMoney = useCallback(() => {
    // Show token selection modal
    setShowTokenSelection(true);
  }, []);

  const handleTokenSelect = useCallback((tokenType: 'cusd' | 'confio') => {
    setShowTokenSelection(false);
    
    // Get the active account's Algorand address from the user data
    let algorandAddress = undefined;
    if (userData?.me?.accounts && userData.me.accounts.length > 0) {
      // Get the personal account (accountIndex 0) by default
      const personalAccount = userData.me.accounts.find((acc: any) => acc.accountType === 'personal' && acc.accountIndex === 0);
      algorandAddress = personalAccount?.algorandAddress;
    }
    
    // Navigate to SendToFriend screen with selected token
    navigation.navigate('SendToFriend', { 
      friend: {
        id: friend.id,  // Include the friend ID for Confío users
        userId: friend.id,  // Also as userId for compatibility
        name: friend.name,
        avatar: friend.avatar,
        isOnConfio: friend.isOnConfio,
        phone: friend.phone || ''
      },
      tokenType: tokenType 
    });
  }, [friend, navigation, userData]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    setTransactionLimit(20); // Reset to initial limit
    setHasReachedEnd(false); // Reset end flag
    
    try {
      await unifiedRefetch();
    } catch (error) {
      console.error('Error refreshing transactions:', error);
    } finally {
      setRefreshing(false);
    }
  }, [unifiedRefetch]);

  const loadMoreTransactions = useCallback(async () => {
    if (loadingMore || hasReachedEnd || networkStatus === 3) return;
    
    setLoadingMore(true);
    const newLimit = transactionLimit + 10;
    
    try {
      await fetchMore({
        variables: {
          accountType: 'personal',
          accountIndex: 0,
          limit: newLimit,
          offset: 0,
        },
        updateQuery: (prev, { fetchMoreResult }) => {
          if (!fetchMoreResult) return prev;
          return fetchMoreResult;
        }
      });
      
      // Update the limit to trigger re-render
      setTransactionLimit(newLimit);
      
      // Check if we've reached the end
      if (friendTransactions.length < newLimit) {
        setHasReachedEnd(true);
      }
    } catch (error) {
      console.error('Error loading more transactions:', error);
    } finally {
      setLoadingMore(false);
    }
  }, [loadingMore, hasReachedEnd, networkStatus, fetchMore, transactionLimit, friendTransactions.length]);

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation}
        title={friend.name}
        backgroundColor={colors.primary}
        isLight={true}
        showBackButton={true}
      />

      <ScrollView 
        style={styles.scrollView}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.primary}
            colors={[colors.primary]}
          />
        }
      >
        {/* Friend Info Section with Emerald Background */}
        <View style={[styles.friendSection, { backgroundColor: colors.primary }]}>
          <View style={styles.friendAvatarContainer}>
            <Text style={styles.friendAvatarText}>{friend.avatar}</Text>
          </View>
          <Text style={styles.friendName}>{friend.name}</Text>
          {friend.phone && (
            <Text style={styles.friendPhone}>{friend.phone}</Text>
          )}
          <View style={[
            styles.friendStatus, 
            { backgroundColor: friend.isOnConfio ? 'rgba(255, 255, 255, 0.2)' : 'rgba(239, 68, 68, 0.2)' }
          ]}>
            <View style={[styles.statusIndicator, { backgroundColor: friend.isOnConfio ? '#ffffff' : '#ef4444' }]} />
            <Text style={[styles.statusText, { color: friend.isOnConfio ? '#ffffff' : '#ef4444' }]}>
              {friend.isOnConfio ? 'En Confío' : 'No está en Confío'}
            </Text>
          </View>
        </View>

        {/* Send Button */}
        <View style={styles.sendButtonContainer}>
          <TouchableOpacity 
            style={[styles.sendButton, !friend.isOnConfio && styles.inviteButton]}
            onPress={handleSendMoney}
          >
            <Icon name="send" size={20} color="#ffffff" style={{ marginRight: 8 }} />
            <Text style={styles.sendButtonText}>
              {friend.isOnConfio ? 'Enviar' : 'Enviar & Invitar'}
            </Text>
          </TouchableOpacity>
          {!friend.isOnConfio && (
            <Text style={styles.inviteNote}>
              Tu amigo recibirá el dinero y una invitación a Confío
            </Text>
          )}
        </View>

        {/* Transactions Section */}
        <View style={styles.transactionsSection}>
          <View style={styles.transactionsHeader}>
            <Text style={styles.transactionsTitle}>
              {friend.isOnConfio ? `Historial con ${friend.name}` : 'Historial de envíos'}
            </Text>
            <View style={styles.transactionsFilters}>
              <TouchableOpacity 
                style={[
                  styles.filterButton,
                  showSearch && styles.filterButtonActive
                ]}
                onPress={() => setShowSearch(!showSearch)}
              >
                <Icon name="search" size={16} color={showSearch ? colors.primary : "#6b7280"} />
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
                  color={hasActiveFilters() ? colors.primary : "#6b7280"} 
                />
                {hasActiveFilters() && (
                  <View style={styles.filterDot} />
                )}
              </TouchableOpacity>
            </View>
          </View>

          {/* Search Bar */}
          {showSearch && (
            <View style={styles.searchContainer}>
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
            </View>
          )}

          <View style={styles.transactionsList}>
            {unifiedLoading ? (
              <View style={styles.loadingContainer}>
                <Text style={styles.loadingText}>Cargando transacciones...</Text>
              </View>
            ) : filteredTransactions.length === 0 ? (
              <View style={styles.emptyTransactionsContainer}>
                <Icon name="inbox" size={32} color="#9ca3af" />
                <Text style={styles.emptyTransactionsText}>
                  {searchQuery || hasActiveFilters() 
                    ? 'No se encontraron transacciones'
                    : friend.isOnConfio ? 'No hay transacciones aún' : 'Tu amigo no está en Confío'
                  }
                </Text>
                <Text style={styles.emptyTransactionsSubtext}>
                  {searchQuery || hasActiveFilters()
                    ? 'Intenta cambiar los filtros o términos de búsqueda'
                    : !friend.isOnConfio ? 
                      `Cuando envíes dinero a ${friend.name}, recibirá una invitación para unirse a Confío` :
                      `Aquí aparecerán las transacciones que realices con ${friend.name}`
                  }
                </Text>
              </View>
            ) : (
              filteredTransactions.map((transaction, index) => (
                <TransactionItem 
                  key={`${transaction.id}-${index}`}
                  transaction={transaction} 
                  onPress={() => {
                    // Handle P2P trade navigation
                    if (transaction.type === 'exchange' && transaction.p2pTradeId) {
                      navigation.navigate('ActiveTrade', { 
                        trade: { 
                          id: transaction.p2pTradeId 
                        } 
                      });
                    } else {
                      // Handle regular transaction navigation
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
                          fromAddress: transaction.type === 'received' ? transaction.senderAddress : undefined,
                          toAddress: transaction.type === 'sent' ? transaction.recipientAddress : undefined,
                          blockNumber: '2,847,392',
                          gasUsed: '21,000',
                          gasFee: '0.001',
                          confirmations: 127,
                          note: transaction.type === 'received' ? `Pago de ${friend.name}` : 
                                transaction.type === 'sent' ? `Envío a ${friend.name}` : 
                                `Pago a ${friend.name}`,
                          avatar: friend.avatar,
                          isInvitedFriend: transaction.isInvitation || false, // Use transaction's invitation status
                          invitationClaimed: transaction.invitationClaimed || false,
                          invitationReverted: transaction.invitationReverted || false,
                          invitationExpiresAt: transaction.invitationExpiresAt,
                        }
                      };
                      // @ts-ignore - Navigation type mismatch, but works at runtime
                      navigation.navigate('TransactionDetail', params);
                    }
                  }} 
                />
              ))
            )}
          </View>

          {transactions.length > 0 && !hasReachedEnd && !searchQuery && !hasActiveFilters() && (
            <TouchableOpacity 
              style={styles.viewMoreButton}
              onPress={loadMoreTransactions}
              disabled={loadingMore}
            >
              {loadingMore ? (
                <Text style={styles.viewMoreButtonText}>Cargando...</Text>
              ) : (
                <Text style={styles.viewMoreButtonText}>Ver más</Text>
              )}
            </TouchableOpacity>
          )}
        </View>
      </ScrollView>
      
      {/* Token Selection Modal */}
      <Modal
        visible={showTokenSelection}
        transparent
        animationType="fade"
        onRequestClose={() => setShowTokenSelection(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Elige el token a enviar</Text>
              <TouchableOpacity onPress={() => setShowTokenSelection(false)}>
                <Icon name="x" size={24} color="#6b7280" />
              </TouchableOpacity>
            </View>
            
            <TouchableOpacity 
              style={styles.tokenOption}
              onPress={() => handleTokenSelect('cusd')}
            >
              <View style={styles.tokenInfo}>
                <Image source={cUSDLogo} style={styles.tokenLogo} />
                <View style={styles.tokenDetails}>
                  <Text style={styles.tokenName}>Confío Dollar</Text>
                  <Text style={styles.tokenSymbol}>$cUSD</Text>
                  <Text style={styles.tokenDescription}>
                    Moneda estable para pagos diarios
                  </Text>
                </View>
              </View>
            </TouchableOpacity>
            
            <TouchableOpacity 
              style={styles.tokenOption}
              onPress={() => handleTokenSelect('confio')}
            >
              <View style={styles.tokenInfo}>
                <Image source={CONFIOLogo} style={styles.tokenLogo} />
                <View style={styles.tokenDetails}>
                  <Text style={styles.tokenName}>Confío</Text>
                  <Text style={styles.tokenSymbol}>$CONFIO</Text>
                  <Text style={styles.tokenDescription}>
                    Moneda de gobernanza y utilidad
                  </Text>
                </View>
              </View>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* Transaction Filter Modal */}
      <TransactionFilterModal
        visible={showFilterModal}
        onClose={() => setShowFilterModal(false)}
        onApply={setTransactionFilters}
        currentFilters={transactionFilters || {
          types: { sent: true, received: true, payment: true, exchange: true, conversion: true },
          currencies: { cUSD: true, CONFIO: true, USDC: true },
          status: { completed: true, pending: true },
          timeRange: 'all',
          amountRange: { min: '', max: '' }
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#ffffff',
  },
  scrollView: {
    flex: 1,
  },
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  errorText: {
    fontSize: 16,
    color: colors.text.primary,
    textAlign: 'center',
  },
  friendSection: {
    alignItems: 'center',
    paddingTop: 12,
    paddingBottom: 24,
    paddingHorizontal: 20,
  },
  friendAvatarContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: '#ffffff',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
    padding: 8,
  },
  friendAvatarText: {
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.primary,
  },
  friendName: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#ffffff',
    marginBottom: 4,
    textAlign: 'center',
  },
  friendPhone: {
    fontSize: 16,
    color: 'rgba(255, 255, 255, 0.8)',
    marginBottom: 12,
    textAlign: 'center',
  },
  friendStatus: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
  },
  statusIndicator: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 8,
  },
  statusText: {
    fontSize: 14,
    fontWeight: '500',
  },
  sendButtonContainer: {
    padding: 24,
    backgroundColor: '#ffffff',
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  sendButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primary,
    paddingVertical: 16,
    paddingHorizontal: 24,
    borderRadius: 12,
    marginBottom: 8,
  },
  inviteButton: {
    backgroundColor: colors.primary, // Use same emerald color as regular send button
  },
  sendButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  inviteNote: {
    fontSize: 12,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 16,
  },
  transactionsSection: {
    flex: 1,
    backgroundColor: '#ffffff',
  },
  transactionsHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 24,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  transactionsTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text.primary,
  },
  transactionsFilters: {
    flexDirection: 'row',
    gap: 8,
  },
  filterButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#f9fafb',
    justifyContent: 'center',
    alignItems: 'center',
    position: 'relative',
  },
  filterButtonActive: {
    backgroundColor: colors.primaryLight,
  },
  filterDot: {
    position: 'absolute',
    top: 8,
    right: 8,
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.primary,
  },
  searchContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginHorizontal: 24,
    marginVertical: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#f9fafb',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  searchIcon: {
    marginRight: 12,
  },
  searchInput: {
    flex: 1,
    fontSize: 16,
    color: colors.text.primary,
    padding: 0,
  },
  transactionsList: {
    paddingHorizontal: 24,
  },
  loadingContainer: {
    paddingVertical: 40,
    alignItems: 'center',
  },
  loadingText: {
    fontSize: 16,
    color: colors.text.secondary,
  },
  emptyTransactionsContainer: {
    paddingVertical: 40,
    alignItems: 'center',
  },
  emptyTransactionsText: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    marginTop: 12,
    marginBottom: 8,
    textAlign: 'center',
  },
  emptyTransactionsSubtext: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 20,
    paddingHorizontal: 20,
  },
  transactionItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 16,
    paddingHorizontal: 0,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  invitedTransactionItem: {
    backgroundColor: '#fef2f2',
    borderColor: '#ef4444',
    borderWidth: 1,
    borderRadius: 12,
    marginVertical: 4,
    paddingHorizontal: 16,
    borderBottomWidth: 0,
  },
  transactionIconContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#f9fafb',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  invitedIconContainer: {
    backgroundColor: '#fef2f2',
  },
  transactionInfo: {
    flex: 1,
  },
  transactionTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: 4,
  },
  transactionDate: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  invitedNote: {
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
    fontWeight: '600',
    marginBottom: 4,
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
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    marginLeft: 6,
  },
  viewMoreButton: {
    paddingVertical: 16,
    alignItems: 'center',
    marginTop: 8,
    marginBottom: 24,
  },
  viewMoreButtonText: {
    fontSize: 16,
    color: colors.primary,
    fontWeight: '500',
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 24,
    margin: 24,
    maxWidth: 400,
    width: '100%',
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 24,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text.primary,
  },
  tokenOption: {
    borderWidth: 1,
    borderColor: '#e5e7eb',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
  },
  tokenInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  tokenLogo: {
    width: 40,
    height: 40,
    marginRight: 16,
  },
  tokenDetails: {
    flex: 1,
  },
  tokenName: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: 4,
  },
  tokenSymbol: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.primary,
    marginBottom: 4,
  },
  tokenDescription: {
    fontSize: 12,
    color: colors.text.secondary,
    lineHeight: 16,
  },
});
