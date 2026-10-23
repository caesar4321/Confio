import React, { useEffect } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import { useApolloClient } from '@apollo/client';

import { EmptyState } from '../components/EmptyState';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { GET_TEAM_INVITE } from '../apollo/queries';
import { MainStackParamList } from '../types/navigation';

type Navigation = NativeStackNavigationProp<MainStackParamList>;
type RouteProps = NativeStackScreenProps<MainStackParamList, 'TeamJoinInvite'>['route'];

/** An invite link or push: find its team, then show the team page with the invite attached. */
export const TeamJoinInviteScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProps>();
  const client = useApolloClient();
  const [gone, setGone] = React.useState(false);

  useEffect(() => {
    let live = true;
    client.query({ query: GET_TEAM_INVITE, variables: { token: route.params.token }, fetchPolicy: 'network-only' })
      .then(({ data }) => {
        if (!live) return;
        const invite = data?.teamInvite;
        if (invite?.teamId) navigation.replace('Team', { teamId: String(invite.teamId), inviteToken: route.params.token });
        else setGone(true);
      })
      .catch(() => { if (live) setGone(true); });
    return () => { live = false; };
  }, [client, navigation, route.params.token]);

  return (
    <View style={styles.container}>
      <Header title="Invitación" navigation={navigation as any} onBackPress={() => navigation.goBack()}
        backgroundColor={colors.background} isLight={false} />
      {gone ? (
        <EmptyState icon="users" title="Esta invitación ya no es válida"
          subtitle="Pídele a tu amigo un enlace nuevo." />
      ) : (
        <ActivityIndicator style={styles.loading} color={colors.primary} />
      )}
    </View>
  );
};

export default TeamJoinInviteScreen;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  loading: { marginTop: 32 },
});
