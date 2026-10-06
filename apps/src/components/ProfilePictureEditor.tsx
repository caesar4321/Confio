import React, { useEffect, useRef, useState } from 'react';
import { useIsFocused } from '@react-navigation/native';
import { ActivityIndicator, Alert, Image, Pressable, StyleSheet, View, InteractionManager } from 'react-native';
import { useMutation, useQuery } from '@apollo/client';
import { pickFromLibrary } from '../services/systemPicker';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from './common/AppText';
import { colors } from '../config/theme';
import {
  REMOVE_PROFILE_PICTURE,
  REQUEST_PROFILE_PICTURE_UPLOAD,
  SUBMIT_PROFILE_PICTURE,
} from '../apollo/mutations';
import { GET_MY_PROFILE_PICTURE } from '../apollo/queries';
import { uploadFileToPresignedForm } from '../services/uploadService';
import { usePollWhile } from '../hooks/usePollWhile';
import { isSchemaMismatch } from '../utils/graphqlSchemaMismatch';
import { CommunityRulesSheet } from './CommunityRulesSheet';

const POLL_MS = 3000;
// Past this, the screen stops asking; reopening it shows the outcome.
const POLL_GIVE_UP_MS = 120000;

type MyPicture = {
  url?: string | null;
  latestStatus?: 'PENDING' | 'ACTIVE' | 'REJECTED' | 'FAILED' | 'REMOVED' | null;
  latestReason?: string | null;
  blockMessage?: string | null;
  rulesRequired?: boolean | null;
};

type Props = { initial: string };

/**
 * Pick, upload and track a profile picture. Every picture is screened by AI
 * before anyone else sees it; the current one stays up meanwhile. Renders
 * nothing on a server without profile pictures.
 */
