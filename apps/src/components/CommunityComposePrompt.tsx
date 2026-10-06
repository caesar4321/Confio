import React, { useState } from 'react';
import { Image, Pressable, StyleSheet, View } from 'react-native';
import { useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from './common/AppText';
import { colors } from '../config/theme';
import { GET_MY_PROFILE_PICTURE } from '../apollo/queries';
import { useAuth } from '../contexts/AuthContext';

type Props = { onPress: () => void };

/**
 * "¿Qué quieres compartir?" at the top of the feed: the labeled way into the
 * Comunidad composer. A question reads clearer than any icon, sits in its own
 * row (new chips never crowd it) and never under the Confío IA bubble.
 */
export function CommunityComposePrompt({ onPress }: Props) {
  const { userProfile } = useAuth() as any;
  const { data } = useQuery(GET_MY_PROFILE_PICTURE, { fetchPolicy: 'cache-first' });
  const pictureUrl: string | null = data?.myProfilePicture?.url || null;
  const [pictureFailed, setPictureFailed] = useState(false);
  const initial = (userProfile?.firstName || userProfile?.username || '?').charAt(0).toUpperCase();

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
      accessibilityRole="button"
      accessibilityLabel="Publicar en Comunidad"
      accessibilityHint="Abre el editor para compartir algo con la comunidad"
    >
      <View style={styles.avatar}>
        {pictureUrl && !pictureFailed ? (
          <Image source={{ uri: pictureUrl }} style={styles.avatar} onError={() => setPictureFailed(true)} />
        ) : (
          <Text style={styles.initial}>{initial}</Text>
        )}
      </View>
      <Text style={styles.placeholder} numberOfLines={1}>¿Qué quieres compartir?</Text>
      <View style={styles.photo}>
        <Icon name="image" size={18} color={colors.primaryDark} />
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: 12,
    marginBottom: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.white,
  },
  pressed: {
    opacity: 0.85,
  },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  initial: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.primaryDeep,
  },
  placeholder: {
    flex: 1,
    fontSize: 15,
    color: colors.textTertiary,
  },
  photo: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
