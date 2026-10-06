import React, { useCallback } from 'react';
import { StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useMutation, useQuery } from '@apollo/client';
import { NavigationProp, useNavigation } from '@react-navigation/native';

import { GET_NOTIFICATION_PREFERENCES } from '../apollo/queries';
import { UPDATE_NOTIFICATION_PREFERENCES } from '../apollo/mutations';
import { useAuth } from '../contexts/AuthContext';
import { RootStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { useCommunityComposeEntry } from '../hooks/useCommunityComposeEntry';
import { Header } from './Header';

// Descubrir shares its announcement controls between tab and stack entry.

export const DiscoverStackHeader = ({ showBackButton = true }: { showBackButton?: boolean }) => {
  const navigation = useNavigation<NavigationProp<RootStackParamList>>();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { data } = useQuery(GET_NOTIFICATION_PREFERENCES, {
    skip: !isAuthenticated || authLoading,
  });
  const [updateNotificationPreferences] = useMutation(UPDATE_NOTIFICATION_PREFERENCES);
  const muted = !data?.notificationPreferences?.pushAnnouncements;
  // Always-reachable way to post to Comunidad, even deep in the feed.
  const canCompose = useCommunityComposeEntry(isAuthenticated && !authLoading);
  const toggleMute = useCallback(() => {
    void updateNotificationPreferences({ variables: { pushAnnouncements: muted } });
  }, [muted, updateNotificationPreferences]);

  return (
    <Header
      navigation={navigation}
      isHomeScreen={false}
      title="Descubrir"
      backgroundColor="#fff"
      showBackButton={showBackButton}
      isLight={false}
      unreadNotifications={0}
      currentAccountAvatar="U"
      rightAccessory={(
        <View style={styles.headerActions}>
          {canCompose ? (
            <TouchableOpacity
              onPress={() => (navigation as any).navigate('CommunityCompose')}
              style={styles.headerIconButton}
              hitSlop={{ top: 4, bottom: 4, left: 4, right: 4 }}
              accessibilityRole="button"
              accessibilityLabel="Publicar en Comunidad"
            >
              <Icon name="edit-3" size={16} color={colors.primaryDark} />
            </TouchableOpacity>
          ) : null}
        <TouchableOpacity
          onPress={toggleMute}
          style={[styles.headerIconButton, muted && styles.headerIconButtonActive]}
          hitSlop={{ top: 4, bottom: 4, left: 4, right: 4 }}
          accessibilityRole="button"
          accessibilityLabel={muted ? 'Activar anuncios' : 'Silenciar anuncios'}
        >
          <Icon name={muted ? 'volume-x' : 'bell-off'} size={16} color={muted ? '#FFFFFF' : '#667085'} />
        </TouchableOpacity>
        </View>
      )}
    />
  );
};

export const SendStackHeader = () => {
  const navigation = useNavigation<NavigationProp<RootStackParamList>>();
  return (
    <Header
      navigation={navigation}
      isHomeScreen={false}
      title="Enviar"
      backgroundColor="#fff"
      showBackButton
      isLight={false}
      unreadNotifications={0}
      currentAccountAvatar="U"
    />
  );
};

// Recibir mirrors Enviar exactly: same header, only the title differs.
export const ReceiveStackHeader = () => {
  const navigation = useNavigation<NavigationProp<RootStackParamList>>();
  return (
    <Header
      navigation={navigation}
      isHomeScreen={false}
      title="Recibir"
      backgroundColor="#fff"
      showBackButton
      isLight={false}
      unreadNotifications={0}
      currentAccountAvatar="U"
    />
  );
};

const styles = StyleSheet.create({
  headerActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  headerIconButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerIconButtonActive: {
    backgroundColor: '#111827',
    borderColor: '#111827',
  },
});