export function ProfilePictureEditor({ initial }: Props) {
  const { data, error, refetch, startPolling, stopPolling } = useQuery(GET_MY_PROFILE_PICTURE, {
    fetchPolicy: 'cache-and-network',
  });
  const [requestUpload] = useMutation(REQUEST_PROFILE_PICTURE_UPLOAD);
  const [submitPicture] = useMutation(SUBMIT_PROFILE_PICTURE);
  const [removePicture] = useMutation(REMOVE_PROFILE_PICTURE, {
    refetchQueries: [{ query: GET_MY_PROFILE_PICTURE }],
  });
  const [uploading, setUploading] = useState(false);
  const [localPreview, setLocalPreview] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [rulesOpen, setRulesOpen] = useState(false);
  // A ref, so the deferred pick reads focus at fire time, not render time.
  const focusedRef = useRef(true);
  focusedRef.current = useIsFocused();
  const mounted = useRef(true);
  const pendingPick = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingTask = useRef<{ cancel: () => void } | null>(null);
  useEffect(() => () => {
    mounted.current = false;
    pendingTask.current?.cancel();
    if (pendingPick.current) clearTimeout(pendingPick.current);
  }, []);

  const picture: MyPicture | undefined = data?.myProfilePicture;
  const pending = picture?.latestStatus === 'PENDING';

  // Each new upload restarts the polling deadline.
  const [submission, setSubmission] = useState(0);
  usePollWhile(pending, startPolling, stopPolling, POLL_MS, POLL_GIVE_UP_MS, String(submission));
  useEffect(() => {
    if (!pending) setLocalPreview(null);
  }, [pending]);

  // Only a server without profile pictures hides the editor; a dropped poll
  // keeps showing the last known state.
  if (isSchemaMismatch(error) || !picture) return null;

  const pick = async (rulesJustAccepted = false) => {
    // A pick is already on its way right after the rules were accepted.
    if (!rulesJustAccepted && (pendingPick.current || pendingTask.current)) return;
    if (picture.rulesRequired && !rulesJustAccepted) {
      // A photo is shown to other members, so the community rules apply.
      setRulesOpen(true);
      return;
    }
    if (picture.blockMessage && !(rulesJustAccepted && picture.rulesRequired)) {
      setMessage(picture.blockMessage);
      return;
    }
    let result;
    try {
      result = await pickFromLibrary({
        mediaType: 'photo',
        selectionLimit: 1,
        maxWidth: 1024,
        maxHeight: 1024,
        quality: 0.8,
      });
    } catch {
      setMessage('No pudimos abrir tu galería.');
      return;
    }
    if (result.errorCode) {
      setMessage('No pudimos abrir tu galería. Revisa el permiso de fotos en Ajustes.');
      return;
    }
    const asset = result.assets?.[0];
    if (result.didCancel || !asset?.uri) return;
    const type = asset.type === 'image/png' || asset.type === 'image/webp' ? asset.type : 'image/jpeg';
    setUploading(true);
    setMessage(null);
    try {
      const { data: upload } = await requestUpload({ variables: { contentType: type } });
      const ticket = upload?.requestProfilePictureUpload;
      if (!ticket?.success || !ticket.upload) throw new Error(ticket?.error || 'No pudimos subir tu foto.');
      const fields = typeof ticket.upload.fields === 'string' ? JSON.parse(ticket.upload.fields) : ticket.upload.fields;
      await uploadFileToPresignedForm(ticket.upload.url, fields || {}, asset.uri, asset.fileName || 'foto.jpg', type);
      const { data: submitted } = await submitPicture({ variables: { imageKey: ticket.upload.key } });
      const outcome = submitted?.submitProfilePicture;
      if (!outcome?.success) throw new Error(outcome?.error || 'No pudimos enviar tu foto.');
      setLocalPreview(asset.uri);
      setSubmission((n) => n + 1);
      await refetch();
    } catch (e: any) {
      setMessage(e?.message && !/network|graphql/i.test(e.message) ? e.message : 'No pudimos subir tu foto. Revisa tu conexión.');
    } finally {
      setUploading(false);
    }
  };

  const confirmRemove = () => {
    Alert.alert('¿Quitar tu foto?', 'Volverás a mostrar tu inicial.', [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Quitar', style: 'destructive', onPress: () => { void removePicture().catch(() => {}); } },
    ]);
  };

  const shown = pending && localPreview ? localPreview : picture.url;
  const refused = picture.latestStatus === 'REJECTED' || picture.latestStatus === 'FAILED';
  return (
    <View style={styles.wrap}>
      <Pressable onPress={() => { void pick(); }} disabled={uploading} accessibilityRole="button"
        accessibilityLabel="Cambiar foto de perfil">
        <View style={styles.avatar}>
          {shown ? (
            <Image source={{ uri: shown }} style={[styles.image, pending && styles.imagePending]} />
          ) : (
            <Text style={styles.initial}>{initial}</Text>
          )}
          {uploading || pending ? (
            <View style={styles.overlay}>
              <ActivityIndicator color={colors.white} />
            </View>
          ) : null}
          <View style={styles.cameraBadge}>
            <Icon name="camera" size={14} color={colors.white} />
          </View>
        </View>
      </Pressable>
      {pending ? (
        <Text style={styles.status}>Revisando tu foto… suele tardar unos segundos.</Text>
      ) : refused ? (
        <Text style={styles.refused}>{picture.latestReason || 'Tu foto no se aprobó. Prueba con otra.'}</Text>
      ) : (
        <Text style={styles.hint}>Revisamos cada foto antes de mostrarla en Comunidad.</Text>
      )}
      {message ? <Text style={styles.refused}>{message}</Text> : null}
      <View style={styles.actions}>
        <Pressable onPress={() => { void pick(); }} disabled={uploading} hitSlop={8} accessibilityRole="button">
          <Text style={styles.action}>{picture.url ? 'Cambiar foto' : 'Agregar foto'}</Text>
        </Pressable>
        {picture.url && !pending ? (
          <Pressable onPress={confirmRemove} hitSlop={8} accessibilityRole="button">
            <Text style={styles.actionMuted}>Quitar</Text>
          </Pressable>
        ) : null}
      </View>
      <CommunityRulesSheet
        visible={rulesOpen}
        onAccepted={() => {
          setRulesOpen(false);
          refetch().catch(() => {});
          // Let the sheet finish closing first: iOS cannot present the
          // picker over a modal that is still dismissing.
          // Cancelled if the person leaves first (see the unmount cleanup).
          const task = InteractionManager.runAfterInteractions(() => {
            pendingPick.current = setTimeout(() => {
              pendingPick.current = null;
              pendingTask.current = null;
              if (mounted.current && focusedRef.current) void pick(true);
            }, 450);
          });
          pendingTask.current = task;
        }}
        onClose={() => setRulesOpen(false)}
      />
    </View>
  );
}

const SIZE = 88;

const styles = StyleSheet.create({
  wrap: {
    alignItems: 'center',
    marginBottom: 20,
  },
  avatar: {
    width: SIZE,
    height: SIZE,
    borderRadius: SIZE / 2,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  image: {
    width: SIZE,
    height: SIZE,
    borderRadius: SIZE / 2,
  },
  imagePending: {
    opacity: 0.6,
  },
  initial: {
    fontSize: 34,
    fontWeight: '700',
    color: colors.primaryDark,
  },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: SIZE / 2,
    backgroundColor: 'rgba(17, 24, 39, 0.35)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  cameraBadge: {
    position: 'absolute',
    right: 0,
    bottom: 0,
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: colors.primaryDark,
    borderWidth: 2,
    borderColor: colors.white,
    alignItems: 'center',
    justifyContent: 'center',
  },
  status: {
    marginTop: 8,
    fontSize: 13,
    color: colors.textSecondary,
    textAlign: 'center',
  },
  hint: {
    marginTop: 8,
    fontSize: 12,
    color: colors.textTertiary,
    textAlign: 'center',
  },
  refused: {
    marginTop: 8,
    fontSize: 13,
    color: colors.error.text,
    textAlign: 'center',
  },
  actions: {
    marginTop: 8,
    flexDirection: 'row',
    gap: 20,
  },
  action: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  actionMuted: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.textSecondary,
  },
});
