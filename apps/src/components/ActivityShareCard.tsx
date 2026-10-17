import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Switch, View } from 'react-native';
import { useMutation, useQuery } from '@apollo/client';
import { useIsFocused, useNavigation } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';

import { Text, TextInput } from './common/AppText';
import { ActivitySummary, type ActivityShare } from './ActivitySummary';
import { CommunityRulesSheet } from './CommunityRulesSheet';
import { colors } from '../config/theme';
import { GET_MY_COMMUNITY_POST, GET_SHAREABLE_ACTIVITY } from '../apollo/queries';
import { SHARE_ACTIVITY } from '../apollo/mutations';
import { useAccount } from '../contexts/AccountContext';
import { usePollWhile } from '../hooks/usePollWhile';

export type ActivityShareGroup = 'stock' | 'ramp' | 'send' | 'receive';

type Props = {
  /** Newest unshared confirmed activity of this kind (polled until the server marks it final). */
  group?: ActivityShareGroup;
  /** One specific activity, e.g. from a receipt. Takes precedence over `group`. */
  unifiedTransactionId?: string | null;
  /** The status screen's own id (ramp order id, local-transfer reference): pins `group` to that one activity. */
  reference?: string | null;
};

type Shareable = {
  unifiedTransactionId: string;
  canShare: boolean;
  blockCode?: string | null;
  blockMessage?: string | null;
  noteMaxChars?: number | null;
  activity?: ActivityShare | null;
};

type PostStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'FAILED' | 'REMOVED' | string;

// Blocks we never nag about: the card simply does not appear.
const SILENT_BLOCKS = new Set(['not_verified', 'banned', 'disabled', 'business_context']);

const ERROR_COPY: Record<string, string> = {
  already_shared: 'Ya compartiste este movimiento.',
  not_shareable: 'Este movimiento ya no se puede compartir.',
  too_long: 'Tu nota es demasiado larga.',
  links: 'Las notas no pueden incluir enlaces.',
};

const POLL_MS = 3000;
const FIND_MAX_MS = 60000;
const REVIEW_MAX_MS = 30000;

/**
 * "¿Lo compartes en Comunidad?" — offered after a money movement completes.
 * Never posts on its own: every share is an explicit tap on "Compartir".
 * Any failure (older server, network) renders nothing, so it can never break
 * the success screen it sits on.
 */
