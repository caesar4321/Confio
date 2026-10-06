import React, { useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, View } from 'react-native';
import { useMutation, useQuery } from '@apollo/client';
import { notifyMemberBlocked } from '../services/communityEvents';
import { isSchemaMismatch } from '../utils/graphqlSchemaMismatch';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from './common/AppText';
import { colors } from '../config/theme';
import { BLOCK_COMMUNITY_MEMBER, DELETE_COMMUNITY_POST, REPORT_COMMUNITY_POST } from '../apollo/mutations';
import { GET_COMMUNITY_POST_VIEWER } from '../apollo/queries';
import { ReportReasonSheet } from './ReportReasonSheet';
import { CommunityComments } from './CommunityComments';

type Props = {
  contentItemId: number;
  onDeleted: () => void;
};

/** Report (anyone else's) or delete (your own) a Comunidad post. */
function PostActionRow({ contentItemId, onDeleted, viewer, refetch }: Props & { viewer: any; refetch: () => any }) {
  const variables = { contentItemId: String(contentItemId) };
  const [reportPost, { loading: reporting }] = useMutation(REPORT_COMMUNITY_POST);
  const [deletePost, { loading: deleting }] = useMutation(DELETE_COMMUNITY_POST);
  const [blockMember, { loading: blocking }] = useMutation(BLOCK_COMMUNITY_MEMBER);
  const [picking, setPicking] = useState(false);

  const report = async (reason: string) => {
    setPicking(false);
    try {
      const { data: result } = await reportPost({ variables: { ...variables, reason } });
      const outcome = result?.reportCommunityPost;
      if (!outcome?.success) {
        Alert.alert('No pudimos enviar tu reporte', outcome?.error || 'Inténtalo de nuevo.');
        return;
      }
      Alert.alert('Gracias por avisarnos', 'Revisaremos esta publicación.');
      void refetch();
    } catch {
      Alert.alert('No pudimos enviar tu reporte', 'Revisa tu conexión e inténtalo de nuevo.');
    }
  };

  const confirmDelete = () => {
    Alert.alert('¿Eliminar publicación?', 'Dejará de verse en Comunidad.', [
      { text: 'Cancelar', style: 'cancel' },
      {
        text: 'Eliminar',
        style: 'destructive',
        onPress: async () => {
          try {
            const { data: result } = await deletePost({ variables });
            if (result?.deleteCommunityPost?.success) onDeleted();
          } catch {
            Alert.alert('No pudimos eliminarla', 'Revisa tu conexión e inténtalo de nuevo.');
          }
        },
      },
    ]);
  };

  if (viewer.isOwn) {
    return (
      <Pressable style={styles.action} onPress={confirmDelete} disabled={deleting} accessibilityRole="button">
        {deleting ? <ActivityIndicator size="small" color={colors.textSecondary} /> : (
          <Icon name="trash-2" size={14} color={colors.textSecondary} />
        )}
        <Text style={styles.actionText}>Eliminar mi publicación</Text>
      </Pressable>
    );
  }

  const confirmBlock = () => {
    if (!viewer.authorId) return;
    Alert.alert(
      `¿Bloquear a ${viewer.authorName}?`,
      'No verás sus publicaciones ni comentarios, y no podrá ver los tuyos ni mencionarte. Puedes desbloquear cuando quieras desde Mis publicaciones.',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Bloquear',
          style: 'destructive',
          onPress: async () => {
            try {
              const { data: result } = await blockMember({ variables: { userId: viewer.authorId } });
              if (!result?.blockCommunityMember?.success) {
                Alert.alert('No pudimos bloquear', result?.blockCommunityMember?.error || 'Inténtalo de nuevo.');
                return;
              }
              Alert.alert('Bloqueado', `Ya no verás contenido de ${viewer.authorName}.`);
              // Descubrir re-reads its feed on return, so their other posts
              // disappear too (nothing else in the app refetches).
              notifyMemberBlocked();
              onDeleted();
            } catch {
              Alert.alert('No pudimos bloquear', 'Revisa tu conexión e inténtalo de nuevo.');
            }
          },
        },
      ],
    );
  };

  return (
    <View style={styles.actionRow}>
      {viewer.viewerReported ? (
        <View style={styles.action}>
          <Icon name="flag" size={14} color={colors.textTertiary} />
          <Text style={[styles.actionText, styles.muted]}>Reportaste esta publicación</Text>
        </View>
      ) : viewer.canReport ? (
        <Pressable style={styles.action} onPress={() => setPicking(true)} disabled={reporting} accessibilityRole="button">
          {reporting ? <ActivityIndicator size="small" color={colors.textSecondary} /> : (
            <Icon name="flag" size={14} color={colors.textSecondary} />
          )}
          <Text style={styles.actionText}>Reportar</Text>
        </Pressable>
      ) : null}
      {viewer.authorId ? (
        <Pressable style={styles.action} onPress={confirmBlock} disabled={blocking} accessibilityRole="button">
          {blocking ? <ActivityIndicator size="small" color={colors.textSecondary} /> : (
            <Icon name="slash" size={14} color={colors.textSecondary} />
          )}
          <Text style={styles.actionText}>Bloquear a {viewer.authorName}</Text>
        </Pressable>
      ) : null}
      <ReportReasonSheet
        visible={picking}
        title="¿Por qué la reportas?"
        onPick={(reason) => { void report(reason); }}
        onClose={() => setPicking(false)}
      />
    </View>
  );
}

/**
 * A Comunidad post's own controls: report or delete it, and its comments.
 * Its own query: on a server without Comunidad it errors and renders nothing.
 */
export function CommunityPostActions({ contentItemId, onDeleted }: Props) {
  const { data, error, refetch } = useQuery(GET_COMMUNITY_POST_VIEWER, {
    variables: { contentItemId: String(contentItemId) },
    fetchPolicy: 'network-only',
  });
  const viewer = data?.communityPostViewer;
  // A transient error keeps the last state (and any comment being typed);
  // only a server without Comunidad hides this.
  if (isSchemaMismatch(error) || !viewer?.isCommunity) return null;
  return (
    <>
      <PostActionRow contentItemId={contentItemId} onDeleted={onDeleted} viewer={viewer} refetch={refetch} />
      <CommunityComments
        contentItemId={contentItemId}
        canComment={Boolean(viewer.canComment)}
        blockMessage={viewer.commentBlockMessage}
        blockCode={viewer.commentBlockCode}
        onRulesAccepted={() => { refetch(); }}
        maxChars={viewer.commentMaxChars || 500}
      />
    </>
  );
}

const styles = StyleSheet.create({
  actionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    columnGap: 20,
  },
  action: {
    marginTop: 16,
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: 6,
    paddingVertical: 6,
  },
  actionText: {
    fontSize: 13,
    color: colors.textSecondary,
  },
  muted: {
    color: colors.textTertiary,
  },
});
