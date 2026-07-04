import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Switch,
  TouchableOpacity,
  Alert,
  ActivityIndicator,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useQuery, useMutation } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import notifee, { AndroidImportance } from '@notifee/react-native';
import messagingService from '../services/messagingService';
import {
  UPDATE_NOTIFICATION_PREFERENCES,
  SEND_TEST_PUSH_NOTIFICATION,
} from '../graphql/mutations/notifications';
import { GET_NOTIFICATION_PREFERENCES } from '../graphql/queries/notifications';
import { colors } from '../config/theme';
import { InlineBanner } from '../components/common/InlineBanner';

const NotificationSettingsScreen: React.FC = () => {
  const [systemNotificationsEnabled, setSystemNotificationsEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [banner, setBanner] = useState<{ message: string; variant: 'error' | 'success' } | null>(null);
  const dismissBanner = React.useCallback(() => setBanner(null), []);

  const { data, loading: queryLoading, refetch } = useQuery(GET_NOTIFICATION_PREFERENCES);
  const [updatePreferences] = useMutation(UPDATE_NOTIFICATION_PREFERENCES);
  const [sendTestPush] = useMutation(SEND_TEST_PUSH_NOTIFICATION);

  const preferences = data?.notificationPreferences || {};

  useEffect(() => {
    checkSystemPermissions();
  }, []);

  const checkSystemPermissions = async () => {
    const enabled = await messagingService.areNotificationsEnabled();
    setSystemNotificationsEnabled(enabled);
    setLoading(false);
  };

  const handleSystemToggle = async () => {
    if (!systemNotificationsEnabled) {
      const granted = await messagingService.requestPermissions();
      if (granted) {
        setSystemNotificationsEnabled(true);
        setBanner({ variant: 'success', message: 'Notificaciones activadas' });
      } else {
        Alert.alert(
          'Permiso denegado',
          'Activa las notificaciones en la configuración de tu dispositivo para recibir avisos.',
          [
            { text: 'Cancelar', style: 'cancel' },
            { text: 'Abrir configuración', onPress: () => {
              // Open system settings
              // Linking.openSettings();
            }},
          ]
        );
      }
    } else {
      Alert.alert(
        'Desactivar notificaciones',
        'Para desactivar las notificaciones, ve a la configuración de tu dispositivo.',
        [
          { text: 'Entendido' },
          { text: 'Abrir configuración', onPress: () => {
            // Open system settings
            // Linking.openSettings();
          }},
        ]
      );
    }
  };

  const handlePreferenceToggle = async (key: string, value: boolean) => {
    try {
      await updatePreferences({
        variables: { [key]: value },
        optimisticResponse: {
          updateNotificationPreferences: {
            success: true,
            preferences: {
              ...preferences,
              [key]: value,
            },
          },
        },
      });
    } catch (error) {
      setBanner({ variant: 'error', message: 'No se pudieron actualizar tus preferencias. Intenta de nuevo.' });
    }
  };

  const handleSendTestNotification = async () => {
    try {
      const result = await sendTestPush();
      if (result.data?.sendTestPushNotification?.success) {
        setBanner({ variant: 'success', message: 'Notificación de prueba enviada' });
      } else {
        setBanner({ variant: 'error', message: 'No se pudo enviar la notificación de prueba' });
      }
    } catch (error) {
      setBanner({ variant: 'error', message: 'No se pudo enviar la notificación de prueba' });
    }
  };

  const handleTestLocalNotification = async () => {
    try {
      // Create channel first for Android
      if (Platform.OS === 'android') {
        await notifee.createChannel({
          id: 'default',
          name: 'Default Channel',
          importance: AndroidImportance.HIGH,
        });
      }
      
      // Test local notification with Notifee
      await notifee.displayNotification({
        title: 'Notificación de prueba',
        body: 'Esta es una notificación de prueba de Confío',
        android: {
          channelId: 'default',
          smallIcon: 'ic_stat_ic_notification',
          color: '#8b5cf6',  // Confío violet accent color
          pressAction: {
            id: 'default',
          },
        },
        ios: {
          foregroundPresentationOptions: {
            badge: true,
            sound: true,
            banner: true,
          },
        },
      });
      setBanner({ variant: 'success', message: 'Notificación local mostrada' });
    } catch (error) {
      setBanner({ variant: 'error', message: 'No se pudo mostrar la notificación local' });
    }
  };

  if (loading || queryLoading) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.secondary} />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        {banner && (
          <InlineBanner
            message={banner.message}
            variant={banner.variant}
            onDismiss={dismissBanner}
            autoHideMs={banner.variant === 'success' ? 2500 : undefined}
            style={{ marginHorizontal: 16, marginTop: 12, marginBottom: 0 }}
          />
        )}
        <View style={styles.header}>
          <Text style={styles.title}>Notificaciones</Text>
          <Text style={styles.subtitle}>
            Controla cómo recibes las notificaciones de Confío
          </Text>
        </View>

        {/* System Notifications */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="bell" size={24} color="#333" />
            <Text style={styles.sectionTitle}>Notificaciones del sistema</Text>
          </View>
          
          <View style={styles.settingRow}>
            <View style={styles.settingInfo}>
              <Text style={styles.settingLabel}>Notificaciones push</Text>
              <Text style={styles.settingDescription}>
                Recibe notificaciones aunque la app esté cerrada
              </Text>
            </View>
            <Switch
              value={systemNotificationsEnabled}
              onValueChange={handleSystemToggle}
              trackColor={{ false: '#E0E0E0', true: colors.violetLight }}
              thumbColor={systemNotificationsEnabled ? colors.secondary : '#f4f3f4'}
            />
          </View>
        </View>

        {/* Push Notification Categories */}
        {systemNotificationsEnabled && (
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Icon name="sliders" size={24} color="#333" />
              <Text style={styles.sectionTitle}>Categorías de notificaciones</Text>
            </View>
            
            <View style={styles.settingRow}>
              <View style={styles.settingInfo}>
                <Text style={styles.settingLabel}>Todas las notificaciones push</Text>
                <Text style={styles.settingDescription}>
                  Interruptor general para todas las notificaciones push
                </Text>
              </View>
              <Switch
                value={preferences.pushEnabled}
                onValueChange={(value) => handlePreferenceToggle('pushEnabled', value)}
                trackColor={{ false: '#E0E0E0', true: colors.violetLight }}
                thumbColor={preferences.pushEnabled ? colors.secondary : '#f4f3f4'}
              />
            </View>

            {preferences.pushEnabled && (
              <>
                <View style={styles.settingRow}>
                  <View style={styles.settingInfo}>
                    <Text style={styles.settingLabel}>Transacciones</Text>
                    <Text style={styles.settingDescription}>
                      Pagos enviados, recibidos y conversiones
                    </Text>
                  </View>
                  <Switch
                    value={preferences.pushTransactions}
                    onValueChange={(value) => handlePreferenceToggle('pushTransactions', value)}
                    trackColor={{ false: '#E0E0E0', true: colors.violetLight }}
                    thumbColor={preferences.pushTransactions ? colors.secondary : '#f4f3f4'}
                  />
                </View>

                <View style={styles.settingRow}>
                  <View style={styles.settingInfo}>
                    <Text style={styles.settingLabel}>Intercambio P2P</Text>
                    <Text style={styles.settingDescription}>
                      Actualizaciones de intercambios, ofertas y disputas
                    </Text>
                  </View>
                  <Switch
                    value={preferences.pushP2p}
                    onValueChange={(value) => handlePreferenceToggle('pushP2p', value)}
                    trackColor={{ false: '#E0E0E0', true: colors.violetLight }}
                    thumbColor={preferences.pushP2p ? colors.secondary : '#f4f3f4'}
                  />
                </View>

                <View style={styles.settingRow}>
                  <View style={styles.settingInfo}>
                    <Text style={styles.settingLabel}>Alertas de seguridad</Text>
                    <Text style={styles.settingDescription}>
                      Intentos de inicio de sesión y avisos de seguridad
                    </Text>
                  </View>
                  <Switch
                    value={preferences.pushSecurity}
                    onValueChange={(value) => handlePreferenceToggle('pushSecurity', value)}
                    trackColor={{ false: '#E0E0E0', true: colors.violetLight }}
                    thumbColor={preferences.pushSecurity ? colors.secondary : '#f4f3f4'}
                  />
                </View>

                <View style={styles.settingRow}>
                  <View style={styles.settingInfo}>
                    <Text style={styles.settingLabel}>Promociones</Text>
                    <Text style={styles.settingDescription}>
                      Ofertas especiales y recompensas
                    </Text>
                  </View>
                  <Switch
                    value={preferences.pushPromotions}
                    onValueChange={(value) => handlePreferenceToggle('pushPromotions', value)}
                    trackColor={{ false: '#E0E0E0', true: colors.violetLight }}
                    thumbColor={preferences.pushPromotions ? colors.secondary : '#f4f3f4'}
                  />
                </View>

                <View style={styles.settingRow}>
                  <View style={styles.settingInfo}>
                    <Text style={styles.settingLabel}>Anuncios</Text>
                    <Text style={styles.settingDescription}>
                      Novedades y actualizaciones de Confío
                    </Text>
                  </View>
                  <Switch
                    value={preferences.pushAnnouncements}
                    onValueChange={(value) => handlePreferenceToggle('pushAnnouncements', value)}
                    trackColor={{ false: '#E0E0E0', true: colors.violetLight }}
                    thumbColor={preferences.pushAnnouncements ? colors.secondary : '#f4f3f4'}
                  />
                </View>
              </>
            )}
          </View>
        )}

        {/* In-App Notifications */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="smartphone" size={24} color="#333" />
            <Text style={styles.sectionTitle}>Notificaciones en la app</Text>
          </View>
          
          <View style={styles.settingRow}>
            <View style={styles.settingInfo}>
              <Text style={styles.settingLabel}>Todas las notificaciones en la app</Text>
              <Text style={styles.settingDescription}>
                Notificaciones que se muestran mientras usas la app
              </Text>
            </View>
            <Switch
              value={preferences.inAppEnabled}
              onValueChange={(value) => handlePreferenceToggle('inAppEnabled', value)}
              trackColor={{ false: '#E0E0E0', true: colors.violetLight }}
              thumbColor={preferences.inAppEnabled ? colors.secondary : '#f4f3f4'}
            />
          </View>
        </View>

        {/* Test Notifications */}
        {systemNotificationsEnabled && (
          <>
            {preferences.pushEnabled && (
              <TouchableOpacity
                style={styles.testButton}
                onPress={handleSendTestNotification}
              >
                <Icon name="send" size={20} color="#FFF" />
                <Text style={styles.testButtonText}>Enviar notificación de prueba</Text>
              </TouchableOpacity>
            )}
            
            <TouchableOpacity
              style={[styles.testButton, { backgroundColor: colors.primaryLight, marginTop: 10 }]}
              onPress={handleTestLocalNotification}
            >
              <Icon name="bell" size={20} color="#000" />
              <Text style={[styles.testButtonText, { color: '#000' }]}>Probar notificación local</Text>
            </TouchableOpacity>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F8F9FA',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  scrollContent: {
    paddingBottom: 30,
  },
  header: {
    padding: 20,
    backgroundColor: '#FFF',
    borderBottomWidth: 1,
    borderBottomColor: '#E0E0E0',
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#333',
    marginBottom: 5,
  },
  subtitle: {
    fontSize: 14,
    color: '#666',
  },
  section: {
    marginTop: 20,
    backgroundColor: '#FFF',
    paddingVertical: 10,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#F0F0F0',
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#333',
    marginLeft: 10,
  },
  settingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 15,
    borderBottomWidth: 1,
    borderBottomColor: '#F8F8F8',
  },
  settingInfo: {
    flex: 1,
    marginRight: 10,
  },
  settingLabel: {
    fontSize: 16,
    color: '#333',
    marginBottom: 3,
  },
  settingDescription: {
    fontSize: 13,
    color: '#666',
  },
  testButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#8b5cf6',
    marginHorizontal: 20,
    marginTop: 30,
    paddingVertical: 15,
    borderRadius: 10,
  },
  testButtonText: {
    color: '#FFF',
    fontSize: 16,
    fontWeight: '600',
    marginLeft: 8,
  },
});

export default NotificationSettingsScreen;