export function ActivityShareCard({ group, unifiedTransactionId, reference }: Props) {
  const navigation = useNavigation<any>();
  const { activeAccount } = useAccount();
  const isBusiness = (activeAccount?.type || '').toLowerCase() === 'business';
  const targeted = !!unifiedTransactionId;

  const [dismissed, setDismissed] = useState(false);
  const [note, setNote] = useState('');
  const [showAmount, setShowAmount] = useState(true);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [posted, setPosted] = useState<{ id: string; status: PostStatus; reason?: string | null } | null>(null);

  const skip = isBusiness || dismissed || (!targeted && !group);
  const { data, error: queryError, refetch, startPolling, stopPolling } = useQuery(GET_SHAREABLE_ACTIVITY, {
    variables: targeted ? { unifiedTransactionId } : reference ? { group, reference } : { group },
    skip,
    fetchPolicy: 'network-only',
  });
  const shareable: Shareable | null = data?.shareableActivity ?? null;

  // Trades become final on the server a few seconds after the app shows
  // success: keep asking until something shows up (or the deadline passes).
  usePollWhile(
    !skip && !targeted && !shareable && !queryError && !posted,
    startPolling,
    stopPolling,
    POLL_MS,
    FIND_MAX_MS,
    `${group || ''}:${reference || ''}:${activeAccount?.id || ''}`,
  );

  // Back from choosing a username: ask again so the card can unlock.
  const focused = useIsFocused();
  const blocked = !!shareable && !shareable.canShare;
  useEffect(() => {
    if (focused && blocked && !skip) refetch().catch(() => {});
  }, [focused, blocked, skip, refetch]);

  // A note goes to review first; it usually resolves in seconds.
  const pendingId = posted?.status === 'PENDING' ? posted.id : null;
  const review = useQuery(GET_MY_COMMUNITY_POST, {
    variables: { contentItemId: pendingId },
    skip: !pendingId,
    fetchPolicy: 'network-only',
  });
  const reviewed = review.data?.myCommunityPost as { id: string; status: PostStatus; reason?: string | null } | undefined;
  const reviewStatus: PostStatus | undefined = reviewed?.status;
  usePollWhile(
    !!pendingId && (!reviewStatus || reviewStatus === 'PENDING'),
    review.startPolling,
    review.stopPolling,
    POLL_MS,
    REVIEW_MAX_MS,
    pendingId || '',
  );

  const [shareActivity, { loading: sharing }] = useMutation(SHARE_ACTIVITY);

  const share = useCallback(async () => {
    if (!shareable?.unifiedTransactionId || sharing) return;
    setError(null);
    try {
      const { data: result } = await shareActivity({
        variables: {
          unifiedTransactionId: shareable.unifiedTransactionId,
          note: note.trim(),
          showAmount,
        },
      });
      const payload = result?.shareActivity;
      if (!payload?.success || !payload.post) {
        const code = payload?.errorCode as string | undefined;
        setError(payload?.error || (code && ERROR_COPY[code]) || 'No pudimos compartirlo. Intenta de nuevo.');
        return;
      }
      setPosted({ id: String(payload.post.id), status: payload.post.status, reason: payload.post.reason });
    } catch {
      setError('No pudimos compartirlo. Revisa tu conexión e intenta de nuevo.');
    }
  }, [shareable, sharing, shareActivity, note, showAmount]);

  const openPost = useCallback(
    (id: string) => navigation.navigate('DiscoverPostDetail', { contentItemId: Number(id) }),
    [navigation],
  );

  if (dismissed || isBusiness) return null;

  // Confirmation after sharing (stays even if the server now says "nothing to share").
  if (posted) {
    const status = reviewStatus || posted.status;
    const reason = reviewed?.reason ?? posted.reason;
    if (status === 'APPROVED') {
      return (
        <View style={[styles.card, styles.doneCard]} testID="activity-share-done">
          <Icon name="check-circle" size={20} color={colors.successText} />
          <View style={styles.doneBody}>
            <Text style={styles.doneTitle}>¡Publicado en Comunidad!</Text>
            <Pressable onPress={() => openPost(posted.id)} accessibilityRole="link" hitSlop={8}>
              <Text style={styles.link}>Ver publicación</Text>
            </Pressable>
          </View>
        </View>
      );
    }
    if (status === 'PENDING') {
      return (
        <View style={[styles.card, styles.doneCard]} testID="activity-share-pending">
          <Icon name="clock" size={20} color={colors.text.secondary} />
          <View style={styles.doneBody}>
            <Text style={styles.doneTitle}>Lo estamos revisando</Text>
            <Text style={styles.subtitle}>Te avisaremos cuando se publique.</Text>
          </View>
        </View>
      );
    }
    return (
      <View style={[styles.card, styles.doneCard]} testID="activity-share-rejected">
        <Icon name="alert-circle" size={20} color={colors.error.icon} />
        <View style={styles.doneBody}>
          <Text style={styles.doneTitle}>No pudimos publicarlo</Text>
          <Text style={styles.subtitle}>{reason || 'Revisa tu nota en Mis publicaciones.'}</Text>
        </View>
      </View>
    );
  }

  if (queryError || !shareable || !shareable.activity) return null;
  if (!shareable.canShare && (!shareable.blockCode || SILENT_BLOCKS.has(shareable.blockCode))) return null;

  const header = (
    <View style={styles.headerRow}>
      <View style={styles.headerText}>
        <Text style={styles.title}>¿Lo compartes en Comunidad?</Text>
        <Text style={styles.subtitle}>Tus seguidores verán esto. Tú decides qué se publica.</Text>
      </View>
      <Pressable
        onPress={() => setDismissed(true)}
        hitSlop={10}
        accessibilityRole="button"
        accessibilityLabel="Ahora no"
      >
        <Icon name="x" size={18} color={colors.text.light} />
      </Pressable>
    </View>
  );

  // Not yet able to post: one gentle step away (username or rules).
  if (!shareable.canShare) {
    const needsUsername = shareable.blockCode === 'username_required';
    const needsRules = shareable.blockCode === 'rules_required';
    if (!needsUsername && !needsRules) return null;
    return (
      <View style={styles.card} testID="activity-share-blocked">
        {header}
        <ActivitySummary activity={shareable.activity} compact />
        <Pressable
          style={styles.primary}
          onPress={() => (needsUsername ? navigation.navigate('UpdateUsername') : setRulesOpen(true))}
          accessibilityRole="button"
        >
          <Text style={styles.primaryText}>
            {needsUsername ? 'Elige tu nombre de usuario para compartir' : 'Lee las normas para compartir'}
          </Text>
        </Pressable>
        {needsRules ? (
          <CommunityRulesSheet
            visible={rulesOpen}
            onAccepted={() => {
              setRulesOpen(false);
              refetch().catch(() => {});
            }}
            onClose={() => setRulesOpen(false)}
          />
        ) : null}
      </View>
    );
  }

  // The preview hides money when the member turns "Mostrar monto" off (the % stays).
  const preview: ActivityShare = showAmount
    ? shareable.activity
    : { ...shareable.activity, amountUsd: null, pnlUsd: null };
  const maxChars = shareable.noteMaxChars || 280;

  return (
    <View style={styles.card} testID="activity-share-card">
      {header}
      <ActivitySummary activity={preview} compact />
      <TextInput
        style={styles.input}
        value={note}
        onChangeText={setNote}
        placeholder="Cuenta por qué (opcional)"
        placeholderTextColor={colors.textTertiary}
        multiline
        maxLength={maxChars}
        editable={!sharing}
        textAlignVertical="top"
        testID="activity-share-note"
      />
      <View style={styles.switchRow}>
        <Text style={styles.switchLabel}>Mostrar monto</Text>
        <Switch
          value={showAmount}
          onValueChange={setShowAmount}
          disabled={sharing}
          trackColor={{ false: colors.borderMedium, true: colors.primary }}
          thumbColor={colors.white}
          testID="activity-share-show-amount"
        />
      </View>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <View style={styles.actions}>
        <Pressable
          style={styles.secondary}
          onPress={() => setDismissed(true)}
          disabled={sharing}
          accessibilityRole="button"
        >
          <Text style={styles.secondaryText}>Ahora no</Text>
        </Pressable>
        <Pressable
          style={[styles.primary, styles.primaryFlex, sharing && styles.disabled]}
          onPress={share}
          disabled={sharing}
          accessibilityRole="button"
          testID="activity-share-submit"
        >
          {sharing ? (
            <ActivityIndicator size="small" color={colors.white} />
          ) : (
            <Text style={styles.primaryText}>Compartir</Text>
          )}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    alignSelf: 'stretch',
    backgroundColor: colors.background,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 16,
    padding: 14,
    marginTop: 16,
    gap: 12,
  },
  doneCard: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  doneBody: { flex: 1, gap: 4 },
  doneTitle: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
  link: { fontSize: 14, fontWeight: '600', color: colors.successText },
  headerRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  headerText: { flex: 1, gap: 2 },
  title: { fontSize: 16, fontWeight: '700', color: colors.text.primary },
  subtitle: { fontSize: 13, color: colors.text.secondary },
  input: {
    minHeight: 64,
    maxHeight: 140,
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
  switchLabel: { fontSize: 14, color: colors.text.primary },
  error: { fontSize: 13, color: colors.error.text },
  actions: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  primary: {
    backgroundColor: colors.primaryDark,
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 16,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 44,
  },
  primaryFlex: { flex: 1 },
  primaryText: { color: colors.white, fontSize: 15, fontWeight: '600', textAlign: 'center' },
  disabled: { opacity: 0.6 },
  secondary: { paddingVertical: 12, paddingHorizontal: 14, minHeight: 44, justifyContent: 'center' },
  secondaryText: { color: colors.text.secondary, fontSize: 15, fontWeight: '600' },
});
