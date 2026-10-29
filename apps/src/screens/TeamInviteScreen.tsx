import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, Share, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import { useMutation } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { CREATE_TEAM_INVITE } from '../apollo/mutations';
import { MainStackParamList } from '../types/navigation';
import { buildTeamInviteLink, buildTeamInviteMessage } from '../utils/teams';

type Navigation = NativeStackNavigationProp<MainStackParamList>;
type RouteProps = NativeStackScreenProps<MainStackParamList, 'TeamInvite'>['route'];

/**
 * Friend invites: share the team link (WhatsApp, anywhere). Contacts are no
 * longer matched against Confío (they stay on the phone), so the link is the
 * one way in. The friend still needs a verified, public profile to join; the
 * captain's link skips approval.
 */
export const TeamInviteScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProps>();
  const { teamId, teamName } = route.params;
  const [token, setToken] = useState<string | null>(null);
  const [createInvite] = useMutation(CREATE_TEAM_INVITE);
  const live = useRef(true);
  useEffect(() => () => { live.current = false; }, []);

  useEffect(() => {
    createInvite({ variables: { teamId } })
      .then(({ data }) => {
        const result = data?.createTeamInvite;
        if (!live.current) return;
        if (result?.success && result.token) setToken(result.token);
        else {
          Alert.alert('No pudimos crear tu invitación', result?.error || 'Inténtalo de nuevo.');
          navigation.goBack();
        }
      })
      .catch(() => {
        if (!live.current) return;
        Alert.alert('No pudimos crear tu invitación', 'Revisa tu conexión e inténtalo de nuevo.');
        navigation.goBack();
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamId]);

  const link = useMemo(
    () => (token ? buildTeamInviteLink(token) : null),
    [token],
  );

  const share = async () => {
    if (!link) return;
    try {
      await Share.share({ message: buildTeamInviteMessage(teamName, link) });
    } catch {
      // Dismissed.
    }
  };

  return (
    <View style={styles.container}>
      <Header title="Invitar a un amigo" navigation={navigation as any} onBackPress={() => navigation.goBack()}
        backgroundColor={colors.background} isLight={false} />
      <View style={styles.card}>
        <Text style={styles.title}>Comparte el enlace de {teamName}</Text>
        <Text style={styles.body}>
          Por WhatsApp o donde quieras. Si tu amigo aún no tiene Confío, el enlace lo lleva a descargarla.
        </Text>
        <Pressable style={[styles.primary, !link && styles.disabled]} disabled={!link} onPress={() => { void share(); }}
          accessibilityRole="button">
          {link ? <Icon name="share-2" size={18} color={colors.white} /> : <ActivityIndicator color={colors.white} />}
          <Text style={styles.primaryText}>Compartir enlace</Text>
        </Pressable>
        <Text style={styles.note}>
          Al invitar, tu amigo verá tu nombre de usuario de Comunidad y tu rentabilidad, como cualquier miembro del equipo.
        </Text>
      </View>
    </View>
  );
};

export default TeamInviteScreen;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  card: { margin: 16, padding: 16, gap: 10, borderRadius: 14, backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 17, fontWeight: '700', color: colors.dark },
  body: { fontSize: 14, color: colors.textSecondary },
  note: { fontSize: 12, color: colors.textSecondary },
  primary: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, paddingVertical: 12, borderRadius: 24,
    backgroundColor: colors.primaryDark,
  },
  primaryText: { fontSize: 15, fontWeight: '700', color: colors.white },
  disabled: { opacity: 0.5 },
});
