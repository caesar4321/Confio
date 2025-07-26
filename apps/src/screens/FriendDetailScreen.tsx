import React, { useState } from 'react';
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
import { GET_SEND_TRANSACTIONS_WITH_FRIEND, GET_PAYMENT_TRANSACTIONS_WITH_FRIEND } from '../apollo/queries';

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
  type: 'received' | 'sent' | 'payment';
  from?: string;
  to?: string;
  amount: string;
  currency: string;
  date: string;
  time: string;
  status: string;
  hash: string;
}

export const FriendDetailScreen = () => {
  const navigation = useNavigation<FriendDetailScreenNavigationProp>();
  const route = useRoute<FriendDetailScreenRouteProp>();
  const { formatNumber } = useNumberFormat();
  const [refreshing, setRefreshing] = useState(false);
  const [transactionLimit, setTransactionLimit] = useState(20);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasReachedEnd, setHasReachedEnd] = useState(false);
  const [showTokenSelection, setShowTokenSelection] = useState(false);

  // Friend data from navigation params
  const friend = {
    id: route.params?.friendId || '1',
    name: route.params?.friendName || 'Friend',
    avatar: route.params?.friendAvatar || 'F',
    phone: route.params?.friendPhone || '',
    isOnConfio: route.params?.isOnConfio || true,
  };

  // Check if this is a device contact (not a real Confío user)
  const isDeviceContact = friend.id.startsWith('contact_');
  
  // Get real transaction data from GraphQL (only if it's a real user)
  const { data: sendTransactionsData, loading: sendLoading, refetch: refetchSend, fetchMore: fetchMoreSend } = useQuery(GET_SEND_TRANSACTIONS_WITH_FRIEND, {
    variables: {
      friendUserId: friend.id,
      limit: transactionLimit
    },
    skip: isDeviceContact || !friend.isOnConfio // Skip query for device contacts or non-Confío users
  });

  const { data: paymentTransactionsData, loading: paymentLoading, refetch: refetchPayment, fetchMore: fetchMorePayment } = useQuery(GET_PAYMENT_TRANSACTIONS_WITH_FRIEND, {
    variables: {
      friendUserId: friend.id,
      limit: transactionLimit
    },
    skip: isDeviceContact || !friend.isOnConfio // Skip query for device contacts or non-Confío users
  });

  // Transform real transactions into the format expected by the UI
  const formatTransactions = () => {
    const allTransactions: Transaction[] = [];

    // Add send transactions
    if (sendTransactionsData?.sendTransactionsWithFriend) {
      sendTransactionsData.sendTransactionsWithFriend.forEach((tx: any) => {
        const currentUserIsSender = tx.senderUser?.id !== friend.id;
        
        allTransactions.push({
          type: currentUserIsSender ? 'sent' : 'received',
          from: currentUserIsSender ? undefined : friend.name,
          to: currentUserIsSender ? friend.name : undefined,
          amount: currentUserIsSender ? `-${tx.amount}` : `+${tx.amount}`,
          currency: tx.tokenType,
          date: new Date(tx.createdAt).toISOString().split('T')[0],
          time: new Date(tx.createdAt).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }),
          status: tx.status.toLowerCase() === 'confirmed' ? 'completed' : 'pending',
          hash: tx.transactionHash || 'pending'
        });
      });
    }

    // Add payment transactions
    if (paymentTransactionsData?.paymentTransactionsWithFriend) {
      paymentTransactionsData.paymentTransactionsWithFriend.forEach((tx: any) => {
        const currentUserIsPayer = tx.payerUser?.id !== friend.id;
        
        allTransactions.push({
          type: 'payment',
          from: undefined,
          to: currentUserIsPayer ? friend.name : undefined,
          amount: currentUserIsPayer ? `-${tx.amount}` : `+${tx.amount}`,
          currency: tx.tokenType,
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
  
  // Check if we've reached the end after loading more
  React.useEffect(() => {
    if (loadingMore) return;
    
    // If we have transactions and the count is less than the limit,
    // it means we've loaded all available transactions
    const totalCount = (sendTransactionsData?.sendTransactionsWithFriend?.length || 0) + 
                      (paymentTransactionsData?.paymentTransactionsWithFriend?.length || 0);
    
    // If we have fewer transactions than the limit, we've reached the end
    if (totalCount > 0 && totalCount < transactionLimit) {
      setHasReachedEnd(true);
    }
  }, [sendTransactionsData, paymentTransactionsData, transactionLimit, loadingMore]);

  const getTransactionTitle = (transaction: Transaction) => {
    switch(transaction.type) {
      case 'received':
        return `Recibido de ${transaction.from}`;
      case 'sent':
        return `Enviado a ${transaction.to}`;
      case 'payment':
        return `Pago a ${transaction.to}`;
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
            <Text style={styles.statusText}>
              {transaction.status === 'completed' ? 'Completado' : 'Pendiente'}
            </Text>
            <View style={[styles.statusDot, { backgroundColor: transaction.status === 'completed' ? '#10b981' : '#f59e0b' }]} />
          </View>
        </View>
      </TouchableOpacity>
    );
  };

  const handleSendMoney = () => {
    // Show token selection modal
    setShowTokenSelection(true);
  };

  const handleTokenSelect = (tokenType: 'cusd' | 'confio') => {
    setShowTokenSelection(false);
    // Navigate to SendToFriend screen with selected token
    navigation.navigate('SendToFriend', { 
      friend: {
        name: friend.name,
        avatar: friend.avatar,
        isOnConfio: friend.isOnConfio,
        phone: friend.phone
      },
      tokenType: tokenType 
    });
  };

  const onRefresh = async () => {
    setRefreshing(true);
    setTransactionLimit(20); // Reset to initial limit
    setHasReachedEnd(false); // Reset end flag
    
    // Don't refetch for device contacts or non-Confío users
    if (isDeviceContact || !friend.isOnConfio) {
      setRefreshing(false);
      return;
    }
    
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
    
    // Don't fetch more for device contacts or non-Confío users
    if (isDeviceContact || !friend.isOnConfio) {
      return;
    }
    
    setLoadingMore(true);
    const newLimit = transactionLimit + 10;
    
    try {
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
        {/* Friend Info Section */}
        <View style={styles.friendSection}>
          <View style={styles.friendAvatarContainer}>
            <Text style={styles.friendAvatarText}>{friend.avatar}</Text>
          </View>
          <Text style={styles.friendName}>{friend.name}</Text>
          {friend.phone && (
            <Text style={styles.friendPhone}>{friend.phone}</Text>
          )}
          <View style={styles.friendStatus}>
            <View style={[styles.statusIndicator, { backgroundColor: friend.isOnConfio ? colors.primary : '#9ca3af' }]} />
            <Text style={styles.statusText}>
              {friend.isOnConfio ? 'En Confío' : 'No está en Confío'}
            </Text>
          </View>
        </View>

        {/* Send Button */}
        <View style={styles.sendButtonContainer}>
          <TouchableOpacity 
            style={styles.sendButton}
            onPress={handleSendMoney}
          >
            <Icon name="send" size={20} color="#ffffff" style={{ marginRight: 8 }} />
            <Text style={styles.sendButtonText}>Enviar</Text>
          </TouchableOpacity>
        </View>

        {/* Transactions Section */}
        <View style={styles.transactionsSection}>
          <View style={styles.transactionsHeader}>
            <Text style={styles.transactionsTitle}>Historial con {friend.name}</Text>
            <View style={styles.transactionsFilters}>
              <TouchableOpacity style={styles.filterButton}>
                <Icon name="filter" size={16} color="#6b7280" />
              </TouchableOpacity>
            </View>
          </View>

          <View style={styles.transactionsList}>
            {(sendLoading || paymentLoading) ? (
              <View style={styles.loadingContainer}>
                <Text style={styles.loadingText}>Cargando transacciones...</Text>
              </View>
            ) : transactions.length === 0 ? (
              <View style={styles.emptyTransactionsContainer}>
                <Icon name="inbox" size={32} color="#9ca3af" />
                <Text style={styles.emptyTransactionsText}>No hay transacciones aún</Text>
                <Text style={styles.emptyTransactionsSubtext}>
                  {isDeviceContact ? 
                    `Invita a ${friend.name} a Confío para empezar a enviar dinero` :
                    `Aquí aparecerán las transacciones que realices con ${friend.name}`
                  }
                </Text>
              </View>
            ) : (
              transactions.map((transaction, index) => (
                <TransactionItem 
                  key={index} 
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
                        note: transaction.type === 'received' ? `Pago de ${friend.name}` : 
                              transaction.type === 'sent' ? `Envío a ${friend.name}` : 
                              `Pago a ${friend.name}`,
                        avatar: friend.avatar,
                      }
                    };
                    // @ts-ignore - Navigation type mismatch, but works at runtime
                    navigation.navigate('TransactionDetail', params);
                  }} 
                />
              ))
            )}
          </View>

          {transactions.length > 0 && !hasReachedEnd && (
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
              <Text style={styles.modalTitle}>Selecciona la moneda</Text>
              <TouchableOpacity onPress={() => setShowTokenSelection(false)}>
                <Icon name="x" size={24} color="#6B7280" />
              </TouchableOpacity>
            </View>
            
            <Text style={styles.modalSubtitle}>
              ¿Qué moneda quieres enviar a {friend.name}?
            </Text>
            
            <View style={styles.tokenOptions}>
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
                <Icon name="chevron-right" size={20} color="#6B7280" />
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
                <Icon name="chevron-right" size={20} color="#6B7280" />
              </TouchableOpacity>
            </View>
            
            <TouchableOpacity 
              style={styles.cancelButton}
              onPress={() => setShowTokenSelection(false)}
            >
              <Text style={styles.cancelButtonText}>Cancelar</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
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
  friendSection: {
    backgroundColor: colors.primary,
    paddingTop: 20,
    paddingBottom: 32,
    paddingHorizontal: 20,
    alignItems: 'center',
    marginBottom: 16,
  },
  friendAvatarContainer: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: '#ffffff',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  friendAvatarText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: colors.primary,
  },
  friendName: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#ffffff',
    marginBottom: 8,
  },
  friendPhone: {
    fontSize: 16,
    color: '#ffffff',
    opacity: 0.8,
    marginBottom: 12,
  },
  friendStatus: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  statusIndicator: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 8,
  },
  statusText: {
    fontSize: 14,
    color: '#ffffff',
    opacity: 0.9,
  },
  sendButtonContainer: {
    paddingHorizontal: 16,
    marginBottom: 16,
  },
  sendButton: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    ...Platform.select({
      ios: {
        shadowColor: colors.primary,
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.3,
        shadowRadius: 8,
      },
      android: {
        elevation: 4,
      },
    }),
  },
  sendButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#ffffff',
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
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginLeft: 4,
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
  },
  modalContent: {
    backgroundColor: '#fff',
    borderRadius: 20,
    padding: 24,
    width: '90%',
    maxWidth: 400,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#1f2937',
  },
  modalSubtitle: {
    fontSize: 16,
    color: '#6b7280',
    marginBottom: 24,
  },
  tokenOptions: {
    marginBottom: 16,
  },
  tokenOption: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 16,
    paddingHorizontal: 16,
    backgroundColor: '#f9fafb',
    borderRadius: 12,
    marginBottom: 12,
  },
  tokenInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  tokenLogo: {
    width: 48,
    height: 48,
    marginRight: 16,
  },
  tokenDetails: {
    flex: 1,
  },
  tokenName: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1f2937',
    marginBottom: 2,
  },
  tokenSymbol: {
    fontSize: 14,
    color: '#6b7280',
    marginBottom: 4,
  },
  tokenDescription: {
    fontSize: 12,
    color: '#9ca3af',
  },
  cancelButton: {
    backgroundColor: '#f3f4f6',
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: 'center',
  },
  cancelButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#6b7280',
  },
});