import React, { useState, useCallback, useEffect, useMemo } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Alert, Platform, StatusBar, Image, FlatList, ActivityIndicator, RefreshControl } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { PendingInvitationBanner } from '../components/PendingInvitationBanner';
import CONFIOLogo from '../assets/png/CONFIO.png';
import { useQuery, useMutation } from '@apollo/client';
import { GET_PRESALE_STATUS, GET_NOTIFICATIONS, GET_UNREAD_NOTIFICATION_COUNT } from '../apollo/queries';
import { MARK_NOTIFICATION_READ, MARK_ALL_NOTIFICATIONS_READ } from '../apollo/mutations';
import moment from 'moment';
import 'moment/locale/es';
import { contactService } from '../services/contactService';

type NotificationScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

interface Notification {
  id: string;
  notificationType: string;
  title: string;
  message: string;
  isRead: boolean;
  createdAt: string;
  data: any;
  relatedObjectType?: string;
  relatedObjectId?: string;
  actionUrl?: string;
  isBroadcast: boolean;
  broadcastTarget?: string;
}

export const NotificationScreen = () => {
  const navigation = useNavigation<NotificationScreenNavigationProp>();
  const [refreshing, setRefreshing] = useState(false);
  
  // Check if presale is globally active
  const { data: presaleStatusData } = useQuery(GET_PRESALE_STATUS, {
    fetchPolicy: 'cache-and-network',
  });
  const isPresaleActive = presaleStatusData?.isPresaleActive === true;

  // Query notifications
  const { data, loading, error, refetch, fetchMore } = useQuery(GET_NOTIFICATIONS, {
    variables: { first: 20 },
    fetchPolicy: 'cache-and-network',
  });

  // Mutations
  const [markNotificationRead] = useMutation(MARK_NOTIFICATION_READ, {
    refetchQueries: [{ query: GET_UNREAD_NOTIFICATION_COUNT }],
  });

  const [markAllRead] = useMutation(MARK_ALL_NOTIFICATIONS_READ, {
    refetchQueries: [
      { query: GET_NOTIFICATIONS, variables: { first: 20 } },
      { query: GET_UNREAD_NOTIFICATION_COUNT }
    ],
  });

  const notifications = data?.notifications?.edges?.map((edge: any) => edge.node) || [];
  const unreadCount = data?.notifications?.unreadCount || 0;
  const hasNextPage = data?.notifications?.pageInfo?.hasNextPage || false;

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    await refetch();
    setRefreshing(false);
  }, [refetch]);

  const handleNotificationPress = useCallback(async (notification: Notification) => {
    // Mark as read if not already
    if (!notification.isRead) {
      try {
        await markNotificationRead({
          variables: { notificationId: notification.id }
        });
      } catch (error) {
        console.error('Error marking notification as read:', error);
      }
    }

    // Handle navigation based on notification type or actionUrl
    if (notification.actionUrl) {
      // Parse deep link and navigate accordingly
      const url = notification.actionUrl;
      if (url.includes('p2p/trade/')) {
        const tradeId = url.split('p2p/trade/')[1];
        navigation.navigate('ActiveTrade', { 
          trade: { 
            id: tradeId 
          } 
        });
      } else if (url.includes('p2p/offer/')) {
        const offerId = url.split('p2p/offer/')[1];
        // Navigate to offer details or trade confirmation
      } else if (url.includes('transaction/')) {
        const transactionId = url.split('transaction/')[1];
        // Use the complete transaction data stored in the notification
        const transactionData = notification.data;
        
        console.log('[NotificationScreen] Navigating to transaction:', {
          transactionId,
          notificationType: notification.notificationType,
          hasData: !!transactionData,
          dataType: typeof transactionData,
          dataKeys: transactionData ? Object.keys(transactionData) : [],
          data: transactionData
        });
        
        // Navigate to TransactionDetail with complete data
        // The data field now contains all necessary fields for TransactionDetailScreen
        navigation.navigate('TransactionDetail', { 
          transactionType: transactionData?.transaction_type || 'send',
          transactionData: transactionData || { id: transactionId }
        });
      } else if (url.includes('business/')) {
        const businessId = url.split('business/')[1];
        // Navigate to business details
      }
    }
  }, [markNotificationRead, navigation]);

  const handleMarkAllAsRead = useCallback(async () => {
    try {
      await markAllRead();
      Alert.alert('Éxito', 'Todas las notificaciones han sido marcadas como leídas');
    } catch (error) {
      Alert.alert('Error', 'No se pudieron marcar las notificaciones como leídas');
    }
  }, [markAllRead]);

  const loadMore = useCallback(() => {
    if (hasNextPage && !loading) {
      fetchMore({
        variables: {
          first: 20,
          after: data?.notifications?.pageInfo?.endCursor,
        },
        updateQuery: (prev, { fetchMoreResult }) => {
          if (!fetchMoreResult) return prev;
          return {
            notifications: {
              ...fetchMoreResult.notifications,
              edges: [
                ...prev.notifications.edges,
                ...fetchMoreResult.notifications.edges,
              ],
            },
          };
        },
      });
    }
  }, [hasNextPage, loading, fetchMore, data]);

  const getNotificationIcon = (type: string) => {
    const iconMap: { [key: string]: { icon: string; color: string } } = {
      // Send transactions
      SEND_RECEIVED: { icon: 'download', color: '#10B981' },
      SEND_SENT: { icon: 'send', color: '#3B82F6' },
      SEND_INVITATION_SENT: { icon: 'user-plus', color: '#8B5CF6' },
      SEND_INVITATION_CLAIMED: { icon: 'user-check', color: '#10B981' },
      SEND_INVITATION_EXPIRED: { icon: 'user-x', color: '#EF4444' },
      SEND_FROM_EXTERNAL: { icon: 'download', color: '#06B6D4' },
      
      // Payment transactions
      PAYMENT_RECEIVED: { icon: 'credit-card', color: '#10B981' },
      PAYMENT_SENT: { icon: 'credit-card', color: '#3B82F6' },
      INVOICE_PAID: { icon: 'file-text', color: '#10B981' },
      
      // P2P Trade
      P2P_OFFER_RECEIVED: { icon: 'bell', color: '#F59E0B' },
      P2P_OFFER_ACCEPTED: { icon: 'check-circle', color: '#10B981' },
      P2P_TRADE_STARTED: { icon: 'refresh-cw', color: '#8B5CF6' },
      P2P_PAYMENT_CONFIRMED: { icon: 'check', color: '#10B981' },
      P2P_CRYPTO_RELEASED: { icon: 'unlock', color: '#10B981' },
      P2P_TRADE_COMPLETED: { icon: 'check-circle', color: '#10B981' },
      P2P_TRADE_CANCELLED: { icon: 'x-circle', color: '#EF4444' },
      P2P_TRADE_DISPUTED: { icon: 'alert-triangle', color: '#F59E0B' },
      
      // Conversion
      CONVERSION_COMPLETED: { icon: 'refresh-cw', color: '#8B5CF6' },
      CONVERSION_FAILED: { icon: 'x-circle', color: '#EF4444' },
      
      // USDC
      USDC_DEPOSIT_PENDING: { icon: 'clock', color: '#F59E0B' },
      USDC_DEPOSIT_COMPLETED: { icon: 'download', color: '#06B6D4' },
      USDC_WITHDRAWAL_COMPLETED: { icon: 'upload', color: '#06B6D4' },
      
      // Account & Security
      ACCOUNT_VERIFIED: { icon: 'user-check', color: '#10B981' },
      SECURITY_ALERT: { icon: 'shield', color: '#EF4444' },
      NEW_LOGIN: { icon: 'log-in', color: '#F59E0B' },
      
      // Business
      BUSINESS_EMPLOYEE_ADDED: { icon: 'users', color: '#8B5CF6' },
      BUSINESS_PERMISSION_CHANGED: { icon: 'settings', color: '#F59E0B' },
      
      // General
      PROMOTION: { icon: 'gift', color: '#EC4899' },
      SYSTEM: { icon: 'info', color: '#6B7280' },
      ANNOUNCEMENT: { icon: 'bell', color: '#3B82F6' },
    };
    
    return iconMap[type] || { icon: 'bell', color: '#6B7280' };
  };

  const formatTime = (dateString: string) => {
    moment.locale('es');
    const date = moment.utc(dateString).local();
    const now = moment();
    const diffInHours = now.diff(date, 'hours');
    
    if (diffInHours < 24) {
      return date.fromNow();
    } else {
      return date.format('DD MMM YYYY');
    }
  };

  // Helper function to replace names in notification text with contact names
  const replaceWithContactNames = useCallback((text: string, data: any): string => {
    let processedText = text;
    
    // Parse data if it's a string
    let parsedData = data;
    if (typeof data === 'string') {
      try {
        parsedData = JSON.parse(data);
      } catch (e) {
        console.warn('Failed to parse notification data:', e);
        return text;
      }
    }
    
    // Try to extract phone numbers and names from notification data
    if (parsedData) {
      try {
        // For send notifications - received
        if (parsedData.sender_phone && parsedData.sender_name) {
          const senderContact = contactService.getContactByPhoneSync(parsedData.sender_phone);
          if (senderContact) {
            processedText = processedText.replace(parsedData.sender_name, senderContact.name);
          }
        }
        
        // For send notifications - sent
        if (parsedData.recipient_phone && parsedData.recipient_name) {
          const recipientContact = contactService.getContactByPhoneSync(parsedData.recipient_phone);
          if (recipientContact) {
            processedText = processedText.replace(parsedData.recipient_name, recipientContact.name);
          }
        }
        
        // For invitation notifications - replace phone number in message
        if (parsedData.recipient_phone) {
          const recipientContact = contactService.getContactByPhoneSync(parsedData.recipient_phone);
          if (recipientContact) {
            // Replace phone number with contact name in the message
            processedText = processedText.replace(parsedData.recipient_phone, recipientContact.name);
          } else if (parsedData.recipient_name && parsedData.recipient_name !== parsedData.recipient_phone) {
            // If we have a recipient_name that's different from the phone, use it
            processedText = processedText.replace(parsedData.recipient_phone, parsedData.recipient_name);
          }
        }
        
        // For P2P notifications
        if (parsedData.trader_phone && parsedData.trader_name) {
          const traderContact = contactService.getContactByPhoneSync(parsedData.trader_phone);
          if (traderContact) {
            processedText = processedText.replace(parsedData.trader_name, traderContact.name);
          }
        }
        
        if (parsedData.counterparty_phone && parsedData.counterparty_name) {
          const counterpartyContact = contactService.getContactByPhoneSync(parsedData.counterparty_phone);
          if (counterpartyContact) {
            processedText = processedText.replace(parsedData.counterparty_name, counterpartyContact.name);
          }
        }
      } catch (error) {
        console.error('Error getting contact names:', error);
      }
    }
    
    return processedText;
  }, []);

  const renderNotification = ({ item }: { item: Notification }) => {
    const { icon, color } = getNotificationIcon(item.notificationType);
    
    // Process title and message to replace with contact names
    const processedTitle = replaceWithContactNames(item.title, item.data);
    const processedMessage = replaceWithContactNames(item.message, item.data);
    
    return (
      <TouchableOpacity
        style={[
          styles.notificationItem,
          !item.isRead && styles.unreadNotification
        ]}
        onPress={() => handleNotificationPress(item)}
      >
        <View style={[styles.notificationIcon, { backgroundColor: `${color}20` }]}>
          <Icon name={icon as any} size={20} color={color} />
        </View>
        <View style={styles.notificationContent}>
          <View style={styles.notificationHeader}>
            <Text style={[
              styles.notificationTitle,
              !item.isRead && styles.unreadTitle
            ]}>
              {processedTitle}
            </Text>
            {!item.isRead && (
              <View style={styles.unreadDot} />
            )}
          </View>
          <Text style={styles.notificationMessage}>
            {processedMessage}
          </Text>
          <Text style={styles.notificationTime}>
            {formatTime(item.createdAt)}
          </Text>
        </View>
      </TouchableOpacity>
    );
  };

  const ListHeader = () => (
    <>
      {/* Pending Employee Invitations */}
      <PendingInvitationBanner />
      
      {/* CONFIO Presale Banner - Only show if presale is active */}
      {isPresaleActive && (
        <View style={styles.presaleBanner}>
          <TouchableOpacity 
            style={styles.presaleBannerContent}
            onPress={() => navigation.navigate('ConfioPresale')}
            activeOpacity={0.9}
          >
            <View style={styles.presaleBannerLeft}>
              <View style={styles.presaleBadge}>
                <Text style={styles.presaleBadgeText}>🚀 PREVENTA</Text>
              </View>
              <Text style={styles.presaleBannerTitle}>Preventa Exclusiva de $CONFIO</Text>
              <Text style={styles.presaleBannerSubtitle}>
                Únete ahora y obtén acceso anticipado a las monedas $CONFIO
              </Text>
            </View>
            <View style={styles.presaleBannerRight}>
              <Image source={CONFIOLogo} style={styles.presaleBannerLogo} />
              <Icon name="chevron-right" size={20} color="#8b5cf6" />
            </View>
          </TouchableOpacity>
        </View>
      )}
    </>
  );

  const EmptyState = () => (
    <View style={styles.emptyState}>
      <Icon name="bell" size={64} color="#D1D5DB" />
      <Text style={styles.emptyTitle}>No tienes notificaciones</Text>
      <Text style={styles.emptySubtitle}>
        Cuando tengas nuevas notificaciones aparecerán aquí
      </Text>
    </View>
  );

  const ListFooter = () => {
    if (loading && notifications.length > 0) {
      return (
        <View style={styles.loadingFooter}>
          <ActivityIndicator size="small" color="#34d399" />
        </View>
      );
    }
    return null;
  };

  if (loading && notifications.length === 0) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity 
            style={styles.backButton}
            onPress={() => navigation.goBack()}
          >
            <Icon name="arrow-left" size={20} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Notificaciones</Text>
        </View>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#34d399" />
        </View>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity 
            style={styles.backButton}
            onPress={() => navigation.goBack()}
          >
            <Icon name="arrow-left" size={20} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Notificaciones</Text>
        </View>
        <View style={styles.errorContainer}>
          <Icon name="alert-circle" size={48} color="#EF4444" />
          <Text style={styles.errorText}>Error al cargar notificaciones</Text>
          <TouchableOpacity style={styles.retryButton} onPress={() => refetch()}>
            <Text style={styles.retryText}>Reintentar</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity 
          style={styles.backButton}
          onPress={() => navigation.goBack()}
        >
          <Icon name="arrow-left" size={20} color="#fff" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Notificaciones</Text>
      </View>

      {/* Notifications List */}
      <FlatList
        data={notifications}
        renderItem={renderNotification}
        keyExtractor={(item) => item.id}
        ListHeaderComponent={ListHeader}
        ListEmptyComponent={EmptyState}
        ListFooterComponent={ListFooter}
        onEndReached={loadMore}
        onEndReachedThreshold={0.5}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={handleRefresh}
            tintColor="#34d399"
          />
        }
        contentContainerStyle={notifications.length === 0 ? styles.emptyContainer : undefined}
      />

      {/* Mark all as read button */}
      {unreadCount > 0 && (
        <View style={styles.markAllContainer}>
          <TouchableOpacity 
            style={styles.markAllButton}
            onPress={handleMarkAllAsRead}
          >
            <Text style={styles.markAllText}>
              Marcar todas como leídas ({unreadCount})
            </Text>
          </TouchableOpacity>
        </View>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  header: {
    backgroundColor: '#34d399',
    paddingTop: Platform.OS === 'ios' ? 48 : (StatusBar.currentHeight || 32),
    paddingBottom: 16,
    paddingHorizontal: 20,
    flexDirection: 'row',
    alignItems: 'center',
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.2)',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#fff',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 40,
  },
  errorText: {
    fontSize: 16,
    color: '#6B7280',
    marginTop: 16,
    marginBottom: 24,
  },
  retryButton: {
    backgroundColor: '#34d399',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 8,
  },
  retryText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  emptyContainer: {
    flexGrow: 1,
  },
  emptyState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 40,
    paddingTop: 100,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#6B7280',
    marginTop: 16,
    marginBottom: 8,
  },
  emptySubtitle: {
    fontSize: 14,
    color: '#9CA3AF',
    textAlign: 'center',
    lineHeight: 20,
  },
  notificationItem: {
    flexDirection: 'row',
    paddingVertical: 16,
    paddingHorizontal: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#F3F4F6',
  },
  unreadNotification: {
    backgroundColor: '#EFF6FF',
  },
  notificationIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  notificationContent: {
    flex: 1,
  },
  notificationHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 4,
  },
  notificationTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6B7280',
    flex: 1,
  },
  unreadTitle: {
    color: '#1F2937',
  },
  unreadDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#3B82F6',
    marginLeft: 8,
    marginTop: 2,
  },
  notificationMessage: {
    fontSize: 13,
    color: '#6B7280',
    lineHeight: 18,
    marginBottom: 4,
  },
  notificationTime: {
    fontSize: 12,
    color: '#9CA3AF',
  },
  markAllContainer: {
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderTopWidth: 1,
    borderTopColor: '#E5E7EB',
    backgroundColor: '#F9FAFB',
  },
  markAllButton: {
    backgroundColor: '#34d399',
    paddingVertical: 12,
    borderRadius: 12,
    alignItems: 'center',
  },
  markAllText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  loadingFooter: {
    paddingVertical: 20,
    alignItems: 'center',
  },
  // CONFIO Presale Banner styles
  presaleBanner: {
    marginHorizontal: 16,
    marginVertical: 12,
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
});