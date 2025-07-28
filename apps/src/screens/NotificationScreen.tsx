import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Alert, Platform, StatusBar } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { PendingInvitationBanner } from '../components/PendingInvitationBanner';

type NotificationScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

interface Notification {
  id: number;
  type: 'envio' | 'recibo' | 'intercambio' | 'verificacion' | 'seguridad';
  title: string;
  message: string;
  time: string;
  read: boolean;
  icon: string;
  iconColor: string;
}

export const NotificationScreen = () => {
  const navigation = useNavigation<NotificationScreenNavigationProp>();
  const [notifications, setNotifications] = useState<Notification[]>([
    {
      id: 1,
      type: "envio",
      title: "Envio completado",
      message: "Enviaste $125.50 cUSD a Evelyn",
      time: "Hace 5 min",
      read: false,
      icon: "send",
      iconColor: "#3B82F6"
    },
    {
      id: 2,
      type: "recibo",
      title: "Pago recibido", 
      message: "Recibiste $80.00 cUSD de Julian",
      time: "Hace 15 min",
      read: false,
      icon: "download",
      iconColor: "#10B981"
    },
    {
      id: 3,
      type: "intercambio",
      title: "Intercambio exitoso",
      message: "Compraste 100.00 cUSD por 3,600.00 Bs.",
      time: "Hace 1 hora", 
      read: true,
      icon: "refresh-cw",
      iconColor: "#8B5CF6"
    },
    {
      id: 4,
      type: "verificacion",
      title: "Verificacion pendiente",
      message: "Complete su verificacion de identidad",
      time: "Hace 1 dia",
      read: false,
      icon: "user-check",
      iconColor: "#F97316"
    },
    {
      id: 5,
      type: "seguridad",
      title: "Nuevo dispositivo detectado",
      message: "Acceso desde iPhone 14 - Caracas, Venezuela",
      time: "Hace 2 dias",
      read: true,
      icon: "shield",
      iconColor: "#CA8A04"
    }
  ]);

  const unreadNotifications = notifications.filter(n => !n.read).length;

  const handleNotificationPress = (notification: Notification) => {
    if (!notification.read) {
      setNotifications(prev => 
        prev.map(n => 
          n.id === notification.id ? { ...n, read: true } : n
        )
      );
    }
  };

  const markAllAsRead = () => {
    setNotifications(prev => 
      prev.map(n => ({ ...n, read: true }))
    );
  };

  const getNotificationIcon = (icon: string, color: string) => {
    return <Icon name={icon as any} size={20} color={color} />;
  };

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
      <ScrollView style={styles.notificationsList} showsVerticalScrollIndicator={false}>
        {/* Pending Employee Invitations */}
        <PendingInvitationBanner />
        
        {notifications.length === 0 ? (
          <View style={styles.emptyState}>
            <Icon name="bell" size={64} color="#D1D5DB" />
            <Text style={styles.emptyTitle}>No tienes notificaciones</Text>
            <Text style={styles.emptySubtitle}>
              Cuando tengas nuevas notificaciones apareceran aqui
            </Text>
          </View>
        ) : (
          <View style={styles.notificationsContainer}>
            {notifications.map((notification) => (
              <TouchableOpacity
                key={notification.id}
                style={[
                  styles.notificationItem,
                  !notification.read && styles.unreadNotification
                ]}
                onPress={() => handleNotificationPress(notification)}
              >
                <View style={styles.notificationIcon}>
                  {getNotificationIcon(notification.icon, notification.iconColor)}
                </View>
                <View style={styles.notificationContent}>
                  <View style={styles.notificationHeader}>
                    <Text style={[
                      styles.notificationTitle,
                      !notification.read && styles.unreadTitle
                    ]}>
                      {notification.title}
                    </Text>
                    {!notification.read && (
                      <View style={styles.unreadDot} />
                    )}
                  </View>
                  <Text style={styles.notificationMessage}>
                    {notification.message}
                  </Text>
                  <Text style={styles.notificationTime}>
                    {notification.time}
                  </Text>
                </View>
              </TouchableOpacity>
            ))}
          </View>
        )}
      </ScrollView>

      {/* Mark all as read button */}
      {unreadNotifications > 0 && (
        <View style={styles.markAllContainer}>
          <TouchableOpacity 
            style={styles.markAllButton}
            onPress={markAllAsRead}
          >
            <Text style={styles.markAllText}>
              Marcar todas como leidas ({unreadNotifications})
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
  notificationsList: {
    flex: 1,
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
  notificationsContainer: {
    // Remove horizontal padding to allow background to fill completely
  },
  notificationItem: {
    flexDirection: 'row',
    paddingVertical: 16,
    paddingHorizontal: 20, // Add horizontal padding here instead
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
    backgroundColor: '#F3F4F6',
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
}); 