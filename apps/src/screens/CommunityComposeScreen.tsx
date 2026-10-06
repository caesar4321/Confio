import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  View,
} from 'react-native';
import { useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import { useApolloClient, useMutation, useQuery } from '@apollo/client';
import { pickFromLibrary } from '../services/systemPicker';
import Icon from 'react-native-vector-icons/Feather';

import { Text, TextInput } from '../components/common/AppText';
import { InlineBanner } from '../components/common/InlineBanner';
import { CommunityRulesSheet } from '../components/CommunityRulesSheet';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { CREATE_COMMUNITY_POST, REQUEST_COMMUNITY_IMAGE_UPLOAD } from '../apollo/mutations';
import { GET_COMMUNITY_POSTING_STATUS, GET_MY_COMMUNITY_POST } from '../apollo/queries';
import { uploadFileToPresignedForm } from '../services/uploadService';
import { MainStackParamList } from '../types/navigation';

type Navigation = NativeStackNavigationProp<MainStackParamList>;
type RouteProps = NativeStackScreenProps<MainStackParamList, 'CommunityCompose'>['route'];

type Phase = 'editing' | 'sending' | 'reviewing' | 'approved' | 'still_reviewing';

type PickedImage = { uri: string; type: string; fileName: string };

// The AI usually answers in seconds; past this the post keeps its place in
// the queue and appears in Comunidad on its own once approved.
const REVIEW_POLL_MS = 2000;
const REVIEW_WAIT_MS = 60000;

const RULES = [
  'Comparte experiencias, preguntas y consejos.',
  'Sin enlaces, teléfonos ni redes para contactarte en privado.',
  'Nunca pidas dinero ni prometas ganancias.',
];

export const CommunityComposeScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProps>();
  const client = useApolloClient();
  // "Editar y reenviar" from Mis publicaciones starts from the refused text.
  const [body, setBody] = useState(route.params?.initialBody || '');
  const [image, setImage] = useState<PickedImage | null>(null);
  const [phase, setPhase] = useState<Phase>('editing');
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  const { data: statusData, loading: statusLoading, refetch: refetchStatus } = useQuery(
    GET_COMMUNITY_POSTING_STATUS,
    { fetchPolicy: 'network-only' },
  );
  // Back from "Verificar identidad" (or anything else that changes it):
  // ask again rather than keep showing the old block.
  const focusedOnce = useRef(false);
  useFocusEffect(
    useCallback(() => {
      if (!focusedOnce.current) {
        focusedOnce.current = true;
        return;
      }
      refetchStatus().catch(() => {});
    }, [refetchStatus]),
  );
  const [requestUpload] = useMutation(REQUEST_COMMUNITY_IMAGE_UPLOAD);
  const [createPost] = useMutation(CREATE_COMMUNITY_POST);

  const status = statusData?.communityPostingStatus as
    | { canPost: boolean; blockCode?: string | null; blockMessage?: string | null; maxChars: number }
    | undefined;
  const maxChars = status?.maxChars || 1000;
  const trimmed = body.trim();
  const canSubmit = phase === 'editing' && trimmed.length > 0 && trimmed.length <= maxChars && status?.canPost;

  const pickImage = async () => {
    const result = await pickFromLibrary({
      mediaType: 'photo',
      selectionLimit: 1,
      // Downscaled on the phone so the upload stays well under the 5 MB cap.
      maxWidth: 1600,
      maxHeight: 1600,
      quality: 0.8,
    });
    // An error (e.g. permission denied) also arrives without an asset, so
    // check it before treating "no asset" as a cancel.
    if (result.errorCode) {
      setError('No pudimos abrir tu galería.');
      return;
    }
    const asset = result.assets?.[0];
    if (result.didCancel || !asset?.uri) return;
    const type = asset.type === 'image/png' || asset.type === 'image/webp' ? asset.type : 'image/jpeg';
    setImage({ uri: asset.uri, type, fileName: asset.fileName || 'foto.jpg' });
  };

  const uploadImage = async (picked: PickedImage): Promise<string> => {
    const { data } = await requestUpload({ variables: { contentType: picked.type } });
    const result = data?.requestCommunityImageUpload;
    if (!result?.success || !result.upload) {
      throw new Error(result?.error || 'No pudimos subir tu imagen.');
    }
    const fields = typeof result.upload.fields === 'string' ? JSON.parse(result.upload.fields) : result.upload.fields;
    await uploadFileToPresignedForm(result.upload.url, fields || {}, picked.uri, picked.fileName, picked.type);
    return result.upload.key;
  };

  const waitForReview = async (contentItemId: string) => {
    const deadline = Date.now() + REVIEW_WAIT_MS;
    while (mounted.current && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, REVIEW_POLL_MS));
      try {
        const { data } = await client.query({
          query: GET_MY_COMMUNITY_POST,
          variables: { contentItemId },
          fetchPolicy: 'network-only',
        });
        const post = data?.myCommunityPost;
        if (!mounted.current || !post || post.status === 'PENDING') continue;
        if (post.status === 'APPROVED') {
          setPhase('approved');
          return;
        }
        // Rejected or the review failed: their text stays for editing.
        setError(post.reason || 'Tu publicación no cumple las normas de la comunidad.');
        setPhase('editing');
        return;
      } catch {
        // A dropped poll is not a verdict; keep waiting.
      }
    }
    if (mounted.current) setPhase('still_reviewing');
  };

  const submit = async () => {
    if (!canSubmit) return;
    setError(null);
    setPhase('sending');
    try {
      // Every attempt uploads afresh: one upload backs one post.
      const imageKey = image ? await uploadImage(image) : null;
      const { data } = await createPost({ variables: { body: trimmed, imageKey } });
      const result = data?.createCommunityPost;
      if (!result?.success || !result.post) {
        throw new Error(result?.error || 'No pudimos enviar tu publicación.');
      }
      setPhase('reviewing');
      await waitForReview(result.post.id);
    } catch (e: any) {
      if (!mounted.current) return;
      setError(e?.message && !/network|graphql/i.test(e.message) ? e.message : 'No pudimos enviar tu publicación. Revisa tu conexión.');
      setPhase('editing');
    }
  };

  const header = (
    <Header
      title="Publicar en Comunidad"
      navigation={navigation as any}
      onBackPress={() => navigation.goBack()}
      backgroundColor={colors.background}
      isLight={false}
    />
  );

  if (phase === 'reviewing' || phase === 'approved' || phase === 'still_reviewing') {
    const copy = {
      reviewing: {
        icon: null,
        title: 'Revisando tu publicación…',
        subtitle: 'Toma unos segundos. Revisamos cada publicación para cuidar a la comunidad.',
      },
      approved: {
        icon: 'check-circle',
        title: '¡Publicado!',
        subtitle: 'Tu publicación ya está en Comunidad.',
      },
      still_reviewing: {
        icon: 'clock',
        title: 'Sigue en revisión',
        subtitle: 'Aparecerá en Comunidad en cuanto se apruebe y te avisaremos. Puedes seguirla en Mis publicaciones.',
      },
    }[phase];
    return (
      <View style={styles.container}>
        {header}
        <View style={styles.stateWrap}>
          {copy.icon ? (
            <View style={styles.stateIcon}>
              <Icon name={copy.icon} size={28} color={colors.primaryDark} />
            </View>
          ) : (
            <ActivityIndicator size="large" color={colors.primary} />
          )}
          <Text style={styles.stateTitle}>{copy.title}</Text>
          <Text style={styles.stateSubtitle}>{copy.subtitle}</Text>
          {phase !== 'reviewing' ? (
            <>
              <Pressable style={styles.primaryButton} onPress={() => navigation.goBack()} accessibilityRole="button">
                <Text style={styles.primaryButtonText}>Volver a Comunidad</Text>
              </Pressable>
              <Pressable
                style={styles.secondaryButton}
                onPress={() => navigation.replace('MyCommunityPosts')}
                accessibilityRole="button"
              >
                <Text style={styles.secondaryButtonText}>Ver mis publicaciones</Text>
              </Pressable>
            </>
          ) : null}
        </View>
      </View>
    );
  }

  if (statusLoading && !status) {
    return (
      <View style={styles.container}>
        {header}
        <View style={styles.stateWrap}>
          <ActivityIndicator size="small" color={colors.primary} />
        </View>
      </View>
    );
  }

  if (status?.blockCode === 'rules_required') {
    // First time: the rules, accepted once, then straight into the editor.
    return (
      <View style={styles.container}>
        {header}
        <CommunityRulesSheet
          visible
          onAccepted={() => { refetchStatus().catch(() => {}); }}
          onClose={() => navigation.goBack()}
        />
      </View>
    );
  }

  if (!status || !status.canPost) {
    const needsVerification = status?.blockCode === 'not_verified';
    return (
      <View style={styles.container}>
        {header}
        <View style={styles.stateWrap}>
          <View style={styles.stateIcon}>
            <Icon name={needsVerification ? 'shield' : 'info'} size={28} color={colors.primaryDark} />
          </View>
          <Text style={styles.stateTitle}>
            {needsVerification ? 'Verifica tu identidad para publicar' : 'No puedes publicar ahora'}
          </Text>
          <Text style={styles.stateSubtitle}>
            {status?.blockMessage || 'No pudimos cargar la comunidad. Inténtalo de nuevo más tarde.'}
          </Text>
          {needsVerification ? (
            <>
              <Text style={styles.stateSubtitle}>
                En Comunidad todas las personas están verificadas: así evitamos estafas y cuentas falsas.
              </Text>
              <Pressable
                style={styles.primaryButton}
                onPress={() => navigation.navigate('Verification')}
                accessibilityRole="button"
              >
                <Text style={styles.primaryButtonText}>Verificar identidad</Text>
              </Pressable>
            </>
          ) : null}
        </View>
      </View>
    );
  }

  const sending = phase === 'sending';
  return (
    <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      {header}
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        {error ? <InlineBanner message={error} variant="error" onDismiss={() => setError(null)} /> : null}
        <View style={styles.card}>
          <TextInput
            style={styles.input}
            value={body}
            onChangeText={setBody}
            placeholder="¿Qué quieres compartir con la comunidad?"
            placeholderTextColor={colors.textTertiary}
            multiline
            maxLength={maxChars}
            editable={!sending}
            autoFocus
            textAlignVertical="top"
          />
          {image ? (
            <View style={styles.imageWrap}>
              <Image source={{ uri: image.uri }} style={styles.image} resizeMode="cover" />
              {!sending ? (
                <Pressable
                  style={styles.removeImage}
                  onPress={() => setImage(null)}
                  accessibilityRole="button"
                  accessibilityLabel="Quitar imagen"
                >
                  <Icon name="x" size={16} color={colors.white} />
                </Pressable>
              ) : null}
            </View>
          ) : null}
          <View style={styles.toolbar}>
            <Pressable
              onPress={() => { void pickImage(); }}
              disabled={sending || Boolean(image)}
              style={({ pressed }) => [styles.toolButton, (pressed || image) && styles.toolButtonMuted]}
              accessibilityRole="button"
              accessibilityLabel="Agregar una foto"
            >
              <Icon name="image" size={18} color={colors.primaryDark} />
              <Text style={styles.toolButtonText}>Foto</Text>
            </Pressable>
            <Text style={[styles.counter, trimmed.length > maxChars && styles.counterOver]}>
              {body.length}/{maxChars}
            </Text>
          </View>
        </View>

        <View style={styles.rules}>
          {RULES.map((rule) => (
            <View key={rule} style={styles.ruleRow}>
              <Icon name="check" size={14} color={colors.primaryDark} />
              <Text style={styles.ruleText}>{rule}</Text>
            </View>
          ))}
          <Text style={styles.rulesFootnote}>
            Revisamos cada publicación antes de mostrarla. Se publica con tu nombre y la inicial de tu apellido.
          </Text>
        </View>

        <Pressable
          style={[styles.primaryButton, !canSubmit && styles.primaryButtonDisabled]}
          onPress={() => { void submit(); }}
          disabled={!canSubmit}
          accessibilityRole="button"
        >
          {sending ? (
            <ActivityIndicator size="small" color={colors.white} />
          ) : (
            <Text style={styles.primaryButtonText}>Publicar</Text>
          )}
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
};

