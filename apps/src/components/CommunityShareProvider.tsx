import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Animated,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  View,
} from 'react-native';
import { useMutation, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';

import { Text, TextInput } from './common/AppText';
import { ActivitySummary, cryptoCategoryOf, tradeSide, type ActivityShare } from './ActivitySummary';
import { CommunityRulesSheet } from './CommunityRulesSheet';
import { PostByline } from './PostByline';
import { colors } from '../config/theme';
import {
  GET_MY_COMMUNITY_POST,
  GET_MY_PROFILE_PICTURE,
  GET_SHARE_SHEET_ACTIVITY,
  GET_SHARE_SHEET_CRYPTO_ACTIVITY,
} from '../apollo/queries';
import { RECORD_ACTIVITY_SHARE_DISMISSAL, SHARE_ACTIVITY_INTENT } from '../apollo/mutations';
import { useAccount } from '../contexts/AccountContext';
import { navigate, navigationRef } from '../navigation/RootNavigation';
import { setActivityShareListener, type ActivityShareGroup } from '../services/communityShare';

type Request = { group: ActivityShareGroup; reference: string };

type Shareable = {
  unifiedTransactionId?: string | null;
  pending?: boolean | null;
  canShare: boolean;
  blockCode?: string | null;
  blockMessage?: string | null;
  noteMaxChars?: number | null;
  activity?: ActivityShare | null;
};

type ShareStatus = 'published' | 'in_review' | 'scheduled';
type Done = { status: ShareStatus; postId: string | null };
type ReviewedPost = { id: string; status: string; reason?: string | null };

// Blocks we never nag about: the sheet simply does not appear.
const SILENT_BLOCKS = new Set(['not_verified', 'banned', 'disabled', 'business_context']);

const ERROR_COPY: Record<string, string> = {
  already_shared: 'Ya compartiste este movimiento.',
  not_shareable: 'Este movimiento ya no se puede compartir.',
  too_long: 'Tu nota es demasiado larga.',
  links: 'Las notas no pueden incluir enlaces.',
};

const REVIEW_POLL_MS = 3000;
const REVIEW_MAX_MS = 30000;
const DEFAULT_NOTE_MAX = 280;

const SUBTITLE = '¿Lo cuentas en Comunidad? Inspira a otros con tu movimiento.';

export function headlineFor(activity: ActivityShare, pending: boolean): string {
  const side = tradeSide(activity);
  if (side && cryptoCategoryOf(activity)) {
    if (side === 'sell') return 'Venta lista ✅';
    return activity.ticker ? `¡Ya tienes ${activity.ticker}! 🎉` : '¡Compra lista! 🎉';
  }
  switch (activity.kind) {
    case 'stock_buy':
      return activity.ticker ? `¡Ya tienes ${activity.ticker}! 🎉` : '¡Compra lista! 🎉';
    case 'stock_sell':
      return 'Venta lista ✅';
    case 'top_up':
      return '¡Recarga lista! 💵';
    case 'withdraw':
      return pending ? '¡Retiro en camino! 🚀' : '¡Retiro listo! 🚀';
    case 'send':
      return '¡Enviado! 💸';
    case 'receive':
      return '¡Recibido! 💵';
    case 'pay':
      return activity.merchant ? `¡Pagado en ${activity.merchant}! 🛍️` : '¡Pago listo! 🛍️';
    default:
      return '¡Listo! 🎉';
  }
}

const CHIPS: Record<string, string[]> = {
  stock_buy: ['📈 A largo plazo', '💡 Creo en la empresa', '🧪 Empezando con poco'],
  stock_sell: ['🎯 Tomé ganancias', '🔁 Rebalanceando', '📚 Aprendí algo'],
  crypto_buy: ['🛡️ Para guardar valor', '🧪 Empezando con poco', '📅 Pensando a largo plazo'],
  crypto_sell: ['🎯 Tomé ganancias', '🔁 Rebalanceando', '💵 Volví a mis dólares'],
  top_up: ['⚡ Fue rapidísimo', '🏦 Sin ir al banco', '💵 Dólares en minutos'],
  withdraw: ['⚡ Llegó rapidísimo', '✅ Sin complicaciones', '🏦 Directo a mi cuenta'],
  send: ['💸 Sin comisiones', '🤝 A mi familia', '⚡ Llegó al instante'],
  pay: ['📱 Pagué con QR en segundos', '💵 Sin efectivo', '☕ Mi lugar favorito'],
  receive: ['⚡ Llegó rapidísimo', '🤝 De mi familia', '💵 Directo a mis dólares'],
};

export const chipsFor = (kind: string): string[] => CHIPS[kind] || [];

/** Tapping a chip: replaces an empty note or another chip, removes itself, appends to free text. */
export function applyChip(note: string, chip: string, chips: string[], maxChars: number): string {
  const current = note.trim();
  if (current === chip) return '';
  if (!current || chips.includes(current)) return chip;
  if (current.includes(chip)) return current;
  const next = `${current} ${chip}`;
  return next.length <= maxChars ? next : current;
}

/**
 * The one "share to Comunidad" sheet for every Confío movement. Mounted once
 * above the authenticated navigator; screens open it through
 * services/communityShare.requestActivityShare, so it looks the same
 * everywhere and survives the user leaving the success screen.
 */
export function CommunityShareProvider() {
  const { activeAccount } = useAccount();
  const isBusiness = (activeAccount?.type || '').toLowerCase() === 'business';
  const [request, setRequest] = useState<Request | null>(null);
  const currentRef = useRef<Request | null>(null);
  const businessRef = useRef(isBusiness);
  businessRef.current = isBusiness;

  useEffect(
    () =>
      setActivityShareListener((next) => {
        // One sheet at a time; business and employee accounts never see it.
        if (currentRef.current || businessRef.current) return false;
        currentRef.current = next;
        setRequest(next);
        return true;
      }),
    [],
  );

  const close = useCallback(() => {
    currentRef.current = null;
    setRequest(null);
  }, []);

  if (!request || isBusiness) return null;
  return <ActivityShareSheet key={`${request.group}:${request.reference}`} request={request} onClose={close} />;
}

function ActivityShareSheet({ request, onClose }: { request: Request; onClose: () => void }) {
  // Crypto shares exist only on servers that also serve `category`.
  const sheetQuery = request.group === 'crypto' ? GET_SHARE_SHEET_CRYPTO_ACTIVITY : GET_SHARE_SHEET_ACTIVITY;
  const { data, loading, error: queryError, refetch } = useQuery(sheetQuery, {
    variables: { group: request.group, reference: request.reference },
    fetchPolicy: 'network-only',
  });
  const shareable: Shareable | null = data?.shareableActivity ?? null;
  const picture = useQuery(GET_MY_PROFILE_PICTURE, { fetchPolicy: 'cache-first' });
  const avatarUrl: string | null = picture.data?.myProfilePicture?.url || null;

  const [note, setNote] = useState('');
  const [showAmount, setShowAmount] = useState(true);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [away, setAway] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Done | null>(null);
  const [shareIntent, { loading: sharing }] = useMutation(SHARE_ACTIVITY_INTENT);
  const [recordDismissal] = useMutation(RECORD_ACTIVITY_SHARE_DISMISSAL);

  const rulesRequired = !!shareable && !shareable.canShare && shareable.blockCode === 'rules_required';
  const offerable =
    !queryError && !!shareable?.activity && (shareable.canShare || rulesRequired);

  // Nothing to offer (not theirs, failed, already shared, older server,
  // silent block): close quietly. A sheet that already shared stays put.
  useEffect(() => {
    if (done || loading) return;
    if (!offerable) onClose();
  }, [done, loading, offerable, onClose]);

  // A note goes to review first; it usually resolves in seconds.
  const reviewId = done?.status === 'in_review' ? done.postId : null;
  const [reviewExpired, setReviewExpired] = useState(false);
  const review = useQuery(GET_MY_COMMUNITY_POST, {
    variables: { contentItemId: reviewId },
    skip: !reviewId,
    fetchPolicy: 'network-only',
  });
  const reviewed: ReviewedPost | undefined = review.data?.myCommunityPost;
  const reviewPending = !!reviewId && !reviewExpired && (!reviewed || reviewed.status === 'PENDING');
  useEffect(() => {
    if (!reviewId) return undefined;
    const timer = setTimeout(() => setReviewExpired(true), REVIEW_MAX_MS);
    return () => clearTimeout(timer);
  }, [reviewId]);
  useEffect(() => {
    if (!reviewPending) return undefined;
    review.startPolling(REVIEW_POLL_MS);
    return () => review.stopPolling();
  }, [reviewPending]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reading the full Terms (from the rules sheet) hides this sheet until the
  // member comes back, without losing the note.
  useEffect(() => {
    if (!away) return undefined;
    const unsubscribe = navigationRef.addListener('state', () => {
      if (navigationRef.getCurrentRoute()?.name !== 'LegalDocument') setAway(false);
    });
    return unsubscribe;
  }, [away]);
  const openTerms = useCallback(() => {
    setAway(true);
    // These screens live in the nested Main navigator: a root-level dispatch
    // of the bare name never reaches them.
    navigate('Main', { screen: 'LegalDocument', params: { docType: 'terms' } });
  }, []);

  const maxChars = shareable?.noteMaxChars || DEFAULT_NOTE_MAX;

  const share = useCallback(async () => {
    if (sharing || !shareable?.canShare) return;
    setError(null);
    try {
      const { data: result } = await shareIntent({
        variables: { group: request.group, reference: request.reference, note: note.trim(), showAmount },
      });
      const payload = result?.shareActivityIntent;
      if (!payload?.success) {
        const code = payload?.errorCode as string | undefined;
        setError(payload?.error || (code && ERROR_COPY[code]) || 'No pudimos compartirlo. Intenta de nuevo.');
        return;
      }
      const postId = payload.post?.id != null ? String(payload.post.id) : null;
      const status: ShareStatus =
        payload.status === 'published' || payload.status === 'in_review' || payload.status === 'scheduled'
          ? payload.status
          : !postId
            ? 'scheduled'
            : payload.post?.status === 'PENDING'
              ? 'in_review'
              : 'published';
      setDone({ status, postId });
    } catch {
      setError('No pudimos compartirlo. Revisa tu conexión e intenta de nuevo.');
    }
  }, [sharing, shareable, shareIntent, request, note, showAmount]);

  const openPost = useCallback(
    (id: string) => {
      onClose();
      navigate('Main', { screen: 'DiscoverPostDetail', params: { contentItemId: Number(id) } });
    },
    [onClose],
  );

  if (!done && (!offerable || !shareable?.activity)) return null;

  const dismiss = () => {
    if (sharing) return;
    // Bookkeeping ("did they see it, and what did they do"): fire and
    // forget, so a slow or older server never holds the sheet open. A sheet
    // that already shared is recorded as shared on the server.
    if (!done) {
      recordDismissal({ variables: { group: request.group, reference: request.reference } }).catch(() => undefined);
    }
    onClose();
  };

  return (
    <Modal visible={!away} transparent animationType="slide" onRequestClose={dismiss}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={styles.backdrop}>
          <Pressable
            style={StyleSheet.absoluteFill}
            onPress={dismiss}
            accessibilityRole="button"
            accessibilityLabel="Cerrar"
          />
          <View style={styles.sheet} testID="community-share-sheet">
            <View style={styles.grabber} />
            {done ? (
              <DoneState done={done} reviewed={reviewed} onOpenPost={openPost} onClose={onClose} />
            ) : shareable?.activity ? (
              <Composer
                shareable={shareable}
                activity={shareable.activity}
                avatarUrl={avatarUrl}
                note={note}
                setNote={setNote}
                showAmount={showAmount}
                setShowAmount={setShowAmount}
                maxChars={maxChars}
                sharing={sharing}
                error={error}
                rulesRequired={rulesRequired}
                onShare={() => { void share(); }}
                onOpenRules={() => setRulesOpen(true)}
                onDismiss={dismiss}
              />
            ) : null}
          </View>
        </View>
        {rulesRequired ? (
          <CommunityRulesSheet
            visible={rulesOpen}
            onAccepted={() => {
              setRulesOpen(false);
              refetch().catch(() => {});
            }}
            onClose={() => setRulesOpen(false)}
            onOpenTerms={openTerms}
          />
        ) : null}
      </KeyboardAvoidingView>
    </Modal>
  );
}

type ComposerProps = {
  shareable: Shareable;
  activity: ActivityShare;
  avatarUrl: string | null;
  note: string;
  setNote: (value: string) => void;
  showAmount: boolean;
  setShowAmount: (value: boolean) => void;
  maxChars: number;
  sharing: boolean;
  error: string | null;
  rulesRequired: boolean;
  onShare: () => void;
  onOpenRules: () => void;
  onDismiss: () => void;
};

function Composer({
  shareable,
  activity,
  avatarUrl,
  note,
  setNote,
  showAmount,
  setShowAmount,
  maxChars,
  sharing,
  error,
  rulesRequired,
  onShare,
  onOpenRules,
  onDismiss,
}: ComposerProps) {
  const side = tradeSide(activity);
  const chips = chipsFor(side && cryptoCategoryOf(activity) ? `crypto_${side}` : activity.kind);
  // The preview hides money when "Mostrar monto" is off (the % stays).
  const preview: ActivityShare = showAmount ? activity : { ...activity, amountUsd: null, pnlUsd: null };
  const trimmed = note.trim();

  return (
    <ScrollView
      style={styles.scroll}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
    >
      <Text style={styles.title} accessibilityRole="header">
        {headlineFor(activity, !!shareable.pending)}
      </Text>
      <Text style={styles.subtitle}>{SUBTITLE}</Text>

      <View style={styles.previewCard} testID="community-share-preview">
        <PostByline name="Tú" avatarUrl={avatarUrl} meta="Así lo verá Comunidad" />
        <ActivitySummary activity={preview} compact />
        {trimmed ? <Text style={styles.previewNote}>{trimmed}</Text> : null}
      </View>

      {chips.length ? (
        <View style={styles.chips}>
          {chips.map((chip) => {
            const selected = trimmed === chip || trimmed.includes(chip);
            return (
              <Pressable
                key={chip}
                onPress={() => setNote(applyChip(note, chip, chips, maxChars))}
                disabled={sharing}
                style={[styles.chip, selected && styles.chipSelected]}
                accessibilityRole="button"
                accessibilityState={{ selected }}
                accessibilityLabel={`Nota rápida: ${chip}`}
                testID="community-share-chip"
              >
                <Text style={[styles.chipText, selected && styles.chipTextSelected]}>{chip}</Text>
              </Pressable>
            );
          })}
        </View>
      ) : null}

      <TextInput
        style={styles.input}
        value={note}
        onChangeText={setNote}
        placeholder="O escribe tu propia nota (opcional)"
        placeholderTextColor={colors.textTertiary}
        multiline
        maxLength={maxChars}
        editable={!sharing}
        textAlignVertical="top"
        accessibilityLabel="Tu nota para Comunidad"
        testID="community-share-note"
      />

      <View style={styles.switchRow}>
        <Text style={styles.switchLabel}>Mostrar monto</Text>
        <Switch
          value={showAmount}
          onValueChange={setShowAmount}
          disabled={sharing}
          trackColor={{ false: colors.borderMedium, true: colors.primary }}
          thumbColor={colors.white}
          accessibilityLabel="Mostrar monto en la publicación"
          testID="community-share-show-amount"
        />
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <Pressable
        style={({ pressed }) => [styles.primary, (sharing || pressed) && styles.primaryPressed]}
        onPress={rulesRequired ? onOpenRules : onShare}
        disabled={sharing}
        accessibilityRole="button"
        accessibilityLabel={rulesRequired ? 'Lee las normas para compartir' : 'Compartir en Comunidad'}
        testID="community-share-submit"
      >
        {sharing ? (
          <ActivityIndicator size="small" color={colors.white} />
        ) : (
          <Text style={styles.primaryText}>
            {rulesRequired ? 'Lee las normas para compartir' : 'Compartir en Comunidad'}
          </Text>
        )}
      </Pressable>
      <Pressable
        style={styles.secondary}
        onPress={onDismiss}
        disabled={sharing}
        accessibilityRole="button"
        accessibilityLabel="Ahora no"
        testID="community-share-dismiss"
      >
        <Text style={styles.secondaryText}>Ahora no</Text>
      </Pressable>
      <Text style={styles.reassurance}>Solo se publica si tocas Compartir. Nunca mostramos la hora exacta.</Text>
    </ScrollView>
  );
}

function DoneState({
  done,
  reviewed,
  onOpenPost,
  onClose,
}: {
  done: Done;
  reviewed?: ReviewedPost;
  onOpenPost: (id: string) => void;
  onClose: () => void;
}) {
  const scale = useRef(new Animated.Value(0.4)).current;
  useEffect(() => {
    Animated.spring(scale, { toValue: 1, friction: 4, tension: 120, useNativeDriver: true }).start();
  }, [scale]);

  // A note under review resolves to published or rejected.
  let status: ShareStatus | 'rejected' = done.status;
  if (done.status === 'in_review' && reviewed && reviewed.status !== 'PENDING') {
    status = reviewed.status === 'APPROVED' ? 'published' : 'rejected';
  }

  const copy = {
    published: {
      icon: 'check',
      tone: colors.primaryDark,
      title: '¡Publicado en Comunidad!',
      body: 'Gracias por inspirar a otros.',
    },
    in_review: {
      icon: 'clock',
      tone: colors.primaryDark,
      title: 'Lo estamos revisando',
      body: 'Suele tardar unos segundos. Te avisamos cuando se publique.',
    },
    scheduled: {
      icon: 'check',
      tone: colors.primaryDark,
      title: '¡Listo para Comunidad!',
      body: 'Se publicará en cuanto se confirme tu movimiento.',
    },
    rejected: {
      icon: 'alert-circle',
      tone: colors.error.icon,
      title: 'No pudimos publicarlo',
      body: reviewed?.reason || 'Revisa tu nota en Mis publicaciones.',
    },
  }[status];

  return (
    <View style={styles.done} testID={`community-share-done-${status}`}>
      <Animated.View style={[styles.doneBadge, { backgroundColor: copy.tone, transform: [{ scale }] }]}>
        <Icon name={copy.icon} size={34} color={colors.white} />
      </Animated.View>
      <Text style={styles.doneTitle}>{copy.title}</Text>
      <Text style={styles.doneBody}>{copy.body}</Text>
      {status === 'published' && done.postId ? (
        <Pressable
          style={styles.primary}
          onPress={() => onOpenPost(done.postId as string)}
          accessibilityRole="button"
          accessibilityLabel="Ver publicación"
          testID="community-share-open-post"
        >
          <Text style={styles.primaryText}>Ver publicación</Text>
        </Pressable>
      ) : null}
      <Pressable
        style={status === 'published' && done.postId ? styles.secondary : styles.primary}
        onPress={onClose}
        accessibilityRole="button"
        accessibilityLabel="Cerrar"
        testID="community-share-close"
      >
        <Text style={status === 'published' && done.postId ? styles.secondaryText : styles.primaryText}>Cerrar</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(17, 24, 39, 0.45)',
    justifyContent: 'flex-end',
  },
  sheet: {
    maxHeight: '92%',
    backgroundColor: colors.white,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingTop: 8,
  },
  grabber: {
    alignSelf: 'center',
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.borderMedium,
    marginBottom: 8,
  },
  scroll: { flexGrow: 0 },
  content: { paddingHorizontal: 20, paddingBottom: 28, gap: 14 },
  title: { fontSize: 22, fontWeight: '800', color: colors.textFlat, textAlign: 'center', marginTop: 4 },
  subtitle: { fontSize: 14, lineHeight: 20, color: colors.textSecondary, textAlign: 'center', marginTop: -6 },
  previewCard: {
    backgroundColor: colors.white,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 16,
    padding: 12,
    gap: 10,
    shadowColor: colors.shadowBase,
    shadowOpacity: 0.06,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 3 },
    elevation: 2,
  },
  previewNote: { fontSize: 15, lineHeight: 21, color: colors.text.primary },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  chipSelected: { backgroundColor: colors.primarySoft, borderColor: colors.primaryDark },
  chipText: { fontSize: 14, color: colors.text.primary },
  chipTextSelected: { color: colors.successText, fontWeight: '600' },
  input: {
    minHeight: 56,
    maxHeight: 120,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
    color: colors.text.primary,
    backgroundColor: colors.surface,
  },
  switchRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  switchLabel: { fontSize: 15, color: colors.text.primary },
  error: { fontSize: 13, color: colors.error.text },
  primary: {
    alignSelf: 'stretch',
    backgroundColor: colors.primaryDark,
    borderRadius: 14,
    minHeight: 52,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  primaryPressed: { opacity: 0.8 },
  primaryText: { color: colors.white, fontSize: 16, fontWeight: '700', textAlign: 'center' },
  secondary: { alignSelf: 'center', paddingVertical: 10, paddingHorizontal: 16, minHeight: 44, justifyContent: 'center' },
  secondaryText: { color: colors.textSecondary, fontSize: 15, fontWeight: '600' },
  reassurance: { fontSize: 12, lineHeight: 17, color: colors.textTertiary, textAlign: 'center', marginTop: -6 },
  done: { alignItems: 'center', paddingHorizontal: 24, paddingTop: 16, paddingBottom: 28, gap: 10 },
  doneBadge: {
    width: 72,
    height: 72,
    borderRadius: 36,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 6,
  },
  doneTitle: { fontSize: 21, fontWeight: '800', color: colors.textFlat, textAlign: 'center' },
  doneBody: { fontSize: 15, lineHeight: 21, color: colors.textSecondary, textAlign: 'center', marginBottom: 8 },
});
