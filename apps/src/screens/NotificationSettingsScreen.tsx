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
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useQuery, useMutation } from '@apollo/client';
import Icon from 'react-native-vector-icons/Ionicons';
import messagingService from '../services/messagingService';
import {
  UPDATE_NOTIFICATION_PREFERENCES,
  SEND_TEST_PUSH_NOTIFICATION,
} from '../graphql/mutations/notifications';
import { GET_NOTIFICATION_PREFERENCES } from '../graphql/queries/notifications';

const NotificationSettingsScreen: React.FC = () => {
  const [systemNotificationsEnabled, setSystemNotificationsEnabled] = useState(false);
  const [loading, setLoading] = useState(true);

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
        Alert.alert('Success', 'Push notifications enabled');
      } else {
        Alert.alert(
          'Permission Denied',
          'Please enable notifications in your device settings to receive push notifications.',
          [
            { text: 'Cancel', style: 'cancel' },
            { text: 'Open Settings', onPress: () => {
              // Open system settings
              // Linking.openSettings();
            }},
          ]
        );
      }
    } else {
      Alert.alert(
        'Disable Notifications',
        'To disable notifications, please go to your device settings.',
        [
          { text: 'OK' },
          { text: 'Open Settings', onPress: () => {
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
      console.error('Error updating preference:', error);
      Alert.alert('Error', 'Failed to update notification preferences');
    }
  };

  const handleSendTestNotification = async () => {
    try {
      const result = await sendTestPush();
      if (result.data?.sendTestPushNotification?.success) {
        Alert.alert('Success', 'Test notification sent successfully');
      } else {
        Alert.alert('Error', 'Failed to send test notification');
      }
    } catch (error) {
      console.error('Error sending test notification:', error);
      Alert.alert('Error', 'Failed to send test notification');
    }
  };

  if (loading || queryLoading) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#6200EA" />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        <View style={styles.header}>
          <Text style={styles.title}>Notification Settings</Text>
          <Text style={styles.subtitle}>
            Manage how you receive notifications from Confío
          </Text>
        </View>

        {/* System Notifications */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="notifications-outline" size={24} color="#333" />
            <Text style={styles.sectionTitle}>System Notifications</Text>
          </View>
          
          <View style={styles.settingRow}>
            <View style={styles.settingInfo}>
              <Text style={styles.settingLabel}>Push Notifications</Text>
              <Text style={styles.settingDescription}>
                Receive notifications even when the app is closed
              </Text>
            </View>
            <Switch
              value={systemNotificationsEnabled}
              onValueChange={handleSystemToggle}
              trackColor={{ false: '#E0E0E0', true: '#B39DDB' }}
              thumbColor={systemNotificationsEnabled ? '#6200EA' : '#f4f3f4'}
            />
          </View>
        </View>

        {/* Push Notification Categories */}
        {systemNotificationsEnabled && (
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Icon name="options-outline" size={24} color="#333" />
              <Text style={styles.sectionTitle}>Push Notification Categories</Text>
            </View>
            
            <View style={styles.settingRow}>
              <View style={styles.settingInfo}>
                <Text style={styles.settingLabel}>All Push Notifications</Text>
                <Text style={styles.settingDescription}>
                  Master switch for all push notifications
                </Text>
              </View>
              <Switch
                value={preferences.pushEnabled}
                onValueChange={(value) => handlePreferenceToggle('pushEnabled', value)}
                trackColor={{ false: '#E0E0E0', true: '#B39DDB' }}
                thumbColor={preferences.pushEnabled ? '#6200EA' : '#f4f3f4'}
              />
            </View>

            {preferences.pushEnabled && (
              <>
                <View style={styles.settingRow}>
                  <View style={styles.settingInfo}>
                    <Text style={styles.settingLabel}>Transactions</Text>
                    <Text style={styles.settingDescription}>
                      Payments sent, received, and conversions
                    </Text>
                  </View>
                  <Switch
                    value={preferences.pushTransactions}
                    onValueChange={(value) => handlePreferenceToggle('pushTransactions', value)}
                    trackColor={{ false: '#E0E0E0', true: '#B39DDB' }}
                    thumbColor={preferences.pushTransactions ? '#6200EA' : '#f4f3f4'}
                  />
                </View>

                <View style={styles.settingRow}>
                  <View style={styles.settingInfo}>
                    <Text style={styles.settingLabel}>P2P Trading</Text>
                    <Text style={styles.settingDescription}>
                      Trade updates, offers, and disputes
                    </Text>
                  </View>
                  <Switch
                    value={preferences.pushP2p}
                    onValueChange={(value) => handlePreferenceToggle('pushP2p', value)}
                    trackColor={{ false: '#E0E0E0', true: '#B39DDB' }}
                    thumbColor={preferences.pushP2p ? '#6200EA' : '#f4f3f4'}
                  />
                </View>

                <View style={styles.settingRow}>
                  <View style={styles.settingInfo}>
                    <Text style={styles.settingLabel}>Security Alerts</Text>
                    <Text style={styles.settingDescription}>
                      Login attempts and security notifications
                    </Text>
                  </View>
                  <Switch
                    value={preferences.pushSecurity}
                    onValueChange={(value) => handlePreferenceToggle('pushSecurity', value)}
                    trackColor={{ false: '#E0E0E0', true: '#B39DDB' }}
                    thumbColor={preferences.pushSecurity ? '#6200EA' : '#f4f3f4'}
                  />
                </View>

                <View style={styles.settingRow}>
                  <View style={styles.settingInfo}>
                    <Text style={styles.settingLabel}>Promotions</Text>
                    <Text style={styles.settingDescription}>
                      Special offers and rewards
                    </Text>
                  </View>
                  <Switch
                    value={preferences.pushPromotions}
                    onValueChange={(value) => handlePreferenceToggle('pushPromotions', value)}
                    trackColor={{ false: '#E0E0E0', true: '#B39DDB' }}
                    thumbColor={preferences.pushPromotions ? '#6200EA' : '#f4f3f4'}
                  />
                </View>

                <View style={styles.settingRow}>
                  <View style={styles.settingInfo}>
                    <Text style={styles.settingLabel}>Announcements</Text>
                    <Text style={styles.settingDescription}>
                      Platform updates and news
                    </Text>
                  </View>
                  <Switch
                    value={preferences.pushAnnouncements}
                    onValueChange={(value) => handlePreferenceToggle('pushAnnouncements', value)}
                    trackColor={{ false: '#E0E0E0', true: '#B39DDB' }}
                    thumbColor={preferences.pushAnnouncements ? '#6200EA' : '#f4f3f4'}
                  />
                </View>
              </>
            )}
          </View>
        )}

        {/* In-App Notifications */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="phone-portrait-outline" size={24} color="#333" />
            <Text style={styles.sectionTitle}>In-App Notifications</Text>
          </View>
          
          <View style={styles.settingRow}>
            <View style={styles.settingInfo}>
              <Text style={styles.settingLabel}>All In-App Notifications</Text>
              <Text style={styles.settingDescription}>
                Notifications shown while using the app
              </Text>
            </View>
            <Switch
              value={preferences.inAppEnabled}
              onValueChange={(value) => handlePreferenceToggle('inAppEnabled', value)}
              trackColor={{ false: '#E0E0E0', true: '#B39DDB' }}
              thumbColor={preferences.inAppEnabled ? '#6200EA' : '#f4f3f4'}
            />
          </View>
        </View>

        {/* Test Notification */}
        {systemNotificationsEnabled && preferences.pushEnabled && (
          <TouchableOpacity
            style={styles.testButton}
            onPress={handleSendTestNotification}
          >
            <Icon name="send-outline" size={20} color="#FFF" />
            <Text style={styles.testButtonText}>Send Test Notification</Text>
          </TouchableOpacity>
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
    backgroundColor: '#6200EA',
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