export default CommunityComposeScreen;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.neutral,
  },
  content: {
    padding: 16,
    gap: 16,
  },
  card: {
    backgroundColor: colors.white,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
  },
  input: {
    minHeight: 140,
    fontSize: 16,
    lineHeight: 22,
    color: colors.textFlat,
  },
  imageWrap: {
    marginTop: 12,
    borderRadius: 12,
    overflow: 'hidden',
  },
  image: {
    width: '100%',
    aspectRatio: 4 / 3,
    backgroundColor: colors.neutralDark,
  },
  removeImage: {
    position: 'absolute',
    top: 8,
    right: 8,
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: 'rgba(17, 24, 39, 0.7)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  toolbar: {
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: colors.borderLight,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  toolButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 999,
    backgroundColor: colors.primarySoft,
  },
  toolButtonMuted: {
    opacity: 0.5,
  },
  toolButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  counter: {
    fontSize: 12,
    color: colors.textTertiary,
  },
  counterOver: {
    color: colors.error.text,
  },
  rules: {
    gap: 8,
    paddingHorizontal: 4,
  },
  ruleRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
  },
  ruleText: {
    flex: 1,
    fontSize: 14,
    lineHeight: 20,
    color: colors.textSecondary,
  },
  rulesFootnote: {
    marginTop: 4,
    fontSize: 12,
    lineHeight: 17,
    color: colors.textTertiary,
  },
  primaryButton: {
    marginTop: 8,
    alignSelf: 'stretch',
    minHeight: 50,
    borderRadius: 14,
    backgroundColor: colors.primaryDark,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 20,
  },
  secondaryButton: {
    alignSelf: 'stretch',
    minHeight: 46,
    alignItems: 'center',
    justifyContent: 'center',
  },
  secondaryButtonText: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  primaryButtonDisabled: {
    opacity: 0.4,
  },
  primaryButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.white,
  },
  stateWrap: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
    gap: 12,
  },
  stateIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stateTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.textFlat,
    textAlign: 'center',
  },
  stateSubtitle: {
    fontSize: 15,
    lineHeight: 21,
    color: colors.textSecondary,
    textAlign: 'center',
  },
});
