import React, { useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Image, Pressable, StyleSheet, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useMutation, useQuery } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { EmptyState } from '../components/EmptyState';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { UNBLOCK_COMMUNITY_MEMBER } from '../apollo/mutations';
import { GET_MY_BLOCKED_MEMBERS } from '../apollo/queries';

type Member = { id: string; name: string; avatarUrl?: string | null };

/** Comunidad members you blocked, with a way to undo it. */
export const BlockedMembersScreen = () => {
  const navigation = useNavigation<any>();
  const { data, loading, error, refetch } = useQuery(GET_MY_BLOCKED_MEMBERS, { fetchPolicy: 'network-only' });
  const [unblock] = useMutation(UNBLOCK_COMMUNITY_MEMBER);
  const [busyId, setBusyId] = useState<string | null>(null);
  const members: Member[] = data?.myBlockedMembers || [];

  const confirmUnblock = (member: Member) => {
    Alert.alert(`¿Desbloquear a ${member.name}?`, 'Volverán a ver sus publicaciones y comentarios.', [
      { text: 'Cancelar', style: 'cancel' },
      {
        text: 'Desbloquear',
        onPress: async () => {
          setBusyId(member.id);
          try {
            await unblock({ variables: { userId: member.id } });
            await refetch();
          } catch {
            Alert.alert('No pudimos desbloquear', 'Revisa tu conexión e inténtalo de nuevo.');
          } finally {
            setBusyId(null);
          }
        },
      },
    ]);
  };

  return (
    <View style={styles.container}>
      <Header
        title="Personas bloqueadas"
        navigation={navigation}
        onBackPress={() => navigation.goBack()}
        backgroundColor={colors.background}
        isLight={false}
      />
      {loading && !data ? (
        <ActivityIndicator style={styles.loading} color={colors.primary} />
      ) : (
        <FlatList
          data={members}
          keyExtractor={(m) => m.id}
          contentContainerStyle={members.length ? styles.list : styles.emptyList}
          initialNumToRender={20}
          maxToRenderPerBatch={20}
          windowSize={11}
          renderItem={({ item }) => (
            <View style={styles.row}>
              <View style={styles.avatar}>
                {item.avatarUrl ? (
                  <Image source={{ uri: item.avatarUrl }} style={styles.avatar} />
                ) : (
                  <Text style={styles.initial}>{item.name.charAt(0).toUpperCase()}</Text>
                )}
              </View>
              <Text style={styles.name}>{item.name}</Text>
              <Pressable
                onPress={() => confirmUnblock(item)}
                disabled={busyId === item.id}
                style={styles.unblock}
                accessibilityRole="button"
              >
                {busyId === item.id ? (
                  <ActivityIndicator size="small" color={colors.primaryDark} />
                ) : (
                  <Text style={styles.unblockText}>Desbloquear</Text>
                )}
              </Pressable>
            </View>
          )}
          ListEmptyComponent={
            error ? (
              <EmptyState
                icon="wifi-off"
                title="No pudimos cargar la lista"
                subtitle="Revisa tu conexión e inténtalo de nuevo."
                actionLabel="Reintentar"
                onAction={() => { refetch().catch(() => {}); }}
              />
            ) : (
              <EmptyState
                icon="users"
                title="No has bloqueado a nadie"
                subtitle="Si alguien te molesta en Comunidad, puedes bloquearlo desde su publicación o comentario."
              />
            )
          }
        />
      )}
    </View>
  );
};

export default BlockedMembersScreen;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  loading: { marginVertical: 24 },
  list: { padding: 16, gap: 10 },
  emptyList: { flexGrow: 1 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.white,
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
  initial: { fontSize: 15, fontWeight: '700', color: colors.primaryDeep },
  name: { flex: 1, fontSize: 15, fontWeight: '600', color: colors.textFlat },
  unblock: { paddingHorizontal: 12, paddingVertical: 8, minWidth: 96, alignItems: 'center' },
  unblockText: { fontSize: 14, fontWeight: '600', color: colors.primaryDark },
});
